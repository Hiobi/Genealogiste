# Organiser un fonds généalogique

Un fonds, ici, c’est simplement un dossier : scans d’actes, photos d’archives, PDF, captures d’arbres en
ligne, enregistrements, parfois des notes Markdown. Il n’a pas besoin d’être un vault Obsidian. Le plugin
peut le ranger, le compléter et le relier à l’arbre, toujours en deux temps : un plan présenté, puis une
application après votre accord.

Trois points d’entrée :

1. [Organiser un dossier existant](#1-organiser-un-dossier-existant) ;
2. [Créer une base depuis zéro](#2-créer-une-base-depuis-zéro) ;
3. [Partir d’un arbre GEDCOM ou Gramps Web](#3-partir-dun-arbre-gedcom-ou-gramps-web).

Les sections suivantes valent pour les trois : [notes Markdown existantes](#reprendre-des-notes-markdown-existantes),
[méthode](#méthode--ce-quun-fichier-prouve-et-ne-prouve-pas), [de l’image à l’arbre](#de-limage-à-larbre)
et [archives en ligne](#archives-en-ligne--ce-qui-est-automatisé-et-ce-qui-ne-lest-pas).
Le détail technique reste dans [Pièces et médias](../docs/pieces.md) et [Notes et Obsidian](../docs/notes.md).

**Avant de commencer** : faire une copie du dossier ou vérifier sa [sauvegarde](Sauvegardes.md). Les outils
ne suppriment rien et savent annuler, mais une copie reste la meilleure assurance.

## 1. Organiser un dossier existant

**Demandes types**

> Organise ce dossier de scans : /chemin/prive/genealogie
>
> Range mes photos d’archives, je ne sais plus ce qu’il y a dedans.
>
> Classe mes PDF d’actes et repère les doublons.

ou directement `/genealogiste:organise /chemin/prive/genealogie`, et `/genealogiste:organise /chemin triage`
pour lancer aussi l’identification des fichiers opaques.

**Prérequis** : le plugin [installé](Installation.md) ; un dossier privé, hors du dépôt du plugin. Aucun arbre
n’est nécessaire pour ranger. Obsidian est facultatif.

**Configuration** : aucune pour un dossier autonome, qui devient lui-même la racine du rangement. Pour que les
pièces archivées plus tard arrivent dans ce même dossier, fixer
`GENEALOGISTE_MEDIA_DIR=/chemin/prive/genealogie/documents` : l’arborescence (`documents/`, `photographies/`,
`archives/`, `_À trier/`) part alors du dossier parent ([médias dans le vault](../docs/pieces.md#médias-et-rapports-dans-le-vault)).

**Plan présenté**

1. Inventaire (`pieces_inventaire`) : comptes par type, patronymes, doublons, pièces déjà rangées, fichiers
   ignorés (notes `.md`, textes).
2. Proposition (`pieces_proposer`) : racine, périmètre, résumé par dossier, doublons isolés dans
   `archives/Doublons/`, nombre de pièces envoyées dans `_À trier/`, extrait de l’aperçu, chemin du plan complet
   (TSV). Rien n’a bougé à ce stade.
3. Si des notes Markdown pointent vers des pièces déplacées ou renommées, la liste `references_notes` les
   montre avant l’accord (voir plus bas).
4. Triage des noms opaques (`IMG_1234.jpg`, UUID, captures) : l’agent `trieur` lit chaque image en aperçu et
   propose un nom à la [convention](../docs/pieces.md#convention-de-nommage), avec un niveau de confiance. Ces
   renommages forment un **second plan**, présenté à son tour.

**Validations** : une pour le rangement, une pour chaque lot de renommages, une autre pour toute proposition
d’arbre qui en découle. Un refus, ou l’absence de réponse, ne déplace rien : le jeton expire au bout d’une heure.

**Résultat attendu**

- pièces identifiées dans `documents/<type>/<NOM>/` ou `photographies/<NOM>/` ;
- doublons (même contenu, empreinte SHA-256) dans `archives/Doublons/`, jamais supprimés ;
- pièces non identifiables dans `_À trier/` ;
- pièces déjà nommées et rangées, notes Markdown et dossiers cachés laissés en place ;
- un contrôle : autant de fichiers avant et après, empreintes identiques ;
- un journal `_organisation/<date>.tsv`. Relancer l’organisation répond « Rien à déplacer ».

**Annulation** : `pieces_proposer(dossier, annuler="<journal>.tsv")`, puis accord, puis `pieces_appliquer`.
Annuler les journaux du plus récent au plus ancien. Le retour est exact, notes compagnons comprises.

**Pièces déjà rangées** : une pièce placée sous `documents/` n’est jamais déplacée par une nouvelle
organisation. Quand le classement évolue (en 0.27.0, une déclaration de succession passe de
`documents/Notaires/` à `documents/Enregistrement/`, code `MPD`), la déplacer à la main, ou la remettre dans
`_À trier/` avant de relancer l’organisation. Les codes de type sont listés dans la
[convention](../docs/pieces.md#codes-de-type).

## 2. Créer une base depuis zéro

**Demandes types**

> Je commence ma généalogie : prépare un espace de recherche dans /chemin/prive/famille.
>
> Ajoute mon arrière-grand-père Jean DUPONT, né vers 1880 à Erre, sans source pour l’instant.

**Prérequis** : le plugin installé ; un dossier privé vide. Commencer de préférence par le
[tutoriel fictif](Demarrage.md) pour voir les propositions sans risque.

**Configuration** (dans l’environnement ou le `.env` du dossier de données, voir [Configuration](Configuration.md)) :

| Variable | Exemple | Rôle |
|---|---|---|
| `GENEALOGISTE_DATA_DIR` | `/chemin/prive/famille/donnees` | arbre `arbre.ged`, journal, historique Git |
| `GENEALOGISTE_MEDIA_DIR` | `/chemin/prive/famille/documents` | pièces archivées, rangées à la convention |
| `GENEALOGISTE_NOTES_DIR` | `/chemin/prive/famille` | fiches Markdown générées depuis l’arbre |
| `GENEALOGISTE_BACKEND` | `fichier` (défaut) | arbre local versionné ([mode fichier](Mode-fichier.md)) |

`GENEALOGISTE_RAPPORTS_DIR` et `GENEALOGISTE_EXPORTS_DIR` sont facultatifs. Avec ces réglages, un seul dossier
contient pièces (`documents/`, `photographies/`) et fiches (`personnes/`, `familles/`, `sources/`) et peut
être ouvert dans Obsidian. Le `.obsidian/` n’est pas nécessaire.

**Plan présenté**

1. `arbre_info` : backend `fichier` et 0 personne.
2. Saisie des premières personnes avec `/genealogiste:ajoute` : chaque ajout est une proposition (diff,
   alertes). Sans citation, un fait est refusé, sauf mention explicite « non sourcé » avec un motif.
3. Premières pièces : `piece_archiver` pour un acte en ligne ou un fichier téléchargé, puis rattachement à
   l’arbre (voir [de l’image à l’arbre](#de-limage-à-larbre)).
4. `notes_generer("tout")` : fiches, index et kit Obsidian.

**Validations** : chaque écriture dans l’arbre (`arbre_appliquer`) ; l’archivage d’une pièce crée des fichiers
mais n’écrit pas dans l’arbre.

**Résultat attendu** : un arbre versionné (un commit par modification acceptée), des pièces nommées et rangées
avec leur note compagnon, des fiches de personnes avec leurs pièces et le statut de preuve de chaque fait.

**Annulation** : une modification d’arbre se défait par `arbre_annuler_modification` puis `arbre_appliquer`
([mode fichier](Mode-fichier.md#modifier-sans-perdre-la-trace)). Une pièce archivée reste un fichier ordinaire :
la déplacer avec `/genealogiste:organise`, jamais à la main.

## 3. Partir d’un arbre GEDCOM ou Gramps Web

**Demandes types**

> Importe mon arbre /chemin/prive/copie-arbre.ged, puis organise les scans qui vont avec.
>
> Mon arbre est dans Gramps Web : prépare les fiches Markdown et range mes pièces.

**Prérequis** : une **copie** du GEDCOM (5.5.1 ou 7), ou un compte local Gramps Web dédié au rôle *Editor*
([Gramps Web](../docs/gramps-web.md#configuration)).

**Configuration**

- GEDCOM : `GENEALOGISTE_BACKEND=fichier` (défaut), plus `GENEALOGISTE_MEDIA_DIR` et `GENEALOGISTE_NOTES_DIR`
  comme dans l’entrée 2.
- Gramps Web en direct : `GENEALOGISTE_BACKEND=gramps`, `GENEALOGISTE_GRAMPS_URL`, `GENEALOGISTE_GRAMPS_USER`,
  `GENEALOGISTE_GRAMPS_PASSWORD`. Pour une simple copie locale de l’arbre Gramps, rester en mode `fichier`
  et utiliser `gramps_tirer`.

**Plan présenté**

1. `/genealogiste:import <chemin.ged>` (`arbre_importer_gedcom`, mode `ajouter` par défaut ; aussi `.gramps` et
   `.gpkg` de Gramps Desktop, [voir le guide](../docs/gramps.md#import-depuis-gramps-desktop)) ou `gramps_tirer` :
   bilan (personnes, familles, sources, avertissements) et extrait du diff. En mode `gramps`, pas d’import :
   l’arbre est lu directement.
2. `arbre_coherence` et recoupement des doublons probables (`/genealogiste:recoupe`). Rien n’est fusionné
   automatiquement.
3. `notes_generer("tout")` : une fiche par personne, famille, source et patronyme.
4. Organisation du dossier de pièces comme dans l’entrée 1. Les fichiers déjà référencés par un média de
   l’arbre ne sont **pas déplacés** ; `pieces_proposer(dossier, suivre_medias=true)` les range et prépare
   ensuite une proposition d’arbre (`modifier_media`) qui demande un second accord
   ([suivre les médias](../docs/pieces.md#suivre-les-médias-de-larbre)).

**Validations** : l’import ; chaque rangement ; chaque proposition d’arbre, y compris la mise à jour des
chemins de médias.

**Résultat attendu** : l’arbre importé, signalé comme **non vérifié** (un import ne vaut pas preuve) ; des fiches
Markdown liées entre elles ; des pièces rangées dont les références de médias restent valides.

**Annulation** : import et modifications d’arbre par `arbre_annuler_modification` puis `arbre_appliquer` (en
mode `gramps`, transaction inverse) ; rangement par son journal TSV. Si un rangement a déplacé des médias de
l’arbre, son annulation prépare aussi la proposition inverse.

## Reprendre des notes Markdown existantes

Vos notes de recherche (`.md`) ne sont **jamais réécrites** par l’organisation. Le traitement est le suivant.

- **Analyse.** L’inventaire les compte parmi les fichiers ignorés ; le modèle peut les lire pour en tirer des
  pistes (noms, dates, lieux, cotes). Ce qu’il en déduit reste une piste tant qu’aucune source n’est citée.
- **Rapprochement avec l’arbre.** Une personne ou un fait trouvé dans une note est recherché dans l’arbre
  (`arbre_recherche`, `arbre_fiche`). Un ajout ou une correction passe par `arbre_proposer`, avec un diff et
  votre accord. Une note ne modifie jamais l’arbre par elle-même.
- **Texte libre et propriétés.** Une note ordinaire n’est ni déplacée ni modifiée. Une note compagnon de pièce
  (`type: piece` dans son frontmatter, même nom que la pièce) suit sa pièce : seules la propriété `fichier`,
  le titre et l’image générée changent, la section `## Notes` et les autres propriétés restent. Dans les fiches
  générées, la section `## Notes libres` et les propriétés ajoutées à la main sont conservées
  ([format d’une fiche](../docs/notes.md#format-dune-fiche)).
- **Liens.** Un lien wiki par nom (`[[IMG_1234.jpg]]`) reste valide si la pièce change seulement de dossier.
  Il devient caduc si elle est renommée ; un lien par chemin (`[acte](scans/acte.pdf)`) devient caduc dès qu’elle
  bouge. Le plan signale ces liens dans `references_notes` (note, lien, ancien et nouveau chemin), **sans les
  corriger**. Vous choisissez alors : garder l’ancien nom, corriger les liens dans Obsidian, ou demander une
  correction note par note, présentée avant d’être faite.
- **Réorganisation des notes.** Déplacer ou fusionner des notes n’est pas automatique. Le modèle peut proposer
  un plan (quelle note, où, pourquoi) ; rien n’est fait sans votre accord explicite.

## Méthode : ce qu’un fichier prouve et ne prouve pas

**Un nom de fichier n’est jamais une preuve.** Le classement automatique lit le nom pour ranger : un type ou un
patronyme ainsi déduit est une hypothèse de rangement, pas un fait généalogique. En cas de doute, la pièce
reste dans `_À trier/`.

Ce qu’il faut relever pour chaque pièce, et que la [convention](../docs/pieces.md#convention-de-nommage) et la
note compagnon conservent :

| Élément | Ce que c’est | Exemple |
|---|---|---|
| provenance | d’où vient la pièce : service, site, cousin, archive familiale ; date de consultation | lien de visionneuse, `consulte_le` |
| dépôt | l’institution qui conserve l’original | `AD59`, `AM Lille`, `SHD` |
| cote | la référence du document dans l’inventaire du dépôt, à vérifier sur place | `5 Mi 023 R 008` |
| vue et numéro d’acte | la page numérisée et l’acte dans cette page | `p.466 n.36` |
| source et citation | la source décrit le document (registre, fonds) ; la citation pointe un passage précis (vue, acte) | `S3` et sa citation |

- **Transcription incertaine** : marquer les mots douteux `(?)`, les passages illisibles `[…]`, les
  abréviations développées entre `[ ]`, et donner une confiance par champ (skill `paleographie`). Ne jamais
  compléter un nom ou une date « au plus probable ».
- **Hypothèse ou fait** : un fait n’est établi qu’avec une citation. Le statut de preuve (confirmé, probable,
  hypothèse, contradictoire, réfuté) se calcule sur des sources **indépendantes**. Une capture d’arbre en ligne
  (`CAPTURE`) est une piste, pas une source.
- Une cote suggérée par le plugin est une indication : la confirmer dans l’inventaire du service.

## De l’image à l’arbre

Le parcours complet pour un acte, en ligne ou déjà sur votre disque :

1. **Aperçu** : `archive_image(source)` en 800 px et en gris. La source peut être un fichier local, un lien IIIF,
   un ARK Gallica ou une vue AD59.
2. **Recadrage** : `archive_image(source, region="pct:x,y,l,h", largeur=1500)` sur l’acte seul. Ces images restent
   dans le cache, hors du fonds.
3. **Transcription** : `/genealogiste:transcris <source>`, avec les marques d’incertitude ci-dessus.
4. **Original archivé** : `piece_archiver(source, personnes=[…], type_piece=…, commune=…, cote=…, acte=…,
   source_arbre="S3")` télécharge la vue entière en couleur, la nomme et la range. Une vue déjà archivée n’est
   jamais retéléchargée.
5. **Note compagnon** : créée à côté de la pièce (ARK, URL, vue, dépôt, cote, date de consultation, empreinte,
   conditions de réutilisation, liens vers les fiches). Votre transcription et vos remarques vont sous
   `## Notes`, jamais réécrite.
6. **Proposition de rattachement** : `piece_archiver` renvoie les opérations suggérées (`ajouter_media`,
   `ajouter_citation`). Le modèle les présente par `arbre_proposer`, avec le diff ; `arbre_appliquer` n’a lieu
   qu’après votre accord. Une image seule ne confirme pas une filiation.

Pour une pièce déjà rangée par `/genealogiste:organise`, les étapes 1 à 3 s’appliquent à son chemin. L’étape 4
n’est pas nécessaire : `piece_archiver` sur un fichier local en fait une copie, sauf s’il porte déjà le nom et
l’emplacement que l’outil calculerait. La pièce se rattache directement par `arbre_proposer`
(`ajouter_media` avec son chemin relatif à l’arborescence des pièces), toujours après accord.

## Archives en ligne : ce qui est automatisé et ce qui ne l’est pas

- **Recherche de registres** : `archives_registres` cherche par commune et année dans les registres de neuf
  services (AD59, AD14, AD19, AD25, AD27, AD37, AD39, AD51, AD55, AD58, AD69, AD80, AD90, AD91, AD972). Pour les autres départements, la recherche
  dans l’inventaire reste manuelle ;
  `archives_service` donne la fiche du service et `liens_recherche` des liens de recherche. Un registre trouvé ne
  prouve pas que l’acte y figure.
- **Téléchargement**, du plus automatique au plus manuel :
  1. **IIIF** (manifeste, `info.json`, URL d’image IIIF) : fonctionne quel que soit le pays ;
  2. **visionneuse reconnue** : AD59 (ARK de vue) et Gallica (ARK) ;
  3. **URL directe** d’une image (`.jpg`, `.png`, `.tif`…) : téléchargée telle quelle, sans pérennité garantie ;
  4. **téléchargement manuel** depuis la visionneuse du service (bouton d’export, capture pleine page), puis
     chemin du fichier local. C’est le cas des PDF et des services sans adaptateur.
- Un défi anti-robot met le service en pause : ouvrir la vue dans le navigateur et fournir l’image téléchargée.
- Le [catalogue des services](Services-archives.md) indique, service par service, le lien à fournir. Le
  [référentiel des archives](../docs/archives.md) donne les fonds et séries à chercher.
