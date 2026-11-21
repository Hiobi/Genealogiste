# Mode Gramps Web : Genealogiste en direct sur un arbre Gramps Web

Deux backends, choisis par `GENEALOGISTE_BACKEND` (pas de synchronisation bidirectionnelle) :

| Backend | Arbre de référence | Écriture | Historique / annulation |
|---|---|---|---|
| `fichier` (défaut) | `arbre.ged` (GEDCOM 7) dans le dépôt Git des données | un commit par proposition validée | `git log` / `git revert` |
| `gramps` | l'arbre Gramps Web (API) | une transaction `/api/transactions/` par proposition validée | `gramps-transactions.jsonl` local / transaction inverse |

Le contrat est le même dans les deux cas : `arbre_proposer` → diff → **accord explicite** →
`arbre_appliquer`. Rien n'est écrit sans accord, y compris une annulation (`arbre_annuler_modification`
puis `arbre_appliquer`).

## Configuration

Compte **local** Gramps Web dédié à Genealogiste, rôle *Editor* (créé dans Gramps Web : Paramètres >
Administration > Utilisateurs). Identifiants dans l'environnement ou le `.env` du répertoire de données,
jamais dans Git, un journal ou une issue.

| Variable | Rôle |
|---|---|
| `GENEALOGISTE_BACKEND` | `fichier` (défaut) ou `gramps` |
| `GENEALOGISTE_GRAMPS_URL` | ex. `http://localhost:5055` (`http://grampsweb:5000` dans la stack Docker) |
| `GENEALOGISTE_GRAMPS_USER` / `_PASSWORD` | compte local dédié, rôle Editor |
| `GENEALOGISTE_GRAMPS_TTL` | secondes entre deux relectures incrémentales en lecture (défaut 30) |
| `GENEALOGISTE_GRAMPS_NOTES_AUTO` | notes de preuve `Genealogiste:auto` : `true` (défaut, recalcul sur toute la base à chaque écriture), `modifies` (recalcul limité aux objets touchés), `false` (aucune note ni étiquette générée ; celles qui existent sont conservées telles quelles) |
| `GENEALOGISTE_MARQUEURS` | forme écrite des attributs et de l'étiquette gérés : `genealogiste` (défaut, `Genealogiste-*`, `Genealogiste:auto`) ou `sosa` (`Sosa-*`, `Sosa:auto`, pour une base partagée avec une ancienne version) ; les deux formes sont toujours lues (voir « Marqueurs historiques ») |
| `GENEALOGISTE_GIT_MIRROR` | `true` : miroir GEDCOM 7 versionné de l'arbre Gramps (défaut `false`) |
| `GENEALOGISTE_GIT_REMOTE` | dépôt distant optionnel du répertoire de données (**privé**) |

### Rôle requis et contrôle au diagnostic

Écrire exige le rôle **Editor** (3) : `POST /api/transactions/` demande `AddObject`, `EditObject` et
`DeleteObject`. Un compte *Contributor* (2) ne peut qu'ajouter, *Member* (1) et *Guest* (0) ne font que lire.
*Owner* (4) et *Admin* (5) écrivent aussi, mais gèrent en plus les utilisateurs, les sauvegardes et les
réglages : à éviter pour un compte dont les identifiants sont stockés (privilège minimal).

- **Lecture** : possible avec n'importe quel rôle (recherche, fiches, preuve, ascendance, `gramps_tirer`).
- **Proposition** : en mode `gramps`, `arbre_proposer` et les autres préparations (`gramps_recalculer_notes`,
  `gramps_structurer_lieux`, `marqueurs_migrer_proposer`, annulation, `gramps_bascule_proposer`) refusent
  **avant de lire l'arbre et de calculer le diff** un compte sans droit d'écriture, avec le rôle détecté et le
  correctif. `arbre_appliquer` refuse de même avant de consommer le jeton : une promotion du compte permet de
  réessayer avec la même proposition. Les droits sont ceux du jeton d'accès (le rôle n'y figure pas : seulement
  la liste `permissions`) ; s'ils manquent, le jeton est renouvelé (au plus toutes les 5 secondes, car
  `/token/` et `/token/refresh/` sont limités à une requête par seconde) puis `GET /api/users/-/` donne le rôle.
- **Écriture refusée par le serveur** : un HTTP 403 est converti en « droits insuffisants : rôle Editor requis »,
  un HTTP 422 `message: Unknown field` (API < 3.13.0) en « mettre à jour Gramps Web (API 3.13.0 au moins) ».
  Forme réelle d'un 403 constatée sur les trois images de la matrice, avec des comptes *Member* et
  *Contributor* : `{"code":403,"status":"Forbidden"}` (`application/json`, format flask-smorest, sans clé
  `error.message`).

`diagnostic` (réseau activé et `GENEALOGISTE_GRAMPS_URL` renseigné) ajoute à la joignabilité (`gramps_web`) trois
contrôles, chacun indépendant : si `/api/metadata/` ou `/api/users/-/` échoue, le contrôle correspondant passe en
`attention` avec le motif et les autres continuent. Aucun identifiant, jeton ni nom de personne n'y figure.

| Contrôle | Contenu | États |
|---|---|---|
| `gramps_version` | version de l'API et de Gramps (`GET /api/metadata/`), plage testée, fonctions optionnelles disponibles ou absentes d'après `FONCTIONS_API` | `ok` dans la plage ; API plus ancienne que 3.13.0 : `erreur` en mode `gramps`, `attention` sinon ; plus récente ou illisible : `attention` |
| `gramps_role` | rôle du compte (`GET /api/users/-/`) | Editor : `ok` ; sous Editor : `erreur` en mode `gramps`, `attention` sinon ; Owner ou Admin : `attention` (« préférer Editor ») |
| `gramps_reglages` | file de tâches (`server.task_queue`), multi-arbres (`server.multi_tree`), inscription libre | `ok` ; inscription libre ouverte : `attention`. L'inscription libre n'est lisible que depuis l'API 3.26.0 (`GET /api/register/config/`) : avant, « non vérifiable sur cette version ». `/api/config/` est réservé aux Admin : jamais appelé |

Le jeton d'accès Gramps Web dure 15 minutes ; sa revendication `exp` fixe le moment du renouvellement (30 secondes
avant l'échéance), sans délai codé en dur. Le jeton renouvelé garde l'arbre et les droits.

Le mode direct suppose une instance Gramps Web **privée** : les personnes vivantes y sont écrites en clair.
Elles restent masquées par défaut dans les exports publics (`arbre_exporter`).

## Fonctionnement

- **Lecture** : chargement complet au premier besoin (`GET /api/<objets>/`), puis relecture incrémentale
  (`?keys=handle,change`). Les objets modifiés et ceux à l’horodatage le plus récent de chaque classe sont
  relus : Gramps date les modifications à la seconde. Le bilan ne compte que les contenus réellement changés. Preuve, cohérence, ascendance, lacunes
  sont calculées localement.
- **Proposition** : l'arbre est relu, les opérations appliquées sur une copie, puis réécrites en objets
  Gramps **par-dessus** l'état lu ; seuls les objets réellement modifiés entrent dans la transaction. Le
  bilan des objets Gramps (`transaction_gramps`) vient en premier, puis le diff GEDCOM 7 de l'arbre (lisible,
  concis : voir `docs/securite.md`, « Diff concis »).
- **Accord** : nouvelle relecture ; si un objet de la transaction a été modifié dans l'interface depuis la
  proposition, **refus** (le serveur compare aussi `old` à la base). L'arbre est rechargé : reformuler la
  proposition (nouveau diff, nouvel accord). `force` n'est jamais utilisé.
- **Transaction** : atomique, message = titre + justification + opérations + sources ; gros lots en tâche
  de fond (`background`, suivi de `/api/tasks/`).
- **Annulation** : `arbre_historique` donne la référence de la transaction ; `arbre_annuler_modification`
  prépare la transaction inverse (`undo`), refusée si les objets ont changé depuis.

## Journal d'intention et reprise

`gramps-transactions.jsonl` trace chaque transaction en plusieurs lignes (même `id`, fusionnées à la lecture) :

| État | Écrit |
|---|---|
| `intention` | **avant** l'envoi, avec les objets à écrire |
| `envoyee` | dès la réponse de Gramps Web, avec les objets écrits |
| `terminee` / `complements_en_echec` | après les étapes complémentaires (`etapes` : envoi des médias, miroir Git) |
| `refusee` | conflit ou refus du serveur : rien n'a été écrit |
| `indeterminee` | interruption pendant l'envoi (réseau coupé, arrêt) |

Une transaction acceptée par Gramps Web reste donc annulable même si la suite échoue : le résultat porte un
`avertissement` (relancer `gramps_envoyer_medias` ou `gramps_synchroniser`). Avant toute application ou
annulation, les transactions `intention` ou `indeterminee` sont comparées à l'état de Gramps Web et marquées
`envoyee`, `non_envoyee` ou `partielle`. `arbre_historique` affiche l'état et les étapes.

## Correspondance Genealogiste ↔ Gramps (`mcp/src/genealogiste_mcp/gramps/mapping.py`)

Module unique, utilisé par l'export Gramps XML et par le mode direct, testé aller-retour
(`tests/test_gramps_mapping.py`, et sur un vrai Gramps Web par `make test-gramps`).

| Genealogiste | Gramps |
|---|---|
| xref `I12`, `F3`, `S7`, `R1`, `O2`, note partagée `N4` | `gramps_id` |
| uid de personne, famille, événement | attribut `Genealogiste-UID` (absent si l'objet vient de l'interface : uid dérivé du handle) |
| uid des noms | attribut de personne `Genealogiste-UID noms` (dans l'ordre) |
| statut forcé (réfuté, contradictoire) + justification | attribut `Genealogiste-Statut` « refute \| justification » (événement, famille), `Genealogiste-Statut nom N`, `Genealogiste-Statut filiation I3` |
| vivant forcé | attribut `Genealogiste-Vivant` Y/N |
| témoin, parrain, officier… de l'arbre | référence d'événement sur sa fiche (rôle Witness, Godparent, Celebrant, Informant, ou libellé français) + attribut `Genealogiste-Association` |
| intervenant seulement nommé | attribut d'événement `Genealogiste-Association` « rang \| RÔLE \| précision \| nom \| » avec ses citations |
| parrain/marraine de niveau individu | `personref` + attribut de personne `Genealogiste-Association` « … \| xref » |
| citation | page, confiance (QUAY ; attribut `QUAY` si 2), notes `Transcript` / `Citation`, attributs Consulté, Type de source, Information, Preuve, Date de consultation, ARK |
| source | titre, auteur, publication, dépôt + cote, attributs URL, ARK, Type de source, Dérivée de |
| lieu | titre « Commune, Département, Pays », code INSEE, coordonnées ; paroisse en attribut d'événement |
| âge | attribut `Age` de la référence d'événement |
| cause, précision du type | attributs `Cause`, `Précision` |
| date GEDCOM 7 | date Gramps (calendrier, qualificatif, qualité) ; la chaîne GEDCOM est gardée dans `text` |
| étiquettes (`tags`) de personne, famille, événement, citation, source, dépôt, média, note partagée | `tag_list` (handles) + objets `Tag` ; voir « Étiquettes » ci-dessous |

Une personne, un événement ou une note créés dans l'interface Gramps sont lus sans attribut `Genealogiste-*` et
réécrits **à l'identique** tant que Genealogiste ne les modifie pas. Ce que Genealogiste ne modélise pas (adresses, URL,
étiquettes des lieux et des notes « en ligne », couleur et priorité des étiquettes, titres et suffixes de nom, noms
alternatifs et dates des lieux, médias d'événements, notes isolées…) est conservé tel quel.

### Étiquettes (#262)

- **Lecture** : `tag_list` (handles) → noms, dans l'ordre, sans doublon de nom. Les étiquettes gérées
  (`Genealogiste:auto`, `Sosa:auto`, « Preuve : … ») et les handles sans objet `Tag` restent hors du modèle.
- **Écriture** par-dessus l'état lu : un objet non modifié est réécrit à l'identique (ordre de `tag_list`,
  handles, étiquettes gérées et inconnues) ; couleur et priorité d'un `Tag` existant ne sont jamais touchées.
  Une étiquette ajoutée va en fin de liste. Une étiquette inexistante est créée **dans la même transaction**
  (objet `Tag` sans `gramps_id`, handle déterministe, couleur par défaut de Gramps `#000000000000`, priorité
  suivant la plus haute de la base) : elle apparaît dans `transaction_gramps.bilan` (`Tag`). Retirer une
  étiquette d'un objet ne supprime jamais l'objet `Tag`.
- **Noms** : sensibles à la casse (l'API compare les noms à l'identique). L'API n'impose pas l'unicité : deux
  `Tag` de même nom sont lus sans perte (un objet garde le handle qu'il porte) ; une étiquette posée réutilise
  le premier dans l'ordre de priorité (puis de handle), avec un avertissement à la proposition ; rien n'est
  fusionné.
- **Diff concis** : `transaction_gramps.etiquettes`, une ligne par objet (`étiquettes I12 : +Blog −ToDo`,
  `gramps_id` de l'objet) ; `transaction_inverse.etiquettes` à la préparation d'une annulation. Une
  transaction qui pose ou retire une étiquette de l'utilisateur n'est jamais comptée dans
  `dont_notes_de_preuve_seules`.
- **Rôle** : créer un `Tag` par `POST /api/tags/` ne demande que *Contributor*, le modifier ou le supprimer
  *Editor* ; contrairement à l'interface (Paramètres, réservés à Owner/Admin), l'API ne réserve pas les
  étiquettes à Owner/Admin. Genealogiste n'utilise pas `/api/tags/` : l'étiquette part dans la transaction
  ordinaire (`POST /api/transactions/`, *Editor*), journalisée et annulable. Un compte sans droit d'écriture
  est donc refusé **à la proposition** (contrôle commun ci-dessus), jamais à l'application.
- **Annulation** : la transaction inverse restaure les `tag_list` et retire les `Tag` créés par la transaction.
- **Modification en lot** : `POST /api/objects/edit-by-handle/` (API ≥ 3.26.0, `add_tag` / `remove_tag`)
  est **écartée** : hors de `/api/transactions/`, non disponible sur l'image épinglée (3.25.1), et son
  annulation par `gramps-transactions.jsonl` n'est pas établie. Un gros lot reste une transaction ordinaire
  (en tâche de fond au-delà du seuil habituel).
- **Versions** : `Tag` sans `gramps_id` accepté par `POST /api/transactions/` depuis l'API 0.2.0 (clé
  `transactions`) : aucune version minimale supplémentaire.

Non mappé : les nœuds GEDCOM non interprétés (`extra`), perdus à l'aller-retour. Normalisations : type de
nom `BIRTH` = nom de naissance, filiation `BIRTH` = filiation biologique, un même nom de lieu = un seul
lieu Gramps (coordonnées et code INSEE mis en commun). Un événement partagé par plusieurs personnes
(rôle *Primary*) reste partagé tant qu'il n'est pas modifié ; modifié pour l'une d'elles, il est dédoublé.

Export Gramps XML (`export/gramps_xml.py`) : sérialise ces mêmes objets Gramps, **tout leur contenu** compris
(y compris ce que Genealogiste ne modélise pas), selon des tables champ JSON ↔ élément XML que l'import (#269,
`gramps/lecture_xml.py`) relit dans l'autre sens, puis convertit par ce même module (`gramps_to_tree`). Versions
cibles, `.gramps` gzip, paquet `.gpkg`, import et vérifications : voir [Gramps Desktop](gramps.md#contenu-écrit)
et [l'import depuis Gramps Desktop](gramps.md#import-depuis-gramps-desktop).

### Marqueurs historiques (`Sosa-*`, `Sosa:auto`)

Les bases écrites avant le renommage (#182) portent `Sosa-UID`, `Sosa-UID noms`, `Sosa-Statut…`,
`Sosa-Association`, `Sosa-Vivant`, `Sosa-Fichier` et l'étiquette `Sosa:auto`. Ces formes sont **lues sans limite
de durée**. Seuls ces noms exacts sont reconnus : un attribut personnel commençant par `Sosa` n'est jamais touché.

- **Écriture ordinaire** : un attribut ou l'étiquette existants gardent leur forme tant que leur valeur ne
  change pas (aucune migration silencieuse, pas de transaction massive) ; un attribut nouveau ou modifié est
  écrit dans la forme de `GENEALOGISTE_MARQUEURS`.
- **Objet portant les deux formes** : si les valeurs sont identiques, la lecture n'en voit qu'une ; si elles
  diffèrent, la nouvelle forme est lue, l'ancienne est conservée intacte et l'écart est **signalé** par la
  migration (`incoherences`), jamais tranché silencieusement.
- **Migration explicite** : `marqueurs_migrer_proposer` prépare une transaction (bilan, objets, jeton) ;
  après accord, `marqueurs_migrer_appliquer` l'écrit comme toute proposition : journalisée dans
  `gramps-transactions.jsonl`, annulable par `arbre_annuler_modification`. Chaque attribut est renommé en place
  (valeur, citations, confidentialité et position conservées), un doublon identique est retiré, l'étiquette
  `Sosa:auto` est renommée sous le **même handle** (ou, si `Genealogiste:auto` existe déjà, les objets sont
  réétiquetés et l'ancienne étiquette supprimée). Aucun objet n'est créé ni supprimé ; handles, `gramps_id`, uid
  et `_UID` GEDCOM sont inchangés, le miroir Git et les exports GEDCOM restent identiques. Deuxième exécution :
  rien à migrer.

## Notes de preuve générées (`Genealogiste:auto`)

Statut de preuve de chaque fait (note *Research* + étiquette « Preuve : … » sur l'événement), fiche de preuve
de la personne, filiations de la famille, lien cliquable des sources : notes étiquetées **`Genealogiste:auto`**
(ou `Sosa:auto` dans une base non migrée),
recalculées à chaque écriture et ignorées à la lecture. Après des modifications faites dans l'interface,
`gramps_recalculer_notes` propose leur recalcul (toute la base, même en mode `modifies` ; refusé en mode
`false`). Les notes manuelles ne sont **jamais** modifiées.

En mode `modifies`, sont recalculées les notes des personnes, familles, événements et sources modifiés par la
proposition, plus les membres des familles modifiées et les familles des personnes modifiées (filiations). Le
statut d'un fait calculé localement (`arbre_fiche`, `arbre_statut_preuve`) reste toujours exact ; seules les
notes de la base Gramps peuvent être en retard.

`arbre_proposer` indique dans `transaction_gramps.dont_notes_de_preuve_seules` combien d'objets ne changent que
par leurs notes ou étiquettes de preuve, et ajoute un avertissement quand la transaction dépasse 50 objets pour
moins de 5 opérations (première écriture, recalcul global).

Les notes de preuve **sans** étiquette (import d'un GEDCOM ou d'un export GeneWeb produit par Genealogiste) sont
reconnues à leur gabarit : `⛔|🟡|🟢|✅|⚠️|❌ Preuve : …`, `Filiation de … : …`,
`Fiche de preuve (plugin genealogiste)…`, `Lien : http…`. Elles sont **adoptées** à la première écriture
(étiquetées `Genealogiste:auto` et réécrites en place), jamais doublées. Une note manuelle qui commence par l'un de ces
gabarits est donc traitée comme générée : la reformuler si elle doit être conservée.

## Bascule fichier → Gramps Web

1. `gramps_bascule_proposer` : bilan de l'envoi de tout `arbre.ged` dans un arbre Gramps Web **vide** ;
2. `gramps_bascule_appliquer(jeton)` après accord : une transaction, puis `BASCULE.json` et le dernier
   commit « Bascule vers Gramps Web » figent `arbre.ged` (les propositions en mode fichier sont refusées) ;
   `journal.jsonl` reste local ;
3. redémarrer le serveur MCP avec `GENEALOGISTE_BACKEND=gramps`.

## Miroir Git optionnel

`GENEALOGISTE_GIT_MIRROR=true` (mode gramps) : l'arbre Gramps est exporté en GEDCOM 7 dans `arbre.ged`
(même dépôt et même historique qu'en mode fichier), un commit par transaction ; les modifications faites
hors de Genealogiste sont commitées à la synchronisation suivante (« Modifications externes »,
`gramps_synchroniser`).

Le dépôt est local par défaut. `GENEALOGISTE_GIT_REMOTE` ajoute un push après chaque commit : il doit être
**privé** (données de vivants) ; le dépôt du plugin est refusé.

## Tests

- `make test` : faux serveur Gramps Web (`tests/gramps_fake.py`, respx) fidèle au contrat de l'API
  (format des lectures, contrôle de `old`, `undo`, tâches de fond, rôles et droits du jeton, 403, `/api/metadata/`,
  `/api/users/-/`, version d'API paramétrable, expiration du jeton sur horloge injectable).
- `make test-gramps` : vrai Gramps Web jetable (`docker-compose.test.yml`, sans volume), données fictives ; crée
  le compte Editor `sosa-test` et deux comptes à droits insuffisants (`sosa-membre`, rôle 1, et
  `sosa-contributeur`, rôle 2) pour vérifier le diagnostic et le refus d'écriture.
- `make test-gramps-matrice` : `make test-gramps` sur chaque image de la matrice ci-dessous.

## Compatibilité des versions

Relevé du 2026-11-21. Source unique : [compatibilite-gramps.json](../compatibilite-gramps.json) (images
épinglées par empreinte), reprise par la CI et par `genealogiste_mcp/gramps/compatibilite.py` (plage testée,
utilisée par le diagnostic). Un test vérifie que le fichier, ces constantes, le compose de test et cette page
concordent. Gramps Desktop (fichiers Gramps XML) : voir [Gramps Desktop](gramps.md).

**Plage prise en charge : gramps-web-api 3.13.0 à 3.26.0 (API ≥ 3.13.0).**

| Image `grampsweb` | gramps-web-api | Gramps | Statut | Empreinte (`ghcr.io/gramps-project/grampsweb@…`) |
|---|---|---|---|---|
| `26.5.1` | 3.13.0 | 6.0 | prise en charge, **testée en CI** (plancher) | `sha256:d420d9d34b975c21b2fdd35be7f4dcf6ba182d1b945e9b4610d6297f24e433ae` |
| `26.11.0` | 3.25.1 | 6.0 | prise en charge, **testée en CI** (image par défaut de `make test-gramps`) | `sha256:dbd20a8ba954e19ae8ed17e5e1537d55a3d16ccef6adf7a8fe8cb783bab81411` |
| `26.11.3` | 3.26.0 | 6.0 | prise en charge, **testée en CI** (plafond) | `sha256:bf672745c0428ec37f398f51a89e07a0dabe4f2abc1038fd0952e358ae0228a3` |
| `26.5.2` à `26.11.2` | 3.13.1 à 3.25.x | 6.0 | prise en charge (dans la plage), non testée une à une | — |
| `v25.5.0` à `26.5.0` | 3.0.0 à 3.12.2 | 6.0 | **non prise en charge** : écriture refusée (voir ci-dessous) | — |
| avant `v25.5.0` | 2.x et antérieures | 5.2 | **non prise en charge** : format JSON des objets de Gramps 5.2 | — |
| après `26.11.3` | > 3.26.0 | — | non testée : à valider par la matrice avant d'élargir la plage | — |

Pourquoi 3.13.0 : Genealogiste envoie le message de chaque transaction en paramètre (`POST
/api/transactions/?message=…`), paramètre apparu dans gramps-web-api 3.13.0. Les API 3.0.0 à 3.12.x répondent
`HTTP 422 query: message: Unknown field` : aucune écriture possible (chargement, proposition, annulation). Les
lectures fonctionnent. Essai réel : `v25.5.0` (API 3.0.0) et `26.5.0` (API 3.12.2) échouent, `26.5.1` (API
3.13.0) passe tous les tests d'intégration. Genealogiste n'est pas adapté à ces versions : mettre Gramps Web à
jour.

Toutes les images Gramps Web 3.x embarquent Gramps **6.0** : gramps-web-api exige `gramps>=6.0.4,<6.1.0`
(`>=6.0.1` jusqu'à 3.2.0). Gramps 6.1 n'est donc pas disponible dans Gramps Web ; il n'est testé qu'à travers
la bibliothèque Gramps Desktop ([Gramps Desktop](gramps.md)).

### Correspondance image ↔ API

Relevée par comparaison des couches des images (l'image Gramps Web = image gramps-web-api + interface) ; pour
les trois images testées, le test d'intégration vérifie aussi la version lue dans `GET /api/metadata/`.

| `grampsweb` | API | | `grampsweb` | API |
|---|---|---|---|---|
| `v25.5.0`, `v25.5.1` | 3.0.0 | | `26.5.1` | 3.13.0 |
| `v25.5.2` | 3.1.0 | | `26.5.2` | 3.13.1 |
| `v25.6.0`, `25.7.0` à `25.7.3` | 3.2.0 | | `26.5.3` | 3.14.1 |
| `25.8.0`, `25.9.0` | 3.3.0 | | `26.6.0` | 3.15.0 |
| `25.10.0.1`, `25.10.1` | 3.4.0 | | `26.6.1` | 3.16.0 |
| `25.10.2` | 3.4.1 | | `26.6.2` | 3.17.0 |
| `25.11.0` à `25.11.2` | 3.5.0 | | `26.7.0` | 3.18.0 |
| `25.12.0` | 3.6.0 | | `26.7.1` | 3.19.0 |
| `26.1.0` | 3.7.1 | | `26.8.0` | 3.20.1 |
| `26.1.1`, `26.2.0` | 3.7.1.1 | | `26.8.1` | 3.21.1 |
| `26.3.0` à `26.3.1.1` | 3.9.0 | | `26.9.0` | 3.22.0 |
| `26.4.0` | 3.10.0 | | `26.9.1` | 3.22.1 |
| `26.4.1` | 3.11.1 | | `26.10.0`, `26.10.1` | 3.23.1 |
| `26.4.2` | 3.12.0 | | `26.10.2` | 3.24.0 |
| `26.4.3` | 3.12.1 | | `26.11.0` | 3.25.1 |
| `26.5.0` | 3.12.2 | | `26.11.1`, `26.11.2` | inconnue (probablement 3.25.x) |
| | | | `26.11.3` | 3.26.0 |

### Version minimale par fonction

Clés de `FONCTIONS_API` (`genealogiste_mcp/gramps/compatibilite.py`). « Utilisée » : Genealogiste en dépend
aujourd'hui ; « prévue » : fonction envisagée (lots du jalon M6), à conditionner à la version lue par le
diagnostic.

| Fonction | Clé | API minimale | Usage |
|---|---|---|---|
| transaction atomique `POST /api/transactions/` | `transactions` | 0.2.0 | utilisée |
| annulation par transaction inverse (`undo=1`) | `transactions_undo` | 1.0.0 | utilisée |
| historique des transactions | `transactions_historique` | 2.2.0 | prévue (diagnostic) |
| transaction en tâche de fond (`background=1`) | `transactions_fond` | 2.7.0 | utilisée (gros lots) |
| objets JSON de Gramps 6.0 | `objets_json_gramps6` | 3.0.0 | utilisée |
| annuler depuis l'historique du serveur | `historique_annuler` | 3.4.0 | prévue |
| modifier le chercheur (`PUT /api/metadata/researcher/`) | `chercheur_modifier` | 3.9.0 | prévue |
| message de transaction (`message=`) | `transactions_message` | 3.13.0 | **utilisée : fixe le plancher** |
| réglages de l'arbre (`/api/trees/<id>/config`) | `arbre_config` | 3.13.0 | prévue |
| fusion native (`/api/<objets>/merge/`) | `fusion` | 3.15.0 | prévue |
| vérification de l'arbre (`/api/trees/-/verify`) | `verification` | 3.17.0 | prévue |
| requête d'objets (`POST /api/<objets>/query/`) | `requete_objets` | 3.21.0 | prévue |
| historique par objet (onglet Révisions) | `historique_objet` | 3.22.0 | prévue |
| règle `MatchesQuery` (`oql` retiré) | `regle_matches_query` | 3.23.0 | prévue |
| verrous de tâches (409 `task_locked`) | `verrous_taches` | 3.24.0 | prévue |
| `edit-by-handle` (`gql` retiré) | `edit_by_handle` | 3.26.0 | écartée pour les étiquettes (#262 : hors `/api/transactions/`, annulation non établie) |
| inscription libre lisible (`GET /api/register/config/`) | `inscription_libre` | 3.26.0 | utilisée (diagnostic) |

La recherche sémantique a été retirée de l'API en 3.25 ; Genealogiste ne l'utilise pas.

### Lancer la matrice

```bash
make test-gramps                     # image par défaut (26.11.0, API 3.25.1)
make test-gramps GRAMPSWEB_IMAGE=ghcr.io/gramps-project/grampsweb@sha256:… GRAMPSWEB_API=3.26.0
make test-gramps-matrice             # les trois images, bilan final ; ROLES="plancher plafond" pour filtrer
COMPOSE_PROJECT_NAME=gw-essai make test-gramps-matrice GW_PORT=5067   # à côté d'une autre pile de test
```

`GRAMPSWEB_API` fait vérifier la version servie par l'image et son appartenance à la plage. Chaque lancement
détruit le conteneur et ses volumes (`down -v`), même après un échec.

En CI, le workflow `Intégration Gramps` (`.github/workflows/gramps.yml`) lance un job par image et un job par
version de Gramps Desktop : sur les PR et les pushes vers `main` qui touchent l'intégration Gramps (code
`gramps/`, export Gramps XML, GEDCOM, fixtures, matrice, compose, Makefile), chaque mercredi (nouvelles
versions publiées, dérive des registres) et sur demande. Un échec sur une version prise en charge fait échouer
le workflow.

## Médias (images d'actes)

- `ajouter_media` (`fichier` : `reference_media` de `media_enregistrer` ou `fichier` de `piece_archiver`, ou
  chemin relatif au répertoire des médias ou au vault, résolu et normalisé à la proposition ; un fichier local
  introuvable est refusé, voir `docs/operations.md`) crée l'objet Media ; une citation le référence par `medias`
  (`media_list` de la citation Gramps, `OBJE` sous la citation en GEDCOM) : l'image prouve la citation.
- La proposition annonce les fichiers à envoyer (`transaction_gramps.fichiers_a_envoyer`, ou
  `fichiers_absents` pour un média existant dont le fichier a disparu). À l'envoi, un chemin relatif est résolu
  par la règle commune (données, répertoire des médias, arborescence des pièces ; refusé s'il est ambigu :
  `docs/operations.md`) ; les nouvelles références hors des données sont relatives à l'arborescence des pièces
  (#193). Après accord, la transaction crée l'objet, puis chaque fichier est envoyé par
  `PUT /api/media/{handle}/file` (`If-Match` = somme MD5 lue) ; le serveur attribue chemin et somme.
- Le chemin local est gardé dans l'attribut `Genealogiste-Fichier` (`Sosa-Fichier` dans une base non migrée) : le chemin du serveur n'est jamais réécrit.
- `modifier_media` (`arbre_proposer`) change le fichier, le titre ou le format d'un média : le chemin et la
  somme du serveur sont conservés, `Genealogiste-Fichier` est réécrit, et un nouveau contenu (MD5 différent) est envoyé
  après la transaction (`fichiers_a_envoyer`) ; un simple déplacement n'envoie rien.
- `gramps_relocaliser_medias(ancien_prefixe, nouveau_prefixe)` : après un changement de machine, propose en une
  transaction la réécriture des `Genealogiste-Fichier` qui commencent par l'ancien préfixe ; existence et MD5 vérifiés,
  médias introuvables ou au contenu différent listés à part et non modifiés. Application par `arbre_appliquer`,
  annulation par `arbre_annuler_modification` (voir `docs/operations.md`).
- `gramps_envoyer_medias` : liste des fichiers absents ou différents dans Gramps Web (médias créés avant cette
  version, bascule), puis envoi avec `appliquer=true` après accord. La bascule envoie aussi les fichiers.

## Lieux hiérarchiques

- Un lieu « Commune, Département, Pays » est écrit en hiérarchie Gramps : commune (type *City*, code INSEE,
  coordonnées) → département (*Department*, code du département) → pays (*Country*). Les lieux englobants sont
  partagés et réutilisés s'ils existent déjà sous le même nom complet.
- Le nom relu (commune, puis lieux englobants) est identique au nom écrit : l'aller-retour GEDCOM ↔ Gramps ne
  change pas. Une forme non canonique (espaces autour des virgules, niveau vide) reste à plat.
- La **région n'est pas ajoutée** : les régions actuelles (2016) seraient anachroniques pour des actes anciens et
  changeraient le nom du lieu. Une région déjà présente dans le nom devient un niveau *Region*.
- `gramps_structurer_lieux` : propose de rattacher les lieux à plat d'une base existante (titre complet, créés
  par une version antérieure ou un import) à cette hiérarchie ; diff puis accord, aucun événement modifié.

## Plusieurs arbres

Dans Gramps Web, **un compte appartient à un seul arbre** : l'arbre est inscrit dans le jeton de connexion
(revendication `tree`) et toutes les requêtes passent par lui. Gérer plusieurs arbres (familles, clients)
demande donc un compte Gramps par arbre et, côté Genealogiste, **un répertoire de données par arbre** (journal,
propositions, miroir Git et notes ne doivent jamais se mélanger).

Garde-fou : à la première connexion, l'arbre du compte est enregistré dans `<données>/GRAMPS_ARBRE.json` ; un
autre arbre est ensuite refusé avec un message explicite (lecture et écriture). Changement voulu : vérifier,
puis supprimer ce fichier.

Exemple : un serveur MCP par arbre (paramètres utilisateur de Claude Code, `.mcp.json`), les identifiants de
chaque arbre dans le `.env` de son répertoire de données :

```json
{
  "mcpServers": {
    "genealogiste-famille": {
      "command": "uv",
      "args": ["run", "--quiet", "--directory", "/chemin/vers/Genealogiste/mcp", "genealogiste-mcp"],
      "env": {"GENEALOGISTE_DATA_DIR": "~/genealogie/famille"}
    },
    "genealogiste-client-dupont": {
      "command": "uv",
      "args": ["run", "--quiet", "--directory", "/chemin/vers/Genealogiste/mcp", "genealogiste-mcp"],
      "env": {"GENEALOGISTE_DATA_DIR": "~/genealogie/client-dupont"}
    }
  }
}
```

```sh
# ~/genealogie/client-dupont/.env
GENEALOGISTE_BACKEND=gramps
GENEALOGISTE_GRAMPS_URL=https://gramps.exemple.org
GENEALOGISTE_GRAMPS_USER=sosa-dupont
GENEALOGISTE_GRAMPS_PASSWORD=…
```

Hors v1 : fusion native de Gramps (la fusion passe par `/fusionne`).

## Reprise des lectures

Les GET sont tentés au plus trois fois sur erreur réseau ou HTTP 502/503/504 (attentes de 2 puis
4 secondes). Un 401 de lecture autorise un renouvellement de jeton et une nouvelle lecture ; les autres
statuts ne déclenchent pas de reprise. Le jeton expiré localement est renouvelé avant tout appel.

Les appels `/token/` et `/token/refresh/` (limités à une requête par seconde, HTTP 429 au-delà) sont retentés
une seule fois après une pause d'environ une seconde.

POST, PUT et DELETE ne sont jamais rejoués automatiquement, y compris sur 401. Après un refus 401,
un nouvel appel explicite renouvelle d’abord le jeton. Après une réponse perdue pendant une écriture,
relire l’arbre et le journal avant de proposer une nouvelle opération : l’absence de réponse ne prouve
pas que la transaction a échoué.

Le miroir Git utilise l’état qui vient d’être lu, sans nouvelle synchronisation imbriquée : son message
conserve le bilan des modifications externes, même avec un TTL de zéro.
