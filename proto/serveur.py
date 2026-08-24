#!/usr/bin/env python3
"""Point d'entrée du serveur : assemble l'API avec ses collaborateurs de production.

    uvicorn serveur:app --host 0.0.0.0 --port 8000

Variables requises (fichier `.env` à la racine) :
    DATABASE_URL             Postgres (Supabase, région UE) — connexion directe
    DATABASE_URL_POOLER      repli si la directe ne répond pas (IPv6)
    RELAIS_WEBHOOK_SECRET    secret partagé avec la plateforme vocale
    RELAIS_BASE_URL          racine publique des liens de validation client (SMS)

Variable optionnelle :
    RELAIS_COOKIE_SECURE     `false` UNIQUEMENT pour tester en HTTP local depuis un
                             téléphone. Défaut `true` : la production ne doit pas pouvoir
                             régresser par oubli.

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
    return creer_app(depot, registre, make_llm, base_url=_exige("RELAIS_BASE_URL"),
                     cookie_secure=secure)


app = construire()
