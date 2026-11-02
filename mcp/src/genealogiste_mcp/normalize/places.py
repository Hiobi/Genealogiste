"""Lieux : normalisation des libellés (paroisse ↔ commune, Saint/St, département)."""

from __future__ import annotations

import re

from .names import basic, jaro_winkler

DEPARTEMENTS = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence", "05": "Hautes-Alpes",
    "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes", "09": "Ariège", "10": "Aube", "11": "Aude",
    "12": "Aveyron", "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud", "2B": "Haute-Corse",
    "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse", "24": "Dordogne", "25": "Doubs", "26": "Drôme",
    "27": "Eure", "28": "Eure-et-Loir", "29": "Finistère", "30": "Gard", "31": "Haute-Garonne", "32": "Gers",
    "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine", "36": "Indre", "37": "Indre-et-Loire",
    "38": "Isère", "39": "Jura", "40": "Landes", "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire",
    "44": "Loire-Atlantique", "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne", "48": "Lozère",
    "49": "Maine-et-Loire", "50": "Manche", "51": "Marne", "52": "Haute-Marne", "53": "Mayenne",
    "54": "Meurthe-et-Moselle", "55": "Meuse", "56": "Morbihan", "57": "Moselle", "58": "Nièvre", "59": "Nord",
    "60": "Oise", "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme", "64": "Pyrénées-Atlantiques",
    "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales", "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône",
    "70": "Haute-Saône", "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie",
    "75": "Paris", "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sèvres",
    "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var", "84": "Vaucluse", "85": "Vendée",
    "86": "Vienne", "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne", "90": "Territoire de Belfort",
    "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis", "94": "Val-de-Marne",
    "95": "Val-d'Oise", "971": "Guadeloupe", "972": "Martinique", "973": "Guyane", "974": "La Réunion",
    "976": "Mayotte",
}
# Anciens noms de départements -> code actuel
ANCIENS_DEPARTEMENTS = {
    "charente-inferieure": "17", "seine-inferieure": "76", "loire-inferieure": "44", "basses-pyrenees": "64",
    "basses-alpes": "04", "cotes-du-nord": "22", "seine-et-oise": "78", "seine": "75", "mayenne-et-loire": "49",
}
_DEP_BY_NAME = {basic(v).replace("-", " "): k for k, v in DEPARTEMENTS.items()}
_DEP_BY_NAME.update({k.replace("-", " "): v for k, v in ANCIENS_DEPARTEMENTS.items()})

PREFIXES = [
    r"^paroisse (?:de |d'|du |des )?", r"^parr?oisse (?:de |d')?", r"^commune (?:de |d')?",
    r"^ville (?:de |d')?", r"^bourg (?:de |d')?", r"^village (?:de |d')?",
]


def expand_saints(s: str) -> str:
    s = re.sub(r"\bste\b\.?", "sainte", s)
    s = re.sub(r"\bst\b\.?", "saint", s)
    return s


def place_key(name: str) -> str:
    s = expand_saints(basic(name).replace("-", " ").replace("'", " "))
    for p in PREFIXES:
        s = re.sub(p, "", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_place(text: str) -> dict:
    """'St Jean d'Angély (17)' -> commune, département, pays, clé de comparaison."""
    if not text:
        return {}
    raw = text.strip()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    commune = parts[0] if parts else raw
    dep_code = None
    m = re.search(r"\((\d{2,3}|2[AB])\)", commune)
    if m:
        dep_code = m.group(1)
        commune = commune[: m.start()].strip()
    pays = None
    lieu_dit = None
    for p in parts[1:]:
        k = basic(p).replace("-", " ")
        if re.fullmatch(r"\d{5}", p):
            continue
        if re.fullmatch(r"\d{2,3}|2[ab]", k):
            dep_code = dep_code or p.upper()
        elif k in _DEP_BY_NAME:
            dep_code = dep_code or _DEP_BY_NAME[k]
        elif k in ("france", "fr"):
            pays = "France"
        elif pays is None and len(parts) > 2 and p is parts[-1]:
            pays = p
    if " - " in commune:
        commune, lieu_dit = (x.strip() for x in commune.split(" - ", 1))
    clean = commune
    for pre in ("paroisse de ", "paroisse d'", "commune de ", "ville de "):
        if clean.lower().startswith(pre):
            clean = clean[len(pre):]
    clean = re.sub(r"\bSt\b\.?", "Saint", clean)
    clean = re.sub(r"\bSte\b\.?", "Sainte", clean)
    out = {
        "original": raw,
        "commune": clean,
        "cle": place_key(clean),
        "departement_code": dep_code,
        "departement": DEPARTEMENTS.get(dep_code) if dep_code else None,
        "pays": pays or ("France" if dep_code else None),
    }
    if lieu_dit:
        out["lieu_dit"] = lieu_dit
    return out


def gedcom_place(commune: str, dep_code: str | None = None, pays: str = "France") -> str:
    parts = [commune]
    if dep_code and dep_code in DEPARTEMENTS:
        parts.append(DEPARTEMENTS[dep_code])
    if pays:
        parts.append(pays)
    return ", ".join(parts)


def place_similarity(a: str, b: str) -> dict:
    if not a or not b:
        return {"score": 0.5, "raison": "lieu manquant"}
    na, nb = normalize_place(a), normalize_place(b)
    if na["departement_code"] and nb["departement_code"] and na["departement_code"] != nb["departement_code"]:
        same_name = na["cle"] == nb["cle"]
        return {"score": 0.3 if same_name else 0.05,
                "raison": "même nom mais départements différents" if same_name else "départements différents"}
    if na["cle"] == nb["cle"]:
        return {"score": 1.0, "raison": "même lieu (normalisé)"}
    if na["cle"] in nb["cle"] or nb["cle"] in na["cle"]:
        return {"score": 0.85, "raison": "l'un inclut l'autre (commune fusionnée ou paroisse ?)"}
    jw = jaro_winkler(na["cle"], nb["cle"])
    return {"score": round(jw * 0.9, 3), "raison": f"similarité {jw:.2f}"}
