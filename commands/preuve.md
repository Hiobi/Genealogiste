---
description: Rapport de preuve (proof argument) rédigé pour un fait difficile
argument-hint: <id> [fait : BIRT|DEAT|MARR|filiation|uid]
---
Rapport de preuve : **$ARGUMENTS**

1. `arbre_rapport_preuve(id, fait)` : trame pré-remplie (pièces avec citations normalisées, recherches
   négatives du journal, statut, contradictions, cohérence, suite).
2. Si la recherche n'est pas raisonnablement exhaustive (peu de pièces, aucune recherche négative), le dire
   et proposer `/genealogiste:enquete` ou l'agent `chercheur` avant de conclure.
3. Faire rédiger par l'agent **`redacteur`** les sections Question, Analyse et corrélation, Contradictions et
   Conclusion, à partir de la trame uniquement (aucun fait nouveau non sourcé).
4. Présenter le rapport ; sur accord, `rapport_enregistrer(id, titre, contenu)` (commit dans le dépôt de
   données). Si la conclusion change un statut (réfutation, filiation), proposer l'opération correspondante.
