"""Wikidata SPARQL (lecture seule)."""

from __future__ import annotations

import re

from ..normalize.dates import GREG_MONTHS
from .base import DAY, SourceContext, envelope, error_envelope, person_record, rank

ENDPOINT = "https://query.wikidata.org/sparql"
FORBIDDEN = re.compile(r"\b(INSERT|DELETE|LOAD|CLEAR|DROP|CREATE|COPY|MOVE|ADD)\b", re.I)

PERSON_QUERY = """
SELECT ?p ?lab ?lfr ?len ?birth ?bprec ?death ?dprec ?birthPlaceLabel ?deathPlaceLabel ?fatherLabel ?motherLabel
       ?sexLabel ?desc WHERE {
  SERVICE wikibase:mwapi { bd:serviceParam wikibase:endpoint "www.wikidata.org"; wikibase:api "EntitySearch";
    mwapi:search %(search)s; mwapi:language "fr". ?p wikibase:apiOutputItem mwapi:item. ?lab wikibase:apiOutput "@label". }
  ?p wdt:P31 wd:Q5.
  OPTIONAL { ?p rdfs:label ?lfr FILTER(lang(?lfr) = "fr") }
  OPTIONAL { ?p rdfs:label ?len FILTER(lang(?len) = "en") }
  OPTIONAL { ?p schema:description ?desc FILTER(lang(?desc) = "fr") }
  OPTIONAL { ?p p:P569/psv:P569 [ wikibase:timeValue ?birth; wikibase:timePrecision ?bprec ] }
  OPTIONAL { ?p p:P570/psv:P570 [ wikibase:timeValue ?death; wikibase:timePrecision ?dprec ] }
  OPTIONAL { ?p wdt:P19 ?birthPlace. } OPTIONAL { ?p wdt:P20 ?deathPlace. }
  OPTIONAL { ?p wdt:P22 ?father. } OPTIONAL { ?p wdt:P25 ?mother. } OPTIONAL { ?p wdt:P21 ?sex. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en". }
} LIMIT %(limit)d
"""


def _lit(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _date(value: str, precision: str) -> str:
    m = re.match(r"^([+-]?\d{1,4})-(\d{2})-(\d{2})", value or "")
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    p = int(precision or 11)
    if p >= 11:
        return f"{d} {GREG_MONTHS[mo - 1]} {y}"
    if p == 10:
        return f"{GREG_MONTHS[mo - 1]} {y}"
    if p == 9:
        return str(y)
    return f"ABT {y}"


def sparql(ctx: SourceContext, requete: str, ttl_jours: int = 7) -> dict:
    if FORBIDDEN.search(re.sub(r"\"[^\"]*\"|'[^']*'", "", requete)):
        return {"erreur": "Seules les requêtes de lecture (SELECT/ASK/CONSTRUCT/DESCRIBE) sont autorisées."}
    try:
        data, cached = ctx.http.get(ENDPOINT, params={"query": requete, "format": "json"},
                                    headers={"Accept": "application/sparql-results+json"},
                                    ttl=ttl_jours * DAY, source="wikidata")
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "wikidata", "sparql", {"requete": requete[:500]}, exc)
    rows = [{k: v.get("value") for k, v in b.items()} for b in data.get("results", {}).get("bindings", [])]
    ctx.journal.add("wikidata", "sparql", {"requete": requete[:500]}, "positif" if rows else "negatif",
                    nb_resultats=len(rows), cache=cached)
    return {"source": "wikidata", "nb_lignes": len(rows), "lignes": rows[:500], "depuis_cache": cached}


def search_person(ctx: SourceContext, nom: str, prenom: str = "", ne_vers: str = "", lieu: str = "",
                  limite: int = 20, personne: str | None = None) -> dict:
    search = f"{prenom} {nom}".strip()
    q = PERSON_QUERY % {"search": _lit(search), "limit": min(limite * 3, 150)}
    params = {"recherche": search, "ne_vers": ne_vers, "lieu": lieu}
    try:
        data, cached = ctx.http.get(ENDPOINT, params={"query": q, "format": "json"},
                                    headers={"Accept": "application/sparql-results+json"},
                                    ttl=7 * DAY, source="wikidata")
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "wikidata", "personne", params, exc, personne)
    seen: dict[str, dict] = {}
    for b in data.get("results", {}).get("bindings", []):
        v = {k: x.get("value") for k, x in b.items()}
        qid = v["p"].rsplit("/", 1)[-1]
        if qid in seen:
            continue
        label = v.get("lfr") or v.get("lab") or v.get("len") or qid
        parts = label.split()
        given, surname = (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else ("", label)
        url = f"https://www.wikidata.org/wiki/{qid}"
        seen[qid] = person_record(
            "wikidata", qid, prenoms=given, nom=surname,
            sexe={"masculin": "M", "féminin": "F", "male": "M", "female": "F"}.get(v.get("sexLabel", ""), "U"),
            naissance={"date": _date(v.get("birth", ""), v.get("bprec")), "lieu": v.get("birthPlaceLabel", "")},
            deces={"date": _date(v.get("death", ""), v.get("dprec")), "lieu": v.get("deathPlaceLabel", "")},
            url=url, description=v.get("desc"), pere=v.get("fatherLabel"), mere=v.get("motherLabel"),
            citation={"titre_source": "Wikidata", "page": f"{qid} ({label})", "type_source": "composite",
                      "information": "indeterminee", "preuve": "directe", "url": url,
                      "note": "Base collaborative : vérifier les références de chaque déclaration."},
        )
    records = rank({"nom": nom, "prenom": prenom, "ne_vers": ne_vers, "lieu": lieu}, list(seen.values()))[:limite]
    return envelope(ctx, "wikidata", "personne", params, records, len(seen), cached, personne,
                    couverture="Personnalités notables uniquement.")
