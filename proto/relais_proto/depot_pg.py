"""Adaptateur Postgres du port `Depot` (cf. depot.py).

Même contrat que `DepotMemoire`, mêmes tests : `contrat_depot.verifier()` tourne contre les
deux implémentations. Si l'un passe et l'autre pas, c'est l'adaptateur qui a tort.

Deux choix qui méritent d'être explicites :

* **Les identifiants sont générés en Python** (uuid4), pas par `default gen_random_uuid()`.
  Le domaine a besoin de l'id AVANT l'insert (`Rdv.depuis_hold(id=...)` construit l'objet,
  qui journalise sa création). Le défaut SQL reste, pour les insertions manuelles.

* **`rdvs_echus()` ne verrouille pas.** Un `FOR UPDATE SKIP LOCKED` supposerait de tenir
  une transaction ouverte pendant tout le traitement du worker, ce que le port n'exprime
  pas. Et ce n'est pas nécessaire à la correction : deux workers concurrents ne peuvent pas
  doubler un SMS (l'unicité de `cle_idempotence` est portée par la base) ni voler une
  décision à l'artisan (`Rdv.valider()` refuse un RDV échu). Au pire, deux entrées
  d'historique identiques. Le verrouillage est une optimisation à ajouter quand plusieurs
  workers tourneront pour de vrai, pas un prérequis de justesse.
"""
from __future__ import annotations

import datetime as dt
import uuid

from .depot import Appel, Introuvable, Lead
from .messages import Brouillon, MessageSortant, StatutMessage
from .rdv import Rdv, StatutRdv, TERMINAUX

_NON_TERMINAUX = tuple(s.value for s in StatutRdv if s not in TERMINAUX)


def _json(valeur):
    """Enveloppe jsonb. Import tardif : psycopg n'est pas requis en mode mock."""
    from psycopg.types.json import Jsonb
    return Jsonb(valeur)


def options_dsn(dsn: str) -> dict:
    """Options de connexion déduites du DSN. Un pooler en mode TRANSACTION (port 6543) ne
    survit pas aux prepared statements que psycopg active de lui-même."""
    return {"prepare_threshold": None} if ":6543/" in dsn or dsn.rstrip("/").endswith(":6543") else {}


def resoudre_connexion(candidats: list[tuple[str, str]], timeout: int = 8):
    """Essaie chaque `(libellé, dsn)` dans l'ordre et rend le premier qui répond, sous la
    forme `(dsn, options, libellé)`.

    **Partagé par TOUS les points d'entrée**, et c'est le point : ce repli n'existait
    d'abord que dans `run_depot_pg.py`. Le 24/08, l'hôte direct de Supabase a cessé de
    résoudre sur la machine de dév (il est en IPv6) — le lanceur de tests basculait
    tranquillement sur le pooler pendant que `worker.py` et `serveur.py` tombaient. Une
    logique de résilience qui ne vit que dans le harnais de test ne protège personne.
    """
    import psycopg
    echecs = []
    for nom, dsn in [(n, d) for n, d in candidats if d]:
        opts = options_dsn(dsn)
        try:
            psycopg.connect(dsn, connect_timeout=timeout, **opts).close()
        except Exception as exc:  # noqa: BLE001 — on veut le message tel quel
            echecs.append(f"{nom} ({type(exc).__name__})")
            continue
        return dsn, opts, (f"{nom} (après échec de {', '.join(echecs)})" if echecs else nom)
    raise RuntimeError(
        "aucune connexion Postgres ne répond. Essayés : "
        + (", ".join(echecs) or "aucun DSN fourni")
        + ". Renseigne DATABASE_URL et DATABASE_URL_POOLER (voir .env.example) — l'hôte "
          "direct de Supabase est en IPv6 et peut être injoignable selon le réseau.")


def candidats_env() -> list[tuple[str, str]]:
    """Les deux DSN attendus, dans l'ordre de préférence. Centralisé ici pour que les
    points d'entrée ne divergent pas sur les noms de variables."""
    import os
    return [("directe", os.environ.get("DATABASE_URL", "")),
            ("session pooler", os.environ.get("DATABASE_URL_POOLER", ""))]


class DepotPostgres:
    """Une connexion, autocommit. Suffisant pour le worker et pour les tests ;
    un pool viendra avec l'API, qui sert plusieurs requêtes en parallèle."""

    def __init__(self, dsn: str, **options):
        """`options` passe à psycopg.connect : `prepare_threshold=None` est nécessaire
        derrière un pooler en mode transaction, qui ne survit pas aux prepared
        statements que psycopg active de lui-même après quelques exécutions."""
        import psycopg  # import tardif : dépendance optionnelle
        self.cx = psycopg.connect(dsn, autocommit=True, **options)

    def fermer(self) -> None:
        self.cx.close()

    # ---- outils ----
    @staticmethod
    def _id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _uuid(valeur, cle: str) -> str:
        """Un identifiant qui n'est même pas un UUID est introuvable par construction.

        Sans ce filtre, Postgres lèverait une erreur de cast là où le dépôt mémoire rend
        simplement `Introuvable` : deux comportements pour un même appel, et un 500 au
        lieu d'un 404 le jour où l'API passera directement un id fourni par le client.
        """
        try:
            uuid.UUID(str(valeur))
        except (ValueError, AttributeError, TypeError):
            raise Introuvable(cle) from None
        return str(valeur)

    def _un(self, sql: str, params: tuple, cle: str) -> tuple:
        with self.cx.cursor() as cur:
            cur.execute(sql, params)
            ligne = cur.fetchone()
        if ligne is None:
            raise Introuvable(cle)
        return ligne

    def _plusieurs(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self.cx.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _executer(self, sql: str, params: tuple) -> int:
        with self.cx.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    # ---- appels ----
    def ouvrir_appel(self, artisan_id: str, maintenant: dt.datetime) -> Appel:
        appel = Appel(id=self._id(), artisan_id=artisan_id, debut_a=maintenant)
        self._executer(
            "insert into appel (id, artisan_id, debut_a) values (%s, %s, %s)",
            (appel.id, artisan_id, maintenant))
        return appel

    def enregistrer_etat(self, appel_id: str, etat: dict) -> None:
        appel_id = self._uuid(appel_id, appel_id)
        if not self._executer("update appel set etat_conversation = %s where id = %s",
                              (_json(etat), appel_id)):
            raise Introuvable(appel_id)

    def appel(self, appel_id: str) -> Appel:
        appel_id = self._uuid(appel_id, appel_id)
        ligne = self._un(
            "select id, artisan_id, debut_a, fin_a, lead_id, etat_conversation "
            "from appel where id = %s", (appel_id,), appel_id)
        return Appel(id=str(ligne[0]), artisan_id=ligne[1], debut_a=ligne[2],
                     fin_a=ligne[3], lead_id=str(ligne[4]) if ligne[4] else None,
                     etat_conversation=ligne[5])

    def cloturer_appel(self, appel_id: str, lead_donnees: dict,
                       maintenant: dt.datetime) -> Lead:
        appel = self.appel(appel_id)          # lève Introuvable si absent
        if appel.fin_a is not None:
            raise ValueError(f"appel {appel_id} déjà clôturé")
        lead = Lead(id=self._id(), appel_id=appel_id, artisan_id=appel.artisan_id,
                    donnees=lead_donnees)
        self._executer(
            "insert into lead (id, appel_id, artisan_id, donnees) values (%s,%s,%s,%s)",
            (lead.id, appel_id, lead.artisan_id, _json(lead_donnees)))
        self._executer("update appel set fin_a = %s, lead_id = %s where id = %s",
                       (maintenant, lead.id, appel_id))
        return lead

    def lead(self, lead_id: str) -> Lead:
        lead_id = self._uuid(lead_id, lead_id)
        ligne = self._un("select id, appel_id, artisan_id, donnees from lead where id = %s",
                         (lead_id,), lead_id)
        return Lead(id=str(ligne[0]), appel_id=str(ligne[1]), artisan_id=ligne[2],
                    donnees=ligne[3])

    def marquer_lead_alerte(self, lead_id: str, motif: str,
                            maintenant: dt.datetime) -> None:
        lead_id = self._uuid(lead_id, lead_id)
        alerte = {"motif": motif, "horodatage": maintenant.isoformat(timespec="seconds")}
        # jsonb_set ne crée pas la clé sur un objet vide de façon fiable : on fusionne,
        # ce qui écrase une alerte précédente — le comportement voulu (la dernière compte).
        if not self._executer(
                "update lead set donnees = donnees || %s where id = %s",
                (_json({"alerte": alerte}), lead_id)):
            raise Introuvable(lead_id)

    # ---- RDV ----
    _COLS_RDV = ("id, lead_id, artisan_id, creneau, duree_min, urgence, statut, "
                 "expire_a, cree_a, notifie_a, decide_a, historique, "
                 "confirmation_sha256")

    @staticmethod
    def _rdv_de_ligne(l: tuple) -> Rdv:
        return Rdv(id=str(l[0]), lead_id=str(l[1]), artisan_id=l[2], creneau=l[3],
                   duree_min=l[4], urgence=l[5], statut=StatutRdv(l[6]), expire_a=l[7],
                   cree_a=l[8], notifie_a=l[9], decide_a=l[10], historique=l[11],
                   confirmation_sha256=l[12])

    def creer_rdv(self, *, lead_id: str, hold: dict, lead_donnees: dict, cfg: dict,
                  maintenant: dt.datetime) -> Rdv:
        lead = self.lead(lead_id)
        rdv = Rdv.depuis_hold(hold, id=self._id(), lead_id=lead_id,
                              artisan_id=lead.artisan_id, lead=lead_donnees,
                              cfg=cfg, maintenant=maintenant)
        self._executer(
            f"insert into rdv ({self._COLS_RDV}) values "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (rdv.id, rdv.lead_id, rdv.artisan_id, _json(rdv.creneau), rdv.duree_min,
             rdv.urgence, rdv.statut.value, rdv.expire_a, rdv.cree_a, rdv.notifie_a,
             rdv.decide_a, _json(rdv.historique), rdv.confirmation_sha256))
        return rdv

    def rdv(self, rdv_id: str) -> Rdv:
        rdv_id = self._uuid(rdv_id, rdv_id)
        return self._rdv_de_ligne(
            self._un(f"select {self._COLS_RDV} from rdv where id = %s",
                     (rdv_id,), rdv_id))

    def sauver_rdv(self, rdv: Rdv) -> None:
        self._uuid(rdv.id, rdv.id)
        if not self._executer(
                "update rdv set statut = %s, expire_a = %s, notifie_a = %s, "
                "decide_a = %s, historique = %s, creneau = %s, "
                "confirmation_sha256 = %s where id = %s",
                (rdv.statut.value, rdv.expire_a, rdv.notifie_a, rdv.decide_a,
                 _json(rdv.historique), _json(rdv.creneau),
                 rdv.confirmation_sha256, rdv.id)):
            raise Introuvable(rdv.id)

    def rdvs_en_attente(self, artisan_id: str) -> list[Rdv]:
        return [self._rdv_de_ligne(l) for l in self._plusieurs(
            f"select {self._COLS_RDV} from rdv where artisan_id = %s "
            "and statut = any(%s) order by expire_a", (artisan_id, list(_NON_TERMINAUX)))]

    def rdvs_echus(self, maintenant: dt.datetime) -> list[Rdv]:
        return [self._rdv_de_ligne(l) for l in self._plusieurs(
            f"select {self._COLS_RDV} from rdv where statut = any(%s) "
            "and expire_a <= %s order by expire_a",
            (list(_NON_TERMINAUX), maintenant))]

    def rdv_par_confirmation(self, empreinte: str) -> Rdv:
        if not empreinte:
            raise Introuvable("jeton vide")
        return self._rdv_de_ligne(self._un(
            f"select {self._COLS_RDV} from rdv where confirmation_sha256 = %s",
            (empreinte,), "jeton de confirmation inconnu"))

    # ---- file sortante ----
    _COLS_MSG = ("id, cle_idempotence, destinataire, canal, cible, texte, statut, "
                 "cree_a, envoye_a, essais, derniere_erreur, envoyer_apres, reference, "
                 "artisan_id, cout")

    @staticmethod
    def _msg_de_ligne(l: tuple) -> MessageSortant:
        return MessageSortant.from_dict({
            "id": str(l[0]), "cle_idempotence": l[1], "destinataire": l[2], "canal": l[3],
            "cible": l[4], "texte": l[5], "statut": l[6],
            "cree_a": l[7].isoformat(), "envoye_a": l[8].isoformat() if l[8] else None,
            "essais": l[9], "derniere_erreur": l[10],
            "envoyer_apres": l[11].isoformat() if l[11] else None, "reference": l[12],
            "artisan_id": l[13], "cout": l[14]})

    def enfiler_message(self, brouillon: Brouillon,
                        maintenant: dt.datetime) -> tuple[MessageSortant, bool]:
        """INSERT ... ON CONFLICT DO NOTHING : c'est la BASE qui refuse le doublon, pas
        un test applicatif — deux workers concurrents peuvent tenter le même insert."""
        nouvel_id = self._id()
        cree = self._executer(
            f"insert into message_sortant ({self._COLS_MSG}) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (cle_idempotence) do nothing",
            (nouvel_id, brouillon.cle_idempotence, brouillon.destinataire.value,
             brouillon.canal.value, brouillon.cible, brouillon.texte,
             StatutMessage.A_ENVOYER.value, maintenant, None, 0, None, None, None,
             brouillon.artisan_id, None))
        ligne = self._un(
            f"select {self._COLS_MSG} from message_sortant where cle_idempotence = %s",
            (brouillon.cle_idempotence,), brouillon.cle_idempotence)
        return self._msg_de_ligne(ligne), bool(cree)

    def messages(self, statut: StatutMessage | None = None) -> list[MessageSortant]:
        if statut is None:
            return [self._msg_de_ligne(l) for l in self._plusieurs(
                f"select {self._COLS_MSG} from message_sortant order by cree_a, id")]
        return [self._msg_de_ligne(l) for l in self._plusieurs(
            f"select {self._COLS_MSG} from message_sortant where statut = %s "
            "order by cree_a, id", (statut.value,))]

    # ---- sessions ----
    def creer_session(self, empreinte: str, artisan_id: str, expire_a: dt.datetime,
                      maintenant: dt.datetime, appareil: str | None = None) -> None:
        # ON CONFLICT : une reconnexion sur le même appareil réécrit sa session au lieu
        # d'en empiler une seconde
        self._executer(
            "insert into session_artisan (empreinte, artisan_id, cree_a, expire_a, "
            "appareil) values (%s,%s,%s,%s,%s) on conflict (empreinte) do update set "
            "expire_a = excluded.expire_a, appareil = excluded.appareil",
            (empreinte, artisan_id, maintenant, expire_a, appareil))

    def artisan_de_session(self, empreinte: str, maintenant: dt.datetime) -> str:
        """L'expiration est appliquée EN SQL : impossible d'oublier de la vérifier."""
        ligne = self._un(
            "select artisan_id from session_artisan where empreinte = %s "
            "and expire_a > %s", (empreinte, maintenant), "session inconnue ou périmée")
        return ligne[0]

    def supprimer_session(self, empreinte: str) -> None:
        self._executer("delete from session_artisan where empreinte = %s", (empreinte,))

    def marquer_message_envoye(self, message_id: str, maintenant: dt.datetime,
                               reference: str | None = None,
                               cout: int | None = None) -> None:
        message_id = self._uuid(message_id, message_id)
        if not self._executer(
                "update message_sortant set statut = %s, envoye_a = %s, reference = %s, "
                "cout = %s where id = %s",
                (StatutMessage.ENVOYE.value, maintenant, reference, cout, message_id)):
            raise Introuvable(message_id)

    def marquer_message_echec(self, message_id: str, erreur: str,
                              maintenant: dt.datetime,
                              definitif: bool = False) -> None:
        """`essais` incrémenté EN SQL (`essais + 1`) et non depuis la valeur lue : deux
        expéditeurs concurrents ne doivent pas se marcher dessus sur le compteur."""
        message_id = self._uuid(message_id, message_id)
        if definitif:
            sql = ("update message_sortant set essais = essais + 1, derniere_erreur = %s, "
                   "statut = %s where id = %s")
            params = (erreur, StatutMessage.ECHEC.value, message_id)
        else:
            sql = ("update message_sortant set essais = essais + 1, derniere_erreur = %s "
                   "where id = %s")
            params = (erreur, message_id)
        if not self._executer(sql, params):
            raise Introuvable(message_id)

    def differer_message(self, message_id: str, envoyer_apres: dt.datetime) -> None:
        message_id = self._uuid(message_id, message_id)
        if not self._executer(
                "update message_sortant set envoyer_apres = %s where id = %s",
                (envoyer_apres, message_id)):
            raise Introuvable(message_id)
