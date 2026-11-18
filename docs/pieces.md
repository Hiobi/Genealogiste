# Pièces : convention de nommage et organisation d'un dossier existant

Un dossier de pièces existant (scans d'actes, photos, PDF d'AD ou de Geneanet, captures d'arbres en ligne,
audio, ancienne base GeneWeb…) s'organise en trois temps :

1. **inventaire et classement** par règles : `/genealogiste:organise <dossier>` ;
2. **triage** des pièces non identifiables : l'agent `trieur` lit chaque image et propose un nom ;
3. **application** du plan après ton accord. L'opération est **réversible** et ne fait **aucune suppression**.

Le même mécanisme que `arbre_proposer` s'applique : un plan est présenté, puis exécuté seulement avec son jeton
et après accord explicite.

Pour les pièces en ligne, consulter les [services pris en charge et leurs limites](../wiki/Services-archives.md)
avant de choisir un lien de visionneuse, IIIF ou de fichier.

## Convention de nommage

```
NOM Prénom[ + NOM Prénom] -- COMMUNE - DÉPÔT - TYPE [AAAA-AAAA] - cote - p.vue n.acte.ext
```

Exemple : `DUPONT Jean + MARTIN Marie -- ERRE - AD59 - NMD [1829-1870] - 5 Mi 023 R 008 - p.466 n.36.jpg`

| Segment | Contenu | Exemple |
|---|---|---|
| personnes | `NOM Prénom` (nom en capitales), plusieurs reliées par ` + ` ; la première donne le dossier patronymique | `DUPONT Jean + MARTIN Marie` |
| `--` | sépare les personnes de la description | |
| commune | en capitales | `ERRE` |
| dépôt | sigle | `AD59`, `AM Lille`, `SHD`, `ANMT` |
| type et années | code (tableau ci-dessous), puis années entre crochets | `NMD [1829-1870]`, `D [1880]` |
| cote | telle que dans l'inventaire (`/` remplacé par `-`) | `5 Mi 023 R 008` |
| localisation | `p.` vue, `n.` numéro d'acte | `p.466 n.36` |

Les segments absents sont omis : `DUPONT Jean -- PHOTO.jpg`. Les noms sont rendus compatibles avec Windows et
Nextcloud. Les caractères `? : * " < > | / \` sont remplacés par `-`. Les espaces et points finaux sont
retirés, les noms réservés (`CON`, `NUL`…) préfixés, et la longueur est bornée à 200 octets.

`piece_nommer` produit ce nom à partir de ce que tu sais ou de l'arbre. Il accepte des identifiants de
personnes (`I12`) et une source (`S3`), dont il reprend le sigle du dépôt et la cote. Il ne renomme rien.

### Codes de type

| Code | Pièce | Classée dans |
|---|---|---|
| `N` `B` `M` `D` `S` | naissance, baptême, mariage, décès, sépulture | `documents/État civil/<NOM>/` |
| `NMD` `BMS` `TD` | registres, tables décennales | `documents/État civil/<NOM>/` |
| `RM` | registre ou fiche matricule | `documents/Militaire/<NOM>/` |
| `ANMT` | fiche de mineur (Archives nationales du monde du travail) | `documents/Mines (ANMT)/<NOM>/` |
| `PM` | dossier du personnel des mines (houillères) | `documents/Mines (ANMT)/<NOM>/` |
| `NOT` | acte notarié : contrat de mariage, testament, acte de notoriété, partage, inventaire, déclaration de succession, attestation immobilière… | `documents/Notaires/<NOM>/` |
| `CNI` | carte d'identité | `documents/Divers/<NOM>/` |
| `COUR` | courrier ou démarche : demande d'acte (récapitulatif service-public, lettre à une mairie), réponse d'un service, lettre | `documents/Divers/<NOM>/` |
| `REC` | recensement | `documents/Divers/<NOM>/` |
| `CAPTURE` | capture d'arbre en ligne (Geneanet, Filae…) : une piste, pas une source | `documents/Divers/<NOM>/` |
| `SIGN` | signature | `documents/Signatures/<NOM>/` |
| `PHOTO` | photographie | `photographies/<NOM>/` |
| `TOMBE` | sépulture photographiée | `photographies/Sépultures/<NOM>/` |
| `LIEU` | lieu | `photographies/Lieux/` |
| audio | témoignage oral (`.mp3`, `.m4a`, `.wav`…) | `documents/Témoignages oraux/[<NOM>/]` |
| GeneWeb, GEDCOM, INSEE | bases (`*.gwb` déplacé en bloc), `.ged`, fichiers bruts du fichier des décès | `archives/GeneWeb/`, `archives/GEDCOM/`, `archives/INSEE/` |

Sans patronyme ou sans type reconnu, la pièce va dans `_À trier/` en attendant le triage.

**Actes notariés : un seul code.** La nature précise s'écrit en libellé libre après le code, dans le même
segment : `type_piece="NOT testament"` donne `DUPONT Jean -- ERRE - Étude Leroy - NOT TESTAMENT [1850].pdf`
(le segment type est en capitales), l'étude se place dans le segment dépôt. Le classement ne lit que le code.

**Actes notariés et série 3 E (#223).** Le code `NOT` est relié au type d'archives `notaire` du vocabulaire
commun ([archives.md](archives.md#types-de-documents-communs--129)), dont la série indicative est la sous-série
3 E des archives départementales (minutes notariales, classées par étude ; les répertoires du notaire
localisent l'acte). Pour une pièce `NOT`, `piece_nommer` et `piece_archiver` renvoient un bloc `archives` :
`type_document` (`notaire`), `serie` (texte du vocabulaire), `cote` et une `consigne` :

| `cote` | Situation | Effet |
|---|---|---|
| `serie_3e` | la cote commence par `3 E` ou `3E` (`3 E 52/123`, `3E 1234`) | acceptée telle quelle |
| `a_completer` | aucune cote | suggestion : chercher la cote `3 E <étude>/<article>` dans l'inventaire du service |
| `hors_3e` | autre cote | conservée telle quelle, jamais refusée : vérifier le classement du service |

La suggestion porte sur le cadre de classement des archives départementales, pas sur un service donné :
la forme exacte de la cote (numéro d'étude, article) dépend de l'inventaire. Des minutes peuvent être
conservées ailleurs ; le référentiel signale par exemple le Minutier central des notaires de Paris aux
Archives nationales (entrée `AN`). Aucune autre exception n'est déduite.

Dans un nom à la convention sans segment type, une cote 3 E suffit à reconnaître un acte notarié :
`DUPONT Jean -- ERRE - AD59 - 3 E 1234.pdf` est lu `NOT` et classé dans `documents/Notaires/DUPONT/`. Un type
explicite prime toujours (`… - M [1850] - 3 E 1234` reste `M`).

**Détection depuis un nom libre** (premier motif trouvé). Un nom à la convention est lu par son code ;
sinon les mots du nom sont essayés dans cet ordre :

1. `COUR` : « demande d'acte », « courrier », « service-public » (une demande d'acte de naissance est un
   courrier, pas l'acte) ;
2. registres, matricules, `PM` (« personnel des mines »), `ANMT`, `CNI` (« carte d'identité »), recensement,
   signature, capture, tombe ;
3. `NOT` : notaire, notarié, notoriété, testament, contrat de mariage, partage, succession, attestation
   immobilière, hypothèque(s). Placé **avant** `N`, `M`, `D` : « attestation immobilière après décès »
   ou « contrat de mariage » est notarié ; « acte de mariage » reste `M` ;
4. `N`, `B`, `M`, `D`, `S` ;
5. `COUR` : « lettre », « réponse », seulement si aucun type d'acte n'a été reconnu ;
6. `PHOTO`.

Le code `PM` n'est pas déduit du sigle seul (trop ambigu dans un nom libre) : l'écrire dans le segment type.

## Arborescence produite

```
documents/{État civil,Militaire,Mines (ANMT),Notaires,Signatures,Témoignages oraux,Divers}/<NOM>/
photographies/<NOM>/ · photographies/Sépultures/<NOM>/ · photographies/Lieux/
archives/{GeneWeb,GEDCOM,INSEE,Doublons}/
courriers/                seulement par dossier explicite (jamais déduit du type)
_À trier/
_organisation/            journaux TSV des déplacements
```

## Règles de sûreté

- **Rien n'est déplacé sans plan accepté.** `pieces_proposer` ne modifie rien. `pieces_appliquer(jeton)`
  demande confirmation (hook), et son jeton est à usage unique et valable une heure.
- **Jamais de suppression.** Les doublons (même SHA-256) vont dans `archives/Doublons/<chemin d'origine>`.
  On garde l'exemplaire déjà classé, sinon le premier par ordre de chemin.
- **Journal TSV** `_organisation/<date>.tsv` (`ancien_chemin`, `nouveau_chemin`, `motif`, `sha256`). Il est
  écrit et synchronisé ligne par ligne. Pour annuler : `pieces_proposer(dossier, annuler="<journal>.tsv")`,
  puis `pieces_appliquer`. Les journaux avec notes compagnons contiennent aussi leurs contenus avant/après
  et leurs empreintes, pour restaurer exactement le texte initial. Ils restent privés dans le fonds.
- **Contrôle** : le dossier doit être identique au plan (nombre de fichiers et empreintes), sinon le plan est
  refusé. Chaque fichier est vérifié avant son déplacement. Après l'application, le résultat indique le
  nombre de fichiers avant et après et compare les empreintes.
- **Hors du périmètre**, et donc jamais touchés : les dossiers `personnes/`, `familles/`, `sources/` et `patronymes/`
  générés par les notes ([notes.md](notes.md)), les dossiers et fichiers cachés (`.obsidian`, `.git`), les
  liens symboliques, les notes Markdown ordinaires et les fichiers texte qui ne sont pas des fichiers INSEE. Une note
  de même nom de base que la pièce et portant `type: piece` suit celle-ci ; `fichier` et son image
  incorporée sont actualisés. La section `## Notes` et les autres propriétés sont préservées. Une note
  modifiée depuis le plan bloque l’application avant tout déplacement.
- **Médias de l'arbre** : par défaut, un fichier référencé par un média de l'arbre n'est pas déplacé (la
  référence casserait) ; il est listé dans `references_arbre_non_deplacees`. Avec `suivre_medias=true`, il
  est rangé comme les autres pièces et sa référence est mise à jour (voir
  [Suivre les médias de l'arbre](#suivre-les-médias-de-larbre)).
- Tous les déplacements restent **dans la racine affichée** (chemins résolus et confinés, voir
  [securite.md](securite.md)) : un nom proposé comme `../x.jpg` se réduit à `x.jpg`. La racine du disque et
  le dossier personnel sont refusés.
- Déplacements par renommage atomique, sans copie puis suppression.

## Triage des pièces non identifiables

L'agent `trieur` traite `_À trier/` et les noms opaques (UUID, `IMG_…`, `Capture d'écran…`, identifiants Find a
Grave) :

1. il lit chaque image avec `archive_image` en aperçu économe (800 px, gris), et recadre seulement si c'est
   nécessaire ;
2. il rend le tableau `actuel → proposé | confiance (haute, moyenne, basse) | résumé`, avec des noms
   produits par `piece_nommer` ;
3. il signale les personnes présumées vivantes (`arbre_vivant`) et les faits nouveaux, sous forme d'une
   proposition `arbre_proposer` à valider. **Il n'écrit jamais dans l'arbre** ;
4. il laisse les pièces illisibles dans `_À trier/` avec un nom descriptif (`illisible - acte manuscrit
   XVIIIe - 1.jpg`) ;
5. il passe les renommages à `pieces_proposer(dossier, renommages=[{actuel, propose}], seulement_renommages=true)`. Chaque pièce est
   reclassée d'après son nouveau nom.

### Dossier explicite

Quand aucun code ne couvre la pièce, un renommage peut imposer son dossier :
`{"actuel": "_À trier/scan.pdf", "propose": "DUPONT Jean -- demande acte D [1995].pdf", "dossier": "courriers/DUPONT"}`.
`propose` reste un **nom de fichier** : un chemin écrit dans `propose` est réduit à son nom et ne change pas le
dossier. `dossier` est contrôlé avant tout plan :

- relatif à la racine affichée, sous `documents/`, `photographies/` ou `courriers/` uniquement ;
- jamais `personnes/`, `familles/`, `sources/`, `patronymes/`, `archives/` ni `_À trier/` ;
- ni `..`, ni chemin absolu, ni `\`, ni dossier caché, ni caractère ou nom interdit sous Windows ;
- un lien symbolique qui mène hors de la racine ou vers un autre dossier est refusé.

Un dossier refusé rejette tout le plan (`erreur`), sans rien déplacer. Le plan se présente et s'applique
ensuite comme les autres (`pieces_appliquer` après accord). `courriers/` compte désormais parmi les dossiers
classés : une organisation suivante n'en déplace plus les pièces, comme `documents/` ou `photographies/`.

## Médias et rapports dans le vault

| Variable | Défaut | Rôle |
|---|---|---|
| `GENEALOGISTE_MEDIA_DIR` | `<données>/medias` | images d'actes (`media_enregistrer`, `archive_image`), par exemple `<vault>/documents` |
| `GENEALOGISTE_RAPPORTS_DIR` | `<données>/rapports` | rapports de preuve (`rapport_enregistrer`) |
| `GENEALOGISTE_EXPORTS_DIR` | `<données>/exports` | exports GEDCOM, GeneWeb, Gramps XML… |
| `GENEALOGISTE_CACHE_IMAGES_DIR` | `<données>/cache-images` | aperçus et recadrages de lecture (`archive_image`), jamais dans le vault ni dans Git |
| `GENEALOGISTE_CACHE_PDF_DIR` | `<données>/cache-pdf` | Markdown extrait des PDF (`pdf_markdown`), jamais dans le vault ni dans Git |
| `GENEALOGISTE_TESSERACT` | `tesseract` (PATH) | binaire Tesseract utilisé pour l'OCR des PDF scannés |

Quand le répertoire des médias s'appelle `documents` (ex. `<vault>/documents`), l'arborescence des pièces
(`documents/`, `photographies/`, `archives/`, `_À trier/`) part de son dossier parent, le vault : une pièce classée
va dans `<vault>/documents/État civil/DUPONT/`, une photo dans `<vault>/photographies/DUPONT/`.

- Un média situé dans le répertoire de données est référencé en relatif (`medias/…`). Hors de celui-ci, sous
  l'arborescence des pièces, il l'est en relatif à celle-ci (`documents/État civil/…`, `photographies/…`) pour
  ne pas dépendre de la machine (#193) ; ailleurs, en chemin absolu. Un chemin relatif présent sous deux
  racines avec des contenus différents est refusé comme ambigu (règle : `docs/operations.md`, « Résolution
  d'un chemin de média »). L'envoi vers Gramps Web accepte ces racines et refuse tout le reste.
- Un rapport écrit hors du répertoire de données n'est **pas versionné** par Genealogiste (`commit: null`).
- `media_enregistrer(chemin, nom, classer=true)` range directement selon la convention :
  `documents/<type>/<NOM>/`, ou `_À trier/` si le nom ne suffit pas.

Ces variables remplacent le contournement par liens symboliques (`<données>/medias → <vault>/documents`).

## Archiver une pièce consultée en ligne (ARK, IIIF)

`archive_image` sert à **lire** (aperçu 800 px en gris, recadrages) : ses images restent dans le cache, hors du
vault. Sa réponse est minimale (chemin, vue, dimensions, coût) et ne porte pas la licence : celle-ci est conservée
ici, dans la note compagnon. Pour **conserver** une vue d'acte, `piece_archiver` :

1. télécharge la vue entière en **pleine résolution et en couleur** (IIIF `full/max`, repli `full/full`), ou
   résout un lien de visionneuse AD59, reprend un fichier local ou une URL directe. Un lien IIIF reste
   utilisable indépendamment du pays ; les autres visionneuses demandent un adaptateur qualifié ou un
   téléchargement manuel ;
2. la nomme selon la convention (vue renseignée d'après l'ARK ou le manifeste ; dépôt et cote repris de la
   source de l'arbre avec `source_arbre`, ou des métadonnées de la vue résolue) et la range dans `documents/<type>/<NOM>/` (sinon `_À trier/`) ;
3. écrit à côté une **note** `<même nom>.md` : propriétés Obsidian (`ark`, `url`, `url_image`, `service_iiif`,
   `manifeste`, `vue`, `depot`, `cote`, `consulte_le`, `sha256`, `reutilisation`), l'image affichée, des liens
   vers les fiches des personnes et de la source, et une section libre jamais réécrite ;
4. inscrit la pièce dans `<données>/pieces-archivees.jsonl` : une vue déjà archivée (même vue ou même contenu)
   n'est **jamais retéléchargée** ; même nom avec un autre contenu : suffixe « (2) » ;
5. renvoie les opérations à proposer (`ajouter_media`, puis `ajouter_citation` avec `citation_suggeree` : ARK,
   vue, `consultation: image`). Rien n'est écrit dans l'arbre sans `arbre_proposer` et ton accord.

Le même lien peut être utilisé pour l'aperçu, le recadrage et l'archivage. Une originale sans IIIF déjà
lue est réutilisée, sans nouveau téléchargement. La citation et le lien pérenne de la note privilégient
l'ARK de la vue ; l'URL technique de l'image reste distincte. Si seule une URL est connue, sa pérennité
n'est pas affirmée. La cote, le titre, la période et la déclaration de droits peuvent venir du service :
ce sont des métadonnées à contrôler, pas une transcription ni une preuve de filiation.

`nom_fichier` est facultatif et désigne un **nom complet** suivant la convention (` -- ` requis), jamais
un patronyme seul. L'omettre pour construire le nom avec `personnes`, `type_piece`, `commune`, `cote`,
`vue` et `acte`. `nom` reste un ancien alias avec avertissement. Le classement utilise les personnes et
le type fournis, y compris lorsqu'un nom complet personnalisé remplace le nom calculé. Les noms invalides
et références inconnues sont refusés avant de télécharger. `.md` est réservé à la note : un nom de pièce
avec cette extension est refusé ; une autre extension doit correspondre au contenu réellement reçu.
Sans extension d'image/PDF, celle de l'originale est ajoutée. Un ARK de manifeste ou de ressource n'est
pas transformé en identifiant de vue dans la citation suggérée.

Exemples de demandes : « Lis cette vue des AD59 en aperçu », « Recadre la moitié droite », puis
« Archive l'original pour I1, naissance, acte 47 ». L'archivage crée des fichiers et une note ; le
rattachement à l'arbre passe ensuite par une proposition et l'accord utilisateur.


Alertes : pièce rangée dans `_À trier/`, personne présumée vivante (son nom figure dans le nom du fichier),
conditions de réutilisation du dépôt (champ `reutilisation` du référentiel, sinon renvoi au site du service).
Une vue par appel ; aucune collecte automatique des vues voisines. Les conditions restent propres au service et au document.

**Dans Obsidian.** Chaque fiche de personne générée (`notes_generer`) a une section **« Pièces »** : les images
de ses médias, de ses faits et de leurs citations sont affichées (liens image Markdown à destination URL encodée), avec un lien vers la note de chaque
pièce. La note de la pièce renvoie à la personne et à la source : la vue graphique relie personne, pièce et
source (afficher les pièces jointes dans les filtres du graphe pour y voir aussi les images). Rien pour une
personne masquée.

## Outils

| Outil | Effet | Confirmation |
|---|---|---|
| `pieces_inventaire(dossier)` | comptes par type, patronymes, doublons, fichiers ignorés | non |
| `pieces_proposer(dossier, renommages, annuler, seulement_renommages, suivre_medias)` | plan complet (TSV), aperçu, résumé par dossier, médias suivis, jeton | non |
| `pieces_appliquer(jeton)` | déplacements, journal, contrôle ; proposition d'arbre pour les médias déplacés | **oui** |
| `piece_nommer(personnes, …)` | nom selon la convention et dossier de destination | non |
| `piece_archiver(source, page, personnes, …)` | vue téléchargée en pleine résolution, nommée, rangée, avec sa note | règle par défaut |
| `media_enregistrer(chemin, nom, classer)` | copie d'une pièce dans le répertoire des médias | règle par défaut |

## Ranger depuis un sous-dossier

`dossier` délimite les pièces à examiner. La racine des destinations est déterminée séparément :

1. racine des pièces configurée (`GENEALOGISTE_MEDIA_DIR`, ou son parent si le dossier s’appelle `documents`),
   lorsque le périmètre se trouve dedans ;
2. sinon, plus proche dossier parent contenant `.obsidian/` ;
3. sinon, le dossier fourni constitue un fonds autonome. Un dossier extérieur n’est pas importé
   automatiquement dans le vault configuré.

Le plan affiche `racine`, `perimetre` et des chemins depuis la racine :

```text
racine : /chemin/fonds
perimetre : /chemin/fonds/_À trier
_À trier/scan.jpg → documents/État civil/DUPONT/DUPONT Jean -- N [1850].jpg
_À trier/scan.md  → documents/État civil/DUPONT/DUPONT Jean -- N [1850].md
```

Les chemins `actuel` des renommages restent relatifs au `dossier` fourni. Pour traiter seulement
quelques pièces, utiliser `seulement_renommages=true` : les autres pièces et doublons ne sont pas déplacés.
Sans ce paramètre, le classement complet porte sur le périmètre. Les destinations et journaux
`_organisation/` restent sous la racine. Une relance sans changement dans `_À trier/` ne crée aucun
niveau supplémentaire (même si ce dossier constitue un fonds autonome) ; une pièce déjà à sa place n’apparaît pas dans le plan.

L’image et sa note sont traitées ensemble : une collision sur l’un des deux noms entraîne un suffixe
commun ; un échec de déplacement restaure le groupe. Une note partagée par plusieurs pièces est refusée
pour éviter d’attribuer son contenu au mauvais fichier. Le renommage conserve l’extension : il ne convertit
pas l’image. Le contrôle d’empreintes porte sur les pièces ; les notes actualisées sont contrôlées séparément.

Pour annuler, fournir le nom du journal à `pieces_proposer`, depuis la racine ou un de ses sous-dossiers.
Les anciens journaux restent lisibles en désignant leur racine d’origine. Le registre d’archivage suit les
nouveaux emplacements et leur annulation, pour reconnaître une originale conservée sans la télécharger
à nouveau. Les médias déjà référencés dans l’arbre restent protégés ; le rattachement se fait après rangement.

## Suivre les médias de l'arbre

Une pièce déjà rattachée à l'arbre (média dont le fichier local la désigne, en mode fichier comme en mode
gramps via `Genealogiste-Fichier`) peut être rangée en suivant sa référence :

1. `pieces_proposer(dossier, suivre_medias=true)` classe ces pièces comme les autres (motif « média de
   l'arbre suivi ») et liste `medias_suivis` (`O3 : ancien → nouveau`). Elles ne sont jamais isolées comme
   doublons : c'est leur exemplaire qui est gardé. Rien n'est écrit, ni dans le dossier ni dans l'arbre.
   L'option est ignorée (`medias_conseil`) si la racine d'organisation est hors des répertoires des médias
   (données, `GENEALOGISTE_MEDIA_DIR`, arborescence des pièces) : le nouveau chemin serait refusé par
   `modifier_media`. Une note compagnon elle-même référencée par l'arbre bloque toujours sa pièce.
2. `pieces_appliquer(jeton)`, après accord, déplace les fichiers **puis** prépare une proposition d'arbre :
   une opération `modifier_media` par média concerné (référence au format `media_ref` : relative aux données
   quand elle s'y trouve, absolue sinon), avec diff et jeton (`proposition_arbre`). Le nouveau fichier existe
   déjà, donc la proposition est contrôlée comme toute autre ; en mode gramps, le contenu étant identique,
   rien n'est renvoyé à Gramps Web.
3. `arbre_appliquer(proposition_arbre.jeton)` après un second accord explicite : une seule modification,
   annulable par `arbre_annuler_modification`.

L'ordre est voulu : la proposition d'arbre ne peut être validée qu'une fois le nouveau fichier présent, et
l'arbre n'est jamais modifié pour des fichiers qui n'auraient pas bougé (un déplacement en échec est ignoré).
Si l'arbre est illisible au moment d'appliquer, rien n'est déplacé.

**État intermédiaire** : entre `pieces_appliquer` et `arbre_appliquer`, les médias listés dans
`medias_a_mettre_a_jour` désignent leurs anciens chemins, désormais absents. Pour en sortir :

- appliquer `proposition_arbre` (cas normal) ;
- si la proposition n'a pas pu être préparée (arbre verrouillé, Gramps Web injoignable), le résultat donne
  `operations_medias` et `avertissement_medias` : reproposer `arbre_proposer(operations_medias, …)` ;
- si le jeton a expiré ou a été refusé : reproposer les mêmes `modifier_media` (lignes
  `medias_a_mettre_a_jour`), ou `gramps_relocaliser_medias(ancien_dossier, nouveau_dossier)` pour un dossier
  entier ;
- ou annuler le rangement (`pieces_proposer(dossier, annuler="<journal>.tsv")` puis `pieces_appliquer`) :
  les fichiers reviennent et, si l'arbre avait déjà été mis à jour, une proposition inverse est préparée.

Toute application d'un plan (annulation comprise) prépare ainsi la proposition pour les fichiers référencés
qu'elle a effectivement déplacés.

## Vérifier le téléchargement sur des ressources publiques

Les tests ordinaires utilisent des images et réponses synthétiques, sans réseau. La recette réseau
est explicite et séparée de la CI :

```bash
uv --directory mcp run python ../scripts/verifier_telechargements.py --service ad59
# autres cas : ad59_td, suisse, loc ; tous pour l'ensemble des quatre ressources
```

Elle utilise un dossier jetable, un arbre vide, un aperçu, un recadrage et un archivage avec note compagnon,
puis exige qu'un nouvel archivage ne fasse aucune requête. Aucune image réelle n'est ajoutée au dépôt.
Les quatre cas ont été essayés le 8 novembre 2026 : [résultats et limites](telechargement-international.md).
Les estimations de tokens sont des ordres de grandeur, pas un décompte de facturation du modèle.
Voir le [catalogue de compatibilité du wiki](../wiki/Services-archives.md).

## PDF dactylographiés ou imprimés → Markdown

`pdf_markdown(chemin, langue="fra", forcer_ocr=false, reconvertir=false)` convertit un PDF en **un** fichier
Markdown compact avant lecture par le modèle : un jugement, un extrait d'acte dactylographié, une notice
imprimée ou un relevé coûtent alors quelques centaines de tokens au lieu de 1 000 à 4 000 par page en image.

- **Texte natif** (PDF produit par un logiciel, ou scan déjà OCRisé) : extraction directe par pdfplumber, sans
  OCR. Les titres sont déduits de la taille de police (`##`, `###`), les tableaux tracés deviennent des
  tableaux Markdown, les puces et les césures sont rétablies.
- **Scan** (page sans texte, ou couverte d'images avec un simple tampon) : rendu à 300 DPI (pypdfium2) puis OCR
  Tesseract, en français par défaut (`langue="fra+lat"` pour un imprimé latin). La confiance moyenne est notée
  dans le Markdown.
- **Repli vision** : une page dont l'OCR est vide, peu fiable (confiance < 60, typiquement un manuscrit) ou
  impossible (Tesseract absent) n'est pas devinée : elle est listée dans `pages_a_lire_en_image` et se lit avec
  `archive_image(chemin, page=n)`, qui rend désormais une page de PDF en image.
- **Tesseract ou langue absents** : la réponse contient `installation` (commande adaptée au système détecté :
  apt, pacman, dnf, brew, winget ; pages concernées ; surcoût estimé de la lecture en image). Le modèle propose
  la commande à l'utilisateur **avant** de lire ces pages en image ; il ne l'exécute jamais lui-même. L'absence
  n'est pas mémorisée : après installation, relancer `pdf_markdown` suffit, sans recharger le plugin, et les
  pages restées en vision sont reconverties malgré le cache. `make check` indique l'état de l'OCR.
- **Une section par page** : `<!-- page 2/5 · texte natif -->`, `<!-- page 3/5 · OCR fra, confiance 87 -->`.
- **Cache** : `<données>/cache-pdf/<empreinte>-<langue>-v<version>.md`. La clé est l'empreinte SHA-256 du
  contenu : un PDF inchangé, même renommé ou déplacé, n'est jamais reconverti ; un PDF modifié l'est. Le
  Markdown n'est pas écrit à côté du PDF : un `.md` voisin d'une pièce est réservé à sa note compagnon.
- La réponse ne contient pas le texte : seulement `chemin_absolu`, les pages natives/OCR/à lire en image et
  l'estimation `tokens_estimes_markdown` / `tokens_estimes_images`.

**Installer Tesseract** (OCR des scans ; sans lui, seules les pages à texte natif sont converties) :

```bash
sudo apt install tesseract-ocr tesseract-ocr-fra      # Debian, Ubuntu
sudo pacman -S tesseract tesseract-data-fra           # Arch
brew install tesseract tesseract-lang                 # macOS
```

Ajouter `tesseract-ocr-lat` (ou `tesseract-data-lat`) pour le latin. L'image Docker inclut Tesseract avec le
français et le latin. Binaire hors du PATH, ou machine sans droits d'administration : indiquer son chemin dans
`GENEALOGISTE_TESSERACT` (par exemple un script qui appelle `tesseract` dans un conteneur en montant `/tmp` au
même chemin avec l'utilisateur courant). Aucun moteur d'OCR n'est téléchargé ni embarqué par le plugin. Bibliothèques Python, toutes sous licence permissive : pdfplumber (MIT), pypdfium2
(Apache-2.0/BSD), pytesseract (Apache-2.0).
