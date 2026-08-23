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
from dataclasses import dataclass, field
from typing import Protocol

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
class Lead:
    id: str
    appel_id: str
    artisan_id: str
    # sortie de build_lead() telle quelle : c'est le contrat de la carte lead du
    # dashboard (spec produit §6), figé ici plutôt que redécoupé en colonnes
    donnees: dict = field(default_factory=dict)


class Depot(Protocol):
    """Ce que l'API et le worker d'expiration ont le droit de demander au stockage."""

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


class DepotMemoire:
    """Implémentation de test. Identifiants séquentiels : les tests restent lisibles,
    et l'adaptateur Postgres mettra des UUID sans que le domaine s'en aperçoive."""

    def __init__(self) -> None:
        self._appels: dict[str, dict] = {}
        self._leads: dict[str, dict] = {}
        self._rdvs: dict[str, dict] = {}
        self._compteurs: dict[str, int] = {}

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
                     debut_a=dt.datetime.fromisoformat(d["debut_a"]),
                     etat_conversation=d["etat_conversation"],
                     fin_a=dt.datetime.fromisoformat(d["fin_a"]) if d["fin_a"] else None,
                     lead_id=d["lead_id"])
