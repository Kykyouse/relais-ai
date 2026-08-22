#!/usr/bin/env python3
"""Exploration manuelle automatisée : je joue l'appelant sur les 6 cas non couverts."""
import json, pathlib
from relais_proto.engine import Conversation
from relais_proto.llm import MockLLM
from relais_proto.scoring import build_lead

CFG = json.loads(pathlib.Path("config/dupont.json").read_text(encoding="utf-8"))

CAS = {
    "A_tout_d_un_coup": [
        "Fuite urgente, je suis Garcia à Nogent 94130, mon numéro c'est 06 12 34 56 78, dispo cet après-midi",
        "Oui c'est bien ça",
        "Le premier",
    ],
    "B_changement_commune": [
        "Bonjour j'ai une fuite, c'est urgent, ça coule",
        "94130",
        "Ah non pardon, en fait c'est chez ma mère, à Créteil, 94000",
        "Bernard, 06 11 22 33 44",
        "Oui",
        "Le premier",
    ],
    "B2_changement_vers_hors_zone": [
        "Bonjour j'ai une fuite, c'est urgent, ça coule",
        "94130",
        "Ah non pardon, c'est chez ma mère à Champigny, 94500",
    ],
    "C_gaz": [
        "Bonjour, ça sent le gaz près de la chaudière, je m'inquiète",
    ],
    "D_veut_humain": [
        "Je veux parler à Julien s'il vous plaît",
        "Non, je veux vraiment parler à Julien, pas à une machine",
    ],
    "E_silence": ["...", "..."],
    "F_deuxieme_creneau": [
        "fuite urgente ça coule",
        "94130",
        "Martin, 06 11 22 33 44",
        "Oui",
        "Plutôt le second",
    ],
}

for nom, lignes in CAS.items():
    convo = Conversation(CFG, MockLLM())
    print(f"\n════ {nom} ════")
    print(f"🤖 {convo.open()}")
    for l in lignes:
        if convo.state.value in ("S11", "FIN"):
            break
        print(f"👤 {l}")
        print(f"🤖 {convo.process(l)}")
    lead = build_lead(convo)
    print(f"   ⇒ score {lead['score']}/5 · {lead['categorie']} · zone={lead['zone']} · "
          f"rdv={'oui' if lead['rdv'] else 'non'} · slots CP={lead['slots'].get('code_postal')}")
