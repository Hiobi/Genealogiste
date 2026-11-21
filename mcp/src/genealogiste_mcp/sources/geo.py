"""API Géo (communes actuelles) + COG historique INSEE (communes fusionnées, renommées depuis 1943)."""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict

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


# ---------------------------------------------------------------------------- chronologie d'une commune (#277)

# Départements supprimés depuis 1943 dont le code a été réattribué ou éclaté (COG : mouvements « changement de code
# (département) », MOD 41) : nom du département avant la date d'effet. Tout autre code garde son nom actuel.
DEPARTEMENTS_SUPPRIMES = {"75": ("Seine", "1968-01-01"), "78": ("Seine-et-Oise", "1968-01-01"),
                          "20": ("Corse", "1976-01-01")}
INSEE = re.compile(r"^(?:\d{5}|2[AB]\d{3})$")


def code_departement(code: str) -> str:
    return code[:3] if code.startswith("97") else code[:2]


def nom_departement(dep: str, fin: str | None) -> str:
    """Nom du département ``dep`` pour une période qui finit à ``fin`` (date ISO exclue ; None : en cours)."""
    ancien = DEPARTEMENTS_SUPPRIMES.get(dep)
    if ancien and fin and fin <= ancien[1]:
        return ancien[0]
    return DEPARTEMENTS.get(dep, "")


class IndexCog:
    """Fichiers COG indexés par code commune (lignes de v_commune_depuis_1943, mouvements de v_mvt_commune)."""

    def __init__(self, communes: list[dict], mouvements: list[dict]):
        self.lignes: dict[str, list[dict]] = defaultdict(list)
        for c in communes:
            self.lignes[c["COM"]].append(c)
        self.mvts: dict[str, list[dict]] = defaultdict(list)
        for m in mouvements:
            self.mvts[m["COM_AV"]].append(m)
            if m["COM_AP"] != m["COM_AV"]:
                self.mvts[m["COM_AP"]].append(m)

    def lignee(self, code: str) -> list[str]:
        """Codes successifs d'une même commune, reliés par un changement de code de département (MOD 41)."""
        vus, todo = {code}, [code]
        while todo:
            c = todo.pop()
            for m in self.mvts.get(c, []):
                if m["MOD"] == "41" and m["TYPECOM_AV"] == m["TYPECOM_AP"] == "COM":
                    for x in (m["COM_AV"], m["COM_AP"]):
                        if x not in vus:
                            vus.add(x)
                            todo.append(x)
        return sorted(vus)

    def chronologie(self, code: str) -> dict:
        """Chronologie d'une commune d'après le COG : noms successifs (périodes contiguës : un nom vaut jusqu'au
        début du suivant), départements successifs (d'après les seuls changements de code), rattachements de
        commune déléguée ou associée à une autre commune, communes absorbées. Dates ISO, ``fin`` exclue."""
        codes = self.lignee(code)
        lignes = sorted((x for c in codes for x in self.lignes.get(c, [])), key=lambda x: (x["DATE_DEBUT"], x["COM"]))
        out: dict = {"code_insee": code, "codes": codes, "connue": bool(lignes), "noms": [], "departements": [],
                     "rattachements": [], "absorbees": []}
        for x in lignes:
            if not out["noms"] or out["noms"][-1]["nom"] != x["LIBELLE"]:
                out["noms"].append({"nom": x["LIBELLE"], "debut": x["DATE_DEBUT"]})
            dep = code_departement(x["COM"])
            if not out["departements"] or out["departements"][-1]["code"] != dep:
                out["departements"].append({"code": dep, "debut": x["DATE_DEBUT"]})
        for liste in (out["noms"], out["departements"]):
            for a, b in zip(liste, liste[1:], strict=False):
                a["fin"] = b["debut"]
            if liste:
                liste[-1]["fin"] = None
        for d in out["departements"]:
            d["nom"] = nom_departement(d["code"], d["fin"])
        mvts = sorted({id(m): m for c in codes for m in self.mvts.get(c, [])}.values(),
                      key=lambda m: (m["DATE_EFF"], m["MOD"], m["COM_AV"], m["COM_AP"]))
        out["rattachements"] = _rattachements(code, mvts, lignes)
        for m in mvts:
            if m["COM_AP"] in codes and m["COM_AV"] not in codes and m["TYPECOM_AV"] == m["TYPECOM_AP"] == "COM" \
                    and m["MOD"] in ("31", "32", "33", "34"):
                out["absorbees"].append({"code_insee": m["COM_AV"], "nom": m["LIBELLE_AV"], "date": m["DATE_EFF"],
                                         "type": MOD.get(m["MOD"], m["MOD"])})
        return out


def _rattachements(code: str, mvts: list[dict], lignes: list[dict]) -> list[dict]:
    """Périodes où la commune ``code`` est déléguée ou associée d'une autre commune (de code différent)."""
    out: list[dict] = []
    for m in mvts:
        if m["COM_AV"] != code:
            continue
        courant = out[-1] if out and out[-1]["fin"] is None else None
        if m["TYPECOM_AP"] in ("COMD", "COMA") and m["COM_AP"] == code:
            parent = next((x for x in mvts if x is not m and x["DATE_EFF"] == m["DATE_EFF"] and x["MOD"] == m["MOD"]
                           and x["COM_AV"] == code and x["TYPECOM_AP"] == "COM"), None)
            statut = "commune déléguée" if m["TYPECOM_AP"] == "COMD" else "commune associée"
            if courant and (parent is None or parent["COM_AP"] == courant["code_insee"]):
                courant["statut"] = statut  # MOD 70 : associée devenue déléguée de la même commune
                continue
            if courant:
                courant["fin"] = m["DATE_EFF"]
            if parent and parent["COM_AP"] != code:
                out.append({"code_insee": parent["COM_AP"], "nom": parent["LIBELLE_AP"], "statut": statut,
                            "debut": m["DATE_EFF"], "fin": None})
        elif courant and m["TYPECOM_AV"] in ("COMD", "COMA") and m["DATE_EFF"] > courant["debut"]:
            courant["fin"] = m["DATE_EFF"]  # rétablissement, suppression de la commune déléguée, fusion simple
    for r in out:  # commune rétablie sous son code : sa nouvelle ligne clôt le rattachement
        if r["fin"] is None:
            r["fin"] = next((x["DATE_DEBUT"] for x in lignes if x["COM"] == code and x["DATE_DEBUT"] > r["debut"]),
                            None)
    return out


def chronologies(ctx: SourceContext, codes: list[str]) -> dict:
    """Chronologies COG de plusieurs communes (codes INSEE). Les deux fichiers COG sont lus une fois (cache de
    180 jours, politique réseau et limites de débit du client HTTP) ; une entrée de journal pour l'ensemble,
    positive ou négative. Renvoie l'enveloppe ``{resultats: [chronologie…]}`` ou une enveloppe d'erreur."""
    codes = sorted({c for c in codes if INSEE.match(c or "")})
    params = {"codes_insee": codes[:50] + ([f"… {len(codes) - 50} de plus"] if len(codes) > 50 else [])}
    try:
        cog = Cog(ctx)
        index = IndexCog(cog.communes(), cog.mouvements())
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "cog", "chronologie", params, exc)
    records = []
    for c in codes:
        ch = index.chronologie(c)
        if len(ch["noms"]) > 1 or len(ch["departements"]) > 1 or ch["rattachements"] or ch["absorbees"]:
            records.append({**ch, "titre": f"{ch['noms'][-1]['nom']} ({c})", "id_externe": c})
    inconnus = [c for c in codes if not index.lignes.get(c)]
    return envelope(ctx, "cog", "chronologie", params, records, len(records), False, inconnus=inconnus,
                    resume=f"{len(codes)} commune(s) : aucun changement de nom ou de département, aucun rattachement")
