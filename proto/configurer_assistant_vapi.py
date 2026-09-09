#!/usr/bin/env python3
"""Pousse `config/assistant-vapi.json` sur l'assistant Vapi.

    python configurer_assistant_vapi.py              # blanc : montre l'ÉCART, n'écrit rien
    python configurer_assistant_vapi.py --ecrire     # applique (PATCH)
    python configurer_assistant_vapi.py --relever    # imprime la config DISTANTE, brute

Pourquoi ce script existe. Jusqu'au 09/09, la configuration de l'assistant vocal ne vivait
que dans le tableau de bord Vapi. Or elle décide du comportement du produit : la voix, la
langue, ce qui fait RACCROCHER, le barge-in, le prompt système. Un réglage pareil non
versionné n'est ni relisible, ni reproductible, ni comparable — et c'est ainsi que
`endCallPhrases` a pu rester en anglais pendant deux semaines pendant qu'on cherchait
pourquoi personne ne raccrochait.

Le fichier est la source de vérité, ce script n'est qu'un bras. Blanc par défaut, comme
`semer_artisans.py` et `envoyer_un_sms.py` : il ÉCRASE une configuration distante, on doit
pouvoir regarder avant.

DEUX PIÈGES MESURÉS LE 09/09, tous deux coûteux à redécouvrir :

1. **Cloudflare bloque `urllib` sur sa signature par défaut.** Sans en-tête `User-Agent`,
   `api.vapi.ai` répond 403 avec « error code: 1010 » — un code CLOUDFLARE, pas un code
   Vapi. On croit à une clé invalide et on va chercher une clé qui n'a rien. N'importe quel
   UA explicite passe. D'où `EN_TETES` ci-dessous.
2. **La clé attendue est la clé PRIVÉE** (`VAPI_API_KEY`), pas la publique du SDK web.
   Le `.env.example` le disait déjà ; le 403 ci-dessus donne l'illusion du contraire.

Ce script ne touche JAMAIS au fichier de config : la config reste versionnée dans git,
c'est son historique qui répond à « comment l'agent était-il réglé le jour de cet appel ? »
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

RACINE = pathlib.Path(__file__).parent
load_dotenv(RACINE.parent / ".env")

CONFIG = RACINE / "config" / "assistant-vapi.json"
API = "https://api.vapi.ai"

# Les clés qui commencent par « _ » sont des commentaires (convention de `produit.json`) :
# elles ne partent jamais chez Vapi.
def sans_commentaires(obj):
    if isinstance(obj, dict):
        return {k: sans_commentaires(v) for k, v in obj.items()
                if not k.startswith("_")}
    if isinstance(obj, list):
        return [sans_commentaires(v) for v in obj]
    return obj


def en_tetes(cle: str) -> dict:
    # Le User-Agent n'est pas cosmétique : cf. piège n°1 de l'en-tête.
    return {"Authorization": f"Bearer {cle}",
            "Content-Type": "application/json",
            "User-Agent": "nelyo-outillage/1.0"}


def appel(methode: str, chemin: str, cle: str, corps: dict | None = None):
    donnees = json.dumps(corps).encode("utf-8") if corps is not None else None
    req = urllib.request.Request(f"{API}{chemin}", data=donnees,
                                 headers=en_tetes(cle), method=methode)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        # On REND l'erreur de Vapi telle quelle : c'est elle qui connaît son schéma, et un
        # message d'erreur recopié vaut mieux qu'un schéma que nous aurions deviné.
        print(f"❌ {methode} {chemin} → HTTP {exc.code}\n   {detail}", file=sys.stderr)
        if exc.code == 403 and "1010" in detail:
            print("   (403 + 1010 = Cloudflare, pas Vapi : c'est le User-Agent, "
                  "pas la clé)", file=sys.stderr)
        raise SystemExit(2) from exc


def _court(valeur, maxi: int = 220) -> str:
    """Une valeur lisible dans un écart. Le prompt anglais par défaut de Vapi fait 6 000
    caractères : l'afficher en entier noie les sept autres différences, qui sont celles
    qu'on doit voir."""
    t = json.dumps(valeur, ensure_ascii=False)
    return t if len(t) <= maxi else f"{t[:maxi]}… (+{len(t) - maxi} caractères)"


def ecart(distant: dict, voulu: dict, chemin: str = "") -> list[str]:
    """Les champs que le PATCH changerait, et eux seuls.

    On ne compare que ce que le fichier prétend décider : tout le reste de l'objet
    distant (identifiants, dates, réglages que nous ne pilotons pas) est hors sujet, et
    l'afficher noierait le seul écart qui compte.
    """
    lignes = []
    for cle, veut in voulu.items():
        ici = f"{chemin}.{cle}" if chemin else cle
        a = distant.get(cle)
        if isinstance(veut, dict) and isinstance(a, dict):
            lignes += ecart(a, veut, ici)
        elif a != veut:
            lignes.append(f"  {ici}\n      distant : {_court(a)}"
                          f"\n      voulu   : {_court(veut)}")
    return lignes


PRIVE = ("localhost", "127.", "0.0.0.0", "10.", "192.168.", "172.16.", "172.17.",
         "172.18.", "172.19.", "172.2", "172.30.", "172.31.", "[::1]", ".local")


def url_injoignable(base: str) -> str | None:
    """Pourquoi Vapi ne pourrait PAS joindre cette URL, ou None si elle est plausible.

    Garde ajouté après une frayeur du 09/09 : `RELAIS_BASE_URL` valait
    `http://192.168.1.175:8000` — parfaitement correct pour son autre usage (les liens
    SMS ouverts depuis le réseau local), et parfaitement injoignable depuis Vapi. Poussée
    telle quelle, elle aurait cassé la voix en silence : l'assistant aurait appelé une
    adresse privée, et l'appel serait mort sans trace côté serveur.

    Une variable qui sert à deux choses finit par en trahir une. On refuse plutôt que de
    deviner.
    """
    if not base.startswith(("http://", "https://")):
        return "ce n'est pas une URL http(s)"
    hote = base.split("://", 1)[1].split("/", 1)[0]
    if any(hote.startswith(p) or hote.endswith(p) for p in PRIVE):
        return f"« {hote} » est une adresse PRIVÉE : Vapi ne peut pas l'atteindre"
    if base.startswith("http://"):
        return "Vapi exige https pour un custom LLM (et un secret en clair sur http)"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ecrire", action="store_true",
                    help="applique réellement (PATCH). Sans ça : blanc.")
    ap.add_argument("--relever", action="store_true",
                    help="imprime la configuration DISTANTE brute et s'arrête")
    ap.add_argument("--assistant", help="identifiant Vapi (défaut : le seul existant)")
    ap.add_argument("--url", help="URL PUBLIQUE de notre serveur (tunnel ou PaaS). "
                                 "Prime sur RELAIS_BASE_URL, qui sert aussi aux liens "
                                 "SMS et vaut souvent une adresse locale.")
    args = ap.parse_args()

    cle = os.environ.get("VAPI_API_KEY", "")
    if not cle:
        print("VAPI_API_KEY absente du .env — clé PRIVÉE, tableau de bord Vapi > API Keys",
              file=sys.stderr)
        return 2

    assistants = appel("GET", "/assistant", cle)
    if args.assistant:
        distant = next((a for a in assistants if a["id"] == args.assistant), None)
        if distant is None:
            print(f"aucun assistant {args.assistant!r}", file=sys.stderr)
            return 2
    elif len(assistants) == 1:
        distant = assistants[0]
    else:
        print(f"{len(assistants)} assistants — préciser --assistant :", file=sys.stderr)
        for a in assistants:
            print(f"   {a['id']}  {a.get('name')!r}", file=sys.stderr)
        return 2

    if args.relever:
        print(json.dumps(distant, ensure_ascii=False, indent=2))
        return 0

    voulu = sans_commentaires(json.loads(CONFIG.read_text(encoding="utf-8")))

    # L'URL de notre serveur n'est PAS dans le fichier : elle change à chaque tunnel, et
    # la figer ferait d'un fichier versionné un fichier périmé. RELAIS_BASE_URL décide.
    base = (args.url or os.environ.get("RELAIS_BASE_URL") or "").rstrip("/")
    marqueur = "«RELAIS_BASE_URL»"
    if marqueur in voulu.get("model", {}).get("url", ""):
        if not base:
            print("Aucune URL : passer --url, ou renseigner RELAIS_BASE_URL.\n"
                  "   C'est l'URL PUBLIQUE de notre serveur (tunnel en dév, PaaS ensuite).",
                  file=sys.stderr)
            return 2
        if (pourquoi := url_injoignable(base)):
            print(f"URL refusée : {base}\n   {pourquoi}\n"
                  f"   Passer --url avec l'adresse publique du tunnel. Pousser celle-ci "
                  f"casserait la voix sans laisser de trace côté serveur.",
                  file=sys.stderr)
            return 2
        voulu["model"]["url"] = voulu["model"]["url"].replace(marqueur, base)

    print(f"assistant {distant['id']}  {distant.get('name')!r}")
    print(f"custom LLM → {voulu['model']['url']}")
    lignes = ecart(distant, voulu)
    if not lignes:
        print("\n✅ la configuration distante est déjà celle du fichier")
        return 0

    print(f"\n{len(lignes)} champ(s) à changer :")
    for l in lignes:
        print(l)

    if not args.ecrire:
        print("\n⚪ BLANC — rien n'a été envoyé. Relancer avec --ecrire pour appliquer.")
        return 0

    appel("PATCH", f"/assistant/{distant['id']}", cle, voulu)
    print("\n✅ appliqué. Vérifier par --relever, puis PASSER UN APPEL : "
          "la voix, le raccrochage et le barge-in ne se vérifient qu'à l'oreille.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
