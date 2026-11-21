"""Inventaire des formes de date Gramps (#272) : table commune aux tests unitaires et au banc Gramps Desktop.

Produit cartésien raisonné, chaque date étant un objet ``Date`` JSON que Gramps peut réellement contenir
(``Date.set`` l'accepte : vérifié par le banc ``scripts/verifier_gramps_desktop.py`` sur 5.2, 6.0 et 6.1) :

- 7 calendriers × modificateurs aucun / before / after / about / from / to (un point) et range / span (deux
  points) × qualités aucune / estimated / calculated ;
- points : jour-mois-année, mois-année, année seule, jour sans mois, année inconnue (``????``), année négative
  (grégorien, julien) ; un côté vide pour range / span ;
- double datation (``dualdated`` : Gramps force alors le calendrier julien), nouvel an (Mar1, Mar25, Sep1,
  ``mois-jour``) pour les calendriers où Gramps l'admet (grégorien, julien, suédois), avant et après la coupure ;
- dates textuelles (``textonly``), dont des textes qui ressemblent à une date ;
- dates vides porteuses d'un calendrier, d'un modificateur ou d'une qualité : refusées par ``Date.set`` mais
  présentes en JSON (``Date()`` par défaut, éditeur de Gramps Web qui garde le calendrier d'une date effacée) ;
  jamais écrites en Gramps XML.

Hors inventaire, parce que Gramps les refuse (``Date.set`` lève DateError ; à l'import XML elles deviennent des
dates textuelles portant le XML, voir ``REFUSEES``) : plage ou intervalle au début vide, plage avec nouvel an dont
le début tombe après la coupure, jour ou mois impossible.

Aucune donnée réelle : dates synthétiques.
"""

from __future__ import annotations

import itertools

# point de référence par calendrier (valide dans ce calendrier) et second point, postérieur
POINTS = {
    0: ((12, 3, 1850), (5, 6, 1860)),       # grégorien
    1: ((12, 2, 1721), (5, 6, 1725)),       # julien
    2: ((10, 8, 5600), (15, 1, 5602)),      # hébreu (8 = Nisan : présent toute année)
    3: ((12, 1, 3), (4, 13, 3)),            # républicain (4e jour complémentaire de l'an III, sextile)
    4: ((12, 1, 1300), (5, 6, 1301)),       # persan
    5: ((12, 1, 1300), (5, 6, 1301)),       # islamique
    6: ((12, 3, 1705), (1, 1, 1710)),       # suédois
}
NEGATIFS = {0, 1}  # calendriers où une année avant notre ère a un sens dans Gramps
NOUVEL_AN = {0, 1, 6}  # calendriers dont Gramps admet un nouvel an décalé (calendar_has_fixed_newyear)
UN_POINT = (0, 1, 2, 3, 7, 8)
COMPOSES = (4, 5)
QUALITES = (0, 1, 2)
TEXTES = ("vers la Saint-Jean", "1850", "ABT 1850", "(entre parenthèses)", "12 mars 1850", "",
          "  espaces  ", "INT 1850 (texte)", "<dateval val=\"1850-02-30\"/>")


def _variantes(cal: int) -> list[tuple[str, tuple[int, int, int]]]:
    (d, m, y), _ = POINTS[cal]
    out = [("jma", (d, m, y)), ("ma", (0, m, y)), ("a", (0, 0, y)), ("j-sans-mois", (d, 0, y)),
           ("annee-inconnue", (d, m, 0)), ("mois-seul", (0, m, 0))]
    if cal in NEGATIFS:
        out += [("negatif", (d, m, -y)), ("negatif-a", (0, 0, -y))]
    return out


def _date(cal: int, mod: int, qual: int, val: list, ny=0, text: str = "") -> dict:
    from genealogiste_mcp.gramps.types import valeur_tri

    d = {"_class": "Date", "format": None, "calendar": cal, "modifier": mod, "quality": qual,
         "dateval": val, "text": text, "sortval": 0, "newyear": ny}
    d["sortval"] = valeur_tri(d)
    return d


def inventaire() -> list[tuple[str, dict]]:
    """(nom stable, Date JSON) pour chaque forme. Le nom décrit la forme (calendrier, modificateur…)."""
    out: list[tuple[str, dict]] = []
    for cal, mod, qual in itertools.product(POINTS, UN_POINT, QUALITES):
        for nom, (d, m, y) in _variantes(cal):
            out.append((f"c{cal}-m{mod}-q{qual}-{nom}", _date(cal, mod, qual, [d, m, y, False])))
    for cal, mod, qual in itertools.product(POINTS, COMPOSES, QUALITES):
        (d1, m1, y1), (d2, m2, y2) = POINTS[cal]
        paires = [("jma", (d1, m1, y1), (d2, m2, y2)), ("a", (0, 0, y1), (0, 0, y2)),
                  ("fin-vide", (d1, m1, y1), (0, 0, 0)),
                  ("inverse", (d2, m2, y2), (d1, m1, y1)), ("annee-inconnue", (d1, m1, 0), (d2, m2, 0))]
        if cal in NEGATIFS:
            paires += [("negatif", (d1, m1, -y2), (d2, m2, -y1))]
        for nom, a, b in paires:
            out.append((f"c{cal}-m{mod}-q{qual}-{nom}", _date(cal, mod, qual, [*a, False, *b, False])))
    # double datation : Gramps la range toujours en julien (Date.set)
    for mod, qual in itertools.product((0, 1, 3, 7, 8), QUALITES):
        out.append((f"double-m{mod}-q{qual}", _date(1, mod, qual, [12, 2, 1722, True])))
        out.append((f"double-a-m{mod}-q{qual}", _date(1, mod, qual, [0, 0, 1700, True])))
    for mod in COMPOSES:
        out.append((f"double-m{mod}", _date(1, mod, 0, [12, 2, 1722, True, 5, 1, 1725, True])))
        out.append((f"double-debut-m{mod}", _date(1, mod, 0, [12, 2, 1722, True, 5, 6, 1725, False])))
        out.append((f"double-negatif-m{mod}", _date(1, mod, 0, [12, 2, -1725, True, 5, 1, -1722, True])))
    out.append(("double-negatif", _date(1, 0, 0, [12, 2, -1722, True])))
    # nouvel an : avant et après la coupure, un et deux points
    for cal, ny in itertools.product(sorted(NOUVEL_AN), (1, 2, 3, [4, 15])):
        (d, m, y), (d2, m2, y2) = POINTS[cal]
        nyn = ny if isinstance(ny, int) else "-".join(map(str, ny))
        for nom, val in (("fev", [12, 2, y, False]), ("oct", [12, 10, y, False]), ("a", [0, 0, y, False])):
            for mod, qual in ((0, 0), (3, 1), (8, 2)):
                out.append((f"ny{nyn}-c{cal}-{nom}-m{mod}-q{qual}", _date(cal, mod, qual, val, ny)))
        out.append((f"ny{nyn}-c{cal}-m4", _date(cal, 4, 0, [12, 2, y, False, d2, m2, y2, False], ny)))
        if cal == 1:
            out.append((f"ny{nyn}-double", _date(1, 0, 0, [12, 2, 1722, True], ny)))
    # textes
    for i, t in enumerate(TEXTES):
        out.append((f"texte-{i}", _date(0, 6, 0, [0, 0, 0, False], text=t)))
    # dates vides porteuses d'un attribut
    for nom, (cal, mod, qual) in (("vide-c1", (1, 0, 0)), ("vide-m1", (0, 1, 0)), ("vide-q1", (0, 0, 1)),
                                  ("vide-m4", (0, 4, 0)), ("vide", (0, 0, 0))):
        val = [0, 0, 0, False] + ([0, 0, 0, False] if mod in COMPOSES else [])
        out.append((nom, _date(cal, mod, qual, val)))
    return out


# Formes refusées par Gramps (Date.set : DateError, vérifié sur 5.2.4 et 6.0.8) : élément XML -> raison.
REFUSEES = {
    '<daterange start="" stop="1860-06-05"/>': "début vide",
    '<datespan start="????" stop="1860"/>': "début vide",
    '<daterange start="1850-10-12" stop="1860-06-05" newyear="Mar25"/>': "nouvel an, début après la coupure",
    '<dateval val="1850-02-30"/>': "30 février",
    '<dateval val="1850-13-01"/>': "mois 13",
    '<dateval val="0003-13-07" cformat="French Republican"/>': "7e jour complémentaire de l'an III",
    '<dateval val="1300-12-31" cformat="Islamic"/>': "31 du 12e mois islamique",
}


# Champs comparés pour l'identité d'une date relue (tous ceux que l'objet JSON Gramps porte) ; ``text`` d'une
# date non textuelle est comparé à part (saisie libre non affichée, absente du Gramps XML).
CHAMPS = ("calendar", "modifier", "quality", "dateval", "newyear", "sortval")


def ecarts(a: dict, b: dict, texte: bool = True) -> list[str]:
    out = []
    for k in CHAMPS:
        va, vb = a.get(k), b.get(k)
        if k == "dateval":
            va, vb = list(va or []), list(vb or [])
        if k == "newyear":
            va, vb = (list(va) if isinstance(va, (list, tuple)) else va or 0,
                      list(vb) if isinstance(vb, (list, tuple)) else vb or 0)
        if va != vb:
            out.append(f"{k}: {va!r} -> {vb!r}")
    if (texte or a.get("modifier") == 6) and (a.get("text") or "") != (b.get("text") or ""):
        out.append(f"text: {a.get('text')!r} -> {b.get('text')!r}")
    return out
