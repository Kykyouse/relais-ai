#!/usr/bin/env python3
"""Point d'entrée du serveur : assemble l'API avec ses collaborateurs de production.

    uvicorn serveur:app --host 0.0.0.0 --port 8000

Variables requises (fichier `.env` à la racine) :
    DATABASE_URL             Postgres (Supabase, région UE) — connexion directe
    DATABASE_URL_POOLER      repli si la directe ne répond pas (IPv6)
    RELAIS_WEBHOOK_SECRET    secret partagé avec la plateforme vocale
    RELAIS_BASE_URL          racine publique des liens de validation client (SMS)

Variables optionnelles :
    RELAIS_COOKIE_SECURE     `false` UNIQUEMENT pour tester en HTTP local depuis un
                             téléphone. Défaut `true` : la production ne doit pas pouvoir
                             régresser par oubli.
    RELAIS_SONDE_VOIX        allume la sonde de l'étape 0 du chantier voix (route
                             `/voix/sonde`, cf. `sonde_voix.py`). Valeur = chemin du
                             journal, ou `1` pour `proto/sonde-vapi.jsonl`. Absente par
                             défaut : la route n'est alors même pas déclarée.
    RELAIS_VERSION           identifiant de la révision déployée, exposé par `/sante`.
                             Sans elle, il est lu depuis git ; utile quand le dépôt n'est
                             pas présent (conteneur, archive).
    RELAIS_VOIX_ARTISAN      artisan auquel rattacher les appels vocaux SANS numéro
                             appelé — c'est-à-dire les appels web (`call.type ==
                             "webCall"`), le mode du spike. Sans elle, un tel appel est
                             refusé en 404 plutôt que rattaché au hasard. Inutile dès
                             qu'un vrai numéro est branché : le numéro composé l'emporte.

Rien de métier ici : uniquement du câblage. Les collaborateurs sont les mêmes objets que
ceux des tests, avec les implémentations réelles à la place des doubles — c'est tout
l'intérêt d'avoir injecté le dépôt, le LLM et l'horloge.
"""
from __future__ import annotations

import os
import pathlib

from dotenv import load_dotenv

from relais_proto.api import creer_app
from relais_proto.depot_pg import DepotPostgres, candidats_env, resoudre_connexion
from relais_proto.envoi import choisir_envoyeur
from relais_proto.llm import make_llm
from relais_proto.registre import Registre

RACINE = pathlib.Path(__file__).parent
load_dotenv(RACINE.parent / ".env")


def _exige(nom: str) -> str:
    valeur = os.environ.get(nom)
    if not valeur:
        raise RuntimeError(
            f"{nom} manquant. Renseigne-le dans .env (voir .env.example) — le serveur "
            f"refuse de démarrer plutôt que de tourner à moitié configuré.")
    return valeur


def _cookie_secure() -> bool:
    """Défaut TRUE, et seul le mot exact « false » le désactive.

    Fail-safe volontaire : une faute de frappe (`flase`, `False!`, `0 `) laisse le cookie
    en `Secure` plutôt que de l'ouvrir en clair. C'est le sens de la demande — la prod ne
    doit pas pouvoir régresser par oubli ou par étourderie.

    Pourquoi ce réglage existe : un cookie `Secure` est jeté par le navigateur en HTTP.
    `localhost` est une exception chez Chrome, **mais pas une IP de réseau local** — d'où
    une connexion qui boucle sur le formulaire quand on teste depuis un téléphone sur
    `http://192.168.x.x:8000` (constaté le 24/08).
    """
    return (os.environ.get("RELAIS_COOKIE_SECURE") or "true").strip().lower() != "false"


def _version() -> str:
    """Le commit qui tourne, ou « inconnue ».

    Lu depuis git au démarrage, avec un repli sur la variable `RELAIS_VERSION` pour les
    déploiements où le dépôt n'est pas là (conteneur, archive). Jamais bloquant : une
    version inconnue ne doit pas empêcher le serveur de démarrer.
    """
    depuis_env = (os.environ.get("RELAIS_VERSION") or "").strip()
    if depuis_env:
        return depuis_env
    try:
        import subprocess
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           cwd=RACINE.parent, capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "inconnue"


def _sonde_voix() -> pathlib.Path | None:
    """Chemin du journal de la sonde, ou None — le défaut, qui ne déclare pas la route.

    Éteinte par défaut et non « protégée par le secret » : une sonde est un outil de
    diagnostic, et la seule garantie qui tienne dans le temps est qu'il n'y ait rien à
    atteindre. La variable accepte un chemin (pour ranger le journal où l'on veut) ou un
    simple `1`, parce qu'on l'allume depuis un terminal en cinq secondes, une fois.
    """
    valeur = (os.environ.get("RELAIS_SONDE_VOIX") or "").strip()
    if not valeur or valeur.lower() in ("0", "false", "non"):
        return None
    if valeur.lower() in ("1", "true", "oui"):
        return RACINE / "sonde-vapi.jsonl"
    return pathlib.Path(valeur)


def construire():
    # même repli que le worker et le lanceur de tests : l'hôte direct de Supabase est en
    # IPv6 et peut être injoignable selon le réseau. Le pooler prend alors le relais.
    dsn, opts, libelle = resoudre_connexion(candidats_env())
    print(f"base Postgres : {libelle}")
    depot = DepotPostgres(dsn, **opts)
    # Depuis la migration 008, le registre vient de la TABLE `artisan`, pas du fichier.
    # `config/artisans.json` reste la graine (`python semer_artisans.py --ecrire`) ; les
    # `config/*.json` restent des fichiers versionnés, lus par identifiant.
    registre = Registre.charger(depot, RACINE / "config",
                                _exige("RELAIS_WEBHOOK_SECRET"))
    # un client LLM neuf par tour : make_llm() rend le mode réel si la clé est là,
    # le mode scripté sinon — l'appel aboutit dans les deux cas (dégradation gracieuse)
    # base_url EXIGÉE, sans valeur par défaut : elle part dans un SMS. Un lien pointant
    # sur un domaine d'exemple serait mort chez le client, sans erreur côté serveur.
    secure = _cookie_secure()
    # Annoncé À CHAQUE démarRAGE, pas seulement quand il est faible : le 24/08, c'est
    # l'ABSENCE de cet avertissement qui a fait perdre un tour de diagnostic. Un état qu'on
    # ne voit que lorsqu'il est anormal ne se distingue pas d'un réglage non pris en compte.
    brut = os.environ.get("RELAIS_COOKIE_SECURE")
    print(f"cookie de session : Secure={secure} (RELAIS_COOKIE_SECURE={brut!r})")
    if not secure:
        print("⚠️  cookie émis SANS Secure : acceptable en test HTTP local, "
              "JAMAIS en production.")
    # L'API a besoin d'un envoyeur pour LE code de connexion, et pour lui seul : un code
    # qui arriverait au prochain passage du cron ne serait pas un code de connexion. Même
    # sélection que le worker (`RELAIS_SMS`), donc même défaut inoffensif.
    envoyeur, mode_sms = choisir_envoyeur()
    print(f"envoi des codes de connexion : {mode_sms}")
    version = _version()
    # Annoncée au démarrage, comme le réglage du cookie et la sonde : c'est la première
    # chose qu'on veut savoir quand un appel se comporte autrement que l'arbre local.
    print(f"version déployée : {version}")
    voix_artisan = (os.environ.get("RELAIS_VOIX_ARTISAN") or "").strip() or None
    if voix_artisan:
        # annoncé, comme la sonde : c'est un rattachement PAR DÉFAUT, donc exactement le
        # genre de réglage qu'on oublie et qui envoie les leads chez le mauvais artisan
        print(f"appels vocaux sans numéro appelé → artisan {voix_artisan!r} "
              f"(RELAIS_VOIX_ARTISAN)")
    sonde = _sonde_voix()
    # Annoncée au démarrage, comme le réglage du cookie et pour la même raison : un état
    # qu'on ne voit que lorsqu'il est anormal ne se distingue pas d'un réglage non pris en
    # compte. Ici l'enjeu est inverse — c'est l'oubli d'ÉTEINDRE qu'on veut voir.
    if sonde is not None:
        print(f"⚠️  SONDE VOIX ALLUMÉE : POST /voix/sonde → {sonde} "
              f"(diagnostic étape 0 ; à éteindre après usage)")
    return creer_app(depot, registre, make_llm, base_url=_exige("RELAIS_BASE_URL"),
                     cookie_secure=secure, envoyeur=envoyeur, sonde_voix=sonde,
                     voix_artisan_defaut=voix_artisan, version=version)


app = construire()
