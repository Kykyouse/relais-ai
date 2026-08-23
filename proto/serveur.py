#!/usr/bin/env python3
"""Point d'entrée du serveur : assemble l'API avec ses collaborateurs de production.

    uvicorn serveur:app --host 0.0.0.0 --port 8000

Variables requises (fichier `.env` à la racine) :
    DATABASE_URL             Postgres (Supabase, région UE)
    RELAIS_WEBHOOK_SECRET    secret partagé avec la plateforme vocale
    RELAIS_BASE_URL          racine publique des liens de validation client (SMS)

Rien de métier ici : uniquement du câblage. Les collaborateurs sont les mêmes objets que
ceux des tests, avec les implémentations réelles à la place des doubles — c'est tout
l'intérêt d'avoir injecté le dépôt, le LLM et l'horloge.
"""
from __future__ import annotations

import os
import pathlib

from dotenv import load_dotenv

from relais_proto.api import creer_app
from relais_proto.depot_pg import DepotPostgres
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


def construire():
    depot = DepotPostgres(_exige("DATABASE_URL"))
    registre = Registre.depuis_fichier(RACINE / "config" / "artisans.json",
                                       _exige("RELAIS_WEBHOOK_SECRET"))
    # un client LLM neuf par tour : make_llm() rend le mode réel si la clé est là,
    # le mode scripté sinon — l'appel aboutit dans les deux cas (dégradation gracieuse)
    # base_url EXIGÉE, sans valeur par défaut : elle part dans un SMS. Un lien pointant
    # sur un domaine d'exemple serait mort chez le client, sans erreur côté serveur.
    return creer_app(depot, registre, make_llm, base_url=_exige("RELAIS_BASE_URL"))


app = construire()
