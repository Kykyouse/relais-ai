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

from . import produit, temps
from .depot import normaliser_numero


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
    def __init__(self, artisans: list[Artisan], secret_webhook_sha256: str,
                 config_produit: dict | None = None):
        # La config PRODUIT, une fois pour toutes. Elle est identique pour tous les
        # artisans (c'est le sens d'un expéditeur unique), mais elle doit être joignable
        # SANS artisan : la page « lien invalide » s'affiche avant qu'on sache de qui
        # relève le jeton, et elle porte quand même le nom du produit.
        #
        # R94 (20/09) : cette règle était écrite ici et CONTREDITE par la ligne suivante,
        # qui dérivait la config de la liste d'artisans. Sur une base de production neuve
        # — table `artisan` vide, ce qui est l'état normal d'une installation — le produit
        # devenait `None` et `creer_app` refusait de construire l'application. Les deux
        # constructeurs chargeaient pourtant déjà `produit.charger(...)` sans le passer.
        #
        # La dérivation reste en REPLI, et pas par prudence : des dizaines de tests
        # construisent un `Registre` directement avec des configs qui portent déjà
        # `produit`. L'explicite gagne, l'implicite dépanne.
        self.produit: dict | None = config_produit or next(
            (a.config["produit"] for a in artisans if a.config.get("produit")), None)
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
        # index du MOBILE du patron, pour la connexion par code SMS. Normalisé des deux
        # côtés comme le numéro Relais, et pour la même raison : l'artisan tape « 06 12 34
        # 56 78 » là où le registre dit « +33612345678 ».
        self._par_telephone = {_normaliser(a.telephone): a
                               for a in artisans if a.telephone}
        self._secret_webhook_sha256 = secret_webhook_sha256

    @classmethod
    def depuis_fichier(cls, chemin: pathlib.Path, secret_webhook: str) -> Registre:
        """Registre lu dans `config/artisans.json`. **Voie de SECOURS et d'amorçage**
        depuis la migration 008 : la source normale est la base (`depuis_depot`). Reste
        utile pour démarrer sans Postgres et pour semer la table la première fois."""
        brut = json.loads(chemin.read_text(encoding="utf-8"))
        base = chemin.parent
        p = produit.charger(base)
        artisans = [
            Artisan(id=a["id"], numero_relais=a["numero_relais"],
                    token_sha256=a["token_sha256"],
                    telephone=a.get("telephone"), config_fichier=a["config"],
                    config=produit.appliquer(
                        json.loads((base / a["config"]).read_text(encoding="utf-8")), p))
            for a in brut["artisans"]]
        return cls(artisans, empreinte(secret_webhook), config_produit=p)

    @classmethod
    def depuis_depot(cls, depot, dossier_config: pathlib.Path,
                     secret_webhook: str) -> tuple[Registre, list[str]]:
        """Registre lu dans la table `artisan` (migration 008). Rend `(registre, ignorés)`.

        Les lignes **inutilisables** — sans numéro Relais ou sans fichier de config, c'est
        à dire les reprises créées par la migration à partir de données existantes — sont
        écartées et rendues à part plutôt qu'avalées : un artisan absent du registre est
        déjà géré partout (l'API rend 404, le worker le signale au lieu de deviner), mais
        il faut que quelqu'un puisse le VOIR au démarrage.

        LA CONFIG VIENT DE LA BASE quand elle y est (migration 011), du fichier sinon.

        L'ordre compte et il a changé le 21/09. Le fichier versionné répondait à
        « qu'est-ce que l'agent savait le jour de cet appel ? » par son historique git —
        mais il faisait payer cette réponse par un COMMIT ET UN REDÉPLOIEMENT à chaque
        inscription d'artisan et à chaque changement de zone ou de tarif. La garantie est
        désormais portée par `appel.config_utilisee`, figée sur la ligne d'appel : une
        lecture exacte au lieu d'un recoupement de dates de déploiement.

        Le fichier reste comme MODÈLE et comme repli — une base antérieure à la migration
        continue de fonctionner sans être convertie.
        """
        # chargée UNE fois, et avant tout le reste : une config produit invalide (nom
        # vide, expéditeur non conforme AF2M) doit empêcher le démarrage, pas produire
        # des SMS que l'opérateur refusera
        p = produit.charger(dossier_config)
        artisans, ignores = [], []
        for ligne in depot.artisans():
            if not ligne.utilisable():
                ignores.append(f"{ligne.id} ({ligne.etat_abonnement}, "
                               f"numero_relais={ligne.numero_relais!r}, "
                               f"config={ligne.config_fichier!r})")
                continue
            if ligne.config is not None:
                brute = ligne.config
            else:
                chemin = dossier_config / ligne.config_fichier
                if not chemin.exists():
                    ignores.append(f"{ligne.id} (config introuvable : {chemin.name})")
                    continue
                brute = json.loads(chemin.read_text(encoding="utf-8"))
            artisans.append(Artisan(
                id=ligne.id, numero_relais=ligne.numero_relais,
                token_sha256=ligne.token_sha256 or "",
                telephone=ligne.telephone, etat_abonnement=ligne.etat_abonnement,
                config_fichier=ligne.config_fichier,
                config=produit.appliquer(brute, p)))
        return cls(artisans, empreinte(secret_webhook), config_produit=p), ignores

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

    def par_telephone(self, numero: str) -> Artisan | None:
        """L'artisan dont c'est le mobile — la porte d'entrée de la connexion par SMS."""
        return self._par_telephone.get(_normaliser(numero)) if numero else None

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


# La normalisation a DÉMÉNAGÉ dans `depot.py` le 21/09 : la migration 011 en stocke le
# résultat en colonne pour pouvoir l'indexer, et il ne doit exister qu'une définition de
# « le même numéro » dans le système. L'alias reste — c'est le nom sous lequel ce module
# la connaît, et plusieurs appelants s'en servent.
_normaliser = normaliser_numero


class RegistreBase:
    """Le registre LU EN BASE, à chaque recherche. Même interface que `Registre`.

    Pourquoi une seconde implémentation plutôt qu'un mode de la première : `Registre` est
    un objet-valeur construit à partir d'une liste, et seize tests le construisent ainsi.
    Deux implémentations d'une même interface, éprouvées par un contrat commun, est
    exactement le motif déjà retenu pour le port `Depot` — et il vaut mieux qu'une classe
    dont le comportement dépend de son constructeur.

    CE QU'ELLE CORRIGE (21/09). `Registre.charger` lisait la table UNE FOIS au démarrage
    de `serveur.py`. Un artisan écrit en base restait donc invisible jusqu'au
    redéploiement suivant — constaté en semant l'artisan de démo, dont le jeton tout neuf
    n'était reconnu par personne. Cela condamnait la page d'admin avant même de l'écrire :
    un formulaire qui crée un artisan ne sert à rien si l'application ne le voit qu'au
    prochain déploiement. Et un cache local aurait divergé dès le second processus.

    UNE PROPRIÉTÉ EST AMÉLIORÉE AU PASSAGE, pas seulement conservée. `Registre` validait
    le fuseau de TOUS les artisans à la construction et refusait de démarrer si l'un
    d'eux était faux : une faute de frappe dans la config d'un client empêchait de servir
    tous les autres. Ici la validation est par artisan, au moment de le lire : celui dont
    la config est invalide est écarté et signalé, les autres sont servis.
    """

    def __init__(self, depot, config_produit: dict, secret_webhook_sha256: str,
                 dossier_config: pathlib.Path, journal=print):
        self.produit = config_produit
        self._depot = depot
        self._secret_webhook_sha256 = secret_webhook_sha256
        self._dossier = dossier_config
        self._journal = journal

    # ---- conversion ----
    def _artisan(self, ligne) -> Artisan | None:
        """Une ligne de base en `Artisan`, ou `None` si elle n'est pas servable.

        Rend `None` plutôt que de lever : un artisan mal configuré ne doit pas faire
        tomber la requête d'un autre. Le motif est journalisé — un artisan écarté en
        silence serait un appel qui meurt sans explication.
        """
        if ligne is None or not ligne.utilisable():
            return None
        if ligne.config is not None:
            brute = ligne.config
        else:
            chemin = self._dossier / ligne.config_fichier
            if not chemin.exists():
                self._journal(f"  ⚠️  artisan écarté : {ligne.id} "
                              f"(config introuvable : {chemin.name})")
                return None
            brute = json.loads(chemin.read_text(encoding="utf-8"))
        cfg = produit.appliquer(brute, self.produit)
        try:
            temps.fuseau(cfg)
        except Exception as exc:
            self._journal(f"  ⚠️  artisan écarté : {ligne.id} "
                          f"(fuseau invalide {cfg.get('fuseau')!r} — {exc})")
            return None
        return Artisan(id=ligne.id, numero_relais=ligne.numero_relais,
                       token_sha256=ligne.token_sha256 or "",
                       telephone=ligne.telephone,
                       etat_abonnement=ligne.etat_abonnement,
                       config_fichier=ligne.config_fichier, config=cfg)

    # ---- accès ----
    def artisan(self, artisan_id: str) -> Artisan | None:
        return self._artisan(self._depot.artisan_par_id(artisan_id))

    def par_numero_relais(self, numero: str) -> Artisan | None:
        return self._artisan(self._depot.artisan_par_numero_relais(numero))

    def par_telephone(self, numero: str) -> Artisan | None:
        return self._artisan(self._depot.artisan_par_telephone(numero)) if numero else None

    def par_token(self, token: str) -> Artisan | None:
        """Recherche indexée, PUIS comparaison à temps constant.

        `Registre` parcourait tous les artisans avec `compare_digest` pour que ni la
        validité du jeton ni la position de son porteur ne se lisent dans le temps de
        réponse. L'index remplace le parcours — il ne doit pas remplacer la comparaison.
        Elle est donc refaite ici sur la ligne rendue : ce que l'index fait gagner, il ne
        le fait pas perdre.
        """
        cible = empreinte(token or "")
        if not token:
            return None
        ligne = self._depot.artisan_par_token(cible)
        if ligne is None or not secrets.compare_digest(ligne.token_sha256 or "", cible):
            return None
        return self._artisan(ligne)

    def secret_webhook_valide(self, secret: str) -> bool:
        return secrets.compare_digest(self._secret_webhook_sha256,
                                      empreinte(secret or ""))

    # ---- diagnostic de démarrage ----
    def inventaire(self) -> tuple[int, list[str]]:
        """(servables, écartés) — pour l'annonce au démarrage. Un parcours complet, mais
        UNE fois : c'est un diagnostic, pas un chemin de requête.

        Il ne remplace pas la validation par artisan et ne bloque rien : il rend visible,
        au démarrage, ce qui serait sinon découvert au premier appel d'un client.
        """
        ecartes = []
        servables = 0
        for ligne in self._depot.artisans():
            if self._artisan(ligne) is not None:
                servables += 1
            else:
                ecartes.append(f"{ligne.id} ({ligne.etat_abonnement}, "
                               f"numero_relais={ligne.numero_relais!r})")
        return servables, ecartes
