# Fichiers écrits par Gramps Desktop (fictifs)

Arbre **fictif** (Jean DUPONT, Marie MARTIN, Pierre DUPONT, Paul LEROY à Villefictive, archives et sources
inventées) construit par l'API de la vraie bibliothèque Gramps, puis exporté comme Gramps Desktop le fait,
pour l'import Gramps de Genealogiste (#269, `tests/test_gramps_xml_import.py`) :

| Dossier | Bibliothèque | Gramps XML |
|---|---|---|
| `gramps-5.2/` | `gramps==5.2.4` (PyPI) | 1.7.1 |
| `gramps-6.0/` | `gramps==6.0.8` (PyPI) | 1.7.2 |
| `gramps-6.1/` | `v6.1.0-beta2`, commit `2153e4fa4b0e4ddf7542f1c064c7820bc345a482` | 1.7.2 |

- `famille.gramps` : `XmlWriter(db, user, 0, 1)`, Gramps XML compressé gzip (option par défaut « Use
  Compression » de l'export de Gramps Desktop) ;
- `famille.gpkg` : `PackageWriter` (tar gzip : le média `actes/acte fictif é.jpg`, 18 octets fictifs, puis
  `data.gramps`). Noms d'utilisateur et de groupe de la machine retirés du tar ; chemin des médias relatif
  (`medias`).

Contenu (voir `generer` dans `scripts/sonde_gramps_desktop.py`) : attributs `Genealogiste-UID` et forme
historique `Sosa-UID`, `Sosa-Statut`, `Sosa-Statut filiation I0003`, étiquette `Sosa:auto` sur une note générée,
personne privée, témoin de mariage, parrain (`personref`), dates grégoriennes, juliennes et républicaines,
lieux hiérarchiques, et ce que le modèle de Genealogiste ne représente pas (adresse, URL, note stylée,
étiquette, suffixe, nom alternatif daté).

Régénérés le 2026-11-21 par `uv --directory mcp run python ../scripts/verifier_gramps_desktop.py --fixtures`
(bibliothèques isolées du banc Desktop, GLib et Gtk factices) ; les handles et identifiants sont fixes, les
dates de modification sont celles de la génération.

`valeurs-tri-gramps-6.0.8.json` : `[calendrier, jour, mois, année, nouvel an, sortval]` de 202 dates des sept
calendriers, valeurs de tri calculées par `gramps.gen.lib.Date.set` de Gramps 6.0.8 (nombres seulement).
