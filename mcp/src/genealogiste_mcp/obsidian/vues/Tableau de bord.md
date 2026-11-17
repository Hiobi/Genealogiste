---
type: tableau_de_bord
---
# Tableau de bord généalogique

Requêtes **Dataview** (extension communautaire) sur les fiches générées par Genealogiste. Sans Dataview,
ouvrir plutôt `Genealogiste.base` (Obsidian Bases, intégré). Fichier remplacé par les versions suivantes
tant qu'il n'est pas modifié ; une copie modifiée est conservée.

## Ascendance (Sosa)

```dataview
TABLE sosa AS "Sosa", naissance, deces, statut
WHERE type = "personne" AND sosa
SORT sosa ASC
```

## À reprendre : preuve faible

```dataview
TABLE statut, sosa AS "Sosa", naissance, deces
WHERE type = "personne" AND contains(list("non_source", "hypothese", "contradictoire", "refute"), statut)
SORT sosa ASC, file.name ASC
```

## Personnes sans aucune source

```dataview
LIST
WHERE type = "personne" AND !vivant AND length(sources) = 0
SORT file.name ASC
```

## Recherches en cours

```dataview
TABLE personne, date, etat
WHERE type = "recherche" AND etat != "close" AND !contains(file.folder, "_genealogiste")
SORT date DESC
```

## Courriers sans réponse

```dataview
TABLE destinataire, envoye_le, objet
WHERE type = "courrier" AND envoye_le AND !reponse_le AND !contains(file.folder, "_genealogiste")
SORT envoye_le ASC
```

## Fiches mises à jour récemment

```dataview
TABLE type, mis_a_jour
WHERE mis_a_jour
SORT mis_a_jour DESC
LIMIT 20
```
