# Relais — point d'étape au 24/08/2026

> Document **autonome** : écrit pour être lu ou collé hors du dépôt (Claude Desktop, un
> tiers, soi-même dans trois semaines). Le journal de bord détaillé est `docs/journal.md`.

## Le produit en trois phrases

Un agent IA répond aux appels manqués des artisans (renvoi conditionnel de leur ligne),
qualifie la demande au téléphone, et réserve un créneau. L'artisan **valide en un tap**
avant que le client reçoive sa confirmation par SMS — l'agent ne confirme jamais seul.
Cible V1 : plombiers-chauffagistes en France. Équipe : Geoffrey (dev + produit, en binôme
avec Claude), son cousin au marketing (interviews terrain en cours).

## Où on en est vraiment

**La chaîne complète fonctionne, sauf la voix.** Concrètement, aujourd'hui :

un appel entre par HTTP → l'agent mène la conversation (machine à états déterministe, le
LLM n'extrait et ne formule que) → un lead scoré 0–5 est produit → un créneau est bloqué en
tampon → l'artisan ouvre une page web sur son téléphone et valide, refuse ou repropose →
le client reçoit un SMS avec un lien à un tap → s'il ne se passe rien avant l'échéance, un
worker libère le créneau, prévient le client et relance l'artisan.

Tout ça tourne contre un vrai Postgres (Supabase, région UE) et est couvert par
**29 tests** rejouables en 3 secondes sans clé API ni base.

**Ce qui est encore simulé, et pourquoi ce n'est pas caché :**

| Brique | État | Ce qui manque |
|---|---|---|
| Voix | ❌ absente | aucune plateforme vocale, aucun numéro. Les webhooks qu'elle appellera existent déjà |
| SMS | ⚠️ partiel | ça part **réellement** (premier SMS reçu le 24/08), mais via un numéro court qui **bloque les URL** — donc le lien de validation ne peut pas encore passer |
| Calendrier | ⚠️ simulé | les vraies règles d'agenda sont appliquées, mais reliées à aucun Google/Outlook |
| Push | ❌ absent | la relance artisan est mise en file, jamais délivrée |
| Compte artisan | ⚠️ provisoire | connexion par jeton collé dans un champ ; doit devenir un code reçu par SMS |

## Ce qui bloque, et sur quoi

Trois choses, dont **deux ont un délai externe** — c'est le point important pour décider de
l'ordre des travaux :

1. **Sender ID SMS** (`DupontChauf`) : ~72 h de déclaration, avec un risque de refus. Tant
   qu'il n'est pas validé, on reste sur un numéro court qui bloque les URL — donc le
   parcours client à un tap ne peut pas être testé en vrai. **L'attente court en arrière-plan
   dès qu'on la lance.**
2. **OAuth Google Calendar** : délai de vérification également. Même logique.
3. **Plateforme vocale** : pas de délai imposé, mais une décision structurante non prise.

## Les décisions ouvertes qui méritent une discussion

**A. Plateforme vocale — la vraie décision non prise.** Les plateformes managées (Vapi,
Retell) fournissent leurs propres numéros ou s'intègrent en trunk SIP. Décidé jusqu'ici :
*ne pas* prendre de numéros chez un opérateur avant d'avoir choisi la plateforme, sinon on
crée une double tuyauterie à réconcilier. Reste à trancher : managé (rapide, dépendance
forte, coût à la minute) contre assemblage maison (contrôle, latence maîtrisée, beaucoup
plus de travail). C'est la décision qui conditionne le plus la suite.

**B. Fournisseur SMS.** Choix ouvert et **réversible** — tout passe par un port unique, donc
en changer coûte un adaptateur. Le seul besoin depuis qu'on est passé au lien : envoyer un
SMS transactionnel vers un mobile FR avec un sender ID alphanumérique déclaré. Critère de
choix retenu : la qualité du processus de déclaration du Sender ID, plus DPA et hébergement
UE. Candidats jugés équivalents : OVHcloud (en place), LinkMobility, Octopush, SMSFactor,
Brevo.

**C. Comment l'artisan se connecte.** Le mobile *est* l'identité professionnelle de
l'artisan, et le canal SMS existe déjà — un code par SMS est le candidat naturel. Question
de coût par contre : chaque connexion consomme un crédit.

**D. Ce qui vient après la validation à un tap.** La brique produit centrale marche. La
suite naturelle serait le vrai calendrier (le créneau proposé au client devient un créneau
réellement libre), mais ce n'est pas la seule option — le terrain dira peut-être autre chose.

## Ce qui est déjà tranché (à ne pas rouvrir sans raison neuve)

- **Le LLM ne décide jamais.** Transitions, prix, créneaux et promesses viennent du
  contrôleur et de listes blanches de config. Le LLM extrait et formule, c'est tout.
- **L'artisan valide toujours.** Pas d'auto-validation en V1, même sur un lead noté 5/5.
- **SMS strictement sortant**, « Répondez OUI » remplacé par un lien à un tap. Motif
  vérifié : les numéros mobiles FR sont interdits à l'A2P, le bidirectionnel imposerait un
  numéro `09 3X`, et la Charte AF2M du 1er mars 2026 durcit le cadre. Le lien supprime le
  numéro dédié et toute la conformité entrante.
- **Délais de validation : 24 h en temps normal, 2 h en urgence**, réglables par artisan.
  Le défaut est venu du terrain : la plupart des artisans ne regardent leur application que
  le soir, un délai de 4 h expirait pendant qu'ils étaient sur chantier.
- **L'échéance fait foi, pas le passage du worker.** Valider une seconde trop tard est
  refusé — sinon la décision de l'artisan dépendrait de la latence d'un cron.
- **Annonce IA en ouverture** (AI Act art. 50) et **téléphone confirmé avant tout RDV** :
  intouchables.
- **Le temps** (tranché ce 24/08) : un horodatage est un instant en UTC, une heure écrite en
  config est une heure de pendule lue dans le fuseau de l'artisan. Ça paraît technique, mais
  ça portait une vraie promesse produit : sans ça, deux heures par an, un artisan pouvait se
  voir refuser une validation faite dans les temps.

## Si tu ne dois retenir qu'une question

**Faut-il lancer maintenant les deux démarches à délai externe (Sender ID + OAuth Google),
et coder autre chose pendant qu'elles mûrissent — ou trancher d'abord la plateforme vocale,
qui est la décision la plus structurante et qui pourrait rendre une partie du reste
caduque ?**
