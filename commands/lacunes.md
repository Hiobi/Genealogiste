---
description: Faits manquants ou faibles et plan de recherche priorisé
argument-hint: <id|arbre>
---
Lacunes de : **$ARGUMENTS**

1. Si « arbre » ou vide : `arbre_lacunes()` (classement des personnes à traiter) ; sinon `arbre_lacunes(id)`.
2. Pour chaque action, par priorité (contradictions et erreurs de cohérence d'abord, puis faits manquants,
   puis faits faibles) : fait, problème, **source à consulter**, service et **cote typique**
   (`cotes_a_consulter`), accès en ligne, délai de communicabilité si récent (`communicabilite`).
3. Regrouper les actions par service d'archives / déplacement pour un plan efficace.
4. Proposer de lancer les recherches en ligne correspondantes (`/genealogiste:cherche` ou agent `chercheur`).
5. Si `medias_a_lier` est présent : images jointes à des citations mais absentes des fiches (personne, événement,
   source). Lister média et cibles, et proposer de soumettre les opérations `operation` par `arbre_proposer` ;
   `arbre_appliquer` seulement après accord explicite.
6. **Tâches de Gramps Web** (seulement si l'utilisateur le demande, une personne à la fois, backend gramps et
   `GENEALOGISTE_GRAMPS_TACHES=true`) : lister d'abord les tâches existantes
   (`arbre_recherche(etiquette="ToDo", objet="source")`), puis `arbre_lacunes(id, taches=true)` →
   `taches_a_proposer` (priorité Gramps calculée de la priorité de lacune : 0-1 haute, 2 moyenne, 3 basse).
   Garder les actions retenues par l'utilisateur, `arbre_proposer` (tâches privées par défaut ; diff et
   avertissements), `arbre_appliquer` seulement après accord explicite. Réglage désactivé : le dire et
   s'arrêter là.
