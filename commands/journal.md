---
description: Historique des recherches (journal) et des modifications de l'arbre
argument-hint: [source|id personne|texte] [nombre]
---
Journal : **$ARGUMENTS**

1. `journal_lister(...)` avec le filtre déduit des arguments (source connue : matchid, wikitree, gallica,
   wikidata, geo, cog, geneanet… ; identifiant I… ; sinon recherche texte).
2. Afficher un tableau chronologique : date, source, opération, paramètres clés, statut
   (positif / **négatif** / erreur / manuel), nombre de résultats.
3. Si pertinent, ajouter les derniers commits de l'arbre (`arbre_historique`) avec leur justification.
4. Signaler les recherches à refaire (erreurs) et les sources jamais interrogées pour la personne.
