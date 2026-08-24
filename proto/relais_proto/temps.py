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
