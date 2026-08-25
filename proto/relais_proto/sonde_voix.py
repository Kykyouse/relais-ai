"""Sonde de l'étape 0 du chantier voix : entendre ce que la plateforme nous envoie.

Ce module ne fait PAS partie du produit. Il existe pour répondre à une question qu'aucune
documentation ne tranche de façon fiable et qu'un pari coûterait cher : **la charge utile
de la plateforme vocale porte-t-elle un identifiant d'appel ?**

C'est la question qui décide de l'adaptateur. L'API a été bâtie autour d'un principe
(cf. `api.py`) : *un tour d'appel = une requête, sans aucune session en mémoire*, l'état
étant relu du dépôt à chaque tour. Cela suppose une CLÉ stable pour retrouver cet état.
Si la plateforme en fournit une, l'adaptateur se réduit à une traduction de formats. Si
elle n'en fournit pas, il faut la fabriquer (dériver du couple appelant/appelé, ou tenir
une correspondance) — un montage nettement plus lourd, avec ses propres modes de panne.
Les deux sont trop différents pour être écrits sur une hypothèse.

**Premier fait d'étape 0, acquis le 25/08** : Vapi appelle `POST <url>/chat/completions`
et n'envoie **aucun en-tête personnalisé** — le contenu de son champ « API Key » part en
`Authorization: Bearer`. La sonde accepte donc le secret par les deux canaux. Reste à
confirmer que c'est bien le canal d'authentification retenu pour l'adaptateur.

La sonde répond en un appel réel, et donne trois choses au passage :
  1. la charge utile brute, conservée pour écrire l'adaptateur ensuite ;
  2. les identifiants CANDIDATS, extraits et mis en évidence (`identifiants_candidats`) ;
  3. un premier aller-retour audible de bout en bout — réseau, transcription, notre
     serveur, synthèse vocale — donc une mesure de latence AVANT tout adaptateur.

Éteinte par défaut : la route n'est même pas déclarée sans `RELAIS_SONDE_VOIX`. Une sonde
de diagnostic ne doit pas pouvoir se retrouver en production par oubli.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

# Ce que la sonde répond, mot pour mot. Une constante, pas une génération : la sonde n'a
# ni conversation, ni config d'artisan (le numéro appelé fait partie de ce qu'on découvre),
# donc rien à faire passer par `guards.check_output` à l'exécution. Le contrôle a lieu au
# test (R40), qui la soumet aux garde-fous : ni prix, ni « c'est confirmé », ni diagnostic,
# ni caractère non prononçable.
#
# L'annonce IA y figure quand même (règle n°5, AI Act art. 50). Elle vaut ici pour deux
# raisons : la sonde décroche un vrai téléphone, et sa phrase doit ressembler à l'ouverture
# réelle pour que la mesure de synthèse vocale porte sur quelque chose de représentatif.
PHRASE_SONDE = (
    "Bonjour, je suis un assistant vocal, et ceci est un test technique. "
    "Dites quelques mots pour que je vérifie la liaison, puis raccrochez.")

# Clés dont la valeur pourrait servir de clé de conversation. Volontairement large : à ce
# stade on veut voir des candidats et trancher à l'œil, pas rater le bon parce qu'il ne
# s'appelait pas comme prévu.
_INDICES = ("id", "call", "session", "conversation", "assistant", "customer",
            "number", "phone", "tel", "sid", "uuid", "ref")


def identifiants_candidats(charge, prefixe: str = "") -> dict:
    """Parcourt la charge utile et rend {chemin: valeur} pour tout scalaire dont la clé
    ressemble à un identifiant. Récursif, listes comprises.

    C'est LA sortie utile de l'étape 0 : un coup d'œil suffit alors à dire si un champ
    stable existe, plutôt que de relire une charge utile de plusieurs kilo-octets.
    """
    trouves: dict = {}
    if isinstance(charge, dict):
        for cle, valeur in charge.items():
            chemin = f"{prefixe}.{cle}" if prefixe else str(cle)
            if isinstance(valeur, (dict, list)):
                trouves.update(identifiants_candidats(valeur, chemin))
            elif valeur is not None and valeur != "":
                if any(i in str(cle).lower() for i in _INDICES):
                    trouves[chemin] = valeur
    elif isinstance(charge, list):
        for rang, element in enumerate(charge):
            trouves.update(identifiants_candidats(element, f"{prefixe}[{rang}]"))
    return trouves


def resume(charge: dict, entetes: dict, instant: dt.datetime,
           voie_auth: str | None = None) -> dict:
    """Ce qu'on garde d'une requête. Les en-têtes sont réduits à leurs NOMS : ils portent
    le secret partagé, et une sonde n'a aucune raison d'écrire un secret dans un fichier.
    Les noms suffisent à diagnostiquer une authentification qui échoue.

    `voie_auth` dit par QUEL en-tête le secret est arrivé. C'est un fait d'étape 0 au même
    titre que l'identifiant d'appel : le 25/08, le premier appel réel a montré que Vapi
    passe par `Authorization: Bearer` et n'envoie aucun en-tête personnalisé. Si la
    plateforme change de canal, on doit le LIRE dans le journal, pas le redécouvrir par un
    401 et un tunnel à remonter.
    """
    messages = charge.get("messages") if isinstance(charge, dict) else None
    return {
        "horodatage": instant.isoformat(),
        "voie_auth": voie_auth,
        "entetes": sorted(entetes),
        # `stream` en évidence : l'arbitrage a tranché qu'on ne diffuserait PAS une sortie
        # passée aux garde-fous. Savoir si la plateforme le demande quand même, et si elle
        # accepte une réponse d'un seul bloc, fait partie de ce qu'on vient mesurer.
        "stream_demande": bool(charge.get("stream")) if isinstance(charge, dict) else None,
        "modele_demande": charge.get("model") if isinstance(charge, dict) else None,
        "nb_messages": len(messages) if isinstance(messages, list) else None,
        "roles": [m.get("role") for m in messages
                  if isinstance(m, dict)] if isinstance(messages, list) else None,
        "identifiants_candidats": identifiants_candidats(charge),
        "cles_racine": sorted(charge) if isinstance(charge, dict) else None,
        "charge_utile": charge,
    }


def journaliser(entree: dict, chemin: pathlib.Path) -> None:
    """Écrit sur la sortie standard ET dans un fichier.

    Les deux, parce qu'ils servent à des moments différents : la console pour l'appel qu'on
    observe en direct, le fichier pour celui qu'on passe sans regarder l'écran. Le fichier
    contient une conversation : il n'a rien à faire dans le dépôt (voir `.gitignore`).
    """
    apercu = dict(entree)
    apercu.pop("charge_utile", None)
    print("\n" + "=" * 70)
    print("SONDE VOIX — requête reçue")
    print(json.dumps(apercu, ensure_ascii=False, indent=2))
    print("=" * 70 + "\n", flush=True)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False, default=str) + "\n")


def reponse_openai(texte: str, modele: str, instant: dt.datetime) -> dict:
    """Réponse au format `chat.completion`, d'un seul bloc.

    Pas de diffusion en flux : décision d'arbitrage n°4, et de toute façon la sonde n'a
    rien à diffuser. Une réponse d'un seul bloc acceptée par la plateforme est justement
    l'une des choses qu'on veut vérifier ici plutôt que de la croire sur parole.
    """
    return {
        "id": "sonde-relais",
        "object": "chat.completion",
        "created": int(instant.timestamp()),
        "model": modele or "relais-sonde",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": texte},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
