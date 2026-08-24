#!/usr/bin/env python3
"""Un passage des workers de fond, à appeler par un cron.

    python worker.py            # un passage : expiration puis expédition
    python worker.py --a-vide   # sans rien envoyer (inspection seule)

Deux passages enchaînés, dans cet ordre :
  1. `WorkerExpiration` — les RDV échus : créneau libéré, lead en alerte, messages en file.
  2. `Expediteur` — la file sortante : plage de silence, réessais, échec définitif.

L'ENVOI RÉEL EST OPT-IN, par `RELAIS_SMS` :

    RELAIS_SMS=journal   (défaut)  rien ne part, tout est journalisé
    RELAIS_SMS=ovh                 envoi RÉEL via OVH (exige OVH_* et OVH_SMS_COMPTE)

Le défaut est volontairement inoffensif : un cron mal configuré ne doit pas se mettre à
écrire à de vrais clients. `--a-vide` n'envoie ni ne marque rien, quel que soit le mode.

`RELAIS_SMS_NUMERO_COURT=1` envoie via un numéro court (aucune déclaration d'expéditeur
requise). ⚠️ Les URL y sont **bloquées** : les SMS de reproposition, qui portent le lien de
validation, échoueront alors définitivement — visiblement, dans le rapport. C'est un mode de
transition, pas un mode de production.

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

SEUIL_CREDITS = 20   # en dessous, on alerte : recharger prend du temps, une file
                     # bloquée pendant ce temps-là, c'est des clients non prévenus
RACINE = pathlib.Path(__file__).parent
load_dotenv(RACINE.parent / ".env")


def _choisir_envoyeur():
    """Rend (envoyeur, libellé). Défaut inoffensif : un cron mal configuré ne doit pas se
    mettre à écrire à de vrais clients. L'envoi réel se demande explicitement."""
    mode = (os.environ.get("RELAIS_SMS") or "journal").strip().lower()
    if mode != "ovh":
        return EnvoyeurJournal(), "journal (rien ne part)"
    compte = os.environ.get("OVH_SMS_COMPTE")
    if not compte:
        raise RuntimeError("RELAIS_SMS=ovh exige OVH_SMS_COMPTE (voir .env.example)")
    from relais_proto.envoi_ovh import EnvoyeurOVH, transport_sdk
    numero_court = os.environ.get("RELAIS_SMS_NUMERO_COURT") == "1"
    libelle = "OVH — ENVOI RÉEL" + (" par NUMÉRO COURT (URL bloquées : les SMS de "
                                    "reproposition échoueront)" if numero_court else "")
    return EnvoyeurOVH(transport_sdk(), compte, numero_court=numero_court), libelle


def run() -> int:
    from relais_proto import temps
    from relais_proto.depot_pg import candidats_env, resoudre_connexion
    try:
        dsn, opts, libelle = resoudre_connexion(candidats_env())
    except Exception as exc:
        print(exc)
        return 2
    print(f"  base : {libelle}")
    depot = DepotPostgres(dsn, **opts)
    # même source que le serveur : la table `artisan` (migration 008). Un artisan écarté
    # ici n'est pas deviné — son travail reste en file et apparaît dans le rapport.
    registre = Registre.charger(depot, RACINE / "config",
                                os.environ.get("RELAIS_WEBHOOK_SECRET", "inutile"),
                                journal=lambda m: print(f"  {m}"))

    def config_pour(artisan_id):
        artisan = registre.artisan(artisan_id)
        return artisan.config if artisan else None

    # l'un des DEUX seuls endroits où l'horloge système entre (l'autre est api.py).
    # Affichée à la pendule française : un log de cron se lit à l'heure du pays, l'instant
    # UTC est rappelé entre parenthèses pour pouvoir le recouper avec la base.
    maintenant = temps.maintenant()
    print(f"passage du {temps.en_local(maintenant).isoformat(timespec='seconds')} "
          f"({maintenant.strftime('%H:%M:%S')} UTC)")

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

    try:
        envoyeur, mode = _choisir_envoyeur()
    except Exception as exc:      # configuration incomplète : message net, pas une trace
        print(f"  {exc}")
        depot.fermer()
        return 2
    print(f"  mode d'envoi : {mode}")
    envoi = Expediteur(depot, envoyeur, config_pour).passer(maintenant)
    print(f"  expédition : {envoi.examines} examiné(s), {len(envoi.envoyes)} envoyé(s), "
          f"{len(envoi.differes)} différé(s), {len(envoi.reessais)} à réessayer, "
          f"{len(envoi.echecs)} en échec | coût {envoi.cout_total} crédit(s)")
    for e in envoi.echecs:
        print(f"    ! {e}")
    if envoi.envoyes and isinstance(envoyeur, EnvoyeurJournal):
        print("    (EnvoyeurJournal : rien n'est réellement parti)")
    # Réserve de crédits : une réserve à zéro arrête tous les SMS clients sans provoquer
    # d'erreur applicative. Elle doit être VISIBLE à chaque passage, pas découverte par un
    # client qui n'a rien reçu.
    restants = getattr(envoyeur, "credits_restants", None)
    if restants is not None:
        alerte = "  ⚠️ RECHARGER" if restants < SEUIL_CREDITS else ""
        print(f"  crédits SMS restants : {restants}{alerte}")
    depot.fermer()
    return 0


if __name__ == "__main__":
    sys.exit(run())
