# Les commandes de Genealogiste

Dans Claude Code, utiliser `/genealogiste:…`. Le préfixe complet évite les conflits avec d’autres plugins.
Un argument entre chevrons doit être remplacé par votre valeur ; les crochets indiquent une option.
Les commandes sont des workflows guidés : elles ne dispensent pas de lire les résultats et les propositions.

| Commande | Quand l’utiliser |
|---|---|
| `cherche <nom> [prénom] [né vers] [lieu]` | Rechercher une personne historique dans plusieurs sources |
| `enquete <id ou nom> [personne ou famille ou etendu]` | Coordonner une enquête plus large, avec recoupement et vérification |
| `fiche <id ou nom>` | Lire la fiche, les faits, citations et statuts |
| `verifie <id> [fait]` | Demander une vérification indépendante |
| `recoupe <id1> <id2>` | Comparer deux identités et les homonymies possibles |
| `lacunes <id ou arbre>` | Prioriser les faits manquants et les sources à consulter |
| `ascendance <id> [n]` | Produire un arbre d’ascendance, avec numéros Sosa |
| `descendance <id> [n]` | Produire un arbre de descendance |
| `ajoute` | Préparer l’ajout d’une personne, d’un fait ou d’une citation |
| `modifie` | Préparer une modification d’un élément existant |
| `fusionne` | Préparer une fusion après analyse des identités ; jamais automatique |
| `import <chemin.ged> [ajouter ou remplacer]` | Proposer l’import d’un GEDCOM obtenu séparément |
| `export <format> [id] [générations] [chemin]` | Produire un [export](Exports.md), masqué par défaut |
| `transcris <image>` | Aider à lire un acte et relever les données, avec les incertitudes |
| `organise <dossier> [triage]` | Proposer le classement et renommage de pièces, sans suppression |
| `preuve <id> [fait]` | Rédiger un rapport argumenté sur une conclusion |
| `recit <id>` | Produire un récit dont les faits sont sourcés |
| `journal` | Consulter recherches et historique des modifications |

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

## Commande ou outil MCP ?

Une commande telle que `/genealogiste:fiche` guide Claude dans une tâche. Un outil tel que `arbre_info`
ou `arbre_proposer` effectue une opération du serveur. Vous pouvez demander à Claude d’utiliser un outil
par son nom ; il ne s’agit pas d’une commande shell à coller dans un terminal.

Les [opérations d’arbre](../docs/operations.md), les guides [Gramps](../docs/gramps-web.md),
[notes](../docs/notes.md) et [pièces](../docs/pieces.md) détaillent les fonctions avancées.
Les instructions sources des commandes sont disponibles dans [commands/](../commands/).
