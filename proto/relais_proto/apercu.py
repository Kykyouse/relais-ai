"""Le portail d'APERÇU : un mot de passe unique devant le site vitrine.

POURQUOI CE N'EST PAS `session.py` NI `admin.py`. Les deux autres portes identifient
QUELQU'UN — un artisan, un administrateur — et ouvrent une session qui lui appartient.
Celle-ci n'identifie personne : elle répond à « ce visiteur a-t-il reçu l'adresse de la
part de Geoffrey ? ». Un seul secret, partagé, destiné à être dit au téléphone ou collé
dans un message. Les mêler aurait donné à un relecteur de passage un objet qui ressemble
à une session d'artisan.

CE QUE ÇA PROTÈGE, ET CE QUE ÇA NE PROTÈGE PAS. C'est un rideau, pas une serrure : il
empêche la page d'être lue par un passant ou indexée par un moteur, le temps de la
montrer à des collaborateurs et de récolter des avis. Le secret est unique, il ne se
révoque pas individuellement, et quiconque le reçoit peut le transmettre. Il ne doit donc
jamais garder autre chose qu'une page de présentation — l'espace artisan et
l'administration ont leurs propres portes, et le portail ne les remplace pas.

LE MOT DE PASSE VIENT DE L'ENVIRONNEMENT, jamais du code. La règle du projet vaut ici
comme pour les clés d'API : un secret écrit dans un fichier suivi par git est un secret
publié, et ce dépôt est sur GitHub. `RELAIS_VITRINE_MOTDEPASSE` est posée dans le
tableau de bord de l'hébergeur.

ET SON ABSENCE EST LE MODE PUBLIC. Variable vide ou non posée : la vitrine s'ouvre à
tous et redevient indexable. Le jour du lancement, il n'y a donc rien à déployer — on
retire la variable. Un drapeau de plus (`RELAIS_VITRINE_PRIVEE=0/1`) aurait fait deux
réglages à tenir d'accord, et un jour ils ne l'auraient plus été.
"""
from __future__ import annotations

import hashlib
import hmac

NOM_COOKIE = "nelyo_apercu"
DUREE_JOURS = 30

# Le paramètre passé dans un lien partageable : `…/?cle=<mot de passe>`. Il évite de
# devoir transmettre l'adresse ET le mot de passe séparément à chaque relecteur.
PARAM_CLE = "cle"

# Étiquette fixe du HMAC. Sa seule raison d'être : que le cookie ne soit pas le SHA-256
# nu d'un mot de passe probablement court. Un condensat nu se retrouve dans n'importe
# quelle table arc-en-ciel, et révélerait un mot de passe que Geoffrey réutilise
# peut-être ailleurs. Versionnée : changer l'étiquette invalide tous les cookies émis.
_ETIQUETTE = b"nelyo-apercu-v1"


def jeton(motdepasse: str) -> str:
    """Ce que vaut le cookie pour ce mot de passe. Déterministe, sans état en base.

    Pas de session stockée : il n'y a rien à révoquer individuellement, et une table de
    plus pour un rideau serait disproportionnée. Changer `RELAIS_VITRINE_MOTDEPASSE`
    invalide d'un coup tous les accès, ce qui est exactement le geste qu'on veut.
    """
    return hmac.new(motdepasse.encode("utf-8"), _ETIQUETTE, hashlib.sha256).hexdigest()


def ouvert(jeton_recu: str | None, motdepasse: str | None) -> bool:
    """Le visiteur a-t-il le droit de voir la page ?

    Sans mot de passe configuré, tout le monde entre — c'est le mode public.
    """
    if not motdepasse:
        return True
    if not jeton_recu:
        return False
    return hmac.compare_digest(jeton_recu, jeton(motdepasse))


def motdepasse_juste(propose: str | None, motdepasse: str | None) -> bool:
    """Comparaison à TEMPS CONSTANT : une comparaison `==` sur une chaîne s'arrête au
    premier caractère qui diffère, et le temps de réponse dit alors combien de
    caractères étaient bons."""
    if not motdepasse or not propose:
        return False
    return hmac.compare_digest(propose.encode("utf-8"), motdepasse.encode("utf-8"))


def attributs_cookie(secure: bool = True) -> dict:
    """Mêmes garanties que le cookie de session : illisible par un script, et qui ne
    part pas sur une requête venue d'un autre site."""
    return {"httponly": True, "samesite": "lax", "secure": secure,
            "max_age": DUREE_JOURS * 24 * 3600, "path": "/"}
