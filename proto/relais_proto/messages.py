"""Messages sortants (SMS client, relance artisan) : catalogue fermé + file d'attente.

Comme les consignes sécurité, **les textes sont écrits par nous**, pas par le LLM et pas
par l'artisan (cf. docs/config-artisan-v1.md : `sms.templates_personnalises = null` en V1,
l'artisan ne règle que son sender ID). Un SMS est une sortie de l'agent au même titre
qu'une réplique au téléphone : il passe donc par `guards.check_output` avant d'entrer dans
la file — règle n°2 du projet, étendue au canal écrit.

Ce module NE parle à aucun fournisseur. Il produit des brouillons ; l'envoi réel (et la
plage de non-envoi 21 h–08 h, décidée pour plus tard) viendront avec l'adaptateur SMS.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

from .guards import check_output


class Destinataire(str, Enum):
    CLIENT = "client"
    ARTISAN = "artisan"


class Canal(str, Enum):
    SMS = "sms"
    PUSH = "push"


class StatutMessage(str, Enum):
    A_ENVOYER = "a_envoyer"
    ENVOYE = "envoye"
    ECHEC = "echec"


class MessageInterdit(RuntimeError):
    """Un texte de la file a violé un garde-fou : c'est un bug de template, pas une
    donnée d'exécution. On refuse de le mettre en file plutôt que de l'envoyer."""


@dataclass(frozen=True)
class Brouillon:
    """Message prêt à entrer en file. Pas d'`id` : c'est le dépôt qui l'attribue,
    comme le fera l'INSERT Postgres."""
    cle_idempotence: str
    destinataire: Destinataire
    canal: Canal
    cible: str
    texte: str


@dataclass
class MessageSortant:
    id: str
    cle_idempotence: str
    destinataire: Destinataire
    canal: Canal
    cible: str
    texte: str
    cree_a: dt.datetime
    statut: StatutMessage = StatutMessage.A_ENVOYER
    envoye_a: dt.datetime | None = None

    def to_dict(self) -> dict:
        return {"id": self.id, "cle_idempotence": self.cle_idempotence,
                "destinataire": self.destinataire.value, "canal": self.canal.value,
                "cible": self.cible, "texte": self.texte, "statut": self.statut.value,
                "cree_a": self.cree_a.isoformat(),
                "envoye_a": self.envoye_a.isoformat() if self.envoye_a else None}

    @classmethod
    def from_dict(cls, d: dict) -> MessageSortant:
        return cls(id=d["id"], cle_idempotence=d["cle_idempotence"],
                   destinataire=Destinataire(d["destinataire"]), canal=Canal(d["canal"]),
                   cible=d["cible"], texte=d["texte"], statut=StatutMessage(d["statut"]),
                   cree_a=dt.datetime.fromisoformat(d["cree_a"]),
                   envoye_a=dt.datetime.fromisoformat(d["envoye_a"]) if d["envoye_a"]
                   else None)


# --------------------------------------------------------------- catalogue fermé
# Aucun délai chiffré ici : l'artisan vient précisément de laisser expirer le sien,
# lui en promettre un second ne serait pas crédible. Le SMS dit ce qui s'est passé
# et que l'artisan reprend contact, sans inventer d'échéance.
TEMPLATES = {
    # {creneau} est le libellé produit par le calendrier ("demain entre 08h et 10h",
    # "aujourd'hui entre 17h et 19h") : il se lit en apposition, jamais après un article,
    # sinon on écrit « le créneau du aujourd'hui entre 17h et 19h ».
    "expiration_client": (
        "Bonjour, c'est {nom_entreprise}. Nous n'avons pas pu valider votre créneau : "
        "{creneau}. {prenom} vous recontacte pour convenir d'un autre horaire. "
        "Désolés pour ce contretemps."),
    "expiration_artisan": (
        "Relais : RDV expiré sans validation — {creneau}, {client} ({commune}). "
        "Le créneau est libéré et le client a été prévenu. À rappeler : {telephone}."),
}


def _texte(cle: str, cfg: dict, **variables: str) -> str:
    texte = TEMPLATES[cle].format(**variables)
    # un SMS est une sortie de l'agent : même contrôle qu'une réplique au téléphone
    violations = check_output(texte, cfg, rdv_valide=False)
    if violations:
        raise MessageInterdit(f"template {cle} : {violations}")
    return texte


def repli_client(rdv, lead_donnees: dict, cfg: dict) -> Brouillon:
    """SMS de repli au client dont le créneau a expiré sans réponse de l'artisan."""
    telephone = lead_donnees["slots"].get("telephone_rappel")
    if not telephone:
        raise MessageInterdit(f"RDV {rdv.id} : pas de téléphone pour joindre le client")
    return Brouillon(
        cle_idempotence=f"expiration_client:{rdv.id}",
        destinataire=Destinataire.CLIENT, canal=Canal.SMS, cible=telephone,
        texte=_texte("expiration_client", cfg,
                     nom_entreprise=cfg["entreprise"]["nom"],
                     prenom=cfg["entreprise"]["prenom_patron"],
                     creneau=rdv.creneau["label"]))


def relance_artisan(rdv, lead_donnees: dict, cfg: dict) -> Brouillon:
    """Relance de l'artisan : il a laissé filer un lead qualifié, il doit le savoir.

    La cible est son **identifiant de compte**, pas un numéro : c'est un push vers son
    app (spec §6, `validation.canal_notification`). Le repli SMS vers `transfert.cible`
    viendra avec l'adaptateur d'envoi, quand il faudra gérer un artisan sans app.
    """
    slots = lead_donnees["slots"]
    return Brouillon(
        cle_idempotence=f"expiration_artisan:{rdv.id}",
        destinataire=Destinataire.ARTISAN, canal=Canal.PUSH,
        cible=rdv.artisan_id,
        texte=_texte("expiration_artisan", cfg, creneau=rdv.creneau["label"],
                     client=slots.get("nom") or "un client",
                     commune=slots.get("commune") or slots.get("code_postal") or "?",
                     telephone=slots.get("telephone_rappel") or "?"))
