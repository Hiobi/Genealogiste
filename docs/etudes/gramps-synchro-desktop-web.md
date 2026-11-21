# Étude : coexistence avec l'addon de synchronisation Gramps Desktop ↔ Gramps Web (#271)

Statut : **étude**, rien n'est implémenté. Le mainteneur valide la procédure et les contrôles avant toute
implémentation.

Les essais ont été faits le 2026-11-21, sur un Gramps Web jetable et une base Gramps Desktop temporaire, avec
l'arbre fictif du dépôt (`mcp/tests/fixtures/famille.ged`) et des objets fictifs ajoutés pour l'essai. Le serveur
a été supprimé à la fin, volumes compris (`down -v`). Ce qui n'a pas été exécuté est marqué **non éprouvé**.

## Résumé

L'essai complet a été mené jusqu'au bout. L'addon a tourné **sans interface** : son cœur (`session.py`,
`diffhandler.py`, `webapihandler.py`) n'importe pas GTK. Le serveur était une image Gramps Web épinglée avec Redis
et un worker Celery.

Ce que montrent les essais :

- **Les marqueurs survivent quand un seul côté modifie.** Les attributs `Genealogiste-*`, l'étiquette
  `Genealogiste:auto` et les 25 notes de preuve arrivent intacts dans les deux sens.
- **Un objet modifié des deux côtés est fusionné, au détriment du plugin** :
  - un attribut géré à deux valeurs différentes est **gardé en double** ;
  - la note de preuve prend le **texte distant** ;
  - une étiquette retirée **revient** ;
  - un objet `Tag` est remplacé par sa version distante, **sans erreur** (`BaseObject.merge` ne fait rien),
    ce qui lève l'incertitude de la recherche amont.
- **Découverte majeure : la synchro renumérote les `gramps_id` de Genealogiste.** L'addon réimporte le serveur par
  Gramps XML. À cet import, Gramps reformate les identifiants numériques selon les préférences de l'utilisateur
  (`I3` → `I0003`). Tout objet dont l'identifiant n'a pas ce format devient alors « modifié des deux côtés » et
  sa fusion écrit le nouvel identifiant **des deux côtés**. Les identifiants de Genealogiste (`I3`, `F2`, `S1`,
  `R1`, ou `I10` pour une personne créée par le plugin) changent donc. Une proposition qui citait `I3` échoue
  ensuite (« personne inconnue »). Pour les objets copiés vers Desktop, les deux côtés finissent même avec des
  identifiants différents (`I2` sur le Web, `I0002` dans Desktop), et l'addon ne le voit jamais.
- **Une modification faite dans Desktop est bien vue par le plugin comme une modification externe.** Elle arrive
  sur le serveur en « Raw transaction ». Le rafraîchissement du plugin la compte, et une proposition en cours sur
  l'objet est refusée au moment d'appliquer (conflit).
- **Une transaction du plugin peut être écrasée par une synchro (`force=1`).** Si le plugin écrit entre la
  comparaison et l'envoi de l'addon, son écriture est perdue alors que son journal la dit « terminée ». À la
  synchro suivante, une étiquette créée par le plugin pendant cette fenêtre est **supprimée du serveur**. Un
  prototype de contrôle (journal comparé à l'état courant, puis à l'historique du serveur) a retrouvé les deux
  objets en cause.
- **Médias** :
  - un média ajouté dans Desktop **avec sa somme MD5** est envoyé et garde son chemin relatif sur le serveur ;
  - sans somme, l'envoi est refusé (409) et le média reste indéfiniment « à fusionner » et « manquant ».
- **Recommandation** :
  - une procédure stricte : un seul écrivain à la fois, synchroniser avant et après une session du plugin, jamais
    pendant ;
  - deux contrôles de `diagnostic` : transactions du plugin modifiées depuis, et identifiants renumérotés ;
  - une décision sur le format des `gramps_id` créés par Genealogiste ;
  - pas de test addon en CI par défaut, mais une cible manuelle.

## Contexte

L'addon **Gramps Web Sync** de Gramps Desktop synchronise une base locale avec un serveur Gramps Web. Un même arbre
peut alors être modifié dans Desktop, dans l'interface web et par le plugin (backend `gramps`,
[docs/gramps-web.md](../gramps-web.md)). L'étude de code amont publiée sur #271 décrit l'algorithme :

1. export Gramps XML complet du serveur, importé dans une base temporaire ;
2. comparaison par handle, en ignorant `change` ;
3. coupure à la dernière date commune ;
4. fusion avec le distant comme base ;
5. `POST /transactions/?force=1&background=1`.

Cette note reprend ses points « incertain » par l'essai.

## Faits amont

| Dépôt | Branche / version | Commit | Fichiers |
|---|---|---|---|
| gramps-project/addons-source | `maintenance/gramps60`, GrampsWebSync 1.5.8 | `85e5d094a71e0b83db3a420c21c65b8239ece283` | `session.py`, `diffhandler.py`, `webapihandler.py`, `const.py`, `adapters.py`, `tests/` |
| gramps (bibliothèque) | `gramps==6.0.8` (PyPI, banc) | — | `gen/db/utils.py`, `gen/db/generic.py`, `plugins/importer/importxml.py`, `gen/lib/baseobj.py` |
| gramps-project/gramps-web-api | `master` | `9cbf9330fb53711a6d5c1abd16c4b24e5de5a77d` | `api/resources/file.py`, `api/resources/history.py`, `api/__init__.py`, `auth/const.py` |

### Structure de l'addon et dépendances

- Le cœur ne dépend pas de GTK :
  - `SyncSession` (`session.py:442`) reçoit ses collaborateurs en paramètres : serveur, identifiants, médias,
    exécution, horloge, observateur ;
  - `diffhandler.py` et `webapihandler.py` n'importent que `gramps` et la bibliothèque standard ;
  - seuls `adapters.py` (`GLib`) et `grampswebsync.py` (`Gtk`) touchent l'interface.

  L'addon a ses propres tests sans interface (`tests/scenario.py`, `tests/fakes.py`).
- Conditions d'exécution :
  - l'addon exige une file de tâches côté serveur (`session.py:935`) et la permission `ViewPrivate` (`:937`) ;
  - `docker-compose.test.yml` n'a pas de Celery, d'où un compose d'essai propre (ci-dessous).

### Comment la synchro traite les données

- **Base temporaire** : `import_as_dict` crée une base en mémoire avec les **préfixes d'identifiants des
  préférences de l'utilisateur** (`gen/db/utils.py:143-160`, `config.get("preferences.iprefix")`, `I%04d` par
  défaut).
- **Renumérotation à l'import XML** : `importxml.legalize_id` (`plugins/importer/importxml.py:1018-1044`) passe
  chaque identifiant dans `id2user_format`. Cette fonction (`gen/db/generic.py:1042-1075`) reformate
  `<préfixe><chiffres>` selon le motif de la préférence : `I3` devient `I0003`. Un identifiant non numérique
  (`E0cced640`) n'est pas touché. Un motif sans largeur (`I%d`) ne correspond pas à l'expression
  `(.*)%[0 ](\d+)[diu]$` et laisse les identifiants tels quels (lu, **non éprouvé**).
- **Fusion d'un objet modifié des deux côtés** : `deepcopy(distant).merge(local sans gramps_id)`, écrit des deux
  côtés (`diffhandler.py:300-311`). `Tag` hérite de `BaseObject.merge`, qui ne fait rien
  (`gen/lib/baseobj.py:216-228`) : le distant gagne sans erreur.
- **Médias** : `PUT media/{handle}/file?uploadmissing=1` (`webapihandler.py:565-575`).
  - Le serveur garde le `path` existant si la somme envoyée égale celle de l'objet (`file.py:126-139`).
  - Sinon, il répond 409 « wrong checksum » (`file.py:145-147`), que l'addon traite comme un échec non bloquant.
- **Jetons** : les routes de jetons d'accès ne portent que sur l'utilisateur courant
  (`/users/-/access-tokens/<scope>/…`, gramps-web-api `api/__init__.py:882-894`). Le compte du plugin ne peut
  donc pas voir le jeton `sync` d'un autre compte.
- **Historique** : `GET /transactions/history/` exige `ViewPrivate` (`history.py:119-126`), donc il est lisible
  par le compte Editor du plugin. Chaque entrée porte `description`, `connection.user` et `changes[].obj_handle`.

## Essai réel

### Montage

| Élément | Version |
|---|---|
| Gramps Web | image `ghcr.io/gramps-project/grampsweb@sha256:dbd20a8b…` (26.11.0, API 3.25.1, Gramps 6.0.8, schéma 21), comme `docker-compose.test.yml` |
| File de tâches | `redis:7-alpine` (`sha256:8da19c73…`), worker `celery -A gramps_webapi.celery worker` (même image), volumes nommés partagés entre serveur et worker |
| Compose | dans le dossier de travail de l'essai, `COMPOSE_PROJECT_NAME=genealogiste-etude-271`, port `127.0.0.1:5071`, supprimé par `down -v` (aucun volume restant vérifié) |
| Addon | GrampsWebSync 1.5.8 (`85e5d09`), exécuté par un pilote sans interface dans l'environnement `gramps==6.0.8` du banc (GLib factice). Pilote : `SyncSession`, vrai `WebApiHandler`, identifiants en mémoire, exécution en ligne, médias d'un dossier |
| Desktop | base SQLite temporaire créée par la bibliothèque 6.0.8 (`HOME`/`GRAMPSHOME` redirigés), chargée avec les 74 objets du mapping (`famille.ged`) |
| Plugin | `GrampsBackend` et `GrampsClient` réels du dépôt (`main` `3d61e68`) |
| Comptes | un seul compte fictif `Owner`, partagé par l'addon et le plugin, pour simplifier. En usage normal, le plugin a son compte Editor dédié. |

Temps de mise en place : environ 20 s pour `up --wait`. Le scénario complet tient en quelques minutes.

Incident constaté : quand le plugin venait de se connecter, la connexion de l'addon a reçu un **429**
(`/api/token/` limité à une requête par seconde), rapporté par l'addon comme `RATE_LIMITED`. Une pause de 2 s
avant chaque synchro a suffi.

### Résultats

| Étape | Ce qui est fait | Constat |
|---|---|---|
| S0 | Première synchro Desktop → Web (serveur vide) | Tout est ajouté côté serveur : une transaction « Raw transaction » de 199 changements. Desktop et Web sont **identiques** (hors `change`) : attributs `Genealogiste-UID`, `Genealogiste-UID noms`, étiquettes `Genealogiste:auto` et `Preuve : …`, 25 notes de preuve étiquetées. |
| S1 | Le plugin applique une proposition sur le Web (`ajouter_evenement` sur I2, `etiqueter` I1), puis synchro | Les ajouts et mises à jour du plugin arrivent dans Desktop, avec la note de preuve `Genealogiste:auto` recalculée. **En plus, 14 fusions (`mrg_remote`) sur des objets que personne n'avait touchés** (I3 à I9, F1 à F3, S1 à S4, R1). Cause : renumérotation à l'import XML de l'addon. Après la synchro, `I3` est devenu `I0003` des deux côtés (« Raw transaction » de 14 changements). Pour I1 et I2, copiés vers Desktop (`upd_local`), Desktop a `I0001`/`I0002` et le Web garde `I1`/`I2`. |
| S2 | Proposition du plugin sur I3, puis attribut ajouté à I3 dans Desktop, synchro, puis application de la proposition | La proposition rédigée avec `I3` **échoue** (« personne inconnue : 'I3' », identifiant renuméroté) ; refaite avec l'identifiant courant. La synchro envoie `upd_remote` (« Raw transaction », 1 changement). Le rafraîchissement du plugin rapporte `{"Person": {"modifies": 1}}`. La proposition en cours est **refusée** au moment d'appliquer : « Conflit : update Person I0003 a été modifié… ». |
| S3 | Objets modifiés des deux côtés, puis synchro (4 fusions, `DONE`) | (a) `Genealogiste-UID` de I4 : `valeur-desktop` contre `valeur-web` donne **deux attributs** `Genealogiste-UID` des deux côtés. (b) Note `Genealogiste:auto` : Desktop change le texte et retire l'étiquette, le Web change le texte ; résultat des deux côtés : texte **Web**, étiquette **rétablie**, texte Desktop perdu. (c) Objet `Tag` `Genealogiste:auto` : couleur changée dans Desktop, priorité sur le Web ; résultat : **version Web entière**, couleur Desktop perdue, aucune erreur. (d) I1 : étiquette « Essai 271 » retirée dans Desktop, `private` passé à vrai sur le Web ; résultat : étiquette **revenue**, `private` vrai. |
| S4 | Attribut ajouté à I6 dans Desktop. L'addon compare (`upd_remote` I6). **Entre la comparaison et l'envoi**, le plugin applique `etiqueter` I6, avec le recalcul des notes. L'addon envoie ensuite. | Dans l'historique du serveur, la transaction 7 (plugin) précède la transaction 8 (« Raw transaction », 2 changements, `force=1`). **I6 sur le serveur est la version Desktop : l'étiquette du plugin est perdue.** Le journal du plugin dit `terminee`. |
| S5 | Synchro suivante | L'étiquette « Plugin s4 », créée par le plugin pendant la fenêtre de S4, existe seulement sur le serveur et son `change` précède la coupure : l'addon la classe « supprimée en local » et **la supprime du serveur** (`del_remote`). Les objets réécrits par le plugin en S4 (9 notes, S2, I4) passent en « fusion ». |
| S5 médias, sans somme | Média ajouté dans Desktop avec `checksum` vide, fichier présent sous le chemin de base | `add_remote`. L'envoi du fichier est **refusé** (409, `envoyes: false`). Le serveur garde `path` = chemin relatif Desktop, sans fichier. À chaque synchro suivante : « fusion » du média et « manquant côté serveur ». L'identifiant `O271` devient `O0271`. |
| S5 médias, avec somme MD5 | Même chose, `checksum` = MD5 du fichier, comme le pose l'éditeur de média de Desktop | Envoi **accepté**. Le serveur garde le chemin relatif `actes/acte fictif b.jpg` (fichier rangé sous `/app/media/actes/`, pas de renommage `<MD5>.<ext>`), avec la même somme des deux côtés. Pourtant, les synchros suivantes l'annoncent encore en « fusion » et « manquant côté serveur », alors que `GET /media/?filemissing=1` ne le liste pas et que `GET /media/{handle}/file` répond 200. Cause **non élucidée** ; hypothèse non éprouvée : somme recalculée à l'import XML dans la base temporaire, où le fichier est introuvable. |

Non éprouvés :

- un média envoyé par le plugin (chemin `<MD5>.<ext>`) puis descendu dans Desktop ;
- le miroir Git du plugin (désactivé pendant l'essai) ;
- les modes « reset » de l'addon ;
- l'addon 6.1 (`maintenance/gramps61`, 1.5.9) ;
- une base Desktop 5.2.

### Prototype du contrôle « transactions du plugin modifiées depuis »

Algorithme essayé, en lecture seule, à la fin du scénario :

1. Pour chaque objet écrit par une transaction effective du journal, retenir le **dernier** `new` écrit par le
   plugin.
2. Le comparer, hors `change`, à l'état courant du serveur (l'instantané que le backend tient déjà).
3. Pour chaque écart, chercher dans `GET /transactions/history/` la dernière transaction du serveur qui touche
   ce handle après la transaction du plugin, et la classer :
   - « Raw transaction » (description par défaut de l'addon, sans message) : **synchro probable** ;
   - une transaction nommée d'un autre compte : **édition ordinaire**.

Résultat : 2 objets signalés, `Person:I0001` (édition web en S3 puis fusion) et `Person:I0006` (écrasé en S4). Le
serveur liste 5 « Raw transaction ». Les deux cas sont donc retrouvés. Seule l'étape 3 les distingue d'une
édition ordinaire.

Coût :

- un instantané complet, déjà chargé par le backend ;
- la lecture du journal ;
- quelques pages d'historique, jusqu'à la plus ancienne transaction effective du plugin.

Faux positifs :

- toute édition ordinaire d'un objet que le plugin a écrit. C'est un « modifié depuis » réel, mais ce n'est pas
  une synchro ;
- une transaction « Raw transaction » d'un autre client que l'addon. Le compte utilisateur (`connection.user`)
  aide à trancher : celui de l'humain qui synchronise, pas celui du plugin ;
- un objet supprimé puis recréé par une annulation est comparé à son état réel, sans faux positif dans l'essai.

## Réponses aux questions de l'issue

- **Attributs inconnus et notes étiquetées** : ils survivent tels quels si un seul côté les modifie. Ils sont
  fusionnés au détriment du plugin si les deux côtés modifient (S3).
- **Modification Desktop vue comme externe** : oui (S2). Elle arrive en « Raw transaction ». `snapshot`
  la compte, ce qui déclenche aussi le commit « Modifications externes » du miroir Git quand il est actif (même
  chemin de code que pour une édition web, non exécuté ici). Une proposition en cours est invalidée par le
  contrôle `old`.
- **Synchro qui écrase une transaction du plugin** :
  - c'est possible (S4) ;
  - ce n'est détectable qu'**après coup**, en comparant le journal (`new`) à l'état courant et en corrélant avec
    l'historique « Raw transaction » ;
  - le champ `change` seul ne suffit pas, puisque la synchro le réécrit de toute façon.
- **Objet `Tag` modifié des deux côtés** : pas d'échec ; le distant gagne entièrement (S3 c).

## Procédure recommandée

1. **Un seul écrivain à la fois.**
   - Pendant une session du plugin, ne rien modifier dans Gramps Desktop et ne pas lancer de synchro.
   - Pendant une synchro, ne rien appliquer depuis le plugin. S4 montre que la fenêtre entre la comparaison et
     l'envoi suffit à perdre une écriture.
2. **Avant la session** : synchroniser depuis Desktop (les modifications locales montent), puis laisser le plugin
   rafraîchir (`gramps_synchroniser`). **Après la session** : synchroniser pour descendre les écritures du plugin.
3. **Maître des données gérées** : les attributs `Genealogiste-*`, les notes et l'étiquette `Genealogiste:auto`,
   et les étiquettes `Preuve : …` ne sont modifiés **que par le plugin**. Dans Desktop, on les lit sans les
   modifier, sinon on obtient doublons, étiquettes rétablies et textes perdus (S3).
4. **Identifiants** : tant que la question 2 ci-dessous n'est pas tranchée, ne pas synchroniser un arbre dont les
   identifiants viennent de Genealogiste (`I3`, `F2`…) sans accepter leur renumérotation. Option à éprouver :
   préfixes de Desktop sans largeur (`I%d`, Préférences, onglet « ID Formats ») pour que l'import XML de l'addon
   n'y touche pas (non éprouvé).
5. **Médias ajoutés dans Desktop** : par l'éditeur de média, qui pose la somme MD5. Sans somme, l'envoi échoue à
   chaque synchro.
6. **Comptes** : l'addon sous le compte de l'utilisateur, le plugin sous son compte dédié. L'historique du serveur
   permet alors d'attribuer chaque « Raw transaction ».

## Garde-fous proposés

- **`diagnostic`, contrôle `gramps_transactions_modifiees`** : l'algorithme ci-dessus. Il liste les objets écrits
  par le plugin qui ont été modifiés depuis, classés « synchro probable » ou « édition ». Il donne les identifiants
  seulement, jamais un nom. Il est aussi appelé, en version courte, à la fin de `arbre_annuler_modification` : une
  annulation sur un objet réécrit par une synchro est déjà refusée par le contrôle `old`, et le contrôle en
  explique la raison.
- **Renumérotation externe** : au rafraîchissement, signaler un même handle dont le `gramps_id` a changé, et le
  contrôle de `diagnostic` correspondant. Les identifiants cités dans le journal, les enquêtes, les notes et les
  pièces deviennent faux sans autre signe.
- **Avertissement à l'application** : si une « Raw transaction » d'un autre compte date de moins de N minutes
  (valeur à fixer), `arbre_appliquer` avertit qu'une synchro est peut-être en cours. Ce n'est qu'un indice : la
  phase de comparaison de l'addon ne laisse aucune trace d'écriture sur le serveur.
- **Jeton `sync` actif** : non détectable par le compte du plugin (routes limitées à l'utilisateur courant). À
  abandonner.

## Test d'intégration en CI : coût et valeur

Ce qu'il faudrait :

- le compose de l'essai (Redis et worker Celery, environ 40 Mo d'image en plus, l'image Gramps Web étant déjà en
  cache pour `test-gramps`) ;
- l'addon à un commit épinglé de `addons-source` ;
- l'environnement `gramps==6.0.8` du banc et son GLib factice ;
- un pilote sans interface, environ 150 lignes, à partir des ports de `SyncSession` ;
- des pauses à cause de la limite de `/api/token/`.

Durée estimée : 2 à 3 minutes. Risques d'instabilité : Celery, la limite de débit et l'évolution de l'addon (une
version tous les quelques mois sur `maintenance/gramps60`).

Valeur : il fige des comportements **amont** (fusion, renumérotation, médias) plutôt que ceux du plugin. La
procédure et les contrôles de `diagnostic` se testent sans l'addon, en simulant ses effets par des transactions
« Raw transaction » sur le Gramps Web jetable existant.

Recommandation : **pas dans la CI par défaut**. Une cible manuelle `make test-gramps-synchro`, lancée avant de
documenter une nouvelle version de l'addon, et des tests `gramps_live` qui simulent la synchro.

## Liens avec #280 et #270

- **#280 (médias)** :
  - ce qui est confirmé par l'essai : l'addon conserve le chemin relatif d'un média Desktop porteur de sa somme, ce
    qui est favorable à la règle « chemin de base = racine du vault » ;
  - ce qui reste non éprouvé : un média envoyé par le plugin (`path` = `<MD5>.<ext>` sur le serveur) puis
    descendu dans Desktop. La section
    [Addon Gramps Web Sync : non éprouvé](../gramps.md#addon-gramps-web-sync--non-éprouvé) reste valable pour ce
    cas.
- **#270 (backend Desktop)** :
  - pour un utilisateur de Desktop seul, le backend Desktop rend l'addon inutile : une seule base, un seul
    écrivain, sans fusion ni renumérotation ([étude #270](gramps-backend-desktop.md)) ;
  - l'addon reste utile à qui veut **aussi** l'accès web. Le plugin vise alors **un seul** côté, le Web, et traite
    la synchro comme une source de modifications externes ;
  - le plugin ne doit pas écrire des deux côtés : backend Desktop sur la base locale **et** synchro vers un Web sur
    lequel le plugin écrit aussi, ce qui ferait deux écrivains et des fusions.

## Risques

- Perte silencieuse d'une écriture du plugin (S4), et suppression d'un objet créé pendant la fenêtre de synchro
  (S5).
- Renumérotation des identifiants (S1) : références de Genealogiste rompues, divergence durable entre Desktop et
  Web que l'addon ne voit pas.
- Doublons d'attributs gérés et notes de preuve écrasées (S3) : statuts de preuve incohérents jusqu'au prochain
  recalcul.
- Le comportement de l'addon peut changer d'une version à l'autre (1.5.9 sur 6.1, non éprouvé).

## Questions ouvertes pour le mainteneur

1. Valider la procédure (un seul écrivain, synchro avant et après, données gérées par le plugin seul) et son
   emplacement : une section de [docs/gramps-web.md](../gramps-web.md) ou une page dédiée.
2. **Identifiants** : Genealogiste doit-il créer des `gramps_id` au format Gramps par défaut (`I0010` plutôt que
   `I10`) pour résister à la renumérotation ? Cela changerait le format écrit et les références existantes, et
   relève de votre décision. La renumérotation dépend aussi des préférences de chaque poste Desktop.
3. Contrôle `gramps_transactions_modifiees` : seuil de l'avertissement « synchro récente » ? Classement par
   compte (`connection.user`) ou par description ?
4. Signaler en amont (addons-source) :
   - la renumérotation par l'import XML de la base temporaire, qui crée des fusions parasites et une divergence
     d'identifiants ;
   - la suppression d'objets créés sur le serveur pendant la fenêtre de synchro ;
   - le média sans somme, signalé à chaque synchro.
5. Faut-il versionner le pilote sans interface (`scripts/etudes/`) en vue de la cible manuelle ?

## Découpage proposé en issues (non créées)

1. **docs(gramps) : coexistence avec l'addon Gramps Web Sync.** Procédure, données gérées, identifiants, médias,
   avec les constats de cette étude.
2. **feat(diagnostic) : `gramps_transactions_modifiees`.** Journal comparé à l'état courant, classement par
   l'historique du serveur ; tests `gramps_live` avec des « Raw transaction » simulées.
3. **feat(gramps) : détection d'une renumérotation externe des `gramps_id`.** Au rafraîchissement, et dans
   `diagnostic`.
4. **Décision, puis feat(gramps) : format des `gramps_id` créés** (question 2).
5. **test(gramps) : cible manuelle `make test-gramps-synchro`.** Compose avec Celery, addon épinglé, scénario
   S0 à S5.
6. **chore : signalements amont** (question 4).

## Sources

- gramps-project/addons-source `maintenance/gramps60` `85e5d094a71e0b83db3a420c21c65b8239ece283` (GrampsWebSync
  1.5.8) : `session.py:81,442-536,684-737,816-830,935-938`, `diffhandler.py:300-311,319-359`,
  `webapihandler.py:398-400,565-590`.
- gramps `6.0.8` (PyPI) : `gen/db/utils.py:143-160`, `gen/db/generic.py:1042-1086`,
  `plugins/importer/importxml.py:1018-1044`, `gen/lib/baseobj.py:216-228`.
- gramps-project/gramps-web-api `master` `9cbf9330fb53711a6d5c1abd16c4b24e5de5a77d` :
  `api/resources/file.py:107-171`, `api/resources/history.py:119-126,269-276`, `api/__init__.py:882-894`,
  `auth/const.py:81-101,153-164`.
- Recherche amont publiée sur #271 (lecture de code, 2026-11-21).
- Genealogiste `main` `3d61e68` : `gramps/backend.py` (`snapshot`, `apply`, `_check`, `transactions`),
  `gramps/client.py` (`history`, `refresh`).
