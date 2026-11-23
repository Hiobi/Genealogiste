"""Protocole OAI-PMH (#286) : réponses GetRecord et ListRecords au format ``oai_dc``.

OAI-PMH ne connaît pas la recherche plein texte : il sert à **récupérer une notice dont l'identifiant OAI est
connu** (GetRecord) ou à moissonner un ensemble (ListRecords). Une erreur OAI (``<error code=…>``) lève
``ReponseInvalide`` ; une notice supprimée (``header status="deleted"``) est ignorée.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ReponseInvalide
from ._xml import descendants, dublin_core, enfant, local, racine, texte

__all__ = ["NoticeOai", "notices"]


@dataclass
class NoticeOai:
    identifiant: str
    datestamp: str = ""
    dc: dict[str, list[tuple[str, str]]] = field(default_factory=dict)

    def valeurs(self, nom: str) -> list[str]:
        return [v for v, _ in self.dc.get(nom, [])]


def notices(xml_text) -> list[NoticeOai]:
    """Notices oai_dc d'une réponse OAI-PMH (GetRecord ou ListRecords)."""
    root = racine(xml_text)
    if local(root) != "OAI-PMH":
        raise ReponseInvalide(f"réponse OAI-PMH inattendue : <{local(root)}>")
    err = enfant(root, "error")
    if err is not None:
        raise ReponseInvalide(f"erreur OAI-PMH {err.get('code') or ''} : {texte(err)[:200]}".strip())
    out = []
    for rec in descendants(root, "record"):
        head = enfant(rec, "header")
        if head is None or head.get("status") == "deleted":
            continue
        meta = enfant(rec, "metadata")
        dc = next(iter(meta), None) if meta is not None else None
        out.append(NoticeOai(texte(enfant(head, "identifier")), texte(enfant(head, "datestamp")),
                             dublin_core(dc) if dc is not None else {}))
    return out
