---
description: Ajouter personne, événement, relation, source, citation ou média (diff + validation)
argument-hint: <description de l'ajout>
---
Ajout dans l'arbre : **$ARGUMENTS**

1. Établir précisément ce qui est ajouté **et sa source**. Sans source : l'ajout est possible mais marqué
   « non sourcé » ; le dire à l'utilisateur.
2. Vérifier l'existant (`arbre_recherche`, `arbre_comparer`) pour éviter un doublon ; vérifier la cohérence.
3. Créer la source si nécessaire (`ajouter_source` : titre, dépôt, cote, URL, type ; `original` pour une
   source dérivée), puis les objets avec citations complètes (`page`, `type_source`, `information`,
   `preuve`). Dates : formats GEDCOM ou français (« 12 vendémiaire an III » est converti).
4. `arbre_proposer(operations, titre, justification)` → montrer le **résumé, le diff et les nouvelles alertes**.
5. Demander : « Valider cette modification ? ». Appeler `arbre_appliquer(jeton)` **uniquement** après un
   accord explicite ; sinon `arbre_annuler_proposition`.
