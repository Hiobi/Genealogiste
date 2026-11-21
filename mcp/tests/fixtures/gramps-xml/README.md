# Schémas Gramps XML (DTD et RELAX NG), copies de test

Fichiers du projet Gramps (https://github.com/gramps-project/gramps), répertoire `data/`, copiés sans
modification pour valider l'export Gramps XML de Genealogiste (`tests/test_gramps_xml_export.py`).
Licence : GNU GPL version 2 **ou toute version ultérieure** (en-tête conservé dans chaque fichier), donc
utilisables dans ce dépôt sous GPL-3.0-or-later. Ils ne servent qu'aux tests et ne sont pas distribués avec
le serveur.

| Dossier | Version XML | Origine | SHA-256 |
|---|---|---|---|
| `1.7.1/` | 1.7.1 (schéma lu et écrit par Gramps 5.1 ; étiquette de Gramps 5.2) | tag `v5.1.6` (`ddfc8894`), `data/grampsxml.dtd` et `data/grampsxml.rng` | dtd `c7e4f54f…d295c`, rng `3f3e2436…3c35f` |
| `1.7.2/` | 1.7.2 (Gramps 6.0, 6.1 ; avec les modificateurs de date `from`/`to` ajoutés en 6.1) | tag `v6.1.0-beta2` (`2153e4fa4b0e4ddf7542f1c064c7820bc345a482`, branche `maintenance/gramps61`) | dtd `2bf00e50…be2`, rng `66407f42…be72` |

Le schéma 1.7.2 de la branche `maintenance/gramps60` ne diffère de celui-ci que par l'absence de
`from`/`to` dans `dateval/@type`. Le schéma 1.8.0 (branche `master`, objets ADN) n'est pas publié : non copié.
