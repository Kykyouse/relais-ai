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


# ─────────────────────────────────────────────────────────────────────────────────
# LES FAITS : ce qu'une réplique FORMULÉE n'a pas le droit d'énoncer.
#
# Renversement du 26/08. Jusqu'ici, chaque fois que le formuleur écornait un fait, on
# figeait la PHRASE entière en `verbatim` : les créneaux (R38), la clôture (R44), la
# commune (R45), la question du secteur (R56), le refus et la re-dictée (R57). Chacun
# justifié par un défaut réel — et l'effet cumulé est que l'agent sonne préenregistré.
# Geoffrey, après l'appel où la même phrase est sortie trois fois : « on vend de l'IA avec
# notre produit, pas du message préenregistré ».
#
# La ligne est déplacée : **le contrôleur ÉNONCE les faits, le formuleur DEMANDE**. Une
# réplique formulée peut être tournée comme le modèle veut, mais elle ne peut contenni
# aucun chiffre, aucun jour, aucun nom de lieu. Ce sont exactement les trois choses qu'il
# a inventées en production :
#
#   chiffres   « 0-6-1-0-1-5-4-7-6-8-7-9. C'est bien ça ? »   (numéro refusé, R57)
#   jours      « je n'ai pas de disponibilité le samedi »      (créneaux niés, R38)
#   lieux      « Vous êtes sur Orange, dans le Vaucluse ? »    (lieu inventé, R56)
#
# Un fait ne se reformule pas : il se cite ou il se tait.
_RE_CHIFFRE = re.compile(r"\d")
_RE_JOUR = re.compile(
    r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche"
    r"|demain|aujourd'?hui|apr[eè]s-?demain|ce soir|matin|apr[eè]s-?midi)\b",
    re.IGNORECASE)


# Un NOM PROPRE au milieu d'une phrase. C'est le seul critère mécanique qui attrape ce que
# le formuleur a réellement produit : « Orange » et « Vaucluse » (hors Île-de-France, donc
# absents de nos tables), « Nogènes-sur-Marne » (qui n'existe pas), « Deuil La Barre »
# (un autre département), « Essonne » (un département pris pour une commune).
#
# Une table de communes ne suffisait pas : elle ne connaît que l'Île-de-France, et le
# formuleur cite ce qu'il veut. En français, une majuscule en milieu de phrase est
# presque toujours un nom propre — et un nom propre est un FAIT.
#
# `[a-zà-ÿ]{2,}` : capitale suivie de minuscules, donc pas les sigles (« SMS », « RDV »),
# qui ne sont pas des faits.
#
# ⚠️ COMPROMIS ASSUMÉ : la règle ne sait pas distinguer « Orange » d'un mot courant
# capitalisé au milieu d'une phrase (« Alors, Dites-moi… »). Il faudrait un dictionnaire
# pour cela. Le faux positif coûte du NATUREL — la réplique replie sur l'instruction du
# contrôleur, correcte par construction — jamais de la correction. On préfère un agent
# parfois plus sec à un agent qui invente un nom de ville.
_RE_NOM_PROPRE = re.compile(r"\b([A-ZÀ-Þ][a-zà-ÿ]{2,})")
_FINS_DE_PHRASE = ".!?…:"
# Les civilites portent une majuscule et ne sont pas des faits : personne ne peut
# se tromper en disant « Monsieur ». Les laisser interdites ferait replier une
# reponse polie sur l'instruction brute, ce qui est exactement l'inverse du but.
CIVILITES = frozenset({"monsieur", "madame", "mademoiselle", "messieurs", "mesdames"})


def _mots_autorises(config: dict, slots: dict | None) -> set[str]:
    """Les noms propres que l'agent a le droit de prononcer : les siens, et ceux que le
    contrôleur a RÉSOLUS. Le nom d'une commune établie ou celui de l'appelant ne sont plus
    des inventions possibles — ils sont dans l'état."""
    from . import communes as _c

    sources = [(config.get("entreprise") or {}).get("nom"),
               (config.get("entreprise") or {}).get("prenom_patron"),
               (config.get("produit") or {}).get("nom")]
    for cle in ("commune", "nom"):
        sources.append((slots or {}).get(cle))
    mots = set(CIVILITES)
    for s in sources:
        mots.update(_c.normaliser(str(s or "")).split())
    return mots


def _faits_enonces(text: str, config: dict, slots: dict | None = None) -> list[str]:
    """Les FAITS qu'une réplique formulée n'aurait pas dû énoncer."""
    from . import communes as _c

    violations = []
    if m := _RE_CHIFFRE.search(text or ""):
        violations.append(f"chiffre_hors_verbatim:{m.group(0)}")
    if m := _RE_JOUR.search(text or ""):
        violations.append(f"jour_hors_verbatim:{m.group(0)}")
    autorises = _mots_autorises(config, slots)
    texte = text or ""
    for m in _RE_NOM_PROPRE.finditer(texte):
        # une majuscule en DÉBUT de phrase est normale : on ne regarde que celles du
        # milieu, là où elle signale un nom propre
        avant = texte[:m.start()].rstrip()
        if not avant or avant[-1] in _FINS_DE_PHRASE:
            continue
        if _c.normaliser(m.group(1)) in autorises:
            continue
        violations.append(f"nom_propre_hors_verbatim:{m.group(1)}")
        break
    return violations


def check_output(text: str, config: dict, rdv_valide: bool = False,
                 en_conversation: bool = False,
                 formule: bool = False, slots: dict | None = None) -> list[str]:
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

    # 9. Les FAITS, dans une réplique FORMULÉE seulement (voir `_faits_enonces`). C'est
    # le renversement du 26/08 : on n'interdit plus au formuleur de PARLER, on lui interdit
    # d'ÉNONCER. Il retrouve sa liberté de tournure là où le contrôleur ne fait que poser
    # une question, et il ne peut plus inventer un chiffre, un jour ou un lieu.
    if formule:
        violations.extend(_faits_enonces(text, config, slots))

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
