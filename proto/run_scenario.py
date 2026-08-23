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

from relais_proto.calendar_stub import CalendarStub
from relais_proto.engine import Conversation
from relais_proto.llm import MockLLM, ResilientLLM
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

    print(f"\n{'✅ Tous les smoke tests passent' if not echecs else f'❌ {echecs} échec(s)'}")
    return echecs


if __name__ == "__main__":
    sys.exit(run())
