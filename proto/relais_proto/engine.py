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
        # `en_conversation` : l'accueil a le droit — et le devoir — de saluer. Il se
        # reconnaît à ce que rien n'a encore été dit. Tous les tours suivants sont des
        # tours de conversation, où une salutation est déplacée (R46).
        en_conv = bool(self.transcript)
        violations = check_output(texte, self.cfg, en_conversation=en_conv)
        if violations:
            self.flags["violations"].extend(violations)
            # repli = l'instruction du contrôleur elle-même (sûre par construction),
            # pas une phrase générique hors sujet — sauf si elle est elle-même fautive
            texte = instruction \
                if not check_output(instruction, self.cfg, en_conversation=en_conv) \
                else safe_fallback(violations, self.cfg)
        self.transcript.append(("agent", texte))
        return texte

    # slots corrigeables tant que le RDV n'est pas réservé (leçon des bugs "numéro" et "commune")
    OVERWRITABLE = {"code_postal", "commune", "disponibilites"}

    @staticmethod
    def _code_postal_fr(valeur) -> str | None:
        """Un code postal français, ou rien. Cinq chiffres, département 01–98.

        Même raison que `_numero_fr`, sur le champ qui décide si on envoie un artisan chez
        quelqu'un — et la conséquence est PIRE. Un numéro faux produit un RDV bancal ; un
        code postal faux produit un **refus définitif**.

        Le 26/08, au cinquième appel réel, le modèle a rendu « 160 » d'une phrase où
        l'appelant se reprenait (« le quatre-vingt Non, c'est 160 »). Le contrôleur l'a
        comparé aux listes de la zone, n'y a rien trouvé, et a raccroché. L'appelant était
        réellement hors zone : on a eu raison par accident. À Nogent, on perdait un client
        sur un artefact de transcription.

        Le projet avait déjà écrit la règle pour la commune — « une décision terminale et
        coûteuse ne se prend pas sur une donnée que personne n'a vérifiée » — mais elle ne
        couvrait pas le code postal venu de l'extracteur.
        """
        brut = str(valeur or "")
        chiffres = "".join(c for c in brut if c.isdigit())
        if len(chiffres) != 5:
            return None
        # Les séparateurs sont TOLÉRÉS — « 91 260 » est un code postal, et l'extracteur le
        # rend parfois ainsi. Les lettres, non : elles trahissent autre chose qu'un code
        # postal (« 94130 environ », « le 91 ou le 92 »). Même partage que `_numero_fr`.
        # J'avais d'abord exigé la forme exacte, ce qui rejetait « 91 260 » — trop strict,
        # et une mutation survivante l'a montré.
        if any(c.isalpha() for c in brut):
            return None
        # 00 et 99 ne sont pas des départements. Contrôle léger, mais il écarte les
        # suites de cinq chiffres qui n'en sont pas.
        return chiffres if "01" <= chiffres[:2] <= "98" else None

    @staticmethod
    def _numero_fr(valeur) -> str | None:
        """Un numéro FR à dix chiffres, ou rien. Aucune tolérance, aucune troncature.

        Le contrôle vit ICI, dans le contrôleur, et non dans l'extracteur : le LLM extrait,
        il ne décide pas (règle n°1). Corriger la seule expression régulière du mock
        n'aurait protégé que les tests — le modèle réel peut parfaitement rendre dix
        chiffres sur douze entendus, et c'est exactement ce qui est arrivé au téléphone le
        26/08 : douze chiffres dictés, dix répétés, « oui c'est bien ça », et un RDV dont
        le seul moyen de rappel est faux.

        Un numéro à peu près juste est pire qu'un numéro absent : sans numéro, l'invariant
        arrête la réservation et l'artisan rappelle ; avec un numéro faux, le RDV a
        l'apparence de la normalité.
        """
        chiffres = "".join(c for c in str(valeur or "") if c.isdigit())
        if len(chiffres) != 10 or not chiffres.startswith("0"):
            return None
        # tout ce qui n'est ni chiffre ni séparateur d'écriture usuel trahit autre chose
        # qu'un numéro (« 06 12 chez ma mère 34 56 78 »)
        if any(c.isalpha() for c in str(valeur or "")):
            return None
        return chiffres

    def _chiffres_dits(self, texte: str, extracted: dict) -> None:
        """Complète l'extraction avec les nombres PRONONCÉS en toutes lettres.

        Au téléphone, un code postal se dit « quatre-vingt-onze, deux cent soixante » et un
        numéro « zéro six, douze, trente-quatre… ». La transcription rend des mots ; nos
        extracteurs cherchaient des chiffres, et le slot passait à travers. Mesuré le 26/08
        sur trois appels d'affilée — sur le premier, l'appelant a fini par renoncer.

        Ici et pas dans le prompt (règle n°1) : c'est une conversion, pas une
        interprétation. Le modèle réel y arrive PARFOIS, et « parfois » ne fait pas un
        produit quand la donnée décide si on envoie quelqu'un chez un client.

        **Complète, n'écrase jamais** : ce que l'extracteur a lu en chiffres fait foi.
        Et la longueur exacte est exigée (`suite_de_chiffres`), sans quoi on inventerait
        une donnée à partir de bruit — « cinquante euros » ne fait pas un code postal.
        """
        from .nombres import suite_de_chiffres

        # Seulement si AUCUN code postal n'est encore connu. Un numéro de téléphone dicté
        # en lettres contient une sous-suite de cinq chiffres — « zéro six, douze,
        # trente-quatre… » donne 61234 — et elle écrasait un code postal déjà établi,
        # envoyant hors zone un appelant qui n'y était pas. Trouvé en écrivant R47 : le
        # cas (e) du test faisait tomber le cas (d).
        #
        # Ce n'est pas une limitation : une CORRECTION de commune passe par le nom
        # (`_resoudre_commune`) ou par des chiffres, deux chemins qui restent ouverts.
        if not extracted.get("code_postal") and self.slots.get("code_postal") is None:
            # `_code_postal_fr` est le juge unique (R50) : on lui soumet un candidat,
            # on ne décide pas à sa place.
            cp = self._code_postal_fr(suite_de_chiffres(texte, 5))
            if cp:
                extracted["code_postal"] = cp
        if not extracted.get("telephone_rappel"):
            tel = suite_de_chiffres(texte, 10)
            # `_numero_fr` reste le juge (R42) : on lui soumet un candidat, on ne décide
            # pas à sa place.
            if tel and self._numero_fr(tel):
                extracted["telephone_rappel"] = tel

    def _commune_connue(self, nom) -> str | None:
        """Le nom canonique de la commune si nos tables la connaissent, sinon None.

        Deux tables, comme `_resoudre_commune` : celle de la zone artisan (avec ses alias
        configurés), puis l'Île-de-France. Rendue capitalisée, parce qu'elle finit dans une
        phrase dite à l'appelant et dans le SMS de relance à l'artisan.

        Une commune hors Île-de-France est donc « inconnue » et ne sera pas nommée : c'est
        volontaire. Mieux vaut « votre secteur » qu'un nom qu'on ne peut pas vérifier — et
        la zone, elle, reste tranchée par le code postal.
        """
        cible = self._normalise(str(nom or ""))
        if not cible:
            return None
        for table in (self.cfg["zone"].get("communes", {}), self._communes_idf()):
            for connu in table:
                if self._normalise(connu) == cible:
                    return " ".join(m.capitalize() for m in connu.split())
        return None

    def _merge(self, extracted: dict) -> None:
        for k, v in extracted.items():
            if k not in self.slots or v in (None, ""):
                continue
            # Le code postal et le numéro de rappel sont les deux slots revérifiés en
            # entrée : ce sont les seuls dont une valeur approximative produit une
            # décision d'apparence normale — un refus définitif pour l'un, un RDV dont le
            # rappel est impossible pour l'autre.
            if k == "code_postal":
                v = self._code_postal_fr(v)
                if v is None:
                    continue
            if k == "telephone_rappel":
                v = self._numero_fr(v)
                if v is None:
                    continue
            # `commune` ne s'écrit JAMAIS seule : elle forme une paire avec `code_postal`,
            # et un nom sans code postal produisait un lead qui se contredisait
            # (« Nogent-sur-Marne / 94000 », soit Créteil — trouvé le 25/08 sur T10).
            # Le nom que l'appelant prononce sert à la RÉSOLUTION (`_resoudre_commune`
            # balaie la phrase entière), pas à remplir le slot directement.
            if k == "commune" and not extracted.get("code_postal"):
                continue
            # ...et la commune ne s'écrit QUE si notre table la connaît. Le 26/08, le
            # modèle a rendu « Essonne » — un DÉPARTEMENT — et l'agent a répondu
            # « Dupont Chauffage n'intervient pas sur Essonne ». Le nom venait de
            # l'extracteur et le contrôleur l'a répété sans le vérifier.
            #
            # C'est le pendant de R45 : là-bas le formuleur écorchait un nom propre, ici
            # l'extracteur en invente la nature. Même règle — on ne prononce que ce que
            # notre table connaît. Le repli (« votre secteur ») existait déjà, il n'était
            # simplement jamais atteint. La DÉCISION, elle, ne change pas : c'est le code
            # postal qui tranche la zone, pas le nom.
            if k == "commune":
                v = self._commune_connue(v)
                if v is None:
                    continue
            if self.slots[k] is None or (k in self.OVERWRITABLE and self.flags["hold"] is None):
                self.slots[k] = v
        if extracted.get("prestation") and not self.slots["intent"]:
            p = extracted["prestation"]
            self.slots["intent"] = ("urgence" if p in URGENT_PRESTATIONS
                                    else "entretien" if p == "entretien_chaudiere"
                                    else "devis_travaux")
        self._promouvoir_urgence()

    def _promouvoir_urgence(self) -> None:
        """Une urgence DÉCLARÉE par l'appelant rend le lead urgent, quelle que soit la
        prestation retenue.

        L'`intent` était dérivé de la SEULE prestation, via `URGENT_PRESTATIONS` — le
        second signal disponible, `urgence_reelle`, était ignoré. Un appelant qui disait
        « ça coule, c'est urgent » d'un robinet obtenait `devis_travaux`, et son lead
        plafonnait à 4 (le score 5 exige `urgence_reelle` ET `intent == "urgence"`).

        Trouvé le 25/08 par le prérequis Haiku : les six échecs avaient tous
        `urgence_reelle = True` avec `intent = devis_travaux`. Ce n'était pas une faiblesse
        de modèle — Haiku lisait « fuite au robinet » comme `robinetterie`, ce qui est
        défendable. **Sonnet masquait le défaut en tombant du bon côté de la taxonomie.**
        C'est l'appelant qui sait si ça coule, pas la nomenclature.

        Exception : un DEVIS reste un devis. « Un devis pour une PAC, c'est urgent » ne
        doit pas consommer une fenêtre d'urgence réservée — la place d'une vraie fuite.
        """
        if not self.slots["urgence_reelle"] or self.slots["intent"] == "urgence":
            return
        if (self.slots["prestation"] or "").startswith("devis_"):
            return
        self.slots["intent"] = "urgence"

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
        # Passe par `_say` comme tout le reste (règle n°2 : aucune sortie ne contourne les
        # garde-fous). Elle y échappait — l'accueil s'écrivait directement dans le
        # transcript. Le risque était faible, la formule venant de la config, mais « faible
        # » n'est pas « nul » : une config mal relue pouvait faire annoncer un prix, ou
        # perdre l'annonce IA dans une formule maison. Trouvé par une mutation survivante
        # de R46, qui ne pouvait pas être tuée parce que ce chemin-là n'existait pas.
        #
        # VERBATIM : l'annonce IA est non négociable (règle n°5), elle ne se reformule pas.
        # Et c'est le seul tour où `en_conversation` vaut faux, donc le seul où saluer est
        # permis — ce qui n'a de sens que si l'accueil passe bien par ici.
        return self._say(formule, verbatim=True)

    # ------------------------------------------------------------- tour
    def process(self, user_text: str) -> str:
        if self.state in (State.S11_CLOTURE, State.FIN):
            # VERBATIM, et pour deux raisons dont la seconde est la vraie.
            #
            # 1. Une phrase de fin n'a rien à reformuler. La faire passer par le formuleur,
            #    c'est payer un appel LLM pour prendre un risque sans contrepartie — et le
            #    risque s'est réalisé le 26/08 : « L'appel. L'appel est terminé. »
            # 2. C'EST ELLE QUI FAIT RACCROCHER. Personne ne raccroche aujourd'hui : la
            #    plateforme rejoue des tours jusqu'à ce que le client raccroche lui-même.
            #    Le mécanisme qui coupe la ligne (`endCallPhrases`) compare ce que l'agent
            #    DIT à une liste de phrases ; une phrase reformulée à chaque tour ne peut
            #    correspondre à rien. La déterminer est le préalable au raccrochage.
            return self._say("L'appel est terminé. Bonne journée !", verbatim=True)

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
        self._chiffres_dits(user_text, extracted)
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

    # Marqueurs de correction, cherchés DANS LE TEXTE. Volontairement explicites : pas de
    # « pas » nu, qui abonde dans « je ne peux pas venir ». Ils ne comptent que si une
    # commune est par ailleurs reconnue dans la même phrase — sans quoi il n'y a rien à
    # corriger.
    MARQUEURS_CORRECTION = (
        "non", "pardon", "excusez", "plutot", "en fait", "c est pas", "au lieu",
        "je me suis trompe", "je me suis trompee", "erreur", "je confondais",
        "je confonds", "attendez",
    )

    def _signal_de_correction(self, texte: str, ex: dict | None) -> bool:
        """L'appelant est-il en train de SE CORRIGER dans cette phrase ?

        **Détecté dans le TEXTE, pas confié au LLM.** La première version lisait
        `ex["confirme"] is False` — c'est-à-dire qu'elle confiait une règle produit à un
        jugement subtil du modèle. Haiku ne posait pas `confirme: false` sur « c'est pas
        Créteil, c'est Nogent-sur-Marne », et la correction passait à la trappe deux fois
        sur trois (prérequis du 25/08, persona T10). Le contrôleur décide, le LLM extrait :
        c'est la règle n°1, et elle valait aussi pour ce cas-là.

        Un code postal prononcé reste un signal : cinq chiffres ne sont jamais un homonyme.
        """
        if bool((ex or {}).get("code_postal")):
            return True
        phrase = " " + self._normalise(texte) + " "
        return any(" " + m + " " in phrase or phrase.startswith(" " + m + " ")
                   for m in self.MARQUEURS_CORRECTION)

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
                and not self._signal_de_correction(texte, ex):
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
            # BORNÉE. C'est le troisième compteur de cette famille — `tentatives_tel`
            # borne la demande du numéro, `confirmations_tel` sa confirmation (R32),
            # `tours_creneaux` les propositions — et la commune n'était bornée par rien.
            # Le 26/08, avec un STT qui entendait « Orange » pour « Juvisy-sur-Orge »,
            # l'agent a reposé la même question mot pour mot jusqu'à ce que l'appelant
            # renonce. Une boucle sans borne au téléphone n'est pas une gêne : c'est un
            # appel perdu, et un client convaincu que personne ne l'écoute.
            #
            # Le compteur monte à CHAQUE passage sans code postal. J'avais d'abord écrit
            # « seulement si la question a déjà été posée » — condition toujours vraie, car
            # `_s1` pose la question et lève le drapeau avant qu'on arrive ici. Une
            # mutation l'a montrée sans effet, et du code mort qui a l'air d'une garantie
            # est pire que pas de garantie du tout. Troisième fois dans ce projet.
            #
            # L'appelant garde donc deux chances : la question de `_s1`, puis une relance.
            self.flags["commune_ratees"] = self.flags.get("commune_ratees", 0) + 1
            if self.flags["commune_ratees"] >= 2:
                # On ignore la zone, donc on ne promet aucun RDV : on prend le lead et
                # Julien rappellera. Un lead exploitable vaut infiniment mieux qu'une
                # boucle — et c'est déjà ce qu'on fait quand le numéro n'arrive pas.
                return self._sans_rdv()
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
            # Pas de promotion d'urgence ici : elle serait DU CODE MORT. Cette branche ne
            # s'exécute que si l'intent est DÉJÀ « urgence » (voir la condition ci-dessus),
            # auquel cas il n'y a rien à promouvoir. La promotion vit dans `_merge`, qui
            # voit passer toutes les extractions — y compris une urgence déclarée à un
            # tour ultérieur. Constaté par mutation le 25/08 : l'appel placé ici ne
            # pouvait pas être tué par un test, parce qu'il ne pouvait rien faire.
        self.state = State.S4_IDENTITE
        return self._s4({})

    def _s4(self, ex: dict) -> str:
        if not self.flags.get("identite_demandee") and self.slots["telephone_rappel"] is None:
            self.flags["identite_demandee"] = True
            # C'est ICI que la commune est acquittée, et c'est le seul endroit où le
            # client peut vérifier qu'on l'a compris. Le 26/08, le formuleur y a prononcé
            # « Nogènes-sur-Marne » alors que la résolution avait trouvé Nogent-sur-Marne
            # et que la base le prouve : la seule chose fausse de tout l'appel était la
            # seule que le client ait entendue.
            #
            # Donc VERBATIM, avec le nom tel qu'il est dans NOTRE table. Le formuleur n'a
            # aucune raison d'écrire un nom propre : il ne peut que l'écorcher. Et si la
            # résolution se trompe un jour pour de bon, le client entendra une commune
            # fausse qui vient de nous — donc reconnaissable, donc corrigeable.
            #
            # Même remède que R38 : là où le fond compte, le contrôleur parle lui-même.
            lieu = (f"C'est noté pour {self.slots['commune']}. "
                    if self.slots.get("commune") else "Très bien. ")
            return self._say(f"{lieu}À quel nom, et sur quel numéro "
                             f"{self._prenom} peut vous confirmer le rendez-vous ?",
                             verbatim=True)
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
            digits = _re.sub(r"\D", "", self._dernier_client())
            # Le code postal est retiré des CHIFFRES, pas du texte : depuis qu'il peut
            # être dicté avec un séparateur (R43), la forme normalisée « 94130 » ne se
            # retrouve pas telle quelle dans « je suis au 94 130 », et le retrait par le
            # texte échouait en silence — cinq chiffres de trop, et un numéro parfaitement
            # valide déclaré « incomplet ».
            if ex.get("code_postal"):
                digits = digits.replace(ex["code_postal"], "", 1)
            # Des chiffres, mais pas un numéro exploitable. Deux cas, deux phrases : trop
            # PEU (l'appelant s'est arrêté) et trop (il en a dit un de plus, ou le STT en
            # a inventé). Le second manquait, et c'est celui du 26/08 : douze chiffres
            # tombaient dans la branche « il me faut un numéro », qui réclame à l'appelant
            # quelque chose qu'il venait de donner — de quoi le braquer, et surtout de
            # quoi masquer que c'est la DICTÉE qui n'allait pas.
            if len(digits) >= 5:
                self.flags["tel_incomplets"] = self.flags.get("tel_incomplets", 0) + 1
                if self.flags["tel_incomplets"] >= 3:
                    return self._sans_rdv()
                if len(digits) > 10:
                    return self._say("Je n'ai pas bien noté votre numéro — pouvez-vous "
                                     "me le redonner, chiffre par chiffre ?")
                return self._say("Ce numéro me semble incomplet — pouvez-vous me le "
                                 "redonner en entier, avec les dix chiffres ?")
            self.flags["tentatives_tel"] += 1
            if self.flags["tentatives_tel"] >= 2:  # 2 tentatives max (T11), puis repli propre
                return self._sans_rdv()  # invariant 2 : pas de RDV sans rappel
            return self._say("Il me faut un numéro où vous joindre pour la confirmation — "
                             "sans ça je ne peux pas réserver. Quel est votre numéro ?")
        if not self.slots["tel_confirme"]:
            # correction : un NOUVEAU numéro donné pendant la confirmation remplace l'ancien
            nouveau = self._numero_fr(ex.get("telephone_rappel"))
            if nouveau and nouveau != self.slots["telephone_rappel"]:
                self.slots["telephone_rappel"] = nouveau
                # virgule et non point : un point placé juste après un groupe de
                # chiffres est lu par la synthèse vocale comme une fin d'énoncé, et le
                # « c'est bien ça ? » arrive détaché, comme une phrase sans rapport
                # (entendu le 26/08). Une virgule garde la question dans le même souffle.
                return self._say(f"Je répète votre numéro : {self._tel_espace()}, "
                                 f"c'est bien ça ?", verbatim=True)  # chiffres jamais réécrits
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
                return self._say(f"Je répète votre numéro : {self._tel_espace()}, "
                                 f"c'est bien ça ? Répondez simplement oui ou non.",
                                 verbatim=True)  # chiffres jamais réécrits
        self.state = State.S5_CRENEAU
        return self._s5({})

    def _s5(self, ex: dict) -> str:
        # Les contraintes de disponibilité sont lues EN TÊTE : la branche « rien de plus
        # tôt » comme la reproposition en dépendent toutes les deux.
        # ("que le samedi matin" — bug T03-LLM)
        jours, moment = self._contraintes_dispo()
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
        # plus tôt, on lui proposait plus tard et lundi disparaissait).
        #
        # MAIS une CONTRAINTE nouvelle prime sur ce raccourci. Le 25/08 (T03), l'appelant
        # a dit « je ne suis disponible que le samedi matin, c'est possible d'avoir un
        # créneau samedi ? » — donc PLUS TARD — et s'est entendu répondre « je n'ai rien
        # de plus tôt : le premier créneau est demain entre 08h et 10h ». Deux fautes en
        # une phrase : le mot « plus tôt » à contresens, et le créneau qu'il venait de
        # refuser reproposé. Le raccourci ne vaut que si les contraintes n'ont PAS bougé ;
        # sinon c'est une reproposition qu'il faut faire, pas une fin de non-recevoir.
        contraintes_stables = (self.flags.get("contraintes_proposees")
                               == [sorted(jours) if jours else None, moment])
        if ex.get("veut_plus_tot") and self._proposes and contraintes_stables:
            self.flags["tours_creneaux"] += 1
            if self.flags["tours_creneaux"] <= 2:
                # verbatim : cette phrase énonce une DATE (cf. le bloc de `_s5` plus bas)
                return self._say(
                    f"Je n'ai malheureusement rien de plus tôt : le premier créneau "
                    f"disponible est {self._proposes[0]['label']}. "
                    f"Voulez-vous que je vous le réserve ?", verbatim=True)
        # (re)proposer — max 2 tours (invariant 6)
        if self.flags["tours_creneaux"] >= 2:
            return self._sans_rdv()
        urgent = bool(self.slots["urgence_reelle"]) and self.slots["intent"] == "urgence"
        # 2e tour = créneaux SUIVANTS, jamais les mêmes reproposés.
        #
        # SAUF si les contraintes ont CHANGÉ entre-temps. Le saut sert à ne pas resservir
        # ce que l'appelant vient de refuser ; il n'a aucun sens quand il vient d'ajouter
        # une contrainte, car les créneaux déjà proposés l'ont été sous d'autres règles —
        # il ne les a jamais vus dans ce cadre, donc jamais refusés.
        #
        # Le 25/08 (persona T03) : « je ne suis disponible que le samedi matin », annoncé
        # après deux créneaux de semaine, faisait sauter les samedis 29/08 et 05/09 pour
        # offrir le 12/09. L'appelant refusait, et l'appel se concluait sans RDV. Pire, il
        # s'entendait dire qu'il n'y avait rien le samedi matin — alors que la config
        # ouvre `sam 09:00–13:00`.
        #
        # `tours_creneaux`, lui, continue de compter : l'invariant n°6 (deux tours max)
        # n'est pas touché.
        contraintes = [sorted(jours) if jours else None, moment]
        saut = (0 if self.flags.get("contraintes_proposees") != contraintes
                else 2 * self.flags["tours_creneaux"])
        self.flags["contraintes_proposees"] = contraintes
        self._proposes = self.cal.get_slots(self.slots["prestation"], urgent, n=2,
                                            skip=saut, jours=jours, moment=moment)
        self.flags["tours_creneaux"] += 1
        if not self._proposes:
            return self._sans_rdv()
        if len(self._proposes) == 1:
            offre = f"Je peux vous proposer {self._proposes[0]['label']}. Ça vous irait ?"
        else:
            offre = (f"Je peux vous proposer {self._proposes[0]['label']}, "
                     f"ou {self._proposes[1]['label']}. Lequel vous arrange ?")
        # VERBATIM. `_reserver` portait déjà cette règle — « date et engagement jamais
        # réécrits » — mais elle n'avait pas été étendue à la PROPOSITION, qui est le même
        # acte : énoncer une date. Le 25/08, le formuleur a répondu « je n'ai pas de
        # disponibilité le samedi matin » alors que le contrôleur venait de lui donner
        # samedi 29/08 : il a NIÉ les créneaux qu'on lui passait, et l'appelant a raccroché
        # sans RDV avec une information fausse sur les disponibilités de l'artisan.
        #
        # Aucun garde-fou ne pouvait l'attraper : le mensonge portait sur le FOND, et
        # `check_output` vérifie la forme. La seule défense est de ne pas laisser réécrire.
        #
        # Effet de bord bienvenu pour la voix : un tour verbatim économise l'appel au
        # formuleur — c'est ce qui explique les minima de latence mesurés (0,67 s contre
        # 1,93 s de médiane en Haiku).
        return self._say(offre, verbatim=True)

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
