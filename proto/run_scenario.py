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
from zoneinfo import ZoneInfo

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
    maintenant = heure_fr(2026, 8, 24, 9, 0)
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


PARIS = ZoneInfo("Europe/Paris")


def heure_fr(annee: int, mois: int, jour: int, h: int = 0, mn: int = 0, *,
             fold: int = 0) -> dt.datetime:
    """L'INSTANT (en UTC) correspondant à une heure de PENDULE française.

    Les tests décrivent ce que voient l'artisan et le client — « vendredi 17 h », « 3 h du
    matin » — jamais des offsets : c'est le niveau auquel les règles produit sont écrites.
    La conversion vers l'instant se fait ici, une fois, et pas dans chaque cas de test.

    `fold=1` désigne la SECONDE occurrence d'une heure répétée (nuit du retour à l'heure
    d'hiver). C'est le seul moyen de distinguer deux instants qui portent la même pendule,
    donc d'écrire le cas (e) de R25.
    """
    return dt.datetime(annee, mois, jour, h, mn,
                       tzinfo=PARIS, fold=fold).astimezone(dt.UTC)


def heure_fr_le(jour: dt.date, heure: dt.time) -> dt.datetime:
    """Même chose depuis une date et une heure déjà construites."""
    return heure_fr(jour.year, jour.month, jour.day, heure.hour, heure.minute)


LUNDI_9H = heure_fr(2026, 8, 24, 9, 0)  # horloge de référence des tests RDV (heure locale)


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
        (False, heure_fr(2026, 8, 24, 9, 0), heure_fr(2026, 8, 25, 9, 0)),
        (False, heure_fr(2026, 8, 28, 17, 0), heure_fr(2026, 8, 29, 17, 0)),
        (True, heure_fr(2026, 8, 30, 20, 0), heure_fr(2026, 8, 30, 22, 0)),
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
        ("lundi 09:00 (en pleine fenêtre)", heure_fr(2026, 8, 24, 9, 0),
         heure_fr(2026, 8, 24, 13, 0)),
        ("lundi 07:00 (avant ouverture)", heure_fr(2026, 8, 24, 7, 0),
         heure_fr(2026, 8, 24, 12, 0)),
        ("lundi 17:00 (déborde sur mardi)", heure_fr(2026, 8, 24, 17, 0),
         heure_fr(2026, 8, 25, 11, 0)),
        ("vendredi 17:00 (déborde sur samedi court)", heure_fr(2026, 8, 28, 17, 0),
         heure_fr(2026, 8, 29, 12, 0)),
        ("samedi 12:00 (dimanche fermé, saute au lundi)", heure_fr(2026, 8, 29, 12, 0),
         heure_fr(2026, 8, 31, 11, 0)),
        ("dimanche 10:00 (jour fermé)", heure_fr(2026, 8, 30, 10, 0),
         heure_fr(2026, 8, 31, 12, 0)),
    ]
    for libelle, depuis, attendu in cas_ouvrees:
        obtenu = calculer_expiration(cfg_ouvrees, urgence=False, depuis=depuis)
        if obtenu != attendu:
            print(f"   heures ouvrées · {libelle} : {obtenu} au lieu de {attendu}")
            return False

    # l'urgence reste en heures RÉELLES même en mode "ouvrees" : une fuite prise dimanche
    # 20 h n'attend pas l'ouverture du lundi, sinon le mot urgence ne veut plus rien dire
    urgent = calculer_expiration(cfg_ouvrees, urgence=True,
                                 depuis=heure_fr(2026, 8, 30, 20, 0))
    if urgent != heure_fr(2026, 8, 30, 22, 0):
        print(f"   urgence en mode ouvrées : {urgent}, attendu dimanche 22:00 (réelles)")
        return False

    # les mêmes règles traversées par Rdv.depuis_hold, à une heure où les deux modes
    # DIVERGENT (vendredi 17 h) : 24 h réelles → samedi 17 h ; 4 h ouvrées → samedi 12 h ;
    # urgence → vendredi 19 h dans les deux modes.
    vendredi_17h = heure_fr(2026, 8, 28, 17, 0)
    hold_nu = {"date": "2026-09-01", "de": "08:00", "a": "10:00", "urgence": False,
               "label": "mardi 01/09 entre 08h et 10h", "duree_min": 90}
    cas_hold = [
        (CFG, None, heure_fr(2026, 8, 29, 17, 0)),
        (CFG, True, heure_fr(2026, 8, 28, 19, 0)),
        (cfg_ouvrees, None, heure_fr(2026, 8, 29, 12, 0)),
        (cfg_ouvrees, True, heure_fr(2026, 8, 28, 19, 0)),
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
    if rdv2.expire_a != heure_fr(2026, 8, 25, 9, 0):  # 24 h réelles depuis lundi 9 h
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
        (Destinataire.CLIENT, dt.time(3, 0), heure_fr_le(jour, dt.time(8, 0))),
        (Destinataire.CLIENT, dt.time(7, 59), heure_fr_le(jour, dt.time(8, 0))),
        (Destinataire.CLIENT, dt.time(21, 0),
         heure_fr_le(jour + dt.timedelta(days=1), dt.time(8, 0))),
        (Destinataire.CLIENT, dt.time(23, 30),
         heure_fr_le(jour + dt.timedelta(days=1), dt.time(8, 0))),
        (Destinataire.CLIENT, dt.time(8, 0), None),      # None = tout de suite
        (Destinataire.CLIENT, dt.time(20, 59), None),
        # l'artisan est un professionnel qui a choisi ses horaires : jamais différé
        (Destinataire.ARTISAN, dt.time(3, 0), None),
    ]
    for dest, heure, attendu in cas:
        t = heure_fr_le(jour, heure)
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
    midi = heure_fr_le(jour, dt.time(12, 0))
    m_client, _ = depot.enfiler_message(brouillon("r20:client", Destinataire.CLIENT), midi)
    rapport = expediteur.passer(midi)
    if rapport.envoyes != [m_client.id] or len(journal.envoyes) != 1:
        print(f"   envoi nominal : {rapport}")
        return False
    envoye = depot.messages(StatutMessage.ENVOYE)
    if len(envoye) != 1 or not envoye[0].reference:
        print("   le message envoyé n'a pas d'accusé fournisseur")
        return False
    # le coût est PERSISTÉ par message : c'est ce qui permettra de chiffrer la dépense SMS
    # par artisan et par mois. La donnée ne repasse jamais.
    if envoye[0].cout != 1 or rapport.cout_total != 1:
        print(f"   coût non persisté : message={envoye[0].cout!r}, "
              f"passage={rapport.cout_total!r}")
        return False
    # deuxième passage : rien à renvoyer (le statut sort le message de la file)
    if expediteur.passer(midi + dt.timedelta(minutes=1)) or len(journal.envoyes) != 1:
        print("   un message déjà envoyé est renvoyé au passage suivant")
        return False

    # (c) 3 h du matin : le SMS client attend 8 h, le push artisan part tout de suite
    depot2 = DepotMemoire()
    journal2 = EnvoyeurJournal()
    exp2 = Expediteur(depot2, journal2, cfg_pour)
    nuit = heure_fr_le(jour, dt.time(3, 0))
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
    rapport = exp2.passer(heure_fr_le(jour, dt.time(8, 0)))
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
    LABEL_NOUVEAU = "mercredi 26/08 entre 14h et 16h"
    LABEL_ANCIEN = rdv.creneau["label"]          # celui d'avant la reproposition
    if r.json()["creneau"]["label"] != LABEL_NOUVEAU:
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
    # 16 octets d'aléa -> 22 caractères base64url, soit 128 bits : hors de portée d'une
    # énumération pour un jeton à usage unique et borné dans le temps. Le seuil est là pour
    # attraper une réduction accidentelle, pas pour exiger 32 octets.
    if len(jeton) < 22:
        print(f"   jeton trop court ({len(jeton)} caractères) : énumérable")
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
    if "text/html" not in r.headers.get("content-type", ""):
        print(f"   la page client n'est pas du HTML : "
              f"{r.headers.get('content-type')!r} — un client ne lit pas du JSON")
        return False
    for attendu in ("<!DOCTYPE html>", 'lang="fr"', "viewport",
                    CFG["entreprise"]["nom"], LABEL_NOUVEAU, "<form",
                    'method="post"'):
        if attendu not in vu:
            print(f"   la page client ne contient pas {attendu!r}")
            return False
    # et surtout PAS l'ancien créneau : montrer au client celui qu'on remplace serait
    # une vraie confusion, pas un détail d'affichage
    if LABEL_ANCIEN in vu:
        print(f"   la page client affiche l'ANCIEN créneau ({LABEL_ANCIEN!r})")
        return False
    # aucune ressource externe : rien qui échoue sur un réseau de chantier, rien qui
    # piste l'appelant d'un artisan
    for interdit in ("http://", "https://fonts", "<script"):
        if interdit in vu:
            print(f"   la page client charge une ressource externe : {interdit!r}")
            return False
    for secret in (lead.donnees["slots"]["telephone_rappel"], "transcript"):
        if secret in vu:
            print(f"   la page client expose « {secret} »")
            return False
    r404 = cli().get("/c/jeton-invente-de-toutes-pieces")
    if r404.status_code != 404 or "n'est plus valide" not in r404.text:
        print(f"   jeton inventé : {r404.status_code}, page = {r404.text[:80]!r}")
        return False

    # (e) validation par le client
    r = cli().post(f"/c/{jeton}")
    if r.status_code != 200 or "confirmé" not in r.text:
        print(f"   validation client : {r.status_code} {r.text[:150]}")
        return False
    if depot.rdv(rdv.id).statut is not StatutRdv.VALIDE:
        print("   le RDV n'est pas validé en base")
        return False
    if not [m for m in depot.messages() if m.destinataire is Destinataire.ARTISAN
            and "validé" in m.texte]:
        print("   l'artisan n'est pas prévenu de la validation")
        return False
    # Usage unique : le lien ne resservira pas. Mais le client qui recharge sa page après
    # avoir validé doit être RASSURÉ, pas inquiété — le même texte sert au lien inconnu.
    apres = cli().get(f"/c/{jeton}")
    if apres.status_code != 404 or "c'est bien pris en compte" not in apres.text:
        print(f"   rechargement après validation : {apres.status_code}, le message ne "
              f"rassure pas le client : {apres.text[:90]!r}")
        return False
    if cli().post(f"/c/{jeton}").status_code != 404:
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
    if r.status_code != 409 or "plus disponible" not in r.text:
        print(f"   lien périmé (POST) : {r.status_code}, page = {r.text[:80]!r}")
        return False
    # en simple consultation : 410 Gone, avec une page qui explique la suite
    r = cli().get(f"/c/{jeton2}")
    if r.status_code != 410 or "recontacte" not in r.text:
        print(f"   lien périmé (GET) : {r.status_code}, page = {r.text[:80]!r}")
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
        """Réponse calquée sur celle RÉELLEMENT reçue d'OVH le 24/08 (réf. ovh:802084252),
        champs non anticipés compris. Ce double n'est plus une hypothèse : c'est une
        observation."""
        vus.append((chemin, corps))
        return {"ids": [802084252], "validReceivers": corps["receivers"],
                "invalidReceivers": [], "totalCreditsRemoved": 1, "creditsLeft": 99,
                "tag": "vtbnzoi6prvylh12"}

    envoi = EnvoyeurOVH(transport_ok, "sms-ab12345-1").envoyer(msg, CFG)
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
    if corps["message"] != msg.texte or envoi.reference != "ovh:802084252":
        print(f"   message ou référence : {corps['message']!r} / {envoi.reference!r}")
        return False
    # `totalCreditsRemoved` était jeté : c'est le coût de CET envoi, la seule donnée qui
    # permettra de chiffrer la dépense SMS par artisan (elle ne repasse jamais).
    if envoi.cout != 1:
        print(f"   coût de l'envoi non remonté : {envoi.cout!r}, attendu 1")
        return False

    cfg_sans_expediteur = {**CFG, "sms": {k: v for k, v in CFG["sms"].items()
                                          if k != "expediteur"}}
    try:
        EnvoyeurOVH(transport_ok, "sms-ab12345-1").envoyer(msg, cfg_sans_expediteur)
        print("   expéditeur manquant accepté en mode normal")
        return False
    except EchecDefinitif:
        pass

    # (b bis) mode NUMÉRO COURT : `senderForResponse` remplace `sender`, et les deux sont
    # mutuellement exclusifs côté OVH. Permet de tester sans attendre la déclaration d'un
    # Sender ID (~72 h, avec risque de refus).
    vus.clear()
    EnvoyeurOVH(transport_ok, "sms-ab12345-1", numero_court=True).envoyer(msg, CFG)
    _, corps = vus[0]
    if corps.get("senderForResponse") is not True:
        print(f"   numéro court : senderForResponse absent ({corps.get('senderForResponse')!r})")
        return False
    if "sender" in corps:
        print(f"   numéro court : la clé « sender » est présente ({corps['sender']!r}) — "
              f"OVH refuse les deux ensemble")
        return False
    # le mode fonctionne même sans expéditeur configuré : c'est tout son intérêt
    if EnvoyeurOVH(transport_ok, "sms-ab12345-1", numero_court=True).envoyer(
            msg, cfg_sans_expediteur).reference != "ovh:802084252":
        print("   numéro court : bloqué par l'absence d'expéditeur, alors qu'il s'en passe")
        return False

    # GARDE : une URL en numéro court est bloquée par l'opérateur. Le cœur du produit
    # étant un lien de validation, ce garde-fou empêche un SMS silencieusement jeté.
    msg_lien = MessageSortant(
        id="m2", cle_idempotence="k2", destinataire=Destinataire.CLIENT, canal=Canal.SMS,
        cible="0612345678", texte="Validez ici : https://relais.test/c/abc",
        cree_a=LUNDI_9H, artisan_id="art-dupont")
    try:
        EnvoyeurOVH(transport_ok, "sms-ab12345-1", numero_court=True).envoyer(msg_lien, CFG)
        print("   numéro court : un message contenant une URL a été accepté — "
              "il serait jeté par l'opérateur sans erreur visible")
        return False
    except EchecDefinitif:
        pass
    # en revanche le mode NORMAL doit accepter ce même message : c'est le cas de prod
    if not EnvoyeurOVH(transport_ok, "sms-ab12345-1").envoyer(msg_lien, CFG):
        print("   mode normal : le lien de validation devrait passer")
        return False

    # La réserve de crédits est lue dans la réponse : une réserve épuisée arrête TOUS les
    # SMS clients sans erreur applicative. Sans cette capture, la panne ne serait visible
    # que par un client qui n'a rien reçu.
    envoyeur = EnvoyeurOVH(transport_ok, "sms-ab12345-1")
    if envoyeur.credits_restants is not None:
        print("   les crédits ne devraient pas être renseignés avant tout envoi")
        return False
    envoyeur.envoyer(msg, CFG)
    if envoyeur.credits_restants != 99:
        print(f"   réserve de crédits non captée : {envoyeur.credits_restants!r}")
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

    # (d) intégration : un échec DÉFINITIF sort de la file au PREMIER passage, sans
    # consommer les trois tentatives — sinon on retarde toute la file pour un numéro faux
    depot = DepotMemoire()
    brouillon = Brouillon(cle_idempotence="r22:faux", destinataire=Destinataire.CLIENT,
                          canal=Canal.SMS, cible="pas-un-numero", texte="test",
                          artisan_id="art-dupont")
    m, _ = depot.enfiler_message(brouillon, LUNDI_9H)
    midi = heure_fr(2026, 8, 24, 12, 0)
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

    # (d bis) le DIAGNOSTIC des erreurs, sur les messages RÉELLEMENT reçus d'OVH le 24/08.
    # Cette fonction s'est trompée trois fois de suite avant d'être mise sous test : deux
    # motifs manquants, puis un motif générique masquant un motif spécifique. Les entrées
    # ci-dessous sont des observations, pas des inventions.
    from relais_proto.envoi_ovh import diagnostic
    reels = [
        # celui-ci était diagnostiqué « nom de service faux » : « does not exist » masquait
        # « sender ». C'est LE cas qui a motivé l'ordre du plus spécifique au plus générique.
        ("APIError: Sms sender DupontChauf does not exists. Please create it first",
         "EXPÉDITEUR"),
        ("EchecEnvoi: ResourceNotFoundError: This service does not exist", "SERVICE SMS"),
        ("NotGrantedCall: This call has not been granted", "PORTÉE"),
        ("InvalidKey: This application key is invalid", "IDENTIFIANTS"),
    ]
    for message_ovh, attendu in reels:
        obtenu = diagnostic(message_ovh)
        if attendu not in obtenu:
            print(f"   diagnostic · {message_ovh[:48]!r}\n"
                  f"     attendu une piste « {attendu} », obtenu : {obtenu[:70]}")
            return False
    # un motif inconnu doit tout de même orienter, pas répondre « je ne sais pas »
    repli = diagnostic("PouetError: quelque chose de neuf")
    if "probabilité" not in repli or "Query-ID" not in repli:
        print(f"   le repli du diagnostic n'oriente pas : {repli[:80]}")
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


def check_cout_sms() -> bool:
    """R23 : le coût d'un SMS est une propriété du CODE, pas une fatalité.

    Un segment = un crédit facturé. Deux façons de payer double sans s'en apercevoir :
    dépasser 160 caractères, ou glisser **un seul** caractère hors de l'alphabet GSM-7 —
    la limite tombe alors à 70. Le 24/08, le « ô » de « plutôt » coûtait 3 segments au SMS
    de reproposition.

    Ce test exige une MARGE, pas seulement « ça tient » : la longueur dépend de données par
    artisan (nom de l'entreprise, prénom du patron) et d'un libellé de créneau variable. Un
    gabarit pile à 160 repasserait à 2 segments au premier artisan au nom un peu long, sans
    que personne ne le voie."""
    from relais_proto.envoi import segments_sms
    from relais_proto.messages import TEMPLATES

    # Deux exigences DISTINCTES, et c'est le point :
    #  · GSM-7 pour TOUS les gabarits — gratuit, et ça protège les push qui deviendront
    #    peut-être des SMS de repli (prévu pour l'artisan sans app) ;
    #  · un seul segment pour les seuls gabarits réellement envoyés PAR SMS, c'est-à-dire
    #    ceux destinés au client. Un push n'a pas de limite de longueur : lui imposer 160
    #    caractères serait une contrainte inventée.
    # Convention de nommage : un gabarit « *_client » part en SMS.
    MARGE_MIN = 5    # petit tampon : le libellé de créneau varie de quelques caractères
    # Valeurs de rendu volontairement plus longues que la config de référence : un artisan
    # au nom à rallonge ne doit pas doubler la facture.
    # Ces valeurs définissent l'ENVELOPPE SUPPORTÉE, pas un cas pathologique : au-delà,
    # le SMS coûtera deux crédits. À faire respecter à l'onboarding si besoin.
    LONG = {
        "nom_entreprise": "Plomberie du Val-de-Marne",   # 25 car. (Dupont Chauffage : 16)
        "prenom": "Jean-Christophe",                     # 15 car. (Julien : 6)
        "creneau": "mercredi 26/08 entre 14h et 16h",    # le libellé le plus long possible
        "client": "Van Der Berghe",
        "commune": "Saint-Maur-des-Fossés",
        "telephone": "0612345678",
        # base publique + jeton de 16 octets (22 car.). Un domaine long coûte des crédits :
        # c'est une raison concrète de choisir une racine courte.
        "lien": "https://relais.app/c/" + "x" * 22,
    }

    ok = True
    for cle, gabarit in TEMPLATES.items():
        rendu = gabarit.format(**{k: v for k, v in LONG.items() if "{" + k + "}" in gabarit})
        segments, encodage = segments_sms(rendu)
        limite = 70 if encodage == "UCS-2" else 160
        marge = limite - len(rendu)
        if encodage != "GSM-7":
            hors = sorted({c for c in rendu if segments_sms(c)[1] == "UCS-2"})
            print(f"   {cle} : encodage {encodage} à cause de {hors} → limite 70 au lieu "
                  f"de 160. Remplacer ces caractères (é è ù ì ò à sont légaux, pas ê ô À).")
            ok = False
            continue
        if not cle.endswith("_client"):
            continue          # push : pas de facturation au segment
        if segments != 1:
            print(f"   {cle} : {len(rendu)} caractères = {segments} segments, donc "
                  f"{segments} crédits par envoi")
            ok = False
        elif marge < MARGE_MIN:
            print(f"   {cle} : tient en 1 segment mais marge de {marge} caractères "
                  f"seulement (minimum {MARGE_MIN}) — un artisan au nom plus long "
                  f"doublerait le coût sans alerte")
            ok = False

    # le calcul lui-même doit être juste, sinon le test ci-dessus ne prouve rien
    for texte, attendu in (("a" * 160, (1, "GSM-7")), ("a" * 161, (2, "GSM-7")),
                           ("a" * 70 + "ô", (2, "UCS-2")), ("ô", (1, "UCS-2")),
                           ("é" * 160, (1, "GSM-7"))):
        if segments_sms(texte) != attendu:
            print(f"   segments_sms({texte[:6]}…, {len(texte)} car.) = "
                  f"{segments_sms(texte)}, attendu {attendu}")
            ok = False
    return ok


def check_app_artisan() -> bool:
    """R24 : la boîte de validation dans un NAVIGATEUR — session par cookie, pages HTML,
    aucun JavaScript. C'est « LA fonction » de la spec §6 : sans elle, personne ne peut
    déclencher une reproposition autrement qu'avec curl."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("   fastapi/httpx absents : pip install -r requirements.txt")
        return False

    from relais_proto.api import creer_app
    from relais_proto.registre import Artisan, Registre, empreinte as emp_token
    from relais_proto.session import NOM_COOKIE

    TOK_A, TOK_B = "tok-dupont", "tok-martin"
    registre = Registre([Artisan("art-dupont", "+33189701234", emp_token(TOK_A), CFG),
                         Artisan("art-martin", "+33189705678", emp_token(TOK_B), CFG)],
                        emp_token("secret-voix"))
    depot = DepotMemoire()
    pendule = [LUNDI_9H]
    # cookie_secure=False : les tests parlent en HTTP, un cookie Secure ne serait pas
    # renvoyé. En production il reste à True.
    app = creer_app(depot, registre, MockLLM, lambda: pendule[0],
                    base_url="https://relais.test", cookie_secure=False)

    lead, rdv = _appel_avec_rdv(depot, "T01_urgence_fuite", LUNDI_9H)
    rdv.notifier(LUNDI_9H)
    depot.sauver_rdv(rdv)

    # (a) sans session : la page de connexion, PAS une erreur brute. Un artisan dont la
    # session a expiré doit voir un écran utilisable.
    with TestClient(app) as anonyme:
        r = anonyme.get("/app")
        if r.status_code != 401 or "<form" not in r.text or "Connexion" not in r.text:
            print(f"   /app sans session : {r.status_code}, page = {r.text[:90]!r}")
            return False
        # Le diagnostic doit être DANS la page : sans cookie reçu, la cause la plus
        # probable est l'attribut Secure en HTTP. Deux tours de débogage ont été perdus
        # là-dessus le 24/08 — l'indice est donc verrouillé par ce test.
        if "RELAIS_COOKIE_SECURE" not in r.text or "aucun cookie" not in r.text:
            print("   /app sans cookie ne dit pas quoi vérifier")
            return False
        # avec un cookie inconnu, le diagnostic doit être DIFFÉRENT : session expirée
        anonyme.cookies.set(NOM_COOKIE, "jeton-qui-ne-correspond-a-rien")
        r = anonyme.get("/app")
        if "expirée" not in r.text or "RELAIS_COOKIE_SECURE" in r.text:
            print(f"   cookie inconnu : mauvais diagnostic, {r.text[:110]!r}")
            return False
        anonyme.cookies.clear()
        if anonyme.post("/connexion", data={"jeton": "mauvais"}).status_code != 401:
            print("   un jeton refusé n'est pas rejeté")
            return False

    # (b) connexion, puis le cookie porte tout le reste — sans en-tête Authorization
    with TestClient(app) as julien:
        r = julien.post("/connexion", data={"jeton": TOK_A}, follow_redirects=False)
        if r.status_code != 303 or r.headers.get("location") != "/app":
            print(f"   connexion : {r.status_code} → {r.headers.get('location')!r}")
            return False
        biscuit = julien.cookies.get(NOM_COOKIE)
        if not biscuit or len(biscuit) < 40:
            print(f"   cookie de session absent ou trop court : {biscuit!r}")
            return False
        # le jeton en clair ne doit exister QUE dans le cookie
        from relais_proto.session import empreinte as emp_session
        if not depot._sessions.get(emp_session(biscuit)):
            print("   la session n'est pas enregistrée sous son empreinte")
            return False
        if any(biscuit in str(v) for v in depot._sessions.values()):
            print("   le jeton de session est stocké en clair")
            return False

        r = julien.get("/app")
        if r.status_code != 200:
            print(f"   /app avec session : {r.status_code}")
            return False
        # les valeurs interpolées sont ÉCHAPPÉES dans la page (l'apostrophe de
        # « aujourd'hui » devient &#x27;) : on compare donc à la forme échappée, sinon
        # c'est l'assertion qui est naïve, pas la page qui a tort
        from html import escape as _esc
        for attendu in ("<!DOCTYPE html>", "Julien", _esc(rdv.creneau["label"]), "5/5",
                        "URGENCE", "Valider", "Refuser", 'type="date"'):
            if attendu not in r.text:
                print(f"   la boîte de validation ne contient pas {attendu!r}")
                return False
        if "<script" in r.text or "http://" in r.text:
            print("   la page artisan charge une ressource externe ou du JS")
            return False
        # les raisons du score sont ce qui rend la carte utile : « URGENCE réelle », etc.
        if not any(_esc(m) in r.text for m in lead.donnees["raisons"]):
            print(f"   les raisons du lead n'apparaissent pas : {lead.donnees['raisons']}")
            return False

        # (c) valider depuis la page : POST puis redirection, pour qu'un rechargement
        # ne rejoue pas l'action
        r = julien.post(f"/app/{rdv.id}/valider", follow_redirects=False)
        if r.status_code != 303 or r.headers.get("location") != "/app":
            print(f"   validation depuis la page : {r.status_code}")
            return False
        if depot.rdv(rdv.id).statut is not StatutRdv.VALIDE:
            print(f"   le RDV n'est pas validé : {depot.rdv(rdv.id).statut.value}")
            return False
        if "Aucun rendez-vous en attente" not in julien.get("/app").text:
            print("   la boîte n'est pas vide après validation")
            return False

        # (d) reproposer depuis la page, avec les champs natifs date/heure
        lead2, rdv2 = _appel_avec_rdv(depot, "R11_dispo_samedi_respectee", LUNDI_9H)
        rdv2.notifier(LUNDI_9H)
        depot.sauver_rdv(rdv2)
        r = julien.post(f"/app/{rdv2.id}/reproposer",
                        data={"date": "2026-08-26", "de": "14:00", "a": "16:00"},
                        follow_redirects=False)
        if r.status_code != 303:
            print(f"   reproposition depuis la page : {r.status_code} {r.text[:120]}")
            return False
        sms = [m for m in depot.messages() if m.destinataire is Destinataire.CLIENT]
        if len(sms) != 1 or "https://relais.test/c/" not in sms[0].texte:
            print(f"   le SMS de reproposition n'est pas parti : {[m.texte for m in sms]}")
            return False

        # (e) une action inconnue ne doit pas être devinée
        if julien.post(f"/app/{rdv2.id}/supprimer",
                       follow_redirects=False).status_code != 404:
            print("   une action inconnue n'est pas refusée")
            return False

        # (f) déconnexion : la session est révoquée côté serveur, pas seulement le cookie
        julien.post("/deconnexion", follow_redirects=False)
        if depot._sessions:
            print("   la session survit à la déconnexion côté serveur")
            return False

    # (g) étanchéité : la session de Dupont ne donne rien chez Martin
    with TestClient(app) as martin:
        martin.post("/connexion", data={"jeton": TOK_B})
        page = martin.get("/app").text
        from html import escape as _esc2
        if _esc2(rdv2.creneau["label"]) in page or "Aucun rendez-vous" not in page:
            print("   Martin voit les rendez-vous de Dupont")
            return False

    # (g bis) un RDV ÉCHU mais pas encore traité par le worker : il reste dans la liste
    # (masquer un lead perdu serait pire) mais SANS boutons, et une action dessus rend une
    # PAGE. Constaté en usage réel le 24/08 : un tap donnait 409 en JSON brut sur le
    # téléphone, sur un RDV que la page proposait pourtant de valider.
    with TestClient(app) as julien2:
        julien2.post("/connexion", data={"jeton": TOK_A})
        pendule[0] = rdv2.expire_a + dt.timedelta(hours=1)   # l'échéance est passée
        page = julien2.get("/app").text
        if "Délai dépassé" not in page:
            print("   un RDV échu n'est pas signalé comme tel dans la boîte")
            return False
        if f"/app/{rdv2.id}/valider" in page:
            print("   un RDV échu propose encore un bouton Valider : le tap ne peut "
                  "qu'échouer")
            return False
        r = julien2.post(f"/app/{rdv2.id}/valider", follow_redirects=False)
        if r.status_code != 409:
            print(f"   action sur un RDV échu : {r.status_code}, attendu 409")
            return False
        if "text/html" not in r.headers.get("content-type", "") \
                or "Action impossible" not in r.text or 'href="/app"' not in r.text:
            print(f"   le refus n'est pas une page lisible : "
                  f"{r.headers.get('content-type')!r} {r.text[:80]!r}")
            return False
        pendule[0] = LUNDI_9H

    # /sante expose le réglage : le vérifier depuis le téléphone doit prendre dix secondes
    with TestClient(app) as sonde:
        if sonde.get("/sante").json().get("cookie_secure") is not False:
            print("   /sante n'expose pas le réglage cookie_secure")
            return False

    # (h) les attributs du cookie, lus dans l'EN-TÊTE Set-Cookie et non déduits du
    # comportement du client. `TestClient` n'applique pas `Secure` : un test qui se fie à
    # lui passe sur PC pendant que le téléphone jette le cookie en HTTP et boucle sur le
    # formulaire de connexion. C'est exactement le bug du 24/08 — `serveur.py` ne
    # raccordait pas `cookie_secure`, et rien ne le voyait.
    for secure_voulu in (True, False):
        app_s = creer_app(depot, registre, MockLLM, lambda: pendule[0],
                          cookie_secure=secure_voulu)
        with TestClient(app_s) as c:
            entete = c.post("/connexion", data={"jeton": TOK_A},
                            follow_redirects=False).headers.get("set-cookie", "").lower()
        if ("secure" in entete) is not secure_voulu:
            print(f"   cookie_secure={secure_voulu} : attribut Secure "
                  f"{'absent' if secure_voulu else 'présent'} dans {entete!r}")
            return False
        # ces deux-là ne dépendent d'aucun mode : jamais lisible par un script, et
        # non envoyé sur une requête inter-sites
        for obligatoire in ("httponly", "samesite=lax"):
            if obligatoire not in entete:
                print(f"   cookie sans {obligatoire} : {entete!r}")
                return False
    return True


def check_fuseaux() -> bool:
    """R25 : le temps. Deux natures d'horodatage, qui ne doivent jamais se mélanger.

    * un INSTANT (échéance, création, envoi, session) est un point sur la ligne du temps :
      il vit en UTC, et une durée s'y ajoute en heures RÉELLES ;
    * une HEURE DE PENDULE (plage de silence 21h–08h, heures ouvrées, « demain entre 08h
      et 10h ») n'a de sens que dans le fuseau de l'artisan, et doit y être calculée.

    Ce que ce test verrouille, et qu'aucun test précédent ne pouvait voir parce qu'ils se
    tenaient tous en août : **les deux changements d'heure**. Trouvé en traitant la dette
    n°1 du journal, pas en production — mais la panne était réelle, et de deux sortes.
    """
    from relais_proto import temps
    from relais_proto.envoi import heure_d_envoi_autorisee
    from relais_proto.messages import Canal

    hold_nu = {"date": "2026-04-01", "de": "08:00", "a": "10:00", "urgence": False,
               "label": "mercredi 01/04 entre 08h et 10h", "duree_min": 90}
    lead_nu = {"slots": {"tel_confirme": True, "urgence_reelle": None}}

    # (a) l'horloge du système rend un INSTANT, pas une heure de pendule
    t = temps.maintenant()
    if t.tzinfo is None or t.utcoffset() != dt.timedelta(0):
        print(f"   temps.maintenant() n'est pas un instant UTC : {t!r}")
        return False

    # (b) un instant naïf est REFUSÉ à la frontière du domaine. C'est la propriété qui
    # rend toutes les autres tenables : un chemin oublié plante au lieu de dériver d'une
    # heure en silence, et il plante en test avant de planter en production.
    try:
        Rdv.depuis_hold(hold_nu, id="rdv-naif", lead_id="lead-n", artisan_id="art-t",
                        lead=lead_nu, cfg=CFG,
                        maintenant=dt.datetime(2026, 3, 28, 20, 0))
    except (ValueError, TypeError):
        pass
    else:
        print("   un instant naïf est entré dans le domaine sans protester")
        return False

    # (c) 24 h de délai à travers le PASSAGE À L'HEURE D'ÉTÉ (29/03/2026, 02h → 03h).
    # L'artisan a droit à 24 heures réelles : son échéance tombe donc à 21 h à sa pendule,
    # pas à 20 h. Le calcul naïf en heure locale ne lui en laissait que 23.
    samedi_20h = heure_fr(2026, 3, 28, 20, 0)
    echeance = calculer_expiration(CFG, urgence=False, depuis=samedi_20h)
    if echeance - samedi_20h != dt.timedelta(hours=24):
        print(f"   passage à l'heure d'été : {echeance - samedi_20h} de délai réel "
              f"au lieu de 24 h")
        return False
    if temps.en_local(echeance, CFG).strftime("%d/%m %H:%M") != "29/03 21:00":
        print(f"   24 h réelles depuis samedi 20 h devraient tomber dimanche 21 h à la "
              f"pendule : {temps.en_local(echeance, CFG)}")
        return False

    # (d) le mode "ouvrees" raisonne en heure de PENDULE, et doit continuer de le faire
    # après le changement d'offset : lundi 09:00 + 4 h ouvrées = lundi 13:00 à la pendule.
    cfg_ouvrees_r25 = {**CFG, "validation": {**CFG["validation"],
                                             "base_delai": "ouvrees",
                                             "delai_max_heures": 4}}
    lundi_apres = heure_fr(2026, 3, 30, 9, 0)
    obtenu = calculer_expiration(cfg_ouvrees_r25, urgence=False, depuis=lundi_apres)
    if obtenu != heure_fr(2026, 3, 30, 13, 0):
        print(f"   heures ouvrées après le changement d'heure : "
              f"{temps.en_local(obtenu, CFG)}, attendu lundi 13:00")
        return False

    # (e) LE RETOUR À L'HEURE D'HIVER (25/10/2026) : 02h00 → 02h59 arrive DEUX FOIS.
    # Deux instants portent la même pendule, séparés d'une heure réelle. Une échéance
    # posée à la seconde occurrence ne doit pas être opposée à l'artisan qui tape à la
    # première — sinon on lui vole une heure et une décision valide.
    premier_2h30 = heure_fr(2026, 10, 25, 2, 30, fold=0)
    second_2h30 = heure_fr(2026, 10, 25, 2, 30, fold=1)
    if second_2h30 - premier_2h30 != dt.timedelta(hours=1):
        print("   repère cassé : les deux 2h30 du 25/10 devraient être à 1 h d'écart")
        return False
    rdv_nuit = Rdv(id="rdv-nuit", lead_id="lead-n", artisan_id="art-t",
                   creneau=dict(hold_nu), duree_min=90, urgence=False,
                   cree_a=heure_fr(2026, 10, 25, 0, 30),
                   expire_a=second_2h30, statut=StatutRdv.EN_ATTENTE_VALIDATION)
    if rdv_nuit.est_echu(premier_2h30):
        print("   RDV échu une heure AVANT son échéance (pendule ambiguë du 25/10)")
        return False
    if not rdv_nuit.est_echu(second_2h30):
        print("   RDV pas échu à son échéance exacte")
        return False
    rdv_nuit.valider(premier_2h30)          # la décision de l'artisan doit passer
    if rdv_nuit.statut is not StatutRdv.VALIDE:
        print("   validation refusée dans l'heure répétée alors qu'elle est dans les temps")
        return False

    # et le dépôt doit trancher exactement pareil : c'est lui qui alimente le worker
    depot = DepotMemoire()
    lead_donnees = {**lead_nu, "categorie": "rdv_reserve", "score": 4, "raisons": []}
    minuit_30 = heure_fr(2026, 10, 25, 0, 30)
    appel = depot.ouvrir_appel("art-dupont", minuit_30)
    ref = depot.cloturer_appel(appel.id, lead_donnees, minuit_30)
    rdv_d = depot.creer_rdv(lead_id=ref.id, hold=hold_nu, lead_donnees=lead_donnees,
                            cfg={**CFG, "validation": {**CFG["validation"],
                                                       "delai_max_heures": 2}},
                            maintenant=premier_2h30)
    if depot.rdvs_echus(premier_2h30 + dt.timedelta(minutes=90)):
        print("   rdvs_echus() a sorti un RDV encore dans les temps (heure répétée)")
        return False
    if not depot.rdvs_echus(premier_2h30 + dt.timedelta(hours=2)):
        print("   rdvs_echus() n'a pas vu un RDV échu de 2 h réelles")
        return False

    # (f) l'aller-retour par le dépôt rend le MÊME instant, pas un instant décalé
    relu = depot.rdv(rdv_d.id)
    for champ in ("cree_a", "expire_a"):
        h = getattr(relu, champ)
        if h.tzinfo is None or h.utcoffset() != dt.timedelta(0):
            print(f"   {champ} relu du dépôt n'est pas un instant UTC : {h!r}")
            return False
    if relu.expire_a != rdv_d.expire_a or relu.cree_a != premier_2h30:
        print(f"   aller-retour du dépôt : {relu.expire_a} au lieu de {rdv_d.expire_a}")
        return False
    # un blob écrit AVANT la migration 007 porte une heure locale naïve : elle doit être
    # relue comme telle (Europe/Paris), pas comme de l'UTC — sinon 2 h d'écart silencieux
    ancien = {**rdv_d.to_dict(), "expire_a": "2026-03-29T21:00:00"}
    if Rdv.from_dict(ancien).expire_a != heure_fr(2026, 3, 29, 21, 0):
        print(f"   blob d'avant la migration relu de travers : "
              f"{Rdv.from_dict(ancien).expire_a}")
        return False

    # (g) la plage de silence est une heure de PENDULE : un SMS bloqué à 3 h du matin part
    # à 8 h chez le client, le jour du changement d'heure comme les autres. Calculée en UTC
    # elle l'aurait fait partir à 9 h locale — une heure de retard pour un client qui
    # attend, et 7 h du matin l'autre jour de l'année, ce qui est bien pire.
    for nuit, libelle in ((heure_fr(2026, 10, 25, 3, 0), "retour à l'heure d'hiver"),
                          (heure_fr(2026, 3, 29, 3, 0), "passage à l'heure d'été")):
        msg = MessageSortant(id="m-r25", cle_idempotence="k-r25",
                             destinataire=Destinataire.CLIENT, canal=Canal.SMS,
                             cible="0612345678", texte="t", cree_a=nuit)
        local = temps.en_local(nuit, CFG)
        attendu = heure_fr(local.year, local.month, local.day, 8, 0)
        obtenu = heure_d_envoi_autorisee(msg, CFG, nuit)
        if obtenu != attendu:
            print(f"   plage de silence · {libelle} : {temps.en_local(obtenu, CFG)}, "
                  f"attendu 08:00 à la pendule du client")
            return False

    # (h) un fuseau mal orthographié est refusé au CHARGEMENT du registre. Sans ce
    # contrôle, « Europe/Pari » ne se manifesterait qu'au premier calcul d'heure : en
    # plein appel, chez un artisan donné, un jour donné.
    from relais_proto.registre import Artisan, Registre
    try:
        Registre([Artisan(id="art-faute", numero_relais="+33189700000",
                          token_sha256="0" * 64,
                          config={**CFG, "fuseau": "Europe/Pari"})], "x")
    except RuntimeError:
        pass
    else:
        print("   un fuseau inexistant a été accepté au chargement du registre")
        return False
    return True


def check_extraction_nom() -> bool:
    """R26 : le nom de l'appelant dans `MockLLM`. Traîne depuis le 22/08.

    Deux raisons pour que ça compte plus qu'un détail de test :

    * `MockLLM` n'est pas qu'un double : c'est le **chemin de dégradation en production**
      (`ResilientLLM`). Quand l'API LLM tombe, c'est lui qui extrait. Un nom raté devient
      « un client » dans le push à l'artisan ; un nom FAUX devient « Nogent a validé le
      créneau ».
    * `nom` n'est pas dans `Conversation.OVERWRITABLE` : le premier nom capté est
      **définitif**. Un faux positif au premier tour ne se rattrape pas.

    D'où la règle que ce test verrouille : **dans le doute, pas de nom**. Un « un client »
    est lisible ; un mauvais nom est une erreur qu'on affiche à l'artisan avec aplomb.

    Le correctif NAÏF — ajouter `re.IGNORECASE` à la regex d'origine — est un piège, et
    c'est pour ça que ce test liste autant de contre-exemples : `[A-ZÉÈ]` servait aussi de
    filtre de capitalisation. En insensible à la casse, « Oui c'est bien ça » donne
    nom='bien' et « le créneau c'est parfait » donne nom='parfait' — deux phrases qui sont
    déjà dans les scénarios ci-dessus.
    """
    from relais_proto.llm import MockLLM

    mock = MockLLM()
    question_identite = ("Très bien. À quel nom, et sur quel numéro Julien peut vous "
                         "confirmer le rendez-vous ?")

    # (a) ce qui DOIT donner un nom. La casse n'est pas un critère fiable : un moteur de
    # transcription vocale rend « je m'appelle garcia » aussi bien que « Je m'appelle
    # Garcia ». On s'appuie sur l'introducteur, pas sur la majuscule.
    doit_donner = [
        ("Je m'appelle Garcia, mon numéro c'est 06 12 34 56 78", "Garcia"),
        ("je m'appelle garcia", "garcia"),
        ("Je m'appelle Monsieur Diallo", "Diallo"),
        ("Je m'appelle Mme Lefèvre", "Lefèvre"),
        ("Je m'appelle Dupont-Martin", "Dupont-Martin"),
        ("Je m'appelle Müller", "Müller"),
        ("Mon nom est Garcia", "Garcia"),
        ("Mon nom c'est Bernard", "Bernard"),
        ("C'est Monsieur Diallo", "Diallo"),      # « c'est » AVEC titre : sans ambiguïté
        ("Garcia à l'appareil", "Garcia"),
    ]
    for phrase, attendu in doit_donner:
        obtenu = mock.extract(phrase, {}).get("nom")
        if obtenu != attendu:
            print(f"   nom manqué : {obtenu!r} au lieu de {attendu!r} — « {phrase} »")
            return False

    # (b) ce qui ne doit SURTOUT PAS donner un nom. Les six premières sont des phrases
    # réelles de nos scénarios : c'est exactement là que le correctif naïf déraille.
    ne_doit_pas = [
        "C'est en cours là, ça goutte dans le placard",
        "Oui c'est bien ça",
        "Le premier créneau c'est parfait, je suis chez moi quand vous voulez",
        "c'est urgent",
        "Je suis à Nogent-sur-Marne, 94130, je suis propriétaire",
        "Non je préfère pas donner mon numéro, je rappellerai",
        "C'est Nogent-sur-Marne",                 # une commune n'est pas un nom
        "C'est pour un entretien",
        "C'est Julien qui m'a donné votre numéro",  # « c'est » sans titre : on s'abstient
        "Bonjour, j'ai une fuite sous l'évier, l'eau coule encore, c'est urgent !",
    ]
    for phrase in ne_doit_pas:
        obtenu = mock.extract(phrase, {}).get("nom")
        if obtenu is not None:
            print(f"   faux nom {obtenu!r} inventé sur « {phrase} »")
            return False

    # (c) la réponse DIRECTE à la question d'identité. « Garcia, 06 12 34 56 78 » n'a aucun
    # introducteur : c'est le contexte — l'agent vient de demander le nom — qui le rend
    # lisible. `MockLLM` ignorait complètement le `context` que l'interface lui passe déjà.
    ctx = {"dernier_agent": question_identite}
    for phrase, attendu in [("Garcia, 06 12 34 56 78", "Garcia"),
                            ("Diallo, 07 88 11 22 33", "Diallo"),
                            ("Lefèvre 06 12 34 56 78", "Lefèvre"),
                            ("Garcia", "Garcia")]:       # réponse d'un seul mot
        obtenu = mock.extract(phrase, ctx).get("nom")
        if obtenu != attendu:
            print(f"   réponse à « à quel nom » : {obtenu!r} au lieu de {attendu!r} "
                  f"— « {phrase} »")
            return False
    # ... mais la même question suivie d'un REFUS ne donne pas un nom. Les trois premiers
    # sont arrêtés par la forme (rien ne suit le mot d'ouverture) ; les suivants sont des
    # réponses d'UN SEUL MOT, qui passent la forme et que seul `_PAS_UN_NOM` arrête —
    # c'est ce qui rend ce filet nécessaire et non décoratif.
    for refus in ("Non je préfère pas donner mon numéro, je rappellerai",
                  "Non merci", "je rappellerai plus tard",
                  "Non", "Non,", "Merci", "Bonjour"):
        if mock.extract(refus, ctx).get("nom") is not None:
            print(f"   un refus est pris pour un nom : « {refus} »")
            return False
    # ... et hors de ce contexte, la même phrase ne donne rien : c'est la question de
    # l'agent qui autorise la lecture, pas la forme de la phrase
    if mock.extract("Garcia, 06 12 34 56 78", {}).get("nom") is not None:
        print("   nom lu sans que l'agent l'ait demandé")
        return False

    # (d) le chemin « nom connu » de bout en bout : c'est CE trou que la note du journal
    # signalait. Jusqu'ici tous les leads mock sortaient sans nom, donc tous les messages
    # à l'artisan disaient « un client » — la moitié du gabarit n'était jamais rendue.
    depot = DepotMemoire()
    lead, rdv = _appel_avec_rdv(depot, "T01_urgence_fuite", LUNDI_9H)
    if lead.donnees["slots"].get("nom") != "Garcia":
        print(f"   lead sans nom après un scénario qui le donne : "
              f"{lead.donnees['slots'].get('nom')!r}")
        return False
    texte = messages.relance_artisan(rdv, lead.donnees, CFG).texte
    if "Garcia" not in texte or "un client" in texte:
        print(f"   relance artisan : « {texte} »")
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
              "immédiat vs transitoire réessayé, mode numéro court (URL bloquée), "
              "diagnostic sur les erreurs réelles d'OVH : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R23_cout_sms ────")
    if check_cout_sms():
        print("   → tous les gabarits en GSM-7 et en 1 seul segment, avec marge, même "
              "avec un artisan au nom long : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R24_app_artisan ────")
    if check_app_artisan():
        print("   → session par cookie, boîte de validation en HTML sans JS, valider et "
              "reproposer depuis le navigateur, étanchéité entre artisans : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R25_fuseaux ────")
    if check_fuseaux():
        print("   → instants en UTC et instant naïf refusé, 24 h réelles à travers "
              "le passage à l'heure d'été, heure répétée du 25/10 sans décision "
              "volée, plage de silence à la pendule du client, fuseau invalide "
              "refusé au chargement : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n──── R26_extraction_nom ────")
    if check_extraction_nom():
        print("   → nom capté quels que soient la casse, le titre et les accents, aucun "
              "faux nom sur « c'est » nu, réponse directe à la question d'identité, "
              "chemin « nom connu » exercé de bout en bout : ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    print(f"\n{'✅ Tous les smoke tests passent' if not echecs else f'❌ {echecs} échec(s)'}")
    return echecs


if __name__ == "__main__":
    sys.exit(run())
