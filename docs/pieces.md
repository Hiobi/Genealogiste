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
- **Hors du périmètre**, et donc jamais touchés : les dossiers `personnes/`, `familles/`, `sources/` et `patronymes/`
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
| `GENEALOGISTE_CACHE_IMAGES_DIR` | `<données>/cache-images` | aperçus et recadrages de lecture (`archive_image`), jamais dans le vault ni dans Git |

Quand le répertoire des médias s'appelle `documents` (ex. `<vault>/documents`), l'arborescence des pièces
(`documents/`, `photographies/`, `archives/`, `_À trier/`) part de son dossier parent, le vault : une pièce classée
va dans `<vault>/documents/État civil/DUPONT/`, une photo dans `<vault>/photographies/DUPONT/`.

- Un média situé dans le répertoire de données est référencé en relatif (`medias/…`). Hors de celui-ci, il
  l'est en chemin absolu. L'envoi vers Gramps Web accepte les deux racines et refuse tout le reste.
- Un rapport écrit hors du répertoire de données n'est **pas versionné** par Genealogiste (`commit: null`).
- `media_enregistrer(chemin, nom, classer=true)` range directement selon la convention :
  `documents/<type>/<NOM>/`, ou `_À trier/` si le nom ne suffit pas.

Ces variables remplacent le contournement par liens symboliques (`<données>/medias → <vault>/documents`).

## Archiver une pièce consultée en ligne (ARK, IIIF)

`archive_image` sert à **lire** (aperçu 800 px en gris, recadrages) : ses images restent dans le cache, hors du
vault. Pour **conserver** une vue d'acte, `piece_archiver` :

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
| `pieces_proposer(dossier, renommages, annuler)` | plan complet (TSV), aperçu, résumé par dossier, jeton | non |
| `pieces_appliquer(jeton)` | déplacements, journal, contrôle | **oui** |
| `piece_nommer(personnes, …)` | nom selon la convention et dossier de destination | non |
| `piece_archiver(source, page, personnes, …)` | vue téléchargée en pleine résolution, nommée, rangée, avec sa note | règle par défaut |
| `media_enregistrer(chemin, nom, classer)` | copie d'une pièce dans le répertoire des médias | règle par défaut |

Le reclassement ultérieur depuis un sous-dossier et le déplacement automatique des notes compagnons
restent suivis dans [l'issue #101](https://github.com/Hiobi/Genealogiste/issues/101). Pour une pièce connue,
renseigner les personnes et le type dès l'archivage pour obtenir directement son emplacement final ;
éviter de déplacer séparément l'image et sa note.

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
Le catalogue de compatibilité complet du wiki est suivi dans [l'issue #107](https://github.com/Hiobi/Genealogiste/issues/107).
