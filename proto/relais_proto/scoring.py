"""Lead + scoring 0–5 post-appel (docs/script-conversation-v1.md §3).

Chaque score est accompagné de raisons AFFICHABLES : c'est la carte lead du dashboard.
"""
from __future__ import annotations

import datetime as dt


def build_lead(convo) -> dict:
    s, f = convo.slots, convo.flags
    score, raisons = _score(s, f)
    return {
        "horodatage": dt.datetime.now().isoformat(timespec="seconds"),
        "source": "appel_telephonique",
        "base_legale": "demande_entrante",   # loi 11/08/2026 : consentement tracé
        "categorie": f["categorie"] or "autre",
        "zone": f["zone"],
        "score": score,
        "raisons": raisons,
        "slots": {k: v for k, v in s.items() if v is not None},
        "rdv": f["hold"],
        "violations_gardes_fous": f["violations"],
        "degradations_llm": list(getattr(convo.llm, "degradations", [])),
        "transcript": convo.transcript,
    }


def _score(s: dict, f: dict) -> tuple[int, list[str]]:
    raisons: list[str] = []
    if f["categorie"] in ("hors_zone", "hors_perimetre", "spam"):
        return 0, [f["categorie"].replace("_", " ")]

    if s.get("probleme"):
        raisons.append(s["probleme"])
    if s.get("commune") or s.get("code_postal"):
        raisons.append(s.get("commune") or s["code_postal"])
    if s.get("statut_occupant"):
        raisons.append(s["statut_occupant"])
    if s.get("disponibilites"):
        raisons.append(f"dispo : {s['disponibilites']}")

    coords = bool(s.get("telephone_rappel"))
    rdv = f["hold"] is not None
    urgent = bool(s.get("urgence_reelle")) and s.get("intent") == "urgence"

    if rdv and urgent and coords:
        raisons.insert(0, "URGENCE réelle")
        return 5, raisons
    if rdv:
        raisons.insert(0, "RDV réservé (en attente de validation)")
        return 4, raisons
    if s.get("prestation") and f["zone"] in ("en_zone", "limitrophe") and coords:
        return 3, raisons
    if coords:
        return 2, raisons
    return 1, raisons
