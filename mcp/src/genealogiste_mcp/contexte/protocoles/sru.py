"""Protocole SRU (#286) : searchRetrieveResponse (SRU 1.1 / 1.2), Dublin Core et UNIMARC XML.

Formes relevées le 2026-11-23 : catalogue de la BnF (``recordSchema=dublincore`` : ``oai_dc:dc`` dans
``srw:recordData``, identifiant ARK dans ``dc:identifier``) et Sudoc (``recordSchema=unimarc`` : ``record`` sans
espace de noms, ``leader``, ``controlfield``, ``datafield``/``subfield``). Un diagnostic SRU lève
``ReponseInvalide``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from . import ReponseInvalide
from ._xml import descendants, dublin_core, enfant, enfants, local, racine, texte

__all__ = ["Unimarc", "cql_mots", "cql_phrase", "dublin_core", "enregistrements", "unimarc"]


def cql_phrase(texte_: str) -> str:
    """Terme CQL entre guillemets, guillemets et barres obliques inverses retirés."""
    t = re.sub(r"\s+", " ", (texte_ or "").replace('"', " ").replace("\\", " ")).strip()
    return f'"{t}"' if t else ""


def cql_mots(texte_: str) -> list[str]:
    """Mots d'un texte libre pour CQL (opérateurs et caractères de syntaxe retirés)."""
    propre = re.sub(r'[()"=<>/\\*?^]', " ", texte_ or "")
    return [m for m in propre.split() if m.lower() not in ("and", "or", "not", "prox", "all", "any")]


def enregistrements(xml_text) -> tuple[int | None, list[ET.Element]]:
    """(numberOfRecords, contenus de recordData) d'une réponse searchRetrieve. ReponseInvalide sur diagnostic SRU
    ou forme inattendue."""
    root = racine(xml_text)
    if local(root) != "searchRetrieveResponse":
        raise ReponseInvalide(f"réponse SRU inattendue : <{local(root)}>")
    diag = descendants(root, "diagnostic")
    if diag:
        msg = texte(enfant(diag[0], "message")) or texte(enfant(diag[0], "details")) or "diagnostic SRU"
        raise ReponseInvalide(f"diagnostic SRU : {msg[:200]}")
    n = texte(enfant(root, "numberOfRecords"))
    total = int(n) if n.isdigit() else None
    out = []
    recs = enfant(root, "records")
    for rec in enfants(recs, "record") if recs is not None else []:
        data = enfant(rec, "recordData")
        contenu = next(iter(data), None) if data is not None else None
        if contenu is not None:
            out.append(contenu)
    return total, out


@dataclass
class Unimarc:
    """Notice UNIMARC XML : ``leader``, ``controles`` (étiquette -> valeur), ``champs`` [(étiquette, indicateurs,
    [(code, valeur)])]."""

    leader: str = ""
    controles: dict[str, str] = field(default_factory=dict)
    champs: list[tuple[str, str, list[tuple[str, str]]]] = field(default_factory=list)

    def sous_champs(self, etiquette: str, code: str) -> list[str]:
        return [v for tag, _, sf in self.champs if tag == etiquette for c, v in sf if c == code and v]

    def premier(self, etiquette: str, code: str) -> str:
        return next(iter(self.sous_champs(etiquette, code)), "")

    def a(self, etiquette: str) -> bool:
        return any(tag == etiquette for tag, _, _ in self.champs)

    def occurrences(self, etiquette: str) -> list[list[tuple[str, str]]]:
        return [sf for tag, _, sf in self.champs if tag == etiquette]


def unimarc(el: ET.Element) -> Unimarc:
    """Notice UNIMARC d'un élément ``record`` (MARCXML)."""
    if local(el) != "record":
        raise ReponseInvalide(f"notice UNIMARC attendue, reçu <{local(el)}>")
    chef = enfant(el, "leader")  # positions significatives : jamais d'espaces retirés
    n = Unimarc(leader=("".join(chef.itertext()) if chef is not None else "").ljust(24))
    for c in el:
        nom = local(c)
        if nom == "controlfield":
            n.controles[c.get("tag") or ""] = texte(c)
        elif nom == "datafield":
            sf = [(s.get("code") or "", texte(s)) for s in enfants(c, "subfield")]
            n.champs.append((c.get("tag") or "", (c.get("ind1") or " ") + (c.get("ind2") or " "), sf))
    return n
