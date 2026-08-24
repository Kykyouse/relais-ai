#!/usr/bin/env python3
"""Écrit `config/artisans.json` dans la table `artisan` (migration 008).

    python semer_artisans.py              # blanc : montre ce qui serait écrit
    python semer_artisans.py --ecrire     # écrit réellement

Depuis la migration 008, la table `artisan` EST le registre : c'est elle que lisent le
serveur et le worker. `config/artisans.json` devient une **graine** — pratique pour amorcer
une base neuve et pour reprendre les lignes que la migration a créées à partir de données
existantes (celles marquées `a_reprendre`, dont elle ne connaissait que l'identifiant).

Blanc par défaut, comme `envoyer_un_sms.py` : ce script ÉCRASE des lignes de registre à
partir d'un fichier, et on doit pouvoir regarder avant. L'écriture est un UPSERT, donc
rejouable sans dommage.

Ce que ce script ne fait PAS : toucher aux `config/*.json`. La config reste un fichier
versionné dans git — c'est son historique qui répond à « qu'est-ce que l'agent savait le
jour de cet appel ? » (décision du 25/08).
"""
from __future__ import annotations

import pathlib
import sys

from dotenv import load_dotenv

from relais_proto.depot_pg import DepotPostgres, candidats_env, resoudre_connexion
from relais_proto.registre import Registre

RACINE = pathlib.Path(__file__).parent
load_dotenv(RACINE.parent / ".env")


def run() -> int:
    ecrire = "--ecrire" in sys.argv
    registre = Registre.depuis_fichier(RACINE / "config" / "artisans.json", "inutile")

    try:
        dsn, opts, libelle = resoudre_connexion(candidats_env())
    except Exception as exc:
        print(exc)
        return 2
    print(f"base : {libelle}")
    depot = DepotPostgres(dsn, **opts)
    try:
        avant = {a.id: a for a in depot.artisans()}
        graine = {a.id: a for a in registre._artisans.values()}

        for aid, a in sorted(graine.items()):
            etat = avant.get(aid)
            if etat is None:
                verdict = "CRÉÉ"
            elif (etat.numero_relais, etat.telephone, etat.config_fichier,
                  etat.token_sha256, etat.etat_abonnement) == (
                    a.numero_relais, a.telephone, a.config_fichier,
                    a.token_sha256 or None, a.etat_abonnement):
                verdict = "inchangé"
            else:
                verdict = f"MIS À JOUR (était : {etat.etat_abonnement})"
            print(f"  {aid:14} {a.numero_relais:14} tel={a.telephone or '?':14} "
                  f"{a.config_fichier:14} {verdict}")

        # Ce que la base a et que la graine n'a pas : lignes de reprise laissées par la
        # migration, ou artisans retirés du fichier. On ne les touche pas — supprimer un
        # artisan qui porte des rendez-vous est refusé par la clé étrangère, et c'est
        # voulu : une résiliation se marque, elle n'efface pas.
        for aid, a in sorted(avant.items()):
            if aid not in graine:
                print(f"  {aid:14} {'—':14} {'—':14} {'—':14} "
                      f"EN BASE SEULEMENT ({a.etat_abonnement}) — laissé tel quel")

        if not ecrire:
            print("\nBlanc : rien écrit. Relance avec --ecrire pour appliquer.")
            return 0
        n = registre.semer(depot)
        print(f"\n{n} artisan(s) écrit(s) dans la table.")
        return 0
    finally:
        depot.fermer()


if __name__ == "__main__":
    sys.exit(run())
