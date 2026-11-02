"""Mise en forme des citations selon l'usage des généalogistes français.

Forme : Dépôt (sigle), cote, titre de la source, localisation précise (acte, folio, vue) ; consulté le … ;
[ce qui a été vu ; classification].
Ex. : AD17, 2 E 299/12, État civil de Rochefort, naissances 1820, acte n° 45, vue 12/80 ;
consulté le 02/11/2026 [image numérisée ; source originale, information primaire].
"""

from __future__ import annotations

from .models import Citation, Tree

VU = {"original": "document original", "image": "image numérisée", "transcription": "transcription",
      "index": "index ou relevé seulement", "non_vu": "NON VU — cité d'après une autre source"}
TYPES = {"originale": "source originale", "derivee": "source dérivée", "composite": "source composite"}
INFOS = {"primaire": "information primaire", "secondaire": "information secondaire"}
PREUVES = {"indirecte": "preuve indirecte", "negative": "preuve négative"}


def _fr_date(iso: str) -> str:
    parts = iso.split("-")
    return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else iso


def format_citation(tree: Tree, c: Citation, classification: bool = True) -> str:
    src = tree.sources.get(c.source)
    parts = []
    if src:
        repo = tree.depots.get(src.depot) if src.depot else None
        if repo:
            parts.append(repo.sigle or repo.nom)
        if src.cote:
            parts.append(src.cote)
        if src.auteur:
            parts.append(src.auteur)
        parts.append(src.titre or f"source {src.id}")
    else:
        parts.append(f"source {c.source} (introuvable)")
    if c.page:
        parts.append(c.page)
    text = ", ".join(p for p in parts if p)
    if src and src.url:
        text += f" <{src.url}>"
    if c.date_consultation:
        text += f" ; consulté le {_fr_date(c.date_consultation)}"
    if classification:
        tags = []
        if c.consultation:
            tags.append(VU.get(c.consultation, c.consultation))
        stype = c.type_source if c.type_source != "indeterminee" else (src.type_source if src else "")
        if stype in TYPES:
            tags.append(TYPES[stype])
        if c.information in INFOS:
            tags.append(INFOS[c.information])
        if c.preuve in PREUVES:
            tags.append(PREUVES[c.preuve])
        if tags:
            text += f" [{' ; '.join(tags)}]"
    return text + "."


def format_citations(tree: Tree, citations: list[Citation], classification: bool = True) -> list[str]:
    return [format_citation(tree, c, classification) for c in citations]
