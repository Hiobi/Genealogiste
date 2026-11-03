---
description: Importer un GEDCOM (5.5.1/7) ou un export FamilySearch
argument-hint: <chemin.ged | familysearch ID1 [ID2…]> [ajouter|remplacer]
---
Import : **$ARGUMENTS**

- **Fichier GEDCOM** : `arbre_importer_gedcom(chemin, mode)` (défaut `ajouter`, renumérotation).
- **FamilySearch** : `familysearch_exporter(ids, ascendants, descendants)` (identifiants dans le `.env`
  du répertoire de données ; l'utilisateur confirme), puis `arbre_importer_gedcom(fichier, "ajouter")`.
- **Gramps Web** (mode fichier) : `gramps_tirer(mode)` lit l'arbre Gramps Web par l'API. Pour travailler en
  direct sur Gramps Web, `GENEALOGISTE_BACKEND=gramps` ; pour y envoyer l'arbre local une fois pour toutes :
  `gramps_bascule_proposer` puis, après accord, `gramps_bascule_appliquer` (docs/gramps-web.md).

Présenter le bilan (version, personnes, familles, sources, avertissements) et un extrait du diff ; rappeler
que les données importées sont **composites/non vérifiées**. Appliquer seulement après accord explicite.
Ensuite : `arbre_coherence()` et proposer `/gen:recoupe` sur les doublons probables (même nom ± 2 ans).
