"""Adaptateur OVH derrière le port `Envoyeur`. Isolé dans son propre module : `envoi.py`
reste sans fournisseur, et un autre adaptateur se mettra à côté sans le toucher.

**Le transport est injecté.** La signature de requête et le choix d'endpoint sont délégués
au SDK officiel `ovh` en production, et à un double en test. Ce qui reste ici — et qui est
donc réellement à nous, donc réellement testable hors ligne — c'est :

  * la mise au format **E.164** des numéros (nous stockons « 0612345678 », OVH veut
    « +33612345678 ») ;
  * le corps de la requête, dont `noStopClause` ;
  * la **classification des échecs** : un numéro invalide est définitif (le réessayer
    n'y changera rien), une panne réseau est transitoire.

⚠️ **Le contrat d'API d'OVH encodé ici est une HYPOTHÈSE tant qu'aucun envoi réel n'a eu
lieu.** Les doubles de test reproduisent la forme de réponse que j'attends
(`ids` / `validReceivers` / `invalidReceivers`) : le premier appel réel la confirmera ou la
démentira. À vérifier dans leur documentation avant la première salve.
"""
from __future__ import annotations

import re

from .envoi import EchecDefinitif, EchecEnvoi
from .messages import MessageSortant


def en_e164(numero: str) -> str:
    """« 06 12 34 56 78 », « 0612345678 », « 0033612345678 » → « +33612345678 ».

    Un numéro qu'on ne sait pas mettre au format est un échec DÉFINITIF : il ne deviendra
    pas valide au troisième essai. Autant le dire tout de suite et le rendre visible.
    """
    brut = re.sub(r"[^\d+]", "", numero or "")
    if brut.startswith("+"):
        candidat = brut
    elif brut.startswith("00"):
        candidat = "+" + brut[2:]
    elif brut.startswith("0") and len(brut) == 10:
        candidat = "+33" + brut[1:]
    else:
        candidat = brut
    if not re.fullmatch(r"\+\d{8,15}", candidat):
        raise EchecDefinitif(f"numéro inexploitable : {numero!r}")
    return candidat


class EnvoyeurOVH:
    def __init__(self, transport, compte: str):
        """`transport(chemin, **corps) -> dict` : en prod, `client.post` du SDK `ovh`.
        `compte` est le service SMS (forme « sms-xx11111-1 »)."""
        self.transport = transport
        self.compte = compte

    def envoyer(self, message: MessageSortant, cfg: dict) -> str:
        expediteur = (cfg.get("sms") or {}).get("expediteur")
        if not expediteur:
            raise EchecDefinitif("sms.expediteur absent de la config artisan")
        destinataire = en_e164(message.cible)

        corps = {
            "message": message.texte,
            "receivers": [destinataire],
            "sender": expediteur,
            # SMS transactionnel : réponse à une demande entrante du client, pas de
            # prospection. La clause STOP n'est donc pas requise — et l'ajouter mangerait
            # une vingtaine de caractères utiles sur chaque message.
            "noStopClause": True,
            "charset": "UTF-8",
            "priority": "high",
        }
        try:
            reponse = self.transport(f"/sms/{self.compte}/jobs", **corps)
        except EchecDefinitif:
            raise
        except Exception as exc:  # réseau, quota, 5xx : réessayable
            raise EchecEnvoi(f"{type(exc).__name__}: {exc}") from exc

        # OVH accepte la requête mais peut rejeter le destinataire : un 200 ne suffit pas
        if destinataire in (reponse or {}).get("invalidReceivers", []):
            raise EchecDefinitif(f"destinataire refusé par OVH : {destinataire}")
        ids = (reponse or {}).get("ids") or []
        if not ids:
            raise EchecEnvoi(f"OVH n'a rendu aucun identifiant d'envoi : {reponse!r}")
        return f"ovh:{ids[0]}"


def transport_sdk(endpoint: str = "ovh-eu"):
    """Transport de production. Le SDK lit ses identifiants dans l'environnement
    (`OVH_APPLICATION_KEY`, `OVH_APPLICATION_SECRET`, `OVH_CONSUMER_KEY`) : la signature de
    requête ne passe donc jamais par notre code.

    Le consumer key doit être limité à `POST /sms/*` avec expiration — jamais `/*`.
    """
    import ovh  # import tardif : dépendance optionnelle, inutile hors envoi réel
    client = ovh.Client(endpoint=endpoint)
    return lambda chemin, **corps: client.post(chemin, **corps)
