"""Socle commun des sources : contexte, sortie normalisée, journalisation automatique."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlsplit

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
    registres_vus: set = field(default_factory=set)  # ARK de registre déjà détaillés dans la session


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


def consigne_antirobot(protection: str | None, url: str = "") -> str:
    """Marche à suivre quand un service oppose un défi anti-robot : la vue passe par l'utilisateur (#196)."""
    lien = f" ({url})" if url else ""
    return (f"Défi anti-robot{f' {protection}' if protection else ''} : ne pas relancer ni tenter de le résoudre. "
            f"Demander à l'utilisateur d'ouvrir la vue dans son navigateur{lien} et de fournir une capture ou "
            "l'image téléchargée de la vue ; l'enregistrer avec media_enregistrer(chemin, nom, classer=true) "
            "(nom proposé par piece_nommer), puis la lire et tracer le relevé avec source_collee.")


def suite_sans_navigateur(url: str = "") -> dict:
    """Suite exploitable par le modèle après un défi anti-robot, sans navigateur côté serveur (#150) : ne pas
    relancer, poursuivre les autres pistes, confier la consultation à l'utilisateur (tâche manuelle) et
    reprendre son relevé ou son fichier avec les outils locaux."""
    return {
        "relancer": False,
        "navigateur_serveur": False,
        "poursuivre": "Passer aux autres pistes et sources de l'enquête ; ne pas réessayer ce service en boucle.",
        "ouvrir": url,
        "utilisateur": ("Depuis son propre poste, ouvrir le lien et relever cote, registre, numéro de vue et "
                        "provenance, ou télécharger la vue."),
        "tache": ("Avec enquete=<id>, la tâche est inscrite dans l'enquête (taches_manuelles) ; sinon la noter "
                  "avec enquete_noter(tache={description, service}) pour la reprendre."),
        "reprise": ["source_collee", "piece_archiver", "media_enregistrer"],
        "lever": "cache_purger('coupe_circuit') lève la pause ou l'exclusion pour un nouvel essai explicite.",
    }


def error_envelope(ctx: SourceContext, source: str, operation: str, params: dict, exc: Exception,
                   personne: str | None = None) -> dict:
    # Les adaptateurs gardent la cause HTTP avec « raise … from exc ».
    cause = exc
    vues = set()
    while not getattr(cause, "bloque_antirobot", False) and cause.__cause__ is not None and id(cause) not in vues:
        vues.add(id(cause))
        cause = cause.__cause__
    bloque = getattr(cause, "bloque_antirobot", False)
    if not bloque:
        cause = exc
    url = getattr(cause, "url", "") or ""
    tache = ({"statut": "a_faire", "url": url,
              "action": "Relever la cote, le registre, la vue et la provenance depuis un accès autorisé ; "
                        "fournir le résultat avec source_collee ou le fichier local avec piece_archiver."}
             if bloque else None)
    apres = getattr(cause, "reessayer_apres", None)
    resume = str(exc) + (f" [reessayer_apres={apres} s]" if apres is not None else "")
    details = ({"protection": cause.protection, "date_detection": cause.date_detection,
                "tache_manuelle": tache} if bloque else {})
    jid = ctx.journal.add(source=source, operation=operation, parametres=params,
                          statut="bloque_antirobot" if bloque else "erreur",
                          resume=resume, personne=personne, references=[url] if url else [],
                          note=json.dumps(details, ensure_ascii=False) if details else "",
                          cache=bool(getattr(cause, "echec_memorise", False) or getattr(cause, "coupe_circuit", False)))
    out = {"source": source, "requete": params, "erreur": str(exc), "journal": jid,
           "conseil": "Réessayer plus tard, vérifier la configuration, ou utiliser la recherche manuelle (liens_recherche)."}
    if getattr(cause, "echec_memorise", False):
        out.update(echec_memorise=True, depuis_cache=True)
    if getattr(cause, "coupe_circuit", False):
        out["coupe_circuit"] = True
    if getattr(cause, "intervalle", None):
        out["intervalle_actuel"] = cause.intervalle  # hôte ralenti pour la journée (#211)
    if apres is not None:
        out["reessayer_apres"] = apres
        out["conseil"] = (f"Service saturé ou indisponible : réessayer dans {round(apres)} s au plus tôt, passer à une "
                          "autre source en attendant ; ne pas relancer en boucle.")
    if bloque:
        from .. import archives, ark
        hote = urlsplit(url).hostname or source

        def _sans_www(h: str | None) -> str:
            return (h or "").removeprefix("www.")

        # Le référentiel note parfois « www. » alors que la visionneuse sert sans (AD15, #253).
        candidats = [s for s in archives.services()
                     if _sans_www(hote) in {_sans_www(urlsplit(s.get(k) or "").hostname) for k in ("site", "visionneuse")}]
        identifiant = ark.find(url) or ark.find(params.get("source") or "")
        matches = [s for s in candidats if identifiant and s.get("ark_naan") == identifiant.naan]
        service = matches[0]["code"] if len(matches) == 1 else candidats[0]["code"] if len(candidats) == 1 else hote
        out.update(statut="bloque_antirobot", bloque="anti-robot", service=service, protection=cause.protection,
                   date_detection=cause.date_detection, url=url, tache_manuelle=tache,
                   consigne=consigne_antirobot(cause.protection, url), suite=suite_sans_navigateur(url))
        if getattr(cause, "exclusion", False):
            out.update(exclusion=True, exclu_jusqu_au=cause.exclu_jusqu_au)
        out["conseil"] = ("Conserver cette tâche au journal et poursuivre les autres pistes. "
                          "Quand un accès autorisé est disponible, reprendre avec source_collee ou fournir "
                          "un fichier local à piece_archiver ; ne pas relancer en boucle ni contourner le défi.")
    return out


__all__ = ["SourceContext", "consigne_antirobot", "suite_sans_navigateur", "person_record", "rank", "envelope", "error_envelope", "SourceError", "DAY"]
