"""Traduction entre la plateforme vocale (Vapi, forme OpenAI) et notre moteur.

**Ce module ne décide rien** — corollaire de la règle n°1 et de son pendant backend
(« l'API ne décide jamais »). Il lit une charge utile, en extrait quatre choses, et remet
du texte au format attendu. Les transitions restent dans `engine.py`, le RDV dans `rdv.py`.

Tout ce qui suit vient de la **récolte de l'étape 0** (`sonde_voix.py`, appels réels du
25/08), pas d'une documentation. Ce qui est écrit ici a été observé.

CE QUE VAPI ENVOIE, À CHAQUE TOUR
---------------------------------
- `call.id` : UUID **stable sur toute la durée de l'appel** — vérifié sur trois appels et
  leurs dix requêtes. C'est notre clé de conversation, et c'est un UUID valide, donc il
  entre tel quel dans la colonne `appel.id`. Rien à fabriquer.
- `messages` : **tout l'historique**, système compris — et ce message système est celui de
  l'assistant par défaut de Vapi (« You are Riley… »). On l'**ignore entièrement** : notre
  état vit dans le dépôt et notre prompt vient de notre moteur. Un prompt étranger qui
  déciderait quoi que ce soit serait une violation directe de la règle n°1.
- `stream: true` : une réponse d'un seul bloc reçoit 200 et **n'est jamais prononcée**.
- `metadata.assistantTurnInterrupted` : l'appelant a coupé l'agent (barge-in).

DEUX SURPRISES QUI ONT CHANGÉ LA CONCEPTION
-------------------------------------------
1. **Un appel web n'a AUCUN numéro appelé.** `call.type = "webCall"`, transport Daily,
   et pas un seul champ en `+33…` dans la charge utile. Or `/webhooks/appel` identifie
   l'artisan par le numéro composé. Pour le spike — qui se fait justement sans numéro
   français — il faut donc un autre chemin : `artisan_de_l_appel` prend le numéro appelé
   s'il existe (le cas de production), et retombe sinon sur un artisan désigné en
   configuration. Explicite, journalisé, et refusé si personne ne l'a désigné.

2. **Vapi rejoue le même tour.** Le 25/08 à 21:20, quatre requêtes en sept secondes ont
   porté le MÊME nombre de messages, pendant un barge-in. Si on traite chacune, le
   contrôleur avance de quatre états pour une seule phrase de l'appelant, et la
   conversation part de travers. D'où `est_un_rejeu` : Vapi envoyant tout l'historique, le
   nombre de messages `user` fait office de numéro de séquence, qu'on compare aux tours
   déjà inscrits dans notre transcript. Aucun stockage nouveau — l'état existant suffit.
"""
from __future__ import annotations

import datetime as dt
import json


# --------------------------------------------------------------- lecture de la charge
def identifiant_appel(corps: dict) -> str | None:
    """`call.id` : notre clé de conversation, stable sur tout l'appel."""
    appel = (corps or {}).get("call")
    if not isinstance(appel, dict):
        return None
    valeur = appel.get("id")
    return str(valeur) if valeur else None


def numero_appele(corps: dict) -> str | None:
    """Le numéro composé par l'appelant, quand il y en a un.

    Absent des appels web (`call.type == "webCall"`), qui sont le mode du spike. C'est la
    voie de production : elle identifiera l'artisan comme le fait déjà `/webhooks/appel`.
    """
    appel = (corps or {}).get("call")
    if not isinstance(appel, dict):
        return None
    numero = appel.get("phoneNumber")
    if isinstance(numero, dict) and numero.get("number"):
        return str(numero["number"])
    # certaines charges portent le numéro à plat
    return str(appel["phoneNumberId"]) if appel.get("phoneNumberId") else None


def messages_utilisateur(corps: dict) -> list[str]:
    """Les tours de l'APPELANT, dans l'ordre. Le message système et les tours de l'agent
    sont écartés ici même : ils n'ont aucun rôle chez nous."""
    messages = (corps or {}).get("messages")
    if not isinstance(messages, list):
        return []
    textes = []
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "user":
            contenu = m.get("content")
            if isinstance(contenu, str):
                textes.append(contenu)
    return textes


def interrompu(corps: dict) -> bool:
    """L'appelant a coupé l'agent au tour précédent (barge-in).

    Pas encore exploité par le moteur : consigné pour que l'information existe le jour où
    les phrases-tampons en auront besoin. Le repérer coûte deux lignes, le retrouver après
    coup coûterait un appel réel.
    """
    meta = (corps or {}).get("metadata")
    return bool(meta.get("assistantTurnInterrupted")) if isinstance(meta, dict) else False


def est_un_rejeu(corps: dict, tours_traites: int,
                 dernier_traite: str | None = None) -> bool:
    """Vrai si cette requête redit un tour que nous avons DÉJÀ traité.

    Vapi renvoyant tout l'historique, le nombre de messages `user` est un numéro de
    séquence : il augmente d'une unité par vraie prise de parole. S'il n'a pas dépassé ce
    que notre transcript contient déjà, c'est *a priori* une retransmission — mesuré le
    25/08, quatre requêtes identiques en sept secondes pendant un barge-in.

    ⚠️ MAIS LE COMPTAGE NE SUFFIT PAS, et ça a coûté un client en zone le 26/08.

    Quand l'appelant parle par-dessus l'accueil, la transcription de son tour arrive en
    DEUX temps : d'abord tronquée, puis complète. Les deux requêtes portent le même nombre
    de messages `user` — le comptage seul les confond, et la seconde était jetée. Ce qui a
    été jeté ce jour-là, c'est « J'habite sur Nogent-sur-Marne » : le client s'est entendu
    redemander sa commune trois fois, a répondu « Déjà dit », et l'appel s'est terminé sans
    RDV alors qu'il était en zone.

    Ce qui distingue les deux cas : un rejeu porte un texte IDENTIQUE, une transcription
    qui se précise s'ALLONGE. On compare donc aussi le dernier texte à celui qu'on a
    réellement traité.

    Sans `dernier_traite`, le comportement d'avant : le comptage seul.
    """
    textes = messages_utilisateur(corps)
    if len(textes) > tours_traites:
        return False
    if dernier_traite is not None and textes \
            and len(textes[-1].strip()) > len(dernier_traite.strip()):
        # même tour, transcription plus complète : à traiter, pas à jeter
        return False
    return True


def artisan_de_l_appel(corps: dict, registre, artisan_par_defaut: str | None):
    """(artisan, voie) — comment cet appel a été rattaché à un artisan.

    Deux voies, dans cet ordre : le numéro composé (production), puis un artisan désigné
    en configuration (spike sur appel web, où AUCUN numéro n'existe). La voie est rendue
    pour être journalisée : le jour où un appel se rattache au mauvais artisan, on doit
    lire par où il est passé, pas le déduire.
    """
    numero = numero_appele(corps)
    if numero:
        return registre.par_numero_relais(numero), "numero_appele"
    if artisan_par_defaut:
        return registre.artisan(artisan_par_defaut), "artisan_par_defaut"
    return None, None


# --------------------------------------------------------------- écriture de la réponse
def reponse_openai(texte: str, modele: str, instant: dt.datetime) -> dict:
    """Réponse `chat.completion`, d'un seul bloc.

    Vapi n'en veut pas (voir `evenements_sse`), mais d'autres plateformes si, et c'est la
    forme la plus lisible en diagnostic.
    """
    return {
        "id": "relais",
        "object": "chat.completion",
        "created": int(instant.timestamp()),
        "model": modele or "relais",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": texte},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def evenements_sse(texte: str, modele: str, instant: dt.datetime):
    """Rend le texte en `text/event-stream`, au format des morceaux OpenAI.

    ⚠️ LIRE AVANT DE MODIFIER — c'est ici que se joue la décision d'arbitrage n°4.

    Le texte arrive ENTIER et part en **un seul morceau de contenu**. Le flux est un mode
    de TRANSPORT, jamais un mode de génération. La raison n'est pas esthétique : tout ce
    qui sort de l'agent passe par `guards.check_output` (règle n°2), et des garde-fous ne
    peuvent rien contre un fragment de phrase. Un prix interdit, un « c'est confirmé »
    prématuré ou un diagnostic improvisé se reconnaissent sur la phrase complète ; émettre
    au fil des jetons reviendrait à prononcer d'abord et vérifier ensuite.

    Le découpage est donc interdit, et R40 le vérifie explicitement plutôt que de le
    confier au commentaire ci-dessus.

    Pourquoi du flux malgré tout : mesuré le 25/08 à 21:02, Vapi envoie `"stream": true`
    et une réponse d'un seul bloc lui vaut un 200 **et un silence**. Le flux n'est pas un
    choix de conception, c'est une exigence du transport — d'où la séparation stricte
    entre les deux.

    Conséquence pour la latence, à ne pas se cacher : émettre d'un bloc signifie que le
    premier son sort quand la phrase entière est prête. C'est le coût assumé de
    l'invariant, et c'est ce que les phrases-tampons pré-approuvées doivent couvrir — pas
    le streaming.
    """
    base = {"id": "relais", "object": "chat.completion.chunk",
            "created": int(instant.timestamp()), "model": modele or "relais"}
    # premier morceau : le rôle ET tout le texte. Certains clients exigent que `role`
    # figure dans le premier delta.
    yield "data: " + json.dumps(
        {**base, "choices": [{"index": 0,
                              "delta": {"role": "assistant", "content": texte},
                              "finish_reason": None}]},
        ensure_ascii=False) + "\n\n"
    # second morceau : la fin, delta vide. Séparer la fin du contenu évite qu'un client
    # qui s'arrête au premier `finish_reason` tronque la phrase.
    yield "data: " + json.dumps(
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ensure_ascii=False) + "\n\n"
    yield "data: [DONE]\n\n"
