---
description: Exporter l'arbre (GEDCOM 7/5.5.1, Gramps XML ou .gpkg, Mermaid, SVG, fiche Markdown)
argument-hint: <geneweb|gedcom7|gedcom551|gramps|gpkg|mermaid_asc|mermaid_desc|svg_asc|svg_desc|fiche> [id] [générations] [chemin]
---
Export : **$ARGUMENTS**

`arbre_exporter(format, chemin, id, generations, masquer_vivants=True, version_xml="1.7.1", compresse=False, chemin_base_medias="", chercheur=None)`. Les personnes présumées vivantes
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

**fiche du chercheur, signets, formats de nom** (mode gramps, #282) : `chercheur=None` (défaut) écrit la fiche de la base Gramps
(`SUBM` en GEDCOM, `<researcher>` en Gramps XML) **seulement dans un export privé** (`masquer_vivants=False`), jamais dans un
export public ; `chercheur=True` la demande explicitement (même en public : le rappeler, ce sont des coordonnées personnelles) ;
`chercheur=False` l'exclut. Lire `chercheur` du résultat (écrit, champs absents du format, ou motif). Les signets de la base
(`signets` : écrits, retirés pour objet masqué, non écrits) et ses formats de nom (`formats_de_noms`) sont écrits en gramps
et gpkg. Ne jamais afficher la valeur de la fiche. Docs : docs/gramps-web.md.

**gramps avec images** : `chemin_base_medias` (absolu, facultatif) écrit le chemin de base des médias (`<mediapath>`) et rend relatifs à lui les
chemins des médias du vault : Gramps Desktop les retrouve directement si ce dossier est la racine du vault sur sa machine.
C'est un chemin personnel : jamais par défaut, refusé en export public (`masquer_vivants=True`) et pour `gpkg` ; le demander à
l'utilisateur, ne jamais le deviner. Lire `chemin_base_medias.medias` du résultat (hors base, introuvables). Docs : docs/gramps.md.

**gpkg** : paquet Gramps Desktop (XML + fichiers des médias locaux, chemins relatifs). Afficher le bilan
`medias` : médias inclus, **manquants** (introuvables ou hors des répertoires autorisés, avec le motif) et
distants. Docs : docs/gramps.md.
