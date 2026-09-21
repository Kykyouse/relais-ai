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

import hashlib
import hmac
import secrets

# Paramètres de dérivation. `n` est le coût : 2^15 tient en ~32 Mo et quelques dizaines de
# millisecondes, ce qui est imperceptible sur un formulaire de connexion et très cher à
# répéter des milliards de fois.
#
# ILS SONT STOCKÉS AVEC L'EMPREINTE, pas seulement ici : le jour où l'on durcit les
# paramètres, les mots de passe déjà enregistrés doivent rester vérifiables. Une constante
# globale relue à la vérification invaliderait tout le monde en silence.
N, R, P, DKLEN, SEL_OCTETS = 2 ** 15, 8, 1, 32, 16


def _maxmem(n: int, r: int) -> int:
    """La limite mémoire à autoriser pour ces paramètres.

    OpenSSL refuse au-delà de 32 Mo par défaut, et scrypt consomme exactement
    `128 * n * r` octets — soit 32 Mo tout rond pour n=2^15, r=8. Le calcul tombe donc
    pile sur la limite et lève « memory limit exceeded ». On la relève explicitement, en
    la DÉRIVANT des paramètres plutôt qu'en la codant en dur : durcir `n` plus tard ne
    doit pas rouvrir la même panne, et une empreinte ancienne doit rester vérifiable avec
    les paramètres qu'elle porte.
    """
    return 128 * n * r * 2

# Longueur minimale. Ce compte peut TOUT faire sur les données de vrais clients : le seuil
# est plus haut que pour un compte ordinaire, et il est vérifié à l'écriture — un contrôle
# qui ne vit que dans le HTML est un contrôle absent.
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
    """« scrypt$n$r$p$sel$empreinte », tout en hexadécimal.

    Format auto-descriptif : les paramètres voyagent avec l'empreinte, donc les durcir
    plus tard n'invalide pas les mots de passe existants.
    """
    if len(mot_de_passe or "") < LONGUEUR_MINIMALE:
        raise ValueError(
            f"mot de passe trop court : {LONGUEUR_MINIMALE} caractères minimum. "
            f"Ce compte peut tout faire sur les données de vrais clients.")
    sel = secrets.token_bytes(SEL_OCTETS)
    brut = hashlib.scrypt(mot_de_passe.encode("utf-8"), salt=sel,
                          n=N, r=R, p=P, dklen=DKLEN, maxmem=_maxmem(N, R))
    return f"scrypt${N}${R}${P}${sel.hex()}${brut.hex()}"


def verifier(mot_de_passe: str, enregistre: str) -> bool:
    """Le mot de passe correspond-il à l'empreinte enregistrée ?

    Rend `False` sur tout ce qui n'est pas une correspondance franche — empreinte vide,
    format inconnu, paramètres illisibles. Une empreinte qu'on ne sait pas lire n'est pas
    une raison de laisser entrer : c'est la raison inverse.
    """
    try:
        marque, n, r, p, sel_hex, attendu_hex = (enregistre or "").split("$")
        if marque != "scrypt":
            return False
        brut = hashlib.scrypt(mot_de_passe.encode("utf-8"),
                              salt=bytes.fromhex(sel_hex),
                              n=int(n), r=int(r), p=int(p),
                              dklen=len(attendu_hex) // 2,
                              maxmem=_maxmem(int(n), int(r)))
    except (ValueError, TypeError, AttributeError, MemoryError):
        return False
    # Comparaison à temps constant : le temps de réponse ne doit pas révéler combien de
    # caractères de tête sont justes. Même exigence que `Registre.par_token`.
    return hmac.compare_digest(brut.hex(), attendu_hex)


def mot_de_passe_suggere() -> str:
    """Un mot de passe solide, pour la création d'un compte en ligne de commande.

    Proposé plutôt qu'imposé : un admin qui préfère le sien le donnera. Mais un compte
    créé sans proposition finit avec un mot de passe choisi à la hâte.
    """
    return secrets.token_urlsafe(18)
