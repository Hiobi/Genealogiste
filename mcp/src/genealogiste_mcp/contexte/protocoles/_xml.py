"""Lecture XML commune aux protocoles SRU et OAI-PMH : analyse sans DTD, noms locaux (espaces de noms ignorés)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from . import ReponseInvalide, refuser_dtd


def racine(xml_text) -> ET.Element:
    if isinstance(xml_text, bytes):
        xml_text = xml_text.decode("utf-8", errors="replace")
    if not isinstance(xml_text, str) or not xml_text.strip():
        raise ReponseInvalide("réponse XML vide")
    refuser_dtd(xml_text)
    try:
        return ET.fromstring(xml_text.encode("utf-8") if xml_text.lstrip().startswith("<?xml") else xml_text)
    except ET.ParseError as exc:
        raise ReponseInvalide(f"réponse XML illisible : {exc}") from None


def local(el: ET.Element) -> str:
    """Nom local d'un élément (« {ns}record » -> « record »)."""
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def enfants(el: ET.Element, nom: str) -> list[ET.Element]:
    return [c for c in el if local(c) == nom]


def enfant(el: ET.Element, nom: str) -> ET.Element | None:
    return next((c for c in el if local(c) == nom), None)


def descendants(el: ET.Element, nom: str) -> list[ET.Element]:
    return [c for c in el.iter() if local(c) == nom]


def texte(el: ET.Element | None) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def dublin_core(el: ET.Element) -> dict[str, list[tuple[str, str]]]:
    """Éléments Dublin Core d'un enregistrement (oai_dc:dc ou équivalent) : nom local -> [(valeur, langue)]."""
    out: dict[str, list[tuple[str, str]]] = {}
    for c in el:
        v = texte(c)
        if v:
            out.setdefault(local(c), []).append((v, c.get(LANG) or ""))
    return out
