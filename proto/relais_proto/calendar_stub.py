"""Faux calendrier : génère des créneaux en appliquant les VRAIES règles agenda de la config.

En prod, ce module sera remplacé par la lecture free/busy Google/Outlook + le calendrier
tampon. L'interface (get_slots / hold_slot) est celle que l'agent appellera en prod.
"""
from __future__ import annotations

import datetime as dt

from . import temps

JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"]


def _heure_parlee(hhmm: str) -> str:
    """« 09:00 » → « 9 heures ». Ce qu'on DIT, pas ce qu'on écrit.

    La synthèse vocale lit « 08h » comme « zéro huit H » — entendu le 27/08. Elle ne
    devine pas qu'un zéro de cadrage ne se prononce pas.
    """
    h, m = hhmm.split(":")
    heures = int(h)
    mot = "heure" if heures == 1 else "heures"
    return f"{heures} {mot}" if m == "00" else f"{heures} {mot} {int(m)}"


def libelle_parle(d: dt.date, de: str, a: str, aujourd_hui: dt.date) -> str:
    """Le créneau tel qu'on le PRONONCE. Jumeau de `libelle_creneau`, pour l'oreille.

    Le 27/08, l'agent a dit à un appelant : « samedi 29 **barre oblique** 0 8 entre 0 9 h
    et 11 heures ». Ce n'était pas la transcription : c'était NOTRE libellé, « samedi
    29/08 entre 09h et 11h », lu littéralement par la synthèse. Comme pour le code postal
    (R58), **ce qu'on écrit est ce qu'elle dit**.

    Pourquoi un JUMEAU et non une réécriture de `libelle_creneau` : le libellé écrit part
    aussi dans les SMS, où « août » ferait basculer le message en UCS-2 — soixante-dix
    caractères au lieu de cent soixante (R23). Le mois en toutes lettres est bon pour
    l'oreille et coûteux pour l'écrit. Une seule SOURCE de données, deux rendus.
    """
    if d == aujourd_hui:
        jour = "aujourd'hui"
    elif d == aujourd_hui + dt.timedelta(days=1):
        jour = "demain"
    else:
        quantieme = "1er" if d.day == 1 else str(d.day)
        jour = f"{JOURS_FR[d.weekday()]} {quantieme} {MOIS_FR[d.month - 1]}"
    return f"{jour} entre {_heure_parlee(de)} et {_heure_parlee(a)}"


def libelle_creneau(d: dt.date, de: str, a: str, aujourd_hui: dt.date) -> str:
    """Le libellé prononcé à l'appelant ET écrit dans le SMS de reproposition. UNE seule
    source : si l'API le reconstruisait de son côté, l'agent et le SMS finiraient par ne
    plus dire la même chose du même créneau."""
    jour = ("aujourd'hui" if d == aujourd_hui else
            "demain" if d == aujourd_hui + dt.timedelta(days=1) else
            f"{JOURS_FR[d.weekday()]} {d.day:02d}/{d.month:02d}")
    return f"{jour} entre {de.replace(':00', 'h')} et {a.replace(':00', 'h')}"


class CalendarStub:
    def __init__(self, config: dict, now: dt.datetime | None = None,
                 urgences_consommees_aujourdhui: int = 0, jours_pleins: int = 0):
        self.config = config
        self.cfg = config["agenda"]
        # `now` est un INSTANT ; tout ce que ce module en tire (« aujourd'hui », « avant
        # 17 h », les libellés) est de l'heure de PENDULE. D'où les deux attributs : celui
        # qu'on sérialise et celui sur lequel on raisonne (cf. temps.py).
        self.now = temps.exige_instant(now) if now else temps.maintenant()
        self.urgences_consommees = urgences_consommees_aujourdhui
        self.jours_pleins = jours_pleins  # pour simuler T12 (calendrier saturé)
        self.holds: list[dict] = []

    @property
    def local(self) -> dt.datetime:
        """L'instant `now` à la pendule de l'artisan : la seule base valable pour dire
        « aujourd'hui », « demain » ou « avant 17 h »."""
        return temps.en_local(self.now, self.config)

    # ---- règles ----
    def _fenetres_du_jour(self, d: dt.date) -> list[tuple[str, str]]:
        wd = d.weekday()
        if wd <= 4:
            key = "lun-ven"
        elif wd == 5:
            key = "sam"
        else:
            key = "dim"
        return [(f["de"], f["a"]) for f in self.cfg["horaires_rdv"].get(key, [])]

    def _duree(self, prestation: str | None) -> int:
        d = self.cfg["durees_min"]
        return d.get(prestation or "", d["defaut"])

    # ---- interface agent ----
    @staticmethod
    def _moment_ok(h: int, moment: str | None) -> bool:
        if moment == "matin":
            return h < 12
        if moment == "apres_midi":
            return h >= 12
        return True

    def get_slots(self, prestation: str | None, urgent: bool, n: int = 2, skip: int = 0,
                  jours: set[int] | None = None, moment: str | None = None,
                  dates: set[str] | None = None) -> list[dict]:
        """Jusqu'à n fenêtres de 2 h (sautant les `skip` premières), en respectant les
        disponibilités exprimées : `jours` (weekdays 0–6), `moment` (matin/apres_midi) et
        `dates` (ISO, bornantes).

        `dates` existe parce qu'un jour RELATIF n'est pas un jour de la semaine. Le 27/08,
        un appelant a demandé « aujourd'hui » à 17 h 30 : plus rien ce jour-là, et la
        contrainte — résolue en « jeudi » — a proposé **jeudi 3 septembre**. Une semaine
        plus tard. « Aujourd'hui » ne peut pas vouloir dire jeudi prochain : c'est une
        DATE, et elle borne la recherche au lieu de la faire boucler."""
        n_total = n + skip
        slots: list[dict] = []
        local = self.local
        # Urgence : d'abord la fenêtre réservée du jour si dispo (et compatible)
        if urgent and self.cfg["urgences"]["acceptees"] \
                and self.urgences_consommees < self.cfg["urgences"]["max_par_jour"]:
            f = self.cfg["urgences"]["fenetres_reservees"][0]
            d = local.date()
            if d.weekday() <= 4 and local.time() < dt.time(17, 0) \
                    and (not jours or d.weekday() in jours) \
                    and (not dates or d.isoformat() in dates) \
                    and self._moment_ok(int(f["de"].split(":")[0]), moment):
                slots.append(self._mk(d, f["de"], f["a"], urgence=True))
        # Puis les jours suivants (en sautant les jours "pleins" simulés)
        day = local.date() + dt.timedelta(days=1 + self.jours_pleins)
        while len(slots) < n_total:
            # RACCOURCI, pas un garde : le garde-fou des 21 jours plus bas arrête déjà
            # la boucle, et le filtre par `dates` écarte de toute façon les jours suivants.
            # Celui-ci évite seulement de balayer trois semaines pour rien. Une mutation
            # l'a montré sans effet observable, et c'est normal — à distinguer du code mort,
            # qui, lui, prétend protéger quelque chose.
            if dates and day.isoformat() > max(dates):
                break
            if (not jours or day.weekday() in jours) \
                    and (not dates or day.isoformat() in dates):
                for de, a in self._fenetres_du_jour(day):
                    debut = dt.datetime.strptime(de, "%H:%M")
                    # fenêtres de 2 h : matin (ouverture) et après-midi (14h) si couvert
                    for h in (debut.hour, 14):
                        fin_h = h + 2
                        if h >= debut.hour and fin_h <= int(a.split(":")[0]) \
                                and self._moment_ok(h, moment):
                            slots.append(self._mk(day, f"{h:02d}:00", f"{fin_h:02d}:00"))
                            if len(slots) >= n_total:
                                return slots[skip:skip + n]
            day += dt.timedelta(days=1)
            if (day - local.date()).days > 21:
                break  # garde-fou (21 j : laisse leur chance aux jours rares type samedi)
        return slots[skip:skip + n]

    def _mk(self, d: dt.date, de: str, a: str, urgence: bool = False) -> dict:
        return {"date": d.isoformat(), "de": de, "a": a, "urgence": urgence,
                "label": libelle_creneau(d, de, a, self.local.date()),
                # le jumeau parlé : c'est lui que l'agent prononce (R66)
                "label_parle": libelle_parle(d, de, a, self.local.date())}

    # ---- sérialisation (l'état d'appel doit survivre au process : cf. Conversation.to_dict) ----
    def to_dict(self) -> dict:
        return {"now": self.now.isoformat(),
                "urgences_consommees": self.urgences_consommees,
                "jours_pleins": self.jours_pleins,
                "holds": [dict(h) for h in self.holds]}

    @classmethod
    def from_dict(cls, data: dict, config: dict) -> CalendarStub:
        # `now` est RECHARGÉ, jamais relu à l'horloge : sinon les libellés déjà
        # prononcés ("demain", "samedi 29/08") changeraient de sens d'un tour à l'autre.
        cal = cls(config, now=temps.depuis_iso(data["now"], config),
                  urgences_consommees_aujourdhui=data["urgences_consommees"],
                  jours_pleins=data["jours_pleins"])
        cal.holds = [dict(h) for h in data["holds"]]
        return cal

    def hold_slot(self, slot: dict, prestation: str | None) -> dict:
        """Bloque le créneau dans le calendrier tampon (statut : en attente de validation)."""
        hold = {**slot, "duree_min": self._duree(prestation),
                "statut": "en_attente_validation"}
        self.holds.append(hold)
        if slot.get("urgence"):
            self.urgences_consommees += 1
        return hold
