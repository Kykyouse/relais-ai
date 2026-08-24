"""Adaptateur OVH derrière le port `Envoyeur`. Isolé dans son propre module : `envoi.py`
reste sans fournisseur, et un autre adaptateur se mettra à côté sans le toucher.

**Le transport est injecté.** La signature de requête et le choix d'endpoint sont délégués
au SDK officiel `ovh` en production, et à un double en test. Ce qui reste ici — et qui est
donc réellement à nous, donc réellement testable hors ligne — c'est :

  * la mise au format **E.164** des numéros (nous stockons « 0612345678 », OVH veut
    « +33612345678 ») ;
  * le corps de la requête, dont `noStopClause` ;
  * la **classification des échecs** : un numéro invalide est définitif (le réessayer
    n'y changera rien), une panne réseau est transitoire ;
  * le **diagnostic** des erreurs de l'API, qui est une connaissance du fournisseur.

⚠️ **Le contrat d'API encodé ici reste une HYPOTHÈSE tant qu'aucun envoi n'a abouti.**
Au 24/08, sont confirmés par des appels réels : l'authentification, le nom du service, et
l'acceptation de la requête. Ne l'est PAS : la forme de la réponse en cas de succès
(`ids` / `validReceivers` / `invalidReceivers`) — il manquait l'expéditeur.
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


# Un SMS envoyé depuis un numéro court OVH est BLOQUÉ s'il contient une URL. Or le cœur
# du produit — la validation à un tap (§3.5bis) — est justement un lien. Le mode numéro
# court est donc réservé aux tests, et cette règle est un GARDE, pas un commentaire : un
# commentaire s'ignore, un garde-fou non. Sans lui, le SMS de reproposition partirait et
# serait silencieusement jeté par l'opérateur.
_RE_URL = re.compile(r"https?://|www\.", re.IGNORECASE)


class EnvoyeurOVH:
    def __init__(self, transport, compte: str, numero_court: bool = False):
        """`transport(chemin, **corps) -> dict` : en prod, `client.post` du SDK `ovh`.
        `compte` est le service SMS (forme « sms-xy12345-1 »).

        `numero_court` : envoie via un numéro court OVH (`senderForResponse`), disponible
        sans déclaration. **Mode explicite et non déduit de l'absence d'expéditeur** : une
        config incomplète basculerait alors silencieusement en numéro court, où les URL
        sont bloquées — le lien de validation disparaîtrait sans erreur visible. Une
        omission de configuration doit lever, pas changer de comportement.
        """
        self.transport = transport
        self.compte = compte
        self.numero_court = numero_court

    def envoyer(self, message: MessageSortant, cfg: dict) -> str:
        destinataire = en_e164(message.cible)
        corps = {
            "message": message.texte,
            "receivers": [destinataire],
            # SMS transactionnel : réponse à une demande entrante du client, pas de
            # prospection. La clause STOP n'est donc pas requise — et l'ajouter mangerait
            # une vingtaine de caractères utiles sur chaque message.
            "noStopClause": True,
            "charset": "UTF-8",
            "priority": "high",
        }
        if self.numero_court:
            if _RE_URL.search(message.texte or ""):
                raise EchecDefinitif(
                    "message avec URL en numéro court : l'opérateur le bloquerait. "
                    "Le mode numéro court sert aux tests, jamais au lien de validation.")
            # `sender` et `senderForResponse` sont mutuellement exclusifs côté OVH :
            # en numéro court, on n'envoie PAS de clé `sender`.
            corps["senderForResponse"] = True
        else:
            expediteur = (cfg.get("sms") or {}).get("expediteur")
            if not expediteur:
                raise EchecDefinitif("sms.expediteur absent de la config artisan")
            corps["sender"] = expediteur
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


# ------------------------------------------------------- diagnostic des erreurs
# Table construite à partir des erreurs RÉELLEMENT observées. Elle ne saura jamais tout
# d'avance : elle se remplit à chaque échec.
#
# ORDRE = DU PLUS SPÉCIFIQUE AU PLUS GÉNÉRIQUE, et c'est essentiel. Le 24/08, le message
# « Sms sender DupontChauf does not exists » a été diagnostiqué « nom de service faux »
# parce qu'un motif générique (« does not exist ») était testé AVANT le motif spécifique
# (« sender »). Un motif générique doit donc être à la fois tardif et étroit.
_PISTES: list[tuple[tuple[str, ...], str]] = [
    (("sender", "Sender", "expediteur"),
     "→ L'EXPÉDITEUR n'existe pas encore côté OVH, ou n'est pas validé. Le créer dans "
     "l'espace client (Telecom > SMS > Expéditeurs). Un expéditeur alphanumérique doit "
     "être déclaré auprès des opérateurs (Charte AF2M du 01/03/2026) : compter un délai, "
     "et un motif d'usage à justifier."),
    (("NotGrantedCall", "not been granted"),
     "→ PORTÉE du consumer key : la clé est valide, mais cet appel n'est pas dans ses "
     "règles d'accès. Le plus sûr est de lire ce dont tu as besoin dans l'espace client "
     "plutôt que d'élargir la clé."),
    (("credit", "Credit", "insufficient"),
     "→ Plus de CRÉDITS SMS : en recharger dans l'espace client."),
    # motif volontairement ÉTROIT : « service does not exist », et non « does not exist »
    (("service does not exist", "ResourceNotFound"),
     "→ Le NOM DU SERVICE SMS est faux, ou le service n'a pas été commandé. Créer un "
     "compte OVH ne crée PAS de service SMS. Nom visible dans l'espace client "
     "(Telecom > SMS), forme « sms-xy12345-1 »."),
    (("InvalidKey", "InvalidSignature", "InvalidCredential", "Forbidden", "Unauthorized"),
     "→ IDENTIFIANTS : vérifier le triplet application key / secret / consumer key, et "
     "que le consumer key n'a pas expiré."),
]


def diagnostic(texte: str) -> str:
    """Oriente vers la cause probable. Un diagnostic incomplet est normal ; un diagnostic
    qui n'oriente pas est un défaut — d'où un repli qui nomme les familles."""
    for motifs, piste in _PISTES:
        if any(m in texte for m in motifs):
            return piste
    return ("→ Motif non reconnu. Par ordre de probabilité : expéditeur non créé ou non "
            "validé · service SMS non commandé ou mal nommé · portée du consumer key trop "
            "étroite · crédits épuisés. Rapporte le message et le Query-ID : ils "
            "enrichiront cette table.")


def transport_sdk(endpoint: str = "ovh-eu"):
    """Transport de production. Le SDK lit ses identifiants dans l'environnement
    (`OVH_APPLICATION_KEY`, `OVH_APPLICATION_SECRET`, `OVH_CONSUMER_KEY`) : la signature de
    requête ne passe donc jamais par notre code.

    Le consumer key doit être limité à `POST /sms/*` avec expiration — jamais `/*`.
    """
    import ovh  # import tardif : dépendance optionnelle, inutile hors envoi réel
    client = ovh.Client(endpoint=endpoint)
    return lambda chemin, **corps: client.post(chemin, **corps)
