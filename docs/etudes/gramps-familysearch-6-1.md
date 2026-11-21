# Étude #281 : s'aligner sur l'intégration FamilySearch de Gramps 6.1

Note de conception, 2026-11-21. **Aucune fonction produit n'est implémentée** : le mainteneur valide avant tout
développement. Aucun appel à l'API FamilySearch, aucune clé, aucun compte ; identifiants fictifs seulement
(`XXXX-XX1`…). Ce qui n'a pas été exécuté est marqué « non éprouvé ».

## Contexte

Gramps 6.1 (bêta) intègre FamilySearch dans son noyau : liaison d'une personne à son profil de l'arbre familial
FamilySearch, comparaison, import en masse. #281 demande que Genealogiste lise et écrive le lien dans **le même
attribut** que Gramps, sans refaire ce que Gramps fait, et que #122 (intégration directe par l'API FamilySearch) soit
mise à jour avec l'option « intégration via Gramps ». La recherche amont publiée dans #281 est reprise et complétée
ici, avec des essais.

## Sources

| Dépôt | Référence | SHA |
|---|---|---|
| gramps-project/gramps | `maintenance/gramps61` (HEAD au 2026-11-21) | `e9c09a44791def6a6b81079dc7f8cbe8c7e69cc0` |
| gramps-project/gramps | tag `v6.1.0-beta2` (banc Desktop) | `2153e4fa4b0e4ddf7542f1c064c7820bc345a482` |
| gramps-project/gramps | `maintenance/gramps60`, `maintenance/gramps52` | `32aa296`, `14c01e5` |
| gramps-project/gramps-web-api | tag `v3.26.0` | `5b3f890703537c828009656e7886a2f1e856c060` |
| DavidMStraub/gramps-gedcom7 (export GEDCOM 7 de Gramps Web) | tag `v0.6.0` | `77d6a4bc4eb594fdf03a714eb16004a2c27a2f0a` |
| FamilySearch/GEDCOM-registries | `main` | `7538dc3f3597be1407ccbd6f15af75fa9292031a` |

Sauf mention, `fichier:ligne` renvoie à `maintenance/gramps61`.

## Faits amont

### L'identifiant de personne : attribut `_FSFTID`

- **Forme** : attribut de personne de type **personnalisé** (chaîne) `_FSFTID`, valeur = l'identifiant seul
  (`XXXX-XXX`), jamais une URL. Écrit par `link_gramps_fs_id` (`gramps/gen/fs/utils/linking.py:35-79` :
  met à jour l'attribut existant, sinon en ajoute un, puis valide la personne ; ligne 64 `attr.set_type("_FSFTID")`) ;
  `link_gramps_fs_id_by_handle` (l. 85-110) valide sur la copie en base. Constante `FS_ATTR_CANON = "_FSFTID"`
  (`gramps/gen/fs/actions.py:40`).
- **Lecture** : `get_fsftid` (`gramps/gen/fs/utils/attributes.py:59-70`) ne reconnaît **que** `_FSFTID`. Les anciens
  noms `_FSTID` et `FamilySearch ID` (`actions.py:41-42`) ne sont lus que par `_get_fs_id` (`actions.py:62-72`) et
  `tags.py:155-178`, et sont **remplacés** par un `_FSFTID` unique quand Gramps réécrit le lien (`_set_fs_id`,
  `actions.py:75-96` ; envoi vers FamilySearch, `sync_directions.py:1120-1140`).
- **Index** : `FS_INDEX_PEOPLE[fsid] = handle`, reconstruit par balayage avec `get_fsftid`
  (`gramps/gui/fs/utils/index.py:34-69`) ; un même identifiant sur deux personnes donne un avertissement
  « FamilySearch duplicate ID » (l. 57-61). La recherche par identifiant passe toujours par l'attribut
  (`_find_person_by_fsid`, `actions.py:265-300`).
- **Même attribut ailleurs** : `_FSFTID` porte l'identifiant du fait FamilySearch sur un `Event`
  (`gramps/gen/fs/fs_import/events.py:112-117`) et l'identifiant de source sur une `Citation`, en `SrcAttribute`
  (`linking.py:58-66`, `fs_import/sources.py:793-805`).
- **Lieux** : pas d'attribut ; deux `Url` de type personnalisé `FamilySearch` (description d'API et page publique,
  `fs_import/places.py:44-62`), indexées par `index.py:71-80`.
- **URL publique** ouverte par Gramps : `https://www.familysearch.org/<langue>/tree/person/details/<ID>`
  (`gramps/gui/fs/actions.py:271`). Le registre GEDCOM (`uri/exid-types/FamilySearch-PersonId.yaml`, modifié le
  2026-09-30, `05519e8a`) donne `https://www.familysearch.org/en/search/tree/results?q.personId=<ID>` et précise
  que ces URL ne sont pas garanties stables.

### `Person.familysearch_sync` (Gramps 6.1 seulement)

Objet secondaire `FamilySearchSync` (`gramps/gen/lib/fs/familysearchsync.py:31-197` : `fsid`, horodatages,
indicateurs de conflit), indice 21 de `Person.serialize` (`person.py:173`), ajouté par la migration de schéma 22
(`gramps/gen/db/upgrade.py:65-100`). C'est un **cache de comparaison**, pas la liaison : aucune recherche ne lit
`familysearch_sync.fsid`. Absent de l'export et de l'import **Gramps XML** et **GEDCOM** (aucune occurrence dans
`gramps/plugins/export/`, `importer/`, `lib/libgrampsxml.py`). Essai : après import XML par la bibliothèque 6.1,
`familysearch_sync.fsid` vaut `None` (ci-dessous).

### Étiquettes `FS_*`

Étiquettes Gramps ordinaires (objets `Tag`) créées au besoin (`gramps/gen/fs/tags.py:53-107`) :

| Étiquette | Qui la pose | Sens |
|---|---|---|
| `FS_Linked` / `FS_NotLinked` | Gramps (`retag_all_link_status`, `tags.py:181-`) | personne liée ou non (exclusives) |
| `FS_Synced` / `FS_OutOfSync` | Gramps (comparaison, `compare/aggregate.py`) | état de la dernière comparaison (exclusives) |
| `FS_Dok`, `FS_Dup` | **l'utilisateur** ; lues par `compare/aggregate.py:223-232` | marques de l'utilisateur (« documenté », « doublon ») prises en compte par la comparaison |

Elles n'existent que si l'utilisateur a lancé les outils FamilySearch de Gramps 6.1.

### GEDCOM

- **Gramps Desktop** : l'export GEDCOM (5.5.1) écrit `1 _FSFTID <ID>` pour l'attribut de personne
  (`gramps/plugins/export/exportgedcom.py:714`, identique en 5.2 et 6.0) ; l'import crée l'attribut personnalisé
  `_FSFTID` (`gramps/plugins/lib/libgedcom.py:307, 334, 1323` → `calc_attr`, l. 1295-1301). Le jeton existe déjà
  dans Gramps 4.2.8, 5.0.0 et 5.1.0 (`libgedcom.py` de ces tags). Gramps ne lit ni n'écrit `EXID` (aucune
  occurrence), et n'a pas d'import GEDCOM 7.
- **GEDCOM 7, forme standard** : `EXID <ID>` + `TYPE https://gedcom.io/exid-type/FamilySearch-PersonId`
  (registre FamilySearch/GEDCOM-registries, `uri/exid-types/FamilySearch-PersonId.yaml`). Aucune extension
  `_FSFTID` n'y est enregistrée.
- **Gramps Web** : import GEDCOM 5.5.1 par la bibliothèque Gramps 6.0 ; export GEDCOM 7 par `gramps-gedcom7` :
  un attribut personnalisé qui n'est ni `EXID:…` ni `REFN:…` y devient `FACT` + `TYPE <nom>`
  (`gramps_gedcom7/export/util.py:323-350`) ; à l'import (bibliothèque, pas de route d'import `ged7` dans
  Gramps Web), un `EXID` devient un attribut `EXID:<TYPE>` (`gramps_gedcom7/util.py:505-540`), pas `_FSFTID`.

### Gramps Web 6.0 et addon de synchronisation

- **Gramps Web** : toutes les images 3.x embarquent Gramps 6.0 (`gramps[all]>=6.0.4,<6.1.0`,
  `gramps-web-api` `pyproject.toml:18`). `_FSFTID` y est un attribut personnalisé comme un autre, `FS_*` des étiquettes
  comme les autres ; aucune occurrence de `FSFTID` dans gramps-web-api 3.26.0 ni dans l'interface 26.11.3 (seul un
  lien de recherche de documents FamilySearch par nom, `GrampsjsFormExternalSearch.js:44-50`).
  `familysearch_sync` ne peut pas y exister.
- **Addon Gramps Web Sync** (étude de #271, `addons-source` `GrampsWebSync` 1.5.8/1.5.9) : synchronise par export
  Gramps XML puis transactions. `_FSFTID` et les `FS_*` passent comme tout attribut ou étiquette. Objet modifié des
  deux côtés : deux valeurs différentes de `_FSFTID` sont **gardées côte à côte** (`attrbase.py:129-147`), les
  étiquettes sont unies (une `FS_Synced` retirée revient, `FS_Synced` et `FS_OutOfSync` peuvent coexister).
  `familysearch_sync` ne passe pas par le XML ; ce qu'il advient d'une transaction JSON 6.1 portant ce champ envoyée
  à un serveur 6.0 est **non éprouvé**.

### Stabilité du nom (Gramps 6.1 en bêta)

Historique de `gramps/gen/fs` sur `maintenance/gramps61` (API GitHub, 9 commits du 2026-04-17 `4972a2eb`
« Implement FamilySearch-Gramps Integration » au 2026-07-30 `15153d76` « Persist FamilySearch ID links independent of
editor ») : `FS_ATTR_CANON = "_FSFTID"` et `get_fsftid` sont identiques depuis le premier commit ; seule la liste des
alias a été resserrée (`tags.py` du premier commit acceptait aussi `FSFTID`, `FSID`, `FS_FTID`, `_FS_FTID`). Le nom
`_FSFTID` est par ailleurs le jeton GEDCOM de Gramps depuis 4.2 au moins. Risque de changement : faible.

## Essais (2026-11-21)

### Plugin, hors ligne (révision `78fd096` + branche d'étude)

Script `essai_fsftid.py` (scratchpad, non versionné) : GEDCOM fictifs 5.5.1 (`1 _FSFTID XXXX-XX1` sur une personne
décédée, `XXXX-XX2` sur une personne née en 1990) et 7 (`EXID XXXX-XX3` avec le `TYPE` FamilySearch, `REFN XXXX-XX4`
`TYPE FamilySearch`).

| Chemin | Résultat |
|---|---|
| `read_gedcom` (backend fichier) | les trois formes vont dans `Person.extra` (nœud non interprété) |
| `write_gedcom` 7 et 5.5.1 | réécrites telles quelles (aller-retour sans perte en mode fichier) ; `_FSFTID` non déclaré dans `SCHMA` |
| `privacy.publication` (export public) | `XXXX-XX2` (personne présumée vivante) retiré avec tout `extra` ; `XXXX-XX1`, `EXID`, `REFN` d'un défunt conservés |
| `tree_to_gramps`, `to_gramps_xml` | **perdu** : aucun attribut, aucune trace (`extra` n'est pas porté vers Gramps) |
| Gramps → modèle (`gramps_to_tree`) d'une personne portant l'attribut `_FSFTID` | absent du modèle et donc du miroir Git et des exports GEDCOM |
| Réécriture par-dessus l'état lu après modification du nom de cette personne | attribut `_FSFTID` **conservé** côté Gramps |

Conséquences : en mode fichier, l'identifiant d'un GEDCOM importé survit sans être compris ; **la bascule vers
Gramps Web et l'import d'un GEDCOM en mode gramps le perdent** ; un lien posé dans Gramps survit aux écritures
de Genealogiste mais n'est ni lu, ni exporté, ni montré.

### Gramps Web jetable (images `26.11.0` / API 3.25.1 et `26.11.3` / API 3.26.0)

Script `live281.py`, projet Compose `genealogiste-etude-266`, port 5066, `down -v` : résultats identiques sur les
deux images.

- `POST /api/importers/ged/file` d'un GEDCOM 5.5.1 `1 _FSFTID XXXX-XX1` → attribut de personne `_FSFTID` =
  `XXXX-XX1`.
- Exports : `ged` → `1 _FSFTID XXXX-XX1` ; `gramps` → `<attribute type="_FSFTID" value="XXXX-XX1"/>` ; `ged7` →
  `1 FACT XXXX-XX1` / `2 TYPE _FSFTID` (pas d'`EXID`).
- Routes d'import : `csv ged gw gramps grdb def vcf jsonl` (pas de `ged7`).

### Bibliothèque Gramps Desktop 6.1.0-beta2 (banc, sans interface)

Sonde `sonde61.py` (`import_as_dict` puis `get_fsftid`) : Gramps XML avec `_FSFTID` → `get_fsftid` = `XXXX-XX1` ;
attributs `FamilySearch ID` et `_FSTID` → `get_fsftid` vide (attributs conservés) ; GEDCOM 5.5.1 `_FSFTID` → lu ;
GEDCOM `EXID` avec `TYPE` FamilySearch → **ignoré** (aucun attribut créé) ; `familysearch_sync.fsid` = `None`.

## Où le plugin en est aujourd'hui

- Aucun champ d'identifiant FamilySearch dans le modèle (`models.Person`) ; `liens_recherche` ne produit aucun lien
  FamilySearch (`sources/liens.py:21-75`) ; `familysearch_exporter` est désactivé (`sources/familysearch.py` :
  `getmyancestors` imposait des dépendances vulnérables, consigne « ne pas fournir d'identifiants FamilySearch au
  plugin »).
- Étiquettes : seules `Genealogiste:auto`, `Sosa:auto` et « Preuve : … » sont gérées (`etiquettes.geree`) ; les
  `FS_*` seraient lues comme des étiquettes de l'utilisateur (modèle, `_ETIQUETTE` GEDCOM, exports).

## Conception proposée

### 1. Un champ du modèle, les formes de Gramps

`Person.familysearch_id: str` (vide par défaut), une seule valeur. Correspondances :

| Support | Lecture (toutes reconnues) | Écriture d'une valeur nouvelle ou modifiée |
|---|---|---|
| Gramps (API, XML, futur backend Desktop) | attribut `_FSFTID` ; alias `_FSTID`, `FamilySearch ID`, `EXID:https://gedcom.io/exid-type/FamilySearch-PersonId` (import `gramps-gedcom7`) | attribut `_FSFTID` (type personnalisé, valeur = ID), comme `link_gramps_fs_id` |
| GEDCOM 5.5.1 | `_FSFTID` ; `EXID` + `TYPE` FamilySearch | `1 _FSFTID <ID>` (forme lue par Gramps) |
| GEDCOM 7 | `EXID` + `TYPE https://gedcom.io/exid-type/FamilySearch-PersonId` ; `_FSFTID` ; `FACT <ID>` + `TYPE _FSFTID` (export `ged7` de Gramps Web) | `EXID` + `TYPE` standard |

Règle du projet (dates, types, marqueurs) : **une forme lue est réécrite à l'identique tant que la valeur ne change
pas** ; aucune migration silencieuse. Un alias n'est remplacé par `_FSFTID` que si l'utilisateur modifie le lien
(diff explicite). Deux formes **différentes** sur une même personne (cas de la synchronisation Sync) : lues toutes
deux, signalées par `arbre_coherence` (`familysearch_id_multiple`), jamais tranchées. `_FSFTID` des événements et
`SrcAttribute` des citations : non modélisés, conservés côté Gramps (comme aujourd'hui).

Aller-retour sans perte à vérifier par les tests : GEDCOM 7 → modèle → GEDCOM 7 ; GEDCOM 5.5.1 → modèle →
GEDCOM 5.5.1 ; Gramps → modèle → Gramps (attribut et position inchangés) ; bascule et import GEDCOM en mode gramps
(l'identifiant arrive en `_FSFTID`).

### 2. Poser ou retirer le lien : opération d'`arbre_proposer`

`lier_familysearch {personne, identifiant}` et `delier_familysearch {personne}` (ou un champ de
`modifier_personne`, à trancher). Validation : majuscules, forme `XXXX-XXX` (une URL `…/tree/person/details/<ID>`
réduite à l'identifiant, comme le champ « FamilySearch ID or URL » de Gramps, `gui/fs/actions.py:819-820`) ; refus si
l'identifiant est déjà sur une autre personne (Gramps l'avertit comme doublon). Diff : une ligne
`@@ FamilySearch I12 : XXXX-XXX @@`. Accord, journal, annulation comme toute proposition. Pas de citation exigée
(`EXIGER_SOURCE`) : le lien n'est pas un fait ; il ne change aucun statut de preuve (un profil de l'arbre familial
FamilySearch est une source **dérivée**, #122 §5).

### 3. Ce que le plugin ne fait pas (laissé à Gramps 6.1)

Connexion, comparaison, import en masse, envoi vers FamilySearch, statut de synchronisation : Gramps 6.1 Desktop,
avec le compte de l'utilisateur. Le plugin ne lit ni n'écrit `familysearch_sync` ; dans le futur backend Desktop
(#270), il le conserve tel quel (la bibliothèque le relit et le réécrit avec la personne), jamais par le XML.

### 4. Étiquettes `FS_*`

Proposition : `FS_Linked`, `FS_NotLinked`, `FS_Synced`, `FS_OutOfSync` deviennent des **étiquettes gérées par
Gramps** : hors de `tags` du modèle (comme `Genealogiste:auto`), conservées côté Gramps, ni posées ni retirées par une
opération (refus explicite), absentes des exports GEDCOM et publics. `FS_Dok` et `FS_Dup`, posées par l'utilisateur,
restent des étiquettes ordinaires. À trancher (question 2).

### 5. Lien public et garde des vivants

- `arbre_fiche` (et `liens_recherche` s'il reçoit une personne) donne l'URL
  `https://www.familysearch.org/tree/person/details/<ID>` : construite localement, ouverte par l'utilisateur, **aucun
  appel** du plugin.
- **Vivants** : pour une personne présumée vivante ou privée, l'identifiant n'apparaît dans aucune sortie destinée à
  l'extérieur : pas de lien, retrait par `privacy.publication` (déjà le cas pour `extra` ; à garder pour le nouveau
  champ, test dédié), pas d'envoi à un outil réseau. Lecture locale (fiche, diff) inchangée.
- Exports publics : identifiant d'un défunt publié (donnée publique de l'arbre familial FamilySearch) ; à confirmer
  (question 4).

## Recommandation

1. Adopter l'attribut **`_FSFTID`** (valeur = identifiant seul) comme forme Gramps du lien, et `EXID` + `TYPE`
   standard en GEDCOM 7, `_FSFTID` en GEDCOM 5.5.1, avec lecture de tous les alias relevés.
2. Corriger d'abord la **perte** actuelle (bascule et import GEDCOM en mode gramps), qui est un défaut indépendant du
   reste : c'est le premier lot.
3. Ne rien dupliquer de Gramps : pas de client FamilySearch dans le plugin tant que #122 n'a pas levé ses blocages ;
   le plugin s'appuie sur les liens posés dans Gramps.
4. Mettre #122 en attente au profit de l'option « via Gramps » (commentaire publié dans #122).

## Risques

- Gramps 6.1 en bêta : nom stable depuis le premier commit et jeton GEDCOM ancien (risque faible) ; `familysearch_sync`
  et la forme des `FS_*` peuvent encore bouger (sans effet si le plugin ne les écrit pas).
- Gramps Web ne peut pas porter l'intégration avant que gramps-web-api accepte Gramps 6.1 ; le lien ne circule entre
  Desktop et Web que par l'attribut (base partagée, Sync, import XML).
- Doubles valeurs après une synchronisation Sync des deux côtés : signalées, jamais tranchées.
- Le banc Desktop 6.1 importe `gramps.gen.fs` sans interface (essai ci-dessus) ; une évolution de la bêta qui
  ajouterait une dépendance à l'import casserait le test (à surveiller par la matrice).

## Questions ouvertes pour le mainteneur

1. Opérations dédiées (`lier_familysearch` / `delier_familysearch`) ou champ de `modifier_personne` ?
2. `FS_Linked`… gérées par Gramps hors du modèle (proposé), ou laissées comme étiquettes ordinaires ?
3. GEDCOM 7 : `EXID` standard seul (proposé), ou `EXID` **et** `_FSFTID` pour les outils qui ne lisent que
   l'extension (Gramps n'importe pas le GEDCOM 7) ?
4. Identifiant d'un défunt dans les exports publics : publié (proposé) ou retiré par défaut ?
5. Lien public : forme `tree/person/details/<ID>` (celle de Gramps) ou celle du registre GEDCOM (`q.personId=`) ?

## Découpage proposé en issues (non créées)

| Titre | Périmètre | Critères d'acceptation |
|---|---|---|
| `fix(gramps): ne plus perdre l'identifiant FamilySearch à la bascule et à l'import` | champ `Person.familysearch_id`, lecture/écriture des formes du tableau §1, bascule, import, miroir | aller-retours GEDCOM 5.5.1/7 et Gramps sans perte ; forme lue réécrite à l'identique ; banc Desktop 6.1 : `get_fsftid` lit ce que le plugin écrit en Gramps XML et en GEDCOM 5.5.1 ; `make test-gramps-matrice` : attribut relu sur les trois images |
| `feat(operations): poser et retirer le lien FamilySearch d'une personne` | opérations §2, diff, journal, annulation, doublon d'identifiant | refus de forme invalide et de doublon ; annulation exacte ; aucun accès réseau |
| `feat(gramps): étiquettes FS_* gérées par Gramps` (si question 2 tranchée ainsi) | `etiquettes.geree`, exports | relecture et réécriture identiques ; absentes des exports ; opération refusée |
| `feat(liens): lien public FamilySearch depuis l'identifiant` | `arbre_fiche`, `liens_recherche(personne=…)` | aucun lien pour un vivant ou un privé (test) ; aucune requête réseau |

Version minimale : aucune (attribut personnalisé et `POST /api/transactions/`, déjà requis).

## Impact sur #122

Paragraphe publié en commentaire de #122 : l'intégration par l'API FamilySearch reste bloquée par l'accès production
(§4.2), la clause IA (§4.3) et la certification d'écriture (§4.6) ; Gramps 6.1 offre une voie sans clé ni compte côté
plugin. #122 passe en attente ; sa phase 0 (réponse écrite du support FamilySearch) ne se justifie que pour un besoin que
Gramps ne couvre pas (recherche de documents, sources rattachées).
