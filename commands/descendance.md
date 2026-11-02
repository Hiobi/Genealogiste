---
description: Arbre descendant en liste et Mermaid
argument-hint: <id> [générations=3]
---
Descendance de : **$ARGUMENTS**

1. `arbre_descendance(id, n, "liste")` et `arbre_descendance(id, n, "mermaid")`.
2. Afficher la descendance indentée (unions, enfants, dates) et le diagramme Mermaid.
3. Les vivants apparaissent « Vivant » : ne jamais chercher à les identifier.
4. Proposer l'export SVG (`arbre_exporter("svg_desc", id=…)`).
