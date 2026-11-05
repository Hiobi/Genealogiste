"""matchID — fichier des personnes décédées INSEE (décès depuis 1970). 1 requête/s."""

from __future__ import annotations

from pathlib import Path

from ..chemins import CheminRefuse, sortie_donnees
from ..normalize.dates import parse_date
from .base import DAY, SourceContext, envelope, error_envelope, person_record, rank

BASE = "https://deces.matchid.io/deces/api/v1"
TITLE = "Fichier des personnes décédées (INSEE), via matchID"


def _gdate(yyyymmdd: str) -> str:
    if not yyyymmdd:
        return ""
    g = parse_date(yyyymmdd)
    return g.gedcom(7) if g else yyyymmdd


def _loc(loc: dict | None) -> dict:
    if not loc:
        return {}
    city = loc.get("city")
    if isinstance(city, list):
        city = city[0] if city else ""
    parts = [p for p in (city, loc.get("departmentCode") and f"({loc['departmentCode']})", loc.get("country")) if p]
    return {"lieu": " ".join(parts[:2]) + (f", {parts[2]}" if len(parts) > 2 else ""),
            "code_insee": loc.get("code") or "", "pays": loc.get("country") or ""}


def normalize_person(p: dict) -> dict:
    name = p.get("name") or {}
    first = name.get("first") or []
    birth, death = p.get("birth") or {}, p.get("death") or {}
    nais = {"date": _gdate(birth.get("date", "")), **_loc(birth.get("location"))}
    dec = {"date": _gdate(death.get("date", "")), **_loc(death.get("location"))}
    if death.get("age") is not None:
        dec["age"] = f"{death['age']}y"
    cert = death.get("certificateId") or ""
    commune = dec.get("lieu", "").split(" (")[0]
    page = (f"Acte de décès n° {cert}, {commune}, {death.get('date', '')}" if cert else
            f"Décès {death.get('date', '')}") + f" (fichier INSEE {p.get('source', '')}, ligne {p.get('sourceLine', '')})"
    return person_record(
        "matchid", p.get("id", ""), prenoms=" ".join(first), nom=name.get("last", ""), sexe=p.get("sex", "U"),
        naissance=nais, deces=dec, url=f"https://deces.matchid.io/id/{p.get('id', '')}",
        citation={"titre_source": TITLE, "page": page, "type_source": "derivee", "information": "secondaire",
                  "preuve": "directe",
                  "note": "Index dérivé des bulletins de décès : l'acte de décès de la commune est l'original à consulter."},
        acte_deces_a_demander={"commune": commune, "numero": cert, "date": death.get("date", "")} if cert else None,
    )


def search(ctx: SourceContext, nom: str = "", prenom: str = "", ne_vers: str = "", lieu_naissance: str = "",
           decede_vers: str = "", lieu_deces: str = "", sexe: str = "", texte: str = "", taille: int = 20,
           page: int = 1, personne: str | None = None) -> dict:
    params = {
        "q": texte, "lastName": nom, "firstName": prenom, "birthDate": _fmt_date(ne_vers),
        "birthCity": lieu_naissance, "deathDate": _fmt_date(decede_vers), "deathCity": lieu_deces,
        "sex": sexe, "size": min(max(taille, 1), 100), "page": page, "fuzzy": "true",
    }
    shown = {k: v for k, v in params.items() if v not in ("", None)}
    try:
        data, cached = ctx.http.get(f"{BASE}/search", params=params, ttl=30 * DAY, source="matchid")
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "matchid", "recherche", shown, exc, personne)
    resp = data.get("response", {})
    records = [normalize_person(p) for p in resp.get("persons", [])]
    rank({"nom": nom, "prenom": prenom, "ne_vers": ne_vers, "lieu": lieu_naissance, "decede_vers": decede_vers,
          "sexe": sexe}, records)
    return envelope(ctx, "matchid", "recherche", shown, records, resp.get("total"), cached, personne,
                    couverture="Décès survenus en France (et Français à l'étranger) depuis 1970.")


def _fmt_date(v: str) -> str:
    """matchID attend JJ/MM/AAAA, AAAA ou une tranche « JJ/MM/AAAA-JJ/MM/AAAA » (sans espaces, vérifié sur l'API)."""
    if not v:
        return ""
    g = parse_date(v)
    if not g:
        return v
    if g.qualifier in ("ABT", "CAL", "EST", "BET"):
        d = g.to_dict()
        lo, hi = d["debut_gregorien"].split("-"), d["fin_gregorien"].split("-")
        return f"{lo[2]}/{lo[1]}/{lo[0]}-{hi[2]}/{hi[1]}/{hi[0]}"
    p = g.start
    if p.calendar == "GREGORIAN" and p.day and p.month:
        return f"{p.day:02d}/{p.month:02d}/{p.year}"
    return str(g.to_dict()["annee_min"])


def bulk_submit(ctx: SourceContext, chemin_csv: str, colonnes: dict, sep: str = ",", format_date: str = "",
                candidats: int = 1) -> dict:
    """Lance un appariement par lot. colonnes : {firstName: 'Prenom', lastName: 'Nom', birthDate: 'Date', ...}."""
    path = Path(chemin_csv).expanduser()
    if not path.is_file():
        return {"erreur": f"Fichier introuvable : {path}"}
    allowed = {"firstName", "lastName", "legalName", "sex", "birthDate", "birthCity", "birthDepartment",
               "birthCountry", "deathDate", "deathCity", "deathDepartment", "deathCountry", "lastSeenAliveDate"}
    bad = set(colonnes) - allowed
    if bad:
        return {"erreur": f"Colonnes inconnues {sorted(bad)} ; autorisées : {sorted(allowed)}"}
    data = {**colonnes, "sep": sep, "candidateNumber": str(candidats)}
    if format_date:
        data["dateFormat"] = format_date
    headers = {"Authorization": f"Bearer {ctx.config.matchid_token}"} if ctx.config.matchid_token else None
    params = {"fichier": str(path), **data}
    try:
        with path.open("rb") as fh:
            res, _ = ctx.http.post(f"{BASE}/search/csv", data=data, files={"fileName": (path.name, fh, "text/csv")},
                                   headers=headers, ttl=0, source="matchid", use_cache=False)
    except Exception as exc:  # noqa: BLE001
        out = error_envelope(ctx, "matchid", "appariement_csv", params, exc)
        if "401" in str(exc) or "403" in str(exc):
            out["conseil"] = ("L'appariement par lot exige un compte matchID : définir GENEALOGISTE_MATCHID_TOKEN "
                              "(jeton obtenu via /deces/api/v1/register puis /auth).")
        return out
    ctx.journal.add("matchid", "appariement_csv", params, "positif", resume=f"job {res.get('id')}")
    return {"job": res.get("id"), "statut": res.get("msg"), "suite": "Appeler matchid_appariement_statut(job)."}


def bulk_status(ctx: SourceContext, job: str, sortie: str = "") -> dict:
    cible = None
    if sortie:
        try:
            cible = sortie_donnees(ctx.config.data_dir, sortie, ".csv")
        except CheminRefuse as exc:
            return {"erreur": f"{exc} (sortie : fichier .csv dans le répertoire de données)"}
    headers = {"Authorization": f"Bearer {ctx.config.matchid_token}"} if ctx.config.matchid_token else None
    try:
        res, _ = ctx.http.get(f"{BASE}/search/csv/{job}", params={"order": "true"}, headers=headers,
                              ttl=0, parse="text", use_cache=False, source="matchid")
    except Exception as exc:  # noqa: BLE001
        return {"erreur": str(exc)}
    text = res if isinstance(res, str) else str(res)
    if text.lstrip().startswith("{"):
        import json
        try:
            return {"job": job, "en_cours": True, "etat": json.loads(text)}
        except ValueError:
            pass
    out = {"job": job, "en_cours": False, "lignes": text.count("\n")}
    if cible:
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(text, encoding="utf-8")
        out["fichier"] = str(cible)
    else:
        out["apercu"] = "\n".join(text.splitlines()[:20])
    ctx.journal.add("matchid", "appariement_resultat", {"job": job}, "positif", nb_resultats=out["lignes"])
    return out
