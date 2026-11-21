# Étude : fusion native de Gramps et `fusionner_personnes` (#278)

Note de conception du lot 4 du jalon M6. **Aucune fonction n'est implémentée** : la piste retenue attend la
validation du mainteneur. Date : 2026-11-21. Données des essais : arbre fictif sur des Gramps Web jetables,
détruits après usage (`down -v`). Jamais de fusion automatique, quelle que soit la piste.

## Contexte

Gramps Web expose la fusion native de Gramps Desktop : `POST /api/<objets>/<phoenix>/merge/<titanic>`.
Genealogiste fusionne par son modèle (`fusionner_personnes`, `fusionner_sources`) puis écrit le résultat en une
transaction `POST /api/transactions/` après diff et accord, journalisée dans `gramps-transactions.jsonl` et
annulable. Questions de l'issue : même résultat ? fusion native annulable et visible dans l'historique ? diff et
accord conservables en prévisualisant localement puis en appelant la fusion native ?

## Faits amont (lus dans le code)

Références : gramps-web-api tag `v3.26.0` (`5b3f890703537c828009656e7886a2f1e856c060`, `merge.py` et
`history.py` identiques en `v3.25.1`) ; Gramps tag `v6.0.8` (`13fdd22bf573fdf58ad519515c6ed90eb54dbc83`),
version servie par les deux images testées (lue dans `/api/metadata/`).

### Routes (`gramps_webapi/api/resources/merge.py`)

- Personnes (l. 108-135) : corps `{"family_merger": bool}` (défaut vrai) ; familles (l. 138-172) :
  `{"phoenix_father_handle", "phoenix_mother_handle"}` ; événements, lieux, sources, citations, dépôts, médias,
  notes (l. 175-269) : aucun corps. Pas d'étiquettes. Introduites en 3.15.0.
- Permission `EditObject` + `DeleteObject` (Editor). Réponse **200 `{}`** : aucune transaction renvoyée ;
  404 (handle inconnu), 409 (`MergeError` : conjoints, parent et enfant), 400 (parent de famille invalide).
- **Aucun état `old` comparé** : la requête lit les deux objets et fusionne.
- Index de recherche : titanic retiré, phénix réindexé (`_update_search_index`, l. 56-68). Les transactions
  du plugin le mettent aussi à jour (`transactions.py:128-133`) : ce n'est pas un avantage propre à la fusion
  native.

### Règles de Gramps (`gramps/gen/merge/`, `gramps/gen/lib/`)

- `MergePersonQuery` (`mergepersonquery.py:43-208`) : refus si conjoints ou parent et enfant (l. 52-67) ;
  `phoenix.merge(titanic)` ; références au titanic réécrites ; familles de parents : le titanic est remplacé
  (aucune fusion de familles de parents) ; familles de conjoint : avec `family_merger`, deux familles du même
  couple sont fusionnées (`merge_families`, l. 83-128), sauf cas complexes (plusieurs familles avec le même
  conjoint : fusion sautée, l. 178-190) ; personne de référence reportée sur le phénix (l. 200-205) ; titanic
  supprimé. Une seule transaction `DbTxn(_("Merge Person"))` (l. 135).
- `Person.merge` (`person.py:596-630`) : ajoute un attribut **`_("Merged Gramps ID")`** = `gramps_id` du titanic
  (traduit dans la locale du serveur) ; `private` = OU ; nom principal du titanic inséré en tête de ses noms
  alternatifs puis noms réunis (identiques ignorés, équivalents fusionnés) ; références d'événements réunies
  (une référence n'est fusionnée qu'au **même événement et même rôle**, `eventref.py:223-237` : deux événements
  distincts de même type restent deux) ; médias, adresses, URL, associations réunis ; **attributs** : un
  attribut n'est fusionné que si type **et** valeur sont égaux (`attribute.py:140-154`,
  `attrbase.py:129-147`), sinon les deux sont gardés côte à côte ; notes, citations, étiquettes : union
  (`notebase.py:177-186`, `citationbase.py:203-212`, `tagbase.py:120-129`) ; familles : union. Le sexe du
  phénix est gardé.
- `MergeFamilyQuery` (`mergefamilyquery.py:42-223`) : parents différents fusionnés par `MergePersonQuery` sans
  fusion de familles ; `Family.merge` (`family.py:436-455`) : relation reprise seulement si celle du phénix est
  inconnue ; événements, médias, enfants, attributs, notes, citations, étiquettes réunis ; « Lost: handle, id,
  relation, father, mother of acquisition ». Transaction `DbTxn(_("Merge Family"))` (l. 149).
- `MergeSourceQuery` (`mergesourcequery.py:44-81`) : citations du titanic repointées vers le phénix, sans
  dédoublonnage ; `Source.merge` (`src.py:287-299`) réunit notes, médias, étiquettes, attributs, dépôts.
- Annulation par l'historique (`history.py`) : `GET …/history/<id>/undo` diagnostique (l. 314-412) en comparant
  l'état courant au `new_data` de **chaque** changement ; `POST …/history/<id>/undo` (l. 414-460) inverse la
  transaction (`reverse_transaction`) et la rejoue par `process_transactions`, qui compare les états `old`
  (sauf `force`).

### Fusion du plugin (`mcp/src/genealogiste_mcp/tree/ops.py`)

`op_fusionner_personnes` (l. 1038-1097) : sexes différents refusés sauf `forcer`, justification obligatoire ;
noms réunis par nom complet ; événements « identiques » (`_same_event`, l. 1000-1001 : **même type, même date,
même lieu**, valeur et description ignorées) fusionnés champ par champ (`_merge_event`, l. 1009-1035 : valeur
divergente reportée en note, statut le plus grave) ; `vivant` le plus protecteur, `prive` OU ; extensions,
étiquettes, citations, associations, médias réunis ; note « Fusion de … : justification » ajoutée ; références
du titanic dans les familles remplacées ; **aucune fusion de familles**. `op_fusionner_sources` (l. 791-833) :
citations réécrites, citations devenues identiques (même source, même page, même porteur) fondues.

## Essais réels

### Protocole

Gramps Web jetable par `docker-compose.test.yml` (`COMPOSE_PROJECT_NAME=genealogiste-test-27578`, port 5078,
comptes Editor, Member, Contributor, Owner, Invité). Scripts hors du dépôt, qui importent le paquet du plugin.

Arbre de départ `s0` écrit par le plugin (`GrampsBackend.propose` puis `apply`), puis retouché par les routes
objets comme l'interface : 10 personnes, 5 familles, 12 événements, 18 citations, 27 notes, 2 médias,
2 sources. Paire fusionnée : **A** = Jean MARTIN (I5, phénix / `conserver`) et **B** = Jean Baptiste MARTIN
(I6, titanic / `absorber`).

| | A (I5) | B (I6) |
|---|---|---|
| Noms | Jean MARTIN | Jean Baptiste MARTIN, alternatif Jean MARTIN |
| Événements propres | naissance 1 JAN 1850 Fictiville, décès 1910, profession « laboureur » | naissance 1 JAN 1850 Fictiville (citation distincte, statut `contradictoire`), inhumation 1910, profession « cultivateur » |
| Événement partagé | recensement 1881 (même événement Gramps, rôle principal chez A et B) | idem |
| Marqueurs | `Genealogiste-UID`, `-UID noms`, `-Vivant` = N | `Genealogiste-UID`, `-UID noms`, `-Vivant` = Y, `-Association` (témoin nommé) |
| Autres | note manuelle, note générée `Genealogiste:auto`, étiquette `Essai-A`, média O1 | note manuelle, note générée, étiquette `Essai-B`, média O2, **privé**, attribut natif `Nickname` |
| Parents | F1 (Pierre MARTIN × Marie DURAND) | F2 (Paul MARTIN × Anne LEROY) |
| Unions | F3 avec Louise BERNARD (mariage 1875, enfant I9) | F4 avec Louise BERNARD (mariage 1875, enfant I10), F5 avec Claire PETIT |

Chaque essai part de `s0` ; après chaque fusion, l'annulation est appliquée et l'état comparé objet par objet à
`s0` (champ `change` exclu) : **identique** à chaque fois, ce qui garantit des points de départ égaux.

Versions : image épinglée `26.11.0` (API 3.25.1), puis image plafond `26.11.3` (API 3.26.0) : **mêmes
résultats** (seuls diffèrent les UID aléatoires et les numéros de transaction). Image plancher `26.5.1`
(API 3.13.0) : `POST /api/people/…/merge/…` → 404.

### Personnes : résultat comparé

| Objet | Plugin (`fusionner_personnes`) | Natif, `family_merger=true` | Natif, `family_merger=false` |
|---|---|---|---|
| Durée | 0,8 à 1,0 s (proposition + application) | 0,03 s | 0,03 s |
| Objets touchés | 28 éléments de transaction (diff de 145 lignes) | 8 objets (6 modifiés, 2 supprimés), 48 changements à l’historique | 5 objets (4 modifiés, 1 supprimé), 32 changements |
| Personne gardée | I5, même handle | I5, même handle | I5, même handle |
| Noms | Jean ; alternatif Jean Baptiste | idem | idem |
| Naissances | **une** (deux citations, statut `contradictoire` repris) | **deux** événements (statut sur la seconde seulement) | deux |
| Professions | **une** : « laboureur », « cultivateur » reporté en note (valeur ignorée par `_same_event`) | deux | deux |
| Recensement partagé | une référence | une référence | une référence |
| `Genealogiste-UID` | un (celui de A) | **deux** (A et B) | deux |
| `Genealogiste-UID noms` | un, cohérent avec les noms | **deux** | deux |
| `Genealogiste-Vivant` | **Y** (le plus protecteur, conflit signalé) | **deux : N puis Y** | deux |
| `Genealogiste-Association` | gardé | gardé | gardé |
| Attribut natif `Nickname` du titanic | **perdu** | gardé | gardé |
| Trace de la fusion | note « Fusion de Jean Baptiste MARTIN [I6] : … » + message de transaction | attribut `Merged Gramps ID` = I6 (en anglais) + « Merge Person » à l'historique | idem |
| Privé | oui (OU, signalé) | oui (OU) | oui |
| Étiquettes, médias | réunis | réunis | réunis |
| Note manuelle de B | gardée, **recréée** (nouveau handle) | gardée, même handle | même handle |
| Notes générées | recalculées (fiche de preuve de I5 à jour, celle de I6 supprimée) | **les deux gardées** : la fiche « réf. I6 » décrit une personne supprimée | idem |
| Citations des événements absorbés | 3 citations **recréées** (nouveaux handles) | inchangées | inchangées |
| Familles de parents | F1 et F2 | F1 et F2 | F1 et F2 |
| Unions avec Louise BERNARD | **F3 et F4 en double**, aucune alerte | **F3 seule** (F4 fondue : 2 mariages, 2 enfants, 2 `Genealogiste-UID`, 2 notes) | F3 et F4 en double |
| Union avec Claire PETIT | F5 | F5 | F5 |
| Réécriture par le plugin juste après, sans opération | aucune | 10 éléments : `Genealogiste-Vivant` = **N** seul gardé, UID et UID noms ramenés à un, notes recalculées, notes de I6 et F4 supprimées | 7 éléments, même effet sur la personne |

Référence : sur `s0`, la même réécriture sans opération donne déjà 5 éléments (normalisation de l'événement de
recensement créé par l'interface) ; ils se retrouvent dans chaque colonne.

Constats décisifs :

1. **Pas le même résultat.** La fusion native garde tout côte à côte (deux naissances, deux professions,
   marqueurs en double), la fusion du plugin dédoublonne selon ses propres règles et recalcule la preuve.
2. **Protection des vivants dégradée par la fusion native** : le plugin lit le premier `Genealogiste-Vivant`
   (`_attr`, `gramps/mapping.py:227-232`), donc « N » ; sa prochaine écriture ne garde que « N ». Le « Y » du
   titanic disparaît sans conflit signalé.
3. **Notes de preuve fausses** après une fusion native : la fiche générée « réf. I6 » reste attachée à I5
   jusqu'à la prochaine écriture du plugin.
4. **Pertes de la fusion du plugin** : attributs Gramps du titanic non modélisés (ici `Nickname`) ; handles de
   la note manuelle et des citations déplacées changent (étiquettes de note, liens `gramps://`, historique par
   objet rompus) ; deux professions distinctes sans date ni lieu confondues ; unions en double non signalées.

### Familles et sources

- Famille (après fusion native sans `family_merger`) : `POST /api/families/F3/merge/F4` → 200 `{}` ; F3 garde
  ses champs, reçoit le mariage et l'enfant de F4 (2 mariages, 2 `Genealogiste-UID`, 2 notes) ; F4 supprimée ;
  conjoints et enfant mis à jour ; « Merge Family », 20 changements ; annulation par l'historique : état exact.
  Le plugin n'a **pas** d'opération de fusion de familles.
- Sources S2 → S1 : le plugin réécrit 2 citations et **fond** les deux citations identiques de I1 (même page)
  en une ; la fusion native repointe les 2 citations sans les fondre (I1 garde deux citations « N 1820 n° 3 »
  de S1). Les deux suppriment S2 ; les deux s'annulent exactement.

### Annulabilité et historique

| Question | Constat |
|---|---|
| La fusion native figure-t-elle dans `GET /api/transactions/history/` ? | oui : « Merge Person » / « Merge Family » / « Merge Source » (anglais, locale du serveur `en_US`), utilisateur de la connexion (`sosa-test`), changements avec `old_data` / `new_data` (`?old=1&new=1`) |
| `POST /api/transactions/history/<id>/undo` la défait-il exactement ? | oui, pour les trois fusions et les deux valeurs de `family_merger` : 200, état comparé objet par objet à `s0` **identique** |
| Diagnostic `GET …/<id>/undo` | faux conflit avec `family_merger=true` (`can_undo_without_force: false`, « Person … has been modified ») : la transaction met à jour le phénix deux fois et le diagnostic compare chaque changement à l'état courant ; le `POST` réussit pourtant sans `force` |
| L'intention se reconstruit-elle après coup ? | oui : `after_id` = dernier identifiant lu avant l'appel, puis changements réduits à l'état net par objet (premier `old_data`, dernier `new_data` ; une suppression a `new_data = {}`) : 8 éléments, conformes à l'état du serveur ; inscrits au journal du plugin, `propose_undo` puis `apply` rétablissent `s0` exactement |
| Fenêtre de course | constatée : une modification de A faite entre un « aperçu » et l'appel est fusionnée sans erreur (200) ; aucune comparaison d'état |
| Droits | Member et Contributor : 403 ; Editor : 200 |

### Prévisualisation locale exacte ?

Essai : base SQLite jetable chargée avec `s0` (objets JSON du serveur, handles conservés) par la bibliothèque
`gramps==6.0.8` (environnement isolé du banc Desktop, module `gi` factice comme `scripts/sonde_gramps_desktop.py`),
puis `MergePersonQuery(db, A, B).execute(family_merger=…)`. Comparaison objet par objet avec l'état réel du
serveur après la fusion native : **0 écart** pour `family_merger=true` et `false`, sur API 3.25.1 et 3.26.0
(0,2 s). Une prévisualisation **exacte** est donc possible, à quatre conditions : même version de Gramps que le
serveur (lue dans `/api/metadata/`), même locale (`Merged Gramps ID` est traduit), copie complète de la base
(les rétroliens servent à réécrire les références), dépendance du plugin à la bibliothèque Gramps (GPL v2+,
installation lourde, aujourd'hui seulement dans le banc). Un portage des règles en Python pur serait
approximatif et à maintenir à chaque version.

Même exacte, la prévisualisation ne garantit pas l'écriture : la fusion native ne compare aucun état. Un
contrôle avant l'appel (relecture des objets touchés) réduit la fenêtre sans la fermer ; un contrôle après
(comparer le `old_data` net de la transaction à la base de la prévisualisation) détecte l'écart, mais l'écriture
a déjà eu lieu et l'accord porte alors sur autre chose que ce qui est écrit.

## Pistes comparées

| Critère | A. Fusion du plugin (actuelle) | B. Fusion native | C. Hybride (aperçu local + appel natif + journal reconstruit) |
|---|---|---|---|
| Fidélité du diff à l'écriture | exacte (le diff est la transaction) | aucun diff | exacte seulement si bibliothèque et version identiques ; course non fermée |
| Concurrence | refus si un objet a changé (`old` comparé) | aucune vérification | contrôle avant et après, non atomique |
| Annulation, journal | `gramps-transactions.jsonl`, `arbre_annuler_modification` | historique du serveur seulement | journal reconstruit (essai concluant) |
| Marqueurs `Genealogiste-*` | cohérents | **doublés**, `Vivant` lu au moins protecteur | doublés, puis seconde transaction de normalisation (non atomique) |
| Preuve | recalculée | notes générées périmées | recalcul par une seconde transaction |
| Données Gramps non modélisées du titanic | **perdues** (à corriger) | gardées | gardées |
| Familles du même couple | non fusionnées, non signalées | fusionnées (`family_merger`) | fusionnées |
| Index de recherche | mis à jour | mis à jour | mis à jour |
| Versions d'API | 0.2.0 (transactions) | 3.15.0 ; annulation par l'historique 3.4.0 | 3.15.0 et bibliothèque Gramps égale au serveur |
| Backend fichier | oui | non | non |
| « Jamais de fusion automatique » | accord sur le diff | accord sans diff | accord sur un aperçu |
| Effort | corrections ciblées | moyen | élevé (dépendance Gramps, gestion des versions, deux transactions) |

## Recommandation

**Garder la fusion du plugin (piste A) comme seul chemin d'écriture et la corriger.** La fusion native ne
garde ni le contrat diff → accord → appliquer, ni la cohérence des marqueurs, et elle dégrade la protection
d'une personne vivante à la lecture suivante. L'hybride est faisable (aperçu exact constaté, journal reconstruit
constaté) mais lourd et non atomique ; à ne reconsidérer que si le plugin dépend un jour de la bibliothèque
Gramps (backend Desktop).

Corrections à apporter à la fusion du plugin (constatées par l'essai) :

1. Conserver les données Gramps non modélisées du titanic : attributs autres que `Genealogiste-*` (comme Gramps :
   attributs différents gardés côte à côte) ; vérifier de même adresses, URL et ordonnances (non éprouvé).
2. Réutiliser les objets existants au lieu de les recréer : note manuelle du titanic et citations des
   événements absorbés gardent leur handle.
3. `_same_event` : ne pas confondre deux événements dont la valeur ou la description diffèrent quand ils n'ont
   ni date ni lieu (deux professions).
4. Unions avec le même conjoint après fusion : les signaler dans la proposition, et proposer une opération
   `fusionner_familles` (même contrat ; règles de `Family.merge` comme référence).
5. Trace de l'identifiant absorbé : envisager un attribut lisible par Gramps (`Merged Gramps ID`) en plus de la
   note, pour que les deux outils retrouvent l'ancien identifiant.

Et, indépendamment de la piste, **la fusion native reste accessible dans l'interface de Gramps Web** : le plugin
doit lire sans dommage une fusion faite là.

6. Lecture : plusieurs `Genealogiste-Vivant` sur une personne → retenir le plus protecteur et le signaler ;
   plusieurs `Genealogiste-UID` → alerte d'`arbre_coherence` (et choix explicite, pas le premier venu).
7. Notes générées rattachées à un autre objet que celui qu'elles décrivent (« réf. I6 » sur I5) : les signaler
   et les recalculer par proposition.

## Risques

- Une fusion native faite dans l'interface, puis toute écriture du plugin, retire aujourd'hui le « Y » de
  `Genealogiste-Vivant` sans le dire (constaté) : risque de publication d'une personne vivante. Correction 6
  prioritaire.
- Corrections 1 et 2 : elles touchent l'écrivain Gramps (`tree_to_gramps`), donc toutes les écritures ; tests
  de non-régression sur le faux serveur et en live.
- Piste C : version de Gramps du serveur différente de la bibliothèque locale → aperçu faux sans signal.

## Questions ouvertes pour le mainteneur

1. Piste A confirmée (fusion native écartée comme chemin d'écriture) ?
2. Priorité de la correction 6 (lecture après fusion native) : lot à part, avant les corrections de la fusion ?
3. `fusionner_familles` : à ajouter, et avec quelles règles (parents identiques seulement, ou choix du père et
   de la mère comme Gramps) ?
4. Trace `Merged Gramps ID` : l'écrire aussi (forme amont, en anglais) ou garder la seule note ?
5. Fusion d'événements : quelles règles retenir (Gramps ne fusionne jamais deux événements distincts ; le plugin
   les fond s'ils sont « identiques ») ?

## Découpage proposé (issues à créer après accord)

1. `fix(gramps)` : lecture après fusion native (marqueurs en double, `Vivant` le plus protecteur, alertes) ; test
   live : fusion native puis lecture et réécriture.
2. `fix(arbre)` : `fusionner_personnes` conserve les attributs et données non modélisés du titanic et les
   handles de ses notes et citations ; `_same_event` tient compte de la valeur ; test live comparatif.
3. `feat(arbre)` : signalement des unions en double et opération `fusionner_familles` (diff, accord, journal).
4. Facultatif : trace `Merged Gramps ID`.

## Ce qui est exécuté, ce qui est lu

- Exécuté (API 3.25.1 et 3.26.0) : les deux fusions de personnes (natif avec et sans `family_merger`), la
  fusion native de familles, les deux fusions de sources, les annulations (plugin et historique), le
  diagnostic d'annulation, la reconstruction du journal et son annulation, la modification concurrente, les
  droits Member et Contributor, la prévisualisation locale par la bibliothèque `gramps==6.0.8` ; 404 sur
  l'API 3.13.0.
- Lu seulement : refus `MergeError` (conjoints, parent et enfant), cas « complexes » de `family_merger`, fusions
  d'événements, lieux, citations, dépôts, médias et notes, comportement avec Celery, fusion native sous une
  locale française.
