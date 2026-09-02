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
python run_scenario.py              # suite de non-régression (mock, sans clé, ~3 s) — 84 tests
python run_llm_eval.py --mock       # plomberie de l'éval appelant-simulé (sans clé)
python run_extract_eval.py [--mock] [--only plus_tot]
                                    # tests unitaires d'EXTRACTION : (phrase + contexte)
                                    # → action attendue du menu (actions.py). C'est ICI
                                    # qu'on encode les tournures, jamais dans le moteur.
                                    # --mock ne mesure QUE la plomberie. Sort 2 si les
                                    # appels ont échoué : « ça n'a pas marché » ne doit
                                    # pas se lire comme « le modèle n'a pas compris ».
                                    # Couvre les ACTIONS (menu de S5) et les FAITS
                                    # (veut_humain, telephone_rappel) sur deux contextes.
                                    # 02/09 : 47/49 avec Haiku. Les 2 échecs sont des
                                    # violations MESURÉES du modèle sur le numéro
                                    # (8 chiffres rendus en 10, 12 rendus en 10) —
                                    # renforcer le prompt n'y change rien, seul le
                                    # contrôle de `_numero_suspect` protège.
python run_llm_eval.py [--n 3] [--only T05]   # éval LLM réel → evals/results-*.json
                                    # 19 personas, dont 5 tirés d'appels vocaux RÉELS
                                    # RELAIS_MODEL = l'agent, RELAIS_MODEL_APPELANT
                                    # = l'appelant simulé (à garder FIXE pour comparer)
                                    # RELAIS_MODEL_EXTRACTEUR / _FORMULEUR : les deux
                                    # rôles se règlent séparément (défaut : RELAIS_MODEL).
                                    # Mesuré le 01/09 sur run_extract_eval : Haiku et
                                    # Sonnet à 36/36, p50 1,05 s contre 2,62 s et p95
                                    # 2,1 s contre 7,0 s → l'extracteur reste HAIKU.
                                    # Le banc est au plafond : il ne peut pas justifier le
                                    # changement, il ne prouve pas que Sonnet n'aiderait
                                    # jamais. À rejouer quand le banc grossit.
python chat.py [--mock]             # conversation interactive (tu joues l'appelant)
python explore.py                   # banc d'essai libre (cas A–F)
uvicorn serveur:app --port 8000     # API HTTP (DATABASE_URL, RELAIS_WEBHOOK_SECRET,
                                    #           RELAIS_BASE_URL)
                                    # ⚠️ PAS de --reload : un `git pull` n'a AUCUN effet
                                    # sur le processus en cours. Redémarrer uvicorn après
                                    # chaque changement — le tunnel, lui, n'a rien à voir.
curl localhost:8000/sante           # dit la RÉVISION qui tourne vraiment (R65).
                                    # À travers le tunnel aussi : si les deux diffèrent,
                                    # c'est le routage ; si les deux sont vieilles,
                                    # uvicorn n'a pas été redémarré.
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

1. **Le LLM ne décide jamais ce qui ENGAGE** : transitions, prix, créneaux, promesses
   viennent du contrôleur (`engine.py`) et des listes blanches de la config.
   **Mais c'est le LLM qui COMPREND** (décidé le 01/09, après R68/R70/R71 : trois défauts
   nés de listes de mots-clés dans le contrôleur qui tenaient lieu de compréhension).
   Chaque état expose un menu d'actions FERMÉ (`actions.py`) ; l'extracteur reçoit le
   contexte et rend UNE action de ce menu, ou `pas_clair` ; le contrôleur valide contre le
   menu et les invariants, puis exécute. **Le contrôleur ne fait plus de correspondance de
   texte** — pas un `in`, pas une liste de tournures. Les mots-clés vivent dans `MockLLM`,
   qui est un harnais de test, et les mille formulations dans `run_extract_eval.py`.
   Une tournure ratée en appel réel devient une ligne d'éval, JAMAIS une ligne de moteur.
2. **Toute sortie passe par `guards.check_output`** — ne jamais contourner `_say()`.
   **Et les garde-fous ne voient pas tout : ils vérifient un contenu INTERDIT, jamais la
   FIDÉLITÉ à l'instruction.** Le 02/09, le formuleur a transformé « redonnez-moi le bon
   numéro ? » en « quel est votre problème avec votre plomberie ? » — formellement
   irréprochable, conversationnellement désastreux. D'où la frontière (R76) : **demander
   un CHAMP précis (commune, code postal, numéro, confirmation) est VERBATIM ; RÉPONDRE à
   ce que l'appelant vient de dire reste au formuleur.** Une question qui vise une donnée
   n'a rien à gagner d'une reformulation, et tout à y perdre.
   Vaut aussi pour l'écrit : les SMS passent par `guards` avant d'entrer en file (`messages.py`).
   **Le contrôleur ÉNONCE les faits, le formuleur DEMANDE** (R63) : une réplique formulée
   ne peut contenir ni chiffre, ni jour, ni nom propre hors liste blanche. Ce qui énonce un
   fait est `verbatim=True` ; ce qui pose une question est laissé au modèle.
3. **Aucun changement de prompt ou d'engine sans rejouer `run_scenario.py` en entier.**
4. **Chaque bug trouvé devient un test R<n>** dans `run_scenario.py` avant d'être corrigé
   (le commentaire du test dit qui l'a trouvé et quoi).
5. Annonce IA en ouverture (AI Act art. 50) et téléphone confirmé avant tout RDV : intouchables.
5bis. **Jamais de repli « on vous rappelle » tant que l'appelant coopère.** Une CONTRAINTE
   (« pas le samedi ») coopère autant qu'un silence : elle ne consomme pas le quota de
   l'invariant n°6, qui borne la NÉGOCIATION — le nombre de fois où l'on fait défiler le
   calendrier devant quelqu'un qui dit non. Une contrainte ne fait pas défiler le
   calendrier, elle le RESSERRE (R72). Une
   incompréhension déclenche une CLARIFICATION, pas un abandon. Le 01/09, deux « le plus
   vite possible » d'un client pressé et coopérant ont suffi à convertir une réservation
   en rappel à faire. `pas_clair` fait répéter, puis reprend le fil en reproposant ; le
   repli reste borné par l'invariant n°6, qui borne la NÉGOCIATION, pas l'écoute.
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
`session.py` sessions artisan par cookie · `vapi.py` adaptateur de la plateforme
vocale (traduit, ne décide rien ; porte aussi le format de fil SSE — lire son en-tête
avant de toucher au chantier voix) · `sonde_voix.py` sonde de diagnostic de l'étape 0
(hors produit, éteinte par défaut : `RELAIS_SONDE_VOIX`) · `sonde_dispo.py` sonde des
TOURNURES DE TEMPS : une ligne par tour disant ce que l'appelant a dit, ce que
l'extracteur en a retenu et ce que le contrôleur en a tiré — de quoi distinguer
« le LLM a laissé tomber » de « notre code est sourd » (hors produit, éteinte par
défaut : `RELAIS_SONDE_DISPO`) · `connexion.py` code SMS à 6 chiffres (empreinte
seule, essais comptés, un seul code vivant) · `serveur.py` câblage de production ·
`worker.py` un passage des workers de fond. **L'API ne décide jamais** — corollaire
backend de la règle n°1 : elle transporte et persiste, le métier reste dans engine/rdv.

`actions.py` le MENU d'actions fermé par état, la validation, et le bout de prompt qui le
décrit — une seule source pour ce que le modèle peut proposer et ce que le code accepte ·
`engine.py` contrôleur déterministe S0–S11 · `llm.py` extracteur+formuleur (Anthropic/Mock/Resilient,
dégradation gracieuse : jamais muet) · `guards.py` invariants en code · `calendar_stub.py` règles
agenda · `scoring.py` lead + score 0–5 · `produit.py` config PRODUIT — nom visible
(**Nelyo**) et expéditeur SMS unique (**nelyo**), contraintes AF2M vérifiées au
démarrage ; « Relais » reste le nom de CODE (repo, modules, tables) ·
`temps.py` instants UTC vs heures de pendule (règle n°7,
à lire avant de toucher à une échéance) · `nombres.py` nombres PRONONCÉS en toutes
lettres → chiffres (code postal, téléphone ; déterministe, jamais confié au LLM) ·
`communes.py` table des communes + normalisation, partagée par le contrôleur ET les
garde-fous · `config/dupont.json` persona de test de bout en bout.

Pièges connus : les modèles à réflexion adaptative (Sonnet 5) comptent leurs tokens de réflexion
dans `max_tokens` (mettre large) et renvoient des ThinkingBlocks (ne lire que les blocs `text`,
cf. `_texte_de`). Timeout API court (10 s) : au téléphone on dégrade vite plutôt que d'attendre.

## Workflow git

Monorepo, branche `wip` pour l'encours, commit+push à chaque fin de session (2 machines).
`docs/` évolue dans les mêmes commits que le code qu'il spécifie.
