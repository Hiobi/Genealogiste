---
description: Arbre ascendant (numérotation Sosa) en tableau et Mermaid
argument-hint: <id> [générations=4]
---
Ascendance de : **$ARGUMENTS**

1. `arbre_ascendance(id, n, "liste")` puis `arbre_ascendance(id, n, "mermaid")`.
2. Afficher le tableau Sosa (n°, nom, dates) et le diagramme Mermaid dans un bloc ```mermaid.
3. Indiquer les ancêtres manquants (n° Sosa vides) par génération et le taux de complétude ; pour les deux
   ou trois branches les plus prometteuses, la prochaine source (`arbre_lacunes`).
4. Proposer l'export SVG (`arbre_exporter("svg_asc", id=…)`). Vivants masqués.
