"""La config PRODUIT — nous — par opposition à la config ARTISAN — eux.

Deux natures de réglage qui étaient mélangées jusqu'au 25/08 :

* la **config artisan** (`config/dupont.json`) dit ce que l'agent SAIT de CET artisan :
  ses tarifs, sa zone, ses horaires, ses délais de validation. Elle lui appartient.
* la **config produit** (`config/produit.json`) dit qui NOUS sommes : le nom affiché dans
  les SMS que l'artisan reçoit, et l'expéditeur SMS déclaré chez l'opérateur. Un artisan
  ne peut rien y régler — c'est exactement le sens de la décision du 25/08, un **expéditeur
  unique déclaré sous notre société**.

Ce que ce module répare : `sms.expediteur` vivait dans la config de chaque artisan, et
« Relais : » était écrit en dur dans trois gabarits. Le premier contredisait frontalement la
décision d'expéditeur unique — en l'état, chaque artisan aurait déclaré le sien. Le second
faisait du nom du produit une chasse dans les textes le jour où il changerait.

**Et il changera** : le nom final n'est pas tranché (décision du cousin), et il ne sera pas
« Relais » — nom de code interne. Rendre ce nom paramétrable AVANT de le connaître est
précisément ce qui permet d'attendre sans être bloqué.
"""
from __future__ import annotations

import json
import pathlib
import re

FICHIER = "produit.json"

# Contraintes de la Charte AF2M en vigueur au 01/03/2026, vérifiées le 25/08 (cf. journal).
# Elles sont encodées ICI plutôt que rappelées dans un document : un nom qui ne passerait
# pas la déclaration doit être refusé au démarrage, pas découvert 72 h après le dépôt.
LONGUEUR_MAX_EXPEDITEUR = 11
_RE_EXPEDITEUR = re.compile(r"^[A-Za-z0-9]+$")
# Termes génériques interdits comme expéditeur : ils ne désignent aucune marque, et
# l'opérateur les refuse pour cette raison — ils sont le vecteur classique du hameçonnage.
GENERIQUES_INTERDITS = {
    "rdv", "alerte", "livraison", "paiement", "info", "infos", "sms", "notification",
    "message", "urgent", "banque", "colis", "compte", "securite", "service", "support",
}


class ConfigProduitInvalide(RuntimeError):
    """La config produit ne permettrait pas de fonctionner. Levée au démarrage."""


def valider_expediteur(nom: str) -> str:
    """Rend `nom` s'il peut être déclaré, lève sinon. Le message dit QUOI corriger.

    Volontairement strict et bruyant : c'est le genre de règle qu'on découvre autrement en
    recevant un refus après trois jours d'attente.
    """
    if not nom:
        raise ConfigProduitInvalide("expediteur_sms vide")
    if len(nom) > LONGUEUR_MAX_EXPEDITEUR:
        raise ConfigProduitInvalide(
            f"expediteur_sms « {nom} » fait {len(nom)} caractères : la Charte AF2M en "
            f"autorise {LONGUEUR_MAX_EXPEDITEUR} au maximum.")
    if not _RE_EXPEDITEUR.match(nom):
        raise ConfigProduitInvalide(
            f"expediteur_sms « {nom} » : alphanumériques latins uniquement, ni espace ni "
            f"caractère spécial ni accent (Charte AF2M).")
    if nom.lower() in GENERIQUES_INTERDITS:
        raise ConfigProduitInvalide(
            f"expediteur_sms « {nom} » est un terme générique, interdit comme expéditeur "
            f"(Charte AF2M) : il doit désigner notre marque.")
    return nom


def charger(dossier_config: pathlib.Path) -> dict:
    """Lit et VALIDE `config/produit.json`. Lève si le fichier manque ou ne convient pas.

    Pas de valeur par défaut : un produit sans nom enverrait des SMS anonymes et un
    expéditeur non conforme se ferait refuser à la déclaration. Mieux vaut ne pas démarrer
    — même raisonnement que `_exige` dans `serveur.py`.
    """
    chemin = pathlib.Path(dossier_config) / FICHIER
    if not chemin.exists():
        raise ConfigProduitInvalide(
            f"{chemin} introuvable : la config produit (nom affiché, expéditeur SMS) "
            f"n'est pas optionnelle.")
    brut = json.loads(chemin.read_text(encoding="utf-8"))
    nom = (brut.get("nom") or "").strip()
    if not nom:
        raise ConfigProduitInvalide(f"{chemin} : « nom » est vide.")
    expediteur = valider_expediteur((brut.get("expediteur_sms") or "").strip())
    return {"nom": nom, "expediteur_sms": expediteur}


def appliquer(cfg_artisan: dict, produit: dict) -> dict:
    """La config d'un artisan, augmentée de la config produit sous la clé `produit`.

    Fusionner ici plutôt que passer un second argument à chaque constructeur de message :
    `cfg` devient « tout ce que le système sait pour cet artisan », ce qui est déjà son
    rôle. Aucune signature existante ne change.
    """
    return {**cfg_artisan, "produit": dict(produit)}


def de_config(cfg: dict) -> dict:
    """La config produit contenue dans une config artisan résolue.

    Lève si elle manque — c'est un défaut de câblage, pas une donnée d'exécution : un
    gabarit rendu sans nom de produit partirait chez un artisan signé de rien.
    """
    p = cfg.get("produit")
    if not p or not p.get("nom"):
        raise ConfigProduitInvalide(
            "config produit absente : la config artisan doit passer par "
            "produit.appliquer() avant d'être utilisée.")
    return p
