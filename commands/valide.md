---
description: Revoir et valider les propositions déposées dans la file, une à la fois (diff frais + accord)
argument-hint: [id de proposition | a_revoir | tous]
---
Revue de la file de propositions : **$ARGUMENTS**

1. `propositions_lister` (avec `statut="a_revoir"` ou `"tous"` si demandé ; sans argument : en attente et à
   revoir). Annoncer le nombre d'entrées et la liste courte (id, titre, personnes, enquête, date de dépôt).
   Si un id est donné, ne traiter que celle-ci.
2. **Une proposition à la fois**, dans l'ordre de dépôt : `propositions_reprendre(id)`.
   - Succès : montrer le titre, la **justification**, les **sources et pièces à l'appui** (chemins des pièces,
     citations des opérations), les personnes visées, puis le **résumé, le diff frais et les nouvelles alertes
     de cohérence**. Pour une pièce citée, proposer de l'ouvrir avant de décider.
   - Échec (`statut: a_revoir`) : montrer la raison (personne modifiée, conflit, citation exigée…) et
     proposer de reformuler les opérations (`arbre_proposer`) ou d'abandonner. Passer à la suivante.
3. Demander : « Valider cette proposition ? ». Appeler `arbre_appliquer(jeton)` **uniquement** après un accord
   explicite pour CETTE proposition (jamais d'accord groupé) ; l'entrée passe alors « appliquee » avec la
   référence du commit ou de la transaction.
   - Refus définitif : `propositions_abandonner(id, motif)`.
   - Remise à plus tard : ne rien faire ; l'entrée reste en attente (le jeton expire, pas l'entrée).
4. Après chaque décision, annoncer la suivante ; à la fin, récapituler appliquées, abandonnées, à revoir.

Rien n'est écrit dans l'arbre sans `arbre_appliquer`. Le dépôt dans la file (`propositions_deposer`) sert aux
recherches sans surveillance : opérations validées à sec, aucune écriture. Voir `docs/propositions.md`.
