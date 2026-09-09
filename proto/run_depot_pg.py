#!/usr/bin/env python3
"""Joue la suite de contrat du port `Depot` contre un VRAI Postgres.

    python run_depot_pg.py --migrer --autoriser-truncate   # première fois (base de TEST)
    python run_depot_pg.py --declarer-production          # sur la base de PROD, une fois :
                                                          # elle refusera tout truncate
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

Depuis R92 (09/09), un SECOND marqueur de sens opposé : `--declarer-production` pose
`relais_production` sur la base de prod, et ce script refuse alors de la préparer — aucun
drapeau ne le fera changer d'avis. Motif : le consentement au truncate est un mot sur une
ligne de commande, et `--migrer --autoriser-truncate` lancé avec un `.env` qui pointe la
production posait le marqueur PUIS tronquait la production. Si les deux marqueurs sont
présents, la production gagne.

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

    from relais_proto.depot_pg import candidats_env, hote_de, resoudre_connexion
    try:
        dsn, opts, libelle = resoudre_connexion(candidats_env(), DELAI_CONNEXION)
    except Exception as exc:  # noqa: BLE001
        print(f"   {exc}")
        return None, None, None, None
    # L'HÔTE, pas seulement le libellé (R92) : « directe » et « session pooler » ne disent
    # pas SUR QUELLE BASE on est tombé, et ce script tronque des tables. Voir l'hôte est la
    # dernière chance de s'apercevoir qu'on visait la prod et qu'on a atterri ailleurs —
    # ou l'inverse.
    print(f"   {libelle} : ✓ connectée → {hote_de(dsn)}")
    return psycopg.connect(dsn, autocommit=True, **opts), dsn, libelle, opts


MARQUEUR_PROD = "relais_production"


class _Base:
    """Ce que la garde a besoin de savoir d'une base : quels marqueurs y sont posés.

    Une classe pour une seule question, parce que `verdict_truncate` doit être éprouvable
    SANS Postgres. La logique qui décide de tronquer une base est le dernier endroit où
    l'on peut accepter « ce n'est testable qu'en réel ».
    """

    def __init__(self, cx):
        self.cx = cx

    def marqueur_present(self, nom: str) -> bool:
        with self.cx.cursor() as cur:
            cur.execute("select to_regclass(%s) is not null", (nom,))
            return bool(cur.fetchone()[0])


def verdict_truncate(base, autoriser: bool, declarer_production: bool
                     ) -> tuple[bool, str | None]:
    """Peut-on préparer cette base (donc la TRONQUER) ? Et sinon, pourquoi ?

    R92, demandé le 09/09 en séparant les bases dev et prod. Le marqueur de test existait
    déjà et reste : il porte le consentement dans la BASE, insensible au renommage des
    variables et valable depuis n'importe quelle machine. Mais séparer les bases révèle un
    trou : ce consentement est un mot sur une ligne de commande, et
    `--migrer --autoriser-truncate` lancé avec un `.env` qui pointe la production POSE le
    marqueur puis tronque la production. Le geste qui protège et le geste qui détruit sont
    le même geste, à l'environnement près — et l'environnement est ce qu'on se trompe.

    D'où un second marqueur de sens opposé, `relais_production`. Trois propriétés voulues :

    - il vit dans la BASE, comme l'autre : une variable d'environnement sur la mauvaise
      machine est précisément le mode de panne visé ;
    - **la production GAGNE** si les deux sont présents : un doute ne se résout pas en
      faveur du `truncate` ;
    - il est ASYMÉTRIQUE : le poser demande un mot, le retirer demande une requête SQL à
      la main. Aucun `--annuler` n'est fourni — l'enlever doit coûter plus cher que de
      créer une base de test.
    """
    prod = base.marqueur_present(MARQUEUR_PROD)
    test = base.marqueur_present(MARQUEUR)

    if declarer_production:
        if test:
            return False, (
                f"cette base porte « {MARQUEUR} » : elle a servi de cible à des truncate. "
                f"La déclarer production masquerait son passé — crée une base neuve.")
        return True, None

    if prod:
        return False, (
            f"cette base est déclarée PRODUCTION (table « {MARQUEUR_PROD} »). "
            f"Ce script tronque les tables : il refuse, et aucun drapeau ne le fera "
            f"changer d'avis. Pointe DATABASE_URL sur une base de test.")

    if not (test or autoriser):
        return False, (
            f"la table « {MARQUEUR} » est absente de cette base : rien ne dit qu'elle est "
            f"une base de test.")

    return True, None


def _marqueur_present(cx) -> bool:
    return _Base(cx).marqueur_present(MARQUEUR)


def _poser_marqueur_prod(cx) -> None:
    import socket
    with cx.cursor() as cur:
        cur.execute(f"create table if not exists {MARQUEUR_PROD} ("
                    "declaree_le timestamp not null default now(), machine text)")
        cur.execute(f"insert into {MARQUEUR_PROD} (machine) values (%s)",
                    (socket.gethostname(),))
    print(f"   marqueur « {MARQUEUR_PROD} » posé : cette base est déclarée PRODUCTION.")
    print(f"   Aucun script de test ne la tronquera plus. Pour annuler — et il faut que "
          f"ce soit pénible — : drop table {MARQUEUR_PROD};")


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
        # La garde est évaluée AVANT toute écriture, marqueur de test compris : poser le
        # consentement puis découvrir qu'on est en production serait poser le consentement
        # EN production (R92).
        autoriser = "--autoriser-truncate" in sys.argv
        declarer = "--declarer-production" in sys.argv
        ok, motif = verdict_truncate(_Base(cx), autoriser=autoriser,
                                     declarer_production=declarer)
        if not ok:
            print(f"\nRefus : {motif}")
            if not declarer and "PRODUCTION" not in (motif or ""):
                print("Si — et seulement si — cette base est bien une base de TEST :")
                print("   python run_depot_pg.py --autoriser-truncate")
            cx.close()
            return 2
        if declarer:
            _poser_marqueur_prod(cx)
            cx.close()
            return 0
        if autoriser:
            _poser_marqueur(cx)
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
