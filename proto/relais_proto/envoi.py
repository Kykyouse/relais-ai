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

from . import temps
from .messages import Canal, Destinataire, MessageSortant, StatutMessage


class EchecEnvoi(RuntimeError):
    """Le fournisseur a refusé le message, de façon TRANSITOIRE : réseau, quota, 5xx.
    Le worker réessaie jusqu'à `sms.essais_max`, puis marque en échec."""


class EchecDefinitif(EchecEnvoi):
    """Échec qu'un réessai ne corrigera pas : numéro invalide, expéditeur refusé.
    Fait partie du contrat du port, pas d'un fournisseur : c'est l'expéditeur qui doit
    savoir ne pas s'acharner. User trois tentatives sur un numéro faux retarde les autres
    messages de la file pour rien."""


@dataclass(frozen=True)
class Envoi:
    """Ce qu'un fournisseur rend quand l'envoi a réussi.

    Le **coût** fait partie de l'envoi, pas de l'état du fournisseur : c'est pourquoi il
    remonte par la valeur de retour et non par un attribut lu après coup. Il est persisté
    par message, ce qui permet de calculer le coût SMS réel par artisan et par mois — la
    donnée qui dira un jour si changer de fournisseur se rentabilise. Elle ne repasse
    jamais : ne pas la stocker maintenant, c'est ne jamais pouvoir la reconstituer.
    """
    reference: str
    cout: int | None = None     # crédits consommés, si le fournisseur les indique


class Envoyeur(Protocol):
    """Ce qu'un fournisseur doit savoir faire. Rend un `Envoi` ; lève `EchecEnvoi` sinon."""

    def envoyer(self, message: MessageSortant, cfg: dict) -> Envoi: ...


def choisir_envoyeur() -> tuple[Envoyeur, str]:
    """Le fournisseur d'envoi d'après l'environnement. Rend `(envoyeur, libellé)`.

    **Partagé par le worker ET le serveur**, comme `resoudre_connexion` l'est pour la base,
    et pour la même raison apprise le 24/08 : une logique de composition qui ne vit que
    dans un point d'entrée laisse l'autre diverger en silence. Depuis que l'API envoie
    elle-même les codes de connexion, les deux ont besoin d'un envoyeur — il ne doit pas y
    avoir deux façons de le choisir.

    Défaut volontairement inoffensif : sans `RELAIS_SMS=ovh`, rien ne part. Un cron ou un
    serveur mal configuré ne doit pas se mettre à écrire à de vrais clients.
    """
    import os
    mode = (os.environ.get("RELAIS_SMS") or "journal").strip().lower()
    if mode != "ovh":
        return EnvoyeurJournal(), "journal (rien ne part)"
    compte = os.environ.get("OVH_SMS_COMPTE")
    if not compte:
        raise RuntimeError("RELAIS_SMS=ovh exige OVH_SMS_COMPTE (voir .env.example)")
    from .envoi_ovh import EnvoyeurOVH, transport_sdk
    numero_court = os.environ.get("RELAIS_SMS_NUMERO_COURT") == "1"
    libelle = "OVH — ENVOI RÉEL" + (" par NUMÉRO COURT (URL bloquées : les SMS de "
                                    "reproposition échoueront)" if numero_court else "")
    return EnvoyeurOVH(transport_sdk(), compte, numero_court=numero_court), libelle


class EnvoyeurJournal:
    """Double de test et mode dév : n'envoie rien, garde tout, ET L'ÉCRIT.

    Volontairement dans le code de production : c'est le mode par défaut tant qu'aucun
    fournisseur n'est choisi, et il vaut mieux un envoi journalisé qu'un envoi vers un
    fournisseur mal configuré.

    ⚠️ IL N'ÉCRIVAIT RIEN JUSQU'AU 02/09, et ça rendait la moitié du produit
    inatteignable en développement. Geoffrey ouvre `/connexion`, entre son numéro, et
    reçoit « code incorrect » : le code à six chiffres partait en file, la file était
    vidée par le worker, et le worker ne montrait rien. Le code existait, dans une table,
    et aucun humain ne pouvait le lire — donc **personne ne pouvait se connecter à la
    boîte de validation en local**. Ni erreur, ni trace, juste « code incorrect ».

    Le nom disait pourtant quoi faire. « Journaliser » veut dire écrire quelque part
    qu'on peut lire, pas garder en mémoire pour soi.

    La mémoire (`envoyes`) reste : toute la suite de tests s'appuie dessus, et la
    remplacer par une lecture de sortie standard serait un recul.
    """

    def __init__(self) -> None:
        self.envoyes: list[MessageSortant] = []

    def envoyer(self, message: MessageSortant, cfg: dict) -> Envoi:
        self.envoyes.append(message)
        # Le TEXTE EN ENTIER : un code de connexion tronqué ne sert à rien, et c'est le
        # cas d'usage qui a motivé cette ligne. La mention « rien n'est parti » est sur la
        # même ligne, pour qu'on ne puisse pas lire ce journal comme une confirmation
        # d'envoi en relisant une capture d'écran trois jours plus tard.
        # `.value` et non l'énumération : `Canal.SMS` est un `str, Enum`, et son f-string
        # rend « Canal.SMS » depuis Python 3.11 — illisible dans un journal qu'on relit
        # à la va-vite.
        print(f"[journal · rien n'est parti] {message.canal.value} → {message.cible} : "
              f"{message.texte}", flush=True)
        # coût simulé d'après la vraie règle de facturation : le mode dév doit donner un
        # ordre de grandeur juste, sinon les chiffres de coût seraient faux en test
        return Envoi(reference=f"journal:{message.id}",
                     cout=segments_sms(message.texte)[0])


# ------------------------------------------------------------- coût d'un SMS
# Alphabet GSM-7 (norme GSM 03.38). **Un seul caractère hors de cet ensemble fait basculer
# tout le message en UCS-2, et la limite tombe de 160 à 70 caractères.** Découvert le 24/08 :
# le « ô » de « plutôt » faisait coûter 3 segments au SMS de reproposition au lieu d'un.
# Attention aux faux amis : é è ù ì ò à sont dans GSM-7, mais PAS ê ô î û ni À — ni les
# guillemets « », le tiret cadratin — ou les points de suspension …
_GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ ÆæßÉ"
            "!\"#¤%&'()*+,-./0123456789:;<=>?¡"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿"
            "abcdefghijklmnopqrstuvwxyzäöñüà") | set("^{}[~]|€\\")


def segments_sms(texte: str) -> tuple[int, str]:
    """(nombre de segments facturés, encodage). Un segment = un crédit chez l'opérateur.

    Les seuils diffèrent selon qu'un message tient en un seul morceau ou doit être
    concaténé : la concaténation consomme 7 octets d'en-tête, d'où 153 et 67 au lieu de
    160 et 70.
    """
    ucs2 = any(c not in _GSM7 for c in texte or "")
    seul, concat = (70, 67) if ucs2 else (160, 153)
    n = len(texte or "")
    segments = 1 if n <= seul else -(-n // concat)
    return segments, ("UCS-2" if ucs2 else "GSM-7")


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

    « 21 h » et « 08 h » sont des heures de PENDULE : c'est le réveil du client qu'on
    protège, pas un offset. Tout le calcul se fait donc sur `local`, et le résultat
    redevient un instant (`temps.instant_de`). Calculée en UTC, la fin de plage tomberait
    à 9 h locale l'été et à 7 h l'hiver — soit exactement ce qu'on cherche à éviter.
    """
    plage = (cfg.get("sms") or {}).get("plage_silence")
    # ne concerne que le client : l'artisan a choisi son outil et ses horaires
    if not plage or message.destinataire is not Destinataire.CLIENT:
        return maintenant

    local = temps.en_local(maintenant, cfg)
    debut, fin = _minutes(plage["de"]), _minutes(plage["a"])
    courant = local.hour * 60 + local.minute
    if debut < fin:                              # plage dans la même journée
        dans_la_plage = debut <= courant < fin
    else:                                        # plage à cheval sur minuit
        dans_la_plage = courant >= debut or courant < fin
    if not dans_la_plage:
        return maintenant

    jour = local.date() if courant < fin else local.date() + dt.timedelta(days=1)
    return temps.instant_de(jour, dt.time(fin // 60, fin % 60), cfg)


# ------------------------------------------------------------- worker d'envoi
@dataclass
class RapportEnvoi:
    examines: int = 0
    envoyes: list[str] = field(default_factory=list)
    differes: list[str] = field(default_factory=list)   # plage de silence
    reessais: list[str] = field(default_factory=list)
    echecs: list[str] = field(default_factory=list)     # essais_max atteint
    cout_total: int = 0                                 # crédits consommés sur ce passage

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

    def passer(self, maintenant: dt.datetime,
               seulement: set[str] | None = None) -> RapportEnvoi:
        """Un passage de la file. `seulement` restreint aux identifiants donnés.

        Ce filtre existe pour le code de connexion : l'API doit pouvoir expédier CE
        message tout de suite, sans vider la file entière depuis une requête web — un
        artisan qui se connecte déclencherait sinon l'envoi de tous les SMS clients en
        attente, hors du cron et hors de tout contrôle de débit.
        """
        rapport = RapportEnvoi()
        for message in self.depot.messages(StatutMessage.A_ENVOYER):
            if seulement is not None and message.id not in seulement:
                continue
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
                envoi = self.envoyeur.envoyer(message, cfg)
            except Exception as exc:  # noqa: BLE001 — tout échec fournisseur est un échec
                essais = message.essais + 1
                # un échec définitif sort de la file immédiatement, sans consommer le quota
                definitif = isinstance(exc, EchecDefinitif) or essais >= essais_max
                self.depot.marquer_message_echec(
                    message.id, f"{type(exc).__name__}: {exc}", maintenant,
                    definitif=definitif)
                (rapport.echecs if definitif else rapport.reessais).append(message.id)
                continue
            self.depot.marquer_message_envoye(message.id, maintenant,
                                              reference=envoi.reference, cout=envoi.cout)
            rapport.envoyes.append(message.id)
            if envoi.cout:
                rapport.cout_total += envoi.cout
        return rapport
