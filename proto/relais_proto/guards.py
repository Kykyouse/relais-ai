"""Garde-fous appliqués EN CODE sur chaque sortie de l'agent.

Principe (invariants du script v0.1) : on ne fait pas confiance au prompt.
Chaque réplique générée passe ici AVANT d'être prononcée. En cas de violation,
l'appelant reçoit une formulation sûre de repli et la violation est loggée.
"""
from __future__ import annotations

import re

# montants en euros : "90 €", "90€", "90 euros", "entre 80 et 120 €"
_RE_PRIX = re.compile(r"\b(\d{1,6})\s*(?:€|euros?\b)", re.IGNORECASE)
_RE_CONFIRME = re.compile(r"\bc'?est\s+confirmé\b|\bje\s+(?:vous\s+)?confirme\b|\bconfirmé\s*[.!]", re.IGNORECASE)
_MOTS_DIAGNOSTIC = [
    "c'est sûrement", "c'est probablement", "ça doit être le", "il faut remplacer",
]


def check_output(text: str, config: dict, rdv_valide: bool = False) -> list[str]:
    """Retourne la liste des violations détectées dans une réplique candidate."""
    violations: list[str] = []

    # 1. Prix : seuls les montants de la liste blanche peuvent apparaître
    prix_autorises = {str(t["prix_ttc"]) for t in config["tarifs"]["communicables"]}
    prix_autorises.add("0 800 47 33 33".replace(" ", ""))  # jamais matché, sécurité
    for m in _RE_PRIX.finditer(text):
        if m.group(1) not in prix_autorises:
            violations.append(f"prix_non_autorise:{m.group(0)}")

    # 2. "Confirmé" interdit tant que l'artisan n'a pas validé
    if not rdv_valide and _RE_CONFIRME.search(text):
        violations.append("confirmation_avant_validation")

    # 3. Diagnostic technique improvisé
    low = text.lower()
    for mot in _MOTS_DIAGNOSTIC:
        if mot in low:
            violations.append(f"diagnostic_improvise:{mot}")

    return violations


SAFE_FALLBACKS = {
    "prix": ("Pour le tarif, ça dépend vraiment de ce que {prenom} constatera sur place — "
             "je préfère ne pas vous annoncer un chiffre faux."),
    "generique": "Je préfère laisser {prenom} vous répondre précisément là-dessus.",
}


def safe_fallback(violations: list[str], config: dict) -> str:
    prenom = config["entreprise"]["prenom_patron"]
    if any(v.startswith("prix") for v in violations):
        return SAFE_FALLBACKS["prix"].format(prenom=prenom)
    return SAFE_FALLBACKS["generique"].format(prenom=prenom)
