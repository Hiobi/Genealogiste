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
| `GENEALOGISTE_GRAMPS_NOTES_LIENS` | `false` (défaut) : notes de preuve en texte simple, comme avant ; `true` : liens internes `gramps://` vers les personnes, événements, familles, sources et citations qu'elles citent ([#279](#texte-enrichi-et-liens-internes-279)). Changer la valeur ne réécrit aucune note : `gramps_recalculer_notes` propose le passage d'une forme à l'autre (diff, accord, journal, annulable) |
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
  `gramps_structurer_lieux`, `gramps_dater_lieux`, `gramps_normaliser_types`, `marqueurs_migrer_proposer`,
  annulation, `gramps_bascule_proposer`) refusent
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
| témoin, parrain, officier… de l'arbre | référence d'événement sur sa fiche (rôle standard : Witness, Godparent, Officiator, Father…, Informant ; personnalisé seulement sans équivalent, voir [Types](#types-personnalisés-et-libellés-français-273)) + attribut `Genealogiste-Association` |
| intervenant seulement nommé | attribut d'événement `Genealogiste-Association` « rang \| RÔLE \| précision \| nom \| » avec ses citations |
| parrain/marraine de niveau individu | `personref` + attribut de personne `Genealogiste-Association` « … \| xref » |
| citation | page, confiance (QUAY ; attribut `QUAY` si 2), notes `Transcript` / `Citation`, attributs Consulté, Type de source, Information, Preuve, Date de consultation, ARK |
| source | titre, auteur, publication, dépôt + cote, attributs URL, ARK, Type de source, Dérivée de |
| lieu | titre « Commune, Département, Pays », code INSEE, coordonnées ; paroisse en attribut d'événement ; noms et rattachements datés côté Gramps seulement, posés par `gramps_dater_lieux` ([#277](#noms-et-rattachements-datés-277)) |
| âge | attribut `Age` de la référence d'événement |
| cause, précision du type | attributs `Cause`, `Précision` |
| date GEDCOM 7 (et extensions) | date Gramps : calendrier, modificateur, qualité, valeur, nouvel an ; table complète ci-dessous ([Dates](#dates-272)) |
| étiquettes (`tags`) de personne, famille, événement, citation, source, dépôt, média, note partagée | `tag_list` (handles) + objets `Tag` ; voir « Étiquettes » ci-dessous |
| texte d'une note | `text.string` ; mise en forme (`text.tags` : gras, italique, liens…) gardée côté Gramps, écrite depuis du Markdown sur demande ([#279](#texte-enrichi-et-liens-internes-279)) |

Une personne, un événement ou une note créés dans l'interface Gramps sont lus sans attribut `Genealogiste-*` et
réécrits **à l'identique** tant que Genealogiste ne les modifie pas. Ce que Genealogiste ne modélise pas (adresses, URL,
étiquettes des lieux et des notes « en ligne », couleur et priorité des étiquettes, titres et suffixes de nom, noms
alternatifs et rattachements datés des lieux — posés seulement par `gramps_dater_lieux`, voir
[#277](#noms-et-rattachements-datés-277) —, médias d'événements, notes isolées…) est conservé tel quel.

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

### Dates (#272)

Correspondance unique (`gramps/types.py` : `date_to_gramps`, `date_from_gramps`), utilisée par le mode direct,
l'export et l'import Gramps XML. Le modèle garde une date GEDCOM 7 ; ce que GEDCOM 7 n'exprime pas s'écrit avec
les extensions de date de [docs/gedcom-extensions.md](gedcom-extensions.md#dates-gramps-272), relues à
l'identique. **Critère : une date lue dans Gramps est réécrite à l'identique tant qu'elle n'est pas modifiée.**
En mode direct, une date non modifiée garde son objet d'origine (texte compris) ; sans état lu (import Gramps XML
puis export, bascule), tout ce que l'objet Date porte revient identique : calendrier, modificateur, qualité,
valeur (double datation comprise), nouvel an, texte d'une date textuelle et valeur de tri recalculée comme
Gramps (calendriers de `gcalendar.py` portés dans `normalize/calendriers.py`). Vérifié sur 1 225 formes
(`mcp/tests/dates_gramps.py`) : avant #272, 1 135 ne revenaient pas à l'identique sans état lu ; aucune depuis.

| Forme Gramps (JSON ; Gramps XML) | Date du modèle (GEDCOM 7) | Statut |
|---|---|---|
| grégorien (`calendar` 0) ; sans `cformat` | `12 MAR 1850`, `MAR 1850`, `1850` | GEDCOM 7, exact |
| julien (1) ; `cformat="Julian"` | `JULIAN 12 FEB 1721` (5.5.1 : `@#DJULIAN@`) | GEDCOM 7, exact |
| hébreu (2) ; `cformat="Hebrew"` | `HEBREW 10 NSN 5600`, mois 1 à 13 = `TSH CSH KSL TVT SHV ADR ADS NSN IYR SVN TMZ AAV ELL` (5.5.1 : `@#DHEBREW@`) | GEDCOM 7, exact |
| républicain (3) ; `cformat="French Republican"` | `FRENCH_R 12 VEND 3`, mois 13 = `COMP` (5.5.1 : `@#DFRENCH R@`) | GEDCOM 7, exact |
| persan (4), islamique (5), suédois (6) | `_PERSIAN 12 FARVA 1300`, `_ISLAMIC 12 MUHAR 1300`, `_SWEDISH 12 MAR 1705` | extension, exact |
| aucun modificateur (0) ; `<dateval val>` | `12 MAR 1850` | GEDCOM 7, exact |
| before (1), after (2), about (3) ; `type="before|after|about"` | `BEF …`, `AFT …`, `ABT …` | GEDCOM 7, exact |
| from (7), to (8) seuls ; `type="from|to"` | `FROM 1850`, `TO 1850` | GEDCOM 7, exact (Gramps 5.2 à 6.1 ; hors DTD avant 6.1 : [Gramps Desktop](gramps.md#dates-et-gramps-52)) |
| range (4) ; `<daterange start stop>` | `BET 1850 AND 1860` | GEDCOM 7, exact |
| span (5) ; `<datespan start stop>` | `FROM 1850 TO 1860` | GEDCOM 7, exact |
| plage aux bornes dans l'ordre inverse | `BET 1860 AND 1850` | exact (Gramps l'admet ; le modèle la signale à la cohérence) |
| estimated (1), calculated (2) seuls ; `quality=` | `EST 1850`, `CAL 1850` | GEDCOM 7, exact |
| qualité + modificateur | `EST BEF 1850`, `CAL ABT 1850`, `EST BET 1850 AND 1860`, `CAL FROM 1850 TO 1860` | extension (lue telle quelle par l'import GEDCOM de Gramps), exact |
| année négative ; `val="-0100"` | `100 BCE`, `BET 120 BCE AND 100 BCE` (5.5.1 : `B.C.`) | GEDCOM 7, exact |
| jour sans mois ; `val="1850-??-12"` | `12 ? 1850` | extension, exact |
| année inconnue ; `val="????-03-12"` | `12 MAR ?`, `MAR ?` | extension, exact |
| bout vide d'une plage ; `stop=""` | `BET 1850 AND ?`, `FROM 1850 TO ?` | extension, exact |
| date vide portant un calendrier, un modificateur ou une qualité (JSON seulement : Gramps XML ne l'écrit pas) | `JULIAN ?`, `BEF ?`, `EST ?`, `BET ? AND ?` | extension, exact |
| double datation (`dateval[3]`, année nouveau style : 1722) ; `dualdated="1"` | `JULIAN 12 FEB 1721/22` | extension (syntaxe GEDCOM 5.5.1), exact ; Gramps la range toujours en julien |
| double datation d'un seul bout d'une plage | `BET JULIAN 1721/22 AND JULIAN 1725` | exact en JSON ; Gramps XML n'a qu'un `dualdated` pour les deux bouts (celui du début), comme chez Gramps |
| nouvel an Mar1 (1), Mar25 (2), Sep1 (3), (mois, jour) ; `newyear=` | suffixe `12 FEB 1721 (Mar25)`, `JULIAN 12 OCT 1721 (4-15)` | extension, exact (grégorien, julien, suédois seulement, comme Gramps) |
| date textuelle (`modifier` 6) ; `<datestr val>` | le texte : `vers la Saint-Jean` ; entre parenthèses s'il serait relu autrement : `(1850)`, `()`, `(  espaces  )` | exact |
| `sortval` | recalculée comme Gramps (`Date._calc_sort_value`, `_adjust_newyear`) | exact (comparée à Gramps 5.2.4, 6.0.8, 6.1.0-beta2) |
| `text` d'une date non textuelle | gardé comme date du modèle s'il relit exactement les mêmes champs (`abt 1850`, phrase `1850 (vers Pâques)`) | écrit dans `text` seulement s'il diffère de la forme canonique (sinon `text` vide, comme après un import Gramps XML) ; Gramps XML ne l'écrit pas |
| date que `Date.set` de Gramps refuse (30 février, plage au début vide, deux calendriers…) | à l'écriture : date textuelle portant la chaîne ; à l'import XML : date textuelle portant l'élément XML, comme Gramps | conforme à Gramps |

Écart connu de Gramps Web (API ≥ 3.25, gramps-web-api#869) : le serveur recalcule `sortval` à chaque écriture
par `Date.recalc_sort_value`, sans le décalage de nouvel an qu'applique `Date.set` (Gramps Desktop,
Genealogiste) ; une date à nouvel an décalé postérieure à la coupure y garde donc une valeur de tri d'un an plus
tardive. Sans effet sur la date elle-même, relue et réécrite à l'identique (vérifié par `make test-gramps`).

Non représentable, signalé : le `text` d'une date non textuelle qui ne relit pas les mêmes champs (saisie dans
une autre langue, texte périmé après modification dans Gramps Web) est remplacé par la forme du modèle à la
première écriture sans état lu ; `format` (format d'affichage) n'est pas porté ; une date sans valeur ni attribut
qui garde un texte est lue comme date textuelle (comme l'export GEDCOM de Gramps) ; une double datation sur un
point sans année est perdue (comptée dans `non_repris` de l'import : `Event.date[forme non reprise]`).

`convertir_date` renvoie aussi `gramps` : `date` (objet Date JSON de Gramps Web), `xml` (élément Gramps XML) et
`affichage` (affichage de Gramps en anglais, format ISO par défaut, identique à `DateDisplayEn` sur les 1 220
formes acceptées de l'inventaire).

Lecture GEDCOM 5.5.1, alignée sur ce que Gramps écrit et relit : double datation `1721/22` (année nouveau style
1722, et non plus 1721), `@#DHEBREW@`, `B.C.`, phrase d'une date `INT 1850 (texte)` gardée (`1850 (texte)`) ; en
GEDCOM 7, `DATE` + `PHRASE` donne `1850 (texte)`. Les 502 rendus 5.5.1 de l'inventaire en calendrier grégorien,
julien, hébreu ou républicain sans `?` sont relus par l'import GEDCOM de Gramps 6.0.8 : 483 à l'identique ; les
autres sont des limites de Gramps (année double seule `1699/00`, nouvel an d'une plage).

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

### Types personnalisés et libellés français (#273)

**Comment Gramps stocke un type.** Type d'événement, rôle, attribut, note, lieu, nom, origine de patronyme,
relation familiale, filiation, dépôt, support, lien : en JSON (Gramps 6, API), `{"_class", "value", "string"}`. Un
type **standard** a son code (`value` : 15 pour *Baptism*) et une chaîne vide ; un type **personnalisé** a la
valeur « personnalisé » (0 ; 4 pour `FamilyRelType`, 7 pour `ChildRefType`) et le texte saisi dans `string`. En
Gramps XML, `type="…"` porte la chaîne XML anglaise du type standard (`Baptism`) ou le texte du type
personnalisé ; à la lecture, une chaîne XML connue redevient le type standard (`set_from_xml_str`), toute autre
reste personnalisée. Les lectures de l'API rendent la chaîne XML ; à l'écriture, l'API accepte la chaîne XML ou le
libellé anglais (serveur en anglais) : « Baptême » y devient un type **personnalisé**.

**Ce que voit l'utilisateur.** Gramps Web et Gramps Desktop affichent les types standard **traduits** (catalogue
`fr.po`) : le standard *Baptism* s'affiche « Baptême », exactement comme un type personnalisé « Baptême ». À
l'écran rien ne les distingue ; dans les données, si (filtres, rapports, statistiques, export GEDCOM : `BAPM` d'un
côté, `EVEN` + `TYPE Baptême` de l'autre). Dans Gramps Desktop en français, saisir exactement le libellé traduit
choisit le type standard ; une variante (« baptême », « Bapteme »), un import GEDCOM ou CSV crée un type
personnalisé. Dans Gramps Web, l'interrupteur « Personnalisé » crée toujours un type personnalisé.

**Référentiel.** `mcp/src/genealogiste_mcp/referentiels/types_gramps.json`, généré par
`scripts/generer_types_gramps.py` depuis les sources de Gramps (`gramps/gen/lib/*type.py`, `_DATAMAP` lu sans
importer Gramps, et `po/fr.po` de la même branche, contexte `msgctxt` respecté, entrées « fuzzy » ignorées comme par
`msgfmt`) : par classe, chaque type standard (chaîne XML), sa valeur, sa version d'apparition et ses libellés
anglais et français **par version**. Provenance : <https://github.com/gramps-project/gramps>, branches
`maintenance/gramps52` (`14c01e56f088a865cd1f5a78708357237b74d92d`, 5.2.5), `maintenance/gramps60`
(`32aa29629b94c549f232cd0b61c137ae95d73acf`, 6.0.8), `maintenance/gramps61`
(`e9c09a44791def6a6b81079dc7f8cbe8c7e69cc0`, 6.1.0-beta2) ; données sous GPL-2.0-or-later, redistribuées sous
GPL-3.0. Un test vérifie que les tables de `gramps/types.py` concordent avec le référentiel ; `--verifier` contrôle
que le fichier versionné correspond aux sources.

| Différence entre versions | Types |
|---|---|
| 5.2 → 6.0 | `EventRoleType` : Father (Père), Mother (Mère), Parent, Child (Enfant), Multiple birth (Naissance multiple), Friend (Ami(e)), Neighbor (Voisin(e)), Officiator (Officiant) |
| 5.2 → 6.0, libellés seulement | `NameOriginType` : contexte « Surname » ajouté à Unknown, Occupation, Location (Location : « Emplacement » en 5.2, « Lieu » ensuite ; Unknown : « Inconnu », « Unknown » faute de traduction en 6.0, « Inconnue » en 6.1) ; `ChildRefType` Adopted : non traduit en 5.2, « Adopté(e) » ensuite |
| 6.0 → 6.1 | aucun type ajouté ni retiré |
| après 6.1 (branche master) | types ADN, hors référentiel tant qu'ils ne sont pas publiés |

**Lecture.** Un type personnalisé dont la chaîne est un libellé d'un type standard **de sa classe** (libellé
français de l'une des trois versions, libellé anglais ou chaîne XML ; comparaison sans casse, accents, espaces
superflus, et apostrophe droite ou typographique confondues) est compris par le modèle comme ce type standard :
événement « Baptême » → `BAPM`, « Recensement » → `CENS`, « Bénédiction » → `EVEN` + `TYPE Blessing` (type sans code
GEDCOM : chaîne XML, comme un *Blessing* standard) ; rôle « Témoin » → `WITN`, « Principal » → événement propre ;
attribut de référence « Âge » → âge ; note « Note sur l'individu » → note de personne, « Transcription » →
transcription de citation ; nom « Alias » → `AKA` ; filiation « Adopté(e) » → `ADOPTED`. Les libellés écrits par
Genealogiste avant #273 pour des rôles qui ont un type standard (« Père », « Mère », « Enfant », « Ami »,
« Voisin », « Plusieurs ») sont lus de même, sans limite de durée (`ANCIENS_LIBELLES`). **Sans ambiguïté**
seulement : un libellé de plusieurs types standard n'est pas reconnu et reste tel quel :

| Classe | Libellé | Types standard |
|---|---|---|
| `EventRoleType` | Officiant | Celebrant (5.2 et suivantes), Officiator (6.0 et suivantes) |
| `SourceMediaType` | Fiche | Card (« Fiche » en français), Fiche (chaîne XML ; « Microfiche » en français) |

La lecture ne modifie **jamais** l'objet Gramps : relu puis réécrit sans changement, il garde son type personnalisé
d'origine (aucune migration silencieuse, même règle que les marqueurs historiques et les dates). Une référence
d'événement saisie dans l'interface (rôle « Témoin », sans attribut `Genealogiste-Association`) reste identique
tant que les intervenants de l'événement ne changent pas (avant #273, elle recevait le rôle *Witness* et l'attribut
à la première écriture). Le compteur `non_repris` d'un import Gramps XML range un attribut sous son type standard
(« Âge » et *Age* : `[Age]`) : un libellé reconnu n'est plus compté comme perdu.

**Écriture.** Un objet nouveau, ou dont le type change, reçoit le type **standard** quand il en existe un, y
compris quand la précision du modèle en est un libellé (événement `EVEN` « Bénédiction » → *Blessing*) ;
personnalisé seulement sinon. Un objet existant garde sa forme tant que son type ne change pas. Rôles des
intervenants nouveaux ou modifiés :

| Rôle du modèle | Avant #273 | Depuis #273 |
|---|---|---|
| `WITN`, `CLERGY` | Witness, Clergy | inchangé |
| `OFFICIATOR` | Celebrant | Officiator (6.0) |
| `GODP` | Godparent, ou la précision (« Parrain ») | Godparent (la précision reste dans `Genealogiste-Association`) |
| `FATH`, `MOTH`, `CHIL` | « Père », « Mère », « Enfant » | Father, Mother, Child (6.0) |
| `FRIEND`, `NGHBR`, `MULTIPLE` | « Ami », « Voisin », « Plusieurs » | Friend, Neighbor, Multiple birth (6.0) |
| `PARENT` | Parent | inchangé (standard en 6.0) |
| déclarant (« Déclarant » en précision) | Informant | inchangé |
| `HUSB`, `WIFE`, `SPOU`, `OTHER` | précision, sinon « Époux », « Épouse », « Conjoint », « Autre » | inchangé (pas de type standard) ; une précision qui est le libellé d'un rôle standard donne ce rôle |

Une précision, un âge ou des citations qui changent sans que le rôle change gardent le rôle existant.

**Versions.** Gramps Web repose sur Gramps ≥ 6.0 : les rôles Father… Officiator y sont standard. L'export Gramps
XML 1.7.1 destiné à Gramps 5.2 les écrit sous leur chaîne XML ; Gramps 5.2 les **lit comme des rôles
personnalisés** portant la même chaîne (aucune perte, mais pas de type standard ; constaté avec la bibliothèque
5.2.4, cas `types` du banc Desktop, [Gramps Desktop](gramps.md#types-et-versions-de-gramps-273)). Pas de repli
silencieux vers Celebrant : relus par Genealogiste, ces rôles personnalisés redonnent les rôles du modèle.

**Lieux.** Les libellés français des `PlaceType` de Gramps sont reconnus : « Pays » (*Country*), « Département »
(*Department*), « Région » (*Region*), « Paroisse » (*Parish*), « Ville » (*City*), « Bourg » (*Town*), « Village »,
« Hameau » (*Hamlet*), « Lieu-dit » (*Locality*), « Municipalité » (*Municipality*), « Quartier »
(*Neighborhood*), « Rue » (*Street*), « Province », « Ferme », « Immeuble », « Numéro », ainsi que « Comté
(Départ.) » (*County*), « Province (Région) » (*State*), « District (Arrondissement) » (*District*) et « Borough
(Arrondissement) » (*Borough*) écrits exactement ainsi. « Commune », « Canton » et « Arrondissement » ne sont
**pas** des libellés de Gramps (Commune pourrait être *City*, que Genealogiste écrit, ou *Municipality*) : ils
restent personnalisés, jamais tranchés. Le type de lieu ne fait pas partie du modèle (nom « Commune, Département,
Pays ») ; il sert à `gramps_structurer_lieux` (un lieu à plat de type personnalisé « Ville » est traité comme
*City* : rattaché, il reçoit le type standard, comme tout objet modifié), à `gramps_dater_lieux` (un lieu
personnalisé « Commune » est identifié comme commune, sans que son type change) et à la normalisation, qui ne
tranche jamais « Commune ». L'écriture de la hiérarchie (commune *City*, département *Department*, pays
*Country*) et de la paroisse (attribut d'événement) ne change pas (#277).

**Détection.** `arbre_coherence` sur tout l'arbre, en mode gramps, ajoute une alerte `type_personnalise_doublon`
(niveau `info`) par classe et par libellé (classe, chaîne, type standard et son libellé, nombre d'objets de
premier niveau et d'occurrences) et `type_personnalise_ambigu` pour un libellé de plusieurs types. Choix de
`arbre_coherence` plutôt que `diagnostic` : le diagnostic contrôle l'exploitation (configuration, versions,
joignabilité) sans lire l'arbre et doit fonctionner même mal configuré ; la cohérence lit déjà tout l'arbre et
signale ses défauts de données (cycles, références cassées). Aucune requête supplémentaire : la base déjà lue
sert.

**Normalisation explicite.** `gramps_normaliser_types(classes?)` (mode gramps, classe *proposition*) prépare
**une** transaction : chaque type personnalisé qui désigne sans ambiguïté un type standard devient ce type, en
place. Bilan par classe et par libellé (`bilan_types` : type standard, objets, occurrences), objets touchés
(`transaction_gramps`), libellés ambigus listés (`ambigus`), jamais tranchés. Seul le type change : handles,
`gramps_id`, valeurs, citations et positions inchangés, aucun objet créé ni supprimé ; le modèle lu (et donc le
miroir Git et les exports GEDCOM) ne change pas. Appliquée par `arbre_appliquer` après accord, journalisée dans
`gramps-transactions.jsonl`, annulable par `arbre_annuler_modification`. `classes` limite aux classes Gramps
voulues (`EventType`, `EventRoleType`, `AttributeType`, `NoteType`, `PlaceType`, `NameType`, `NameOriginType`,
`FamilyRelType`, `ChildRefType`, `RepositoryType`, `SourceMediaType`, `UrlType`, `SrcAttributeType`). Deuxième
exécution : rien à faire (pas de jeton).

## Notes de preuve générées (`Genealogiste:auto`)

Statut de preuve de chaque fait (note *Research* + étiquette « Preuve : … » sur l'événement), fiche de preuve
de la personne, filiations de la famille, lien cliquable des sources : notes étiquetées **`Genealogiste:auto`**
(ou `Sosa:auto` dans une base non migrée),
recalculées à chaque écriture et ignorées à la lecture. Après des modifications faites dans l'interface,
`gramps_recalculer_notes` propose leur recalcul (toute la base, même en mode `modifies` ; refusé en mode
`false`). Les notes manuelles ne sont **jamais** modifiées. Liens internes `gramps://` vers les objets cités :
`GENEALOGISTE_GRAMPS_NOTES_LIENS` ([ci-dessous](#texte-enrichi-et-liens-internes-279)).

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

### Texte enrichi et liens internes (#279)

Module `gramps/texte.py` (fonctions pures, appelées par `gramps/mapping.py` : un seul chemin).

**Forme** (Gramps `gen/lib/styledtext.py`, `styledtexttag.py`, `styledtexttagtype.py`, identiques en 5.2
`maintenance/gramps52` 14c01e5, 6.0 `maintenance/gramps60` 32aa296 et 6.1 `maintenance/gramps61` e9c09a4) :
`text = {"_class": "StyledText", "string": …, "tags": [{"name": <StyledTextTagType>, "value": …, "ranges":
[[début, fin], …]}]}`. Onze styles, les mêmes dans les trois versions : `bold`, `italic`, `underline`,
`fontface` (texte), `fontsize` (entier), `fontcolor` et `highlight` (couleur), `superscript`, `subscript`,
`strikethrough`, `link` (URL). Plusieurs styles peuvent se chevaucher, un même style apparaître plusieurs fois :
Gramps ne fusionne qu'à l'affichage. Le DTD et le RNG livrés (5.2 à 6.1) ne citent pas `strikethrough` ni
`subscript`, que Gramps écrit et relit pourtant (voir [Gramps Desktop](gramps.md#contenu-écrit)).

**Plages : points de code Unicode**, `[début, fin)` en indices de chaîne Python. Gramps découpe
`str(text)[début:fin]` (`gen/plug/docbackend/docbackend.py`, `add_markup_from_styled` : « unicode text must be
sliced correctly ») ; Gramps Desktop compte les caractères GTK (`TextIter.get_offset`,
`gui/widgets/styledtextbuffer.py`) ; l'éditeur de Gramps Web compte aussi en points de code
(`src/components/GrampsjsEditor.js`, « Unicode code-point offset », gramps-web 26.11.3 `20c7655`). Jamais des
unités UTF-16 : 🟡 (hors plan de base) compte 1, ⚠️ (U+26A0 + U+FE0F) compte 2.

**Liens** : style `link`, valeur = URL. Lien interne `gramps://<Classe>/handle/<handle>` (forme écrite par
l'éditeur de lien de Gramps, `gui/editors/editlink.py`, et seule retraduite par l'import XML,
`plugins/importer/importxml.py` `grampsuri`) ; `gramps://<Classe>/gramps_id/<id>` est aussi lu par Gramps et
Gramps Web (`plugins/lib/libhtmlbackend.py`, `format_link`). Lien externe : l'URL telle quelle (`https://…`).

**Notes manuelles** : réécrites à l'identique (texte, styles, étiquettes, type, confidentialité) tant que leur texte
ne change pas, y compris quand l'objet qui les porte est modifié (tests : les onze styles sur notes de personne,
partagée, d'événement, de source et de citation). Quand le texte d'une note existante change (`modifier_evenement`
`champs.note`, note partagée…), la note **garde son handle, ses étiquettes, son type et sa confidentialité** ;
règle des plages : un style dont la plage reste entière dans le **préfixe commun** inchangé est gardé, dans le
**suffixe commun** il est décalé, tout autre (plage touchée par la modification ou hors bornes) est retiré **et
annoncé** dans `avertissements` (« Note N0500 réécrite : mise en forme retirée (plage modifiée) : fontcolor #ff0000
« rouge » [6, 11) »). Jamais de plage hors bornes, jamais de perte silencieuse. Champ unique à plusieurs notes
(note d'événement, de source) : les notes dont le texte reste en tête ou en queue (séparateur « \n\n ») sont gardées
telles quelles, la première des autres reçoit le texte du milieu.

**Markdown simple** (`format_texte: "markdown"` sur une opération, voir [opérations](operations.md#texte-enrichi-des-notes-279)) :
`**gras**`, `*italique*` ou `_italique_`, `[texte](url)` avec `http(s)://`, `mailto:` ou un lien interne
`gramps://Classe/handle|gramps_id/…`, échappement `\` de `\ * _ [ ]`. Rien d'autre : titres, listes, tableaux,
HTML, code restent du texte brut, caractère pour caractère. Une emphase ne traverse pas une fin de ligne ; un
marqueur non fermé, `_` à l'intérieur d'un mot, une URL à schéma refusé (`javascript:`, `data:`, `file:`…) ou
contenant blanc ou crochet restent du texte. Par défaut (`texte`), rien n'est interprété : un `*` reste un `*`.
Aucune note existante n'est convertie. Un lien interne vers un objet absent est retiré et annoncé. Sens inverse :
`vers_markdown` (aller-retour stable sur le sous-ensemble) liste ce qui ne s'écrit pas en Markdown (police,
taille, couleur, surlignage, souligné, barré, exposant, indice, lien à autre schéma, liens qui se chevauchent,
emphases adjacentes ambiguës) ; il n'est pas encore exposé par un outil.

**Backend fichier** : le modèle (GEDCOM 7) ne porte que le texte des notes. La mise en forme reste côté Gramps,
préservée par-dessus l'état lu ; une opération `format_texte: "markdown"` en mode fichier enregistre le texte brut
et l'annonce dans `avertissements`. Import d'un fichier Gramps (`arbre_importer_gedcom`) : les styles non repris
sont comptés dans `non_repris` (`Note.text.tags[]`). Exports (GEDCOM, Gramps XML, GeneWeb) : depuis le modèle,
donc sans mise en forme ni lien interne (aucun handle publié).

**Liens internes des notes de preuve** (`GENEALOGISTE_GRAMPS_NOTES_LIENS=true`) : le texte visible ne change pas
(gabarits de `looks_generated` intacts, adoption des notes sans étiquette inchangée) ; seuls des styles `link` sont
ajoutés, vers les objets réellement écrits dans la même transaction (handles déterministes pour les nouveaux),
jamais vers un objet absent :

| note | plage | cible |
|---|---|---|
| fiche de preuve de la personne | `I12` de « réf. I12 » | la personne |
| | libellé de chaque fait (« Naissance 3 MAY 1846 ») | l'événement (de la personne ou de sa famille) |
| | « Filiation » | la famille des parents |
| statut de preuve d'un événement | titre de la source d'un acte de « Acte(s) cité(s) mais non vu(s) » | la source |
| | page / cote de cet acte | la citation (le titre, si la citation n'a pas de page) |
| filiations de la famille | nom de chaque enfant | la personne |

Le lien de source « Lien : https://… » garde sa forme. Exemple (fiche de preuve, `famille.ged`) :

```json
{"string": "Fiche de preuve (plugin genealogiste) — réf. I3\n⚠️ Naissance 3 MAY 1846 : contradictoire\n…\n🟢 Filiation : probable\n…",
 "tags": [{"name": "link", "value": "gramps://Person/handle/e44dc5f86a9d2ba3d1c4f803", "ranges": [[45, 47]]},
          {"name": "link", "value": "gramps://Event/handle/560a2f0bfbe02046f317dfae", "ranges": [[51, 71]]},
          {"name": "link", "value": "gramps://Event/handle/aebdf08198fbadc6703727f5", "ranges": [[92, 106]]},
          {"name": "link", "value": "gramps://Family/handle/3c8d1919bfd1afa27f41e48d", "ranges": [[126, 135]]}]}
```

**Activer ou désactiver** ne réécrit rien tout seul : une note générée dont le texte ne change pas garde sa forme
(avec ou sans liens) ; une note créée ou dont le texte change prend la forme de l'option. Le passage de toutes les
notes se fait par `gramps_recalculer_notes` (diff, accord, `arbre_appliquer`, journal, annulable) ; le bilan
`transaction_gramps.liens_internes` compte les notes qui gagnent (`notes_avec_liens_ajoutes`) ou perdent
(`notes_avec_liens_retires`) des liens, et l'avertissement « transaction massive » cite ce cas. Un second recalcul
ne propose rien. Option désactivée : sortie strictement identique à celle d'avant #279 (empreintes des fixtures).
En mode `modifies`, seules les notes des objets touchés sont entretenues.

**Rendu par Gramps Web** (`GET /api/notes/<h>?formats=html`, `api/html.py`, bleach) : gras → `<strong>`,
italique → `<em>`, barré → `<s>`, souligné, police, taille et couleurs → `<span style=…>`, lien externe →
`<a href>` ; exposant et indice ne passent pas le filtre (texte gardé). Lien interne : souligné sans `<a>`, sauf
avec `format_options={"link_format": "…/{obj_class}/{gramps_id}"}` (ce que fait le frontend, et pour les billets
de blog : `GrampsjsViewBlogPost.js`), qui donne `<a href="…/person/I1">`. Relevé le 2026-11-21 sur les trois
images de la matrice (API 3.13.0, 3.25.1, 3.26.0 ; Gramps 6.0.8) : HTML identique, par exemple
`<strong>Acte</strong> de <em>naissance</em> : <a href="https://archives.exemple.org/a_(b)">registre</a> et
<a href="/person/I1">Jean</a>` et, pour une fiche de preuve, `réf. <a href="/person/I1">I1</a>`,
`✅ <a href="/event/E3effe1be">Naissance 12 MAR 1820</a>`, `⛔ <a href="/family/F2">Filiation</a>`. Une note
stylée saisie comme l'interface (styles sans `_class`, nom en chaîne) est relue avec les noms en objets
`StyledTextTagType` et réécrite à l'identique.

**Billets de blog (#261)** : un billet est une source étiquetée `Blog` dont la première note est le corps, rendue
par ce même HTML ; une note écrite avec `format_texte: "markdown"` y apparaît donc avec gras, italique et liens.

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
| nom du lieu à la date de l'événement (`place_name` du profil d'événement) | `nom_lieu_date` | 3.26.0 | constatée (#277) : avant, l'interface affiche le nom principal du lieu, `place` (`display_event`) a déjà le nom d'époque |

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

### Noms et rattachements datés (#277)

Gramps date les **noms** d'un lieu (`alt_names`, et la date du nom principal) et ses **rattachements**
(`placeref_list`, une date par lieu englobant). `gramps_dater_lieux` (mode gramps, classe *proposition*) les pose
pour les communes d'après le Code officiel géographique (COG) de l'INSEE, la source de `geo_historique` ;
**jamais automatiquement** : une transaction proposée (diff, jeton), écrite par `arbre_appliquer` après accord,
journalisée dans `gramps-transactions.jsonl`, annulable par `arbre_annuler_modification`. Deuxième exécution :
rien à faire, pas de jeton.

**Règle de Gramps** (lue dans le code ; identique sur `maintenance/gramps52` 14c01e56, `maintenance/gramps60`
32aa2962 et `maintenance/gramps61` e9c09a44) : `PlaceDisplay.display_event` (`gramps/gen/display/place.py`)
affiche le lieu à la date de l'événement par `get_location_list(db, lieu, date)`
(`gramps/gen/utils/location.py`) :

- nom : le **premier** de `[nom principal] + noms alternatifs` dont la date est vide ou correspond à la date de
  l'événement (un nom de la langue du format d'affichage est rendu aussitôt, sinon le premier qui correspond) ;
  aucun : « ? ». Un nom principal **sans date l'emporte donc toujours** ;
- lieu englobant : le premier rattachement dont la date est vide ou correspond ; on remonte ainsi jusqu'au pays ;
- correspondance (`Date.match_exact`, `gramps/gen/lib/date.py`) : « avant D » et « jusqu'à D » valent pour un
  événement **strictement** antérieur à D, « après D » et « depuis D » strictement postérieur, une plage
  (« de… à… », « entre… et… ») bornes comprises, une date simple le même jour ; « vers » et une date textuelle ne
  correspondent jamais. Un événement sans date vaut 0 : seuls « avant » et les dates vides lui correspondent.

**Ce que la proposition écrit**, pour chaque lieu identifié comme commune (code INSEE ; type *City*, *Town*,
*Village*, *Municipality*, ou personnalisé « Commune », que Gramps n'a pas : identifié sans que son type change) :

- **noms** : chaque nom antérieur du COG (changement de nom, commune nouvelle qui prend un autre nom, nom
  repris après rétablissement) devient un nom alternatif daté, et le nom principal (inchangé) est daté de son
  entrée en vigueur. Périodes contiguës, sans jour sans nom ni recouvrement : le premier nom vaut « avant » la
  date du changement (son début est inconnu : le COG commence en 1943), un nom intermédiaire « du » premier jour
  « au » dernier jour de sa période (plage), le nom actuel « après » la veille de son entrée en vigueur ;
- **ancien département** (changement de code de la commune, MOD 41 du COG : Seine et Seine-et-Oise en 1968,
  Corse en 1976, transferts entre départements) : le rattachement actuel est daté « après » la veille du
  changement, et un rattachement à l'ancien département (lieu *Department* réutilisé, sinon créé sous le même
  pays, code de l'ancien département) daté « avant » ;
- **commune déléguée** d'une commune nouvelle (ou associée) : rattachement à la commune nouvelle daté « après »
  la veille de la création, rattachement au département daté « avant », si le lieu de la commune nouvelle (même
  code INSEE) est dans la base.

Exemple, Charleville-Mézières (fusion de 1966) et Boulogne-Billancourt (Seine → Hauts-de-Seine), JSON Gramps
(dates abrégées aux champs utiles) :

```json
{"gramps_id": "P010304", "title": "", "code": "08105", "place_type": {"_class": "PlaceType", "value": 4},
 "name": {"_class": "PlaceName", "value": "Charleville-Mézières", "lang": "",
          "date": {"_class": "Date", "modifier": 2, "dateval": [30, 9, 1966, false]}},
 "alt_names": [{"_class": "PlaceName", "value": "Charleville", "lang": "",
                "date": {"_class": "Date", "modifier": 1, "dateval": [1, 10, 1966, false]}}],
 "placeref_list": [{"_class": "PlaceRef", "ref": "<Ardennes>", "date": {"_class": "Date", "modifier": 0}}]}

{"gramps_id": "P6ee1c7", "code": "92012", "name": {"value": "Boulogne-Billancourt", "date": {"modifier": 0}},
 "placeref_list": [
   {"_class": "PlaceRef", "ref": "<Hauts-de-Seine>", "date": {"modifier": 2, "dateval": [31, 12, 1967, false]}},
   {"_class": "PlaceRef", "ref": "<Seine>", "date": {"modifier": 1, "dateval": [1, 1, 1968, false]}}]}
```

En Gramps XML : `<pname value="Charleville"><dateval val="1966-10-01" type="before"/></pname>`,
`<placeref hlink="…"><dateval val="1967-12-31" type="after"/></placeref>`, plage en `<datespan>`.

**Diff** : une ligne par lieu (`lieux` : « P010304 Charleville-Mézières, Ardennes, France : +« Charleville »
avant 1966-10-01 ; nom principal « Charleville-Mézières » après 1966-09-30 »), plus le bilan de la transaction.
Listés à part, jamais tranchés :

- `conflits` : nom alternatif ou rattachement déjà saisi sur la même période (même langue), nom principal ou
  rattachement actuel déjà daté autrement, nom du lieu différent du nom actuel du COG (ex. lieu nommé
  « Charleville » avec le code 08105), lieu rattaché à autre chose que son département actuel. Le volet en
  conflit (noms, ou rattachements) est laissé tel quel pour ce lieu ;
- `lieux_distincts` : communes réunies (fusion, commune nouvelle) dont un lieu existe aussi dans la base, par
  son code INSEE ou son nom dans le même département (« l'acte dit Mézières ») : gardées distinctes, **jamais
  fusionnées** ;
- `non_traites` : lieu à plat (rattachements possibles après `gramps_structurer_lieux`), commune nouvelle
  absente de la base, rattachement terminé (commune rétablie) ou cumulé avec un changement de département ;
- `codes_inconnus_du_cog`.

**Événements sans date, annoncés avant l'accord.** Un événement de valeur de tri 0 — date vide, ou date
textuelle, y compris une date invalide importée comme texte (`Date.set_as_text`, `_calc_sort_value` de Gramps) —
ne correspond qu'aux noms et rattachements « avant » : après datation, Gramps lui affiche le nom le plus ancien et
l'ancien département au lieu du nom actuel. La proposition le simule pour chaque événement concerné (lieu affiché
avant et après, la date de l'événement étant 0) et l'annonce au même niveau que le bilan : `evenements_non_dates`,
une ligne par lieu modifié (« P010304 Charleville-Mézières, Ardennes, France : 2 événement(s) sans date
afficheront « Charleville, Ardennes, France » au lieu de « Charleville-Mézières, Ardennes, France » (E…) »),
`nombre_evenements_non_dates`, et un `avertissement` global dès qu'il y en a un. Un événement daté, même « vers »,
n'est pas concerné ; une commune déléguée non plus (sans date, son département seul reste affiché).
`gramps_dater_lieux(ignorer_lieux_evenements_non_dates=true)` laisse ces lieux hors de la proposition
(`lieux_exclus`) ; sinon, dater ces événements avant d'appliquer.

**Invariants** : seules les dates du nom principal et du premier rattachement sont posées (s'ils n'en ont pas),
des noms et rattachements ajoutés en fin de liste, un lieu *Department* créé au besoin ; aucun événement modifié.
Le nom relu par Genealogiste (nom principal, puis premier rattachement : « Commune, Département, Pays ») ne
change pas : arbre, miroir Git et exports GEDCOM identiques, aller-retour Gramps → modèle → Gramps sans diff. Un
nom ou rattachement saisi dans Gramps est conservé tel quel (comme tout ce que le modèle ne représente pas), un
doublon identique n'est jamais ajouté.

**Réseau** : les deux fichiers du COG (`GENEALOGISTE_COG_COMMUNES_URL`, `GENEALOGISTE_COG_MVT_URL`, hôte
`www.insee.fr`) sont lus une fois par proposition, en cache 180 jours, sous la politique réseau et les limites
de débit habituelles ; aucun nom de personne n'est envoyé (fichiers complets, rien de la base ne part). Une
entrée de journal par proposition (source `cog`, opération `chronologie`, codes examinés), positive ou
négative ; COG injoignable : erreur claire, entrée « erreur » au journal, rien n'est préparé ni écrit. Sans
commune identifiée : aucune requête.

**Affichage vérifié** (#277) :

- Gramps Desktop 5.2.4, 6.0.8, 6.1.0-beta2 (vraie bibliothèque, `make test-gramps-desktop`, cas `lieux`) :
  `PlaceDisplay.display_event` rend « Charleville, Ardennes, France » en 1950, « Charleville-Mézières, Ardennes,
  France » en 1980, « Boulogne-Billancourt, Seine, France » en 1950, « Meythet, Annecy, Haute-Savoie, France »
  en 2020 ; noms et rattachements relus par Genealogiste depuis le réexport de Gramps ;
- Gramps Web (`make test-gramps`, chaque image de la matrice) : le profil d'événement
  (`GET /api/events/<handle>?profile=all`) donne `place` = `display_event` au nom d'époque sur toutes les images.
  `place_name`, que l'interface affiche **en priorité** dans les listes (événements, personnes, familles,
  anniversaires) et la fiche de personne, est le nom du lieu à la date de l'événement seulement depuis l'API
  3.26.0 (`get_location_list`) ; avant, c'est le nom principal (`place.get_name()`, API 3.25.1, image épinglée
  26.11.0), et l'interface y montre donc le nom actuel (clé `nom_lieu_date`,
  [version minimale par fonction](#version-minimale-par-fonction)).

**Limites** :

- Événement **sans date** (ou à date textuelle) : Gramps lui donne le plus ancien nom (« avant ») et l'ancien
  département ; règle amont, sans représentation qui l'évite (nom principal sans date : le nom d'époque ne
  s'afficherait jamais). Annoncé par lieu dans la proposition, lieux excluables (ci-dessus).
- COG : depuis 1943 seulement ; avant, et pour les paroisses d'Ancien Régime, le dictionnaire « Des villages de
  Cassini aux communes d'aujourd'hui » (EHESS), non exploité. Un changement de département sans changement de code
  n'est pas un mouvement du COG (Versailles, Paris : Seine-et-Oise et Seine avant 1968 non posés) ; les
  départements renommés (Seine-Inférieure, Basses-Pyrénées, Côtes-du-Nord…) non plus : leur lieu garde son nom.
- Canton et arrondissement : les fichiers du COG utilisés n'en donnent pas l'historique daté ; rien n'est
  ajouté. Un « changement de code (transfert de chef-lieu) » (MOD 50) ne relie pas deux codes comme une même
  commune.
- **Paroisses** : inchangées, attribut d'événement (décision du mainteneur) ; pas de lieu de type Paroisse.
- **Backend fichier** : le modèle n'a pas d'objet lieu (titre, code INSEE, coordonnées) ; l'outil répond
  « Disponible en mode gramps ». Les noms et rattachements datés restent côté Gramps et passent par le Gramps
  XML (export et import sans perte des objets) ; importés dans le modèle, `non_repris` les compte toujours
  (`Place.alt_names[]`, dates des noms et des rattachements).

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
