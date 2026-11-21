# Gramps Desktop : compatibilité des fichiers Gramps XML

`arbre_exporter` (format `gramps`) écrit du **Gramps XML 1.7.1 non compressé** par défaut, à importer dans
Gramps Desktop (Arbres familiaux > Importer) ou dans Gramps Web. Options (#268) : `version_xml="1.7.2"` (Gramps
6.x seulement), `compresse=True` (`.gramps` gzip, forme native de Gramps Desktop) et format `gpkg` (paquet
Gramps : XML et fichiers des médias, voir [plus bas](#paquet-gpkg)). Cette page dit quelles versions de Gramps Desktop relisent ce
fichier et ce que la CI vérifie. Pour le mode direct sur Gramps Web (API, versions d'images) : voir
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
8. aller-retour : réexport en Gramps XML par Gramps (`GrampsXmlWriter`), mêmes nombres et mêmes handles.

Résultat du 2026-11-21 : 36 vérifications sur 36 réussies en local (GLib factice ; 3 versions × 3 arbres × 4
formes, dont 3 refus attendus de 1.7.2 par Gramps 5.2).

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
n'est pas la première (réordonné). Non vérifié : l'import d'un fichier Gramps dans Genealogiste (#269), l'export
`.gpkg` de Gramps lui-même (exige GTK).

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
  avertissements_admis)`) ; `refus_attendu` liste les versions qui doivent refuser le fichier (1.7.2 dans
  Gramps 5.2), `enrichir` ajoute à l'arbre ce que le cas exige (média du `.gpkg`) ;
- `CONTROLES` : contrôles supplémentaires sur chaque import réussi (le réexport de Gramps y est déjà comparé),
  par exemple relire ce réexport avec l'import Gramps XML de Genealogiste (#269).

Une nouvelle version de Gramps s'ajoute dans `compatibilite-gramps.json`, `GRAMPS_DESKTOP_TESTES` et cette
page ; le test `tests/test_compatibilite_gramps.py` signale tout oubli.
