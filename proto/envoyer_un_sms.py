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


# Diagnostic par motif. Un indice unique et générique envoie chercher au mauvais endroit :
# le 24/08, « service does not exist » a été lu comme un problème de Sender ID alors que
# c'était le nom du service. Ordre volontaire — le premier motif reconnu gagne.
_PISTES = [
    (("does not exist", "ResourceNotFound"),
     "→ Le NOM DU SERVICE SMS est faux, ou le service SMS n'a pas été commandé.\n"
     "  Créer un compte OVH ne crée PAS de service SMS : il faut le commander et le\n"
     "  créditer. Nom visible dans l'espace client (Telecom > SMS), ou :\n"
     "      python envoyer_un_sms.py --comptes"),
    # NotGrantedCall AVANT les motifs d'identifiants : la clé est valide, c'est sa PORTÉE
    # qui ne couvre pas l'appel. Les confondre envoie vérifier un triplet qui va bien.
    (("NotGrantedCall", "not been granted"),
     "→ PORTÉE du consumer key : la clé est valide, mais cet appel n'est pas dans ses\n"
     "  règles d'accès. Deux options :\n"
     "    · le plus simple, et le plus sûr : lire le nom du service dans l'espace client\n"
     "      OVH (Telecom > SMS) et le mettre dans OVH_SMS_COMPTE — la clé reste minimale ;\n"
     "    · ou ajouter `GET /sms` aux règles de la clé, si tu veux --comptes. Lecture\n"
     "      seule, aucun envoi possible avec ce droit."),
    (("InvalidKey", "InvalidSignature", "InvalidCredential", "Forbidden",
      "Unauthorized", "403"),
     "→ IDENTIFIANTS : vérifier le triplet application key / secret / consumer key, et\n"
     "  que le consumer key n'a pas expiré."),
    (("sender", "Sender", "expediteur"),
     "→ L'EXPÉDITEUR est refusé : le Sender ID alphanumérique doit être déclaré auprès\n"
     "  des opérateurs (Charte AF2M du 01/03/2026). Délai de plusieurs jours."),
    (("credit", "Credit", "insufficient"),
     "→ Plus de CRÉDITS SMS : en recharger dans l'espace client."),
]


def _diagnostic(texte: str) -> str:
    for motifs, piste in _PISTES:
        if any(m in texte for m in motifs):
            return piste
    # Cette table se construit une panne à la fois : elle ne saura jamais tout d'avance.
    # Le repli doit donc rester utile — nommer les familles les plus probables plutôt que
    # de renvoyer un « je ne sais pas » qui laisse sans prise.
    return ("→ Motif non reconnu. Par ordre de probabilité : service SMS non commandé ou\n"
            "  mal nommé · portée du consumer key trop étroite · Sender ID non déclaré ·\n"
            "  crédits épuisés.\n"
            "  Rapporte le message et le Query-ID : ils enrichiront ce diagnostic, et\n"
            "  confirmeront ou démentiront l'hypothèse encodée dans l'adaptateur.")


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
        print(_diagnostic(f"{type(exc).__name__}: {exc}"))
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
    # Garde contre le gabarit recopié tel quel. Sans elle, on part appeler OVH avec un nom
    # de service inventé et l'erreur renvoyée fait chercher ailleurs (vécu le 24/08).
    if compte and ("remplace" in compte.lower() or compte == "sms-ab12345-1"):
        print(f"\nOVH_SMS_COMPTE vaut encore le gabarit : {compte!r}")
        print("Le vrai nom est dans l'espace client OVH (Telecom > SMS), forme")
        print("« sms-xy12345-1 », ou :  python envoyer_un_sms.py --comptes")
        return 2

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
        print(_diagnostic(f"{type(exc).__name__}: {exc}"))
        return 1
    print(f"\n✅ envoyé, référence : {reference}")
    print("Compare la réponse brute ci-dessus à ce que suppose l'adaptateur "
          "(ids / validReceivers / invalidReceivers) et dis-moi si ça diverge.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
