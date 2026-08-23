#!/usr/bin/env python3
"""Premier envoi RÉEL d'un SMS, à lancer à la main. UN seul message, vers TON numéro.

    python envoyer_un_sms.py 0612345678              # blanc : montre, n'envoie pas
    python envoyer_un_sms.py 0612345678 --envoyer    # envoie pour de vrai

Par défaut ce script **n'envoie rien** : il affiche le corps exact de la requête. Il faut
`--envoyer` pour qu'un SMS parte. Un script qui sort du système ne doit pas pouvoir le faire
par accident.

À quoi il sert : **valider mes hypothèses sur l'API d'OVH.** L'adaptateur suppose une
réponse contenant `ids`, `validReceivers` et `invalidReceivers` ; R22 teste cette forme,
mais avec des doubles que j'ai écrits. Ce script affiche la réponse BRUTE : c'est elle qui
tranche.

Variables requises (dans `.env` à la racine) :
    OVH_APPLICATION_KEY / OVH_APPLICATION_SECRET / OVH_CONSUMER_KEY
    OVH_SMS_COMPTE      le service SMS, forme « sms-ab12345-1 »

Le consumer key doit être limité à `POST /sms/*` avec une expiration — jamais `/*`.

Échec probable au premier essai : « sender not allowed » ou équivalent, si l'expéditeur
alphanumérique n'est pas encore déclaré auprès des opérateurs. C'est une information utile,
pas une panne : la déclaration prend des jours (Charte AF2M du 01/03/2026), autant le savoir
maintenant.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

from dotenv import load_dotenv

RACINE = pathlib.Path(__file__).parent
load_dotenv(RACINE.parent / ".env")

CFG = json.loads((RACINE / "config" / "dupont.json").read_text(encoding="utf-8"))
TEXTE = ("Bonjour, c'est un test technique Relais. Aucun rendez-vous n'est concerne. "
         "Vous pouvez ignorer ce message.")


def run() -> int:
    from relais_proto.envoi_ovh import EnvoyeurOVH, en_e164
    from relais_proto.messages import Canal, Destinataire, MessageSortant

    cibles = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(cibles) != 1:
        print(__doc__)
        return 2
    try:
        destinataire = en_e164(cibles[0])
    except Exception as exc:
        print(f"Numéro inexploitable : {exc}")
        return 2

    compte = os.environ.get("OVH_SMS_COMPTE")
    manquants = [n for n in ("OVH_APPLICATION_KEY", "OVH_APPLICATION_SECRET",
                             "OVH_CONSUMER_KEY", "OVH_SMS_COMPTE")
                 if not os.environ.get(n)]

    import datetime as dt
    message = MessageSortant(
        id="test-manuel", cle_idempotence="test-manuel", artisan_id="art-dupont",
        destinataire=Destinataire.CLIENT, canal=Canal.SMS, cible=destinataire,
        texte=TEXTE, cree_a=dt.datetime.now())

    print(f"destinataire : {destinataire}")
    print(f"expéditeur   : {CFG['sms']['expediteur']}")
    print(f"compte SMS   : {compte or '(absent)'}")
    print(f"texte        : {TEXTE}")
    print(f"longueur     : {len(TEXTE)} caractères")

    if "--envoyer" not in sys.argv:
        print("\nBlanc : rien n'est parti. Ajoute --envoyer pour envoyer réellement.")
        return 0
    if manquants:
        print(f"\nIdentifiants manquants : {', '.join(manquants)} (voir .env.example)")
        return 2
    try:
        import ovh  # noqa: F401
    except ImportError:
        print('\nSDK absent : pip install ovh')
        return 2

    from relais_proto.envoi_ovh import transport_sdk

    # transport enveloppé pour afficher la réponse BRUTE : c'est tout l'intérêt du test
    reel = transport_sdk()

    def transport_bavard(chemin, **corps):
        print(f"\nPOST {chemin}")
        print(json.dumps(corps, ensure_ascii=False, indent=2))
        reponse = reel(chemin, **corps)
        print("\nréponse brute d'OVH :")
        print(json.dumps(reponse, ensure_ascii=False, indent=2, default=str))
        return reponse

    try:
        reference = EnvoyeurOVH(transport_bavard, compte).envoyer(message, CFG)
    except Exception as exc:
        print(f"\n❌ {type(exc).__name__}: {exc}")
        print("Si le motif porte sur l'expéditeur, c'est la déclaration du Sender ID qui "
              "manque — délai de plusieurs jours, à lancer sans attendre.")
        return 1
    print(f"\n✅ envoyé, référence : {reference}")
    print("Compare la réponse brute ci-dessus à ce que suppose l'adaptateur "
          "(ids / validReceivers / invalidReceivers) et dis-moi si ça diverge.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
