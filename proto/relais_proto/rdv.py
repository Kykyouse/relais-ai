"""Cycle de vie d'un RDV : tampon → en_attente_validation → validé / refusé / expiré.

Pendant backend de `guards.py` : les transitions autorisées et le calcul de l'expiration
sont en CODE, pas en convention d'appel. Trois règles non négociables ici :

  1. Aucune sortie d'un état terminal. Un RDV expiré ne redevient jamais validé, même si
     l'artisan tape « valider » une seconde trop tard : le créneau tampon a été rendu et
     le SMS de repli est parti chez le client. Valider ici créerait deux vérités.
  2. Aucun appel à `dt.datetime.now()`. L'horloge est toujours un paramètre — sinon le
     worker d'expiration n'est testable qu'en attendant quatre heures, donc pas testé.
  3. Le chrono part de la RÉSERVATION, pas de la notification push. C'est à la
     réservation que l'agent a promis un SMS « d'ici 4 heures » à l'appelant : la
     promesse court dès qu'elle est prononcée, même si le push échoue derrière.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum


class StatutRdv(str, Enum):
    TAMPON = "tampon"                                # créneau bloqué, artisan pas encore notifié
    EN_ATTENTE_VALIDATION = "en_attente_validation"  # notifié, l'artisan peut décider
    REPROPOSE = "repropose"                          # autre créneau proposé, en attente DU CLIENT
    VALIDE = "valide"
    REFUSE = "refuse"
    EXPIRE = "expire"


TERMINAUX = frozenset({StatutRdv.VALIDE, StatutRdv.REFUSE, StatutRdv.EXPIRE})

# Le tampon peut expirer sans avoir jamais été notifié : si le push échoue, l'appelant
# ne doit pas rester avec un créneau fantôme que personne ne regarde.
TRANSITIONS: dict[StatutRdv, frozenset[StatutRdv]] = {
    StatutRdv.TAMPON: frozenset({StatutRdv.EN_ATTENTE_VALIDATION, StatutRdv.EXPIRE}),
    StatutRdv.EN_ATTENTE_VALIDATION: frozenset({StatutRdv.VALIDE, StatutRdv.REFUSE,
                                                StatutRdv.REPROPOSE, StatutRdv.EXPIRE}),
    # en attente du client : il confirme, ou l'échéance passe et le repli s'applique.
    # Non terminal, donc toujours dans la file du worker — un client qui ne répond pas
    # ne laisse pas un créneau bloqué indéfiniment.
    StatutRdv.REPROPOSE: frozenset({StatutRdv.VALIDE, StatutRdv.REFUSE, StatutRdv.EXPIRE}),
    StatutRdv.VALIDE: frozenset(),
    StatutRdv.REFUSE: frozenset(),
    StatutRdv.EXPIRE: frozenset(),
}


class TransitionInterdite(RuntimeError):
    """Transition hors du graphe, depuis un état terminal, ou décision après échéance."""


# ------------------------------------------------------------------ expiration
def _fenetres_ouvrees(cfg: dict, jour: dt.date) -> list[tuple[str, str]]:
    """Fenêtres pendant lesquelles l'artisan est réputé joignable pour valider.

    Utilisé seulement en mode `base_delai = "ouvrees"`. À défaut de
    `validation.heures_ouvrees`, on retombe sur les horaires de RDV — approximation :
    « quand il intervient » n'est pas « quand il regarde son téléphone ».
    """
    source = (cfg.get("validation", {}).get("heures_ouvrees")
              or cfg["agenda"]["horaires_rdv"])
    cle = ("lun-ven" if jour.weekday() <= 4 else "sam" if jour.weekday() == 5 else "dim")
    return [(f["de"], f["a"]) for f in source.get(cle, [])]


def _a(jour: dt.date, hhmm: str) -> dt.datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return dt.datetime.combine(jour, dt.time(h, m))


def _ajouter_heures_ouvrees(cfg: dict, depuis: dt.datetime, heures: float) -> dt.datetime:
    """Avance de `heures` en ne consommant que les fenêtres ouvrées."""
    restant = dt.timedelta(hours=heures)
    curseur = depuis
    for _ in range(60):  # garde-fou : 60 jours d'avance max (config d'horaires vide)
        for de, a in _fenetres_ouvrees(cfg, curseur.date()):
            debut = max(_a(curseur.date(), de), curseur)
            fin = _a(curseur.date(), a)
            if fin <= debut:
                continue
            if fin - debut >= restant:
                return debut + restant
            restant -= fin - debut
        curseur = _a(curseur.date() + dt.timedelta(days=1), "00:00")
    raise ValueError("aucune heure ouvrée trouvée en 60 jours : horaires de config vides ?")


def calculer_expiration(cfg: dict, urgence: bool, depuis: dt.datetime) -> dt.datetime:
    """Échéance de la décision artisan, d'après la config `validation` de CET artisan.

    Deux réglages, modifiables par artisan depuis son compte :
      - `delai_max_heures` (défaut 24) et `delai_max_urgence_heures` (défaut 2) ;
      - `base_delai` : "reelles" (défaut) ou "ouvrees".

    **L'urgence est toujours comptée en heures réelles**, quel que soit `base_delai` :
    une fuite prise à 19 h ne peut pas attendre l'ouverture du lendemain, c'est tout le
    sens du mot urgence.

    Le défaut est passé de 4 h ouvrées à 24 h réelles (retour terrain du 23/08 : la
    plupart des artisans ne regardent leur app que le soir — un délai de 4 h expire
    pendant qu'ils sont sur chantier). À 24 h réelles, le calcul en heures ouvrées perd
    son intérêt : la fenêtre contient de toute façon une soirée. Le mode "ouvrees" reste
    disponible pour un artisan qui voudrait un délai court sans expirer la nuit.
    """
    v = cfg["validation"]
    heures = v["delai_max_urgence_heures"] if urgence else v["delai_max_heures"]
    if urgence or v.get("base_delai", "reelles") == "reelles":
        return depuis + dt.timedelta(hours=heures)
    return _ajouter_heures_ouvrees(cfg, depuis, heures)


# ------------------------------------------------------------------ entité
@dataclass
class Rdv:
    id: str
    lead_id: str
    artisan_id: str
    creneau: dict          # {date, de, a, label, urgence} tel que produit par le calendrier
    duree_min: int
    urgence: bool
    expire_a: dt.datetime
    cree_a: dt.datetime
    statut: StatutRdv = StatutRdv.TAMPON
    notifie_a: dt.datetime | None = None
    decide_a: dt.datetime | None = None
    # empreinte SHA-256 du jeton de confirmation client. Jamais le jeton en clair : il part
    # dans un SMS, il vaut capacité — une fuite de base ne doit pas permettre de confirmer
    # des rendez-vous à la place des clients.
    confirmation_sha256: str | None = None
    historique: list[dict] = field(default_factory=list)

    CHAMPS_CRENEAU = ("date", "de", "a", "label", "urgence")

    @classmethod
    def depuis_hold(cls, hold: dict, *, id: str, lead_id: str, artisan_id: str,
                    lead: dict, cfg: dict, maintenant: dt.datetime) -> Rdv:
        """Construit le RDV tampon à partir du hold calendrier produit par la conversation.

        L'urgence est lue dans les SLOTS du lead, pas dans le hold : le hold dit seulement
        si le créneau vient de la fenêtre d'urgence réservée, alors que le délai promis à
        l'appelant par `engine._reserver` dépend de `urgence_reelle`. Prendre l'autre
        source ferait diverger l'échéance en base de la promesse prononcée au téléphone.
        """
        # invariant produit (CLAUDE.md règle 5) : jamais de RDV sans téléphone confirmé.
        # Déjà garanti par la machine à états — revérifié ici parce que c'est la frontière
        # de persistance, et qu'un RDV en base est un engagement vis-à-vis du client.
        if lead["slots"].get("tel_confirme") is not True:
            raise ValueError(f"RDV {id} refusé : téléphone non confirmé")
        urgence = bool(lead["slots"].get("urgence_reelle"))
        rdv = cls(id=id, lead_id=lead_id, artisan_id=artisan_id,
                  creneau={c: hold.get(c) for c in cls.CHAMPS_CRENEAU},
                  duree_min=hold["duree_min"], urgence=urgence,
                  expire_a=calculer_expiration(cfg, urgence, maintenant),
                  cree_a=maintenant)
        rdv._journaliser(StatutRdv.TAMPON, maintenant, "systeme")
        return rdv

    # ---- transitions ----
    def est_echu(self, maintenant: dt.datetime) -> bool:
        return maintenant >= self.expire_a

    def _journaliser(self, statut: StatutRdv, maintenant: dt.datetime, par: str) -> None:
        self.historique.append({"statut": statut.value, "par": par,
                                "horodatage": maintenant.isoformat(timespec="seconds")})

    def _transition(self, vers: StatutRdv, maintenant: dt.datetime, par: str) -> None:
        if vers not in TRANSITIONS[self.statut]:
            raise TransitionInterdite(
                f"RDV {self.id} : {self.statut.value} → {vers.value} interdit")
        self.statut = vers
        self._journaliser(vers, maintenant, par)

    def _refuser_si_echu(self, maintenant: dt.datetime) -> None:
        """LA course critique : l'artisan tape à 4 h 00 min 01 s, le worker d'expiration
        n'est pas encore passé. On refuse quand même. L'échéance est portée par
        `expire_a`, jamais par le fait que le worker soit à l'heure — sinon la décision
        de l'artisan dépend de la latence d'un cron, et le client reçoit deux messages
        contradictoires (SMS de repli, puis confirmation)."""
        if self.est_echu(maintenant):
            raise TransitionInterdite(
                f"RDV {self.id} échu depuis {self.expire_a.isoformat()} : décision "
                f"refusée, il faut repasser par une nouvelle proposition de créneau")

    def notifier(self, maintenant: dt.datetime, par: str = "systeme") -> None:
        self._transition(StatutRdv.EN_ATTENTE_VALIDATION, maintenant, par)
        self.notifie_a = maintenant

    def valider(self, maintenant: dt.datetime, par: str = "artisan") -> None:
        self._refuser_si_echu(maintenant)
        self._transition(StatutRdv.VALIDE, maintenant, par)
        self.decide_a = maintenant

    def refuser(self, maintenant: dt.datetime, par: str = "artisan") -> None:
        # un refus après échéance est refusé aussi : le créneau est déjà rendu, et le
        # statut doit rester EXPIRE pour que le funnel distingue « refusé » de « ignoré »
        self._refuser_si_echu(maintenant)
        self._transition(StatutRdv.REFUSE, maintenant, par)
        self.decide_a = maintenant

    def reproposer(self, nouveau_creneau: dict, cfg: dict, maintenant: dt.datetime,
                   confirmation_sha256: str, par: str = "artisan") -> None:
        """L'artisan propose un autre créneau (spec §3.5bis). La main passe au CLIENT.

        Le créneau précédent part dans l'historique : on doit pouvoir dire plus tard ce qui
        avait été proposé, et quand. Et l'échéance REPART de zéro — c'est maintenant le
        client qu'on attend, il ne peut pas hériter du temps déjà consommé par l'artisan.
        """
        manquants = [c for c in self.CHAMPS_CRENEAU if c not in nouveau_creneau]
        if manquants:
            raise ValueError(f"créneau incomplet, champs manquants : {manquants}")
        self._refuser_si_echu(maintenant)
        ancien = dict(self.creneau)
        self._transition(StatutRdv.REPROPOSE, maintenant, par)
        self.creneau = {c: nouveau_creneau.get(c) for c in self.CHAMPS_CRENEAU}
        self.expire_a = calculer_expiration(cfg, self.urgence, maintenant)
        self.confirmation_sha256 = confirmation_sha256
        self.historique[-1]["creneau_precedent"] = ancien

    def confirmer_par_client(self, jeton: str, maintenant: dt.datetime) -> None:
        """Le client confirme via le lien reçu par SMS. Le jeton EST l'authentification :
        il n'a pas de compte. D'où trois vérifications en dur, dans le domaine et pas dans
        l'API — comparaison à temps constant, échéance opposée, et usage unique."""
        import hashlib
        import secrets as _secrets
        if not self.confirmation_sha256:
            raise TransitionInterdite(
                f"RDV {self.id} : aucune confirmation client attendue")
        empreinte = hashlib.sha256((jeton or "").encode("utf-8")).hexdigest()
        if not _secrets.compare_digest(self.confirmation_sha256, empreinte):
            raise TransitionInterdite(f"RDV {self.id} : jeton de confirmation invalide")
        self._refuser_si_echu(maintenant)
        self._transition(StatutRdv.VALIDE, maintenant, "client")
        self.decide_a = maintenant
        self.confirmation_sha256 = None   # usage unique : le lien ne resservira pas

    def expirer(self, maintenant: dt.datetime, par: str = "systeme") -> None:
        if not self.est_echu(maintenant):
            raise TransitionInterdite(
                f"RDV {self.id} pas encore échu (expire_a={self.expire_a.isoformat()})")
        self._transition(StatutRdv.EXPIRE, maintenant, par)
        self.decide_a = maintenant

    # ---- persistance (le dépôt stocke des dicts, jamais l'instance vivante) ----
    HORODATAGES = ("expire_a", "cree_a", "notifie_a", "decide_a")

    def to_dict(self) -> dict:
        d = {"id": self.id, "lead_id": self.lead_id, "artisan_id": self.artisan_id,
             "creneau": dict(self.creneau), "duree_min": self.duree_min,
             "urgence": self.urgence, "statut": self.statut.value,
             "confirmation_sha256": self.confirmation_sha256,
             "historique": [dict(h) for h in self.historique]}
        for c in self.HORODATAGES:
            h = getattr(self, c)
            d[c] = h.isoformat() if h else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Rdv:
        horodatages = {c: dt.datetime.fromisoformat(d[c]) if d[c] else None
                       for c in cls.HORODATAGES}
        return cls(id=d["id"], lead_id=d["lead_id"], artisan_id=d["artisan_id"],
                   creneau=dict(d["creneau"]), duree_min=d["duree_min"],
                   urgence=d["urgence"], statut=StatutRdv(d["statut"]),
                   confirmation_sha256=d.get("confirmation_sha256"),
                   historique=[dict(h) for h in d["historique"]], **horodatages)
