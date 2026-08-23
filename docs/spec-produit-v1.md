# Relais — Spécification produit

v0.2 — 22/08/2026 · v0.1 rédigée par Claude ; v0.2 intègre les arbitrages de Geoffrey
(appels sortants exclus, renégociation d'horaire par SMS bidirectionnel, app mobile + site,
annulation/modification de RDV par le client = exigence V1).
Légende : ✅ construit (prototype) · 🔜 à construire · ❓ hypothèse jamais tranchée — à valider.

---

## 1. Ce que c'est (une phrase)

**Relais répond aux appels que l'artisan rate, qualifie le prospect, et remplit son agenda —
chaque rendez-vous étant validé par l'artisan en un tap avant d'être confirmé au client par SMS.**

Ce n'est PAS : un logiciel de gestion BTP (devis/factures/planning chantier — Obat, Tolteck),
un CRM généraliste, ni un « standard téléphonique IA » générique. L'obsession unique :
**transformer les appels ratés en chiffre d'affaires**, et le prouver.

## 2. Pour qui

- **Client** : artisan du bâtiment, d'abord **plombiers/chauffagistes** France. Sweet spot :
  patron + 0 à 10 personnes, sans secrétariat dédié, qui rate des appels parce qu'il est
  sur chantier. Élargissement ensuite : électriciens, clim/PAC.
- **Utilisateur final indirect** : le particulier qui appelle (il ne choisit rien, mais
  l'expérience doit être assez bonne pour qu'il ne raccroche pas).
- ❓ Les entreprises AVEC secrétaire : discours « niveau 1 IA / niveau 2 humain » évoqué
  en amont-projet, jamais spécifié. V2 ?

## 3. Le mécanisme central

1. L'artisan garde son numéro. Il active un **renvoi conditionnel** (occupé / non-réponse /
   injoignable) vers le numéro Relais qui lui est attribué. 🔜 (attribution des numéros,
   vérification du renvoi à l'onboarding)
2. L'agent IA décroche, **s'annonce comme assistant** (AI Act art. 50), qualifie :
   besoin → commune/zone → urgence → identité + téléphone confirmé → créneau. ✅ (texte) / 🔜 (voix)
3. Le créneau est **réservé provisoirement** dans un calendrier tampon (jamais « confirmé »
   au client). ✅
4. L'artisan reçoit une **notification push** (app mobile) et **valide / modifie / refuse
   en 1 tap**. 🔜
5. Validation → écriture dans son calendrier perso + **SMS de confirmation** au client
   + rappel J-1 (H-2 si urgence). 🔜
5bis. **Modification d'horaire par l'artisan** (décision 22/08, **flux révisé le 23/08**) :
   l'artisan propose un autre créneau depuis l'app → SMS au client : « {Prénom} vous
   propose plutôt {créneau}. Si cela vous convient, validez ici : {lien} » → le client
   valide **d'un tap**, l'artisan est prévenu. ✅ construit (§3.5bis = `POST /rdv/{id}/reproposer`
   puis `GET|POST /c/{jeton}`).
   **Le « Répondez OUI » est abandonné** : les opérateurs français réservent les numéros
   mobiles au P2P (interdits à l'A2P), le SMS bidirectionnel exigerait un numéro `09 3X`
   dédié, et la Charte Business Messaging de l'AF2M du 1er mars 2026 durcit la validation
   des Sender ID. Le lien supprime le numéro dédié, la conformité entrante et toute la
   brique « lecture des SMS reçus ». Un tap vaut mieux qu'un mot à taper.
   ❓ restent à trancher : relance si le client ne valide pas (aujourd'hui : l'échéance
   court et le repli d'expiration s'applique), et cas du client sans data mobile.
6. **Expiration** (4 h ouvrées / 1 h urgence, configurable) sans réponse artisan → SMS de
   repli au client, créneau tampon libéré, lead en alerte rouge, relance artisan. ✅ (logique) / 🔜 (SMS réels)
7. Chaque appel produit un **lead scoré 0–5** avec raisons affichables + transcript. ✅

## 4. Les canaux d'entrée

- **Téléphone (appels ratés)** : le canal V1. ✅ logique conversationnelle / 🔜 voix + téléphonie réelles.
- **SMS entrants : ABANDONNÉS en V1** (décision 23/08, revient sur le 22/08). Le SMS est
  strictement **sortant** : les validations passent par un lien (§3.5bis), ce qui évite le
  numéro `09 3X` dédié et la conformité entrante. ❓ Les SMS spontanés d'un prospect au
  numéro Relais restent une question ouverte — sans objet tant qu'on n'a pas de numéro
  capable d'en recevoir.
- 🔜 V1.1 : **formulaire du site** de l'artisan → même pipeline de qualification, mêmes leads.
- **Email entrant : à réfléchir** (décision 22/08 — ni engagé ni exclu).
- ❓ WhatsApp : évoqué au tout début, jamais re-discuté. V2+ ?
- **Appels SORTANTS : EXCLU** (décision 22/08) — cadre légal trop instable (loi 11/08/2026
  et suites) et risque disproportionné. L'agent ne compose JAMAIS un numéro. Les relances
  passent par SMS (canal transactionnel d'une demande entrante) et par l'artisan lui-même.

## 5. L'agent conversationnel (le cœur — construit en prototype texte)

Architecture « le code sait, le LLM comprend » : ✅
- Contrôleur déterministe : machine à états S0–S11, remplissage opportuniste de slots,
  transitions décidées par le code. Le LLM ne décide jamais.
- LLM extracteur (avec contexte des propositions en cours) + LLM formuleur.
- Phrases critiques en **verbatim** : réservation, promesse de rappel, répétition du numéro.
- **Garde-fous en code** sur chaque sortie : prix = liste blanche uniquement, jamais de
  diagnostic, jamais « confirmé », promesses bornées à la config. Violation → repli sûr + log.
- **Dégradation gracieuse** : LLM/réseau en panne → mode scripté, l'appel aboutit quand même.
- Résolution **commune → CP** : table zone artisan + base officielle Île-de-France
  (1 504 entrées, multi-CP, Paris par arrondissement). Le LLM n'a pas le droit de deviner un CP.
- Comportements spécifiés : question-prix ≠ refus, « plus tôt ? » ≠ rejet, correction de
  numéro/commune en cours d'appel, consignes sécurité (fuite, gaz) en catalogue fermé,
  demande d'humain → 1 reprise puis transfert, répondeur/spam/silence, disponibilités
  exprimées respectées (« que le samedi matin »).
- **Config artisan = tout ce que l'agent sait** (docs/config-artisan-v1.md) : identité,
  prestations couvertes/refusées, zone + communes, horaires/durées/buffers/urgences,
  tarifs communicables (phrases pré-rédigées), transfert, validation, SMS. ✅ schéma + exemple Dupont.

Qualité prouvée : suite de non-régression **25 tests** (mock, ~2 s, sans clé ni base) +
éval LLM réelle 8 personas adversariaux → **32 conversations, 0 échec**. Chaque test de
backend est éprouvé par mutation (on casse la règle, on exige que le test échoue). ✅

## 6. Les interfaces artisan 🔜 (rien de construit — prochaine grosse brique)

**Décision 22/08 : site web (SaaS) + application mobile.** Les artisans vivent sur leur
smartphone : l'app mobile est l'interface principale du quotidien (validation, leads,
notifications **push natives**) et doit être d'une simplicité radicale ; le site web porte
le reste (config détaillée, funnel/stats, facturation, onboarding). Conséquence technique
probable : app cross-platform (type React Native/Expo ou Flutter — à trancher en phase
backend) pour iOS + Android avec une seule base de code, partageant l'API du site.

- **La boîte de validation** (app mobile) : les RDV en attente, validation/modification/
  refus en 1 tap, renégociation d'horaire par SMS (§3.5bis) avec les réponses client
  remontées en push. C'est LA fonction — le reste est secondaire.
- **La liste des leads** : carte par lead (score + raisons, ex. « 🔥 5/5 — fuite active,
  Créteil, propriétaire, dispo 14h–18h »), catégories (à rappeler, prioritaire, hors zone…),
  transcript consultable.
- **Le funnel du mois** : appels traités → qualifiés → RDV pris → honorés → chantiers gagnés
  → € générés. Principe clé hérité des discussions amont : ne JAMAIS inventer le « CA
  récupéré » — l'artisan marque gagné/perdu + montant (plus tard : auto via intégrations).
  Distinguer CA confirmé vs pipeline potentiel.
- **La config self-service** : zone (carte ou liste de communes), prestations, horaires,
  tarifs communicables, délais de validation. ❓ jusqu'où en V1 vs onboarding assisté ?
- ❓ Multi-utilisateurs (patron + compagne qui gère l'admin le soir — cas Dupont) : V1 ou V2 ?

## 7. Calendrier & RDV

- ✅ Stub avec les vraies règles : fenêtres 2 h, horaires par jour, durées par prestation,
  buffer trajet fixe 30 min, fenêtres urgence réservées (max/jour), plafond RDV IA/jour.
- 🔜 Lecture free/busy **Google Calendar** puis Outlook (OAuth à lancer tôt — vérification
  Google longue). Mode **sans calendrier connecté** (notre calendrier fait foi) pour les
  artisans papier — probablement le mode bêta par défaut.
- ❓ Buffer trajet intelligent (distance réelle vs 30 min fixes) : V2.
- **Annulation / modification de RDV par le CLIENT — exigence V1** (décision 22/08),
  par les deux canaux :
  - **Rappel téléphonique** : l'agent reconnaît le numéro appelant lié à un RDV à venir
    et ouvre directement dessus (« Vous appelez au sujet de votre rendez-vous de mardi ? »).
    Annulation → créneau libéré (tampon ou calendrier perso), notification push artisan,
    SMS récapitulatif au client. Modification → proposition de nouveaux créneaux (mêmes
    règles agenda) → repasse par le flow de validation artisan standard.
    → nécessite un état dédié dans la machine (S12 « gestion RDV existant ») : script v0.2.
  - ~~**SMS** : « finalement mardi je ne peux pas » sur le fil de confirmation~~ —
    **sans objet depuis le 23/08** (SMS strictement sortant, cf. §4). L'annulation par le
    client passe donc par le rappel téléphonique, ou par un lien à prévoir sur le modèle
    de §3.5bis. 🔜
  - ❓ à trancher : une modification demandée par le client re-passe-t-elle TOUJOURS par
    la validation artisan (mon penchant : oui en V1, cohérent avec « jamais d'engagement
    sans l'artisan »), et gestion des annulations tardives (< 2 h avant le RDV : notification
    « urgente » à l'artisan pour qu'il ne se déplace pas pour rien).

## 8. Téléphonie & voix 🔜 (la prochaine frontière — bascule Claude Code prévue ici)

Décisions prises : plateforme vocale managée (Vapi / Retell / ElevenLabs Agents — à
benchmarker) derrière une couche d'abstraction à nous ; numéros FR avec API ; latence
cible < 1 s par tour ; annonce IA < 5 s ; repli si STT/TTS down = message pré-enregistré
+ SMS client et artisan.
❓ Non décidés : le fournisseur, le coût cible par minute, la voix (genre, ton, prénom de
l'assistant ?), enregistrement audio (V1 : transcript seul — décision RGPD à confirmer).

## 9. Données, légal, conformité

- ✅ (logique) Chaque lead : horodatage, source, base légale (demande entrante — loi du
  11/08/2026), transcript, violations et dégradations tracées.
- 🔜 Persistance réelle (aujourd'hui : JSON local). ❓ Choix DB/hébergement (mon penchant :
  Postgres managé, hébergement UE).
- 🔜 RGPD : DPA avec les artisans (nous = sous-traitant), durées de rétention (365 j
  transcripts posé dans la config — à confirmer), info des appelants, registre.
- Annonce IA obligatoire : dans la formule d'ouverture, validée à la saisie de config. ✅

## 10. Modèle économique (hérité des réflexions amont — RIEN de validé) ❓

Abonnement ~149–249 €/mois selon les hypothèses de départ, bêta ~149 €. Coûts variables à
maîtriser : voix (~0,05–0,15 €/min), LLM (< 0,01 €/appel en texte), SMS, numéro.
North Star Metric : **€ de CA généré/récupéré pour l'artisan** (d'où le funnel §6).
❓ Pricing final, période d'essai, engagement — décisions business avec ton cousin.

## 11. Ce que la V1 ne fait PAS (exclusions assumées)

Devis, facturation, paiement, planning chantier, gestion d'équipe, compta (le marché est
pris et ce n'est pas la promesse). **Appels sortants : exclus définitivement (décision
22/08, risque légal).** Multi-langue. Avis Google. Call center multi-artisans. Email
entrant : en réflexion, ni engagé ni exclu. — Le reste est V2+ ou jamais.

## 12. État d'avancement global

| Brique | État |
|---|---|
| Specs conception (script, config, scénarios, diagramme) | ✅ v0.1 |
| Agent conversationnel texte + garde-fous + dégradation | ✅ prototype validé (32/32) |
| Suites d'éval (mock + LLM adversarial + boucle par fichiers) | ✅ opérationnelles |
| Résolution commune→CP Île-de-France | ✅ |
| Persistance (Postgres/Supabase) + port de dépôt + contrat | ✅ vérifié sur base réelle |
| Cycle de vie du RDV, expiration, file sortante idempotente | ✅ (23/08) |
| API HTTP : webhooks appel, boîte de validation, 1 tap | ✅ (23/08) |
| Validation client par lien à un tap (remplace le SMS bidirectionnel) | ✅ (23/08) |
| Envoi SMS réel | 🔜 port prêt, **aucun fournisseur câblé** — rien ne part |
| App mobile (push) + site web | 🔜 l'API les attend (`GET /rdv`) |
| Téléphonie + voix | 🔜 aucun numéro, aucune plateforme branchée |
| Calendriers réels (Google/Outlook) | 🔜 (OAuth à lancer en avance) |
| Onboarding artisan 20 min | 🔜 (plan posé dans config-artisan-v1.md §3) |
| Marketing / interviews terrain | 🔜 côté cousin (guide livré) |

---

*À toi : corrige les ❓, barre ce qui est faux, ajoute ce qui manque — cette spec deviendra
la référence dans docs/ et le journal pointera dessus.*
