"""Jetons de confirmation client : le lien a un tap envoye par SMS.

Le client n'a pas de compte : le jeton EST son authentification. D'ou trois exigences,
toutes verifiees dans le domaine (`Rdv.confirmer_par_client`) et non dans l'API :

* **imprevisible** : 32 octets d'alea (`secrets.token_urlsafe`), soit bien au-dela de ce
  qu'une attaque par enumeration peut couvrir ;
* **stocke en empreinte SHA-256 seulement** : le jeton vaut capacite, une fuite de base ne
  doit pas permettre de confirmer des rendez-vous a la place des clients ;
* **a usage unique et borne dans le temps** : efface a la confirmation, et l'echeance du
  RDV lui est opposee.
"""
from __future__ import annotations

import hashlib
import secrets


def creer_jeton() -> tuple[str, str]:
    """Rend (jeton en clair, empreinte). Le clair ne part QUE dans le SMS ; seule
    l'empreinte est persistee."""
    jeton = secrets.token_urlsafe(32)
    return jeton, empreinte(jeton)


def empreinte(jeton: str) -> str:
    return hashlib.sha256((jeton or "").encode("utf-8")).hexdigest()


def lien(base_url: str, jeton: str) -> str:
    """URL courte : elle passe dans un SMS, ou chaque caractere compte."""
    return f"{base_url.rstrip('/')}/c/{jeton}"
