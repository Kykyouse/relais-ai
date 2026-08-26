"""Table des communes et normalisation des noms. Partagée par le contrôleur ET les
garde-fous.

Elle vivait dans `engine.py`, où seul le contrôleur s'en servait pour RÉSOUDRE une commune
citée par l'appelant. Depuis le 26/08, les garde-fous en ont besoin aussi, pour une raison
symétrique : **vérifier qu'une réplique formulée ne nomme pas un lieu**. Le formuleur a
prononcé « Orange », « Deuil La Barre », « Nogènes-sur-Marne », « Essonne » — un nom de lieu
est un FAIT, et un modèle ne peut que l'écorcher ou l'inventer.

`guards` ne peut pas importer `engine` (qui importe `guards`), d'où ce module tiers.
"""
from __future__ import annotations

import json
import pathlib
import re
import unicodedata

# Alias d'un seul mot qui sont AUSSI des mots français courants. La table porte, pour
# chaque commune composée, un alias court bien utile — « Issy », « Sucy », « Ivry » sont ce
# que les gens disent vraiment. Mais quelques-uns sont des homonymes qui apparaissent
# naturellement dans un appel de plomberie, et les garder coûte des leads.
#
# Trouvé par l'éval LLM du 25/08 : « il faudrait que quelqu'un VIENNE assez vite » a résolu
# Vienne-en-Arthies (95510), classé l'appel hors zone et raccroché au premier tour. Sur une
# fuite d'eau en cours.
#
# L'exclusion vit ICI et non dans le fichier de données : celui-ci est régénéré depuis la
# base officielle, et une régénération réintroduirait les homonymes en silence. Le nom
# COMPLET reste résoluble dans tous les cas (« Vienne-en-Arthies », « Bois-le-Roi »).
ALIAS_AMBIGUS = frozenset({
    "vienne",   # « qu'il vienne », « que quelqu'un vienne » — subjonctif de venir
    "bois",     # « je bois », « le bois », « sous le bois »
    "champs",   # « les champs »
    "bourg",    # « le bourg »
    # Méré (78490). « C'est pour la chaudière de ma mère » est une des phrases les plus
    # courantes du métier — beaucoup d'appels sont passés POUR quelqu'un d'autre.
    # Trouvé le 25/08 par le persona T12, qui visait tout autre chose.
    "mere",
})

_TABLE: dict | None = None
_RE_ESPACES = re.compile(r"\s+")
_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, ponctuation en espaces.

    « c'est Saint-Maur. » doit correspondre à « saint maur » (bug LLM-run3 : la virgule et
    le point cassaient la résolution).
    """
    t = unicodedata.normalize("NFD", (texte or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return _RE_ESPACES.sub(" ", _RE_NON_ALNUM.sub(" ", t)).strip()


def table_idf() -> dict:
    """La table Île-de-France (base officielle Etalab), alias ambigus exclus."""
    global _TABLE
    if _TABLE is None:
        chemin = pathlib.Path(__file__).parent / "data" / "communes_idf.json"
        brut = json.loads(chemin.read_text(encoding="utf-8")) if chemin.exists() else {}
        _TABLE = {n: cp for n, cp in brut.items() if n not in ALIAS_AMBIGUS}
    return _TABLE


def nommees(texte: str, communes_zone: dict | None = None) -> list[str]:
    """Les communes que ce texte NOMME, sous leur forme de table.

    Sert aux garde-fous : une réplique formulée qui nomme un lieu énonce un fait, et le
    formuleur n'a pas le droit d'énoncer un fait (R63).

    Les noms les plus longs d'abord, et on retire ce qui a été trouvé avant de continuer :
    « le perreux sur marne » ne doit pas être compté aussi comme « perreux ».
    """
    phrase = " " + normaliser(texte) + " "
    trouvees: list[str] = []
    for nom in sorted({**(communes_zone or {}), **table_idf()}, key=len, reverse=True):
        cible = " " + normaliser(nom) + " "
        if cible in phrase:
            trouvees.append(nom)
            phrase = phrase.replace(cible, " ")
    return trouvees
