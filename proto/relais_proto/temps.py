"""Le temps dans Relais. **Deux natures d'horodatage, qui ne se mélangent jamais.**

* Un **INSTANT** — échéance de validation, création d'un RDV, envoi d'un SMS, expiration
  d'une session — est un point sur la ligne du temps. Il vit en **UTC**, on lui ajoute des
  durées en heures RÉELLES, et deux instants se comparent sans ambiguïté.

* Une **HEURE DE PENDULE** — la plage de silence 21h–08h, les heures ouvrées, « demain
  entre 08h et 10h » — n'a de sens que dans le fuseau de l'artisan. Elle se calcule donc
  APRÈS conversion, et jamais sur l'instant brut.

Pourquoi cette séparation, et pourquoi elle n'est pas un détail d'implémentation (dette
n°1 du journal, tranchée le 24/08) : le domaine manipulait des datetime naïfs en heure
locale française, et le schéma des colonnes `timestamp` sans fuseau. Deux pannes en
découlaient, distinctes :

  1. **Une durée fausse.** `depuis + timedelta(hours=24)` en heure locale vaut 23 h ou
     25 h réelles autour d'un changement d'heure. L'artisan à qui on promet 24 heures en
     perdait une, la nuit du dernier dimanche de mars.
  2. **Un ordre ambigu**, pire que la première. Le dernier dimanche d'octobre, 02h00–02h59
     arrive DEUX FOIS à la pendule. `maintenant >= expire_a` pouvait donc être vrai, puis
     redevenir faux — un RDV « dé-expiré », en contradiction frontale avec l'invariant
     n°1 de `rdv.py` (aucune sortie d'un état terminal) et avec la décision verrouillée
     « l'échéance fait foi, pas le passage du worker ».

Le choix du **tz-aware plutôt que d'une convention « naïf = UTC »** est délibéré : Python
REFUSE de comparer un naïf et un aware. Un chemin de conversion oublié lève donc une
`TypeError` bruyante, en test avant la production, au lieu de dériver silencieusement
d'une heure. La règle n°2 de `rdv.py` (l'horloge est toujours un paramètre) rend cette
protection efficace : il n'y a que deux points d'entrée réels, `api.py` et `worker.py`.

**Arithmétique : toujours sur des instants UTC, jamais sur un datetime aware en heure
locale.** `paris_aware + timedelta(hours=24)` ajoute 24 h à la PENDULE en conservant le
fuseau — soit 23 h réelles un jour de basculement. C'est exactement le piège d'origine,
reproduit avec un objet aware. Tout ce qui circule dans le domaine est donc en UTC.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

UTC = dt.UTC

# Le fuseau est une propriété de l'ARTISAN, pas une constante du produit : `cfg["fuseau"]`.
# La V1 vise la France métropolitaine, mais écrire « Europe/Paris » en dur dans le calcul
# rendrait le jour où un artisan est à La Réunion indiscernable d'un bug.
FUSEAU_DEFAUT = "Europe/Paris"


def maintenant() -> dt.datetime:
    """L'instant présent. **Le seul point où l'horloge système entre dans le code.**"""
    return dt.datetime.now(UTC)


def fuseau(cfg: dict | None = None) -> ZoneInfo:
    """Le fuseau de CET artisan, d'après sa config."""
    return ZoneInfo((cfg or {}).get("fuseau") or FUSEAU_DEFAUT)


def exige_instant(valeur: dt.datetime, nom: str = "horodatage") -> dt.datetime:
    """Contrôle de frontière : un instant naïf n'entre pas dans le domaine.

    Levée volontairement franche plutôt qu'une interprétation charitable : deviner que le
    naïf est « sans doute de l'heure de Paris » ferait exactement ce que cette refonte
    supprime — une conversion implicite qui se trompe d'une heure deux fois par an.
    """
    if valeur.tzinfo is None or valeur.utcoffset() is None:
        raise ValueError(
            f"{nom} naïf ({valeur.isoformat()}) : le domaine n'accepte que des instants "
            f"datés d'un fuseau. Utilise temps.maintenant() ou temps.instant_de().")
    return valeur.astimezone(UTC)


def en_local(instant: dt.datetime, cfg: dict | None = None) -> dt.datetime:
    """L'instant vu à la pendule de l'artisan. À utiliser dès qu'une RÈGLE parle d'heures
    (plage de silence, heures ouvrées) ou qu'un texte s'adresse à un humain."""
    return exige_instant(instant).astimezone(fuseau(cfg))


def instant_de(jour: dt.date, heure: dt.time | str,
               cfg: dict | None = None) -> dt.datetime:
    """L'instant (UTC) où la pendule de l'artisan affichera `jour` à `heure`.

    Le chemin inverse de `en_local`, et le seul autorisé pour reconstruire un instant
    depuis une heure écrite dans la config (« 08:00 », « 21:00 »).

    Les deux jours difficiles de l'année :

    * **heure inexistante** (dernier dimanche de mars, 02h00 → 03h00) : la pendule saute,
      `astimezone` reporte le résultat APRÈS le saut. Une échéance placée dans le trou
      tombe donc à 03 h — jamais avant l'heure demandée, ce qui est le sens voulu.
    * **heure ambiguë** (dernier dimanche d'octobre, 02h00 arrive deux fois) : on prend la
      PREMIÈRE occurrence (`fold=0`). Une fin de plage de silence ou une ouverture de
      fenêtre ouvrée s'applique ainsi au plus tôt : on ne fait pas attendre un client une
      heure de plus au motif que la pendule bégaie.
    """
    if isinstance(heure, str):
        h, m = (int(x) for x in heure.split(":"))
        heure = dt.time(h, m)
    return dt.datetime.combine(jour, heure, tzinfo=fuseau(cfg)).astimezone(UTC)


def depuis_iso(texte: str, cfg: dict | None = None) -> dt.datetime:
    """Relit un horodatage sérialisé (blob `etat_conversation`, dépôt mémoire, JSON d'API).

    **Compatibilité avec l'avant-migration 007** : les valeurs écrites quand le domaine
    était naïf portent une heure locale française sans fuseau. Les relire comme de l'UTC
    décalerait tout de deux heures en silence — précisément l'erreur contre laquelle
    `exige_instant` protège ailleurs. Ici on ne peut pas refuser : la donnée existe déjà
    et il faut bien la lire. On l'interprète donc dans le fuseau de l'artisan, ce qui est
    ce qu'elle voulait dire.

    Ce repli pourra disparaître quand plus aucun blob d'avant le 24/08/2026 ne circulera.
    """
    valeur = dt.datetime.fromisoformat(texte)
    if valeur.tzinfo is None:
        valeur = valeur.replace(tzinfo=fuseau(cfg))
    return valeur.astimezone(UTC)


# ══════════════════════════════════════════ LES PÉRIODES D'ÉCRAN (29/10)
#
# Un écran qui agrège demande « sur quoi ? ». La maquette v5 répond par quatre
# raccourcis — Ce mois, 3 mois, 12 mois, Tout — et une plage libre « du … au … », en
# disant que **les raccourcis ne sont que des préréglages** : ils se résolvent dans la
# même paire de dates que la plage libre, et il n'y a donc qu'un seul chemin de calcul.
#
# CE SONT DES DATES DE PENDULE, et c'est la raison d'être de ce code ici plutôt que
# dans `api.py`. « Ce mois » se lit dans le calendrier de l'artisan : pour quelqu'un à
# La Réunion, le 1er octobre ne commence pas au même instant que pour quelqu'un à Paris.
# Toute la règle n°7 tient dans cette phrase — on borne en dates locales, et c'est à
# l'appelant de convertir ses INSTANTS (`en_local(...).date()`) avant de comparer.
# `Rdv.creneau["date"]` est déjà une date de pendule : il se compare directement.
PERIODES = {
    "mois": "Ce mois",
    "3mois": "3 mois",
    "12mois": "12 mois",
    "tout": "Tout",
}

# LE DÉFAUT EST « TOUT », ET PAS « CE MOIS » comme dans la maquette. Décidé le 29/10
# parce que T18 l'a attrapé : sa pendule avance de 30 jours entre le chantier et la
# consultation, et le CA déclaré disparaissait de l'écran.
#
# Ce n'était pas un artefact de test, c'est le cas NORMAL. Un chantier se déclare après
# coup — on borne sur la date du CRÉNEAU, pas sur celle de la déclaration — donc tout
# chantier de fin de mois se déclare au mois suivant. Avec « Ce mois » par défaut,
# l'artisan qui vient de saisir « 1 480 € » rouvre l'écran et lit **0 €**. Sur la seule
# page qui répond à « qu'est-ce que ça me rapporte ? », et juste après le geste qu'elle
# existe pour encourager.
#
# La maquette a raison pour un tableau de bord dont les données sont toujours récentes ;
# les siennes sont fictives et datées d'aujourd'hui. Les raccourcis restent à un clic.
DEFAUT = "tout"

# Les bornes de « Tout ». Mêmes valeurs que celles qu'`api.py` passait en dur avant
# d'avoir des périodes : « depuis toujours » reste une fenêtre, pas un cas particulier
# — sinon chaque appelant devrait porter une branche « si pas de période ».
TOUT_DEBUT = "2000-01-01"
TOUT_FIN = "2100-12-31"


def _fin_de_mois(jour: dt.date) -> dt.date:
    suivant = jour.replace(day=28) + dt.timedelta(days=4)
    return suivant - dt.timedelta(days=suivant.day)


def _recul_mois(jour: dt.date, mois: int) -> dt.date:
    """Le 1er du mois, `mois` mois plus tôt. Jamais d'arithmétique sur 30 jours :
    « 3 mois » dans un tableau de bord désigne trois mois CIVILS, pas 90 jours."""
    total = (jour.year * 12 + jour.month - 1) - mois
    return dt.date(total // 12, total % 12 + 1, 1)


def _libelle_date(jour: dt.date) -> str:
    from .calendar_stub import MOIS_FR
    return f"{jour.day} {MOIS_FR[jour.month - 1]} {jour.year}"


def fenetre(aujourdhui: dt.date, preset: str = "", du: str = "",
            au: str = "") -> dict:
    """Résout une période d'écran en deux dates de pendule, bornes INCLUSES.

    Rend `{du, au, preset, libelle, erreur}`. `preset` est `None` quand la plage a été
    saisie à la main — c'est ce qui permet à l'écran de n'allumer aucun raccourci.

    `erreur` n'est pas une exception : une date mal tapée dans une barre d'outils ne
    doit pas rendre l'écran inatteignable. On retombe sur le défaut ET on dit pourquoi
    — un tableau de bord qui se réaffiche silencieusement sur une autre période que
    celle demandée est pire qu'un message, parce qu'on lit ses chiffres en croyant
    autre chose.
    """
    if du or au:
        try:
            debut = dt.date.fromisoformat(du)
            fin = dt.date.fromisoformat(au)
        except ValueError:
            return {**fenetre(aujourdhui, DEFAUT),
                    "erreur": "Dates illisibles — période remise au défaut."}
        if debut > fin:
            # Inverser en silence serait une politesse mensongère : l'écran afficherait
            # une période que personne n'a demandée, avec l'air d'avoir obéi.
            return {**fenetre(aujourdhui, DEFAUT),
                    "erreur": "La date de début est après celle de fin — période "
                              "remise au défaut."}
        return {"du": debut.isoformat(), "au": fin.isoformat(), "preset": None,
                "libelle": f"du {_libelle_date(debut)} au {_libelle_date(fin)}",
                "erreur": ""}

    preset = preset if preset in PERIODES else DEFAUT
    if preset == "tout":
        return {"du": TOUT_DEBUT, "au": TOUT_FIN, "preset": "tout",
                "libelle": "depuis le début", "erreur": ""}

    mois_en_arriere = {"mois": 0, "3mois": 2, "12mois": 11}[preset]
    debut = _recul_mois(aujourdhui, mois_en_arriere)
    fin = _fin_de_mois(aujourdhui)
    libelle = (f"du {_libelle_date(debut)} au {_libelle_date(fin)}"
               if mois_en_arriere else f"{_libelle_date(debut).split(' ', 1)[1]}")
    return {"du": debut.isoformat(), "au": fin.isoformat(), "preset": preset,
            "libelle": libelle, "erreur": ""}


def dans_fenetre(instant: dt.datetime | None, fen: dict,
                 cfg: dict | None = None) -> bool:
    """Un INSTANT tombe-t-il dans une fenêtre de dates locales ?

    Le pont entre les deux natures d'horodatage, et le seul endroit où il se fait pour
    les écrans : `debut_a` d'un appel est un instant UTC, la fenêtre est un calendrier.
    Comparer l'un à l'autre sans convertir décale la frontière de deux heures, c'est-
    à-dire range les appels du soir dans le mauvais mois une fois sur douze.
    """
    if instant is None:
        return False
    return fen["du"] <= en_local(instant, cfg).date().isoformat() <= fen["au"]
