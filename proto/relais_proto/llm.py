"""Le LLM en deux rôles étroits : EXTRACTEUR de slots et FORMULEUR de répliques.

- AnthropicLLM : la vraie version (nécessite ANTHROPIC_API_KEY dans l'environnement / .env).
- MockLLM     : extraction par règles + répliques template. Sans réseau, déterministe —
                sert aux tests automatisés et à valider la machine à états seule.

Le contrôleur (engine.py) passe une INSTRUCTION précise ("demande la commune",
"propose ces 2 créneaux : ...") : le LLM met en mots, il ne décide pas.
"""
from __future__ import annotations

import json
import os
import re

EXTRACT_SYSTEM = """Tu extrais des informations d'une phrase d'un appelant au téléphone d'un artisan {metier}.
Réponds UNIQUEMENT un objet JSON avec les clés présentes dans la phrase (omets les absentes) :
- prestation: une de {prestations} si identifiable
- probleme: résumé très court "équipement + symptôme" (ex: "chaudière ne démarre plus")
- commune: nom de commune si mentionné
- code_postal: 5 chiffres si mentionné
- urgence_reelle: true/false si l'appelant exprime (ou nie) un dégât/besoin immédiat
- statut_occupant: proprietaire|locataire|syndic|autre si déductible
- nom: nom de famille si donné
- telephone_rappel: numéro FR si donné (format 0XXXXXXXXX)
- disponibilites: contraintes de dispo si exprimées
- danger_gaz: true si odeur/fuite de gaz évoquée
- confirme: true/false si la phrase est une confirmation/refus de ce que l'agent vient de proposer
- creneau_choisi: 1 ou 2 si l'appelant choisit une des propositions en cours
- veut_plus_tot: true si l'appelant demande un créneau PLUS TÔT que les propositions
- question_prix: true si l'appelant demande un prix, un tarif ou une fourchette
- veut_humain: true si l'appelant demande à parler à un humain/au patron
Ne déduis rien qui ne soit pas dans la phrase.

Contexte de la conversation :
- L'agent vient de dire : "{dernier_agent}"
- Propositions de créneaux en cours : {propositions}
Si la phrase de l'appelant désigne une des propositions (par son heure, son jour ou
son rang — "le matin", "plutôt lundi", "le premier"), renvoie creneau_choisi (1 ou 2)."""

REPLY_SYSTEM = """Tu es l'assistant vocal de {nom_entreprise} ({metier}), au téléphone.
Tu parles pour un appel VOCAL : phrases courtes, chaleureuses, naturelles. UNE seule question à la fois.
Règles absolues :
- Jamais de prix ni de fourchette (sauf texte exact fourni dans l'instruction).
- Jamais de diagnostic technique. Jamais "c'est confirmé".
- Ne promets rien qui n'est pas dans l'instruction : n'annonce JAMAIS un rappel,
  une transmission ou un rendez-vous que l'instruction ne contient pas explicitement.
- Si l'instruction PROPOSE des créneaux, présente-les comme des propositions et pose la
  question — ne dis jamais "c'est noté" ou "c'est réservé" à la place d'une proposition.
- Recopie les dates et horaires EXACTEMENT tels que l'instruction les donne.
Instruction du contrôleur (mets-la en mots naturellement, sans rien ajouter d'engageant) :
{instruction}"""


class MockLLM:
    """Extraction par règles simples + répliques = l'instruction elle-même (déjà rédigée)."""

    PRESTATION_KEYWORDS = {
        "fuite": ["fuite", "coule", "goutte", "inond"],
        "chaudiere_panne": ["chaudière", "chaudiere", "chauffage ne", "plus de chauffage"],
        "chauffe_eau": ["chauffe-eau", "chauffe eau", "eau chaude", "ballon"],
        "wc_evacuation": ["wc", "toilette", "bouché", "bouche", "évacuation", "canalisation"],
        "robinetterie": ["robinet", "mitigeur"],
        "devis_pac": ["pompe à chaleur", "pac"],
        "devis_chaudiere": ["nouvelle chaudière", "remplacer la chaudière", "changer de chaudière"],
        "devis_sdb": ["salle de bain"],
        "entretien_chaudiere": ["entretien", "révision"],
    }

    def extract(self, utterance: str, context: dict) -> dict:
        u = utterance.lower()
        out: dict = {}
        for prest, kws in self.PRESTATION_KEYWORDS.items():
            if any(k in u for k in kws):
                out["prestation"] = prest
                out["probleme"] = utterance.strip()[:80]
                break
        if m := re.search(r"\b(\d{5})\b", u):
            out["code_postal"] = m.group(1)
        if m := re.search(r"\b(0\d(?:[\s.\-]?\d{2}){4})\b", utterance):
            out["telephone_rappel"] = re.sub(r"[\s.\-]", "", m.group(1))
        if m := re.search(r"(?:je m'appelle|c'est) (?:m\.|mme|madame|monsieur)?\s*([A-ZÉÈ][a-zé-]+)", utterance):
            out["nom"] = m.group(1)
        if "gaz" in u and ("odeur" in u or "sent" in u):
            out["danger_gaz"] = True
        if "propriétaire" in u:
            out["statut_occupant"] = "proprietaire"
        if "locataire" in u:
            out["statut_occupant"] = "locataire"
        if any(w in u for w in ["urgent", "urgence", "tout de suite", "aujourd'hui", "l'eau coule"]):
            out["urgence_reelle"] = True
        if any(w in u for w in ["dispo", "après", "avant", "matin", "après-midi", "quand vous voulez", "chez moi"]):
            out["disponibilites"] = utterance.strip()[:80]
        if re.search(r"\b(oui|d'accord|ok|parfait|ça marche|c'est bon|exact)\b", u):
            out["confirme"] = True
        if re.search(r"\b(non|pas possible|impossible)\b", u):
            out["confirme"] = False
        if "premier" in u or "le 1" in u:
            out["creneau_choisi"] = 1
        if "deuxième" in u or "second" in u or "le 2" in u:
            out["creneau_choisi"] = 2
        if any(w in u for w in ["un humain", "quelqu'un", "le patron", "parler à julien"]):
            out["veut_humain"] = True
        if any(w in u for w in ["plus tôt", "rien avant", "pas avant"]):
            out["veut_plus_tot"] = True
        if any(w in u for w in ["combien", "prix", "tarif", "fourchette", "coûte", "euros"]):
            out["question_prix"] = True
        return out

    def reply(self, instruction: str, context: dict) -> str:
        return instruction  # les instructions du contrôleur sont déjà des phrases prononçables


def _texte_de(msg) -> str:
    """Concatène les blocs texte de la réponse — les modèles récents peuvent renvoyer
    des blocs de réflexion (ThinkingBlock) avant le texte : on ne lit QUE les blocs texte."""
    return "".join(b.text for b in msg.content
                   if getattr(b, "type", "") == "text").strip()


class AnthropicLLM:
    def __init__(self, model: str | None = None):
        import anthropic  # import tardif : optionnel en mode mock
        # timeout court + 1 retry : au téléphone, mieux vaut dégrader vite que faire
        # attendre l'appelant (le SDK attendrait sinon bien plus longtemps)
        self.client = anthropic.Anthropic(timeout=10.0, max_retries=1)
        self.model = model or os.environ.get("RELAIS_MODEL", "claude-haiku-4-5")

    def extract(self, utterance: str, context: dict) -> dict:
        # max_tokens large : les modèles à réflexion adaptative (Sonnet 5) consomment
        # leurs tokens de réflexion DANS max_tokens — 200 tronquait les réponses en plein mot.
        msg = self.client.messages.create(
            model=self.model, max_tokens=1500,
            system=EXTRACT_SYSTEM.format(
                metier=context["metier"], prestations=context["prestations"],
                dernier_agent=context.get("dernier_agent", ""),
                propositions=context.get("propositions", []) or "aucune"),
            messages=[{"role": "user", "content": utterance}],
        )
        text = _texte_de(msg)
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    def reply(self, instruction: str, context: dict) -> str:
        dernier = context.get("dernier_tour") or "(l'appelant reste silencieux)"
        msg = self.client.messages.create(
            model=self.model, max_tokens=1500,
            system=REPLY_SYSTEM.format(
                nom_entreprise=context["nom_entreprise"], metier=context["metier"],
                instruction=instruction),
            messages=[{"role": "user", "content": dernier}],
        )
        texte = _texte_de(msg)
        # ceinture + bretelles : jamais de réplique vide au téléphone
        return texte or instruction


class ResilientLLM:
    """Dégradation gracieuse : si le LLM primaire échoue (réseau coupé, API en panne,
    timeout), l'appel CONTINUE en mode scripté — extraction par règles (MockLLM) et
    répliques = instructions du contrôleur. Moins naturel, jamais muet.

    Chaque dégradation est journalisée et remonte dans le lead
    (`degradations_llm`) : l'artisan a un lead un peu moins bien qualifié,
    nous avons l'alerte monitoring. En prod, s'y ajoutera l'étage voix.
    """

    def __init__(self, primary, fallback=None):
        self.primary = primary
        self.fallback = fallback or MockLLM()
        self.degradations: list[str] = []

    def _degrade(self, quoi: str, exc: Exception) -> None:
        self.degradations.append(f"{quoi}:{type(exc).__name__}")

    def extract(self, utterance: str, context: dict) -> dict:
        try:
            return self.primary.extract(utterance, context)
        except Exception as exc:  # réseau, API, timeout : on ne laisse JAMAIS tomber l'appel
            self._degrade("extract", exc)
            return self.fallback.extract(utterance, context)

    def reply(self, instruction: str, context: dict) -> str:
        try:
            return self.primary.reply(instruction, context)
        except Exception as exc:
            self._degrade("reply", exc)
            return self.fallback.reply(instruction, context)  # = l'instruction, prononçable


def make_llm(mock: bool = False):
    if mock or not os.environ.get("ANTHROPIC_API_KEY"):
        return MockLLM()
    return ResilientLLM(AnthropicLLM())
