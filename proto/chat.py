#!/usr/bin/env python3
"""CLI du prototype : tu joues l'appelant, l'agent répond.

Usage :
    python chat.py                 # LLM Anthropic si ANTHROPIC_API_KEY est défini, sinon mock
    python chat.py --mock          # force le mode mock (sans réseau)
    python chat.py --config config/dupont.json

Commandes en cours d'appel : tape "..." pour simuler un silence, Ctrl+C ou "bye" pour raccrocher.
À la fin de l'appel : le LEAD produit (score, raisons, RDV, violations) s'affiche en JSON.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

try:
    from dotenv import load_dotenv
    # override=True : le .env du repo fait foi (une variable Windows résiduelle ne le masque pas)
    load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env", override=True)
except ImportError:
    pass

from relais_proto.engine import Conversation
from relais_proto.llm import make_llm
from relais_proto.scoring import build_lead
from relais_proto.states import State


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/dupont.json")
    ap.add_argument("--mock", action="store_true", help="forcer le LLM mock (sans clé API)")
    args = ap.parse_args()

    cfg = json.loads(pathlib.Path(args.config).read_text(encoding="utf-8"))
    llm = make_llm(mock=args.mock)
    convo = Conversation(cfg, llm)

    print(f"[mode LLM : {type(llm).__name__}]  — Ctrl+C ou 'bye' pour raccrocher\n")
    print(f"🤖 {convo.open()}")

    try:
        while convo.state not in (State.S11_CLOTURE, State.FIN):
            user = input("👤 ")
            if user.strip().lower() in ("bye", "quit", "exit"):
                break
            print(f"🤖 {convo.process(user)}")
    except (KeyboardInterrupt, EOFError):
        print("\n[appel interrompu]")

    lead = build_lead(convo)
    print("\n" + "=" * 60)
    print(f"LEAD — score {lead['score']}/5 · {lead['categorie']}")
    for r in lead["raisons"]:
        print(f"  · {r}")
    if lead["rdv"]:
        print(f"  RDV tampon : {lead['rdv']['label']} ({lead['rdv']['duree_min']} min, "
              f"{lead['rdv']['statut']})")
    if lead["violations_gardes_fous"]:
        print(f"  ⚠ violations interceptées : {lead['violations_gardes_fous']}")
    if lead["degradations_llm"]:
        print(f"  ⚠ mode dégradé (LLM indisponible) : {lead['degradations_llm']}")
    print("=" * 60)
    out = pathlib.Path("last_lead.json")
    out.write_text(json.dumps(lead, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"(lead complet écrit dans {out})")


if __name__ == "__main__":
    sys.exit(main())
