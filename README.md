# Relais

Agent IA qui répond aux appels manqués des artisans, qualifie la demande et remplit leur agenda —
avec validation du rendez-vous par l'artisan avant confirmation au client.

**Cible V1 :** plombiers / chauffagistes (France) · **Mécanisme :** renvoi conditionnel de la ligne
de l'artisan vers notre numéro → agent vocal → qualification → réservation provisoire → validation
1-tap → SMS de confirmation.

## Structure

```
docs/       Specs de conception (source de vérité — évolue avec le code)
evals/      Suite de scénarios de test T01–T12 (future exécution automatisée)
proto/      Prototype texte de l'agent (machine à états, sans voix ni téléphonie)
packages/   Plus tard : core, config, calendar
apps/       Plus tard : api, dashboard
```

## Documents fondateurs (v0.1 — 21/08/2026)

| Document | Rôle |
|---|---|
| `docs/script-conversation-v1.md` | La machine à états S0–S11, les slots, les 9 invariants, le flow de validation « expiration + repli » |
| `docs/config-artisan-v1.md` | Tout ce que l'agent sait : schéma JSON + persona de test « Dupont Chauffage » + plan d'onboarding 20 min |
| `docs/machine-etats-v1.html` | Diagramme complet (ouvrir dans un navigateur) |
| `docs/scenarios-test-v1.md` | Les 12 scénarios d'éval — la définition de « l'agent marche » |

## Principes non négociables

1. Le LLM ne sait rien de lui-même : tout vient de la config (prix, consignes, promesses = listes blanches).
2. Aucun RDV sans téléphone de rappel confirmé.
3. Jamais « confirmé » avant validation artisan.
4. Annonce IA en ouverture d'appel (AI Act art. 50).
5. On ne change jamais un prompt sans rejouer la suite d'éval complète.

## Décisions d'architecture prises

- Voix en plateforme managée (Vapi/Retell/ElevenLabs) derrière une couche d'abstraction à nous —
  notre valeur est le pipeline, pas la voix.
- Monorepo unique. `docs/` versionné avec le code.
- Prochaine étape : prototype texte dans `proto/`, joué contre les 12 scénarios.

## Équipe

Geoffrey (dev + produit, avec Claude en binôme) · Cousin (marketing, acquisition, interviews terrain).
