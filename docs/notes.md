# Notes de recherche Markdown (Obsidian, LLM)

Espace de travail humain à côté de l'arbre : hypothèses, pistes, courriers, actes en attente. Les fiches sont
lisibles et modifiables dans **Obsidian** et servent de contexte aux agents (`notes_lire`). **L'arbre reste la
référence** : rien n'est écrit dans l'arbre depuis les notes (`arbre_proposer` → accord → `arbre_appliquer`).

## Configuration

| Variable | Rôle |
|---|---|
| `GENEALOGISTE_NOTES_DIR` | répertoire des notes (vault Obsidian ou sous-dossier) ; vide = fonctionnalité désactivée |
| `GENEALOGISTE_NOTES_VIVANTS` | `masquer` (défaut) : fiche réduite, sans nom dans le nom de fichier ; `complet` |
| `GENEALOGISTE_NOTES_KIT` | `true` (défaut) : `notes_generer("tout")` dépose le kit Obsidian (voir « Kit Obsidian ») ; `false` : aucun fichier de kit |
| `GENEALOGISTE_NOTES_AUTO` | `true` (défaut) : après `arbre_appliquer`, fiches des personnes, familles et sources modifiées régénérées ; après `journal_ajouter` avec `personne`, fiche de cette personne |
| `GENEALOGISTE_NOTES_ATTENTE` | `20` (s) : après `arbre_appliquer`, la régénération tourne en arrière-plan ; l'outil attend au plus ce délai puis répond `notes.etat = en_cours`, consultable par `arbre_statut_transaction(jeton)` |
| `GENEALOGISTE_SOSA_RACINE` | id de la personne n° 1 : propriété `sosa` des ascendants |
| `GENEALOGISTE_MARQUEURS` | forme écrite des balises des sections générées : `genealogiste` (défaut) ou `sosa` (ancienne forme, pour partager le vault avec une ancienne version) ; les deux formes sont toujours lues |

## Arborescence

```
<NOTES_DIR>/
├── personnes/I1 - Jean MARTIN (1820-1885).md
├── familles/F1 - MARTIN × DUPONT.md
├── sources/S1 - Registres d'état civil de Rochefort.md
├── patronymes/MARTIN.md
└── index.md
```

Le nom de fichier est préfixé par l'id. Les fiches de personnes portant encore leur nom généré sont
**renommées lors de `notes_generer`** si le nom ou les dates ont changé, y compris après une application
avec génération automatique. Les anciens noms issus d'un affichage erroné (par exemple `~1874` pour
`BEF 1925`) sont ainsi corrigés. Le résultat indique les chemins `ancien` et `nouveau` dans `renommees`.
Une génération ciblée ne renomme que la personne demandée ; `notes_generer("tout")` traite l'ensemble.

Les dates compactes conservent leur sens : `BEF 1925` → `av. 1925`, `AFT` → `ap. …`, `ABT`/`EST`/`CAL`
→ `~…`, `BET 1920 AND 1925` et `FROM 1920 TO 1925` → `1920/1925`. Les arbres en liste, Mermaid et SVG
partagent ce formatage. Pour les noms de fichiers portables, les points sont retirés et la barre d'un
intervalle est remplacée par ` à ` : `(1820-av 1925)` ou `(1820-1920 à 1925)`.

Les destinations des wikilinks et des liens Markdown URL encodés du vault sont mises à jour, y compris
leurs fragments ; les alias/libellés et le reste du texte libre sont conservés. Les exemples en code et
les liens externes restent inchangés. Les références hors du vault et les wikilinks sans dossier dont le
nom est ambigu restent à vérifier manuellement. Les noms personnalisés par l'utilisateur sont conservés
(préfixe `<id> - ` requis), ainsi que le traitement manuel des anciennes fiches remasquées décrit plus bas.

Les dossiers `recherches/` et `courriers/` peuvent être créés librement : aucune fiche n'y est générée,
mais les liens vers une fiche renommée peuvent y être actualisés. Les propriétés manuelles sont conservées.
Une collision de noms ou un lien symbolique sur une fiche à renommer provoque un refus sans écrasement.
Le renommage nécessite un système de fichiers acceptant les liens physiques ; sinon il est refusé en
conservant les originaux. Garder la sauvegarde habituelle du vault avant une régénération importante.

## Reprendre des notes existantes

Un dossier de notes Markdown écrit avant Genealogiste (recherches, transcriptions, courriers) peut servir de
`GENEALOGISTE_NOTES_DIR`. Les fiches sont générées dans `personnes/`, `familles/`, `sources/` et `patronymes/` ;
les autres notes ne sont ni déplacées ni modifiées, ni par `notes_generer`, ni par l'organisation des pièces.

- **Analyse** : le modèle lit les notes pour en tirer des pistes. Une information sans source citée reste une
  piste ou une hypothèse.
- **Rapprochements** : une personne ou un fait trouvé dans une note est cherché dans l'arbre ; tout ajout passe
  par `arbre_proposer`, puis accord, puis `arbre_appliquer`.
- **Texte libre et propriétés** : jamais réécrits. Pour une fiche générée, voir « Format d'une fiche » ; pour une
  note compagnon de pièce, voir [pièces](pieces.md#règles-de-sûreté).
- **Liens** : quand une organisation de pièces rendrait un lien caduc, le plan le signale (`references_notes`) sans le
  corriger.
- **Réorganisation** (déplacer, fusionner, renommer des notes) : jamais automatique ; un plan est présenté, puis
  exécuté seulement après accord explicite.

Parcours pas à pas : [organiser un fonds](../wiki/Organiser-un-fonds.md#reprendre-des-notes-markdown-existantes).

## Format d'une fiche

- **Frontmatter** (propriétés Dataview / Bases) : `id`, `type` (`personne` | `famille` | `source` | `patronyme` |
  `index`), `nom`, `patronyme`, `statut` (statut le plus faible parmi naissance, décès, filiation), `sosa`, `naissance`, `deces`,
  `lieux`, `sources` (liens), `journal` (ids des entrées), `vivant`, `mis_a_jour`. Les propriétés ajoutées à la
  main sont **conservées** (replacées en fin de frontmatter).
- **Sections générées** entre `<!-- genealogiste:debut NOM -->` et `<!-- genealogiste:fin -->` : identité et
  liens familiaux, faits et statut de preuve, sources, prochaines sources, recherches du journal. Elles sont
  réécrites à chaque génération : ne pas écrire dedans. Voir « Marqueurs historiques » pour la forme
  `<!-- sosa:debut NOM -->` / `<!-- sosa:fin -->`.
- **`## Notes libres`** : jamais modifiée par l'outil. `notes_ajouter` y ajoute seulement une entrée datée, sous
  `### Hypothèses`, `### Pistes`, `### Conclusions`, `### Courriers`, `### À faire` ou `### Notes`.

Régénérer sans changement dans l'arbre ne modifie **aucun** fichier (`mis_a_jour` ne bouge que si le contenu
change).

## Marqueurs historiques (`sosa:`)

Les fiches écrites avant le renommage (#182) portent `<!-- sosa:debut NOM -->` / `<!-- sosa:fin -->`. Les deux
formes sont **lues sans limite de durée** (sauvegardes, anciens vaults) :

- **Régénération** : une fiche régénérée (`notes_generer`, régénération automatique) est écrite dans la forme
  de `GENEALOGISTE_MARQUEURS` ; ses anciennes balises sont converties, le texte hors balises n'est jamais touché.
- **Fiche mixte** (même section sous les deux formes) : un seul bloc en sortie, avec le contenu régénéré ; le
  texte libre entre ou autour des blocs est conservé.
- **Migration explicite** : `marqueurs_migrer_proposer` liste les fiches concernées avec le diff (seules les
  balises changent) et renvoie un jeton ; après accord, `marqueurs_migrer_appliquer` réécrit ces fiches (refus si
  l'une a changé entre-temps) et fait **un commit** des seuls fichiers migrés si le répertoire des notes est dans
  un dépôt Git. Une section présente deux fois avec des contenus différents est laissée en l'état et listée dans
  `a_regenerer` : `notes_generer(id)` la résout. Deuxième exécution : rien à migrer, pas de jeton.
- **Vault partagé avec une ancienne version** : `GENEALOGISTE_MARQUEURS=sosa` garde l'ancienne forme en écriture
  (la migration est alors désactivée).

## Kit Obsidian

`notes_generer("tout")` dépose de quoi exploiter les fiches sans extension à développer :

```
<NOTES_DIR>/_genealogiste/
├── vues/Genealogiste.base       # Obsidian Bases (intégré) : Ascendance (Sosa), À reprendre, Personnes,
│                                #   Familles, Sources, Patronymes, Recherches et courriers
├── vues/Tableau de bord.md      # mêmes vues en Dataview (extension communautaire) + sans source,
│                                #   courriers sans réponse, fiches récentes
├── modeles/Recherche.md         # fiche de recherche (question, sources consultées y compris négatives,
│                                #   analyse, conclusion, prochaine source) : type: recherche
├── modeles/Courrier.md          # demande à un service d'archives : type: courrier, envoye_le, reponse_le
└── .kit.json                    # empreintes des fichiers déposés
<vault>/.obsidian/snippets/genealogiste.css
```

- **Filtres sur la propriété `type`** : les vues fonctionnent quel que soit l'emplacement des notes dans le vault.
  Les modèles (dans `_genealogiste/`) sont exclus des vues de recherches et courriers.
- **Extrait CSS** : déposé dans `.obsidian/snippets/` du vault qui contient les notes (le répertoire des notes ou
  le premier parent qui a un dossier `.obsidian`). Sans vault détecté, il reste dans `_genealogiste/` à copier
  à la main. À activer dans *Réglages → Apparence → Extraits CSS* : les lignes de balises
  `<!-- genealogiste:debut … -->` / `<!-- genealogiste:fin -->` (ou `sosa:`) sont surlignées en mode source et aperçu en direct, pour repérer
  les sections régénérées (tout commentaire HTML seul sur sa ligne l'est aussi).
- **Modèles** : régler le dossier de l'extension *Modèles* sur `_genealogiste/modeles` (ou le dossier
  équivalent de Templater). Si les notes sont dans un sous-dossier du vault, préfixer ce chemin par
  ce sous-dossier, par exemple `Genealogie/_genealogiste/modeles` ; `kit.consigne` donne le chemin adapté.
- **Mise à jour** : un fichier du kit n'est remplacé que s'il est absent ou identique à la version déposée
  précédemment. Une copie modifiée est conservée et signalée dans `kit.conserves` ; la supprimer pour reprendre
  la version du plugin. Une copie personnelle non UTF-8 est également conservée. Un lien symbolique
  sur une cible est refusé (`kit.refuses`) ; si le dossier du kit ou son manifeste est lié, le dépôt du
  kit est refusé avant toute lecture du manifeste ou écriture.
- Une génération ciblée (une personne, un lot) ne touche pas au kit.

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

## Médias confidentiels connus (0.14.1)

Avant de lister ou d’incorporer une pièce, les fiches de personnes et de patronymes consultent la
provenance du modèle : marques privées, liens directs ou citations d’un porteur masqué, ressources
partagées avec un défunt, citations et événements privés, citations des associations désignant un
porteur masqué (par identifiant ou par nom). Une règle commune avec les exports détermine
les ressources exclues ; le filtrage des noms de fichiers reste un complément, avec prise en charge
des noms et prénoms d’un seul caractère.

Les chemins des médias sont résolus par la règle commune (`docs/operations.md`, « Résolution d'un chemin de
média ») : données, répertoire des médias puis arborescence des pièces ; une référence relative et une
référence absolue vers le même fichier sont exclues ensemble. Une référence relative ambiguë (fichiers
différents sous deux racines) n'affiche aucune image (ligne « chemin ambigu ») et, pour un média privé, tous
ses candidats restent exclus. Les fichiers physiques ne sont ni
supprimés ni modifiés. En mode `complet`, les médias des vivants peuvent être affichés, mais les marques
privées explicites restent appliquées. Une pièce non enregistrée dans le modèle et sans nom
identifiant ne peut pas être classée confidentielle par ces seuls contrôles.

Après mise à jour ou changement de politique de visibilité, lancer `notes_generer("tout")` pour nettoyer
toutes les sections générées existantes. Les textes libres et propriétés manuelles restent conservés
et doivent être relus avant tout partage. Les notes demeurent un espace de travail privé.
