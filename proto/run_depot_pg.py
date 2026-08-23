#!/usr/bin/env python3
"""Joue la suite de contrat du port `Depot` contre un VRAI Postgres.

    python run_depot_pg.py --migrer     # applique migrations/*.sql puis teste
    python run_depot_pg.py              # teste seulement

La connexion est lue dans `DATABASE_URL_TEST` (fichier `.env`), **jamais** dans
`DATABASE_URL`. Ce script TRONQUE les tables avant chaque exécution : le faire pointer
sur la base de production serait une catastrophe silencieuse. Deux variables distinctes
rendent l'accident impossible plutôt qu'improbable.

Codes de sortie : 0 = tout passe · 1 = écarts de contrat · 2 = pas de base joignable
(jamais 0 sans avoir rien testé — un « succès » vide est pire qu'un échec).
"""
from __future__ import annotations

import os
import pathlib
import sys

MIGRATIONS = pathlib.Path(__file__).parent / "migrations"
TABLES = ("message_sortant", "rdv", "lead", "appel")  # ordre inverse des dépendances

MODE_EMPLOI = """
Aucune base de test configurée.

1. Crée une instance Postgres managée en UE (Neon ou Supabase : offre gratuite suffisante,
   choisir une région européenne — Frankfurt ou Paris — cf. spec produit §9).
2. Sur Neon, crée une BRANCHE dédiée aux tests (ou une seconde base sur Supabase) : ce
   script tronque les tables à chaque exécution.
3. Ajoute la chaîne de connexion de cette branche dans le fichier `.env` à la racine :

   DATABASE_URL_TEST=postgresql://user:motdepasse@host/dbname?sslmode=require

4. Installe le pilote :  pip install "psycopg[binary]>=3.2"
5. Relance :             python run_depot_pg.py --migrer
"""


def _dsn() -> str | None:
    try:
        from dotenv import load_dotenv
        load_dotenv(pathlib.Path(__file__).parent.parent / ".env")
    except ImportError:
        pass
    dsn = os.environ.get("DATABASE_URL_TEST")
    if not dsn and os.environ.get("DATABASE_URL"):
        print("⚠️  DATABASE_URL est défini mais pas DATABASE_URL_TEST.")
        print("   Refus délibéré : ce script tronque les tables, il ne touchera jamais")
        print("   la base désignée par DATABASE_URL. Configure DATABASE_URL_TEST.")
        return None
    return dsn


def _migrer(cx) -> None:
    for chemin in sorted(MIGRATIONS.glob("*.sql")):
        print(f"   migration {chemin.name}")
        with cx.cursor() as cur:
            cur.execute(chemin.read_text(encoding="utf-8"))


def _vider(cx) -> None:
    with cx.cursor() as cur:
        cur.execute(f"truncate {', '.join(TABLES)} cascade")


def run() -> int:
    dsn = _dsn()
    if not dsn:
        print(MODE_EMPLOI)
        return 2
    try:
        import psycopg
    except ImportError:
        print('Pilote absent : pip install "psycopg[binary]>=3.2"')
        return 2

    from contrat_depot import verifier
    from relais_proto.depot_pg import DepotPostgres
    from run_scenario import CFG, check_worker_expiration

    try:
        cx = psycopg.connect(dsn, autocommit=True)
    except Exception as exc:  # noqa: BLE001 — on veut le message tel quel
        print(f"Connexion impossible : {type(exc).__name__}: {exc}")
        return 2
    # sécurité supplémentaire : on refuse une base dont le nom sent la production
    nom_base = cx.info.dbname
    if any(mot in nom_base.lower() for mot in ("prod", "production", "live")):
        print(f"Refus : la base « {nom_base} » ressemble à une base de production.")
        cx.close()
        return 2
    print(f"Base de test : {nom_base}")

    try:
        if "--migrer" in sys.argv:
            _migrer(cx)
        _vider(cx)
    except Exception as exc:  # noqa: BLE001
        print(f"Préparation impossible : {type(exc).__name__}: {exc}")
        print("Si les tables n'existent pas encore, relance avec --migrer.")
        cx.close()
        return 2

    echecs = 0
    print("\n──── contrat du port Depot ────")
    depots: list[DepotPostgres] = []

    def fabrique():
        d = DepotPostgres(dsn)
        depots.append(d)
        return d

    ecarts = verifier(fabrique, CFG)
    for e in ecarts:
        print(f"   {e}")
    print(f"   → {'✅ PASS' if not ecarts else f'❌ {len(ecarts)} écart(s)'}")
    echecs += bool(ecarts)

    print("\n──── worker d'expiration sur Postgres ────")
    _vider(cx)
    if check_worker_expiration(fabrique=fabrique):
        print("   → ✅ PASS")
    else:
        print("   → ❌ FAIL")
        echecs += 1

    for d in depots:
        d.fermer()
    cx.close()
    print(f"\n{'✅ Postgres conforme au port' if not echecs else f'❌ {echecs} bloc(s) en échec'}")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(run())
