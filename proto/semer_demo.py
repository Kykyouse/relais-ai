#!/usr/bin/env python3
"""Crée un artisan de DÉMONSTRATION et lui fabrique un historique d'appels crédible.

    python semer_demo.py                                   # blanc : dit ce qu'il ferait
    python semer_demo.py --ecrire --telephone "06 12 34 56 78"
    python semer_demo.py --env-file ../.env.prod --ecrire --telephone "06 …"
    python semer_demo.py --env-file ../.env.prod --effacer  # retire tout

POURQUOI CE SCRIPT EXISTE (21/09). La table `artisan` de la production est vide, et
volontairement : `semer_artisans.py` sème `config/artisans.json`, dont les jetons sont
des jetons de DÉV documentés en clair dans le dépôt — les pousser en production
publierait des identifiants. Conséquence non voulue : **personne ne pouvait ouvrir
l'application, Geoffrey compris.** La connexion cherche l'artisan par son MOBILE dans
la table ; aucune ligne, aucune connexion possible.

Ce script est donc la première forme d'onboarding : il crée un artisan avec un jeton
**GÉNÉRÉ**, jamais un jeton du dépôt. Ce n'est pas encore la page d'admin — c'est le
geste que cette page fera, écrit une fois pour qu'on puisse voir le produit.

CE QU'IL ÉCRIT, et rien d'autre : une ligne `artisan` d'identifiant `demo-nelyo`, et
des appels/leads/RDV qui lui appartiennent. `--effacer` les retire tous. Aucune autre
donnée n'est touchée — le script refuse de supprimer quoi que ce soit d'autre.

LES APPELS SONT JOUÉS PAR LE VRAI MOTEUR, avec `MockLLM` comme interlocuteur. Écrire
des leads à la main aurait fabriqué une deuxième définition de ce qu'est un lead, et
la démo aurait divergé du produit sans prévenir. Ici les transcripts sont de vraies
conversations, les scores sortent de `scoring.py`, les catégories de `engine.py`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import secrets
import sys

from dotenv import load_dotenv

RACINE = pathlib.Path(__file__).parent

ARTISAN_DEMO = "demo-nelyo"
NUMERO_RELAIS_DEMO = "+33189700001"   # fictif : aucune plateforme vocale ne le connaît
CONFIG_DEMO = "dupont.json"

# Les appels de la démo. Chacun déclare la catégorie ATTENDUE : si le moteur en produit
# une autre, le script s'arrête au lieu de semer une démo qui ment. Une démo fausse est
# pire qu'une démo absente — c'est celle qu'on montre à un prospect.
#
# L'ANCIENNETÉ EST EN MINUTES, et ce n'est pas du zèle. Premier essai le 21/09 : l'appel
# urgent était daté de 2 h dans le passé, or un RDV URGENT a une fenêtre de validation de
# 2 h (`delai_max_urgence_heures`). Il est donc né expiré, le cron l'a passé à `expire`
# dans les dix minutes, et la boîte de validation — l'écran principal, celui avec les
# boutons — était vide dans la démo. Une démo dont la page maîtresse est vide ne se
# rattrape pas devant un prospect.
APPELS_DEMO = [
    {
        # URGENT : fenêtre de 2 h seulement. Daté d'il y a 20 min, il reste donc
        # décidable ~1 h 40. C'est le cas le plus démonstratif (5/5, bandeau urgence),
        # et c'est aussi le plus périssable.
        "il_y_a_min": 20,
        "categorie": "rdv_reserve",
        "lignes": [
            "Bonjour, j'ai une fuite sous l'évier, l'eau coule encore, c'est urgent !",
            "Je suis à Nogent-sur-Marne, 94130, je suis propriétaire",
            "C'est en cours là, ça goutte dans le placard",
            "Je m'appelle Garcia, mon numéro c'est 06 12 34 56 78",
            "Oui c'est bien ça",
            "Le premier créneau c'est parfait, je suis chez moi quand vous voulez",
        ],
    },
    {
        # NON URGENT : fenêtre de 24 h. C'est LUI qui fait qu'une démo montrée demain
        # matin a encore quelque chose à valider à l'écran.
        "il_y_a_min": 3 * 60,
        "categorie": "rdv_reserve",
        "lignes": [
            "Bonjour, mon robinet de salle de bain goutte un peu",
            "Nogent-sur-Marne, 94130, je suis propriétaire",
            "Je m'appelle Petit, mon numéro c'est 06 55 66 77 88",
            "Oui c'est bien ça",
            "Le premier créneau c'est parfait",
        ],
    },
    {
        # LE cas qui justifie la page « Mes appels » : un client joignable, qualifié,
        # qui n'a pas réservé. Avant elle, ce lead-là n'apparaissait nulle part.
        "il_y_a_min": 5 * 60,
        "categorie": "a_rappeler",
        "lignes": [
            "Bonjour, ma chaudière ne s'allume plus",
            "Nogent, 94130",
            "Je m'appelle Lefèvre, mon numéro c'est 06 22 33 44 55",
            "Oui c'est bien ça",
            "Non aucun des deux ne me va",
            "Non plus, je travaille toute la semaine",
            "Non vraiment aucun",
        ],
    },
    {
        "il_y_a_min": 6 * 60,
        "categorie": "injoignable",
        "lignes": [
            "Bonjour, j'ai une petite fuite au robinet de la cuisine",
            "Nogent, 94130",
            "Non je préfère pas donner mon numéro, je rappellerai",
            "Non, pas de numéro je vous dis",
            "Non vraiment pas",
        ],
    },
    {
        "il_y_a_min": 26 * 60,
        "categorie": "hors_zone",
        "lignes": [
            "Bonjour, je voudrais un devis pour une pompe à chaleur",
            "J'habite à Champigny, 94500",
            "Oui c'est bien ça",
        ],
    },
]


def _jouer(depot, cfg, quand: dt.datetime, lignes: list[str]):
    """Un appel complet, par le moteur réel. Rend (lead, donnees)."""
    from relais_proto.calendar_stub import CalendarStub
    from relais_proto.engine import Conversation
    from relais_proto.llm import MockLLM
    from relais_proto.scoring import build_lead

    convo = Conversation(cfg, MockLLM(), CalendarStub(cfg, now=quand))
    convo.open()
    for ligne in lignes:
        if convo.state.value in ("S11", "FIN"):
            break
        convo.process(ligne)
    donnees = build_lead(convo)
    appel = depot.ouvrir_appel(ARTISAN_DEMO, quand)
    depot.enregistrer_etat(appel.id, convo.to_dict())
    return depot.cloturer_appel(appel.id, donnees, quand), donnees


def _effacer(depot) -> None:
    """Retire l'artisan de démo et TOUT ce qui lui appartient, dans l'ordre des clés
    étrangères. Les identifiants sont en dur : ce script ne doit pas pouvoir servir à
    supprimer autre chose, même en se trompant d'argument."""
    with depot.cx.cursor() as cur:
        for sql in (
            "delete from message_sortant where artisan_id = %s",
            "delete from rdv where artisan_id = %s",
            "delete from lead where artisan_id = %s",
            "delete from appel where artisan_id = %s",
            "delete from code_connexion where artisan_id = %s",
            "delete from session_artisan where artisan_id = %s",
            "delete from artisan where id = %s",
        ):
            cur.execute(sql, (ARTISAN_DEMO,))
            print(f"   {cur.rowcount:>3} ligne(s) — {sql.split(' where')[0]}")


def run() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ecrire", action="store_true", help="écrire réellement")
    ap.add_argument("--effacer", action="store_true", help="retirer la démo")
    ap.add_argument("--telephone", default="",
                    help="le MOBILE qui servira à se connecter (le tien)")
    ap.add_argument("--env-file", default="",
                    help="fichier d'environnement à charger en priorité "
                         "(ex. ../.env.prod). Évite de faire transiter le mot de passe "
                         "de la base par la ligne de commande.")
    args = ap.parse_args()

    # `--env-file` gagne sur `.env` ; sans lui, le `.env` local, sans override, pour que
    # les variables déjà posées sur la ligne de commande l'emportent (convention du repo).
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

    from relais_proto import produit
    from relais_proto.depot import LigneArtisan
    from relais_proto.depot_pg import (DepotPostgres, candidats_env,
                                       resoudre_connexion)
    from relais_proto.registre import empreinte as emp_token

    try:
        dsn, opts, libelle = resoudre_connexion(candidats_env())
    except Exception as exc:
        print(exc)
        return 2
    depot = DepotPostgres(dsn, **opts)
    # L'HÔTE, pas seulement « directe » : ce script ÉCRIT, et se tromper de base est le
    # mode de panne que R92 a appris à nommer.
    print(f"base : {libelle} → {depot.cx.info.host}")
    print()

    try:
        if args.effacer:
            if not args.ecrire:
                print(f"Blanc : dirait quoi supprimer pour « {ARTISAN_DEMO} ». "
                      "Relance avec --ecrire --effacer.")
                return 0
            print(f"suppression de « {ARTISAN_DEMO} » :")
            _effacer(depot)
            print("\nDémo retirée.")
            return 0

        if not args.telephone:
            print("--telephone est obligatoire : c'est le mobile par lequel tu te "
                  "connecteras (le code SMS est envoyé à CE numéro).")
            return 2

        cfg = produit.appliquer(
            json.loads((RACINE / "config" / CONFIG_DEMO).read_text(encoding="utf-8")),
            produit.charger(RACINE / "config"))

        # Le jeton est GÉNÉRÉ ici et affiché UNE fois : la base n'en garde que
        # l'empreinte, comme pour tous les autres. Personne ne pourra le relire.
        jeton = f"nelyo_{secrets.token_urlsafe(24)}"

        # On réutilise la normalisation DU REGISTRE plutôt que d'en écrire une ici : la
        # recherche par téléphone passe par elle des deux côtés, et deux normalisations
        # qui divergent donneraient un artisan introuvable au moment de se connecter —
        # c'est-à-dire un échec sans message, au pire endroit. Ma première version
        # faisait `lstrip("0")` sur les chiffres bruts et transformait « +33 6 … » en
        # « +3333… » : le genre de faute qui ne se voit qu'à la connexion.
        from relais_proto.registre import _normaliser
        national = _normaliser(args.telephone)
        if not (len(national) == 10 and national[:2] in ("06", "07")):
            print(f"« {args.telephone} » ne donne pas un mobile français "
                  f"(lu : {national!r}). Il doit pouvoir RECEVOIR le code de connexion.")
            return 2
        tel = "+33" + national[1:]

        print(f"artisan      : {ARTISAN_DEMO} ({cfg['entreprise']['nom']})")
        print(f"mobile       : {tel}  ← c'est lui qui reçoit le code de connexion")
        print(f"numéro Relais: {NUMERO_RELAIS_DEMO} (fictif)")
        print(f"appels       : {len(APPELS_DEMO)} à fabriquer")
        print()
        if not args.ecrire:
            print("Blanc : rien écrit. Relance avec --ecrire pour appliquer.")
            return 0

        depot.enregistrer_artisan(LigneArtisan(
            id=ARTISAN_DEMO, nom_affiche=cfg["entreprise"]["nom"],
            numero_relais=NUMERO_RELAIS_DEMO, telephone=tel,
            config_fichier=CONFIG_DEMO, token_sha256=emp_token(jeton),
            etat_abonnement="actif"))
        print(f"artisan écrit.")

        from relais_proto import temps
        maintenant = temps.maintenant()
        for spec in APPELS_DEMO:
            quand = maintenant - dt.timedelta(minutes=spec["il_y_a_min"])
            lead, donnees = _jouer(depot, cfg, quand, spec["lignes"])
            obtenue = donnees.get("categorie")
            if obtenue != spec["categorie"]:
                print(f"\n  ARRÊT : appel attendu « {spec['categorie']} », "
                      f"moteur rendu « {obtenue} ». La démo ne sera pas semée à moitié "
                      f"fausse — corrige les répliques ou l'attendu.")
                return 2
            marque = ""
            if donnees.get("rdv"):
                rdv = depot.creer_rdv(lead_id=lead.id, hold=donnees["rdv"],
                                      lead_donnees=donnees, cfg=cfg, maintenant=quand)
                # notifié : c'est l'état dans lequel la boîte de validation l'affiche
                # avec ses boutons. Un RDV en tampon n'y apparaîtrait pas comme décidable.
                rdv.notifier(quand)
                depot.sauver_rdv(rdv)
                # GARDE-FOU, né du premier essai : un RDV semé DÉJÀ EXPIRÉ disparaît de
                # la boîte de validation au passage suivant du cron, et la démo montre
                # un écran vide. Le script le dit au lieu de laisser le découvrir devant
                # quelqu'un.
                if rdv.est_echu(maintenant):
                    print(f"\n  ARRÊT : le RDV est déjà expiré "
                          f"(créé il y a {spec['il_y_a_min']} min, échéance "
                          f"{rdv.expire_a:%H:%M} UTC). Un RDV urgent n'a que "
                          f"{cfg['validation']['delai_max_urgence_heures']} h de "
                          f"validation — rapproche `il_y_a_min` de zéro.")
                    return 2
                reste = int((rdv.expire_a - maintenant).total_seconds() // 60)
                marque = f", RDV à valider (encore {reste} min)"
            print(f"  il y a {spec['il_y_a_min']:>4} min — {obtenue}"
                  f" (score {donnees.get('score')}){marque}")

        print()
        print("=" * 68)
        print("JETON PORTEUR (affiché UNE SEULE FOIS, la base n'a que son empreinte) :")
        print(f"  {jeton}")
        print("=" * 68)
        print()
        print("POUR OUVRIR L'APPLICATION :")
        print(f"  1. https://nelyo-api.onrender.com/connexion")
        print(f"  2. saisis {args.telephone}")
        print( "  3. le code à 6 chiffres N'ARRIVE PAS par SMS (RELAIS_SMS=journal) :")
        print( "     il s'affiche dans les logs de `nelyo-api` sur Render.")
        print( "     Dashboard Render → nelyo-api → Logs, cherche « code de connexion ».")
        print( "  4. la session dure 90 jours : c'est à faire une seule fois.")
        return 0
    finally:
        depot.fermer()


if __name__ == "__main__":
    sys.exit(run())
