"""Sonde des disponibilités : ce que l'appelant dit du TEMPS, et ce qu'on en fait.

Ce module ne fait **PAS** partie du produit. Il existe pour répondre à une question qu'on
ne peut pas trancher depuis un bureau : **quelles tournures de temps les gens emploient-ils
vraiment au téléphone, et lesquelles nous échappent ?**

Le 27/08, en sondant 21 tournures inventées, trois se sont révélées **inversées** (« pas le
samedi » proposait samedi — R68) et treize simplement **ignorées** : « maintenant », « au
plus vite », « dans la journée », « la semaine prochaine », « en soirée »… L'inversion est
corrigée. Restent les ignorées, et avec elles une décision d'architecture : allonger
indéfiniment une liste de mots-clés dans le contrôleur ne converge pas — le français en a
trop, et chaque ajout est une occasion de refaire l'inversion qu'on vient de corriger. La
seule réponse qui tienne à l'échelle est de faire **classer** le texte libre par le modèle
vers un vocabulaire FERMÉ que le contrôleur possède (comme `prestation` déjà). Le LLM ne
déciderait toujours rien : il rangerait dans des cases qu'on a écrites.

Mais on ne peut pas écrire ces cases de mémoire. Les seize défauts R42→R68 sont tous venus
d'appels RÉELS ou de personas tirés d'appels réels, pendant que les tournures inventées se
sont trompées plusieurs fois de cible. Cette sonde sert donc à une chose : que le prochain
lot d'appels réels rende la **liste des tournures effectivement prononcées**, chacune avec
ce que le contrôleur en a fait. Le vocabulaire fermé s'écrira sur ces données.

**Elle enregistre CHAQUE tour du client, sans filtrer.** C'est délibéré et c'est le point
important du module : filtrer sur des mots de temps connus reproduirait exactement la
cécité qu'on mesure — une tournure absente de la liste ne serait pas enregistrée, et on
conclurait que personne ne la dit. Un fichier bavard est le prix d'une mesure non biaisée.

Trois champs et leur raison d'être, car c'est là que se joue la question « le modèle est-il
trop bête, ou est-ce nous ? » :

- `dit`   — la phrase du client, telle que la transcription nous la rend ;
- `brut`  — ce que l'EXTRACTEUR (le LLM) en a retenu dans le slot `disponibilites` ;
- `lecture` — ce que le CONTRÔLEUR en a tiré (`_contraintes_dispo`, du Python pur).

Une tournure présente dans `dit`, absente de `brut` : l'extraction l'a laissée tomber.
Présente dans `brut`, sans effet dans `lecture` : c'est notre code qui est sourd. Les deux
se corrigent à des endroits différents, et rien d'autre ne permet de les distinguer.

Éteinte par défaut, comme `sonde_voix` : sans `RELAIS_SONDE_DISPO`, aucun fichier n'est
ouvert et rien n'est appelé. Le fichier contient des conversations réelles — il n'a rien à
faire dans le dépôt (`.gitignore` couvre `*.sonde.jsonl`).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib


def _jsonifiable(valeur):
    """Les contraintes portent des ensembles ; JSON n'en connaît pas. Triés plutôt que
    convertis à la va-vite : deux relectures du même appel doivent donner le même texte."""
    if isinstance(valeur, (set, frozenset)):
        return sorted(valeur)
    return valeur


def lecture(convo) -> dict | None:
    """Ce qu'on garde d'un tour, ou None s'il n'y a rien à observer (personne n'a parlé).

    `convo` est la conversation APRÈS traitement du tour. On rappelle `_contraintes_dispo`
    au lieu de demander au moteur de nous tendre son résultat : la sonde reste ainsi
    entièrement hors du chemin produit, et l'état de la conversation — qui voyage
    sérialisé d'un tour à l'autre — n'a pas à porter un champ de diagnostic.
    """
    dit = next((txt for role, txt in reversed(convo.transcript) if role == "client"), None)
    brut = (convo.slots.get("disponibilites") or "").strip() or None
    if dit is None and brut is None:
        return None

    contraintes, erreur = None, None
    try:
        contraintes = {cle: _jsonifiable(val)
                       for cle, val in convo._contraintes_dispo().items()}
    except Exception as exc:                       # noqa: BLE001 — cf. `entendu` plus bas
        # Une sonde qui laisse remonter une exception raccroche au nez d'un client. On
        # garde la trace de la panne et l'appel continue : c'est le seul arbitrage
        # acceptable pour un outil de diagnostic branché sur un appel en cours.
        erreur = repr(exc)

    return {
        "horodatage": dt.datetime.now(dt.UTC).isoformat(),
        "etat": getattr(convo.state, "name", str(convo.state)),
        "tour": sum(1 for role, _ in convo.transcript if role == "client"),
        "dit": dit,
        "brut": brut,
        "lecture": contraintes,
        # « entendu » = le contrôleur a tiré QUELQUE CHOSE de ce que l'appelant a dit.
        # Faux avec un `brut` rempli, c'est une tournure qui nous échappe — la ligne
        # exacte qu'on vient chercher dans ce fichier.
        "entendu": bool(contraintes and any(v for v in contraintes.values())),
        "erreur": erreur,
        # ce que l'appelant a effectivement reçu : une lecture juste mal appliquée se voit
        # ici et nulle part ailleurs
        "propose": [c.get("label_parle") or c.get("label")
                    for c in (getattr(convo, "_proposes", None) or [])],
    }


def journaliser(entree: dict, chemin: pathlib.Path) -> None:
    """Une ligne JSON par tour, plus un résumé d'une ligne sur la console.

    Le résumé tient sur une ligne (et non le pavé de `sonde_voix`) parce que celui-ci part
    à CHAQUE tour : un pavé rendrait la console illisible pendant qu'on écoute l'appel.
    """
    if entree.get("erreur"):
        verdict = f"PANNE {entree['erreur'][:40]}"
    elif entree.get("entendu"):
        lu = {c: v for c, v in (entree.get("lecture") or {}).items() if v}
        verdict = " ".join(f"{c}={v}" for c, v in lu.items())
    elif entree.get("brut"):
        verdict = "SOURD"                       # il a dit quelque chose, on n'en fait rien
    else:
        verdict = "—"
    print(f"SONDE DISPO t{entree.get('tour')} "
          f"« {(entree.get('dit') or '')[:60]} » → {verdict}", flush=True)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False, default=str) + "\n")
