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


# Salutation, où qu'elle soit dans la réplique. L'ancrage en tête a été RETIRÉ le 26/08 :
# le sixième appel réel a produit « Pouvez-vous ? Oui, Bonjour, vous avez une fuite… », où
# le « Bonjour » est au milieu et passait donc à travers.
#
# J'avais ancré le motif pour protéger « dites-lui bonjour de ma part », et j'avais même
# écrit un test qui l'exigeait. Cette phrase n'existe pas dans ce produit ; le « Bonjour »
# perdu au milieu d'une réplique, lui, s'est produit. Un garde-fou calibré sur un cas
# imaginé plutôt que sur un cas observé protège le mauvais côté.
_RE_SALUTATION = re.compile(r"\b(bonjour|bonsoir|salut|re-?bonjour)\b", re.IGNORECASE)

# Tutoiement. Les formes retenues sont celles qui ne sont QUE des marques de deuxième
# personne du singulier : « tu », « te », « toi », « ton », « ta », « tes », et l'élision « t'a /
# t'es / t'ai ». Pas de formes verbales — elles sont innombrables, et le pronom ou le
# possessif accompagne presque toujours.
#
# Les limites de mot doivent connaître les accents : « vous êtes » contient « tes », et
# `\b` en Python le sait (contrairement à `grep` dans une locale C, qui m'a fait croire à
# des faux positifs). Vérifié sur tous les textes du produit : aucune correspondance.
_RE_TUTOIEMENT = re.compile(r"\b(tu|te|toi|ton|ta|tes)\b|\bt'(?=[aeiouyéèêà])",
                            re.IGNORECASE)


def check_output(text: str, config: dict, rdv_valide: bool = False,
                 en_conversation: bool = False) -> list[str]:
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

    # 7. Tutoiement. Un artisan ne tutoie pas ses clients.
    #
    # Le 26/08, cinquième appel réel : « je comprends que TU m'appelles depuis le cent
    # soixante ». Le formuleur a changé de registre en pleine phrase. Aucun garde-fou ne
    # pouvait l'attraper — ni prix, ni promesse, ni caractère imprononçable, ni salutation
    # déplacée. Même famille que la re-salutation, mais plus grave : un client qu'on tutoie
    # sans le connaître entend un défaut de sérieux, chez un artisan qu'il paie.
    #
    # Contrairement à la re-salutation, la règle vaut PARTOUT — SMS et pages comprises. Il
    # n'existe aucun contexte où ce produit tutoie.
    if m := _RE_TUTOIEMENT.search(text or ""):
        violations.append(f"tutoiement:{m.group(0)}")

    # 8. Plusieurs questions dans une seule réplique.
    #
    # Sixième appel réel du 26/08 : « Pouvez-vous ? Oui, Bonjour, vous avez une fuite dans
    # la salle de bain ? D'accord, dites-moi, vous êtes sur quelle commune ? » — trois
    # points d'interrogation.
    #
    # Au téléphone, c'est pire qu'inélégant : l'appelant répond à celle qu'il a retenue, et
    # le contrôleur reçoit une réponse à une question qu'il n'a pas posée. Le slot attendu
    # n'arrive pas, la question est reposée, et l'appelant a l'impression de se répéter —
    # c'est le mécanisme exact des boucles qu'on passe notre temps à borner.
    #
    # La règle ne contraint que le FORMULEUR : aucune instruction du contrôleur, aucun
    # gabarit de message ne pose plus d'une question (vérifié). Le repli est donc toujours
    # une réplique valide.
    if (text or "").count("?") > 1:
        violations.append(f"questions_multiples:{(text or '').count('?')}")

    # 6. Re-salutation. On dit bonjour une fois par conversation, et l'accueil l'a déjà
    # fait. Le formuleur resalue parce que chaque tour lui arrive comme un début — au
    # téléphone le 26/08, l'agent a dit « Bonjour » au deuxième tour, juste après avoir
    # dit bonjour. C'est l'un des tics qui font entendre qu'on parle à une machine, et
    # aucun des garde-fous précédents ne pouvait l'attraper : ce n'est ni un prix, ni une
    # promesse, ni un caractère imprononçable — juste une phrase déplacée.
    #
    # Seule la salutation EN TÊTE est visée : « dites-lui bonjour de ma part » reste une
    # phrase légitime, et censurer le mot lui-même serait une autre faute.
    #
    # Et le drapeau est OPT-IN, pas opt-out. Premier essai fait à l'envers : la règle
    # s'appliquait par défaut, et six tests sont tombés d'un coup — les gabarits de SMS et
    # la phrase de la sonde commencent par « Bonjour », légitimement. Un SMS est un
    # premier contact, pas un tour de conversation. Le défaut d'un garde-fou doit être de
    # ne rien interdire à ceux qui ne l'ont pas demandé.
    if en_conversation and _RE_SALUTATION.search(text or ""):
        violations.append("resalutation")

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
