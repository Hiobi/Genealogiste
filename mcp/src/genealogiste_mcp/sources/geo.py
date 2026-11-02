"""API Géo (communes actuelles) + COG historique INSEE (communes fusionnées, renommées depuis 1943)."""

from __future__ import annotations

import csv
import io

from ..normalize.names import basic
from ..normalize.places import DEPARTEMENTS, normalize_place, place_key
from .base import DAY, SourceContext, envelope, error_envelope

GEO = "https://geo.api.gouv.fr"
MOD = {
    "10": "changement de nom", "20": "création", "21": "rétablissement", "30": "suppression",
    "31": "fusion simple", "32": "création de commune nouvelle", "33": "fusion-association",
    "34": "transformation de fusion-association en fusion simple", "35": "suppression de commune déléguée",
    "41": "changement de code (département)", "50": "changement de code (transfert de chef-lieu)",
    "70": "transformation de commune associée en commune déléguée", "71": "rétablissement de commune déléguée",
}


def commune(ctx: SourceContext, nom: str = "", code_postal: str = "", code_insee: str = "", departement: str = "",
            limite: int = 10) -> dict:
    fields = "nom,code,codesPostaux,codeDepartement,departement,region,population,centre"
    params = {"fields": fields, "limit": str(limite), "boost": "population"}
    if code_insee:
        url = f"{GEO}/communes/{code_insee}"
        params.pop("limit")
        params.pop("boost")
    else:
        url = f"{GEO}/communes"
        if nom:
            n = normalize_place(nom)
            params["nom"] = n.get("commune", nom)
            departement = departement or (n.get("departement_code") or "")
        if code_postal:
            params["codePostal"] = code_postal
        if departement:
            params["codeDepartement"] = departement
    shown = {k: v for k, v in params.items() if k != "fields"}
    try:
        data, cached = ctx.http.get(url, params=params, ttl=90 * DAY, source="geo")
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "geo", "communes", shown, exc)
    items = data if isinstance(data, list) else [data]
    records = []
    for c in items:
        centre = (c.get("centre") or {}).get("coordinates") or [None, None]
        dep = (c.get("departement") or {}).get("nom") or DEPARTEMENTS.get(c.get("codeDepartement", ""), "")
        records.append({
            "source": "geo", "id_externe": c.get("code"), "titre": f"{c.get('nom')} ({c.get('codeDepartement')})",
            "commune": c.get("nom"), "code_insee": c.get("code"), "codes_postaux": c.get("codesPostaux"),
            "departement": dep, "departement_code": c.get("codeDepartement"),
            "region": (c.get("region") or {}).get("nom"), "population": c.get("population"),
            "latitude": centre[1], "longitude": centre[0],
            "lieu_gedcom": f"{c.get('nom')}, {dep}, France",
        })
    return envelope(ctx, "geo", "communes", shown, records, len(records), cached,
                    note="Communes actuelles. Pour une commune disparue ou fusionnée : geo_historique.")


class Cog:
    """Fichiers COG INSEE téléchargés une fois puis mis en cache (TTL 180 jours)."""

    def __init__(self, ctx: SourceContext):
        self.ctx = ctx

    def _csv(self, url: str) -> list[dict]:
        text, _ = self.ctx.http.get(url, ttl=180 * DAY, source="cog", parse="text")
        return list(csv.DictReader(io.StringIO(text)))

    def communes(self) -> list[dict]:
        return self._csv(self.ctx.config.cog_communes_url)

    def mouvements(self) -> list[dict]:
        return self._csv(self.ctx.config.cog_mvt_url)


def history(ctx: SourceContext, nom: str = "", code_insee: str = "", departement: str = "") -> dict:
    """Historique d'une commune : noms successifs, fusions, commune actuelle de rattachement."""
    params = {"nom": nom, "code_insee": code_insee, "departement": departement}
    try:
        cog = Cog(ctx)
        communes = cog.communes()
        mvts = cog.mouvements()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "cog", "historique", params, exc)
    key = place_key(nom) if nom else ""
    dep = departement or (normalize_place(nom).get("departement_code") if nom else "") or ""
    matches = []
    for c in communes:
        if code_insee and c["COM"] != code_insee:
            continue
        if key and place_key(c["LIBELLE"]) != key and basic(c["NCC"]).replace("-", " ") != key:
            continue
        if dep and not c["COM"].startswith(dep):
            continue
        matches.append(c)
    codes = {c["COM"] for c in matches}
    events = []
    for m in mvts:
        if m["COM_AV"] in codes or m["COM_AP"] in codes:
            events.append({
                "date": m["DATE_EFF"], "type": MOD.get(m["MOD"], m["MOD"]),
                "avant": f"{m['LIBELLE_AV']} ({m['COM_AV']})", "apres": f"{m['LIBELLE_AP']} ({m['COM_AP']})",
            })
    events = [dict(t) for t in dict.fromkeys(tuple(e.items()) for e in events)]
    events.sort(key=lambda e: e["date"])
    records = []
    for c in matches:
        rec = {"source": "cog", "id_externe": c["COM"], "titre": f"{c['LIBELLE']} ({c['COM']})",
               "libelle": c["LIBELLE"], "code_insee": c["COM"], "debut": c["DATE_DEBUT"], "fin": c["DATE_FIN"] or None,
               "actuelle": not c["DATE_FIN"]}
        if c["DATE_FIN"]:
            after = [e for e in events if e["avant"].endswith(f"({c['COM']})") and e["date"] == c["DATE_FIN"]]
            if after:
                rec["devenue"] = after[-1]["apres"]
                rec["motif"] = after[-1]["type"]
        records.append(rec)
    note = ("COG INSEE : historique depuis 1943. Pour les paroisses et communes d'Ancien Régime ou les changements "
            "1790-1943, consulter le dictionnaire « Des villages de Cassini aux communes d'aujourd'hui » (EHESS).")
    return envelope(ctx, "cog", "historique", {k: v for k, v in params.items() if v}, records, len(records), False,
                    mouvements=events[:200], note=note,
                    cassini="http://cassini.ehess.fr/ (rechercher la commune par son nom)")
