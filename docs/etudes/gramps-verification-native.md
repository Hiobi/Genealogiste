# Étude : vérification native de Gramps et `arbre_coherence` (#275)

Note de conception du lot 4 du jalon M6. **Aucune fonction n'est implémentée** : la piste retenue attend la
validation du mainteneur. Date : 2026-11-21. Données des essais : arbres fictifs (patronymes `CASnn`) sur des
Gramps Web jetables, détruits après usage (`down -v`).

## Contexte

Gramps a l'outil « Vérifier les données » (âges improbables, ordre des événements, écarts parents-enfants…).
Gramps Web l'expose depuis l'API 3.17.0 : `POST /api/trees/-/verify`. Genealogiste a ses propres contrôles,
`arbre_coherence` (module `coherence.py`), appelés aussi à chaque proposition (`nouvelles_alertes_coherence`).
L'issue propose de lancer la vérification native en mode `gramps`, de fusionner et dédoublonner les alertes en
indiquant leur origine, d'aligner les seuils et, pour un futur backend Desktop, d'utiliser la même vérification
par la bibliothèque `gramps`.

## Faits amont (lus dans le code)

Références : gramps-web-api tag `v3.26.0` (`5b3f890703537c828009656e7886a2f1e856c060`) ; `git diff v3.25.1
v3.26.0` est vide pour `verify.py`, `verify_lib.py` et la tâche (relevé amont du 2026-11-21) : les lignes valent
pour l'image épinglée. Gramps tag `v6.0.8` (`13fdd22bf573fdf58ad519515c6ed90eb54dbc83`).

- **Route** : `api/__init__.py:961` ; ressource `api/resources/verify.py:36-61`. Permission `ViewPrivate`
  (rôle Member et au-dessus). Arbre `-` = arbre du jeton ; un autre arbre : 403. Paramètres **en query string**
  (`VerifyQueryArgs`, `schemas.py:3606`), plus `locale`. Paramètre inconnu : 422.
- **Tâche** : `verify_database`, `api/tasks.py:834-853`, `@shared_task()` **sans clé de verrou** ; base ouverte
  `view_private=True, readonly=True` (l. 848). Sans Celery, exécution dans la requête et **HTTP 201** + liste ;
  avec Celery, 202 + `{"task": {"href", "id"}}` à suivre par `GET /api/tasks/<id>` (non éprouvé : l'image de
  test n'a pas Celery).
- **Bibliothèque** : `gramps_webapi/verify_lib.py`, « GUI-free port of the Gramps "Verify the Data" tool »
  (en-tête l. 24-37), licence GPL v2 ou ultérieure (en-tête). Dépend seulement de `gramps.gen`.
  `run_verify(db, options, translate=)` l. 1610-1624.
- **Options et défauts** (`VerifyOptions.defaults`, l. 75-91) : `oldage=90, hwdif=30, cspace=8, cbspan=25,
  yngmar=17, oldmar=50, oldmom=48, yngmom=17, yngdad=18, olddad=65, wedder=3, mxchildmom=12, mxchilddad=15,
  lngwdw=30, oldunm=99, estimate_age=false, invdate=true`. `lngwdw` est déclarée mais transmise à aucune règle
  (l. 88 et 108 seulement). Mêmes défauts dans l'outil Desktop (`plugins/tool/verify.py:1179-1197`).
- **Constantes fixes** (non réglables) : père décédé plus de 294 jours avant la naissance (l. 1478), inhumation
  plus de 14 jours après le décès (l. 1019), baptême plus de 120 jours après la médiane de la fratrie (l. 1002).
- **Dates** : sans `estimate_age`, seules les dates complètes (jour et mois connus) comptent
  (`VerifyPerson`, l. 280-289 : `exact_date = 0` sinon) ; avec `estimate_age`, la valeur de tri (un point) de
  toute date. Les calculs d'âge divisent des écarts de jours juliens par 365.
- **Résultat** (`Rule.report_itself`, l. 615-626) : `{message, object_type: Person|Family, object_id,
  object_handle, name, rule_id, rule_params, severity: error|warning}`. Le message est traduit par `locale`
  (sinon locale du serveur). Une règle de famille ne dit pas quel enfant ni (hors message) quel parent.
- **Coût** : `VerifyRunner` précharge toutes les personnes si elles sont au plus 20 000 et toutes les familles
  au plus 10 000 (l. 369-370, `_preload`), puis parcourt une fois la base.
- **Outil Desktop** : `plugins/tool/verify.py` importe `Gtk`, `Gdk`, `GObject` au chargement (l. 53-55) bien
  qu'il ait un mode CLI (`tools.gpr.py`, `TOOL_MODE_CLI`) ; il garde une liste d'objets ignorés dans un fichier
  (l. 834-858) que l'API n'a pas. Comparaison automatique des deux fichiers (classe, `ID`, `SEVERITY`, messages) :
  **43 règles identiques** dans `verify.py` 6.0.8 et `verify_lib.py` 3.26.0. Le port n'a pas été relu ligne à
  ligne.

### Inventaire des règles de Gramps

| ID | Règle | Gravité | Option (défaut) |
|---|---|---|---|
| 1 | Baptême avant la naissance | erreur | |
| 2 | Décès avant le baptême | erreur | |
| 3 | Inhumation avant la naissance | erreur | |
| 4 | Inhumation avant le décès | erreur | |
| 5 | Décès avant la naissance | erreur | |
| 6 | Inhumation avant le baptême | erreur | |
| 7 | Âge élevé au décès | alerte | `oldage` (90) |
| 8 | Sexe inconnu | alerte | |
| 9 | Plusieurs familles de parents | alerte | |
| 10 | Marié souvent | alerte | `wedder` (3) |
| 11 | Âgé et non marié | alerte | `oldunm` (99) |
| 12 | Trop d'enfants | alerte | `mxchilddad` (15), `mxchildmom` (12) |
| 13 | Couple de même sexe | alerte | |
| 14 | Époux de sexe féminin | alerte | |
| 15 | Épouse de sexe masculin | alerte | |
| 16 | Époux de même patronyme (noms de naissance) | alerte | |
| 17 | Grand écart d'âge entre époux | alerte | `hwdif` (30) |
| 18 | Mariage avant la naissance | erreur | |
| 19 | Mariage après le décès | erreur | |
| 20 | Mariage précoce | alerte | `yngmar` (17) |
| 21 | Mariage tardif | alerte | `oldmar` (50) |
| 22 | Mère / père âgé | alerte | `oldmom` (48), `olddad` (65) |
| 23 | Mère / père jeune | alerte | `yngmom` (17), `yngdad` (18) |
| 24 | Parent pas encore né | erreur | |
| 25 | Parent décédé (père : + 294 j) | erreur | |
| 26 | Étendue des naissances des enfants | alerte | `cbspan` (25) |
| 27 | Grand écart entre deux enfants | alerte | `cspace` (8) |
| 28 | Personne isolée | alerte | |
| 29 | Date de naissance invalide | erreur | `invdate` (vrai) |
| 30 | Date de décès invalide | erreur | `invdate` (vrai) |
| 31 | Date de mariage, relation non « mariés » | alerte | |
| 32 | Âgé sans décès (comparé à la date du jour) | alerte | `oldage` (90) |
| 33 | Naissance le jour du décès | alerte | |
| 34 | Naissance le jour du mariage | erreur | |
| 35 | Décès le jour du mariage | alerte | |
| 36 | Baptême tardif selon la fratrie (+ 120 j) | alerte | |
| 37 | Inhumation tardive (> 14 j) | alerte | |
| 38 | Enfants hors ordre chronologique | erreur | |
| 39 | Familles hors ordre chronologique | alerte | |
| 40 | Famille : événement de rôle « inconnu » | erreur | |
| 41 | Personne : événement de rôle « inconnu » | erreur | |
| 42 | Famille : événements hors ordre | erreur | |
| 43 | Personne : événements hors ordre | erreur | |

`estimate_age` s'applique aux règles 7, 11, 17 à 27, 32, 38 et 39.

### Contrôles d'`arbre_coherence` (Genealogiste)

`coherence.py` (`LIMITS` l. 8-13, `check_person` l. 32-125, `check_tree` l. 128-142) et, en mode `gramps`,
`server.py:1243-1270`. Les dates sont des **intervalles** (date approchée, année seule, calendriers) : une alerte
n'est levée que si tout l'intervalle viole la règle.

| Code | Règle | Seuil |
|---|---|---|
| `bapteme_avant_naissance` | baptême (CHR/BAPM) avant naissance | erreur |
| `inhumation_avant_deces` | inhumation avant décès | erreur |
| `deces_avant_naissance` | décès (ou inhumation à défaut) avant naissance (ou baptême à défaut) | erreur |
| `longevite` | âge au décès | alerte > 100, erreur > 110 |
| `age_declare` | âge déclaré dans un acte incompatible avec la naissance | alerte |
| `age_mere` | âge de la mère à la naissance | erreur < 12 ou > 55, alerte > 48 |
| `age_pere` | âge du père à la naissance | erreur < 14 ou > 85, alerte > 70 |
| `naissance_apres_deces_mere` / `_pere` | naissance après le décès du parent | mère 0 j, père 292 j (0,8 an) |
| `mariage_precoce` | âge au mariage (âge négatif compris) | erreur < 12 |
| `mariage_apres_deces` | mariage après le décès | erreur |
| `intervalle_naissances` | deux naissances d'une même mère à moins de 270 j (jumeaux exclus) | alerte |
| `cycle_parente`, `uid_duplique`, `reference_cassee` | intégrité | erreur |
| `type_personnalise_doublon`, `type_personnalise_ambigu` | types personnalisés (mode `gramps`) | info |

### Correspondance

| Genealogiste | Gramps | Écart |
|---|---|---|
| `bapteme_avant_naissance` | 1 | équivalentes ; Gramps : dates complètes seulement |
| `inhumation_avant_deces` | 4 | équivalentes |
| `deces_avant_naissance` | 5 (et en partie 2, 3, 6 : replis du plugin sur baptême et inhumation) | équivalentes |
| `longevite` | 7 | **seuils** : 100/110 contre 90 |
| `age_mere` | 22, 23, 24 (mère) | **seuils** : alerte > 48 = `oldmom` 48 ; minimum 12 contre `yngmom` 17 ; erreur > 55 sans équivalent |
| `age_pere` | 22, 23, 24 (père) | **seuils** : 70 contre `olddad` 65 ; minimum 14 contre `yngdad` 18 |
| `naissance_apres_deces_*` | 25 | **seuil** père : 292 j contre 294 j |
| `mariage_precoce` | 20 et 18 | **seuils** : 12 (erreur) contre `yngmar` 17 (alerte) ; le plugin range le mariage avant la naissance sous `mariage_precoce` |
| `mariage_apres_deces` | 19 | équivalentes |
| `intervalle_naissances`, `age_declare`, intégrité, types personnalisés | aucune | propres au plugin |
| aucune | 8 à 17, 21, 26 à 43 | propres à Gramps (sexe, unions, fratrie, ordre, rôles, dates invalides, isolés, âgés sans décès) |

## Essais réels

Protocole : `docker-compose.test.yml` du dépôt, `COMPOSE_PROJECT_NAME=genealogiste-test-27578`, port 5078,
comptes de test Editor (`--role 3`), Member, Contributor, Owner, Invité. Arbre écrit par le plugin
(`GrampsBackend.propose` puis `apply`, `exiger_source=false`), puis trois retouches par les routes objets comme
l'interface (rôle d'événement « Unknown », personne vivante marquée privée, date de naissance « texte seul » :
le plugin refuse une date non reconnue). 49 personnes, 19 familles, 72 événements, 28 situations. Scripts
d'essai hors du dépôt, qui importent le paquet du plugin (`uv --directory mcp run python …`).

Versions : image épinglée `26.11.0` (API 3.25.1, Gramps 6.0.8, locale `en_US`), puis image plafond `26.11.3`
(API 3.26.0, Gramps 6.0.8) : **résultats identiques** (mêmes constats, mêmes tableaux, mêmes réponses par
rôle). Image plancher `26.5.1` (API 3.13.0) : `POST /api/trees/-/verify` → **404**.

### Résultats globaux

| Mesure | Résultat |
|---|---|
| Réponse (Editor, défauts, sans Celery) | 201, liste de 83 constats, 0,035 s |
| `estimate_age=true` | 201, 85 constats (règles 7 et 11 en plus sur le cas des années seules) |
| `locale=fr` | messages traduits (« Baptême avant la naissance », « Individu déconnecté »… ; une coquille amont : « Les enfants se sont pas dans l'ordre chronologique. ») ; sans `locale` : anglais (locale du serveur) |
| Paramètre inconnu (`inconnu=1`) | 422 |
| Rôle Member / Contributor | 201, mêmes 83 constats |
| Rôle Invité | 403 `{"code":403,"status":"Forbidden"}` |
| `arbre_coherence` (même arbre, lu par le plugin) | 15 alertes, 0,025 s |
| Règles Gramps déclenchées | 1, 4, 5, 7, 8, 10, 11, 16, 17, 18, 19, 20, 21, 22, 23, 25, 26, 28, 29, 32, 37, 38, 41, 43 |

Exemple de constat : `{"message": "Baptism before birth", "name": "CAS01, Baptiste", "object_handle": "…",
"object_id": "I1", "object_type": "Person", "rule_id": 1, "rule_params": [], "severity": "error"}`.

### Comparaison cas par cas (défauts des deux côtés)

Les règles 28 (12 personnes isolées) et 8 (1 cas) sont omises du tableau ; la règle 16 se déclenche sur tous
les couples de l'essai parce que les deux époux portent le patronyme du cas (artefact de l'arbre fictif).

| Cas | Construction | Genealogiste | Gramps |
|---|---|---|---|
| 1 | baptême 5 jours avant la naissance | `bapteme_avant_naissance` (erreur) | 1 (erreur), 43, 32 |
| 2 | inhumation avant le décès | `inhumation_avant_deces` | 4, 43 |
| 3 | décès avant la naissance | `deces_avant_naissance` | 5, 43 |
| 4 | 95 ans, dates complètes | — | 7 |
| 5 | 105 ans, dates complètes | `longevite` (alerte) | 7, 11 |
| 6 | 115 ans, **années seules** | `longevite` (erreur) | — (7 et 11 avec `estimate_age`) |
| 7 | mère de 15 ans | — | 23 |
| 7 bis | mère de 11 ans | `age_mere` (**erreur**) | 23 (**alerte**) |
| 8 | mère de 50 ans | `age_mere` (alerte) | 22 |
| 9 | père de 67 ans | — | 22 |
| 9 bis | père de 75 ans | `age_pere` (alerte) | 22 |
| 10 | naissance 293 jours après le décès du père | `naissance_apres_deces_pere` (erreur) | — (seuil 294 j) |
| 11 | naissance après le décès de la mère | `naissance_apres_deces_mere` | 25 |
| 12 | mariage à 15 ans | — | 20 |
| 12 bis | mariage à 10 ans | `mariage_precoce` (erreur) | 20 (alerte) |
| 13 | mariage après le décès de l'époux | `mariage_apres_deces` | 19 |
| 14 | mariage avant la naissance de l'époux | `mariage_precoce` (« moins de 12 ans ») | 18, 17 |
| 15 | deux naissances à 200 jours, même mère | `intervalle_naissances` | — |
| 16 | âge déclaré 40 ans au décès d'un sexagénaire | `age_declare` | — |
| 17 | 35 ans d'écart entre époux, mariage à 56 ans | — | 17, 21 |
| 18 | inhumation 20 jours après le décès | — | 37 |
| 19 | enfants hors ordre, 26 ans d'écart | — | 38, 26 |
| 20 | événement de rôle « Unknown », sexe inconnu | — | 41, 8 |
| 24 | quatre unions | — | 10 |
| 26 | date de naissance « texte seul » | — (le plugin refuse d'écrire une telle date) | 29 |
| tous | né il y a plus de 90 ans sans décès | — | 32 (36 constats sur 83) |

Bilan sur les 28 situations (cas 1 à 26 sauf 21, et trois « bis ») : 11 vues des deux côtés ; 4 seulement
par Genealogiste (années seules, posthume à 293 jours, intervalle de naissances, âge déclaré) ; 12 seulement
par Gramps, dont 2 par les seules règles 32 et 16 ; la personne vivante isolée (cas 23) par la seule règle 28.
Répartition des 83 constats : règle 32 : 36, règle 28 : 12, règle 16 : 6, toutes les autres : 29. Les gravités
divergent quand les deux voient le même fait (mère de 11 ans, mariage à 10 ans : erreur contre alerte).

Options de Gramps réglées sur les seuils d'**erreur** du plugin (`oldage=110, oldmom=55, olddad=85, yngmom=12,
yngdad=14, yngmar=12`, et `hwdif`, `cspace`, `cbspan`, `wedder` neutralisés) : 72 constats ; disparaissent les
règles 7 (cas 4 et 5), 22 (cas 8, 9, 9 bis), 23 (cas 7), 20 (cas 12), 17, 26 et 10 ; restent 23 (cas 7 bis),
toutes les règles sans option et la règle 32 (même seuil `oldage`, personnes nées avant 1916).

### Personnes privées et vivantes

La vérification ouvre la base avec `view_private=True` : la personne vivante marquée privée (cas 23) figure
dans le résultat, nom compris (`"name": "CAS23, Vivant"`, règle 28), pour un compte Member comme pour un
Editor. Aucune donnée ne sort de l'instance : l'appel va du backend du plugin à son propre serveur Gramps Web,
comme toute lecture. La règle 32 (« âgé sans décès ») signale en revanche des personnes que Genealogiste
considère comme décédées par présomption : elle ne dit rien de la protection des vivants.

## Conception proposée

### Pistes comparées

| | A. Plugin seul (actuel) | B. Native seule | C. Plugin + native en complément |
|---|---|---|---|
| Alertes sur une proposition avant écriture | oui | **non** : la vérification lit la base écrite | oui (plugin) |
| Dates approchées, années seules, calendriers | intervalles | ignorées (ou point estimé) | plugin |
| Règles de Gramps (ordre, rôles, sexe, unions, fratrie) | non | oui | oui |
| Mêmes verdicts que Gramps Desktop et Web | non | oui | oui pour la part Gramps |
| Backend fichier | oui | non | plugin seul (inchangé) |
| Coût | local | un appel, 0,035 s pour 49 personnes | un appel de plus en mode `gramps` |

**Recommandation : piste C**, limitée à `arbre_coherence` sur tout l'arbre (et filtrée pour `arbre_coherence(id)`)
en mode `gramps`. `nouvelles_alertes_coherence` reste calculé par le plugin seul : la vérification native ne
peut pas juger un état non encore écrit.

### Fusion et dédoublonnage

- Origine sur chaque alerte : `origine: "genealogiste" | "gramps"` ; pour Gramps, garder `rule_id`,
  `object_type`, `object_id`, `severity`, `rule_params`.
- Message : appeler avec `locale=en` (stable, non éprouvé avec cette valeur explicite) et afficher un libellé
  français tenu par le plugin, indexé par `rule_id` ; ou `locale=fr` (traduction amont, coquille comprise).
- Clé de rapprochement `(thème, ancrage)` pour les seules règles équivalentes : thèmes `bapteme_naissance` (1),
  `inhumation_deces` (4), `deces_naissance` (5), `longevite` (7), `age_mere` / `age_pere` (22, 23, 24),
  `deces_parent` (25), `mariage_age` (18, 20), `mariage_apres_deces` (19). Ancrage : l'identifiant de la
  personne pour une règle de personne ; celui de la **famille** pour les règles de famille, ce qui impose
  d'ajouter `famille` aux alertes parentales et matrimoniales du plugin (aujourd'hui rattachées à l'enfant ou au
  conjoint seulement). Le parent visé par 22 à 25 n'est donné que par le message (« Old father » / « Old
  mother ») : d'où la locale fixe.
- Alerte vue des deux côtés : une seule ligne, `origine: ["genealogiste", "gramps"]`, gravité la plus forte,
  seuils des deux côtés cités. Les autres alertes restent séparées.
- Bruit : règles 32 (36 constats sur 83 ici, toute personne née il y a plus de 90 ans sans décès connu), 28 et
  16 sont attendues massivement sur un arbre généalogique. Proposition : les résumer par un compte (avec les
  identifiants à la demande) plutôt que de les lister.

### Seuils

Ne pas remplacer les seuils du plugin par ceux de Gramps : les premiers séparent l'impossible (erreur) du rare
(alerte) sur des intervalles de dates ; ceux de Gramps signalent l'inhabituel sur des dates complètes. Pour que
la vérification de Gramps donne les mêmes verdicts en Web et en Desktop, il suffit de lui passer **les mêmes
options** : un réglage du plugin (par exemple `GENEALOGISTE_VERIFICATION_GRAMPS="oldage=90,yngmom=17"`, défauts
de Gramps si absent), transmis tel quel en query string et validé localement contre la liste des 16 options
utiles (l'API répond 422 à une option inconnue ; `lngwdw` sans effet). `estimate_age` : faux par défaut, le
plugin couvrant déjà les dates imprécises par intervalles ; vrai ajoute des constats sur des points estimés.
Un seul alignement suggéré : la marge du père posthume, 292 jours (plugin) contre 294 (Gramps), à trancher.

### Dégradation

| Situation | Comportement proposé |
|---|---|
| API < 3.17.0 (`FONCTIONS_API["verification"]`) | plugin seul, mention « vérification de Gramps indisponible (API x.y.z) » ; constaté : 404 sur 3.13.0 |
| Rôle Invité (403) | plugin seul, mention du rôle insuffisant |
| Réponse 202 (Celery) | suivre `GET /api/tasks/<id>` comme `GrampsClient._wait` ; délai borné ; sinon plugin seul |
| 409 `task_locked` | non applicable d'après le code (aucune clé de verrou sur `verify_database`) ; à traiter comme indisponibilité si l'amont change |
| 5xx, délai | plugin seul, mention |

### Backend fichier et backend Desktop

Backend fichier : inchangé (plugin seul). Backend Desktop futur : l'outil `verify.py` de Gramps n'est pas
utilisable sans PyGObject et GTK (imports l. 53-55). `verify_lib.py` n'utilise que `gramps.gen` ; `gramps.gen`
importe `GLib` (`gen/const.py`) : un module `gi` factice suffit, comme le fait déjà
`scripts/sonde_gramps_desktop.py` (`preparer_gi`). Constaté pendant l'étude #278 : la bibliothèque `gramps==6.0.8`
s'importe, ouvre une base SQLite et exécute des requêtes de `gramps.gen` avec ce module factice. **Non éprouvé** :
`run_verify` lui-même hors de Gramps Web. Licence : `verify_lib.py` est GPL v2 ou ultérieure, compatible avec la
GPL v3 ou ultérieure du plugin ; le reprendre (copie datée) ou dépendre de `gramps-webapi` (AGPL v3) est à
décider.

## Risques

- Écart de verdict durable entre deux moteurs : l'utilisateur voit « Gramps : alerte » et « Genealogiste :
  rien » pour un même fait ; l'origine et les seuils affichés doivent l'expliquer.
- Volume : sans résumé des règles 32, 28 et 16, la sortie d'`arbre_coherence` est dominée par du bruit.
- Couplage à la langue : un ancrage par message anglais casse si l'amont change ses libellés (les règles 22 à
  25 n'ont pas d'autre indice) ; prévoir un repli sur `rule_id` seul.
- Grande base : coût non mesuré au-delà de 49 personnes ; requête synchrone sans Celery.

## Questions ouvertes pour le mainteneur

1. Piste C validée, et limitée à `arbre_coherence` sur tout l'arbre (pas `nouvelles_alertes_coherence`) ?
2. Règles 32, 28, 16 : résumées par un compte, masquées par défaut ou listées ?
3. Options de Gramps : défauts amont, ou valeurs proches du plugin ? Réglage par variable d'environnement ?
4. Marge du père posthume : garder 292 jours ou passer à 294 comme Gramps ?
5. Messages : libellés français tenus par le plugin (`locale=en`) ou traduction amont (`locale=fr`) ?
6. Backend Desktop : reprendre `verify_lib.py` (GPL v2+) ou dépendre de `gramps-webapi` ?

## Découpage proposé (issues à créer après accord)

1. `feat(gramps)` : client `verifier(options, locale)` (201 synchrone, 202 suivi de tâche, 403, 404, 422),
   capacité `verification` lue au diagnostic, tests sur le faux serveur (`gramps_fake.py`) et test live
   (`make test-gramps`).
2. `feat(coherence)` : champ `famille` sur les alertes parentales et matrimoniales, table de correspondance
   `rule_id` ↔ thème, fusion et dédoublonnage, champ `origine`, libellés français ; `arbre_coherence` en mode
   `gramps`, résumé des règles bruyantes.
3. `feat(config)` : options de la vérification de Gramps (validation locale, documentation `docs/gramps-web.md`).
4. Plus tard, avec le backend Desktop : même vérification par la bibliothèque.

## Ce qui est exécuté, ce qui est lu

- Exécuté : tous les résultats des sections « Essais réels » (API 3.25.1 et 3.26.0 ; 404 sur 3.13.0) ; la
  comparaison automatique des 43 règles Desktop / Web.
- Lu seulement : réponse 202 et suivi de tâche avec Celery ; absence de verrou ; équivalence ligne à ligne du
  port ; `run_verify` hors de Gramps Web ; coût sur une grande base ; `locale=en` explicite.
