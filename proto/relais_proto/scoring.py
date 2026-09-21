"""Lead + scoring 0–5 post-appel (docs/script-conversation-v1.md §3).

Chaque score est accompagné de raisons AFFICHABLES : c'est la carte lead du dashboard.
"""
from __future__ import annotations

from . import temps


def build_lead(convo) -> dict:
    s, f = convo.slots, convo.flags
    score, raisons = _score(s, f)
    return {
        # instant UTC, comme tout le reste : cette date sert à trier des leads entre eux,
        # pas à être lue telle quelle. L'affichage la convertira (cf. temps.en_local).
        "horodatage": temps.maintenant().isoformat(timespec="seconds"),
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


def est_urgent(slots: dict) -> bool:
    """Une urgence RÉELLE, et pas seulement une demande présentée comme urgente.

    Les deux conditions comptent : l'appelant a décrit une urgence (`intent`) ET elle a
    été confirmée (`urgence_reelle`). Extrait de `_score` le 21/09 parce que la page
    « Mes appels » doit signaler les mêmes appels comme urgents que le score — deux
    copies de cette règle finiraient par diverger, et l'écart se lirait comme un bug du
    score alors qu'il serait un bug de l'affichage.
    """
    return bool(slots.get("urgence_reelle")) and slots.get("intent") == "urgence"


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
    urgent = est_urgent(s)

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
