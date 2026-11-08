---
description: Fusionner deux fiches (ou scinder une fiche) après analyse et validation
argument-hint: <id_conservé> <id_absorbé> | scinder <id>
---
Fusion / scission : **$ARGUMENTS**

1. Toujours commencer par l'analyse `/genealogiste:recoupe` (score, contradictions, pièce reliant les deux mentions).
   Si le verdict n'est pas « même personne » étayé, le dire et ne pas proposer la fusion sans
   insistance explicite de l'utilisateur.
2. Fusion : `fusionner_personnes(conserver, absorber, justification)` — la justification cite la pièce
   décisive. Scission : `scinder_personne(id, evenements=[uid…], familles_parents, familles_conjoint,
   justification)`.
3. `arbre_proposer` → présenter le diff complet et les nouvelles alertes → accord explicite →
   `arbre_appliquer(jeton)`.
