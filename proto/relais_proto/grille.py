"""Placer les événements d'une semaine sur une grille horaire. Pur, sans état.

Séparé de `pages.py` parce que ce n'est pas du HTML : c'est le calcul qui décide OÙ
tombe chaque bloc. Le garder à part permet de l'éprouver sans rendre une page — et
c'est ce calcul qui porte la lisibilité, pas le balisage.
"""
from __future__ import annotations

import datetime as dt


# ══════════════════════════════════════════ LA GRILLE HORAIRE DE L'AGENDA (29/10)
#
# Geoffrey : « un rendez-vous à 17 h ne peut pas être sur la même ligne que celui de 8 h
# du jour d'après, c'est illisible ». Il avait raison et le défaut était structurel : la
# semaine n'était pas un calendrier mais **six listes côte à côte**. Les événements s'y
# empilaient dans l'ordre, donc rien n'était aligné sur l'heure. La maquette v5 a la même
# faiblesse — c'est donc un pas au-delà d'elle, pas un rattrapage.
#
# L'AXE VERTICAL DEVIENT L'HEURE. Une rangée par demi-heure, et chaque événement posé sur
# `grid-row: début / fin` : un RDV de 17 h est physiquement sous celui de 8 h, et sa
# HAUTEUR dit sa durée. Tout en CSS — pas de JavaScript (écart assumé n°2).
#
# L'AMPLITUDE VIENT DE LA CONFIG, jamais d'un réglage en dur : le minimum et le maximum
# des `horaires_rdv` de la semaine, ÉLARGIS si un événement déborde. Un bloc perso posé à
# 7 h doit se voir ; une grille qui s'arrête à l'heure d'ouverture le ferait disparaître,
# et un agenda qui cache un engagement est pire qu'un agenda absent (c'est la raison
# d'être de T15).
PAS_MINUTES = 30


def _en_minutes(hhmm: str, defaut: int = 0) -> int:
    try:
        h, m = (int(x) for x in str(hhmm).split(":")[:2])
        return h * 60 + m
    except (ValueError, AttributeError):
        return defaut


def _plages_ouvrees(cfg: dict, jour) -> list[tuple[int, int]]:
    """Les heures ouvrées de CE jour, en minutes. Vide = journée fermée."""
    horaires = ((cfg.get("agenda") or {}).get("horaires_rdv") or {})
    cle = "dim" if jour.weekday() == 6 else ("sam" if jour.weekday() == 5 else "lun-ven")
    return [(_en_minutes(p.get("de"), 0), _en_minutes(p.get("a"), 0))
            for p in (horaires.get(cle) or [])]


def amplitude_semaine(cfg: dict, jours: list) -> tuple[int, int]:
    """(début, fin) en minutes : ce que la grille doit couvrir pour ne RIEN cacher.

    Les heures ouvrées donnent le cadre, les événements l'élargissent. Arrondi au pas
    inférieur/supérieur pour que les rangées tombent juste.
    """
    bornes = []
    for j in jours:
        for de, a in _plages_ouvrees(cfg, dt.date.fromisoformat(j["iso"])):
            bornes += [de, a]
        for e in j["evenements"]:
            bornes += [_en_minutes(e.get("de")), _en_minutes(e.get("a"))]
    bornes = [b for b in bornes if b > 0]
    if not bornes:
        bornes = [8 * 60, 18 * 60]          # une semaine vide reste une journée lisible
    debut = (min(bornes) // PAS_MINUTES) * PAS_MINUTES
    fin = -(-max(bornes) // PAS_MINUTES) * PAS_MINUTES
    return debut, max(fin, debut + PAS_MINUTES * 2)


def poser_sur_la_grille(evenements: list[dict], debut: int, fin: int) -> int:
    """Donne à chaque événement sa rangée et sa PISTE. Rend le nombre de pistes.

    CÔTE À CÔTE EN CAS DE CONFLIT, choix de Geoffrey, et c'est le bon : deux blocs
    superposés diraient « il y a quelque chose », deux blocs côte à côte disent « il y a
    DEUX choses en même temps » — c'est l'information qui compte, puisque c'est elle qui
    appelle une décision.

    L'affectation est celle d'un agenda classique : on trie par début, et chaque
    événement prend la première piste libre à cette heure-là.
    """
    fins = []                               # fin de la dernière réservation, par piste
    for e in sorted(evenements, key=lambda x: (_en_minutes(x.get("de")),
                                               _en_minutes(x.get("a")))):
        d = max(debut, min(_en_minutes(e.get("de")), fin - PAS_MINUTES))
        f = min(fin, max(_en_minutes(e.get("a")), d + PAS_MINUTES))
        piste = next((i for i, libre in enumerate(fins) if libre <= d), len(fins))
        if piste == len(fins):
            fins.append(f)
        else:
            fins[piste] = f
        e["ligne_debut"] = (d - debut) // PAS_MINUTES + 1
        e["ligne_fin"] = (f - debut) // PAS_MINUTES + 1
        e["piste"] = piste
        e["minutes"] = (d, f)

    # CE QUI NE CHEVAUCHE RIEN PREND TOUTE LA LARGEUR. Sans ça, un rendez-vous isolé à
    # 17 h se retrouvait à demi-largeur parce qu'une autre heure de SA JOURNÉE avait
    # deux pistes — il payait un conflit auquel il ne participe pas, et la colonne
    # donnait à lire un encombrement qui n'existait pas.
    # DEUX PASSES, et c'est nécessaire : supprimer `minutes` dans la boucle qui lit
    # celui des autres fait tomber le second tour sur une clé absente.
    for e in evenements:
        d, f = e["minutes"]
        e["etendu"] = not any(
            autre is not e and autre["minutes"][0] < f and d < autre["minutes"][1]
            for autre in evenements)
    for e in evenements:
        e.pop("minutes", None)
    return max(1, len(fins))


def heures_fermees(cfg: dict, jour, debut: int, fin: int) -> list[tuple[int, int]]:
    """Les tranches HORS heures ouvrées, en rangées de grille — à hachurer.

    Ce qui est fermé doit se VOIR : sans ça, une grille qui va de 7 h à 20 h laisse
    croire que tout y est vendable, alors que l'agent ne propose jamais ces heures-là.
    """
    plages = sorted(_plages_ouvrees(cfg, jour))
    fermees, curseur = [], debut
    for de, a in plages:
        if de > curseur:
            fermees.append((curseur, min(de, fin)))
        curseur = max(curseur, a)
    if curseur < fin:
        fermees.append((curseur, fin))
    return [((d - debut) // PAS_MINUTES + 1, (f - debut) // PAS_MINUTES + 1)
            for d, f in fermees if f > d]
