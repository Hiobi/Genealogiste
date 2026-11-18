---
name: organisation-pieces
description: Organiser un dossier de pièces généalogiques existant, simple répertoire ou vault Obsidian — inventaire, classement par type et patronyme, doublons, renommage selon la convention « NOM Prénom -- COMMUNE - DÉPÔT - TYPE [années] - cote - p.vue n.acte », triage des pièces non identifiables, reprise des notes Markdown existantes et de leurs liens, archivage d'un acte avec sa note. À utiliser pour /organise, « organise ce dossier de scans », « range mes photos d'archives », « classe mes PDF d'actes », « range mes scans », « trie ce dossier », « mets de l'ordre dans mes documents de généalogie », « renomme ces actes », « comment nommer mes fichiers », « reprends mes notes de recherche », import d'un dossier de pièces hétérogène.
---

# Organisation des pièces

Référence complète : `docs/pieces.md` du plugin.

## Règles impératives
- **Proposer, puis appliquer.** `pieces_proposer` ne touche à rien. `pieces_appliquer(jeton)` ne s'utilise
  qu'après l'accord explicite de l'utilisateur sur le plan présenté (résumé par dossier, doublons, `_À trier/`).
- **Jamais de suppression**, ni par les outils, ni à la main (pas de `rm`). Les doublons vont dans
  `archives/Doublons/`. Ne jamais déplacer de fichier hors des outils : seuls leur journal TSV et leur contrôle
  d'empreintes garantissent la réversibilité.
- Ne pas toucher `personnes/`, `familles/` et `sources/` (notes générées), ni les dossiers cachés. Les
  outils les excluent d'office.
- Un nom de fichier ne vaut pas une source. Un type ou un patronyme déduit du nom reste une hypothèse de
  classement : en cas de doute, laisser la pièce dans `_À trier/`.
- Personnes présumées vivantes : les noms de fichiers restent locaux, mais aucune recherche externe ni
  aucun envoi ne doit les concerner (`arbre_vivant`).

## Convention
`NOM Prénom[ + NOM Prénom] -- COMMUNE - DÉPÔT - TYPE [AAAA-AAAA] - cote - p.vue n.acte.ext`.
Produire les noms avec `piece_nommer`, jamais à la main : l'outil garantit la compatibilité Windows et
Nextcloud et reprend depuis l'arbre les noms (`I12`), le dépôt et la cote (`S3`).
Codes de type : N, B, M, D, S, NMD, BMS, TD, RM (matricule), SGM (Seconde Guerre mondiale : Arolsen, GR 16 P, Stalag, STO, épuration), ANMT (mineur), PM (personnel des mines),
NOT (acte notarié), CNI (carte d'identité), COUR (courrier, demande ou réponse administrative), REC
(recensement), SIGN, CAPTURE (arbre en ligne), PHOTO, TOMBE, LIEU.
Actes notariés : un seul code `NOT`, la nature en libellé libre après lui (`type_piece="NOT testament"`),
l'étude dans le dépôt. Une attestation immobilière après décès ou un contrat de mariage est `NOT`, pas `D`
ou `M` ; une demande d'acte est `COUR`, pas l'acte demandé. Pour `NOT`, le bloc `archives` de
`piece_nommer` relie la pièce au type `notaire` : cote 3 E acceptée, absente (chercher la cote 3 E de l'étude
dans l'inventaire), ou autre (conservée, classement du service à vérifier).
Pièce qu'aucun code ne couvre : `dossier` explicite dans le renommage (`{actuel, propose, dossier}`), sous
`documents/`, `photographies/` ou `courriers/` seulement. Ne jamais mettre de chemin dans `propose`.

## Déroulé
1. `pieces_inventaire` → 2. `pieces_proposer` → accord → `pieces_appliquer` → 3. triage de `_À trier/`
(analyse de classement) → `pieces_proposer(renommages=…, seulement_renommages=true)` → accord → `pieces_appliquer`.
Présenter la racine, le périmètre et le résumé du plan. Les chemins `actuel` sont relatifs au dossier
parcouru ; l’aperçu est relatif à la racine. Les notes `type: piece` suivent automatiquement leur image.
Gros dossiers : présenter le résumé, jamais la liste complète. Le plan complet est dans le fichier TSV.
Un dossier ordinaire suffit : ni vault ni `.obsidian` ne sont requis (la racine est alors le dossier lui-même).
Réexécuter sur un dossier rangé doit répondre « Rien à déplacer » ; annuler les journaux du plus récent au
plus ancien. Parcours détaillés (dossier existant, base depuis zéro, arbre GEDCOM/Gramps) : wiki
`Organiser-un-fonds`.

## Notes Markdown existantes
- **Jamais réécrites** par l'organisation, ni déplacées (seule une note compagnon `type: piece` suit sa pièce,
  texte libre et propriétés conservés).
- **Liens** : présenter `references_notes` (`nb_references_notes`) avec le plan, avant l'accord : liens wiki vers une pièce
  renommée, liens par chemin vers une pièce déplacée. Proposer ensuite, au choix : garder l'ancien nom (retirer
  ce renommage), correction dans Obsidian par l'utilisateur, ou correction note par note présentée (avant/après)
  et faite seulement après accord.
- **Analyse et rapprochements** : lire les notes pour en tirer des pistes (noms, dates, lieux, cotes) ; chercher
  les personnes dans l'arbre (`arbre_recherche`, `arbre_fiche`) ; un fait nouveau devient une proposition
  `arbre_proposer`, avec sa source, jamais une écriture directe. Sans source citée, c'est une hypothèse.
- **Réorganiser des notes** (déplacer, fusionner, renommer) : jamais automatique ; présenter un plan (note,
  destination, motif) et ne rien faire sans accord explicite.

## Méthode
Pour chaque pièce : provenance (service, lien, date de consultation), dépôt, cote (à vérifier dans
l'inventaire), vue et numéro d'acte. Transcription : abréviations développées `[ ]`, incertitudes `(?)`,
illisible `[…]` (skill `paleographie`). Une source décrit le document, une citation pointe la vue et l'acte. Un
fait sans citation reste une hypothèse ; une capture d'arbre en ligne est une piste. Ni le nom de fichier ni
le dossier ne sont une preuve.

## De l'image à l'arbre
`archive_image` (aperçu 800 px, gris) → recadrage (`region`, `largeur` 1500) → transcription → `piece_archiver`
(original pleine résolution, nommé, rangé) → note compagnon (texte personnel sous `## Notes`) → opérations
suggérées présentées par `arbre_proposer` → `arbre_appliquer` après accord. Pièce déjà rangée : ne pas la
réarchiver (copie), la rattacher par `ajouter_media` avec son chemin. Archives en ligne : registres cherchables
par commune et année pour dix services (`archives_registres`, liste dans `archives_service`) ; ailleurs IIIF, URL directe d'image, ou téléchargement manuel depuis
la visionneuse puis fichier local (wiki `Services-archives`).

## Rattacher une pièce à l'arbre
Une fois la pièce rangée et nommée, l'ajouter comme média d'une citation via une proposition `arbre_proposer`
(opération `ajouter_media`, `fichier` = `reference_media` rendu par `media_enregistrer`, ou chemin relatif au
vault ; un fichier introuvable est refusé). Un fichier référencé par l'arbre ne sera plus déplacé par
les organisations suivantes, sauf `pieces_proposer(…, suivre_medias=true)` : `pieces_appliquer` déplace
alors la pièce puis renvoie `proposition_arbre` (`modifier_media`) ; la présenter et n'appeler
`arbre_appliquer` qu'après un second accord. Tant qu'elle n'est pas appliquée, le média désigne un fichier
absent (reprise : `operations_medias`, ou annulation du rangement ; docs/pieces.md).

## Vault Obsidian
Pour ranger directement les nouvelles pièces dans le vault : `GENEALOGISTE_MEDIA_DIR=<vault>/documents`
(et au besoin `GENEALOGISTE_RAPPORTS_DIR`, `GENEALOGISTE_EXPORTS_DIR`). Ensuite,
`media_enregistrer(chemin, nom, classer=true)` range selon la convention.
