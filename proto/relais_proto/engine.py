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

from . import actions, communes, temps
from .calendar_stub import JOURS_FR, MOIS_FR, CalendarStub


def _cle_contraintes(c: dict) -> list:
    """Une clé comparable pour savoir si les contraintes ont CHANGÉ (cf. `saut`).

    Les valeurs sont des ensembles : il faut les trier pour que deux lectures de la même
    phrase donnent la même clé.
    """
    return [sorted(c["jours"]) if c["jours"] else None, c["moment"],
            sorted(c["dates"]) if c["dates"] else None,
            sorted(c["jours_exclus"]) if c["jours_exclus"] else None,
            c["moment_exclu"], c["pas_avant"]]


def _re_chiffres():
    """Les suites de chiffres d'un texte, séparateurs d'écriture compris.

    Une SUITE est ce qu'on prononce d'un trait : « 0 6. 0 6 30. 30 11 » en est une seule.
    La virgule n'y figure pas — elle sépare des choses, elle ne les compose pas (R55).
    Partagée par la lecture d'un numéro (R64) et par la détection d'une troncature (R55) :
    deux définitions divergeraient, et c'est précisément sur cette découpe que les deux
    raisonnent.
    """
    import re as _re
    return _re.compile(r"\d[\d\s.\-]*\d|\d")
from .guards import check_output, safe_fallback
from .states import EMPTY_SLOTS, State, URGENT_PRESTATIONS


class Conversation:
    def __init__(self, config: dict, llm, calendar: CalendarStub | None = None,
                 numero_appelant: str | None = None):
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
        # LE NUMÉRO D'OÙ L'ON APPELLE (R81). Idée de Geoffrey : le proposer plutôt que le
        # faire dicter. La dictée d'un numéro à dix chiffres au téléphone a produit à elle
        # seule R55, R58, R62, R75 et R78, et coûté deux appels réels ; un numéro que la
        # plateforme nous donne déjà supprime tout ce chemin pour presque tout le monde.
        #
        # VALIDÉ comme n'importe quel numéro : un appelant masqué, un numéro étranger ou
        # tronqué ne doit pas être prononcé — on retombe alors sur la demande normale.
        #
        # Il est rangé dans SON slot, et recopié dans `telephone_rappel` pour que la
        # confirmation existante s'applique telle quelle. `tel_confirme` reste faux : la
        # règle n°5 ne bouge pas, on ne réserve rien sur un numéro que l'appelant n'a pas
        # validé à voix haute. C'est une PROPOSITION, pas un acquis.
        propose = self._numero_fr(self._depuis_e164(numero_appelant))
        if propose:
            self.slots["numero_appelant"] = propose
            self.slots["telephone_rappel"] = propose

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
            "propositions": [self._dit(s) for s in self._proposes],
            # L'ÉTAT, parce que le menu d'actions en dépend (`actions.py`). Sans lui, le
            # modèle recevrait un choix d'actions qui ne correspond pas au moment de
            # l'appel — et le contrôleur refuserait tout, donc ferait répéter sans fin.
            "etat": self.state.name,
            # LE JOUR COURANT (R73). Il manquait, et personne ne s'en apercevait : les
            # propositions arrivent en libellés auto-descriptifs (« demain entre 8 heures
            # et 10 heures ») et les jours relatifs sont résolus par le contrôleur. Mais
            # sans lui, « pas le vendredi » est ininterprétable — le modèle ne peut pas
            # savoir si « demain » EST un vendredi — et « la semaine prochaine » ou
            # « avant vendredi » le resteront tant qu'il l'ignore.
            #
            # RÈGLE N°7 : heure de PENDULE, dérivée de l'horloge de l'appel. Jamais
            # `datetime.now()` (interdit ici), jamais l'instant UTC brut : un appel passé
            # à 23 h 30 UTC un lundi est déjà mardi à Paris, et un modèle qui croirait
            # lundi placerait tous les jours relatifs un cran trop loin.
            "aujourdhui": self._aujourdhui(),
        }

    def _aujourdhui(self) -> str:
        """« mardi 1 septembre 2026, 17 h » — ou rien du tout sans horloge.

        Rendu vide plutôt que deviné quand aucun calendrier n'est injecté : `_ctx` est
        appelé à chaque tour, et une date inventée serait pire que pas de date — le modèle
        la croirait.
        """
        cal = getattr(self, "cal", None)
        if cal is None:
            return ""
        local = temps.en_local(cal.now, self.cfg)
        return (f"{JOURS_FR[local.weekday()]} {local.day} {MOIS_FR[local.month - 1]} "
                f"{local.year}, {local.hour} h")

    def _dernier_client(self) -> str:
        return next((t for who, t in reversed(self.transcript) if who == "client"), "")

    @staticmethod
    def _dit(creneau: dict) -> str:
        """Le créneau tel qu'on le PRONONCE (R66). Le libellé écrit reste dans les SMS et
        les pages ; la synthèse vocale, elle, lit « 29/08 » comme « 29 barre oblique 08 ».

        Repli sur le libellé écrit : un état sérialisé par une version antérieure ne porte
        pas encore le jumeau parlé, et un appel en cours ne doit pas devenir muet pour ça.
        """
        return creneau.get("label_parle") or creneau["label"]

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
        # `formule` : le texte vient-il du modèle ? Si oui, il n'a pas le droit d'ÉNONCER
        # un fait — chiffre, jour, lieu (R63). L'INSTRUCTION du contrôleur, elle, en
        # contient légitimement : c'est elle qui les énonce.
        violations = check_output(texte, self.cfg, en_conversation=en_conv,
                                 formule=not verbatim, slots=self.slots)
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
    def _numero_suspect(texte: str, numero: str, cp: str | None = None) -> bool:
        # (la découpe des suites est partagée avec `_chiffres_dits` : cf. `_re_chiffres`)
        """Vrai si `numero` ne correspond pas à ce qui a été dit dans `texte` — TRONQUÉ
        (R55) ou FABRIQUÉ (R75).

        ⚠️ CE CONTRÔLE EST LA SEULE PROTECTION, ET C'EST MESURÉ. Le 02/09, sur le banc
        d'extraction (`run_extract_eval.py`, cas `tel/*`), Haiku a violé sa consigne de
        façon DÉTERMINISTE : huit chiffres dictés rendus en dix (« 0 6. 30. 30 11 » →
        `0630301100`), douze rendus en dix. Un renforcement du prompt — consigne de
        COMPTER les chiffres, trois exemples chiffrés — n'a rien changé : mêmes deux
        échecs, au chiffre près. Le prompt a donc été remis dans sa forme courte, pour ne
        pas payer des tokens contre une illusion de garantie.
        Autrement dit : ce n'est pas une ceinture en plus des bretelles du prompt. C'est
        la ceinture, et il n'y a pas de bretelles.

        La limite de tout contrôle de FORME (`_numero_fr`) : il ne dit rien de la
        correspondance entre ce qui est extrait et ce qui a été prononcé. Le 26/08, l'éval
        réelle a montré le modèle rendre « 0610154768 » là où l'appelant avait dicté douze
        chiffres — une forme irréprochable, et deux chiffres perdus. Trois passages sur
        trois, et exactement le défaut de l'appel vocal du matin.

        La signature d'une troncature est nette : le numéro extrait est un **préfixe
        strict** d'une suite de chiffres présente dans la phrase. Un numéro donné
        normalement est ÉGAL à sa suite, pas un morceau de suite.

        Une suite s'interrompt sur autre chose qu'un chiffre, une espace, un point ou un
        tiret — donc « j'ai 2 enfants, mon numéro est 06 12 34 56 78 » en contient deux,
        et la seconde est le numéro entier. La virgule coupe volontairement : elle sépare
        des choses, elle ne les compose pas.

        Exception : un code postal prononcé juste après le numéro allonge la suite sans
        rien tronquer. Les chiffres en excès sont alors exactement le code postal.
        """
        for suite in _re_chiffres().findall(texte or ""):
            chiffres = "".join(c for c in suite if c.isdigit())
            if len(chiffres) > len(numero) and chiffres.startswith(numero):
                if cp and chiffres[len(numero):] == cp:
                    continue
                return True
        # ---- et le cas SYMÉTRIQUE : le numéro est plus long que ce qui a été dit ----
        #
        # Le 02/09, l'appelant a dicté HUIT chiffres — « 0 6. 30. 30 11 » — et le modèle a
        # rendu « 0630301100 ». Il a complété, ce que son prompt lui interdit en toutes
        # lettres. La relecture et le « non » de l'appelant ont rattrapé (règle n°5), mais
        # dépendre de l'oreille du client pour écarter une donnée fabriquée n'est pas un
        # contrôle.
        #
        # Une troncature donne un numéro qui n'aboutit pas ; une FABRICATION peut donner
        # le numéro de quelqu'un d'autre. C'est le plus grave des deux, et il manquait.
        #
        # La règle : les chiffres du numéro doivent se retrouver, DANS L'ORDRE ET D'AFFILÉE,
        # parmi ceux qui ont été prononcés. Tous les chiffres de la phrase, sans tenir
        # compte du découpage en suites — et c'est délibéré, contrairement au contrôle de
        # troncature juste au-dessus qui, lui, raisonne suite par suite.
        #
        # Deux raisons. La dictée par morceaux est la réponse NORMALE à notre propre
        # consigne « chiffre par chiffre » (R58), et une virgule au milieu (« 06 30 30,
        # euh, 11 11 ») produirait deux suites pour un seul numéro : vérifier suite par
        # suite refuserait un numéro parfaitement dicté. Et le chiffre parasite (« j'ai
        # 2 enfants, mon numéro est… ») passe quand même, puisqu'il ALLONGE la
        # concaténation au lieu de l'amputer.
        #
        # Une première version découpait en suites avant de les reconcaténer : deux
        # mutations y ont survécu, parce que reconcaténer annule le découpage. Du code
        # qui a l'air de raffiner sans rien changer est pire que le code simple.
        dits = "".join(c for c in (texte or "") if c.isdigit())
        return numero not in dits

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

    def _phrase_confirme_tel(self, relance: bool = False) -> str:
        """La demande de confirmation du numéro, selon son ORIGINE.

        « Je répète votre numéro » est faux quand l'appelant ne l'a jamais dit : il vient
        de son identifiant d'appel (R81). Le lui présenter comme une répétition sonne
        comme si on avait mal écouté — et c'est le tour le plus important de l'appel,
        celui qui décide si on peut le rappeler.

        Le fond ne change pas : dans les deux cas on énonce les chiffres et on attend un
        oui. Seule la façon de les introduire diffère, et elle doit être exacte.
        """
        suffixe = " Répondez simplement oui ou non." if relance else ""
        if self.slots.get("numero_appelant") \
                and self.slots["telephone_rappel"] == self.slots["numero_appelant"]:
            return (f"Je vous rappelle sur le {self._tel_espace()}, celui d'où vous "
                    f"appelez — c'est bien le bon ?{suffixe}")
        # virgule et non point : cf. la note de la branche de correction
        return (f"Je répète votre numéro : {self._tel_espace()}, "
                f"c'est bien ça ?{suffixe}")

    @staticmethod
    def _depuis_e164(valeur) -> str | None:
        """« +33630301111 » → « 0630301111 ». Tout le reste passe INCHANGÉ.

        Uniquement pour l'identifiant d'appel, qui arrive en E.164 depuis la plateforme.
        Volontairement PAS appliqué à ce que l'appelant dicte : la sévérité de `_numero_fr`
        sur la forme nationale est une fonctionnalité, et R55/R75 comparent les chiffres
        extraits à ceux prononcés — élargir la conversion là-bas rendrait ces contrôles
        plus flous sans rien gagner (personne ne dicte son indicatif pays au téléphone).
        Un indicatif étranger reste donc tel quel, et `_numero_fr` le refusera : c'est le
        comportement voulu, on ne propose pas de rappeler un numéro qu'on ne sait pas lire.
        """
        chiffres = "".join(c for c in str(valeur or "") if c.isdigit())
        if chiffres.startswith("33") and len(chiffres) == 11:
            return "0" + chiffres[2:]
        return valeur

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
        # Le numéro RENDU par l'extracteur est confronté à ce qui a été dit : une
        # troncature produit une forme valide, que `_numero_fr` ne peut pas voir (R55).
        # On l'écarte plutôt que de la corriger — deviner les chiffres manquants serait
        # exactement la faute qu'on reproche au modèle.
        rendu = self._numero_fr(extracted.get("telephone_rappel"))
        if rendu and self._numero_suspect(texte, rendu, extracted.get("code_postal")):
            extracted.pop("telephone_rappel", None)
        if not extracted.get("telephone_rappel"):
            # LES CHIFFRES ÉCRITS, quelle que soit leur découpe. La reconnaissance d'un
            # numéro reposait sur une expression régulière qui présuppose des PAIRES
            # (`0\d` puis quatre groupes de deux). « 0 6 0 6 3 0 3 0 1 1 » n'en a pas ;
            # « 0 6. 0 6 30. 30 11 » non plus.
            #
            # Or c'est exactement ce qu'on obtient quand on demande à quelqu'un d'épeler —
            # donc la réponse à NOTRE PROPRE consigne (« dites-moi les dix chiffres d'un
            # seul coup ») était la seule qu'on ne savait pas lire. Le 26/08, un appelant
            # a dicté dix chiffres valides quatre fois de suite, et s'est entendu répondre
            # « ce numéro me semble incomplet ».
            #
            # Même leçon que R47 pour le code postal : **le découpage appartient à celui
            # qui parle.** Le contrôleur lit les chiffres, pas leur mise en forme — et
            # `_numero_fr` reste le juge (R42), sur des suites MAXIMALES, donc sans jamais
            # tronquer (R55).
            # Le PREMIER numéro valide gagne — comme `re.search` dans l'extracteur, dont
            # ce chemin est le filet. Deux numéros valides dans un même tour sont rares, et
            # je n'ai AUCUNE observation pour trancher entre le premier et le dernier : une
            # reprise dans la même phrase (« … ah non pardon, le … ») passe de toute façon
            # par la branche de confirmation de `_s4`, qui l'entend comme un refus.
            #
            # Le test épingle donc le comportement ACTUEL, pas une règle qu'on aurait
            # déduite. Le jour où un appel réel montrera l'autre cas, il faudra le changer
            # exprès — et le test le dira.
            for suite in _re_chiffres().findall(texte or ""):
                candidat = self._numero_fr("".join(c for c in suite if c.isdigit()))
                if candidat:
                    extracted["telephone_rappel"] = candidat
                    break
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

    def _commune_coherente(self, nom, cp) -> str | None:
        """Le nom canonique de la commune si nos tables la connaissent ET si son code
        postal correspond à `cp`. Sinon None.

        `_commune_connue` (R49) vérifiait l'existence, pas la CORRESPONDANCE. Le 26/08, la
        deuxième éval réelle a produit `commune: Orsay, code_postal: 91260` — Orsay est
        91400 — et l'agent a relu « vous êtes bien à Deuil La Barre ? », qui est 95170. Un
        autre département. Chaque valeur était individuellement valide : R35 exige la
        PAIRE, R49 exige une commune connue, et personne ne vérifiait qu'elles vont
        ensemble.

        Le code postal décide de la zone : c'est donc lui qui fait foi. Une commune qui ne
        lui correspond pas est écartée, et on dit « votre secteur » ou on relit les
        chiffres — ce qui est toujours préférable à nommer une ville au hasard.
        """
        canonique = self._commune_connue(nom)
        # `not cp` est un RACCOURCI, pas une garantie : sans lui la boucle ci-dessous
        # rendrait None de toute facon (`None in cps` est faux). Il evite seulement de
        # balayer mille cinq cents entrees a chaque tour. Une mutation l'a montre sans
        # effet observable, et c'est normal — a distinguer du code mort qui, lui, avait
        # l'air de proteger quelque chose.
        if canonique is None or not cp:
            return None
        table = {**self.cfg["zone"].get("communes", {}), **self._communes_idf()}
        cible = self._normalise(str(nom or ""))
        for connu, v in table.items():
            if self._normalise(connu) == cible:
                cps = v if isinstance(v, list) else [v]
                if cp in cps:
                    return canonique
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
                # connue de nos tables (R49) ET cohérente avec le code postal (R57) :
                # une commune qui ne correspond pas au code postal donné est écartée,
                # c'est le code postal qui décide de la zone.
                v = self._commune_coherente(v, extracted.get("code_postal"))
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
            # Ce que l'appelant dit APRÈS la clôture est conservé, même si le contrôleur
            # n'en fait rien. Auparavant on rendait la phrase de fin avant même de
            # l'enregistrer : la correction ne figurait donc dans AUCUN transcript, et
            # Julien ne pouvait pas voir que son client avait insisté. C'était le seul
            # défaut du 26/08 silencieux des deux côtés — ni entendu, ni tracé.
            #
            # On ne relance pas la conversation pour autant : dans le chemin API, le lead
            # est déjà persisté à ce stade et `cloturer_appel` refuse un second passage.
            # Rouvrir serait un autre objet. Ici, on garde la trace — c'est ce qui permet
            # un rappel humain, et ça ne coûte rien.
            if user_text.strip():
                self.transcript.append(("client", user_text.strip()))
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
            # UNE seule question (R53), et le garde-fou a trouvé celle-ci chez nous
            # avant de trouver quoi que ce soit chez le formuleur. Les exemples sont une
            # liste, pas une seconde question : un tiret les rattache à la première.
            # Deux points d'interrogation, au téléphone, font répondre à l'une des deux.
            return self._say("Pouvez-vous me préciser ce qui vous arrive — une fuite, "
                             "un souci de chauffage, autre chose ?")
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
        # VERBATIM. Une question factuelle de six mots n'a rien à gagner à être
        # reformulée, et beaucoup à perdre : celle-ci a été mutilée trois fois en
        # production — « Pouvez-vous ? Oui, Bonjour, … », les re-salutations, et un
        # quiz sur le Vaucluse (« Vous êtes sur Orange. C'est dans le Vaucluse, non ? »)
        # qui nommait au passage un lieu que nos tables ne connaissent pas.
        self.flags["commune_demandee"] = True
        # DÉGELÉE le 26/08 : elle était verbatim (R56) uniquement pour empêcher le
        # formuleur d'y glisser un nom de lieu (« Vous êtes sur Orange, dans le
        # Vaucluse ? »). Le garde-fou des faits l'interdit désormais directement
        # (R63), donc la question peut être TOURNÉE librement. C'est une question,
        # pas une affirmation : rien à énoncer, tout à demander.
        # champ visé → verbatim (R76) : le formuleur a posé une AUTRE question le 02/09
        return self._say("Vous êtes sur quelle commune ?", verbatim=True)

    @staticmethod
    def _normalise(texte: str) -> str:
        """Délègue à `communes.normaliser` (extrait le 26/08, cf. `_communes_idf`)."""
        return communes.normaliser(texte)

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
    # La source de vérité est dans `communes.py` (extrait le 26/08) ; l'attribut reste
    # pour les tests qui le vérifient (R30) et pour la lisibilité du contrôleur.
    ALIAS_AMBIGUS = communes.ALIAS_AMBIGUS

    @classmethod
    def _communes_idf(cls) -> dict:
        """Délègue à `communes.py`, extrait le 26/08 : les garde-fous en ont besoin aussi,
        pour vérifier qu'une réplique formulée ne nomme pas un lieu (R63). `guards` ne peut
        pas importer `engine`, d'où le module tiers."""
        return communes.table_idf()

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

    # « demain » est un jour, dit autrement — et c'est la façon la PLUS courante de le
    # dire au téléphone, bien avant « mardi ». Le plus long d'abord : « après-demain »
    # contient « demain », et un appelant qui dit après-demain ne doit pas obtenir demain.
    JOURS_RELATIFS = (("apres demain", 2), ("demain", 1), ("aujourd hui", 0))

    def _jour_dit(self, texte: str) -> str | None:
        """Le fragment de `texte` qui NOMME un jour, ou None.

        Lu par le contrôleur, pas par l'extracteur (règle n°1, et même leçon que R47 et
        R64). Le 27/08, un appelant a répondu « Aujourd'hui » à une proposition de
        créneaux : le slot `disponibilites` est resté vide, `_contraintes_dispo` n'avait
        rien à lire, et le contrôleur a pris ce tour pour « aucun des deux ». Il a donc
        AVANCÉ dans le calendrier — samedi et lundi, deux jours plus loin que ce qu'on
        venait de proposer. **Préciser sa préférence donnait l'inverse de ce qu'on
        demande.**

        Rendu tel quel : c'est `_contraintes_dispo` qui l'interprète, et lui seul sait
        résoudre « demain » en heure de pendule (R61).
        """
        d = self._normalise(texte or "")
        mots = [m for m, _ in self.JOURS_RELATIFS] + list(self.JOURS_SEMAINE)
        return texte if any(f" {m} " in f" {d} " for m in mots) else None

    # Ce qui NIE ce qui suit. « pas », « sauf », « jamais »… Une négation ne se devine pas
    # d'un mot isolé : c'est ce qui PRÉCÈDE le jour qui décide.
    NEGATIONS = ("pas", "sauf", "jamais", "hormis", "excepte", "impossible", "aucun")
    # « pas AVANT jeudi » n'est ni une exclusion ni une préférence : c'est un plancher.
    PLANCHERS = ("avant", "des", "a partir de", "apres")

    def _contraintes_dispo(self) -> dict:
        """Contraintes de créneaux tirées des disponibilités exprimées par l'appelant.

        Trouvé le 26/08 sur un appel réel : l'appelant demandait un rendez-vous
        « n'importe quand dans la journée de DEMAIN » dès sa première phrase, et l'agent
        lui proposait « aujourd'hui entre 17 h et 19 h ». Il a fallu qu'il réponde « J'ai
        dit demain » pour obtenir ce qu'il avait demandé d'emblée. Seuls les NOMS de jours
        étaient reconnus.

        Règle n°7 : un jour relatif se résout contre l'horloge de l'appel, en heure de
        PENDULE. Un appel passé à 23 h 30 UTC un lundi est encore lundi à Paris, et son
        lendemain est mardi — pas mercredi.
        """
        import datetime as _dt

        d = self._normalise(self.slots.get("disponibilites") or "")
        mots = d.split()

        def _nie(cible: str) -> tuple[bool, bool]:
            """(nié, plancher) : ce qui précède `cible` dans la phrase.

            Une négation devenait une PRÉFÉRENCE pour ce qu'on refuse — « pas le samedi »
            proposait samedi (R68). On regarde donc les trois mots qui précèdent, ce qui
            couvre « pas le samedi », « surtout pas le samedi », « je ne peux pas le
            samedi ». Au-delà, la phrase parle d'autre chose.
            """
            debut = mots.index(cible.split()[0]) if cible.split()[0] in mots else -1
            if debut < 0:
                return False, False
            avant = mots[max(0, debut - 3):debut]
            if not any(n in avant for n in self.NEGATIONS):
                return False, False
            # « pas AVANT jeudi » : la négation porte sur l'antériorité, pas sur le jour
            return True, any(p in " ".join(avant) for p in self.PLANCHERS)

        jours, exclus, plancher = set(), set(), None
        for nom, n in self.JOURS_SEMAINE.items():
            if nom not in d:
                continue
            nie, est_plancher = _nie(nom)
            if est_plancher:
                plancher = n
            elif nie:
                exclus.add(n)
            else:
                jours.add(n)

        dates = set()
        cal = getattr(self, "cal", None)
        if cal is not None:
            local = temps.en_local(cal.now, self.cfg)
            for mot, delta in self.JOURS_RELATIFS:
                if mot not in d:
                    continue
                nie, est_plancher = _nie(mot)
                jour = local + _dt.timedelta(days=delta)
                if est_plancher:
                    plancher = jour.weekday()
                elif nie:
                    exclus.add(jour.weekday())
                else:
                    jours.add(jour.weekday())
                    # ...ET la date : un jour relatif désigne UN jour, pas tous les jeudis.
                    # Sans elle, « aujourd'hui » saturé proposait jeudi prochain (R67).
                    dates.add(jour.date().isoformat())
                break

        moment = moment_exclu = None
        for cle, mots_cles in (("matin", ("matin",)),
                               ("apres_midi", ("apres midi", "aprem"))):
            for mc in mots_cles:
                if mc not in d:
                    continue
                nie, _ = _nie(mc)
                if nie:
                    moment_exclu = cle
                else:
                    moment = cle
                break
        return {"jours": jours or None, "moment": moment, "dates": dates or None,
                "jours_exclus": exclus or None, "moment_exclu": moment_exclu,
                "pas_avant": plancher}

    def _zone_de(self, cp: str | None) -> str:
        zone = self.cfg["zone"]
        if cp in zone["codes_postaux"]:
            return "en_zone"
        if cp in zone["codes_postaux_limitrophes"]:
            return "limitrophe"
        return "hors_zone"

    def _s2(self, ex: dict) -> str:
        # Une confirmation de secteur est en attente (cf. plus bas). Le secteur RESTE
        # dans les slots pendant ce temps : il était vidé, et sept tests l'ont relevé d'un
        # coup en attendant de l'y trouver. Ils avaient raison — un état où l'on a posé une
        # question SUR un code postal sans plus l'avoir en mémoire est incohérent, et si
        # l'appelant raccroche pendant la relecture, le lead ne dit plus rien du tout.
        #
        # Ce qui rendait le vidage nécessaire — relire la réponse sans entrave — est
        # assuré autrement : `_resoudre_commune` relit dès qu'il y a signal de correction,
        # et un code postal corrigé passe par `_merge` (`code_postal` est réécrivable tant
        # qu'aucun créneau n'est bloqué).
        candidat = self.flags.get("commune_a_confirmer")
        if candidat:
            # un secteur DIFFÉRENT du candidat : l'appelant s'est corrigé, on repart dessus
            if self.slots["code_postal"] not in (None, candidat[1]):
                self.flags["commune_a_confirmer"] = None
            elif ex.get("confirme") is True:
                self.flags["commune_a_confirmer"] = None
                self.slots["commune"], self.slots["code_postal"] = candidat
                self.flags["zone"] = self._zone_de(candidat[1])
                return self._hors_zone()
            else:                                          # « non », ou rien d'exploitable
                self.flags["commune_a_confirmer"] = None
                self.flags["commune_demandee"] = True
                # dégelée, cf. l'autre occurrence (R63)
                return self._say("Vous êtes sur quelle commune ?", verbatim=True)

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
            if self.flags["commune_ratees"] >= 3:
                # On ignore la zone, donc on ne promet aucun RDV : on prend le lead et
                # Julien rappellera. Un lead exploitable vaut infiniment mieux qu'une
                # boucle — et c'est déjà ce qu'on fait quand le numéro n'arrive pas.
                return self._sans_rdv()
            self.flags["commune_demandee"] = True
            # La SECONDE relance ne répète pas la première : elle demande les cinq
            # chiffres. C'est la leçon de R43, restée jusqu'ici au journal — le code
            # postal a sauvé un appel réel que le nom de commune avait perdu deux fois, le
            # STT entendant « je visite sur Orange » pour « Juvisy-sur-Orge ». Cinq
            # chiffres résistent à la transcription bien mieux qu'un nom propre.
            #
            # C'est aussi ce qui justifie la troisième chance : répéter deux fois la même
            # question et abandonner n'est pas une conversation. Poser une question
            # DIFFÉRENTE, si. La borne reste — elle passe de deux tentatives à trois.
            if self.flags["commune_ratees"] >= 2:
                # dégelée (R63) — « cinq » est un mot, pas un chiffre énoncé
                return self._say("Je n'arrive pas à situer votre commune. Pouvez-vous "
                                 "me donner votre code postal, les cinq chiffres ?",
                                 verbatim=True)
            # R63 l'avait dégelée (une question sans fait revenait au formuleur) ;
            # R76 la regèle, pour la raison inverse : elle VISE UN CHAMP.
            return self._say("J'ai besoin de votre commune ou code postal pour vérifier "
                             "qu'on intervient chez vous — vous êtes où ?",
                             verbatim=True)
        self.flags["zone"] = self._zone_de(cp)
        if self.flags["zone"] == "hors_zone":
            # NE PAS raccrocher sur une commune glanée au passage. C'est la même règle que
            # « pas de RDV sans téléphone confirmé » : une décision terminale et coûteuse
            # ne se prend pas sur une donnée que personne n'a vérifiée. Le 25/08, « il
            # faudrait que quelqu'un vienne » a coûté un lead de fuite en cours.
            # Une commune DEMANDÉE, elle, tranche immédiatement — pas de question de trop.
            # La règle valait pour la commune GLANÉE au passage, et exemptait la
            # donnée DEMANDÉE — en supposant que demander suffit à la fiabiliser. Les six
            # appels vocaux du 26/08 cassent cette hypothèse : « Zivier-sur-Orge » pour
            # Juvisy, « 91/260 » illisible trois fois, « 160 » pour un code postal. Un
            # secteur demandé n'est pas un secteur vérifié.
            #
            # On relit donc AVANT de refuser, dans tous les cas. Coût : un tour de plus
            # sur chaque appel hors zone. Bénéfice : l'appelant mal transcrit a un moyen
            # de revenir — et il n'en avait AUCUN, la clôture étant sourde.
            #
            # Deux appels sur six ont essayé de se corriger après le refus. Aucun n'a été
            # entendu ; les deux étaient réellement hors zone, donc on a eu raison par
            # accident.
            if not self.flags.get("secteur_relu"):
                self.flags["secteur_relu"] = True
                self.flags["commune_a_confirmer"] = (self.slots["commune"], cp)
                self.flags["commune_incidente"] = False
                nom = self.slots["commune"]
                # Ici se trouvait `self.flags["zone"] = None`, hérité du temps où les
                # slots étaient vidés. Une mutation a montré qu'il n'avait plus AUCUN effet
                # observable : une correction vers un autre secteur hors zone est refusée
                # une seule fois de toute façon — soit par la revalidation de `process`,
                # soit par ce bloc-ci, jamais deux. Retiré : quatrième fois dans ce projet
                # qu'une mutation survivante révèle du code mort, et du code mort qui a
                # l'air d'une garantie est pire que pas de garantie du tout.
                # Nommer la commune quand notre table la connaît (R49), sinon relire les
                # CHIFFRES — groupés 2+3 comme on les prononce, et suivis d'une virgule
                # et non d'un point (R46 : un point après des chiffres est lu comme une
                # fin d'énoncé par la synthèse vocale).
                question = (f"Juste pour être sûr — vous êtes bien à {nom} ?" if nom
                            # VIRGULE entre les deux groupes, pas une espace : la
                            # synthèse vocale joint « 91 260 » en « quatre-vingt-onze
                            # MILLE deux cent soixante » (entendu le 26/08). Un code
                            # postal francais est DEUX nombres — le departement, puis le
                            # reste — et c'est ainsi qu'on le prononce. R58.
                            else f"J'ai noté le {cp[:2]}, {cp[2:]} — c'est bien ça ?")
                return self._say(question, verbatim=True)  # chiffres jamais réécrits
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
        # On pose la question d'identité aussi quand le numéro vient de l'identifiant
        # d'appel : il faut toujours le NOM (il part dans le SMS et dans le lead), mais
        # plus le numéro. Demander « sur quel numéro ? » à quelqu'un dont on a le numéro
        # affiché à l'écran est le genre de détail qui fait sonner faux tout le reste.
        if not self.flags.get("identite_demandee") \
                and (self.slots["telephone_rappel"] is None
                     or self.slots["telephone_rappel"] == self.slots["numero_appelant"]):
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
            # ACQUITTER LA LOCALISATION, même quand la commune n'a pas pu être
            # résolue (R82). Le 01 et 02/09, le STT a rendu « Nos gens sur Marne » puis
            # « Naugeon-sur-Marne » : c'est le CODE POSTAL qui a validé la zone, et
            # l'appelant n'a rien entendu sur l'endroit où l'on croyait intervenir. Or
            # c'est le seul moment où il peut nous corriger — la leçon de R56, écrite
            # pour la commune et jamais appliquée au code postal.
            #
            # Groupé 2+3 comme il se dicte (R43) : collé, la synthèse vocale le lirait
            # comme un nombre (« quatre-vingt-quatorze mille cent trente »).
            if self.slots.get("commune"):
                lieu = f"C'est noté pour {self.slots['commune']}. "
            elif self.slots.get("code_postal"):
                cp = self.slots["code_postal"]
                lieu = f"C'est noté, le {cp[:2]} {cp[2:]}. "
            else:
                lieu = "Très bien. "
            if self.slots.get("numero_appelant"):
                return self._say(f"{lieu}À quel nom {self._prenom} peut-il noter le "
                                 f"rendez-vous ?", verbatim=True)
            return self._say(f"{lieu}À quel nom, et sur quel numéro "
                             f"{self._prenom} peut vous confirmer le rendez-vous ?",
                             verbatim=True)
        # UN NUMÉRO VALIDE EFFACE L'ARDOISE (R78). Le 02/09, l'appelant a dicté huit
        # chiffres deux fois, puis DIX — captés et relus —, puis s'est corrigé après la
        # relecture. Sa correction est tombée sur un compteur déjà à deux, et l'appel a
        # été perdu au tour suivant. **Le filet de sécurité punissait celui qui s'en
        # sert** : la relecture existe pour qu'il corrige (règle n°5).
        #
        # Les deux échecs étaient PÉRIMÉS : entre-temps un numéro valide avait été capté,
        # donc on sait qu'il sait dicter des chiffres. Le budget borne quelqu'un qui n'y
        # ARRIVE PAS, pas quelqu'un qui se reprend.
        #
        # Même raisonnement que `confirmations_tel` trois branches plus bas — écrit là
        # depuis T09 et jamais appliqué au compteur voisin. Mais PAS la même forme, et la
        # différence vaut d'être dite : `confirmations_tel` a besoin d'un marqueur
        # (`tel_repete_pour`) parce qu'il est lu TANT QUE le numéro est là, donc le
        # remettre à zéro à chaque tour l'annulerait. Celui-ci n'est lu que dans la
        # branche « numéro ABSENT » : une remise à zéro répétée n'a aucun effet, et le
        # marqueur que j'avais ajouté par symétrie était du CODE MORT — une mutation y a
        # survécu. Septième fois dans ce projet, et toujours la même leçon.
        if self.slots["telephone_rappel"]:
            self.flags["tel_incomplets"] = 0

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
            # Des chiffres, mais pas un numéro exploitable. Deux cas pour la PREMIÈRE
            # relance : trop PEU (l'appelant s'est arrêté) et trop (il en a dit un de
            # plus, ou le STT en a inventé). Le second manquait, et c'est celui du 26/08 :
            # douze chiffres tombaient dans la branche « il me faut un numéro », qui
            # réclame à l'appelant quelque chose qu'il venait de donner.
            #
            # DEUX chiffres suffisent à compter comme une tentative. Le seuil était à cinq,
            # et « 0 6. 30 » — un appelant qui dicte par morceaux — tombait donc dans la
            # branche de celui qui n'a RIEN donné, bornée à deux tours. On le renvoyait au
            # repli en croyant qu'il se dérobait, alors qu'il était en train de répondre.
            if len(digits) >= 2:
                self.flags["tel_incomplets"] = self.flags.get("tel_incomplets", 0) + 1
                if self.flags["tel_incomplets"] >= 3:
                    return self._sans_rdv()
                # LA RELANCE VARIE, et la seconde reconnaît qu'on a déjà demandé.
                #
                # Trois fois la même phrase, mot pour mot, à quelqu'un qui coopère : c'est
                # ce qu'a entendu l'appelant du 26/08, et ça sonne préenregistré. Ce n'est
                # pas un défaut du modèle — ces phrases sont verbatim (R57), le formuleur
                # n'est pas appelé. **Le caractère « robot » est le prix cumulé des
                # verbatim**, chacun justifié par un défaut réel.
                #
                # La réponse n'est pas de rendre la main au formuleur — il inventerait à
                # nouveau des chiffres — mais de donner au contrôleur PLUSIEURS phrases au
                # lieu d'une. Ce sont les « phrases-tampons pré-approuvées » de
                # l'arbitrage voix du 25/08, enfin écrites.
                if self.flags["tel_incomplets"] >= 2:
                    # DÉGELÉE (R63). C'est la relance qui sonnait le plus robot, et
                    # elle n'a aucun fait à énoncer : le formuleur peut la tourner comme
                    # il veut, il ne peut plus y mettre de chiffres.
                    return self._say("Excusez-moi, je n'y arrive pas. Dites-moi les "
                                     "dix chiffres d'un seul coup, sans pause — je vous "
                                     "écoute.", verbatim=True)
                if len(digits) > 10:
                    # VERBATIM. Le formuleur en a fait une RELECTURE des douze chiffres
                    # qu'on venait de refuser (« 0-6-1-0-1-5-4-7-6-8-7-9. C'est bien
                    # ça ? »), l'appelant a dit oui, et rien n'a été enregistré : il a
                    # fait confirmer un numéro que le contrôleur avait rejeté.
                    # DÉGELÉE (R63) : elle était figée pour empêcher le formuleur d'en
                    # faire une relecture des chiffres refusés. Le garde-fou des faits
                    # l'interdit maintenant, et la phrase redevient une vraie question.
                    return self._say("Je n'ai pas bien noté votre numéro — pouvez-vous "
                                     "me le redonner, chiffre par chiffre ?",
                                     verbatim=True)
                # dégelée par R63, regelée par R76 : elle vise un champ
                return self._say("Ce numéro me semble incomplet — pouvez-vous me le "
                                 "redonner en entier, avec les dix chiffres ?",
                                 verbatim=True)
            self.flags["tentatives_tel"] += 1
            if self.flags["tentatives_tel"] >= 2:  # 2 tentatives max (T11), puis repli propre
                return self._sans_rdv()  # invariant 2 : pas de RDV sans rappel
            # dégelée (R63)
            return self._say("Il me faut un numéro où vous joindre pour la "
                             "confirmation — sans ça je ne peux pas réserver. Quel est "
                             "votre numéro ?", verbatim=True)
        if not self.slots["tel_confirme"]:
            # correction : un NOUVEAU numéro donné pendant la confirmation remplace l'ancien
            # `_numero_fr` reste, lui : une mutation de R42 l'avait montré indispensable.
            # J'y avais AUSSI ajouté la confrontation au texte dit (R55) — inutile, et une
            # mutation l'a montrée sans effet : `_chiffres_dits` retire déjà tout numéro
            # suspect de `extracted` avant qu'on arrive ici, et les deux contrôles portent
            # sur le même texte. Retiré : cinquième fois dans ce projet qu'une mutation
            # survivante révèle du code mort, et du code mort qui a l'air d'une garantie
            # est pire que pas de garantie du tout.
            nouveau = self._numero_fr(ex.get("telephone_rappel"))
            if nouveau and nouveau != self.slots["telephone_rappel"]:
                self.slots["telephone_rappel"] = nouveau
                # virgule et non point : un point placé juste après un groupe de
                # chiffres est lu par la synthèse vocale comme une fin d'énoncé, et le
                # « c'est bien ça ? » arrive détaché, comme une phrase sans rapport
                # (entendu le 26/08). Une virgule garde la question dans le même souffle.
                return self._say(self._phrase_confirme_tel(),
                                 verbatim=True)  # chiffres jamais réécrits
            if ex.get("confirme") is True:
                self.slots["tel_confirme"] = True
            elif ex.get("confirme") is False:
                # le numéro répété est FAUX : on l'efface et on redemande (jamais re-répéter le faux)
                self.slots["telephone_rappel"] = None
                # BORNE DES CORRECTIONS (R78). Remettre `tel_incomplets` à zéro à chaque
                # numéro valide rend la boucle « numéro valide → non → autre numéro
                # valide → non » infinie : chaque tour repartait à neuf, et
                # `confirmations_tel` se remet à zéro lui aussi dès que le numéro change.
                # Il fallait donc une borne PROPRE à la correction — trois refus de la
                # relecture ne convergeront pas, et l'artisan est mieux placé que nous.
                #
                # Trois, et non deux : ce sont trois refus DE L'APPELANT, pas des
                # malentendus de transcription. Il a le droit de se tromper deux fois.
                self.flags["corrections_tel"] = self.flags.get("corrections_tel", 0) + 1
                if self.flags["corrections_tel"] >= 3:
                    return self._sans_rdv()
                # LE CAS DU 02/09 : le formuleur a transformé cette phrase en
                # « Quel est votre problème avec votre plomberie ? », et l'appelant s'est
                # entendu redemander ce qu'il avait dit trois tours plus tôt.
                return self._say("Au temps pour moi — redonnez-moi le bon numéro ?",
                                 verbatim=True)
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
                return self._say(self._phrase_confirme_tel(relance=True),
                                 verbatim=True)  # chiffres jamais réécrits
        self.state = State.S5_CRENEAU
        return self._s5({})

    def _s5(self, ex: dict) -> str:
        # UN JOUR NOMMÉ ICI EST UNE CONTRAINTE, pas un refus (R67). La lecture est
        # cantonnée à `_s5` : ailleurs, « aujourd'hui c'est la catastrophe » décrit une
        # journée, pas une préférence. Ici, l'agent vient de proposer des créneaux — nommer
        # un jour ne peut vouloir dire qu'une chose.
        #
        # Le slot est REMPLACÉ et non complété : une préférence énoncée maintenant
        # remplace celle d'avant (« finalement plutôt samedi »).
        # (j'avais gardé ceci sous `if self.flags["hold"] is None` — condition morte :
        # `_s5` n'est atteint qu'en état S5, et un créneau bloqué fait passer en S6. Une
        # mutation l'a montrée sans effet. Sixième fois dans ce projet, et toujours la
        # même règle : du code mort qui a l'air d'une garantie est pire que rien.)
        jour = self._jour_dit(self._dernier_client())
        if jour:
            self.slots["disponibilites"] = jour

        # Les contraintes de disponibilité sont lues EN TÊTE : la branche « rien de plus
        # tôt » comme la reproposition en dépendent toutes les deux.
        # ("que le samedi matin" — bug T03-LLM)
        c = self._contraintes_dispo()
        jours, moment, dates = c["jours"], c["moment"], c["dates"]
        # L'ACTION du menu de cet état (`actions.py`), déjà validée : soit l'une des
        # actions que NOUS avons écrites, soit `pas_clair`. Le contrôleur ne lit plus une
        # ligne de texte de l'appelant — c'est tout le déplacement décidé le 01/09, après
        # trois défauts (R68, R70, R71) nés de listes de mots-clés qui tenaient lieu de
        # compréhension.
        action, rang = actions.valider(ex, self.state.name, len(self._proposes))

        # choix d'un créneau proposé ?
        if action == actions.CHOISIR and self._proposes:
            # « Oui, MAIS ça coûte combien ? » n'est pas le choix d'un créneau. Un `oui`
            # accompagné d'une question ne vaut acceptation de rien : réserver dessus
            # donnerait un rendez-vous que l'appelant n'a pas accepté — la faute que tout
            # le produit est construit pour éviter.
            #
            # Le modèle est censé rendre `pas_clair` dans ce cas ; le contrôleur le vérifie
            # quand même. C'est la ligne de partage : interpréter est au modèle, ENGAGER
            # reste au code, et un engagement se contrôle même quand on fait confiance.
            if not self._prix_a_repondre(ex):
                return self._reserver(self._proposes[rang - 1])
        # Une QUESTION de prix n'est pas un refus de créneau. Elle tombait pourtant dans
        # le quota de l'invariant n°6 : l'agent reproposait des créneaux, le compteur
        # avançait, et DEUX questions suffisaient à faire perdre le RDV — à un client qui
        # était toujours partant (Katz, éval réelle du 25/08). S4 avait appris la leçon
        # dès le 22/08 sans qu'elle soit généralisée à l'état suivant.
        # On répond avec la liste blanche et on RAPPELLE les créneaux déjà proposés :
        # les remplacer ferait changer la liste sous les pieds de l'appelant, qui ne
        # pourrait plus répondre « le premier ».
        if self._proposes and self._prix_a_repondre(ex):
            rappel = (self._dit(self._proposes[0]) if len(self._proposes) == 1
                      else f"{self._dit(self._proposes[0])}, ou "
                           f"{self._dit(self._proposes[1])}")
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
                               == _cle_contraintes(c))
        # PLUS TÔT — une seule action pour « le plus vite possible » et « vous n'avez rien
        # avant ? ». Les deux demandent la même chose : le créneau le plus proche. Elles
        # étaient traitées par deux branches et deux formulations ; c'était une définition
        # de trop, et c'est ce genre de doublon qui a produit R70.
        #
        # ELLE NE CONSOMME PAS LE QUOTA. Le précédent est déjà dans ce fichier, pour les
        # questions de prix : une question n'est pas un refus. Ici non plus — l'appelant ne
        # rejette rien, il demande le créneau le plus proche, celui qu'on vient de
        # proposer. Le 01/09, deux « le plus vite possible » d'affilée ont suffi à faire
        # perdre le rendez-vous à quelqu'un de coopérant et pressé.
        #
        # L'invariant n°6 (deux tours de créneaux) n'est pas touché : il borne la
        # NÉGOCIATION, et redire « au plus vite » ne fait pas avancer le calendrier.
        if action == actions.PLUS_TOT and self._proposes and contraintes_stables:
            dits = self.flags.get("plus_tot_dits", 0) + 1
            self.flags["plus_tot_dits"] = dits
            if dits <= 3:
                # LA PHRASE VARIE (acquis de R57) : redire mot pour mot à quelqu'un qui
                # vient de répéter sonne préenregistré, et c'est justement le moment où il
                # a besoin de comprendre qu'on l'a entendu.
                #
                # verbatim : elle énonce une DATE (cf. le bloc de `_s5` plus bas).
                creneau = self._dit(self._proposes[0])
                if dits == 1:
                    return self._say(f"Le plus tôt que je peux, c'est {creneau}. "
                                     f"Voulez-vous que je vous le réserve ?",
                                     verbatim=True)
                return self._say(f"C'est vraiment le premier créneau disponible : "
                                 f"{creneau}. Dites-moi oui et je vous le réserve.",
                                 verbatim=True)

        # PAS CLAIR — le modèle dit qu'il n'a pas compris, et c'est une réponse
        # RESPECTABLE. Le 01/09, la transcription a rendu « agençum » et « Nos gens sur
        # Marne » : agir sur ce bruit-là coûte un rendez-vous faux, bien plus cher qu'un
        # tour de plus. On redit donc la proposition et on fait répéter.
        #
        # NOUVEL INVARIANT (n°10) : on ne bascule JAMAIS en repli « on vous rappelle »
        # tant que l'appelant coopère. Une incompréhension déclenche une clarification,
        # pas un abandon. Le repli reste borné à trois, parce que trois tours sans qu'on
        # se comprenne veut dire que le canal est cassé, et l'artisan est alors mieux placé
        # que nous — mais c'est une panne de liaison, pas un client qu'on renvoie.
        if action == actions.PAS_CLAIR and self._proposes:
            flous = self.flags.get("tours_flous", 0) + 1
            self.flags["tours_flous"] = flous
            if flous <= 3:
                # verbatim : énonce une DATE
                # « saisi. demain entre 8 heures… » : minuscule après un point. À
                # l'écrit une coquille, à la synthèse vocale deux fragments — l'appelant
                # entend une phrase qui repart à côté au lieu d'une question.
                return self._say(f"Pardon, je n'ai pas bien saisi. Est-ce que "
                                 f"{self._dit(self._proposes[0])} vous va ? Vous pouvez "
                                 f"répondre oui ou non.", verbatim=True)
            # Budget de clarification épuisé : on REPREND LE FIL en reproposant, on
            # n'abandonne pas. Répéter « je n'ai pas saisi » indéfiniment est le seul
            # comportement pire que d'agir de travers ; basculer sur « Julien vous
            # rappellera » serait renvoyer quelqu'un qui est peut-être simplement mal
            # transcrit. On tombe donc dans le chemin normal, qui propose la suite et dont
            # le quota (invariant n°6) finit l'appel proprement.

        # DONNER UNE CONTRAINTE, C'EST COOPÉRER (R72). Le 01/09, « en tout cas pas le
        # vendredi » puis « ni le jeudi » ont suffi à faire raccrocher : `tours_creneaux`
        # comptait ces tours comme de la négociation. L'appelant n'avait rien refusé — il
        # précisait ses disponibilités, ce qu'on lui demande de faire.
        #
        # L'invariant n°6 n'est pas affaibli, il est LU CORRECTEMENT : il borne le nombre
        # de fois où l'on fait défiler le calendrier devant quelqu'un qui dit non. Une
        # contrainte ne fait pas défiler le calendrier, elle le RESSERRE.
        #
        # Même faute que R71, à un état près, et l'invariant écrit la veille la nommait
        # déjà — « jamais de repli tant que l'appelant coopère ». Je ne l'avais appliqué
        # qu'à `pas_clair`. Une contrainte coopère au moins autant qu'un silence.
        coopere = action == actions.CONTRAINTE
        if coopere:
            dites = self.flags.get("contraintes_dites", 0) + 1
            self.flags["contraintes_dites"] = dites
            # Borne propre : au-delà de trois contraintes sans qu'on aboutisse, on ne se
            # comprend plus, et l'appel doit pouvoir finir. On retombe alors dans le
            # comptage normal plutôt que de boucler sans fin.
            coopere = dites <= 3

        # (re)proposer — max 2 tours (invariant 6)
        if not coopere and self.flags["tours_creneaux"] >= 2:
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
        contraintes = _cle_contraintes(c)
        saut = (0 if self.flags.get("contraintes_proposees") != contraintes
                else 2 * self.flags["tours_creneaux"])
        self.flags["contraintes_proposees"] = contraintes
        # ce qui était proposé AVANT, pour savoir si la contrainte a changé quelque chose
        avant = [s.get("date") for s in self._proposes], [s.get("de") for s in self._proposes]
        self._proposes = self.cal.get_slots(self.slots["prestation"], urgent, n=2,
                                            skip=saut, jours=jours, moment=moment,
                                            dates=dates,
                                            jours_exclus=c["jours_exclus"],
                                            moment_exclu=c["moment_exclu"],
                                            pas_avant=c["pas_avant"])
        if not coopere:
            self.flags["tours_creneaux"] += 1
        # Le jour demandé est SATURÉ : on ne perd pas le rendez-vous pour autant. Avant
        # R67, une contrainte impossible menait droit au repli « Julien vous rappellera » —
        # un lead perdu parce que l'appelant avait exprimé une préférence.
        if not self._proposes and any(c.values()):
            self._proposes = self.cal.get_slots(self.slots["prestation"], urgent, n=1)
            if self._proposes:
                self.flags["contraintes_proposees"] = contraintes
                # verbatim : la phrase énonce une DATE (même règle que l'offre, R38)
                return self._say(
                    f"Je n'ai plus rien à ce moment-là. Le plus tôt que je peux vous "
                    f"proposer, c'est {self._dit(self._proposes[0])}. Ça vous irait ?",
                    verbatim=True)
        if not self._proposes:
            return self._sans_rdv()
        # UNE CONTRAINTE QUI NE CHANGE RIEN SE DIT (R82). Le 02/09, « en tout cas pas le
        # vendredi » n'a rien changé — « demain » était un mercredi — et l'agent a resservi
        # la même phrase MOT POUR MOT. À l'oreille, ça s'entend comme « je ne t'ai pas
        # écouté », et c'est le contraire de ce qui s'est passé : l'exclusion avait bien
        # été lue (R68), elle ne mordait sur rien.
        #
        # La comparaison se fait sur ce qui est PROPOSÉ, pas sur la contrainte : c'est la
        # seule façon de savoir qu'elle n'a pas mordu, sans avoir à raisonner sur son
        # contenu (« demain est-il un vendredi ? » n'est pas au contrôleur de le dire ici).
        inchange = (coopere
                    and ([s.get("date") for s in self._proposes],
                         [s.get("de") for s in self._proposes]) == avant
                    and any(c.values()))
        if inchange:
            self.flags["contrainte_sans_effet"] = \
                self.flags.get("contrainte_sans_effet", 0) + 1

        if len(self._proposes) == 1:
            offre = (f"Je peux vous proposer {self._dit(self._proposes[0])}. "
                     f"Ça vous irait ?")
        else:
            offre = (f"Je peux vous proposer {self._dit(self._proposes[0])}, "
                     f"ou {self._dit(self._proposes[1])}. Lequel vous arrange ?")
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
        if inchange:
            # verbatim : l'offre énonce des dates, et cette phrase-ci les introduit
            return self._say(f"Ces créneaux respectent déjà ce que vous me dites. "
                             f"{offre}", verbatim=True)
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
            f"Parfait, je vous réserve {self._dit(slot)}. Vous recevrez un SMS de "
            f"confirmation de {self._prenom} d'ici {delai} {heures}. "
            f"Si quoi que ce soit coince, on vous rappelle. Bonne journée !",
            verbatim=True)  # LA phrase du script : date et engagement jamais réécrits
        self.state = State.S11_CLOTURE
        return texte

    def _sans_rdv(self) -> str:
        # SANS NUMÉRO, PAS DE PROMESSE DE RAPPEL (R79). Le 02/09, un appel s'est terminé
        # sur « il vous rappelle sous 2 heures » alors qu'aucun numéro n'avait pu être
        # noté. Deux dommages en une phrase :
        #
        #   — au CLIENT, une promesse intenable. C'est exactement ce que tout le produit
        #     s'interdit : `guards` empêche le formuleur d'inventer un engagement, et le
        #     contrôleur en faisait un faux lui-même, verbatim, avec l'autorité du code ;
        #   — à JULIEN, un lead marqué « à rappeler » sans numéro. Il ne pourra jamais le
        #     traiter et ne le saura qu'en l'ouvrant. Un lead inexploitable qui ressemble
        #     à un lead exploitable coûte du temps et de la confiance.
        #
        # On dit donc les choses : on n'a pas pu noter le numéro, et l'appelant peut
        # rappeler. Une issue, pas une porte fermée — il n'a rien fait de mal, c'est
        # souvent la transcription qui a échoué.
        if not self.slots.get("telephone_rappel"):
            self.flags["categorie"] = "injoignable"
            texte = self._say(
                # Formulation NEUTRE, vraie dans les deux cas qui mènent ici : celui
                # dont on n'a pas réussi à noter le numéro, et celui qui a refusé de le
                # donner. « Je n'arrive pas à noter votre numéro » accusait le second à
                # tort — il l'avait très bien dit, il ne voulait pas le donner.
                "Sans numéro, je ne peux pas faire rappeler. N'hésitez pas à rappeler "
                "ce numéro quand vous voulez — on reprendra tranquillement. "
                "Bonne journée !",
                verbatim=True)  # ce qu'on s'engage à faire, ou pas : jamais réécrit
            self.state = State.S11_CLOTURE
            return texte
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
            f"{self.cfg['accueil']['promesse_rappel']['ouvree']}.",
            # VERBATIM : c'est une PROMESSE DE RAPPEL, avec un delai chiffre. `_sans_rdv`
            # l'etait deja (« engagement jamais reecrit ») ; ce chemin-ci ne l'etait pas.
            # Incoherence trouvee par le garde-fou des faits (R63) des son premier
            # passage, sur notre propre code — comme R53 l'avait fait pour la question
            # double de S1.
            verbatim=True)
        self.state = State.S11_CLOTURE
        return texte

    def _hors_zone(self) -> str:
        self.flags["zone"] = "hors_zone"
        self.flags["categorie"] = "hors_zone"
        # VERBATIM : c'est la phrase la plus définitive de l'appel. Elle passait par le
        # formuleur, qui y a glissé « Vous me dites Yvelines, 91260, Zivier-sur-Orge » —
        # un département faux et une commune inexistante (éval réelle du 26/08).
        texte = self.cfg["zone"]["message_hors_zone"] or self._say(
            f"Je suis désolé, {self.cfg['entreprise']['nom']} n'intervient pas sur "
            f"{self.slots['commune'] or 'votre secteur'}. Bonne continuation !",
            verbatim=True)
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
