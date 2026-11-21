# Gramps Desktop : compatibilité des fichiers Gramps XML

`arbre_exporter` (format `gramps`) écrit du **Gramps XML 1.7.1 non compressé** par défaut, à importer dans
Gramps Desktop (Arbres familiaux > Importer) ou dans Gramps Web. Options (#268) : `version_xml="1.7.2"` (Gramps
6.x seulement), `compresse=True` (`.gramps` gzip, forme native de Gramps Desktop) et format `gpkg` (paquet
Gramps : XML et fichiers des médias, voir [plus bas](#paquet-gpkg)). Cette page dit quelles versions de Gramps Desktop relisent ce
fichier, comment importer dans Genealogiste un arbre exporté par Gramps Desktop
([plus bas](#import-depuis-gramps-desktop), #269) et ce que la CI vérifie. Pour le mode direct sur Gramps Web (API, versions d'images) : voir
[Gramps Web](gramps-web.md#compatibilité-des-versions).

## Versions

Relevé du 2026-11-21. Versions déclarées dans [compatibilite-gramps.json](../compatibilite-gramps.json)
(`gramps_desktop`), reprises par `GRAMPS_DESKTOP_TESTES` (`genealogiste_mcp/gramps/compatibilite.py`).

| Gramps Desktop | Bibliothèque testée | Gramps XML écrit | Gramps XML lu | Statut |
|---|---|---|---|---|
| Gramps 5.2 | `gramps==5.2.4` (PyPI) | 1.7.1 | jusqu'à 1.7.1 | prise en charge, **testée en CI** |
| Gramps 6.0 | `gramps==6.0.8` (PyPI) | 1.7.2 | jusqu'à 1.7.2 | prise en charge, **testée en CI** |
| Gramps 6.1 | `v6.1.0-beta2` (sources, commit `2153e4fa4b0e4ddf7542f1c064c7820bc345a482`) | 1.7.2 | jusqu'à 1.7.2 | bêta, **testée en CI** |
| Gramps (master) | — | 1.8.0 (objets ADN) | jusqu'à 1.8.0 | non publiée, non testée |
| Gramps 5.1 et antérieures | — | ≤ 1.7.1 | — | non prise en charge, non testée |

Gramps 6.1 n'est pas sur PyPI : la CI prend les sources au commit du tag, vérifié après téléchargement. Gramps
Web ne l'embarque pas non plus (gramps-web-api exige `gramps<6.1.0`) : la bibliothèque est le seul banc de test
de Gramps 6.1.

### Pourquoi 1.7.1

L'importeur Gramps refuse un fichier dont la version XML dépasse la sienne et ne regarde que l'espace de noms
(`xmlns`), jamais la DTD. Seule l'étiquette 1.7.1 est acceptée par 5.2, 6.0 et 6.1. Vérifié avec les
bibliothèques ci-dessus :

| Fichier remis | Gramps 5.2 | Gramps 6.0 | Gramps 6.1 |
|---|---|---|---|
| export Genealogiste (1.7.1) | importé | importé | importé |
| même contenu étiqueté 1.7.2 | **refusé** (« made by version … older version 5.2.4 ») | importé | importé |
| même contenu étiqueté 1.8.0 | refusé | refusé | refusé |

Le contenu écrit (citations sous `eventref`, genre `X`, modificateurs `from`/`to`) est déjà lu par Gramps 5.2
quelle que soit l'étiquette. Gramps 6.1 ajoute `from`/`to` à sa DTD sans changer de version XML.

`version_xml` ne change que l'étiquette (espace de noms `http://gramps-project.org/xml/<version>/`, DOCTYPE,
`<created version>` 5.2.0 ou 6.0.0) : le contenu est le même, comme celui que Gramps 5.2 écrit lui-même sous
l'étiquette 1.7.1. Défaut **1.7.1**, seule étiquette lue par les trois versions ; `1.8.0` (objets ADN, branche
master) est refusé tant que Gramps ne l'a pas publié. Écarts au schéma 1.7.1 strict (DTD de Gramps 5.1),
communs avec Gramps 5.2 et lus par 5.2, 6.0 et 6.1 : citations de référence d'événement, genre `X`,
modificateurs `from`/`to`. Les styles de note `strikethrough` et `subscript` de Gramps 6 sont écrits comme Gramps
le fait, hors de toute DTD publiée.

### Dates et Gramps 5.2

Correspondance complète des dates : [Gramps Web](gramps-web.md#dates-272). Pour Gramps 5.2 (cible de 1.7.1),
vérifié avec la bibliothèque 5.2.4 sur les 1 220 formes de date écrites en XML de l'inventaire
(`mcp/tests/dates_gramps.py`, cas `dates` du banc) :

- `from` / `to` seuls (`<dateval type="from|to">`) : **aucun repli**, écrits tels quels. Gramps 5.2 les lit et les
  réécrit à l'identique (`MOD_FROM` / `MOD_TO` existent depuis 5.2) ; seules les DTD et RNG de 5.2 et 6.0 ne les
  listent pas (ajoutés par 6.1, sans changement de version XML). C'est le seul écart de schéma admis par le banc.
- année négative dans une plage ou un intervalle (`<daterange start="-0120" …>`) : l'import de 5.2 ne la lit pas
  et en fait une date textuelle portant l'élément XML (corrigé en 6.0). L'export 1.7.1 le **signale**
  (`avertissements_dates` du résultat d'`arbre_exporter`) ; Gramps 6.0 et 6.1 la lisent.
- `<dateval val="">` fait échouer l'import de 5.2 : **jamais écrit** (une date sans valeur n'est pas écrite,
  comme chez Gramps).
- date textuelle au texte vide : lue, mais absente du réexport de 5.2.

### Types et versions de Gramps (#273)

Types standard par version (référentiel `referentiels/types_gramps.json`, tiré des sources de Gramps ; détail et
règle de lecture : [Gramps Web](gramps-web.md#types-personnalisés-et-libellés-français-273)) : de 5.2 à 6.0, seuls
huit rôles d'événement s'ajoutent (Father, Mother, Parent, Child, Multiple birth, Friend, Neighbor, Officiator) ;
rien de 6.0 à 6.1. Genealogiste écrit ces rôles en type standard ; en Gramps XML, un type standard s'écrit par sa
chaîne XML anglaise. Constaté avec la bibliothèque (cas `types` du banc, 2026-11-21) :

- Gramps 6.0.8 et 6.1.0-beta2 lisent les huit rôles comme types **standard** ;
- Gramps 5.2.4 les lit comme rôles **personnalisés** portant la même chaîne (« Father »…) : aucune perte, la
  chaîne revient telle quelle au réexport, mais ce ne sont pas des types standard pour 5.2 (filtres, traduction).
  Pas de repli vers un autre rôle : relus par Genealogiste, ils redonnent les rôles du modèle ;
- un type personnalisé en français (« Baptême », « Témoin », « Paroisse », attribut « Âge ») reste personnalisé
  dans les trois versions : Gramps ne traduit jamais une chaîne XML à l'import. Genealogiste le lit comme le type
  standard qu'il désigne (`BAPM`, `WITN`, âge), et `non_repris` ne le compte pas comme perdu.

### Contenu écrit

Le XML est produit depuis les objets Gramps du module de correspondance unique (`gramps/mapping.py`) et en écrit
**tout le contenu** (`export/gramps_xml.py`, tables `SPEC_*` : un champ JSON ↔ un attribut ou un élément, dans
l'ordre du DTD) : `priv` à chaque niveau, étiquettes, attribut `change`, noms (groupe, tri, affichage, origine et
connecteur des patronymes), noms alternatifs datés et localisés des lieux, références de lieux datées, adresses,
URL, ordonnances LDS, attributs, rectangles des références de médias, texte stylé et format des notes, dates
complètes (double datation, nouvel an, jour sans mois, date composée à un seul bout, comme `write_date` de Gramps).
Restent hors du fichier, comme chez Gramps : `Date.text` (sauf date texte) et `Date.sortval`, recalculés, et
`birth_ref_index`/`death_ref_index`, que Gramps déduit de l'ordre des références d'événement (la référence
retenue passe en tête quand Gramps ne la retrouverait pas sinon). Les sections hors objets (`<people home>`,
signets, `namemaps`) ont leur point d'extension (`Metadonnees`), vide tant que Genealogiste ne les gère pas.

### Paquet .gpkg

`arbre_exporter("gpkg")` écrit une archive tar gzip, comme Gramps : chaque fichier de média local, sous un chemin
relatif, puis `data.gramps` (le XML, gzippé). Les médias sont résolus par la règle commune des médias
(`chemins.localiser` : répertoire de données, répertoire des médias, arborescence des pièces ; ni chemin hors de
ces racines, ni traversée `..`, ni lien symbolique sortant, ni composant caché comme `.env`) ; dans le XML, `src`
désigne le chemin relatif du fichier dans l'archive. Fichiers introuvables, refusés ou ambigus : listés dans
`medias.manquants` du résultat, jamais empaquetés (seul leur nom de fichier reste dans le XML) ; adresses web dans
`medias.distants`. Les médias d'une personne masquée (vivants, objets privés) sont retirés par la projection de
publication avant l'empaquetage. Archive déterministe (date nulle, propriétaire 0, membres triés), écrite à côté
puis renommée. À l'import, Gramps extrait les médias dans `<dossier des médias>/<nom>.gpkg.media/`.

## Import depuis Gramps Desktop

`arbre_importer_gedcom(chemin, mode)` (commande `/genealogiste:import`) lit aussi les fichiers de Gramps
Desktop. Le format est reconnu **au contenu**, jamais à l'extension : GEDCOM, Gramps XML (`.gramps`,
compressé gzip comme Gramps l'écrit par défaut, ou non) ou paquet `.gpkg` (tar gzip : `data.gramps` et les
fichiers des médias). Même nom d'outil, même classe de permission (proposition) et même contrat que l'import
GEDCOM : modes `ajouter` (renumérotation de toutes les références, doublons à recouper par
`/genealogiste:recoupe`) et `remplacer`, diff et jeton, **rien n'est écrit sans accord explicite**
(`arbre_appliquer`). En mode `gramps`, la proposition est une transaction Gramps Web, comme pour un GEDCOM.

### Versions acceptées

| Fichier | Résultat |
|---|---|
| Gramps XML 1.7.1 (Gramps 5.2) et 1.7.2 (Gramps 6.0, 6.1), espace de noms `http(s)://gramps-project.org/xml/<version>/` | lu |
| Gramps XML 1.8.0 (objets ADN, branche master de Gramps, non publiée) | **refusé**, message explicite |
| autre version (1.6.0 et antérieures, 2.x…), autre hôte (`www.gramps-project.org`), espace de noms absent ou étranger | **refusé** : la lecture des versions anciennes n'est pas vérifiée |
| en-tête sans `<created version>` | **refusé**, comme par Gramps lui-même |

### Un seul chemin de conversion

Gramps XML → objets Gramps JSON → modèle Genealogiste. Le lecteur (`gramps/lecture_xml.py`) est le symétrique
de l'export : il parcourt les **mêmes** tables `SPEC_*` (`Champ.genre`, `Conv.lire`), sans seconde table de
correspondance. Les objets obtenus passent par `gramps_to_tree` (`gramps/mapping.py`), le module de
correspondance du mode direct ; l'arbre obtenu suit ensuite exactement le chemin de l'import GEDCOM
(opération `remplacer_arbre`). Conséquences :

- les `gramps_id` de Gramps (`I0001`, `F0001`, `S0001`, `R0001`, `O0001`, `N0001`) deviennent les identifiants de
  Genealogiste ; un identifiant vide, invalide comme référence GEDCOM (espace, `@`) ou en double (Gramps
  l'admet) reçoit un identifiant libre (`IX1`…), listé dans `import.identifiants_reattribues` ;
- marqueurs reconnus : attributs `Genealogiste-*` et leur forme historique `Sosa-*` (UID, statuts, intervenants,
  fichier), étiquettes `Genealogiste:auto` / `Sosa:auto` (notes générées ignorées) ;
- étiquettes de l'utilisateur (#262) reprises sur les personnes, familles, événements, citations, sources,
  dépôts, médias et notes partagées (extension GEDCOM `_ETIQUETTE`) ; celles des lieux et des notes « en
  ligne », et une étiquette qui n'étiquette rien, restent comptées dans `non_repris` (couleur et priorité ne
  sont pas reprises : l'arbre ne garde que les noms) ;
- le drapeau `priv` de Gramps devient `prive` là où le modèle le porte (personne, famille, événement, source,
  citation, média, note) ; l'import ne pose ni ne retire aucune protection. Il est local : rien ne part vers
  l'extérieur ;
- reconstruit comme Gramps à l'import, faute d'être dans le XML : `birth_ref_index` / `death_ref_index`
  (première référence d'un événement Birth / Death de rôle Primary), `Date.sortval` (sept calendriers de Gramps
  et nouvel an ; 202 dates comparées à Gramps 6.0.8), valeur entière de la taille de police d'une note stylée.

### Médias

- `.gramps` : les chemins des médias sont repris **tels quels**, fichiers non copiés. Ils sont relatifs au
  dossier des médias de Gramps (`<mediapath>`), que Genealogiste ne reprend pas (compté dans `non_repris`).
- `.gpkg` : les fichiers sont extraits dans une **zone d'attente** neuve du répertoire de données,
  `<données>/imports/gramps/<nom>-<AAAAMMJJ-HHMMSS>/`, et le chemin de chaque média de la proposition y est
  relocalisé (`import.medias.fichiers`). Rien n'est rangé dans le vault ni déplacé. Une fois l'import appliqué,
  les ranger selon la convention : `pieces_proposer(dossier=<zone_attente>, suivre_medias=true)` (plan), puis,
  après accord, `pieces_appliquer` et la proposition `modifier_media` qui suit ([pièces](pieces.md)). Un
  import refusé ne laisse aucune zone ; une proposition abandonnée laisse la sienne, à supprimer à la main.
  Limite : un paquet dont un membre porte un nom non portable (chemin absolu Windows `C:\…`, antislash) est
  refusé en entier, comme un nom dangereux ; ranger les médias sous le dossier des médias de Gramps (chemins
  relatifs) avant d'exporter.

### Ce que l'arbre ne reprend pas

Le modèle de Genealogiste (celui de GEDCOM 7) ne représente pas tout ce que Gramps sait écrire. Ce qui n'en
fait pas partie n'est pas importé, **dans les deux modes** (l'import passe par le modèle), et n'est jamais
perdu en silence : `import.non_repris` compte les valeurs en moins **par chemin de champ Gramps**, en comparant
le fichier lu à ce que l'arbre importé redonnerait (`Person.address_list[]: 1`, `Note.text.tags[]: 38`,
`Place.alt_names[]: 8`, `Métadonnées.signets: 4`…), et la proposition porte un avertissement. C'est un
compteur, pas un diff : une valeur gardée sous une autre forme (hiérarchie de lieux aplatie en titre
« Commune, Département, Pays ») est comptée sous son ancien chemin. Sur l'arbre d'exemple de Gramps, par exemple :
étiquettes des lieux, noms alternatifs et noms datés des lieux, hiérarchie et types de lieux, adresses, URL,
texte stylé, ordonnances LDS, attributs utilisateur (âge, profession…), suffixe, titre et nom d'usage,
patronymes multiples, rectangles des références de médias, notes privées, plusieurs dépôts d'une source, et
les métadonnées (chercheur, dossier des médias, personne de référence, formats de noms, signets,
regroupements). Leur reprise relève du lot 2 du jalon M6 (#277, #279) ; les étiquettes des autres
objets sont reprises depuis #262, et un type personnalisé qui est le libellé d'un type standard (« Baptême »,
attribut « Âge ») est repris comme ce type depuis #273 (un attribut est compté sous son type standard). Dates d'événement (#272) : toutes les formes de Gramps sont reprises à
l'identique ; une forme qui ne le serait pas (double datation sur un point sans année) est comptée sous
`Event.date[forme non reprise]`. Comme l'import de Gramps, une date que `Date.set` refuse (30 février, plage au
début vide…) devient une date textuelle portant l'élément XML, et une date à double datation passe en julien.

### Aller-retour sans perte

Gramps XML → objets Gramps → Gramps XML redonne le même document, après cette normalisation
(`lecture_xml.comparer_xml`) : mise en forme (espaces entre éléments, indentation), ordre des attributs, ordre
des objets dans une section (Gramps les trie par handle, Genealogiste par identifiant) et élément `<created>`
(date et version de Gramps qui a écrit le fichier). Le texte et les valeurs comptent, espaces compris. Vérifié
sur `gramps-objets-riches.json` (octet pour octet), sur l'export de chaque fixture du dépôt, sur le réexport
de chaque bibliothèque Gramps et sur les deux arbres d'exemple de Gramps (`example.gramps`, 2 157 personnes, et
`data.gramps`, commit `2153e4fa4b0e4ddf7542f1c064c7820bc345a482`). Ce qui n'est pas rendu à l'identique :

- l'élément `<created>` (réécrit : date du jour, version 5.2.0 ou 6.0.0 selon la version XML) ;
- l'ordre des objets d'une section, l'ordre des enfants d'un objet (ramené à celui du DTD, que Gramps suit
  déjà), la mise en forme, les commentaires XML ;
- l'attribut `default` de `<people>` (ignoré par Gramps aussi ; signalé dans `import.avertissements`) ;
- une personne sans `<name>` (Gramps en écrit toujours un) reçoit un nom vide ;
- double datation d'une date composée : un seul attribut `dualdated` pour les deux bouts, comme chez Gramps ;
- handles : seul le `_` initial est retiré (l'importeur de Gramps les retire tous ; jamais rencontré dans un
  fichier de Gramps).

Élément, attribut ou section inconnus du schéma (1.7.1 / 1.7.2), texte égaré, handle en double : **refus
explicite** avec la ligne, plutôt qu'un abandon muet (Gramps, lui, les ignore). Choix fait pour ne rien perdre
sans le dire ; un fichier écrit par Gramps 5.2 à 6.1 n'en contient pas.

## Ce que la CI vérifie

Workflow `Intégration Gramps`, un job `Gramps Desktop <version>` par version (voir
[Gramps Web](gramps-web.md#lancer-la-matrice) pour les déclencheurs). Pour chaque arbre synthétique du dépôt
(`mcp/tests/fixtures/famille.ged`, `legacy551.ged`, `geneweb7_gwb2ged.ged`) et chaque forme de fichier
(`CAS` : `xml-1.7.1`, `xml-1.7.2`, `gramps-gzip`, `gpkg` avec un média local au nom accentué) :

1. export par Genealogiste ; l'export doit contenir exactement les objets du modèle Gramps de Genealogiste ;
2. **validité DTD et RNG** contre les schémas livrés avec la bibliothèque testée (`data/grampsxml.dtd`, `.rng`),
   étiquette ramenée à celle du schéma (1.7.2 pour les trois versions) ;
3. `xml-1.7.2` dans Gramps 5.2 : **refus attendu** (« older version ») ;
4. import par la bibliothèque `gramps` dans une base SQLite en mémoire (`import_as_dict`, sans interface, plugin
   choisi selon l'extension) : **aucune erreur ni avertissement** de Gramps (pour un `.gpkg`, seul l'avertissement
   « Base path for relative media set » est admis) ;
5. **mêmes objets, classe par classe** : personnes, familles, événements, sources, citations, lieux, notes,
   dépôts, médias, étiquettes ; mêmes nombres et **mêmes handles** (Gramps renumérote les identifiants `I…`
   selon ses préférences ; les handles, eux, sont conservés) ;
6. Gramps 6.0 et 6.1 : **chaque objet importé identique, champ par champ**, à l'objet Gramps exporté (format JSON
   `object_to_dict`), hors identifiants renumérotés, date de modification nulle remplacée par celle du fichier et
   champs recalculés (`Date.sortval`, `Date.text`, somme de contrôle) ;
7. `.gpkg` : le média empaqueté est retrouvé par Gramps à son chemin relatif après extraction ;
8. aller-retour : réexport en Gramps XML par Gramps (`GrampsXmlWriter`), mêmes nombres et mêmes handles ;
9. sens inverse (#269, `controle_lecture`) : ce réexport est **relu par l'import de Genealogiste** ; aller-retour
   XML sans perte (normalisation ci-dessus) ; en 6.0 et 6.1, chaque objet relu identique champ par champ à
   l'objet importé par Gramps, `gramps_id`, `change` et `Date.sortval` compris (seuls écarts admis : ceux de
   l'écriture de Gramps, qui retire les espaces de début et de fin des valeurs et calcule la somme de contrôle
   d'un média) ; en 5.2, mêmes handles ;
10. cycle complet (`cycle:<forme>`) : l'objet relu est réécrit par Genealogiste (1.7.1) puis réimporté par la
    bibliothèque : mêmes handles et, en 6.x, mêmes objets champ par champ que le premier import ;
11. arbre fictif écrit par la bibliothèque elle-même (`desktop:famille.gramps`, gzip, et `desktop:famille.gpkg`,
    `PackageWriter`, avec un média) : relu par Genealogiste (version et format détectés, objets identiques à
    ceux que Gramps importe, hors `gramps_id` que Gramps renumérote) ; import complet (`Genealogiste-*`,
    `Sosa-*`, `Sosa:auto`, privé, témoin, statuts, média extrait, pertes listées) ; puis cycle complet. Ces
    fichiers sont les fixtures `mcp/tests/fixtures/gramps-desktop/` (`--fixtures` pour les régénérer) ;
12. arbres d'exemple de Gramps (`exemple`), téléchargés au commit de la bibliothèque 6.1 et vérifiés par
    empreinte SHA-256, jamais copiés dans le dépôt : aller-retour XML sans perte ; en 6.x, objets relus
    identiques à ceux que Gramps importe de l'original ; réécriture 1.7.1 réimportée par chaque version (5.2
    comprise, qui refuse l'original en 1.7.2) avec les mêmes objets. `--sans-exemple` pour s'en passer.
13. dates (#272) : cas `dates`, un événement par forme de date de l'inventaire (`mcp/tests/dates_gramps.py`,
    1 220 formes écrites en XML : 7 calendriers, tous les modificateurs et qualités, double datation, nouvel an,
    jour sans mois, année inconnue ou négative, bout vide, dates textuelles) exporté en 1.7.1 ; chaque date
    revient du réexport de Gramps, relue par Genealogiste, **identique**, repasse par le modèle à l'identique et
    redonne la même date GEDCOM 7 (`controle_dates`) ; en 6.x, valeur de tri de Gramps = celle de Genealogiste.
    Seuls écarts admis, nommés dans `ECARTS_DATES` et comptés à chaque exécution : limites du format XML (un
    seul `dualdated` par plage ; espaces de bord d'un texte retirés par l'écriture de Gramps) et pièges de 5.2
    (ci-dessus). Validation DTD/RNG stricte, `from`/`to` exceptés pour 5.2 et 6.0. Puis `dates:reference` : les
    1 225 formes soumises à `Date.set` de la bibliothèque (acceptée ou refusée comme `date_acceptee`, même
    valeur de tri, même affichage `DateDisplayEn`), et les formes que Gramps refuse (`REFUSEES`) importées par
    Gramps comme Genealogiste les lit. `--fixtures` écrit la référence `dates-gramps-<version>.json`.
14. types (#273) : cas `types`, un baptême dont dix intervenants de l'arbre portent les huit rôles de Gramps 6.0,
    le témoin et le parrain, plus des types personnalisés saisis en français (événements « Baptême » et
    « Recensement », rôle « Témoin », attribut de référence « Âge », lieu « Paroisse »), exporté en 1.7.1. La
    sonde relève chaque type importé (classe, chaîne XML, personnalisé ou non, par l'API de la bibliothèque, 5.2
    comprise) : rôles de 6.0 standard en 6.x et personnalisés en 5.2, libellés français personnalisés partout
    (`controle_types`) ; le réexport de Gramps, importé par Genealogiste, redonne `BAPM`, `CENS`, les dix rôles du
    modèle et l'âge, sans perte due à un type.

Résultat du 2026-11-21 (#273) : 102 vérifications sur 102 réussies, dont les 6 du cas `types` (import et cycle
pour 5.2, 6.0 et 6.1). Résultat du 2026-11-21 (#272) : 96 vérifications sur 96 réussies en local (GLib factice) pour 5.2, 6.0 et 6.1 :
39 imports des formes de l'export (dont 3 refus attendus de 1.7.2 par Gramps 5.2, et le cas `dates` : 1 233
dates relues sans écart non nommé par version), 36 cycles, 12 sur l'arbre fictif (lecture et cycle), 3 références
de dates (1 225 formes chacune, aucun écart) et 6 arbres d'exemple. Écarts connus comptés : 5.2, 14 plages à
année négative, 1 date textuelle vide ; toutes versions, 2 plages à double datation d'un seul bout, 1 texte aux
espaces de bord.

| Arbre | Personnes | Familles | Événements | Sources | Citations | Lieux | Notes | Dépôts | Étiquettes |
|---|---|---|---|---|---|---|---|---|---|
| `famille.ged` | 8 | 3 | 13 | 4 | 10 | 3 | 26 | 1 | 6 |
| `legacy551.ged` | 1 | 1 | 3 | 0 | 0 | 1 | 5 | 0 | 2 |
| `geneweb7_gwb2ged.ged` | 8 | 4 | 13 | 7 | 8 | 3 | 27 | 0 | 4 |

Hors CI : objets Gramps riches couvrant chaque champ (`mcp/tests/fixtures/gramps-objets-riches.json`) ; les tests
unitaires (`tests/test_gramps_xml_export.py`) vérifient que tout y est écrit et que le fichier est valide au
schéma 1.7.1 (Gramps 5.1, copié dans `mcp/tests/fixtures/gramps-xml/`) et 1.7.2 (Gramps 6.1). Essai manuel du
2026-11-21 : importés sans erreur par Gramps 5.2.4 (1.7.1), ils reviennent de Gramps 6.0.8 et 6.1.0-beta2
(1.7.1 et 1.7.2) identiques champ par champ, sauf trois cas que Gramps ne sait pas représenter : date composée sans début (relue comme date texte),
décès retenu qui n'est pas un événement *Death* (non retenu), ordre des références quand la naissance retenue
n'est pas la première (réordonné). L'export `.gpkg` de Gramps lui-même est vérifié depuis #269 (point 11 :
`PackageWriter` lancé avec un module Gtk factice, la boîte de dialogue n'étant pas utilisée).

## Lancer la vérification

```bash
make test-gramps-desktop                      # 5.2, 6.0 et 6.1
make test-gramps-desktop GRAMPS_DESKTOP=6.0   # une version ; plusieurs : GRAMPS_DESKTOP="5.2 6.1"
make test-gramps-desktop GI=systeme PYTHON=/usr/bin/python3   # PyGObject du système, comme la CI
```

Chaque version est installée dans un environnement Python isolé, dans
`~/.cache/genealogiste/gramps-desktop/` (`--cache` pour un autre dossier), jamais dans `mcp/.venv` ni
`mcp/uv.lock`. Réseau nécessaire au premier lancement (PyPI, GitHub), réutilisé ensuite. Le script
(`scripts/verifier_gramps_desktop.py`) fait tourner la sonde `scripts/sonde_gramps_desktop.py` dans cet
environnement ; elle n'importe que la bibliothèque standard et `gramps`.

### Gramps sans interface

- Gramps 5.2 et 6.0 importent `gi.repository.GLib` (PyGObject) dès le démarrage, même en ligne de commande.
  La CI installe les paquets système `python3-gi`, `gir1.2-glib-2.0` et `gir1.2-gtk-3.0` et crée les
  environnements avec `--system-site-packages` (`GI=systeme` : le vrai PyGObject est exigé). Sans PyGObject, la
  sonde fournit un module `GLib` factice limité aux chemins de l'utilisateur ; le rapport indique le mode
  (`gi systeme` ou `gi factice`).
- L'export XML de Gramps importe les boîtes d'options GTK de son interface (`gramps.gui.plug.export`), sur
  toutes les versions. La sonde les remplace toujours par un module factice : l'écriture du fichier est testée,
  pas la boîte de dialogue d'export.
- Gramps 6.1 est lancé depuis ses sources sans compiler les traductions (`msgfmt` inutile) : ressources prises
  dans `data/` (`GRAMPS_RESOURCES`), messages en anglais.

### Étendre la vérification

`scripts/verifier_gramps_desktop.py` expose deux points d'extension :

- `CAS` : formes de fichier remises à Gramps (`Cas(nom, description, produire, refus_attendu, enrichir,
  avertissements_admis, arbres, schema_admis)`) ; `refus_attendu` liste les versions qui doivent refuser le
  fichier (1.7.2 dans Gramps 5.2), `enrichir` ajoute à l'arbre ce que le cas exige (média du `.gpkg`, formes de
  date), `arbres` restreint le cas à certains arbres, `schema_admis` nomme l'écart de schéma admis par version ;
- `CONTROLES` : contrôles supplémentaires sur chaque import réussi (réexport de Gramps, médias, champs,
  relecture par l'import de Genealogiste, `controle_lecture`, qui prépare le cycle complet, et dates,
  `controle_dates`) ;
- `ECARTS_DATES` : écarts connus de Gramps sur les dates, par version (`*` : toutes), chacun avec la date que
  Gramps rend réellement ; tout autre écart échoue.

La sonde sait aussi construire l'arbre fictif par l'API de Gramps et l'exporter (`--generer`) ; le banc
télécharge les arbres d'exemple épinglés (`EXEMPLE` : commit et empreintes).

Une nouvelle version de Gramps s'ajoute dans `compatibilite-gramps.json`, `GRAMPS_DESKTOP_TESTES` et cette
page ; le test `tests/test_compatibilite_gramps.py` signale tout oubli.
