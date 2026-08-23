"""Worker d'expiration : le RDV que l'artisan n'a pas validé à temps.

Spec produit §3.6 : échéance dépassée sans réponse → créneau tampon libéré, SMS de repli
au client, lead en alerte, relance artisan. C'est la brique qui rend la promesse tenable :
sans elle, un artisan silencieux laisse un client attendre indéfiniment un SMS.

Deux propriétés que ce worker doit avoir, et que R16 vérifie :

  1. **Idempotent.** Un cron qui double-tire, un redémarrage au mauvais moment, deux
     instances en parallèle : le client ne doit recevoir qu'UN SMS. C'est la clé
     d'idempotence de la file sortante qui le garantit, pas la prudence de l'appelant.
  2. **Il ne vole jamais une décision à l'artisan.** La course est déjà fermée en amont :
     `rdvs_echus()` ne rend que des RDV échus, et `Rdv.valider()` refuse un RDV échu —
     donc un RDV que le worker voit ne peut plus être validé, et un RDV validé n'est
     jamais dans sa file. Le garde-fou de `rdv.py` sert les deux côtés.

L'horloge est un paramètre de `passer()` : aucun `dt.datetime.now()` ici non plus.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import messages as msg
from .rdv import TransitionInterdite


@dataclass
class RapportPassage:
    """Ce qu'un passage du worker a fait — destiné au monitoring autant qu'aux tests."""
    examines: int = 0
    expires: list[str] = field(default_factory=list)       # ids de RDV
    messages_crees: list[str] = field(default_factory=list)
    deja_traites: list[str] = field(default_factory=list)  # messages déjà en file
    echecs: list[str] = field(default_factory=list)        # RDV expirés, message impossible

    def __bool__(self) -> bool:
        return bool(self.expires or self.messages_crees or self.echecs)


class WorkerExpiration:
    def __init__(self, depot, cfg: dict):
        self.depot = depot
        self.cfg = cfg

    def passer(self, maintenant: dt.datetime) -> RapportPassage:
        """ORDRE VOLONTAIRE : les effets idempotents d'abord, le changement d'état en
        dernier. C'est le passage au statut terminal qui retire le RDV de `rdvs_echus()`
        — donc tant qu'il n'a pas eu lieu, un passage interrompu sera rejoué et rattrapé.
        L'ordre inverse perdrait le SMS pour de bon : un process tué juste après
        `sauver_rdv()` laisserait un RDV expiré que plus aucun passage ne reverrait, et
        un client qui n'a jamais été prévenu."""
        rapport = RapportPassage()
        for rdv in self.depot.rdvs_echus(maintenant):
            rapport.examines += 1
            try:
                self._traiter(rdv, rapport, maintenant)
            except Exception as exc:
                # Un RDV qui échoue ne bloque pas la file : il reste échu (son statut n'a
                # pas été écrit) et sera repris au passage suivant. Sans cette isolation,
                # une seule ligne fautive gèlerait l'expiration de tous les autres.
                rapport.echecs.append(f"{rdv.id}:{type(exc).__name__}: {exc}")
        return rapport

    def _traiter(self, rdv, rapport: RapportPassage, maintenant: dt.datetime) -> None:
        self._enfiler(rdv, rapport, maintenant)
        # Le créneau tampon est libéré par le changement de statut lui-même : un RDV
        # expiré n'occupe plus rien. Pas d'écriture calendrier séparée en V1 — quand le
        # calendrier réel arrivera, c'est ici que se posera la libération.
        self.depot.marquer_lead_alerte(rdv.lead_id, "rdv_expire_sans_reponse", maintenant)
        try:
            rdv.expirer(maintenant)
        except TransitionInterdite:
            # ne devrait pas arriver (rdvs_echus filtre les terminaux) : on passe sans
            # rien casser plutôt que d'écraser un statut décidé ailleurs
            return
        self.depot.sauver_rdv(rdv)
        rapport.expires.append(rdv.id)

    def _enfiler(self, rdv, rapport: RapportPassage, maintenant: dt.datetime) -> None:
        lead = self.depot.lead(rdv.lead_id)
        for construire in (msg.repli_client, msg.relance_artisan):
            try:
                brouillon = construire(rdv, lead.donnees, self.cfg)
            except msg.MessageInterdit as exc:
                # le RDV reste expiré : l'état ne doit pas dépendre de la réussite d'un
                # message. L'échec est visible dans le rapport, pas avalé.
                rapport.echecs.append(f"{rdv.id}:{exc}")
                continue
            message, nouveau = self.depot.enfiler_message(brouillon, maintenant)
            (rapport.messages_crees if nouveau else rapport.deja_traites).append(message.id)
