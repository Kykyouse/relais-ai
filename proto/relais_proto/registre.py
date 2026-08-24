"""Registre des artisans : qui est qui, et par quelle porte il entre.

**Deux chemins d'authentification distincts**, décidés en cadrage de la phase backend :

* le **webhook téléphonie** présente un secret partagé. L'appelant y est la plateforme
  vocale, PAS l'artisan : l'artisan est identifié par le **numéro Relais appelé**. Mettre
  un token d'artisan dans la configuration d'un fournisseur de voix serait le mauvais
  périmètre (un secret par artisan chez un tiers) et impossible à faire tourner.
* l'**app artisan** présente un token porteur qui lui est propre.

En V1 le registre est un fichier JSON ; il deviendra la table `artisan` (avec la clé
étrangère que `rdv.artisan_id` attend déjà). Les tokens n'y sont stockés qu'en **SHA-256** :
ce fichier finira en base, autant prendre l'habitude tout de suite.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import secrets
from dataclasses import dataclass

from . import temps


def empreinte(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Artisan:
    id: str
    numero_relais: str
    token_sha256: str
    config: dict
    telephone: str | None = None      # mobile du patron : identité pro + canal du code SMS
    etat_abonnement: str = "actif"
    # le NOM du fichier de config, gardé à côté de son contenu : c'est lui qui est stocké
    # en base (la config reste un fichier versionné), et sans lui `semer()` écrirait une
    # ligne que `depuis_depot()` jugerait ensuite inutilisable
    config_fichier: str | None = None


class Registre:
    def __init__(self, artisans: list[Artisan], secret_webhook_sha256: str):
        for a in artisans:
            # Le fuseau est vérifié À LA CONSTRUCTION, pas à l'usage : `ZoneInfo` lève sur
            # un identifiant inconnu, et sans ce contrôle une faute de frappe dans une
            # config (« Europe/Pari ») ne se manifesterait qu'au premier calcul d'heure —
            # donc en plein appel, chez un artisan, un jour donné. Même esprit que
            # `_exige` dans serveur.py : refuser de démarrer plutôt que tourner à moitié
            # configuré. Ici et pas dans `depuis_fichier` : l'invariant est celui du
            # registre, quelle que soit la source (fichier aujourd'hui, table demain).
            try:
                temps.fuseau(a.config)
            except Exception as exc:
                raise RuntimeError(
                    f"artisan « {a.id} » : fuseau invalide "
                    f"({a.config.get('fuseau')!r}) — {exc}") from None
        self._artisans = {a.id: a for a in artisans}
        # normalisé DES DEUX CÔTÉS : le registre peut être écrit en +33..., la plateforme
        # vocale annoncer 01... — sans ça la recherche échoue silencieusement
        self._par_numero = {_normaliser(a.numero_relais): a for a in artisans}
        self._secret_webhook_sha256 = secret_webhook_sha256

    @classmethod
    def depuis_fichier(cls, chemin: pathlib.Path, secret_webhook: str) -> Registre:
        """Registre lu dans `config/artisans.json`. **Voie de SECOURS et d'amorçage**
        depuis la migration 008 : la source normale est la base (`depuis_depot`). Reste
        utile pour démarrer sans Postgres et pour semer la table la première fois."""
        brut = json.loads(chemin.read_text(encoding="utf-8"))
        base = chemin.parent
        artisans = [
            Artisan(id=a["id"], numero_relais=a["numero_relais"],
                    token_sha256=a["token_sha256"],
                    telephone=a.get("telephone"), config_fichier=a["config"],
                    config=json.loads((base / a["config"]).read_text(encoding="utf-8")))
            for a in brut["artisans"]]
        return cls(artisans, empreinte(secret_webhook))

    @classmethod
    def depuis_depot(cls, depot, dossier_config: pathlib.Path,
                     secret_webhook: str) -> tuple[Registre, list[str]]:
        """Registre lu dans la table `artisan` (migration 008). Rend `(registre, ignorés)`.

        Les lignes **inutilisables** — sans numéro Relais ou sans fichier de config, c'est
        à dire les reprises créées par la migration à partir de données existantes — sont
        écartées et rendues à part plutôt qu'avalées : un artisan absent du registre est
        déjà géré partout (l'API rend 404, le worker le signale au lieu de deviner), mais
        il faut que quelqu'un puisse le VOIR au démarrage.

        La config reste un fichier : c'est son historique git qui répond à « qu'est-ce que
        l'agent savait le jour de cet appel ? ».
        """
        artisans, ignores = [], []
        for ligne in depot.artisans():
            if not ligne.utilisable():
                ignores.append(f"{ligne.id} ({ligne.etat_abonnement}, "
                               f"numero_relais={ligne.numero_relais!r}, "
                               f"config={ligne.config_fichier!r})")
                continue
            chemin = dossier_config / ligne.config_fichier
            if not chemin.exists():
                ignores.append(f"{ligne.id} (config introuvable : {chemin.name})")
                continue
            artisans.append(Artisan(
                id=ligne.id, numero_relais=ligne.numero_relais,
                token_sha256=ligne.token_sha256 or "",
                telephone=ligne.telephone, etat_abonnement=ligne.etat_abonnement,
                config_fichier=ligne.config_fichier,
                config=json.loads(chemin.read_text(encoding="utf-8"))))
        return cls(artisans, empreinte(secret_webhook)), ignores

    @classmethod
    def charger(cls, depot, dossier_config: pathlib.Path, secret_webhook: str,
                journal=print) -> Registre:
        """La façon NORMALE d'obtenir un registre en production : la table `artisan`.

        Les artisans écartés sont annoncés à chaque démarrage, pas seulement quand il y en
        a — même raisonnement que pour `cookie_secure` le 24/08 : un état qu'on ne voit
        que lorsqu'il est anormal ne se distingue pas d'un réglage non pris en compte.
        """
        registre, ignores = cls.depuis_depot(depot, dossier_config, secret_webhook)
        journal(f"registre : {len(registre._artisans)} artisan(s) servable(s), "
                f"{len(ignores)} écarté(s)")
        for quoi in ignores:
            journal(f"  ⚠️  artisan écarté : {quoi}")
        if not registre._artisans:
            journal("  ⚠️  AUCUN artisan servable : amorce la table avec "
                    "« python semer_artisans.py --ecrire ».")
        return registre

    def semer(self, depot) -> int:
        """Écrit ce registre dans la table `artisan`. Idempotent (UPSERT).

        Sert à amorcer la base depuis `config/artisans.json`, une fois. Rendu comme une
        méthode du registre et non comme un script à part pour qu'il n'y ait qu'UNE
        définition de ce qu'est un artisan à enregistrer.
        """
        from .depot import LigneArtisan
        for a in self._artisans.values():
            depot.enregistrer_artisan(LigneArtisan(
                id=a.id, nom_affiche=a.config.get("entreprise", {}).get("nom"),
                numero_relais=a.numero_relais, telephone=a.telephone,
                config_fichier=a.config_fichier, token_sha256=a.token_sha256 or None,
                etat_abonnement=a.etat_abonnement))
        return len(self._artisans)

    # ---- accès ----
    def artisan(self, artisan_id: str) -> Artisan | None:
        return self._artisans.get(artisan_id)

    def par_numero_relais(self, numero: str) -> Artisan | None:
        return self._par_numero.get(_normaliser(numero))

    def par_token(self, token: str) -> Artisan | None:
        """Comparaison à temps constant, et sur TOUS les artisans : ni la validité du
        token ni la position de l'artisan dans le registre ne doivent se lire dans le
        temps de réponse."""
        cible = empreinte(token or "")
        trouve = None
        for a in self._artisans.values():
            if secrets.compare_digest(a.token_sha256, cible):
                trouve = a
        return trouve

    def secret_webhook_valide(self, secret: str) -> bool:
        return secrets.compare_digest(self._secret_webhook_sha256,
                                      empreinte(secret or ""))


def _normaliser(numero: str) -> str:
    """« 01 89 70 12 34 », « +33189701234 » : la plateforme vocale ne garantit pas le
    format. On ne garde que les chiffres et un éventuel indicatif."""
    chiffres = "".join(c for c in (numero or "") if c.isdigit())
    if chiffres.startswith("33") and len(chiffres) == 11:
        return "0" + chiffres[2:]
    return chiffres
