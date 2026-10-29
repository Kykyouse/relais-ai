"""Le schéma que CE code attend, lu dans ses propres migrations (29/10).

POURQUOI CE MODULE EXISTE. Le 29/10, la production a servi pendant deux heures un code
qui lisait `rdv.issue` alors que la migration 015 n'avait jamais été appliquée. Le
service démarrait, `/sante` répondait « ok », et **seule la première requête qui touchait
la colonne échouait** — le cron toutes les dix minutes, et n'importe quel écran montrant
un rendez-vous. Rien ne le disait, et il a fallu lire les journaux de l'hébergeur.

C'est le même angle mort que R102, un étage plus haut : une panne silencieuse dont le
symptôme n'apparaît qu'à l'usage. Le remède est celui de R65 (la révision qui tourne) et
de R86 (le dernier passage du worker) : **en faire une donnée qu'on lit en dix secondes**,
plutôt qu'une enquête.

LA LISTE N'EST PAS ÉCRITE À LA MAIN, et c'est tout l'intérêt. Elle est DÉRIVÉE des
fichiers `migrations/*.sql` — la même règle que `registre.valider_config`, qui dérive ses
exigences du modèle plutôt que de les énumérer : une liste tenue à la main vieillit en
silence, et celle-ci vieillirait exactement le jour où elle compterait, c'est-à-dire à la
migration suivante. Ajouter une migration suffit donc à étendre le contrôle.

CE QUE ÇA NE FAIT PAS : vérifier les types, les contraintes ou les index. On répond à une
seule question — « le schéma de cette base porte-t-il ce que ce code va lire ? » — parce
que c'est celle qui a coûté deux heures, et qu'un contrôle qui prétend tout vérifier
finit par n'être lu par personne.
"""
from __future__ import annotations

import pathlib
import re

# Ce qui, dans un `create table`, n'est PAS une colonne. Les contraintes de table
# commencent par l'un de ces mots ; tout le reste est une définition de colonne.
_MOTS_DE_CONTRAINTE = ("primary", "unique", "foreign", "check", "constraint",
                       "exclude", "like")

# `\w` et non `[a-z_]` : un identifiant SQL porte des CHIFFRES. Premier essai sans eux,
# et `confirmation_sha256` est ressorti tronqué en `confirmation_sha` — une colonne
# fantôme annoncée manquante sur une base parfaitement à jour.
_IDENT = r"\w+"
_CREATE = re.compile(
    rf"create\s+table\s+(?:if\s+not\s+exists\s+)?({_IDENT})\s*\(", re.I)
_ALTER = re.compile(
    rf"alter\s+table\s+(?:if\s+exists\s+)?({_IDENT})\s+add\s+column\s+"
    rf"(?:if\s+not\s+exists\s+)?({_IDENT})", re.I)


def _corps_de_table(sql: str, debut: int) -> str:
    """Le contenu entre la parenthèse ouvrante d'un `create table` et sa fermante.

    Compté PARENTHÈSE PAR PARENTHÈSE et non par un `)` cherché bêtement : une colonne
    peut porter `numeric(10,2)` ou `check (x in ('a','b'))`, et s'arrêter à la première
    fermante couperait la table en deux sans rien signaler.
    """
    profondeur, i = 0, debut
    while i < len(sql):
        if sql[i] == "(":
            profondeur += 1
        elif sql[i] == ")":
            profondeur -= 1
            if profondeur == 0:
                return sql[debut + 1:i]
        i += 1
    return ""


def _definitions(corps: str) -> list[str]:
    """Le corps d'un `create table` découpé sur ses virgules DE PREMIER NIVEAU.

    Un `split(",")` naïf coupe aussi à l'intérieur des parenthèses — et
    `check (etat_abonnement in ('actif', 'essai', 'suspendu'))` devenait alors trois
    « colonnes » nommées `'essai'`, `'suspendu'` et `'actif'))`. Annoncées manquantes
    sur une base à jour, au premier contact avec la production.
    """
    morceaux, courant, profondeur = [], [], 0
    for c in corps:
        if c == "(":
            profondeur += 1
        elif c == ")":
            profondeur -= 1
        if c == "," and profondeur == 0:
            morceaux.append("".join(courant))
            courant = []
        else:
            courant.append(c)
    morceaux.append("".join(courant))
    return morceaux


def attendu(dossier: pathlib.Path | None = None) -> dict[str, set[str]]:
    """{table: {colonnes}} tel que les migrations de ce dépôt le construisent."""
    dossier = dossier or (pathlib.Path(__file__).parent.parent / "migrations")
    tables: dict[str, set[str]] = {}
    for chemin in sorted(dossier.glob("*.sql")):
        sql = re.sub(r"--[^\n]*", "", chemin.read_text(encoding="utf-8"))
        for m in _CREATE.finditer(sql):
            table = m.group(1).lower()
            colonnes = tables.setdefault(table, set())
            for ligne in _definitions(_corps_de_table(sql, m.end() - 1)):
                mot = ligne.strip().split()
                if mot and mot[0].lower() not in _MOTS_DE_CONTRAINTE:
                    colonnes.add(mot[0].lower().strip('"'))
        for table, colonne in _ALTER.findall(sql):
            tables.setdefault(table.lower(), set()).add(colonne.lower())
    return tables


def manquant(present: dict[str, set[str]] | None,
             dossier: pathlib.Path | None = None) -> list[str]:
    """Ce que le code lira et que la base n'a pas, en « table.colonne ».

    `present` à `None` signifie « ce dépôt n'a pas de schéma » (implémentation mémoire) :
    on rend une liste vide plutôt que de prétendre qu'il manque tout. Le contrôle ne
    s'applique qu'à une vraie base — c'est elle qui peut diverger du code.
    """
    if present is None:
        return []
    ecarts = []
    for table, colonnes in sorted(attendu(dossier).items()):
        connues = present.get(table)
        if connues is None:
            ecarts.append(f"{table} (table absente)")
            continue
        ecarts += [f"{table}.{c}" for c in sorted(colonnes - connues)]
    return ecarts
