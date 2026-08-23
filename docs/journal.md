# Journal du projet Relais

> 3 lignes par session : fait / décidé / prochaine étape. Toute nouvelle conversation
> (Claude ou humaine) redémarre en lisant ce fichier + `docs/`.

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
