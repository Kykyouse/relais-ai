"""Envoi des messages sortants : plage de silence, réessais, port fournisseur.

Trois responsabilités, séparées exprès :

* `heure_d_envoi_autorisee` — la **plage de silence**. Depuis que les délais de validation
  sont comptés en heures réelles (24 h / 2 h), une échéance peut tomber à 3 h du matin.
  On ne réveille pas le client d'un artisan : le SMS attend l'ouverture. Cette règle ne
  s'applique qu'aux messages **client** — la relance de l'artisan est son outil de travail,
  et c'est lui qui a choisi de prendre les urgences la nuit.
* `Envoyeur` — le port fournisseur. Aucun fournisseur n'est câblé ici : `EnvoyeurJournal`
  sert aux tests et au dév, l'adaptateur réel se greffera derrière sans toucher au reste.
* `Expediteur` — le worker. Idempotent par construction : il ne traite que les messages
  encore en `a_envoyer`, et le passage à `envoye` est écrit APRÈS l'acquittement du
  fournisseur. Un process tué juste après l'envoi rejouera donc l'envoi — d'où l'importance
  que la clé d'idempotence de la file protège déjà contre le doublon en amont.

Aucun `dt.datetime.now()` : l'horloge est un paramètre, comme partout ailleurs.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol

from .messages import Canal, Destinataire, MessageSortant, StatutMessage


class EchecEnvoi(RuntimeError):
    """Le fournisseur a refusé le message, de façon TRANSITOIRE : réseau, quota, 5xx.
    Le worker réessaie jusqu'à `sms.essais_max`, puis marque en échec."""


class EchecDefinitif(EchecEnvoi):
    """Échec qu'un réessai ne corrigera pas : numéro invalide, expéditeur refusé.
    Fait partie du contrat du port, pas d'un fournisseur : c'est l'expéditeur qui doit
    savoir ne pas s'acharner. User trois tentatives sur un numéro faux retarde les autres
    messages de la file pour rien."""


class Envoyeur(Protocol):
    """Ce qu'un fournisseur doit savoir faire. Rend une référence d'envoi ; lève
    `EchecEnvoi` sinon."""

    def envoyer(self, message: MessageSortant, cfg: dict) -> str: ...


class EnvoyeurJournal:
    """Double de test et mode dév : n'envoie rien, garde tout. Volontairement dans le code
    de production : c'est le mode par défaut tant qu'aucun fournisseur n'est choisi, et il
    vaut mieux un envoi journalisé qu'un envoi vers un fournisseur mal configuré."""

    def __init__(self) -> None:
        self.envoyes: list[MessageSortant] = []

    def envoyer(self, message: MessageSortant, cfg: dict) -> str:
        self.envoyes.append(message)
        return f"journal:{message.id}"


# ------------------------------------------------------------- plage de silence
def _minutes(hhmm: str) -> int:
    h, m = (int(x) for x in hhmm.split(":"))
    return h * 60 + m


def heure_d_envoi_autorisee(message: MessageSortant, cfg: dict,
                            maintenant: dt.datetime) -> dt.datetime:
    """Quand ce message peut partir. `maintenant` si tout de suite, sinon la fin de la
    plage de silence.

    La plage traverse minuit (21 h → 08 h) : on compare donc en minutes depuis minuit avec
    un OU, et non un ET — l'erreur classique qui rendrait la plage vide.
    """
    plage = (cfg.get("sms") or {}).get("plage_silence")
    # ne concerne que le client : l'artisan a choisi son outil et ses horaires
    if not plage or message.destinataire is not Destinataire.CLIENT:
        return maintenant

    debut, fin = _minutes(plage["de"]), _minutes(plage["a"])
    courant = maintenant.hour * 60 + maintenant.minute
    if debut < fin:                              # plage dans la même journée
        dans_la_plage = debut <= courant < fin
    else:                                        # plage à cheval sur minuit
        dans_la_plage = courant >= debut or courant < fin
    if not dans_la_plage:
        return maintenant

    heure_fin = dt.time(fin // 60, fin % 60)
    jour = maintenant.date() if courant < fin else maintenant.date() + dt.timedelta(days=1)
    return dt.datetime.combine(jour, heure_fin)


# ------------------------------------------------------------- worker d'envoi
@dataclass
class RapportEnvoi:
    examines: int = 0
    envoyes: list[str] = field(default_factory=list)
    differes: list[str] = field(default_factory=list)   # plage de silence
    reessais: list[str] = field(default_factory=list)
    echecs: list[str] = field(default_factory=list)     # essais_max atteint

    def __bool__(self) -> bool:
        return bool(self.envoyes or self.differes or self.reessais or self.echecs)


class Expediteur:
    def __init__(self, depot, envoyeur: Envoyeur, config_pour):
        """`config_pour(artisan_id)` rend la config de CET artisan, ou None s'il est
        inconnu. La plage de silence et le nombre d'essais sont des réglages par artisan :
        passer une config unique appliquerait celle du premier aux clients de tous
        (défaut corrigé par la migration 004)."""
        self.depot = depot
        self.envoyeur = envoyeur
        self.config_pour = config_pour

    def passer(self, maintenant: dt.datetime) -> RapportEnvoi:
        rapport = RapportEnvoi()
        for message in self.depot.messages(StatutMessage.A_ENVOYER):
            rapport.examines += 1
            cfg = self.config_pour(message.artisan_id) if message.artisan_id else None
            if cfg is None:
                # on REFUSE de deviner : un message sans artisan connu resterait envoyé
                # avec la plage de silence de quelqu'un d'autre. Il reste en file et
                # apparaît dans le rapport — bruyant plutôt que muet.
                rapport.echecs.append(
                    f"{message.id}: artisan « {message.artisan_id or 'absent'} » inconnu")
                continue
            essais_max = (cfg.get("sms") or {}).get("essais_max", 3)
            autorise_a = heure_d_envoi_autorisee(message, cfg, maintenant)
            if autorise_a > maintenant:
                # on inscrit l'heure autorisée en base : le passage suivant n'a plus à la
                # recalculer, et le monitoring voit pourquoi le message attend
                self.depot.differer_message(message.id, autorise_a)
                rapport.differes.append(message.id)
                continue
            if message.envoyer_apres and message.envoyer_apres > maintenant:
                rapport.differes.append(message.id)
                continue
            try:
                reference = self.envoyeur.envoyer(message, cfg)
            except Exception as exc:  # noqa: BLE001 — tout échec fournisseur est un échec
                essais = message.essais + 1
                # un échec définitif sort de la file immédiatement, sans consommer le quota
                definitif = isinstance(exc, EchecDefinitif) or essais >= essais_max
                self.depot.marquer_message_echec(
                    message.id, f"{type(exc).__name__}: {exc}", maintenant,
                    definitif=definitif)
                (rapport.echecs if definitif else rapport.reessais).append(message.id)
                continue
            self.depot.marquer_message_envoye(message.id, maintenant, reference=reference)
            rapport.envoyes.append(message.id)
        return rapport
