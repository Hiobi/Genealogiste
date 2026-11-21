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
| `GENEALOGISTE_GRAMPS_TACHES` | `false` (défaut) : aucune source n'est lue ni écrite comme tâche, comportement inchangé ; `true` : tâches de la vue Tâches (source + note étiquetées `ToDo`) lues et écrites par `ajouter_tache` / `modifier_tache`, correspondance avec les enquêtes et les lacunes ([#263](#tâches-263)). Jamais automatique |
| `GENEALOGISTE_GRAMPS_PRIVE_VIVANTS` | `off` (défaut) : rien d'ajouté aux propositions, comportement inchangé ; `propose` : une proposition qui touche une personne présumée vivante ajoute à son diff la pose du privé de cette personne et de ses données propres. `auto` est **refusé** au démarrage : le drapeau privé n'est jamais posé ni retiré sans proposition ([vivants et privé](#vivants-et-privé-264)) |
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
  `gramps_structurer_lieux`, `gramps_dater_lieux`, `gramps_normaliser_types`, `gramps_proteger_vivants`,
  `marqueurs_migrer_proposer`, annulation, `gramps_bascule_proposer`) refusent
  **avant de lire l'arbre et de calculer le diff** un compte sans droit d'écriture, avec le rôle détecté et le
  correctif. `arbre_appliquer` refuse de même avant de consommer le jeton : une promotion du compte permet de
  réessayer avec la même proposition. Les droits sont ceux du jeton d'accès (le rôle n'y figure pas : seulement
  la liste `permissions`) ; s'ils manquent, le jeton est renouvelé (au plus toutes les 5 secondes, car
  `/token/` et `/token/refresh/` sont limités à une requête par seconde) puis `GET /api/users/-/` donne le rôle.
- **Fiche du chercheur** (#282) : son écriture exige le rôle **Owner** (`EditTree`), au-dessus d'Editor : `gramps_reglages(chercheur=…)` refuse un compte Editor avant tout calcul, avec la procédure manuelle. Les signets n'exigent qu'Editor (`EditObject`).
- **Écriture refusée par le serveur** : un HTTP 403 est converti en « droits insuffisants : rôle Editor requis »,
  un HTTP 422 `message: Unknown field` (API < 3.13.0) en « mettre à jour Gramps Web (API 3.13.0 au moins) ».
  Forme réelle d'un 403 constatée sur les trois images de la matrice, avec des comptes *Member* et
  *Contributor* : `{"code":403,"status":"Forbidden"}` (`application/json`, format flask-smorest, sans clé
  `error.message`).

`diagnostic` (réseau activé et `GENEALOGISTE_GRAMPS_URL` renseigné) ajoute à la joignabilité (`gramps_web`) des
contrôles, chacun indépendant : si `/api/metadata/` ou `/api/users/-/` échoue, le contrôle correspondant passe en
`attention` avec le motif et les autres continuent. Aucun identifiant, jeton ni nom de personne n'y figure.

| Contrôle | Contenu | États |
|---|---|---|
| `gramps_version` | version de l'API et de Gramps (`GET /api/metadata/`), plage testée, fonctions optionnelles disponibles ou absentes d'après `FONCTIONS_API` | `ok` dans la plage ; API plus ancienne que 3.13.0 : `erreur` en mode `gramps`, `attention` sinon ; plus récente ou illisible : `attention` |
| `gramps_role` | rôle du compte (`GET /api/users/-/`) | Editor : `ok` ; sous Editor : `erreur` en mode `gramps`, `attention` sinon ; Owner ou Admin : `attention` (« préférer Editor ») |
| `gramps_reglages` | file de tâches (`server.task_queue`), multi-arbres (`server.multi_tree`), inscription libre | `ok` ; inscription libre ouverte : `attention`. L'inscription libre n'est lisible que depuis l'API 3.26.0 (`GET /api/register/config/`) : avant, « non vérifiable sur cette version ». `/api/config/` est réservé aux Admin : jamais appelé |
| `gramps_personne_reference` | racine Sosa (`GENEALOGISTE_SOSA_RACINE`) comparée à la personne de référence de Gramps (`default_person` de `GET /api/metadata/`, traduite en `gramps_id` par `GET /api/people/<handle>?keys=gramps_id`, puis `GET /api/people/?gramps_id=…&keys=gramps_id` pour la racine ; aucun chargement de l'arbre) | même personne : `ok` ; différentes : `attention` avec les deux `gramps_id` ; Gramps sans personne de référence (ou référence supprimée) : `attention` ; racine introuvable dans l'arbre : `erreur` en mode `gramps`, `attention` sinon ; racine non définie : `ok` (information, avec une `suggestion` si Gramps a une référence). Jamais de nom de personne ; panne de lecture : `attention` avec le motif, le diagnostic continue |
| `gramps_chercheur` | fiche du chercheur de la base (`researcher` de `GET /api/metadata/`, déjà lu : aucune requête de plus) | toujours `ok` : « renseignée » ou « vide » et `modifiable` (droit `EditTree`, rôle Owner) ; **jamais le contenu** (nom, adresse, courriel), ni le nombre ou le nom des champs |

Le jeton d'accès Gramps Web dure 15 minutes ; sa revendication `exp` fixe le moment du renouvellement (30 secondes
avant l'échéance), sans délai codé en dur. Le jeton renouvelé garde l'arbre et les droits.

Le mode direct suppose une instance Gramps Web **privée** : les personnes vivantes y sont écrites en clair.
Elles restent masquées par défaut dans les exports publics (`arbre_exporter`). Pour une instance ouverte à des
comptes Invité ou à l'inscription libre : `gramps_proteger_vivants` et les contrôles `gramps_vivants`,
`gramps_prive_a_retirer` et `gramps_regle_vivants` de `diagnostic(vivants=true)` ([vivants et privé](#vivants-et-privé-264)).

## Vivants et privé (#264)

Gramps Web **ne masque pas les vivants** : aucune lecture de l'API ne filtre une personne parce qu'elle est
vivante (aucun `LivingProxyDb` dans gramps-web-api ; seul l'export propose un filtre `living`). Le seul rempart
est le drapeau **privé** (`private`), et seulement contre un compte sans le droit `ViewPrivate`, c'est-à-dire le
rôle **Invité** (Guest, 0) : *Member* (1) et au-dessus voient tout le privé (`auth/const.py`). Genealogiste ne pose
ni ne retire jamais ce drapeau sans proposition : diff, accord explicite, `arbre_appliquer`, transaction
journalisée et annulable par `arbre_annuler_modification`.

### Ce que masque le drapeau privé (relevé amont)

Sources lues : gramps-web-api `v3.26.0` (`5b3f890`), `v3.25.1` (`77263b8`), `v3.13.0` ; Gramps `maintenance/gramps60`
(`gramps/gen/proxy/private.py`). Depuis l'API **3.25.0** (commit `4345fef`, « Replace the private proxy with
RestrictedDb », #1107), un Invité lit la base à travers `RestrictedDb` (`api/access/db.py`, `api/access/sanitize.py`) ;
avant (3.13.0), à travers `PrivateProxyDb` de Gramps. Les deux font la même chose sur les objets :

- un **objet principal privé** (personne, famille, événement, citation, source, média, note) est introuvable :
  listes, lecture par handle ou par `gramps_id`, rétroliens, recherche, export, `/api/living/<handle>` ;
- dans un objet visible, les **références vers un objet invisible** sont retirées (`father_handle` /
  `mother_handle` vidés, enfant retiré de `child_ref_list`, références d'événement, de média, de citation, de
  note retirées ; une citation dont la source est privée est masquée) et les **sous-objets privés** (nom,
  attribut, référence, adresse…) supprimés ; un nom principal privé devient « Private » ;
- en revanche un objet principal **non privé reste visible même si tout ce qui le référence est privé** :
  l'événement de naissance d'une personne privée, sa note, sa citation, son image restent listés (date, lieu,
  texte, fichier). Rendre privée la seule personne ne suffit donc pas.

### Périmètre du marquage

Pour une personne présumée vivante (règle du plugin, `arbre_vivant`) :

| Objet | Marqué privé quand… | Sinon |
|---|---|---|
| la personne | toujours (ses noms, attributs, références, adresses suivent : la personne est masquée en entier) | — |
| famille | tous ses conjoints sont masqués (enfant décédé visible : sa filiation est masquée, listée dans `references_masquees`) | conjoint non masqué (décédé) : famille et événements familiaux **laissés visibles**, listés dans `partages` ; le vivant n'y figure plus (référence retirée par Gramps) |
| événement | tous ses « propriétaires » (rôle Principal ou Famille) sont masqués ; un témoin ou parrain resté visible perd sa participation (listée) | partagé avec un propriétaire visible : laissé, listé |
| citation, source, média, note | **tous** les objets qui les référencent sont masqués | partagé avec un objet visible : laissé, listé avec ses référents |
| note générée (`Genealogiste:auto`) | elle nomme la personne et reste visible ailleurs (ex. « Filiation de … » portée par la famille d'un parent décédé, constaté sur Gramps Web réel) : elle ne parle que d'elle | — |
| média d'un billet ou d'une tâche privés | son seul référent est ce billet ou cette tâche (outil sur tout l'arbre) | lié ailleurs : avertissement (voir [Blog](#blog-261)) |

Jamais modifiés : lieux, dépôts, étiquettes, notes et textes saisis par l'utilisateur sur un objet resté visible.
Un texte resté visible qui nomme un vivant (note d'un défunt, page de citation, description, attribut
`Genealogiste-Association`) est **listé** dans `residus`, jamais réécrit.

### Outil, réglage, opération

- `gramps_proteger_vivants(personnes, limite, retraits)` : bilan (personnes présumées vivantes, vivants non
  privés, objets à marquer par classe, `partages`, `references_masquees`, `residus`, `non_masquable`), puis une
  transaction ordinaire (`POST /api/transactions/`, en tâche de fond au-delà de 200 objets) : seul `private`
  change. `limite` (100 par défaut) borne le nombre de personnes par lot, `reste_apres_ce_lot` dit s'il faut
  relancer. Idempotent : rien à faire, pas de jeton.
- `GENEALOGISTE_GRAMPS_PRIVE_VIVANTS` : `off` (défaut, comportement inchangé : aucune ligne ajoutée au diff) ou
  `propose` : toute proposition qui touche une personne présumée vivante (personne modifiée, membre d'une famille
  modifiée) ajoute à son propre diff la pose du privé de cette personne et de ses données propres, ligne par ligne
  (`transaction_gramps.prive_vivants`, bilan `prive_vivants`). **`auto` est refusé au démarrage** : il poserait le
  drapeau sans proposition, contraire à la règle du plugin.
- `marquer_vivant` avec `"prive": true` : même pose pour cette personne, quel que soit le réglage ; refusée si la
  personne n'est pas présumée vivante ; sans `vivant`, le statut forcé est inchangé. `prive: false` est refusé : le
  retrait passe par l'outil.
- La **modification en lot** de Gramps Web (`POST /api/objects/edit-by-handle/`, `set_private`) n'est pas utilisée :
  absente avant l'API 3.26.0 et hors de `/api/transactions/`, son annulation n'est pas établie (même décision que
  pour les étiquettes, #262).

### Trace et retrait au décès

Le journal local `gramps-transactions.jsonl` enregistre, pour chaque transaction acceptée, les objets dont le
plugin a posé le privé « parce que vivant » (`protection` : classe, handle, `gramps_id`, personnes motivantes) et
ceux dont il l'a retiré (`retrait_protection`). **Aucun attribut n'est écrit dans Gramps** (une note n'a pas
d'attribut : un marqueur dans Gramps ne couvrirait pas tout le périmètre). Quand toutes les personnes motivantes
d'un objet ne sont plus présumées vivantes (décès saisi, âge dépassé), `arbre_coherence` (code
`prive_vivant_a_retirer`) et `diagnostic(vivants=true)` (`gramps_prive_a_retirer`) le signalent, et `gramps_proteger_vivants`
propose le retrait, jamais automatique. Seul ce que le plugin a posé est retiré : un privé voulu par l'utilisateur
n'est jamais touché ; un objet qui masque encore un autre vivant reste privé ; une transaction annulée ne compte
plus. Sans ce journal (répertoire de données perdu, autre poste), rien n'est retiré : retrait à la main dans
Gramps Web.

Conséquence à connaître : comme toute note privée, une note rendue privée sort du modèle de Genealogiste (fiches,
notes de recherche, exports ne la lisent plus) ; elle reste intacte dans Gramps et lisible des rôles Membre et
plus, et redevient lue après le retrait. En mode `off`, une modification ultérieure d'un vivant protégé (nouvel
événement, nouvelle note) crée des objets publics : relancer `gramps_proteger_vivants`, ou utiliser `propose`.

### Ce qu'un Invité voit encore (constaté)

Banc réel `test_vivants_prives_invisibles_pour_un_invite` (personnes fictives, conteneurs jetables), compte
`sosa-invite` de rôle 0, après protection de tout l'arbre :

| Voie | 3.13.0 (plancher) | 3.25.1 (épinglée) | 3.26.0 (plafond) |
|---|---|---|---|
| `GET /api/people/`, `/api/<objets>/` | vivants et données propres absents | idem | idem |
| `GET /api/people/<handle>` | `200 {}` (objet vide) | 404 | 404 |
| `GET /api/people/?gramps_id=…` | 404 | 404 | 404 |
| `GET /api/people/<handle>/timeline` | 500 (page d'erreur, aucune donnée) | 404 | 404 |
| `GET /api/living/<handle>`, `/dates` | 404 | 404 | 404 |
| média : objet / fichier / vignette | `200 {}` / 500 / 500 | 404 / 404 / 404 | 404 / 404 / 404 |
| famille partagée avec un défunt (`extend`, `profile`, `backlinks`) | défunt seul, sans conjoint ni enfant vivants | idem | idem |
| `GET /api/search/?query=<nom du vivant>` | la famille et le mariage partagés sont **trouvés** (nom non renvoyé) ; la note saisie qui le nomme | seule la note saisie (résidu) | idem |
| `/api/metadata/` `object_counts` | compte sans les objets privés | idem | idem |
| export `GET /api/exporters/ged/file` | aucun vivant (hors résidu) | idem | idem |

Restent donc visibles, et listés par la proposition : une famille partagée avec un conjoint décédé (l'existence
d'une union), les textes saisis qui nomment le vivant (`residus`), les types personnalisés (collectés sur tous les
objets, fuite connue de Gramps Web), et, **avant l'API 3.25.0**, le résultat de recherche d'une famille ou d'un
événement partagés par le nom du vivant (index `sifts` remplacé en 3.25.0, commit `0f2a99d`) : mettre à jour
Gramps Web. Rendu dans le navigateur non automatisé : implémenté, non éprouvé visuellement.

### Deux règles « vivant » : alignement

- **Plugin** (`privacy.is_living`) : présumé vivant tant qu'une naissance il y a moins de **100 ans** reste
  possible (borne haute), sauf décès non réfuté ou statut forcé (`Genealogiste-Vivant` Y/N, `marquer_vivant`).
- **Gramps** (`gramps.gen.utils.alive.probably_alive`) : `GET /api/living/<handle>` → `{"living": bool}` et
  `GET /api/living/<handle>/dates` → `{birth, death, explain, other}` (`api/__init__.py:765-771`,
  `resources/living.py`). Il n'existe **pas** de route `/api/people/<handle>/alive` (seules des docstrings la
  citent ; le commentaire de l'issue #264 est à corriger). Paramètres facultatifs `max_age_probably_alive`,
  `average_generation_gap`, `max_sibling_age_difference` ; sans eux, réglages de Gramps `behavior.max-age-prob-alive`
  (**110**), `avg-generation-gap` (20), `max-sib-age-diff` (20). Gramps ignore le statut forcé du plugin, lit un
  décès réfuté, raisonne sur les proches ; une personne sans aucune date est vivante pour les deux.
- **Comparaison** (`diagnostic`, contrôle `gramps_regle_vivants`) : pas de portage de l'algorithme de Gramps (récursif
  sur ascendants, descendants, fratrie et conjoints : un portage infidèle mentirait). Échantillon ciblé sur la zone
  d'incertitude, par priorité : statut forcé ou décès réfuté ; sans décès avec une naissance au plus tard estimée
  il y a 85 à 125 ans ; sans aucune date. Plafond de **30 requêtes** par diagnostic, pause de 0,1 s entre deux ;
  une divergence est réinterrogée avec `max_age_probably_alive=100` : « seuil » si Gramps rejoint alors le plugin,
  « méthode » sinon. Sortie : comptes, `gramps_id` des divergences, jamais de nom. Constaté sur 3.25.1 : une
  personne née il y a 105 ans sans décès (« seuil ») et une personne forcée décédée née en 1970 (« méthode »).
- **Aligner** : les réglages `behavior.*` ne sont **pas** modifiables par l'API (`/api/config/` n'accepte que les
  clés de messagerie et d'URL, `DB_CONFIG_ALLOWED_KEYS`, `const.py:61-69`, et seulement pour un Admin). Gramps Desktop :
  Préférences > Limites, « Espérance de vie maximale » = 100. Serveur Gramps Web : `gramps.ini` de l'utilisateur du
  processus (section `[behavior]`, `max-age-prob-alive=100`), non vérifié ici. Appel ponctuel :
  `GET /api/living/<handle>?max_age_probably_alive=100`. La règle du plugin reste 100 ans (`privacy.LIVING_YEARS`,
  non réglable) ; un seuil réglable serait une option à décider (elle changerait aussi la garde réseau, les exports
  et les notes), non ajoutée.

### Diagnostic

Le contrôle des vivants est **explicite** : `diagnostic(vivants=true)` (réseau activé, mode `gramps`). Il lit
l'arbre complet et envoie au plus 30 requêtes `/api/living/`. Par défaut (`vivants=false`), le diagnostic reste
léger : ni lecture de l'arbre ni requête `/api/living/`, une seule ligne `gramps_vivants` « non lancé » (`ok`) qui
dit comment le lancer et ce qu'il coûte. Exception gratuite : inscription libre ouverte (déjà lue par
`gramps_reglages`) et `GENEALOGISTE_GRAMPS_PRIVE_VIVANTS=off` : la ligne passe en `attention` et recommande
`diagnostic(vivants=true)` ou `gramps_proteger_vivants`, toujours sans lire l'arbre. Avec `vivants=true` :

| Contrôle | Contenu | États |
|---|---|---|
| `gramps_vivants` | personnes présumées vivantes et non privées (compte) ; exposition : comptes Invité (`GET /api/users/`, rôle Owner seulement ; sinon « non vérifiable ») et inscription libre (API ≥ 3.26.0) | aucun vivant non privé, ou exposition vérifiée nulle : `ok` ; sinon `attention` (exposée ou non vérifiable), remède `gramps_proteger_vivants` |
| `gramps_prive_a_retirer` | personnes motivant un privé posé par le plugin et qui ne sont plus présumées vivantes (`gramps_id`, nombre d'objets) | présent seulement s'il y en a : `attention` |
| `gramps_regle_vivants` | divergences plugin / Gramps sur l'échantillon borné ci-dessus (comptes, `gramps_id`, cause) | `ok` sans divergence ; `attention` sinon |

Ces contrôles n'existent qu'en mode `gramps`.

## Personne de référence et racine Sosa (#274)

Gramps (Desktop et Web) a une **personne de référence** (`default_person`) : point de départ de l'interface, des
rapports natifs (dont la numérotation Ahnentafel/Sosa) et du calcul des relations. Genealogiste a sa propre racine,
`GENEALOGISTE_SOSA_RACINE`, qui fixe la personne n° 1 de la numérotation Sosa des notes. Si les deux divergent, les
numéros des notes et ceux des rapports Gramps ne concordent plus, sans avertissement. Trois outils les rapprochent :

- **`diagnostic`** : le contrôle `gramps_personne_reference` (tableau ci-dessus) signale l'écart, avec les deux
  identifiants, et la procédure à suivre.
- **Export** (`arbre_exporter`, formats `gramps` et `gpkg`) : la racine Sosa devient `<people home="…">` du fichier,
  quand elle est configurée **et** présente dans l'export. Non configurée : rien n'est écrit (rien n'est inventé).
  Racine masquée par l'export public (personne vivante ou privée, `masquer_vivants`) : aucun `home`, ni dans le
  fichier ni ailleurs ; le résultat dit seulement `personne_reference.ecrite: null` et le motif.
- **Import** (`arbre_importer_gedcom` d'un fichier Gramps) : la personne de référence du fichier est rapportée dans
  `import.personne_reference` (`gramps_id`, jamais un nom), avec son état par rapport à la racine Sosa
  (`identique`, `differente`, `racine_non_definie`, ou `a_verifier` en mode `ajouter`, qui renumérote) et, selon le cas, la
  suggestion « Racine Sosa suggérée : I0001 ». **Rien n'est jamais modifié** : ni la configuration, ni le `.env`. L'arbre
  Genealogiste ne conserve pas cette personne (comptée sous `non_repris`, `Métadonnées.personne_reference`).

### Pas d'écriture par l'API : procédure manuelle

**Gramps Web n'offre aucun point d'API pour définir la personne de référence** (lecture seule via
`GET /api/metadata/`). Source : `gramps-web-api` 3.26.0, commit `9cbf933` ; `grep -rn "set_default_person\|default_person"`
dans `gramps_webapi/` ne trouve que la lecture (`resources/metadata.py`) et deux effacements (une transaction ou une
restauration qui supprime la personne de référence appelle `set_default_person_handle(None)`, `api/tasks.py`,
`resources/restore.py`). La « Home person » de l'interface Gramps Web est un réglage **du navigateur** (`localStorage`,
clé `grampsjs_settings_tree`, propre à chaque navigateur et à chaque arbre) : elle n'est ni stockée dans la base ni lisible
par l'API, donc `diagnostic` ne la voit pas. En conséquence, l'opération `definir_personne_reference` envisagée par
l'issue n'est **pas** ajoutée à `arbre_proposer` pour Gramps Web. Le futur backend Gramps Desktop (#270, étude à venir)
pourra la porter, puisqu'il écrira dans la base elle-même (`set_default_person_handle`).

Pour définir la personne de référence de la base :

1. **Gramps Desktop** : ouvrir l'arbre, sélectionner la personne dans la vue « Personnes », puis menu
   **Édition > Définir la personne de référence**. Gramps Web lit ensuite cette valeur si l'arbre lui est transmis
   (export `.gramps` puis import, ou sauvegarde de la base).
2. **Gramps Web, arbre vide** : exporter avec `arbre_exporter` (format `gramps` ou `gpkg`, racine Sosa configurée : le fichier
   porte `<people home>`), puis l'importer dans l'arbre vide (Paramètres > Administration > Importer, rôle Owner :
   `ImportFile`). Gramps applique le `home` **à chaque import qui en porte un, même si l'arbre en a déjà une**
   (`gramps/plugins/importer/importxml.py` : `start_people` mémorise `home`, `parse` appelle ensuite
   `set_default_person_handle` sans condition ; maintenance/gramps52 `14c01e5` l. 1074-1076 et 1662, gramps60 `32aa296` l. 1076-1078 et 1664, gramps61 `e9c09a4`
   l. 1076-1078 et 1664 ; constaté sur Gramps Web jetable, voir ci-dessous). Un second import dans un arbre déjà rempli
   duplique les données : réserver cette voie aux arbres vides.
3. **Réglage de l'interface Gramps Web** : il ne concerne que le navigateur où il est fait ; il n'aligne pas les
   rapports ni `default_person`.

Après l'une de ces voies, relancer `diagnostic` : `gramps_personne_reference` repasse à `ok` si la référence est la
racine Sosa. Pour l'inverse (aligner la racine Sosa sur Gramps), régler `GENEALOGISTE_SOSA_RACINE` à la main avec la
valeur de `suggestion`.

## Groupes de noms (#276)

Gramps classe les personnes par **nom de groupe** dans ses vues par nom, ses index et ses rapports : `Dupond` peut
être rangé sous `DUPONT`. **Un groupe de noms n'est pas une fusion de personnes** : aucune personne, aucun nom,
aucun événement n'est touché ; seul change le classement affiché. Deux niveaux existent dans Gramps :

- le **regroupement global** de la base, table `name_group` (patronyme → nom de groupe) ; `get_name_group_mapping`
  rend le groupe, ou le patronyme lui-même s'il n'est pas regroupé. Les clés sont **sensibles à la casse**
  (`Dupont` et `DUPONT` sont deux clés). C'est lui que lit `GET /api/name-groups/` ;
- `group_as` du **nom d'une personne** (champ `group` du nom dans le XML) : propre à ce nom, il **prime** sur le
  regroupement global (`gramps.gen.display.name.name_grouping_name` : « si `group_as` est défini, l'utiliser ; sinon
  le regroupement du patronyme principal ; sinon le patronyme »). Le champ du nom n'est pas un regroupement global.

### Routes de l'API (relevé amont)

Sources : `gramps-web-api` tag `v3.26.0` (`5b3f890`) et `main` `9cbf933` ; `gramps_webapi/api/resources/name_groups.py`,
`api/__init__.py` l. 689-705, `auth/const.py` ; `gramps` `maintenance/gramps52` (`14c01e5`), `gramps60` (`32aa296`),
`gramps61` (`e9c09a4`) : `plugins/db/dbapi/dbapi.py`, `plugins/export/exportxml.py`, `plugins/importer/importxml.py`.

| Route | Droit | Effet |
|---|---|---|
| `GET /api/name-groups/` | tout jeton valide | `[{surname, group}]` : seuls les patronymes **regroupés** (`get_name_group_keys`), par ordre de nom |
| `GET /api/name-groups/<surname>` | tout jeton valide | `{surname, group}` : le groupe, ou le patronyme lui-même sans regroupement |
| `POST /api/name-groups/<surname>/<group>` | `EditNameGroup` (rôle **Editor**) | `set_name_group_mapping`, 201 `{surname, group}` ; pas de corps (paramètres dans l'URL) |

Aucune route de suppression ni de modification d'un autre type : constaté sur les trois images de la matrice,
`DELETE` et `PUT` répondent 405, `POST /api/name-groups/<surname>/` sans groupe 404, un `POST` avec le rôle Member 403
(`{"code":403,"status":"Forbidden"}`). La lecture existe
depuis l'API 0.1 (commit `b050663`, 2020-11-07, première étiquette `v0.1`), le droit `EditNameGroup` depuis `v0.6.0`
(`d8f423d`, 2023-03-15) : clés `groupes_noms` et `groupes_noms_ecriture` de `FONCTIONS_API` (tableau des versions
minimales ci-dessous), donc toujours disponibles dans la plage testée (API ≥ 3.13.0). Un patronyme qui contient « / »
ne peut pas être un segment d'URL (convertisseur `string` de Flask) : il ne peut pas être regroupé par cette route.

### Pourquoi Genealogiste n'écrit pas les groupes de noms

Le contrat est : proposition (diff) → accord explicite → application, journalisée, **annulable**. L'écriture d'un
groupe de noms ne peut pas le respecter, constaté dans le code amont **et** sur chaque image de la matrice
(`test_groupes_de_noms_lecture_ecriture_et_irreversibilite_sur_vrai_gramps_web`) :

1. **hors historique** : `set_name_group_mapping` fait son propre `INSERT`/`UPDATE` et `commit` SQL ; la route ne
   passe par aucun `DbTxn`. L'écriture n'entre donc ni dans `GET /api/transactions/history/` (inchangé après un
   `POST`) ni dans le journal d'annulation d'un `POST /api/transactions/` (aucun élément de classe adaptée : un groupe
   de noms n'est pas un objet Gramps) ;
2. **« aucun regroupement » inatteignable** : `set_name_group_mapping(nom, None)` supprime la clé, mais la route exige
   un groupe non vide (le segment vide n'est pas routé : 404). Regrouper un patronyme sous lui-même
   (`POST …/Dupond/Dupond`) laisse la clé **listée** par `GET /api/name-groups/` et écrite dans `<namemaps>` : l'état
   « aucun regroupement » n'est jamais restauré exactement ;
3. **pas de détection de conflit** : aucun `old` comparé (contrairement à `POST /api/transactions/`) ; un
   regroupement changé entre la proposition et l'application ne serait pas vu par le serveur.

Constaté le 2026-11-21 sur `26.5.1` (API 3.13.0), `26.11.0` (3.25.1) et `26.11.3` (3.26.0) : un `POST` répond 201
et la lecture le rend, l'historique (`GET /api/transactions/history/`) est inchangé, `POST …/Dupond/Dupond` laisse
`Dupond` listé, l'import d'un document de regroupements seuls répond 201 sans créer d'objet.

Dans le doute, la voie sûre a été retenue : **lecture, export XML, import rapporté, et une proposition sous forme de
liste à appliquer à la main**. Rien n'est écrit sur Gramps Web par ce lot.

### Ce que fait Genealogiste

- **Lecture** : `GrampsClient.name_groups()` (`GET /api/name-groups/`), mode gramps seulement ; en mode fichier, pas
  de groupes (rien n'est inventé).
- **`gramps_grouper_noms`** (mode gramps, classe **lecture** : aucun jeton, aucune écriture) : propose des groupes
  d'après les **patronymes réellement attestés** (patronyme principal du nom principal de chaque personne ; les
  fiches `patronymes/` des notes sont générées depuis les mêmes patronymes). Critère volontairement étroit :
  `typographie` (casse, accents, espaces, tirets, apostrophes, particule agglutinée : `LE GRAND`, `Legrand` ;
  `Lefèvre`, `Lefevre`) et `transcription` d'un tréma ou ß (`Müller`, `Mueller`, `Strauß`, `Strauss`). **Jamais** de
  rapprochement phonétique, de diphtongue (`Meyer`, `Maier`), de finale (`Schmidt`, `Schmitt`), ni de forme latine :
  ces patronymes proches sont listés en `candidats_non_retenus` (score de `comparer_noms`) pour examen humain. Le
  nom de groupe est le regroupement existant s'il y en a un, sinon la forme la plus portée dans l'arbre (égalité :
  ordre alphabétique, signalée dans `egalite`). Les **conflits** avec les regroupements existants (plusieurs
  groupes pour une même famille d'écritures, ou un groupe étranger à cette famille) sont listés dans `conflits` et
  **jamais tranchés** : rien n'est proposé pour eux. **Idempotent** : une fois les regroupements posés, l'outil
  les rapporte en `deja_en_place` et `a_appliquer` est vide. Résultat : `groupes_proposes` (groupe, patronymes,
  personnes, motif), `deja_en_place`, `conflits`, `a_appliquer` (la route de chaque regroupement),
  `groupes_existants`, `xml_import` et `procedure`. `patronymes=[…]` limite aux familles d'écritures citées.
  Les personnes dont le nom porte son propre `group_as` sont comptées par patronyme (`personnes_group_as_propre`) :
  ce champ prime chez Gramps sur le regroupement global proposé.
- **`arbre_recherche`** (mode gramps) : avec `groupes_noms=True` (défaut), les patronymes regroupés par Gramps sous
  le même groupe que le nom cherché (ou le `group_as` du nom de la personne) sont **ajoutés** aux résultats,
  marqués `via_groupe_noms: true`, listés après les autres (au plus `limite`). **Aucun résultat d'avant n'est
  retiré** ; `groupes_noms=False` rend la recherche d'avant. Sans aucun groupe dans Gramps, ou en mode fichier : aucun
  changement.
- **`recherche_multi`** (mode gramps) : les groupes ne servent **qu'en local**. Quand le nom cherché a des patronymes
  apparentés dans la table de Gramps, la réponse porte `groupe_de_noms` (`apparentes`, `envoyees_aux_sources: false`) :
  rien n'est ajouté à la requête des sources externes (matchID, WikiTree, Wikidata, Gallica) ; chaque variante à
  tenter fait l'objet d'un appel explicite, donc de la garde des personnes vivantes (`_garde`).
- **Export** (`arbre_exporter`, formats `gramps` et `gpkg`) : en mode gramps, les regroupements lus dans Gramps sont
  écrits en `<namemaps>` (`groupes_de_noms` dans le résultat) ; en mode fichier, aucun. **Export public**
  (`masquer_vivants`) : un regroupement n'est écrit que si son patronyme figure dans l'export (une personne non
  masquée le porte) **et** que son groupe n'est pas un patronyme porté seulement par des personnes masquées ; le
  bilan ne nomme jamais un regroupement retiré (`retires_export_public` : un nombre).
- **Import** (fichier Gramps XML ou `.gpkg`) : les `<namemaps>` sont lus et rapportés (`import.regroupements`, aussi
  comptés sous `non_repris`, `Métadonnées.regroupements`), **jamais appliqués** ; l'aller-retour XML → objets → XML
  les conserve (`lecture_xml.comparer_xml`).

### Procédure : poser les regroupements proposés

Après relecture de `a_appliquer`, au choix :

1. **Gramps Web, par patronyme** (rôle Editor) : la route donnée pour chaque regroupement, par exemple
   `curl -X POST -H "Authorization: Bearer <jeton d'accès>" "<url>/api/name-groups/LE%20GRAND/Legrand"`. Le jeton
   s'obtient par `POST /api/token/`. Un patronyme à « / » ne peut pas être posé ainsi (voir ci-dessus).
2. **Import d'un fichier de regroupements** (Gramps Desktop, ou Gramps Web avec le rôle Owner : Paramètres >
   Administration > Importer) : enregistrer `xml_import` dans un fichier `.gramps` et l'importer. Le document ne porte
   que l'en-tête et `<namemaps>` : **aucun objet n'est créé** (vérifié sur Gramps Web et par chaque bibliothèque
   Gramps). Un regroupement **déjà présent** n'est jamais écrasé : Gramps avertit (« Gramps ignored a name
   grouping ») et garde l'ancien.

Défaire un regroupement n'est possible ni par l'API ni par l'import (ni par Genealogiste) : regrouper un patronyme
sous lui-même rétablit l'affichage, pas l'état de la table (la clé reste listée et exportée). Retirer la clé relève
d'un outil de Gramps lui-même, non éprouvé ici : à ne faire qu'en connaissance de cause.

### Forme XML

`<namemaps><map type="group_as" key="<patronyme>" value="<groupe>"/></namemaps>`, dernier élément de `<database>`
(après `<bookmarks>`), identique en Gramps XML 1.7.1 (Gramps 5.2, 6.0, 6.1) et 1.7.2 (6.0, 6.1) : DTD et RNG livrés
avec Gramps 5.2, 6.0 et 6.1 (`data/grampsxml.dtd`, `.rng`) ; `type` ne peut valoir que `group_as`. L'écrivain de Gramps
(`write_namemaps`) n'écrit l'élément que s'il y a des regroupements ; l'importeur (`start_namemap`) pose chaque
regroupement absent, n'écrase pas un regroupement présent et ignore la valeur `None` (fichiers corrompus par un
ancien bogue). Genealogiste écrit les clés triées par patronyme et les valeurs telles que lues.

## Signets, fiche du chercheur et formats de nom (#282)

Trois réglages de la **base** Gramps (partagés par Gramps Desktop et Gramps Web quand c'est la même base), que
Genealogiste lit, exporte et, pour deux d'entre eux, écrit sur proposition. Faits relevés dans le code amont
(`gramps-web-api` tag `v3.26.0`, `5b3f890703537c828009656e7886a2f1e856c060` ; `gramps` 5.2 `14c01e5`, 6.0 `32aa296`,
6.1 `e9c09a4` ; `gramps-web` `v26.5.1`, `v26.11.0` `8df6820`, `v26.11.3` `20c7655`) puis constatés sur les trois images
de la matrice (`test_reglages_*`, `test_chercheur_*`, `test_signets_*`, `test_formats_de_nom_*` de `test_gramps_live.py`).

### Faits amont

| | Fiche du chercheur | Signets | Formats de nom |
|---|---|---|---|
| Lecture | `GET /api/metadata/` (`researcher`) ou `GET /api/metadata/researcher/` ; onze champs chaînes : `name`, `addr`, `street`, `locality`, `city`, `county`, `state`, `country`, `postal`, `phone`, `email` (vides à l'état neuf) | `GET /api/bookmarks/<espace>` (liste ordonnée de handles) et `GET /api/bookmarks/` (les neuf espaces : `people`, `families`, `events`, `places`, `sources`, `citations`, `repositories`, `media`, `notes`) ; autre espace : 404 | `GET /api/name-formats/` → `[{number, name, format, active}]` (formats **personnalisés** de la base ; vide à l'état neuf) |
| Écriture | `PUT /api/metadata/researcher/`, corps JSON : mise à jour **partielle** (seules les clés envoyées), clé inconnue refusée (422), chaîne vide admise | `PUT /api/bookmarks/<espace>/<handle>` (ajoute **en fin de liste** ; 404 si l'objet n'existe pas) et `DELETE …` (404 si le signet n'existe pas) ; corps vide | **aucune** (ni POST, ni PUT, ni DELETE : 404/405) |
| Droit, rôle | `EditTree` : **Owner** (4) au moins ; lecture : tout rôle | `EditObject` : **Editor** (3) ; lecture : tout rôle | lecture : tout rôle |
| API d'apparition | lecture : v0.1 ; écriture : **3.9.0** (`7235b75`, 2026-03-27) | lecture : v0.1 (`a611816`, 2020-11-19) ; écriture : **1.5.0** (`10f8fd6`, 2023-12-18) | lecture : v0.1 (`a611816`) |
| Dans l'historique des transactions ? | **non** : `set_researcher` ne passe par aucun `DbTxn` ; `GET /api/transactions/history/` inchangé | **non** : `bookmarks.append` / `remove`, aucun `DbTxn` ; historique inchangé | sans objet |
| État antérieur lisible et restaurable exactement ? | **oui**, y compris « vide » : `PUT` des onze champs, chaînes vides comprises (constaté : relecture identique à l'état neuf) | **oui**, à l'ordre près : un ajout se défait exactement (`DELETE`) ; un retrait se défait par `PUT`, qui remet le signet **en fin de liste** (aucune route ne réordonne) | sans objet |
| Détection de conflit côté serveur ? | non (aucun `old` comparé) | non | sans objet |
| Persistance | métadonnées de la base, écrites à la fermeture de la base à la fin de la requête (`DbGeneric.close`, `_set_all_metadata` ; `api/util.py` ferme la base ouverte en écriture) ; relues par une requête suivante | idem | `name_formats` de la base |

**Signets : ceux de la base, mais pas ceux de l'interface de Gramps Web.** `GET /api/bookmarks/` rend les signets
de la **base** : ce sont ceux du menu Signets de Gramps Desktop, partagés par tout client de la même base. L'interface
de Gramps Web, elle, **ne les utilise pas** : ses signets sont un réglage du **navigateur**
(`localStorage['bookmarks']`, par arbre ; `gramps-web` `src/api.js`, présent à l'identique dans `v26.5.1`, `v26.11.0` et
`v26.11.3`, ajouté par #335 le 2023-12-27 ; aucun appel à `/api/bookmarks` dans le code de l'interface). Un signet posé
par Genealogiste est donc visible dans Gramps Desktop et pour les clients de l'API, **pas** dans le menu de Gramps Web ;
et ceux de l'interface Web ne sont jamais lus ni écrits ici.

**Fiche du chercheur : usage par Gramps.** L'export GEDCOM de Gramps écrit l'enregistrement `SUBM` (`NAME`, adresse en
`ADDR` structurée, `PHON`, `EMAIL`) et le droit d'auteur de l'en-tête (`COPR`) d'après `db.get_researcher()`
(`exportgedcom.py`, `_header` et `_submitter`) ; l'export Gramps XML écrit `<researcher>` (`exportxml.py`). L'interface de
Gramps Web n'affiche la fiche que dans la page d'informations système, en lecture. À l'import XML, Gramps ne reprend la
fiche du fichier que si la base cible est **vide** (`importxml.py` : `import_researcher = db.get_total() == 0`) ; une base
Gramps Web vide au chargement reçoit sinon la fiche par défaut de la configuration du serveur (`dbloader.py`). Le format
XML ne porte ni `street` ni `county` (`exportxml.py` écrit neuf champs) ; l'export GEDCOM de Gramps recopie `addr` dans
`ADR1` et n'écrit pas `street`.

**Format de nom par défaut de l'arbre : pas dans la base.** `GET /api/name-formats/` ne rend que les formats
personnalisés enregistrés **dans** la base (`db.name_formats`, avec un indicateur `active`). Le format **par défaut**
est la préférence `preferences.name-format` de la **configuration de Gramps** (`gramps.ini` du poste pour Gramps
Desktop ; configuration du processus serveur pour Gramps Web : `dbloader.py` applique `name_displayer.set_default_format`
d'après `config.get("preferences.name-format")`). Il n'est lisible ni par l'API ni par la base. Constat de l'import XML
de Gramps (5.2, 6.0, 6.1) : `active = bool(attrs.get("active", True))`, donc un format écrit `active="0"` est importé
**actif** (la chaîne « 0 » est vraie) ; un numéro déjà pris est remplacé par le premier numéro négatif libre.

### Contrat retenu pour chaque écriture et pourquoi

Règle commune : proposition (diff) → accord explicite → application, journal d'intention, annulation possible, jamais
automatique. Ces écritures sont **hors transaction Gramps** : elles ne figurent pas dans l'historique de Gramps Web
(onglet Révisions) et le serveur ne sait pas les défaire. Elles respectent pourtant le contrat parce que l'état
antérieur est **lisible** et **restaurable exactement** par l'API, et que l'état est **relu** avant l'application :

- **Fiche du chercheur : écriture proposée** (`gramps_reglages(chercheur={…})`). Le diff montre avant et après de
  chaque champ modifié. Les valeurs sont celles que fournit l'utilisateur : rien n'est déduit de l'environnement, de
  git, du système ni d'un export. L'état antérieur (onze champs) est mémorisé dans le jeton et le journal ; l'annulation
  renvoie les onze champs (chaîne vide comprise) et redonne l'état initial **exact**. Rôle Owner exigé : refus avant
  tout calcul pour un compte Editor, avec la procédure manuelle (Gramps Desktop : Édition > Préférences > Chercheur).
- **Signets : écriture proposée** (`gramps_reglages(signets={…})`, et signets d'enquête). Un ajout se défait exactement ;
  un retrait annulé remet le signet **en fin de liste** (ordre non restitué, annoncé dans la proposition d'annulation :
  `ordre_restitue`). Seuls les signets nommés (ou ceux que le plugin a posés pour une enquête) sont touchés.
- **Formats de nom : lecture seule** (aucune route d'écriture).

**Journal d'intention et conflit.** `gramps-transactions.jsonl` reçoit l'`intention` (type `reglage`, état
`avant` et `apres`) avant l'envoi, puis `envoyee` et `terminee` avec la vérification par relecture (`conforme`) ;
`arbre_historique` et `arbre_statut_transaction` les montrent, `recover()` compare l'état de la base à l'état avant et
après après une interruption (`envoyee`, `non_envoyee`, `partielle`). **Conflit** : le serveur n'en détecte pas ; avant
d'appliquer et avant d'annuler, Genealogiste relit l'état et refuse (« Conflit », jeton consommé, rien écrit) s'il n'est
plus celui de la proposition (fiche ou signets modifiés dans Gramps entre-temps). Cette comparaison est faite par le
client en deux requêtes (lecture, puis écriture) : une modification faite par un autre client entre les deux n'est pas
vue (fenêtre de quelques millisecondes, pas de verrou côté serveur). L'annulation est refusée si l'état n'est plus celui
que l'écriture a laissé. **Données personnelles** : le journal des transactions (local, droits privés) garde l'état
avant et après de la fiche, nécessaire à l'annulation, comme il garde déjà les objets des transactions ; ni le diagnostic,
ni le journal de recherche, ni le résumé des propositions en attente ne contiennent une valeur de la fiche.

### Ce que fait Genealogiste

- **`gramps_reglages`** (mode gramps, classe **proposition**) : sans paramètre, **lecture** : fiche renseignée ou vide et
  noms des champs renseignés (**jamais les valeurs**), signets par type d'objet (identifiants Gramps, jamais un nom),
  formats de nom personnalisés (numéro, nom, format, actif), droits du compte et rappel que le format par défaut n'est
  pas lisible. `chercheur={…}` ou `signets={ajouter, retirer}` ou `signets={enquete, action}` : proposition (jeton, diff)
  pour `arbre_appliquer` après accord, annulable par `arbre_annuler_modification`.
- **Exports** (`arbre_exporter`, mode gramps) :
  - *fiche du chercheur* : `SUBM` (`gedcom7`, `gedcom551`) ou `<researcher>` (`gramps`, `gpkg`), écrit seulement dans un
    export **privé** (`masquer_vivants=False`) ou sur demande explicite (`chercheur=True`, avec un avertissement en export
    public) ; `chercheur=False` l'exclut. **Export public par défaut : aucune coordonnée**, sortie identique à celle d'avant
    (octet pour octet en GEDCOM ; en Gramps XML, `<researcher/>` vide) ; fiche vide : rien d'écrit, motif donné. `street` et
    `county` sont absents du Gramps XML (`champs_absents_du_format`) ; en GEDCOM, comme Gramps : `ADDR` (lignes adresse,
    lieu-dit, ville, comté, état, code postal, pays), `ADR1` = `addr`, `ADR2`, `CITY`, `STAE`, `POST`, `CTRY`, `PHON`, `EMAIL`.
    Un soumetteur importé d'un autre fichier cède la place à la fiche. Mode fichier : aucune fiche, rien d'inventé.
    Le banc Gramps Desktop relit le `SUBM` par l'import GEDCOM réel (5.2.4, 6.0.8, 6.1.0-beta2 : `chercheur:ged`) et le
    `<researcher>` par l'import XML (cas `reglages`).
  - *signets* (`<bookmarks>`, gramps et gpkg) : ceux de la base, dans l'ordre, pour les personnes, familles, sources,
    dépôts, médias et notes de l'export (retrouvés par leur identifiant Gramps) ; événements, lieux et citations (dont
    l'identifiant ne se conserve pas à l'export) sont comptés `non_ecrits`. **Export public** : un signet vers une personne
    ou une famille masquée est **retiré** (la personne reste un « Vivant » anonyme, aucun signet ne la désigne), les sources,
    médias et notes privés ne sont plus dans l'export ; les compteurs `signets.retires` ne nomment rien.
  - *formats de nom* (`<name-formats>`) : les formats personnalisés de la base, aussi en export public (aucune donnée de
    personne).
- **Import** (Gramps XML, `.gpkg`) : `import.metadonnees` rapporte `chercheur` (`renseigne`, nombre de `champs`, **jamais le
  contenu**), le nombre de `signets` et de `formats_noms` ; rien n'est écrit dans l'arbre, la configuration ni Gramps Web ;
  l'aller-retour XML → objets → XML conserve fiche, signets et formats (`Métadonnées.*` sous `non_repris`).
- **Diagnostic** : contrôle `gramps_chercheur` : fiche **renseignée** ou **vide**, et `modifiable` (droit `EditTree`) ;
  jamais un nom, une adresse ni un courriel, ni le nombre de champs. Toujours `ok` (une fiche vide n'est pas une anomalie).
- **Signets d'une enquête** : voir [enquetes.md](enquetes.md#signets-de-gramps-282).
- **Jamais vers l'extérieur** : aucun outil réseau (sources externes) ne reçoit ces champs ; `tests/test_gramps_reglages_export.py`
  le vérifie (requêtes sortantes de `recherche_multi`, journal de recherche, et garantie statique : aucun module de `sources/`
  ne mentionne la fiche).

### Option non livrée : afficher les noms selon le format de l'arbre

Fiches et récits gardent leur affichage actuel. Le « format par défaut de l'arbre » n'étant **pas** dans la base (voir
plus haut), il ne peut pas être lu par l'API. L'option serait un réglage **du plugin** (variable d'environnement,
défaut = affichage actuel inchangé octet pour octet) acceptant un format Gramps (`%s, %f`, `%f %S`…) dont il faudrait
porter fidèlement les codes (`%t %f %p %n %l %s %m %y %c %x %o %g %u %a %e`, majuscules et variantes `%F`/`%S`…, texte
littéral, nettoyage des espaces et ponctuations en trop de `gramps/gen/display/name.py`) et les valider contre la
vraie bibliothèque dans le banc Desktop. C'est disproportionné pour ce lot (priorité basse) : à décider. Les formats
personnalisés de la base sont néanmoins lus (`gramps_reglages`) et exportés.

### Procédures manuelles

- **Fiche du chercheur sans compte Owner** : Gramps Desktop, Édition > Préférences > Chercheur (le menu est celui de la
  base ouverte) ; Gramps Web : pas d'écran de modification de la fiche (lecture seule dans les informations système).
- **Formats de nom** : Gramps Desktop, Édition > Préférences > Affichage > Format du nom > Modifier ; un fichier Gramps
  XML qui porte `<name-formats>` les ajoute à l'import (numéros renumérotés si déjà pris, tous importés actifs).
- **Retrouver les signets posés pour une enquête** : `enquete_etat` (`signets_poses`, identifiants Gramps et handles).

### Limites

- Les signets de la base ne sont pas ceux de l'interface de Gramps Web (navigateur) : voir plus haut.
- Écritures hors historique : annulables seulement par Genealogiste, tant que l'état n'a pas changé ; l'ordre des signets
  d'un retrait annulé n'est pas restitué.
- Conflit détecté par le client (relecture), sans verrou serveur.
- Un format de nom ne s'écrit pas : aucune route ; et Gramps importe actif tout format d'un fichier.

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

### Blog (#261)

La page Blog de Gramps Web n'a pas d'objet propre : un billet est une **source portant l'étiquette `Blog`**.
Relevé dans le frontend gramps-web `v26.11.0` (`8df6820`, image épinglée ; identique en `v26.11.3`, `20c7655`,
hors présentation) :

| Billet | Gramps | Code |
|---|---|---|
| liste | `GET /api/sources/?rules={"rules":[{"name":"HasTag","values":["Blog"]}]}&sort=-change&extend=all` (6 par page) ; dernier billet du tableau de bord : même requête, `pagesize=1` | `GrampsjsViewBlog.js:174-190`, `GrampsjsViewRecentBlogPosts.js` |
| étiquette | nom exact `Blog` (casse comprise) ; créée par `POST /api/tags/` si absente | `GrampsjsViewNewBlogPost.js:176-200` |
| ordre, date affichée | `change` de la source (dernière modification), pas une date d'événement | `GrampsjsBlogPostPreview.js:89-95`, `GrampsjsBlogPost.js:104-113` |
| titre, auteur | `title`, `author` de la source | `GrampsjsBlogPost.js:104-106` |
| corps | **première note** (`extended.notes[0]`), relue par `GET /api/notes/?gramps_id=…&formats=html&format_options={"link_format":"/{obj_class}/{gramps_id}"}` ; aperçu de la liste : 250 premiers caractères du texte brut | `GrampsjsViewBlogPost.js:75-88`, `GrampsjsBlogPostPreview.js:101-115` |
| type de note | aucun : l'interface crée la note sans `type` (Gramps : `General`, relevé sur l'API) ; la page ne filtre pas sur le type | `GrampsjsViewNewBlogPost.js:108-118, 142-174` |
| images | premier `media_list` = aperçu (recadré par son `rect`), galerie si plus d'un média | `GrampsjsBlogPostPreview.js:117-131`, `GrampsjsBlogPost.js:128-136, 169-187` |
| privé | interrupteur de la source ; la note du corps n’est privée comme la source qu’à partir de `v26.11.3` (`GrampsjsViewNewBlogPost.js:173` de cette version) | `GrampsjsViewNewBlogPost.js:142-174` |

Écriture par Genealogiste (`ajouter_billet`, [opérations](operations.md#billets-du-blog-de-gramps-web-261)) :

- une seule transaction (`POST /api/transactions/`, *Editor*) : `Source` (`private`, `tag_list` Blog,
  `media_list` dans l'ordre demandé), `Note` du corps (type `Source Note`, privée comme la source, étiquetée
  `Blog` comme le fait l'interface, texte stylé si `format_texte: markdown`), `Tag` `Blog` si absent, médias ;
- le **corps reste la première note** : à chaque écriture d'un billet créé ou modifié, les notes générées
  (`Genealogiste:auto`, « Lien : … » d'une source qui a une URL) passent après le corps ; un billet saisi dans
  l'interface dont une note générée précède le corps est remis en ordre la première fois que Genealogiste le
  modifie (avertissement « corps remis en première note ») ; tant qu'il ne change pas, il n'est jamais réécrit,
  quel que soit `GENEALOGISTE_GRAMPS_NOTES_AUTO` (`true`, `modifies`) ou `gramps_recalculer_notes` ;
- **confidentialité** : le corps et les notes générées d'un billet créé ou modifié prennent la confidentialité
  de la source. Le corps privé d'un billet privé est lu dans le modèle (`Source.note`, il peut donc être
  modifié ou retiré par `modifier_source`) ; toute autre note privée reste hors du modèle, intacte (c'est le
  cas du corps privé d'un billet public : jamais publié par Genealogiste) ;
- **compte Invité** (rôle 0, sans `ViewPrivate`) : la base lui est servie à travers le filtre du privé ; un
  billet privé n'apparaît ni dans la liste, ni par son identifiant (`/api/sources/<handle>` : 404 ; `200 {}`, objet vide, sur l'API 3.13.0), et sa note
  non plus (`/api/notes/?gramps_id=…` : 404). Un billet public et son corps lui sont lisibles. Gramps Web
  ne masque pas les vivants par rôle : d'où le refus d'un billet public qui nomme une personne présumée vivante
  ([sécurité](securite.md#billets-du-blog-de-gramps-web-261)). Les **médias** gardent leur propre
  confidentialité : l'image d'un billet privé reste lisible par un Invité si le média est public. Depuis #264, la
  proposition d'un billet ou d'une tâche privés l'**avertit** pour chaque média public, avec l'opération qui le
  rend privé (`modifier_media`, `champs.prive`) et les autres objets qui le lient ; `gramps_proteger_vivants` (tout
  l'arbre) propose de rendre privé le média dont le seul référent est un billet ou une tâche privés ;
- **synchronisation** : `gramps_synchroniser`, le miroir Git et `gramps_tirer` (mode fichier) lisent le billet
  comme une source ordinaire (étiquette `_ETIQUETTE Blog`, `_RESN PRIVACY`, corps en `NOTE`, `OBJE` dans
  l'ordre) : ni doublon ni écrasement ;
- version : rien de plus que les étiquettes (#262) et le texte enrichi (#279) ; la page Blog existe dans
  toutes les images de la [matrice](#compatibilité-des-versions). Vérifié par `make test-gramps-matrice`
  (requêtes de la page, compte Invité, annulation) ; le **rendu dans le navigateur n'est pas automatisé** :
  implémenté, non éprouvé visuellement.

### Tâches (#263)

Comme le blog, la vue Tâches n'a pas d'objet propre : une tâche est une **source portant l'étiquette `ToDo`**.
Relevé dans le frontend gramps-web `v26.11.0` (`8df6820`, image épinglée) et `v26.11.3` (`20c7655`, constantes
regroupées dans `src/taskConstants.js`, mêmes requêtes) ; côté Desktop, gramps `v6.0.8`
(`maintenance/gramps60`, `32aa296`) :

| Tâche | Gramps | Code |
|---|---|---|
| liste | `GET /api/sources/?rules={"rules":[{"name":"HasTag","values":["ToDo"]}]}&locale=…&sort=-gramps_id&extend=tag_list`, puis tri local par statut (Open, In Progress, Blocked, autre, Done) | `GrampsjsViewTasks.js:72-103` (v26.11.3), `taskConstants.js:88-102` |
| étiquette | nom exact `ToDo` (casse comprise), masquée à l'affichage ; créée par `POST /api/tags/` si absente | `GrampsjsViewNewTask.js:205-223`, `GrampsjsTasks.js:428` |
| statut | attribut de source (`SrcAttribute`) de type **personnalisé** (chaîne) `Status` : `Open`, `In Progress`, `Blocked`, `Done` ; un autre statut (Gramps Desktop, saisie à la main) est affiché tel quel | `taskConstants.js:1-17`, `GrampsjsTask.js:211-217` |
| priorité | attribut `Priority` (chaîne) : l'interface écrit `"1"` (High), `"5"` (Medium), `"9"` (Low) ; toute valeur numérique < 5 est haute, 5 moyenne, > 5 basse ; absente ou non numérique : sans priorité | `taskConstants.js:19-25, 73-86` |
| création | `POST /api/objects/` : source (`attribute_list` : `Priority "5"` puis `Status "Open"`, `tag_list` ToDo + étiquettes choisies) et note (type `To Do`, mêmes étiquettes) ; sans description, aucune note | `GrampsjsViewNewTask.js:22-25, 167-203` |
| description | **première note** de `note_list` (`taskNote`) ; ajoutée depuis la page d'une tâche : note `To Do`, étiquettes et confidentialité de la tâche | `taskConstants.js:64-71`, `GrampsjsTask.js:482-511` |
| statut ou priorité changés (une tâche ou plusieurs en lot) | une requête par tâche : `PUT /api/sources/<handle>` de l'objet complet, l'attribut retiré puis remis **en fin de liste** (`{_class: "SrcAttribute", type, value}` ; v26.11.0 : `{type, value}`) ; aucune transaction | `GrampsjsViewTasks.js:105-129`, `GrampsjsTasks.js:550-557` |
| confidentialité | interrupteur de la source ; la note de description est privée comme la tâche à partir de `v26.11.3` seulement (v26.11.0 : note créée sans `private`) | `GrampsjsViewNewTask.js:200`, `GrampsjsViewTask.js:68-101` |
| liens | aucun : l'interface ne rattache pas une tâche à une personne ou un autre objet | `GrampsjsViewTask.js`, `GrampsjsTask.js` |

**Gramps Desktop** n'a pas de vue Tâches : son gramplet « To Do » liste les **notes** de type `To Do`
(`plugins/gramplet/todogramplet.py:98-107`, règle `HasType(["To Do"])`) avec l'objet qui les porte, et le
rapport complémentaire « ToDoReport » (greffon 1.2.40 pour 6.0) liste les notes portant une étiquette choisie.
La description d'une tâche y apparaît donc (rattachée à sa source), sans statut ni priorité, qui restent des
attributs de la source. Genealogiste ne crée pas de seconde représentation (note `To Do` isolée) : la tâche
Web est la seule forme ; l'export Gramps XML la conserve telle quelle (source, attributs, étiquettes, note).

Écriture par Genealogiste, **seulement avec `GENEALOGISTE_GRAMPS_TACHES=true`** (sinon une source étiquetée
`ToDo` reste une source ordinaire, ses attributs `Status` et `Priority` intacts, et `ajouter_tache` est refusé) :

- `ajouter_tache` ([opérations](operations.md#tâches-de-gramps-web-263)) : une transaction (*Editor*) avec la
  `Source` (titre, `Priority` puis `Status`, comme l'interface ; défauts `5` et `Open`), la `Note` de description
  (type `To Do`, étiquetée `ToDo`, privée comme la source, texte stylé si `format_texte: markdown`) et le `Tag`
  `ToDo` si absent ; **privée par défaut** ;
- `modifier_tache` : statut, priorité, titre, description, confidentialité ; l'attribut changé est retiré puis
  remis en fin de liste, comme le fait l'interface ; les autres restent à leur place ;
- la **description reste la première note** : aucune note générée (`Genealogiste:auto`) n'est ajoutée à une
  tâche (un « Lien : … » deviendrait sa description), une note générée déjà présente est gardée telle quelle ;
  une tâche saisie dans l'interface dont une autre note précède la description est remise en ordre la première
  fois que Genealogiste la modifie (avertissement) ; tant qu'elle ne change pas, elle n'est jamais réécrite,
  quel que soit `GENEALOGISTE_GRAMPS_NOTES_AUTO` ou `gramps_recalculer_notes` ;
- un **statut ou une priorité changés dans l'interface** (PUT) sont relus sans réécriture ; la description
  privée d'une tâche privée est lue dans le modèle (même règle que le corps d'un billet) ;
- **compte Invité** : une tâche privée et sa description sont invisibles dans la vue Tâches ; une tâche publique
  qui nomme une personne présumée vivante (nom ou identifiant) est refusée
  ([sécurité](securite.md#tâches-de-gramps-web-263)) ;
- le **diff** porte une ligne par tâche créée ou dont le statut ou la priorité change
  (`@@ tâche S5 : statut Open → Done @@`), invisible autrement dans le GEDCOM ; le miroir Git et
  `gramps_tirer` ne gardent pas `Status` ni `Priority` (seulement l'étiquette et la description) ;
- lecture : `arbre_recherche(etiquette="ToDo", objet="source")` donne pour chaque tâche `tache` (statut,
  priorité et son libellé, ouverte) ;
- version : rien de plus que les étiquettes (#262) ; la vue Tâches existe dans toutes les images de la
  [matrice](#compatibilité-des-versions). Vérifié par `make test-gramps-matrice` (requêtes exactes de la vue
  Tâches et de la page d'une tâche, tri, changements « comme l'interface », compte Invité, annulation) ; le
  **rendu dans le navigateur n'est pas automatisé** : implémenté, non éprouvé visuellement.

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
| modifier le chercheur (`PUT /api/metadata/researcher/`, droit `EditTree`) | `chercheur_modifier` | 3.9.0 | utilisée (#282 : proposition, accord, journal, annulation par Genealogiste ; rôle Owner) |
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
| signets de la base, lecture (`GET /api/bookmarks/<espace>`) | `signets` | 0.1.0 | utilisée (#282 : export `<bookmarks>`, `gramps_reglages`) |
| signets de la base, écriture (`PUT`/`DELETE /api/bookmarks/<espace>/<handle>`, droit `EditObject`) | `signets_ecriture` | 1.5.0 | utilisée (#282 : proposition, accord, journal, annulation par Genealogiste) |
| formats de nom personnalisés, lecture (`GET /api/name-formats/`) | `formats_noms` | 0.1.0 | utilisée (#282 : `gramps_reglages`, export `<name-formats>`) ; aucune route d'écriture |
| groupes de noms, lecture (`GET /api/name-groups/`) | `groupes_noms` | 0.1.0 | utilisée (#276 : `arbre_recherche`, export, `gramps_grouper_noms`) |
| groupes de noms, écriture (`POST /api/name-groups/<patronyme>/<groupe>`, droit `EditNameGroup`) | `groupes_noms_ecriture` | 0.6.0 | écartée (#276) : hors historique, retour à « aucun regroupement » impossible |

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
- Chemin et Gramps Web (#280) : à l'envoi d'un contenu nouveau (`PUT /media/{handle}/file`), le serveur range le fichier
  à plat sous `<somme MD5><extension>` dans son propre dossier de médias et **remplace** `path` (et somme, type) ; le
  chemin relatif d'origine n'existe plus que dans `Genealogiste-Fichier`. Un média sans fichier garde le `path` écrit, sans
  somme. Aucune route n'expose le dossier de base du serveur. Conséquence pour Gramps Desktop (chemin de base = racine du
  vault, procédure, addon de synchronisation non éprouvé) : [docs/gramps.md](gramps.md#chemin-de-base-des-médias-280). Le
  contrôle `gramps_medias_chemins` du diagnostic compte les médias dont le chemin ne se résout pas.
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

Hors v1 : fusion native de Gramps (la fusion passe par `/fusionne`). Études du jalon M6 :
[fusion native](etudes/gramps-fusion-native.md) (#278) et [vérification native](etudes/gramps-verification-native.md) (#275).

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
