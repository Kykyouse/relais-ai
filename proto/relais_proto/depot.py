"""Port de persistance (appel / lead / RDV) + implémentation en mémoire.

Le port est la seule chose que l'API connaîtra : l'adaptateur Postgres se greffe derrière
sans toucher au domaine (`rdv.py`) ni au moteur (`engine.py`). Corollaire backend de la
règle n°1 du projet — « le LLM ne décide jamais » a pour pendant « le dépôt ne décide
jamais » : il stocke et retrouve, les transitions restent dans `Rdv`.

L'implémentation en mémoire SÉRIALISE à l'écriture et RECONSTRUIT à la lecture : elle ne
rend jamais deux fois la même instance. Sans cela, un test passerait en mutant l'objet
récupéré sans jamais appeler `sauver_rdv()`, et casserait le jour où il y a une vraie base
derrière — le pire genre de test double, celui qui rassure à tort.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace
from typing import Protocol

from . import temps
from .messages import Brouillon, MessageSortant, StatutMessage
from .rdv import Rdv, StatutRdv, TERMINAUX


class Introuvable(KeyError):
    """Identifiant absent du dépôt."""


@dataclass
class Appel:
    id: str
    artisan_id: str
    debut_a: dt.datetime
    # blob versionné produit par Conversation.to_dict() : c'est lui qui permet au tour
    # suivant de tomber sur un autre process (cf. brique sérialisation, test R14)
    etat_conversation: dict | None = None
    fin_a: dt.datetime | None = None
    lead_id: str | None = None


@dataclass
class LigneArtisan:
    """Le REGISTRE d'un artisan, tel qu'il vit en base (migration 008) : qui il est et par
    quelle porte il entre. **Pas sa config** — elle reste un fichier versionné dans git
    (`config_fichier`), parce que son historique est ce qui répond à « qu'est-ce que
    l'agent savait le jour de cet appel ? ».

    `numero_relais`, `telephone` et `config_fichier` sont facultatifs : la migration crée
    une ligne pour chaque artisan déjà référencé par des données existantes, dont elle ne
    connaît que l'identifiant. Ces lignes portent `etat_abonnement = "a_reprendre"`.
    """
    id: str
    nom_affiche: str | None = None
    numero_relais: str | None = None
    telephone: str | None = None
    config_fichier: str | None = None
    token_sha256: str | None = None
    etat_abonnement: str = "actif"

    def utilisable(self) -> bool:
        """Un artisan qu'on peut réellement servir : il a un numéro Relais et une config.
        Les autres sont des reprises de données, pas des clients."""
        return bool(self.numero_relais and self.config_fichier)


@dataclass
class Lead:
    id: str
    appel_id: str
    artisan_id: str
    # sortie de build_lead() telle quelle : c'est le contrat de la carte lead du
    # dashboard (spec produit §6), figé ici plutôt que redécoupé en colonnes
    donnees: dict = field(default_factory=dict)


class Depot(Protocol):
    """Ce que l'API et le worker d'expiration ont le droit de demander au stockage."""

    def artisans(self) -> list[LigneArtisan]: ...

    def enregistrer_artisan(self, ligne: LigneArtisan) -> None: ...

    def ouvrir_appel(self, artisan_id: str, maintenant: dt.datetime) -> Appel: ...

    def enregistrer_etat(self, appel_id: str, etat: dict) -> None: ...

    def appel(self, appel_id: str) -> Appel: ...

    def cloturer_appel(self, appel_id: str, lead_donnees: dict,
                       maintenant: dt.datetime) -> Lead: ...

    def creer_rdv(self, *, lead_id: str, hold: dict, lead_donnees: dict, cfg: dict,
                  maintenant: dt.datetime) -> Rdv: ...

    def rdv(self, rdv_id: str) -> Rdv: ...

    def sauver_rdv(self, rdv: Rdv) -> None: ...

    def rdvs_en_attente(self, artisan_id: str) -> list[Rdv]: ...

    def rdvs_echus(self, maintenant: dt.datetime) -> list[Rdv]: ...

    def rdv_par_confirmation(self, empreinte: str) -> Rdv: ...

    def lead(self, lead_id: str) -> Lead: ...

    def marquer_lead_alerte(self, lead_id: str, motif: str,
                            maintenant: dt.datetime) -> None: ...

    def enfiler_message(self, brouillon: Brouillon,
                        maintenant: dt.datetime) -> tuple[MessageSortant, bool]: ...

    def messages(self, statut: StatutMessage | None = None) -> list[MessageSortant]: ...

    def creer_session(self, empreinte: str, artisan_id: str, expire_a: dt.datetime,
                      maintenant: dt.datetime, appareil: str | None = None) -> None: ...

    def artisan_de_session(self, empreinte: str, maintenant: dt.datetime) -> str: ...

    def supprimer_session(self, empreinte: str) -> None: ...

    def marquer_message_envoye(self, message_id: str, maintenant: dt.datetime,
                               reference: str | None = None,
                               cout: int | None = None) -> None: ...

    def marquer_message_echec(self, message_id: str, erreur: str,
                              maintenant: dt.datetime,
                              definitif: bool = False) -> None: ...

    def differer_message(self, message_id: str,
                         envoyer_apres: dt.datetime) -> None: ...


class DepotMemoire:
    """Implémentation de test. Identifiants séquentiels : les tests restent lisibles,
    et l'adaptateur Postgres mettra des UUID sans que le domaine s'en aperçoive."""

    def __init__(self) -> None:
        self._appels: dict[str, dict] = {}
        self._leads: dict[str, dict] = {}
        self._rdvs: dict[str, dict] = {}
        self._messages: dict[str, dict] = {}
        self._par_cle: dict[str, str] = {}   # clé d'idempotence -> id message
        self._sessions: dict[str, dict] = {}  # empreinte -> session
        self._artisans_registre: dict[str, LigneArtisan] = {}
        self._compteurs: dict[str, int] = {}

    # ---- registre des artisans ----
    def artisans(self) -> list[LigneArtisan]:
        return [replace(a) for a in self._artisans_registre.values()]

    def enregistrer_artisan(self, ligne: LigneArtisan) -> None:
        """Créer ou mettre à jour. La synchronisation depuis le registre fichier rejoue
        cet appel à chaque démarrage : il doit être idempotent."""
        self._artisans_registre[ligne.id] = replace(ligne)

    def _id(self, prefixe: str) -> str:
        self._compteurs[prefixe] = self._compteurs.get(prefixe, 0) + 1
        return f"{prefixe}-{self._compteurs[prefixe]}"

    # ---- appels ----
    def ouvrir_appel(self, artisan_id: str, maintenant: dt.datetime) -> Appel:
        appel = Appel(id=self._id("apl"), artisan_id=artisan_id, debut_a=maintenant)
        self._appels[appel.id] = self._appel_en_dict(appel)
        return appel

    def enregistrer_etat(self, appel_id: str, etat: dict) -> None:
        self._exige(self._appels, appel_id)["etat_conversation"] = etat

    def appel(self, appel_id: str) -> Appel:
        return self._appel_de_dict(self._exige(self._appels, appel_id))

    def cloturer_appel(self, appel_id: str, lead_donnees: dict,
                       maintenant: dt.datetime) -> Lead:
        brut = self._exige(self._appels, appel_id)
        if brut["fin_a"] is not None:
            raise ValueError(f"appel {appel_id} déjà clôturé")
        lead = Lead(id=self._id("lead"), appel_id=appel_id,
                    artisan_id=brut["artisan_id"], donnees=lead_donnees)
        self._leads[lead.id] = {"id": lead.id, "appel_id": lead.appel_id,
                                "artisan_id": lead.artisan_id, "donnees": lead.donnees}
        brut["fin_a"] = maintenant.isoformat()
        brut["lead_id"] = lead.id
        return lead

    def lead(self, lead_id: str) -> Lead:
        d = self._exige(self._leads, lead_id)
        return Lead(id=d["id"], appel_id=d["appel_id"], artisan_id=d["artisan_id"],
                    donnees=d["donnees"])

    # ---- RDV ----
    def creer_rdv(self, *, lead_id: str, hold: dict, lead_donnees: dict, cfg: dict,
                  maintenant: dt.datetime) -> Rdv:
        lead = self.lead(lead_id)
        rdv = Rdv.depuis_hold(hold, id=self._id("rdv"), lead_id=lead_id,
                              artisan_id=lead.artisan_id, lead=lead_donnees,
                              cfg=cfg, maintenant=maintenant)
        self._rdvs[rdv.id] = rdv.to_dict()
        return rdv

    def rdv(self, rdv_id: str) -> Rdv:
        return Rdv.from_dict(self._exige(self._rdvs, rdv_id))

    def sauver_rdv(self, rdv: Rdv) -> None:
        self._exige(self._rdvs, rdv.id)
        self._rdvs[rdv.id] = rdv.to_dict()

    def rdvs_en_attente(self, artisan_id: str) -> list[Rdv]:
        """La boîte de validation de l'artisan : ce sur quoi il doit taper."""
        return [r for r in self._tous_rdvs()
                if r.artisan_id == artisan_id and r.statut not in TERMINAUX]

    def rdvs_echus(self, maintenant: dt.datetime) -> list[Rdv]:
        """La file du worker d'expiration. Inclut les RDV encore en TAMPON : un push
        qui n'est jamais parti ne doit pas laisser un créneau bloqué indéfiniment."""
        return [r for r in self._tous_rdvs()
                if r.statut not in TERMINAUX and r.est_echu(maintenant)]

    def _tous_rdvs(self) -> list[Rdv]:
        return [Rdv.from_dict(d) for d in self._rdvs.values()]

    def rdv_par_confirmation(self, empreinte: str) -> Rdv:
        """Le client ne présente qu'un jeton : c'est la seule entrée dont il dispose."""
        if not empreinte:
            raise Introuvable("jeton vide")
        for r in self._tous_rdvs():
            if r.confirmation_sha256 == empreinte:
                return r
        raise Introuvable("jeton de confirmation inconnu")

    def marquer_lead_alerte(self, lead_id: str, motif: str,
                            maintenant: dt.datetime) -> None:
        """Alerte rouge sur la carte lead (spec §3.6). Écrite DANS les données du lead :
        c'est ce que le dashboard lit, pas une table à part."""
        brut = self._exige(self._leads, lead_id)
        brut["donnees"] = {**brut["donnees"],
                           "alerte": {"motif": motif,
                                      "horodatage": maintenant.isoformat(
                                          timespec="seconds")}}

    # ---- file sortante ----
    def enfiler_message(self, brouillon: Brouillon,
                        maintenant: dt.datetime) -> tuple[MessageSortant, bool]:
        """Équivalent d'un INSERT ... ON CONFLICT (cle_idempotence) DO NOTHING.

        Renvoie (message, nouveau). Deux passages du worker sur le même RDV rendent donc
        le MÊME message : c'est ce qui garantit qu'un client ne reçoit pas deux SMS, sans
        que l'appelant ait à s'en préoccuper.
        """
        existant = self._par_cle.get(brouillon.cle_idempotence)
        if existant:
            return MessageSortant.from_dict(self._messages[existant]), False
        message = MessageSortant(
            id=self._id("msg"), cle_idempotence=brouillon.cle_idempotence,
            destinataire=brouillon.destinataire, canal=brouillon.canal,
            cible=brouillon.cible, texte=brouillon.texte, cree_a=maintenant,
            artisan_id=brouillon.artisan_id)
        self._messages[message.id] = message.to_dict()
        self._par_cle[message.cle_idempotence] = message.id
        return message, True

    def messages(self, statut: StatutMessage | None = None) -> list[MessageSortant]:
        tous = [MessageSortant.from_dict(d) for d in self._messages.values()]
        return [m for m in tous if statut is None or m.statut is statut]

    def marquer_message_envoye(self, message_id: str, maintenant: dt.datetime,
                               reference: str | None = None,
                               cout: int | None = None) -> None:
        brut = self._exige(self._messages, message_id)
        brut["statut"] = StatutMessage.ENVOYE.value
        brut["envoye_a"] = maintenant.isoformat()
        brut["reference"] = reference
        brut["cout"] = cout

    def marquer_message_echec(self, message_id: str, erreur: str,
                              maintenant: dt.datetime,
                              definitif: bool = False) -> None:
        """Un échec transitoire laisse le message en file (réessai) ; au-delà de
        `essais_max` il passe en `echec` — visible en monitoring plutôt que réessayé
        indéfiniment."""
        brut = self._exige(self._messages, message_id)
        brut["essais"] = brut.get("essais", 0) + 1
        brut["derniere_erreur"] = erreur
        if definitif:
            brut["statut"] = StatutMessage.ECHEC.value

    def differer_message(self, message_id: str, envoyer_apres: dt.datetime) -> None:
        self._exige(self._messages, message_id)["envoyer_apres"] =             envoyer_apres.isoformat()

    # ---- sessions ----
    def creer_session(self, empreinte: str, artisan_id: str, expire_a: dt.datetime,
                      maintenant: dt.datetime, appareil: str | None = None) -> None:
        self._sessions[empreinte] = {"artisan_id": artisan_id, "cree_a": maintenant,
                                     "expire_a": expire_a, "appareil": appareil}

    def artisan_de_session(self, empreinte: str, maintenant: dt.datetime) -> str:
        """Rend l'artisan de la session, ou lève `Introuvable`.

        Une session PÉRIMÉE est traitée comme absente : c'est le dépôt qui applique
        l'expiration, pas l'appelant. Sinon il suffirait d'oublier de la vérifier une fois.
        """
        brut = self._sessions.get(empreinte)
        if brut is None or brut["expire_a"] <= maintenant:
            raise Introuvable("session inconnue ou périmée")
        return brut["artisan_id"]

    def supprimer_session(self, empreinte: str) -> None:
        self._sessions.pop(empreinte, None)   # déconnexion idempotente

    # ---- utils ----
    @staticmethod
    def _exige(table: dict, cle: str) -> dict:
        if cle not in table:
            raise Introuvable(cle)
        return table[cle]

    @staticmethod
    def _appel_en_dict(a: Appel) -> dict:
        return {"id": a.id, "artisan_id": a.artisan_id, "debut_a": a.debut_a.isoformat(),
                "etat_conversation": a.etat_conversation,
                "fin_a": a.fin_a.isoformat() if a.fin_a else None, "lead_id": a.lead_id}

    @staticmethod
    def _appel_de_dict(d: dict) -> Appel:
        return Appel(id=d["id"], artisan_id=d["artisan_id"],
                     debut_a=temps.depuis_iso(d["debut_a"]),
                     etat_conversation=d["etat_conversation"],
                     fin_a=temps.depuis_iso(d["fin_a"]) if d["fin_a"] else None,
                     lead_id=d["lead_id"])
