"""Contrôles de portée d'un élément de contexte (#321) : purs, sans réseau.

Un élément hors des bornes de lieu ou de période de la vie est rejeté (anachronisme, hors sujet) ; un élément
d'échelle supérieure à la commune porte la mention « tendance générale, ne prouve rien pour l'individu ».
Utilisés par ``contexte_local`` (#289) et par le vérificateur (#324).

Lieux de vie : ``LieuDeVie`` distingue ``pays`` (État : « France ») et ``pays_naturel`` (région naturelle ou bassin,
échelle « pays » : « Bassin minier du Nord-Pas-de-Calais »). Correspondance par échelle :
commune -> commune, departement -> département (nom ou code), region -> région, pays -> pays naturel,
nation -> pays, international -> toujours compatible. Un lieu de vie qui ne renseigne pas l'échelle demandée
n'est jamais compatible : l'absence d'information ne vaut pas preuve.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..normalize.places import DEPARTEMENTS, normalize_place, place_key
from .modeles import MENTION_TENDANCE, ElementContexte


@dataclass(frozen=True)
class Periode:
    """Années de début et de fin (incluses)."""

    de: int
    a: int

    def __post_init__(self):
        if self.a < self.de:
            raise ValueError(f"période invalide : {self.de}-{self.a}")

    def to_dict(self) -> dict:
        return {"de": self.de, "a": self.a}


@dataclass(frozen=True)
class LieuDeVie:
    """Lieu où l'individu est attesté, avec les années de présence attestées (``de``, ``a``, facultatives)."""

    commune: str = ""
    departement: str = ""  # nom ou code
    region: str = ""
    pays: str = ""  # État
    pays_naturel: str = ""  # région naturelle ou bassin (échelle « pays »)
    de: int | None = None
    a: int | None = None


def _periode(vie) -> Periode:
    return vie if isinstance(vie, Periode) else Periode(*vie)


def dans_la_periode(element: ElementContexte, vie: Periode | tuple[int, int]) -> bool:
    """Vrai si les années de l'élément recoupent la période de vie (bornes incluses)."""
    v = _periode(vie)
    return element.portee.de <= v.a and element.portee.a >= v.de


def _departement(texte: str) -> str:
    """Code de département d'un nom ou d'un code (« Pas-de-Calais », « 62 », « Charente-Inférieure ») ; à défaut,
    clé de comparaison du libellé."""
    t = (texte or "").strip()
    if t.upper() in DEPARTEMENTS:
        return t.upper()
    code = normalize_place(f"x, {t}").get("departement_code")
    return code or place_key(t)


def _correspond(echelle: str, libelle: str, lieu: LieuDeVie) -> bool:
    if echelle == "international":
        return True
    if echelle == "commune":
        return bool(lieu.commune) and normalize_place(libelle).get("cle") == place_key(lieu.commune)
    if echelle == "departement":
        return bool(lieu.departement) and _departement(libelle) == _departement(lieu.departement)
    attendu = {"region": lieu.region, "pays": lieu.pays_naturel, "nation": lieu.pays}[echelle]
    return bool(attendu) and place_key(libelle) == place_key(attendu)


def dans_les_lieux(element: ElementContexte, lieux: list[LieuDeVie]) -> bool:
    """Vrai si le lieu de l'élément, à son échelle, correspond à l'un des lieux de vie."""
    return any(_correspond(element.portee.echelle, element.portee.lieu, lieu) for lieu in lieux)


def mention(element: ElementContexte) -> str:
    """Mention obligatoire d'un élément d'échelle supérieure à la commune ("" pour la commune)."""
    return "" if element.portee.echelle == "commune" else MENTION_TENDANCE


def controler(element: ElementContexte, vie: Periode | tuple[int, int], lieux: list[LieuDeVie]) -> dict:
    """Contrôle complet : ``{"retenu": bool, "motifs": [raisons du rejet], "mention": str}``."""
    v = _periode(vie)
    motifs = []
    if not dans_la_periode(element, v):
        motifs.append(f"hors de la période de vie ({element.portee.de}-{element.portee.a} hors de {v.de}-{v.a})")
    if not dans_les_lieux(element, lieux):
        motifs.append(f"hors des lieux de vie ({element.portee.echelle} : {element.portee.lieu})")
    return {"retenu": not motifs, "motifs": motifs, "mention": mention(element)}
