#!/usr/bin/env python3
"""Éval en mode LLM RÉEL : un appelant simulé (LLM qui joue un persona) contre l'agent.

Usage (sur ta machine, clé API dans le .env à la racine du repo) :
    python run_llm_eval.py              # tous les personas, 1 répétition
    python run_llm_eval.py --n 3        # 3 répétitions par persona (variabilité LLM)
    python run_llm_eval.py --only T05   # un seul persona
    python run_llm_eval.py --mock       # test de plomberie sans clé (appelant scripté)

Sortie : evals/results-<horodatage>.json (verdicts + transcripts + leads complets)
         → à faire lire à Claude pour analyse/corrections. Résumé lisible en console.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

try:
    from dotenv import load_dotenv
    # override=True : le .env du repo fait foi, même si une ANTHROPIC_API_KEY
    # traîne dans les variables d'environnement Windows (setx d'un ancien essai)
    load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env", override=True)
except ImportError:
    pass

from relais_proto import produit
from relais_proto.engine import Conversation
from relais_proto.llm import AnthropicLLM, MockLLM, ResilientLLM, _texte_de
from relais_proto.scoring import build_lead

_DOSSIER_CONFIG = pathlib.Path(__file__).parent / "config"
CFG = produit.appliquer(
    json.loads((_DOSSIER_CONFIG / "dupont.json").read_text(encoding="utf-8")),
    produit.charger(_DOSSIER_CONFIG))

MAX_TOURS = 14  # garde-fou anti-boucle

# ---------------------------------------------------------------- personas
# `attendu` : mêmes clés que run_scenario + tous vérifiés mécaniquement sur le lead.
# `script`  : lignes de repli pour --mock (test de plomberie sans clé).
PERSONAS = {
    "T01_urgence_fuite": {
        "role": ("Mme Garcia, 52 ans, stressée. Fuite sous l'évier de la cuisine, l'eau "
                 "goutte encore dans le placard. Tu habites Nogent-sur-Marne (94130), "
                 "propriétaire. Tu veux quelqu'un vite. Tu donnes ton 06 12 34 56 78 sans "
                 "difficulté si on te le demande. Dispo quand on veut, tu es chez toi."),
        "cache": "Tu n'as PAS coupé l'arrivée d'eau — tu ne sais pas où c'est. Ne le dis que si on t'en parle.",
        "attendu": {"score": 5, "categorie": "rdv_reserve", "rdv": True},
        "script": ["J'ai une fuite sous l'évier, l'eau coule, c'est urgent !", "Nogent-sur-Marne 94130, propriétaire",
                   "Garcia, 06 12 34 56 78", "Oui", "Le premier"],
    },
    "T02_hors_zone": {
        "role": ("M. Lefèvre, calme et réfléchi. Tu veux un devis pour remplacer ta chaudière "
                 "fioul par une pompe à chaleur. Tu habites Champigny-sur-Marne (94500). "
                 "Échéance : avant l'hiver."),
        "cache": "Tu ne donnes ton code postal que si on te le demande explicitement.",
        "attendu": {"score": 0, "categorie": "hors_zone", "rdv": False},
        "script": ["Je voudrais un devis pour une pompe à chaleur", "Champigny, 94500"],
    },
    "T03_entretien_samedi_prix": {
        "role": ("M. Diallo, organisé. Tu veux l'entretien annuel de ta chaudière à Nogent "
                 "(94130). Tu demandes LE PRIX dès le début et tu ne peux QUE le samedi matin. "
                 "Ton numéro : 07 88 11 22 33. Tu acceptes un créneau du samedi matin."),
        "cache": "Si on te propose un créneau en semaine, refuse : samedi matin uniquement.",
        "attendu": {"score": 4, "categorie": "rdv_reserve", "rdv": True},
        "script": ["Je veux un entretien de chaudière, c'est combien ?", "Nogent 94130",
                   "Diallo, 07 88 11 22 33", "Oui", "Le premier"],
    },
    "T05_chasse_au_prix": {
        "role": ("M. Katz, pressant. WC bouché à Créteil (94000). Tu veux un PRIX, tu insistes "
                 "sous plusieurs formes : 'en gros ?', 'une fourchette ?', 'le minimum ?', "
                 "'chez les autres c'est 150 €'. Tu finis quand même par prendre le RDV. "
                 "Numéro : 06 99 88 77 66."),
        "cache": "Insiste sur le prix au moins 3 fois avant de lâcher l'affaire.",
        "attendu": {"score": 5, "categorie": "rdv_reserve", "rdv": True},  # WC urgent + RDV = 5
        "script": ["Mes WC sont bouchés, c'est urgent, c'est combien ?", "Créteil 94000", "Et en gros ça coûte ?",
                   "Katz, 06 99 88 77 66", "Oui", "Le premier"],
    },
    "T07_client_furieux": {
        "role": ("M. Brun, EN COLÈRE. Une intervention de la semaine dernière refuit déjà. "
                 "Tu veux 'Julien au téléphone, pas un robot'. Tu le redemandes avec insistance "
                 "au moins deux fois. Tu ne veux PAS prendre de nouveau rendez-vous payant."),
        "cache": "Ne te calme que si on te promet une prise en charge prioritaire.",
        "attendu": {"score": 1, "categorie": "prioritaire", "rdv": False},
        "script": ["Je veux parler à Julien, votre intervention refuit déjà !",
                   "Non, un humain, pas une machine !"],
    },
    "T11_refus_numero": {
        "role": ("Tu as une petite fuite au robinet à Nogent (94130). Tu es coopératif sur "
                 "tout SAUF ton numéro de téléphone : tu refuses de le donner ('je rappellerai'). "
                 "Tu refuses jusqu'au bout."),
        "cache": "Aucune insistance ne te fera donner ton numéro.",
        "attendu": {"score": 1, "categorie": "a_rappeler", "rdv": False},
        "script": ["Petite fuite au robinet de la cuisine", "Nogent 94130",
                   "Non ça peut attendre", "Non je préfère pas donner mon numéro",
                   "Non vraiment pas"],
    },
    "R09_commune_sans_cp": {
        "role": ("Mme Petit. Ton chauffe-eau ne chauffe plus, à Saint-Maur. Tu ne connais pas "
                 "ton code postal par cœur — tu dis juste 'Saint-Maur' et tu ne donnes JAMAIS "
                 "de code postal. Numéro : 06 44 55 66 77. Urgent : plus d'eau chaude depuis hier."),
        "cache": "Si on te demande ton code postal, dis que tu ne le connais pas, juste 'Saint-Maur'.",
        "attendu": {"score": 5, "categorie": "rdv_reserve", "rdv": True, "cp": "94100"},
        "script": ["Mon chauffe-eau ne marche plus, c'est urgent", "Je suis à Saint-Maur",
                   "Petit, 06 44 55 66 77", "Oui", "Le premier"],
    },
    "T08_aspirateur_infos": {
        "role": ("Un appelant curieux (peut-être un concurrent). Tu poses des questions sur "
                 "l'entreprise : combien de techniciens, où habite Julien, ça marche bien "
                 "niveau chiffre d'affaires, quels outils ils utilisent. Tu ne demandes "
                 "JAMAIS d'intervention et tu finis par raccrocher (dis 'FIN')."),
        "cache": "Ne révèle jamais ton propre nom ni un numéro.",
        "attendu": {"rdv": False},  # tolérant sur score/catégorie ; l'important : violations=0
        "script": ["Vous avez combien de techniciens ?", "Et Julien il habite où ?", "FIN"],
    },
}

CALLER_SYSTEM = """Tu joues un APPELANT au téléphone d'un artisan. Ton personnage :
{role}
Information cachée (ne la révèle que si la conversation l'amène) : {cache}

Règles :
- Réponds UNIQUEMENT ta prochaine réplique d'appelant. Courte, orale, naturelle. Pas de guillemets.
- Ne facilite pas la tâche de l'agent : réponds à ce qu'on te demande, sans anticiper le reste.
- Reste dans ton personnage du début à la fin.
- Quand l'agent a clairement conclu l'appel (au revoir, récapitulatif final), réponds exactement : FIN"""


class CallerLLM:
    """L'appelant simulé (LLM)."""

    # Variable PROPRE à l'appelant, distincte de `RELAIS_MODEL` qui pilote l'agent.
    # Sans ça, faire varier le modèle de l'agent changeait aussi celui de l'appelant :
    # deux runs n'étaient pas comparables, puisque l'énoncé bougeait avec la copie.
    MODELE_DEFAUT = "claude-sonnet-5"

    def __init__(self, persona: dict, model: str | None = None):
        import os

        import anthropic
        self.client = anthropic.Anthropic(timeout=30.0, max_retries=2)
        self.model = model or os.environ.get("RELAIS_MODEL_APPELANT", self.MODELE_DEFAUT)
        self.system = CALLER_SYSTEM.format(role=persona["role"], cache=persona["cache"])

    def next_line(self, transcript: list[tuple[str, str]]) -> str:
        # du point de vue de l'appelant : l'agent est "user", l'appelant est "assistant"
        messages = []
        for who, texte in transcript:
            role = "user" if who == "agent" else "assistant"
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] += "\n" + texte
            else:
                messages.append({"role": role, "content": texte})
        # RÉFLEXION DÉSACTIVÉE, et c'est une question de validité de l'éval, pas de coût.
        # Sonnet 5 réfléchit par défaut même sans paramètre, et ses tokens de réflexion
        # sont décomptés de `max_tokens` : à 1000 tokens pour produire UNE réplique, la
        # réflexion pouvait tout consommer et rendre un texte vide — que `run_one` prend
        # pour une fin d'appel. On fabriquait des FAIL avec le harnais.
        # Un appelant qui joue un personnage en une phrase n'a rien à en tirer.
        msg = self.client.messages.create(
            model=self.model, max_tokens=1000, system=self.system, messages=messages,
            thinking={"type": "disabled"})
        return _texte_de(msg)


class ScriptedCaller:
    """Repli --mock : rejoue les lignes scriptées (test de plomberie sans clé)."""

    def __init__(self, persona: dict):
        self.lignes = list(persona["script"])

    def next_line(self, transcript) -> str:
        return self.lignes.pop(0) if self.lignes else "FIN"


def verdict(lead: dict, attendu: dict) -> tuple[bool, list[str], list[str]]:
    problemes, warns = [], []
    for cle in ("score", "categorie"):
        if cle in attendu and lead[cle] != attendu[cle]:
            problemes.append(f"{cle}={lead[cle]} (attendu {attendu[cle]})")
    if "rdv" in attendu and bool(lead["rdv"]) != attendu["rdv"]:
        problemes.append(f"rdv={'oui' if lead['rdv'] else 'non'} (attendu {attendu['rdv']})")
    if "cp" in attendu and lead["slots"].get("code_postal") != attendu["cp"]:
        problemes.append(f"cp={lead['slots'].get('code_postal')} (attendu {attendu['cp']})")
    # une violation INTERCEPTÉE (le client a entendu le repli correct) = le garde-fou
    # a fait son travail → WARN (à surveiller : c'est le formuleur qui dérape), pas FAIL
    if lead["violations_gardes_fous"]:
        warns.append(f"violations interceptées : {lead['violations_gardes_fous']}")
    return (not problemes), problemes, warns


def run_one(nom: str, persona: dict, mock: bool) -> dict:
    agent_llm = MockLLM() if mock else ResilientLLM(AnthropicLLM())
    caller = ScriptedCaller(persona) if mock else CallerLLM(persona)
    convo = Conversation(CFG, agent_llm)
    convo.open()
    for _ in range(MAX_TOURS):
        if convo.state.value in ("S11", "FIN"):
            break
        ligne = caller.next_line(convo.transcript).strip()
        if ligne == "FIN" or not ligne:
            break
        convo.process(ligne)
    lead = build_lead(convo)
    ok, problemes, warns = verdict(lead, persona["attendu"])
    return {"persona": nom, "pass": ok, "problemes": problemes, "warns": warns,
            "tours": sum(1 for w, _ in convo.transcript if w == "client"),
            "lead": lead}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1, help="répétitions par persona")
    ap.add_argument("--only", help="ne jouer qu'un persona (préfixe accepté, ex. T05)")
    ap.add_argument("--mock", action="store_true", help="plomberie sans clé API")
    args = ap.parse_args()

    cibles = {k: v for k, v in PERSONAS.items()
              if not args.only or k.startswith(args.only)}
    if not cibles:
        print(f"Aucun persona ne correspond à '{args.only}'"); return 2

    resultats, echecs = [], 0
    for nom, persona in cibles.items():
        for i in range(args.n):
            # UN incident réseau ne doit pas détruire le passage entier. L'agent a sa
            # dégradation gracieuse (`ResilientLLM`) ; le harnais n'avait rien, et une
            # coupure a emporté 25 minutes de mesures déjà acquises le 25/08. Une
            # conversation perdue est un résultat manquant, pas une suite perdue.
            try:
                r = run_one(nom, persona, args.mock)
            except Exception as exc:  # noqa: BLE001 — poursuivre, quoi qu'il arrive
                r = {"persona": nom, "pass": False, "tours": 0, "lead": None,
                     "warns": [], "problemes": [f"{type(exc).__name__}: {exc}"],
                     "erreur_harnais": True}
            resultats.append(r)
            tag = "✅ PASS" if r["pass"] else "❌ FAIL " + "; ".join(r["problemes"])
            if r["warns"]:
                tag += "  ⚠ " + "; ".join(r["warns"])
            print(f"{nom} [{i + 1}/{args.n}] ({r['tours']} tours) : {tag}")
            if not r["pass"]:
                echecs += 1

    # Les résultats sont écrits même si tout n'a pas abouti : un passage partiel se
    # lit, un passage perdu ne se lit pas.
    outdir = pathlib.Path(__file__).parent.parent / "evals"
    outdir.mkdir(exist_ok=True)
    horodatage = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = outdir / f"results-{horodatage}.json"
    import os
    # Les MODÈLES sont consignés : sans eux, deux fichiers de résultats ne se comparent
    # pas — on ne saurait pas si un écart vient de l'agent ou de l'appelant.
    out.write_text(json.dumps({
        "horodatage": horodatage, "mode": "mock" if args.mock else "llm",
        "modele_agent": None if args.mock else os.environ.get(
            "RELAIS_MODEL", "claude-haiku-4-5"),
        "modele_appelant": None if args.mock else os.environ.get(
            "RELAIS_MODEL_APPELANT", CallerLLM.MODELE_DEFAUT),
        "total": len(resultats), "echecs": echecs, "runs": resultats,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    incidents = sum(1 for r in resultats if r.get("erreur_harnais"))
    if incidents:
        print(f"\n⚠️  {incidents} conversation(s) perdue(s) par un incident du HARNAIS "
              f"(réseau, API) — à ne pas confondre avec un défaut de l'agent.")
    print(f"\n{len(resultats) - echecs}/{len(resultats)} PASS → {out}")
    print("→ dis à Claude de lire ce fichier pour l'analyse.")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
