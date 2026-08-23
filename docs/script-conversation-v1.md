# Script de conversation V1 — Agent vocal entrant

**Métier cible : plombier / chauffagiste** · Version 0.1 — 21/08/2026 · Statut : draft à confronter aux interviews

> Principe directeur : l'agent est une **machine à états avec un LLM dedans**, pas une conversation libre.
> Le LLM rend chaque étape naturelle (reformulations, tolérance aux digressions), mais le déroulé,
> les slots à remplir et les garde-fous sont définis ici et appliqués par le code, pas par le prompt.

---

## 0. Contexte d'entrée

L'appel arrive chez nous **uniquement** via le renvoi conditionnel de la ligne de l'artisan
(occupé / pas de réponse / injoignable). L'appelant croyait joindre l'artisan : l'agent doit
immédiatement établir (1) qu'il est au bon endroit, (2) qu'il parle à un assistant IA.

Chaque appel démarre avec en mémoire : `config` (fiche artisan, cf. `config-artisan-v1.md`),
`caller_number` (peut être masqué), date/heure, et l'état `S0`.

---

## 1. Les slots (données à collecter)

La conversation est un remplissage de slots. Un slot peut être rempli à n'importe quel état si
l'appelant donne l'info spontanément — on ne repose JAMAIS une question dont on a déjà la réponse.

| Slot | Type | Obligatoire pour RDV | Exemple |
|---|---|---|---|
| `intent` | enum : `urgence`, `depannage`, `devis_travaux`, `entretien`, `suivi_dossier`, `autre` | oui | fuite → `urgence` |
| `probleme` | texte court structuré (équipement + symptôme) | oui | « chaudière Frisquet, ne démarre plus » |
| `commune` + `code_postal` | texte + CP | oui | « Nogent-sur-Marne 94130 » |
| `urgence_reelle` | bool + justification | oui si `intent=urgence` | eau coupée ? dégât en cours ? |
| `statut_occupant` | enum : `proprietaire`, `locataire`, `syndic/gestionnaire`, `autre` | non (mais pèse au score) | |
| `nom` | texte | oui | |
| `telephone_rappel` | tel FR validé (répété à voix haute) | **oui — jamais de RDV sans** | |
| `disponibilites` | créneaux exprimés par le client | oui | « après 16h en semaine » |
| `acces` | infos utiles (étage, digicode, présence) | non | |
| `photo_ok` | bool — accepte de recevoir un SMS pour envoyer des photos | non (V1.1) | |

**Règle de saturation** : dès que les slots obligatoires sont remplis ET que le lead est en zone,
on passe à la proposition de créneau. On ne « déroule » pas le script pour le plaisir —
un appel efficace dure moins de 3 minutes.

---

## 2. La machine à états

### S0 — OUVERTURE
- **Dire** (≤ 2 phrases, obligation AI Act art. 50 intégrée) :
  > « {config.accueil.formule} » — défaut : « Bonjour, vous êtes bien chez {config.entreprise.nom}.
  > Je suis son assistant vocal — {config.entreprise.prenom_patron} est en intervention,
  > mais je peux tout organiser avec vous. Que se passe-t-il ? »
- **Transitions** : parole détectée → `S1`. Silence > 3 s → relance une fois (« Je vous écoute »),
  silence encore → `S9-REPONDEUR-CHECK`. Détection robot/spam → `S10-SPAM`.

### S1 — COMPRENDRE LE BESOIN
- Objectif : remplir `intent` + `probleme`. Une question ouverte, puis max 2 questions de précision.
- Précisions métier plomberie/chauffage (posées seulement si pertinentes) :
  - fuite → « L'eau coule encore en ce moment ? Vous avez pu couper l'arrivée d'eau ? »
  - chaudière → « Plus de chauffage, plus d'eau chaude, ou les deux ? Vous voyez un code erreur ? »
  - WC/évacuation → « Complètement bouché ou ça s'écoule lentement ? »
  - devis (PAC, chaudière neuve, salle de bain) → pas de diagnostic ; noter le projet et l'échéance.
- **Garde-fou** : l'agent ne donne JAMAIS de conseil technique au-delà de la sécurité de base
  autorisée dans `config.securite.consignes_autorisees` (ex. « coupez l'arrivée d'eau »,
  « si vous sentez le gaz, aérez, ne touchez pas aux interrupteurs et appelez le 0 800 47 33 33 »).
- **Transitions** : `intent` ∈ prestations couvertes (`config.prestations`) → `S2`.
  `intent` hors prestations → `S8-HORS-PERIMETRE`. `intent=suivi_dossier` ou client existant
  mécontent → `S7-TRANSFERT`. Odeur de gaz / danger → consigne sécurité PUIS continuer vers `S2`
  (le RDV reste pertinent) ou `S7` selon `config.securite.transfert_si_danger`.

### S2 — LOCALISER
- « Vous êtes sur quelle commune ? » → vérifier `code_postal` ∈ `config.zone.codes_postaux`.
- **Transitions** : en zone → `S3`. Hors zone → `S8-HORS-ZONE`.
  Zone limitrophe (`config.zone.codes_postaux_limitrophes`) → continuer mais marquer le lead
  `zone=limitrophe` (l'artisan tranchera à la validation).

### S3 — QUALIFIER L'URGENCE ET LE CONTEXTE
- Si `intent=urgence` : établir `urgence_reelle` (dégât en cours ? depuis quand ?).
- `statut_occupant` si naturel de le demander (« C'est votre logement ? »).
- **Tarifs — garde-fou strict** : ne communiquer QUE ce qui est dans `config.tarifs.communicables`
  (ex. « le déplacement + diagnostic est à 90 € TTC, déduit si vous faites les travaux »).
  Toute autre question prix → « Ça dépend de ce que {prenom} constatera sur place,
  je ne veux pas vous annoncer un chiffre faux. » **Jamais d'estimation improvisée.**
- **Transition** : → `S4`.

### S4 — IDENTITÉ ET RAPPEL
- `nom`, puis `telephone_rappel` : **répéter le numéro chiffre par chiffre et faire confirmer**.
  Si le numéro appelant est visible : « Je vous rappelle sur le numéro qui s'affiche, le 06… ? »
- **Transition** : confirmé → `S5`. Refus de laisser un numéro → `S6-SANS-RDV`
  (on ne prend pas de RDV sans moyen de recontact).

### S5 — PROPOSER UN CRÉNEAU
- Appel de l'outil `calendar.get_slots(intent, commune, duree_estimee)` qui applique les règles
  de `config.agenda` (durées par type, buffers trajet, fenêtres d'urgence, limites journalières).
- **Dire** : proposer **au maximum 2 créneaux** à la fois (« Je peux vous proposer demain entre
  14h et 16h, ou vendredi matin entre 8h et 10h »). Toujours en **fenêtres**, jamais en heure pile.
- Si urgence et fenêtre d'urgence disponible aujourd'hui → la proposer en premier.
- Si aucun créneau ne convient après 2 tours de propositions → `S6-SANS-RDV` (lead chaud à rappeler).
- **Formulation de conclusion — LA phrase la plus importante du script** (statut provisoire,
  cohérent avec le flow de validation « expiration + repli ») :
  > « Parfait, je vous **réserve** demain entre 14h et 16h. Vous recevrez un **SMS de confirmation**
  > de {prenom} d'ici {config.validation.delai_max_heures} heures. Si quoi que ce soit coince,
  > on vous rappelle au 06… »
  — Ni « c'est confirmé » (l'artisan peut refuser), ni « on vous rappellera » (c'est le problème
  qu'on résout). Le créneau est **bloqué** dans le calendrier tampon dès cet instant.
- **Transition** : → `S11-CLOTURE`.

### S6 — SANS-RDV (repli propre)
- Cas : refus de numéro, aucun créneau compatible, client veut « juste parler au patron ».
- **Dire** : « Je transmets tout ça à {prenom} dès qu'il sort d'intervention, il vous rappelle
  {aujourd'hui avant X h / demain matin} » — la promesse de délai vient de
  `config.accueil.promesse_rappel`, jamais improvisée.
- Lead créé quand même, marqué `a_rappeler`, avec tout ce qui a été collecté. → `S11`.

### S7 — TRANSFERT HUMAIN
- Déclencheurs : client existant avec litige/mécontentement, danger si configuré, demande explicite
  et insistante d'un humain (après une tentative de reprise), sujet hors script (facturation, RH…).
- Si `config.transfert.actif` et dans les horaires : tentative de mise en relation
  (« Je regarde si je peux vous le passer, un instant »). Échec ou hors horaires → `S6` avec
  marquage `prioritaire`.

### S8 — HORS-ZONE / HORS-PÉRIMÈTRE
- Poli, court, honnête : `config.zone.message_hors_zone` si rempli, sinon défaut :
  « {config.entreprise.nom} n'intervient pas à {commune} / ne fait pas ce type de travaux,
  je suis désolé. » Si `config.prestations.confreres_recommandation` est rempli, le donner.
- Lead créé avec score 0 (l'artisan voit ce qu'il refuse — donnée précieuse pour lui et pour nous). → `S11`.

### S9 — RÉPONDEUR-CHECK
- Silence persistant ou détection de messagerie (bip). Un message unique :
  « Vous avez appelé {config.entreprise.nom}. Rappelez-nous ou envoyez un SMS à ce numéro,
  nous revenons vers vous rapidement. » → fin, lead `appel_muet` avec `caller_number` si visible.

### S10 — SPAM / ROBOT / DÉMARCHAGE
- Détection : discours commercial sortant, robocall, silence + musique.
  « Nous ne sommes pas intéressés, bonne journée. » → fin. Lead score 0, catégorie `spam`
  (n'apparaît que dans le compteur, pas dans la liste des leads).

### S11 — CLÔTURE
- Récapitulatif en 1 phrase (besoin + créneau ou promesse de rappel), remerciement, fin d'appel.
- Post-appel (pipeline, hors conversation) : transcript + slots → création du lead → **scoring**
  → si RDV : blocage du créneau tampon + notification push à l'artisan → minuterie
  `config.validation.delai_max_heures`.

---

## 3. Scoring du lead (calculé post-appel, pas pendant)

| Score | Critères |
|---|---|
| 0 | Hors zone, hors périmètre, spam |
| 1 | Demande d'info sans projet, pas de coordonnées |
| 2 | Projet flou, pas d'échéance, coordonnées OK |
| 3 | Besoin réel identifié, en zone, coordonnées OK, pas de RDV pris |
| 4 | Besoin précis + RDV réservé (en attente de validation) |
| 5 | Urgence réelle + RDV réservé + coordonnées complètes |

Chaque score est accompagné des **raisons affichables** (« Fuite active · Créteil · propriétaire ·
dispo 14h–18h ») — c'est la carte lead du dashboard, pas un chiffre nu.

## 4. Flow de validation « expiration + repli » (décision produit du 21/08)

1. RDV réservé → créneau bloqué dans le **calendrier tampon** → push à l'artisan.
2. L'artisan **valide** (1 tap) → événement écrit dans son calendrier perso → SMS de confirmation
   au client → rappel SMS à J-1 (ou H-2 pour une urgence). Il peut aussi **modifier** (nouveau
   créneau → SMS « finalement, {prenom} vous propose plutôt… ») ou **refuser** (SMS + lead repasse
   `a_rappeler`).
3. **Pas de réponse après le délai** (`delai_max_heures`, défaut 24 h ; `delai_max_urgence_heures`, défaut 2 h ;
   `base_delai` = reelles|ouvrees, l'urgence toujours en heures réelles) :
   SMS de repli au client (« {prenom} vous rappelle très vite pour fixer l'horaire exact »),
   le créneau tampon est libéré, le lead passe en **alerte prioritaire** rouge sur le dashboard
   et déclenche une relance push + SMS à l'artisan.

## 5. Invariants (à faire respecter par le code, pas par le prompt)

1. L'agent s'annonce comme assistant IA dans les 5 premières secondes (AI Act art. 50).
2. Aucun RDV sans `telephone_rappel` confirmé.
3. Aucun prix hors `config.tarifs.communicables`. Aucun diagnostic technique.
4. Aucune promesse de délai hors `config.accueil.promesse_rappel` / créneaux calendrier.
5. Jamais « confirmé » avant validation artisan ; jamais « on vous rappellera » quand un créneau existe.
6. Max 2 créneaux proposés par tour, max 2 tours.
7. Toute demande client de parler à un humain, réitérée une fois → `S7`, sans négocier.
8. Durée d'appel cible < 3 min ; > 6 min → l'agent conclut vers `S6` proprement.
9. Chaque appel produit un lead tracé : horodatage, source, transcript, consentement implicite
   (demande entrante) — base légale loggée (loi du 11/08/2026).

## 6. À confronter aux interviews (questions ouvertes)

- Q17 → le délai de validation par défaut (4 h) et l'éventuelle auto-validation des urgences.
- Q10/Q11 → faut-il un mode « sans calendrier connecté » (calendrier 100 % chez nous) pour les
  artisans papier ? (probable : oui, et c'est plus simple techniquement pour la bêta)
- Q13 → les durées types et la gestion du trajet (buffer fixe vs zones)
- La formule d'ouverture : « assistant » vs « secrétariat » vs prénom donné à l'agent — à A/B tester.
