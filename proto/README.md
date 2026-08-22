# proto/ — Prototype texte de l'agent Relais

Valide la logique conversationnelle (machine à états, slots, garde-fous, scoring)
**avant** toute brique vocale ou téléphonique. Cf. `docs/script-conversation-v1.md`.

## Lancer

```bash
pip install -r requirements.txt      # anthropic + python-dotenv (optionnels en mode mock)

python run_scenario.py               # smoke tests scriptés (mode mock, sans clé API)
python chat.py --mock                # conversation interactive, LLM simulé
python chat.py                       # conversation interactive, vrai LLM (ANTHROPIC_API_KEY requis)
```

La clé API se met dans un fichier `.env` à la racine du repo (voir `.env.example`) — jamais commité.

## Architecture (miroir de la future prod)

| Fichier | Rôle |
|---|---|
| `relais_proto/engine.py` | **Le contrôleur** : états S0–S11, transitions, remplissage de slots. Déterministe. |
| `relais_proto/llm.py` | Le LLM en 2 rôles étroits : extracteur de slots + formuleur. `MockLLM` = mode sans réseau. |
| `relais_proto/guards.py` | Invariants appliqués en code sur chaque sortie : prix liste blanche, « confirmé » interdit, diagnostic interdit. |
| `relais_proto/calendar_stub.py` | Faux calendrier appliquant les vraies règles agenda (fenêtres, urgences 2/j, durées). |
| `relais_proto/scoring.py` | Lead + score 0–5 + raisons affichables, post-appel. |
| `config/dupont.json` | Config « Dupont Chauffage » (persona de test des specs). |
| `run_scenario.py` | Smoke tests : T01, T02, T11 + garde-fou prix (T05 partiel). |

Principe central : **le LLM ne décide jamais** — ni la transition, ni un prix, ni un créneau,
ni une promesse. Il met en mots ce que le contrôleur a décidé, et `guards.check_output`
vérifie derrière (violation ⇒ formulation de repli sûre + log).

## État au 21/08/2026

- ✅ Chemin nominal complet (T01 : urgence fuite → RDV réservé, score 5, SMS annoncé)
- ✅ Hors zone (T02), refus de numéro → repli propre (T11), garde-fou prix/« confirmé » (T05)
- ⬜ À couvrir : T03–T04, T06–T10, T12 (scénarios restants de `docs/scenarios-test-v1.md`)
- ⬜ Mode LLM réel à éprouver (les smoke tests tournent en mock)
- ⬜ Persistance des leads (pour l'instant : `last_lead.json`)
