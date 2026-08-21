# Schéma de configuration artisan — V1

Version 0.1 — 21/08/2026 · Compagnon de `script-conversation-v1.md`

> Ce document définit **tout ce que l'agent sait** sur un artisan. Règle absolue : le LLM ne
> « sait » rien de lui-même — chaque information prononcée au téléphone provient d'un champ ici.
> C'est aussi, en creux, le **formulaire d'onboarding** : chaque champ = une question posée à
> l'artisan à l'inscription. Objectif : onboarding complet en **moins de 20 minutes**, donc
> chaque champ doit mériter sa place (les champs V2 sont marqués, pas implémentés).

---

## 1. Schéma (JSON annoté)

```jsonc
{
  "entreprise": {
    "nom": "string",                          // « Dupont Chauffage »
    "prenom_patron": "string",                // utilisé par l'agent : « Julien est en intervention »
    "metier": "plombier_chauffagiste",        // enum — sélectionne le pack de questions métier du script
    "siret": "string",                        // facturation + vérification, jamais prononcé
    "adresse_base": { "cp": "94130", "ville": "Nogent-sur-Marne" }  // point de départ trajets
  },

  "telephonie": {
    "numero_artisan": "+33612345678",         // sa vraie ligne (celle qui porte le renvoi conditionnel)
    "numero_agent": "+33940000000",           // notre numéro, cible du renvoi — attribué par nous
    "renvoi_verifie": true                    // onboarding : on vérifie par appel test que le renvoi marche
  },

  "accueil": {
    "formule": "string|null",                 // null → formule par défaut du script (S0)
                                              // contrainte : doit contenir l'annonce IA (validation à la saisie)
    "promesse_rappel": {                      // la SEULE promesse de délai autorisée (S6)
      "ouvree": "sous 2 heures",
      "soir_weekend": "demain matin avant 9h"
    }
  },

  "prestations": {
    "couvertes": [                            // pilote S1 : intent couvert ou non
      "fuite", "chaudiere_panne", "chauffe_eau", "wc_evacuation",
      "robinetterie", "devis_chaudiere", "devis_pac", "devis_sdb", "entretien_chaudiere"
    ],
    "refusees": ["debouchage_colonne_immeuble", "gaz_installation_neuve"],
    "confreres_recommandation": "string|null" // S8 : « pour ça, appelez plutôt X » (optionnel)
  },

  "zone": {
    "codes_postaux": ["94130", "94170", "94300", "94100"],   // S2 : en zone
    "codes_postaux_limitrophes": ["94000", "93360"],         // S2 : accepté mais marqué, l'artisan tranche
    "message_hors_zone": "string|null"
  },

  "agenda": {
    "calendriers_connectes": [                // lecture des disponibilités (free/busy)
      { "type": "google", "id": "...", "sens": "lecture" }
    ],
    "mode_sans_calendrier": false,            // true = notre calendrier fait foi (artisans papier — bêta friendly)
    "horaires_rdv": {                         // fenêtres où l'agent a le droit de placer des RDV
      "lun-ven": [{ "de": "08:00", "a": "18:00" }],
      "sam": [{ "de": "09:00", "a": "13:00" }],
      "dim": []
    },
    "durees_min": {                           // durée bloquée par type d'intervention
      "fuite": 90, "chaudiere_panne": 90, "wc_evacuation": 60,
      "devis_*": 60, "entretien_chaudiere": 60, "defaut": 90
    },
    "buffer_trajet_min": 30,                  // V1 : buffer fixe entre 2 RDV. V2 : calcul par distance
    "urgences": {
      "acceptees": true,
      "fenetres_reservees": [                 // créneaux tenus libres pour l'urgent (S5)
        { "jours": "lun-ven", "de": "17:00", "a": "19:00" }
      ],
      "max_par_jour": 2
    },
    "max_rdv_agent_par_jour": 4,              // plafond de ce que l'IA peut réserver seule
    "granularite_proposition": "fenetre_2h"   // on propose « entre 14h et 16h », jamais « 14h30 »
  },

  "validation": {                             // flow « expiration + repli » (décision 21/08)
    "delai_max_heures_ouvrees": 4,
    "delai_max_urgence_heures": 1,
    "canal_notification": ["push", "sms"],
    "auto_validation": "jamais"               // enum : jamais | urgences_5_5 | tout — V1 : « jamais »
  },

  "tarifs": {
    "communicables": [                        // S3 : la LISTE BLANCHE — tout le reste est interdit
      { "libelle": "deplacement_diagnostic", "prix_ttc": 90,
        "phrase": "Le déplacement avec diagnostic est à 90 € TTC, déduits si vous faites les travaux." },
      { "libelle": "entretien_chaudiere", "prix_ttc": 120,
        "phrase": "L'entretien annuel chaudière est à 120 € TTC." }
    ],
    "majoration_soir_weekend": "string|null"  // phrase exacte ou null = ne pas en parler
  },

  "securite": {
    "consignes_autorisees": ["couper_eau", "gaz_aerer_et_grdf"],  // catalogue fermé, textes écrits par nous
    "transfert_si_danger": true               // gaz/inondation grave → tenter S7 avant de conclure
  },

  "transfert": {                              // S7
    "actif": true,
    "cible": "+33612345678",                  // le portable du patron ou de la secrétaire (niveau 2)
    "horaires": { "lun-ven": [{ "de": "08:00", "a": "19:00" }] },
    "declencheurs_supplementaires": ["client_existant_mecontent"]
  },

  "sms": {
    "expediteur": "DupontChauf",              // 11 caractères max (norme sender ID)
    "rappel_rdv": "j-1_18h",                  // et H-2 pour les urgences (fixe V1)
    "templates_personnalises": null           // V2 — V1 : templates globaux avec variables
  },

  "conformite": {
    "enregistrement_appels": false,           // V1 : transcript seul (pas d'audio conservé) — plus simple RGPD
    "retention_transcripts_jours": 365,
    "dpa_signe": true, "date_dpa": "2026-09-01"
  },

  "dashboard": {                              // V2 sauf devise — listés pour mémoire
    "objectif_ca_mensuel": null,
    "montant_moyen_chantier": null            // servira au pipeline « valeur potentielle »
  }
}
```

---

## 2. Exemple rempli : « Dupont Chauffage » (persona de test de bout en bout)

Julien Dupont, plombier-chauffagiste, lui + 2 techniciens, Nogent-sur-Marne, zone 94 est,
Google Calendar partagé avec sa compagne qui fait la facturation le soir. 25–35 appels/semaine,
en rate ~10. Déplacement diagnostic 90 €, entretien 120 €. Veut valider chaque RDV lui-même,
accepte 2 urgences/jour en fin de journée. *(Valeurs : voir le JSON ci-dessus, qui EST cette fiche.)*

Ce persona sert de fil rouge : chaque scénario de test du script (l'appel « fuite à Créteil »,
le « devis PAC à Torcy » hors zone, le client furieux) se joue contre cette config.

## 3. Ce que l'onboarding demande vraiment (les 20 minutes)

| Étape | Champs | Temps estimé |
|---|---|---|
| 1. Identité + numéros | `entreprise`, `telephonie` (avec appel test du renvoi) | 5 min |
| 2. Ce que je fais / où | `prestations.couvertes` (cases à cocher métier), `zone` (carte cliquable) | 4 min |
| 3. Mon agenda | connexion Google/Outlook OU `mode_sans_calendrier`, `horaires_rdv`, durées par défaut pré-remplies métier | 5 min |
| 4. Ce que l'agent peut dire | `tarifs.communicables` (0, 1 ou 2 lignes), `accueil.formule` (défaut proposé) | 3 min |
| 5. Validation & SMS | `validation.delai_max`, `transfert.cible` | 3 min |

**Défauts métier** : pour `plombier_chauffagiste`, tout champ non renseigné a une valeur par défaut
sensée (durées, buffers, fenêtres d'urgence). L'artisan personnalise, il ne construit pas.

## 4. Règles de validation du schéma (côté code)

1. `accueil.formule` personnalisée → doit passer le check « annonce IA présente » sinon rejetée.
2. `tarifs.communicables[].phrase` : rédigée/validée par nous à l'onboarding — l'agent lit, n'improvise pas.
3. `zone.codes_postaux` non vide ; `prestations.couvertes` non vide ; `telephonie.renvoi_verifie=true`
   avant activation.
4. Somme `max_rdv_agent_par_jour` + fenêtres urgences cohérente avec `horaires_rdv` (lint config).
5. Tout changement de config est versionné (audit : « qu'est-ce que l'agent savait le jour de cet appel ? »).

## 5. Questions ouvertes (interviews / bêta)

- `mode_sans_calendrier` : combien d'artisans papier en vrai ? (Q10 du guide) — décide la priorité.
- `buffer_trajet_min` fixe suffit-il en zone dense vs rurale ? (Q13)
- `auto_validation=urgences_5_5` : à activer si Q17 montre que les artisans font confiance.
- Faut-il un mode « vacances/chantier longue durée » (l'agent dit quoi quand l'artisan est absent 3 semaines) ? — probable V1.1.
