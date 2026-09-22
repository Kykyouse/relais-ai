"""Le compte ADMIN : l'exploitant du produit, pas un artisan.

Geoffrey, le 21/09 : « je suis pas un artisan je suis le maitre du produit, si on me
demande de l'assistance il faut que je puisse tout faire ». D'où un sujet distinct, avec
sa table, sa session et son cookie — et non un drapeau posé sur une ligne `artisan`.

**POURQUOI UN MOT DE PASSE ET NON UN CODE SMS.** L'artisan se connecte par code SMS parce
que son mobile EST son identité professionnelle et qu'il est sur un chantier. Pour l'admin,
trois raisons renversent le choix :

  * en production `RELAIS_SMS=journal` — un code d'admin atterrirait dans les journaux de
    l'hébergeur. Se connecter en lisant les logs du service qu'on administre n'est pas un
    parcours, c'est un contournement ;
  * l'admin est devant un clavier, pas sur un toit ;
  * activer l'envoi réel pour se connecter soi-même ferait dépendre l'administration d'un
    crédit SMS et d'un opérateur. Une panne OVH ne doit pas empêcher d'administrer.

`hashlib.scrypt` est dans la bibliothèque standard : aucune dépendance nouvelle, et une
fonction de dérivation à coût mémoire — c'est ce qui la distingue d'un simple SHA-256, que
du matériel dédié parcourt à des milliards d'essais par seconde.

Ce module ne connaît ni la base ni HTTP : il dérive et compare. La persistance passe par le
port `Depot`, la session par `session.py` — comme pour l'artisan.
"""
from __future__ import annotations

from . import motdepasse

# Longueur minimale POUR UN ADMIN. Plus haute que pour un artisan, et c'est le sens du
# paramètre de `motdepasse.chiffrer` : ce compte peut tout faire sur les données de tous
# les clients, celui d'un artisan ne voit que les siennes.
LONGUEUR_MINIMALE = 12

NOM_COOKIE = "nelyo_admin"

# Le cookie du mode SUPPORT : « je regarde l'espace de cet artisan ».
#
# Il ne porte qu'un identifiant d'artisan, en clair, et **il ne vaut rien seul** : la
# résolution exige une session d'admin valide à CHAQUE requête. Sans cette règle, poser
# un cookie à la main suffirait à devenir n'importe quel artisan — c'est-à-dire que le
# mode support serait une élévation de privilège offerte à tout visiteur.
NOM_COOKIE_VUE = "nelyo_vue"

# Plus court que les 90 jours d'un artisan, et délibérément. L'artisan valide des RDV
# plusieurs fois par jour depuis son téléphone ; l'admin ouvre l'outil rarement, et son
# cookie ouvre l'accès à tous les clients. Une session qui peut tout faire doit se
# refermer plus vite qu'une session qui peut valider un rendez-vous.
DUREE_JOURS = 7


def chiffrer(mot_de_passe: str) -> str:
    """L'empreinte d'un mot de passe d'ADMIN — même mécanisme que pour l'artisan, seuil
    plus exigeant. Le hachage lui-même vit dans `motdepasse.py` depuis le 22/09 : deux
    implémentations auraient fini par diverger sur les paramètres, et ce jour-là les mots
    de passe d'un des deux côtés seraient devenus invérifiables."""
    return motdepasse.chiffrer(mot_de_passe, LONGUEUR_MINIMALE)


def verifier(mot_de_passe: str, enregistre: str) -> bool:
    return motdepasse.verifier(mot_de_passe, enregistre)


def mot_de_passe_suggere() -> str:
    return motdepasse.suggerer()
