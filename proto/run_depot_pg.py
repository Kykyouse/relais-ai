#!/usr/bin/env python3
"""Joue la suite de contrat du port `Depot` contre un VRAI Postgres.

    python run_depot_pg.py --migrer --autoriser-truncate   # première fois
    python run_depot_pg.py --migrer                        # après un changement de schéma
    python run_depot_pg.py                                 # tests seuls

Connexions lues dans `.env` (racine) :
  DATABASE_URL          connexion DIRECTE (db.<ref>.supabase.co:5432) — essayée d'abord
  DATABASE_URL_POOLER   session pooler (...pooler.supabase.com:5432) — repli si la
                        directe échoue (l'hôte direct est en IPv6 sur les projets récents)

Ce script TRONQUE les tables. La garde n'est pas le nom de la variable ni celui de la base
— toutes les bases Supabase s'appellent `postgres`, un contrôle par nom ne se déclencherait
jamais. Elle est un MARQUEUR écrit dans la base, une fois, par `--autoriser-truncate` :
consentement explicite, porté par la base elle-même, insensible au renommage des variables
et valable depuis n'importe quelle machine.

Codes de sortie : 0 = tout passe · 1 = écarts de contrat · 2 = rien testé (pas de base,
pas de marqueur, préparation impossible). Jamais 0 sans avoir rien testé.
"""
from __future__ import annotations

import os
import pathlib
import sys

MIGRATIONS = pathlib.Path(__file__).parent / "migrations"
TABLES = ("message_sortant", "rdv", "lead", "appel")  # ordre inverse des dépendances
MARQUEUR = "relais_base_de_test"
DELAI_CONNEXION = 8  # secondes : on veut basculer vite sur le pooler, pas attendre

MODE_EMPLOI = """
Aucune base configurée.

1. Projet Supabase dédié aux TESTS, région UE (Frankfurt ou Paris — spec produit §9).
   Un projet à part, pas celui de prod : ce script tronque les tables.
   (Les « branches » Supabase sont réservées aux plans payants ; sur l'offre gratuite,
   un second projet est la solution simple.)
2. Dashboard → bouton « Connect » en haut du projet (ou Settings → Database).
3. Remplace [YOUR-PASSWORD] par le mot de passe de la base (Settings → Database →
   Reset database password si perdu). Caractères spéciaux à encoder en %XX.
4. Colle les DEUX chaînes dans le fichier `.env` À LA RACINE (jamais commité) :

   DATABASE_URL=postgresql://postgres:mdp@db.<ref>.supabase.co:5432/postgres?sslmode=require
   DATABASE_URL_POOLER=postgresql://postgres.<ref>:mdp@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require

5. pip install "psycopg[binary]>=3.2"
6. python run_depot_pg.py --migrer --autoriser-truncate
"""


def _charger_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(pathlib.Path(__file__).parent.parent / ".env")
    except ImportError:
        pass


def _connecter():
    """Rend (connexion, dsn, libellé, options). Le repli directe → pooler est mutualisé
    dans `depot_pg.resoudre_connexion` : il doit servir aussi au worker et au serveur, pas
    seulement ici (défaut constaté le 24/08)."""
    import psycopg

    from relais_proto.depot_pg import candidats_env, resoudre_connexion
    try:
        dsn, opts, libelle = resoudre_connexion(candidats_env(), DELAI_CONNEXION)
    except Exception as exc:  # noqa: BLE001
        print(f"   {exc}")
        return None, None, None, None
    print(f"   {libelle} : ✓ connectée")
    return psycopg.connect(dsn, autocommit=True, **opts), dsn, libelle, opts


def _marqueur_present(cx) -> bool:
    with cx.cursor() as cur:
        cur.execute("select to_regclass(%s) is not null", (MARQUEUR,))
        return bool(cur.fetchone()[0])


def _poser_marqueur(cx) -> None:
    import socket
    with cx.cursor() as cur:
        cur.execute(f"create table if not exists {MARQUEUR} ("
                    "autorise_le timestamp not null default now(), machine text)")
        cur.execute(f"insert into {MARQUEUR} (machine) values (%s)",
                    (socket.gethostname(),))
    print(f"   marqueur « {MARQUEUR} » posé : cette base est déclarée base de test")


def _migrer(cx) -> None:
    for chemin in sorted(MIGRATIONS.glob("*.sql")):
        print(f"   migration {chemin.name}")
        with cx.cursor() as cur:
            cur.execute(chemin.read_text(encoding="utf-8"))


def _vider(cx) -> None:
    with cx.cursor() as cur:
        cur.execute(f"truncate {', '.join(TABLES)} cascade")


def run() -> int:
    _charger_env()
    from relais_proto.depot_pg import candidats_env
    if not any(d for _, d in candidats_env()):
        print(MODE_EMPLOI)
        return 2
    try:
        import psycopg  # noqa: F401
    except ImportError:
        print('Pilote absent : pip install "psycopg[binary]>=3.2"')
        return 2

    print("──── connexion ────")
    cx, dsn, libelle, opts = _connecter()
    if cx is None:
        print("\nAucune des chaînes fournies ne répond. Si la directe échoue en réseau "
              "IPv4, renseigne DATABASE_URL_POOLER (session pooler, port 5432).")
        return 2

    try:
        if "--migrer" in sys.argv:
            _migrer(cx)
        if "--autoriser-truncate" in sys.argv:
            _poser_marqueur(cx)
        if not _marqueur_present(cx):
            print(f"\nRefus : la table « {MARQUEUR} » est absente de cette base.")
            print("Ce script tronque les tables. Si — et seulement si — cette base est")
            print("bien une base de TEST, autorise-la une fois pour toutes :")
            print("   python run_depot_pg.py --autoriser-truncate")
            cx.close()
            return 2
        _vider(cx)
    except Exception as exc:  # noqa: BLE001
        print(f"Préparation impossible : {type(exc).__name__}: {exc}")
        print("Si les tables n'existent pas encore, relance avec --migrer.")
        cx.close()
        return 2

    from contrat_depot import verifier
    from relais_proto.depot_pg import DepotPostgres
    from run_scenario import CFG, check_worker_expiration

    depots: list[DepotPostgres] = []

    def fabrique():
        d = DepotPostgres(dsn, **opts)
        depots.append(d)
        return d

    echecs = 0
    print("\n──── contrat du port Depot ────")
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
    print(f"\nConnexion utilisée : {libelle}")
    print("✅ Postgres conforme au port" if not echecs
          else f"❌ {echecs} bloc(s) en échec")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(run())
