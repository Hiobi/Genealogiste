---
description: Recherche multi-sources d'une personne, résultats classés par score de correspondance
argument-hint: <nom> [prénom] [né vers] [lieu]
---
Recherche généalogique : **$ARGUMENTS**

Applique la skill `methodologie-gps`. Délègue la recherche à l'agent `chercheur` si elle demande plusieurs
sources ou variantes ; sinon :

1. Interpréter les arguments (nom, prénom, date approximative « né vers », lieu) ; demander une précision
   seulement si le nom manque. Si la personne existe dans l'arbre (`arbre_recherche`), utiliser son id
   (`personne=`) et refuser toute recherche externe si elle est présumée vivante.
2. `recherche_multi(nom, prenom, ne_vers, lieu)` puis, si utile, variantes (`normaliser_nom`, latin, « dit »)
   et sources ciblées.
3. Présenter un tableau classé par score : source, identité, naissance, décès, score et raisons principales,
   classification de la source (originale/dérivée/composite), lien. Signaler les **homonymes probables**.
4. Lister les recherches négatives et les liens des sources secondaires (`liens_recherche`) à consulter par
   l'utilisateur (Geneanet, AD, Mémoire des hommes…) ; proposer de coller le résultat (`source_collee`).
5. Terminer par la prochaine source à consulter. Ne rien écrire dans l'arbre sans `/genealogiste:ajoute`.
