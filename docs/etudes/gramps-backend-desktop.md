# Étude : backend Gramps Desktop sur la base locale (#270)

Statut : **étude**, rien n'est implémenté. Le mainteneur choisit la piste avant toute issue d'implémentation.
Date des essais : 2026-11-21. Données : uniquement l'arbre fictif du dépôt (`mcp/tests/fixtures/famille.ged`,
8 personnes, 74 objets Gramps) et des objets fictifs ajoutés pour l'essai. Ce qui n'a pas été exécuté est marqué
**non éprouvé**.

## Résumé

- **Le contrat tient.** Le `GrampsBackend` actuel, sans modification, a été branché sur un « client » qui pilote la
  bibliothèque Gramps dans un sous-processus. Sur une base SQLite Gramps 6.0 puis 6.1, il a enchaîné proposition,
  application, annulation et refus d'une proposition rendue caduque par une édition concurrente. Le journal
  `gramps-transactions.jsonl` est le même.
- **`mapping.py` est réutilisable tel quel en 6.0.** Les 74 objets écrits par `DbTxn`, puis relus par la
  bibliothèque, sont identiques champ à champ, à `change` près, et le GEDCOM relu est identique. En **6.1**, la lecture
  est identique aussi, mais une personne écrite sans `familysearch_sync` devient un objet Gramps invalide
  (`AttributeError` sur `serialize()`). Il faut compléter les objets avant de les écrire. En **5.2**, les objets du
  mapping sont acceptés **sans erreur mais corrompus** : 57 objets sur 74 perdent leurs types.
- **Le verrou de Gramps n'est qu'un fichier, et la bibliothèque ne le respecte pas.** `load()` en écriture ne le
  vérifie pas et l'écrase. `close()` l'efface, même après une ouverture en lecture seule : une simple lecture par la
  bibliothèque **retire le verrou d'un Gramps Desktop ouvert**. Le contrôle doit donc être fait par le plugin, avant
  toute ouverture.
- **Danger découvert.** Si la bibliothèque 6.0 ouvre en écriture une base 6.1 (schéma 22), elle refuse bien
  (`DbVersionError`), mais elle a déjà réécrit les métadonnées en fermant la base : **la base 6.1 est marquée
  schéma 21** et deux listes de types personnalisés sont vidées. Il faut lire la version du schéma directement dans
  SQLite et n'ouvrir la base qu'avec la bibliothèque de **la même** version.
- **L'annulation native de Gramps ne survit pas à la fermeture** : l'historique est en mémoire et aucun fichier
  `undo.db` n'est écrit. L'annulation doit rester celle du plugin : une transaction inverse calculée à partir de
  `old`/`new` journalisés, comme pour Gramps Web. C'est ce que fait le prototype.
- **La lecture est possible sans la bibliothèque** en 6.x : les colonnes `json_data` lues directement dans SQLite
  donnent les mêmes objets que la bibliothèque. Une lecture longue bloque toutefois les écritures de Desktop
  (`database is locked` après 5 s). L'écriture sans la bibliothèque est déconseillée : index secondaires, table
  `reference` et métadonnées sont à maintenir.
- **Recommandation** : piste 1, découpée ainsi. Lecture directe dans SQLite, en lecture seule et brève. Écriture par
  un sous-processus qui exécute la bibliothèque `gramps` **de la version du schéma de la base**, seulement si
  aucun verrou n'est posé, avec un verrou exclusif pendant l'opération, une sauvegarde avant la première
  écriture et un refus de tout schéma inconnu. Gramps 5.2 n'est pas pris en charge en direct : la voie XML existe
  déjà (#268/#269). L'addon de synchronisation (piste 3) n'est pas une alternative sûre (voir
  [l'étude #271](gramps-synchro-desktop-web.md)).

## Contexte

Genealogiste a deux backends : `fichier` (GEDCOM 7 dans un dépôt Git) et `gramps` (Gramps Web par son API,
[docs/gramps-web.md](../gramps-web.md)). Un utilisateur de Gramps Desktop seul passe aujourd'hui par
l'export et l'import de Gramps XML ([docs/gramps.md](../gramps.md)). L'issue #270 envisage trois pistes :

1. la bibliothèque `gramps` (`DbTxn`) sur la base locale ;
2. l'échange de fichiers Gramps XML seul, déjà livré par #268 et #269 ;
3. Gramps Web avec l'addon de synchronisation.

Le contrat à tenir est le même que pour Gramps Web : `arbre_proposer`, diff, accord, `arbre_appliquer`, journal
d'intention, annulation (voir [Journal d'intention et reprise](../gramps-web.md#journal-dintention-et-reprise)).

## Faits amont

Sauf mention contraire, les citations renvoient aux bibliothèques exactes du banc
(`make test-gramps-desktop`, environnements de `~/.cache/genealogiste/gramps-desktop/`) :
`gramps==5.2.4` et `gramps==6.0.8` (PyPI), et `v6.1.0-beta2` (commit `2153e4fa4b0e4ddf7542f1c064c7820bc345a482`,
sources). Les branches de maintenance consultées sont `maintenance/gramps52` `14c01e5`, `maintenance/gramps60`
`32aa296` et `maintenance/gramps61` `e9c09a4`. Pour gramps-web-api : `master` `9cbf933`.

### Stockage et schéma

| Version | Schéma (`DbGeneric.VERSION`) | Stockage des objets | Référence |
|---|---|---|---|
| 5.2.4 | 20 | `blob_data` (pickle de tuples) | `gen/db/generic.py:373`, `plugins/db/dbapi/dbapi.py:108-129` |
| 6.0.8 | 21 | `json_data` (JSON de Gramps 6), conversion depuis 20 par `gramps_upgrade_21` | `gen/db/generic.py:423`, `plugins/db/dbapi/dbapi.py:109-252` |
| 6.1.0-beta2 | 22 | `json_data`, plus `familysearch_sync` dans chaque personne (`gramps_upgrade_22`) | `gen/db/generic.py:422`, `gen/db/upgrade.py:84-108`, `gen/lib/person.py:173,314,330` |

Contrôle de version dans `load()` (6.0.8, `gen/db/generic.py:822-836`, même code en 5.2 l. 716-730 et en 6.1
l. 821-835) :

- si la base est **plus récente** que la bibliothèque, `self.close()` est appelé, puis `DbVersionError` est levée ;
- si elle est **plus ancienne** et ouverte en écriture, la bibliothèque appelle `self.close(update=False)` puis
  lève `DbUpgradeRequiredError`, sauf si `force_schema_upgrade` est passé.

En 6.x, `close()` sans `update=False` réécrit toutes les métadonnées, y compris `version` (`_set_all_metadata`,
`gen/db/generic.py:876-930`, `version` l. 881). C'est l'origine de la corruption constatée à l'essai E2.

Autres données que la bibliothèque maintient à côté des objets (6.0.8) :

- colonnes secondaires, mises à jour à chaque `commit_*` (`_update_secondary_values`, `dbapi.py:1171-1200`) ;
- table `reference` (`dbapi.py:740-790`) ;
- `name_group` (`dbapi.py:650-671`) ;
- `gender_stats` ;
- métadonnées : types personnalisés, prochains identifiants, liste des patronymes. Elles sont gardées **en mémoire**
  par la base ouverte et réécrites à la fermeture (`close()`, `generic.py:850-871`).

### Verrou

- Le verrou est un **fichier `lock`** dans le dossier de l'arbre, qui contient `utilisateur@hôte`. Il est écrit en
  mode `"w"`, sans création exclusive, ce qui n'empêche pas deux écrivains de le poser en même temps
  (`write_lock_file`, `gen/db/utils.py:219-240`, `open(…, "w")` l. 225) ; il est effacé par `clear_lock_file`
  (l. 209-216).
- `DbGeneric.load()` **pose le verrou dès qu'il ouvre en écriture, sans regarder s'il en existe déjà un**
  (`generic.py:728-729`). `close()` l'**efface toujours**, y compris pour une base ouverte en lecture seule
  (`generic.py:864-867`).
- Seuls les appelants contrôlent le verrou :
  - `lookup_family_tree` renvoie `locked` (`utils.py:105-130`) et `open_database` refuse sauf `force_unlock`
    (l. 91-102) ;
  - la ligne de commande refuse (`cli/arghandler.py:566-576` `check_db`, `cli/grampscli.py:264-272`) ;
  - l'interface propose de « casser » le verrou (`gui/dbman.py:530-559`) ;
  - `CLIDbManager.break_lock` le supprime (`cli/clidbman.py:495`).

  Genealogiste ne doit **jamais** appeler `break_lock`, `force_unlock` ni `force_schema_upgrade`.
- La connexion SQLite est ouverte avec les réglages par défaut de Python : mode de journal `delete` (constaté) et
  délai d'attente de 5 s (`plugins/db/dbapi/sqlite.py:105`, `sqlite3.connect(*args)` sans `timeout`).

### Annulation

L'annulation native repose sur `DbGenericUndo` (`generic.py:146-192`), une liste Python en mémoire
(`self.undodb = []`, l. 153). `load()` calcule bien un chemin `undo.db` (`DBUNDOFN`, l. 786-791), mais cette classe ne
l'utilise pas : l'historique d'annulation disparaît à la fermeture (vérifié à l'essai E4).

### Données dont le Web ne permet pas l'écriture

- **Personne de référence** : `set_default_person_handle` écrit la métadonnée `default-person-handle`
  (`generic.py:2574-2576`).
- **Groupes de noms** : `set_name_group_mapping(nom, None)` **supprime** la clé (`dbapi.py:650-671`). L'état
  « aucun regroupement », impossible à rétablir par l'API web
  ([docs/gramps-web.md](../gramps-web.md#pourquoi-genealogiste-nécrit-pas-les-groupes-de-noms)), redevient
  donc atteignable.
- Ces deux écritures passent par `_set_metadata` ou `_txn_begin`, qui ne font rien quand une transaction `DbTxn`
  est en cours (`dbapi.py:265-272`, `403-425`) : elles peuvent être **atomiques** avec les objets. Elles
  n'entrent pas pour autant dans l'historique d'annulation de Gramps, donc le plugin doit journaliser leurs états
  avant et après lui-même.

### Chemins et effets de bord de la bibliothèque

- Sous Linux, la base est par défaut dans `$XDG_DATA_HOME/gramps/grampsdb/<id>/` (`gen/const.py:116-119`,
  `gen/config.py:201`). `GRAMPSHOME` remplace ce chemin par `$GRAMPSHOME/gramps` (`const.py:99-101`).
- **Effet de bord à l'import** : si `~/.gramps` existe et que les dossiers XDG n'existent pas, l'import de
  `gramps.gen.const` copie `~/.gramps/grampsdb` vers XDG (`const.py:121-129`).
- La bibliothèque lit aussi les greffons de l'utilisateur au chargement du registre (`make_database`).
- Le plugin doit donc exécuter la bibliothèque avec un `GRAMPSHOME` **à lui**, vide, et ouvrir la base par son
  chemin (`make_database("sqlite").load(chemin)`), jamais par `lookup_family_tree` dans les dossiers de
  l'utilisateur.

### Distribution de la bibliothèque

| Source | Ce qu'on trouve | Statut |
|---|---|---|
| PyPI `gramps==5.2.4` / `6.0.8` | Bibliothèque seule. PyGObject n'est qu'un extra `gui`, mais `gramps.gen.const` importe `GLib` (le banc fournit un module factice). En 6.0, `orjson` est requis (`METADATA` des paquets). | éprouvé (banc) |
| Sources 6.1 (`v6.1.0-beta2`, absente de PyPI) | Dépendances `orjson`, `requests`, `certifi` (`pyproject.toml:42-46`). Plus d'import de `gi` dans la bibliothèque. | éprouvé (banc) |
| Debian / Ubuntu | Paquet `gramps` qui dépend de `python3-gi` (`debian/control` des sources 6.1). Bibliothèque dans le Python système. | lu, non éprouvé |
| Windows AIO | Application figée par cx_Freeze (bibliothèque dans `lib/library.zip`) qui refuse une seconde instance (mutex `org.gramps-project.gramps`, `aio/grampsaioc.py`). Aucun interpréteur réutilisable. | lu, non éprouvé |
| macOS | Paquet d'application avec Python 3.14 embarqué (`mac/gramps.bundle:45`). | lu, non éprouvé |
| Flatpak, AppImage | Bibliothèque dans le bac à sable de l'application. | non éprouvé |

Licence : `gramps` est sous GPL-2.0-or-later, Genealogiste sous GPL-3.0-or-later (`plugin.json`). Les deux sont
compatibles, l'ensemble relevant de la GPL 3.

## Essais réels

### Protocole

- Environnements du banc (Python 3.12, `uv`), module `GLib` factice pour 5.2 et 6.0, comme
  `scripts/sonde_gramps_desktop.py`.
- `HOME`, `GRAMPSHOME` et `XDG_*` redirigés vers le dossier de travail de l'essai (un contrôle dans le script
  refuse tout autre chemin). Aucune base de l'utilisateur n'est lue.
- Arbre fictif : `famille.ged` lu par Genealogiste, puis `tree_to_gramps_stats` (les objets JSON que le mode
  Gramps Web enverrait). On en tire soit un fichier Gramps XML 1.7.1 à importer, soit les objets eux-mêmes, écrits
  par `DbTxn` (`commit_<classe>`) dans une base vide créée par `CLIDbManager.create_new_db_cli`.
- Gramps Desktop « ouvert » est simulé par un second processus qui ouvre la base en écriture (`load()`, verrou
  posé), la garde ouverte, y écrit éventuellement par `DbTxn`, puis la ferme. Le comportement de l'interface
  graphique elle-même n'est **pas** éprouvé.
- Les scripts d'essai sont des prototypes jetables, non versionnés (voir les questions ouvertes) :
  - `biblio.py` : pilote de la bibliothèque ;
  - `prototype_contrat.py` : `GrampsBackend` et client par sous-processus ;
  - `verrou.sh`, `sqlite_direct.py`, `lecture_longue.py`.

### E1. Format des objets : `mapping.py` et la bibliothèque

| Version | Import XML puis lecture | Objets du mapping écrits par `DbTxn` puis relus | `to_raw` | GEDCOM relu par `gramps_to_tree` |
|---|---|---|---|---|
| 6.0.8 | 16 écarts, tous sur `gramps_id` (renumérotation à l'import, `I1` → `I0001`) | **0 écart** (hors `change`) | idempotent sur les 74 objets | identique |
| 6.1.0-beta2 | idem, et `familysearch_sync` en plus (champ que le banc ignore déjà) | **0 écart** | idempotent | identique |
| 5.2.4 | format de `serialize.to_json` différent : types sans `value` (`{"_class": "EventType", "string": "Death"}`), dates vides à `null` | **accepté sans erreur, mais 57 objets sur 74 faux** : types ramenés à la valeur 0 (par exemple type de nom `Birth Name` → 0), d'après `serialize()` comparé à l'import XML | — | différent (92 lignes) |

Conclusion : en 6.0, le JSON de la bibliothèque (`object_to_dict`, `data_to_object`) **est** le format du mapping.
Le client par bibliothèque se branche sans couche de conversion, avec la même normalisation que celle déjà admise
par le banc pour `thumb`, `complete`, `familysearch_sync` et `Date.format/text`.

Cas 6.1 :

- un `Person` créé par `data_to_object` à partir d'un objet sans `familysearch_sync` n'a pas l'attribut ;
- `get_familysearch_sync()` et `serialize()` lèvent alors `AttributeError`, tandis que
  `get_referenced_handles_recursively()` passe ;
- une personne ajoutée par le prototype est relue sans ce champ.

Le backend Desktop 6.1 devra compléter les objets avec les valeurs par défaut de la bibliothèque, comme le fait
gramps-web-api (`complete_gramps_object_dict`, `gramps_webapi/api/util.py:849-858`). Une mise à jour d'objet lu
devrait conserver le champ, puisque le mapping écrit par-dessus l'objet lu (attendu, non éprouvé).

Cas 5.2 : écrire avec le mapping actuel est **exclu**. Il faudrait un convertisseur JSON 6 → tuples 5.2 (l'inverse
de `gen/db/conversion_tools/conversion_21.py` de 6.0), à maintenir et à tester pour chaque classe.

### E2. Versions de schéma croisées (copies de bases fictives)

| Bibliothèque | Base | Lecture seule | Écriture | Base modifiée ? |
|---|---|---|---|---|
| 6.0 | 5.2 (schéma 20) | **ouverte** : les objets sont lus au format JSON 6 par le sérialiseur `blob` | refus `DbUpgradeRequiredError` | non (empreinte identique) |
| 6.1 | 5.2 (20) | ouverte, mais la lecture échoue : `ValueError: not enough values to unpack (expected 22, got 21)` | refus `DbUpgradeRequiredError` | non |
| 6.1 | 6.0 (21) | ouverte, lecture correcte | refus `DbUpgradeRequiredError` | non |
| 6.0 | 6.1 (22) | refus `DbVersionError` | refus `DbVersionError` | lecture seule : non. **Écriture : OUI.** Les métadonnées sont réécrites à la fermeture, `version` passe de 22 à 21, `pattr_names` et `sattr_names` sont vidés. Ensuite, 6.0 ouvre la base comme une base 21 et 6.1 exige une « mise à niveau ». |
| 5.2 | 6.0 (21) | refus `DbVersionError` | refus `DbVersionError` | non (`close()` de 5.2 n'écrit pas `version`) |

Règles qui en découlent :

1. Lire `metadata.version` directement dans SQLite (`file:…?mode=ro`) **avant** tout `load()`.
2. N'ouvrir en écriture qu'avec la bibliothèque dont `VERSION[0]` est **égal** au schéma de la base.
3. Refuser un schéma inconnu ou plus récent, sans rien ouvrir.
4. Ne jamais mettre le schéma à niveau.

Le défaut amont (`close()` qui réécrit les métadonnées avant `DbVersionError`) touche aussi Gramps Desktop
lui-même. Le signaler en amont est une question ouverte.

### E3. Verrou : Gramps Desktop simulé ouvert pendant 10 s

Mêmes résultats pour 5.2.4, 6.0.8 et 6.1.0-beta2, sauf B1 en 5.2 : l'écriture y est refusée par le contrôle `old`,
les objets 5.2 n'ayant pas le format du mapping.

| Cas | Constat |
|---|---|
| A1. Le plugin vérifie le verrou (fichier `lock` présent), puis veut écrire | refus propre, rien n'est ouvert |
| A2. Lecture par la bibliothèque en lecture seule pendant que Desktop est ouvert | lecture correcte (0,03 s), mais **le verrou de Desktop a disparu** après `close()` (A3) |
| B1. Écriture naïve par `load()` en écriture sans contrôle, Desktop ouvert | l'écriture **réussit** au niveau SQLite, le verrou de Desktop est écrasé puis effacé |
| B3/B4. Desktop écrit ensuite, puis se ferme | son écriture réussit, mais à la fermeture il réécrit les métadonnées de sa mémoire : le type d'attribut créé par le plugin (`Genealogiste-Essai-verrou`) **disparaît de `pattr_names`** alors que l'attribut reste dans l'objet. Les objets des deux écrivains sont présents parce qu'ils portaient sur des personnes différentes. Sur une même personne, l'éditeur de Desktop réécrirait son état en mémoire (non éprouvé, mais c'est le fonctionnement de `commit_person`). |
| C. Lecture SQLite directe qui garde une transaction de lecture 8 s pendant une écriture de Desktop | **l'écriture de Desktop échoue** après 5,01 s : `OperationalError: database is locked` |

Conséquences pour la conception :

- **Écriture** : le plugin ne compte jamais sur la bibliothèque pour le verrou. Il vérifie le fichier `lock` et
  refuse s'il existe. Sinon, il crée son propre verrou de façon exclusive (`O_CREAT | O_EXCL`, contenu
  `genealogiste@hôte pid`), ouvre, écrit, puis ferme (ce qui efface son verrou).
- **Durée du verrou** : il est tenu **le temps de l'opération** (`arbre_appliquer`, quelques centaines de
  millisecondes pour l'arbre d'essai), **jamais pour une session MCP**. Sinon Desktop ne pourrait plus ouvrir
  l'arbre de toute la session.
- **Course résiduelle** : Desktop qui ouvre l'arbre pendant l'écriture du plugin voit le verrou et propose de le
  « casser ». La documentation doit dire de ne pas le faire. Un Desktop ouvert dont le verrou a disparu n'est pas
  détectable par le fichier. La détection d'un processus Gramps en cours est non éprouvée et dépend du système.
- **Lecture** : directe dans SQLite, **jamais** par `load()` (sinon le verrou de Desktop est effacé). Une seule
  transaction courte, sans rien tenir entre deux appels. Elle reste permise quand Desktop est ouvert (lecture de
  l'état validé). La lecture complète de l'arbre d'essai a pris 4 à 10 ms. Pour une grande base, mesurer et lire
  par tranches si nécessaire (non éprouvé au-delà de l'arbre d'essai).

### E4. Annulation

Pour les trois versions : une écriture par `DbTxn` donne `len(undodb) == 1` en session et `db.undo()` fonctionne
avant la fermeture. Aucun fichier `undo.db` n'est créé dans le dossier de l'arbre. Après réouverture,
`len(undodb) == 0`, `db.undo()` renvoie `False` et la modification est toujours là.

L'annulation « possible » ne peut donc venir que du journal du plugin. C'est ce que fait déjà le backend Web :
`gramps-transactions.jsonl` (`old`/`new`), puis `propose_undo` qui applique la transaction inverse **après**
vérification que l'état courant est bien le `new` journalisé (sinon conflit). Le prototype E5 le vérifie sur une
base Desktop.

### E5. Prototype : le contrat complet sur une base Desktop

`GrampsBackend` est **inchangé**. On lui fournit un `ClientDesktopEssai` qui offre `load_all`, `refresh`, `get` et
`transaction(items, message, undo)`. Chaque appel lance un sous-processus de la bibliothèque, qui :

- pour lire, ouvre la base en lecture seule (sans Desktop ouvert pendant l'essai) ;
- pour écrire, refuse si le fichier `lock` existe, sinon pose le verrou exclusif, compare `old` à l'état courant
  (hors `change`, comme `old_unchanged` de gramps-web-api) et écrit en une `DbTxn` avec `commit_<classe>` et
  `remove_<classe>`, comme `apply_transactions` (`gramps_webapi/api/tasks.py:980-1066`).

Résultats sur 6.0.8 et 6.1.0-beta2 :

| Étape | Résultat |
|---|---|
| `propose` : `ajouter_personne`, `etiqueter`, `ajouter_evenement` (`non_source`) | jeton. Transaction de 8 objets : Tag +1, Note +2/~1, Event +1, Person +1/~2 (notes de preuve comprises) |
| `apply` | appliquée, journal `intention` → `envoyee` → `terminee`, personne relue dans la base |
| `propose_undo` puis `apply` | transaction inverse appliquée (Tag −1, Note −2/~1, Event −1, Person −1/~2), personne retirée |
| Proposition, puis modification « Desktop » du même objet, puis `apply` | **refus** : « Conflit : update Person I1 a été modifié dans Gramps Web depuis la proposition… » (libellé à généraliser) |

Coût mesuré : un sous-processus de lecture complète de l'arbre d'essai prend 0,16 s (import de la bibliothèque
compris).

### E6. Lecture sans la bibliothèque

`SELECT handle, json_data FROM <classe>` sur une connexion `mode=ro` donne, sur 6.0 et 6.1, **exactement** les
mêmes 74 objets que la bibliothèque. `metadata.version` se lit de la même façon. Une base 5.2 n'a pas de colonne
`json_data` (pickle) : la lecture directe y est impossible sans dépickler des tuples de la bibliothèque 5.2.

L'**écriture** directe en SQL est déconseillée. Il faudrait reproduire :

- les colonnes secondaires (`given_name`, `surname`, `gramps_id`, `enclosed_by`…) ;
- les lignes de `reference` ;
- `gender_stats` ;
- les métadonnées : types personnalisés, prochains identifiants, liste des patronymes ;
- le tout pour chaque version de schéma.

Une erreur ne se voit qu'à l'usage dans Desktop : index faux, liens arrière manquants, types inconnus de
l'interface. Le risque de corruption silencieuse est réel, et l'essai B4 montre que même la bibliothèque perd ces
métadonnées si deux écrivains se chevauchent.

## Réponses aux questions de l'issue

- **« `mapping.py` réutilisable tel quel »** : vrai pour 6.0. Vrai pour 6.1 en lecture, et en écriture à condition
  de compléter les objets avec `familysearch_sync` et tout futur champ de schéma. Faux pour 5.2.
- **Verrou** : l'écriture est refusée si et seulement si le plugin vérifie le fichier lui-même. La lecture seule est
  possible, à condition de ne pas passer par `load()`/`close()`. `force` et `break_lock` sont exclus.
- **Annulation** : pas d'annulation native persistante. Le journal du plugin et la transaction inverse vérifiée
  suffisent, comme pour le Web.
- **Gramps 5.2** : pas de backend direct. Lecture par l'import Gramps XML déjà livré, écriture par l'export Gramps
  XML 1.7.1 déjà livré. La bibliothèque 6.0 sait **lire** une base 5.2 en lecture seule (E2), mais cela ouvrirait
  par `load()` et effacerait un verrou éventuel. La voie XML est plus simple.

## Pistes comparées

| Critère | 1. Bibliothèque + `DbTxn` (sous-processus) | 2. Échange Gramps XML (livré) | 3. Gramps Web + addon de synchro |
|---|---|---|---|
| Contrat proposer → accord → appliquer | **identique** (E5) | non : l'écriture est un fichier à importer à la main, et un second import duplique les données | identique côté Web, mais l'addon réécrit l'arbre en dehors du contrat (#271) |
| Verrou / concurrence | à gérer par le plugin (E3), écriture refusée quand Desktop est ouvert | sans objet | sans objet en local ; la synchro écrase avec `force=1` |
| Annulation | journal du plugin, transaction inverse vérifiée | non | côté Web oui ; ce qu'a fait la synchro, non |
| Sans perte | oui en 6.0 et 6.1 (E1) | aller-retour sans perte vérifié par le banc (#269), sauf ce que le modèle ne représente pas | **non** : fusions, renumérotation des `gramps_id`, doublons d'attributs (#271) |
| Gramps 5.2 | non (XML) | oui | addon 5.2 non étudié |
| Installation | bibliothèque `gramps` de la bonne version, via un environnement géré par le plugin comme le banc | rien | serveur Gramps Web, Celery, Redis, addon |
| Sécurité | chemin de base unique fixé par la configuration, `GRAMPSHOME` dédié, sauvegarde avant la première écriture, aucun réseau | fichiers seulement | compte, jetons, exposition réseau |
| Accès distant, comptes, partage | non | non | oui |
| Effort | moyen (voir le découpage) | nul | faible côté plugin, élevé côté utilisateur |
| Tests en CI | le banc existe déjà : bases fictives créées par la bibliothèque, essais de verrou par processus | existants | lourds : Celery, Redis, addon (#271) |

### Ce que le backend Desktop débloquerait

- Personne de référence (`definir_personne_reference`, #274) : métadonnée écrite dans la même transaction SQL que
  les objets, état avant et après journalisé pour l'annulation.
- Groupes de noms (#276) : écriture et retour exact à « aucun regroupement » par
  `set_name_group_mapping(nom, None)`.
- Fiche du chercheur, signets et formats de nom (#282) en écriture journalisée, avec le même schéma état avant /
  état après que les réglages Web.
- Vérification par la bibliothèque : relire les objets écrits avec la bibliothèque de la même version et contrôler
  `serialize()` attrape ce que l'essai E1 a révélé en 6.1.
- Pas de serveur, pas de compte, pas de réseau pour l'arbre.

### Ce qu'il n'aurait pas

- Pas d'accès distant ni de comptes et rôles : l'arbre est sur le poste qui exécute le serveur MCP. Le Docker du
  plugin devrait monter le dossier de l'arbre.
- Pas d'écriture quand Desktop est ouvert : l'utilisateur ferme l'arbre dans Desktop pour appliquer (la lecture
  reste possible).
- Pas d'historique côté application (Desktop n'a rien de persistant) : seul le journal du plugin fait foi.
- Pas d'envoi de médias : les fichiers restent où Desktop les attend (`get_mediapath` de la base) ; voir #280.

## Recommandation

**Piste 1**, sous la forme suivante, avec 6.0 et 6.1 seulement. 5.2 reste sur la voie XML.

1. **Lecture** : lecture directe dans SQLite (`mode=ro`), une transaction courte par chargement. Pas de
   bibliothèque, pas de verrou, et c'est permis quand Desktop est ouvert. Le rafraîchissement incrémental du
   backend (`refresh` : comparer `handle, change`) se fait par une seule requête par table.
2. **Écriture** : un sous-processus (« agent Gramps ») qui exécute la bibliothèque de la **même** version que le
   schéma lu. Il refuse si un fichier `lock` existe, pose un verrou exclusif, vérifie `old` puis écrit en une
   `DbTxn`, et ferme. Le verrou n'est tenu que le temps d'une application.
3. **Sauvegarde** : copie de `sqlite.db` par l'API de sauvegarde de SQLite, dans le dossier de données de
   Genealogiste, avant la **première** écriture sur une base, puis selon une politique à fixer (question ouverte).
4. **Refus** : schéma inconnu, plus récent ou plus ancien que les bibliothèques disponibles ; base hors du chemin
   configuré ; verrou présent.
5. **Journal et annulation** : réutiliser tels quels `gramps-transactions.jsonl`, `recover()` et `propose_undo`.

### Architecture cible

- **Interface commune** : `GrampsBackend` ne dépend que d'un client (E5). On extrait un `Protocol` de client
  Gramps : `load_all`, `refresh`, `get`, `transaction`, `tree`, `exiger_ecriture`, `permissions`, et les lectures
  ou écritures de réglages (`chercheur`, `signets`, `formats_noms`, `name_groups`). Il aurait deux
  implémentations, `GrampsClient` (HTTP) et `ClientDesktop` (SQLite + agent).

  Les parties propres au Web sont à paramétrer :
  - envoi des médias (`media_pending`/`media_upload`) ;
  - identité de l'arbre (`check_tree`) ;
  - historique serveur (`client.history`) ;
  - libellés « Gramps Web » des messages.
- **Agent Gramps** : un script de la bibliothèque standard plus `gramps`, livré avec le plugin et lancé avec
  `-I`, avec `GRAMPSHOME` égal à un dossier vide du cache. Entrée et sortie en JSON (fichier ou stdin), une
  commande par processus (`ecrire`, `verifier`). Aucun import de `genealogiste_mcp` dans l'agent, comme la
  sonde du banc. Le serveur MCP n'importe jamais `gramps`, donc pas d'extra obligatoire.
- **Bibliothèque** : par défaut, un environnement géré par le plugin dans le cache, créé à la demande (comme
  `scripts/verifier_gramps_desktop.py:864-900`). Variante : `GENEALOGISTE_GRAMPS_DESKTOP_PYTHON` désigne un
  interpréteur où `import gramps` fonctionne (Python système Debian, par exemple). L'agent rapporte la version
  de la bibliothèque, qui doit correspondre au schéma.
- **Configuration** (noms proposés, à trancher) :
  - `GENEALOGISTE_BACKEND=gramps_desktop` ;
  - `GENEALOGISTE_GRAMPS_DESKTOP_BASE` : dossier de l'arbre, celui qui contient `sqlite.db`, `database.txt` et
    `name.txt`. Seul ce dossier est ouvert, après résolution des liens ; il n'y a jamais de recherche dans
    `grampsdb/`.
  - `GENEALOGISTE_GRAMPS_DESKTOP_PYTHON` (facultatif).
- **Journal et données** : `GENEALOGISTE_DATA_DIR/gramps-transactions.jsonl`, avec le même format. Un fichier
  d'identité de l'arbre (chemin, contenu de `name.txt`, nom du dossier) refuse un autre arbre, comme `check_tree`.
  Les sauvegardes vont sous `GENEALOGISTE_DATA_DIR/sauvegardes-gramps-desktop/`.
- **`server.py`** : les 12 tests `config.backend == "gramps"` deviennent un prédicat « famille Gramps »,
  avec des capacités par backend (médias envoyés, réglages écrits, tâches).
- **`diagnostic`** : contrôles `gramps_desktop_base` (trouvée, schéma lu, version de bibliothèque
  correspondante), `gramps_desktop_verrou` (posé ou non, par qui) et `gramps_desktop_sauvegarde`.

## Risques

- **Corruption par une mauvaise version de bibliothèque** (E2) : contrôle du schéma avant `load()`, obligatoire et
  testé.
- **Desktop ouvert sans verrou** (verrou cassé, plantage) : on ne peut pas le détecter par le fichier. Les
  métadonnées de Desktop écrasent alors celles du plugin à sa fermeture (E3 B4). À documenter, et éventuellement
  à détecter par processus (non éprouvé).
- **Lecture longue** qui bloque une écriture de Desktop (E3 C) : lectures en une transaction courte.
- **Gramps 6.1** n'est qu'en bêta : le schéma 22 et `familysearch_sync` peuvent encore évoluer ; ce support est
  à revalider à la version finale.
- **Installation de la bibliothèque** : sous Windows AIO et macOS, pas d'interpréteur réutilisable. Il faut
  l'environnement géré, donc Python et `uv` sur le poste.
- **Docker** : l'arbre doit être monté dans le conteneur, à un chemin dont le propriétaire peut écrire.

## Questions ouvertes pour le mainteneur

1. Piste 1 retenue, avec 6.0 et 6.1 seulement et 5.2 sur la voie XML ?
2. Nom de la valeur : `gramps_desktop` ? Et des variables `GENEALOGISTE_GRAMPS_DESKTOP_*` ?
3. Bibliothèque : environnement géré par le plugin (téléchargement PyPI de `gramps==6.0.x`, sources épinglées
   pour 6.1), ou seulement l'interpréteur désigné par l'utilisateur ?
4. Sauvegarde : avant la première écriture de chaque session, chaque jour, ou avant chaque écriture ? Rétention ?
5. Faut-il versionner les prototypes d'essai (`scripts/etudes/`) ou les transformer directement en tests du banc ?
6. Signaler en amont les deux comportements de la bibliothèque : `close()` qui efface le verrou d'une base ouverte en
   lecture seule, et `close()` qui réécrit `version` avant `DbVersionError` ?
7. Lecture quand Desktop est ouvert : l'autoriser (état validé, sans les types personnalisés que Desktop n'a pas
   encore écrits) ou la refuser pour éviter toute confusion ?

## Découpage proposé en issues d'implémentation (non créées)

1. **refactor(gramps) : interface commune de client Gramps.** `Protocol`, capacités par backend, libellés
   généralisés, prédicat « famille Gramps » dans `server.py`. Aucun changement de comportement ; tests existants.
2. **feat(gramps-desktop) : lecture SQLite d'une base 6.x.** Contrôle du schéma, refus de 5.2 et des schémas
   inconnus, `load_all`/`refresh`, identité de l'arbre. Tests : bases fictives créées par la bibliothèque du banc.
3. **feat(gramps-desktop) : agent d'écriture.** Verrou exclusif, contrôle `old`, `DbTxn`, sauvegarde,
   complétion des objets 6.1, refus si verrou. Tests sur le banc : verrou posé par un processus « Desktop », base
   plus récente, base 6.1.
4. **feat(gramps-desktop) : backend dans `App`.** Configuration, `diagnostic`, journal, `recover`, annulation,
   documentation `docs/gramps-desktop.md`.
5. **feat(gramps-desktop) : environnement de la bibliothèque.** Installation à la demande, version choisie selon
   le schéma, documentation par plateforme. Les cas Windows, macOS et Flatpak sont à éprouver.
6. **feat(gramps-desktop) : médias.** Chemin de base de la base (`media-path`), pas d'envoi, rapport des fichiers
   absents (lien avec #280).
7. **feat(gramps-desktop) : réglages et métadonnées.** Personne de référence (#274), groupes de noms (#276),
   fiche du chercheur, signets et formats de nom (#282), en écriture journalisée et annulable.
8. **chore : signalement amont** des comportements de `close()` (si la question 6 est acceptée).

## Matrice de tests proposée

| Cas | 6.0.8 | 6.1 (tag épinglé) | 5.2.4 |
|---|---|---|---|
| Lecture SQLite = lecture bibliothèque (74 objets, `famille.ged`, `legacy551.ged`, `geneweb7_gwb2ged.ged`) | oui | oui | refus attendu (schéma 20) |
| Écriture `DbTxn` des objets du mapping, relecture identique, `serialize()` sans erreur | oui | oui (avec complétion) | — |
| Proposer → appliquer → annuler, journal `terminee` | oui | oui | — |
| Conflit : objet modifié entre proposition et application | oui | oui | — |
| Verrou posé par un autre processus : refus, verrou intact | oui | oui | — |
| Lecture pendant que « Desktop » est ouvert : verrou intact | oui | oui | — |
| Base de schéma supérieur ou inconnu : refus **sans modification** (empreinte du fichier) | 22 → refus | 23 fictif → refus | — |
| Base de schéma inférieur : refus sans mise à niveau | — | 21 → refus | — |
| Sauvegarde créée avant la première écriture et restaurable | oui | oui | — |
| Personne de référence et groupes de noms : écriture, annulation exacte | oui | oui | — |

Ces cas s'ajoutent au banc existant (`make test-gramps-desktop`, environnements déjà installés en CI). Les tests
unitaires sans bibliothèque se contentent d'une base SQLite de fixture produite une fois par le banc.

## Sources

- Bibliothèques exactes du banc : `gramps==5.2.4`, `gramps==6.0.8` (PyPI), `v6.1.0-beta2`
  (`2153e4fa4b0e4ddf7542f1c064c7820bc345a482`).
- gramps-project/gramps `maintenance/gramps52` `14c01e56f088a865cd1f5a78708357237b74d92d`, `maintenance/gramps60`
  `32aa29629b94c549f232cd0b61c137ae95d73acf`, `maintenance/gramps61` `e9c09a44791def6a6b81079dc7f8cbe8c7e69cc0`.
- gramps-project/gramps-web-api `master` `9cbf9330fb53711a6d5c1abd16c4b24e5de5a77d` : `api/tasks.py:980-1066`,
  `api/util.py:849-858`.
- Genealogiste `main` `3d61e68` : `mcp/src/genealogiste_mcp/gramps/backend.py` (`GrampsBackend`), `gramps/client.py`,
  `gramps/mapping.py`, `scripts/verifier_gramps_desktop.py`, `scripts/sonde_gramps_desktop.py`.
