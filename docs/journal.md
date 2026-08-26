# Journal du projet Relais

> 3 lignes par session : fait / décidé / prochaine étape. Toute nouvelle conversation
> (Claude ou humaine) redémarre en lisant ce fichier + `docs/`.

---

# ÉTAT AU 25/08/2026 (soir) — à lire en premier

> **Ce bloc se REMPLACE, il ne s'empile pas.** Les entrées datées plus bas sont le journal
> chronologique (le pourquoi des décisions) ; ce bloc-ci est le où-on-en-est.

## En une phrase

Le produit s'appelle **NELYO**. Le backend de la phase 1 est fonctionnel, vérifié contre
un vrai Postgres, et l'agent conversationnel passe **57/57** en éval LLM réelle sur
**19 personas**, dont cinq tirés d'appels VOCAUX réels. L'artisan se connecte par code SMS et valide en
1 tap ; le client est prévenu sur toutes les issues. **Il ne manque que la voix** — le
point d'entrée du produit. Plus rien d'autre n'est bloqué côté code.

## Ce qui tourne

```bash
cd proto
python run_scenario.py                              # 66 tests, ~3 s, sans clé ni base
python semer_artisans.py [--ecrire]                 # amorce la table `artisan`
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
| Adaptateur OVH : E.164, corps, échecs (R22) | ✅ | **SMS réellement reçu, 24/08** |
| Page de confirmation client (HTML, sans JS) | ✅ | mock — le lien SMS mène à une vraie page |
| Boîte de validation artisan + session (R24) | ✅ | mock — utilisable dans un navigateur |
| Instants UTC vs heures de pendule (R25) | ✅ | mock + **migration 007 sur Supabase** |
| Extraction du nom de l'appelant (R26) | ✅ | mock, mutations 6/6 |
| Nom de produit et expéditeur en config (R29) | ✅ | mock, mutations 7/7 |
| Homonymes de communes, commune confirmée (R30) | ✅ | mock, mutations 6/6 |
| Question de prix ≠ refus de créneau (R31) | ✅ | mock, mutations 4/4 |
| Homonymes, corrections, boucles bornées (R32) | ✅ | mock, mutations 6/6 |
| Prestation refusée déclinée (R33) | ✅ | mock, mutations 6/6 |
| **Éval LLM réelle, 14 personas × 3** | ✅ **42/42** | agent **Haiku 4.5**, appelant Sonnet 5 — 7ᵉ passage, 0 incident de harnais |
| **19 personas** (5 tirés d'appels vocaux réels) | ✅ **57/57** | agent Haiku 4.5 — 50/57 → 55/57 → **57/57** le 26/08, 0 incident de harnais |
| SMS de confirmation au client, chemin nominal (R27) | ✅ | mock, mutations 5/5 |
| Table `artisan` + FK sur 5 tables (migration 008) | ✅ | **Supabase réel**, contrat du port |
| Connexion artisan par code SMS (R28) | ✅ | mock, mutations 7/8 (1 défense en profondeur) |
| Nom du produit et expéditeur SMS en config (R29) | ✅ | mock, mutations 7/7 |
| Sortie prononçable : emoji et markdown (R37) | ✅ | mock, mutations 5/5 |
| Créneaux prononcés verbatim (R38) | ✅ | mock, mutations 2/2 |
| Contrainte nouvelle > « rien de plus tôt » (R39) | ✅ | mock, mutations 2/2 |
| **Sonde de l'étape 0, chantier voix (R40)** | ✅ | mock, mutations 13/13 + 7/7 + 8/8 — **appel réel : la sonde PARLE** |
| **Adaptateur de la plateforme vocale (R41)** | ✅ | mock, mutations 14/14 — **deux appels vocaux réels, scénarios complets** |
| Numéro jamais tronqué (R42) | ✅ | mock, mutations 10/10 |
| Code postal dicté avec séparateur (R43) | ✅ | mock, mutations 6/6 |
| Clôture verbatim et stable (R44) | ✅ | mock, mutations 5/5 |
| Commune canonique prononcée (R45) | ✅ | mock, *idem* |
| Une seule salutation par appel (R46) | ✅ | mock, mutations 7/7 |
| Nombres prononcés en toutes lettres (R47) | ✅ | mock, mutations 10/11 (1 défense en profondeur) |
| Question de la commune bornée (R48) | ✅ | mock, *idem* |
| Code postal avec barre, commune vérifiée (R49) | ✅ | mock, mutations 6/6 |
| Code postal validé par le contrôleur (R50) | ✅ | mock, mutations 7/8 (1 défense en profondeur, vérifiée) |
| Vouvoiement, jamais de tutoiement (R51) | ✅ | mock, *idem* |
| Aucune salutation en conversation (R52) | ✅ | mock, mutations 7/7 |
| Une seule question par réplique (R53) | ✅ | mock, *idem* — **contrôle AST de toutes les instructions** |
| Relecture du secteur avant refus (R54) | ✅ | mock, mutations 8/8 |
| Numéro confronté à ce qui a été dit (R55) | ✅ | mock, mutations 7/7 |
| Question du secteur verbatim, relance par les chiffres (R56) | ✅ | mock, *idem* |
| Paire commune/CP cohérente, refus verbatim (R57) | ✅ | mock, mutations 5/5 |
| Code postal relu en DEUX groupes (R58) | ✅ | mock, mutations 5/5 |
| Transcription qui se précise ≠ rejeu (R59) | ✅ | mock, mutations 5/5 — **un lead en zone perdu le 26/08** |
| Rattrapage des tours manqués (R60) | ✅ | mock, mutations 5/5 |
| « demain » / « aujourd'hui » comme contrainte (R61) | ✅ | mock, mutations 6/6 |
| Relance du numéro qui varie (R62) | ✅ | mock, mutations 5/5 — **premières phrases-tampons** |
| Identifiant d'appel imposé au dépôt (port) | ✅ | **contrat rejoué sur Supabase** |

## Ce qui est encore un double (et non un manque caché)

- **Pas de voix** : aucune plateforme vocale branchée, aucun numéro. L'API expose déjà les
  webhooks qu'elle appellera. **Le spike vocal ne s'ouvre pas seul** : session dédiée avec
  Claude (Cowork) avant tout engagement.
- **Envoi SMS** : la chaîne sort réellement (premier SMS réel le 24/08, réf.
  `ovh:802084252`), en mode **numéro court**. `EnvoyeurJournal` reste le défaut
  (`RELAIS_SMS=journal`), donc un cron mal configuré n'écrit à personne.
- **Réception SMS** : n'existe pas. C'est le pendant entrant du worker sortant, rendu
  nécessaire par la révision OUI/NON du 25/08. Trois questions à poser à OVH avant d'écrire
  la moindre ligne (coût des entrants, traitement du STOP, polling ou callback).
- **`CalendarStub`** : applique les vraies règles d'agenda sans être relié à un calendrier.
  Ce n'est **pas un cas dégradé** — c'est le cas de l'artisan sans agenda numérique, sans
  doute le cas courant. Le calendrier externe sera un anti-double-réservation, pas une
  condition d'existence du produit. Google/Outlook : **volontairement non lancé** (cf.
  dette n°4).
- **Pas de push** : la relance artisan est mise en file, jamais délivrée.
- **Onboarding d'un artisan** : la table `artisan` existe, mais le seul chemin
  d'écriture est `semer_artisans.py` depuis `config/artisans.json`. Il faudra un vrai
  parcours d'inscription, pas un script.

## Décisions verrouillées

- **Le LLM ne décide jamais**, l'artisan valide toujours (pas d'auto-validation en V1),
  annonce IA en ouverture et téléphone confirmé avant tout RDV.
- **Une décision terminale ne se prend jamais sur une donnée non relue** (R54, 26/08). Le
  secteur est relu à l'appelant avant tout refus hors zone — une fois, et une seule. La
  règle valait pour la commune glanée au passage et exemptait la donnée DEMANDÉE ; six
  appels vocaux ont montré que demander ne fiabilise rien quand la transcription se trompe.
- **Délais de validation : 24 h / 2 h en heures réelles**, réglables par artisan.
- **L'échéance fait foi, pas le passage du worker.**
- **Un horodatage est un INSTANT en UTC ; une heure de config est une heure de PENDULE**
  (`temps.py`, règle n°7).
- **SMS strictement sortant — CIRCONSCRIT le 25/08, pas annulé.** Le dialogue libre par
  SMS et le parsing de texte libre restent interdits. Mais la confirmation client passe
  désormais par une **réponse à vocabulaire fermé** (OUI/NON, liste blanche, une seule
  proposition active par numéro), qui n'est pas un dialogue. Le lien à un tap reste dans le
  code et redeviendra le chemin de confort quand un Sender ID existera : le canal devient un
  point de config (`sms_oui_non | lien`, défaut `sms_oui_non`).
- **Conséquence : le Sender ID ne bloque plus AUCUNE fonctionnalité.** Il ne reste que du
  confort de marque. ⚠ Mais le Kbis qu'il demandait **reparaît côté VOIX** : un numéro
  français exige un bundle réglementaire ARCEP (Kbis + pièce d'identité du dirigeant).
  Reporter l'administratif déplace le mur, il ne le supprime pas.
- **Deux portes d'authentification distinctes** (secret webhook / jeton porteur).
- **L'API ne décide jamais** : corollaire backend de la règle n°1.
- **Expéditeur SMS UNIQUE, déclaré sous NOTRE société** — pas sous celle de chaque artisan
  (décision du 25/08). Motifs : un seul Kbis à fournir, une réputation cumulée chez les
  opérateurs, des gabarits clients qui nomment déjà l'artisan dans le texte, et l'honnêteté
  vis-à-vis de l'opérateur — c'est nous qui émettons. Reste ouvert avec le cousin : le
  positionnement (produit visible vs marque blanche), pas la faisabilité.
- **⚠️ Affirmation PÉRIMÉE, produite le 24/08 et corrigée le 25/08** : « le Sender ID attend
  un artisan réel, qui attend la voix ». **Faux.** Il n'attend que le nom commercial, la
  structure juridique et le domaine. Ne pas la redécouvrir comme si elle était vraie.

## Dettes et décisions ouvertes

0. **LE COÛT CUMULÉ DES VERBATIM** (ouvert le 26/08, à trancher). Chaque `verbatim=True` a
   été ajouté après un défaut réel — R38, R44, R45, R56, R57 — et l'effet d'ensemble est que
   l'agent sonne préenregistré là où il devrait s'adapter. Geoffrey : *« on vend de l'IA avec
   notre produit, pas du message préenregistré »*. R62 apporte la réponse actuelle : donner
   au CONTRÔLEUR plusieurs phrases au lieu d'une (les « phrases-tampons » de l'arbitrage
   voix). **La piste à évaluer ensuite** : au lieu de figer des PHRASES, interdire les
   FAITS dans un tour formulé — un garde-fou qui refuse chiffres, dates, prix et noms de
   lieux hors verbatim. Le formuleur retrouverait sa liberté de formulation sans pouvoir
   inventer une donnée. Ce n'est PAS un changement de modèle : les phrases fautives sont
   verbatim, donc aucun modèle n'est consulté (mesuré).

1. ~~Le chemin nominal est muet~~ — **traité le 25/08** (`confirmation_client`, refus
   couvert aussi, R27). La classe de test qui manquait — confronter la promesse ORALE aux
   messages réellement mis en file — existe désormais.
2. ~~Nom commercial~~ — **tranché le 25/08 : NELYO.** Affiché « Nelyo », expéditeur
   déclaré « nelyo » (minuscules), 5 caractères sur les 11 autorisés, distinctif et
   prononçable à l'oral par le futur agent vocal. « Relais » reste le nom de CODE interne :
   repo, modules et tables ne sont pas renommés.
   Homonymes notés, non bloquants : une SAS NELYO (2020, coaching) et une SARL NELYO
   (2008, portails, apparemment dormante) — c'est la marque qui compte.
   **Séquence externe restante, aucune ne bloque le code** :
   INPI/marque → domaine (candidat `nelyo-ia.*`, **pas encore acheté**) → structure &
   Kbis → dépôt du Sender ID chez OVH (~72 h).
3. ~~Conséquences code du nom~~ — **traitées le 25/08** (`config/produit.json`, R29).
   Le nom et l'expéditeur sont des réglages, les contraintes AF2M sont vérifiées au
   démarrage, et R23 éprouve déjà 11 caractères. Le jour où le nom arrive : une ligne.
4. **Premier calendrier à brancher** (Google / Outlook / aucun) — tranché par les
   **interviews terrain** du cousin, question ajoutée à sa liste. L'OAuth Google n'est
   **volontairement pas lancé** : sa vérification exige nom d'app, domaine vérifié et
   politique de confidentialité hébergée, donc la même décision de nom que le Sender ID.
5. **Plateforme vocale** — décision structurante, à prendre en session dédiée. Les
   plateformes managées (Vapi, Retell) fournissent leurs numéros ou s'intègrent en trunk
   SIP ; prendre des numéros avant de choisir créerait une double tuyauterie.
6. **Fournisseur SMS** — choix réversible (tout passe par le port `Envoyeur`). Critère :
   qualité du processus de déclaration du Sender ID, DPA, hébergement UE. Candidats
   équivalents : OVHcloud (en place), LinkMobility, Octopush, SMSFactor, Brevo.
7. ~~Table `artisan`~~ et ~~écran de connexion provisoire~~ — **traités le 25/08**
   (migrations 008 et 009, R28). Le jeton porteur survit pour l'API et la future app
   mobile : c'est aussi le filet si le SMS ne part pas (crédits épuisés, fournisseur en
   panne) — sans lui, une panne SMS nous enfermerait dehors.
8. **`FOR UPDATE SKIP LOCKED`** quand plusieurs workers tourneront (optimisation, pas
   justesse).
9. Formulation « d'ici 24 heures » à l'oral, un peu mécanique — à retoucher sciemment.
10. **Document « décisions côté cousin »** (5 blocs : nom, structure juridique,
    positionnement expéditeur, questions terrain, bêta/prix/confidentialité) : produit et
    transmis, **pas encore versionné dans `docs/`**.

## Prochaine étape

**SPIKE VOIX en cours.** Arbitrage rendu le 25/08 sur `docs/etat-des-lieux-voix.md` :
plateforme **managée (Vapi)**, numéro **non français**, agent en **Haiku**, et — décision
d'invariant définitive pour cette phase — **pas de streaming des sorties gardées** : la
latence se traite par des phrases-tampons pré-approuvées, jamais en contournant
`guards.check_output`.

Prérequis Haiku **RENDU le 25/08 : 42/42**, à parité avec Sonnet, après correction de trois
défauts produit que Sonnet masquait. Latence du tour ramenée de 3,42 s à 1,93 s de médiane.
**Confirmé au 7ᵉ passage** (`evals/results-20260825-213151.json`) sur l'arbre corrigé, sans
un seul incident de harnais : le 41/42 du 6ᵉ passage venait bien du défaut que R39 corrige.

Les garde-fous de prononçabilité (R37) travaillent en continu — une quinzaine
d'interceptions sur ce passage, dont **le numéro d'urgence sécurité gaz mis en gras** sur
T04. Elles ne font pas échouer les scénarios (le repli sur l'instruction du contrôleur
fonctionne), mais elles disent que le formuleur produirait sans cesse de l'imprononçable si
on le laissait faire. C'est un argument de plus pour le verbatim là où le fond compte.

Le garde-fou emoji est fait (R37). La **sonde de l'étape 0 est écrite** (R40) : il ne reste
qu'à la jouer. Reste aussi la ligne `RELAIS_MODEL` du `.env` de Geoffrey.

**LA VOIX MARCHE DE BOUT EN BOUT.** Deux appels vocaux réels le 26/08, scénarios
complets : une sortie hors zone correcte, et **une réservation qui a produit un vrai RDV
en base**, `en_attente_validation` chez art-dupont. La boucle voix → validation artisan
est démontrable aujourd'hui.

Six défauts en sont sortis, tous corrigés (R42–R46) — voir l'entrée datée. Le plus grave,
R42, produisait un RDV d'apparence normale sur un numéro de téléphone faux.

**Reste ouvert côté voix** : personne ne raccroche (la phrase de fin est désormais
déterministe, il reste à brancher `endCallPhrases` côté Vapi), le barge-in à activer
(`stopSpeakingPlan`), et la latence à mesurer sur un appel complet.

Ce qui reste du branchement initial :

```bash
# 1. l'assistant Vapi, créé proprement par l'API : STT/TTS français, custom LLM
#    pointant sur <tunnel>/voix/vapi, et SURTOUT aucun `firstMessage` — l'annonce IA
#    doit sortir de NOTRE moteur (règle n°5), pas d'un champ de tableau de bord.
# 2. champ « API Key » de Vapi = RELAIS_WEBHOOK_SECRET (il part en Authorization: Bearer)
# 3. activer stopSpeakingPlan (barge-in) — cf. mesure d'oreille n°3
RELAIS_VOIX_ARTISAN=art-dupont uvicorn serveur:app --port 8000
```

Scénario cible du premier appel : « j'ai une fuite » → commune → première question de
qualification (S0→S2). C'est exactement ce que R41 joue en mock.

**Mode d'emploi de la sonde** (elle reste utile pour toute nouvelle plateforme) :

```bash
RELAIS_SONDE_VOIX=1 uvicorn serveur:app --port 8000   # le serveur l'annonce au démarrage
# un tunnel public (ngrok/cloudflared) vers le port 8000
# Vapi : custom LLM → URL = https://<tunnel>/voix/sonde
#        en-tête personnalisé X-Relais-Secret = RELAIS_WEBHOOK_SECRET
# puis on appelle le numéro et on lit proto/sonde-vapi.jsonl
```

On y cherche `identifiants_candidats` : si un champ stable y figure, l'adaptateur se réduit
à une traduction de formats vers `/webhooks/appel/{id}/tour`. Sinon il faut fabriquer la clé
(dérivée du couple appelant/appelé, ou table de correspondance) — un montage plus lourd, avec
ses propres modes de panne. **Ne pas écrire l'adaptateur avant d'avoir lu ce fichier.**

### ÉTAPE 0 TERMINÉE — récolte du 25/08 (`sonde-vapi.jsonl`, requête de 21:02)

| Fait | Conséquence pour l'adaptateur |
|---|---|
| **`call.id`** : UUID à la racine de l'objet `call`, stable sur tout l'appel | ✅ **La clé existe.** L'adaptateur est une traduction de formats vers `/webhooks/appel/{id}/tour`. Rien à fabriquer. |
| `"stream": true` — **une réponse d'un bloc reçoit 200 et n'est JAMAIS prononcée** | SSE obligatoire. Gardes sur le texte **entier**, puis un seul morceau + `[DONE]`. |
| `Authorization: Bearer` (confirmé en réel), aucun en-tête personnalisé | Mettre `RELAIS_WEBHOOK_SECRET` dans le champ « API Key » de Vapi. |
| Vapi appelle `POST <url>/chat/completions` | Déclarer le suffixe, pas l'URL nue. |
| **Tout l'historique est renvoyé à chaque tour**, message système compris (celui de l'assistant par défaut de Vapi) | **L'ignorer entièrement.** Notre état vit dans le dépôt, indexé par `call.id` ; le prompt vient de notre moteur. |
| `metadata.assistantTurnInterrupted` | Détection du barge-in disponible — matière pour les phrases-tampons. |
| `startSpeakingPlan.waitSeconds = 0.4` | Le budget de silence toléré avant que l'agent reprenne la parole. |

**Ce que le silence a coûté et rapporté.** Le 200 muet est le meilleur argument de toute la
session pour la sonde : côté serveur, tout était vert. Aucun test d'intégration, aucun
contrat, aucune relecture n'aurait signalé quoi que ce soit. Il fallait un vrai appel et
une vraie oreille.

Ce qu'il faut retenir pour l'arbitrage : la latence d'un tour du contrôleur est **mesurée**
à 3,4 s (Sonnet 5) / 1,9 s (Haiku) hors STT et TTS, contre un budget conversationnel de 0,5
à 1 s ; le premier spike proposé se fait sur un **numéro non français**, qui n'exige pas de
Kbis.

En parallèle, à préparer sans coder : la brique de **réception SMS** (révision OUI/NON), une
fois les trois questions OVH tranchées.

Candidats sans dépendance externe, par valeur décroissante :

1. **Couvrir `appel_muet` (S9)** — la dernière des six issues du moteur que personne
   n'emprunte. Le harnais lit une réplique vide comme une fin d'appel : un persona
   silencieux est aujourd'hui indistinguable d'un persona qui raccroche. Il faut que
   l'appelant simulé puisse rendre un silence EXPLICITE.
   Et continuer d'élargir : 42/42 ne veut pas dire que l'agent est bon, mais que ces
   quatorze-là ne trouvent plus rien. Cinq des six bugs du 25/08 sont venus de tournures
   auxquelles personne n'avait pensé. Restent à écrire : les accents régionaux, l'appelant
   qui coupe l'agent, celui qui répond à côté, le bruit de chantier.
2. **Un vrai parcours d'onboarding** pour remplacer `semer_artisans.py`.
3. **Un worker de rattrapage** pour les RDV décidés dont le SMS n'a pas été mis en file
   (l'écriture et la mise en file ne sont pas atomiques — point laissé ouvert le 25/08).

Le spike vocal ne s'ouvre **qu'en session dédiée**.

Le spike vocal ne s'ouvre **qu'en session dédiée**. Le Sender ID et l'OAuth Google attendent
le nom commercial — c'est-à-dire le cousin, pas nous.
---

## Session du 25/08/2026 (fin) — sonde de l'étape 0 : demander à la plateforme plutôt que parier

**Fait.** La sonde du chantier voix (`proto/relais_proto/sonde_voix.py`, route
`POST /voix/sonde` et `/voix/sonde/chat/completions`), couverte par **R40**, mutations
**13/13**. Suite à **44 PASS**. Écrite pendant qu'un septième passage de l'éval Haiku
tournait — les deux ne se touchent pas : l'éval instancie `Conversation` directement et ne
passe jamais par `api.py`.

**Pourquoi une sonde et pas l'adaptateur.** Une seule question commande la forme de
l'adaptateur : *la charge utile de Vapi porte-t-elle un identifiant d'appel ?* L'API est
bâtie sur un principe — *un tour = une requête, sans session en mémoire*, l'état relu du
dépôt à chaque tour — qui suppose une CLÉ stable. Si la plateforme en fournit une,
l'adaptateur est une traduction de formats. Sinon il faut fabriquer la clé, et c'est un
autre objet. Les deux sont trop différents pour être écrits sur une hypothèse, et la
documentation d'un tiers n'est pas une source suffisante pour engager une architecture.

**Ce que la sonde rapporte**, au-delà de la charge utile brute : les `identifiants_candidats`
(tout scalaire dont la clé ressemble à un identifiant, extrait par chemin, listes comprises)
— pour trancher d'un coup d'œil au lieu de relire des kilo-octets ; et `stream_demande`,
parce que la décision d'arbitrage n°4 dit qu'on ne diffusera pas une sortie gardée : savoir
si la plateforme le demande quand même, et si elle accepte une réponse d'un seul bloc, fait
partie de ce qu'on vient mesurer.

Elle répond une phrase FIXE, ce qui donne gratuitement un premier aller-retour audible de
bout en bout — réseau, transcription, notre serveur, synthèse vocale — donc une mesure de
latence **avant** tout adaptateur. La phrase porte l'annonce IA (règle n°5) : la sonde
décroche un vrai téléphone, et la mesure doit porter sur quelque chose de représentatif.

**Éteinte par défaut, et pas seulement « protégée ».** Sans `RELAIS_SONDE_VOIX`, la route
n'est pas déclarée du tout. Un 401 laisserait une surface ; un 404 dit qu'il n'y a rien à
atteindre. Le serveur l'annonce à chaque démarrage quand elle est allumée — même logique que
le réglage du cookie, mais dans l'autre sens : ici, c'est l'oubli d'ÉTEINDRE qu'on veut voir.

**Deux chemins pour une seule fonction**, `/voix/sonde` et `/voix/sonde/chat/completions` :
selon la façon dont l'URL est renseignée côté plateforme, celle-ci appelle la racine telle
quelle ou lui ajoute le suffixe de la convention OpenAI. Une sonde qui rendrait 404 parce
qu'on a mal deviné le suffixe ne mesurerait rien — et on ne l'apprendrait qu'après avoir
monté le tunnel et passé l'appel.

**Le journal n'écrit jamais une valeur d'en-tête, seulement leurs NOMS.** Le secret partagé
en est une. Les noms suffisent à diagnostiquer une plateforme mal configurée, et c'est
justement pour ça que l'échec d'authentification est journalisé lui aussi : sans cela, un
premier appel qui 401 n'apprendrait rien. Le fichier contient une conversation réelle — il
est dans `.gitignore`.

**Deux défauts de mes propres tests, trouvés par mutation.**

1. Ma vérification de fuite cherchait le mot « faux » — qui figure dans le message de refus
   écrit par la sonde elle-même. Le test échouait sur son propre texte. Sentinelles
   improbables depuis.
2. Plus grave : cette vérification ne lisait que le journal du **refus**. Or ce sont les
   requêtes **acceptées** qui portent le VRAI secret. Une mutation faisant écrire les
   en-têtes en clair sur le chemin nominal a survécu. Le contrôle porte désormais sur tout
   le journal, secret réel compris. Une n-ième illustration de la règle : un test qu'on n'a
   pas essayé de tuer ne prouve rien.

**Piège de l'outillage, à ne pas redécouvrir** : l'outil Bash mange les antislashs dans un
heredoc, même délimiteur entre quotes. Un `\\n` destiné à rester littéral est devenu un vrai
saut de ligne au milieu d'une f-string, et le fichier ne compilait plus. Écrire les scripts
de correctif avec l'outil d'écriture de fichier, jamais par heredoc.

**Décidé.** Rien de nouveau : la sonde applique l'arbitrage du 25/08, elle ne le modifie pas.
Elle n'est pas du produit et n'a pas vocation à le devenir.

**Prochaine étape.** Jouer l'étape 0 (mode d'emploi dans le bloc ÉTAT en tête), lire
`identifiants_candidats`, **puis** écrire l'adaptateur.

### Premier appel réel, le soir même : la sonde a rendu 401, et c'est sa réussite

Le 401 n'était pas une panne, c'était la mesure. Vapi **n'envoie aucun en-tête
personnalisé** vers un custom LLM : le contenu de son champ « API Key » part en
`Authorization: Bearer`. Le journal des NOMS d'en-têtes sur le chemin du refus — décidé
« au cas où » quelques heures plus tôt — est précisément ce qui l'a dit. Sans lui, un 401
muet n'aurait rien appris et il aurait fallu remonter le tunnel pour deviner.

Deux autres faits acquis au passage : la plomberie fonctionne de bout en bout, et Vapi
appelle bien `POST <url>/chat/completions`, pas l'URL nue — avoir déclaré les deux chemins
a évité un aller-retour.

**Correctif : la sonde accepte le secret webhook par l'une OU l'autre voie.** Le préfixe
`Bearer ` est retiré s'il est là et toléré absent, plusieurs plateformes envoyant la valeur
nue. La voie utilisée est **journalisée** (`voie_auth`) : si Vapi change de canal, on doit
le lire dans le fichier, pas le redécouvrir par un 401.

**Ce que l'élargissement ne fait PAS**, et qui est verrouillé par mutation : ouvrir la
porte de l'artisan. `Bearer` est le format de l'AUTRE porte (`artisan_authentifie`), et la
règle du projet est que les deux ne se substituent jamais l'une à l'autre. Un jeton
d'artisan présenté à la sonde est refusé — la mutation qui remplace la vérification du
secret par `registre.par_token` est tuée, avec le bon message. Sans ce contrôle, la sonde
serait exactement le trou par lequel les deux portes communiquent.

Et l'élargissement vaut pour la **sonde seule** : `webhook_authentifie`, la porte de
production, n'y touche pas. Une commodité de diagnostic n'a pas à devenir une règle
d'authentification.

R40 étendu, mutations **7/7** en plus des 13/13. Suite : 44 PASS.

### Deuxième appel réel : 200, et un silence

L'authentification passe, la sonde répond, Vapi renvoie 200 — et **rien n'est prononcé**.
C'est le meilleur argument de toute la session pour avoir fait une sonde plutôt qu'un
adaptateur : côté serveur, tout était vert. Aucun test d'intégration, aucun contrat, aucune
relecture n'aurait signalé quoi que ce soit. Il fallait un vrai appel et une vraie oreille.

Vapi envoie `"stream": true` et n'accepte pas une réponse d'un seul bloc.

**La décision d'arbitrage n°4 n'est pas entamée — elle est précisée.** « Pas de streaming »
voulait dire : aucune sortie prononcée avant d'avoir été vérifiée entière. Cela ne dit rien
du TRANSPORT. La sonde émet donc en SSE, mais le texte part **entier, en un seul morceau de
contenu** :

> le flux est un mode de transport, jamais un mode de génération.

La raison n'est pas esthétique. Tout ce qui sort passe par `guards.check_output` (règle
n°2), et des garde-fous ne peuvent rien contre un fragment de phrase : un prix hors liste
blanche, un « c'est confirmé » prématuré ou un diagnostic improvisé ne se reconnaissent que
sur la phrase complète. Émettre au fil des jetons, ce serait prononcer d'abord et vérifier
ensuite.

**Ce n'est pas confié au commentaire** : R40 compte les morceaux de contenu et exige qu'il
n'y en ait qu'un. La mutation qui diffuse au fil des mots est tuée avec le bon message
(« 23 morceaux de contenu au lieu d'un seul »). Le jour où quelqu'un voudra streamer les
jetons, le test l'arrêtera.

Coût assumé, écrit dans le code : le premier son sort quand la phrase entière est prête.
C'est ce que les **phrases-tampons pré-approuvées** doivent couvrir — pas le streaming.

**Récolte complète de l'étape 0** : tableau dans le bloc ÉTAT en tête. Le fait qui débloque
tout est `call.id`, un UUID stable à la racine de l'objet `call` : la clé existe, donc
l'adaptateur est une traduction de formats et non un montage à fabriquer une clé.

R40 étendu (test écrit et vu échouer avant), mutations **8/8** en plus des 13/13 et 7/7.
Suite : 44 PASS.

**Un défaut de mes propres données de test** : la charge utile de base portait déjà
`stream: true`, si bien que les six contrôles d'authentification recevaient du SSE et que
`r.json()` tombait. Deux charges distinctes depuis — celle en flux est explicite.

**Contre-épreuve faite le soir même : la sonde PARLE.** Appel complet de plusieurs tours,
phrase prononcée en français à chaque tour, transcript propre côté Vapi. Le silence
précédent est donc prouvé dans les deux sens — c'était bien le transport, rien d'autre.

Trois mesures d'oreille, consignées comme données d'arbitrage :

1. **Latence** : le délai de la sonde (plancher réseau + STT + TTS + tunnel, zéro calcul)
   est confortable. C'est le **plancher, pas le verdict** — le vrai test est plancher +
   contrôleur (~1,9 s en Haiku). Les phrases-tampons restent au programme.
2. **Fin de tour** : léger blanc si l'appelant marque une pause en milieu de phrase —
   c'est `startSpeakingPlan.waitSeconds = 0.4`, vu dans la charge utile. Défaut
   raisonnable pour notre public (appelant stressé, parfois âgé) : **ne pas le réduire**,
   curseur à régler sur du réel.
3. **Barge-in** : impossible de couper l'agent en l'état. Pas bloquant sur des répliques
   courtes, mais **à activer** (`stopSpeakingPlan`) : les tours verbatim longs
   (récapitulatif de RDV, consignes de sécurité) sont exactement ceux qu'un appelant
   pressé voudra couper. Décision réversible, à trancher à l'oreille.

---

## Session du 26/08/2026 (fin) — R62 : le prix cumulé des verbatim, et la réponse

Geoffrey, après l'appel où l'agent a répété trois fois la même phrase à quelqu'un qui
coopérait : *« ça m'a l'air d'être un problème basique qu'elle aurait pu comprendre au lieu
de tourner en rond comme un robot préenregistré… et non une IA. On vend de l'IA avec notre
produit quand même. Est-ce que ça vaudrait le coup de repasser sur Sonnet ? »*

### Non — et c'est mesurable

Ces phrases sont **verbatim** (R57, pour empêcher le formuleur de faire confirmer des
chiffres refusés). Mesuré avec un espion sur `reply` : **zéro appel au formuleur** pendant
ces trois tours. Aucun modèle n'est consulté ; Sonnet produirait les mêmes octets.

Et sur le fond, la comparaison a déjà été faite le 25/08 : Sonnet 42/42, Haiku 42/42 — à
parité sur les verdicts — pour une latence de tour de **3,42 s contre 1,93 s**. Au téléphone,
c'est décisif dans l'autre sens.

⚠️ Une comparaison des seules INTERCEPTIONS de garde-fous entre les deux modèles n'est pas
disponible : les passages Sonnet du 25/08 précèdent R37, R46, R51, R52 et R53. Pour trancher
il faudrait rejouer les 19 personas en Sonnet sur l'arbre courant. C'est faisable et cher ;
la question est posée au journal, pas tranchée.

### La vraie cause est de mon fait

Chaque `verbatim=True` a été ajouté après un défaut réel : R38 (le formuleur niait les
créneaux), R44 (clôture bégayée), R45 (commune écorchée), R56 (quiz sur le Vaucluse), R57
(relecture de chiffres refusés). Chacun justifié localement. **L'effet d'ensemble est que
l'agent sonne préenregistré** — et c'est exactement ce que Geoffrey a entendu.

La réponse n'est pas de rendre la main au formuleur, qui inventerait à nouveau des chiffres.
C'est de donner au **contrôleur plusieurs phrases au lieu d'une** : les « phrases-tampons
pré-approuvées » de l'arbitrage voix du 25/08, restées au journal jusqu'ici. R62 en écrit les
premières — la seconde relance reconnaît qu'on a déjà demandé et **change de stratégie** :
« Excusez-moi, je n'y arrive pas. Dites-moi les dix chiffres d'un seul coup, sans pause. »

### La piste à évaluer ensuite

Au lieu de figer des PHRASES, interdire les FAITS dans un tour formulé : un garde-fou qui
refuse chiffres, dates, prix et noms de lieux hors verbatim. Le formuleur retrouverait sa
liberté de formulation sans pouvoir inventer une donnée. Consigné en dette n°0.

### Un second défaut trouvé en écrivant le test

« 0 6. 30 » compte trois chiffres, et la branche « numéro inexploitable » n'en tenait compte
qu'à partir de CINQ. Un appelant qui dicte **par morceaux** tombait donc dans la branche de
celui qui n'a rien donné, bornée à deux tentatives. On le renvoyait au repli en croyant qu'il
se dérobait, alors qu'il était en train de répondre. Seuil abaissé à deux chiffres — et une
mutation a exigé qu'un chiffre ISOLÉ (« j'ai pas 2 minutes ») n'en soit pas une.

Suite : **66 PASS**. Mutations 5/5.

---

## Session du 26/08/2026 (fin) — R61 : « demain » n'était pas un jour

Appel réel où le RDV est bien pris, mais où l'appelant a dû se répéter. Sa première phrase :

    « j'ai une fuite dans la salle de bain, qui habite à Nogent-sur-Marne, voudrais un
      rendez-vous n'importe quand dans la journée de DEMAIN si possible »

Et l'agent propose « aujourd'hui entre 17 h et 19 h, ou demain entre 08 h et 10 h ». Il a
fallu qu'il réponde **« J'ai dit demain. »** pour obtenir ce qu'il avait demandé d'emblée.

`_contraintes_dispo` ne reconnaissait que les NOMS de jours (« samedi ») et les moments
(« matin »). « demain » n'est pas dans la table des jours de la semaine — la contrainte
n'existait donc pas. C'est pourtant la façon **la plus courante** de dire un jour au
téléphone, bien avant « mardi ».

Même famille que R36 (contrainte annoncée tardivement) et R39 (« rien de plus tôt » contre
une contrainte nouvelle) : le créneau proposé doit respecter ce que l'appelant a dit, quand
il l'a dit. Ici, la contrainte était là depuis le premier mot.

### La mutation qui a trouvé le vrai piège

« après-demain » contient « demain » : sans un ordre explicite du plus long au plus court,
un appelant qui dit après-demain obtient demain. Tué du premier coup.

Mais une mutation a survécu : *calculer le jour sur l'instant UTC au lieu de l'heure de
pendule*. À 9 h du matin, UTC et Paris tombent le même jour — le défaut est invisible. Il
a fallu **l'appel de nuit** : à 22 h 30 UTC un lundi, il est 00 h 30 le MARDI à Paris, donc
« demain » vaut mercredi. Calculé en UTC, on répondrait mardi — soit la nuit même.

Un appelant qui a une fuite à minuit et demi et qui dit « demain » n'entend pas « dans une
heure ». C'est la règle n°7 qui se gagne ou se perd là, et R25 avait déjà payé pour
l'apprendre.

### Ce que cet appel montre AUSSI, et qui n'est pas de notre ressort

Le début de chaque réplique de l'agent est **coupé à l'audio** : « Se passe-t-il » pour
« Que se passe-t-il », « je n'ai● », « Je pas bien noté », « Peux vous proposer »,
« Recevrez un SMS », « Quoi que ce soit coince ». Notre texte est complet et verbatim — la
troncature est en aval. À rapprocher de `startSpeakingPlan` et du chevauchement déjà
constaté.

Et une observation d'ergonomie à trancher plus tard : l'appelant a dicté son numéro en
morceaux (« 0 6. 30 », « 30 », « 4 0 4 5 »), et chaque fragment a reçu **la même phrase de
refus**, mot pour mot, trois fois. R55 a raison de refuser ; répéter la même phrase à
quelqu'un qui coopère n'aide pas. Une relance qui varie — « donnez-moi les dix chiffres d'un
seul coup » — reste à écrire.

Suite : **65 PASS**. Mutations 6/6.

---

## Session du 26/08/2026 (fin) — R60 : on jetait des tours que la plateforme nous donnait

Trouvé en répondant à une question de Geoffrey : *« à quel point le mock joue sur le
comportement de Haiku ? Normalement l'IA aurait dû pouvoir couvrir les infos de la
conversation, non ? »*

La réponse directe est non, et par construction : **l'extracteur ne voit jamais
l'historique.** Il reçoit la phrase courante et un contexte minuscule ; c'est le contrôleur
qui tient l'état (règle n°1). Ce n'est pas un chat. Et dans le cas de R59, le tour n'est même
jamais arrivé jusqu'au modèle — `est_un_rejeu` s'exécute dans `api.py`, avant `process()`.

Mais la question portait juste par un autre chemin, et elle a trouvé un second trou.

### La plateforme nous donne tout, et nous ne lisions que le dernier message

Mesuré : si une requête est perdue (réseau, 500, expiration) et que la suivante arrive avec
deux tours d'avance, l'adaptateur ne traitait que le dernier.

    Vapi envoie : [« J'ai une fuite, j'habite Nogent-sur-Marne 94130 »,
                   « Dupont, 06 12 34 56 78 »]
    traité       : [« Dupont, 06 12 34 56 78 »]
    slots        : {telephone_rappel} — commune, code postal et problème PERDUS

L'information était dans la charge utile. On la jetait. Et le client n'a aucune raison de
redire ce qu'il a déjà dit : c'est le « Déjà dit. » de R59, vu par un autre chemin.

`textes[traites:]` rattrape le retard, dans l'ordre. Avec une **borne** à trois tours : un
retard de un ou deux vient d'une requête perdue, ce qui arrive ; un retard de dix voudrait
dire que plusieurs requêtes consécutives ont échoué, et rejouer dix tours dans une seule
requête HTTP ferait expirer l'appel — le client entendrait le silence, ce qui est pire que
de perdre un tour.

### Ce que le mock change vraiment, puisque la question était là

Il ne tourne **jamais** au téléphone — sauf comme filet : `ResilientLLM` y retombe si l'API
échoue, pour ne jamais rester muet. Là où il compte, c'est sur ce que nos tests peuvent
VOIR. Quand il est *meilleur* que Haiku sur un point, un test passe et la production casse :
c'est exactement T14, dont la regex refusait douze chiffres là où Haiku les tronquait (R55).
R26, R42, R47, R55 viennent tous de cet écart — et c'est ce qui justifie le coût de l'éval
réelle.

### Trois bancs de mutation à recalibrer, et une mutation resurvécue

Le rattrapage a déplacé le traitement du tour courant : l'ancre de R41 (« c'est le PREMIER
tour qui est traité ») visait un index qui n'existe plus, et la mutation « la transcription
qui se précise n'est traitée par personne » appartient désormais au banc de R59, seul à
exercer ce cas. **Un correctif qui touche un chemin partagé périme les mutations de tous les
tests qui passent par là** — c'est la troisième fois aujourd'hui, et ça vaut d'être su :
après un changement d'architecture, rejouer les bancs voisins, pas seulement le nouveau.

Suite : **64 PASS**. Mutations 5/5 (R60), 6/6 (R59), 14/14 (R41), contrat Postgres rejoué.

---

## Session du 26/08/2026 (fin) — R59 : le garde de rejeu a jeté la commune d'un client

L'appel le plus coûteux de la série. L'appelant donne sa commune dans sa PREMIÈRE phrase —
Nogent-sur-Marne, **en zone** — et s'entend redemander trois fois où il habite :

    User  : Je suis dans la salle de bain. J'habite sur Nogent-sur-Marne.
    …
    Agent : Êtes sur quelle commune
    User  : Déjà dit.
    Agent : J'ai besoin de votre commune ou code postal…
    User  : Bonjour sur le membre.                      (STT : Nogent-sur-Marne)
    Agent : Je n'arrive pas à situer votre commune…
    User  : Vis à nos gens sur moi.                     (STT : Nogent-sur-Marne)
    Agent : Je transmets tout ça à Julien…

« Déjà dit. » Il avait raison. **Un client en zone, avec une fuite, perdu** — la catégorie
d'échec la plus chère du produit, et la première fois qu'on la voit.

### La résolution n'a pas fauté

Rejouée sur l'arbre courant, cette phrase donne `Nogent-sur-marne / 94130` du premier coup :
avec un extracteur vide, avec une commune sans code postal, avec une paire incohérente. Les
trois variantes plausibles du modèle réel aboutissent. **Le texte que le moteur a reçu
n'était donc pas celui que la plateforme affiche.**

### Le coupable est un garde que j'ai écrit à l'étape 0

`est_un_rejeu` comparait le NOMBRE de messages `user` à ce que notre transcript contient
déjà. Quand l'appelant parle par-dessus l'accueil — ce qui est arrivé aux deux derniers
appels, faute de `stopSpeakingPlan` — la transcription de son tour arrive en **deux temps** :
d'abord tronquée, puis complète. Les deux requêtes portent le même nombre de messages. Le
garde prend la seconde pour une retransmission et la jette.

Ce qui a été jeté ici, c'est « J'habite sur Nogent-sur-Marne ».

Le barge-in de l'étape 0 (quatre requêtes en sept secondes) était bien un rejeu : texte
**identique**. Une transcription qui se précise, elle, **s'allonge**. C'est ce qui les
distingue, et le garde ne regardait pas.

⚠️ Sans la charge utile de cet appel, je ne peux pas PROUVER que c'est la cause. Ce que le
test prouve, c'est que le garde perdait bel et bien un tour dans ce cas-là.

### Ce que cet épisode dit de l'étape 0

`est_un_rejeu` est né d'une mesure réelle — quatre requêtes identiques pendant un barge-in —
et il était juste pour ce cas-là. Il a échoué sur le cas voisin, que la mesure n'avait pas
montré. **Un correctif taillé sur une seule observation couvre une seule observation.** La
sonde a bien fait son travail ; c'est mon inférence qui a généralisé trop vite.

### Effet en cascade sur les bancs de mutation

Changer la signature a fait tomber trois ancres de R41, et une mutation y a **resurvécu** :
« traiter le PREMIER tour au lieu du dernier ». R41 vérifiait qu'un tour avait avancé, pas
LEQUEL — et depuis R59, traiter un ancien message fait aussi avancer le compteur. R41 exige
désormais que le dernier tour traité soit bien le dernier envoyé. 14/14 rétabli.

Suite : **63 PASS**. Mutations 5/5 (R59), 14/14 (R41), contrat Postgres rejoué.

---

## Session du 26/08/2026 (fin) — R58 : un code postal français est DEUX nombres

Premier appel où **l'agent parle en premier** (réglage Vapi corrigé côté Geoffrey). Le
déroulé est propre de bout en bout : ouverture avec l'annonce IA, consigne de sécurité,
question du secteur, `91 260` lu du premier coup, **relecture avant refus** (R54 en
production), refus verbatim sans commune inventée. Aucun garde-fou déclenché.

Une observation, et elle est plus grosse qu'elle n'en a l'air. Nous émettions
« J'ai noté le 91 260 » — avec une espace — et la synthèse a prononcé
**« quatre-vingt-onze MILLE deux cent soixante »**. Elle joint les deux groupes en un seul
nombre ; une espace ne lui suffit pas.

Geoffrey l'a formulé en l'écrivant, et c'est la clé de tout ce qu'on a corrigé aujourd'hui :
**on dit le numéro du département, puis le reste.** « Quatre-vingt-onze, deux cent
soixante. » Jamais en un seul nombre.

D'où la symétrie qu'on n'avait pas vue. R43 (« 91 260 »), R47
(« quatre-vingt-onze, deux cent soixante »), R49 (« 91/260 ») : trois correctifs, trois
symptômes du même fait. **Un code postal français est deux nombres, pas un.** Le STT le rend
en deux morceaux parce qu'il est prononcé en deux morceaux — et nous, on l'écrivait en un
seul, donc la synthèse le lisait en un seul. Les deux bouts de la chaîne butaient sur la
même chose, vue d'abord à l'entrée puis à la sortie.

Virgule entre les groupes désormais, et le tiret avant la question de confirmation (un point
après des chiffres est lu comme une fin d'énoncé, R46).

⚠️ Ce que le test ne prouve pas : que la synthèse prononce bien deux groupes. Il vérifie ce
qu'on ÉMET, seule chose qui nous appartienne. Le reste demande une oreille.

**Reste à régler côté plateforme** : l'appelant a parlé par-dessus l'ouverture (« Vit dans la
salle de bain. J'ai une fuite. » — deux tours mêlés), faute de `stopSpeakingPlan`.

---

## Session du 26/08/2026 (fin) — 57/57, et ce que les appels réels ont coûté

Troisième passage : **57/57**, zéro incident de harnais. Trajectoire de la journée sur les
dix-neuf personas : **50/57 → 55/57 → 57/57**, chaque palier après un lot de correctifs
tirés des échecs du précédent.

### Le bilan de la journée

Onze défauts, tous trouvés par un appel vocal réel ou par un persona qui en reprenait la
dictée : R42 (numéro tronqué), R43 (code postal dicté), R44 (clôture verbatim), R45
(commune canonique), R46 (re-salutation), R47 (nombres prononcés), R48 (commune bornée),
R49 (barre oblique, commune vérifiée), R50 (code postal validé), R51 (vouvoiement), R52
(salutation nulle part), R53 (une seule question), R54 (relecture avant refus), R55 (numéro
confronté au dit), R56 (question verbatim), R57 (paire cohérente).

**Aucun n'avait été vu par les quatorze personas écrits en imaginant des appelants.** C'est
la leçon la plus solide de la journée : un persona tiré d'un appel réel trouve ce qu'aucune
imagination ne produit — y compris avant d'être joué, T15 ayant révélé le bug de la virgule
en mock.

### Les garde-fous travaillent en continu

Sur ce dernier passage, **23 interceptions** sur 57 conversations : 7 re-salutations,
6 caractères imprononçables, 4 mises en forme markdown, 3 tutoiements, 3 questions
multiples. Aucune n'a fait échouer un scénario — le repli sur l'instruction du contrôleur
fonctionne — mais elles disent que le formuleur produirait sans cesse de l'inacceptable si
on le laissait faire. Les cinq garde-fous nés aujourd'hui tirent tous les trois passages.

### Ce qui reste au formuleur

L'accueil, la qualification, la réponse tarifaire, les tours d'empathie. **Tout ce qui
énonce un fait, un lieu, un chiffre ou un engagement est verbatim.** Ce n'est pas une
décision prise d'un coup, c'est le résidu de six correctifs successifs, chacun ajouté après
qu'une phrase précise a été mutilée au téléphone.

### Prochaine étape

Un appel vocal réel sur l'arbre corrigé, avec `endCallPhrases` branché sur la phrase de fin
et `stopSpeakingPlan` actif. Les six appels de la journée ont tous été passés avant au moins
une partie des correctifs : on n'a encore jamais entendu ce produit dans son état actuel.

---

## Session du 26/08/2026 (suite) — R57 : la paire commune/CP n'était pas recoupée

Deuxième passage réel : **55/57** (contre 50 avant R55/R56). Deux échecs restants, un sur
trois chacun, et trois causes — toutes de la même famille : *un fait est accepté sans être
recoupé, ou une phrase de fait est laissée au formuleur.*

### La paire commune / code postal n'était pas vérifiée

    client : C'est Zivier-sur-Orge, avec le code postal, c'est le 91260.
    agent  : Juste pour être sûr — vous êtes bien à Deuil La Barre ?

Le lead portait `commune: Orsay, code_postal: 91260`. **Orsay est 91400.** Deuil-la-Barre
est 95170 — un autre département, et c'est celle qui a été PRONONCÉE.

Chaque valeur était individuellement valide. R35 exige que commune et CP s'écrivent en
PAIRE ; R49 exige que la commune soit connue de nos tables. **Personne ne vérifiait que la
paire est cohérente.** Trois règles empilées sur la même donnée, et le trou était entre
elles.

Le code postal décide de la zone : c'est donc lui qui fait foi. Une commune qui ne lui
correspond pas est écartée, et on dit « votre secteur » ou on relit les chiffres — toujours
préférable à nommer une ville au hasard.

### Deux phrases de fait encore laissées au formuleur

**La demande de re-dictée du numéro.** T14 : le contrôleur a refusé douze chiffres (R55
fonctionne) et demandé de redonner le numéro chiffre par chiffre. Le formuleur en a fait une
RELECTURE des douze chiffres refusés — « 0-6-1-0-1-5-4-7-6-8-7-9. C'est bien ça ? ».
L'appelant a dit oui, le contrôleur n'a rien enregistré, l'appel a fini sans RDV. **Le
formuleur a fait confirmer un numéro que le contrôleur venait de rejeter.**

**La phrase de refus hors zone.** Elle passait par le formuleur, qui y a glissé « Vous me
dites Yvelines, 91260, Zivier-sur-Orge » : un département faux et une commune inexistante,
dans la phrase la plus définitive de l'appel.

### Ce que le formuleur a encore le droit de dire

À force de retirer, la liste tient en une ligne : **l'accueil, la qualification, la réponse
tarifaire, les tours d'empathie.** Tout ce qui énonce un fait, un lieu, un chiffre ou un
engagement est verbatim. Ce n'est pas une décision prise d'un coup — c'est le résultat de
R38, R44, R45, R56 et R57, chacune ajoutée après qu'une phrase précise a été mutilée en
production.

### Une mutation équivalente qui n'est PAS du code mort

`if canonique is None or not cp: return None` : sans le `not cp`, la boucle rendrait None de
toute façon (`None in cps` est faux). La mutation survit donc, et c'est normal — c'est un
raccourci qui évite de balayer mille cinq cents entrées à chaque tour, pas un garde qui
prétendrait protéger quelque chose. Gardé et documenté comme tel, à distinguer des cinq
retraits de code mort précédents.

Suite : **61 PASS**. Mutations 5/5, éval mock 19/19.

---

## Session du 26/08/2026 (suite) — première éval réelle des nouveaux personas : 50/57

Les cinq personas tirés des appels vocaux ont trouvé, au premier passage, **trois défauts
que quatorze personas imaginés n'avaient jamais vus** — et les sept échecs sont tous chez
eux. C'est exactement ce qu'on leur demandait.

### R55 — un numéro bien FORMÉ mais tronqué (T14, 3 échecs sur 3)

    client : c'est le 06 10 15 47 68 79.
    agent  : Je répète votre numéro : 06 10 15 47 68, c'est bien ça ?
    client : Oui c'est bien ça.

Le défaut de l'appel vocal du matin, reproduit à l'identique — **alors que R42 était censé
le couvrir.** R42 vérifie la FORME : dix chiffres, commençant par 0, sans lettres. Le
modèle a rendu « 0610154768 » : une forme irréprochable, deux chiffres perdus. Le
contrôleur n'avait aucun moyen de le savoir.

C'est la limite de tout contrôle de forme : il ne dit rien de la **correspondance** entre ce
qui est extrait et ce qui a été dit. `_numero_suspect` confronte donc les deux — la
signature d'une troncature est nette, le numéro extrait est un *préfixe strict* d'une suite
de chiffres de la phrase. Un numéro donné normalement est ÉGAL à sa suite, pas un morceau
de suite.

Leçon plus large : **R42, R50, R55 sont trois couches sur le même problème** — le
contrôleur ne peut pas faire confiance à l'extracteur, et chaque couche a été ajoutée après
qu'un cas réel a franchi la précédente. La forme, la plausibilité, puis la correspondance.

### T15 — mon persona était fautif, pas le produit

L'appelant simulé disait « j'habite à Créteil, le code postal c'est quatre-vingt-quatorze,
cent trente ». Créteil est **limitrophe** (94000) : le modèle a tranché en faveur de la
commune, ce qui est défendable sur une entrée contradictoire. Le produit a eu raison ; c'est
mon rôle qui n'épinglait pas la commune, et l'appelant simulé en a inventé une dont le vrai
code postal contredisait celui qu'il prononçait.

Deuxième fois qu'un de mes personas dérive ainsi (après T07). La règle, écrite dans le
persona : **un persona doit épingler tout fait que le verdict affirme.** Si le verdict exige
`cp=94130`, le rôle doit faire de 94130 la seule réponse cohérente.

### R56 — le formuleur a transformé la question en quiz (T17, 2 échecs sur 3)

    client : J'habite je visite sur Orange.
    agent  : Ah d'accord ! Vous êtes sur Orange. C'est dans le Vaucluse, c'est bien ça ?
    client : Ben non non, attendez, c'est Zivier-sur-Orge…
    agent  : Je transmets tout ça à Julien — il vous rappelle sous 2 heures.

Deux défauts en quatre lignes.

**Le formuleur a remplacé « Vous êtes sur quelle commune ? » par une question de
géographie**, en nommant au passage un lieu que nos tables ne connaissent pas — ce que R49
interdit au contrôleur et n'interdisait pas au formuleur. Troisième mutilation de cette
question précise (« Pouvez-vous ? Oui, Bonjour… », les re-salutations, le Vaucluse). Elle
est désormais **verbatim** : une question factuelle de six mots n'a rien à gagner à être
reformulée.

**Et la borne de R48 a lâché pendant que l'appelant insistait.** Deux tentatives, puis
repli. R48 avait raison de borner, mais répéter deux fois la même question et abandonner
n'est pas une conversation. La seconde relance demande maintenant **les cinq chiffres du
code postal** — la leçon de R43, restée jusqu'ici au journal : le code postal a sauvé un
appel réel que le nom de commune avait perdu deux fois. Cinq chiffres résistent mieux à la
transcription qu'un nom propre. Et c'est ce qui justifie une troisième chance : poser une
question DIFFÉRENTE, pas la même.

### Effet de bord révélateur

Rendre cette question verbatim a fait tomber R51, R52 et R53 : leurs doubles de formuleur
étaient branchés sur ce tour, qui ne l'appelle plus. Il a fallu les déplacer sur la demande
de précision de S1. C'est une mesure de ce qui reste au formuleur : l'accueil, la
qualification, la réponse tarifaire et les tours d'empathie. Tout ce qui énonce un fait ou
un engagement est verbatim.

### Encore du code mort, cinquième fois

J'avais ajouté la confrontation au texte dit **aussi** dans la branche de correction de
`_s4`. Une mutation l'a montrée sans effet : `_chiffres_dits` retire déjà tout numéro
suspect avant qu'on y arrive, et les deux contrôles portent sur le même texte. Retiré.

Et une mutation a été supprimée plutôt que forcée (la virgule dans les séparateurs de
suite) : entre l'inclure et l'exclure, aucun énoncé réaliste ne change de verdict.

Suite : **60 PASS**. Mutations 7/7 (R55/R56), R42 rejouée 10/10, éval mock 19/19.

---

## Session du 26/08/2026 (suite) — R54 : rendre la correction possible avant le refus

Question de Geoffrey avant de lancer l'éval : quand quelqu'un essaie de se corriger et que
l'agent est déjà passé à l'étape suivante, est-ce vu et corrigé, ou laissé tel quel par
choix ? **Ni l'un ni l'autre — ça n'avait jamais été examiné.**

Deux gels coexistaient, et un seul était voulu. Le gel **après réservation** (`hold`) est un
choix écrit et commenté : créneau bloqué, plus rien ne bouge. Le gel **après clôture**,
lui, était un effet de bord — et R44 l'a *durci* la veille en rendant la phrase de fin
verbatim pour accrocher `endCallPhrases`. La boucle a été renforcée sans qu'on se demande
si elle devait exister.

Deux appels sur six ont buté dessus. Et pire que l'ignorer : `process` rendait la phrase de
clôture **avant même d'enregistrer** ce que l'appelant avait dit. La correction ne figurait
donc dans AUCUN transcript — Julien ne pouvait pas voir que son client avait insisté. Le
seul défaut de la journée silencieux des deux côtés : ni entendu, ni tracé.

### Ce qui change

1. **Le secteur est relu avant tout refus.** « J'ai noté le 91 260, c'est bien ça ? », ou
   le nom de la commune quand notre table la connaît (R49). Une fois, et une seule. Cela
   place la correction là où la machinerie fonctionne déjà, au lieu d'espérer la rattraper
   après coup.
2. **Ce qui est dit après la clôture est conservé** dans le transcript. On ne relance pas
   la conversation pour autant — dans le chemin API le lead est déjà persisté et
   `cloturer_appel` refuse un second passage — mais la trace permet un rappel humain.

Coût assumé : un tour de plus sur chaque appel hors zone. Bénéfice : l'appelant mal
transcrit a un moyen de revenir, et il n'en avait aucun.

### Une décision renversée, et il faut le dire

R30 contenait le point inverse, explicitement : *« une commune donnée EN RÉPONSE à la
question ne se fait pas reconfirmer »*, au motif qu'une donnée demandée est fiable et
qu'une question de plus est une question de trop. C'était défendable à l'écrit. Six appels
vocaux l'ont invalidé : « Zivier-sur-Orge » pour Juvisy, « 160 » pour un code postal,
« 91/260 » illisible trois fois. **Demander ne fiabilise rien quand la transcription se
trompe.** Le test porte désormais la trace du renversement plutôt que d'être réécrit en
silence.

### Sept tests sont tombés, et ils avaient raison

Premier jet : la relecture VIDAIT les slots, comme le faisait le chemin de la commune
glanée. Sept tests l'ont relevé d'un coup en attendant d'y trouver le code postal. Ils
avaient raison — un état où l'on a posé une question SUR un code postal sans plus l'avoir
en mémoire est incohérent, et si l'appelant raccroche pendant la relecture, le lead ne dit
plus rien. Le secteur reste donc dans les slots ; ce que le vidage garantissait est assuré
autrement (signal de correction dans `_resoudre_commune`, `code_postal` réécrivable tant
qu'aucun créneau n'est bloqué).

### Encore du code mort, quatrième fois

`self.flags["zone"] = None` pendant la relecture : hérité du temps où les slots étaient
vidés, et sans **aucun** effet observable une fois le vidage retiré — une correction vers
un autre secteur hors zone est refusée une seule fois de toute façon, soit par la
revalidation de `process`, soit par le bloc de `_s2`, jamais deux. Une mutation l'a montré.
Retiré.

Et un trou dans ma propre assertion : je vérifiais que la correction remplissait le slot et
que l'appel n'était pas clos, sans vérifier qu'il **avançait**. Une mutation survivait en
laissant l'agent redemander sa commune à quelqu'un qui venait de la donner.

Mutations 8/8. Suite : **58 PASS**. Éval mock 19/19, contrat Postgres rejoué.

---

## Session du 26/08/2026 (suite) — cinq personas tirés des appels réels

Les six appels vocaux du 26/08 ont produit dix défauts. Aucun n'était couvert par les
quatorze personas existants — ils avaient été écrits en imaginant des appelants, pas en
en écoutant. Cinq personas nouveaux reprennent les dictées **telles qu'elles ont été
prononcées ou transcrites** :

| Persona | Dictée réelle | Défaut qu'il verrouille |
|---|---|---|
| `T14_numero_douze_chiffres` | « 06 10 15 47 68 79 » | R42 — troncature silencieuse |
| `T15_code_postal_en_lettres` | « quatre-vingt-quatorze, cent trente » | R47 — nombres prononcés |
| `T16_appelant_se_reprend` | « le quatre-vingt Non, c'est 160 » | R50 — CP invalide qui raccroche |
| `T17_commune_deformee` | « je visite sur Orange », « Zivier-sur-Orge » | R49 — commune non vérifiée |
| `T18_premier_tour_incomprehensible` | « Et tu cliques dans la salle de bain » | R52/R53 — réplique brouillonne |

**Le verdict de l'éval sait désormais vérifier le NUMÉRO** (`tel`). Il ne le faisait pas :
c'est pourtant le seul champ dont une valeur fausse produit un RDV d'apparence
parfaitement normale — lead complet, score correct, et personne ne peut rappeler le
client. Aucune autre clé du verdict ne l'aurait vu, et c'est précisément le défaut R42.

**T14 est construit pour être discriminant** : le numéro correct donné après relance
(`06 44 55 66 77`) n'est PAS un préfixe de la dictée fautive. Une troncature silencieuse
rendrait `0610154768` — un numéro qui ressemble à s'y méprendre à un numéro valide, et que
le test aurait accepté si j'avais gardé le même numéro dans les deux tours.

### Un persona a trouvé un défaut avant même d'être joué en réel

`T15` échouait en mock. « quatre-vingt-quatorze, cent trente » — la façon NORMALE de dicter
94130 — donnait 9400 : la virgule est invisible pour l'analyseur, et « cent » multipliait le
nombre en cours. Le français « quatre-vingt-quatorze cents » existe, mais ce n'est pas ce
que dit quelqu'un qui donne son code postal.

**La ponctuation ferme désormais un nombre ; le trait d'union, non.** Le trait d'union est
interne aux nombres français (« quatre-vingt-onze ») et le premier appel réel l'avait sur
toute la dictée : « Quatre-vingt-onze-deux-cent-soixante ». S'il coupait, ce cas-là
casserait.

Un persona qui reprend une vraie dictée trouve des défauts tout seul — c'est l'argument
pour les écrire à partir d'appels plutôt que d'imagination.

### Non joué

Le passage réel n'est **pas** lancé : 19 personas × 3 coûtent une clé et du temps, et c'est
une décision qui appartient à Geoffrey. La plomberie est vérifiée (19/19 en mock).

---

## Session du 26/08/2026 (suite) — R52/R53 : quand un garde-fou trouve d'abord notre faute

Sixième appel réel. Une seule réplique, deux défauts :

    Agent: « Pouvez-vous ? Oui, Bonjour, vous avez une fuite dans la salle de bain ?
             D'accord, dites-moi, vous êtes sur quelle commune ? »

### R52 — la salutation n'était interdite qu'en TÊTE de réplique

R46 signalait la re-salutation, mais ancrée au début. Ici le « Bonjour » est au milieu,
précédé d'un fragment, et il passe.

**C'était mon jugement, et la production le contredit.** J'avais ancré le motif pour
protéger une phrase comme « dites-lui bonjour de ma part », et j'avais même écrit un test
qui l'exigeait. Cette phrase n'existe pas dans ce produit ; le « Bonjour » perdu au milieu
d'une réplique, lui, s'est produit. *Un garde-fou calibré sur un cas imaginé plutôt que sur
un cas observé protège le mauvais côté.* L'exception a été retirée, et le test qui la
défendait porte désormais la note de sa suppression.

### R53 — une réplique ne pose qu'une question

Trois points d'interrogation. Au téléphone, c'est pire qu'inélégant : l'appelant répond à
celle qu'il a retenue, et le contrôleur reçoit une réponse à une question qu'il n'a pas
posée. Le slot attendu n'arrive pas, la question est reposée, et l'appelant a l'impression
de se répéter. **C'est le mécanisme exact des boucles qu'on passe notre temps à borner** —
R48 et R32 en traitaient les symptômes.

### Et le garde-fou a trouvé notre faute avant celle du formuleur

Premier effet de la règle : **deux tests existants sont tombés** (R38, R45). Cause :
l'instruction de S1 posait elle-même deux questions —

    « Pouvez-vous me préciser ce qui vous arrive ? Une fuite, un souci de chauffage,
      autre chose ? »

Les exemples sont une liste, pas une seconde question : un tiret les rattache désormais à
la première.

Ce que cet incident révèle est plus important que la coquille. **Quand une instruction du
contrôleur viole un garde-fou, `_say` replie sur `safe_fallback`** — une phrase générique
(« je préfère laisser Julien vous répondre »). L'agent devient donc MUET sur cet état-là,
sans erreur, sans trace ailleurs que dans le lead. R53 inscrit donc un contrôle
**exhaustif par lecture de l'arbre syntaxique** de toutes les instructions `_say` : pas un
balayage de scénarios, qui en manquerait toujours un.

Ma vérification préalable, elle, était un `grep` sur des littéraux d'une seule ligne — et
l'instruction fautive était écrite sur deux. Deuxième fois de la journée qu'un contrôle
approximatif me fait croire une chose fausse (la première : `grep` et « vous **êtes** »).
Pour affirmer une propriété sur tout le code, lire le code, pas des lignes.

---

## Session du 26/08/2026 (suite) — R50/R51 : premier appel sur l'arbre corrigé

Cinquième appel réel, et le premier à tourner sur le code corrigé. **R49 a fonctionné en
production** : l'appelant disait « Zivier-sur-Orge » (le STT pour Juvisy), la commune n'est
dans aucune de nos tables, et l'agent a dit « votre secteur » au lieu de répéter un nom qui
n'existe pas. C'est la première fois qu'un correctif se vérifie à l'oreille.

Deux défauts nouveaux, tous deux dans la même réplique :

    User : « Je suis sur Zivier-sur-Orge, le quatre-vingt Non, c'est 160 »
    Agent: « Ah d'accord, je comprends que TU m'appelles depuis le cent soixante.
             Je suis désolé, mais Dupont Chauffage n'intervient pas sur votre secteur. »

### R50 — un code postal qui n'en est pas un a raccroché

Le modèle a rendu `code_postal = "160"`. **Trois chiffres.** Le contrôleur l'a accepté tel
quel, l'a comparé aux listes de la zone, n'y a rien trouvé — et a **raccroché**.

C'est exactement le trou que R42 a bouché pour le téléphone, sur le champ qui décide si on
envoie un artisan chez quelqu'un. Et la conséquence est **pire** : un numéro faux produit un
RDV bancal, un code postal faux produit un refus définitif. Le projet avait déjà écrit la
règle pour la commune — « une décision terminale et coûteuse ne se prend pas sur une donnée
que personne n'a vérifiée » — mais elle ne couvrait pas le code postal venu de l'extracteur.

L'appelant était réellement hors zone : **on a eu raison par accident**. À Nogent, on
perdait un client sur un artefact de transcription.

`_code_postal_fr` rejoint `_numero_fr` dans le contrôleur, et `_merge` est le juge unique
des deux. Une mutation a d'ailleurs montré que mon premier contrôle était **trop strict** :
j'exigeais la forme exacte, ce qui rejetait « 91 260 » — un code postal parfaitement valide
que l'extracteur rend parfois ainsi. Les séparateurs sont tolérés, les lettres non (« 94130
environ » n'est pas un code postal). Même partage que pour le téléphone.

### R51 — l'agent a tutoyé

« Je comprends que **tu** m'appelles. » Le formuleur a changé de registre en pleine phrase.

Aucun garde-fou ne pouvait l'attraper : ni prix, ni promesse, ni caractère imprononçable, ni
salutation déplacée. Même famille que R46, mais plus grave — un client qu'on tutoie sans le
connaître entend un défaut de sérieux, chez un artisan qu'il paie. Et contrairement à R46,
la règle vaut **partout** : SMS et pages comprises, il n'existe aucun contexte où ce produit
tutoie.

Le motif ne retient que les marques qui ne sont QUE de la deuxième personne du singulier —
pronoms, possessifs, élision — et jamais de formes verbales, innombrables et ambiguës.
Vérifié par balayage sur **tous** les textes du produit et des configs : zéro correspondance.

Piège au passage : `grep` dans une locale C m'a fait croire à des faux positifs sur « vous
**êtes** », qui contient « tes ». En Python, `\b` connaît l'Unicode et ne s'y trompe pas.
Ne pas conclure d'un `grep` sur du texte accentué.

### Ce que les mutations ont encore corrigé dans mon travail

Sept sur huit. La survivante est une **défense en profondeur vérifiée** et non supposée :
`_chiffres_dits` soumet un candidat de code postal, et si son propre contrôle disparaît,
`_merge` le refuse quand même (mesuré : `00123` → None, `94130` → retenu). Le juge est
unique, les contrôles amont sont des ceintures.

Une mutation a été **retirée** parce qu'elle visait le mauvais test, et une autre **recalée**
sur R47, où le cas qu'elle exerce est réellement couvert. Une mutation qui tue pour la
mauvaise raison, ou qui ne peut rien exercer, ne prouve rien.

---

## Session du 26/08/2026 (suite) — R49 : l'appelant avait raison trois fois

Quatrième appel réel, et le plus frustrant du lot. **L'appelant a donné son code postal
trois fois, correctement, et n'a jamais été compris.**

    User : J'ai pissé sur Orange le 91/160. Le 91/260.
    User : Dans l'Essonne. Le 91. Code postal 91/160.
    User : Dans l'Essonne, 91/160.

La transcription écrit les codes postaux avec une **barre oblique**. R43 tolérait l'espace,
le point et le tiret ; pas celle-là. Le slot était dans la phrase, trois fois de suite, et
passait à travers trois fois.

**Et R48 aggrave le symptôme au lieu de le masquer.** Depuis que la question de la commune
est bornée, on ne boucle plus : **on raccroche poliment sur quelqu'un qui a répondu juste**.
Une borne est bonne pour l'appelant qui ne sait pas répondre ; elle est cruelle pour celui
qu'on n'écoute pas. Les deux correctifs devaient arriver ensemble — c'est une leçon sur
l'ordre dans lequel on corrige, pas seulement sur ce qu'on corrige.

### Second défaut : « n'intervient pas sur Essonne »

L'Essonne est un DÉPARTEMENT. Le nom venait de l'extracteur, et le contrôleur l'a répété
sans le vérifier.

C'est le pendant exact de R45 : là-bas le formuleur écorchait un nom propre, ici
l'extracteur en invente la nature. Même règle — **on ne prononce que ce que notre table
connaît**. Le repli (« votre secteur ») existait déjà ; il n'était simplement jamais
atteint. La DÉCISION, elle, ne change pas : c'est le code postal qui tranche la zone, pas
le nom. Une commune hors Île-de-France ne sera donc pas nommée, et c'est volontaire : mieux
vaut « votre secteur » qu'un nom qu'on ne peut pas vérifier.

### Deux mutations survivantes, un trou de test bien caché

« Supprimer la table Île-de-France » et « ne reconnaître aucune commune » survivaient toutes
deux. Raison : dans mon test, le nom de commune était DANS la phrase, donc il venait de
`_resoudre_commune` — le nouveau chemin (`_merge` → `_commune_connue`) n'était jamais
emprunté. Il a fallu un cas où l'extracteur donne la commune et où le texte brut est trop
déformé pour la retrouver (« Je suis à Sussi en Bri » → Sucy-en-Brie). Deux chemins mènent
au même slot ; en tester un ne teste pas l'autre. Troisième fois ce mois-ci.

Une mutation a été retirée plutôt que forcée : entre `{0,3}` et `{0,6}` caractères de
séparation, aucun énoncé réaliste ne diffère — il faudrait quatre séparateurs consécutifs,
et ce qui sépare vraiment deux nombres (des lettres) n'est pas dans la classe. Une mutation
sans objet ne se tue pas, elle se supprime.

### Reste

Ces quatre appels tournaient tous sur du code antérieur. **Redéployer avant de rappeler** :
la moitié de ce qu'on observe est déjà corrigé dans l'arbre.

---

## Session du 26/08/2026 (suite) — trois appels de plus : la parole n'est pas de l'écrit

**⚠️ Ces trois appels tournaient sur du code ANTÉRIEUR au commit `af67d6d`.** Vérifié : les
quatre re-salutations observées sont toutes interceptées par les garde-fous actuels, y
compris la pire — celle où l'agent a **redémarré la conversation** (« Bonjour, vous appelez
Dupont chauffage. Comment puis-je vous aider ? ») au lieu de reposer sa question. R46 la
remplace par l'instruction du contrôleur. **Redéployer avant de retester**, sans quoi on
corrigera deux fois les mêmes choses.

Deux défauts étaient malgré tout nouveaux, et tous deux tiennent à la même chose : *la
parole n'est pas de l'écrit.*

### R47 — un code postal se PRONONCE, il ne s'épelle pas

Trois appels d'affilée, trois façons de dire le même code postal :

    « Quatre-vingt-onze soixante. »              → 91 60 : incomplet, à redemander
    « Quatre-vingt-onze-deux-cent-soixante. »    → 91260
    « 91.260. »                                  → déjà des chiffres

Nos extracteurs cherchaient des chiffres. Le slot était dans la phrase et passait à
travers ; sur l'appel 1, l'appelant a fini par renoncer. **C'est la forme NORMALE de la
parole**, pas un cas tordu : personne ne dit « neuf quatre un trois zéro ».

`nombres.py` convertit les nombres prononcés, **dans le contrôleur et pas dans le prompt**
(règle n°1) : c'est une conversion, pas une interprétation. Le modèle réel y arrive
PARFOIS — une fois sur deux sur ces trois appels — et « parfois » ne fait pas un produit
quand la donnée décide si on envoie un artisan chez quelqu'un.

Le français rend l'exercice moins trivial qu'il n'y paraît, et deux pièges ont été trouvés
en écrivant le module :

- **« soixante-dix-huit »** se lisait 70 puis 8. Un numéro de téléphone dicté à voix haute
  y perdait un chiffre en route.
- **« quatre cent quatre-vingt-dix »** se lisait 404 puis 30 : dans « quatre cent quatre »
  le second « quatre » vaut 4, dans « quatre cent quatre-vingt-dix » il ouvre 80. Résolu
  par une fusion « quatre vingt » → un seul mot AVANT l'analyse, plutôt qu'un cas
  particulier traîné dans tout l'automate.

Le même mécanisme sert au téléphone (« zéro six, douze, trente-quatre… »), et il reste
soumis au verrou de R42.

**Un défaut trouvé en écrivant le test, pas après** : la dictée d'un numéro contient une
sous-suite de cinq chiffres (« zéro six, douze, trente-quatre » → 61234) qui **écrasait un
code postal déjà établi**, envoyant hors zone un appelant qui n'y était pas. Le cas (e) du
test faisait tomber le cas (d). On ne cherche donc un code postal en lettres que si l'on
n'en a aucun ; la correction par le nom ou par les chiffres reste ouverte.

### R48 — la question de la commune n'était bornée par rien

Sur les trois appels, quand la commune n'est pas comprise — et avec un STT qui entend
« Orange » pour « Juvisy-sur-Orge », cela arrive — l'agent repose la même question, mot
pour mot, sans fin. Mesuré en mock : six tours identiques, et ça continuerait.

**Troisième compteur manquant de la même famille** : `tentatives_tel` borne la demande du
numéro, `confirmations_tel` sa confirmation (R32), `tours_creneaux` les propositions de
créneau — la commune, rien. Une boucle sans borne au téléphone n'est pas une gêne : c'est
un appel perdu, et un client convaincu que personne ne l'écoute.

Deux chances (la question, puis une relance), puis `_sans_rdv` : on ignore la zone, donc on
ne promet aucun RDV — on prend le lead et Julien rappellera. Un lead exploitable vaut
infiniment mieux qu'une boucle.

### Une mutation a encore trouvé du code mort

J'avais écrit « le compteur ne monte que si la question a déjà été posée » — condition
**toujours vraie**, `_s1` posant la question et levant le drapeau avant qu'on arrive là. La
mutation qui la neutralise ne changeait rien : elle était équivalente. Retirée. Du code
mort qui a l'air d'une garantie est pire que pas de garantie du tout, et c'est la troisième
fois dans ce projet qu'une mutation survivante le révèle.

### Ce qui marchait, dans ces trois appels

L'agent a demandé de répéter sur une transcription incompréhensible (« Je viens de fuir
donner un sale demain ») au lieu d'inventer. L'appel 2 a conclu hors zone correctement sur
un code postal dicté en lettres — le modèle réel l'avait converti, cette fois. L'appel 3 a
conclu sur « 91.260 », que R43 couvre désormais côté contrôleur.

### Reste à faire

Redéployer, puis retester : trois des problèmes observés sont déjà corrigés dans l'arbre.
Et brancher `endCallPhrases` — sur l'appel 3, l'agent a terminé par « bonne continuation,
et. », phrase tronquée, sans que personne ne raccroche.

---

## Session du 26/08/2026 — DEUX APPELS VOCAUX RÉELS : six défauts, dont un grave

**Fait.** Le produit a parlé au téléphone, deux fois, sur des scénarios COMPLETS — une
sortie hors zone et une réservation. Un vrai RDV est en base, `en_attente_validation` chez
art-dupont : **la boucle voix → validation artisan est démontrable**. Six défauts en sont
sortis. R42 à R46, mutations 10/10, 6/6, 5/5, 7/7. Suite : **50 PASS**.

### R42 — un numéro à peu près juste est pire qu'un numéro absent

Douze chiffres dictés (« 06 10 15 47 68 79 »), dix répétés par l'agent sans rien signaler,
« oui c'est bien ça », et un RDV réservé. Le lead en base le prouve :
`telephone: '0610154768'`, `tel_confirme: True`.

L'invariant « pas de RDV sans téléphone confirmé » était **syntaxiquement respecté et trahi
en substance** : ce qui a été confirmé n'est pas ce qui a été dicté. C'est le défaut le plus
grave trouvé jusqu'ici, parce qu'il produit un RDV parfaitement normal en apparence dont le
seul moyen de rappel est faux. Sans numéro, l'invariant arrête la réservation et l'artisan
rappelle ; avec un numéro faux, personne ne voit rien.

Deux étages. La regex `0\d(?:[\s.\-]?\d{2}){4}\b` s'arrêtait après quatre paires — le
`\b` tenait, un espace suivant. Et surtout : **le contrôleur faisait confiance à
l'extracteur**. Corriger la seule regex n'aurait protégé que le mock ; le modèle réel peut
rendre dix chiffres sur douze entendus. `_numero_fr` vit donc dans le CONTRÔLEUR, et
`telephone_rappel` est le seul slot revérifié en entrée — le seul dont une valeur
approximative produit un RDV d'apparence normale.

### R43 — un code postal dicté n'était pas reconnu

« C'est le 91 260 » : le slot était dans la phrase, et manqué. Puis manqué une seconde fois
sur « Dans le 91. 260 ». Un code postal se PRONONCE en deux groupes, et la transcription
pose un séparateur au milieu — parfois deux caractères (« . »). Exiger cinq chiffres collés
faisait perdre un tour entier.

**Leçon produit, plus grosse que le correctif** : c'est le CODE POSTAL qui a sauvé cet
appel, là où le nom de commune a échoué deux fois — le STT entendait « Orange » pour
« Juvisy-sur-Orge ». Cinq chiffres résistent à la transcription bien mieux qu'un nom propre.
**Faut-il inverser la question de S1 (« votre code postal, ou votre commune ? ») ? Ouvert,
non tranché** — c'est une décision produit, pas une correction.

### R44 et R45 — deux fois la même leçon que R38

**Personne ne raccroche.** Après S11, chaque tour reçoit une phrase de fin jusqu'à ce que le
CLIENT raccroche. Et cette phrase, laissée au formuleur, est sortie bégayée : « L'appel.
L'appel est terminé. » Elle est désormais **verbatim**, donc identique à chaque tour — ce
qui n'est pas un détail de style : le mécanisme qui coupe la ligne côté Vapi
(`endCallPhrases`) compare ce que l'agent DIT à une liste de phrases, et une phrase
reformulée à chaque tour ne peut correspondre à rien. **Rendre la clôture déterministe est
le préalable au raccrochage.** Le signal de fin par appel d'outil n'est PAS écrit : on ne
l'a pas mesuré, et l'étape 0 a montré ce que valent les paris sur cette plateforme.

**La commune prononcée n'était pas la nôtre.** Le transcript est net sur qui fautait :
l'appelant dit « Nogent-sur-Marne » (bien transcrit), l'agent répond « Nogènes-sur-Marne ».
La résolution avait parfaitement fonctionné — le lead porte `Nogent-sur-marne / 94130`,
zone `en_zone`. **La seule chose fausse de tout l'appel était la seule que le client ait
entendue.** Le formuleur écrivait un nom propre : précisément ce qu'un modèle ne devrait
jamais avoir à écrire. Le contrôleur acquitte désormais la commune lui-même, verbatim, avec
la forme de notre table.

Troisième et quatrième fois que le même remède s'applique : **là où le fond compte, le
contrôleur parle lui-même.**

### R46 — une seule salutation, et pas de point après des chiffres

L'agent a resalué au deuxième tour. C'est l'un des tics qui font entendre qu'on parle à une
machine, et aucun garde-fou ne pouvait l'attraper : ni prix, ni promesse, ni caractère
imprononçable — juste une phrase déplacée. Nouveau garde-fou, **opt-in** : mon premier essai
l'appliquait par défaut et six tests sont tombés d'un coup, les SMS et la phrase de la sonde
commençant légitimement par « Bonjour ». Un SMS est un premier contact, pas un tour de
conversation. *Le défaut d'un garde-fou doit être de ne rien interdire à ceux qui ne l'ont
pas demandé.*

Et un point placé juste après un groupe de chiffres est lu par la synthèse vocale comme une
fin d'énoncé : « 06 10 15 47 68. C'est bien ça ? » devient deux phrases sans rapport. Une
virgule garde la question dans le même souffle. ⚠️ Ce qu'on entend comporte AUSSI des
coupures qu'on n'écrit pas — elles viennent du découpage de la plateforme. Corrigé ce qui
nous appartient ; le reste demande une oreille.

### Une mutation survivante a trouvé un contournement de la règle n°2

`open()` n'appelait pas `_say` : il écrivait l'accueil directement dans le transcript.
**La ligne d'accueil échappait donc entièrement aux garde-fous** — celle qui porte l'annonce
IA. Le risque était faible (la formule vient de la config) mais « faible » n'est pas
« nul ». Corrigé, et R46 le vérifie avec une formule d'accueil délibérément fautive : si
elle ressort sans violation, c'est que personne ne l'a regardée.

### Un piège d'outillage qui fausse les mesures de mutation

Une mutation qui conserve la TAILLE du fichier et s'écrit dans la même seconde que la
restauration laisse Python servir un **.pyc périmé** (l'invalidation se fait sur mtime +
taille). Remplacer « , » par « . » ne change pas un octet : le banc annonçait alors des
résultats sans rapport avec le code testé — un 7/7 contaminé, redescendu à 6/7 une fois
mesuré proprement. Tous les bancs purgent désormais le bytecode après chaque écriture.

### Trois mesures d'oreille, consignées

1. **Latence** : le plancher (réseau + STT + TTS + tunnel, zéro calcul) est confortable.
   C'est un plancher, pas un verdict — le vrai test est plancher + contrôleur (~1,9 s en
   Haiku). Les phrases-tampons restent au programme.
2. **Fin de tour** : `startSpeakingPlan.waitSeconds = 0.4` produit un léger blanc si
   l'appelant marque une pause. **Ne pas le réduire** : notre public est stressé, parfois
   âgé. Curseur à régler sur du réel.
3. **Barge-in** : impossible de couper l'agent en l'état. À activer (`stopSpeakingPlan`) —
   les tours verbatim longs (récapitulatif de RDV, consignes de sécurité) sont exactement
   ceux qu'un appelant pressé voudra couper.

**Prochaine étape.** Brancher `endCallPhrases` sur la phrase de fin désormais stable,
activer `stopSpeakingPlan`, et rappeler. Les évals réelles devront intégrer les dictées de
ces deux appels — un numéro à douze chiffres et un code postal séparé sont des cas de
production, pas des curiosités.

---

## Session du 25/08/2026 (fin de soirée) — l'adaptateur vocal (R41)

**Fait.** `proto/relais_proto/vapi.py` + la route `POST /voix/vapi[/chat/completions]`,
couverts par **R41**, mutations **14/14**. Le port `Depot` accepte désormais un identifiant
d'appel imposé, vérifié par le contrat **sur Supabase réel**. Suite : **45 PASS**.

**La récolte a changé deux hypothèses de conception.** C'est le retour sur investissement
de la sonde, et il ne s'est pas vu venir :

1. **Un appel web ne porte AUCUN numéro appelé.** `call.type == "webCall"`, transport
   Daily, pas un seul champ en `+33` dans toute la charge utile. Or `/webhooks/appel`
   identifie l'artisan par le numéro composé — et le spike se fait justement **sans**
   numéro français. Sans la sonde, l'adaptateur aurait été écrit autour d'un champ qui
   n'existe pas dans le seul mode où on allait s'en servir. D'où `artisan_de_l_appel` :
   le numéro composé s'il existe (production), sinon un artisan désigné en configuration
   (`RELAIS_VOIX_ARTISAN`), sinon **404 explicite** — un rattachement au hasard enverrait
   les leads d'un artisan chez un autre, sans la moindre erreur visible.

2. **Vapi rejoue le même tour.** Le 25/08 à 21:20 : quatre requêtes en sept secondes,
   même nombre de messages, pendant un barge-in. Les traiter ferait avancer le contrôleur
   de quatre états pour une seule phrase de l'appelant — la conversation part de travers
   et personne ne comprend pourquoi. `est_un_rejeu` s'en sert du fait que Vapi renvoie
   **tout l'historique** : le nombre de messages `user` est un numéro de séquence, comparé
   aux tours déjà inscrits dans notre transcript. **Aucun stockage nouveau** — l'état
   existant suffisait. Sur un rejeu, on redit la dernière réplique, ce qui est aussi le
   bon comportement à l'oreille : l'appelant qui a coupé l'agent n'a pas entendu la fin.

**L'identifiant de la plateforme EST notre clé.** `call.id` est un UUID valide et stable
sur tout l'appel, donc il entre tel quel dans `appel.id`. Le port a gagné un paramètre
`appel_id` facultatif plutôt qu'une table de correspondance : une table de plus, c'est une
désynchronisation de plus. Le contrat du port a été étendu et rejoué contre les DEUX
implémentations — la colonne est de type `uuid`, c'est exactement le genre d'ajout qui
marche en mémoire et casse en base.

**Ce que l'adaptateur ignore, et pourquoi c'est un invariant** : le message système de
Vapi (celui de son assistant par défaut, « You are Riley… ») et tout l'historique renvoyé.
Notre état vit dans le dépôt, notre prompt vient de notre moteur. R41 le vérifie avec un
prompt système **hostile** — il promet 500 dollars et une confirmation immédiate — et
exige qu'aucun des deux n'apparaisse. Un prompt étranger qui déciderait quoi que ce soit
serait une violation directe de la règle n°1.

**L'annonce IA sort du moteur, jamais d'un `firstMessage` configuré chez le prestataire.**
Elle est non négociable (règle n°5) et ne doit pas pouvoir diverger dans un tableau de
bord que personne ne relit. L'assistant Vapi doit donc être créé **sans** premier message.

**Clôture factorisée.** `/webhooks/appel/{id}/tour` et la porte voix partagent désormais
`_cloturer_appel` : deux transports, un seul métier. Le jour où l'un des deux oublierait
de créer le RDV, c'est LA fonction produit qui disparaîtrait sans la moindre erreur.

**Mutation, et un kill pour la mauvaise raison.** La mutation « un jeton d'artisan ouvre
la porte voix » a d'abord été tuée par un 401 sur le chemin NORMAL : en remplaçant le
contrôle du secret, elle cassait aussi l'authentification légitime, si bien que le
contrôle visé n'était jamais atteint. Rejouée sous la forme réaliste — un `or` qui ACCEPTE
les deux — elle est tuée par le bon message, sur R41 comme sur R40. Une mutation qui tue
par effet de bord ne prouve rien.

**Prochaine étape.** Créer l'assistant Vapi par l'API (STT/TTS français, sans premier
message, `stopSpeakingPlan` actif), pointer le custom LLM sur `/voix/vapi`, et appeler.
Le prérequis Haiku est **déjà rendu** : 42/42 au 7ᵉ passage sur l'arbre corrigé
(`evals/results-20260825-213151.json`), sans incident de harnais.

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

### 24/08 — coût par message persisté, envoi réel opt-in, et un défaut de résilience trouvé

**1. Le coût de chaque envoi est désormais stocké.** `totalCreditsRemoved` était jeté.
Modélisation : `Envoyeur.envoyer()` rend maintenant un **`Envoi(reference, cout)`** au lieu
d'une chaîne. Le coût est une propriété de l'ENVOI, il remonte donc par la valeur de retour ;
`creditsLeft`, qui est l'état du COMPTE, reste un attribut de l'adaptateur. Migration 005,
colonne `cout`, aller-retour vérifié par le contrat sur Postgres. `EnvoyeurJournal` simule un
coût d'après la vraie règle de facturation, pour que les chiffres de dév soient justes.
Objectif : chiffrer la dépense SMS par artisan et par mois — la donnée qui dira si changer de
fournisseur se rentabilise (spec §10). **Elle ne repasse jamais** : ne pas la stocker, c'est
ne jamais pouvoir la reconstituer.

**2. Envoi réel opt-in dans `worker.py`.** `RELAIS_SMS=journal` par défaut (rien ne part),
`ovh` pour l'envoi réel. Le défaut est volontairement inoffensif : **un cron mal configuré ne
doit pas se mettre à écrire à de vrais clients.** Le mode est annoncé à chaque passage, le
coût du passage est affiché, et `RELAIS_SMS_NUMERO_COURT=1` existe comme mode de transition —
avec la conséquence assumée que les SMS de reproposition y échoueront définitivement, puisque
les URL sont bloquées.

**3. Défaut de résilience trouvé en vérifiant.** `worker.py` est tombé alors que
`run_depot_pg.py` passait : l'hôte direct de Supabase **a cessé de résoudre sur cette
machine** (il est en IPv6 — le piège annoncé s'est matérialisé), et le repli sur le pooler
n'existait **que dans le lanceur de tests**. Une logique de résilience qui ne vit que dans le
harnais de test ne protège personne. `resoudre_connexion()` est maintenant dans `depot_pg.py`
et partagée par les trois points d'entrée. Vérifié : le worker annonce désormais
« session pooler (après échec de directe) » et travaille normalement.

À retenir : c'est la troisième fois aujourd'hui qu'une vérification d'apparence routinière
révèle un vrai défaut — le gabarit `.env` trompeur, le motif de diagnostic masqué, et ce
repli manquant. Aucun n'aurait été trouvé en relisant le code.

Suite : **27 PASS**, Postgres vert (via le pooler).

### 24/08 — page de confirmation client : le lien mène enfin quelque part

Le lien qu'on avait rendu délivrable menait à `{"entreprise":"Dupont Chauffage",...}`. Il n'y
avait **aucune ligne de HTML dans le projet**. C'est corrigé.

**`relais_proto/pages.py`** : HTML rendu côté serveur, **aucun framework, aucune étape de
build, aucun JS**. 1,7 ko autonome. Pourquoi ce choix : la page est ouverte une fois, depuis
un SMS, sur un téléphone dont on ne sait rien — réseau de chantier, navigateur intégré à
l'application de messagerie. Et **aucune ressource externe** : ni police distante, ni script
tiers. Rien qui puisse échouer, rien qui puisse pister l'appelant d'un artisan. R21 vérifie
l'absence de `<script>` et de `http://` dans la page.

Le formulaire poste sur la **même URL**, donc ça marche sans JavaScript, partout.

**Quatre états, tous rendus en pages lisibles** (plus aucune erreur brute) :
- proposition (200) : entreprise, créneau, un bouton de 52 px ;
- confirmée (200) ;
- lien inconnu **ou déjà utilisé** (404) ;
- créneau périmé (410 en consultation, 409 en validation).

**La décision d'UX la plus utile de cette brique.** L'usage unique du jeton reste intact,
mais un client qui recharge sa page après avoir validé tombait sur un « lien invalide » —
il pouvait croire que sa validation avait échoué. Le texte du 404 dit désormais : « Si vous
venez de valider, **c'est bien pris en compte** et l'artisan a été prévenu. » Le même texte
sert au lien inconnu, donc on ne renseigne pas un curieux tout en rassurant le client.
R21 le vérifie.

**Deux erreurs de ma part attrapées par le test.**
1. J'asseyais l'assertion sur `rdv.creneau["label"]`, l'objet local **d'avant** la
   reproposition. Remplacé par une assertion plus utile : la page doit montrer le NOUVEAU
   créneau et **pas** l'ancien — afficher au client le créneau qu'on remplace serait une
   vraie confusion.
2. Le `html.escape` transformait l'apostrophe de « aujourd'hui », ce qui a révélé le
   point 1. L'échappement est le bon comportement ; c'était l'assertion qui était naïve.

Suite : **27 PASS**.

### 24/08 — boîte de validation artisan : le produit devient démontrable

C'est « LA fonction » de la spec §6, et il n'y avait aucun moyen de la déclencher sans
`curl`. Maintenant Julien ouvre une page sur son téléphone, voit ses RDV en attente avec
score et raisons, et valide, refuse ou repropose. **Sans JavaScript**, sans ressource
externe, avec les sélecteurs de date et d'heure natifs du téléphone.

**La décision de conception qui compte, et elle vient d'une question de Geoffrey.** Je
proposais un « lien magique » par notification — c'est-à-dire un jeton de capacité dans
chaque SMS, chacun donnant accès à des données client. Sa question (« à terme ils auront
bien des comptes, non ? ») a montré que je résolvais un problème trop étroit. La bonne
réponse est une **session longue sur l'appareil** : Julien valide plusieurs fois par jour,
il se connecte rarement. Et une fois la session posée, **les liens de notification
redeviennent des URL banales** — la couche comptes SUPPRIME du travail au lieu d'en ajouter.

Corollaire consigné : la **méthode** de connexion (code SMS, Google, mot de passe) devient
un détail interchangeable au-dessus de la session. Ce qui compte est qu'elle soit simple le
jour rare où elle sert.

**Fait.**
- `session.py` + migration 006 (`session_artisan`) : 32 octets d'aléa, **empreinte SHA-256
  seule en base**, expiration appliquée PAR LE DÉPÔT (impossible d'oublier de la vérifier),
  révocation à la déconnexion. Cookie `HttpOnly`, `SameSite=Lax`, `Secure` (désactivable
  pour les tests en HTTP).
- `pages.py` : boîte de validation et écran de connexion. Actions en POST + redirection 303,
  pour qu'un rechargement ne rejoue pas la validation.
- L'authentification artisan accepte **deux voies** : jeton porteur (API, future app mobile)
  ou cookie de session (navigateur). Un lien ouvert depuis un SMS ne peut pas porter d'en-tête.
- `/app` sans session rend la **page de connexion**, pas un code d'erreur nu : un artisan
  dont la session a expiré doit voir un écran utilisable.
- Test **R24** : session, contenu de la page, absence de JS et de ressource externe,
  validation et reproposition depuis le navigateur, révocation côté serveur à la
  déconnexion, étanchéité entre artisans. Contrat étendu aux sessions et **vérifié sur
  Postgres** — sinon leur SQL n'aurait jamais tourné.

**Dette assumée et datée.** `POST /connexion` accepte encore le **jeton d'artisan du
registre fichier**. Faire saisir un secret de longue durée dans un champ est acceptable pour
deux artisans de test, **pas pour des clients payants**. À remplacer par un code reçu par
SMS, avec la table `artisan` — c'est la brique suivante.

Suite : **28 PASS**. Postgres vert (via le pooler).

### 24/08 — bug réel : connexion en boucle depuis le téléphone

**Symptôme** (Geoffrey, test réel sur `http://192.168.x.x:8000`) : le jeton est accepté,
mais on retombe indéfiniment sur la page de connexion.

**Cause.** `serveur.py` appelait `creer_app()` **sans raccorder `cookie_secure`**, donc le
défaut `True` s'appliquait : le cookie partait avec l'attribut `Secure` et le navigateur le
jetait en HTTP. `localhost` est une exception chez Chrome, **mais pas une IP de réseau
local** — le paramètre existait, il n'était simplement branché nulle part.

**Le plus instructif est pourquoi R24 ne l'a pas vu.** `TestClient` **n'applique pas**
l'attribut `Secure` : il renvoie le cookie quand même. Un test qui se fie au comportement du
client passe donc sur PC pendant que le téléphone échoue. Le test doit inspecter
**l'en-tête `Set-Cookie` lui-même**.

**Corrigé.**
- `RELAIS_COOKIE_SECURE`, lue dans `serveur.py` et passée à `creer_app`. Défaut `true`, et
  **seul le mot exact « false » désactive** : `flase`, `0`, `False!` laissent le cookie en
  `Secure`. Fail-safe volontaire — la production ne doit pas pouvoir régresser par
  étourderie. Le serveur avertit bruyamment au démarrage quand l'attribut est désactivé.
- R24 vérifie l'en-tête `Set-Cookie` dans **les deux modes**, plus `HttpOnly` et
  `SameSite=Lax` qui ne dépendent d'aucun mode.
- Vérifié que le test attrape bien le défaut d'origine : en rejouant « `creer_app` appelé
  sans `cookie_secure` », R24 échoue.

**Leçon.** Un test qui passe par un client d'intégration ne teste que ce que ce client
applique. Ici, la propriété à vérifier n'était pas « la session marche » mais « l'en-tête
porte les bons attributs » — et seule la seconde formulation attrape le bug.

Suite : **28 PASS**.

### 24/08 — le même bug une seconde fois : je devinais au lieu de rendre visible

**La cause était triviale** : `RELAIS_COOKIE_SECURE` était absent du `.env` racine. Je
l'avais documenté dans `.env.example` **sans le dire explicitement**, et sans rien pour
rendre l'état observable. Deux tours de diagnostic perdus sur une ligne manquante.

**Ce qui était vraiment en cause : rien ne montrait l'état.** L'avertissement ne s'affichait
que lorsque l'attribut était désactivé — donc son absence pouvait signifier « configuration
sûre » **ou** « réglage non pris en compte ». Un état qu'on ne voit que lorsqu'il est anormal
ne se distingue pas d'un réglage ignoré.

**Corrigé, sur trois plans.**
- Le serveur annonce le réglage **à chaque démarrage**, valeur brute comprise :
  `cookie de session : Secure=False (RELAIS_COOKIE_SECURE='false')`.
- `/sante` l'expose : vérifiable depuis le téléphone en dix secondes, sans aller-retour.
- La page de connexion **diagnostique** selon la cause : « aucun cookie reçu » renvoie vers
  l'attribut Secure et `RELAIS_COOKIE_SECURE` ; « cookie inconnu » dit session expirée. Les
  confondre coûtait un tour.
- R24 verrouille les deux messages **et** l'exposition dans `/sante` : un diagnostic non
  testé pourrit.

**Leçon, la troisième du même genre aujourd'hui.** Après le repli de connexion qui ne vivait
que dans le harnais de test, et l'attribut `Secure` que `TestClient` n'applique pas : quand
un réglage décide qu'une chose marche ou non, **le rendre observable vaut mieux que le
documenter**. J'ai passé deux tours à supposer au lieu d'une minute à instrumenter.

Suite : **28 PASS**.

### 24/08 — connexion OK depuis le téléphone, et un défaut que seul l'usage révèle

`POST /connexion` → 303, `GET /app` → **200**. La boîte de validation s'ouvre sur le
téléphone. Mais le premier tap réel a donné **409 Conflict** sur une reproposition.

**Cause, vérifiée en base et non devinée** : le RDV était `en_attente_validation` avec une
échéance à 11:00, alors qu'il était 15:23 — **échu depuis 4 h 23**. Le domaine avait raison
de refuser. Ce sont deux autres choses qui avaient tort.

**1. La boîte affichait des RDV sur lesquels l'artisan ne peut plus rien.**
`rdvs_en_attente()` rend les RDV NON TERMINAUX, échus compris — et le worker d'expiration ne
passe qu'à intervalles, donc il existe toujours une fenêtre pendant laquelle un RDV échu est
encore là. La page proposait donc des boutons qui ne pouvaient qu'échouer.

Choix retenu : **les garder visibles, mais sans boutons**, avec « Délai dépassé — le client
est prévenu et le créneau libéré. Rappelez-le si vous voulez le récupérer. » Les masquer
serait pire : l'artisan doit savoir qu'il a laissé filer un lead. Et l'ordre change — les
décidables d'abord, le plus pressé en tête, les échus ensuite.

**2. Le refus s'affichait en JSON brut.** Après un tap sur un téléphone,
`{"detail":"RDV ... échu depuis ..."}` est illisible. Toute action refusée par le domaine
rend maintenant une page, avec le motif venu du domaine et un lien de retour. Même défaut
que la page client avant sa correction — je l'avais réparé d'un côté, pas de l'autre.

**R24 verrouille les deux** : présence du signalement, absence du bouton, et refus rendu en
HTML avec le lien de retour.

**Leçon.** Aucun test ne pouvait trouver ça, parce que tous mes scénarios créaient des RDV
dans les temps. C'est le RDV **oublié depuis quatre heures** — une donnée réelle, pas un cas
construit — qui a révélé le trou. Les jeux d'essai propres ne produisent pas l'état sale que
la production produit toute seule.

Suite : **28 PASS**.

### 24/08 — les fuseaux : la dette n°1 était deux pannes, pas une

**Fait.** Le domaine passe aux **instants tz-aware en UTC**, le schéma en `timestamptz`
(migration 007, appliquée sur Supabase). Doctrine et outils dans un module dédié,
`relais_proto/temps.py` ; règle n°7 de `CLAUDE.md` ; test **R25**.

**Ce que j'ai trouvé en ouvrant le sujet.** Le journal notait une panne — « une échéance
posée la veille du basculement vaut 23 h ou 25 h ». Il y en avait **deux**, et la seconde
était la plus grave :

1. **Une durée fausse.** `depuis + 24 h` sur une pendule vaut 23 heures réelles le dernier
   dimanche de mars. L'artisan à qui on promet 24 heures en perd une.
2. **Un ordre ambigu.** Le dernier dimanche d'octobre, 02h00–02h59 arrive **deux fois**.
   `maintenant >= expire_a` pouvait donc être vrai, puis redevenir faux. Un RDV
   **dé-expiré** — en contradiction frontale avec l'invariant n°1 de `rdv.py` (aucune
   sortie d'un état terminal) et avec la décision verrouillée le 23/08 : « l'échéance fait
   foi, pas le passage du worker ». Deux heures par an, cette décision était fausse.

Le cas concret que R25 écrit : l'échéance tombe à la **seconde** occurrence de 2 h 30,
l'artisan tape à la **première**. Il est dans les temps d'une heure pleine. Le code naïf
lisait deux fois « 02:30 » et lui refusait sa décision.

**Ce qui était déjà sain, par chance plus que par choix.** Les créneaux prononcés au
client (`{date, de:"08:00", a:"10:00", label}`) sont des **chaînes** dans un `jsonb`,
jamais des colonnes datetime : « demain entre 08h et 10h » ne pouvait pas dériver. Et la
règle n°2 de `rdv.py` — l'horloge est toujours un paramètre — laissait exactement **deux**
points d'entrée à convertir, `api.py` et `worker.py`. Une règle écrite pour la testabilité
a payé sur un sujet qu'elle ne visait pas.

**Décidé.**

- **Instants en UTC, heures de pendule dans le fuseau de l'artisan** (`cfg["fuseau"]`,
  défaut `Europe/Paris`). Restent des heures de pendule, et doivent le rester : la plage de
  silence 21h–08h, les heures ouvrées, la fenêtre d'urgence, les libellés de créneau.
- **tz-aware plutôt qu'une convention « naïf = UTC ».** Python refuse de comparer un naïf
  et un aware : un chemin oublié lève une `TypeError` bruyante au lieu de dériver d'une
  heure en silence. La bascule l'a prouvé tout de suite — la suite a planté au premier
  calcul d'heures ouvrées, exactement là où il fallait.
- **Jamais d'arithmétique sur un aware en heure locale.** `paris_aware + timedelta(24 h)`
  ajoute 24 h à la *pendule* : c'est le piège d'origine reproduit avec un objet aware.
  Tout circule en UTC, la conversion n'a lieu qu'aux bords.
- **Le fuseau est une config d'artisan, pas une constante.** Le jour où un artisan est à
  La Réunion, ça doit se lire comme un réglage, pas comme un bug. Vérifié à la
  construction du `Registre` : « Europe/Pari » refuse de démarrer au lieu de lever en
  plein appel.
- **Ambiguïté et trou : choix explicites.** Heure inexistante (saut de mars) → l'instant
  tombe après le saut. Heure répétée (octobre) → première occurrence. Une fin de plage de
  silence s'applique ainsi au plus tôt : on ne fait pas attendre un client parce que la
  pendule bégaie. Postgres tranche pareil dans la migration 007 — c'est le point.

**Migration.** `at time zone 'Europe/Paris'` sur chaque colonne : les valeurs en base
étaient de l'heure locale, un cast nu les aurait prises pour de l'UTC et décalées de deux
heures sans rien dire. Même précaution côté blobs : `temps.depuis_iso` relit un horodatage
naïf (état de conversation écrit avant aujourd'hui) comme de l'heure de Paris. Repli
supprimable quand plus aucun blob d'avant le 24/08 ne circulera. La session Postgres est
fixée à UTC : deux machines ne doivent pas lire la même ligne avec deux offsets.

**R25 a été écrit avant le correctif** (règle n°4) et **éprouvé par mutation** : six
erreurs de conception réintroduites, dont l'arithmétique sur une pendule locale, la plage
de silence calculée en UTC, et les blobs relus comme de l'UTC. Quatre tuées directement ;
une cinquième (l'instant naïf accepté) ne tombe qu'en retirant les *deux* gardes, ce qui
est de la défense en profondeur et non un trou ; la sixième (heures ouvrées calculées sur
la date UTC) est un **mutant équivalent** — l'algorithme se rattrape par son `max()`.
Noté ici pour ne pas la re-chercher : elle ne peut pas être tuée, et `temps.en_local` reste
la bonne expression de l'intention.

**Ce que ça ne couvre pas.** Le contrôle de fuseau porte sur le registre, pas sur les
fichiers de config lus ailleurs. Et `relais_base_de_test.autorise_le` (table du harnais de
test, pas du domaine) reste en `timestamp` : hors périmètre, signalé pour ne pas passer
pour un oubli.

Suite : **29 PASS**, contrat Postgres rejoué contre Supabase après migration 007.

### 24/08 — le nom de l'appelant : le correctif évident était le mauvais

**Fait.** L'extraction du nom dans `MockLLM` est refaite et couverte par **R26**. La ligne
« rate `Je m'appelle X` » disparaît du bloc ÉTAT, où elle traînait depuis le 22/08.

**Le piège.** Le défaut noté était « regex sans `IGNORECASE` ». Ajouter `re.IGNORECASE`
paraissait donc être le correctif — c'était une **régression**. La regex d'origine était :

    (?:je m'appelle|c'est) (?:m\.|mme|madame|monsieur)?\s*([A-ZÉÈ][a-zé-]+)

`[A-ZÉÈ]` n'y sert pas qu'à décrire un nom : il fait office de **filtre de
capitalisation**, seul garde-fou contre l'alternative `c'est`. En insensible à la casse, ce
garde-fou tombe, et six phrases sur dix produisent un faux nom :

    nom='bien'    <- Oui c'est bien ça
    nom='parfait' <- Le premier créneau c'est parfait, je suis chez moi quand vous voulez
    nom='urgent'  <- c'est urgent
    nom='en'      <- C'est en cours là, ça goutte dans le placard
    nom='Nogent-sur-Marne' <- C'est Nogent-sur-Marne
    nom='Julien'  <- C'est Julien qui m'a donné votre numéro

Les deux premières sont des lignes **de nos propres scénarios de test**. Le correctif
d'une ligne aurait donc empoisonné la suite en la faisant passer au vert.

**Pourquoi ça méritait mieux qu'un rustine de test.** `MockLLM` n'est pas qu'un double :
c'est le **chemin de dégradation en production** (`ResilientLLM`). Quand l'API LLM tombe,
c'est lui qui extrait. Et `nom` n'est pas dans `OVERWRITABLE` : le premier nom capté est
**définitif**. Un faux positif au premier tour part ensuite dans le push à l'artisan —
« Nogent a validé le créneau ». D'où la règle retenue : **dans le doute, pas de nom.** Un
« un client » se lit ; un mauvais nom est une erreur affichée avec aplomb.

**Décidé.**

- **On ne s'appuie plus sur la majuscule mais sur un introducteur explicite.** La casse
  n'est pas un signal fiable : un moteur de transcription vocale rend aussi bien
  « je m'appelle garcia ». `je m'appelle`, `mon nom est`, `au nom de`, `X à l'appareil`.
- **`c'est` nu est exclu**, et c'est le cœur du correctif : c'est l'une des tournures les
  plus fréquentes du français parlé. Il n'est accepté que suivi d'un titre
  (« c'est Monsieur Diallo »). Conséquence assumée : « C'est Garcia » ne donne pas de nom.
  Le coût est un nom manqué, c'est-à-dire la panne acceptable.
- **Le contexte est enfin lu.** « Garcia, 06 12 34 56 78 » n'a aucun introducteur : il
  n'est lisible que parce que l'agent vient de demander « à quel nom ? ». `MockLLM`
  ignorait purement et simplement le `context` que l'interface lui passe déjà — le vrai
  LLM, lui, s'en sert. Une exigence de forme (virgule, numéro ou fin de phrase) évite que
  « Non je préfère pas donner mon numéro » devienne nom='Non'.
- **Jeu de caractères Unicode** : Lefèvre, Dupont-Martin, D'Angelo, Müller passent. Ils
  échouaient tous avec `[a-zé-]`, qui n'admettait qu'un seul accent de toute la langue.

**Ce que ça débloque.** Le chemin « nom connu » des messages artisan n'était jamais
exercé : tous les leads mock sortaient sans nom, donc tous les gabarits rendaient la
branche « un client ». R26 vérifie maintenant de bout en bout qu'un scénario qui donne un
nom produit « Garcia » dans la relance.

**Mutation : 6/6.** Dont le correctif naïf lui-même, `c'est` nu accepté, le contexte
ignoré, et le jeu de caractères sans accents. Le filet `_PAS_UN_NOM` a d'abord **survécu** —
aucun cas ne l'exerçait, la règle de forme arrêtait tout. Ce n'était pas du code mort mais
un test manquant : une réponse d'un seul mot (« Non », « Merci ») passe la forme et n'est
arrêtée que par lui. Cas ajoutés, mutation tuée.

Suite : **30 PASS**.

---

## Session du 25/08/2026 — le Sender ID ne dépendait de rien de ce que je croyais

**Décisions prises avec Claude (Cowork) les 24–25/08, consignées ici pour qu'elles fassent
foi.** Cette entrée corrige explicitement une affirmation fausse produite le 24/08 en
séance de code.

### La correction, d'abord

> ❌ **PÉRIMÉ — ne pas réutiliser :** « le Sender ID attend un premier artisan réel, qui
> attend la voix ; la chaîne est voix → numéro → artisan → Sender ID ».

Ce raisonnement partait d'une prémisse non vérifiée : que l'expéditeur déclaré serait celui
de l'ARTISAN (`sms.expediteur = "DupontChauf"` dans sa config), donc qu'il faudrait le Kbis
d'un artisan réel. La décision actée est l'inverse : **un expéditeur UNIQUE, déclaré sous
notre propre société.** Le Sender ID n'attend donc ni artisan, ni voix, ni numéro.

Quatre raisons retenues pour l'expéditeur unique :

1. **Échelle des justificatifs** : un Kbis à fournir, pas un par artisan.
2. **Réputation cumulée** : un seul expéditeur qui se construit une histoire chez les
   opérateurs, au lieu de N expéditeurs neufs et suspects.
3. **Les gabarits le permettent déjà** : les deux SMS clients ouvrent par « Bonjour, c'est
   {nom_entreprise} » — l'artisan est nommé DANS le message, pas seulement dans
   l'expéditeur. Vérifié dans `messages.py` : aucun des textes clients ne dépend de qui
   signe l'envoi.
4. **Honnêteté vis-à-vis de l'opérateur** : c'est nous qui émettons, techniquement et
   juridiquement. Déclarer la marque d'un artisan reviendrait à dire autre chose.

Le point restant avec le cousin est le **positionnement** (produit visible vs marque
blanche), pas la faisabilité.

### Ce que le Sender ID attend RÉELLEMENT

a) le **nom commercial** — décision du cousin, et information nouvelle : **le nom final ne
   sera pas « Relais »**, qui reste le nom de code interne ;
b) la **structure juridique** au nom aligné — le Kbis est le justificatif demandé par OVH ;
c) le **domaine** assorti.

C'est-à-dire : un seul goulot, le nom.

### DupontChauf supprimé

Geoffrey a retiré l'expéditeur en validation chez OVH. Refus probable (entreprise fictive,
aucun justificatif à produire) et surtout plus aucune valeur de test : le numéro court
couvre tous les besoins actuels. Rien à regretter — l'hypothèse d'API OVH avait déjà été
confirmée le 24/08 par un envoi réel.

### Périmètre réel du besoin Sender ID, affiné

Seuls les SMS **contenant une URL** sont bloqués en numéro court. Vérifié dans le
catalogue : un seul gabarit porte un `{lien}`, `reproposition_client`. Tout le reste —
`expiration_client`, les deux messages artisan, et le futur code de connexion à 6 chiffres
— passe en numéro court **dès aujourd'hui**.

Conséquence stratégique : une bêta sur le flux nominal ne dépend pas du Sender ID.

⚠️ **Mais elle dépend d'autre chose, découvert en vérifiant ce point** — voir « le trou »
ci-dessous.

### Contraintes AF2M 2026 (sources consultées le 25/08)

À consigner pour le choix du nom :

- **11 caractères maximum** ;
- **alphanumériques latins uniquement** — ni espace, ni caractère spécial ;
- déclaration **en minuscules** ;
- **termes génériques interdits** comme expéditeur : RDV, ALERTE, LIVRAISON, PAIEMENT… ;
- l'expéditeur doit correspondre au **nom commercial** ou à une marque dont on a la
  titularité.

### OAuth Google : NE PAS lancer

Contrairement au plan du 24/08. Deux raisons :

1. la vérification exige nom d'app + domaine vérifié + politique de confidentialité
   hébergée — elle attend donc **la même décision de nom** que le Sender ID ;
2. le choix du premier calendrier à brancher (Google, Outlook, ou aucun) sera tranché par
   les **interviews terrain** du cousin — la question est ajoutée à sa liste.

Rappel utile, contre la tentation de traiter le calendrier comme urgent : `CalendarStub`
couvre déjà le cas de l'artisan **sans agenda numérique**, qui n'est pas un cas dégradé
mais probablement le cas courant. Le calendrier externe est un **anti-double-réservation**,
pas une condition d'existence du produit.

### Document « décisions côté cousin »

Produit et transmis, en 5 blocs : nom commercial (goulot unique), structure juridique,
positionnement de l'expéditeur unique, questions terrain (agenda utilisé, Android/iOS,
acceptation d'un expéditeur au nom du produit, délais 24 h/2 h, prix annoncé), et
bêta/prix/politique de confidentialité. **Pas encore versionné** : à déposer dans `docs/`
si on veut qu'il fasse foi ici aussi.

### Le trou, trouvé en vérifiant le point « bêta possible »

**La boucle nominale n'envoie rien au client.** L'agent promet pourtant, verbatim et sans
échappatoire (`engine.py`, phrase du script) :

> « Vous recevrez un SMS de confirmation de Julien d'ici 2 heures. »

Or quand l'artisan tape **Valider**, `api._decider` écrit le RDV et rend la réponse — **aucun
message n'est mis en file**. Idem sur **Refuser**. Le catalogue ne contient que quatre
gabarits, et aucun `confirmation_client` :

| Chemin | Ce que le client reçoit |
|---|---|
| L'artisan valide | **rien** ❌ — alors qu'on le lui a promis à l'oral |
| L'artisan refuse | **rien** ❌ |
| L'artisan repropose | `reproposition_client` ✅ (avec lien) |
| L'échéance passe | `expiration_client` ✅ |

Les deux chemins couverts sont les chemins d'ÉCHEC. Le chemin nominal — celui qui
justifie le produit — est muet. Ça n'a jamais été vu parce que tous les tests vérifient la
transition d'état et la file, pas l'écart entre **ce que l'agent promet à l'oral** et ce
que le système envoie ensuite.

Donc : la bêta sur le flux nominal est bien indépendante du Sender ID, mais elle est
bloquée par ce gabarit manquant. C'est petit (un template + un branchement + un test), et
c'est à faire avant la connexion par code SMS.

### Deux autres conséquences code, vérifiées

- **« Relais : » est EN DUR** dans `confirmation_artisan` et `expiration_artisan`. Puisque
  le nom final ne sera pas « Relais », il doit devenir une **variable de config produit**.
  Et le pire-cas de R23 devra alors être joué avec un nom de **11 caractères**, la limite
  AF2M. Note : le nom du produit n'apparaît dans **aucun** SMS client — il n'y a donc pas
  d'enjeu de coût côté client, seulement côté messages artisan si ceux-ci deviennent un
  jour des SMS de repli.
- **`sms.expediteur` est lu dans la config ARTISAN** (`envoi_ovh.py` : « sms.expediteur
  absent de la config artisan »). Avec un expéditeur unique, ce réglage doit remonter au
  niveau produit — sinon chaque artisan pourrait déclarer le sien, ce qui contredit
  frontalement la décision actée.

### Prochaine brique code, confirmée

**Connexion par code SMS + table `artisan`** (avec l'état d'abonnement, pour la facturation
future). Débloquée à 100 % : un code à 6 chiffres n'a pas d'URL, donc le numéro court
suffit. Précédée du `confirmation_client` ci-dessus, qui est plus court et plus urgent.

**Le spike VOIX reste à discuter en session dédiée avec Claude (Cowork) avant tout
engagement — ne pas l'ouvrir seul.**

### 25/08 — le chemin nominal parle enfin

**Fait.** Gabarit `confirmation_client`, branché sur les deux issues décidées par
l'artisan, et **R27** — une classe de test qui manquait.

**Le texte.** « Bonjour, c'est {nom_entreprise}. C'est confirmé : {prenom} passe
{creneau}. » Il nomme l'entreprise ET le patron : depuis la décision d'expéditeur unique,
l'expéditeur du SMS ne dit plus au client de qui vient le message, c'est donc au texte de
le faire. Pire cas R23 : 113 caractères, 1 segment GSM-7, **47 de marge**. Aucune URL —
il part donc en numéro court dès aujourd'hui, sans attendre le Sender ID.

**Le refus aussi.** L'artisan qui refuse laissait le client attendre un rendez-vous qui
n'aurait pas lieu — la même promesse rompue, en pire. Il reçoit maintenant `repli_client`,
le texte déjà écrit pour l'expiration : de son point de vue c'est la même chose (le créneau
n'est pas retenu, on le recontacte), et les deux issues sont exclusives, donc la clé
d'idempotence existante reste correcte.

**Une trouvaille en passant : `rdv_valide` était du code mort avec une intention.**
`guards.check_output` porte depuis le début un paramètre `rdv_valide` qui autorise le mot
« confirmé » — et `messages._texte` le passait en dur à `False`. Personne ne s'en était
jamais servi, parce que le seul message légitime pour le lever n'existait pas. La
confirmation client est cet appelant : c'est le SEUL texte du produit où « confirmé » est
permis, et seulement parce que l'artisan vient de valider. R27 exige les deux sens — que le
texte passe avec `rdv_valide=True`, et qu'il serait **refusé** sans.

**Ce que R27 verrouille, et pourquoi c'est une classe nouvelle.** Tous les tests
précédents vérifient des transitions d'état et le contenu de la file. Aucun ne relisait la
phrase prononcée à l'appelant pour la confronter aux faits — c'est exactement pour ça que
le trou a vécu depuis le début du projet. R27 tient les deux bouts : il vérifie d'abord que
l'agent dit bien « SMS de confirmation » dans le transcript, puis que chaque issue produit
le bon message. Si la phrase du script change, le test le dit.

Il exige aussi : le bon destinataire (le numéro confirmé par l'appelant, pas un autre), pas
d'URL, 1 segment GSM-7, et **le compte exact** de SMS clients — un SMS de trop est un SMS
payé et subi.

**Décidé : pas de SMS quand le client confirme par le lien.** Il vient de taper et lit la
page de confirmation à l'instant même ; le lui réécrire serait un crédit dépensé pour lui
apprendre ce qu'il a sous les yeux. Noté en commentaire dans `api.confirmer`, là où un
futur « correctif » créerait le doublon.

**Effet de bord assumé sur R24.** Sa validation depuis la page met désormais un SMS en
file, ce qui cassait une assertion « exactement 1 message client ». Elle exige maintenant
**2 messages, dont exactement 1 avec lien** — plus stricte qu'avant, pas plus laxiste.

**Mutation : 5/5.** Dont le trou d'origine (aucun envoi), un refus qui enverrait la
confirmation (le client se déplacerait pour rien), le garde-fou `rdv_valide` non levé, une
URL glissée dans le texte, et la confirmation envoyée à l'artisan au lieu du client.

**Ce qui reste ouvert, et qui est connu.** L'écriture du RDV et la mise en file ne sont pas
atomiques : un process tué entre les deux perd le SMS. C'est le même compromis que pour la
reproposition, et il est retenu dans le même sens — mieux vaut un SMS perdu, rattrapable
par un humain, qu'un SMS envoyé pour un RDV qui ne serait pas enregistré. Un worker de
rattrapage (les RDV validés sans message associé) serait la vraie réponse ; il attend un
besoin réel.

Suite : **31 PASS**, contrat Postgres toujours vert.

### 25/08 — connexion par code SMS : le champ « jeton » disparaît

**Fait.** Table `artisan` (migration 008, FK sur cinq tables), puis connexion par **code à
6 chiffres reçu par SMS** (migration 009, R28). L'écran qui faisait saisir un secret de
longue durée dans un champ n'existe plus.

**Ce que ça ferme.** La dette n°7 (registre fichier avec jetons de dév publics) et l'écran
de connexion provisoire, tous deux ouverts depuis le 23/08.

### La table `artisan` : deux choix de schéma contre-intuitifs

Les deux sont imposés par les données déjà en base, pas par le goût :

- **`id` en `text`, pas en `uuid`.** Les colonnes `artisan_id` portent déjà « art-dupont » :
  une clé en uuid rendait toute reprise impossible. L'identifiant lisible se révèle un
  avantage en exploitation — « artisan art-dupont inconnu » se lit sans jointure.
- **`numero_relais` et `telephone` NULLABLES**, ce qui surprend pour des champs aussi
  essentiels. C'est la condition pour poser les FK sur des données existantes : la
  migration crée d'abord une ligne par `artisan_id` déjà référencé, dont elle ne connaît en
  SQL que l'identifiant. Ces lignes portent `etat_abonnement = 'a_reprendre'`, et le
  registre les écarte **en le disant** au démarrage. Vérifié en vrai : `art-martin`, qui
  avait des données mais aucune graine, a été récupéré exactement ainsi.

Les FK sont posées dans une boucle conditionnelle : **les migrations sont rejouées en
entier** à chaque `--migrer`, et un `add constraint` nu passerait une fois puis casserait
tout. Rejouée deux fois pour le vérifier.

`on delete restrict` est volontaire : on ne supprime pas un artisan qui porte des
rendez-vous ou des messages — ce sont des engagements envers des clients. Une résiliation
se marque dans `etat_abonnement`, elle n'efface rien.

### Le code SMS : la sûreté ne vient pas de la longueur

Six chiffres, c'est un million de possibilités — confortable pour un humain sur un
chantier, dérisoire pour une machine. Trois propriétés compensent, et chacune est
verrouillée par R28 :

1. **le code meurt vite** (10 minutes) ;
2. **les essais sont comptés** (3), et le code meurt avec eux ;
3. **un seul code vivant par artisan** — d'où la clé primaire sur `artisan_id` et non sur
   l'empreinte. Sans ça, chaque demande ajouterait une cible, et en demander mille
   donnerait mille chances au lieu de trois.

S'y ajoutent un **frein au renvoi** (60 s : chaque code est un SMS facturé et une
notification chez quelqu'un — sans frein, un tiers fait sonner le téléphone d'un artisan à
nos frais) et l'**absence d'énumération** : la page répond exactement la même chose pour un
numéro connu et pour un inconnu. Ce dernier point protège nos clients, pas nous : sinon
n'importe qui peut demander à cette page si tel numéro est celui d'un de nos artisans.

L'essai est **consommé avant la comparaison**. Un processus tué au mauvais moment ne doit
pas offrir une tentative gratuite — c'est tout ce qui sépare six chiffres d'un secret
devinable.

### Un bug trouvé par le test, pas par la relecture

La clé d'idempotence du SMS dérivait d'abord de **l'horodatage à la seconde**. Ça paraît
marcher et ça ne marche pas : deux demandes dans la même seconde rendent le PREMIER
message, donc l'ANCIEN code, alors que la base porte déjà l'empreinte du nouveau —
l'artisan reçoit un code que le système refusera. Trouvé en rejouant deux connexions
rapprochées dans R24. La clé dérive maintenant de l'**empreinte du code** : un code donné a
un message et un seul, un code neuf a toujours le sien.

### Envoi immédiat, et une leçon réapprise

Un code qui arrive au prochain passage du cron n'est pas un code de connexion. L'API prend
donc un `Envoyeur` injecté et expédie **ce message seul** (`Expediteur.passer(seulement=…)`)
— surtout pas la file entière : un artisan qui se connecte déclencherait sinon tous les SMS
clients en attente, hors du cron et hors de tout contrôle de débit. La file reste la source
de vérité et le worker rattrape si l'envoi direct échoue.

Le choix du fournisseur (`RELAIS_SMS`) a été **remonté dans `envoi.choisir_envoyeur`**,
partagé par le serveur et le worker. Même leçon que le 24/08 avec `resoudre_connexion` :
une logique de composition qui ne vit que dans un point d'entrée laisse l'autre diverger en
silence.

### Effets sur les tests existants

- **R23** : sa convention de nommage (« `*_client` part en SMS ») est remplacée par une
  **liste explicite**. Le code de connexion est un SMS envoyé à l'ARTISAN : la règle
  déduite du nom laissait passer sans contrôle de coût le seul message que tout artisan
  reçoit à chaque connexion.
- **R24** : se connecte désormais comme un humain — demande, lecture du code **dans le
  SMS**, saisie. Aucun test ne va chercher le code en base : il n'y est pas, et c'est
  précisément la propriété à préserver.
- Le contrôle des attributs de cookie a dû être restructuré : `httpx` refuse d'envoyer un
  cookie `Secure` sur du HTTP — donc une connexion complète en `cookie_secure=True` est
  impossible en test, exactement comme dans un navigateur. C'est le bug du 24/08 qui se
  rejoue, correctement cette fois. Le test repose le cookie à la main pour lire l'en-tête
  émis sans éprouver le transport, et contrôle maintenant **les deux** cookies.

**Mutation : 7/8 sur R28.** Le survivant est le plafond d'essais, doublé par la suppression
du code au troisième échec : en retirant les DEUX gardes, R28 tombe. Défense en profondeur,
pas trou de test.

**Reste ouvert.** Le jeton porteur survit pour l'API et la future app mobile : c'est aussi
le filet si le SMS ne part pas (crédits épuisés, fournisseur en panne) — sans lui, une
panne SMS nous enfermerait dehors. Et `semer_artisans.py` reste le seul chemin d'écriture
du registre : il faudra un vrai onboarding, pas un script.

Suite : **32 PASS**, contrat Postgres vert contre les deux migrations.

### 25/08 — le nom du produit devient un réglage, avant même d'être connu

**Fait.** `config/produit.json` + `relais_proto/produit.py` + **R29**. Le jour où le cousin
tranche le nom, c'est **une ligne à changer**, dans un fichier, une fois.

**Pourquoi maintenant, justement parce qu'on ne connaît pas le nom.** C'est le seul moment
où ce travail a du sens : le faire après aurait été une chasse dans les gabarits, sous la
pression d'une déclaration en attente.

### Deux défauts, et le second était le plus grave

1. **« Relais » était en dur dans trois gabarits** — dont `code_connexion_artisan`, ajouté
   la veille : la dette se creusait pendant qu'on la constatait.
2. **`sms.expediteur` vivait dans la config de chaque ARTISAN**, ce qui contredisait
   frontalement la décision actée du 25/08 : un expéditeur **unique** déclaré sous notre
   société. En l'état, chaque artisan aurait déclaré le sien. Ce n'était pas une dette de
   confort mais un **écart entre le code et une décision verrouillée**.

### La séparation retenue

- **config ARTISAN** (`config/dupont.json`) : ce que l'agent sait de LUI — tarifs, zone,
  horaires, délais. Elle lui appartient.
- **config PRODUIT** (`config/produit.json`) : qui NOUS sommes — le nom affiché dans les
  SMS qu'il reçoit, et l'expéditeur déclaré chez l'opérateur. Il ne peut rien y régler.

La fusion se fait **au chargement du registre** (`produit.appliquer`), pas en passant un
second argument à chaque constructeur de message : `cfg` devient « tout ce que le système
sait pour cet artisan », ce qui était déjà son rôle. Aucune signature existante n'a changé.

### Les contraintes AF2M sont encodées, plus seulement écrites

`produit.valider_expediteur` refuse au **démarrage** : plus de 11 caractères, tout ce qui
n'est pas alphanumérique latin (espace, accent, tiret), et les termes génériques
(`rdv`, `alerte`, `livraison`, `paiement`…). Un nom qui ne passerait pas la déclaration doit
être refusé tout de suite, pas découvert 72 heures après le dépôt du dossier. La règle
vivait dans le journal depuis ce matin ; elle vit maintenant dans le code.

Corollaire : **le pire cas de R23 se joue désormais avec un nom de 11 caractères**
(« Chantierpro »), la limite AF2M — puisque le nom affiché et l'expéditeur désigneront la
même marque, il n'y a pas de raison que l'un dépasse l'autre.

### Détails qui comptent

- `sms.expediteur` a été **retiré** de `config/dupont.json` et de la spec. Le laisser
  traîner ferait croire qu'il est réglable, et le premier onboarding le remplirait pour
  rien. R29 vérifie qu'il n'y revient pas.
- Sans config produit, l'envoi est refusé par un échec **définitif** : aucun passage de
  worker ne réparera une config manquante, et signer un SMS de rien serait pire que ne pas
  l'envoyer.
- La spec artisan portait encore l'arbitrage « sender alphanumérique vs SMS
  bidirectionnel », tranché le 23/08. Nettoyé au passage.

**Mutation : 7/7.** Dont le retour du nom en dur, le nom redevenu une constante déguisée
derrière la config, l'artisan qui reprend la main sur l'expéditeur, et chacune des trois
contraintes AF2M retirée séparément.

**Reste à faire le jour où le nom arrive** : changer `config/produit.json`, vérifier que
R23 passe (il éprouve déjà 11 caractères), déposer le Sender ID. Rien d'autre dans le code.

Suite : **33 PASS**, contrat Postgres vert.

## Session du 25/08/2026 — évals réelles : trois bugs produit, dont un qui perdait des leads

**Fait.** Premier vrai passage d'éval LLM contre l'agent depuis le 22/08 : 24 conversations
(8 personas × 3). **19/24** au départ. Les échecs ont livré trois défauts distincts, tous
corrigés et verrouillés — **R30**, **R31** — plus deux réparations du harnais lui-même.

### Le plus coûteux : « il faudrait que quelqu'un VIENNE assez vite »

Une fuite d'eau en cours, à Nogent, appel perdu **au premier tour**. Mécanisme :

1. `_resoudre_commune` balaie la phrase entière contre les 1 504 communes d'Île-de-France ;
2. la table contient un alias court `vienne` — Vienne-en-Arthies, 95510, Val-d'Oise ;
3. le CP étant « connu », `_s1` **saute la question** « vous êtes sur quelle commune ? » ;
4. `_s2` classe hors zone et raccroche.

Un subjonctif de « venir » — la tournure la plus banale du métier — coûtait le lead.
**Reproductible 3 fois sur 3**, et c'est aussi ce qui a fait tomber R09 [3/3] : quatre des
cinq échecs étaient ce seul bug.

Deux correctifs, parce qu'il y avait deux fautes :

- **La table** portait des alias d'un seul mot qui sont des mots français courants
  (`vienne`, `bois`, `champs`, `bourg`). L'exclusion vit dans le CODE (`ALIAS_AMBIGUS`) et
  non dans le fichier de données : celui-ci est régénéré depuis la base officielle, et une
  régénération réintroduirait les homonymes en silence. Les alias LÉGITIMES restent —
  « Issy », « Sucy », « Ivry » sont ce que les gens disent vraiment — et le nom complet
  reste résoluble.
- **Surtout** : une commune jamais demandée ni confirmée pouvait CLORE l'appel. C'est la
  même faute que valider un RDV sans téléphone confirmé — une décision terminale et
  coûteuse prise sur une donnée que personne n'a vérifiée. Désormais, une commune glanée
  au passage qui mènerait hors zone déclenche **une** question (« vous êtes bien à X ? »).
  Une commune DEMANDÉE, elle, tranche immédiatement : pas de question de trop.

L'astuce d'implémentation qui rend le tout simple : en posant la question de confirmation,
on **vide** les slots et on garde le candidat de côté. La réponse est alors relue sans
entrave — si l'appelant corrige, la nouvelle commune s'installe normalement ; s'il confirme,
on restaure le candidat. Aucun ordre subtil à respecter.

### La même phrase en cachait un second

`MockLLM` lisait « **quelqu'un** » dans « il faudrait que quelqu'un vienne » comme une
demande de parler à un humain. Dans ce métier, c'est la façon la plus banale de demander une
intervention. Et `MockLLM` est le **chemin de dégradation en production** : une panne d'API
transformait donc toute demande d'intervention en transfert. Le mot ne compte plus que dans
un contexte de parole (« parler à quelqu'un »).

### Une leçon apprise en S4 et jamais généralisée à S5

T05 (M. Katz, chasseur de prix) : l'agent propose des créneaux, l'appelant redemande le
prix, l'agent **repropose d'autres créneaux**, le compteur de l'invariant n°6 avance, et à
la deuxième question le RDV est perdu — alors que l'appelant était toujours partant.

Le code de S4 porte pourtant, depuis le 22/08, ce commentaire : « une QUESTION (prix...)
n'est pas un REFUS : on y répond avec la liste blanche et on redemande, **sans consommer le
quota** (bug T05-LLM : Katz posait des questions de prix et perdait son RDV) ». La leçon
avait été apprise une fois, dans un état, et jamais propagée au suivant. Le même persona a
retrouvé le même défaut deux mois plus tard, ailleurs.

Pire : l'agent **avait un prix autorisé à donner** (« le déplacement avec diagnostic est à
90 € TTC ») et ne l'a jamais donné — il a répondu deux fois « je ne suis pas en mesure de
vous donner un tarif ». La phrase tarifaire vivait en ligne dans S4 ; elle est maintenant
factorisée (`_phrase_prix`) et disponible partout.

**Trouvé en écrivant le test, pas en lisant le code** : « Oui MAIS ça coûte combien ? » était
lu comme l'acceptation d'un créneau, et l'agent réservait. Un « oui » accompagné d'une
question ne vaut acceptation de rien — réserver dessus donne un rendez-vous que l'appelant
n'a pas accepté, exactement ce que tout le produit est construit pour éviter.

### Deux réparations du HARNAIS, avant même de mesurer

- **L'appelant simulé tournait en réflexion adaptative sans le savoir.** Sonnet 5 réfléchit
  par défaut même sans paramètre, et ses tokens de réflexion sont décomptés de `max_tokens` :
  à 1 000 tokens pour produire UNE réplique, la réflexion pouvait tout consommer et rendre un
  texte vide — que le harnais prend pour une fin d'appel. On fabriquait des FAIL. Réflexion
  désactivée : un appelant qui joue un personnage en une phrase n'a rien à en tirer.
- **`RELAIS_MODEL` pilotait à la fois l'agent et l'appelant.** Impossible de faire varier
  l'un en gardant l'autre fixe, donc impossible de comparer deux passages : l'énoncé bougeait
  avec la copie. L'appelant a maintenant sa variable (`RELAIS_MODEL_APPELANT`), et les deux
  modèles sont consignés dans le fichier de résultats.

Et une troisième, apprise à la dure en cours de session : **une coupure réseau a détruit un
passage entier** — 25 minutes de mesures déjà acquises, perdues sur une exception. L'agent a
sa dégradation gracieuse, le harnais n'avait rien. Une conversation perdue est maintenant un
résultat manquant (`erreur_harnais`), signalé à part pour ne pas être confondu avec un défaut
de l'agent, et les résultats partiels sont écrits.

### Ce que ça dit de la méthode

Les trois défauts avaient en commun d'être **invisibles aux tests mock** : tous mes scénarios
scriptés disent « Nogent-sur-Marne 94130 » proprement, jamais « il faudrait que quelqu'un
vienne ». Ce n'est pas un manque de rigueur dans les tests, c'est leur nature — un jeu d'essai
écrit par celui qui code ne contient que le français auquel il a pensé.

**Mutation : 6/6 sur R30, 4/4 sur R31.**

**Résultat après correctifs : 24/24** (contre 19/24 avant). T01 passe de « 1 tour » à cinq
tours et va au bout ; T05 aussi. Les cinq échecs venaient bien de ces trois défauts.

Reste un ⚠ sur T07 [1/3] : le formuleur a tenté un « c'est confirmé » et le garde-fou l'a
intercepté — comportement voulu, signalé en WARN et non en FAIL, mais à surveiller : c'est
le formuleur qui dérape, pas le contrôleur.

### 25/08 — le produit s'appelle NELYO

**Décision produit actée.** Le nom commercial est **NELYO**. « Relais » reste le nom de
**code** interne : on ne renomme ni le repo, ni les modules, ni les tables — du churn git
pour zéro valeur. Seul le nom **visible** change.

**Ce qui a été vérifié avant de trancher** (côté Geoffrey et son cousin) :

- **Conformité AF2M** : 5 caractères alphanumériques (limite 11), distinctif — absent des
  génériques proscrits —, et prononçable à l'oral par le futur agent vocal, ce qui n'est
  pas un détail quand le nom sera dit au téléphone. Déclaration de l'expéditeur **en
  minuscules** (`nelyo`), affichage libre en casse (`Nelyo`). Les deux vivent séparément
  dans `config/produit.json`, précisément parce qu'ils ne suivent pas la même règle.
- **Homonymes** : une SAS NELYO (2020, coaching/conseil) et une SARL NELYO (2008, portails
  Internet, apparemment dormante). Non bloquant — c'est la marque qui compte. Vérifications
  INPI (classes logiciels/télécoms) et dépôt : hors code.
- **Domaine** : candidat probable `nelyo-ia.*`. **Pas encore acheté, pas définitif.** Le
  tiret est valide dans un domaine mais pas dans un Sender ID — sans objet ici, l'expéditeur
  étant `nelyo`.

### Ce que ça a changé dans le code

Le gros du travail avait été fait la veille en rendant le nom paramétrable **avant** de le
connaître : il ne restait qu'à écrire `Nelyo` dans `config/produit.json`. Deux ajouts
néanmoins :

- **Les pages HTML ne portaient AUCUN nom de produit** — ni « Relais », ni rien. Le client
  qui ouvre le lien 1-tap ne voyait que son artisan. Ce n'était donc pas un remplacement
  mais un ajout : le nom apparaît maintenant dans le `<title>` (donc dans l'aperçu de lien
  que le téléphone affiche) et en signature discrète. Il est passé en **paramètre** à
  chaque page, jamais lu d'une constante.
- Le nom devait être joignable **sans artisan** : la page « lien invalide » s'affiche avant
  qu'on sache de qui relève le jeton. Il est donc porté par le `Registre`, qui charge déjà
  la config produit, et **exigé à la construction de l'application** — une page signée de
  rien est un défaut de câblage, pas une donnée d'exécution.

### R23 aux bornes : le test a trouvé un vrai coût

Demande explicite : éprouver le pire cas avec le nom réel ET un nom de 11 caractères, plus
un domaine pessimiste. Fait — et **le second a échoué** : avec l'enveloppe supportée
(entreprise 25 car. + prénom 15 car. + créneau 31 car.) et une racine de domaine de
16 caractères, `reproposition_client` tombait à **162 caractères, soit 2 crédits par
envoi**. Sur le seul cas réel, il passait : la borne, elle, a mordu.

Correction : ce gabarit perd sa salutation — le seul des quatre. Arbitrage chiffré et non
oubli : les 9 caractères de « Bonjour, » étaient **les seuls que nous contrôlions**, le nom
de l'artisan et la longueur du créneau ne se négocient pas. Et ce SMS n'est pas un premier
contact : le client vient de parler à l'agent. Marges obtenues, aux deux bornes : **11 à 67
caractères** selon les gabarits.

Au passage, une erreur de ma part corrigée : ma « racine de 16 caractères » en faisait 20.
Le test la mesure maintenant au lieu de la supposer.

Ce que la borne rend concret : **un domaine long coûte des crédits à chaque reproposition.**
C'est un argument chiffré pour le jour de l'achat, pas une préférence esthétique.

### La séquence externe, remise à jour

Plus rien de tout cela ne bloque le code :

**INPI / marque → domaine → structure & Kbis → dépôt du Sender ID chez OVH (~72 h)**

Et la boucle nominale n'attend même pas ce dernier maillon : seul `reproposition_client`
porte une URL, donc seul lui est bloqué par le numéro court.

### 25/08 (suite) — élargir les personas : deux chemins morts, deux boucles, et ma propre régression

**Fait.** Le jeu d'éval passe de 8 à **14 personas**. Les six nouveaux sont choisis par
**couverture du moteur**, pas par intuition. Résultat : **38/42** au premier passage, puis
**42/42** après correctifs (42 conversations, 14 personas × 3).

### La méthode : quels chemins AUCUN persona n'empruntait

Le moteur a six issues possibles (`categorie`) : `rdv_reserve`, `hors_zone`, `prioritaire`,
`a_rappeler`, `hors_perimetre`, `appel_muet`. Les huit personas d'origine en couvraient
**quatre**. Les deux manquantes n'étaient pas des cas exotiques — les travaux refusés, et le
répondeur. Choisir par couverture plutôt qu'au jugé a payé immédiatement.

### Bug 1 — `_hors_perimetre` était injoignable

`_ctx["prestations"]` ne donnait à l'extracteur que les prestations **couvertes**. Il ne
pouvait donc jamais nommer une prestation refusée : « déboucher la colonne de l'immeuble »
était rapproché de `wc_evacuation`, et **l'agent réservait un créneau pour des travaux que
l'artisan a explicitement exclus**. Il se déplace pour rien, le client perd une journée, et
la config `refusees` — écrite le 21/08 — ne servait à rien.

L'extracteur reçoit maintenant les deux listes. Il NOMME, le contrôleur DÉCLINE : la règle
n°1 est respectée, et c'est même elle qui rendait le correctif évident.

Au passage, `MockLLM` s'arrêtait au **premier** mot-clé trouvé : « déboucher la colonne de
l'immeuble, c'est bouché » contient `bouché` (couvert) et `colonne de l'immeuble` (refusé),
et la réponse dépendait de l'ordre du dictionnaire. C'est le mot-clé **le plus spécifique**
qui gagne désormais.

### Bug 2 — une correction de commune par le NOM était ignorée

« Je suis à Créteil… ah non pardon, Nogent-sur-Marne » : l'agent gardait Créteil et
**réservait dans la mauvaise ville**. `_resoudre_commune` sortait dès qu'un code postal
existait. Ce qui a caché le défaut : la correction du **numéro** fonctionnait, elle — une
asymétrie qu'aucune relecture n'attrape, il fallait un appelant qui se corrige.

### Bug 3 — la confirmation du numéro bouclait sans borne

Une réponse ni oui ni non faisait reposer la même question, **indéfiniment**.
`tentatives_tel` borne la DEMANDE du numéro, pas sa confirmation : deux boucles jumelles,
une seule protégée. Un appelant qui répond à côté deux fois tuait l'appel sans produire le
moindre lead.

Deux détails qui ont demandé un second essai : la **première** répétition est normale et
non un échec de compréhension (mon premier compteur la comptait, et cassait R01, le
scénario canonique de correction de numéro) ; et le compteur repart à zéro à chaque
**nouveau** numéro, une correction relançant une confirmation neuve. Au-delà, on conclut
avec un lead exploitable au lieu de mourir — l'invariant tient : pas de RDV sans téléphone
confirmé.

### Bug 4 — « ma mère » n'est pas Méré (78490)

Le persona qui visait les appels **passés pour un tiers** a trouvé un homonyme : « c'est
pour la chaudière de ma mère » résolvait Méré, dans les Yvelines. Trois fois sur trois. Une
des phrases les plus banales du métier — beaucoup d'appels sont passés pour quelqu'un
d'autre.

Le garde-fou du matin (R30) a bien joué : l'agent a demandé « c'est bien à Mère, la
commune ? » et la cliente a corrigé. Mais c'est un tour perdu sur une question absurde, et
`mere` rejoint donc `vienne`, `bois`, `champs` et `bourg`.

### Bug 5 — ma propre régression, trouvée le jour même

En corrigeant le bug 2, j'avais fait relire la commune **à chaque tour, sans condition**.
Conséquence, visible dans le même passage d'éval : « ne notez pas le numéro de **ma mère** »,
prononcé trois tours après coup, **réécrivait une commune déjà confirmée**. Le rendez-vous
changeait de ville en silence.

La règle qui en sort, et qui vaut mieux que les deux extrêmes :

> **Cinq chiffres ne sont jamais un homonyme ; un nom, si.** Un code postal prononcé corrige
> à tout moment. Un nom de commune ne remplace une commune ÉTABLIE que si l'appelant se
> corrige explicitement — négation, ou code postal dans la même phrase. Tant qu'aucune
> commune n'est établie, tout ce qui est nommé est bon à prendre.

Deux bornes, donc : le signal de correction, et le hold (une fois le créneau bloqué, plus
rien ne bouge).

### Un échec qui n'en était pas un

`T07_client_furieux` a échoué une fois sur trois avec `hors_zone`. Ce n'était **pas** un
défaut produit : le rôle du persona ne fixait aucune commune, l'appelant simulé en a donc
inventé une — « Villeneuve, 31270 », en Haute-Garonne — et l'agent a correctement conclu
hors zone. Le persona mesurait l'improvisation du double, pas le chemin qu'il visait. La
commune y est maintenant imposée. **Un persona sous-spécifié produit un faux défaut**, et
c'est aussi coûteux qu'un vrai qu'on ne voit pas.

### Les six personas

| Persona | Ce qu'il éprouve |
|---|---|
| `T04_danger_gaz` | **La consigne de sécurité** — le seul chemin où une erreur peut blesser. Vérifie que le 0 800 47 33 33 est prononcé |
| `T06_hors_perimetre` | Travaux refusés (colonne d'immeuble) — la catégorie jamais atteinte |
| `T09_tout_dun_coup` | Tout donné dans la première phrase : remplissage opportuniste, aucune question redondante |
| `T10_se_corrige` | Se trompe de commune ET de numéro, puis se reprend |
| `T12_pour_un_tiers` | Appelle **pour sa mère** : l'intervention est chez elle, le rappel est pour l'appelante |
| `T13_pieges_de_langue` | Non-régression du matin : « vienne », « bois », « quelqu'un » dans une seule conversation |

Le harnais sait maintenant vérifier **ce que l'agent a dit** (`texte_agent`,
`texte_agent_absent`) et pas seulement le lead produit : une consigne de sécurité non
prononcée ne se voit dans aucun slot.

### Ce qui reste découvert, et pourquoi

**`appel_muet` (S9)** n'est toujours pas couvert : le harnais interprète une réplique vide
comme une fin d'appel, donc un persona silencieux est indistinguable d'un persona qui
raccroche. Il faudrait que l'appelant simulé puisse rendre un « silence » explicite. Noté,
pas fait.

**Mutation : 6/6 sur R32 et R33, 6/6 sur les deux bornes de la relecture de commune.**
Trois de mes propres tests ont d'abord laissé passer des mutations — ils assertaient sur des
symptômes (les slots, une chaîne accentuée) plutôt que sur le comportement. Un cas en
particulier était **inerte** : `process()` court-circuite en clôture après réservation, donc
la garde du hold n'était jamais atteinte par ce chemin. Le test l'éprouve désormais en
direct, et le dit plutôt que de faire semblant.

Suite : **37 PASS** en mock, **42/42** en éval LLM réelle, contrat Postgres vert.

## Session du 25/08/2026 (fin) — la reproposition passe par OUI/NON, et le cap devient la voix

**Deux décisions**, consignées avant tout code : une révision produit sur la confirmation
client, et le cap du prochain gros chantier.

### Révision : la reproposition client sans lien

**Ce qui la déclenche.** Le Sender ID est reporté *sine die* — décision de principe : pas
d'administratif tant que le produit n'a pas prouvé sa valeur. Or le lien à un tap était la
**seule** fonctionnalité qui en dépendait, puisque les numéros courts bloquent les URL.
Plutôt que de laisser la reproposition en otage d'un dossier, elle passe par une **réponse
SMS à vocabulaire fermé** :

> « {Entreprise} vous propose plutôt {créneau}. Répondez OUI pour confirmer ou NON pour
> annuler. »

Zéro URL, donc **numéro court dès aujourd'hui**. Le mode `senderForResponse` qu'on utilise
déjà est prévu pour ça : les réponses arrivent dans le compte SMS OVH.

**Périmètre EXACT de la révision — ce point compte plus que le reste.** La décision du 23/08
« SMS strictement sortant » n'est **pas annulée, elle est circonscrite**. Ce qu'elle
interdisait reste interdit : le dialogue libre par SMS, le parsing de texte libre, un état
conversationnel côté client. Une réponse binaire à vocabulaire fermé n'est pas un dialogue.

- **Liste blanche** : oui / OUI / Oui / ok — non / NON / Non. Tout le reste → **un unique**
  SMS rappelant le format, puis silence. Pas de NLP.
- **UNE seule proposition active par numéro de client à la fois.** C'est ce qui rend « OUI »
  non ambigu — à contraindre dans la machine à états, pas seulement à espérer.
- Rattachement par **numéro E.164 + proposition active**. Réponse hors fenêtre → SMS
  « cette proposition a expiré, {entreprise} vous recontactera » (à formuler, sans URL).
- **Le lien à un tap n'est PAS supprimé du code.** Il redeviendra le chemin de confort le
  jour où un Sender ID existera. Le canal de confirmation client devient un point de
  **config** : `sms_oui_non | lien`, défaut `sms_oui_non`.

**Conséquence stratégique :** le Sender ID ne bloque désormais **aucune fonctionnalité**. Il
ne reste que du confort de marque — un SMS signé « nelyo » plutôt qu'un numéro court.

### À vérifier chez OVH AVANT d'implémenter

Trois questions ouvertes, à documenter dès qu'on a les réponses. Aucune ligne de code avant.

1. **Coût des SMS entrants** en numéro court : consomment-ils des crédits ?
2. **Le STOP** : intercepté par OVH, ou reçu par nous ? S'il nous parvient, c'est une
   obligation légale à traiter — liste noire locale et plus aucun envoi ensuite.
3. **Mécanique de réception** : polling `GET /sms/{service}/incoming` ou callback HTTP ?
   Avec quelle latence réaliste ? Un « OUI » qui met dix minutes à nous parvenir change le
   produit.

### Conséquences code, préparées et non écrites

- **Une brique « réception »** : le pendant entrant du worker sortant. Elle n'existe pas.
- **Deux nouveaux gabarits** (reproposition OUI/NON, expiration de proposition), à mesurer
  au pire cas dans R23 — l'invariant « 1 segment par gabarit client » doit tenir aux bornes,
  comme pour les autres.
- **Machine à états** : « réponse client OUI/NON » devient une nouvelle entrée. Aujourd'hui
  seul le tap sur la page produisait cet événement (`confirmer_par_client`), et il venait
  avec un jeton qui prouvait l'identité. Un SMS entrant ne prouve que le numéro : c'est une
  autorité plus faible, à traiter comme telle.

### Cap : la voix

Le prochain gros chantier est le **point d'entrée du produit** — sans lui, rien n'existe.
État des lieux structuré produit avant toute implémentation : **`docs/etat-des-lieux-voix.md`**.
Il part en arbitrage avec Claude (Cowork) ; rien n'est décidé ici.

Trois choses qu'il a fait apparaître et qui méritent d'être dans le journal :

1. **Un numéro français exige un Kbis et une pièce d'identité du dirigeant** (bundle
   réglementaire ARCEP). Reporter l'administratif a bien libéré le SMS — **mais le même
   Kbis reparaît immédiatement côté voix**. La décision « pas d'administratif pour l'instant »
   ne supprime pas le mur, elle le déplace du SMS vers la voix. D'où la proposition de faire
   le premier spike sur un **numéro non français**, qui n'en demande pas.

2. **La latence, mesurée et non supposée.** Un tour complet du contrôleur, hors STT et hors
   TTS : **3,42 s de médiane en Sonnet 5, 1,93 s en Haiku** (minimum 0,67 s sur les tours
   verbatim). Une conversation naturelle supporte 0,5 à 1 s de blanc. Le seul traitement
   texte consomme donc déjà deux à trois fois le budget.
   Et la cause est structurelle : le LLM extrait, **puis** le contrôleur décide, **puis** le
   LLM formule. Deux allers-retours par tour, c'est le prix de la règle n°1. Ce n'est pas une
   inefficacité à corriger, c'est un invariant à assumer — ou à contourner autrement (son
   d'attente, chemins verbatim étendus, Haiku).

3. **`numero_appelant` est reçu par le webhook et jeté.** Le champ existe dans le contrat et
   n'est utilisé nulle part, alors que la machine à états consacre deux à trois tours à
   demander, répéter et confirmer le numéro — la partie du parcours où l'on perd le plus
   d'appels. À étudier au raccordement, avec la nuance qu'un numéro présenté n'est pas
   toujours celui où le client veut être rappelé, et qu'il peut être masqué.

Signalé aussi : le bloc `telephonie` de la spec (`numero_artisan`, `numero_agent`,
`renvoi_verifie`) **n'existe pas** dans `config/dupont.json`. Le renvoi conditionnel — le
mécanisme même qui amène l'appel jusqu'à nous — n'est modélisé nulle part.

## Session du 25/08/2026 — arbitrage voix rendu : GO spike

Arbitrage rendu avec Claude (Cowork) sur `docs/etat-des-lieux-voix.md`. Décisions actées,
périmètre verrouillé.

### Les décisions

1. **Plateforme managée pour le spike.** Raison qui vaut d'être retenue : le spike doit
   mesurer le **plafond**. Si même un pipeline optimisé par un fournisseur est intenable
   avec nos ~2 s de traitement, l'auto-hébergé ne sauvera rien. Le verrouillage ne compte
   pas pour un spike ; la décision d'architecture viendra après, **avec les chiffres**.
2. **Numéro non français** (US ou UK) : pas de bundle ARCEP, pas de Kbis. L'agent parle
   français dessus, seul Geoffrey appelle. En parallèle et hors code : vérifier qu'un
   **SIREN de micro-entreprise** suffirait pour un bundle FR — la troisième voie entre
   « reporter l'administratif » et « monter une société ».
3. **Haiku d'office** pour l'agent, avec un **prérequis bloquant** : rejouer les 42 évals
   en Haiku. Si ce n'est pas 42/42, on en parle avant d'aller plus loin — c'est une donnée
   d'arbitrage, pas un détail d'implémentation.
4. **PAS de streaming des sorties gardées. Décision d'invariant, définitive pour cette
   phase.** Toute sortie passe par `guards.check_output` AVANT d'être prononcée, sans
   exception. La tension que l'état des lieux signalait (règle n°2 contre la latence) est
   donc tranchée **en faveur de la règle**. La réponse à la latence sera : Haiku +
   **phrases-tampons pré-approuvées** (catalogue fermé, prononcées immédiatement pendant le
   calcul du tour) + extension des chemins verbatim. Si le streaming devient un jour
   indispensable, ce sera un chantier « gardes streamables » à part entière, **pas une
   concession arrachée par la latence**.
5. **Le SMS reste chez OVH**, quelle que soit la plateforme voix. Le port `Envoyeur` existe
   pour que cette question ne soit jamais urgente — et c'est la première fois qu'il sert à
   ça, deux jours après avoir été écrit.
6. **`numero_appelant` : gardé pour APRÈS le spike.** Ne toucher ni S4 ni les évals
   maintenant. La trouvaille est valide, mais elle changerait le parcours mesuré.

### Plateforme retenue : Vapi

Motivée sur le seul critère demandé — la facilité d'adaptation à nos webhooks existants — et
la différence est nette :

| | Vapi | Retell |
|---|---|---|
| Contrat attendu | `POST /chat/completions` compatible OpenAI | **WebSocket exclusivement** |
| Streaming obligatoire ? | **Non** : le JSON simple est accepté autant que le SSE | Oui, protocole de messages propre (`response_required`…) |
| État par appel | Aucun côté serveur | **Une connexion ouverte par appel** |

Trois raisons, dans l'ordre :

1. **Le JSON non streamé est accepté.** L'adaptateur reste un simple endpoint HTTP qui
   traduit une requête en forme OpenAI vers nos deux webhooks et rend une réponse JSON.
   Aucun SSE, aucun WebSocket.
2. **Ça colle à la décision n°4.** Un fournisseur qui n'impose pas le streaming n'exerce
   aucune pression sur l'invariant des garde-fous.
3. **Retell rouvrirait une question d'architecture déjà tranchée.** Une connexion par appel
   réintroduit de l'état de process par appel — précisément ce que « un tour = une requête,
   l'état vit en base » a supprimé, et ce que R19 vérifie. On ne défait pas ça pour un spike.

**Le point de conception de l'adaptateur** (à confirmer sur leur documentation au montage) :
la forme OpenAI transporte l'historique complet des messages, tandis que nos webhooks sont
adressés par `appel_id` avec l'état en base. L'adaptateur doit donc faire correspondre un
appel Vapi à un `appel_id` — c'est là que se joue tout son travail, et c'est aussi la réponse
attendue au verdict §1.1.

### Ce que le spike mesurera

Les quatre mesures de l'état des lieux, plus une : le **verdict sur l'hypothèse §1.1**
(webhook JSON tour-par-tour accepté, ou custom LLM streaming exigé), avec la description
précise de ce que l'adaptateur a dû faire. Et la latence ressentie **avec et sans**
phrase-tampon — c'est la seule façon de savoir si les tampons sont une solution ou un
pansement.

Ce que le spike ne prétend pas mesurer, et ne dira pas : robustesse au bruit, tenue sur la
durée, comportement en panne LLM.

### Une correction de harnais au passage

`run_llm_eval.py` charge le `.env` avec `override=True` — délibéré pour la clé API, mais qui
rendait impossible de choisir le modèle de l'agent en ligne de commande : le `.env` du dépôt
force `claude-sonnet-5` et écrasait toute variable d'environnement. Un drapeau `--modele`
écrit la valeur APRÈS le chargement. Comparer deux modèles à énoncé constant est tout
l'intérêt de l'éval ; l'appelant simulé, lui, garde sa propre variable et ne bouge pas.

### Prérequis Haiku : NON RENDU — crédit API épuisé en cours de passage

Le passage des 42 évals en Haiku s'est arrêté sur `Your credit balance is too low` à partir
du 13ᵉ persona. **30 conversations perdues**, pour une cause qui n'a rien à voir avec
l'agent.

Ce qui est mesuré valablement, sur les 12 conversations jouées avant l'épuisement :

| Persona | Haiku |
|---|---|
| T01_urgence_fuite | **1/3** — deux échecs, score 4 au lieu de 5 |
| T02_hors_zone | 3/3 |
| T03_entretien_samedi_prix | 3/3 |
| T05_chasse_au_prix | 3/3 |

**La cause de l'échec T01 est identifiée et instructive.** Haiku classe « une fuite sous
l'évier de la cuisine, ça goutte dans le placard » en `robinetterie` là où Sonnet lit
`fuite`. Or `robinetterie` n'est pas dans `URGENT_PRESTATIONS` : l'`intent` devient
`devis_travaux` au lieu de `urgence`, et le score du lead tombe de 5 à 4. Une erreur de
taxonomie qui cascade jusqu'à la valeur commerciale du lead.

Ce n'est pas un défaut de formulation mais **d'extraction** — et cela suggère une piste que
l'arbitrage n'avait pas envisagée : **les deux appels LLM d'un tour n'ont pas les mêmes
exigences.** L'extraction demande de la justesse, la formulation demande de la vitesse.
Elles utilisent aujourd'hui le même modèle. Un modèle par rôle est une option à mesurer
(sans illusion sur la latence : les deux appels restent séquentiels).

**Le verdict n'est pas rendu** : dix personas sur quatorze n'ont jamais tourné. Rien ne
sera engagé côté Vapi avant un passage complet — d'autant que le spike facturerait les
tokens sur la même clé, et échouerait donc immédiatement de la même façon.

**Ce que cet incident valide au passage** : la résilience du harnais, écrite ce matin après
qu'une coupure réseau avait détruit un passage entier. Les 30 échecs sont marqués
`erreur_harnais`, comptés à part et signalés comme tels — « à ne pas confondre avec un
défaut de l'agent ». Sans cela, l'exception aurait emporté le passage **et** la trouvaille
sur T01.

### Une trouvaille non liée, pertinente pour la voix

En Haiku, l'agent a répondu « Bonjour Mme Garcia ! 😊 ». **Un emoji, dans un appel
téléphonique.** `guards.check_output` filtre les prix hors liste blanche, les « c'est
confirmé » prématurés et les diagnostics improvisés — **rien n'interdit un emoji**, qui
partirait tel quel au TTS. R23 vérifie l'alphabet GSM-7 des SMS, pas celui de la parole.
À traiter avant le spike : c'est une sortie que le garde-fou laisse passer et que la voix
rendra audible.

### 25/08 — pendant l'attente : contrat Vapi et questions OVH

Travail de documentation mené pendant le passage du prérequis Haiku, sans toucher au code.

#### Contrat Vapi — ce qui est ÉTABLI

D'après leur exemple serveur officiel (`server-side-example-python-flask`) :

- **`POST` sur un chemin finissant par `/chat/completions`**, l'URL étant configurée sur
  l'assistant depuis leur tableau de bord (un tunnel suffit en dév — d'où le besoin d'une
  URL HTTPS publique pour le spike).
- Corps **en forme OpenAI**, avec `messages` (l'historique complet) et un booléen `stream`.
- **Le JSON non streamé est bel et bien accepté** : leur propre exemple « basic » rend un
  objet `chat.completion` ordinaire. **C'est le fait qui valide la décision d'invariant n°4**
  — aucune pression du fournisseur sur `guards.check_output`.

#### Contrat Vapi — ce qui reste OUVERT, et qui change le montage

**Leur exemple n'extrait AUCUN identifiant d'appel**, et je n'ai pas pu confirmer dans la
documentation publique que la requête en transporte un. Or nos webhooks sont adressés par
`appel_id` : c'est exactement le point de conception de l'adaptateur signalé dans l'état des
lieux, et il n'est pas tranchable depuis un fauteuil.

**Conséquence : le spike gagne une étape 0** — journaliser la charge utile brute du premier
appel réel, avant d'écrire une ligne d'adaptateur. Deux montages en découlent :

- **s'il y a un identifiant d'appel** : une correspondance `id externe → appel_id`, et
  l'adaptateur reste sans état ;
- **s'il n'y en a pas** : il faut dériver la continuité de l'historique `messages` lui-même,
  ce qui est plus fragile et mérite d'être su AVANT de concevoir.

Écrire l'adaptateur sur une hypothèse serait du travail à refaire. Dix lignes de
journalisation valent mieux qu'une supposition.

#### Questions OVH : deux réponses sur trois

**3. Mécanique de réception — RÉPONDU, et les deux existent.**
- *Pull* : `GET /sms/{serviceName}/incoming`.
- *Push* : un callback configurable via `PUT /sms/{serviceName}`, annoncé comme temps réel.

C'est le **callback** qu'il faudra pour un « OUI » : un pull par cron ferait dépendre la
confirmation du client de la période du cron, exactement le défaut qu'on a corrigé pour le
code de connexion (« un code qui arrive au prochain passage du cron n'est pas un code »).

**2. Le STOP — partiellement répondu, et il soulève un point de conformité que je n'avais
pas vu.** La mention STOP est ajoutée par défaut aux messages SORTANTS, et `noStopClause` la
supprime — c'est ce que notre adaptateur fait déjà (verrouillé par R22). Reste ouvert : un
client qui RÉPOND « STOP », son message arrive-t-il dans `/incoming`, ou OVH l'intercepte-t-il ?

**Ce que la révision OUI/NON change ici, et c'est important** : jusqu'à présent le SMS était
strictement sortant et personne n'était invité à répondre. Désormais **on demande une
réponse** — donc on recevra des STOP, et pas par accident. Le traitement du STOP passe d'une
éventualité théorique à une obligation opérationnelle, à traiter dans la brique de réception
dès sa conception : liste noire locale, et plus aucun envoi ensuite.

**1. Coût des SMS entrants en numéro court — TOUJOURS OUVERT.** Ne se lit pas dans la
documentation publique ; à vérifier dans l'espace client ou auprès du support.

### 25/08 — prérequis Haiku RENDU : 42/42, au prix de trois défauts produit

Trois passages ont été nécessaires. Le premier a été tué par l'épuisement du crédit API, les
deux suivants ont chacun livré des défauts — **tous masqués par Sonnet**, aucun n'étant à
proprement parler une faiblesse de Haiku.

**Verdict : 42/42 en Haiku**, à parité avec Sonnet, et la latence du tour passe de 3,42 s à
1,93 s de médiane. Le prérequis de l'arbitrage est levé.

| | Défaut | Ce que Sonnet masquait |
|---|---|---|
| 1 | L'`intent` était dérivé de la SEULE prestation : `urgence_reelle` était ignorée | Il classait « fuite sous l'évier » en `fuite` ; Haiku dit `robinetterie`, ce qui est défendable — mais hors de `URGENT_PRESTATIONS`, donc le lead plafonnait à 4 |
| 2 | `commune` et `code_postal` pouvaient divergert (« Nogent-sur-Marne / 94000 ») | Il posait `confirme: false` sur les corrections, donc la re-dérivation du CP partait |
| 3 | Une contrainte de dispo TARDIVE faisait sauter des créneaux jamais vus | Rien : ce défaut était indépendant du modèle, il attendait le bon persona |

**Le troisième est le plus grave, et pas pour la raison évidente.** « Je ne suis disponible
que le samedi matin », annoncé après deux créneaux de semaine, faisait sauter les samedis
29/08 et 05/09 pour offrir le 12/09. L'appelant refusait. Mais surtout **l'agent lui laissait
entendre qu'il n'y avait rien le samedi matin**, alors que la config ouvre `sam 09:00–13:00`.
Ce n'est pas un rendez-vous manqué, c'est une information fausse donnée au client sur les
disponibilités de l'artisan.

**Les correctifs, et ce qu'ils disent de la règle n°1.**

- Une **urgence déclarée** promeut l'intent, quelle que soit la prestation — c'est l'appelant
  qui sait si ça coule, pas la nomenclature. Exception : un `devis_*` n'est pas promu, sans
  quoi « un devis PAC, c'est urgent » consommerait la fenêtre d'urgence d'une vraie fuite.
- **`commune` ne s'écrit plus jamais seule** : sans code postal, un nom ne remplit plus le
  slot, il ne sert qu'à la résolution. Les deux valeurs ne s'écrivent que par PAIRE — même
  discipline que « le LLM ne devine jamais un code postal », appliquée à sa réciproque.
- Le **signal de correction** passe du `confirme` du LLM à une détection dans le texte.
  C'était une règle produit confiée à un jugement subtil du modèle : exactement ce que la
  règle n°1 interdit, et un modèle plus faible l'a démontré.
- Le **saut de créneaux** est remis à zéro quand les contraintes changent. `tours_creneaux`
  continue de compter : l'invariant n°6 est intact.

**Deux fois où mes propres tests ont menti**, révélés par mutation et non par relecture :

- le contrôle de cohérence commune/CP donnait un **laissez-passer** au cas qu'il testait —
  avec une commune absente de la table, il n'avait « rien à vérifier » ;
- mon correctif contenait **du code mort**. J'avais placé la promotion d'urgence dans `_s3`
  en croyant couvrir « l'urgence déclarée plus tard ». Or `_s3` ne pose la question d'urgence
  que si l'intent est DÉJÀ « urgence » : l'appel ne pouvait rien faire. Une mutation a
  survécu à un code sans effet — c'est ainsi qu'on l'a su.

**Reste avant d'appeler un vrai numéro** : le garde-fou emoji (`check_output` laisse passer
un 😊 qui partirait au TTS), la ligne `RELAIS_MODEL` du `.env` à retirer, et l'étape 0 du
spike — journaliser la charge utile brute de Vapi avant d'écrire l'adaptateur.

### 25/08 (fin) — garde-fous de prononçabilité, et le formuleur qui mentait

Deux garde-fous et un correctif, tous nés du prérequis Haiku.

#### Une sortie d'agent doit être PRONONÇABLE (R37)

Trouvé pendant le prérequis : l'agent a répondu « Bonjour Mme Garcia ! 😊 ». Au téléphone,
un emoji est soit lu à voix haute de façon absurde, soit avalé. `check_output` filtrait les
prix hors liste blanche, les « c'est confirmé » prématurés et les diagnostics improvisés —
**rien n'interdisait un emoji**. R23 vérifie l'alphabet GSM-7 des SMS, jamais celui de la
parole ; le canal voix allait rendre la faille audible.

Deux détections, deux mécanismes :

- **emoji et pictogrammes**, par CATÉGORIE Unicode `So` plutôt que par liste : la liste
  serait à maintenir à chaque version d'Unicode, la catégorie couvre 😊 ✅ ⚠ 🔧 © et la
  suite ;
- **markdown**, plus fréquent encore (15 répliques sur 214 contre 11 pour l'emoji), et par
  marqueurs de STRUCTURE seulement — `**gras**`, `__souligné__`, titres, liens, `code`.
  Jamais un caractère isolé : « 90 € TTC (\*) » et « Jean_Dupont » doivent passer, et une
  mutation qui élargit la détection à tout astérisque est tuée.

Dans les deux cas : **détecté, pas nettoyé.** `_say` replie sur l'instruction du contrôleur,
et la violation reste visible dans `violations_gardes_fous`. C'est le formuleur qui dérape,
on veut le savoir plutôt que le maquiller.

**Ce que les garde-fous ont attrapé de plus important** : sur `T04_danger_gaz`, le formuleur
a mis en gras le **numéro d'Urgence Sécurité Gaz** (`**0 800 47 33 33**`). Sur la phrase la
plus critique du produit. Intercepté, replié. Ils ont déclenché sur 24 conversations sur 42
— bien plus que les 12 % estimés.

Un filtre que j'avais ajouté a été **retiré** : les sélecteurs de variation et le liant de
largeur nulle. Une mutation y a survécu, et elle avait raison — tout emoji composite
contient déjà un caractère `So`, et un sélecteur isolé est inaudible : le signaler ferait
jeter une bonne réplique pour un caractère invisible.

#### Le formuleur niait les créneaux du contrôleur (R38)

Le défaut le plus grave de la journée. Le contrôleur proposait « samedi 29/08 entre 09h et
11h » — R36 le vérifie — et le formuleur a dit : « Malheureusement, je n'ai pas de
disponibilité le samedi matin en ce moment. » **Il a nié les créneaux qu'on venait de lui
donner.** L'appelant a raccroché sans RDV, avec une information fausse sur les
disponibilités de l'artisan.

`violations_gardes_fous` était **vide**, et ne pouvait pas ne pas l'être : le mensonge
portait sur le FOND, et `check_output` vérifie la forme. Aucun garde-fou n'attrapera jamais
ça. **La seule défense est de ne pas laisser réécrire.**

Or le remède existait déjà, appliqué à un seul endroit : `_reserver` porte `verbatim=True`
avec le commentaire « LA phrase du script : date et engagement jamais réécrits ». **Proposer
une date est le même acte que la confirmer** — la règle valait ici aussi, elle n'avait
jamais été étendue. Exactement le même schéma que la question de prix apprise en S4 et non
propagée à S5 : une leçon juste, appliquée une fois.

Les propositions de créneau et le « rien de plus tôt » sont désormais verbatim. **Effet de
bord bienvenu pour la voix** : un tour verbatim économise l'appel au formuleur — c'est ce
qui explique les minima de latence mesurés, 0,67 s contre 1,93 s de médiane.

#### Deux corrections du HARNAIS sur T07, aucune du produit

- Son attente épinglait `score: 1`, ce qui supposait que l'appelant refuse son numéro — son
  rôle ne le dit nulle part. Quand il l'a donné, le lead est monté à 2 : un **meilleur**
  lead, compté comme un échec. Le score n'est plus épinglé ; `categorie` et `rdv` le sont,
  et le refus de numéro reste couvert par T11.
- Le persona a été durci sur son point non négociable (refuser tout créneau sans garantie de
  gratuité). C'est la **deuxième fois** que T07 dérive faute de contrainte, après la commune
  inventée en Haute-Garonne. Un persona sous-spécifié fabrique de faux défauts.

#### Une question de conception, consignée et NON tranchée

Le contrôleur est **sourd aux questions restées sans réponse**. « Vous me garantissez que je
passe en priorité ? » a reçu pour réponse une proposition de créneau : il n'a aucune notion
de question en suspens, et le formuleur comblait ce vide avec de l'empathie improvisée.

**Le verbatim n'a pas créé cette surdité — il l'a rendue audible.** Si le contrôleur doit
accuser réception, c'est à lui de le faire, avec des phrases que nous écrivons. Cela rejoint
directement les **phrases-tampons** de l'arbitrage voix (décision n°4), qui devront de toute
façon être un catalogue fermé. À traiter là, pas dans un correctif de fin de journée.

#### Et une troisième fois : le raccourci « rien de plus tôt » (R39)

Sixième passage, 41/42. L'appelant : « je ne suis disponible que le samedi matin,
uniquement. C'est possible d'avoir un créneau samedi ? » — donc PLUS TARD. L'agent :

> « Je n'ai malheureusement rien de PLUS TÔT : le premier créneau disponible est DEMAIN
> entre 08h et 10h. »

Deux fautes en une phrase : « plus tôt » à contresens, et le créneau qu'il venait de
refuser reproposé. La branche `veut_plus_tot` se déclenchait AVANT la prise en compte des
contraintes.

Elle existe pour une bonne raison (bug T01/R09-LLM : la cliente voulait plus tôt, on lui
proposait plus tard, et lundi disparaissait). Mais elle ne vaut que si la contrainte n'a
PAS bougé — sinon ce n'est plus un raccourci, c'est une fin de non-recevoir absurde. Les
contraintes sont désormais lues en tête de `_s5`, et une contrainte nouvelle prime.

**Troisième fois de la journée** qu'un contrôleur rendu honnête révèle qu'il disait quelque
chose de faux. Le formuleur maquillait : la question de prix en S5, la surdité aux questions
en suspens, et maintenant ce contresens. **Le verbatim ne crée pas ces défauts, il les rend
audibles** — et c'est un argument de plus pour lui, pas contre.

#### État à la fin de la journée

- **43 PASS** en mock, contrat Postgres vert.
- Dernière mesure réelle : **41/42** au sixième passage, dont l'unique échec est celui que
  R39 corrige — **le correctif n'a pas été rejoué contre le vrai modèle**, relance à faire.
- Six passages du prérequis, chacun a trouvé quelque chose. Le rythme ralentit (les
  derniers échecs étaient des cas à 1 sur 3, sur un seul persona) mais ne s'est pas arrêté.
  Si un septième passage trouve encore un cas rare, c'est un signal en soi : passer à
  `--n 5` sur moins de personas, ou accepter que la queue de distribution se traite en
  production.
