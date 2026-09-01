"""Le MENU d'actions que le contrôleur expose au modèle, état par état.

**Pourquoi ce module existe.** Pendant trois sessions, chaque échec d'interprétation a été
corrigé de la même façon : une liste de mots-clés de plus dans `engine.py`. R68 (« pas le
samedi » lu comme une préférence POUR le samedi), R70, puis R71 (« le plus vite possible »
qui éloignait le rendez-vous d'un jour avant de faire raccrocher). Trois fois la mauvaise
polarité, trois fois un échec silencieux — rien ne casse, l'agent répond avec aplomb, et
seul un appel réel le révèle.

Geoffrey a tranché le 01/09, et il a raison : **une liste de mots-clés ne couvrira jamais
le français.** « Le plus vite possible », « dès que vous pouvez », « peu importe, le
premier », « avant ma pause déjeuner », « tant que c'est cette semaine » — c'est sans fin,
et chaque ajout est une occasion de refaire l'inversion qu'on vient de corriger.

Ce qui a été mesuré ce jour-là et qui décide de la forme du remède : l'extracteur
**recevait déjà** les propositions en cours et la dernière réplique de l'agent. Il avait
tout pour comprendre. Ce qui lui manquait était son CONTRAT :

    creneau_choisi: 1 ou 2 si l'appelant choisit une des propositions
    veut_plus_tot:  true si l'appelant demande un créneau PLUS TÔT que les propositions

« Le plus vite possible » ne désigne ni heure, ni jour, ni rang, et ne demande pas *plus
tôt que* les propositions. Le modèle s'est comporté correctement au regard de ce qu'on lui
demandait. Il n'y avait ni consigne d'interpréter un sens, ni case pour « je ne suis pas
sûr ». **Le défaut était dans le contrat, pas dans le modèle.**

**Le déplacement, et sa limite exacte.** Le modèle ne choisit plus des mots, il choisit une
ACTION dans un menu FERMÉ que le contrôleur a écrit. Le contrôleur valide ensuite : l'action
existe-t-elle dans cet état, le rang désigne-t-il une proposition réelle, les invariants
tiennent-ils. Les mille façons de dire « le premier » s'effondrent sur cinq actions, et le
contrôleur n'a plus jamais à être modifié pour une tournure de phrase.

La règle n°1 n'est pas assouplie, elle est PRÉCISÉE : le LLM ne décide toujours rien de ce
qui engage — pas un prix, pas une date, pas une promesse, pas une transition. Il dit ce
qu'il a COMPRIS, dans un vocabulaire que nous possédons. Le contrôleur seul exécute.

**`PAS_CLAIR` est la pièce qui rend le reste acceptable.** Une bouillie de transcription —
« agençum », « Nos gens sur Marne », mesurées le 01/09 — ne doit pas devenir une action.
Le modèle a le droit de dire qu'il ne sait pas, et l'agent fait alors répéter. Toute
réponse invalide, inconnue ou malformée dégrade vers `PAS_CLAIR` : c'est la seule sortie de
secours, et elle FAIT RÉPÉTER — elle n'abandonne jamais l'appel.

Les mots-clés, eux, ne disparaissent pas : ils vivent désormais dans `MockLLM`, qui est un
harnais de TEST. C'est leur place — un banc d'essai déterministe, jamais le chemin de
production.
"""
from __future__ import annotations

# ---- le vocabulaire, en un seul endroit ----------------------------------------------
# Des constantes plutôt que des littéraux : une action mal orthographiée dans `engine.py`
# se traduirait par une branche injoignable, donc par un silence — exactement le mode de
# panne que ce module est censé supprimer.
CHOISIR = "choisir"                  # prendre la proposition n° `rang`
PLUS_TOT = "plus_tot"                # veut le plus tôt possible / rien de plus tôt ?
CONTRAINTE = "contrainte"            # une nouvelle contrainte de disponibilité
REFUSER = "refuser"                  # aucune ne convient, sans contrainte exprimée
PAS_CLAIR = "pas_clair"              # phrase confuse ou probablement mal transcrite

# PAS d'action « prix » ni « humain » ici, alors qu'elles se produisent en S5 : ce sont des
# FAITS, lus par le moteur dans tous les états (`question_prix`, `veut_humain`). Les
# inscrire aussi au menu donnerait DEUX définitions de la même chose — le piège exact qui a
# produit R70, où « rejeu » et « affinage » étaient écrits deux fois avec chacun sa version
# de « plus long ». Un fait se constate, une action se choisit ; le menu ne contient que ce
# qui se choisit.

# Ce que chaque action VEUT DIRE, en français, tel que le modèle le lira. Le texte du
# prompt est donc généré depuis la même source que la validation : une action ajoutée ici
# est immédiatement offerte au modèle ET acceptée par le contrôleur. Les faire dériver
# donnerait un modèle qui propose ce que le code refuse, ou l'inverse — et l'appelant
# n'entendrait qu'un agent qui ne répond pas à ce qu'il a dit.
SENS = {
    CHOISIR: ('l\'appelant PREND une des propositions. Ajoute "rang" : 1 pour la '
              'première, 2 pour la deuxième. Il peut la désigner par son rang '
              '(« le premier », « le deuxième »), par son heure ou son jour '
              '(« le matin », « plutôt lundi », « celui de 14 heures »), ou simplement '
              'accepter (« ça me va », « parfait »).'),
    PLUS_TOT: ('l\'appelant veut être servi AU PLUS TÔT, ou demande s\'il n\'y a rien '
               'avant. « Le plus vite possible », « dès que vous pouvez », « au plus '
               'vite », « c\'est urgent », « vous n\'avez rien avant ? », « peu importe, '
               'le premier libre ».'),
    CONTRAINTE: ('l\'appelant donne une CONTRAINTE nouvelle, qui n\'est pas une des '
                 'propositions : un jour, un moment, une exclusion, une borne. '
                 '« Plutôt jeudi », « seulement le matin », « pas le samedi », « pas '
                 'avant la semaine prochaine », « après 18 heures ». Renvoie le texte '
                 'de la contrainte dans "disponibilites".'),
    REFUSER: ('aucune ne convient et l\'appelant ne dit pas ce qu\'il veut à la place. '
              '« Non », « ça ne va pas », « rien de tout ça ».'),
    PAS_CLAIR: ('la phrase est confuse, coupée, hors sujet, ou probablement MAL '
                'TRANSCRITE, et tu ne peux pas dire avec confiance ce que l\'appelant '
                'veut. À utiliser sans hésiter : faire répéter coûte un tour, agir sur '
                'du bruit coûte le rendez-vous.'),
}

# Le menu par état. Seul S5 y figure : c'est là que les trois défauts sont tombés, et c'est
# le tour qui décide du rendez-vous. Les autres états suivront, un par un, chacun avec ses
# cas d'éval — un basculement en bloc de la machine entière ne se vérifierait pas.
MENUS: dict[str, tuple[str, ...]] = {
    "S5_CRENEAU": (CHOISIR, PLUS_TOT, CONTRAINTE, REFUSER, PAS_CLAIR),
}


def menu(etat: str) -> tuple[str, ...]:
    """Les actions permises dans cet état, ou rien du tout.

    Un état absent rend un tuple VIDE, et `valider` dégrade alors tout vers `PAS_CLAIR` :
    un état non converti continue de fonctionner à l'ancienne, il ne se met pas à obéir à
    des actions que personne n'a autorisées pour lui.
    """
    return MENUS.get(etat, ())


def consigne(etat: str) -> str:
    """Le bout de prompt qui décrit le menu de cet état, généré depuis `SENS`.

    Rendu vide pour un état sans menu : le prompt ne doit pas proposer un choix qui
    n'existe pas.
    """
    permises = menu(etat)
    if not permises:
        return ""
    lignes = "\n".join(f'- "{a}" : {SENS[a]}' for a in permises)
    return lignes


def bloc_prompt(etat: str) -> str:
    """Le morceau de prompt qui donne le menu au modèle, ou une chaîne vide.

    La CONSIGNE D'INTERPRÉTATION vit ici, collée au menu, parce que c'est elle qui a
    manqué le 01/09 : l'ancien contrat énumérait des cases sans jamais demander au modèle
    de comprendre une intention. « Si la phrase désigne une des propositions par son heure,
    son jour ou son rang » — « le plus vite possible » ne fait aucun des trois, et rien
    n'invitait le modèle à conclure quand même. Il n'a pas échoué : on ne lui avait pas
    demandé.
    """
    lignes = consigne(etat)
    if not lignes:
        return ""
    return (
        "\nACTION. L'agent attend une réponse. Ajoute la clé \"action\" avec EXACTEMENT "
        "l'une de ces valeurs :\n"
        f"{lignes}\n"
        "INTERPRÈTE LE SENS de la phrase comme le ferait une secrétaire expérimentée, pas "
        "comme un formulaire : les gens ne parlent pas en mots-clés. Si l'intention est "
        "claire, traduis-la, même si la formulation est inattendue. Si elle ne l'est pas — "
        "phrase coupée, hors sujet, ou visiblement mal transcrite — réponds "
        "\"pas_clair\" : on fera répéter, et c'est toujours moins grave que d'agir de "
        "travers.\n")


def valider(brut: object, etat: str, nb_propositions: int) -> tuple[str, int | None]:
    """(action, rang) — ce que le contrôleur va exécuter, jamais autre chose.

    Tout ce qui n'est pas explicitement valide devient `PAS_CLAIR`, qui fait RÉPÉTER.
    Le sens de la dégradation compte autant que la dégradation : un modèle en panne, un
    JSON tronqué ou une action inventée doivent produire « pardon, pouvez-vous répéter »,
    jamais « je transmets à Julien, il vous rappellera ». Le second perd un client qui
    était en train de réserver.
    """
    if not isinstance(brut, dict):
        return PAS_CLAIR, None
    nom = brut.get("action")
    if not isinstance(nom, str) or nom not in menu(etat):
        return PAS_CLAIR, None
    if nom != CHOISIR:
        return nom, None
    # `choisir` sans rang exploitable ne se devine pas : réserver le mauvais créneau est
    # bien pire que faire répéter — l'appelant reçoit un SMS pour un rendez-vous qu'il n'a
    # pas demandé, et l'artisan se déplace pour rien.
    rang = brut.get("rang")
    if isinstance(rang, bool) or not isinstance(rang, int):
        try:
            rang = int(str(rang).strip())
        except (TypeError, ValueError):
            return PAS_CLAIR, None
    if not 1 <= rang <= nb_propositions:
        return PAS_CLAIR, None
    return CHOISIR, rang
