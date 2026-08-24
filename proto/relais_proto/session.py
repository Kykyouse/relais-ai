"""Sessions artisan : ce qui permet à Julien de rester connecté sur son téléphone.

**C'est la session qui compte, pas la méthode de connexion.** Julien valide des rendez-vous
plusieurs fois par jour : lui redemander de s'identifier à chaque fois serait insupportable.
Il se connecte rarement, il reste connecté longtemps. La méthode d'identification (code par
SMS, Google, mot de passe) devient donc un détail interchangeable au-dessus de cette couche.

Conséquence heureuse : une fois la session en place, **les liens des notifications
redeviennent des URL banales**. Pas besoin d'un jeton de capacité par notification — ce qui
aurait multiplié les secrets dans les SMS, chacun donnant accès à des données client.

Trois propriétés, comme pour les jetons de confirmation client :
  * 32 octets d'aléa — ici on ne compte pas les caractères, contrairement au jeton qui part
    dans un SMS : autant prendre large ;
  * **empreinte SHA-256 seule en base**, jamais le jeton en clair ;
  * expiration explicite, et révocation possible (déconnexion, appareil perdu).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets

NOM_COOKIE = "relais_session"
# Longue par choix : c'est tout l'intérêt d'une session pour un usage quotidien. Le
# renouvellement se fera à l'usage plutôt qu'en forçant une reconnexion mensuelle.
DUREE_JOURS = 90


def creer_jeton() -> tuple[str, str]:
    """(jeton en clair, empreinte). Le clair ne quitte le serveur que dans le cookie."""
    jeton = secrets.token_urlsafe(32)
    return jeton, empreinte(jeton)


def empreinte(jeton: str) -> str:
    return hashlib.sha256((jeton or "").encode("utf-8")).hexdigest()


def expiration(maintenant: dt.datetime, jours: int = DUREE_JOURS) -> dt.datetime:
    return maintenant + dt.timedelta(days=jours)


def attributs_cookie(secure: bool = True) -> dict:
    """Attributs du cookie de session.

    `httponly` : aucun script ne doit pouvoir lire le jeton — et nos pages n'ont de toute
    façon pas de JS. `samesite="lax"` : le cookie suit un lien venu d'un SMS (navigation
    de premier niveau) mais pas une requête POST déclenchée depuis un autre site.
    `secure` désactivable uniquement pour les tests en HTTP local.
    """
    return {"httponly": True, "samesite": "lax", "secure": secure,
            "max_age": DUREE_JOURS * 24 * 3600, "path": "/"}
