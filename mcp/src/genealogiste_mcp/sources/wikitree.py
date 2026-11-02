"""WikiTree API (https://api.wikitree.com/api.php) — appId obligatoire (GENEALOGISTE_WIKITREE_APPID).

getAncestors/getDescendants étant dépréciés côté WikiTree, on utilise getPeople (ancestors=/descendants=).
"""

from __future__ import annotations

from ..normalize.dates import GREG_MONTHS, parse_date
from .base import DAY, SourceContext, envelope, error_envelope, person_record, rank

API = "https://api.wikitree.com/api.php"
FIELDS = ("Id,Name,FirstName,MiddleName,LastNameAtBirth,LastNameCurrent,Nicknames,BirthDate,DeathDate,"
          "BirthLocation,DeathLocation,Gender,Father,Mother,DataStatus,IsLiving,Privacy")
TITLE = "WikiTree, arbre collaboratif en ligne"


def _wt_date(v: str) -> str:
    """'1820-03-00' -> 'MAR 1820' ; '0000-00-00' -> ''."""
    if not v or v.startswith("0000"):
        return ""
    y, m, d = (v.split("-") + ["00", "00"])[:3]
    if m in ("00", ""):
        return str(int(y))
    month = GREG_MONTHS[int(m) - 1]
    return f"{month} {int(y)}" if d in ("00", "") else f"{int(d)} {month} {int(y)}"


def normalize(p: dict) -> dict:
    if not p or "Name" not in p:
        return {}
    gender = {"Male": "M", "Female": "F"}.get(p.get("Gender", ""), "U")
    given = " ".join(x for x in (p.get("FirstName"), p.get("MiddleName")) if x)
    key = p["Name"]
    living = str(p.get("IsLiving", "0")) == "1"
    return person_record(
        "wikitree", key, prenoms=given, nom=p.get("LastNameAtBirth", ""), sexe=gender,
        naissance={"date": _wt_date(p.get("BirthDate", "")), "lieu": p.get("BirthLocation", "")},
        deces={"date": _wt_date(p.get("DeathDate", "")), "lieu": p.get("DeathLocation", "")},
        url=f"https://www.wikitree.com/wiki/{key}",
        citation={"titre_source": TITLE, "page": f"Profil {key}", "type_source": "composite",
                  "information": "indeterminee", "preuve": "directe", "url": f"https://www.wikitree.com/wiki/{key}",
                  "note": "Arbre collaboratif : piste, pas preuve. Remonter aux sources citées sur le profil."},
        pere_id=p.get("Father") or None, mere_id=p.get("Mother") or None,
        nom_actuel=p.get("LastNameCurrent") if p.get("LastNameCurrent") != p.get("LastNameAtBirth") else None,
        vivant=True if living else None,
        wikitree_id_numerique=p.get("Id"),
    )


def _call(ctx: SourceContext, action: str, **params) -> tuple[list | dict, bool]:
    if not ctx.config.wikitree_app_id:
        raise RuntimeError("GENEALOGISTE_WIKITREE_APPID non défini (identifiant d'application WikiTree obligatoire).")
    data = {"action": action, "appId": ctx.config.wikitree_app_id, "format": "json", **params}
    return ctx.http.post(API, data=data, ttl=7 * DAY, source="wikitree")


def get_profile(ctx: SourceContext, cle: str) -> dict:
    try:
        res, cached = _call(ctx, "getProfile", key=cle, fields=FIELDS + ",Bio")
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "wikitree", "getProfile", {"cle": cle}, exc)
    prof = res[0].get("profile", {}) if res else {}
    rec = normalize(prof)
    if rec and prof.get("Bio"):
        rec["biographie_et_sources"] = prof["Bio"][:6000]
    return envelope(ctx, "wikitree", "getProfile", {"cle": cle}, [rec] if rec else [], None, cached)


def get_person(ctx: SourceContext, cle: str) -> dict:
    try:
        res, cached = _call(ctx, "getPerson", key=cle, fields=FIELDS + ",Parents,Spouses,Children")
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "wikitree", "getPerson", {"cle": cle}, exc)
    person = res[0].get("person", {}) if res else {}
    rec = normalize(person)
    if rec:
        rec["parents"] = [normalize(v) for v in (person.get("Parents") or {}).values() if normalize(v)]
        rec["enfants"] = [normalize(v) for v in (person.get("Children") or {}).values() if normalize(v)]
        rec["conjoints"] = [{"cle": s.get("Name"), "mariage_date": _wt_date(s.get("marriage_date", "")),
                             "mariage_lieu": s.get("marriage_location", "")}
                            for s in (person.get("Spouses") or [])]
    return envelope(ctx, "wikitree", "getPerson", {"cle": cle}, [rec] if rec else [], None, cached)


def _relatives(ctx: SourceContext, cle: str, sens: str, profondeur: int) -> dict:
    profondeur = max(1, min(profondeur, 10))
    op = "getAncestors" if sens == "ancestors" else "getDescendants"
    try:
        res, cached = _call(ctx, "getPeople", keys=cle, **{sens: str(profondeur)}, fields=FIELDS)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "wikitree", op, {"cle": cle, "profondeur": profondeur}, exc)
    people = (res[0].get("people") or {}) if res else {}
    records = [r for r in (normalize(p) for p in people.values()) if r]
    return envelope(ctx, "wikitree", op, {"cle": cle, "profondeur": profondeur}, records, None, cached)


def get_ancestors(ctx: SourceContext, cle: str, profondeur: int = 3) -> dict:
    return _relatives(ctx, cle, "ancestors", profondeur)


def get_descendants(ctx: SourceContext, cle: str, profondeur: int = 2) -> dict:
    return _relatives(ctx, cle, "descendants", profondeur)


def search(ctx: SourceContext, nom: str, prenom: str = "", ne_vers: str = "", lieu: str = "",
           decede_vers: str = "", limite: int = 20, personne: str | None = None) -> dict:
    params = {"LastName": nom, "FirstName": prenom, "limit": str(min(limite, 100)), "fields": FIELDS}
    by = parse_date(ne_vers) if ne_vers else None
    if by:
        params["BirthDate"] = str(by.to_dict()["annee_min"] if not by.qualifier else by.start.year)
        params["dateInclude"] = "both"
        params["dateSpread"] = "2"
    dy = parse_date(decede_vers) if decede_vers else None
    if dy:
        params["DeathDate"] = str(dy.start.year)
    if lieu:
        params["BirthLocation"] = lieu
    shown = {k: v for k, v in params.items() if k != "fields"}
    try:
        res, cached = _call(ctx, "searchPerson", **params)
        matches = res[0].get("matches", []) if res else []
        total = res[0].get("total") if res else 0
        relaxed = False
        if not matches and lieu:
            params.pop("BirthLocation")
            res, cached = _call(ctx, "searchPerson", **params)
            matches = res[0].get("matches", []) if res else []
            total = res[0].get("total") if res else 0
            relaxed = True
    except Exception as exc:  # noqa: BLE001
        return error_envelope(ctx, "wikitree", "searchPerson", shown, exc, personne)
    records = [r for r in (normalize(m) for m in matches) if r]
    rank({"nom": nom, "prenom": prenom, "ne_vers": ne_vers, "lieu": lieu, "decede_vers": decede_vers}, records)
    extra = {"note": "Lieu retiré de la requête faute de résultat (le lieu sert alors au classement)."} if relaxed else {}
    return envelope(ctx, "wikitree", "searchPerson", shown, records, total, cached, personne, **extra)
