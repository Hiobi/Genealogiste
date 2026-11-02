"""Socle commun des sources : contexte, sortie normalisée, journalisation automatique."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..config import Config
from ..http import HttpClient, SourceError
from ..journal import Journal
from ..matching import compare_profiles

DAY = 86400.0


@dataclass
class SourceContext:
    http: HttpClient
    journal: Journal
    config: Config


def person_record(
    source: str,
    id_externe: str,
    prenoms: str = "",
    nom: str = "",
    sexe: str = "U",
    naissance: dict | None = None,
    deces: dict | None = None,
    url: str = "",
    citation: dict | None = None,
    **extra,
) -> dict:
    """Personne au format interne commun (dates GEDCOM 7, lieux en clair + code INSEE)."""
    rec = {
        "source": source, "id_externe": id_externe, "url": url, "prenoms": prenoms, "nom": nom,
        "sexe": sexe or "U", "naissance": naissance or {}, "deces": deces or {},
    }
    rec.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    if citation:
        citation.setdefault("date_consultation", date.today().isoformat())
        rec["citation_suggeree"] = citation
    return rec


def rank(query: dict, records: list[dict]) -> list[dict]:
    """Classe les résultats par score de correspondance avec la requête (explicite)."""
    q = {
        "prenoms": query.get("prenom") or query.get("prenoms") or "",
        "nom": query.get("nom") or "",
        "sexe": query.get("sexe") or "U",
        "naissance": {"date": query.get("ne_vers") or query.get("naissance") or "", "lieu": query.get("lieu") or ""},
        "deces": {"date": query.get("decede_vers") or "", "lieu": ""},
    }
    for r in records:
        cand = {"prenoms": r.get("prenoms", ""), "nom": r.get("nom", ""), "sexe": r.get("sexe", "U"),
                "naissance": r.get("naissance") or {}, "deces": r.get("deces") or {}}
        res = compare_profiles(q, cand)
        r["score"] = res["score"]
        r["score_detail"] = [f"{d['critere']}: {d['raison']}" for d in res["details"]]
        if res["contradictions"]:
            r["score_contradictions"] = res["contradictions"]
    records.sort(key=lambda r: -r.get("score", 0))
    return records


def envelope(ctx: SourceContext, source: str, operation: str, params: dict, records: list[dict],
             total: int | None, cache: bool, personne: str | None = None, **extra) -> dict:
    statut = "positif" if records else "negatif"
    jid = ctx.journal.add(
        source=source, operation=operation, parametres=params, statut=statut,
        nb_resultats=len(records), cache=cache, personne=personne,
        resume="; ".join((r.get("titre") or f"{r.get('prenoms', '')} {r.get('nom', '')} "
                          f"{(r.get('naissance') or {}).get('date', '')}").strip()
                         for r in records[:5]) or (extra.get("resume") or ""),
        references=[r.get("url") or r.get("id_externe", "") for r in records[:20]],
    )
    out = {"source": source, "requete": params, "total": total if total is not None else len(records),
           "nb_renvoyes": len(records), "depuis_cache": cache, "journal": jid, "resultats": records}
    out.update(extra)
    if not records:
        out["recherche_negative"] = ("Aucun résultat : recherche négative tracée au journal. "
                                     "Élargir (variantes, ±2 ans) ou changer de source.")
    return out


def error_envelope(ctx: SourceContext, source: str, operation: str, params: dict, exc: Exception,
                   personne: str | None = None) -> dict:
    jid = ctx.journal.add(source=source, operation=operation, parametres=params, statut="erreur",
                          resume=str(exc), personne=personne)
    return {"source": source, "requete": params, "erreur": str(exc), "journal": jid,
            "conseil": "Réessayer plus tard, vérifier la configuration, ou utiliser la recherche manuelle (liens_recherche)."}


__all__ = ["SourceContext", "person_record", "rank", "envelope", "error_envelope", "SourceError", "DAY"]
