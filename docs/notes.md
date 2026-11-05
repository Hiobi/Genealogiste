# Notes de recherche Markdown (Obsidian, LLM)

Espace de travail humain à côté de l'arbre : hypothèses, pistes, courriers, actes en attente. Les fiches sont
lisibles et modifiables dans **Obsidian** et servent de contexte aux agents (`notes_lire`). **L'arbre reste la
référence** : rien n'est écrit dans l'arbre depuis les notes (`arbre_proposer` → accord → `arbre_appliquer`).

## Configuration

| Variable | Rôle |
|---|---|
| `GENEALOGISTE_NOTES_DIR` | répertoire des notes (vault Obsidian ou sous-dossier) ; vide = fonctionnalité désactivée |
| `GENEALOGISTE_NOTES_VIVANTS` | `masquer` (défaut) : fiche réduite, sans nom dans le nom de fichier ; `complet` |
| `GENEALOGISTE_NOTES_AUTO` | `true` (défaut) : après `arbre_appliquer`, fiches des personnes, familles et sources modifiées régénérées ; après `journal_ajouter` avec `personne`, fiche de cette personne |
| `GENEALOGISTE_SOSA_RACINE` | id de la personne n° 1 : propriété `sosa` des ascendants |

## Arborescence

```
<NOTES_DIR>/
├── personnes/I1 - Jean MARTIN (1820-1885).md
├── familles/F1 - MARTIN × DUPONT.md
├── sources/S1 - Registres d'état civil de Rochefort.md
└── index.md
```

Le nom de fichier est préfixé par l'id ; une fois créé, il est **réutilisé** même si le nom ou les dates changent
(les `[[wikilinks]]` restent valides). Renommer un fichier dans Obsidian est possible tant que le préfixe
`<id> - ` est conservé. Les dossiers `recherches/` et `courriers/` peuvent être créés librement : l'outil n'y
touche pas.

## Format d'une fiche

- **Frontmatter** (propriétés Dataview / Bases) : `id`, `type` (`personne` | `famille` | `source` | `index`),
  `nom`, `statut` (statut le plus faible parmi naissance, décès, filiation), `sosa`, `naissance`, `deces`,
  `lieux`, `sources` (liens), `journal` (ids des entrées), `vivant`, `mis_a_jour`. Les propriétés ajoutées à la
  main sont **conservées** (replacées en fin de frontmatter).
- **Sections générées** entre `<!-- sosa:debut NOM -->` et `<!-- sosa:fin -->` : identité et liens familiaux,
  faits et statut de preuve, sources, prochaines sources, recherches du journal. Elles sont réécrites à chaque
  génération : ne pas écrire dedans.
- **`## Notes libres`** : jamais modifiée par l'outil. `notes_ajouter` y ajoute seulement une entrée datée, sous
  `### Hypothèses`, `### Pistes`, `### Conclusions`, `### Courriers`, `### À faire` ou `### Notes`.

Régénérer sans changement dans l'arbre ne modifie **aucun** fichier (`mis_a_jour` ne bouge que si le contenu
change).

## Outils

| Outil | Rôle |
|---|---|
| `notes_generer(id \| "tout")` | crée ou met à jour les fiches (sections générées et frontmatter seulement) ; `tout` met aussi à jour `index.md` |
| `notes_lire(id)` | fiche complète, texte libre compris (générée si absente) |
| `notes_ajouter(id, texte, section)` | entrée datée dans le texte libre |

## Personnes vivantes

Par défaut, la fiche d'une personne présumée vivante ou marquée privée ne contient que son id (RGPD) et
`notes_ajouter` est refusé.

**Remasquage** (passage de `complet` à `masquer`, ou personne devenue présumée vivante) : toutes les propriétés et
sections produites par l'outil sont retirées, y compris celles qui n'existent plus dans la fiche masquée, et le
titre est remplacé. Le fichier n'est **pas renommé** (les liens existants restent valides) ; `notes_generer`
renvoie des `alertes` :

- nom de fichier pouvant identifier la personne (ex. `I9 - Lucas MARTIN (1990).md`) : le renommer à la main dans
  Obsidian, qui met les liens à jour ;
- texte libre ou propriétés saisis à la main : conservés, mais signalés pour vérification.
Si le répertoire est dans un dépôt Git qui a un dépôt distant, `notes_generer` avertit : vérifier qu'il est
**privé**.
