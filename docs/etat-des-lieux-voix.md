# Chantier VOIX — état des lieux

> Document d'ARBITRAGE, écrit le 25/08/2026. Il n'engage aucun choix et ne propose aucune
> implémentation. Il dit ce qui existe, ce qui manque, ce qui est mesuré et ce qui ne l'est
> pas. Les chiffres marqués « ⚠ à vérifier » viennent de recherches du jour et doivent être
> reconfirmés auprès des fournisseurs avant tout engagement.

---

## 0. La trouvaille qui devrait ouvrir l'arbitrage

**Un numéro de téléphone français exige un Kbis et une pièce d'identité du dirigeant** —
c'est le « regulatory bundle » que les opérateurs (Twilio et les autres) constituent pour
l'ARCEP, qui audite l'usage des numéros pour limiter les abus de campagnes d'appels.

Or la décision du jour est de **reporter l'administratif** (Sender ID, structure, Kbis)
tant que le produit n'a pas prouvé sa valeur. Cette décision a bien libéré le SMS : la
révision OUI/NON supprime la dernière dépendance au Sender ID. **Mais elle ne libère pas la
voix** — le même Kbis reparaît immédiatement, et cette fois pour le point d'entrée du
produit.

Conséquence à intégrer au raisonnement, pas à trancher ici : soit l'administratif redevient
prioritaire, soit **le premier spike se fait sur un numéro NON français** (voir §4).

---

## 1. Ce qui existe déjà côté voix

### 1.1 Le webhook d'appel entrant — contrat exact

Deux routes, protégées par un **secret partagé** en en-tête `X-Relais-Secret` (porte
distincte de celle de l'app artisan, qui utilise un jeton porteur ou un cookie).

| | |
|---|---|
| `POST /webhooks/appel` | `{numero_appele, numero_appelant?}` → `{appel_id, texte, termine}` |
| `POST /webhooks/appel/{id}/tour` | `{texte}` → `{appel_id, texte, termine, rdv_id?}` |

**C'est l'artisan qui est identifié par le numéro APPELÉ**, jamais par un jeton : mettre un
secret par artisan dans la configuration d'un fournisseur de voix serait le mauvais
périmètre.

- **Testé avec :** R19 (mock + câblage réel sur Supabase). Un tour = une requête, aucun
  état en mémoire de process — l'état conversationnel est relu et réécrit en base à chaque
  tour, donc plusieurs process derrière un répartiteur fonctionnent déjà.
- **Hypothèse non confrontée au réel :** que la plateforme vocale sache appeler un webhook
  **requête/réponse JSON, un tour à la fois**. Les plateformes managées attendent en général
  un « custom LLM » compatible OpenAI **en streaming** (SSE). ⚠ à vérifier plateforme par
  plateforme — c'est peut-être le principal travail d'adaptation.

### 1.2 Un trou déjà visible : `numero_appelant` est reçu et jeté

Le champ existe dans le contrat (`api.py`) et **n'est utilisé nulle part**. Or la
téléphonie nous donnera le numéro de l'appelant gratuitement, alors que la machine à états
consacre **deux à trois tours** (S4) à le demander, le répéter et le faire confirmer.

Ce n'est pas qu'une économie de tours : c'est la partie de la conversation où l'on perd le
plus d'appels (invariant « pas de RDV sans téléphone confirmé », personas T09/T11). À
étudier lors du raccordement — avec la nuance que le numéro présenté n'est pas toujours
celui où le client veut être rappelé, et qu'il peut être masqué.

### 1.3 La machine à états S0–S11 — ce qu'elle suppose du canal

| Hypothèse | État réel |
|---|---|
| **Un tour = une phrase complète** de l'appelant | Vrai en texte. En voix, il faut une détection de fin de tour ; un appelant qui hésite au milieu d'une phrase produirait deux tours |
| **Pas de barge-in** : l'agent parle, puis écoute | Rien dans le code ne gère l'interruption. Un appelant qui coupe l'agent n'est pas modélisé |
| **Le silence est un signal** | Géré : `process("")` → « Je vous écoute ? », puis S9 répondeur et clôture. **Mais jamais testé en éval** — le harnais lit une réplique vide comme une fin d'appel |
| **La latence est tolérable** | Voir §1.5. C'est le point dur |
| **Les phrases critiques sont verbatim** | `_say(verbatim=True)` : la réservation et les promesses de délai ne passent PAS par le formuleur. Utile en voix — ce sont aussi les tours les plus rapides |

Six issues possibles (`categorie`) : `rdv_reserve`, `hors_zone`, `prioritaire`,
`a_rappeler`, `hors_perimetre`, `appel_muet`. **Cinq sont couvertes par l'éval ; seule
`appel_muet` ne l'est pas** — et c'est précisément l'issue la plus liée au canal voix.

### 1.4 MockLLM et les évals

- **`run_llm_eval.py`** : 14 personas × 3 = 42 conversations, **42/42** au 25/08. Un
  appelant simulé (LLM) contre l'agent, **en texte pur**.
- **`MockLLM`** : extraction par règles, sans réseau. Double de test **et** chemin de
  dégradation en production.
- **Hypothèse non confrontée :** l'appelant simulé écrit un français **propre et écrit**.
  La voix apportera des transcriptions avec hésitations, mots coupés, chiffres en toutes
  lettres, homophones. Les cinq bugs du 25/08 sont tous venus de tournures orales
  auxquelles personne n'avait pensé — et c'était encore du texte bien formé.
- Le harnais sait vérifier **ce que l'agent a dit** (`texte_agent`), ce qui servira pour les
  consignes de sécurité prononcées à l'oral.

### 1.5 ⏱ La latence : mesurée, pas supposée

Mesure du jour, sur un tour complet du contrôleur (extraction + décision + formulation),
**hors STT et hors TTS** :

| Modèle de l'agent | min | **médiane** | max |
|---|---|---|---|
| `claude-sonnet-5` | 1,51 s | **3,42 s** | 4,99 s |
| `claude-haiku-4-5` | 0,67 s | **1,93 s** | 2,37 s |

Les minima correspondent aux tours **verbatim** (une seule requête au lieu de deux).

**Pourquoi deux requêtes par tour :** le LLM extrait, **puis** le contrôleur décide, **puis**
le LLM formule. C'est la règle n°1 du projet — le LLM ne décide jamais — et elle impose un
aller-retour supplémentaire. Ce n'est pas une inefficacité à corriger, c'est le prix d'un
invariant produit. L'arbitrage doit le savoir.

**Ordre de grandeur du budget voix :** une conversation naturelle supporte mal plus de
**0,5 à 1 seconde** de blanc. Le seul traitement texte consomme donc déjà **2 à 3,5×** le
budget total, avant d'ajouter STT et TTS.

Pistes à explorer (non tranchées) : passer l'agent en Haiku ; étendre les chemins verbatim ;
émettre un son d'attente pendant le calcul ; commencer la synthèse avant la fin de la
génération. La première est gratuite et divise la latence par deux.

### 1.6 La config artisan

- **Fonctionnel :** liste blanche de prix (S3), zone et table communes→CP (1 504 communes
  d'Île-de-France, avec une liste d'homonymes exclus), horaires et fenêtres d'urgence,
  délais de validation, consignes de sécurité en catalogue fermé.
- **Le numéro Relais** vit dans la table `artisan` (migration 008), pas dans la config.
- ⚠ **Le bloc `telephonie` de la spec n'existe pas dans la config réelle.**
  `docs/config-artisan-v1.md` définit `numero_artisan`, `numero_agent`, `renvoi_verifie` —
  `config/dupont.json` n'en contient rien. **Le renvoi conditionnel n'est donc modélisé
  nulle part**, alors que c'est le mécanisme qui amène l'appel jusqu'à nous.
- **`transfert.cible`** existe et sert déjà (S7), mais le transfert **échoue toujours** :
  c'est un prototype qui marque le lead prioritaire au lieu de transférer.

---

## 2. Ce qui manque, en trois couches

### a) Téléphonie

1. **Un numéro** joignable — et donc le bundle réglementaire (§0).
2. **Le renvoi conditionnel** de la ligne de l'artisan vers ce numéro : c'est une
   manipulation à faire **chez son opérateur à lui**, pas chez nous. Non modélisé, non
   documenté, jamais testé. La spec prévoit un `renvoi_verifie: true` à l'onboarding
   (« appel test ») qui n'existe pas.
3. **Le décrochage** et la fin d'appel : qui raccroche, quand, et que fait-on d'un appel
   coupé au milieu (l'état est en base, mais aucun worker ne clôture un appel abandonné).
4. **Le transfert réel** (S7), aujourd'hui simulé.

### b) Temps réel voix

1. **STT en flux**, français, robuste au bruit de chantier et aux numéros dictés.
2. **TTS** : voix, débit, et surtout la lecture correcte des créneaux et des numéros.
3. **Tours de parole** : détection de fin d'énoncé, gestion des hésitations.
4. **Barge-in** : l'appelant coupe l'agent. Non modélisé du tout.
5. **Le son d'attente** pendant le calcul (§1.5).

### c) Raccordement à l'existant

C'est ici que se joue la question « adapter ou remplacer ».

- **Option adapter :** la plateforme fait STT/TTS et appelle nos webhooks avec du texte.
  L'architecture actuelle tient telle quelle — un tour = une requête, l'état est en base.
  Coût : un adaptateur si la plateforme exige un format « custom LLM » compatible OpenAI en
  streaming (⚠ à vérifier).
- **Option remplacer :** on tient la boucle temps réel nous-mêmes et le webhook actuel
  disparaît. Beaucoup plus de travail, et cela réduirait à néant la valeur de R19.
- **Question ouverte à trancher plus tard :** faut-il exposer le contrôleur en **streaming**
  pour émettre les premiers mots avant la fin du calcul ? Cela toucherait `_say` et la
  garantie que **toute sortie passe par `guards.check_output`** (règle n°2) — on ne peut pas
  vérifier un texte qu'on a déjà commencé à prononcer. **C'est une tension d'invariant, pas
  un détail technique.**

---

## 3. Les options de plateforme (aucune n'est recommandée ici)

⚠ Tous les chiffres ci-dessous datent du 25/08/2026 et proviennent de comparatifs publics ;
aucun n'a été vérifié auprès du fournisseur. Ils servent à cadrer un ordre de grandeur, pas
à décider.

| | Managé (Vapi, Retell) | Cadre auto-hébergé (LiveKit Agents, Pipecat) |
|---|---|---|
| **Prix/min** | Vapi : 0,05 $ d'orchestration, **0,13–0,32 $ tout compris**. Retell : 0,07 $+, **0,11–0,15 $** en pratique | Coût des briques uniquement (STT + TTS + LLM + trunk SIP) + infrastructure |
| **Numéros FR** | Fournis ou via trunk SIP — dans les deux cas le bundle ARCEP s'applique | À contracter séparément chez un opérateur |
| **Latence** | Optimisée par le fournisseur ; ⚠ non mesurée par nous | Contrôle total du pipeline, c'est l'argument principal de Pipecat |
| **Verrouillage** | Fort : la logique de tours, le SIP et les numéros vivent chez eux | Faible : Apache 2.0, on héberge |
| **Testable sans engagement** | Oui, en self-serve, à la minute | Oui, en local, **sans numéro** — c'est le point important |

**Ce qui est réellement testable sans rien signer :** un cadre auto-hébergé se lance en
local et permet de mesurer STT/TTS français et la latence du pipeline **avant** d'avoir un
numéro. Une plateforme managée demande un compte mais reste facturée à la minute.

**Lien avec la révision SMS OUI/NON :** le SMS entrant devient une brique du système. Si la
plateforme voix retenue fournit des numéros **SMS-capables**, la question « réponses via OVH
ou via la plateforme voix » se posera.

- **Managé** : un seul fournisseur pour la voix et le SMS — moins de tuyauterie, mais le
  verrouillage porte alors sur les deux canaux à la fois, et le port `Envoyeur` (qui rend le
  fournisseur SMS interchangeable) perdrait son intérêt.
- **Auto-hébergé** : la voix et le SMS restent indépendants ; OVH continue de servir le SMS,
  qui fonctionne déjà et dont l'adaptateur est écrit et testé.
- Dans les deux cas, **la réception SMS reste à construire** (§ révision produit) : c'est le
  pendant entrant du worker sortant, et il n'existe pas.

---

## 4. Le spike minimal proposé

**Objectif, et rien d'autre :** appeler un vrai numéro et entendre l'agent dérouler S0→S2
sur un cas simple. **Ce n'est pas le produit** — c'est la mesure de deux chiffres qui
décident de tout le reste : la **latence bout-en-bout ressentie** et le **coût par minute
réel**.

**Le geste qui débloque tout : faire ce premier spike sur un numéro NON français.** Un
numéro américain ou britannique s'obtient sans bundle ARCEP, donc **sans Kbis** — et
l'agent peut parfaitement parler français dessus. Cela permet de mesurer la latence, la
qualité du STT/TTS français et le coût **avant** de rouvrir le dossier administratif. Seul
Geoffrey appellera ce numéro pendant le spike ; le surcoût d'un appel international pour un
test ne pèse rien.

**Périmètre volontairement pauvre :**

1. Un numéro non français chez une plateforme managée (self-serve, à la minute).
2. Un adaptateur qui traduit ses appels vers les **webhooks existants** — `POST
   /webhooks/appel` puis `/tour`. Rien à changer dans le moteur.
3. L'agent en **Haiku** (latence divisée par deux, §1.5).
4. Un seul scénario : « j'ai une fuite » → commune → première question de qualification.
   S0→S2, pas plus.

**Ce qu'on mesure, et les seuils qui feraient renoncer :**

| Mesure | Question posée |
|---|---|
| Latence perçue entre la fin de la phrase du client et le début de la réponse | Est-ce tenable sans son d'attente ? Avec ? |
| Coût par minute réel | L'ordre de grandeur du §3 se confirme-t-il ? |
| Qualité du STT français sur un numéro dicté et une commune | Combien de reprises ? |
| Barge-in | Que se passe-t-il si on coupe l'agent ? |

**Ce que le spike ne dit PAS et ne doit pas prétendre dire :** la qualité de la conversation
sur la durée, la robustesse au bruit, ni le comportement en cas de panne LLM.

**Ce qu'il faut décider AVANT de le lancer** (et que ce document ne tranche pas) : managé ou
auto-hébergé pour le spike — sachant qu'un spike managé mesure vite mais mesure *leur*
pipeline, et qu'un spike auto-hébergé mesure le nôtre mais demande plus de travail avant le
premier son.

---

## Sources externes consultées le 25/08/2026

- [Voice AI Pricing Per Minute 2026 — Vapi, Retell, ElevenLabs, Twilio](https://caller.digital/voice-ai-pricing-comparison)
- [AI Voice Agent Pricing 2026 : 10 plateformes comparées](https://www.famulor.io/blog/ai-voice-agent-pricing-2026-what-10-platforms-actually-cost-per-minute)
- [Comment obtenir des numéros de mobile français sur Twilio](https://fr.linkedin.com/pulse/comment-obtenir-des-num%C3%A9ros-de-mobile-fran%C3%A7ais-sur-twilio-rudy-som)
- [France Phone Numbers — Twilio](https://www.twilio.com/en-us/legal/service-country-specific-terms/france-phone-numbers)
- [Plan de numérotation — Arcep](https://www.arcep.fr/actualites/actualites-et-communiques/detail/n/plan-de-numerotation-021225.html)
- [Voice AI agents in production 2026 : LiveKit Agents, OpenAI Realtime, Pipecat, Vapi, Retell](https://www.reactify-solutions.com/articles/voice-ai-agents-production-2026)
- [Vapi vs Pipecat vs LiveKit : quel cadre en 2026 ?](https://inworld.ai/resources/vapi-vs-pipecat-vs-livekit)
