---
description: Fact-check indépendant d'une personne ou d'un fait (agent vérificateur)
argument-hint: <id> [fait : BIRT|DEAT|MARR|filiation|nom|uid]
---
Vérification indépendante : **$ARGUMENTS**

1. Identifier la personne (`arbre_recherche` si besoin) et le fait (tous les faits si non précisé).
2. Lancer l'agent **`verificateur`** avec UNIQUEMENT : l'identifiant, le fait à vérifier et la consigne de
   rendre un verdict. Ne lui transmettre **aucune** conclusion, résumé ou hypothèse issus d'une recherche
   précédente de cette conversation.
3. Restituer son verdict : statut, pièces retenues/écartées, contradictions, homonymes examinés, écarts avec
   l'arbre, prochaine source.
4. Si le verdict diffère de l'arbre (citation à compléter, version à réfuter), proposer les opérations
   (`arbre_proposer`) et n'appliquer qu'après accord explicite.
