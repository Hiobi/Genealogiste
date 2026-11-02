---
description: Exporter l'arbre (GEDCOM 7/5.5.1, Gramps XML, Mermaid, SVG, fiche Markdown)
argument-hint: <gedcom7|gedcom551|gramps|mermaid_asc|mermaid_desc|svg_asc|svg_desc|fiche> [id] [générations] [chemin]
---
Export : **$ARGUMENTS**

`arbre_exporter(format, chemin, id, generations, masquer_vivants=True)`. Les personnes présumées vivantes
sont masquées par défaut (RGPD) ; ne désactiver le masquage que sur demande explicite et pour un usage
strictement privé, en le rappelant. Indiquer le fichier produit, le nombre de vivants masqués et, pour
Mermaid/fiche, afficher l'aperçu.
