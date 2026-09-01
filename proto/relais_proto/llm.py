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
- disponibilites: contraintes de dispo si exprimées
- danger_gaz: true si odeur/fuite de gaz évoquée
- confirme: true/false si la phrase est une confirmation/refus de ce que l'agent vient de proposer
- question_prix: true si l'appelant demande un prix, un tarif ou une fourchette
- veut_humain: true si l'appelant demande à parler à un humain/au patron
Pour les FAITS ci-dessus, ne déduis rien qui ne soit pas dans la phrase.

Contexte de la conversation :
- L'agent vient de dire : "{dernier_agent}"
- Propositions de créneaux en cours : {propositions}
{menu}"""

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
        if any(w in u for w in ["dispo", "après", "avant", "matin", "après-midi", "quand vous voulez", "chez moi"]):
            out["disponibilites"] = utterance.strip()[:80]
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
        if any(w in u for w in self.AU_PLUS_VITE_MOCK):
            return actions.PLUS_TOT, None
        if any(j in u for j in self.JOURS_MOCK) or out.get("disponibilites"):
            return actions.CONTRAINTE, None
        if out.get("confirme") is True:
            return actions.CHOISIR, 1
        if out.get("confirme") is False:
            return actions.REFUSER, None
        return actions.PAS_CLAIR, None

    def reply(self, instruction: str, context: dict) -> str:
        return instruction  # les instructions du contrôleur sont déjà des phrases prononçables


def _texte_de(msg) -> str:
    """Concatène les blocs texte de la réponse — les modèles récents peuvent renvoyer
    des blocs de réflexion (ThinkingBlock) avant le texte : on ne lit QUE les blocs texte."""
    return "".join(b.text for b in msg.content
                   if getattr(b, "type", "") == "text").strip()


class AnthropicLLM:
    def __init__(self, model: str | None = None):
        import anthropic  # import tardif : optionnel en mode mock
        # timeout court + 1 retry : au téléphone, mieux vaut dégrader vite que faire
        # attendre l'appelant (le SDK attendrait sinon bien plus longtemps)
        self.client = anthropic.Anthropic(timeout=10.0, max_retries=1)
        self.model = model or os.environ.get("RELAIS_MODEL", "claude-haiku-4-5")

    def extract(self, utterance: str, context: dict) -> dict:
        # max_tokens large : les modèles à réflexion adaptative (Sonnet 5) consomment
        # leurs tokens de réflexion DANS max_tokens — 200 tronquait les réponses en plein mot.
        msg = self.client.messages.create(
            model=self.model, max_tokens=1500,
            system=EXTRACT_SYSTEM.format(
                metier=context["metier"], prestations=context["prestations"],
                dernier_agent=context.get("dernier_agent", ""),
                propositions=context.get("propositions", []) or "aucune",
                menu=actions.bloc_prompt(context.get("etat", ""))),
            messages=[{"role": "user", "content": utterance}],
        )
        text = _texte_de(msg)
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    def reply(self, instruction: str, context: dict) -> str:
        dernier = context.get("dernier_tour") or "(l'appelant reste silencieux)"
        msg = self.client.messages.create(
            model=self.model, max_tokens=1500,
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
