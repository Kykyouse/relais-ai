"""Le CONTRÔLEUR : machine à états S0–S11 (docs/script-conversation-v1.md).

Chaque tour :
  1. le LLM EXTRAIT les slots de la phrase de l'appelant (remplissage opportuniste :
     un slot se remplit à n'importe quel état, on ne repose jamais une question résolue) ;
  2. le contrôleur applique les transitions et choisit l'INSTRUCTION suivante ;
  3. le LLM FORMULE la réplique ;
  4. guards.check_output vérifie — violation => formulation sûre de repli.

Le LLM ne choisit jamais ni l'état ni le contenu engageant (créneaux, prix, promesses).
"""
from __future__ import annotations

from .calendar_stub import CalendarStub
from .guards import check_output, safe_fallback
from .states import EMPTY_SLOTS, State, URGENT_PRESTATIONS


class Conversation:
    def __init__(self, config: dict, llm, calendar: CalendarStub | None = None):
        self.cfg = config
        self.llm = llm
        self.cal = calendar or CalendarStub(config)
        self.state = State.S0_OUVERTURE
        self.slots = dict(EMPTY_SLOTS)
        self.transcript: list[tuple[str, str]] = []  # (qui, texte)
        self.flags: dict = {"zone": None, "violations": [], "consignes_donnees": [],
                            "demandes_humain": 0, "tours_creneaux": 0,
                            "tentatives_tel": 0, "hold": None, "categorie": None}
        self._proposes: list[dict] = []
        self._silences = 0

    # ------------------------------------------------------------------ utils
    @property
    def _prenom(self) -> str:
        return self.cfg["entreprise"]["prenom_patron"]

    @property
    def _ctx(self) -> dict:
        return {
            "metier": self.cfg["entreprise"]["metier"],
            "nom_entreprise": self.cfg["entreprise"]["nom"],
            # COUVERTES **ET** REFUSÉES. L'extracteur doit pouvoir NOMMER ce qu'il entend,
            # y compris ce que l'artisan ne fait pas — sinon « déboucher la colonne de
            # l'immeuble » se rapproche de `wc_evacuation` et l'agent réserve un créneau
            # pour des travaux explicitement exclus. C'est le contrôleur qui décline
            # (`_hors_perimetre`), pas le LLM : lui ne fait que dire ce qu'il entend.
            # Jusqu'au 25/08 il ne voyait que les couvertes, et ce chemin du moteur était
            # donc injoignable en production.
            "prestations": (list(self.cfg["prestations"]["couvertes"])
                            + list(self.cfg["prestations"].get("refusees") or [])),
            "dernier_tour": self.transcript[-1][1] if self.transcript else "",
            # contexte pour l'EXTRACTEUR : sans ça, il ne peut pas comprendre
            # "le matin entre 8h et 10h" comme le choix de la proposition n°1 (bug R09-LLM)
            "dernier_agent": next((t for w, t in reversed(self.transcript)
                                   if w == "agent"), ""),
            "propositions": [s["label"] for s in self._proposes],
        }

    def _dernier_client(self) -> str:
        return next((t for who, t in reversed(self.transcript) if who == "client"), "")

    def _tel_espace(self) -> str:
        tel = self.slots["telephone_rappel"] or ""
        return " ".join(tel[i:i + 2] for i in range(0, len(tel), 2))

    def _say(self, instruction: str, verbatim: bool = False) -> str:
        # consigne sécurité en attente (ex. "coupez l'eau") : ne JAMAIS la perdre,
        # même quand la conversation saute des étapes (tout donné d'un coup)
        prefix = self.flags.pop("pending_prefix", "")
        if prefix:
            instruction = prefix + instruction
        # verbatim : phrases critiques (réservation, promesse de rappel) prononcées
        # telles quelles — le formuleur n'a pas le droit de réécrire une date ou un engagement
        texte = instruction if verbatim else self.llm.reply(instruction, self._ctx)
        violations = check_output(texte, self.cfg)
        if violations:
            self.flags["violations"].extend(violations)
            # repli = l'instruction du contrôleur elle-même (sûre par construction),
            # pas une phrase générique hors sujet — sauf si elle est elle-même fautive
            texte = instruction if not check_output(instruction, self.cfg) \
                else safe_fallback(violations, self.cfg)
        self.transcript.append(("agent", texte))
        return texte

    # slots corrigeables tant que le RDV n'est pas réservé (leçon des bugs "numéro" et "commune")
    OVERWRITABLE = {"code_postal", "commune", "disponibilites"}

    def _merge(self, extracted: dict) -> None:
        for k, v in extracted.items():
            if k not in self.slots or v in (None, ""):
                continue
            if self.slots[k] is None or (k in self.OVERWRITABLE and self.flags["hold"] is None):
                self.slots[k] = v
        if extracted.get("prestation") and not self.slots["intent"]:
            p = extracted["prestation"]
            self.slots["intent"] = ("urgence" if p in URGENT_PRESTATIONS
                                    else "entretien" if p == "entretien_chaudiere"
                                    else "devis_travaux")

    # ------------------------------------------------------- sérialisation
    # En prod, chaque tour d'appel arrivera comme un webhook HTTP, potentiellement sur
    # un AUTRE process que le tour précédent : l'état de la conversation doit donc
    # pouvoir vivre hors mémoire (Redis/Postgres) et revenir à l'identique.
    # Ne sont PAS sérialisés : la config artisan et le client LLM — ce sont des
    # dépendances injectées au rechargement, pas de l'état d'appel.
    ETAT_VERSION = 1

    def to_dict(self) -> dict:
        """État complet de l'appel, JSON-sérialisable. Version explicite : ce dict
        sera stocké en base, il évoluera plus vite que le code qui le lit."""
        return {
            "v": self.ETAT_VERSION,
            "state": self.state.value,
            "slots": dict(self.slots),
            "transcript": [[qui, texte] for qui, texte in self.transcript],
            "flags": dict(self.flags),
            "proposes": [dict(s) for s in self._proposes],
            "silences": self._silences,
            "calendrier": self.cal.to_dict(),
            # les dégradations vivent sur le CLIENT LLM mais appartiennent à l'appel
            # (elles remontent dans le lead) : elles voyagent donc avec l'état, sinon
            # un appel dégradé rechargé produit un lead faussement « propre ».
            "degradations_llm": list(getattr(self.llm, "degradations", [])),
        }

    @classmethod
    def from_dict(cls, data: dict, config: dict, llm) -> Conversation:
        if data.get("v") != cls.ETAT_VERSION:
            raise ValueError(f"état de conversation v{data.get('v')} non supporté "
                             f"(attendu v{cls.ETAT_VERSION})")
        convo = cls(config, llm,
                    calendar=CalendarStub.from_dict(data["calendrier"], config))
        convo.state = State(data["state"])
        # EMPTY_SLOTS en base : un état écrit avant l'ajout d'un slot doit rester lisible
        convo.slots = {**EMPTY_SLOTS, **data["slots"]}
        convo.transcript = [(qui, texte) for qui, texte in data["transcript"]]
        convo.flags = dict(data["flags"])
        convo._proposes = [dict(s) for s in data["proposes"]]
        convo._silences = data["silences"]
        if isinstance(getattr(llm, "degradations", None), list):
            llm.degradations = list(data.get("degradations_llm", []))
        return convo

    # ------------------------------------------------------------- ouverture
    def open(self) -> str:
        """Première réplique (S0) — l'annonce IA est DANS le texte, non négociable."""
        formule = self.cfg["accueil"]["formule"] or (
            f"Bonjour, vous êtes bien chez {self.cfg['entreprise']['nom']}. "
            f"Je suis son assistant vocal — {self._prenom} est en intervention, "
            f"mais je peux tout organiser avec vous. Que se passe-t-il ?")
        self.state = State.S1_COMPRENDRE
        self.transcript.append(("agent", formule))
        return formule

    # ------------------------------------------------------------- tour
    def process(self, user_text: str) -> str:
        if self.state in (State.S11_CLOTURE, State.FIN):
            return self._say("L'appel est terminé. Bonne journée !")

        user_text = user_text.strip()
        self.transcript.append(("client", user_text))

        # silence / répondeur
        if not user_text or user_text == "...":
            self._silences += 1
            if self._silences == 1:
                return self._say("Je vous écoute ?")
            self.state = State.S9_REPONDEUR
            self.flags["categorie"] = "appel_muet"
            texte = self._say(
                f"Vous avez appelé {self.cfg['entreprise']['nom']}. Rappelez-nous ou "
                f"envoyez un SMS à ce numéro, nous revenons vers vous rapidement.")
            self.state = State.FIN
            return texte

        extracted = self.llm.extract(user_text, self._ctx)
        self._merge(extracted)
        # `extracted` est passé : c'est lui qui porte le signal de correction
        # (négation, code postal prononcé) qui autorise à réécrire une commune établie.
        self._resoudre_commune(user_text, extracted)  # "je suis à Saint-Maur" → CP

        # correction de commune en cours d'appel : revalider la zone immédiatement
        if extracted.get("code_postal") and self.flags["zone"] is not None:
            nouvelle = self._zone_de(self.slots["code_postal"])
            if nouvelle == "hors_zone":
                return self._hors_zone()
            self.flags["zone"] = nouvelle

        # demande d'humain : 1 reprise DÉDIÉE (le contrôleur décide quoi dire —
        # sinon le formuleur improvise des promesses de rappel), puis transfert (invariant 7)
        if extracted.get("veut_humain"):
            self.flags["demandes_humain"] += 1
            if self.flags["demandes_humain"] >= 2:
                return self._goto_transfert()
            return self._say(
                f"Je comprends que vous préfériez parler directement à {self._prenom} — "
                f"il est en intervention en ce moment, mais je peux tout organiser pour vous. "
                f"Dites-moi simplement ce qui vous arrive ?")

        # danger gaz : consigne sécurité immédiate (catalogue fermé), puis on continue
        if self.slots["danger_gaz"] and "gaz" not in self.flags["consignes_donnees"]:
            self.flags["consignes_donnees"].append("gaz")
            consigne = self.cfg["securite"]["consignes_autorisees"]["gaz_aerer_et_grdf"]
            if self.cfg["securite"]["transfert_si_danger"]:
                self.transcript.append(("agent", consigne))
                return self._goto_transfert(prefix=consigne)

        handler = {
            State.S1_COMPRENDRE: self._s1,
            State.S2_LOCALISER: self._s2,
            State.S3_QUALIFIER: self._s3,
            State.S4_IDENTITE: self._s4,
            State.S5_CRENEAU: self._s5,
        }.get(self.state)
        return handler(extracted) if handler else self._cloture()

    # ------------------------------------------------------------- états
    def _s1(self, ex: dict) -> str:
        p = self.slots["prestation"]
        if p is None:
            return self._say("Pouvez-vous me préciser ce qui vous arrive ? "
                             "Une fuite, un souci de chauffage, autre chose ?")
        if p in self.cfg["prestations"]["refusees"] :
            return self._hors_perimetre()
        if p not in self.cfg["prestations"]["couvertes"]:
            return self._hors_perimetre()
        # consigne sécurité fuite (catalogue fermé) — portée par pending_prefix
        # pour survivre aux sauts d'états (cf. bug cas A : tout donné d'un coup)
        if p == "fuite" and "eau" not in self.flags["consignes_donnees"]:
            self.flags["consignes_donnees"].append("eau")
            self.flags["pending_prefix"] = \
                self.cfg["securite"]["consignes_autorisees"]["couper_eau"] + " "
        self.state = State.S2_LOCALISER
        if self.slots["code_postal"]:
            return self._s2({})
        self.flags["commune_demandee"] = True
        return self._say("Vous êtes sur quelle commune ?")

    @staticmethod
    def _normalise(texte: str) -> str:
        import re as _re
        import unicodedata
        t = unicodedata.normalize("NFD", texte.lower())
        t = "".join(c for c in t if unicodedata.category(c) != "Mn")  # sans accents
        # ponctuation → espaces : « c'est Saint-Maur. » doit matcher « saint maur »
        # (bug LLM-run3 : la virgule/le point cassaient la correspondance)
        return _re.sub(r"\s+", " ", _re.sub(r"[^a-z0-9]+", " ", t)).strip()

    _COMMUNES_IDF: dict | None = None  # table France Île-de-France (base officielle Etalab)

    # Alias d'un seul mot qui sont AUSSI des mots français courants. La table porte, pour
    # chaque commune composée, un alias court bien utile — « Issy », « Sucy », « Ivry »
    # sont ce que les gens disent vraiment. Mais quelques-uns sont des homonymes qui
    # apparaissent naturellement dans un appel de plomberie, et les garder coûte des leads.
    #
    # Trouvé par l'éval LLM du 25/08 : « il faudrait que quelqu'un VIENNE assez vite » a
    # résolu Vienne-en-Arthies (95510), classé l'appel hors zone et raccroché au premier
    # tour. Sur une fuite d'eau en cours.
    #
    # L'exclusion vit ICI et non dans le fichier de données : celui-ci est régénéré depuis
    # la base officielle, et une régénération réintroduirait les homonymes en silence. Le
    # nom COMPLET reste résoluble dans tous les cas (« Vienne-en-Arthies », « Bois-le-Roi »).
    ALIAS_AMBIGUS = frozenset({
        "vienne",   # « qu'il vienne », « que quelqu'un vienne » — subjonctif de venir
        "bois",     # « je bois », « le bois », « sous le bois »
        "champs",   # « les champs »
        "bourg",    # « le bourg »
        # Méré (78490). « C'est pour la chaudière de ma mère » est une des phrases les
        # plus courantes du métier — beaucoup d'appels sont passés POUR quelqu'un d'autre.
        # Trouvé le 25/08 par le persona T12, qui visait tout autre chose.
        "mere",
    })

    @classmethod
    def _communes_idf(cls) -> dict:
        if cls._COMMUNES_IDF is None:
            import json
            import pathlib
            chemin = pathlib.Path(__file__).parent / "data" / "communes_idf.json"
            brut = json.loads(chemin.read_text(encoding="utf-8")) \
                if chemin.exists() else {}
            cls._COMMUNES_IDF = {n: cp for n, cp in brut.items()
                                 if n not in cls.ALIAS_AMBIGUS}
        return cls._COMMUNES_IDF

    def _phrase_prix(self) -> str:
        """LA réponse tarifaire autorisée, tirée de la liste blanche de la config.

        Factorisée le 25/08 : elle vivait en ligne dans S4, et S5 n'avait donc rien à dire
        quand on lui posait la question — l'agent refusait de répondre alors qu'il avait
        un prix à annoncer, et perdait le client.
        """
        dep = next((t["phrase"] for t in self.cfg["tarifs"]["communicables"]
                    if t["libelle"] == "deplacement_diagnostic"), None)
        if dep:
            return (dep + " Pour le reste, ça dépendra de ce que "
                    f"{self._prenom} constatera sur place.")
        return (f"Ça dépend de ce que {self._prenom} constatera sur place — "
                "je ne veux pas vous annoncer un chiffre faux.")

    def _prix_a_repondre(self, ex: dict) -> bool:
        """Vrai s'il faut répondre à une question de prix maintenant.

        La patience est BORNÉE et partagée entre les états : au-delà de deux questions,
        on avance au lieu de resservir la même phrase indéfiniment — l'appelant qui
        insiste encore cherche autre chose qu'un tarif.
        """
        if not ex.get("question_prix"):
            return False
        self.flags["questions_prix"] = self.flags.get("questions_prix", 0) + 1
        return self.flags["questions_prix"] <= 2

    @staticmethod
    def _signal_de_correction(ex: dict | None) -> bool:
        """L'appelant est-il en train de SE CORRIGER dans cette phrase ?

        Deux signaux, et seulement deux : une négation (« non… pardon, c'est plutôt… »),
        ou un code postal prononcé — cinq chiffres ne sont jamais un homonyme.
        """
        ex = ex or {}
        return ex.get("confirme") is False or bool(ex.get("code_postal"))

    def _resoudre_commune(self, texte: str, ex: dict | None = None) -> None:
        """Reconnaît une commune citée dans la phrase et en déduit le CP — l'appelant
        donne sa ville, pas son code postal. Deux tables : celle de la zone artisan
        (avec ses alias configurés), puis la base Île-de-France complète (1 500 entrées,
        base officielle des codes postaux) — une commune IdF hors zone est ainsi
        classée hors_zone immédiatement, sans demander le CP.
        Déterministe, dans le contrôleur : le LLM n'a JAMAIS le droit de deviner un CP."""
        # Une commune DÉJÀ connue ne bloque plus la relecture : « je suis à Créteil… ah
        # non pardon, Nogent-sur-Marne » doit gagner. Sortir dès qu'un CP existait rendait
        # toute correction PAR LE NOM impossible, et l'artisan partait dans la mauvaise
        # ville — alors que la correction du NUMÉRO, elle, marchait déjà. C'est cette
        # asymétrie qui a caché le défaut jusqu'au 25/08 (persona T10).
        #
        # MAIS relire à chaque tour sans condition est allé trop loin, et l'éval l'a
        # montré le jour même : « ne notez pas le numéro de ma mère », prononcé trois
        # tours après coup, réécrivait une commune déjà confirmée (persona T12). Un nom
        # de commune est ambigu par nature ; il ne remplace donc une commune ÉTABLIE que
        # si l'appelant se corrige explicitement. Tant qu'aucune n'est établie, tout ce
        # qui est nommé est bon à prendre.
        #
        # Deux bornes, donc : le hold (une fois le créneau bloqué, plus rien ne bouge) et
        # le signal de correction.
        if self.flags["hold"] is not None:
            return
        if self.slots["code_postal"] is not None \
                and not self._signal_de_correction(ex):
            return
        phrase = " " + self._normalise(texte) + " "

        def _cherche(table: dict) -> tuple[str, list[str]] | None:
            # noms les plus longs d'abord ("le perreux sur marne" avant "perreux")
            for nom in sorted(table, key=len, reverse=True):
                if " " + self._normalise(nom) + " " in phrase:
                    v = table[nom]
                    return nom, (v if isinstance(v, list) else [v])
            return None

        trouve = _cherche(self.cfg["zone"].get("communes", {})) \
            or _cherche(self._communes_idf())
        if not trouve:
            return
        nom, cps = trouve
        # D'OÙ vient cette commune : d'une réponse à notre question, ou glanée au passage
        # dans une phrase qui parlait d'autre chose ? La seconde n'a été ni demandée ni
        # confirmée — elle ne pourra donc pas clore l'appel toute seule (cf. `_s2`).
        self.flags["commune_incidente"] = not self.flags.get("commune_demandee")
        zone = self.cfg["zone"]
        # commune multi-CP (ex. Saint-Maur : 94100/94210/94340) : préférer un CP
        # couvert, puis limitrophe, sinon le premier (=> classement hors_zone)
        cp = next((c for c in cps if c in zone["codes_postaux"]),
                  next((c for c in cps if c in zone["codes_postaux_limitrophes"]),
                       cps[0]))
        # Capitalisée avant d'être stockée : c'est une clé de table, mais elle finit dans
        # une phrase dite à l'appelant (« n'intervient pas sur sucy ») et dans le SMS de
        # relance à l'artisan. Le nom d'une ville s'écrit avec des majuscules.
        self.slots["commune"] = " ".join(m.capitalize() for m in nom.split())
        self.slots["code_postal"] = cp

    JOURS_SEMAINE = {"lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
                     "vendredi": 4, "samedi": 5, "dimanche": 6}

    def _contraintes_dispo(self) -> tuple[set[int] | None, str | None]:
        """Contraintes de créneaux tirées des disponibilités exprimées par l'appelant."""
        d = self._normalise(self.slots.get("disponibilites") or "")
        jours = {n for nom, n in self.JOURS_SEMAINE.items() if nom in d} or None
        moment = ("matin" if "matin" in d
                  else "apres_midi" if ("apres midi" in d or "aprem" in d) else None)
        return jours, moment

    def _zone_de(self, cp: str | None) -> str:
        zone = self.cfg["zone"]
        if cp in zone["codes_postaux"]:
            return "en_zone"
        if cp in zone["codes_postaux_limitrophes"]:
            return "limitrophe"
        return "hors_zone"

    def _s2(self, ex: dict) -> str:
        # Une confirmation de commune est en attente (cf. plus bas). Les slots ont été
        # VIDÉS en posant la question, pour que la réponse soit relue sans entrave : si
        # l'appelant corrige, `_resoudre_commune` a déjà fait son travail avant d'arriver
        # ici, et le candidat n'a plus qu'à être oublié.
        candidat = self.flags.get("commune_a_confirmer")
        if candidat:
            if self.slots["code_postal"] is not None:      # il a nommé une autre commune
                self.flags["commune_a_confirmer"] = None
            elif ex.get("confirme") is True:
                self.flags["commune_a_confirmer"] = None
                self.slots["commune"], self.slots["code_postal"] = candidat
                self.flags["zone"] = self._zone_de(candidat[1])
                return self._hors_zone()
            else:                                          # « non », ou rien d'exploitable
                self.flags["commune_a_confirmer"] = None
                self.flags["commune_demandee"] = True
                return self._say("Vous êtes sur quelle commune ?")

        cp = self.slots["code_postal"]
        if cp is None:
            self.flags["commune_demandee"] = True
            return self._say("J'ai besoin de votre commune ou code postal pour vérifier "
                             "qu'on intervient chez vous — vous êtes où ?")
        self.flags["zone"] = self._zone_de(cp)
        if self.flags["zone"] == "hors_zone":
            # NE PAS raccrocher sur une commune glanée au passage. C'est la même règle que
            # « pas de RDV sans téléphone confirmé » : une décision terminale et coûteuse
            # ne se prend pas sur une donnée que personne n'a vérifiée. Le 25/08, « il
            # faudrait que quelqu'un vienne » a coûté un lead de fuite en cours.
            # Une commune DEMANDÉE, elle, tranche immédiatement — pas de question de trop.
            if self.flags.get("commune_incidente"):
                self.flags["commune_a_confirmer"] = (self.slots["commune"], cp)
                self.flags["commune_incidente"] = False
                nom = self.slots["commune"]
                self.slots["commune"] = self.slots["code_postal"] = None
                self.flags["zone"] = None
                return self._say(f"Juste pour être sûr — vous êtes bien à {nom} ?")
            return self._hors_zone()
        self.state = State.S3_QUALIFIER
        return self._s3({})

    def _s3(self, ex: dict) -> str:
        if self.slots["intent"] == "urgence" and self.slots["urgence_reelle"] is None:
            if not self.flags.get("urgence_demandee"):
                self.flags["urgence_demandee"] = True
                return self._say("C'est en cours en ce moment, ou ça peut attendre un peu ?")
            # réponse au tour précédent : on interprète, et on ne redemande JAMAIS
            self.slots["urgence_reelle"] = bool(ex.get("confirme", ex.get("urgence_reelle", False)))
        self.state = State.S4_IDENTITE
        return self._s4({})

    def _s4(self, ex: dict) -> str:
        if not self.flags.get("identite_demandee") and self.slots["telephone_rappel"] is None:
            self.flags["identite_demandee"] = True
            return self._say("Très bien. À quel nom, et sur quel numéro "
                             f"{self._prenom} peut vous confirmer le rendez-vous ?")
        if self.slots["telephone_rappel"] is None:
            # une QUESTION (prix...) n'est pas un REFUS : on y répond avec la liste
            # blanche et on redemande, sans consommer le quota (bug T05-LLM : Katz
            # posait des questions de prix et perdait son RDV)
            if self._prix_a_repondre(ex):
                return self._say(self._phrase_prix() + " Et pour organiser son passage, "
                                 "quel est votre numéro ?")
            # numéro incomplet ? (des chiffres, mais pas un numéro FR valide)
            # — en excluant un code postal donné dans la même phrase (bug B : "94000")
            import re as _re
            texte = self._dernier_client()
            if ex.get("code_postal"):
                texte = texte.replace(ex["code_postal"], "")
            digits = _re.sub(r"\D", "", texte)
            if 5 <= len(digits) <= 9:
                self.flags["tel_incomplets"] = self.flags.get("tel_incomplets", 0) + 1
                if self.flags["tel_incomplets"] >= 3:
                    return self._sans_rdv()
                return self._say("Ce numéro me semble incomplet — pouvez-vous me le "
                                 "redonner en entier, avec les dix chiffres ?")
            self.flags["tentatives_tel"] += 1
            if self.flags["tentatives_tel"] >= 2:  # 2 tentatives max (T11), puis repli propre
                return self._sans_rdv()  # invariant 2 : pas de RDV sans rappel
            return self._say("Il me faut un numéro où vous joindre pour la confirmation — "
                             "sans ça je ne peux pas réserver. Quel est votre numéro ?")
        if not self.slots["tel_confirme"]:
            # correction : un NOUVEAU numéro donné pendant la confirmation remplace l'ancien
            nouveau = ex.get("telephone_rappel")
            if nouveau and nouveau != self.slots["telephone_rappel"]:
                self.slots["telephone_rappel"] = nouveau
                return self._say(f"Je répète votre numéro : {self._tel_espace()}. "
                                 f"C'est bien ça ?", verbatim=True)  # chiffres jamais réécrits
            if ex.get("confirme") is True:
                self.slots["tel_confirme"] = True
            elif ex.get("confirme") is False:
                # le numéro répété est FAUX : on l'efface et on redemande (jamais re-répéter le faux)
                self.slots["telephone_rappel"] = None
                return self._say("Au temps pour moi — redonnez-moi le bon numéro ?")
            else:
                # Ni oui ni non. On repose la question — mais PAS indéfiniment : cette
                # boucle-ci n'était bornée par rien (`tentatives_tel` borne la DEMANDE du
                # numéro, pas sa confirmation), et un appelant qui répond à côté deux fois
                # tuait l'appel sans produire le moindre lead (persona T09, 25/08).
                # Le compteur repart à zéro à CHAQUE nouveau numéro : une correction
                # (« non… c'est plutôt le 07… ») relance une confirmation neuve, elle ne
                # doit pas être pénalisée par les tours passés sur le numéro précédent.
                en_cours = self.slots["telephone_rappel"]
                if self.flags.get("tel_repete_pour") != en_cours:
                    self.flags["tel_repete_pour"] = en_cours
                    self.flags["confirmations_tel"] = 0
                self.flags["confirmations_tel"] += 1
                # 1 = la répétition normale, 2 = la relance « oui ou non », au-delà on
                # arrête : l'appelant ne répond pas à CETTE question-là.
                if self.flags["confirmations_tel"] > 2:
                    # L'invariant reste intouchable : pas de RDV sans téléphone confirmé.
                    # On ne réserve donc pas — on conclut avec un lead exploitable, le
                    # numéro entendu inclus, et c'est l'artisan qui rappellera.
                    return self._sans_rdv()
                return self._say(f"Je répète votre numéro : {self._tel_espace()}. "
                                 f"C'est bien ça ? Répondez simplement oui ou non.",
                                 verbatim=True)  # chiffres jamais réécrits
        self.state = State.S5_CRENEAU
        return self._s5({})

    def _s5(self, ex: dict) -> str:
        # choix d'un créneau proposé ?
        if self._proposes:
            choix = ex.get("creneau_choisi")
            # « Oui, MAIS ça coûte combien ? » n'est pas le choix d'un créneau. Un `oui`
            # accompagné d'une question ne vaut acceptation de rien : réserver dessus
            # donnerait un rendez-vous que l'appelant n'a pas accepté — la faute que tout
            # le produit est construit pour éviter. Un choix EXPLICITE (« le premier »)
            # reste prioritaire, lui.
            if choix is None and ex.get("confirme") is True \
                    and not ex.get("question_prix"):
                choix = 1
            if choix and choix <= len(self._proposes):
                return self._reserver(self._proposes[choix - 1])
        # Une QUESTION de prix n'est pas un refus de créneau. Elle tombait pourtant dans
        # le quota de l'invariant n°6 : l'agent reproposait des créneaux, le compteur
        # avançait, et DEUX questions suffisaient à faire perdre le RDV — à un client qui
        # était toujours partant (Katz, éval réelle du 25/08). S4 avait appris la leçon
        # dès le 22/08 sans qu'elle soit généralisée à l'état suivant.
        # On répond avec la liste blanche et on RAPPELLE les créneaux déjà proposés :
        # les remplacer ferait changer la liste sous les pieds de l'appelant, qui ne
        # pourrait plus répondre « le premier ».
        if self._proposes and self._prix_a_repondre(ex):
            rappel = (self._proposes[0]["label"] if len(self._proposes) == 1
                      else f"{self._proposes[0]['label']}, ou {self._proposes[1]['label']}")
            return self._say(f"{self._phrase_prix()} Pour le rendez-vous, je peux vous "
                             f"proposer {rappel}. Lequel vous arrange ?")
        # "rien de plus tôt ?" n'est PAS un rejet : on re-propose le PREMIER créneau,
        # on n'avance pas dans le calendrier (bug T01/R09-LLM : la cliente voulait
        # plus tôt, on lui proposait plus tard et lundi disparaissait)
        if ex.get("veut_plus_tot") and self._proposes:
            self.flags["tours_creneaux"] += 1
            if self.flags["tours_creneaux"] <= 2:
                return self._say(
                    f"Je n'ai malheureusement rien de plus tôt : le premier créneau "
                    f"disponible est {self._proposes[0]['label']}. "
                    f"Voulez-vous que je vous le réserve ?")
        # (re)proposer — max 2 tours (invariant 6)
        if self.flags["tours_creneaux"] >= 2:
            return self._sans_rdv()
        urgent = bool(self.slots["urgence_reelle"]) and self.slots["intent"] == "urgence"
        # respecter les disponibilités exprimées ("que le samedi matin" — bug T03-LLM)
        jours, moment = self._contraintes_dispo()
        # 2e tour = créneaux SUIVANTS, jamais les mêmes reproposés
        self._proposes = self.cal.get_slots(self.slots["prestation"], urgent, n=2,
                                            skip=2 * self.flags["tours_creneaux"],
                                            jours=jours, moment=moment)
        self.flags["tours_creneaux"] += 1
        if not self._proposes:
            return self._sans_rdv()
        if len(self._proposes) == 1:
            offre = f"Je peux vous proposer {self._proposes[0]['label']}. Ça vous irait ?"
        else:
            offre = (f"Je peux vous proposer {self._proposes[0]['label']}, "
                     f"ou {self._proposes[1]['label']}. Lequel vous arrange ?")
        return self._say(offre)

    # ------------------------------------------------------------- issues
    def _reserver(self, slot: dict) -> str:
        self.flags["hold"] = self.cal.hold_slot(slot, self.slots["prestation"])
        urgent = bool(self.slots["urgence_reelle"])
        # meme source que rdv.calculer_expiration : la promesse prononcee et l'echeance
        # stockee en base ne doivent JAMAIS diverger (verrouille par R15)
        delai = (self.cfg["validation"]["delai_max_urgence_heures"] if urgent
                 else self.cfg["validation"]["delai_max_heures"])
        heures = "heure" if delai == 1 else "heures"
        self.flags["categorie"] = "rdv_reserve"
        # LA phrase du script : "réservé" + SMS de confirmation, jamais "confirmé"
        texte = self._say(
            f"Parfait, je vous réserve {slot['label']}. Vous recevrez un SMS de "
            f"confirmation de {self._prenom} d'ici {delai} {heures}. "
            f"Si quoi que ce soit coince, on vous rappelle. Bonne journée !",
            verbatim=True)  # LA phrase du script : date et engagement jamais réécrits
        self.state = State.S11_CLOTURE
        return texte

    def _sans_rdv(self) -> str:
        self.flags["categorie"] = self.flags["categorie"] or "a_rappeler"
        promesse = self.cfg["accueil"]["promesse_rappel"]["ouvree"]
        texte = self._say(
            f"Je transmets tout ça à {self._prenom} dès qu'il sort d'intervention — "
            f"il vous rappelle {promesse}. Bonne journée !",
            verbatim=True)  # promesse de rappel : engagement jamais réécrit
        self.state = State.S11_CLOTURE
        return texte

    def _goto_transfert(self, prefix: str = "") -> str:
        self.state = State.S7_TRANSFERT
        self.flags["categorie"] = "prioritaire"
        # Prototype : le transfert échoue toujours -> S6 avec marquage prioritaire
        texte = self._say(
            (prefix + " " if prefix else "") +
            f"Je regarde si je peux vous passer {self._prenom}… il est en intervention. "
            f"Je lui transmets en priorité : il vous rappelle "
            f"{self.cfg['accueil']['promesse_rappel']['ouvree']}.")
        self.state = State.S11_CLOTURE
        return texte

    def _hors_zone(self) -> str:
        self.flags["zone"] = "hors_zone"
        self.flags["categorie"] = "hors_zone"
        texte = self.cfg["zone"]["message_hors_zone"] or self._say(
            f"Je suis désolé, {self.cfg['entreprise']['nom']} n'intervient pas sur "
            f"{self.slots['commune'] or 'votre secteur'}. Bonne continuation !")
        self.state = State.S11_CLOTURE
        return texte

    def _hors_perimetre(self) -> str:
        self.flags["categorie"] = "hors_perimetre"
        reco = self.cfg["prestations"]["confreres_recommandation"]
        extra = f" {reco}" if reco else ""
        texte = self._say(
            f"Je suis désolé, ce n'est pas un type de travaux que "
            f"{self.cfg['entreprise']['nom']} réalise.{extra} Bonne continuation !")
        self.state = State.S11_CLOTURE
        return texte

    def _cloture(self) -> str:
        self.state = State.FIN
        return self._say("Merci de votre appel, bonne journée !")
