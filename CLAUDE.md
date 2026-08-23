# Relais — guide pour Claude (Code ou Cowork)

Agent IA qui répond aux appels manqués des artisans (renvoi conditionnel), qualifie la demande,
réserve un RDV que l'artisan valide en 1 tap avant confirmation SMS au client.
Cible V1 : plombiers/chauffagistes FR. Solo dev : Geoffrey (binôme Claude) ; marketing : son cousin.

## À lire avant toute session

1. `docs/journal.md` — état du projet, décisions, backlog. **Le mettre à jour en fin de session.**
2. `docs/script-conversation-v1.md` — la machine à états S0–S11 et les 9 invariants. Source de vérité.
3. `docs/config-artisan-v1.md` — schéma de config (le LLM ne sait RIEN hors config).

## Commandes

```bash
cd proto
pip install -r requirements.txt     # anthropic, python-dotenv (inutiles en mock)
python run_scenario.py              # suite de non-régression (mock, sans clé, ~2 s) — 18 tests
python run_llm_eval.py --mock       # plomberie de l'éval appelant-simulé (sans clé)
python run_llm_eval.py [--n 3] [--only T05]   # éval LLM réel → evals/results-*.json
python chat.py [--mock]             # conversation interactive (tu joues l'appelant)
python explore.py                   # banc d'essai libre (cas A–F)
```

Clé API : fichier `.env` à la racine (voir `.env.example`). JAMAIS commité, JAMAIS dans le code.

## Règles non négociables

1. **Le LLM ne décide jamais** : transitions, prix, créneaux, promesses viennent du contrôleur
   (`engine.py`) et des listes blanches de la config. Le LLM extrait et formule, c'est tout.
2. **Toute sortie passe par `guards.check_output`** — ne jamais contourner `_say()`.
3. **Aucun changement de prompt ou d'engine sans rejouer `run_scenario.py` en entier.**
4. **Chaque bug trouvé devient un test R<n>** dans `run_scenario.py` avant d'être corrigé
   (le commentaire du test dit qui l'a trouvé et quoi).
5. Annonce IA en ouverture (AI Act art. 50) et téléphone confirmé avant tout RDV : intouchables.
6. Textes agent et code commentés en **français** (produit FR, équipe FR).

## Architecture (proto/)

`engine.py` contrôleur déterministe S0–S11 · `llm.py` extracteur+formuleur (Anthropic/Mock/Resilient,
dégradation gracieuse : jamais muet) · `guards.py` invariants en code · `calendar_stub.py` règles
agenda · `scoring.py` lead + score 0–5 · `config/dupont.json` persona de test de bout en bout.

Pièges connus : les modèles à réflexion adaptative (Sonnet 5) comptent leurs tokens de réflexion
dans `max_tokens` (mettre large) et renvoient des ThinkingBlocks (ne lire que les blocs `text`,
cf. `_texte_de`). Timeout API court (10 s) : au téléphone on dégrade vite plutôt que d'attendre.

## Workflow git

Monorepo, branche `wip` pour l'encours, commit+push à chaque fin de session (2 machines).
`docs/` évolue dans les mêmes commits que le code qu'il spécifie.
