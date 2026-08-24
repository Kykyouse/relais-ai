#!/usr/bin/env python3
"""Premier envoi RÉEL d'un SMS, à lancer à la main. UN seul message, vers TON numéro.

    python envoyer_un_sms.py 0612345678              # blanc : montre, n'envoie pas
    python envoyer_un_sms.py 0612345678 --envoyer    # envoie pour de vrai
    python envoyer_un_sms.py 0612345678 --envoyer --numero-court
                                                    # via un numero court OVH : aucune
                                                    # declaration d'expediteur requise,
                                                    # MAIS les URL y sont bloquees ->
                                                    # tests seulement, jamais le lien 1-tap
    python envoyer_un_sms.py 0612345678 --envoyer --expediteur Relais
                                                    # force l'expediteur, sans toucher
                                                    # sms.expediteur de dupont.json

Par défaut ce script **n'envoie rien** : il affiche le corps exact de la requête. Il faut
`--envoyer` pour qu'un SMS parte. Un script qui sort du système ne doit pas pouvoir le faire
par accident.

À quoi il sert : **valider mes hypothèses sur l'API d'OVH.** L'adaptateur suppose une
réponse contenant `ids`, `validReceivers` et `invalidReceivers` ; R22 teste cette forme,
mais avec des doubles que j'ai écrits. Ce script affiche la réponse BRUTE : c'est elle qui
tranche.

Variables requises (dans `.env` à la racine) :
    OVH_APPLICATION_KEY / OVH_APPLICATION_SECRET / OVH_CONSUMER_KEY
    OVH_SMS_COMPTE      le service SMS, lisible dans l'espace client (Telecom > SMS)

Le consumer key doit être limité à `POST /sms/*` avec une expiration — jamais `/*`.

En cas d'échec, le script affiche une PISTE selon le motif renvoyé par OVH (expéditeur non
déclaré, service inconnu, portée de la clé, crédits). La table de correspondance vit dans
`relais_proto/envoi_ovh.py` et est couverte par R22.
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
TEXTE = ("Bonjour Adélan, c'est un test technique Relais-ai. Aucun rendez-vous n'est concerne. "
         "Vous pouvez ignorer ce message.")


from relais_proto.envoi_ovh import diagnostic  # noqa: E402 — après load_dotenv


def _lister_comptes() -> int:
    """`GET /sms` : liste les services SMS du compte. Demande le droit `GET /sms` sur le
    consumer key — seul droit de LECTURE utile ici, et il ne permet aucun envoi."""
    try:
        import ovh
    except ImportError:
        print("SDK absent : pip install ovh")
        return 2
    try:
        comptes = ovh.Client(endpoint="ovh-eu").get("/sms")
    except Exception as exc:
        print(f"❌ {type(exc).__name__}: {exc}")
        print(diagnostic(f"{type(exc).__name__}: {exc}"))
        return 1
    if not comptes:
        print("Aucun service SMS sur ce compte : il faut le commander et le créditer.")
        return 1
    print("Services SMS disponibles (à mettre dans OVH_SMS_COMPTE) :")
    for c in comptes:
        print(f"   {c}")
    return 0


def run() -> int:
    from relais_proto.envoi_ovh import EnvoyeurOVH, en_e164
    from relais_proto.messages import Canal, Destinataire, MessageSortant

    if "--comptes" in sys.argv:
        return _lister_comptes()

    # --expediteur consomme sa valeur AVANT le filtre des cibles, sinon elle serait
    # prise pour un destinataire.
    args = sys.argv[1:]
    expediteur_force = None
    if "--expediteur" in args:
        i = args.index("--expediteur")
        if i + 1 >= len(args) or args[i + 1].startswith("--"):
            print("--expediteur attend une valeur (ex : --expediteur 0612345678)")
            return 2
        expediteur_force = args[i + 1]
        del args[i:i + 2]
        # Un expéditeur-numéro se déclare chez OVH au format international : même
        # normalisation que les destinataires. Un alphanumérique passe tel quel.
        import re as _re
        if _re.fullmatch(r"[\d+\s.\-]+", expediteur_force):
            expediteur_force = en_e164(expediteur_force)

    numero_court = "--numero-court" in args
    if numero_court and expediteur_force:
        print("--numero-court et --expediteur sont contradictoires : en numéro court,")
        print("OVH impose senderForResponse et refuse toute clé « sender ».")
        return 2

    cibles = [a for a in args if not a.startswith("--")]
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
    # Garde contre le gabarit recopié tel quel. Sans elle, on part appeler OVH avec un nom
    # de service inventé et l'erreur renvoyée fait chercher ailleurs (vécu le 24/08).
    if compte and ("remplace" in compte.lower() or compte == "sms-ab12345-1"):
        print(f"\nOVH_SMS_COMPTE vaut encore le gabarit : {compte!r}")
        print("Le vrai nom est dans l'espace client OVH (Telecom > SMS), forme")
        print("« sms-xy12345-1 », ou :  python envoyer_un_sms.py --comptes")
        return 2

    if expediteur_force:
        CFG.setdefault("sms", {})["expediteur"] = expediteur_force

    import datetime as dt
    message = MessageSortant(
        id="test-manuel", cle_idempotence="test-manuel", artisan_id="art-dupont",
        destinataire=Destinataire.CLIENT, canal=Canal.SMS, cible=destinataire,
        texte=TEXTE, cree_a=dt.datetime.now())

    print(f"destinataire : {destinataire}")
    if numero_court:
        print("expéditeur   : NUMÉRO COURT OVH (senderForResponse) — mode TEST")
        print("               les SMS contenant une URL sont bloqués dans ce mode")
    else:
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
        reference = EnvoyeurOVH(transport_bavard, compte,
                                numero_court=numero_court).envoyer(message, CFG)
    except Exception as exc:
        print(f"\n❌ {type(exc).__name__}: {exc}")
        print(diagnostic(f"{type(exc).__name__}: {exc}"))
        return 1
    print(f"\n✅ envoyé, référence : {reference}")
    print("Compare la réponse brute ci-dessus à ce que suppose l'adaptateur "
          "(ids / validReceivers / invalidReceivers) et dis-moi si ça diverge.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
