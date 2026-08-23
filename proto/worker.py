#!/usr/bin/env python3
"""Un passage des workers de fond, à appeler par un cron.

    python worker.py            # un passage : expiration puis expédition
    python worker.py --a-vide   # sans rien envoyer (inspection seule)

Deux passages enchaînés, dans cet ordre :
  1. `WorkerExpiration` — les RDV échus : créneau libéré, lead en alerte, messages en file.
  2. `Expediteur` — la file sortante : plage de silence, réessais, échec définitif.

⚠️ AUCUN FOURNISSEUR SMS N'EST CÂBLÉ. L'expéditeur utilise `EnvoyeurJournal` : les messages
sont marqués envoyés et journalisés, **rien ne part réellement**. C'est volontaire tant que
le fournisseur n'est pas choisi — mieux vaut un envoi journalisé qu'un envoi vers un
fournisseur mal configuré. Le mode `--a-vide` n'envoie ni ne marque rien.

Multi-artisans depuis la migration 004 : chaque message et chaque RDV porte son
`artisan_id`, et les deux workers résolvent la config correspondante. Un artisan absent du
registre n'est pas deviné — son travail reste en file et apparaît dans le rapport.
"""
from __future__ import annotations

import os
import pathlib
import sys

from dotenv import load_dotenv

from relais_proto.depot_pg import DepotPostgres
from relais_proto.envoi import EnvoyeurJournal, Expediteur
from relais_proto.expiration import WorkerExpiration
from relais_proto.messages import StatutMessage
from relais_proto.registre import Registre

RACINE = pathlib.Path(__file__).parent
load_dotenv(RACINE.parent / ".env")


def run() -> int:
    import datetime as dt

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL manquant (voir .env.example).")
        return 2
    registre = Registre.depuis_fichier(RACINE / "config" / "artisans.json",
                                       os.environ.get("RELAIS_WEBHOOK_SECRET", "inutile"))
    def config_pour(artisan_id):
        artisan = registre.artisan(artisan_id)
        return artisan.config if artisan else None

    depot = DepotPostgres(dsn)
    maintenant = dt.datetime.now()
    print(f"passage du {maintenant.isoformat(timespec='seconds')}")

    rapport = WorkerExpiration(depot, config_pour).passer(maintenant)
    print(f"  expiration : {rapport.examines} examiné(s), {len(rapport.expires)} expiré(s), "
          f"{len(rapport.messages_crees)} message(s) en file, {len(rapport.echecs)} échec(s)")
    for e in rapport.echecs:
        print(f"    ! {e}")

    en_file = depot.messages(StatutMessage.A_ENVOYER)
    if "--a-vide" in sys.argv:
        print(f"  expédition : {len(en_file)} message(s) en file, rien envoyé (--a-vide)")
        depot.fermer()
        return 0

    envoyeur = EnvoyeurJournal()
    envoi = Expediteur(depot, envoyeur, config_pour).passer(maintenant)
    print(f"  expédition : {envoi.examines} examiné(s), {len(envoi.envoyes)} journalisé(s), "
          f"{len(envoi.differes)} différé(s), {len(envoi.reessais)} à réessayer, "
          f"{len(envoi.echecs)} en échec")
    if envoi.envoyes:
        print("    (EnvoyeurJournal : rien n'est réellement parti)")
    depot.fermer()
    return 0


if __name__ == "__main__":
    sys.exit(run())
