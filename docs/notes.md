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
├── patronymes/MARTIN.md
└── index.md
```

Le nom de fichier est préfixé par l'id ; une fois créé, il est **réutilisé** même si le nom ou les dates changent
(les `[[wikilinks]]` restent valides). Renommer un fichier dans Obsidian est possible tant que le préfixe
`<id> - ` est conservé. Les dossiers `recherches/` et `courriers/` peuvent être créés librement : l'outil n'y
touche pas.

## Format d'une fiche

- **Frontmatter** (propriétés Dataview / Bases) : `id`, `type` (`personne` | `famille` | `source` | `patronyme` |
  `index`), `nom`, `patronyme`, `statut` (statut le plus faible parmi naissance, décès, filiation), `sosa`, `naissance`, `deces`,
  `lieux`, `sources` (liens), `journal` (ids des entrées), `vivant`, `mis_a_jour`. Les propriétés ajoutées à la
  main sont **conservées** (replacées en fin de frontmatter).
- **Sections générées** entre `<!-- sosa:debut NOM -->` et `<!-- sosa:fin -->` : identité et liens familiaux,
  faits et statut de preuve, sources, prochaines sources, recherches du journal. Elles sont réécrites à chaque
  génération : ne pas écrire dedans.
- **`## Notes libres`** : jamais modifiée par l'outil. `notes_ajouter` y ajoute seulement une entrée datée, sous
  `### Hypothèses`, `### Pistes`, `### Conclusions`, `### Courriers`, `### À faire` ou `### Notes`.

Régénérer sans changement dans l'arbre ne modifie **aucun** fichier (`mis_a_jour` ne bouge que si le contenu
change).

## Patronymes

Une fiche par nom principal, normalisé en Unicode NFC, en capitales et avec des espaces réguliers.
`MARTIN` produit `patronymes/MARTIN.md`. L’identité du patronyme reste distincte du nettoyage de son
nom de fichier : deux noms différents ne sont pas regroupés parce qu’ils donnent le même chemin nettoyé.
Les dossiers de pièces suivent toujours la convention de [pieces.md](pieces.md).

- **Porteurs** : liens vers les fiches, triés par année de naissance ;
- **Variantes** : autres noms et « dit » des porteurs, patronymes de l'arbre de même clé phonétique (liens) ;
- **Berceau** : les 5 communes les plus fréquentes dans leurs faits ;
- **Pièces** : fichiers rangés sous `documents/*/<NOM>/`, `photographies/<NOM>/` et
  `photographies/Sépultures/<NOM>/` (liens Markdown avec destinations URL encodées, notamment pour les crochets des années) ;
- **Requête Dataview** sur `personnes/` (propriété `patronyme`), plus les propriétés `variantes` et `berceau`.

Comme les autres fiches, sections générées et texte libre préservé. Créées par `notes_generer("tout")`, et mises
à jour avec les fiches de personnes (`notes_generer("I1")`, hook après écriture). Une régénération ciblée
réconcilie aussi les fiches de patronymes existantes et un index déjà présent : changement de nom,
remasquage ou disparition du dernier porteur ne laissent pas leurs anciennes sections générées. `notes_lire("MARTIN")` et
`notes_ajouter("MARTIN", …)` acceptent un patronyme.

**Vivants** (mode `masquer`) : les personnes masquées ne sont ni comptées ni listées, ni leurs lieux ; une pièce
dont le nom désigne une personne masquée (`NOM Prénom`) est omise. Un patronyme porté seulement par des personnes
masquées n’a pas de nouvelle fiche ; si elle existait, ses sections générées sont vidées et elle est
signalée dans les `alertes`. Le filtrage des pièces reconnaît les noms connus dans les deux ordres, leurs
graphies sans accents et les caractères nettoyés par la convention de fichier. Il ne permet pas de
classifier une photo anonyme : les notes restent un espace privé, pas un export destiné à publication.

### Noms de fichiers, collisions et contenu manuel

Les noms Windows réservés, les caractères incompatibles et les noms trop longs reçoivent un chemin
portable comportant une empreinte stable du patronyme. La longueur est bornée en octets UTF-8. Les liens
utilisent ce même chemin, sans modifier l’identité enregistrée dans le frontmatter ni la requête Dataview.

Un fichier préexistant non reconnu comme fiche gérée du même patronyme bloque la génération avant
écriture, plutôt que de recevoir le contenu d’un autre nom. Les anciennes fiches gérées dont le nom
ne correspond plus au chemin canonique sont conservées : leurs sections générées sont retirées, leurs
propriétés manuelles et notes libres restent sur place et une alerte demande de vérifier contenu et liens.
Aucun texte libre n’est déplacé ou supprimé automatiquement. La nouvelle fiche canonique est générée à part.

En mode masqué, une fiche qui conserve des porteurs affichables signale également son texte manuel
lorsqu’un porteur du même patronyme est masqué. Ces alertes remontent aussi après une écriture ou un ajout
au journal. Les noms de fichiers et textes libres existants peuvent encore identifier des personnes :
les relire avant tout partage.

## Outils

| Outil | Rôle |
|---|---|
| `notes_generer(id \| "tout")` | crée ou met à jour les fiches (sections générées et frontmatter seulement) ; réconcilie les patronymes et actualise un index existant, `tout` crée aussi `index.md` |
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

## Liens de pièces

Les images des fiches et des nouvelles notes compagnons utilisent `![](chemin-encode)`. Les liens vers
les notes de pièces emploient aussi le Markdown encodé, relativement au fichier qui les contient.
Cela préserve crochets, espaces, parenthèses, accents et `#` sans les interpréter comme syntaxe de lien.
Le [format Markdown encodé est documenté par Obsidian](https://obsidian.md/help/links).

Régénérer les fiches pour actualiser leurs sections « Pièces ». Les notes compagnons déjà présentes
ne sont pas réécrites : leur texte peut avoir été modifié manuellement. Corriger leurs anciennes
incorporations dans Obsidian au besoin. La validation automatique vérifie l’analyse Markdown et la
résolution vers les fichiers synthétiques ; elle ne remplace pas un contrôle visuel dans Obsidian.
