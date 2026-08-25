"""Messages sortants (SMS client, relance artisan) : catalogue fermé + file d'attente.

Comme les consignes sécurité, **les textes sont écrits par nous**, pas par le LLM et pas
par l'artisan (cf. docs/config-artisan-v1.md : `sms.templates_personnalises = null` en V1).
Il ne règle pas non plus l'expéditeur : depuis le 25/08 c'est un expéditeur UNIQUE, déclaré
sous notre société, qui vit dans la config produit (`produit.py`). Un SMS est une sortie de
l'agent au même titre qu'une réplique au téléphone : il passe donc par `guards.check_output`
avant d'entrer dans la file — règle n°2 du projet, étendue au canal écrit.

Ce module NE parle à aucun fournisseur. Il produit des brouillons ; l'envoi réel (et la
plage de non-envoi 21 h–08 h, décidée pour plus tard) viendront avec l'adaptateur SMS.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

from . import produit, temps
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
    # de quel artisan relève ce message. Indispensable à l'expéditeur : la plage de
    # silence est un réglage PAR artisan, et sans ça il appliquerait celle du premier
    # à tous les clients (défaut corrigé par la migration 004).
    artisan_id: str = ""


@dataclass
class MessageSortant:
    id: str
    cle_idempotence: str
    destinataire: Destinataire
    canal: Canal
    cible: str
    texte: str
    cree_a: dt.datetime
    artisan_id: str = ""
    statut: StatutMessage = StatutMessage.A_ENVOYER
    envoye_a: dt.datetime | None = None
    essais: int = 0                        # tentatives d'envoi déjà consommées
    derniere_erreur: str | None = None
    envoyer_apres: dt.datetime | None = None   # différé par la plage de silence
    reference: str | None = None           # accusé du fournisseur
    cout: int | None = None                # crédits consommés (1 par segment SMS)

    HORODATAGES = ("cree_a", "envoye_a", "envoyer_apres")

    def to_dict(self) -> dict:
        d = {"id": self.id, "cle_idempotence": self.cle_idempotence,
             "destinataire": self.destinataire.value, "canal": self.canal.value,
             "cible": self.cible, "texte": self.texte, "statut": self.statut.value,
             "essais": self.essais, "derniere_erreur": self.derniere_erreur,
             "reference": self.reference, "artisan_id": self.artisan_id,
             "cout": self.cout}
        for c in self.HORODATAGES:
            h = getattr(self, c)
            d[c] = h.isoformat() if h else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> MessageSortant:
        horodatages = {c: temps.depuis_iso(d[c]) if d.get(c) else None
                       for c in cls.HORODATAGES}
        return cls(id=d["id"], cle_idempotence=d["cle_idempotence"],
                   destinataire=Destinataire(d["destinataire"]), canal=Canal(d["canal"]),
                   cible=d["cible"], texte=d["texte"], statut=StatutMessage(d["statut"]),
                   essais=d.get("essais", 0), derniere_erreur=d.get("derniere_erreur"),
                   reference=d.get("reference"), artisan_id=d.get("artisan_id") or "",
                   cout=d.get("cout"), **horodatages)


# --------------------------------------------------------------- catalogue fermé
# Aucun délai chiffré ici : l'artisan vient précisément de laisser expirer le sien,
# lui en promettre un second ne serait pas crédible. Le SMS dit ce qui s'est passé
# et que l'artisan reprend contact, sans inventer d'échéance.
TEMPLATES = {
    # {creneau} est le libellé produit par le calendrier ("demain entre 08h et 10h",
    # "aujourd'hui entre 17h et 19h") : il se lit en apposition, jamais après un article,
    # sinon on écrit « le créneau du aujourd'hui entre 17h et 19h ».
    # LONGUEUR ET ALPHABET SONT DU COÛT, pas du style : un segment = un crédit, et un seul
    # caractère hors GSM-7 fait tomber la limite de 160 à 70 (cf. envoi.segments_sms).
    # Faux amis à éviter absolument : ê ô î û À « » — …  (é è ù ì ò à sont légaux).
    # R23 verrouille : GSM-7 partout, et un seul segment avec une marge de sécurité.
    "expiration_client": (
        "Bonjour, c'est {nom_entreprise}. Créneau {creneau} non validé. {prenom} vous "
        "recontacte pour en fixer un autre."),
    # Le lien remplace le « Répondez OUI » de la spec §3.5bis : un sender alphanumérique
    # ne reçoit rien, et les numéros mobiles FR sont interdits à l'A2P. Un tap vaut mieux
    # qu'un mot à taper, et le SMS reste strictement sortant.
    # « à la place » serait plus juste que « propose » seul, mais coûtait 11 caractères
    # sur une marge déjà mince : le lien pèse ~43 caractères à lui seul.
    "reproposition_client": (
        "Bonjour, c'est {nom_entreprise}. {prenom} propose {creneau}. Validez : {lien}"),
    # LA promesse du script tenue par écrit. C'est le SEUL texte du produit où « confirmé »
    # est permis — et il ne l'est que parce que l'artisan vient de valider (garde-fou
    # `rdv_valide`). Il nomme l'entreprise ET le patron : depuis la décision d'expéditeur
    # unique (25/08), l'expéditeur du SMS ne dit plus au client de qui vient le message.
    # Aucune URL : ce SMS part donc en numéro court, sans attendre le Sender ID.
    "confirmation_client": (
        "Bonjour, c'est {nom_entreprise}. C'est confirmé : {prenom} passe {creneau}."),
    # Le code de connexion. Volontairement bref et sans lien : c'est ce qui lui permet de
    # partir par numéro court dès aujourd'hui. La mention « ne le communiquez à personne »
    # tient en quelques caractères et vaut mieux qu'un rappel de sécurité par ailleurs :
    # c'est au moment où il lit le code que l'artisan peut se faire manipuler.
    "code_connexion_artisan": (
        "{produit} : votre code de connexion est {code}. Valable {minutes} minutes. "
        "Ne le communiquez à personne."),
    "confirmation_artisan": (
        "{produit} : {client} a validé le créneau {creneau}. C'est dans votre agenda."),
    "expiration_artisan": (
        "{produit} : RDV expiré sans validation - {creneau}, {client} ({commune}). "
        "Créneau libéré, client prévenu. Rappeler le {telephone}."),
}


def _texte(cle: str, cfg: dict, *, rdv_valide: bool = False, **variables: str) -> str:
    """Rend un gabarit et le soumet aux garde-fous.

    `rdv_valide` par défaut à False : le mot « confirmé » est interdit tant que l'artisan
    n'a pas tranché. Un seul appelant le passe à True — `confirmation_client`, envoyé
    APRÈS la validation. Le paramètre existait dans `guards.check_output` depuis le
    début et n'avait jamais servi : il était prévu exactement pour ce message, qui
    n'existait pas encore.
    """
    # `{produit}` est fourni ici et jamais par l'appelant : le nom du produit vient de la
    # config produit (`config/produit.json`), pas d'un argument que chaque constructeur
    # pourrait oublier ou contredire. Il était écrit en dur dans trois gabarits jusqu'au
    # 25/08, alors que le nom final n'est pas tranché et ne sera pas « Relais ».
    if "{produit}" in TEMPLATES[cle]:
        variables = {**variables, "produit": produit.de_config(cfg)["nom"]}
    texte = TEMPLATES[cle].format(**variables)
    # un SMS est une sortie de l'agent : même contrôle qu'une réplique au téléphone
    violations = check_output(texte, cfg, rdv_valide=rdv_valide)
    if violations:
        raise MessageInterdit(f"template {cle} : {violations}")
    return texte


def code_connexion_artisan(artisan_id: str, telephone: str, code: str, cfg: dict,
                           minutes: int, empreinte_code: str) -> Brouillon:
    """Le code SMS qui ouvre une session artisan.

    **La clé d'idempotence dérive de l'EMPREINTE DU CODE**, et c'est le seul choix juste :

      * dériver du seul `artisan_id` refuserait tout second code — un artisan qui n'a pas
        reçu son SMS ne pourrait plus jamais se connecter ;
      * dériver de l'horodatage à la seconde paraît marcher et ne marche pas : deux
        demandes dans la même seconde rendent le PREMIER message, donc l'ANCIEN code,
        alors que la base porte déjà l'empreinte du nouveau. L'artisan reçoit un code
        que le système refusera. Trouvé par R24 le 25/08, en rejouant deux connexions
        rapprochées.

    Avec l'empreinte : un code donné a un message et un seul (donc un réessai d'envoi ne
    double pas le SMS), et un code neuf a toujours le sien.

    Destinataire ARTISAN : la plage de silence ne s'applique donc pas. C'est voulu — il
    vient de demander à se connecter, à 3 h du matin comme à midi.
    """
    return Brouillon(
        cle_idempotence=f"code_connexion:{artisan_id}:{empreinte_code[:16]}",
        artisan_id=artisan_id,
        destinataire=Destinataire.ARTISAN, canal=Canal.SMS, cible=telephone,
        texte=_texte("code_connexion_artisan", cfg, code=code, minutes=str(minutes)))


def confirmation_client(rdv, lead_donnees: dict, cfg: dict) -> Brouillon:
    """L'artisan a validé : le client reçoit le SMS qu'on lui a promis AU TÉLÉPHONE.

    C'est le chemin nominal — celui qui justifie le produit — et il était muet jusqu'au
    25/08 : seuls les chemins d'ÉCHEC (expiration, reproposition) écrivaient au client.
    L'agent promettait pourtant, verbatim et sans échappatoire, « vous recevrez un SMS de
    confirmation d'ici X heures ». Verrouillé par R27, qui confronte la phrase prononcée
    aux messages réellement mis en file.
    """
    telephone = lead_donnees["slots"].get("telephone_rappel")
    if not telephone:
        raise MessageInterdit(f"RDV {rdv.id} : pas de téléphone pour joindre le client")
    return Brouillon(
        cle_idempotence=f"confirmation_client:{rdv.id}",
        artisan_id=rdv.artisan_id,
        destinataire=Destinataire.CLIENT, canal=Canal.SMS, cible=telephone,
        texte=_texte("confirmation_client", cfg, rdv_valide=True,
                     nom_entreprise=cfg["entreprise"]["nom"],
                     prenom=cfg["entreprise"]["prenom_patron"],
                     creneau=rdv.creneau["label"]))


def repli_client(rdv, lead_donnees: dict, cfg: dict) -> Brouillon:
    """SMS de repli au client dont le créneau n'aboutit pas.

    Deux causes, un seul texte : l'échéance est passée sans réponse de l'artisan, ou
    l'artisan a refusé. Du point de vue du client c'est la même chose — le créneau n'est
    pas retenu et on le recontacte — et les deux issues sont exclusives, donc la clé
    d'idempotence (`expiration_client:{id}`, nommée d'après la première cause connue)
    reste correcte pour les deux.
    """
    telephone = lead_donnees["slots"].get("telephone_rappel")
    if not telephone:
        raise MessageInterdit(f"RDV {rdv.id} : pas de téléphone pour joindre le client")
    return Brouillon(
        cle_idempotence=f"expiration_client:{rdv.id}",
        artisan_id=rdv.artisan_id,
        destinataire=Destinataire.CLIENT, canal=Canal.SMS, cible=telephone,
        texte=_texte("expiration_client", cfg,
                     nom_entreprise=cfg["entreprise"]["nom"],
                     prenom=cfg["entreprise"]["prenom_patron"],
                     creneau=rdv.creneau["label"]))


def reproposition_client(rdv, lead_donnees: dict, cfg: dict, lien: str) -> Brouillon:
    """SMS proposant un autre créneau, avec le lien de validation à un tap.

    La clé d'idempotence est dérivée de l'empreinte du jeton : elle change à chaque
    reproposition (l'artisan peut en faire plusieurs) mais reste stable si l'envoi est
    rejoué — un client ne reçoit pas deux fois la même proposition.
    """
    telephone = lead_donnees["slots"].get("telephone_rappel")
    if not telephone:
        raise MessageInterdit(f"RDV {rdv.id} : pas de téléphone pour joindre le client")
    if not rdv.confirmation_sha256:
        raise MessageInterdit(f"RDV {rdv.id} : pas de jeton de confirmation")
    return Brouillon(
        cle_idempotence=f"reproposition:{rdv.confirmation_sha256[:16]}",
        artisan_id=rdv.artisan_id,
        destinataire=Destinataire.CLIENT, canal=Canal.SMS, cible=telephone,
        texte=_texte("reproposition_client", cfg,
                     nom_entreprise=cfg["entreprise"]["nom"],
                     prenom=cfg["entreprise"]["prenom_patron"],
                     creneau=rdv.creneau["label"], lien=lien))


def confirmation_artisan(rdv, lead_donnees: dict, cfg: dict) -> Brouillon:
    """Le client a validé : l'artisan doit le savoir sans avoir à regarder l'app."""
    return Brouillon(
        cle_idempotence=f"confirmation_artisan:{rdv.id}",
        artisan_id=rdv.artisan_id,
        destinataire=Destinataire.ARTISAN, canal=Canal.PUSH, cible=rdv.artisan_id,
        texte=_texte("confirmation_artisan", cfg,
                     client=lead_donnees["slots"].get("nom") or "un client",
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
        artisan_id=rdv.artisan_id,
        destinataire=Destinataire.ARTISAN, canal=Canal.PUSH,
        cible=rdv.artisan_id,
        texte=_texte("expiration_artisan", cfg, creneau=rdv.creneau["label"],
                     client=slots.get("nom") or "un client",
                     commune=slots.get("commune") or slots.get("code_postal") or "?",
                     telephone=slots.get("telephone_rappel") or "?"))
