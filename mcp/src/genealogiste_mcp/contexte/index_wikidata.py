"""Wikidata utilisé comme **index** par ``contexte_local`` (#289) : gabarits SPARQL légers, versionnés ici.

Wikidata n'est jamais une source (nature ``index`` au référentiel) : une ligne renvoyée n'est qu'une piste. Elle ne
devient un élément de contexte que si elle porte une référence externe (identifiant BnF ``P268``, IdRef ``P269``,
article Persée ``P8758``) **présente dans la réponse** et déjà inscrite au registre des références consultées ;
sinon l'outil la signale « non sourcé » avec les liens de consultation, sans jamais la présenter comme source.

Règles des gabarits (constat de l'issue #289 : requête par rayon ou par département en délai dépassé, puis 429) :

- rattachement administratif (``P276`` lieu ou ``P131`` localisation administrative, puis ``P131*``) à une commune
  désignée par son code INSEE (``P374``), jamais un rayon géographique ;
- classes d'événements fermées (``CLASSES_EVENEMENTS``, sous-classes comprises) ;
- filtre de période (année de ``P585``, sinon ``P580`` à ``P582``) : un événement non daté n'est pas renvoyé ;
- ``LIMIT`` ; délai : celui du client HTTP commun (``GENEALOGISTE_HTTP_TIMEOUT``, 30 s par défaut), limites de débit,
  plafonds et coupe-circuit du client ; cache de 30 jours.

Chaque gabarit livré a une réponse réelle enregistrée (``tests/fixtures/contexte/reponses/WIKIDATA/``, avec
``MANIFESTE.json``) et un test. Les gabarits essayés sans réponse (délai dépassé) sont listés dans ``NON_LIVRES`` :
aucun n'est émis. Seuls un code INSEE et deux années partent : jamais de nom ni d'identifiant de personne.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..sources.base import DAY, SourceContext, error_envelope
from ..sources.wikidata import ENDPOINT
from . import services
from .modeles import Identifiant, ReferenceInvalide

SERVICE = "WIKIDATA"

# Classes d'événements (libellés tels que renvoyés par l'API Wikidata, en français sinon en anglais, le 2026-11-23).
CLASSES_EVENEMENTS = {
    "Q3839081": "catastrophe",
    "Q1550225": "mining accident",
    "Q49776": "grève",
    "Q44512": "épidémie",
    "Q178561": "bataille",
    "Q8068": "inondation",
    "Q168983": "incendie",
}

# Liens de consultation d'un identifiant externe (jamais interrogés par le plugin : dictionnaire, distinct des
# constantes de points d'accès relevées par test_politique_acces).
LIENS = {"bnf": "https://catalogue.bnf.fr/ark:/12148/cb{}",
         "idref": "https://www.idref.fr/{}",
         "persee": "https://www.persee.fr/doc/{}",
         "wikidata": "https://www.wikidata.org/wiki/{}"}

_EVENEMENTS_COMMUNE = """SELECT DISTINCT ?item ?itemLabel ?classe ?date ?debut ?fin ?bnf ?idref ?persee WHERE {
  ?lieu wdt:P374 "%(code)s" .
  ?item (wdt:P276|wdt:P131)/wdt:P131* ?lieu .
  VALUES ?classe { %(classes)s }
  ?item wdt:P31/wdt:P279* ?classe .
  OPTIONAL { ?item wdt:P585 ?date }
  OPTIONAL { ?item wdt:P580 ?debut }
  OPTIONAL { ?item wdt:P582 ?fin }
  BIND(COALESCE(YEAR(?date), YEAR(?debut)) AS ?an0)
  BIND(COALESCE(YEAR(?date), YEAR(?fin), ?an0) AS ?an1)
  FILTER(BOUND(?an0) && ?an0 <= %(a)d && ?an1 >= %(de)d)
  OPTIONAL { ?item wdt:P268 ?bnf }
  OPTIONAL { ?item wdt:P269 ?idref }
  OPTIONAL { ?item wdt:P8758 ?persee }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en" . }
} LIMIT %(limite)d
"""


@dataclass(frozen=True)
class GabaritWikidata:
    nom: str
    echelle: str  # échelle des lieux interrogés (portée des éléments)
    texte: str
    limite: int
    description: str
    ttl: float = 30 * DAY

    def requete(self, code: str, de: int, a: int) -> str:
        if not re.fullmatch(r"\d[\dAB]\d{3}", code or ""):
            raise ValueError(f"code INSEE de commune attendu : {code!r}")
        if not (isinstance(de, int) and isinstance(a, int) and de <= a):
            raise ValueError(f"période invalide : {de}-{a}")
        classes = " ".join(f"wd:{q}" for q in CLASSES_EVENEMENTS)
        return self.texte % {"code": code, "de": de, "a": a, "classes": classes, "limite": self.limite}


GABARITS: dict[str, GabaritWikidata] = {
    "evenements_commune": GabaritWikidata(
        nom="evenements_commune", echelle="commune", texte=_EVENEMENTS_COMMUNE, limite=50,
        description="Événements des classes fermées situés dans la commune (P276 ou P131, puis P131*), datés dans "
                    "la période ; identifiants BnF, IdRef et Persée s'ils existent."),
}

# Gabarits essayés une fois (requête réelle) sans réponse : non livrés, jamais émis.
NON_LIVRES = {
    "evenements_departement": "rattachement au département (P2586 puis P131*, ou communes du département par le "
                              "préfixe du code INSEE) : délai dépassé (60 s) aux deux essais du 2026-11-23 ; non "
                              "livré",
}


@dataclass
class LigneIndex:
    """Une entrée de l'index (un élément Wikidata), toutes lignes de la réponse réunies."""

    qid: str
    libelle: str  # libellé Wikidata : index, jamais énoncé
    classes: list[str] = field(default_factory=list)
    de: int | None = None
    a: int | None = None
    bnf: list[str] = field(default_factory=list)
    idref: list[str] = field(default_factory=list)
    persee: list[str] = field(default_factory=list)

    def identifiants(self) -> list[Identifiant]:
        """Références externes présentes dans la réponse, normalisées (ARK BnF, PPN IdRef, URL Persée)."""
        out = []
        for type_, valeurs, forme in (("ark", self.bnf, "ark:/12148/cb{}"), ("ppn", self.idref, "{}"),
                                      ("url", self.persee, LIENS["persee"])):
            for v in valeurs:
                try:
                    out.append(Identifiant(type_, forme.format(v)))
                except ReferenceInvalide:
                    continue
        return out

    def liens(self) -> list[str]:
        return ([LIENS["bnf"].format(v) for v in self.bnf] + [LIENS["idref"].format(v) for v in self.idref]
                + [LIENS["persee"].format(v) for v in self.persee] + [LIENS["wikidata"].format(self.qid)])

    def to_dict(self) -> dict:
        return {"qid": self.qid, "libelle_index": self.libelle,
                "classes": [CLASSES_EVENEMENTS.get(c, c) for c in self.classes],
                "annees": {"de": self.de, "a": self.a}, "identifiants": [i.cle for i in self.identifiants()],
                "liens": self.liens()}


def _annee(valeur: str) -> int | None:
    m = re.match(r"^([+-]?)(\d{1,4})-", valeur or "")
    if not m or m.group(1) == "-":
        return None
    return int(m.group(2))


def analyser(data) -> list[LigneIndex]:
    """Réponse SPARQL (JSON) -> une ``LigneIndex`` par élément. Forme inattendue : ValueError."""
    if not isinstance(data, dict) or not isinstance((data.get("results") or {}).get("bindings"), list):
        raise ValueError("réponse SPARQL inattendue (results.bindings absent)")
    lignes: dict[str, LigneIndex] = {}
    for b in data["results"]["bindings"]:
        v = {k: (x or {}).get("value", "") for k, x in b.items() if isinstance(x, dict)}
        qid = v.get("item", "").rsplit("/", 1)[-1]
        if not re.fullmatch(r"Q\d+", qid):
            continue
        ligne = lignes.setdefault(qid, LigneIndex(qid, v.get("itemLabel") or qid))
        classe = v.get("classe", "").rsplit("/", 1)[-1]
        if classe and classe not in ligne.classes:
            ligne.classes.append(classe)
        annees = [a for a in (_annee(v.get("date", "")), _annee(v.get("debut", "")), _annee(v.get("fin", "")))
                  if a is not None]
        if annees:
            ligne.de = min([*annees, *([ligne.de] if ligne.de is not None else [])])
            ligne.a = max([*annees, *([ligne.a] if ligne.a is not None else [])])
        for cle in ("bnf", "idref", "persee"):
            if v.get(cle) and v[cle] not in getattr(ligne, cle):
                getattr(ligne, cle).append(v[cle])
    return list(lignes.values())


def interroger(ctx: SourceContext, nom: str, code: str, de: int, a: int, personne: str | None = None,
               residus=None) -> dict:
    """Interroge un gabarit livré. Renvoie ``{"statut": interroge|erreur|ecarte, "lignes": [...], ...}`` ; jamais
    d'exception : un refus du référentiel, un hôte non autorisé ou une panne sont rendus avec leur motif."""
    gab = GABARITS[nom]
    base = {"service": SERVICE, "operation": f"index:{nom}", "lieu": code}
    if refus := services.refus(SERVICE, ctx.config):
        return {**base, "statut": "ecarte", "motif": refus["erreur"], "lignes": []}
    if not services.url_autorisee(SERVICE, ENDPOINT):
        return {**base, "statut": "ecarte", "motif": "point d'accès hors référentiel", "lignes": []}
    requete = gab.requete(code, de, a)
    if residus and (trouves := residus(requete)):
        return {**base, "statut": "erreur", "lignes": [],
                "motif": f"requête non émise : elle contiendrait un élément d'identité ({', '.join(trouves)})"}
    params = {"gabarit": nom, "code_insee": code, "periode": f"{de}-{a}"}
    try:
        data, cache = ctx.http.get(ENDPOINT, params={"query": requete, "format": "json"},
                                   headers={"Accept": "application/sparql-results+json"}, ttl=gab.ttl,
                                   source="wikidata")
        lignes = analyser(data)
    except Exception as exc:  # noqa: BLE001 — un service en échec n'empêche pas les autres
        env = error_envelope(ctx, "wikidata", f"index_{nom}", params, exc, personne)
        return {**base, "statut": "erreur", "motif": env["erreur"], "journal": env["journal"], "lignes": []}
    jid = ctx.journal.add("wikidata", f"index_{nom}", params, "positif" if lignes else "negatif",
                          nb_resultats=len(lignes), cache=cache, personne=personne,
                          resume="; ".join(x.libelle[:60] for x in lignes[:5]),
                          references=[LIENS["wikidata"].format(x.qid) for x in lignes[:20]])
    return {**base, "statut": "interroge", "nb_lignes": len(lignes), "depuis_cache": cache, "journal": jid,
            "lignes": lignes}
