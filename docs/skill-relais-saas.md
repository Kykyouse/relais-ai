---
name: relais-saas
description: >-
  Contexte complet du projet Relais — le SaaS de Geoffrey (avec son cousin) : agent IA qui
  répond aux appels manqués des artisans (plombiers/chauffagistes), qualifie le prospect et
  remplit l'agenda, chaque RDV validé par l'artisan avant confirmation SMS au client.
  Utiliser DÈS que Geoffrey mentionne : Relais, relais-ai, le SaaS artisans, l'agent vocal
  artisan, les appels manqués, Dupont Chauffage, la machine à états S0–S11, run_scenario,
  run_llm_eval, garde-fous/verbatim, renvoi conditionnel, calendrier tampon, validation
  1-tap, scoring de leads, table communes→CP, le backend FastAPI/Supabase du projet, SMS
  OVH, page de validation, app artisan, ou tout travail avec Claude Code sur
  C:\Projets_saas\relais-ai. Déclencher aussi sur « on continue le projet », « lis les
  résultats », « rapport de Claude Code », « où on en est sur le SaaS ». NE PAS confondre
  avec les projets DentalMonitoring (dm-*).
---

# Relais — capsule projet

## Ce que dit ce skill vs ce que dit le repo

Ce skill donne le **contexte stable** : vision, décisions, architecture, méthodes de travail.
L'**état frais** (avancement, backlog) vit dans le repo : `docs/journal.md` (à lire en premier),
`docs/spec-produit-v1.md` (la référence produit, v0.2+), `CLAUDE.md` (règles pour Claude Code).
En début de session : demander à Geoffrey de connecter le dossier `C:\Projets_saas\relais-ai`
(bouton « Ajouter un dossier » de l'app desktop), puis lire `docs/journal.md`. Si le dossier
n'est pas connectable, demander un copier-coller du journal.

## Le produit en une phrase

**Relais répond aux appels que l'artisan rate (renvoi conditionnel — il garde son numéro),
qualifie le prospect, réserve un créneau dans un calendrier tampon, et l'artisan valide /
modifie / refuse en 1 tap avant que le client reçoive le SMS de confirmation.**

- Cible V1 : plombiers/chauffagistes FR, patron + 0-10 personnes sans secrétariat.
- Obsession : transformer les appels ratés en CA **et le prouver** (funnel appels → RDV →
  chantiers → €). North Star : € générés/récupérés pour l'artisan. Ne JAMAIS inventer le
  « CA récupéré » : l'artisan marque gagné/perdu + montant.
- Ce n'est PAS un logiciel de gestion BTP (Obat/Tolteck), pas un CRM, pas un standard IA générique.
- Nom de code `relais` ; nom de marque non choisi (décision avec le cousin, vérif domaine+INPI).
  Attention : decroche.ai est un concurrent direct existant (le créneau est actif).

## Équipe et rôles

- **Geoffrey** : unique développeur (2 machines Windows, sync par git push/pull), produit.
  Profil : ingénieur pipeline 3D chez DentalMonitoring, Python, pas expert web/mobile.
- **Claude Cowork** (ce contexte) : conception, specs, arbitrages produit, analyse des évals
  et des rapports de Claude Code, mémoire longue, revue d'architecture. N'écrit plus le gros
  du code depuis la bascule Claude Code.
- **Claude Code** (sur les machines de Geoffrey) : construction — backend, API, app.
  Il lit `CLAUDE.md` à la racine. Tempérament constructeur : il propose parfois d'aller plus
  vite que la spec (app native trop tôt, fournisseur voix prématuré) — le rôle de Cowork et
  de Geoffrey est de tenir le séquencement. Ses rapports sont fiables et vérifiés (il fait
  des contrôles négatifs) ; les lire de façon critique quand même.
- **Le cousin** : marketing, acquisition (Meta Ads), interviews terrain (guide d'entretien
  19 questions livré), futures ventes. Pas technique.

## Architecture de l'agent (le cœur, prouvé)

Principe : **« le code sait, le LLM comprend »** — le LLM ne décide JAMAIS.

- **Contrôleur déterministe** (`proto/relais_proto/engine.py`) : machine à états S0–S11
  (S12 « gestion RDV existant » à spécifier), remplissage opportuniste de slots, transitions
  en code. Config artisan = tout ce que l'agent sait (`config/dupont.json` = persona de test).
- **LLM en 2 rôles étroits** (`llm.py`) : extracteur de slots (reçoit le contexte : dernière
  réplique agent + propositions en cours) et formuleur. `MockLLM` (règles) pour tests sans
  clé ; `ResilientLLM` = dégradation gracieuse (panne réseau/LLM → mode scripté, jamais muet,
  dégradations tracées dans le lead).
- **Verbatim** : phrases critiques jamais réécrites par le LLM — réservation (dates !),
  promesse de rappel, répétition du numéro (chiffres !).
- **Garde-fous en code** (`guards.py`) sur chaque sortie : prix = liste blanche uniquement,
  jamais de diagnostic, jamais « confirmé » avant validation artisan. Violation → repli =
  l'instruction du contrôleur (sûre par construction) + log.
- **Commune → CP** : table zone artisan (alias configurés) + base officielle Île-de-France
  (1 504 entrées, multi-CP — Saint-Maur = 94100/94210/94340, Paris par arrondissement,
  générée depuis le paquet npm `codes-postaux` d'Etalab). Le LLM a l'interdiction de deviner
  un CP. Extension France entière = retirer le filtre départements du générateur.
- **Scoring 0–5** avec raisons affichables (la carte lead du dashboard).

Qualité : suite de non-régression scriptée (`run_scenario.py`, mock, ~1 s — le nombre de
tests dans les docs est banni : le script fait foi) + éval LLM adversariale
(`run_llm_eval.py`, 8 personas à objectif caché, verdicts mécaniques, violations interceptées
= WARN). Jalon atteint : 32 conversations LLM réelles, 0 échec.

## Décisions actées (ne pas rouvrir sans Geoffrey)

- **Appels sortants : EXCLUS définitivement** (légal instable — loi démarchage 11/08/2026).
  L'agent ne compose jamais. Relances = SMS transactionnels d'une demande entrante.
- **SMS bidirectionnel** : renégociation d'horaire par l'artisan → SMS au client
  (« OUI/NON ») → réponse lue → push artisan. Annulation/modification par le CLIENT =
  exigence V1 (par rappel téléphonique reconnu via numéro + par SMS).
- **Interfaces : site web + app mobile** (artisans smartphone-only, push natives, simplicité
  radicale) — MAIS séquencement : **page web mobile de validation (lien signé par SMS) pour
  la bêta**, app native (probablement Expo) pendant la bêta, sur la même API. L'app native
  n'est pas sur le chemin critique.
- **Validation** : expiration 4 h ouvrées / 1 h urgence, JAMAIS d'auto-validation en V1.
  Une modification demandée par le client repasse par la validation artisan.
- **Stack** : Python/FastAPI + Postgres Supabase (région UE, RGPD). Connexion : directe si
  IPv6 OK, session pooler sinon (les deux dans .env, test empirique). Transcript = listes
  (jsonb), état conversationnel sérialisé et versionné en base à chaque tour (leads partiels).
- **Téléphonie/voix** : plateforme managée (Vapi/Retell/ElevenLabs — NON choisie) derrière
  une abstraction à nous ; les numéros voix viendront de la plateforme choisie, PAS d'OVH.
  OVH = SMS (API FR, tokens à droits minimaux via api.ovh.com/createToken, droits immuables
  → régénérer pour élargir). Latence cible < 1 s/tour ; annonce IA < 5 s (AI Act art. 50).
- **Modèles** : Sonnet 5 (`claude-sonnet-5`) pour l'éval qualité ; Haiku envisagé en prod
  pour la latence. Pièges payés : les modèles à réflexion adaptative comptent leurs tokens de
  réflexion dans max_tokens (mettre large) et émettent des ThinkingBlocks (ne lire que les
  blocs text) ; timeout API court (10 s) + 1 retry ; `load_dotenv(override=True)`.
- **Email entrant** : en réflexion, ni engagé ni exclu. WhatsApp : V2+.

## Méthodes de travail (éprouvées, à maintenir)

1. **Chaque bug trouvé devient un test R<n>** dans `run_scenario.py` AVANT correction, avec
   qui l'a trouvé en commentaire. Aucun changement de prompt/engine sans rejouer la suite.
2. **Boucle d'éval par fichiers** : Geoffrey lance `python run_llm_eval.py` en local (clé API
   dans `.env`, jamais partagée avec Claude) → résultats dans `evals/results-*.json` → il dit
   « lis les résultats » → Cowork stage le fichier depuis le dossier connecté, analyse les
   transcripts des FAIL, corrige ou fait corriger.
3. **Revue des rapports Claude Code** : vérifier idempotence des webhooks entrants (les
   plateformes rejouent !), transitions de statut RDV en compare-and-swap SQL (worker
   d'expiration vs validation simultanées), suites toujours vertes après tout port,
   journal + commit en fin de session (règle qui a déjà sauté).
4. **Fin de session** : mettre à jour `docs/journal.md` (fait / décidé / prochaine étape)
   et commit/push. Les deux machines ne se synchronisent QUE par git.
5. Textes agent et commentaires en **français**. Secrets uniquement en `.env` (un par
   machine, jamais commité) ; tokens nommés, droits minimaux, révocables.

## Leçons de terrain (éviter de re-payer)

Le formuleur LLM improvise s'il le peut (promesses de rappel, « c'est noté », dates
hallucinées) → verbatim + interdictions explicites + garde-fous. L'extracteur sans contexte
ne comprend pas un choix de créneau. Une question (prix) n'est pas un refus ; « plus tôt ? »
n'est pas un rejet. La ponctuation casse les correspondances naïves de noms de communes.
jsonb transforme les tuples en listes. Un slot rempli doit rester corrigeable tant que le
RDV n'est pas réservé (numéro, commune). Les consignes sécurité (couper l'eau, gaz 0 800
47 33 33) sont un catalogue fermé et ne doivent jamais se perdre dans les sauts d'états.

## Historique éclair

Août 2026 : idée validée par étude ChatGPT + contre-analyse (marché encombré — monstandard.ai,
decroche.ai… — le moat = exécution + niche + numéro de téléphone, pas l'IA). Specs fondatrices
(script conversation, config artisan, 12 scénarios, diagramme). Prototype texte : 13+ bugs
trouvés en tests manuels (Geoffrey) et auto-tests (Claude), tous en régression. Éval LLM
adversariale : 32/32. Bascule Claude Code : sérialisation → schéma Postgres → cycle de vie
RDV + worker expiration (contrôle négatif validé) → API FastAPI. Prochaine boucle complète
visée : appel → RDV tampon → SMS artisan → tap validation → SMS confirmation client, démo
de bout en bout avec deux téléphones.
