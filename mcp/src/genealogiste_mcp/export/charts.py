"""Arbres ascendant/descendant : structure, Mermaid, SVG ; numérotation Sosa-Stradonitz."""

from __future__ import annotations

from html import escape

from ..models import Tree
from ..normalize.dates import jdn_to_gregorian, parse_date


def _years(tree: Tree, pid: str) -> str:
    p = tree.personnes[pid]

    def y(*types):
        for e in p.events(*types):
            g = parse_date(e.date)
            if g:
                lo, hi = g.interval
                prefix = "~" if hi - lo > 366 else ""
                return prefix + str(jdn_to_gregorian((lo + hi) // 2)[0])
        return ""

    b, d = y("BIRT", "CHR", "BAPM"), y("DEAT", "BURI")
    return f"{b or '?'}–{d}" if (b or d) else ""


def ancestors(tree: Tree, pid: str, generations: int = 4, hidden: set[str] | None = None) -> list[dict]:
    """Liste Sosa : [{sosa, id, nom, dates, generation}]."""
    hidden = hidden or set()
    out = []
    frontier = [(1, pid)]
    for gen in range(1, generations + 1):
        nxt = []
        for sosa, xid in frontier:
            if not xid or xid not in tree.personnes:
                continue
            p = tree.personnes[xid]
            out.append({
                "sosa": sosa, "id": xid, "generation": gen,
                "nom": "Vivant" if xid in hidden else p.nom_principal.complet,
                "dates": "" if xid in hidden else _years(tree, xid),
            })
            f, m = tree.father_mother(xid)
            nxt += [(2 * sosa, f), (2 * sosa + 1, m)]
        frontier = nxt
    return out


def descendants(tree: Tree, pid: str, generations: int = 3, hidden: set[str] | None = None) -> dict:
    hidden = hidden or set()

    def node(xid: str, depth: int, seen: set[str]) -> dict:
        p = tree.personnes[xid]
        n = {"id": xid, "nom": "Vivant" if xid in hidden else p.nom_principal.complet,
             "dates": "" if xid in hidden else _years(tree, xid), "unions": []}
        if depth >= generations or xid in seen:
            return n
        seen = seen | {xid}
        for fam in tree.spouses_families(xid):
            sp = fam.epouse if fam.epoux == xid else fam.epoux
            u = {"famille": fam.id, "conjoint": None, "enfants": []}
            if sp and sp in tree.personnes:
                u["conjoint"] = {"id": sp, "nom": "Vivant" if sp in hidden else tree.personnes[sp].nom_principal.complet}
            for link in fam.enfants:
                if link.enfant in tree.personnes:
                    u["enfants"].append(node(link.enfant, depth + 1, seen))
            n["unions"].append(u)
        return n

    return node(pid, 0, set())


def _mid(xid: str) -> str:
    return xid.replace("-", "_")


def _label(nom: str, dates: str, extra: str = "") -> str:
    s = f"{extra}{nom}" + (f"<br/>{dates}" if dates else "")
    return s.replace('"', "'")


def mermaid_ancestors(tree: Tree, pid: str, generations: int = 4, hidden: set[str] | None = None) -> str:
    rows = ancestors(tree, pid, generations, hidden)
    by_sosa = {r["sosa"]: r for r in rows}
    lines = ["flowchart BT"]
    for r in rows:
        prefix = f"{r['sosa']}. "
        lines.append(f'  S{r["sosa"]}["{_label(r["nom"], r["dates"], prefix)}"]')
    for s in by_sosa:
        if s > 1 and s // 2 in by_sosa:
            lines.append(f"  S{s} --> S{s // 2}")
    return "\n".join(lines)


def mermaid_descendants(tree: Tree, pid: str, generations: int = 3, hidden: set[str] | None = None) -> str:
    root = descendants(tree, pid, generations, hidden)
    lines = ["flowchart TD"]
    done = set()

    def walk(n: dict):
        if n["id"] not in done:
            lines.append(f'  {_mid(n["id"])}["{_label(n["nom"], n["dates"])}"]')
            done.add(n["id"])
        for u in n["unions"]:
            fid = _mid(u["famille"])
            sp = u["conjoint"]
            lab = f"× {sp['nom']}" if sp else "×"
            lines.append(f'  {fid}(("{lab.replace(chr(34), chr(39))}"))')
            lines.append(f"  {_mid(n['id'])} --- {fid}")
            for c in u["enfants"]:
                walk(c)
                lines.append(f"  {fid} --> {_mid(c['id'])}")

    walk(root)
    return "\n".join(lines)


def svg_ancestors(tree: Tree, pid: str, generations: int = 4, hidden: set[str] | None = None) -> str:
    """Arbre ascendant en éventail horizontal (génération = colonne)."""
    rows = ancestors(tree, pid, generations, hidden)
    box_w, box_h, gap_x, gap_y = 210, 44, 40, 8
    slots = 2 ** (generations - 1)
    height = slots * (box_h + gap_y) + 20
    width = generations * (box_w + gap_x) + 20
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'font-family="sans-serif" font-size="11">',
             '<rect width="100%" height="100%" fill="#fff"/>']
    pos = {}
    for r in rows:
        g = r["generation"]
        first = 2 ** (g - 1)
        idx = r["sosa"] - first
        span = slots / first
        cy = 10 + (idx + 0.5) * span * (box_h + gap_y)
        x = 10 + (g - 1) * (box_w + gap_x)
        pos[r["sosa"]] = (x, cy)
        parts.append(f'<rect x="{x}" y="{cy - box_h / 2:.1f}" width="{box_w}" height="{box_h}" rx="6" '
                     f'fill="{"#e8f0fe" if r["sosa"] % 2 == 0 else "#fdeef4"}" stroke="#555"/>')
        parts.append(f'<text x="{x + 6}" y="{cy - 4:.1f}" font-weight="bold">{r["sosa"]}. {escape(r["nom"][:32])}</text>')
        parts.append(f'<text x="{x + 6}" y="{cy + 12:.1f}" fill="#333">{escape(r["dates"])}</text>')
    for s, (x, cy) in pos.items():
        if s > 1 and s // 2 in pos:
            cx, ccy = pos[s // 2]
            parts.append(f'<path d="M{cx + box_w},{ccy:.1f} C{cx + box_w + gap_x / 2},{ccy:.1f} '
                         f'{x - gap_x / 2},{cy:.1f} {x},{cy:.1f}" fill="none" stroke="#888"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def svg_descendants(tree: Tree, pid: str, generations: int = 3, hidden: set[str] | None = None) -> str:
    root = descendants(tree, pid, generations, hidden)
    box_w, box_h, gap_x, gap_y = 230, 36, 30, 10
    rows: list[tuple[int, str, str]] = []

    def walk(n, depth):
        rows.append((depth, n["nom"], n["dates"]))
        for u in n["unions"]:
            if u["conjoint"]:
                rows.append((depth, f"× {u['conjoint']['nom']}", ""))
            for c in u["enfants"]:
                walk(c, depth + 1)

    walk(root, 0)
    height = len(rows) * (box_h + gap_y) + 20
    width = (generations + 1) * (box_w + gap_x) + 20
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'font-family="sans-serif" font-size="11">', '<rect width="100%" height="100%" fill="#fff"/>']
    for i, (depth, nom, dates) in enumerate(rows):
        x = 10 + depth * (box_w + gap_x)
        y = 10 + i * (box_h + gap_y)
        spouse = nom.startswith("× ")
        parts.append(f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="5" '
                     f'fill="{"#f5f5f5" if spouse else "#eef7ee"}" stroke="#666"/>')
        parts.append(f'<text x="{x + 6}" y="{y + 15}">{escape(nom[:36])}</text>')
        if dates:
            parts.append(f'<text x="{x + 6}" y="{y + 29}" fill="#333">{escape(dates)}</text>')
        if depth:
            parts.append(f'<line x1="{x - gap_x / 2}" y1="{y + box_h / 2}" x2="{x}" y2="{y + box_h / 2}" stroke="#888"/>')
    parts.append("</svg>")
    return "\n".join(parts)
