---
description: Importer un GEDCOM (5.5.1/7) ou un export FamilySearch
argument-hint: <chemin.ged> [ajouter|remplacer]
---
Import : **$ARGUMENTS**

- **Fichier GEDCOM** : `arbre_importer_gedcom(chemin, mode)` (défaut `ajouter`, renumérotation).
- **FamilySearch** : l’ancien exporteur est désactivé pour sécurité. Importer un GEDCOM obtenu
  séparément ; ne jamais demander d’identifiants FamilySearch.
- **Gramps Web** (mode fichier) : `gramps_tirer(mode)` lit l'arbre Gramps Web par l'API. Pour travailler en
  direct sur Gramps Web, `GENEALOGISTE_BACKEND=gramps` ; pour y envoyer l'arbre local une fois pour toutes :
  `gramps_bascule_proposer` puis, après accord, `gramps_bascule_appliquer` (docs/gramps-web.md).

Présenter le bilan (version, personnes, familles, sources, avertissements) et un extrait du diff ; rappeler
que les données importées sont **composites/non vérifiées**. Appliquer seulement après accord explicite.
Ensuite : `arbre_coherence()` et proposer `/genealogiste:recoupe` sur les doublons probables (même nom ± 2 ans).
