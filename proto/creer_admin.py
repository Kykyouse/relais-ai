#!/usr/bin/env python3
"""Crée (ou met à jour) un compte d'ADMINISTRATION.

    python creer_admin.py --identifiant geoffrey
    python creer_admin.py --env-file ../.env.prod --identifiant geoffrey --ecrire
    python creer_admin.py --env-file ../.env.prod --identifiant geoffrey --desactiver --ecrire

L'ŒUF ET LA POULE, et c'est la seule raison d'être de ce script : la page d'admin est
protégée par un compte d'admin. Le premier ne peut donc pas naître d'elle. Il naît ici, en
ligne de commande, sur une machine qui a déjà les identifiants de la base — c'est-à-dire
là où celui qui le crée a de toute façon tout pouvoir.

Blanc par défaut, comme les autres scripts qui écrivent. Le mot de passe est AFFICHÉ une
fois s'il est généré : la base n'en garde que l'empreinte scrypt, il ne sera pas relisible.

`--desactiver` ferme le compte ET ses sessions en cours (clé étrangère en cascade,
migration 012) : un compte révoqué dont le cookie ouvre encore les portes n'est pas
révoqué.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

from dotenv import load_dotenv

RACINE = pathlib.Path(__file__).parent


def run() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--identifiant", required=True, help="ce qu'on tape pour entrer")
    ap.add_argument("--nom", default="", help="nom affiché")
    ap.add_argument("--mot-de-passe", default="",
                    help="le tien ; sinon un mot de passe solide est proposé")
    ap.add_argument("--desactiver", action="store_true",
                    help="ferme le compte et ses sessions")
    ap.add_argument("--ecrire", action="store_true", help="écrire réellement")
    ap.add_argument("--env-file", default="",
                    help="fichier d'environnement prioritaire (ex. ../.env.prod)")
    args = ap.parse_args()

    if args.env_file:
        chemin = pathlib.Path(args.env_file).resolve()
        if not chemin.exists():
            print(f"fichier introuvable : {chemin}")
            return 2
        load_dotenv(chemin, override=True)
        print(f"environnement : {chemin.name}")
    else:
        load_dotenv(RACINE.parent / ".env")
        print("environnement : .env")

    from relais_proto import admin as admin_mdp
    from relais_proto.depot import LigneAdmin
    from relais_proto.depot_pg import (DepotPostgres, candidats_env,
                                       resoudre_connexion)

    try:
        dsn, opts, libelle = resoudre_connexion(candidats_env())
    except Exception as exc:
        print(exc)
        return 2
    depot = DepotPostgres(dsn, **opts)
    # L'HÔTE, avant toute écriture : se tromper de base est le mode de panne que R92 a
    # appris à nommer, et ce script écrit un compte qui peut tout faire.
    print(f"base : {libelle} → {depot.cx.info.host}\n")

    try:
        existants = {a.identifiant: a for a in depot.admins()}
        deja = existants.get(args.identifiant)

        if args.desactiver:
            if deja is None:
                print(f"aucun compte « {args.identifiant} » à désactiver.")
                return 2
            print(f"désactivation de « {args.identifiant} » "
                  f"(ses sessions en cours seront fermées)")
            if not args.ecrire:
                print("\nBlanc : rien écrit. Relance avec --ecrire.")
                return 0
            deja.actif = False
            depot.enregistrer_admin(deja)
            print("compte désactivé.")
            return 0

        mot_de_passe = args.mot_de_passe or admin_mdp.mot_de_passe_suggere()
        try:
            empreinte = admin_mdp.chiffrer(mot_de_passe)
        except ValueError as exc:
            print(exc)
            return 2

        print(f"identifiant : {args.identifiant}"
              f"  ({'MISE À JOUR' if deja else 'création'})")
        print(f"nom         : {args.nom or args.identifiant}")
        print(f"comptes déjà en base : {sorted(existants) or 'aucun'}")
        if not args.ecrire:
            print("\nBlanc : rien écrit. Relance avec --ecrire pour appliquer.")
            return 0

        depot.enregistrer_admin(LigneAdmin(
            id=deja.id if deja else f"adm-{args.identifiant}",
            identifiant=args.identifiant,
            nom=args.nom or args.identifiant,
            mot_de_passe=empreinte, actif=True))
        print("\n" + "=" * 68)
        if args.mot_de_passe:
            print("Mot de passe : celui que tu as fourni (non affiché).")
        else:
            print("MOT DE PASSE (affiché UNE SEULE FOIS — la base n'a que l'empreinte) :")
            print(f"  {mot_de_passe}")
        print("=" * 68)
        print("\nPour entrer : https://nelyo-api.onrender.com/admin/connexion")
        return 0
    finally:
        depot.fermer()


if __name__ == "__main__":
    sys.exit(run())
