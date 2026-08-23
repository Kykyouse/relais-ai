#!/usr/bin/env python3
"""Smoke tests : joue des scénarios scriptés (docs/scenarios-test-v1.md) en mode mock.

Couvre pour l'instant : T01 (urgence fuite), T02 (hors zone), T05 (chasse au prix,
via le garde-fou), T11 (refus de numéro). Usage : python run_scenario.py
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

from relais_proto import messages
from relais_proto.calendar_stub import CalendarStub
from relais_proto.depot import DepotMemoire
from relais_proto.engine import Conversation
from relais_proto.expiration import WorkerExpiration
from relais_proto.guards import check_output
from relais_proto.llm import MockLLM, ResilientLLM
from relais_proto.messages import Destinataire, MessageSortant
from relais_proto.rdv import (Rdv, StatutRdv, TransitionInterdite,
                              calculer_expiration)
from relais_proto.scoring import build_lead

CFG = json.loads((pathlib.Path(__file__).parent / "config" / "dupont.json")
                 .read_text(encoding="utf-8"))

SCENARIOS = {
    "T01_urgence_fuite": {
        "lignes": [
            "Bonjour, j'ai une fuite sous l'évier, l'eau coule encore, c'est urgent !",
            "Je suis à Nogent-sur-Marne, 94130, je suis propriétaire",
            "C'est en cours là, ça goutte dans le placard",
            "Je m'appelle Garcia, mon numéro c'est 06 12 34 56 78",
            "Oui c'est bien ça",
            "Le premier créneau c'est parfait, je suis chez moi quand vous voulez",
        ],
        "attendu": {"score": 5, "categorie": "rdv_reserve", "rdv": True},
    },
    "T02_hors_zone": {
        "lignes": [
            "Bonjour, je voudrais un devis pour une pompe à chaleur",
            "J'habite à Champigny, 94500",
        ],
        "attendu": {"score": 0, "categorie": "hors_zone", "rdv": False},
    },
    "R01_correction_numero": {
        # régression (bug trouvé par Geoffrey 21/08) : "Non" au numéro répété relançait
        # l'ANCIEN numéro, et le nouveau était ignoré → l'agent confirmait un numéro faux.
        "lignes": [
            "Bonjour, j'ai une fuite, c'est urgent, l'eau coule",
            "94130",
            "Je m'appelle Bernard, mon numéro c'est 06 54 23 45 67",
            "Non",
            "07 12 32 13 56",
            "Oui",
            "Le premier",
        ],
        "attendu": {"score": 5, "categorie": "rdv_reserve", "rdv": True,
                     "tel": "0712321356"},
    },
    "R02_numero_incomplet": {
        # régression : un numéro à 6 chiffres était traité comme un refus silencieux.
        "lignes": [
            "fuite sous l'évier, c'est urgent, ça coule",
            "94130",
            "David, mon numéro c'est le 074323",
            "Pardon : 07 43 23 11 22",
            "Oui",
            "Le premier",
        ],
        "attendu": {"score": 5, "categorie": "rdv_reserve", "rdv": True,
                     "tel": "0743231122"},
    },
    "R03_creneaux_differents_puis_repli": {
        # régression : "aucun" reproposait LES MÊMES créneaux au 2e tour.
        "lignes": [
            "fuite au robinet, c'est urgent, ça coule",
            "94130",
            "Martin, 06 11 22 33 44",
            "Oui",
            "Aucun des deux ne m'arrange",
            "Non plus, rien de tout ça",
        ],
        "attendu": {"score": 3, "categorie": "a_rappeler", "rdv": False},
    },
    "R04_changement_commune": {
        # régression : la commune corrigée en cours d'appel était ignorée, ET le CP
        # "94000" était pris pour un numéro de téléphone incomplet.
        "lignes": [
            "Bonjour j'ai une fuite, c'est urgent, ça coule",
            "94130",
            "Ah non pardon, en fait c'est chez ma mère, à Créteil, 94000",
            "Bernard, 06 11 22 33 44",
            "Oui",
            "Le premier",
        ],
        "attendu": {"score": 5, "categorie": "rdv_reserve", "rdv": True, "cp": "94000"},
    },
    "R05_changement_vers_hors_zone": {
        # régression : correction de commune vers une zone non couverte → refus immédiat.
        "lignes": [
            "Bonjour j'ai une fuite, c'est urgent, ça coule",
            "94130",
            "Ah non pardon, c'est chez ma mère à Champigny, 94500",
        ],
        "attendu": {"score": 0, "categorie": "hors_zone", "rdv": False, "cp": "94500"},
    },
    "R06_tout_d_un_coup_consigne_conservee": {
        # régression : quand tout est donné en une phrase, la consigne sécurité
        # "coupez l'eau" était silencieusement perdue (saut d'états).
        "lignes": [
            "Fuite urgente, à Nogent 94130, mon numéro c'est 06 12 34 56 78, dispo cet après-midi",
            "Oui c'est bien ça",
            "Le premier",
        ],
        "attendu": {"score": 5, "categorie": "rdv_reserve", "rdv": True,
                     "texte_agent": "coupez l'arrivée d'eau"},
    },
    "R07_demande_humain_reprise_dediee": {
        # régression : au 1er "je veux un humain", le formuleur improvisait une promesse
        # de transmission jamais décidée par le contrôleur. Désormais : reprise dédiée,
        # puis transfert à la 2e demande.
        "lignes": [
            "Je veux parler à Julien s'il vous plaît",
            "Non je veux un humain, pas une machine",
        ],
        "attendu": {"score": 1, "categorie": "prioritaire", "rdv": False,
                     "texte_agent": "je peux tout organiser pour vous"},
    },
    "R09_commune_sans_cp": {
        # amélioration (cas "Juvisy" trouvé par Geoffrey) : l'appelant donne sa VILLE,
        # pas son CP — les communes de la zone sont résolues sans redemander.
        "lignes": [
            "fuite urgente, ça coule",
            "Je suis à Saint-Maur",
            "Garcia, 06 12 34 56 78",
            "Oui",
            "Le premier",
        ],
        "attendu": {"score": 5, "categorie": "rdv_reserve", "rdv": True, "cp": "94100"},
    },
    "R10_commune_inconnue_demande_cp": {
        # une commune hors table (Juvisy) → on demande le CP, puis refus hors zone propre.
        "lignes": [
            "Bonjour, je voudrais un devis pour une pompe à chaleur",
            "Juvisy-sur-Orge",
            "91260",
        ],
        "attendu": {"score": 0, "categorie": "hors_zone", "rdv": False, "cp": "91260"},
    },
    "R11_dispo_samedi_respectee": {
        # bug T03-LLM : le client dit "que le samedi matin", l'agent proposait lundi/mardi.
        # Les créneaux proposés doivent respecter les disponibilités exprimées.
        "lignes": [
            "Je veux un entretien de chaudière, mais uniquement le samedi matin",
            "Nogent 94130",
            "Diallo, 07 88 11 22 33",
            "Oui",
            "Le premier",
        ],
        "attendu": {"score": 4, "categorie": "rdv_reserve", "rdv": True,
                     "texte_agent": "samedi"},
    },
    "R12_commune_avec_ponctuation": {
        # bug LLM-run3 : « C'est Saint-Maur. » / « Saint-Maur-des-Fossés, dans le
        # Val-de-Marne » — la ponctuation cassait la résolution commune→CP et l'agent
        # bouclait sur la demande de commune.
        "lignes": [
            "Mon chauffe-eau ne marche plus, c'est urgent !",
            "Ben c'est Saint-Maur-des-Fossés, dans le Val-de-Marne.",
            "Petit, 06 44 55 66 77",
            "Oui",
            "Le premier",
        ],
        "attendu": {"score": 5, "categorie": "rdv_reserve", "rdv": True, "cp": "94100"},
    },
    "R13_commune_idf_hors_zone_directe": {
        # table IdF complète : une commune francilienne hors zone est classée
        # hors_zone immédiatement, sans demander le code postal (UX cas Juvisy).
        "lignes": [
            "Bonjour, je voudrais un devis pour une pompe à chaleur",
            "J'habite à Juvisy-sur-Orge.",
        ],
        "attendu": {"score": 0, "categorie": "hors_zone", "rdv": False, "cp": "91260"},
    },
    "T11_refus_numero": {
        "lignes": [
            "Bonjour, j'ai une petite fuite au robinet de la cuisine",
            "Nogent, 94130",
            "Non je préfère pas donner mon numéro, je rappellerai",
            "Non, pas de numéro je vous dis",
            "Non vraiment pas",
        ],
        "attendu": {"score": 1, "categorie": "a_rappeler", "rdv": False},
    },
}


class PanneLLM:  # simule internet coupé / API down sur chaque appel (R08, R14)
    def extract(self, u, c):
        raise ConnectionError("getaddrinfo failed")

    def reply(self, i, c):
        raise ConnectionError("getaddrinfo failed")


def check_panne_llm() -> bool:
    """R08 : le LLM tombe en panne TOTALE (réseau coupé) dès le premier tour →
    l'appel doit aboutir quand même en mode scripté, avec les dégradations tracées."""
    llm = ResilientLLM(PanneLLM())
    convo = Conversation(CFG, llm)
    convo.open()
    for ligne in ["J'ai une fuite, c'est urgent, ça coule",
                  "94130",
                  "Garcia, 06 12 34 56 78",
                  "Oui c'est bien ça",
                  "Le premier"]:
        if convo.state.value in ("S11", "FIN"):
            break
        convo.process(ligne)
    lead = build_lead(convo)
    return (lead["score"] == 5 and lead["rdv"] is not None
            and len(lead["degradations_llm"]) > 0)


def _joue(lignes: list[str], llm_neuf, cal_neuf, aller_retour: bool = False) -> Conversation:
    """Joue un scénario. Si aller_retour, l'objet ET son client LLM sont détruits puis
    rechargés depuis du vrai JSON avant chaque tour — comme le fera un webhook téléphonie
    en prod, où le tour suivant tombe sur un process neuf qui ne partage rien."""
    convo = Conversation(CFG, llm_neuf(), cal_neuf())
    convo.open()
    for ligne in lignes:
        if aller_retour:
            brut = json.dumps(convo.to_dict(), ensure_ascii=False)  # JSON réel, pas un dict
            convo = Conversation.from_dict(json.loads(brut), CFG, llm_neuf())
        if convo.state.value in ("S11", "FIN"):
            break
        convo.process(ligne)
    return convo


FUITE_LIGNES = ["J'ai une fuite, c'est urgent, ça coule", "94130",
                "Garcia, 06 12 34 56 78", "Oui c'est bien ça", "Le premier"]


def check_serialisation() -> bool:
    """R14 : en prod chaque tour arrivera comme un webhook HTTP, potentiellement sur un
    autre process — l'état de la conversation doit donc faire un aller-retour JSON entre
    CHAQUE tour sans rien changer. On rejoue TOUS les scénarios ci-dessus en re-sérialisant
    à chaque tour et on exige des leads identiques (hors horodatage)."""
    # Horloge FIGÉE (un lundi matin) : on teste la sérialisation, pas la marche du temps.
    # Figée et non dt.datetime.now(), parce que la fenêtre d'urgence réservée dépend du
    # jour et de l'heure : un run lancé un dimanche soir ne testerait jamais le quota
    # d'urgences du jour, et le trou passerait inaperçu.
    maintenant = dt.datetime(2026, 8, 24, 9, 0)
    compares = ("score", "categorie", "zone", "raisons", "slots", "rdv",
                "violations_gardes_fous", "degradations_llm", "transcript")
    cal_neuf = lambda: CalendarStub(CFG, now=maintenant)

    cas = [(nom, sc["lignes"], MockLLM, cal_neuf) for nom, sc in SCENARIOS.items()]
    # les dégradations LLM vivent sur le CLIENT, pas sur la conversation : si l'état ne
    # les transporte pas, un appel dégradé rechargé remonte un lead faussement « propre »
    # et on perd l'alerte monitoring. D'où la panne totale, avec client neuf à chaque tour.
    cas.append(("R08_panne_llm_totale", FUITE_LIGNES,
                lambda: ResilientLLM(PanneLLM()), cal_neuf))
    # compteur de silences : sans lui dans l'état, l'appelant muet ne basculerait
    # jamais en S9 (chaque tour se croirait le premier silence — boucle infinie)
    cas.append(("silence_puis_repondeur", ["", "", "il y a quelqu'un ?"],
                MockLLM, cal_neuf))
    # quota d'urgences du jour déjà consommé : s'il n'est pas rechargé, la conversation
    # reprise ressort la fenêtre d'urgence réservée que l'artisan a déjà donnée
    quota = CFG["agenda"]["urgences"]["max_par_jour"]
    cas.append(("urgences_du_jour_saturees", FUITE_LIGNES, MockLLM,
                lambda: CalendarStub(CFG, now=maintenant,
                                     urgences_consommees_aujourdhui=quota)))

    for nom, lignes, llm_neuf, cal in cas:
        a = build_lead(_joue(lignes, llm_neuf, cal))
        b = build_lead(_joue(lignes, llm_neuf, cal, aller_retour=True))
        for cle in compares:
            if a[cle] != b[cle]:
                print(f"   {nom} · '{cle}' diverge\n     mémoire   = {a[cle]!r}"
                      f"\n     rechargée = {b[cle]!r}")
                return False
        if nom.startswith("R08") and not b["degradations_llm"]:
            print("   le cas panne ne trace plus aucune dégradation : test creux")
            return False

    # Point fixe : recharger puis re-sérialiser doit redonner EXACTEMENT le même état.
    # C'est ce qui protège les champs que le stub n'exploite pas encore (holds du
    # calendrier tampon, jours_pleins) mais que le vrai calendrier lira.
    etat = _joue(FUITE_LIGNES, MockLLM, cal_neuf).to_dict()
    reserialise = Conversation.from_dict(json.loads(json.dumps(etat)), CFG,
                                         MockLLM()).to_dict()
    if reserialise != etat:
        divergents = [c for c in set(etat) | set(reserialise)
                      if etat.get(c) != reserialise.get(c)]
        print(f"   aller-retour non idempotent sur : {divergents}")
        return False
    if not etat["calendrier"]["holds"]:
        print("   l'état de référence ne contient aucun hold : point fixe creux")
        return False

    # un état d'une autre version doit être REFUSÉ, jamais lu de travers
    try:
        Conversation.from_dict({**etat, "v": 999}, CFG, MockLLM())
        print("   un état de version inconnue a été accepté")
        return False
    except ValueError:
        pass
    return True


LUNDI_9H = dt.datetime(2026, 8, 24, 9, 0)  # horloge de référence des tests RDV


def cfg_pour(artisan_id: str):
    """Résolveur de config des tests. STRICT volontairement : un `lambda _: CFG`
    n'exercerait pas la résolution par artisan, qui est tout l'objet de la migration 004."""
    return CFG if artisan_id == "art-dupont" else None


def _rdv_test(statut: StatutRdv, echu: bool) -> Rdv:
    """RDV nu dans l'état demandé, échu ou non, pour éprouver le graphe."""
    return Rdv(id="rdv-t", lead_id="lead-t", artisan_id="art-t",
               creneau={"date": "2026-08-25", "de": "08:00", "a": "10:00",
                        "label": "demain entre 08h et 10h", "urgence": False},
               duree_min=90, urgence=False, cree_a=LUNDI_9H,
               expire_a=LUNDI_9H + dt.timedelta(hours=-1 if echu else 4),
               statut=statut)


def check_cycle_vie_rdv() -> bool:
    """R15 : cycle de vie du RDV (tampon → en_attente_validation → validé/refusé/expiré).

    Le pendant backend des garde-fous : un RDV en base est un engagement pris envers un
    client, donc les transitions illégales doivent lever, pas être tolérées."""
    actions = {StatutRdv.EN_ATTENTE_VALIDATION: Rdv.notifier, StatutRdv.VALIDE: Rdv.valider,
               StatutRdv.REFUSE: Rdv.refuser, StatutRdv.EXPIRE: Rdv.expirer,
               StatutRdv.REPROPOSE: lambda r, m: r.reproposer(
                   {**r.creneau, "date": "2026-09-01"}, CFG, m, "a" * 64)}

    # Matrice attendue écrite EN DUR, volontairement pas lue dans rdv.TRANSITIONS : un
    # test qui dérive ses attentes de la table qu'il vérifie ne teste que la cohérence du
    # code avec lui-même. Si quelqu'un ouvre « expiré → validé » dans la table, on veut
    # un échec ici, pas un test qui suit le changement.
    attendus = {
        StatutRdv.TAMPON: {StatutRdv.EN_ATTENTE_VALIDATION, StatutRdv.EXPIRE},
        StatutRdv.EN_ATTENTE_VALIDATION: {StatutRdv.VALIDE, StatutRdv.REFUSE,
                                          StatutRdv.REPROPOSE, StatutRdv.EXPIRE},
        # reproposé = en attente du CLIENT. L'artisan garde le droit de trancher
        # lui-même (il a peut-être eu le client au téléphone), et l'échéance
        # s'applique comme partout ailleurs.
        StatutRdv.REPROPOSE: {StatutRdv.VALIDE, StatutRdv.REFUSE, StatutRdv.EXPIRE},
        StatutRdv.VALIDE: set(),
        StatutRdv.REFUSE: set(),
        StatutRdv.EXPIRE: set(),
    }

    # (a) graphe complet : chaque paire est acceptée si et seulement si elle est autorisée
    for depuis in StatutRdv:
        for vers, action in actions.items():
            attendu = vers in attendus[depuis]
            rdv = _rdv_test(depuis, echu=(vers is StatutRdv.EXPIRE))
            try:
                action(rdv, LUNDI_9H)
                obtenu = True
            except TransitionInterdite:
                obtenu = False
            if obtenu != attendu:
                print(f"   graphe : {depuis.value} → {vers.value} "
                      f"{'accepté' if obtenu else 'refusé'} alors qu'il devrait être "
                      f"{'accepté' if attendu else 'refusé'}")
                return False

    # (b) défauts de la config : 24 h réelles hors urgence, 2 h réelles en urgence
    # (retour terrain 23/08 : l'app n'est souvent regardée que le soir)
    cas_reels = [
        (False, dt.datetime(2026, 8, 24, 9, 0), dt.datetime(2026, 8, 25, 9, 0)),
        (False, dt.datetime(2026, 8, 28, 17, 0), dt.datetime(2026, 8, 29, 17, 0)),
        (True, dt.datetime(2026, 8, 30, 20, 0), dt.datetime(2026, 8, 30, 22, 0)),
    ]
    for urgence, depuis, attendu in cas_reels:
        obtenu = calculer_expiration(CFG, urgence=urgence, depuis=depuis)
        if obtenu != attendu:
            print(f"   heures réelles · urgence={urgence} depuis {depuis} : "
                  f"{obtenu} au lieu de {attendu}")
            return False

    # (b bis) mode "ouvrees" avec un délai court : un RDV pris le vendredi soir ne doit
    # pas expirer pendant la nuit sans que l'artisan ait pu le voir
    cfg_ouvrees = {**CFG, "validation": {**CFG["validation"],
                                         "base_delai": "ouvrees",
                                         "delai_max_heures": 4}}
    cas_ouvrees = [
        ("lundi 09:00 (en pleine fenêtre)", dt.datetime(2026, 8, 24, 9, 0),
         dt.datetime(2026, 8, 24, 13, 0)),
        ("lundi 07:00 (avant ouverture)", dt.datetime(2026, 8, 24, 7, 0),
         dt.datetime(2026, 8, 24, 12, 0)),
        ("lundi 17:00 (déborde sur mardi)", dt.datetime(2026, 8, 24, 17, 0),
         dt.datetime(2026, 8, 25, 11, 0)),
        ("vendredi 17:00 (déborde sur samedi court)", dt.datetime(2026, 8, 28, 17, 0),
         dt.datetime(2026, 8, 29, 12, 0)),
        ("samedi 12:00 (dimanche fermé, saute au lundi)", dt.datetime(2026, 8, 29, 12, 0),
         dt.datetime(2026, 8, 31, 11, 0)),
        ("dimanche 10:00 (jour fermé)", dt.datetime(2026, 8, 30, 10, 0),
         dt.datetime(2026, 8, 31, 12, 0)),
    ]
    for libelle, depuis, attendu in cas_ouvrees:
        obtenu = calculer_expiration(cfg_ouvrees, urgence=False, depuis=depuis)
        if obtenu != attendu:
            print(f"   heures ouvrées · {libelle} : {obtenu} au lieu de {attendu}")
            return False

    # l'urgence reste en heures RÉELLES même en mode "ouvrees" : une fuite prise dimanche
    # 20 h n'attend pas l'ouverture du lundi, sinon le mot urgence ne veut plus rien dire
    urgent = calculer_expiration(cfg_ouvrees, urgence=True,
                                 depuis=dt.datetime(2026, 8, 30, 20, 0))
    if urgent != dt.datetime(2026, 8, 30, 22, 0):
        print(f"   urgence en mode ouvrées : {urgent}, attendu dimanche 22:00 (réelles)")
        return False

    # les mêmes règles traversées par Rdv.depuis_hold, à une heure où les deux modes
    # DIVERGENT (vendredi 17 h) : 24 h réelles → samedi 17 h ; 4 h ouvrées → samedi 12 h ;
    # urgence → vendredi 19 h dans les deux modes.
    vendredi_17h = dt.datetime(2026, 8, 28, 17, 0)
    hold_nu = {"date": "2026-09-01", "de": "08:00", "a": "10:00", "urgence": False,
               "label": "mardi 01/09 entre 08h et 10h", "duree_min": 90}
    cas_hold = [
        (CFG, None, dt.datetime(2026, 8, 29, 17, 0)),
        (CFG, True, dt.datetime(2026, 8, 28, 19, 0)),
        (cfg_ouvrees, None, dt.datetime(2026, 8, 29, 12, 0)),
        (cfg_ouvrees, True, dt.datetime(2026, 8, 28, 19, 0)),
    ]
    for cfg, urgence_reelle, echeance in cas_hold:
        obtenu = Rdv.depuis_hold(
            hold_nu, id="rdv-v", lead_id="lead-v", artisan_id="art-t",
            lead={"slots": {"tel_confirme": True, "urgence_reelle": urgence_reelle}},
            cfg=cfg, maintenant=vendredi_17h).expire_a
        if obtenu != echeance:
            print(f"   depuis_hold(base={cfg['validation']['base_delai']}, "
                  f"urgence={urgence_reelle}) → {obtenu}, attendu {echeance}")
            return False

    # (c) la course critique : l'artisan tape juste après l'échéance, le worker n'est pas
    # encore passé — la décision doit être refusée quand même
    rdv = _rdv_test(StatutRdv.EN_ATTENTE_VALIDATION, echu=False)
    juste_apres = rdv.expire_a + dt.timedelta(seconds=1)
    for nom, action in (("valider", Rdv.valider), ("refuser", Rdv.refuser)):
        try:
            action(_rdv_test(StatutRdv.EN_ATTENTE_VALIDATION, echu=False), juste_apres)
        except TransitionInterdite:
            continue
        print(f"   {nom}() accepté 1 s après l'échéance : la décision dépendrait du cron")
        return False
    # symétriquement, on n'expire pas un RDV encore dans les temps
    try:
        _rdv_test(StatutRdv.EN_ATTENTE_VALIDATION, echu=False).expirer(LUNDI_9H)
        print("   expirer() accepté avant l'échéance")
        return False
    except TransitionInterdite:
        pass

    # (d) bout en bout : T01 (urgence) joué en mock → dépôt → tampon → notifié → validé
    depot = DepotMemoire()
    convo = Conversation(CFG, MockLLM(), CalendarStub(CFG, now=LUNDI_9H))
    convo.open()
    for ligne in SCENARIOS["T01_urgence_fuite"]["lignes"]:
        if convo.state.value in ("S11", "FIN"):
            break
        convo.process(ligne)
    lead_donnees = build_lead(convo)
    appel = depot.ouvrir_appel("art-dupont", LUNDI_9H)
    depot.enregistrer_etat(appel.id, convo.to_dict())   # état sérialisé (R14) en base
    lead = depot.cloturer_appel(appel.id, lead_donnees, LUNDI_9H)
    rdv = depot.creer_rdv(lead_id=lead.id, hold=lead_donnees["rdv"],
                          lead_donnees=lead_donnees, cfg=CFG, maintenant=LUNDI_9H)
    if rdv.statut is not StatutRdv.TAMPON:
        print(f"   RDV créé en {rdv.statut.value} au lieu de tampon")
        return False

    # l'échéance en base doit correspondre à la promesse PRONONCÉE à l'appelant
    urgence_appel = bool(lead_donnees["slots"].get("urgence_reelle"))
    if rdv.expire_a != calculer_expiration(CFG, urgence_appel, LUNDI_9H):
        print(f"   échéance {rdv.expire_a} incohérente avec la config validation")
        return False
    delai = CFG["validation"]["delai_max_urgence_heures" if urgence_appel
                              else "delai_max_heures"]
    paroles = " ".join(t for qui, t in lead_donnees["transcript"] if qui == "agent")
    if f"d'ici {delai} heure" not in paroles:
        print(f"   l'agent n'a pas promis {delai} h : la base et la parole divergent")
        return False

    # (e) le dépôt ne rend jamais l'instance vivante : muter sans sauver ne persiste rien
    fantome = depot.rdv(rdv.id)
    fantome.notifier(LUNDI_9H)
    if depot.rdv(rdv.id).statut is not StatutRdv.TAMPON:
        print("   le dépôt rend l'instance vivante : un test passerait sans sauver_rdv()")
        return False

    rdv.notifier(LUNDI_9H + dt.timedelta(minutes=5))
    depot.sauver_rdv(rdv)
    if [r.id for r in depot.rdvs_en_attente("art-dupont")] != [rdv.id]:
        print("   le RDV notifié n'est pas dans la boîte de validation")
        return False
    rdv.valider(LUNDI_9H + dt.timedelta(minutes=30))
    depot.sauver_rdv(rdv)
    if depot.rdvs_en_attente("art-dupont"):
        print("   un RDV validé reste dans la boîte de validation")
        return False

    # (f) le chemin d'expiration : R11 (non urgent) laissé sans réponse
    convo2 = Conversation(CFG, MockLLM(), CalendarStub(CFG, now=LUNDI_9H))
    convo2.open()
    for ligne in SCENARIOS["R11_dispo_samedi_respectee"]["lignes"]:
        if convo2.state.value in ("S11", "FIN"):
            break
        convo2.process(ligne)
    lead2_donnees = build_lead(convo2)
    appel2 = depot.ouvrir_appel("art-dupont", LUNDI_9H)
    lead2 = depot.cloturer_appel(appel2.id, lead2_donnees, LUNDI_9H)
    rdv2 = depot.creer_rdv(lead_id=lead2.id, hold=lead2_donnees["rdv"],
                           lead_donnees=lead2_donnees, cfg=CFG, maintenant=LUNDI_9H)
    if rdv2.expire_a != dt.datetime(2026, 8, 25, 9, 0):  # 24 h réelles depuis lundi 9 h
        print(f"   échéance non urgente {rdv2.expire_a}, attendu mardi 09:00")
        return False
    if depot.rdvs_echus(LUNDI_9H + dt.timedelta(hours=20)):
        print("   un RDV non échu est remonté dans la file du worker")
        return False
    echus = depot.rdvs_echus(rdv2.expire_a)
    if [r.id for r in echus] != [rdv2.id]:
        print(f"   file du worker à l'échéance : {[r.id for r in echus]}, attendu [{rdv2.id}]")
        return False
    # un tampon jamais notifié doit expirer aussi (push échoué → pas de créneau fantôme)
    if echus[0].statut is not StatutRdv.TAMPON:
        print("   le cas 'tampon jamais notifié' n'est plus couvert : test creux")
        return False
    echus[0].expirer(rdv2.expire_a)
    depot.sauver_rdv(echus[0])
    if depot.rdvs_echus(rdv2.expire_a) or depot.rdv(rdv2.id).statut is not StatutRdv.EXPIRE:
        print("   le RDV expiré reste dans la file du worker")
        return False

    # (g) urgence RÉELLE mais créneau hors fenêtre d'urgence (quota du jour épuisé) :
    # l'échéance suit urgence_reelle (1 h réelle), pas le drapeau du créneau — sinon la
    # base accorde 4 h ouvrées là où l'agent a promis « d'ici 1 heure » au téléphone.
    # C'est le seul cas où les deux sources divergent, d'où ce scénario dédié.
    quota = CFG["agenda"]["urgences"]["max_par_jour"]
    convo_u = Conversation(CFG, MockLLM(),
                           CalendarStub(CFG, now=LUNDI_9H,
                                        urgences_consommees_aujourdhui=quota))
    convo_u.open()
    for ligne in SCENARIOS["T01_urgence_fuite"]["lignes"]:
        if convo_u.state.value in ("S11", "FIN"):
            break
        convo_u.process(ligne)
    lead_u = build_lead(convo_u)
    if not lead_u["slots"].get("urgence_reelle") or lead_u["rdv"]["urgence"]:
        print("   cas urgence/créneau non divergent : quota épuisé sans effet, test creux")
        return False
    appel_u = depot.ouvrir_appel("art-dupont", LUNDI_9H)
    ref_u = depot.cloturer_appel(appel_u.id, lead_u, LUNDI_9H)
    rdv_u = depot.creer_rdv(lead_id=ref_u.id, hold=lead_u["rdv"], lead_donnees=lead_u,
                            cfg=CFG, maintenant=LUNDI_9H)
    if rdv_u.expire_a != LUNDI_9H + dt.timedelta(hours=2):
        print(f"   échéance {rdv_u.expire_a} : suit le créneau et non urgence_reelle "
              f"(attendu lundi 11:00)")
        return False

    # (h) invariant produit : jamais de RDV sans téléphone confirmé, même en base
    sans_tel = {**lead_donnees, "slots": {**lead_donnees["slots"], "tel_confirme": None}}
    appel3 = depot.ouvrir_appel("art-dupont", LUNDI_9H)
    lead3 = depot.cloturer_appel(appel3.id, sans_tel, LUNDI_9H)
    try:
        depot.creer_rdv(lead_id=lead3.id, hold=lead_donnees["rdv"], lead_donnees=sans_tel,
                        cfg=CFG, maintenant=LUNDI_9H)
        print("   RDV créé sans téléphone confirmé (invariant produit violé)")
        return False
    except ValueError:
        pass
    return True


def _appel_avec_rdv(depot, nom_scenario: str, maintenant: dt.datetime):
    """Joue un scénario en mock et pose son RDV dans le dépôt. Rend (lead, rdv)."""
    convo = Conversation(CFG, MockLLM(), CalendarStub(CFG, now=maintenant))
    convo.open()
    for ligne in SCENARIOS[nom_scenario]["lignes"]:
        if convo.state.value in ("S11", "FIN"):
            break
        convo.process(ligne)
    donnees = build_lead(convo)
    appel = depot.ouvrir_appel("art-dupont", maintenant)
    depot.enregistrer_etat(appel.id, convo.to_dict())
    lead = depot.cloturer_appel(appel.id, donnees, maintenant)
    rdv = depot.creer_rdv(lead_id=lead.id, hold=donnees["rdv"], lead_donnees=donnees,
                          cfg=CFG, maintenant=maintenant)
    return lead, rdv


def check_worker_expiration(fabrique=DepotMemoire) -> bool:
    """R16 : worker d'expiration (spec §3.6) — créneau libéré, lead en alerte, SMS de
    repli au client, relance artisan. Deux propriétés critiques : il est idempotent, et
    il ne vole jamais une décision à l'artisan."""
    depot = fabrique()
    worker = WorkerExpiration(depot, cfg_pour)

    # (a) dépôt vide : un passage ne doit rien inventer
    if worker.passer(LUNDI_9H):
        print("   passage sur dépôt vide non vide")
        return False

    # (b) un RDV notifié puis laissé sans réponse (T01, urgence → échéance à 2 h)
    lead, rdv = _appel_avec_rdv(depot, "T01_urgence_fuite", LUNDI_9H)
    rdv.notifier(LUNDI_9H)
    depot.sauver_rdv(rdv)
    if depot.rdvs_echus(rdv.expire_a - dt.timedelta(minutes=1)):
        print("   un RDV encore dans les temps est déjà dans la file du worker")
        return False

    rapport = worker.passer(rdv.expire_a)
    if rapport.expires != [rdv.id] or len(rapport.messages_crees) != 2:
        print(f"   1er passage : expirés={rapport.expires}, "
              f"messages={rapport.messages_crees} (attendu 1 RDV, 2 messages)")
        return False
    if depot.rdv(rdv.id).statut is not StatutRdv.EXPIRE:
        print(f"   le RDV n'est pas expiré en base : {depot.rdv(rdv.id).statut.value}")
        return False
    if depot.lead(lead.id).donnees.get("alerte", {}).get("motif") \
            != "rdv_expire_sans_reponse":
        print("   le lead n'a pas été mis en alerte")
        return False

    # destinataires et contenus : le SMS client part sur le numéro confirmé, la relance
    # artisan sur la cible de transfert, et les deux passent les garde-fous
    par_dest = {m.destinataire: m for m in depot.messages()}
    if set(par_dest) != {Destinataire.CLIENT, Destinataire.ARTISAN}:
        print(f"   destinataires en file : {sorted(d.value for d in par_dest)}")
        return False
    if par_dest[Destinataire.CLIENT].cible != lead.donnees["slots"]["telephone_rappel"]:
        print("   le SMS de repli ne part pas sur le numéro confirmé du client")
        return False
    if par_dest[Destinataire.ARTISAN].cible != rdv.artisan_id:
        print("   la relance artisan ne cible pas le compte artisan (push)")
        return False
    for m in depot.messages():
        violations = check_output(m.texte, CFG)
        if violations:
            print(f"   message {m.destinataire.value} viole un garde-fou : {violations}")
            return False
    # le créneau doit être NOMMÉ au client : un SMS qui ne dit pas lequel est inutile
    if rdv.creneau["label"] not in par_dest[Destinataire.CLIENT].texte:
        print("   le SMS de repli ne rappelle pas le créneau concerné")
        return False

    # (c) deuxième passage : plus rien à faire, et surtout aucun second SMS
    avant = len(depot.messages())
    rapport2 = worker.passer(rdv.expire_a + dt.timedelta(hours=1))
    if rapport2 or len(depot.messages()) != avant:
        print(f"   2e passage non neutre : {rapport2}, {len(depot.messages())} messages")
        return False

    # (d) passage INTERROMPU après l'enfilage, avant l'écriture du statut : le RDV
    # reste échu, le passage suivant doit le rattraper SANS doubler le SMS du client.
    # (c'est pour ça que le worker enfile avant de changer l'état)
    lead_b, rdv_b = _appel_avec_rdv(depot, "R11_dispo_samedi_respectee", LUNDI_9H)
    rdv_b.notifier(LUNDI_9H)
    depot.sauver_rdv(rdv_b)
    brouillons = [messages.repli_client(rdv_b, lead_b.donnees, CFG),
                  messages.relance_artisan(rdv_b, lead_b.donnees, CFG)]
    for b in brouillons:                       # l'enfilage a eu lieu…
        depot.enfiler_message(b, rdv_b.expire_a)
    avant = len(depot.messages())              # …puis le process est mort ici
    rapport3 = worker.passer(rdv_b.expire_a)
    if rapport3.expires != [rdv_b.id]:
        print(f"   le passage de rattrapage n'a pas expiré le RDV : {rapport3.expires}")
        return False
    if rapport3.messages_crees or len(rapport3.deja_traites) != 2:
        print(f"   rattrapage : {len(rapport3.messages_crees)} message(s) recréé(s), "
              f"{len(rapport3.deja_traites)} reconnu(s) — le client serait prévenu deux fois")
        return False
    if len(depot.messages()) != avant:
        print("   le rattrapage a dupliqué des messages")
        return False

    # (d bis) crash PENDANT l'enfilage : l'ordre du worker doit garantir que le client
    # finit prévenu. Si l'état terminal était écrit AVANT l'enfilage, le RDV sortirait
    # de la file et le SMS serait perdu définitivement.
    lead_e, rdv_e = _appel_avec_rdv(depot, "R04_changement_commune", LUNDI_9H)
    rdv_e.notifier(LUNDI_9H)
    depot.sauver_rdv(rdv_e)
    vrai_enfiler = depot.enfiler_message

    def enfiler_qui_casse(brouillon, maintenant):
        raise RuntimeError("réseau coupé pendant l'enfilage")

    depot.enfiler_message = enfiler_qui_casse
    rapport_crash = worker.passer(rdv_e.expire_a)
    depot.enfiler_message = vrai_enfiler
    if not rapport_crash.echecs or rapport_crash.expires:
        print(f"   crash à l'enfilage : {rapport_crash} (attendu 1 échec, 0 expiré)")
        return False
    if depot.rdv(rdv_e.id).statut is StatutRdv.EXPIRE:
        print("   l'état a été écrit avant l'enfilage : le SMS du client est perdu")
        return False
    reprise = worker.passer(rdv_e.expire_a)
    if reprise.expires != [rdv_e.id] or len(reprise.messages_crees) != 2:
        print(f"   reprise après crash : expirés={reprise.expires}, "
              f"messages={reprise.messages_crees}")
        return False

    # (e) le worker ne touche pas un RDV validé, même très en retard
    lead_c, rdv_c = _appel_avec_rdv(depot, "R12_commune_avec_ponctuation", LUNDI_9H)
    rdv_c.notifier(LUNDI_9H)
    rdv_c.valider(LUNDI_9H + dt.timedelta(minutes=10))
    depot.sauver_rdv(rdv_c)
    rapport4 = worker.passer(rdv_c.expire_a + dt.timedelta(days=7))
    if rdv_c.id in rapport4.expires:
        print("   le worker a expiré un RDV déjà validé")
        return False
    if depot.rdv(rdv_c.id).statut is not StatutRdv.VALIDE:
        print("   le statut validé n'a pas survécu au passage du worker")
        return False

    # (f) symétrie de la course : un RDV que le worker peut voir n'est plus validable.
    # C'est le garde-fou de rdv.py qui ferme les deux côtés — pas la chance.
    lead_d, rdv_d = _appel_avec_rdv(depot, "R09_commune_sans_cp", LUNDI_9H)
    rdv_d.notifier(LUNDI_9H)
    depot.sauver_rdv(rdv_d)
    if not depot.rdvs_echus(rdv_d.expire_a):
        print("   le RDV échu n'est pas dans la file : cas (f) creux")
        return False
    try:
        depot.rdv(rdv_d.id).valider(rdv_d.expire_a)
        print("   un RDV visible par le worker a pu être validé : course ouverte")
        return False
    except TransitionInterdite:
        pass
    return True


def check_contrat_depot() -> bool:
    """R17 : la suite de CONTRAT du port `Depot`, jouée contre l'implémentation en
    mémoire. La même suite tourne contre Postgres via `run_depot_pg.py` : c'est elle qui
    dira si l'adaptateur est réellement substituable."""
    from contrat_depot import verifier
    ecarts = verifier(DepotMemoire, CFG)
    for e in ecarts:
        print(f"   {e}")
    return not ecarts


def check_conformite_depot() -> bool:
    """R18 : chaque implémentation du port expose la même surface que le Protocol, avec
    les mêmes noms de paramètres (ils sont appelés par mot-clé un peu partout).

    Tourne SANS base : c'est le seul contrôle de l'adaptateur Postgres possible hors
    ligne, et il attrape la dérive la plus courante — une méthode oubliée, renommée, ou
    dont un paramètre a changé de nom d'un côté seulement."""
    import inspect

    from relais_proto.depot import Depot, DepotMemoire as Memoire
    from relais_proto.depot_pg import DepotPostgres

    attendu = {nom: list(inspect.signature(getattr(Depot, nom)).parameters)
               for nom in dir(Depot)
               if not nom.startswith("_") and callable(getattr(Depot, nom))}
    if len(attendu) < 10:
        print(f"   le port ne déclare que {len(attendu)} méthodes : contrôle creux")
        return False

    ok = True
    for impl in (Memoire, DepotPostgres):
        for nom, params in sorted(attendu.items()):
            methode = getattr(impl, nom, None)
            if methode is None:
                print(f"   {impl.__name__} n'implémente pas {nom}()")
                ok = False
                continue
            obtenus = list(inspect.signature(methode).parameters)
            if obtenus != params:
                print(f"   {impl.__name__}.{nom} : paramètres {obtenus} "
                      f"au lieu de {params}")
                ok = False
    return ok


def check_api_http() -> bool:
    """R19 : l'API HTTP. Quatre propriétés : les deux portes d'authentification ne se
    substituent jamais l'une à l'autre, un tour = une requête sans session en mémoire,
    un artisan ne voit rien de ce qui appartient à un autre, et la course
    validation/expiration remonte en 409."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("   fastapi/httpx absents : pip install -r requirements.txt")
        return False

    from relais_proto.api import creer_app
    from relais_proto.registre import Artisan, Registre, empreinte

    TOK_A, TOK_B, SECRET = "tok-dupont", "tok-martin", "secret-voix"
    NUM_A, NUM_B = "+33189701234", "01 89 70 56 78"   # formats volontairement différents
    registre = Registre([Artisan("art-dupont", NUM_A, empreinte(TOK_A), CFG),
                         Artisan("art-martin", NUM_B, empreinte(TOK_B), CFG)],
                        empreinte(SECRET))
    depot = DepotMemoire()
    pendule = [LUNDI_9H]                              # horloge que le test fait avancer

    def cli():
        """Une app NEUVE à chaque requête : seul le dépôt est partagé. Si l'API gardait le
        moindre état conversationnel en mémoire, l'appel ne pourrait pas se poursuivre."""
        return TestClient(creer_app(depot, registre, MockLLM, lambda: pendule[0]))

    voix = {"X-Relais-Secret": SECRET}
    art_a = {"Authorization": f"Bearer {TOK_A}"}
    art_b = {"Authorization": f"Bearer {TOK_B}"}
    ouvrir = {"numero_appele": NUM_A}

    # (a) les deux portes sont étanches, dans les deux sens
    matrice = [
        ("POST", "/webhooks/appel", {}, 401, "webhook sans secret"),
        ("POST", "/webhooks/appel", {"X-Relais-Secret": TOK_A}, 401,
         "token artisan accepté comme secret webhook"),
        ("POST", "/webhooks/appel", {"Authorization": f"Bearer {TOK_A}"}, 401,
         "webhook ouvert par un simple token artisan"),
        ("GET", "/rdv", {}, 401, "boîte de validation sans token"),
        ("GET", "/rdv", {"Authorization": f"Bearer {SECRET}"}, 401,
         "secret webhook accepté comme token artisan"),
        ("GET", "/sante", {}, 200, "la santé devrait rester ouverte"),
    ]
    for methode, url, entetes, attendu, libelle in matrice:
        r = (cli().post(url, json=ouvrir, headers=entetes) if methode == "POST"
             else cli().get(url, headers=entetes))
        if r.status_code != attendu:
            print(f"   auth · {libelle} : {r.status_code} au lieu de {attendu}")
            return False

    # (b) référence en process, pour comparer mot pour mot ce que dit l'API
    ref = Conversation(CFG, MockLLM(), CalendarStub(CFG, now=LUNDI_9H))
    attendus = [ref.open()]
    for ligne in SCENARIOS["T01_urgence_fuite"]["lignes"]:
        if ref.state.value in ("S11", "FIN"):
            break
        attendus.append(ref.process(ligne))

    r = cli().post("/webhooks/appel", json=ouvrir, headers=voix)
    if r.status_code != 200 or r.json()["texte"] != attendus[0]:
        print(f"   ouverture : {r.status_code} / {r.json()}")
        return False
    appel_id = r.json()["appel_id"]

    rdv_id, i = None, 1
    for ligne in SCENARIOS["T01_urgence_fuite"]["lignes"]:
        r = cli().post(f"/webhooks/appel/{appel_id}/tour", json={"texte": ligne},
                       headers=voix)
        if r.status_code != 200:
            print(f"   tour {i} : {r.status_code} {r.text[:120]}")
            return False
        corps = r.json()
        if corps["texte"] != attendus[i]:
            print(f"   tour {i} diverge de la référence en process :\n"
                  f"     HTTP    = {corps['texte']!r}\n     process = {attendus[i]!r}")
            return False
        i += 1
        if corps["termine"]:
            rdv_id = corps["rdv_id"]
            break
    if rdv_id is None:
        print("   l'appel HTTP ne s'est pas terminé sur un RDV")
        return False

    # un tour de plus sur un appel clôturé : 409, pas un second lead
    if cli().post(f"/webhooks/appel/{appel_id}/tour", json={"texte": "allô ?"},
                  headers=voix).status_code != 409:
        print("   un appel clôturé accepte encore des tours")
        return False

    # (c) la boîte de validation, et l'étanchéité entre artisans
    r = cli().get("/rdv", headers=art_a)
    boite = r.json()
    if len(boite) != 1 or boite[0]["id"] != rdv_id:
        print(f"   boîte de validation de Dupont : {boite}")
        return False
    if boite[0]["statut"] != "en_attente_validation" or boite[0]["lead"]["score"] != 5:
        print(f"   carte de validation incomplète : statut={boite[0]['statut']}, "
              f"score={boite[0]['lead']['score']}")
        return False
    if boite[0]["lead"]["contrat"] != 1:
        print("   le contrat de la carte lead n'est pas versionné dans la réponse")
        return False
    if cli().get("/rdv", headers=art_b).json():
        print("   Martin voit les RDV de Dupont")
        return False
    if cli().post(f"/rdv/{rdv_id}/valider", headers=art_b).status_code != 404:
        print("   Martin peut valider un RDV de Dupont")
        return False

    # (d) validation par le bon artisan
    r = cli().post(f"/rdv/{rdv_id}/valider", headers=art_a)
    if r.status_code != 200 or r.json()["statut"] != "valide":
        print(f"   validation : {r.status_code} {r.text[:120]}")
        return False
    if cli().get("/rdv", headers=art_a).json():
        print("   un RDV validé reste dans la boîte de validation")
        return False
    if cli().post(f"/rdv/{rdv_id}/valider", headers=art_a).status_code != 409:
        print("   un RDV déjà validé accepte une seconde décision")
        return False

    # (e) la course validation/expiration remonte en 409 côté HTTP
    r = cli().post("/webhooks/appel", json=ouvrir, headers=voix)
    appel2 = r.json()["appel_id"]
    rdv2 = None
    for ligne in SCENARIOS["R11_dispo_samedi_respectee"]["lignes"]:
        corps = cli().post(f"/webhooks/appel/{appel2}/tour", json={"texte": ligne},
                           headers=voix).json()
        if corps["termine"]:
            rdv2 = corps["rdv_id"]
            break
    if rdv2 is None:
        print("   second appel : pas de RDV")
        return False
    pendule[0] = LUNDI_9H + dt.timedelta(days=2)      # l'échéance est passée
    r = cli().post(f"/rdv/{rdv2}/valider", headers=art_a)
    if r.status_code != 409:
        print(f"   valider après échéance : {r.status_code}, attendu 409")
        return False
    pendule[0] = LUNDI_9H

    # (f) identifiants inconnus : 404, jamais 500
    absent = "00000000-0000-0000-0000-000000000000"
    for url, entetes in ((f"/webhooks/appel/{absent}/tour", voix),
                         (f"/rdv/{absent}/valider", art_a)):
        if cli().post(url, json={"texte": "x"}, headers=entetes).status_code != 404:
            print(f"   {url} ne rend pas 404 sur un identifiant absent")
            return False
    # numéro Relais inconnu : 404 et non 500
    if cli().post("/webhooks/appel", json={"numero_appele": "+33100000000"},
                  headers=voix).status_code != 404:
        print("   un numéro Relais inconnu ne rend pas 404")
        return False
    return True


def check_expedition() -> bool:
    """R20 : l'expédition des messages sortants — plage de silence, réessais, échec
    définitif. La règle qui compte : depuis que les délais sont en heures réelles, une
    échéance peut tomber à 3 h du matin ; on ne réveille pas le client d'un artisan."""
    from relais_proto.envoi import (EnvoyeurJournal, Expediteur,
                                    heure_d_envoi_autorisee)
    from relais_proto.messages import Brouillon, Canal, StatutMessage

    def brouillon(cle: str, dest: Destinataire,
                  artisan: str = "art-dupont") -> Brouillon:
        return Brouillon(cle_idempotence=cle, destinataire=dest,
                         canal=Canal.SMS if dest is Destinataire.CLIENT else Canal.PUSH,
                         cible="0612345678", texte="texte de test", artisan_id=artisan)

    # (a) la plage 21h–08h traverse minuit : c'est le piège, un ET au lieu d'un OU la
    # rendrait vide. Et elle ne concerne QUE le client.
    jour = dt.date(2026, 8, 24)
    cas = [
        (Destinataire.CLIENT, dt.time(3, 0), dt.datetime.combine(jour, dt.time(8, 0))),
        (Destinataire.CLIENT, dt.time(7, 59), dt.datetime.combine(jour, dt.time(8, 0))),
        (Destinataire.CLIENT, dt.time(21, 0),
         dt.datetime.combine(jour + dt.timedelta(days=1), dt.time(8, 0))),
        (Destinataire.CLIENT, dt.time(23, 30),
         dt.datetime.combine(jour + dt.timedelta(days=1), dt.time(8, 0))),
        (Destinataire.CLIENT, dt.time(8, 0), None),      # None = tout de suite
        (Destinataire.CLIENT, dt.time(20, 59), None),
        # l'artisan est un professionnel qui a choisi ses horaires : jamais différé
        (Destinataire.ARTISAN, dt.time(3, 0), None),
    ]
    for dest, heure, attendu in cas:
        t = dt.datetime.combine(jour, heure)
        msg = MessageSortant(id="m", cle_idempotence="k", destinataire=dest,
                             canal=Canal.SMS, cible="06", texte="t", cree_a=t)
        obtenu = heure_d_envoi_autorisee(msg, CFG, t)
        vise = attendu or t
        if obtenu != vise:
            print(f"   plage · {dest.value} à {heure} : {obtenu}, attendu {vise}")
            return False

    # (b) envoi nominal, en pleine journée
    depot = DepotMemoire()
    journal = EnvoyeurJournal()
    expediteur = Expediteur(depot, journal, cfg_pour)
    midi = dt.datetime.combine(jour, dt.time(12, 0))
    m_client, _ = depot.enfiler_message(brouillon("r20:client", Destinataire.CLIENT), midi)
    rapport = expediteur.passer(midi)
    if rapport.envoyes != [m_client.id] or len(journal.envoyes) != 1:
        print(f"   envoi nominal : {rapport}")
        return False
    envoye = depot.messages(StatutMessage.ENVOYE)
    if len(envoye) != 1 or not envoye[0].reference:
        print("   le message envoyé n'a pas d'accusé fournisseur")
        return False
    # deuxième passage : rien à renvoyer (le statut sort le message de la file)
    if expediteur.passer(midi + dt.timedelta(minutes=1)) or len(journal.envoyes) != 1:
        print("   un message déjà envoyé est renvoyé au passage suivant")
        return False

    # (c) 3 h du matin : le SMS client attend 8 h, le push artisan part tout de suite
    depot2 = DepotMemoire()
    journal2 = EnvoyeurJournal()
    exp2 = Expediteur(depot2, journal2, cfg_pour)
    nuit = dt.datetime.combine(jour, dt.time(3, 0))
    mc, _ = depot2.enfiler_message(brouillon("r20:nuit-client", Destinataire.CLIENT), nuit)
    ma, _ = depot2.enfiler_message(brouillon("r20:nuit-artisan", Destinataire.ARTISAN), nuit)
    rapport = exp2.passer(nuit)
    if rapport.envoyes != [ma.id] or rapport.differes != [mc.id]:
        print(f"   3 h du matin : envoyés={rapport.envoyes}, différés={rapport.differes}")
        return False
    if [m.destinataire for m in journal2.envoyes] != [Destinataire.ARTISAN]:
        print("   un SMS client est parti en pleine nuit")
        return False
    # à 8 h, le client reçoit enfin
    rapport = exp2.passer(dt.datetime.combine(jour, dt.time(8, 0)))
    if rapport.envoyes != [mc.id]:
        print(f"   à 8 h le SMS client n'est pas parti : {rapport}")
        return False

    # (d) réessais puis échec définitif — un échec transitoire ne perd pas le message
    class EnvoyeurEnPanne:
        def envoyer(self, message, cfg):
            raise ConnectionError("fournisseur injoignable")

    depot3 = DepotMemoire()
    exp3 = Expediteur(depot3, EnvoyeurEnPanne(), cfg_pour)
    m3, _ = depot3.enfiler_message(brouillon("r20:panne", Destinataire.CLIENT), midi)
    essais_max = CFG["sms"]["essais_max"]
    for tour in range(1, essais_max + 1):
        rapport = exp3.passer(midi)
        relu = next(m for m in depot3.messages() if m.id == m3.id)
        dernier = tour == essais_max
        if relu.essais != tour:
            print(f"   réessai {tour} : essais = {relu.essais}")
            return False
        if dernier and (rapport.echecs != [m3.id]
                        or relu.statut is not StatutMessage.ECHEC):
            print(f"   au {essais_max}e essai le message devrait être en échec : {relu.statut}")
            return False
        if not dernier and (rapport.reessais != [m3.id]
                            or relu.statut is not StatutMessage.A_ENVOYER):
            print(f"   essai {tour} : le message devrait rester en file ({relu.statut})")
            return False
    if exp3.passer(midi + dt.timedelta(hours=1)):
        print("   un message en échec définitif est encore réessayé")
        return False
    if not next(m for m in depot3.messages() if m.id == m3.id).derniere_erreur:
        print("   l'erreur du fournisseur n'est pas visible pour le monitoring")
        return False

    # (d bis) DEUX artisans, DEUX plages de silence : c'est tout l'objet de la migration
    # 004. Avant elle, l'expéditeur appliquait la plage du premier aux clients de tous.
    CFG_NUIT = {**CFG, "sms": {**CFG["sms"], "plage_silence": None}}   # artisan de nuit

    def cfg_deux(artisan_id):
        return {"art-dupont": CFG, "art-nuit": CFG_NUIT}.get(artisan_id)

    depot_m = DepotMemoire()
    journal_m = EnvoyeurJournal()
    m_jour, _ = depot_m.enfiler_message(
        brouillon("r20:jour", Destinataire.CLIENT, "art-dupont"), nuit)
    m_nuit, _ = depot_m.enfiler_message(
        brouillon("r20:nuit", Destinataire.CLIENT, "art-nuit"), nuit)
    m_inconnu, _ = depot_m.enfiler_message(
        brouillon("r20:inconnu", Destinataire.CLIENT, "art-fantome"), nuit)
    rapport = Expediteur(depot_m, journal_m, cfg_deux).passer(nuit)
    if rapport.differes != [m_jour.id]:
        print(f"   multi-artisans : différés={rapport.differes}, attendu [{m_jour.id}] "
              f"(seul Dupont a une plage de silence)")
        return False
    if rapport.envoyes != [m_nuit.id]:
        print(f"   multi-artisans : envoyés={rapport.envoyes}, attendu [{m_nuit.id}]")
        return False
    # un artisan inconnu n'est PAS deviné : le message reste en file, l'anomalie est visible
    if len(rapport.echecs) != 1 or m_inconnu.id not in rapport.echecs[0]:
        print(f"   artisan inconnu : {rapport.echecs}, attendu 1 échec sur {m_inconnu.id}")
        return False
    if [m.id for m in journal_m.envoyes] != [m_nuit.id]:
        print("   un message a été envoyé avec la config d'un autre artisan")
        return False

    # (e) la chaîne complète : expiration à 3 h du matin → client différé, artisan prévenu
    depot4 = DepotMemoire()
    journal4 = EnvoyeurJournal()
    lead4, rdv4 = _appel_avec_rdv(depot4, "T01_urgence_fuite", nuit)
    rdv4.notifier(nuit)
    depot4.sauver_rdv(rdv4)
    WorkerExpiration(depot4, cfg_pour).passer(rdv4.expire_a)
    rapport = Expediteur(depot4, journal4, cfg_pour).passer(rdv4.expire_a)
    if len(rapport.differes) != 1 or len(rapport.envoyes) != 1:
        print(f"   chaîne complète à 3 h : {rapport}")
        return False
    if journal4.envoyes[0].destinataire is not Destinataire.ARTISAN:
        print("   la chaîne a réveillé le client")
        return False
    return True


def check_confirmation_lien() -> bool:
    """R21 : reproposition par l'artisan + validation du client par LIEN (remplace le
    « Répondez OUI » de la spec §3.5bis). Le jeton est la seule authentification du client :
    imprévisible, stocké en empreinte, à usage unique, et l'échéance lui est opposée."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("   fastapi/httpx absents : pip install -r requirements.txt")
        return False

    from relais_proto.api import creer_app
    from relais_proto.confirmation import empreinte
    from relais_proto.registre import Artisan, Registre, empreinte as emp_token

    TOK_A, TOK_B, SECRET = "tok-dupont", "tok-martin", "secret-voix"
    BASE = "https://relais.test"
    registre = Registre([Artisan("art-dupont", "+33189701234", emp_token(TOK_A), CFG),
                         Artisan("art-martin", "+33189705678", emp_token(TOK_B), CFG)],
                        emp_token(SECRET))
    depot = DepotMemoire()
    pendule = [LUNDI_9H]

    def cli():
        return TestClient(creer_app(depot, registre, MockLLM, lambda: pendule[0],
                                    base_url=BASE))

    art_a = {"Authorization": f"Bearer {TOK_A}"}
    art_b = {"Authorization": f"Bearer {TOK_B}"}

    lead, rdv = _appel_avec_rdv(depot, "T01_urgence_fuite", LUNDI_9H)
    rdv.notifier(LUNDI_9H)
    depot.sauver_rdv(rdv)
    nouveau = {"date": "2026-08-26", "de": "14:00", "a": "16:00"}

    # (a) étanchéité et validation d'entrée
    if cli().post(f"/rdv/{rdv.id}/reproposer", json=nouveau, headers=art_b).status_code != 404:
        print("   Martin peut reproposer un créneau sur un RDV de Dupont")
        return False
    if cli().post(f"/rdv/{rdv.id}/reproposer", json=nouveau).status_code != 401:
        print("   reproposer sans token n'est pas refusé")
        return False
    r = cli().post(f"/rdv/{rdv.id}/reproposer",
                   json={**nouveau, "date": "26/08/2026"}, headers=art_a)
    if r.status_code != 422:
        print(f"   date mal formée : {r.status_code}, attendu 422")
        return False

    # (b) reproposition nominale. L'horloge avance d'une heure AVANT : sinon la remise à
    # zéro de l'échéance est invisible (même instant → même valeur) et le test ne prouve
    # rien. On épingle ensuite la valeur exacte, pas une inégalité.
    pendule[0] = LUNDI_9H + dt.timedelta(hours=1)
    r = cli().post(f"/rdv/{rdv.id}/reproposer", json=nouveau, headers=art_a)
    if r.status_code != 200 or r.json()["statut"] != "repropose":
        print(f"   reproposer : {r.status_code} {r.text[:150]}")
        return False
    if r.json()["creneau"]["label"] != "mercredi 26/08 entre 14h et 16h":
        print(f"   libellé du créneau reproposé : {r.json()['creneau']['label']!r}")
        return False
    # l'échéance repart de zéro : c'est le client qu'on attend maintenant, il n'hérite pas
    # du temps déjà consommé par l'artisan. T01 est urgent → 2 h réelles depuis MAINTENANT.
    attendue = pendule[0] + dt.timedelta(hours=CFG["validation"]["delai_max_urgence_heures"])
    obtenue = dt.datetime.fromisoformat(r.json()["expire_a"])
    if obtenue != attendue:
        print(f"   échéance après reproposition : {obtenue}, attendu {attendue} "
              f"(remise à zéro depuis l'instant de la reproposition)")
        return False
    # le créneau précédent est conservé dans l'audit
    if not any("creneau_precedent" in h for h in depot.rdv(rdv.id).historique):
        print("   le créneau précédent n'est pas tracé dans l'historique")
        return False

    # (c) le SMS porte le lien, et le jeton n'existe en clair NULLE PART en base
    sms = [m for m in depot.messages() if m.destinataire is Destinataire.CLIENT]
    if len(sms) != 1 or f"{BASE}/c/" not in sms[0].texte:
        print(f"   SMS de reproposition : {[m.texte for m in sms]}")
        return False
    jeton = sms[0].texte.split(f"{BASE}/c/")[1].strip()
    if len(jeton) < 32:
        print(f"   jeton trop court ({len(jeton)}) : énumérable")
        return False
    stocke = depot.rdv(rdv.id)
    if stocke.confirmation_sha256 != empreinte(jeton) or jeton in str(stocke.to_dict()):
        print("   le jeton est stocké en clair, ou son empreinte ne correspond pas")
        return False
    if not check_output(sms[0].texte, CFG) == []:
        print(f"   le SMS de reproposition viole un garde-fou : {check_output(sms[0].texte, CFG)}")
        return False

    # (d) la page client ne révèle RIEN sur la personne
    r = cli().get(f"/c/{jeton}")
    if r.status_code != 200:
        print(f"   page de confirmation : {r.status_code} {r.text[:120]}")
        return False
    vu = r.text
    for secret in (lead.donnees["slots"]["telephone_rappel"], "transcript"):
        if secret in vu:
            print(f"   la page client expose « {secret} »")
            return False
    if r.json()["entreprise"] != CFG["entreprise"]["nom"]:
        print("   la page client n'indique pas l'entreprise")
        return False
    if cli().get("/c/jeton-invente-de-toutes-pieces").status_code != 404:
        print("   un jeton inventé ne rend pas 404")
        return False

    # (e) validation par le client
    r = cli().post(f"/c/{jeton}")
    if r.status_code != 200 or r.json()["statut"] != "valide":
        print(f"   validation client : {r.status_code} {r.text[:150]}")
        return False
    if depot.rdv(rdv.id).statut is not StatutRdv.VALIDE:
        print("   le RDV n'est pas validé en base")
        return False
    if not [m for m in depot.messages() if m.destinataire is Destinataire.ARTISAN
            and "validé" in m.texte]:
        print("   l'artisan n'est pas prévenu de la validation")
        return False
    # usage unique : le lien ne resservira pas
    if cli().post(f"/c/{jeton}").status_code != 404 \
            or cli().get(f"/c/{jeton}").status_code != 404:
        print("   le lien de confirmation est réutilisable")
        return False
    if cli().get("/rdv", headers=art_a).json():
        print("   un RDV validé par le client reste dans la boîte de validation")
        return False

    # (f) un lien dont l'échéance est passée est refusé, même avec le bon jeton
    lead2, rdv2 = _appel_avec_rdv(depot, "R11_dispo_samedi_respectee", LUNDI_9H)
    rdv2.notifier(LUNDI_9H)
    depot.sauver_rdv(rdv2)
    cli().post(f"/rdv/{rdv2.id}/reproposer", json=nouveau, headers=art_a)
    sms2 = [m for m in depot.messages()
            if m.destinataire is Destinataire.CLIENT and m.id != sms[0].id]
    jeton2 = sms2[0].texte.split(f"{BASE}/c/")[1].strip()
    pendule[0] = LUNDI_9H + dt.timedelta(days=3)
    r = cli().post(f"/c/{jeton2}")
    if r.status_code != 409:
        print(f"   lien périmé : {r.status_code}, attendu 409")
        return False
    # et un client qui ne répond jamais finit par expirer comme les autres
    if not depot.rdvs_echus(pendule[0]):
        print("   un RDV reproposé sans réponse sort de la file du worker")
        return False
    pendule[0] = LUNDI_9H
    return True


def check_adaptateur_ovh() -> bool:
    """R22 : l'adaptateur OVH. Ce qui est testé ici est ce qui est RÉELLEMENT à nous —
    format E.164, corps de requête, classification des échecs. La signature de requête est
    déléguée au SDK officiel et n'est donc pas de notre ressort.

    ⚠️ La forme de réponse attendue (`ids`, `invalidReceivers`) est une HYPOTHÈSE tant
    qu'aucun envoi réel n'a eu lieu : ces doubles disent ce que je crois, pas ce qui est."""
    from relais_proto.envoi import EchecDefinitif, EchecEnvoi, Expediteur, StatutMessage
    from relais_proto.envoi_ovh import EnvoyeurOVH, en_e164
    from relais_proto.messages import Brouillon, Canal

    # (a) mise au format : nous stockons « 0612345678 », OVH veut « +33612345678 »
    for entree, attendu in (("06 12 34 56 78", "+33612345678"),
                            ("0612345678", "+33612345678"),
                            ("+33612345678", "+33612345678"),
                            ("0033612345678", "+33612345678"),
                            ("07.88.11.22.33", "+33788112233")):
        if en_e164(entree) != attendu:
            print(f"   E.164 · {entree!r} → {en_e164(entree)!r}, attendu {attendu!r}")
            return False
    for mauvais in ("123", "", "abc", "06123456789012345678"):
        try:
            en_e164(mauvais)
        except EchecDefinitif:
            continue
        print(f"   E.164 · {mauvais!r} accepté alors qu'il est inexploitable")
        return False

    msg = MessageSortant(id="m1", cle_idempotence="k1", destinataire=Destinataire.CLIENT,
                         canal=Canal.SMS, cible="06 12 34 56 78",
                         texte="Bonjour, votre créneau a changé.", cree_a=LUNDI_9H,
                         artisan_id="art-dupont")

    # (b) corps de la requête
    vus = []

    def transport_ok(chemin, **corps):
        vus.append((chemin, corps))
        return {"ids": [42], "validReceivers": corps["receivers"], "invalidReceivers": []}

    ref = EnvoyeurOVH(transport_ok, "sms-ab12345-1").envoyer(msg, CFG)
    chemin, corps = vus[0]
    if chemin != "/sms/sms-ab12345-1/jobs":
        print(f"   chemin appelé : {chemin}")
        return False
    if corps["receivers"] != ["+33612345678"]:
        print(f"   destinataire non normalisé : {corps['receivers']}")
        return False
    if corps["sender"] != CFG["sms"]["expediteur"]:
        print(f"   expéditeur : {corps['sender']!r}, attendu la config artisan")
        return False
    if corps.get("noStopClause") is not True:
        print("   noStopClause absent : la clause STOP mangerait 20 caractères utiles "
              "sur un SMS transactionnel qui n'en a pas besoin")
        return False
    if corps["message"] != msg.texte or ref != "ovh:42":
        print(f"   message ou référence : {corps['message']!r} / {ref!r}")
        return False

    # (c) classification des échecs — c'est là que se joue le comportement du worker
    def transport_refuse(chemin, **corps):
        return {"ids": [], "validReceivers": [], "invalidReceivers": corps["receivers"]}

    def transport_vide(chemin, **corps):
        return {"ids": [], "validReceivers": corps["receivers"], "invalidReceivers": []}

    def transport_reseau(chemin, **corps):
        raise ConnectionError("getaddrinfo failed")

    cas = [(transport_refuse, EchecDefinitif, "destinataire refusé"),
           (transport_vide, EchecEnvoi, "aucun identifiant rendu"),
           (transport_reseau, EchecEnvoi, "panne réseau")]
    for transport, attendu, libelle in cas:
        try:
            EnvoyeurOVH(transport, "sms-ab12345-1").envoyer(msg, CFG)
        except attendu as exc:
            # EchecDefinitif hérite d'EchecEnvoi : pour les cas transitoires il faut
            # vérifier que ce n'est PAS un définitif, sinon le test ne distingue rien
            if attendu is EchecEnvoi and isinstance(exc, EchecDefinitif):
                print(f"   {libelle} classé définitif alors qu'il est réessayable")
                return False
            continue
        except Exception as autre:
            print(f"   {libelle} : levé {type(autre).__name__}, attendu {attendu.__name__}")
            return False
        print(f"   {libelle} : rien levé")
        return False

    cfg_sans_expediteur = {**CFG, "sms": {k: v for k, v in CFG["sms"].items()
                                          if k != "expediteur"}}
    try:
        EnvoyeurOVH(transport_ok, "sms-ab12345-1").envoyer(msg, cfg_sans_expediteur)
        print("   expéditeur manquant accepté")
        return False
    except EchecDefinitif:
        pass

    # (d) intégration : un échec DÉFINITIF sort de la file au PREMIER passage, sans
    # consommer les trois tentatives — sinon on retarde toute la file pour un numéro faux
    depot = DepotMemoire()
    brouillon = Brouillon(cle_idempotence="r22:faux", destinataire=Destinataire.CLIENT,
                          canal=Canal.SMS, cible="pas-un-numero", texte="test",
                          artisan_id="art-dupont")
    m, _ = depot.enfiler_message(brouillon, LUNDI_9H)
    midi = dt.datetime(2026, 8, 24, 12, 0)
    rapport = Expediteur(depot, EnvoyeurOVH(transport_ok, "sms-ab12345-1"),
                         cfg_pour).passer(midi)
    if rapport.echecs != [m.id]:
        print(f"   numéro invalide : {rapport}, attendu un échec définitif immédiat")
        return False
    relu = next(x for x in depot.messages() if x.id == m.id)
    if relu.statut is not StatutMessage.ECHEC or relu.essais != 1:
        print(f"   numéro invalide : statut={relu.statut.value}, essais={relu.essais} "
              f"(attendu echec dès le 1er essai)")
        return False
    if not relu.derniere_erreur or "inexploitable" not in relu.derniere_erreur:
        print(f"   la raison n'est pas exploitable en monitoring : {relu.derniere_erreur!r}")
        return False

    # (e) et un échec TRANSITOIRE consomme bien ses trois tentatives
    depot2 = DepotMemoire()
    m2, _ = depot2.enfiler_message(
        Brouillon(cle_idempotence="r22:reseau", destinataire=Destinataire.CLIENT,
                  canal=Canal.SMS, cible="0612345678", texte="test",
                  artisan_id="art-dupont"), LUNDI_9H)
    exp = Expediteur(depot2, EnvoyeurOVH(transport_reseau, "sms-ab12345-1"), cfg_pour)
    for tour in range(1, CFG["sms"]["essais_max"] + 1):
        exp.passer(midi)
    relu2 = next(x for x in depot2.messages() if x.id == m2.id)
    if relu2.essais != CFG["sms"]["essais_max"] \
            or relu2.statut is not StatutMessage.ECHEC:
        print(f"   panne réseau : essais={relu2.essais}, statut={relu2.statut.value}")
        return False
    return True


def check_guard_prix() -> bool:
    """T05 (garde-fou prix) : on injecte une réplique fautive et on vérifie l'interception."""
    from relais_proto.guards import check_output
    fautive = "Pour un débouchage comptez environ 180 € en général."
    v = check_output(fautive, CFG)
    ok = any(x.startswith("prix_non_autorise") for x in v)
    autorisee = "Le déplacement avec diagnostic est à 90 € TTC, déduits si vous faites les travaux."
    ok = ok and not check_output(autorisee, CFG)
    confirme = "C'est confirmé, à demain !"
    ok = ok and any(x == "confirmation_avant_validation" for x in check_output(confirme, CFG))
    return ok


def run() -> int:
    echecs = 0
    for nom, sc in SCENARIOS.items():
        convo = Conversation(CFG, MockLLM())
        print(f"\n──── {nom} ────")
        print(f"🤖 {convo.open()}")
        for ligne in sc["lignes"]:
            if convo.state.value in ("S11", "FIN"):
                break
            print(f"👤 {ligne}")
            print(f"🤖 {convo.process(ligne)}")
        lead = build_lead(convo)
        att = sc["attendu"]
        ok = (lead["score"] == att["score"]
              and lead["categorie"] == att["categorie"]
              and bool(lead["rdv"]) == att["rdv"]
              and not lead["violations_gardes_fous"]
              and lead["slots"].get("telephone_rappel", None) == att.get(
                  "tel", lead["slots"].get("telephone_rappel", None))
              and lead["slots"].get("code_postal", None) == att.get(
                  "cp", lead["slots"].get("code_postal", None)))
        if "texte_agent" in att:  # une réplique de l'agent doit contenir ce texte
            paroles_agent = " ".join(t for who, t in lead["transcript"] if who == "agent")
            ok = ok and att["texte_agent"] in paroles_agent
        print(f"   → score {lead['score']}/5, {lead['categorie']}, "
              f"rdv={'oui' if lead['rdv'] else 'non'} : {'✅ PASS' if ok else '❌ FAIL'}")
        if not ok:
            echecs += 1
            print(f"   attendu : {att}")

    print(f"\n──── T05_garde_fou_prix ────")
    if check_guard_prix():
        print("   → interception prix interdit + 'confirmé' + passage prix autorisé : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R08_panne_llm_totale ────")
    if check_panne_llm():
        print("   → LLM en panne dès le 1er tour : appel abouti en mode scripté, "
              "RDV pris, dégradations tracées : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R14_serialisation_etat ────")
    if check_serialisation():
        print(f"   → {len(SCENARIOS) + 3} scénarios rejoués avec aller-retour JSON à chaque "
              "tour (process neuf) : leads identiques, version d'état contrôlée : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R15_cycle_vie_rdv ────")
    if check_cycle_vie_rdv():
        print("   → graphe de transitions complet, délais 24 h/2 h réelles + mode ouvrées, "
              "course validation-vs-expiration, T01 de bout en bout en dépôt : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R16_worker_expiration ────")
    if check_worker_expiration():
        print("   → créneau libéré, lead en alerte, SMS de repli + relance artisan, "
              "idempotence sur passage interrompu, course artisan fermée : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R17_contrat_depot ────")
    if check_contrat_depot():
        print("   → port Depot : aller-retour exact, files filtrées, idempotence de la "
              "file sortante (contre DepotMemoire) : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R18_conformite_adaptateurs ────")
    if check_conformite_depot():
        print("   → DepotMemoire et DepotPostgres exposent la surface du port, "
              "mêmes noms de paramètres : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R19_api_http ────")
    if check_api_http():
        print("   → deux portes d'auth étanches, T01 rejoué en HTTP (un tour = une "
              "requête, app neuve à chaque fois), étanchéité entre artisans, "
              "409 sur échéance dépassée : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R20_expedition_sms ────")
    if check_expedition():
        print("   → plage de silence 21h–08h (client seulement, à cheval sur minuit), "
              "réessais, échec définitif, config résolue PAR artisan, chaîne "
              "expiration→envoi à 3 h : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R21_confirmation_par_lien ────")
    if check_confirmation_lien():
        print("   → reproposition artisan, jeton imprévisible et stocké en empreinte, "
              "page client sans donnée personnelle, usage unique, lien périmé refusé : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R22_adaptateur_ovh ────")
    if check_adaptateur_ovh():
        print("   → format E.164, corps de requête (noStopClause), échec définitif "
              "immédiat vs transitoire réessayé : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n{'✅ Tous les smoke tests passent' if not echecs else f'❌ {echecs} échec(s)'}")
    return echecs


if __name__ == "__main__":
    sys.exit(run())
