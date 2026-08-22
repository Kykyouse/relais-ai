"""Faux calendrier : génère des créneaux en appliquant les VRAIES règles agenda de la config.

En prod, ce module sera remplacé par la lecture free/busy Google/Outlook + le calendrier
tampon. L'interface (get_slots / hold_slot) est celle que l'agent appellera en prod.
"""
from __future__ import annotations

import datetime as dt

JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


class CalendarStub:
    def __init__(self, config: dict, now: dt.datetime | None = None,
                 urgences_consommees_aujourdhui: int = 0, jours_pleins: int = 0):
        self.cfg = config["agenda"]
        self.now = now or dt.datetime.now()
        self.urgences_consommees = urgences_consommees_aujourdhui
        self.jours_pleins = jours_pleins  # pour simuler T12 (calendrier saturé)
        self.holds: list[dict] = []

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
    def get_slots(self, prestation: str | None, urgent: bool, n: int = 2,
                  skip: int = 0) -> list[dict]:
        """Retourne jusqu'à n fenêtres de 2 h (en sautant les `skip` premières)."""
        n_total = n + skip
        slots: list[dict] = []
        # Urgence : d'abord la fenêtre réservée du jour si dispo
        if urgent and self.cfg["urgences"]["acceptees"] \
                and self.urgences_consommees < self.cfg["urgences"]["max_par_jour"]:
            f = self.cfg["urgences"]["fenetres_reservees"][0]
            d = self.now.date()
            if d.weekday() <= 4 and self.now.time() < dt.time(17, 0):
                slots.append(self._mk(d, f["de"], f["a"], urgence=True))
        # Puis les jours suivants (en sautant les jours "pleins" simulés)
        day = self.now.date() + dt.timedelta(days=1 + self.jours_pleins)
        while len(slots) < n_total:
            for de, a in self._fenetres_du_jour(day):
                debut = dt.datetime.strptime(de, "%H:%M")
                # fenêtres de 2 h : matin (ouverture) et après-midi (14h) si couvert
                for h in (debut.hour, 14):
                    fin_h = h + 2
                    if h >= debut.hour and fin_h <= int(a.split(":")[0]):
                        slots.append(self._mk(day, f"{h:02d}:00", f"{fin_h:02d}:00"))
                        if len(slots) >= n_total:
                            return slots[skip:skip + n]
            day += dt.timedelta(days=1)
            if (day - self.now.date()).days > 14:
                break  # garde-fou
        return slots[skip:skip + n]

    def _mk(self, d: dt.date, de: str, a: str, urgence: bool = False) -> dict:
        label_jour = "aujourd'hui" if d == self.now.date() else (
            "demain" if d == self.now.date() + dt.timedelta(days=1)
            else f"{JOURS_FR[d.weekday()]} {d.day:02d}/{d.month:02d}")
        return {"date": d.isoformat(), "de": de, "a": a, "urgence": urgence,
                "label": f"{label_jour} entre {de.replace(':00', 'h')} et {a.replace(':00', 'h')}"}

    def hold_slot(self, slot: dict, prestation: str | None) -> dict:
        """Bloque le créneau dans le calendrier tampon (statut : en attente de validation)."""
        hold = {**slot, "duree_min": self._duree(prestation),
                "statut": "en_attente_validation"}
        self.holds.append(hold)
        if slot.get("urgence"):
            self.urgences_consommees += 1
        return hold
