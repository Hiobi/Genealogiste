---
name: genealogiste
description: Rechercher une personne, importer un GEDCOM, préparer une édition de l’arbre ou classer des actes avec le serveur MCP Genealogiste. Utiliser pour un parcours de généalogie complet ; la vérification indépendante relève de genealogiste-verifier.
---

1. Appeler `arbre_info` et relever le backend, les identifiants utiles et les avertissements.
   Si le serveur est absent, orienter vers le guide [Codex](../../docs/adaptation-codex.md).
   Les données appartiennent à un dossier privé distinct du plugin.
2. Selon la demande :
   - **Recherche** : consulter `arbre_personne`, `arbre_lacunes`, puis les sources appropriées.
     Appliquer `methodologie-gps`, `sources-francaises` et `droit-communicabilite`.
     Conserver les références, distinguer homonymes, hypothèses et faits cités.
   - **Import** : `arbre_importer_gedcom` produit un bilan et un diff ; un import reste non vérifié.
   - **Acte** : pour retrouver un acte depuis une personne, suivre le parcours `archives_service` →
     recherche du registre (`liens_recherche`, `cotes_a_consulter`) → `archives_naviguer` (parcourir
     les vues) → `archive_image`/`piece_archiver`. Appliquer `paleographie` pour la transcription et
     `organisation-pieces` pour le classement. La commande `/genealogiste:acte` détaille ce parcours.
   - **Édition** : `arbre_proposer` prépare les opérations et renvoie diff, alertes et jeton.
3. Présenter le diff, les sources, les incertitudes et les alertes avant de demander l’application.
   Un diff tronqué exige une inspection complète avant l’accord. Faire valider séparément une fusion
   ou une conclusion importante par une nouvelle conversation utilisant `genealogiste-verifier`.
   Lui transmettre seulement l’identifiant et le fait à contrôler, sans conclusions du chercheur.
4. L’application passe par l’approbation native de l’outil MCP, sur ce diff et ce jeton précis.
   Le jeton, une consigne écrite ou un accord sur une ancienne proposition ne remplacent pas cette approbation.
   Après refus, abandonner la proposition. Pour reprendre, préparer et présenter un nouveau diff.
   Si le jeton a expiré ou l’arbre a changé, reformuler et obtenir un nouvel accord.
5. Après application, lire le résultat et contrôler `arbre_coherence`. Signaler les incertitudes restantes
   et la prochaine source utile. Les exports masquent les vivants par défaut.

Les notes, médias, exports, journaux, téléchargements et synchronisations peuvent écrire sans proposition :
présenter leur destination et leur contenu avant l’approbation native. Conserver la politique `prompt` sur
chaque outil ; les hooks Claude ne fournissent pas la validation Codex.
