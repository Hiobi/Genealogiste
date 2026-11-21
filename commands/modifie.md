---
description: Modifier une personne, un événement, une source ou un statut (diff + validation)
argument-hint: <id> <modification>
---
Modification : **$ARGUMENTS**

1. `arbre_personne(id)` pour repérer l'élément (uid d'événement, index de nom, famille).
2. Exiger la justification et la source de la modification. Corriger une donnée sourcée par une autre
   donnée : ne pas écraser silencieusement — ajouter la nouvelle version avec sa citation et marquer
   l'ancienne `refute` (`definir_statut`, justification obligatoire) si l'analyse le justifie.
3. Opérations : `modifier_personne`, `modifier_evenement`, `supprimer_evenement`, `modifier_source`,
   `modifier_media` (fichier, titre, format ; `gramps_relocaliser_medias` pour un changement de machine),
   `ajouter_citation`, `lier_enfant`/`delier_enfant`, `lier_conjoint`, `definir_statut`, `marquer_vivant` (`"prive": true` en mode gramps : vivant marqué privé avec
   ses données ; tout l'arbre, et retrait au décès : `gramps_proteger_vivants`).
   Étiquettes (`Blog`, `ToDo`…) : `tags` / `tags_retrait` sur les modifications, `etiqueter` pour tout objet
   existant (famille, dépôt, note partagée, citation…) ; voir docs/operations.md, « Étiquettes ».
4. `arbre_proposer` → diff → accord explicite → `arbre_appliquer(jeton)`.
