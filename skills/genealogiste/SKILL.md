---
name: genealogiste
description: Rechercher une personne, importer un GEDCOM, préparer une édition de l’arbre ou classer des actes avec le serveur MCP Genealogiste. Utiliser pour un parcours de généalogie complet ; la vérification indépendante relève de genealogiste-verifier.
---

1. Appeler `arbre_info` et relever le backend, les identifiants utiles et les avertissements.
   Si le serveur est absent, orienter vers le guide [Codex](../../docs/adaptation-codex.md).
   Les données appartiennent à un dossier privé distinct du plugin.
2. Selon la demande :
   - **Recherche** : consulter `arbre_personne`, `arbre_lacunes`, puis les sources appropriées.
     Appliquer `methodologie-gps`, `sources-francaises` et `droit-communicabilite` (période 1939-1945 : `seconde-guerre-mondiale`).
     Conserver les références, distinguer homonymes, hypothèses et faits cités.
   - **Import** : `arbre_importer_gedcom` (GEDCOM, ou `.gramps` / `.gpkg` de Gramps Desktop) produit un bilan
     et un diff ; un import reste non vérifié ; pour Gramps, présenter aussi `import.non_repris`.
   - **Acte** : pour retrouver un acte depuis une personne, suivre le parcours `archives_service` (service et
     couverture) → recherche du registre (`ark_resoudre` pour un ARK déjà cité ; `archives_registres` pour
     AD59 et les services Mnesys du référentiel, avec commune, année, type d'acte et identifiant local `personne` ; sinon `liens_recherche`,
     `cotes_a_consulter`) → `archives_naviguer` (sonder, parcourir les vues) → `archive_image` (lire) →
     transcription → `piece_archiver` (archiver) → citation. Appliquer `paleographie` pour la transcription
     et `organisation-pieces` pour le classement. La commande `/genealogiste:acte` et l'agent `chercheur`
     détaillent ce même parcours.
   - **Enquête sans surveillance** : seulement à la demande explicite (`--autonome`), suivre le mode
     autonome de [docs/enquetes.md](../../docs/enquetes.md) : enquête ouverte ou reprise, `enquete=<id>` sur
     la collecte, aucune question (tâches manuelles par `enquete_noter`), arrêt sur budget, conclusions par
     `propositions_deposer`, compte rendu à format fixe. Dans Codex, chaque outil garde son approbation native.
   - **Contexte historique** : pour situer une personne ou un lieu dans son époque, ou chercher des pistes
     quand les sources de l'individu manquent, `/genealogiste:contexte <personne | lieu>` dans Claude Code ;
     ailleurs, les mêmes outils : `contexte_local` (éléments sourcés, par échelle) puis `pistes_contexte`
     (hypothèses réfutables) ; pour approfondir, `contexte_bibliographie`, `presse_recherche`, `lieu_historique` ;
     avant de rendre un texte, `contexte_verifier`. Règle : **le contexte oriente, il ne conclut pas** ; rien
     n'est affirmé de mémoire, un élément sans source n'est pas affiché, et une piste tirée du seul contexte ne
     devient ni un fait, ni une tâche, ni une proposition. Méthode : `methodologie-gps`, § « Contexte
     historique » ; signatures et sorties : [docs/contexte-historique.md](../../docs/contexte-historique.md).
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
