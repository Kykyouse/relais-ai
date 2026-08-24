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
        brut = json.loads(chemin.read_text(encoding="utf-8"))
        base = chemin.parent
        artisans = [
            Artisan(id=a["id"], numero_relais=a["numero_relais"],
                    token_sha256=a["token_sha256"],
                    config=json.loads((base / a["config"]).read_text(encoding="utf-8")))
            for a in brut["artisans"]]
        return cls(artisans, empreinte(secret_webhook))

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
