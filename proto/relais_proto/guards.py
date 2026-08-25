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

# Caractères qu'une SYNTHÈSE VOCALE ne sait pas dire. Au téléphone, un emoji est soit lu à
# voix haute de façon absurde, soit avalé — dans les deux cas c'est un défaut que le client
# entend. Trouvé le 25/08 : l'agent a répondu « Bonjour Mme Garcia ! 😊 ».
#
# Détection par CATÉGORIE Unicode « So » (symbole autre) plutôt que par une liste d'emoji :
# la liste serait à maintenir à chaque version d'Unicode, la catégorie couvre 😊 ✅ ⚠ 🔧 ©
# et ce qui viendra.
#
# Les sélecteurs de variation et le liant de largeur nulle ne sont PAS filtrés, et c'est
# réfléchi : tout emoji composite (👩‍🔧) contient au moins un caractère « So », donc il est
# déjà pris. Un sélecteur isolé, lui, est inaudible — le signaler ferait jeter une bonne
# réplique pour un caractère invisible. Une mutation a survécu à ce filtre le 25/08, ce qui
# était le bon signal : il ne portait rien.
#
# Ce qui reste AUTORISÉ, et c'est voulu : l'euro (catégorie « Sc », monnaie) et toute la
# ponctuation française — guillemets « », tiret cadratin, apostrophe typographique. Le
# degré « ° » tombe en revanche dans « So » : l'agent doit dire « degrés ».


def _non_prononcables(texte: str) -> list[str]:
    import unicodedata
    vus, hors = set(), []
    for c in texte or "":
        if c not in vus and unicodedata.category(c) == "So":
            vus.add(c)
            hors.append(c)
    return hors


# MISE EN FORME MARKDOWN. Le formuleur en produit, et plus souvent que des emoji : 15
# répliques sur 214 lors de l'éval du 25/08, contre 11. Le pire cas encadre l'information
# la plus importante de la phrase — « **aujourd'hui entre 17h et 19h** » — que la synthèse
# vocale lira ou avalera.
#
# On ne cible QUE les marqueurs de structure, jamais un caractère isolé : un astérisque
# après un tarif (« 90 € TTC (*) ») ou un souligné dans un identifiant ne sont pas de la
# mise en forme, et les signaler ferait jeter de bonnes répliques.
_RE_MARKDOWN = re.compile(
    r"\*\*.+?\*\*"          # **gras**
    r"|__.+?__"             # __souligné__
    r"|^\s{0,3}#{1,6}\s"    # titre en début de ligne
    r"|\[[^\]]+\]\([^)]+\)"  # [texte](lien)
    r"|`[^`]+`",            # `code`
    re.MULTILINE)


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

    # 4. Caractères qu'une synthèse vocale ne sait pas dire (emoji, pictogrammes).
    # Signalés, PAS nettoyés : `_say` replie sur l'instruction du contrôleur, sûre par
    # construction, et la violation reste visible dans le lead. C'est le formuleur qui
    # dérape — on veut le savoir, pas le maquiller.
    muets = _non_prononcables(text)
    if muets:
        violations.append("caractere_non_prononcable:" + "".join(muets))

    # 5. Mise en forme markdown : même finalité, autre mécanisme (ce sont des caractères
    # de ponctuation ordinaires, donc la catégorie Unicode ne les voit pas).
    if forme := _RE_MARKDOWN.search(text or ""):
        violations.append(f"mise_en_forme_non_prononcable:{forme.group(0)[:24]}")

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
