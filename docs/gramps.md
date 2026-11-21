# Gramps Desktop : compatibilité des fichiers Gramps XML

`arbre_exporter` (format `gramps`) écrit du **Gramps XML 1.7.1 non compressé**, à importer dans Gramps Desktop
(Arbres familiaux > Importer) ou dans Gramps Web. Cette page dit quelles versions de Gramps Desktop relisent ce
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
quelle que soit l'étiquette. Gramps 6.1 ajoute `from`/`to` à sa DTD sans changer de version XML. Le choix de la
version cible et la sortie `.gramps` compressée relèvent de #268.

## Ce que la CI vérifie

Workflow `Intégration Gramps`, un job `Gramps Desktop <version>` par version (voir
[Gramps Web](gramps-web.md#lancer-la-matrice) pour les déclencheurs). Pour chaque arbre synthétique du dépôt
(`mcp/tests/fixtures/famille.ged`, `legacy551.ged`, `geneweb7_gwb2ged.ged`) :

1. export par Genealogiste (`to_gramps_xml`, l'export d'`arbre_exporter`) ; l'export doit contenir exactement
   les objets du modèle Gramps de Genealogiste ;
2. import par la bibliothèque `gramps` dans une base SQLite en mémoire (`import_as_dict`, sans interface) :
   **aucune erreur ni avertissement** de Gramps ;
3. **mêmes objets, classe par classe** : personnes, familles, événements, sources, citations, lieux, notes,
   dépôts, médias, étiquettes ; mêmes nombres et **mêmes handles** (Gramps renumérote les identifiants `I…`
   selon ses préférences ; les handles, eux, sont conservés) ;
4. aller-retour : réexport en Gramps XML par Gramps (`GrampsXmlWriter`), mêmes nombres et mêmes handles.

Résultat du 2026-11-21 : 9 vérifications sur 9 réussies, en local (GLib factice) et en CI (ubuntu-latest, PyGObject
système).

| Arbre | Personnes | Familles | Événements | Sources | Citations | Lieux | Notes | Dépôts | Étiquettes |
|---|---|---|---|---|---|---|---|---|---|
| `famille.ged` | 8 | 3 | 13 | 4 | 10 | 3 | 26 | 1 | 6 |
| `legacy551.ged` | 1 | 1 | 3 | 0 | 0 | 1 | 5 | 0 | 2 |
| `geneweb7_gwb2ged.ged` | 8 | 4 | 13 | 7 | 8 | 3 | 27 | 0 | 4 |

Non vérifié ici : le contenu champ par champ (dates, rôles, attributs), la validité DTD/RNG du fichier (#268),
les médias (aucune fixture n'en contient), l'import d'un fichier Gramps dans Genealogiste (#269).

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

- `CAS` : formes de fichier remises à Gramps (`Cas(nom, description, produire, refus_attendu)`), par exemple
  `.gramps` compressé, `.gpkg` ou version XML cible (#268) ; `refus_attendu` liste les versions qui doivent
  refuser le fichier (1.7.2 dans Gramps 5.2) ;
- `CONTROLES` : contrôles supplémentaires sur chaque import réussi (le réexport de Gramps y est déjà comparé),
  par exemple relire ce réexport avec l'import Gramps XML de Genealogiste (#269).

Une nouvelle version de Gramps s'ajoute dans `compatibilite-gramps.json`, `GRAMPS_DESKTOP_TESTES` et cette
page ; le test `tests/test_compatibilite_gramps.py` signale tout oubli.
