# Pièces : convention de nommage et organisation d'un dossier existant

Un dossier de pièces existant (scans d'actes, photos, PDF d'AD ou de Geneanet, captures d'arbres en ligne,
audio, ancienne base GeneWeb…) s'organise en trois temps :

1. **inventaire et classement** par règles : `/genealogiste:organise <dossier>` ;
2. **triage** des pièces non identifiables : l'agent `trieur` lit chaque image et propose un nom ;
3. **application** du plan après ton accord. L'opération est **réversible** et ne fait **aucune suppression**.

Le même mécanisme que `arbre_proposer` s'applique : un plan est présenté, puis exécuté seulement avec son jeton
et après accord explicite.

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
| `REC` | recensement | `documents/Divers/<NOM>/` |
| `CAPTURE` | capture d'arbre en ligne (Geneanet, Filae…) : une piste, pas une source | `documents/Divers/<NOM>/` |
| `SIGN` | signature | `documents/Signatures/<NOM>/` |
| `PHOTO` | photographie | `photographies/<NOM>/` |
| `TOMBE` | sépulture photographiée | `photographies/Sépultures/<NOM>/` |
| `LIEU` | lieu | `photographies/Lieux/` |
| audio | témoignage oral (`.mp3`, `.m4a`, `.wav`…) | `documents/Témoignages oraux/[<NOM>/]` |
| GeneWeb, GEDCOM, INSEE | bases (`*.gwb` déplacé en bloc), `.ged`, fichiers bruts du fichier des décès | `archives/GeneWeb/`, `archives/GEDCOM/`, `archives/INSEE/` |

Sans patronyme ou sans type reconnu, la pièce va dans `_À trier/` en attendant le triage.

## Arborescence produite

```
documents/{État civil,Militaire,Mines (ANMT),Signatures,Témoignages oraux,Divers}/<NOM>/
photographies/<NOM>/ · photographies/Sépultures/<NOM>/ · photographies/Lieux/
archives/{GeneWeb,GEDCOM,INSEE,Doublons}/
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
  puis `pieces_appliquer`.
- **Contrôle** : le dossier doit être identique au plan (nombre de fichiers et empreintes), sinon le plan est
  refusé. Chaque fichier est vérifié avant son déplacement. Après l'application, le résultat indique le
  nombre de fichiers avant et après et compare les empreintes.
- **Hors du périmètre**, et donc jamais touchés : les dossiers `personnes/`, `familles/` et `sources/`
  générés par les notes ([notes.md](notes.md)), les dossiers et fichiers cachés (`.obsidian`, `.git`), les
  liens symboliques, les notes Markdown et les fichiers texte qui ne sont pas des fichiers INSEE.
- **Médias de l'arbre** : un fichier référencé par un média de l'arbre n'est pas déplacé (la référence
  casserait) ; il est listé dans `references_arbre_non_deplacees`.
- Tous les déplacements restent **dans le dossier** (chemins résolus et confinés, voir
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
5. il passe les renommages à `pieces_proposer(dossier, renommages=[{actuel, propose}])`. Chaque pièce est
   reclassée d'après son nouveau nom.

## Médias et rapports dans le vault

| Variable | Défaut | Rôle |
|---|---|---|
| `GENEALOGISTE_MEDIA_DIR` | `<données>/medias` | images d'actes (`media_enregistrer`, `archive_image`), par exemple `<vault>/documents` |
| `GENEALOGISTE_RAPPORTS_DIR` | `<données>/rapports` | rapports de preuve (`rapport_enregistrer`) |
| `GENEALOGISTE_EXPORTS_DIR` | `<données>/exports` | exports GEDCOM, GeneWeb, Gramps XML… |

- Un média situé dans le répertoire de données est référencé en relatif (`medias/…`). Hors de celui-ci, il
  l'est en chemin absolu. L'envoi vers Gramps Web accepte les deux racines et refuse tout le reste.
- Un rapport écrit hors du répertoire de données n'est **pas versionné** par Sosa (`commit: null`).
- `media_enregistrer(chemin, nom, classer=true)` range directement selon la convention :
  `documents/<type>/<NOM>/`, ou `_À trier/` si le nom ne suffit pas.

Ces variables remplacent le contournement par liens symboliques (`<données>/medias → <vault>/documents`).

## Outils

| Outil | Effet | Confirmation |
|---|---|---|
| `pieces_inventaire(dossier)` | comptes par type, patronymes, doublons, fichiers ignorés | non |
| `pieces_proposer(dossier, renommages, annuler)` | plan complet (TSV), aperçu, résumé par dossier, jeton | non |
| `pieces_appliquer(jeton)` | déplacements, journal, contrôle | **oui** |
| `piece_nommer(personnes, …)` | nom selon la convention et dossier de destination | non |
| `media_enregistrer(chemin, nom, classer)` | copie d'une pièce dans le répertoire des médias | règle par défaut |
