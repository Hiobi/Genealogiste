# Étude #266 : fonctions de Gramps Web à exploiter ou écarter

Note de conception, 2026-11-21. **Aucune fonction produit n'est implémentée** : le mainteneur valide avant tout
développement. Données fictives seulement ; ce qui n'a pas été exécuté est marqué « non éprouvé ».

## Contexte

#266 liste huit fonctions de Gramps Web (documentation grampsweb.org) à évaluer pour Genealogiste en mode `gramps`.
Pour chacune : faits amont sourcés, état du plugin, essai réel si utile, verdict (**à faire**, **à documenter**,
**écarté**). La compatibilité et les fonctions déjà livrées sont dans [gramps-web.md](../gramps-web.md).

## Sources

| Alias | Dépôt | Référence | SHA |
|---|---|---|---|
| API | gramps-project/gramps-web-api | tag `v3.26.0` | `5b3f890703537c828009656e7886a2f1e856c060` |
| API-épinglée | gramps-project/gramps-web-api | tag `v3.25.1` (image `26.11.0`) | `77263b895c1d476dae9a655587956ec798536776` |
| WEB | gramps-project/gramps-web | tag `v26.11.3` | `20c7655db9d2a28c2733767eaeded0f29e9154bb` |
| WEB-épinglée | gramps-project/gramps-web | tag `v26.11.0` | `8df682022418d06dc15c45f47096d5f3f8bc5fcf` |
| GRAMPS | gramps-project/gramps | `maintenance/gramps60` | `32aa29629b94c549f232cd0b61c137ae95d73acf` |

Sauf mention, `fichier:ligne` renvoie à API (chemins sous `gramps_webapi/`) ou à WEB (chemins sous `src/`).

## Essais réels

2026-11-21, Gramps Web jetable (`docker-compose.test.yml`, projet `genealogiste-etude-266`, port 5066, sans Celery,
`down -v` en sortie), images de [compatibilite-gramps.json](../../compatibilite-gramps.json) : `26.11.0` (API 3.25.1)
et `26.11.3` (API 3.26.0). Comptes `etude-owner` (rôle 4) et `etude-editor` (rôle 3). Arbre : `example.gramps` de
Gramps (`maintenance/gramps60`, 2 157 personnes, 10 536 objets), importé par `POST /api/importers/gramps/file`, non
copié dans le dépôt. Client : `GrampsClient` du plugin (révision `78fd096`). Scripts `live266.py`, `live266b.py`
(scratchpad, non versionnés). Mesures en local (même machine) : elles comparent des ordres de grandeur, pas des temps
de production.

| Mesure (API 3.25.1 ; 3.26.0 entre parenthèses) | Résultat |
|---|---|
| import natif de l'arbre d'exemple | 201 en 9,5 s (9,6 s) |
| `load_all` (11 requêtes) | 2,2 s (2,1 s) |
| `refresh` sans changement (20 requêtes : 10 listes `keys=handle,change` + 10 relectures de la dernière seconde) | 1,3 s (1,6 s) |
| `GET /api/people/?keys=handle,change` (2 157 objets, 121 Ko) | 5 ms |
| même liste filtrée `rules` `MatchesQuery` `change > T` | 4 ms, 1 objet |
| `POST /api/people/query/` `where_expr: change > T` | 7 ms (12 ms), 1 objet |
| relire 200 personnes : un `GET /api/people/<h>` chacune / un `GET /api/people/?handles=…` | 1,4 s / 0,056 s (10 : 0,68 s / 0,009 s) |
| `GET /api/search/?query=Garner` / `MatchesQuery` `'Garner' in surname` / filtre local sur le modèle déjà converti | 12 ms (312) / 3 ms (70) / 1 ms (71) ; conversion Gramps → modèle 0,42 s |
| `?gql=…` / `?oql=…` | 200 / 422 (422 / 422) |
| second import pendant un import | **409** `task_locked` en 0,1 s |
| `POST /api/transactions/` (Editor) et lecture pendant un import | 200 / 200 |
| second import complet du même fichier | 201 : **4 314 personnes** (tout dupliqué) |
| `refresh` du plugin après ce réimport | 56 requêtes, 5,5 s ; bilan « modifiés » = objets ajoutés |
| `POST /api/objects/delete/` (Owner) puis `refresh` | 0 objet ; bilan « supprimés » complet ; l'ancien jeton Editor lit toujours (200) |

## 1. GOQL et filtres côté serveur

**Faits amont.** `oql` retiré en 3.23.0 (`efaa3e6`) ; `gql` accepté jusqu'à 3.25.x, **422** en 3.26.0 (`12f5e73`,
constaté) ; remplaçant : paramètre `rules` avec la règle `MatchesQuery` (≥ 3.23.0, `api/resources/filters.py:189-240`),
ou `POST /api/<objets>/query/` (`select`, `where_expr`, `limit` ≤ 1000, pagination `after` ; ≥ 3.21.0,
`api/resources/object_query.py:96-200`). Paramètre `handles` des listes (« Comma-delimited list of handles to fetch »,
`api/resources/base.py:476-481`) : absent en 3.13.1, présent en 3.14.1 (tags lus). Lecture : tout rôle.

**Plugin.** Chargement complet par classe (`GrampsClient.load_all`, `gramps/client.py:259-264`), relecture
incrémentale par `keys=handle,change` puis **un GET par objet** changé ou de la dernière seconde, au-delà de 200 la
classe entière (`refresh`, `client.py:266-295`). Recherche locale sur le modèle (`arbre_recherche`), `/api/search/`
pour `gramps_recherche` (`client.py:297-300`).

**Verdict : GOQL écarté ; relecture groupée à faire.** Les listes de clés coûtent quelques millisecondes pour
2 000 à 3 500 objets : un filtre `change > T` n'y gagne rien de mesurable, et le paramètre a changé trois fois de nom en
quatre versions (`oql`, `gql`, `rules`), d'où un risque de dépendance. La recherche locale est déjà plus fine que le
filtre serveur (71 contre 70 : noms alternatifs). Le coût réel est la relecture objet par objet : ×25 en local pour
200 objets, davantage à distance (un aller-retour réseau par objet).

Issue proposée : `perf(gramps): relire en une requête les objets modifiés` — `refresh` relit les handles à relire par
`GET /api/<objets>/?handles=…` par paquets (taille d'URL bornée), repli sur le GET unitaire pour une API < 3.14
(`FONCTIONS_API` : nouvelle clé `liste_handles`, 3.14.0, à confirmer sur le tag 3.14.0) ; critères : même bilan
qu'aujourd'hui (tests existants), nombre de requêtes réduit (faux serveur), matrice verte sur les trois images.
Version minimale : aucune (repli).

## 2. Tâches de fond exclusives

**Faits amont.** Verrous par arbre depuis 3.24.0 (`217e9be`) : clé `write` pour import, restauration, réparation,
migration de schéma, suppressions en lot, `edit-by-handle`, import de médias ; `search-index`, `backup`, et deux clés
« coalescentes » (`util/task_state.py:58-72` ; décorateurs `api/tasks.py:341-1117`). Une seconde tâche sur une clé
tenue reçoit **409** `{"error": {"type": "task_locked", "task": {"href", "id"}}}` (`api/tasks.py:143-176`), y compris
sans Celery (`run_task`, `api/tasks.py:179-216`). **`process_transactions` n'a pas de verrou**
(`api/tasks.py:956`) : une transaction passe pendant un import (constaté, 200). `GET /api/tasks/` ne montre à un
Editor que **ses** tâches (`api/resources/tasks.py:266-287`, `ViewOtherUser` = Owner). Suppression totale :
`POST /api/objects/delete/`, jeton *frais* et droit `DeleteObjectsBatch` (Owner, `api/resources/objects.py:148-170`).

**Plugin.** N'appelle aucune route verrouillée (ni import natif, ni restauration, ni suppression en lot,
ni `edit-by-handle`) : il ne peut pas recevoir de 409. `_wait` (`client.py:367-387`) suit une transaction de fond
(avec Celery seulement), borné à 600 s puis « délai dépassé » : pas d'attente indéfinie ; il ne lit que `state`, pas
`status` (`lost` depuis 3.24). Une transaction écrite pendant un import ou une restauration n'est pas bloquée ; les
conflits sont détectés par `old` (objets supprimés ou changés : refus « l'arbre a changé »). Après une suppression
totale, `refresh` voit tout supprimé et l'ancien jeton reste valide : « se reconnecter » vaut pour l'interface
(jeton frais, cache du navigateur), pas pour le plugin ; en revanche le miroir Git enregistrerait la suppression
comme « Modifications externes ».

**Verdict : à documenter, plus une petite issue de robustesse.** Le « refus clair » demandé n'est pas réalisable
pour un Editor (il ne voit pas la tâche d'un autre compte) et n'est pas nécessaire (aucune route verrouillée).
Issue proposée : `fix(gramps): suivi de tâche et suppression massive externe` — `_wait` traite `status` `failed` et
`lost` (3.24+) comme un échec immédiat ; un 409 `task_locked` éventuel donne un message actionnable (« une tâche
exclusive est en cours sur l'arbre : réessayer après », sans réessai automatique) ; `gramps_synchroniser` et le miroir
avertissent et demandent confirmation quand une relecture voit disparaître plus de la moitié des objets (suppression
totale ou restauration) avant de committer. Critères : faux serveur avec 409 et `lost`, aucun commit miroir sans
accord dans ce cas. Version minimale : aucune.

## 3. Régions de média

**Faits amont.** `MediaRef.rect` : `null` ou `[x1, y1, x2, y2]` entiers en **pourcentage** de l'image, 0 ≤ x1 < x2 ≤ 100
(Gramps `gen/lib/mediaref.py:119-130, 249-255` ; route `/media/<h>/cropped/<x1>/<y1>/<x2>/<y2>`) ; l'API rend `[]` pour
`null` (`api/resources/emit.py:140-141`). Exemples réels de l'arbre d'exemple : `[51, 19, 59, 33]`,
`[15, 27, 25, 43]`. La détection de visages (`GET /api/media/<h>/face_detection`,
`api/resources/face_detection.py:33-50`, présente de 3.13.0 à 3.26.0) **n'écrit rien** : elle renvoie des régions que
l'interface propose d'attacher à une personne (référence de média avec `rect`, `components/GrampsjsMediaObject.js`).
Une citation porte une `media_list` de `MediaRef` : une région peut donc être liée à la citation.

**Plugin.** Le modèle n'a pas de région : `Citation.medias` est une liste d'identifiants ; une citation nouvelle
reçoit `rect: None` (`gramps/mapping.py:1221-1242`), une référence existante est recopiée telle quelle
(`media_refs`, `mapping.py:1178-1189` ; citation réutilisée recopiée entière). L'export et l'import Gramps XML gardent
le rectangle (`export/gramps_xml.py:187-191`, `gramps/lecture_xml.py:343`). Le backend fichier et le miroir GEDCOM le
perdent.

**Verdict : à faire, priorité moyenne.** Issue proposée : `feat(medias): zone de l'acte sur la citation` — opérations
`ajouter_citation` / `modifier_citation` : `medias` accepte `{"id": "O3", "zone": [x1, y1, x2, y2]}` (pourcentages
entiers, validés comme `_abort_if_invalid_crop`) ; écrit en `rect` (Gramps) et en `CROP` sous l'`OBJE` de la citation
(GEDCOM 7, `TOP`/`LEFT`/`HEIGHT`/`WIDTH`) ; conversion pourcentage ↔ `CROP` **non éprouvée** (unité de `CROP` à
vérifier dans la spécification GEDCOM 7.0 et, pour des pixels, dimensions de l'image nécessaires). Critères :
aller-retour Gramps ↔ modèle ↔ GEDCOM sans perte, région affichée par l'interface (vérification visuelle manuelle),
diff lisible. Version minimale : aucune.

## 4. Carte

**Faits amont.** Média géoréférencé : attribut de média de type personnalisé `map:bounds`, valeur **JSON en chaîne**
`[[lat_min, lon_min], [lat_max, lon_max]]` (API `api/file.py:53-70` : refusé si min ≥ max ; interface
`components/GrampsjsFormEditMapLayer.js:320-336`). La carte charge ces médias par
`GET /api/media/?rules={"rules":[{"name":"HasAttribute","values":["map:bounds","*"],"regex":true}]}`
(`views/GrampsjsViewMap.js:1062-1075`) et les superpose (calques avec opacité). Fichiers vectoriels KML, GPX et
GeoJSON rattachés **au lieu** (sa `media_list`, type MIME ou extension) : affichés à la sélection du lieu
(`mapVector.js`, `placeVectorsController.ts`, commit `a3b3123c` du 2026-10-12 ; présents en WEB-épinglée, absents en
`v26.5.1`). Seuls les lieux à coordonnées sont placés.

**Plugin.** Coordonnées écrites sur la commune seulement si le lieu Gramps n'en a pas et que le modèle en a
(`gramps/mapping.py:1549-1550`), avec le code INSEE ; `geo_commune` donne les coordonnées de l'API Géo. Un attribut
`map:bounds` saisi dans l'interface est conservé (attribut non géré, recopié). Aucun contrôle de complétude des
coordonnées n'existe. (Dans l'arbre d'exemple de Gramps : 373 lieux sur 1 296 ont des coordonnées ; sans valeur pour
nos bases.)

**Verdict : à documenter ; complétude des coordonnées à faire (petite) ; cartes anciennes écartées pour l'instant.**
Issue proposée : `feat(gramps): lieux sans coordonnées` — rapport en lecture (communes à code INSEE sans `lat`/`long`)
dans `arbre_lacunes` ou `gramps_structurer_lieux`, et proposition de les compléter depuis l'API Géo (une requête par
commune, journalisée, aucune donnée de personne) ; diff, accord, annulation. Cartes anciennes (Cassini, cadastre
napoléonien) : géoréférencer une image est un travail manuel que l'interface fait déjà ; le plugin n'a pas de source
d'emprises fiable. À rouvrir si un service d'archives publie des emprises.

## 5. OCR et note « Transcript »

**Faits amont.** `POST /api/media/<h>/ocr?lang=…&format=string` (Tesseract, `api/resources/ocr.py:58-90`, présent de
3.13.0 à 3.26.0) **n'écrit rien** : il renvoie le texte. Le bouton « enregistrer comme note » de l'interface crée une
note de type `Transcript`, **sans `private`** (donc publique), par `POST /api/notes/`, puis l'ajoute à la
`note_list` **du média** en cours d'édition (`components/GrampsjsTextRecognition.js:328-345` ; identique en
`v26.5.1` et WEB-épinglée). `server.ocr` de `/api/metadata/` dit si l'OCR est disponible (vrai sur les deux images).

**Plugin.** Écrit ses transcriptions en note `Transcript` **de la citation** (`mapping.py:1229`), confidentialité de la
citation ; à la lecture, les notes `Transcript` non privées d'une citation forment `Citation.texte`
(`mapping.py:623-633`). Le modèle `Media` n'a pas de notes : une note OCR d'un média est conservée côté Gramps,
invisible au modèle et au miroir.

**Verdict : à documenter.** Pas de doublon automatique (porteurs différents : média contre citation). Règle proposée,
à écrire dans gramps-web.md : la note OCR est un texte machine brut rattaché au média ; Genealogiste ne la lit pas comme
transcription de la citation et ne la modifie pas ; il n'écrit jamais de `Transcript` sur un média ; une transcription
vérifiée passe par la citation (`modifier_citation`). Attention : la note OCR est publique par défaut (lisible par un
compte Invité) même si l'acte concerne un vivant ; la rendre privée dans l'interface. Option future (non proposée
maintenant) : signaler dans `arbre_fiche` qu'un média de la citation porte une transcription OCR non vérifiée.

## 6. Assistant IA et propositions d'écriture

**Faits amont.** `LLM_ALLOW_WRITE_PROPOSALS` (défaut `False`, `config.py:109`) n'existe qu'à partir de **3.26.0**
(absent du `config.py` de 3.25.1 ; `241cb877`, 2026-11-16) ; l'interface qui applique les propositions arrive en
**26.11.3** (`fa2b45b7`). L'assistant ne propose que si le chat est configuré (`LLM_MODEL`), si le réglage est actif et
si l'utilisateur a `AddObject`, `EditObject` et `DeleteObject` (`api/resources/chat.py:161-164`,
`api/llm/__init__.py:212-213`) ; les outils de proposition n'écrivent rien (`api/llm/propose.py:20-30`, essai à blanc).
L'utilisateur applique d'un clic : **une transaction ordinaire** `POST /api/transactions/?message=Changes proposed by the
assistant` sous son propre compte (`components/GrampsjsChat.js:265-290`), refusée si un objet a changé depuis la
proposition (400, « outdated »). Le réglage n'est lisible que par `/api/config/` (Admin) ; `server.chat` de
`/api/metadata/` dit seulement si le chat existe.

**Plugin.** Ces écritures sont des modifications externes comme une saisie dans l'interface : vues par `refresh`
(bilan), commitées par le miroir (« Modifications externes »), et toute proposition en cours dont un objet a changé
est refusée à l'application (`old`).

**Verdict : à documenter.** Texte à ajouter à gramps-web.md : les propositions de l'assistant de Gramps Web ne
passent pas par le contrat d'accord de Genealogiste (diff, jeton, journal) ; elles apparaissent dans l'historique de
Gramps Web sous le message « Changes proposed by the assistant » et sont annulables là ; Genealogiste les traite comme
toute modification externe. Option (non proposée) : `diagnostic` rappelle `server.chat` dans `gramps_reglages`.

## 7. Import additif

**Faits amont.** L'import natif (`POST /api/importers/<ext>/file`, Owner, verrou `write`) ajoute toujours : le même
fichier importé deux fois double l'arbre (constaté : 2 157 → 4 314 personnes, réponse 201 sans avertissement).
Restauration : route distincte `…/file/restore` (remplace l'arbre).

**Plugin.** `arbre_importer_gedcom` n'utilise pas l'import natif : il lit le fichier et prépare une proposition
`remplacer_arbre` (`server.py:1497-1543`, `tree/ops.py:1222-1310`), diff et accord. En mode gramps, **aucun garde
sur l'état de l'arbre** :
- `ajouter` : tout est ajouté et renuméroté ; les UID déjà présents sont réattribués et seulement comptés dans le
  résumé (« N UID réattribués », `ops.py:1306`). Un réimport passe donc, avec un diff énorme ;
- `remplacer` : l'arbre du modèle est remplacé puis réécrit par-dessus la base lue : les objets absents du fichier
  sont **supprimés** de Gramps Web dans la transaction (le diff calculé par `gramps/mapping.diff` contient des
  suppressions) ; effet exact sur les objets que le modèle ne représente pas (tâches, billets, notes isolées) **non
  éprouvé**.

La bascule, elle, exige un arbre vide (`gramps/backend.py:927-944`).

**Verdict : à faire.** Issue proposée : `fix(gramps): garde-fous de l'import sur un arbre Gramps Web non vide` —
(a) `remplacer` refusé en mode gramps si l'arbre n'est pas vide (message : bascule ou arbre neuf) ; (b) `ajouter` :
si une part des UID (`Genealogiste-UID`, `_UID`) ou des `gramps_id` sources est déjà dans l'arbre, refus « réimport
probable » avec les nombres, sauf `doublons_acceptes=true` explicite ; (c) dans tous les cas le bilan dit combien
d'objets existants sont touchés. Critères : tests sur faux serveur et `make test-gramps` (réimport du même fichier
refusé ; arbre vide accepté ; `remplacer` sur arbre non vide refusé). Version minimale : aucune.

## 8. Multi-arbres et rôles

**Faits amont.** Un compte appartient à un arbre ; l'arbre est dans le jeton (`tree`, `api/resources/token.py:94-96`) ;
en mono-arbre, l'identifiant est le dossier de la base (`api/util.py:583-605`) ; un Admin multi-arbres sans arbre n'a
pas de revendication. `GET /api/trees/-` (`api/resources/trees.py:209-226`) rend `name`, `id`, quotas et usages
(`quota_people`, `usage_people`, `quota_media`, `quota_ai`…). **Quota de personnes** : une transaction qui dépasse
`quota_people` est refusée en **405** « Not allowed by people quota » (`api/tasks.py:997`, `api/util.py:655-674` ;
présent en 3.13.0).

**Plugin.** `GRAMPS_ARBRE.json` mémorise l'arbre du compte à la première connexion et refuse tout autre arbre
(lecture et écriture, `gramps/backend.py:132-154`) ; `diagnostic` montre `multi_tree` (`diagnostic.py:448-475`) et le
rôle. L'URL mémorisée n'est pas comparée (même arbre restauré sur une autre instance : accepté, voulu).

**Verdict : un trou, à faire (petit).** Le quota n'est vu qu'à l'application, après l'accord, sous un message
HTTP brut. Issue proposée : `feat(gramps): quota de personnes de l'arbre` — `diagnostic` lit `GET /api/trees/-`
(quota et usage, contrôle `gramps_quota`) ; `arbre_proposer`, la bascule et l'import refusent dès la proposition une
transaction dont le nombre de personnes ajoutées dépasse le quota restant ; le 405 est traduit en message actionnable.
Critères : faux serveur avec quota ; sans quota (cas courant) rien ne change. Version minimale : aucune.

## Constat annexe : aller-retour de l'arbre d'exemple de Gramps

En réécrivant l'arbre d'exemple par-dessus lui-même sans aucune opération (`gramps_to_tree` puis
`tree_to_gramps(base=…, generated=False)`, hors ligne et sur les deux images), le diff n'est **pas vide** : 12 objets.
Sept médias reçoivent `Genealogiste-Fichier`, une personne `Genealogiste-Association` (écritures du plugin attendues ou
non : à trancher) ; mais aussi des **pertes** : la citation d'une référence de personne (parrain) est recréée sous un
autre handle et `gramps_id` (`C2832` supprimée, nouvelle citation créée), la citation d'une référence d'événement de
`I0044` est retirée, l'attribut `Age` (avec sa citation) d'une référence d'événement familial de `F0017` disparaît.
La documentation dit que les objets venus de l'interface sont « réécrits à l'identique tant que Genealogiste ne les
modifie pas ». Effet sur une vraie proposition (`arbre_proposer` sur une base de ce type) **non éprouvé**. Issue
proposée, hors #266 : `fix(gramps): aller-retour sans modification de l'arbre d'exemple de Gramps`, avec le cas
d'exemple du banc Desktop comme test.

## Récapitulatif

| Point | Verdict | Issue proposée |
|---|---|---|
| 1. GOQL | écarté (GOQL) ; à faire (relecture groupée) | `perf(gramps): relire en une requête les objets modifiés` |
| 2. Tâches exclusives | à documenter ; petite robustesse | `fix(gramps): suivi de tâche et suppression massive externe` |
| 3. Régions | à faire (moyenne) | `feat(medias): zone de l'acte sur la citation` |
| 4. Carte | à documenter ; coordonnées à faire ; cartes anciennes écartées | `feat(gramps): lieux sans coordonnées` |
| 5. OCR | à documenter | — |
| 6. Assistant IA | à documenter | — |
| 7. Import additif | à faire | `fix(gramps): garde-fous de l'import sur un arbre Gramps Web non vide` |
| 8. Multi-arbres | à faire (quota) | `feat(gramps): quota de personnes de l'arbre` |

## Recommandation

Ordre proposé : 7 (risque de données), constat annexe (perte silencieuse), 8 (quota, petit), 1 (performance à
distance), 2, 3, 4. Les points 5 et 6, et la partie documentaire de 2 et 4, tiennent en une PR de documentation sur
[gramps-web.md](../gramps-web.md).

## Risques

- Mesures locales : l'avantage de la relecture groupée grandit avec la latence réseau, non mesurée.
- `handles=` : version d'apparition encadrée (3.13.1 absent, 3.14.1 présent), tag 3.14.0 non lu.
- Comportement d'une transaction pendant une **restauration** : non éprouvé (seul l'import l'a été).
- Assistant IA : chat non configuré dans l'essai (pas de modèle) ; parcours d'application lu dans le code, non
  éprouvé.

## Questions ouvertes pour le mainteneur

1. Import `ajouter` sur un arbre non vide : refus par défaut avec option explicite (proposé), ou simple avertissement ?
2. Zone d'acte : `CROP` GEDCOM 7 dans le mode fichier (proposé), ou région seulement côté Gramps ?
3. Coordonnées manquantes : rapport seulement, ou proposition de complément depuis l'API Géo ?
4. `Genealogiste-Fichier` et `Genealogiste-Association` ajoutés à un objet non modifié (constat annexe) : voulu ?
