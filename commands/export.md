---
description: Exporter l'arbre (GEDCOM 7/5.5.1, Gramps XML ou .gpkg, Mermaid, SVG, fiche Markdown)
argument-hint: <geneweb|gedcom7|gedcom551|gramps|gpkg|mermaid_asc|mermaid_desc|svg_asc|svg_desc|fiche> [id] [générations] [chemin]
---
Export : **$ARGUMENTS**

`arbre_exporter(format, chemin, id, generations, masquer_vivants=True, version_xml="1.7.1", compresse=False)`. Les personnes présumées vivantes
sont masquées par défaut (RGPD) ; ne désactiver le masquage que sur demande explicite et pour un usage
strictement privé, en le rappelant. Indiquer le fichier produit, le nombre de vivants masqués et, pour
Mermaid/fiche, afficher l'aperçu.

**geneweb** : GEDCOM 5.5.1 pour `ged2gwb` (GeneWeb 7) — citations complètes, statut de preuve et prochaines
sources en notes, témoins et parrains en `ASSO`. Proposer `temoins_en_personnes=True` si l'utilisateur veut
voir les témoins seulement nommés comme fiches dans GeneWeb. Rappeler la commande d'import
(`ged2gwb fichier.ged -o base -f`, voir `docs/geneweb.md`) et que la base GeneWeb est reconstruite à chaque
export.

**gramps** : Gramps XML (`.gramps`), format natif de Gramps / Gramps Web, à préférer au GEDCOM pour Gramps
(son import GEDCOM 7 ignore les extensions `_…`, les témoins d'événement et le détail des OCCU/RESI).
Conserve : URL et type des sources, classification et transcription des citations, témoins/parrains de
l'arbre comme références d'événement avec leur rôle, parrains en associations, notes, statut de preuve
(note de recherche + étiquette « Preuve : … »), coordonnées et code INSEE des lieux. Rappeler qu'un second
import dans un arbre non vide duplique tout (pour travailler en direct sur Gramps Web : docs/gramps-web.md). Pour une instance Gramps Web privée, l'utilisateur peut demander
`masquer_vivants=False`. Garder `version_xml="1.7.1"` (lu par Gramps 5.2, 6.0, 6.1) sauf demande pour
Gramps 6.x seul (`1.7.2`, refusé par 5.2) ; `compresse=True` donne le `.gramps` gzip natif de Gramps Desktop.
La racine Sosa configurée devient la personne de référence du fichier (`personne_reference` du résultat dit si
`home` a été écrit ; jamais pour une racine masquée) : le dire à l'utilisateur.
En mode gramps, les groupes de noms de Gramps sont écrits en `<namemaps>` (`groupes_de_noms` du résultat : nombre écrit, et en export public nombre retiré, sans nom) ; en mode fichier, aucun. Un groupe de noms ne fusionne aucune personne.

**gpkg** : paquet Gramps Desktop (XML + fichiers des médias locaux, chemins relatifs). Afficher le bilan
`medias` : médias inclus, **manquants** (introuvables ou hors des répertoires autorisés, avec le motif) et
distants. Docs : docs/gramps.md.
