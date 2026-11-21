---
description: Importer un GEDCOM (5.5.1/7), un fichier Gramps Desktop (.gramps, .gpkg) ou un export FamilySearch
argument-hint: <chemin.ged|.gramps|.gpkg> [ajouter|remplacer]
---
Import : **$ARGUMENTS**

- **Fichier GEDCOM** : `arbre_importer_gedcom(chemin, mode)` (défaut `ajouter`, renumérotation).
- **Gramps Desktop** : le même outil lit un Gramps XML `.gramps` (1.7.1 ou 1.7.2, compressé ou non) ou un
  paquet `.gpkg`, format reconnu au contenu ; Gramps XML 1.8.0 et versions inconnues sont refusés. Présenter
  aussi `import.non_repris` (ce que l'arbre ne représente pas : étiquettes, adresses, texte stylé, lieux
  hiérarchiques… non importés ; un type personnalisé en français, « Baptême », « Témoin », « Âge », est repris
  comme le type standard qu'il désigne) et, pour un `.gpkg`, `import.medias` : fichiers extraits dans une zone
  d'attente du répertoire de données, jamais rangés sans accord. Après application, proposer de les classer
  avec `pieces_proposer(dossier=<zone_attente>, suivre_medias=true)` (docs/gramps.md#import-depuis-gramps-desktop).
  Si le fichier porte une personne de référence, présenter `import.personne_reference` (identifiant, état par rapport
  à `GENEALOGISTE_SOSA_RACINE`, suggestion) : ne jamais modifier la configuration ni le `.env` soi-même.
  Si le fichier porte des groupes de noms (`<namemaps>`), présenter `import.regroupements` : lus et rapportés, **jamais appliqués** (aucune personne n'est fusionnée) ; en mode gramps, `gramps_grouper_noms` propose les groupes d'après les patronymes de l'arbre, à poser à la main (docs/gramps-web.md, « Groupes de noms »).
- **FamilySearch** : l’ancien exporteur est désactivé pour sécurité. Importer un GEDCOM obtenu
  séparément ; ne jamais demander d’identifiants FamilySearch.
- **Gramps Web** (mode fichier) : `gramps_tirer(mode)` lit l'arbre Gramps Web par l'API. Pour travailler en
  direct sur Gramps Web, `GENEALOGISTE_BACKEND=gramps` ; pour y envoyer l'arbre local une fois pour toutes :
  `gramps_bascule_proposer` puis, après accord, `gramps_bascule_appliquer` (docs/gramps-web.md).

Présenter le bilan (format et version, personnes, familles, sources, avertissements) et un extrait du diff ;
rappeler que les données importées sont **composites/non vérifiées**. Appliquer seulement après accord explicite.
Ensuite : `arbre_coherence()` et proposer `/genealogiste:recoupe` sur les doublons probables (même nom ± 2 ans).
En mode gramps, `arbre_coherence()` signale aussi les types personnalisés qui doublonnent un type standard
(`type_personnalise_doublon`) : `gramps_normaliser_types` en propose la normalisation (diff, accord, annulable).
