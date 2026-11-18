"""Variantes françaises et allemandes d'un nom (#131).

Fonds de la Seconde Guerre mondiale (Arolsen, Bundesarchiv, Volksbund, listes de prisonniers et de déportés) :
un même homme peut y être « Jean MULLER », « Johann Müller » ou « Johann MUELLER ». Ces fonctions produisent des
graphies à essayer dans une recherche manuelle ; elles ne prouvent aucune identité (recoupement : comparer_profils).
"""

from __future__ import annotations

import itertools
import re
import unicodedata

# Prénom français (forme sans accent, minuscule) -> formes allemandes usuelles (Alsace-Moselle annexée, fonds
# allemands). Liste volontairement courte : prénoms fréquents dont la germanisation est attestée par l'usage.
PRENOMS_FR_DE: dict[str, tuple[str, ...]] = {
    "jean": ("Johann", "Johannes", "Hans"),
    "joseph": ("Josef",),
    "charles": ("Karl", "Carl"),
    "louis": ("Ludwig",),
    "pierre": ("Peter",),
    "georges": ("Georg",),
    "henri": ("Heinrich",),
    "guillaume": ("Wilhelm",),
    "jacques": ("Jakob",),
    "francois": ("Franz",),
    "michel": ("Michael",),
    "antoine": ("Anton",),
    "frederic": ("Friedrich",),
    "auguste": ("August",),
    "andre": ("Andreas",),
    "nicolas": ("Nikolaus",),
    "mathieu": ("Matthias",),
    "etienne": ("Stephan",),
    "laurent": ("Lorenz",),
    "martin": ("Martin",),
    "paul": ("Paul",),
    "eugene": ("Eugen",),
    "marie": ("Maria",),
    "anne": ("Anna",),
    "jeanne": ("Johanna",),
    "marguerite": ("Margarete",),
    "catherine": ("Katharina",),
    "madeleine": ("Magdalena",),
    "elisabeth": ("Elisabeth",),
    "louise": ("Luise",),
    "barbe": ("Barbara",),
    "therese": ("Theresia",),
    "caroline": ("Karoline",),
    "francoise": ("Franziska",),
}
PRENOMS_DE_FR: dict[str, str] = {
    _sans_accent: fr
    for fr, des in PRENOMS_FR_DE.items()
    for _sans_accent in {unicodedata.normalize("NFKD", d).encode("ascii", "ignore").decode().lower() for d in des}
}

_UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue"}
_DIPHTONGUES = ("ei", "ey", "ai", "ay")


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def cle_germanique(nom: str) -> str:
    """Clé de comparaison : umlauts et leurs transcriptions confondus, ß = ss, ei/ey/ai/ay confondus, finales
    dt/tt = t, -mann = -man. Müller = Mueller = Muller ; Meyer = Maier ; Schmidt = Schmitt = Schmid."""
    s = (nom or "").lower().replace("ß", "ss")
    for u, t in _UMLAUTS.items():
        s = s.replace(u, t)
    s = _ascii(s)
    s = re.sub(r"[^a-z]", "", s)
    s = re.sub(r"(?<=[a-z])([aou])e", r"\1", s)  # ue -> u, ae -> a, oe -> o (transcription d'umlaut)
    s = re.sub(r"e[iy]|a[iy]", "ai", s)
    s = re.sub(r"(dt|tt|d)$", "t", s)
    s = re.sub(r"mann$", "man", s)
    return s


def variantes_nom(nom: str) -> list[str]:
    """Graphies à essayer pour un nom de famille (majuscules, sans doublon, forme saisie en tête)."""
    base = (nom or "").strip()
    if not base:
        return []
    bas = base.lower()
    formes = {bas}
    # umlauts : forme transcrite (ue) et forme sans tréma (u) ; à rebours, transcription -> umlaut
    if any(u in bas for u in _UMLAUTS):
        t = bas
        for u, tr in _UMLAUTS.items():
            t = t.replace(u, tr)
        formes |= {t, _ascii(bas)}
    else:
        for u, tr in _UMLAUTS.items():
            if re.search(rf"(?<=[a-z]){tr}", bas):
                formes.add(re.sub(rf"(?<=[a-z]){tr}", u, bas))
    if "ß" in bas:
        formes.add(bas.replace("ß", "ss"))
    # ei / ey / ai / ay (Meyer, Meier, Maier, Mayer)
    for f in list(formes):
        m = re.search(r"e[iy]|a[iy]", f)
        if m:
            formes |= {f[:m.start()] + d + f[m.end():] for d in _DIPHTONGUES}
    # finales -dt / -tt / -t / -d (Schmidt, Schmitt, Schmid)
    for f in list(formes):
        m = re.search(r"(dt|tt|d|t)$", f)
        if m and len(f) > 4:
            formes |= {f[:m.start()] + fin for fin in ("dt", "tt", "t", "d")}
    # -mann / -man
    for f in list(formes):
        if f.endswith("mann"):
            formes.add(f[:-1])
        elif f.endswith("man"):
            formes.add(f + "n")
    # C / K initiaux devant a, o, u (Conrad, Konrad)
    for f in list(formes):
        if re.match(r"[ck][aou]", f):
            formes.add(("k" if f[0] == "c" else "c") + f[1:])
    tete = base.upper()
    return [tete] + sorted({f.upper() for f in formes} - {tete})


def variantes_prenom(prenom: str) -> list[str]:
    """Équivalents français / allemands d'un ou plusieurs prénoms (prénom saisi en tête)."""
    out: list[str] = []
    for tok in re.split(r"[\s,]+", (prenom or "").strip()):
        if not tok:
            continue
        cle = _ascii(tok.replace("ß", "ss")).lower()
        groupe = [tok]
        if cle in PRENOMS_FR_DE:
            groupe += list(PRENOMS_FR_DE[cle])
        elif cle in PRENOMS_DE_FR:
            fr = PRENOMS_DE_FR[cle]
            groupe += [fr.capitalize()] + [d for d in PRENOMS_FR_DE[fr] if _ascii(d).lower() != cle]
        out += [g for g in groupe if g not in out]
    return out


def combinaisons(nom: str, prenom: str = "", limite: int = 24) -> list[str]:
    """Couples « Prénom NOM » à essayer, bornés (les premières variantes sont les plus probables)."""
    noms = variantes_nom(nom)
    prenoms = variantes_prenom(prenom.split()[0]) if prenom.strip() else [""]
    return [f"{p} {n}".strip() for p, n in itertools.islice(itertools.product(prenoms, noms), limite)]
