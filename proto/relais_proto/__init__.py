"""Relais — prototype texte de l'agent conversationnel.

Architecture (miroir de la future prod) :
- engine.py     : le CONTRÔLEUR — machine à états S0–S11, décide quoi faire. Déterministe.
- llm.py        : le LLM en deux rôles étroits — EXTRACTEUR de slots et FORMULEUR de répliques.
                  Mode mock (sans clé API) pour les tests.
- guards.py     : les invariants appliqués EN CODE sur chaque sortie (prix, promesses, "confirmé").
- calendar_stub.py : faux calendrier appliquant les vraies règles agenda de la config.
- scoring.py    : lead + score 0–5 post-appel.

Le LLM ne décide jamais de la transition ni du contenu engageant : il met en mots
ce que le contrôleur a décidé, et le garde-fou vérifie derrière.
"""

__version__ = "0.1.0"
