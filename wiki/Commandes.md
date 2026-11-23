# Les commandes de Genealogiste

Dans Claude Code, utiliser `/genealogiste:…`. Le préfixe complet évite les conflits avec d’autres plugins.
Un argument entre chevrons doit être remplacé par votre valeur ; les crochets indiquent une option.
Les commandes sont des workflows guidés : elles ne dispensent pas de lire les résultats et les propositions.

| Commande | Quand l’utiliser |
|---|---|
| `cherche <nom> [prénom] [né vers] [lieu]` | Rechercher une personne historique dans plusieurs sources |
| `enquete <id ou nom> [personne ou famille ou etendu] [--autonome] [budget images=… requetes=…]` | Coordonner une enquête plus large, avec recoupement et vérification ; `--autonome` : sans question, bornée par son budget, conclusions déposées dans la file pour `valide` |
| `campagne <id ou nom ou arbre> [enquetes=N]` | Lancer sans surveillance (tâche planifiée, `claude -p`) des enquêtes autonomes sur les lacunes prioritaires : rapport daté, propositions en file, rien d’écrit dans l’arbre ; avec `GENEALOGISTE_ECRITURE=interdite` ([campagne](../docs/campagne.md)) |
| `fiche <id ou nom>` | Lire la fiche, les faits, citations et statuts |
| `verifie <id> [fait : BIRT, DEAT, MARR, filiation, nom ou uid]` | Demander une vérification indépendante |
| `recoupe <id1> <id2>` | Comparer deux identités et les homonymies possibles |
| `lacunes <id ou arbre>` | Prioriser les faits manquants et les sources à consulter |
| `ascendance <id> [générations, 4 par défaut]` | Produire un arbre d’ascendance, avec numéros Sosa, en tableau et en diagramme Mermaid |
| `descendance <id> [générations, 3 par défaut]` | Produire un arbre de descendance, en liste et en diagramme Mermaid ; vivants masqués |
| `ajoute <description de l’ajout>` | Préparer l’ajout d’une personne, d’un événement, d’une relation, d’une source, d’une citation ou d’un média (diff, puis accord) |
| `modifie <id> <modification>` | Préparer la modification d’une personne, d’un événement, d’une source ou d’un statut (diff, puis accord) |
| `valide [id ou a_revoir ou tous]` | Revoir une à une les propositions déposées dans la [file](../docs/propositions.md) et les appliquer après accord |
| `fusionne <id conservé> <id absorbé>` ou `fusionne scinder <id>` | Préparer la fusion de deux fiches, ou la scission d’une fiche, après analyse des identités ; jamais automatique |
| `import <chemin.ged, .gramps ou .gpkg> [ajouter ou remplacer]` | Proposer l’import d’un GEDCOM ou d’un export de Gramps Desktop |
| `export <format> [id] [générations] [chemin]` | Produire un [export](Exports.md), masqué par défaut |
| `acte <id ou nom> [naissance ou mariage ou deces] [--autonome] [budget images=… requetes=…]` | Trouver le registre d’un acte, y repérer la vue, la transcrire et l’archiver ; registre cherché automatiquement pour l’AD59 et quatorze services Mnesys (AD14, AD19, AD25, AD27, AD37, AD39, AD51, AD55, AD58, AD69, AD80, AD90, AD91, AD972), ailleurs cote ou ARK relevés sur le site du service ; `--autonome` : sans question, ce qui demande une personne devient une tâche manuelle |
| `transcris <image, PDF, lien de visionneuse ou IIIF, ARK> [type d’acte, lieu, date]` | Aider à lire un acte ancien (paléographie, latin) et relever les données, avec les incertitudes |
| `organise <dossier> [triage]` | Proposer le classement et renommage de pièces, sans suppression |
| `preuve <id> [fait : BIRT, DEAT, MARR, filiation ou uid]` | Rédiger un rapport argumenté sur une conclusion |
| `contexte <id ou nom, ou lieu> [--periode AAAA-AAAA] [--echelles commune,departement,…] [--themes mots]` | Situer une personne ou un lieu dans son contexte historique : éléments sourcés par échelle (énoncé, citation de la source, niveau de rattachement), « contexte non documenté » quand rien n’est trouvé, services en échec ou écartés, puis pistes de recherche réfutables ; rien n’est affirmé de mémoire, aucune écriture dans l’arbre ([contexte historique](../docs/contexte-historique.md#parcours-dusage)) |
| `recit <id> [courte ou longue]` | Produire une biographie dont chaque phrase factuelle est sourcée ; contexte historique dans une section séparée, tiré des seules références consultées et contrôlé (`contexte_verifier`), absent s’il n’est pas documenté |
| `billet <id ou sujet> [public]` | Publier un récit sourcé dans le blog de Gramps Web (source étiquetée `Blog`, corps en première note, images) : privé par défaut, refusé s’il est public et nomme une personne présumée vivante, ou si sa section « Contexte » n’est pas conforme (`contexte_verifier`) ; backend gramps requis |
| `journal [source, id de personne ou texte] [nombre]` | Consulter recherches (négatives comprises) et historique des modifications |
| `diagnostic [local] [vivants]` | Contrôler configuration, dépendances, droits, caches, sources joignables, chemins des médias, et pour Gramps Web version de l’API, rôle du compte et réglages, avec un remède par problème ; `local` : aucune requête externe ; `vivants` : contrôle des personnes vivantes exposées et des marqueurs en double (Gramps Web) |

## Exemples fictifs

```text
/genealogiste:fiche I1
/genealogiste:lacunes I1
/genealogiste:ascendance I1 4
/genealogiste:export svg_asc I1 4
```

Ces exemples supposent `I1` dans l’arbre chargé. Ne pas reprendre des identifiants d’un autre arbre.
Pour une recherche, donner au moins un nom et des éléments de contexte ; l’agent demandera une précision
si l’identité est ambiguë. Le [parcours d’enquête](Parcours-de-recherche.md) explique comment lire les résultats.

## Demandes sans commande

Certaines demandes n’ont pas de commande dédiée ; les formuler en langage courant :

| Demande | Ce que fait Claude |
|---|---|
| « Quelles ressources pour le Finistère ? », « que connais-tu sur les protestants ? » | `sources_catalogue` : archives publiques, [sites tiers](../docs/sites-tiers.md) (cercles, relevés, bases thématiques) et API |
| « Mon grand-père était prisonnier en Allemagne » | parcours [Seconde Guerre mondiale](../docs/seconde-guerre-mondiale.md) par profil, fonds et dossiers à demander |
| « Comment chercher MÜLLER Jean dans les fonds allemands ? » | `variantes_noms` : Müller, Mueller, Muller ; Jean, Johann, Hans |
| « Que se passait-il à cet endroit à cette époque ? » | `contexte` : éléments sourcés et pistes ; « contexte non documenté » si rien n’est trouvé, jamais un texte général |
| « Range ce dossier de scans » | `organise` : inventaire, plan de classement, application après accord |

## Commande ou outil MCP ?

Une commande telle que `/genealogiste:fiche` guide Claude dans une tâche. Un outil tel que `arbre_info`
ou `arbre_proposer` effectue une opération du serveur. Vous pouvez demander à Claude d’utiliser un outil
par son nom ; il ne s’agit pas d’une commande shell à coller dans un terminal.

Les [opérations d’arbre](../docs/operations.md), les guides [Gramps](../docs/gramps-web.md),
[notes](../docs/notes.md) et [pièces](../docs/pieces.md) détaillent les fonctions avancées.
Les instructions sources des commandes sont disponibles dans [commands/](../commands/).

## Outils du serveur

Les commandes et les agents appellent ces outils ; vous pouvez aussi en demander un par son nom.
Un astérisque (\*) signale un outil qui écrit : Claude Code demande alors votre accord. Les autres lisent,
collectent (sources, cache, journal, pièce nouvelle) ou préparent une proposition, sans confirmation
([classes de permission](../docs/securite.md#confirmations-hooks)).

| Domaine | Outils |
|---|---|
| Lire l’arbre | `arbre_info` (effectifs, emplacement, propositions en attente) ; `arbre_recherche` ; `arbre_personne` (noms, événements, filiation, unions, statut de chaque fait, alertes) ; `arbre_fiche` ; `arbre_statut_preuve` ; `arbre_coherence` ; `arbre_lacunes` ; `arbre_vivant` ; `arbre_historique` ; `arbre_statut_transaction` |
| Analyser l’arbre | `arbre_ascendance` (numérotation Sosa ; liste, Mermaid ou SVG) ; `arbre_descendance` (vivants masqués) ; `arbre_cercle` (proches à enquêter : `personne`, `famille` ou `etendu`, avec les vivants signalés) ; `arbre_comparer` (même personne ou homonymes : score par critère, contradictions ; ne fusionne jamais) ; `arbre_rapport_preuve` (trame de rapport de preuve : pièces, recherches négatives, contradictions, conclusion à rédiger) |
| Modifier l’arbre | `arbre_proposer` ([opérations](../docs/operations.md)) ; `arbre_appliquer`\* ; `arbre_annuler_proposition` (abandonne une proposition en attente, rien n’est écrit) ; `arbre_annuler_modification` ; `arbre_importer_gedcom` (GEDCOM, `.gramps`, `.gpkg`) ; `arbre_exporter`\* ([exports](Exports.md)) |
| File de propositions | `propositions_deposer`, `propositions_lister`, `propositions_reprendre`, `propositions_abandonner` ([file](../docs/propositions.md)) |
| Enquêtes et rapports | `enquete_ouvrir`, `enquete_noter` (accord demandé pour fixer ou relever un budget, ou rouvrir une enquête) ; `enquete_etat` ; `enquete_reprendre` ([état d’enquête](../docs/enquetes.md)) ; `rapport_enregistrer`\* ; `rapport_campagne_enregistrer` |
| Sources en ligne | `recherche_multi` ; `matchid_recherche`, `matchid_appariement_csv`\*, `matchid_appariement_statut` (accord demandé pour écrire le résultat dans un fichier) ; `wikitree_recherche`, `wikitree_profil`, `wikitree_personne`, `wikitree_ascendants`, `wikitree_descendants` ; `wikidata_personne`, `wikidata_sparql` ; `gallica_recherche`, `gallica_recherche_document`, `gallica_texte`, `gallica_alto`, `gallica_iiif` (adresses IIIF d’un document Gallica : manifeste, page, région, taille ; sans requête) ; `geo_commune`, `geo_historique` ; `liens_recherche` ; `source_collee` ; `familysearch_exporter`\* (désactivé) |
| Contexte historique | `contexte_local` (éléments sourcés par échelle autour d’une personne ou d’un lieu) ; `pistes_contexte` (hypothèses de recherche réfutables) ; `contexte_bibliographie` (littérature historique citée : HAL, Isidore, Sudoc, BnF, theses.fr, Crossref) ; `presse_recherche` (presse ancienne, repli explicite par service) ; `lieu_historique` (commune à une date, niveau par niveau, cartes anciennes) ; `contexte_verifier` (contrôle d’un récit, d’une note ou d’un billet, sans réseau) ([contexte historique](../docs/contexte-historique.md)) |
| Référentiels | `sources_catalogue` ; `archives_service` ; `cotes_a_consulter` ; `prochaine_source` ; `communicabilite` |
| Registres et images | `archives_registres` ; `archives_naviguer` ; `archives_planche` ; `archives_sonder` (vue à lire pour atteindre une date, sans tâtonner) ; `archive_image` ; `ark_resoudre` ; `pdf_markdown` ([archives](../docs/archives.md), [pièces](../docs/pieces.md)) |
| Noms, dates et lieux | `normaliser_nom` (prénoms latins traduits, nom sans particule, surnom « dit », clé phonétique) ; `comparer_noms` ; `variantes_noms` ; `comparer_profils` ; `convertir_date` (grégorien, julien, républicain) ; `naissance_depuis_age` (intervalle de naissance d’après un âge déclaré, ±2 ans) ; `normaliser_lieu` (Saint/St, paroisse, département, ancien département) |
| Pièces et médias | `piece_nommer` ; `piece_archiver` ; `media_enregistrer`\* ; `pieces_inventaire` ; `pieces_proposer` ; `pieces_appliquer`\* ; `gramps_relocaliser_medias` (chemins des médias après un changement de machine ; les deux modes) |
| Notes | `notes_generer`\*, `notes_lire`\*, `notes_ajouter`\* ; `marqueurs_migrer_proposer`, `marqueurs_migrer_appliquer`\* ([notes](../docs/notes.md)) |
| Journal et exploitation | `journal_lister` ; `journal_ajouter` ; `diagnostic` ; `cache_purger`\* |
| Gramps Web | `gramps_recherche`, `gramps_personne` ; `gramps_tirer`\* ; `gramps_bascule_proposer`, `gramps_bascule_appliquer`\* ; `gramps_synchroniser` ; `gramps_recalculer_notes` ; `gramps_structurer_lieux`, `gramps_dater_lieux` ; `gramps_normaliser_types` ; `gramps_proteger_vivants` ; `gramps_grouper_noms` (lecture seule) ; `gramps_reglages` ; `gramps_envoyer_medias` (accord demandé pour l’envoi) ([Gramps Web](../docs/gramps-web.md)) |
