# Relais — guide pour Claude (Code ou Cowork)

Agent IA qui répond aux appels manqués des artisans (renvoi conditionnel), qualifie la demande,
réserve un RDV que l'artisan valide en 1 tap avant confirmation SMS au client.
Cible V1 : plombiers/chauffagistes FR. Solo dev : Geoffrey (binôme Claude) ; marketing : son cousin.

## À lire avant toute session

1. `docs/journal.md` — commencer par le bloc **« ÉTAT AU … »** en tête (où-on-en-est,
   à REMPLACER en fin de session) ; les entrées datées en dessous sont le pourquoi.
2. `docs/script-conversation-v1.md` — la machine à états S0–S11 et les 9 invariants. Source de vérité.
3. `docs/config-artisan-v1.md` — schéma de config (le LLM ne sait RIEN hors config).

## Commandes

```bash
cd proto
pip install -r requirements.txt     # anthropic, python-dotenv (inutiles en mock)
python run_scenario.py              # suite de non-régression (mock, sans clé, ~3 s) — 32 tests
python run_llm_eval.py --mock       # plomberie de l'éval appelant-simulé (sans clé)
python run_llm_eval.py [--n 3] [--only T05]   # éval LLM réel → evals/results-*.json
python chat.py [--mock]             # conversation interactive (tu joues l'appelant)
python explore.py                   # banc d'essai libre (cas A–F)
uvicorn serveur:app --port 8000     # API HTTP (DATABASE_URL, RELAIS_WEBHOOK_SECRET,
                                    #           RELAIS_BASE_URL)
python worker.py [--a-vide]         # un passage : expiration puis expédition (cron).
                                    # RELAIS_SMS=journal (défaut, rien ne part) | ovh
python semer_artisans.py [--ecrire] # ecrit config/artisans.json dans la table `artisan`
                                    # (blanc par defaut). La table EST le registre.
python envoyer_un_sms.py <num> [--envoyer]   # premier envoi REEL, a la main
                                    # (blanc par defaut : n'envoie rien)
python run_depot_pg.py [--migrer] [--autoriser-truncate]   # contrat du port Depot
                                    # contre un vrai Postgres. DATABASE_URL (directe) puis
                                    # DATABASE_URL_POOLER en repli. Tronque les tables :
                                    # exige un marqueur en base, posé 1 fois. Sort 2 si rien testé.
```

Clé API : fichier `.env` à la racine (voir `.env.example`). JAMAIS commité, JAMAIS dans le code.

## Règles non négociables

1. **Le LLM ne décide jamais** : transitions, prix, créneaux, promesses viennent du contrôleur
   (`engine.py`) et des listes blanches de la config. Le LLM extrait et formule, c'est tout.
2. **Toute sortie passe par `guards.check_output`** — ne jamais contourner `_say()`.
   Vaut aussi pour l'écrit : les SMS passent par `guards` avant d'entrer en file (`messages.py`).
3. **Aucun changement de prompt ou d'engine sans rejouer `run_scenario.py` en entier.**
4. **Chaque bug trouvé devient un test R<n>** dans `run_scenario.py` avant d'être corrigé
   (le commentaire du test dit qui l'a trouvé et quoi).
5. Annonce IA en ouverture (AI Act art. 50) et téléphone confirmé avant tout RDV : intouchables.
6. Textes agent et code commentés en **français** (produit FR, équipe FR).
7. **Un horodatage est un INSTANT en UTC ; une heure écrite dans la config est une heure de
   PENDULE** (`temps.py`). Jamais de `datetime.now()` hors `api.py`/`worker.py`, jamais
   d'arithmétique sur un aware en heure locale, et toute règle qui parle d'heures convertit
   d'abord (`temps.en_local`). Verrouillé par R25.

## Architecture (proto/)

`rdv.py` cycle de vie du RDV (tampon→validé/refusé/expiré, horloge injectée) · `depot.py` port de
persistance + implémentation mémoire · `depot_pg.py` adaptateur Postgres · `expiration.py` worker
(effets idempotents AVANT le changement d'état) · `messages.py` file sortante, templates fermés.
`contrat_depot.py` : suite de contrat jouée contre les DEUX implémentations du port.
`api.py` façade HTTP (deux portes d'auth : secret webhook pour la plateforme vocale,
token porteur pour l'app artisan) · `registre.py` artisans + numéros Relais, chargé depuis
la **table `artisan`** (la config reste un fichier versionné) ·
`confirmation.py` jetons du lien de validation client (empreinte seule en base) ·
`envoi.py` plage de silence + réessais + port fournisseur (aucun câblé : `EnvoyeurJournal`) ·
`pages.py` pages HTML (client + boîte de validation artisan, sans JS ni ressource externe) ·
`session.py` sessions artisan par cookie · `connexion.py` code SMS à 6 chiffres (empreinte
seule, essais comptés, un seul code vivant) · `serveur.py` câblage de production ·
`worker.py` un passage des workers de fond. **L'API ne décide jamais** — corollaire
backend de la règle n°1 : elle transporte et persiste, le métier reste dans engine/rdv.

`engine.py` contrôleur déterministe S0–S11 · `llm.py` extracteur+formuleur (Anthropic/Mock/Resilient,
dégradation gracieuse : jamais muet) · `guards.py` invariants en code · `calendar_stub.py` règles
agenda · `scoring.py` lead + score 0–5 · `temps.py` instants UTC vs heures de pendule (règle n°7,
à lire avant de toucher à une échéance) · `config/dupont.json` persona de test de bout en bout.

Pièges connus : les modèles à réflexion adaptative (Sonnet 5) comptent leurs tokens de réflexion
dans `max_tokens` (mettre large) et renvoient des ThinkingBlocks (ne lire que les blocs `text`,
cf. `_texte_de`). Timeout API court (10 s) : au téléphone on dégrade vite plutôt que d'attendre.

## Workflow git

Monorepo, branche `wip` pour l'encours, commit+push à chaque fin de session (2 machines).
`docs/` évolue dans les mêmes commits que le code qu'il spécifie.
