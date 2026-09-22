"""Mots de passe : dérivation, vérification, suggestion. Pour TOUS les sujets.

Extrait de `admin.py` le 22/09, quand l'artisan a eu besoin d'un mot de passe lui aussi :
« j'suis pas contre que les artisans aient juste un id + mdp comme un site classique,
qu'ils pourront enregistré dans leurs appareils pour pas avoir a se reco en permanence ».

Ce module ne connaît ni la base, ni HTTP, ni ce qu'est un artisan ou un admin : il dérive
et il compare. `admin.py` garde ce qui lui est propre — son cookie, la durée de sa session
— et délègue ici. Deux implémentations du même hachage auraient fini par diverger sur les
paramètres, et le jour de la divergence, les mots de passe déjà enregistrés d'un des deux
côtés seraient devenus invérifiables.

`hashlib.scrypt` est dans la bibliothèque standard : aucune dépendance, et une fonction de
dérivation à coût MÉMOIRE — c'est ce qui la distingue d'un simple SHA-256, que du matériel
dédié parcourt à des milliards d'essais par seconde.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

# Paramètres de dérivation. `n` est le coût : 2^15 tient en ~32 Mo et une centaine de
# millisecondes, imperceptible sur un formulaire de connexion et très cher à répéter des
# milliards de fois.
#
# ILS SONT STOCKÉS AVEC L'EMPREINTE, pas seulement ici : le jour où on les durcit, les
# mots de passe déjà enregistrés doivent rester vérifiables. Une constante globale relue à
# la vérification invaliderait tout le monde en silence.
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


def chiffrer(mot_de_passe: str, longueur_minimale: int = 10) -> str:
    """« scrypt$n$r$p$sel$empreinte », tout en hexadécimal.

    Format auto-descriptif : les paramètres voyagent avec l'empreinte, donc les durcir
    plus tard n'invalide pas les mots de passe existants.

    `longueur_minimale` est un PARAMÈTRE parce que les sujets n'ont pas le même pouvoir :
    un compte d'admin peut tout faire sur les données de tous les clients, celui d'un
    artisan ne voit que les siennes. Le seuil est vérifié à l'ÉCRITURE — un contrôle qui
    ne vit que dans le HTML est un contrôle absent.
    """
    if len(mot_de_passe or "") < longueur_minimale:
        raise ValueError(
            f"mot de passe trop court : {longueur_minimale} caractères minimum.")
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


# Une empreinte qui ne correspond à rien, de la BONNE forme et du bon coût.
#
# Elle sert à vérifier un mot de passe MÊME quand le compte n'existe pas : sans ça, le
# temps de réponse dirait quels identifiants existent — scrypt coûte assez cher pour que
# l'écart se mesure depuis l'autre bout d'un réseau.
EMPREINTE_FACTICE = f"scrypt${N}${R}${P}${'00' * SEL_OCTETS}${'00' * DKLEN}"


def suggerer() -> str:
    """Un mot de passe solide, à proposer lors d'une création en ligne de commande.

    Proposé plutôt qu'imposé : qui préfère le sien le donnera. Mais un compte créé sans
    proposition finit avec un mot de passe choisi à la hâte.
    """
    return secrets.token_urlsafe(18)
