"""Connexion de l'artisan par code SMS. Remplace le champ « jeton d'accès » provisoire.

**Le mobile EST l'identité professionnelle de l'artisan**, et le canal existe déjà. Un code
à 6 chiffres ne contient aucune URL : il part donc par numéro court dès aujourd'hui, sans
attendre la déclaration du Sender ID.

Un code de connexion est une **capacité**, au même titre que le jeton de confirmation
client : quiconque l'a peut ouvrir une session. D'où les mêmes exigences, plus celles que
6 chiffres imposent.

  * **Empreinte SHA-256 seule en base.** Le clair ne vit que dans le SMS.
  * **Court dans le temps** : 10 minutes. Un code de connexion n'a pas de raison de
    survivre à la minute où on le tape.
  * **Essais comptés, et le code meurt avec eux.** C'est LA différence avec un jeton de
    32 octets : 6 chiffres, c'est un million de possibilités, ce qui tombe en quelques
    heures de requêtes automatisées si on laisse essayer sans limite. Avec 3 essais, la
    probabilité de tomber juste est de 3 sur un million par code émis.
  * **Un seul code vivant par artisan.** En demander un nouveau invalide le précédent :
    sinon chaque demande ajouterait une cible, et demander mille codes donnerait mille
    chances au lieu de trois.
  * **Délai entre deux demandes.** Chaque code est un SMS facturé et une notification chez
    quelqu'un : sans ce frein, un tiers peut faire sonner le téléphone d'un artisan en
    boucle à nos frais.

Ce module ne connaît ni la base ni le SMS : il produit et vérifie. La persistance passe par
le port `Depot`, l'envoi par la file sortante — comme toute sortie du système (règle n°2).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets

# 6 chiffres : ce que l'artisan lira sur son écran verrouillé et retapera d'une main, sur
# un chantier. Un code plus long serait plus sûr et moins utilisé — la sécurité vient ici
# de la brièveté de vie et du nombre d'essais, pas de la longueur.
LONGUEUR = 6
DUREE_MINUTES = 10
ESSAIS_MAX = 3
# Délai minimal entre deux demandes pour un même artisan. Assez court pour qu'un SMS
# vraiment perdu se redemande sans énerver, assez long pour qu'une boucle automatisée ne
# transforme pas son téléphone en réveil.
DELAI_RENVOI_SECONDES = 60


def creer_code() -> tuple[str, str]:
    """(code en clair, empreinte). Le clair ne quitte le serveur que dans le SMS.

    `randbelow` et non `random` : le code est un secret, pas un aléa d'affichage. Les
    zéros de tête sont conservés — « 004521 » est un code valide, et le tronquer en
    « 4521 » diviserait l'espace par cent.
    """
    code = f"{secrets.randbelow(10 ** LONGUEUR):0{LONGUEUR}d}"
    return code, empreinte(code)


def empreinte(code: str) -> str:
    return hashlib.sha256((code or "").strip().encode("utf-8")).hexdigest()


def expiration(maintenant: dt.datetime) -> dt.datetime:
    return maintenant + dt.timedelta(minutes=DUREE_MINUTES)


def normaliser_telephone(numero: str) -> str:
    """Ramène un numéro FR saisi à la main à la forme du registre (+33...).

    L'artisan tape ce qu'il a l'habitude d'écrire : « 06 12 34 56 78 », « 0612345678 »,
    « +33 6 12 34 56 78 ». Comparer ces formes telles quelles échouerait silencieusement
    et l'artisan verrait « numéro inconnu » avec le bon numéro sous les yeux — le pire
    message d'erreur possible.
    """
    chiffres = "".join(c for c in (numero or "") if c.isdigit())
    if chiffres.startswith("33") and len(chiffres) == 11:
        return "+" + chiffres
    if chiffres.startswith("0") and len(chiffres) == 10:
        return "+33" + chiffres[1:]
    return "+" + chiffres if chiffres else ""


# ---------------------------------------------------------- lien à usage unique
#
# Un LIEN que l'admin engendre pour ouvrir l'espace d'un artisan sans SMS. Demandé le
# 22/09 : en production `RELAIS_SMS=journal`, donc le code ne part pas — il s'imprime dans
# les journaux de l'hébergeur, et se connecter en lisant les logs du service n'est pas un
# parcours. Ce sera aussi la façon de faire entrer un artisan le jour de son inscription,
# sans dépendre d'un SMS qui coûte et qui peut ne pas arriver.
#
# MÊME MÉCANIQUE QUE LE CODE, et c'est voulu : empreinte seule en base, usage unique,
# expiration courte. Il est d'ailleurs RANGÉ AU MÊME ENDROIT (`code_connexion`), ce qui
# lui fait hériter gratuitement de la règle « un seul vivant par artisan » — en engendrer
# un nouveau invalide le précédent, et un code SMS demandé entre-temps l'invalide aussi.
#
# CE QUI CHANGE PAR RAPPORT AU CODE : 32 octets d'aléa au lieu de 6 chiffres. Compter les
# essais n'a donc plus de sens — un million de possibilités se parcourt, 2^256 non. La
# durée, elle, est plus courte : un lien de connexion traîne dans un historique, un
# presse-papier ou une conversation, là où six chiffres tapés à la main ne laissent rien.
DUREE_LIEN_MINUTES = 15


def creer_lien() -> tuple[str, str]:
    """(jeton en clair, empreinte). Le clair ne quitte le serveur qu'une fois, dans le
    lien affiché à l'admin — la base n'en garde que l'empreinte, comme pour le code."""
    jeton = secrets.token_urlsafe(32)
    return jeton, empreinte(jeton)


def expiration_lien(maintenant: dt.datetime) -> dt.datetime:
    return maintenant + dt.timedelta(minutes=DUREE_LIEN_MINUTES)
