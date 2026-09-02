"""Le LLM en deux rôles étroits : EXTRACTEUR de slots et FORMULEUR de répliques.

- AnthropicLLM : la vraie version (nécessite ANTHROPIC_API_KEY dans l'environnement / .env).
- MockLLM     : extraction par règles + répliques template. Sans réseau, déterministe —
                sert aux tests automatisés et à valider la machine à états seule.

Le contrôleur (engine.py) passe une INSTRUCTION précise ("demande la commune",
"propose ces 2 créneaux : ...") : le LLM met en mots, il ne décide pas.
"""
from __future__ import annotations

import json
import os
import re

from . import actions

EXTRACT_SYSTEM = """Tu extrais des informations d'une phrase d'un appelant au téléphone d'un artisan {metier}.
Réponds UNIQUEMENT un objet JSON avec les clés présentes dans la phrase (omets les absentes) :
- prestation: une de {prestations} si identifiable
- probleme: résumé très court "équipement + symptôme" (ex: "chaudière ne démarre plus")
- commune: nom de commune si mentionné
- code_postal: 5 chiffres UNIQUEMENT si l'appelant les prononce — ne déduis JAMAIS
  un code postal du nom d'une commune, même si tu le connais (c'est le système qui le résout)
- urgence_reelle: true/false si l'appelant exprime (ou nie) un dégât/besoin immédiat
- statut_occupant: proprietaire|locataire|syndic|autre si déductible
- nom: nom de famille si donné
- telephone_rappel: numéro FR si donné (format 0XXXXXXXXX, EXACTEMENT dix chiffres).
  Si tu entends plus ou moins de dix chiffres, ne renvoie PAS ce champ — ne tronque
  jamais, ne complète jamais. Un numéro à peu près juste est pire qu'un numéro absent :
  c'est le seul moyen de rappeler le client.
- disponibilites: le TEXTE EXACT de ce que l'appelant a dit sur ses disponibilités,
  recopié tel quel (une chaîne, jamais un objet). Il est lu par l'artisan, pas par la
  machine — c'est la clé "contrainte" décrite plus bas qui porte la structure. Ne mets
  JAMAIS d'objet ici.
- danger_gaz: true si odeur/fuite de gaz évoquée
- confirme: true/false si la phrase est une confirmation/refus de ce que l'agent vient de proposer
- question_prix: true si l'appelant demande un prix, un tarif ou une fourchette
- veut_humain: true si l'appelant veut un CONTACT HUMAIN, sous quelque forme que ce
  soit — parler à quelqu'un, au patron, à l'artisan lui-même, être rappelé par une
  personne, ou qu'on ESSAIE DE LE JOINDRE ou DE L'APPELER pour lui. Pas seulement
  « je veux parler à un humain » : « il faut trouver une solution, essayez de
  l'appeler », « vous ne pouvez pas le prévenir ? », « je préfère lui parler
  directement » comptent tous. Ne pas confondre avec « il faudrait que quelqu'un
  vienne », qui demande une INTERVENTION, pas une conversation.
Pour les FAITS ci-dessus, ne déduis rien qui ne soit pas dans la phrase.

Contexte de la conversation :
- Nous sommes {aujourdhui} (heure locale de l'appelant).
- L'agent vient de dire : "{dernier_agent}"
- Propositions de créneaux en cours : {propositions}
{menu}{menu_contrainte}"""

REPLY_SYSTEM = """Tu es l'assistant vocal de {nom_entreprise} ({metier}), au téléphone.
Tu parles pour un appel VOCAL : phrases courtes, chaleureuses, naturelles. UNE seule question à la fois.
Règles absolues :
- Jamais de prix ni de fourchette (sauf texte exact fourni dans l'instruction).
- Jamais de diagnostic technique. Jamais "c'est confirmé".
- Ne promets rien qui n'est pas dans l'instruction : n'annonce JAMAIS un rappel,
  une transmission ou un rendez-vous que l'instruction ne contient pas explicitement.
- Si l'instruction PROPOSE des créneaux, présente-les comme des propositions et pose la
  question — ne dis jamais "c'est noté" ou "c'est réservé" à la place d'une proposition.
- Recopie les dates et horaires EXACTEMENT tels que l'instruction les donne.
Instruction du contrôleur (mets-la en mots naturellement, sans rien ajouter d'engageant) :
{instruction}"""


# --------------------------------------------------------------- extraction du nom
# Le nom de l'appelant est le seul slot où se tromper coûte plus cher que de ne rien
# trouver : il n'est pas dans `Conversation.OVERWRITABLE` (le premier capté est définitif)
# et il finit affiché à l'artisan (« Garcia a validé le créneau »). D'où la règle :
# **dans le doute, pas de nom.**
#
# ⚠️ Le correctif tentant — ajouter `re.IGNORECASE` à l'ancienne regex — est un PIÈGE.
# `[A-ZÉÈ]` y servait aussi de filtre de capitalisation : en insensible à la casse,
# « Oui c'est bien ça » donne nom='bien' et « c'est parfait » donne nom='parfait'.
# Verrouillé par R26.
#
# On ne s'appuie donc PAS sur la majuscule — un moteur de transcription vocale rend aussi
# bien « je m'appelle garcia » — mais sur un **introducteur explicite**. « c'est » nu en est
# exclu : c'est l'une des tournures les plus fréquentes du français parlé (« c'est urgent »,
# « c'est en cours », « c'est Nogent-sur-Marne »), et elle ne désigne un nom que suivie d'un
# titre.
_TITRE = r"(?:m\.|mr|mme|mlle|madame|monsieur)"
# une lettre Unicode (donc les accents), liée par trait d'union ou apostrophe :
# « Lefèvre », « Dupont-Martin », « D'Angelo », « Müller »
_MOT_NOM = r"[^\W\d_]+(?:['’-][^\W\d_]+)*"

_NOM_INTRODUIT = re.compile(
    rf"""(?: je \s+ m['’] appelle \s+ (?:{_TITRE} \s+)?     # je m'appelle (M.) X
          | mon \s+ nom \s+ (?: est | c['’]est ) \s+        # mon nom est X
          | (?: c['’]est | ici ) \s+ {_TITRE} \s+           # c'est Monsieur X (titre EXIGÉ)
          | au \s+ nom \s+ d[eu] \s+                             # au nom de X
        )
        ({_MOT_NOM})
     """, re.IGNORECASE | re.VERBOSE)

# « Garcia à l'appareil »
_NOM_APPAREIL = re.compile(rf"\b({_MOT_NOM})\s+à\s+l['’]appareil", re.IGNORECASE)

# Réponse DIRECTE à « À quel nom, et sur quel numéro ? » : « Garcia, 06 12 34 56 78 », ou
# « Garcia » tout court. Aucun introducteur — c'est la question de l'agent qui rend la
# phrase lisible. Le nom doit ouvrir la phrase ET être suivi d'une virgule, du numéro, ou
# de rien : sans cette exigence de forme, « Non je préfère pas donner mon numéro »
# donnerait nom='Non'.
_NOM_EN_REPONSE = re.compile(rf"^\s*({_MOT_NOM})\s*(?:,|$|(?=0\d))", re.IGNORECASE)

# Mots qui ne sont jamais un nom de famille, même bien introduits. Filet de sécurité étroit
# et non une liste de courses : l'introducteur fait déjà l'essentiel du tri.
_PAS_UN_NOM = {"non", "oui", "merci", "bonjour", "monsieur", "madame", "pas", "rien",
               "je", "j", "euh", "alors", "bon", "ben"}


def extraire_nom(utterance: str, dernier_agent: str = "") -> str | None:
    """Le nom de famille de l'appelant, ou None. None est une réponse acceptable."""
    m = _NOM_INTRODUIT.search(utterance) or _NOM_APPAREIL.search(utterance)
    if not m and "à quel nom" in (dernier_agent or "").lower():
        m = _NOM_EN_REPONSE.match(utterance)
    if not m:
        return None
    nom = m.group(1)
    return None if nom.lower() in _PAS_UN_NOM else nom


class MockLLM:
    """Extraction par règles simples + répliques = l'instruction elle-même (déjà rédigée)."""

    PRESTATION_KEYWORDS = {
        "fuite": ["fuite", "coule", "goutte", "inond"],
        "chaudiere_panne": ["chaudière", "chaudiere", "chauffage ne", "plus de chauffage"],
        "chauffe_eau": ["chauffe-eau", "chauffe eau", "eau chaude", "ballon"],
        "wc_evacuation": ["wc", "toilette", "bouché", "bouche", "évacuation", "canalisation"],
        "robinetterie": ["robinet", "mitigeur"],
        "devis_pac": ["pompe à chaleur", "pac"],
        "devis_chaudiere": ["nouvelle chaudière", "remplacer la chaudière", "changer de chaudière"],
        "devis_sdb": ["salle de bain"],
        "entretien_chaudiere": ["entretien", "révision"],
        # Prestations que l'artisan REFUSE. Elles doivent être NOMMABLES, sinon le
        # contrôleur ne peut pas les décliner et l'agent réserve un créneau pour des
        # travaux exclus (cf. R33). Leur position dans ce dictionnaire n'a pas
        # d'importance : c'est le mot-clé le plus SPÉCIFIQUE qui gagne, voir `extract`.
        "debouchage_colonne_immeuble": ["colonne de l'immeuble", "colonne d'immeuble",
                                        "colonne commune"],
        "gaz_installation_neuve": ["installation gaz neuve", "installation de gaz neuve",
                                   "créer une arrivée de gaz"],
    }

    def extract(self, utterance: str, context: dict) -> dict:
        u = utterance.lower()
        out: dict = {}
        # LE PLUS SPÉCIFIQUE gagne, pas le premier trouvé. « Il faut déboucher la colonne
        # de l'immeuble, c'est bouché » contient « bouché » (wc_evacuation, couvert) ET
        # « colonne de l'immeuble » (refusé) : s'arrêter au premier match faisait dépendre
        # la réponse de l'ordre du dictionnaire, et l'agent acceptait des travaux exclus.
        trouves = [(k, prest) for prest, kws in self.PRESTATION_KEYWORDS.items()
                   for k in kws if k in u]
        if trouves:
            out["prestation"] = max(trouves, key=lambda t: len(t[0]))[1]
            out["probleme"] = utterance.strip()[:80]
        # Un code postal se PRONONCE en deux groupes (« quatre-vingt-onze, deux cent
        # soixante »), et la transcription pose donc un séparateur au milieu : « 91 260 »,
        # « 91. 260 ». Exiger cinq chiffres collés faisait manquer le slot alors qu'il
        # était dans la phrase — trouvé au premier appel vocal réel du 26/08, où
        # l'appelant a dû répéter, et où ce fut manqué une seconde fois.
        #
        # Le découpage est 2+3 et pas n'importe lequel : c'est celui de la prononciation,
        # et surtout c'est celui qui ne peut PAS mordre sur un numéro de téléphone, fait
        # de paires (« 06 12 34 56 78 » n'offre nulle part deux chiffres suivis de trois).
        # La BARRE OBLIQUE en fait partie : la transcription écrit « 91/260 ».
        # Découvert au quatrième appel réel, où l'appelant a donné son code postal
        # TROIS FOIS, correctement, sans jamais être compris. Et depuis que la
        # question est bornée (R48), on ne boucle plus : on raccroche poliment sur
        # quelqu'un qui a répondu juste. Une borne est bonne pour l'appelant qui ne
        # sait pas répondre, cruelle pour celui qu'on n'écoute pas.
        #
        # `{0,3}` et non `?` : la transcription rend « Dans le 91. 260 », soit un point
        # ET une espace. Un seul séparateur toléré laissait passer le cas réel — trouvé
        # au deuxième essai, sur la deuxième dictée du même appel.
        if m := re.search(r"\b(\d{2})[\s.\-/]{0,3}(\d{3})\b", u):
            out["code_postal"] = m.group(1) + m.group(2)
        # `(?![\s.\-]?\d)` : un chiffre de plus INVALIDE la capture au lieu de la
        # tronquer. Sans lui, « 06 10 15 47 68 79 » (douze chiffres dictés) rendait
        # « 0610154768 » : le `\b` tenait, un espace suivant. Trouvé au premier appel
        # vocal réel du 26/08 — l'agent répétait dix chiffres, l'appelant confirmait sans
        # rien remarquer, et le RDV partait sur un numéro que personne n'avait donné.
        if m := re.search(r"\b(0\d(?:[\s.\-]?\d{2}){4})(?![\s.\-]?\d)", utterance):
            out["telephone_rappel"] = re.sub(r"[\s.\-]", "", m.group(1))
        # le seul extracteur qui lit le CONTEXTE : « Garcia, 06 12 34 56 78 » n'est un nom
        # que parce que l'agent vient de demander « à quel nom ? »
        if nom := extraire_nom(utterance, (context or {}).get("dernier_agent", "")):
            out["nom"] = nom
        if "gaz" in u and ("odeur" in u or "sent" in u):
            out["danger_gaz"] = True
        if "propriétaire" in u:
            out["statut_occupant"] = "proprietaire"
        if "locataire" in u:
            out["statut_occupant"] = "locataire"
        if any(w in u for w in ["urgent", "urgence", "tout de suite", "aujourd'hui", "l'eau coule"]):
            out["urgence_reelle"] = True
        if any(w in u for w in ["dispo", "après", "avant", "matin", "après-midi",
                                "quand vous voulez", "chez moi", "soir", "week-end",
                                "weekend", "midi", "déjeuner"]):
            out["disponibilites"] = utterance.strip()[:80]
            # la contrainte STRUCTURÉE accompagne le texte libre, à tout état : c'est un
            # fait sur l'appel, pas une réponse au tour des créneaux
            out["contrainte"] = self._contrainte_mock(u)
        if re.search(r"\b(oui|d'accord|ok|parfait|ça marche|c'est bon|exact)\b", u):
            out["confirme"] = True
        # « aucun des deux », « ni l'un ni l'autre » : des refus qui ne contiennent pas
        # « non ». Le harnais les ignorait, et la clarification de `pas_clair` avalait donc
        # un tour que le scénario attendait ailleurs. C'est bien la place de ce genre de
        # rustine — dans le banc d'essai, pas dans le contrôleur.
        if re.search(r"\b(non|pas possible|impossible|aucun|aucune|ni l'un ni l'autre)\b",
                     u):
            out["confirme"] = False
        # « quelqu'un » TOUT SEUL ne veut pas dire « je veux parler à un humain » : dans ce
        # métier, « il faudrait que quelqu'un vienne » est la façon la plus banale de
        # demander une intervention. Le mot ne compte que dans un contexte de PAROLE.
        # (trouvé le 25/08 par l'éval réelle, sur la même phrase que l'homonyme « vienne »)
        if any(w in u for w in ["un humain", "une vraie personne", "le patron",
                                "parler à quelqu'un", "parler a quelqu'un",
                                "parler à julien", "parler a julien",
                                "quelqu'un au téléphone"]):
            out["veut_humain"] = True
        if any(w in u for w in ["combien", "prix", "tarif", "fourchette", "coûte", "euros"]):
            out["question_prix"] = True
        # ---- ACTION : le menu de l'état, décidé par mots-clés ICI et NULLE PART AILLEURS.
        # C'est la place des mots-clés : un harnais de test déterministe. Trois défauts
        # (R68, R70, R71) sont nés de la même erreur — les avoir mis dans `engine.py`, où
        # ils tenaient lieu de compréhension sur le chemin de production. En production
        # c'est le modèle qui interprète, contre le même menu fermé (`actions.py`).
        #
        # Ce mock n'a donc PAS pour but de bien comprendre le français : il a pour but de
        # rendre la machine à états jouable sans réseau, de façon reproductible. Les
        # tournures réelles se mesurent ailleurs — `run_extract_eval.py`.
        if actions.menu((context or {}).get("etat", "")):
            out["action"], rang = self._action(u, out)
            if rang is not None:
                out["rang"] = rang
            # le TEXTE LIBRE d'une contrainte, pour le lead. Seulement là où un menu
            # existe — un jour cité pendant le récit du problème (« aujourd'hui c'est la
            # catastrophe ») n'est pas une disponibilité, et c'était déjà la raison pour
            # laquelle `_jour_dit` ne vivait que dans `_s5`.
            if out["action"] == actions.CONTRAINTE and not out.get("disponibilites"):
                out["disponibilites"] = utterance.strip()[:80]
        return out

    # jours nommés : dupliqués du contrôleur à dessein. Un harnais de test qui importerait
    # les tables du moteur ne pourrait plus détecter que le moteur les a cassées.
    JOURS_MOCK = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
                  "demain", "aujourd'hui", "après-demain")
    AU_PLUS_VITE_MOCK = ("le plus vite possible", "le plus rapidement possible",
                         "aussi vite que possible", "le plus tôt possible", "au plus vite",
                         "au plus tôt", "dès que possible", "dès que vous pouvez",
                         "tout de suite", "immédiatement", "en urgence", "d'urgence",
                         "plus tôt", "rien avant", "pas avant")

    # Les négations, ICI et nulle part ailleurs. Elles ont vécu dans `engine.py` jusqu'au
    # 02/09, où elles produisaient encore une INVERSION (« ni le jeudi » préférait jeudi).
    # Un harnais de test a le droit d'être naïf ; un contrôleur non.
    NEGATIONS_MOCK = ("pas ", "sauf", "jamais", "hormis", "excepte", "ni ", "aucun")
    # ORDRE : le plus LONG d'abord, et on s'arrête au premier trouvé. « après-demain »
    # contient « demain » — le même piège que `JOURS_RELATIFS` avait dans le contrôleur,
    # et qui rendait jours={mardi, mercredi} pour un seul jour demandé.
    RELATIFS_MOCK = (("apres-demain", "apres_demain"), ("après-demain", "apres_demain"),
                     ("aujourd'hui", "aujourdhui"), ("demain", "demain"))

    def _contrainte_mock(self, u: str) -> dict:
        """La contrainte STRUCTURÉE, décidée par mots-clés — dans le harnais de test.

        Volontairement naïf : la négation vaut pour toute la phrase, alors que le vrai
        modèle distingue « pas le samedi mais plutôt jeudi ». Ce mock existe pour rendre la
        machine à états jouable sans réseau, pas pour comprendre le français. Les tournures
        réelles se mesurent dans `run_extract_eval.py`.
        """
        nie = any(n in u for n in self.NEGATIONS_MOCK)
        plancher = "pas avant" in u or "a partir de" in u or "à partir de" in u
        jours = [nom for nom in ("lundi", "mardi", "mercredi", "jeudi", "vendredi",
                                 "samedi", "dimanche") if nom in u]
        for mot, v in self.RELATIFS_MOCK:
            if mot in u:
                jours.append(v)
                break
        if "week-end" in u or "weekend" in u:
            jours += ["samedi", "dimanche"]
        moment = None
        if "matin" in u or "avant midi" in u or "avant le dejeuner" in u                 or "avant le déjeuner" in u:
            moment = "matin"
        elif "après-midi" in u or "apres-midi" in u or "aprem" in u:
            moment = "apres_midi"
        elif "soir" in u:
            moment = "soir"
        if plancher and jours:
            return {"pas_avant": jours[0]}
        if nie:
            return {"exclut_jours": jours, "exclut_moment": moment}
        return {"jours": jours, "moment": moment}

    def _action(self, u: str, out: dict) -> tuple[str, int | None]:
        """L'action du menu, dans l'ordre de priorité que le moteur appliquait avant.

        L'ordre EST le contrat : un choix explicite (« le premier ») primait sur une
        question de prix, et un « oui » accompagné d'une question ne valait acceptation de
        rien (Katz, éval réelle du 25/08). Le déplacement vers un menu d'actions ne doit
        rien changer à ces arbitrages — ils ont chacun coûté un appel.
        """
        if "premier" in u or "le 1" in u:
            return actions.CHOISIR, 1
        if "deuxième" in u or "second" in u or "le 2" in u:
            return actions.CHOISIR, 2
        if out.get("question_prix") or out.get("veut_humain"):
            # des FAITS, que le moteur lit par ailleurs : rien à décider ici. `pas_clair`
            # laisserait le moteur faire répéter au lieu de répondre sur le prix.
            return actions.PAS_CLAIR, None
        # « pas avant vendredi » est un PLANCHER, pas une demande d'aller plus vite :
        # testé AVANT la famille « au plus vite », qui contient « rien avant ».
        if ("pas avant" in u or "à partir de" in u) and any(
                j in u for j in self.JOURS_MOCK):
            out["contrainte"] = self._contrainte_mock(u)
            return actions.CONTRAINTE, None
        # Un JOUR ou un MOMENT nommé gagne sur « au plus vite » : « plutôt jeudi, le plus
        # tôt possible » est une contrainte (jeudi) qu'on souhaite tôt DANS ce jour, pas
        # une demande du premier créneau libre. Le contrôleur lisait ce jour dans le texte
        # avant R83 (`_jour_dit`), ce qui masquait la question de priorité ; elle se pose
        # maintenant franchement, et le jour nommé est la contrainte la plus précise.
        if any(w in u for w in self.AU_PLUS_VITE_MOCK) and not any(
                j in u for j in self.JOURS_MOCK):
            return actions.PLUS_TOT, None
        if any(j in u for j in self.JOURS_MOCK) or out.get("disponibilites"):
            out["contrainte"] = self._contrainte_mock(u)
            return actions.CONTRAINTE, None
        if out.get("confirme") is True:
            return actions.CHOISIR, 1
        if out.get("confirme") is False:
            return actions.REFUSER, None
        return actions.PAS_CLAIR, None

    def reply(self, instruction: str, context: dict) -> str:
        return instruction  # les instructions du contrôleur sont déjà des phrases prononçables


def json_de(texte: str) -> dict:
    """Le JSON d'une réponse d'extraction, ou {} — jamais une exception.

    Trois formes rencontrées en vrai, et la troisième est celle qui a motivé cette
    fonction. Mesurée le 01/09 sur le banc d'extraction : à la phrase « Demain c'est
    mercredi ? Alors va pour le matin. », le modèle répond parfois par le bon JSON, et
    parfois en RÉPONDANT à la question posée avant de le donner. La phrase contenait une
    question adressée à l'agent, et un modèle serviable y répond.

    Le nettoyage précédent ne savait retirer que des clôtures ```json ; un préambule en
    prose faisait échouer `json.loads`, l'extraction rendait {}, et le tour partait en
    `pas_clair`. La dégradation était sûre — on fait répéter — mais elle coûtait un tour
    à quelqu'un qui venait de répondre correctement.

    On cherche donc le premier objet `{...}` ÉQUILIBRÉ où qu'il soit dans le texte.
    Équilibré, et non par expression régulière : un JSON contient des accolades imbriquées,
    et `.*` s'arrêterait à la première fermante venue.

    Rendre {} reste la sortie de secours. C'est `actions.valider` qui en fera `pas_clair`,
    donc une demande de répétition — jamais un abandon.
    """
    texte = (texte or "").strip()
    texte = re.sub(r"^```(?:json)?|```$", "", texte, flags=re.MULTILINE).strip()
    try:
        lu = json.loads(texte)
        return lu if isinstance(lu, dict) else {}
    except json.JSONDecodeError:
        pass
    debut = texte.find("{")
    if debut < 0:
        return {}
    profondeur, en_chaine, echappe = 0, False, False
    for i in range(debut, len(texte)):
        c = texte[i]
        if en_chaine:
            # une accolade DANS une chaîne ne compte pas, et un guillemet échappé ne
            # ferme pas la chaîne : sans ça, un `probleme` contenant « { » suffirait
            if echappe:
                echappe = False
            elif c == "\\":
                echappe = True
            elif c == '"':
                en_chaine = False
            continue
        if c == '"':
            en_chaine = True
        elif c == "{":
            profondeur += 1
        elif c == "}":
            profondeur -= 1
            if profondeur == 0:
                try:
                    lu = json.loads(texte[debut:i + 1])
                    return lu if isinstance(lu, dict) else {}
                except json.JSONDecodeError:
                    return {}
    return {}


def _texte_de(msg) -> str:
    """Concatène les blocs texte de la réponse — les modèles récents peuvent renvoyer
    des blocs de réflexion (ThinkingBlock) avant le texte : on ne lit QUE les blocs texte."""
    return "".join(b.text for b in msg.content
                   if getattr(b, "type", "") == "text").strip()


class AnthropicLLM:
    """DEUX MODÈLES, parce que les deux rôles n'ont pas le même profil de risque.

    L'EXTRACTEUR décide du sens. Depuis le menu d'actions (`actions.py`), c'est lui qui
    dit si « le plus vite possible » est un choix de créneau, une contrainte, ou du bruit
    de transcription. Une erreur là déraille toute la conversation — R71 en est né. C'est
    le poste où payer plus de capacité se justifie.

    Le FORMULEUR est borné par ailleurs : `guards.check_output` refuse ses sorties non
    conformes, et tout ce qui énonce un fait (prix, date, engagement) est `verbatim`, donc
    ne passe pas par lui du tout (R63). Au pire il est moins élégant. Et c'est LUI que
    l'appelant attend pour entendre quelque chose : c'est donc lui qui pèse sur la latence
    perçue, et lui qu'on garde rapide.

    Les deux variables se règlent séparément, avec `RELAIS_MODEL` comme défaut commun pour
    que rien ne change sans qu'on l'ait voulu. Un modèle passé en ARGUMENT gagne sur
    l'environnement : `run_extract_eval.py` force un modèle pour le comparer, et une
    variable d'environnement qui écraserait ce choix rendrait la mesure fausse sans le
    dire.
    """

    def __init__(self, model: str | None = None, modele_formuleur: str | None = None):
        import anthropic  # import tardif : optionnel en mode mock
        # timeout court + 1 retry : au téléphone, mieux vaut dégrader vite que faire
        # attendre l'appelant (le SDK attendrait sinon bien plus longtemps)
        self.client = anthropic.Anthropic(timeout=10.0, max_retries=1)
        defaut = os.environ.get("RELAIS_MODEL", "claude-haiku-4-5")
        self.model = model or os.environ.get("RELAIS_MODEL_EXTRACTEUR") or defaut
        self.modele_formuleur = (modele_formuleur
                                 or os.environ.get("RELAIS_MODEL_FORMULEUR") or defaut)

    def extract(self, utterance: str, context: dict) -> dict:
        # max_tokens large : les modèles à réflexion adaptative (Sonnet 5) consomment
        # leurs tokens de réflexion DANS max_tokens — 200 tronquait les réponses en plein mot.
        msg = self.client.messages.create(
            model=self.model, max_tokens=1500,
            system=EXTRACT_SYSTEM.format(
                metier=context["metier"], prestations=context["prestations"],
                dernier_agent=context.get("dernier_agent", ""),
                propositions=context.get("propositions", []) or "aucune",
                aujourdhui=context.get("aujourdhui") or "(date inconnue)",
                menu=actions.bloc_prompt(context.get("etat", "")),
                # TOUJOURS, et pas seulement là où le menu existe : les gens annoncent
                # leurs disponibilités dans leur première phrase (« un entretien, mais
                # uniquement le samedi matin »). Une contrainte est un FAIT sur l'appel ;
                # l'ACTION `contrainte` reste propre au tour des créneaux. Les confondre
                # a fait perdre R11 pendant le refactor de R83 — et R11 existe justement
                # parce qu'un appelant réel avait dit « que le samedi matin » d'emblée.
                menu_contrainte=actions.bloc_prompt_contrainte()),
            messages=[{"role": "user", "content": utterance}],
        )
        return json_de(_texte_de(msg))

    def reply(self, instruction: str, context: dict) -> str:
        dernier = context.get("dernier_tour") or "(l'appelant reste silencieux)"
        msg = self.client.messages.create(
            model=self.modele_formuleur, max_tokens=1500,
            system=REPLY_SYSTEM.format(
                nom_entreprise=context["nom_entreprise"], metier=context["metier"],
                instruction=instruction),
            messages=[{"role": "user", "content": dernier}],
        )
        texte = _texte_de(msg)
        # ceinture + bretelles : jamais de réplique vide au téléphone
        return texte or instruction


class ResilientLLM:
    """Dégradation gracieuse : si le LLM primaire échoue (réseau coupé, API en panne,
    timeout), l'appel CONTINUE en mode scripté — extraction par règles (MockLLM) et
    répliques = instructions du contrôleur. Moins naturel, jamais muet.

    Chaque dégradation est journalisée et remonte dans le lead
    (`degradations_llm`) : l'artisan a un lead un peu moins bien qualifié,
    nous avons l'alerte monitoring. En prod, s'y ajoutera l'étage voix.
    """

    def __init__(self, primary, fallback=None):
        self.primary = primary
        self.fallback = fallback or MockLLM()
        self.degradations: list[str] = []

    def _degrade(self, quoi: str, exc: Exception) -> None:
        self.degradations.append(f"{quoi}:{type(exc).__name__}")

    def extract(self, utterance: str, context: dict) -> dict:
        try:
            return self.primary.extract(utterance, context)
        except Exception as exc:  # réseau, API, timeout : on ne laisse JAMAIS tomber l'appel
            self._degrade("extract", exc)
            return self.fallback.extract(utterance, context)

    def reply(self, instruction: str, context: dict) -> str:
        try:
            return self.primary.reply(instruction, context)
        except Exception as exc:
            self._degrade("reply", exc)
            return self.fallback.reply(instruction, context)  # = l'instruction, prononçable


def make_llm(mock: bool = False):
    if mock or not os.environ.get("ANTHROPIC_API_KEY"):
        return MockLLM()
    return ResilientLLM(AnthropicLLM())
