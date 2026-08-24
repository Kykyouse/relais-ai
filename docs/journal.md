# Journal du projet Relais

> 3 lignes par session : fait / décidé / prochaine étape. Toute nouvelle conversation
> (Claude ou humaine) redémarre en lisant ce fichier + `docs/`.

---

# ÉTAT AU 23/08/2026 — à lire en premier

> **Ce bloc se REMPLACE, il ne s'empile pas.** Les entrées datées plus bas sont le journal
> chronologique (le pourquoi des décisions) ; ce bloc-ci est le où-on-en-est.

## En une phrase

Le backend de la phase 1 est fonctionnel et vérifié contre un vrai Postgres : un appel
entre par HTTP, produit un lead scoré et un RDV, l'artisan valide en 1 tap, l'expiration et
les messages sortants sont gérés. **Rien ne sort encore du système** : ni voix, ni SMS, ni
push — les trois attendent un fournisseur.

## Ce qui tourne

```bash
cd proto
python run_scenario.py                              # 26 tests, ~2 s, sans clé ni base
python run_depot_pg.py [--migrer]                   # contrat du port contre Supabase
uvicorn serveur:app --port 8000                     # API HTTP
python worker.py [--a-vide]                         # expiration + expédition (cron)
python run_llm_eval.py [--mock] [--n 3]             # éval appelant-simulé
```

| Brique | État | Vérifié contre |
|---|---|---|
| Agent conversationnel S0–S11, garde-fous, dégradation | ✅ | mock (25 tests) + 32 convs LLM réelles |
| Sérialisation de l'état d'appel (R14) | ✅ | mock, mutation 10/10 |
| Cycle de vie du RDV, expiration (R15, R16) | ✅ | mock, mutations 11/11 et 9/9 |
| Port `Depot` + adaptateur Postgres (R17, R18) | ✅ | **Supabase réel**, contrat identique |
| API HTTP, 2 portes d'auth, 1 tour = 1 requête (R19) | ✅ | mock + câblage réel sur Supabase |
| Plage de silence, réessais, multi-artisans (R20) | ✅ | mock, mutations 8/8 |
| Validation client par lien à un tap (R21) | ✅ | mock, mutations 7/7 |
| Adaptateur OVH : E.164, corps, échecs (R22) | ✅ | **SMS réellement reçu sur téléphone, 24/08** |

## Ce qui est encore un double (et non un manque caché)

- **Envoi SMS** : l'adaptateur OVH (`envoi_ovh.py`) est écrit et testé hors ligne (R22),
  mais **aucun envoi réel n'a eu lieu** : pas d'identifiants, et le Sender ID n'est pas
  déclaré. `EnvoyeurJournal` reste le mode par défaut, donc **rien ne part**. Le premier
  envoi réel se fait à la main : `python envoyer_un_sms.py <num> --envoyer` (blanc par
  défaut), et `--comptes` liste les services SMS du compte. La forme de réponse d'OVH
  encodée dans l'adaptateur est **CONFIRMÉE** : premier SMS réel envoyé le 24/08 en mode
  numéro court (réf. `ovh:802084252`), réponse conforme à l'hypothèse. Reste à faire :
  valider le Sender ID `DupontChauf` (~72 h, risque de refus) pour sortir du mode test — les
  numéros courts **bloquent les URL**, donc le lien de validation ne peut pas passer par là.
- **`CalendarStub`** : applique les vraies règles d'agenda mais n'est relié à aucun
  calendrier. Google/Outlook non branchés (OAuth Google à lancer tôt : délai calendaire).
- **Pas de voix** : aucune plateforme vocale branchée, aucun numéro. L'API expose déjà les
  webhooks qu'elle appellera.
- **Pas de push** : la relance artisan est mise en file, jamais délivrée.
- **`config/artisans.json`** : registre en fichier, avec des jetons de dév **publics**.
  Deviendra la table `artisan` (et la FK que `rdv.artisan_id` attend déjà).
- **`MockLLM`** : rate « Je m'appelle X » (regex sans `IGNORECASE`) — le chemin
  « nom connu » n'est donc jamais exercé dans les tests mock.

## Décisions verrouillées cette session

- **Délais de validation : 24 h / 2 h en heures réelles**, réglables par artisan. À 24 h le
  calcul en heures ouvrées devient nuisible ; il reste disponible via `base_delai`.
- **L'échéance fait foi, pas le passage du worker** : valider une seconde trop tard est
  refusé, sinon la décision dépend de la latence d'un cron.
- **Effets idempotents avant changement d'état** dans les workers : l'inverse perd le SMS
  du client pour de bon.
- **SMS strictement sortant, « Répondez OUI » remplacé par un lien à un tap.** Motif
  vérifié : numéros mobiles FR interdits à l'A2P, bidirectionnel = numéro `09 3X`, et
  Charte AF2M du 1er mars 2026. Le lien supprime le numéro dédié et toute la conformité
  entrante.
- **Deux portes d'authentification distinctes** : secret partagé pour la plateforme vocale
  (l'artisan est identifié par le numéro appelé), jeton porteur pour l'app artisan.
- **L'API ne décide jamais** : corollaire backend de la règle n°1.

## Dettes et décisions ouvertes

1. **Fuseaux / changement d'heure** — le domaine est en datetime naïfs et le schéma en
   `timestamp` sans fuseau. Avec 24 h de délai réel, une échéance posée la veille du
   basculement vaut 23 h ou 25 h. **À trancher avant la prod**, c'est une décision de
   conception, pas un détail.
2. **Fournisseur SMS** — choix ouvert et **réversible** (tout passe par le port
   `Envoyeur`). Depuis le flux par lien, le seul besoin est : envoyer un SMS transactionnel
   vers un mobile FR avec un **sender ID alphanumérique déclaré**. Critère de sélection =
   qualité du processus de déclaration du Sender ID (Charte AF2M du 01/03/2026), + DPA et
   hébergement UE. Candidats FR/UE équivalents : OVHcloud, LinkMobility, Octopush,
   SMSFactor, Brevo. Aucune clé n'est nécessaire tant que l'adaptateur n'existe pas
   (`EnvoyeurJournal` par défaut) ; le jour où l'on en crée, la porter au strict minimum
   (chez OVH : consumer key limité à `POST /sms/*`, avec expiration).
3. **Fournisseur de NUMÉROS / plateforme vocale** — décision distincte de la précédente,
   et à ne pas anticiper : les plateformes managées (Vapi, Retell) fournissent leurs propres
   numéros ou s'intègrent en trunk SIP. Prendre des numéros chez un opérateur avant d'avoir
   choisi la plateforme créerait une double tuyauterie à réconcilier.
4. **`FOR UPDATE SKIP LOCKED`** quand plusieurs workers tourneront (optimisation, pas
   justesse : l'unicité de la clé d'idempotence protège déjà le client).
5. **Table `artisan`** + FK, en remplacement du registre fichier.
6. Formulation « d'ici 24 heures » à l'oral, un peu mécanique — à retoucher sciemment
   (phrase verbatim et testée).

## Prochaine étape

L'app mobile qui consomme `GET /rdv` — c'est là que la validation 1-tap devient tangible,
et c'est indépendant de tout fournisseur.

---

## Sessions du 21–22/08/2026 — fondations + prototype texte

**Contexte.** Projet : agent IA qui répond aux appels manqués des artisans (renvoi conditionnel),
qualifie, réserve un RDV validé par l'artisan (1 tap) avant confirmation SMS au client.
Équipe : Geoffrey (dev + produit, binôme Claude), cousin (marketing — interviews terrain en cours,
guide d'entretien livré). Cible V1 : plombiers/chauffagistes.

**Fait.**
- 4 specs fondatrices dans `docs/` : script de conversation (machine à états S0–S11, 9 invariants),
  schéma de config artisan (le LLM ne sait rien de lui-même), diagramme HTML, 12 scénarios d'éval.
- Prototype texte complet dans `proto/` : contrôleur déterministe + LLM en 2 rôles étroits
  (extracteur/formuleur) + garde-fous en code + calendrier stub + scoring 0–5.
- Mode LLM réel branché (Sonnet 5, `claude-sonnet-5`) et éprouvé en interactif.
- Suite de smoke tests : **14 PASS** (`python run_scenario.py`, mode mock, sans clé).

**Bugs trouvés et verrouillés en régression** (tests R01–R10) :
- R01 : « Non » au numéro répété confirmait l'ANCIEN numéro ; le corrigé était ignoré.
- R02 : un numéro à 6 chiffres passait pour un refus silencieux.
- R03 : « aucun créneau » reproposait les mêmes créneaux en boucle.
- R04/R05 : commune corrigée en cours d'appel ignorée + CP pris pour un téléphone incomplet.
- R06 : consigne sécurité « coupez l'eau » perdue quand tout est donné en une phrase.
- R07 : le formuleur improvisait une promesse de rappel jamais décidée par le contrôleur.
- R08 : panne réseau/LLM totale → l'appel aboutit en mode scripté, dégradations tracées dans le lead.
- R09/R10 : l'appelant donne sa VILLE, pas son CP → résolution commune→CP par table de config
  (communes de la zone uniquement) ; commune inconnue → on demande le CP.

**Décisions d'architecture.**
- Le LLM ne décide jamais : transitions, prix, créneaux, promesses = contrôleur + listes blanches.
- Voix future en plateforme managée derrière une abstraction à nous.
- Sonnet 5 pour la phase d'éval ; timeout API 10 s + 1 retry + dégradation gracieuse (jamais muet).
- max_tokens large obligatoire : les tokens de réflexion adaptative comptent dedans (sinon troncature).
- Flow de validation « expiration + repli » : 4 h ouvrées / 1 h urgence, jamais d'auto-validation en V1.

**Backlog (ordre suggéré).**
1. Scénarios restants en scripté : T03 (entretien samedi + prix), T06 (gaz complet), T09/T10 (répondeur/spam), T12 (agenda saturé — jours_pleins).
2. Appelant simulé LLM vs agent LLM : rejouer les 12 scénarios automatiquement en mode réel (éval de la couche langage).
3. Annulation d'un RDV validé par le client qui rappelle (trou de spec identifié, v0.2 du script).
4. Changement de commune PAR NOM après CP acquis (seul le changement par CP est géré).
5. Persistance des leads (fichier/DB) au-delà de `last_lead.json`.
6. Spec téléphonie : renvoi conditionnel, choix plateforme voix, repli voix (message + SMS si STT/TTS down).

**Prochaine étape convenue :** compléter la suite scriptée (1), puis l'éval LLM automatisée (2).

---

## Session du 22/08/2026 (suite) — éval LLM automatisée : JALON ATTEINT

**Fait.**
- `run_llm_eval.py` : appelant simulé LLM (8 personas à objectif caché) vs agent LLM,
  verdicts mécaniques, résultats dans `evals/results-*.json` (boucle par fichiers :
  Geoffrey lance, Claude lit/corrige). Mode `--mock` pour la plomberie. `CLAUDE.md` créé
  (transition Claude Code prête — bascule prévue à la phase backend/téléphonie).
- 2 itérations d'éval réelle → 7 correctifs :
  réservation + promesse de rappel + répétition du numéro en **verbatim** (dates, engagements
  et chiffres jamais réécrits par le formuleur) ; repli sur violation = l'instruction du
  contrôleur (plus de phrase générique hors sujet) ; l'extracteur reçoit le **contexte**
  (dernière réplique agent + propositions en cours) ; disponibilités exprimées **respectées**
  (« que le samedi matin » → créneaux samedi, R11) ; question-prix ≠ refus de numéro
  (réponse liste blanche 90 € + re-demande, T05) ; « rien de plus tôt ? » ≠ rejet
  (re-proposition du premier créneau au lieu d'avancer) ; violations interceptées = WARN.

**Résultat final : 8/8 (n=1) puis 24/24 (n=3) — 32 conversations LLM réelles, 0 échec,
2 violations tentées et 2 interceptées.** Suites mock : 15 + 8, toutes PASS.

**Backlog restant (mis à jour).**
1. Personas manquants en éval LLM : T04 (bavard), T06 (gaz), T09/T10 (répondeur/spam), T12 (agenda saturé).
2. Annulation d'un RDV validé par le client qui rappelle (v0.2 du script).
3. Persistance des leads + début du dashboard artisan (validation 1-tap = le cœur produit).
4. Spec téléphonie : renvoi conditionnel, choix plateforme voix, repli voix → **bascule Claude Code ici**.
5. LLM-juge pour les assertions de ton (en plus des verdicts mécaniques).

---

## Session du 23/08/2026 — sérialisation de l'état d'appel (ouverture de la phase backend)

**Fait.**
- `Conversation.to_dict()` / `from_dict()` + `CalendarStub.to_dict()` / `from_dict()` :
  l'état d'un appel (state, slots, transcript, flags, propositions, silences, calendrier,
  dégradations LLM) devient un dict JSON versionné (`ETAT_VERSION = 1`), rechargeable
  à l'identique dans un process neuf.
- Test **R14** dans `run_scenario.py` : les 15 scénarios + 3 cas dédiés sont rejoués DEUX
  fois — une passe en mémoire, une passe où l'objet et son client LLM sont détruits et
  rechargés depuis du vrai JSON avant chaque tour — et les leads doivent être identiques.
  S'y ajoutent un invariant de point fixe (`from_dict(to_dict()) == to_dict()`) et le
  rejet d'un état de version inconnue. Suite : **18 tests PASS**.
- Vérification que R14 n'est pas creux (mutant jetable retirant chaque champ de l'état) :
  3 champs passaient quand même au premier jet → ajout des cas « silence → répondeur »
  (sans le compteur, l'appelant muet ne bascule jamais en S9) et « quota d'urgences du
  jour saturé » (sans lui, la reprise ressort la fenêtre d'urgence déjà donnée), plus
  l'invariant de point fixe pour les champs encore write-only (`holds`, `jours_pleins`).
  Après correction : 10/10 champs détectés.

**Décisions.**
- **Pourquoi cette brique d'abord** : en prod chaque tour arrivera comme un webhook HTTP,
  potentiellement sur un autre process. `slots`/`flags` étaient déjà des dicts plats —
  une heure aujourd'hui, une réécriture du contrôleur plus tard.
- **Frontière posée** : ni la config artisan ni le client LLM ne sont sérialisés — ce sont
  des dépendances injectées au rechargement. C'est ce qui rendra l'API greffable sans
  toucher au moteur.
- `calendrier.now` est rechargé et JAMAIS relu à l'horloge : sinon les libellés déjà
  prononcés à l'appelant (« demain », « samedi 29/08 ») changent de sens d'un tour à l'autre.
- Les dégradations LLM vivent sur le client mais voyagent dans l'état : sans ça un appel
  dégradé repris ailleurs remonte un lead faussement propre et l'alerte monitoring saute.
- R14 tourne sur une **horloge figée** (lundi 09:00) : la fenêtre d'urgence réservée dépend
  du jour et de l'heure, et un run lancé un dimanche soir masquait un trou réel.
- Corollaire backend de la règle n°1 (« le LLM ne décide jamais ») : **l'API ne décide
  jamais non plus** — transitions, créneaux et prix restent dans `engine.py` /
  `calendar_stub.py`, l'API n'est que transport + persistance.

**Cadrage de la phase backend** (arbitrages Geoffrey, via Claude Desktop) :
- **Auth minimale dès l'API** : un token par artisan suffit pour la bêta, à poser AVANT
  l'app mobile — sinon on la greffe après coup. Nuance ajoutée : le webhook téléphonie
  ne s'authentifie PAS avec le token artisan (l'appelant est la plateforme voix, pas
  l'artisan) — secret partagé / vérification de signature à part, artisan identifié par
  le numéro appelé. Deux chemins d'auth distincts dès le départ.
- **Définition de « terminé » pour la phase** (anti-gonflement) : T01 rejoué de bout en
  bout via HTTP (tours simulés en webhooks, un tour = une requête, aucune session en
  mémoire) + un RDV en Postgres traversant tampon → validé ET tampon → expiré → SMS de
  repli + suites d'éval toujours vertes.
- **Chaque brique backend arrive avec son test dans la suite, pas après** (extension de
  la règle n°4 au backend). Contrainte de conception qui en découle : le worker
  d'expiration doit avoir une **horloge injectable**, sinon il n'est pas testable.

**Backlog (ordre suggéré).**
1. Modèle de données + cycle de vie du RDV (`tampon → en_attente_validation → validé /
   refusé / expiré`, avec `expire_a`) : `artisan`, `appel`, `lead`, `rdv`,
   `message_sortant` (clé d'idempotence — un SMS envoyé deux fois est un incident client),
   `evenement` (audit RGPD). Postgres managé UE.
2. Worker d'expiration (horloge injectable) : libère le créneau tampon, lead en alerte,
   SMS de repli.
3. API FastAPI mince, `build_lead()` figé en schéma Pydantic versionné comme contrat +
   auth artisan et auth webhook.
4. À lancer EN PARALLÈLE dès maintenant (temps calendaire, pas temps dev) : vérification
   OAuth Google Calendar, benchmark plateformes voix.
5. Reste de l'agent : personas d'éval manquants (T04, T06, T09/T10, T12), annulation d'un
   RDV validé par le client qui rappelle (S12, script v0.2), LLM-juge pour le ton.

**Prochaine étape convenue :** brique 1 (modèle + cycle de vie du RDV), avec son test.

---

## Session du 23/08/2026 (suite) — brique 1 : modèle de données + cycle de vie du RDV

**Fait.**
- `relais_proto/rdv.py` : le cycle de vie `tampon → en_attente_validation → validé /
  refusé / expiré`, en dataclasse avec graphe de transitions explicite, historique
  d'audit par RDV, et `to_dict`/`from_dict`.
- `relais_proto/depot.py` : le **port** de persistance (appel / lead / RDV) + une
  implémentation en mémoire. `DepotMemoire` sérialise à l'écriture et reconstruit à la
  lecture — elle ne rend jamais deux fois la même instance, sinon un test passerait en
  mutant l'objet sans appeler `sauver_rdv()` et casserait sur une vraie base.
- Test **R15** : graphe complet (20 paires), arithmétique des heures ouvrées, course
  validation-vs-expiration, T01 de bout en bout (conversation → état sérialisé en dépôt →
  lead → RDV → notifié → validé), chemin d'expiration, invariants produit. Suite : **19 PASS**.
- R15 éprouvé par mutation (10 règles cassées une à une) : **10/10 détectées**. Le premier
  jet en laissait passer 3, dont un vrai défaut de conception du test — voir ci-dessous.

**Décisions.**
- **Urgence = heures RÉELLES, hors urgence = heures OUVRÉES.** Une fuite prise à 19 h ne
  peut pas attendre l'ouverture du lendemain ; à l'inverse un RDV pris vendredi 17 h ne
  doit pas expirer pendant la nuit sans que l'artisan ait eu une chance de le voir.
- **Le chrono part de la réservation, pas du push.** C'est à la réservation que l'agent a
  promis « un SMS d'ici 4 heures » : la promesse court dès qu'elle est prononcée. Un
  tampon dont le push a échoué doit donc expirer aussi — sinon créneau fantôme.
- **L'urgence de l'échéance est lue dans `slots.urgence_reelle`, pas dans le drapeau du
  créneau.** Le hold dit seulement si le créneau vient de la fenêtre d'urgence réservée ;
  `engine._reserver` calcule sa promesse sur `urgence_reelle`. Les deux divergent quand le
  quota d'urgences du jour est épuisé — cas désormais testé, sinon la base accorde 4 h là
  où l'agent a dit 1 h.
- **La course critique est arbitrée par `expire_a`, jamais par le passage du worker** :
  l'artisan qui tape « valider » une seconde après l'échéance est refusé. Sinon sa
  décision dépend de la latence d'un cron, et le client reçoit deux messages
  contradictoires (SMS de repli puis confirmation).
- Un refus après échéance est refusé aussi : le statut doit rester `expiré` pour que le
  funnel distingue « refusé » de « ignoré ».
- `validation.heures_ouvrees` est lu s'il existe, sinon repli sur `agenda.horaires_rdv`.
  **Approximation assumée à corriger un jour** : « quand il intervient » n'est pas « quand
  il regarde son téléphone » (beaucoup valident le soir). Le champ dédié existe déjà pour
  séparer les deux sans retoucher le code.

**Leçon de méthode.** Le premier jet de R15 dérivait ses attentes de `rdv.TRANSITIONS`,
la table qu'il était censé vérifier : tautologie. Ouvrir « expiré → validé » dans la table
faisait suivre le test sans échec. La matrice attendue est désormais écrite **en dur** dans
le test. À retenir pour les briques suivantes : un test ne doit jamais lire sa référence
dans l'objet testé.

**Reste à faire pour clore la phase backend** (définition de « terminé » inchangée) :
1. Worker d'expiration au-dessus de `rdvs_echus()` (horloge injectable, déjà prête).
2. Adaptateur Postgres derrière le port `Depot` + migrations.
3. API FastAPI : `build_lead()` figé en schéma Pydantic, auth artisan + auth webhook
   distinctes, T01 rejoué en HTTP (un tour = une requête, aucune session en mémoire).
4. SMS de repli sur expiration (table `message_sortant` avec clé d'idempotence).

**Prochaine étape convenue :** brique 2, le worker d'expiration.

---

## Session du 23/08/2026 (suite) — délais de validation revus : 24 h / 2 h, par artisan

**Décision produit (Geoffrey).** 4 h était trop court : la plupart des artisans ne regardent
leur app que le soir, un délai de 4 h expire pendant qu'ils sont sur chantier. Nouveaux
défauts : **24 h hors urgence, 2 h en urgence**, et ces valeurs doivent être **modifiables
par artisan depuis son compte**.

**Conséquence non anticipée, tranchée dans le même mouvement.** À 24 h, le calcul en heures
ouvrées devient nuisible plutôt que protecteur : 24 h ouvrées depuis vendredi 17 h tombent
au mercredi suivant. Le calcul en heures ouvrées n'existait que pour éviter d'expirer
pendant la nuit — problème qui disparaît de lui-même dès que la fenêtre contient une
soirée. Donc : **heures réelles par défaut**, mode ouvrées conservé et configurable pour un
artisan qui voudrait un délai court sans expirer la nuit.

**Fait.**
- Schéma de config `validation` : `delai_max_heures` (24), `delai_max_urgence_heures` (2),
  `base_delai` (`reelles` | `ouvrees`), `heures_ouvrees` (null → `agenda.horaires_rdv`).
  L'ancienne clé `delai_max_heures_ouvrees` disparaît partout (code, config, 3 docs).
- `rdv.calculer_expiration` : lit `base_delai`. **L'urgence est toujours comptée en heures
  réelles, quel que soit le mode** — sinon le mot urgence ne veut plus rien dire.
- `engine._reserver` lit la même clé que le calcul d'échéance : la promesse prononcée et
  l'échéance stockée ne peuvent pas diverger (verrouillé par R15).
- R15 étendu : cas heures réelles (24 h/2 h), cas mode ouvrées sur config dédiée, urgence
  en mode ouvrées, et les 4 combinaisons (mode × urgence) traversées par `depuis_hold` à une
  heure où les deux modes divergent. Suite : **19 PASS**.
- Mutations : **11/11 détectées** sur R15 (dont « le défaut retombe à 4 h » et « base_delai
  ignoré »), 10/10 toujours sur R14.

**À trancher plus tard.**
- **Heures de silence pour les SMS.** L'expiration déclenche un SMS de repli au client. Avec
  un délai en heures réelles, l'échéance peut tomber à 3 h du matin. Il faudra une plage de
  non-envoi (proposition : 21 h–08 h, report à l'ouverture) au moment de la brique SMS —
  sinon on réveille le client. C'est le vrai remplaçant du calcul en heures ouvrées.
- **Formulation à 24 h.** L'agent dit maintenant « un SMS de confirmation d'ici 24 heures »,
  qui sonne mécanique à l'oral. « d'ici demain » ou « dans la journée » passerait mieux, mais
  la phrase est verbatim et testée : à changer sciemment, pas au passage.
- Le choix 12 h vs 24 h reste ouvert côté produit ; 24 h est posé comme défaut, un artisan
  peut descendre à 12 h sans changement de code.

**Prochaine étape convenue :** brique 2, le worker d'expiration.

---

## Session du 23/08/2026 (suite) — brique 2 : worker d'expiration

**Fait.**
- `relais_proto/messages.py` : file sortante (`message_sortant`) + catalogue **fermé** de
  templates. Comme les consignes sécurité, les textes sont écrits par nous, pas par le LLM
  ni par l'artisan (`sms.templates_personnalises = null` en V1). **Un SMS est une sortie de
  l'agent : il passe par `guards.check_output` avant d'entrer en file** — règle n°2 étendue
  au canal écrit. Un template fautif lève, il n'est pas envoyé.
- `relais_proto/expiration.py` : le worker (spec §3.6). Créneau libéré, lead en alerte,
  SMS de repli au client, relance artisan en push. Horloge en paramètre.
- `depot.py` : file sortante avec **clé d'idempotence** (équivalent d'un
  `INSERT ... ON CONFLICT DO NOTHING`), `marquer_lead_alerte`.
- Test **R16** + mutations : **9/9 détectées**. Suite : **20 PASS**.

**Deux décisions trouvées en écrivant le test, pas en écrivant le code.**
1. **Les effets idempotents AVANT le changement d'état.** Le passage au statut terminal est
   ce qui retire le RDV de `rdvs_echus()`. Si on écrit l'état d'abord et que le process
   meurt avant l'enfilage, le RDV sort de la file et **le client n'est jamais prévenu**.
   Dans l'ordre retenu, un passage interrompu laisse le RDV échu : le suivant le rattrape,
   et la clé d'idempotence évite le doublon. Verrouillé par un test de crash.
2. **Isolation des échecs par RDV.** Un RDV qui échoue ne doit pas geler l'expiration des
   autres : il reste échu, l'échec remonte dans le rapport, la boucle continue.

**Propriété émergente, agréable.** La course worker/artisan est déjà fermée par `rdv.py` :
`rdvs_echus()` ne rend que des RDV échus, et `valider()` refuse un RDV échu. Donc un RDV
que le worker voit ne peut plus être validé, et un RDV validé n'est jamais dans sa file.
Le même garde-fou sert les deux côtés — testé explicitement pour que ça reste vrai.

**Modélisation.** La relance artisan cible son **identifiant de compte** (push vers l'app),
pas un numéro. Le repli SMS vers `transfert.cible` viendra avec l'adaptateur d'envoi, pour
l'artisan sans app. `transfert.cible` a été ajouté à `dupont.json`, qui ne respectait pas
son propre schéma documenté.

**Leçon.** Deux défauts de copie n'ont été vus qu'en imprimant les textes réellement mis en
file : « le créneau **du** aujourd'hui entre 17h et 19h » (le libellé du calendrier se lit
en apposition, jamais après un article) et « pour client sans nom ». Aucun test ne les
aurait attrapés. **Lire la sortie réelle, pas seulement les assertions.**

**Défaut repéré, non corrigé (hors périmètre de la brique).** `MockLLM` rate
« Je m'appelle Garcia » : la regex de nom n'a pas `re.IGNORECASE`, donc seule la minuscule
matche. Conséquence : le slot `nom` reste vide dans les scénarios mock, et le chemin
« nom connu » des messages n'est jamais exercé. Correctif = 1 flag + un test R17 (règle n°4
du projet : le test d'abord).

**Prochaine étape convenue :** brique 3, l'adaptateur Postgres derrière le port `Depot`,
ou l'API FastAPI — au choix.

---

## Session du 23/08/2026 (suite) — brique 3 : adaptateur Postgres (⚠️ non exécuté)

**Contexte matériel.** La machine n'a ni `psycopg`, ni Docker, ni serveur Postgres
(port 5432 fermé). Décision : instance **managée UE** (Neon/Supabase, cible de la spec §9)
créée par Geoffrey, et **psycopg brut + migrations `.sql`** plutôt que SQLAlchemy — une
dépendance, du SQL explicite, et le port `Depot` fournit déjà l'abstraction qu'un ORM
apporterait.

**⚠️ ÉTAT RÉEL : l'adaptateur Postgres n'a JAMAIS tourné.** Aucun serveur n'était joignable.
Ce qui est validé hors ligne : la surface du port (R18) et le contrat métier (R17, contre le
dépôt en mémoire). Ce qui ne l'est pas : chaque requête SQL. Tant que
`python run_depot_pg.py --migrer` n'est pas vert, `depot_pg.py` est un brouillon crédible,
pas du code éprouvé.

**Fait.**
- `migrations/001_initial.sql` : `appel`, `lead`, `rdv`, `message_sortant`. Index partiels
  sur les deux requêtes chaudes (file du worker, boîte de validation). Contraintes `check`
  sur les statuts. Unicité sur `cle_idempotence` : **c'est la base qui refuse le double SMS**,
  pas la prudence de l'appelant.
- `relais_proto/depot_pg.py` : l'adaptateur. Ids générés en Python (le domaine a besoin de
  l'id avant l'insert), `INSERT ... ON CONFLICT DO NOTHING` pour la file sortante.
- `contrat_depot.py` : **la suite de contrat du port, écrite une fois, jouée contre les deux
  implémentations.** C'est la vraie livraison de cette brique : elle valide aujourd'hui
  `DepotMemoire` (R17) et validera `DepotPostgres` d'un seul coup.
- `run_depot_pg.py` : lanceur. Sort **2** (jamais 0) si aucune base n'est joignable, avec le
  mode d'emploi — un succès vide est pire qu'un échec.
- Tests **R17** (contrat) et **R18** (conformité structurelle des deux adaptateurs au
  Protocol, noms de paramètres compris — le seul contrôle possible hors ligne). Suite : **22
  PASS**. Mutations : 5/5 sur R17-R18, et 10/11/9 toujours sur R14/R15/R16.

**Décisions.**
- **`DATABASE_URL_TEST`, distincte de `DATABASE_URL`.** Le lanceur TRONQUE les tables : deux
  variables séparées rendent l'accident impossible plutôt qu'improbable. Le script refuse
  aussi une base dont le nom contient prod/production/live.
- **`timestamp` sans fuseau**, pour coller au domaine (datetime naïfs, heure locale FR) et
  garantir l'aller-retour exact.
- **Pas de `FOR UPDATE SKIP LOCKED` dans `rdvs_echus()`.** Il faudrait tenir une transaction
  ouverte pendant tout le traitement, ce que le port n'exprime pas — et ce n'est pas
  nécessaire à la justesse : deux workers concurrents ne peuvent ni doubler un SMS
  (unicité en base) ni voler une décision (`valider()` refuse un RDV échu). Au pire deux
  entrées d'historique. Optimisation à ajouter quand plusieurs workers tourneront.

**⚠️ À TRANCHER AVANT LA PROD — fuseaux et changement d'heure.** Le domaine est en datetime
naïfs. Avec un délai de validation de 24 h en heures réelles, une échéance posée la veille
du basculement d'heure vaut 23 h ou 25 h. Ça touche aussi les libellés de créneau prononcés
à l'appelant. Passer le domaine en tz-aware est une décision de conception, pas un détail
d'implémentation — et c'est plus simple à faire maintenant qu'après la première prod.

**Reste pour clore la phase backend.**
1. Créer l'instance Neon/Supabase (UE), brancher `DATABASE_URL_TEST`, lancer
   `run_depot_pg.py --migrer` → **c'est ce qui transforme la brique 3 en brique finie.**
2. API FastAPI : `build_lead()` figé en schéma Pydantic, auth artisan + auth webhook
   distinctes, T01 rejoué en HTTP (un tour = une requête).
3. Adaptateur d'envoi SMS + plage de non-envoi 21 h–08 h.
4. Correctif `MockLLM` (regex de nom sans `IGNORECASE`) avec son test R19.

**Prochaine étape convenue :** Geoffrey crée l'instance ; ensuite `run_depot_pg.py`.

---

## Session du 23/08/2026 (suite) — Supabase : préparation du premier run réel

**Décision.** Supabase (projet de test dédié, région UE). Les deux chaînes dans `.env` :
`DATABASE_URL` (connexion directe) et `DATABASE_URL_POOLER` (session pooler).
`run_depot_pg.py` essaie la directe, bascule sur le pooler si elle échoue — l'hôte direct
`db.<ref>.supabase.co` est en IPv6 sur les projets récents, inatteignable depuis un réseau
IPv4 seul. Si la chaîne fournie est un pooler en mode **transaction** (port 6543), le
lanceur passe automatiquement `prepare_threshold=None` : psycobg active des prepared
statements de lui-même, que ce mode ne supporte pas.

**Garde anti-troncature refaite.** L'ancienne reposait sur le nom de la variable
(`DATABASE_URL_TEST`) et, en repli, sur un nom de base contenant « prod ». **Toutes les
bases Supabase s'appellent `postgres`** : cette seconde garde ne pouvait jamais se
déclencher. Remplacée par un **marqueur écrit dans la base** (`relais_base_de_test`), posé
une seule fois par `--autoriser-truncate`. Consentement explicite, porté par la base
elle-même, insensible au renommage des variables et valable depuis n'importe quelle machine.
`--migrer` seul ne le pose pas : pointer les migrations sur la prod n'autorise pas à la vider.

**Deux incompatibilités Postgres trouvées par relecture, avant le premier run.**
1. Le contrat testait `Introuvable` avec l'id `"inconnu-42"`. Contre une colonne `uuid`,
   Postgres lève une **erreur de cast** au lieu de rendre zéro ligne : trois assertions
   auraient échoué. Le contrat utilise désormais un UUID valide mais absent, et
   l'adaptateur filtre les ids malformés (`_uuid`) → `Introuvable`. Enjeu réel au-delà du
   test : un id fourni par un client donnerait un 500 au lieu d'un 404 dans l'API.
2. `build_lead()` met le transcript en **tuples** ; un aller-retour jsonb les rend en
   **listes**. Le contrat aurait échoué alors que le comportement est correct : une colonne
   jsonb restitue un DOCUMENT, pas des objets Python. Les comparaisons de blobs sont
   normalisées en types JSON des deux côtés. Les colonnes `timestamp`, elles, restent
   comparées **exactement** — c'est l'assertion forte, et elle doit le rester.

Suite : **22 PASS**. L'adaptateur Postgres n'a toujours **pas** tourné.

**Prochaine étape :** Geoffrey renseigne les deux chaînes, puis
`python run_depot_pg.py --migrer --autoriser-truncate`. La connexion retenue sur cette
machine sera notée ici.

---

## Session du 23/08/2026 (suite) — Postgres VALIDÉ sur Supabase

**La brique 3 est finie.** `run_depot_pg.py --migrer --autoriser-truncate` passe : contrat du
port ✅, worker d'expiration sur Postgres ✅. Rejoué ensuite sans drapeaux : ✅ (le marqueur
persiste, comme prévu). Suite mock toujours **22 PASS**.

**Connexion qui fonctionne sur cette machine : la CONNEXION DIRECTE**
(`db.<ref>.supabase.co:5432`). Aucun repli sur le pooler nécessaire — le réseau atteint
l'hôte direct. `DATABASE_URL_POOLER` reste renseigné comme filet ; le lanceur basculera tout
seul si la directe cesse de répondre (autre réseau, IPv4 seul).

**Deux blocages au premier lancement, aucun dans le SQL.**
1. `.env` portait encore `DATABASE_URL_TEST` (nom d'avant le renommage) et la chaîne du
   pooler avait été collée **sans nom de variable**. Corrigé par ancrage, sans lire les
   valeurs ; sauvegarde `.env.bak.avant-renommage` (couverte par `.gitignore`).
2. `psycopg` n'était pas installé (pas de venv, Python 3.13 global) → installé, 3.3.4.

**Le SQL est passé du premier coup.** Ce n'est pas de la chance : les deux
incompatibilités réelles (cast d'un id non-UUID, tuples du transcript rendus en listes par
jsonb) avaient été trouvées par relecture juste avant, et corrigées. C'est la relecture qui
a payé, pas l'écriture.

**Vérifié plutôt que cru** — un « ✅ du premier coup » méritait des preuves :
- écritures réelles : 5 appels, 5 leads, 5 RDV, 6 messages en base ;
- cycle de vie complet traversé côté Postgres : `valide` ×1, `expire` ×3,
  `en_attente_validation` ×1 ; file sortante 3 SMS client + 3 push artisan ;
- `jsonb` correctement typé sur les 5 RDV (`creneau` objet, `historique` tableau) ;
- les 5 appels portent un `etat_conversation` versionné (clé `v` présente en base) ;
- **contrôle négatif** : avec `sauver_rdv` neutralisé, le contrat remonte 5 écarts — la
  suite exerce donc réellement Postgres, elle ne passe pas à vide.

**Définition de « terminé » de la phase : le point 1 est atteint.** Un RDV traverse en base
tampon → validé ET tampon → expiré → SMS de repli en file. Restent : l'API HTTP et l'envoi
SMS réel.

**Reste pour clore la phase backend.**
1. API FastAPI : `build_lead()` figé en Pydantic, auth artisan + auth webhook distinctes,
   T01 rejoué en HTTP (un tour = une requête, aucune session en mémoire).
2. Adaptateur d'envoi SMS + plage de non-envoi 21 h–08 h.
3. Correctif `MockLLM` (regex de nom sans `IGNORECASE`) avec son test R19.
4. Décision fuseaux/DST avant la prod (cf. entrée brique 3).
5. `FOR UPDATE SKIP LOCKED` quand plusieurs workers tourneront (optimisation, pas justesse).

**Prochaine étape convenue :** l'API FastAPI.

---

## Session du 23/08/2026 (suite) — brique 4 : API HTTP (FastAPI)

**Fait.**
- `relais_proto/api.py` : la façade. `POST /webhooks/appel` (ouverture),
  `POST /webhooks/appel/{id}/tour` (un tour), `GET /rdv` (boîte de validation),
  `POST /rdv/{id}/valider|refuser`, `GET /sante`. Collaborateurs injectés (dépôt, LLM,
  horloge) : les tests passent des doubles, la prod les implémentations réelles.
- `relais_proto/registre.py` : artisans, numéros Relais, tokens **en SHA-256 seulement**,
  comparaison à temps constant sur tous les artisans. Deviendra la table `artisan`.
- `serveur.py` : câblage de production (`uvicorn serveur:app`). Refuse de démarrer si
  `DATABASE_URL` ou `RELAIS_WEBHOOK_SECRET` manque, plutôt que de tourner à moitié
  configuré. Vérifié contre le vrai Supabase : `/sante` 200, auth 401, aucune écriture.
- Test **R19** + mutations : **7/7 détectées**. Suite : **23 PASS en 1,05 s**.
  Postgres rejoué après coup : toujours vert.

**Les deux portes sont étanches, et c'est testé dans les deux sens.** Un token d'artisan
présenté comme secret webhook est refusé ; le secret webhook présenté comme token porteur
est refusé. C'était le point du cadrage : l'appelant du webhook est la plateforme vocale,
pas l'artisan — celui-ci est identifié par le **numéro Relais appelé**, jamais par un
secret confié à un tiers.

**Un tour = une requête, prouvé de la manière forte.** R19 construit une **app neuve à
chaque requête**, ne partageant que le dépôt. Si l'API gardait le moindre état
conversationnel en mémoire, l'appel ne pourrait pas se poursuivre. Et les répliques HTTP
sont comparées **mot pour mot** à un déroulé en process : l'API ne reformule rien.

**Étanchéité entre artisans.** Martin ne voit pas les RDV de Dupont et ne peut pas les
valider — **404, pas 403** : ne pas révéler qu'un RDV existe chez un autre artisan.

**Deux défauts trouvés en écrivant les tests, pas le code.**
1. L'API laissait `Conversation` créer son calendrier sur `dt.datetime.now()`, hors de
   l'horloge injectée : non testable, et le libellé d'un créneau aurait pu changer en cours
   d'appel. Le calendrier est désormais calé sur l'horloge à l'ouverture, puis son `now`
   voyage dans l'état sérialisé — les libellés prononcés gardent leur sens même si l'appel
   franchit minuit.
2. Un appel dont l'état n'a jamais été écrit produisait une `AttributeError` en 500.
   Désormais 409 explicite. (Défaut révélé par la mutation « état non persisté ».)

**Reste pour clore la phase backend.**
1. Adaptateur d'envoi SMS + plage de non-envoi 21 h–08 h.
2. Correctif `MockLLM` (regex de nom sans `IGNORECASE`) avec son test R20.
3. Décision fuseaux/DST avant la prod.
4. Push réel vers l'app (aujourd'hui la relance artisan reste en file).
5. `FOR UPDATE SKIP LOCKED` quand plusieurs workers tourneront.

**Prochaine étape convenue :** l'envoi SMS réel, ou l'app mobile qui consomme `GET /rdv`.

---

## Session du 23/08/2026 (suite) — brique 5 : expédition des messages sortants

**⚠️ AUCUN FOURNISSEUR SMS N'EST CÂBLÉ.** Ce qui est construit : la plage de silence, les
réessais, l'échec définitif, et le **port fournisseur**. `EnvoyeurJournal` journalise sans
rien envoyer — volontaire tant que le fournisseur n'est pas choisi. Rien ne part réellement.

**Fait.**
- `relais_proto/envoi.py` : `heure_d_envoi_autorisee` (plage de silence), port `Envoyeur`,
  `EnvoyeurJournal`, worker `Expediteur`.
- `message_sortant` gagne `essais`, `derniere_erreur`, `envoyer_apres`, `reference`
  (migration 002, appliquée et vérifiée sur Supabase).
- `worker.py` : un passage expiration + expédition, pour un cron.
- Test **R20** + contrat étendu (les 3 nouvelles méthodes du dépôt tournent aussi contre
  Postgres). Mutations : **8/8 détectées**. Suite : **24 PASS**. Postgres : vert.

**La plage de silence est la vraie substance de cette brique.** Depuis que les délais sont
comptés en heures réelles (24 h / 2 h), une échéance peut tomber à 3 h du matin — et
l'expiration déclenche un SMS au client. Règles retenues :
- plage `21:00 → 08:00`, **configurable par artisan** (`sms.plage_silence`) ;
- elle ne s'applique qu'aux messages **CLIENT** : la relance de l'artisan est son outil de
  travail, et c'est lui qui a choisi de prendre les urgences la nuit ;
- une plage à cheval sur minuit se teste avec un **OU**, pas un ET — l'erreur qui rendrait
  la plage vide est explicitement couverte par une mutation.

**Validé sur données réelles, par accident heureux.** Premier passage de `worker.py` contre
Supabase à 22 h 11 : 6 messages en file → **3 push artisan envoyés, 3 SMS client différés**.
Exactement le comportement voulu, observé sans l'avoir mis en scène.

**Défaut inter-locataires transformé en refus explicite.** `message_sortant` ne porte pas
d'`artisan_id` : l'expéditeur ne peut pas savoir de quel artisan relève un message et
appliquerait la plage de silence du premier à tous. Plutôt que de laisser dormir ce bug,
`worker.py` **refuse de tourner si le registre contient plus d'un artisan**. Correctif :
colonne `artisan_id` sur `message_sortant` (migration 003) + résolution de la config par
message. À faire avant le deuxième artisan, pas avant la prod.

**Contradiction de specs à trancher — bloquante pour le choix du fournisseur.**
`config-artisan-v1.md` prévoit `sms.expediteur: "DupontChauf"`, un sender ID
**alphanumérique**. Or la spec produit §3.5bis et §4 exigent de **lire les réponses SMS du
client** (« Répondez OUI pour confirmer »). Un sender alphanumérique est **unidirectionnel
par construction** : il ne reçoit rien. Conséquence : le SMS doit partir **du numéro
Relais** (qui vit dans le registre, pas dans la config artisan), et `sms.expediteur` n'a
plus de sens en V1. Avertissement ajouté dans le schéma documenté.
À prévoir aussi : les sender IDs alphanumériques doivent être déclarés auprès des
opérateurs français via le fournisseur — délai calendaire, comme la vérification OAuth
Google. Sans objet si l'on part sur un numéro.

**Reste pour clore la phase backend.**
1. **Choix du fournisseur SMS** (contrainte : numéro FR bidirectionnel, hébergement UE) —
   décision business, puis adaptateur derrière le port `Envoyeur`.
2. Lecture des SMS entrants (spec §3.5bis) : réponses OUI/NON sur le fil de confirmation.
3. `artisan_id` sur `message_sortant` (migration 003).
4. Push réel vers l'app.
5. Correctif `MockLLM` (`IGNORECASE`) + test R21. Décision fuseaux/DST.

**Prochaine étape :** trancher sender alphanumérique vs numéro, et choisir le fournisseur.

---

## Session du 23/08/2026 (suite) — brique 6 : validation client par LIEN (remplace §3.5bis)

**Arbitrage produit.** SMS **strictement sortant**, et « Répondez OUI » remplacé par un
**lien à un tap**. Motif : vérifié en séance, les opérateurs français réservent les numéros
mobiles au P2P (interdits à l'A2P), le chemin bidirectionnel passe par un numéro `09 3X`
« SMS conversationnel », et la Charte Business Messaging de l'AF2M du **1er mars 2026**
durcit la validation des Sender ID. Le lien supprime d'un coup le numéro dédié, la
conformité entrante et la brique « lecture des SMS reçus ». Fournisseur : Geoffrey instruit
OVHcloud (téléphonie + SIP + Time2Chat chez le même acteur, français, UE) ; l'adaptateur
attend des identifiants.

**Fait.**
- `rdv.py` : nouvel état **`repropose`** (en attente DU CLIENT, non terminal),
  `reproposer()` et `confirmer_par_client()`.
- `confirmation.py` : jetons de 32 octets d'aléa, **empreinte SHA-256 seule en base**,
  usage unique, échéance opposée.
- API : `POST /rdv/{id}/reproposer` (artisan), `GET /c/{jeton}` et `POST /c/{jeton}`
  (client, sans authentification — le jeton EST son authentification).
- `messages.py` : gabarits `reproposition_client` (avec le lien) et `confirmation_artisan`.
- `calendar_stub.libelle_creneau` extrait : le libellé prononcé à l'appelant et celui écrit
  dans le SMS ont désormais **une seule source**.
- Migration 003 (colonne + index unique sur le jeton + statut au check + les deux index
  partiels élargis), appliquée et vérifiée sur Supabase.
- Test **R21** + mutations **7/7**. Suite : **25 PASS**. Postgres : vert.

**Décisions de sécurité, toutes dans le domaine et non dans l'API.**
- Le jeton n'existe en clair que dans le SMS. Le contrat vérifie qu'il **n'apparaît nulle
  part en base**.
- Usage unique : effacé à la validation. Un lien rejoué rend 404, sans distinguer « déjà
  utilisé » de « jamais existé » — on ne renseigne pas un attaquant.
- L'échéance est opposée au lien comme au tap de l'artisan.
- La page client est volontairement pauvre : entreprise, prénom de l'artisan, créneau.
  **Ni nom, ni téléphone, ni transcript** — l'URL vaut capacité, quiconque la possède ne
  doit rien apprendre sur la personne. Vérifié par assertion.
- `RELAIS_BASE_URL` est **exigée au démarrage** : un lien pointant sur un mauvais domaine
  est mort chez le client sans provoquer la moindre erreur côté serveur.

**Deux fois où le test avait raison contre moi.**
1. La matrice de transitions de R15 est écrite **en dur** : ajouter `repropose` a fait
   échouer le test, ce qui a forcé une décision explicite (l'artisan garde le droit de
   trancher lui-même un RDV reproposé) au lieu de laisser le test suivre le code.
2. Mon assertion « l'échéance repart de zéro » passait à tort avec une horloge figée :
   remise à zéro depuis le même instant → même valeur. Horloge avancée d'une heure et
   valeur exacte épinglée. Une mutation de mon script de mutation était elle aussi
   inopérante (`hashlib` importé dans la fonction, pas au module) — corrigée, le cas
   « lien réutilisable » est bien attrapé.

**Reste pour clore la phase backend.**
1. Adaptateur OVH derrière le port `Envoyeur` (attend les identifiants).
2. `artisan_id` sur `message_sortant` (migration 004) — `worker.py` refuse toujours
   plusieurs artisans.
3. Push réel vers l'app. Correctif `MockLLM` (`IGNORECASE`). Décision fuseaux/DST.

**Prochaine étape :** l'app mobile qui consomme `GET /rdv`, ou l'adaptateur OVH dès que tu
as les accès.

---

## Session du 23/08/2026 (suite) — migration 004 : multi-artisans dans les workers

**Défaut corrigé.** `message_sortant` ne portait pas d'`artisan_id`. L'expéditeur appliquait
donc la plage de silence du premier artisan aux clients de tous. `worker.py` refusait de
tourner au-delà d'un artisan (garde volontairement bruyante) — ce refus est levé.

**Et un défaut plus grave trouvé en chemin.** `WorkerExpiration` avait exactement le même
problème, en pire : les gabarits portent le **nom de l'entreprise et le prénom du patron**,
donc un client aurait reçu un SMS **signé du mauvais artisan**. La plage de silence est un
désagrément ; une signature erronée est une faute vis-à-vis du client et de l'artisan. Les
deux workers résolvent désormais la config via `config_pour(artisan_id)`.

**Fait.**
- Migration 004 : colonne `artisan_id` sur `message_sortant` + index partiel par artisan.
  Nullable et sans reprise de données — aucune base de production n'existe, et l'expéditeur
  **refuse d'envoyer un message sans artisan connu** plutôt que de deviner. Le message
  reste en file et apparaît dans le rapport : bruyant, pas muet.
- `Brouillon` et `MessageSortant` portent `artisan_id` ; les 4 gabarits le renseignent
  depuis `rdv.artisan_id`.
- `WorkerExpiration(depot, config_pour)` et `Expediteur(depot, envoyeur, config_pour)`.
- Contrat étendu (l'`artisan_id` du message fait l'aller-retour, vérifié aussi sur
  Postgres). R20 gagne un cas **deux artisans, deux plages de silence** + un cas artisan
  inconnu. Suite : **25 PASS**. Mutations : R16 9/9, et le comportement d'avant 004
  (« une config pour tous ») est détecté.

**Choix de test.** Le résolveur des tests est **strict** (`CFG` seulement pour
`art-dupont`, `None` sinon) : un `lambda _: CFG` aurait rendu la résolution par artisan
invisible, donc non testée. C'est le même principe que la matrice de transitions écrite en
dur — un test ne doit pas se contenter de suivre le code.

**Vérifié sur Supabase.** Migration 004 appliquée, contrat vert, et `worker.py` tourne
désormais avec les **deux** artisans du registre : 6 messages examinés à 22 h 57 →
3 journalisés, 3 différés (plage de silence), 0 échec.

**Reste pour clore la phase backend.**
1. Adaptateur OVH derrière le port `Envoyeur` (attend les identifiants).
2. Push réel vers l'app.
3. Correctif `MockLLM` (`IGNORECASE`) + test. Décision fuseaux/DST.
4. `FOR UPDATE SKIP LOCKED` quand plusieurs workers tourneront.

**Prochaine étape :** l'app mobile qui consomme `GET /rdv`, ou l'adaptateur OVH.

---

## Session du 23/08/2026 (fin) — correction : OVH était retenu pour une raison périmée

**Question posée par Geoffrey (via Claude Desktop) :** « Pourquoi OVH précisément, et pour
quel usage : l'envoi de SMS, ou les numéros de téléphone ? »

**Réponse honnête : OVH était mon candidat pour la mauvaise raison.** Mon raisonnement
reposait sur une contrainte — *un seul numéro doit porter la voix ET le SMS, pour que les
réponses du client reviennent sur le numéro Relais* — qui faisait d'OVH le seul acteur
plausible (voix + SIP + SMS chez le même fournisseur). **La décision du lien à un tap a
supprimé cette contrainte** : sans SMS entrant, il n'y a plus rien à faire revenir, et voix
et SMS se découplent entièrement. Je l'avais entrevu sur le moment sans mettre la
recommandation à jour : elle est restée dans ce journal avec sa justification morte.

**Deux décisions désormais séparées.**
- **SMS** : choix ouvert et réversible (port `Envoyeur`). OVH reste défendable (FR, UE,
  §9) mais n'est plus spécialement motivé. Le critère a changé : le flux par lien ne
  demande qu'un SMS transactionnel sortant avec **sender ID alphanumérique déclaré**, donc
  ce qui compte est la **qualité du processus de déclaration** (Charte AF2M du 01/03/2026),
  pas le catalogue téléphonie.
- **Numéros / voix** : ne rien anticiper. Les plateformes managées (Vapi, Retell)
  fournissent leurs numéros ou s'intègrent en trunk SIP ; prendre des numéros avant d'avoir
  choisi la plateforme créerait une double tuyauterie. Le choix du fournisseur de numéros
  **découle** du choix de plateforme vocale, qui n'est pas fait.

**Sur les clés d'API.** Aucune n'est nécessaire tant que l'adaptateur n'existe pas :
`EnvoyeurJournal` est le mode par défaut et rien ne part. Le jour où l'on en crée, droits
au strict minimum — chez OVH, un consumer key limité à `POST /sms/*`, avec expiration, et
surtout pas de `/*` ni de `GET /me/*`.

**Leçon.** Une recommandation dont la prémisse tombe doit être révisée explicitement, pas
laissée en place « au cas où ». Elle avait survécu deux entrées de journal.

---

## Session du 23/08/2026 (fin) — adaptateur SMS écrit, premier envoi réel à faire

**Question de Geoffrey : « on ne teste pas les SMS tout de suite au final ? »** Report qui
était mon choix, pas une contrainte — et en répondant « je n'ai besoin d'aucune clé
aujourd'hui » j'oubliais un principe appliqué depuis deux jours : **la déclaration du Sender
ID est du temps calendaire**, comme la vérification OAuth Google. Ça se lance tout de suite.

**Deux blocages distincts, à ne pas confondre.**
- *Tester l'adaptateur* (notre code parle-t-il correctement à OVH, gère-t-il les erreurs,
  les réessais, l'accusé) → il suffit d'une clé, et une bonne partie se teste sans.
- *Tester la délivrabilité* vers un mobile FR avec un expéditeur conforme → dépend de la
  déclaration du Sender ID, qui prend des jours.

**Fait.**
- `envoi_ovh.py` : adaptateur OVH, **transport injecté** — la signature de requête et le
  choix d'endpoint restent au SDK officiel, donc hors de notre code. Ce qui est à nous et
  donc testé : format **E.164** (nous stockons « 0612345678 », OVH veut « +33612345678 »),
  corps de requête avec `noStopClause` (SMS transactionnel : la clause STOP n'est pas
  requise et mangerait ~20 caractères utiles), et classification des échecs.
- **`EchecDefinitif` remonté dans le port** `envoi.py` : ce n'est pas une notion OVH, c'est
  l'expéditeur qui doit savoir ne pas s'acharner. Un numéro invalide sort de la file **au
  premier passage** au lieu d'user trois tentatives et de retarder les autres messages.
- `envoyer_un_sms.py` : premier envoi réel, à la main, **blanc par défaut** — il faut
  `--envoyer` pour qu'un SMS parte. Il affiche la **réponse brute** d'OVH, puisque c'est
  précisément ce qui validera ou démentira l'hypothèse encodée dans l'adaptateur.
- Test **R22**. Suite : **26 PASS**.

**Ce que R22 ne prouve pas.** Les doubles reproduisent la forme de réponse que je *crois*
(`ids` / `validReceivers` / `invalidReceivers`). Un test contre ses propres hypothèses ne
les valide pas : seul le premier appel réel tranche. C'est écrit en tête du module.

**À faire côté Geoffrey.**
1. Compte OVH + crédits SMS + consumer key limité à `POST /sms/*` avec expiration.
2. **Lancer la déclaration du Sender ID sans attendre** (délai de plusieurs jours).
3. `python envoyer_un_sms.py <ton numéro>` puis `--envoyer`, et me rapporter la réponse
   brute — surtout si elle diverge de l'hypothèse.

**Prochaine étape :** l'app mobile sur `GET /rdv`, indépendante de tout fournisseur ; ou
brancher l'`EnvoyeurOVH` dans `worker.py` dès que le premier envoi réel a réussi.

---

## Session du 24/08/2026 — premier envoi réel : échec instructif, et deux fautes à moi

**Résultat brut.** `POST /sms/sms-ab12345-1/jobs` →
`ResourceNotFoundError: This service does not exist`.

**Ce n'était pas le Sender ID.** La valeur envoyée, `sms-ab12345-1`, était **le gabarit de
mon `.env.example`**, recopié tel quel — ce qui est logique, je l'avais écrit sous une forme
qui ressemble à un vrai nom de service, alors que pour Supabase j'utilise des `<ref>`
visiblement faux. Et l'unique indice d'erreur du script pointait vers le Sender ID, ce qui
a envoyé Geoffrey chercher au mauvais endroit. **Deux fautes à moi, pas une erreur de
manipulation.**

**Acquis réel malgré l'échec : l'authentification fonctionne.** La requête a été signée,
acceptée et routée — OVH répond avec une erreur applicative et un `Query-ID`. Une clé
invalide donne `InvalidKey` (vérifié en repassant avec de faux identifiants). Donc le
triplet et les droits du consumer key sont bons.

**Corrigé.**
- `.env.example` : gabarit devenu `<remplace-moi-par-ton-service-sms>`, cohérent avec la
  convention déjà utilisée pour Supabase.
- `envoyer_un_sms.py` **refuse le gabarit avant tout appel réseau** : la boucle
  d'aller-retour ne se reproduira pas.
- **Diagnostic par motif** au lieu d'un indice unique : service inexistant / identifiants
  et droits / Sender ID / crédits / motif inconnu. Chaque piste dit quoi faire. Le motif
  `InvalidKey` a été ajouté grâce à l'essai accidentel avec de faux identifiants.
- `--comptes` : liste les services SMS via `GET /sms`. Demande ce droit de lecture sur le
  consumer key — à noter, la portée minimale que j'avais recommandée (`POST /sms/*` seul)
  ne permet PAS de découvrir le nom du service.

**Diagnostic probable.** Créer un compte OVH ne crée pas de service SMS : il faut le
**commander et le créditer**. C'est très probablement ce qui manque, avant même la question
du nom.

**Leçon.** Un gabarit de configuration doit être **impossible à confondre avec une vraie
valeur**, et un message d'erreur ne doit jamais proposer une seule piste quand plusieurs
causes sont plausibles — il transforme une erreur de dix secondes en fausse piste de dix
minutes.

### 24/08 — suite : `NotGrantedCall`, et un diagnostic qui se construit une panne à la fois

`python envoyer_un_sms.py --comptes` → `NotGrantedCall: This call has not been granted`.
Cause : le consumer key n'a pas `GET /sms` dans ses règles d'accès. C'est un problème de
**portée**, pas d'identifiants — la clé est valide, l'appel n'est simplement pas couvert.

**Deuxième motif manquant en deux essais.** Mon diagnostic est retombé sur « motif non
reconnu ». J'ajoute `NotGrantedCall`, **placé avant** les motifs d'identifiants : les
confondre enverrait vérifier un triplet qui va très bien.

**Arbitrage : ne PAS élargir la clé.** Le nom du service se lit dans l'espace client
(Telecom > SMS) et ne sert qu'une fois. Ajouter `GET /sms` pour la commodité de `--comptes`
contredirait le principe de portée minimale que j'ai moi-même recommandé. `--comptes` reste
disponible pour qui a accordé ce droit, mais ce n'est plus le chemin conseillé.

**Correction de méthode.** Cette table de diagnostic ne saura jamais tout d'avance : elle se
remplit à chaque échec réel. Le repli « motif non reconnu » ne doit donc pas laisser sans
prise — il liste maintenant les quatre familles par ordre de probabilité. Un diagnostic
incomplet est normal ; un diagnostic qui n'oriente pas est un défaut.

### 24/08 — la plomberie OVH répond, et le diagnostic passe enfin sous test

**Progression réelle.** Service `sms-hb237083-1` trouvé dans l'espace client (pas via
`--comptes`, dont l'appel `GET /sms` n'est pas dans la portée de la clé — et c'est très bien
ainsi). La requête atteint désormais le service et est acceptée. Nouvelle erreur :
`APIError: Sms sender DupontChauf does not exists. Please create it first`.

**Ce qui est donc CONFIRMÉ par des appels réels** : l'authentification, le nom du service,
et l'acceptation du corps de requête tel que l'adaptateur le construit. **Pas encore
confirmé** : la forme de la réponse en cas de succès (`ids` / `validReceivers` /
`invalidReceivers`) — il manque l'expéditeur pour aller jusque-là.

**Troisième ratage du diagnostic, et le plus instructif.** Le message contient
« does not exists », qui déclenchait la piste « nom de service faux », alors que le mot
`sender` y figure explicitement. **Un motif générique masquait un motif spécifique**, parce
que les motifs sont testés dans l'ordre. Ce n'était pas une ligne à ajouter mais un défaut
de structure. Deux corrections :
- ordre **du plus spécifique au plus générique**, `sender` en tête ;
- le motif générique resserré : « **service** does not exist » et non « does not exist ».

**Et surtout : le diagnostic est déplacé dans `envoi_ovh.py` et mis sous test.** Une
taxonomie d'erreurs est une connaissance du fournisseur, sa place est dans l'adaptateur, pas
dans un script — et elle devient ainsi couverte par R22, avec les **quatre erreurs
réellement reçues** comme cas de régression. Trois erreurs de suite dans une fonction hors
suite : le vrai défaut était de l'avoir laissée hors suite.

**Prochain essai côté Geoffrey** : créer l'expéditeur `DupontChauf` (Telecom > SMS >
Expéditeurs), puis relancer. Attention, un expéditeur alphanumérique passe par une
validation opérateur — le délai peut être de quelques jours.

### 24/08 — mode numéro court, pour ne pas attendre 72 h

**Objectif : un premier envoi réel aujourd'hui**, sans attendre la validation du Sender ID
`DupontChauf` (lancée, ~72 h, et **risque de refus** : Dupont Chauffage est fictif, aucun
justificatif à ce nom).

**Fait.** `EnvoyeurOVH(..., numero_court=True)` envoie via `senderForResponse: true` et
**sans** clé `sender` — les deux sont mutuellement exclusifs côté OVH. Un numéro court est
disponible par défaut, sans déclaration. Exposé par `--numero-court`, affiché en clair dans
le récapitulatif, et incompatible avec `--expediteur` (refus explicite).

**Deux choix de conception.**
1. **Mode explicite, pas déduit de l'absence d'expéditeur.** Une config incomplète
   basculerait sinon silencieusement en numéro court — où les URL sont bloquées — et le lien
   de validation disparaîtrait sans erreur visible. Une omission de configuration doit
   lever, pas changer de comportement.
2. **La limite « URL bloquée » est un GARDE, pas un commentaire.** Un commentaire s'ignore.
   `EchecDefinitif` si le texte contient une URL en mode numéro court : sans ça le SMS de
   reproposition partirait et serait jeté par l'opérateur, silencieusement. R22 vérifie aussi
   que le mode **normal** accepte ce même message — c'est le cas de production.

**Question produit à trancher (soulevée par Geoffrey).** Un Sender ID par artisan = un
justificatif par artisan : **ça ne passe pas à l'échelle**. Un expéditeur unique
« **Relais** » est probablement la réponse. Argument technique en sa faveur : nos gabarits
identifient déjà l'artisan **dans le corps** du message (« Bonjour, c'est {nom_entreprise} »
et « {prenom} vous propose plutôt… »), donc un expéditeur unique ne perd aucune information.
Contrepartie à assumer : le client voit « Relais » et non la marque de l'artisan — le produit
devient visiblement le nôtre plutôt qu'en marque blanche. À arbitrer avec le cousin ; c'est
une décision de positionnement autant que de conformité.

**Note de méthode.** Les deux modifications que Geoffrey croyait non commitées (réordonnancement
du diagnostic, option `--expediteur`) étaient déjà dans `62293bc` : mon `git add -A` les avait
balayées, comme le fichier de skill. Rien perdu, mais deuxième confirmation que le staging
global est à abandonner.

### 24/08 — PREMIER SMS RÉEL ENVOYÉ, et l'hypothèse d'API confirmée

`python envoyer_un_sms.py 0635475379 --envoyer --numero-court` → **succès**, référence
`ovh:802084252`.

**L'hypothèse encodée dans l'adaptateur était juste.** Réponse observée :

    {"ids": [802084252], "validReceivers": ["+33..."], "invalidReceivers": [],
     "totalCreditsRemoved": 1, "creditsLeft": 99, "tag": "vtbnzoi6prvylh12"}

Les trois clés que R22 supposait sont les bonnes, aux noms et aux formes près. Les doubles
de test ont été **remplacés par cette réponse réelle** : ils ne disent plus ce que je croyais
mais ce qui est.

**Deux champs non anticipés, dont un opérationnellement important.**
- `creditsLeft` : désormais capté par l'adaptateur (`credits_restants`) et remonté à chaque
  passage de `worker.py`, avec alerte sous 20. **Une réserve épuisée arrête tous les SMS
  clients sans provoquer la moindre erreur applicative** — c'est le genre de panne qu'on
  découvre par l'appel d'un client qui n'a rien reçu.
- `tag` : servira à rapprocher les accusés de réception le jour où l'on branchera les
  rapports de livraison.

**Trouvaille de coût, à arbitrer.** Longueur rendue des gabarits, sachant qu'OVH facture
**1 crédit par tranche de 160 caractères** :

| gabarit | caractères | crédits |
|---|---|---|
| `expiration_client` (SMS) | 195 | **2** |
| `reproposition_client` (SMS) | 194 | **2** |
| `expiration_artisan` (push) | 172 | — |
| `confirmation_artisan` (push) | 93 | — |

Les **deux SMS clients dépassent 160 de peu et coûtent donc le double**. Deux leviers :
raccourcir la copie (~35 caractères à gagner), et surtout **raccourcir le jeton de
confirmation** — 32 octets d'aléa donnent une URL de 64 caractères ; 16 octets suffisent
largement pour un lien à usage unique et borné dans le temps (128 bits) et feraient gagner
21 caractères. À arbitrer : c'est de la copie produit et un paramètre de sécurité.

**Reste non vérifié :** le SMS est-il ARRIVÉ sur le téléphone ? `validReceivers` et un
crédit débité disent que l'opérateur l'a accepté, pas qu'il a été délivré.

### 24/08 — LIVRAISON CONFIRMÉE : la chaîne sort enfin du système

Les SMS sont **bien arrivés sur le téléphone**. Ce n'était pas acquis :
`validReceivers` + un crédit débité disaient seulement que l'opérateur avait accepté.
Chaîne complète prouvée : notre code → API OVH → opérateur → téléphone.

**C'est le premier maillon du produit qui sort réellement du système.** Tout le reste —
conversation, RDV, expiration, API, workers — était vérifié en boucle fermée.

**Observation qui débloque la moitié du chemin.** Les deux SMS clients n'ont pas la même
contrainte :

| gabarit | contient une URL ? | numéro court possible ? |
|---|---|---|
| `expiration_client` | non | **oui — utilisable dès maintenant** |
| `reproposition_client` | oui (lien de validation) | non, URL bloquée |

Donc le **SMS de repli sur expiration peut passer en production tout de suite**, sans
attendre la validation du Sender ID. Seule la reproposition doit attendre `DupontChauf` ou
l'expéditeur unique « Relais ». La contrepartie à peser : le client verrait un numéro court
pour un message et un expéditeur nommé pour l'autre — incohérence de marque assumée
temporairement, ou attendre et tout livrer ensemble.

**Deux décisions toujours en attente.**
1. **Jeton à 16 octets au lieu de 32** (128 bits, largement suffisant pour un lien à usage
   unique et borné) + copie raccourcie : ferait passer les deux SMS clients sous 160
   caractères, donc **1 crédit au lieu de 2**. Paramètre de sécurité + copie produit.
2. **Expéditeur unique « Relais »** plutôt qu'un Sender ID par artisan (un justificatif par
   artisan ne passe pas à l'échelle). Décision de positionnement.

**Prochaine étape technique.** `worker.py` utilise encore `EnvoyeurJournal` en dur : rien
ne part du pipeline automatisé. Câbler `EnvoyeurOVH` **en opt-in explicite** (variable
d'environnement, journal par défaut) est le pas qui fait passer de « on sait envoyer à la
main » à « le système sait envoyer ».

### 24/08 — coût du SMS ramené de 3 crédits à 1, et verrouillé par R23

Trois leviers appliqués. Le classement s'est inversé en cours de route.

| gabarit | avant | après |
|---|---|---|
| `expiration_client` | 195 car. GSM-7 → **2 crédits** | 131 car. → **1** |
| `reproposition_client` | 194 car. **UCS-2** → **3 crédits** | 134 car. GSM-7 → **1** |
| `expiration_artisan` (push) | UCS-2 | GSM-7 (sans effet de coût, mais prêt pour un repli SMS) |

**Le levier dominant n'était pas celui annoncé.** Le jeton à 16 octets rend 21 caractères,
mais **seul il ne changeait rien** : la reproposition restait à 3 segments. Le vrai coupable
était l'**encodage** — le « ô » de « plutôt » suffisait à faire basculer tout le message en
UCS-2, où la limite tombe de 160 à 70. Faux amis à connaître : `é è ù ì ò à` sont dans
GSM-7, **`ê ô î û À « » — …` non**.

**Jeton : 32 → 16 octets.** Pas un compromis sécurité/coût — 128 bits pour un lien à usage
unique, borné dans le temps et stocké en empreinte, c'est l'ordre d'un UUID v4. 32 octets
était du gaspillage par réflexe.

**Copie.** « à la place » sacrifié dans la reproposition : plus juste, mais 11 caractères sur
une marge mince (le lien pèse 43 caractères à lui seul). Une **racine de domaine courte est
un gain financier réel** — chaque caractère du lien est payé sur chaque SMS.

**R23 verrouille, et il a corrigé deux erreurs de ma part.**
- `segments_sms()` dans `envoi.py` : GSM-7 vs UCS-2, seuils 160/70 en un segment, 153/67 en
  concaténé (7 octets d'en-tête).
- Le test rend chaque gabarit avec un artisan « nom long » (25 car. + prénom de 15) qui
  définit l'**enveloppe supportée**, pas un cas pathologique. Au-delà, deux crédits — à
  faire respecter à l'onboarding si nécessaire.
- **Première erreur attrapée** : `expiration_client` tenait pile en 160 avec l'artisan de
  référence. Sans marge exigée, le premier artisan au nom un peu long doublait la facture
  en silence.
- **Seconde erreur, la mienne** : j'imposais la limite de 160 aux gabarits **push**, qui n'en
  ont aucune. Contrainte inventée. R23 exige donc GSM-7 partout (gratuit, et utile le jour du
  repli SMS artisan) mais un seul segment uniquement pour les `*_client`.

Suite : **27 PASS**.

**Décision toujours ouverte** : expéditeur unique « Relais » (recommandé) vs Sender ID par
artisan. Rien dans le code ne la préempte — `sms.expediteur` reste par artisan.
