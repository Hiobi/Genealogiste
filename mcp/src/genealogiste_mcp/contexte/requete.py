"""Requêtes de contexte construites depuis l'arbre (#321) : lieux, période de vie, métiers attestés.

Seuls les lieux, dates et métiers des faits **sourcés** (au moins une citation, non réfutés) de la personne et de
ses unions sont lus ; la période et les lieux viennent de l'arbre, jamais d'une supposition. Une
``RequeteContexte`` ne contient **jamais** le nom, le prénom, le surnom ni l'identifiant de la personne : elle n'a
pas de champ pour eux. ``residus_identite`` vérifie qu'une URL ou un texte émis n'en contient pas (tests des outils).

Vivants : construire une requête ne dispense pas de ``_garde`` ; tout outil de contexte recevant ``personne``
l'appelle avant le premier appel externe (le couple commune + période + métier peut suffire à identifier).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote_plus

from ..models import Event, Tree
from ..normalize.dates import jdn_to_gregorian, parse_date
from ..normalize.places import normalize_place, place_key
from .portee import LieuDeVie, Periode


@dataclass
class RequeteContexte:
    """Paramètres d'une recherche de contexte : lieux de vie (avec années de présence), période de vie, métiers."""

    lieux: list[LieuDeVie] = field(default_factory=list)
    periode: Periode | None = None
    metiers: list[str] = field(default_factory=list)

    def termes(self) -> list[str]:
        """Termes de recherche (lieux du plus local au plus large, puis métiers), sans doublon, dans l'ordre."""
        out: list[str] = []
        for lieu in self.lieux:
            out += [lieu.commune, lieu.departement, lieu.region, lieu.pays_naturel, lieu.pays]
        out += self.metiers
        return list(dict.fromkeys(x for x in out if x))

    def parametres(self) -> dict:
        """Paramètres structurés, pour les gabarits de requête des services."""
        def uniques(attr: str) -> list[str]:
            return list(dict.fromkeys(getattr(x, attr) for x in self.lieux if getattr(x, attr)))

        return {"communes": uniques("commune"), "departements": uniques("departement"), "regions": uniques("region"),
                "pays_naturels": uniques("pays_naturel"), "pays": uniques("pays"),
                "de": self.periode.de if self.periode else None, "a": self.periode.a if self.periode else None,
                "metiers": list(self.metiers)}

    def to_dict(self) -> dict:
        return {"lieux": [asdict(x) for x in self.lieux], "periode": self.periode.to_dict() if self.periode else None,
                "metiers": list(self.metiers)}


def _annees(e: Event) -> tuple[int, int] | None:
    g = parse_date(e.date) if e.date else None
    if not g or not g.start:
        return None
    lo, hi = g.interval
    return jdn_to_gregorian(lo)[0], jdn_to_gregorian(hi)[0]


def _retenu(e: Event, sources_seulement: bool) -> bool:
    if e.statut_manuel and e.statut_manuel.statut == "refute":
        return False
    return bool(e.citations) or not sources_seulement


def depuis_personne(tree: Tree, personne: str, *, sources_seulement: bool = True,
                    pays_du_lieu: Callable[[str], str | None] | None = None,
                    region_du_lieu: Callable[[str], str | None] | None = None) -> RequeteContexte:
    """Requête de contexte d'une personne de l'arbre, à partir de ses faits datés ou localisés et de ceux de ses
    unions. ``sources_seulement`` (défaut) : faits cités seulement ; les faits réfutés sont toujours écartés.
    ``pays_du_lieu`` et ``region_du_lieu`` : fonctions libellé de lieu -> pays / région (ex. ``pays_du_lieu`` de
    normalize, #283) ; à défaut, le pays est celui du libellé (« …, France ») et la région reste vide.
    Lève KeyError si la personne est inconnue."""
    p = tree.person(personne)
    evenements = list(p.evenements)
    for fam in tree.spouses_families(p.id):
        evenements += fam.evenements
    faits = [(e, _annees(e)) for e in evenements if _retenu(e, sources_seulement)]
    faits.sort(key=lambda x: x[1] or (10**6, 10**6))

    annees = [a for _, a in faits if a]
    periode = Periode(min(a[0] for a in annees), max(a[1] for a in annees)) if annees else None

    lieux: dict[tuple, dict] = {}
    for e, a in faits:
        if not (e.lieu and e.lieu.nom.strip()):
            continue
        n = normalize_place(e.lieu.nom)
        cle = (place_key(n.get("commune") or ""), n.get("departement_code") or "", (n.get("pays") or "").lower())
        lieu = lieux.setdefault(cle, {"libelle": e.lieu.nom, "n": n, "de": None, "a": None})
        if a:
            lieu["de"] = a[0] if lieu["de"] is None else min(lieu["de"], a[0])
            lieu["a"] = a[1] if lieu["a"] is None else max(lieu["a"], a[1])
    out = []
    for lieu in lieux.values():
        n, libelle = lieu["n"], lieu["libelle"]
        pays = (pays_du_lieu(libelle) if pays_du_lieu else None) or n.get("pays") or ""
        region = (region_du_lieu(libelle) if region_du_lieu else None) or ""
        out.append(LieuDeVie(commune=n.get("commune") or "", departement=n.get("departement") or "", region=region,
                             pays=pays, de=lieu["de"], a=lieu["a"]))

    metiers = [e.valeur.strip() for e, _ in faits if e.type == "OCCU" and e.valeur.strip()]
    return RequeteContexte(lieux=out, periode=periode, metiers=list(dict.fromkeys(metiers)))


def _plat(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").casefold()


def residus_identite(texte: str, tree: Tree, personne: str) -> list[str]:
    """Éléments d'identité de la personne (nom, prénoms, surnom, identifiant) présents dans ``texte`` (URL ou
    requête émise, décodée), sans casse ni accents, en mots entiers. Doit être vide pour toute requête de contexte.
    Un nom de famille identique à un nom de lieu de la requête est aussi signalé : à arbitrer par l'appelant."""
    p = tree.person(personne)
    mots = {p.id}
    for n in p.noms:
        mots |= {n.nom, n.surnom, *n.prenoms.split()}
    plat = _plat(unquote_plus(texte or ""))
    out = set()
    for mot in mots:
        m = _plat(mot.strip().strip("/"))
        if len(m) >= 2 and re.search(rf"(?<![\w]){re.escape(m)}(?![\w])", plat):
            out.add(m)
    return sorted(out)
