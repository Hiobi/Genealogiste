"""Intégrité de l'arbre (#39, #40, #47) : cycles de parenté, références pendantes, UID d'événements dupliqués.

Contrôlé à la fin de chaque proposition (``apply_ops``) : une proposition qui introduit un de ces défauts est
refusée ; les défauts déjà présents sont signalés par ``check_tree`` sans bloquer."""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from ..models import Citation, Tree


def parents_of(tree: Tree, pid: str) -> list[str]:
    out = []
    for fid in tree.personnes[pid].famc if pid in tree.personnes else []:
        fam = tree.familles.get(fid)
        if fam and fam.child(pid):
            out += [x for x in (fam.epoux, fam.epouse) if x]
    return out


def parent_cycles(tree: Tree) -> list[list[str]]:
    """Cycles du graphe enfant → parents (auto-parenté incluse), chacun une seule fois."""
    state: dict[str, int] = {}  # 1 en cours, 2 fini
    cycles, seen = [], set()
    for start in tree.personnes:
        if state.get(start):
            continue
        stack = [(start, iter(parents_of(tree, start)))]
        path = [start]
        state[start] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
                path.pop()
                continue
            if nxt not in tree.personnes:
                continue
            if state.get(nxt) == 1:
                cyc = path[path.index(nxt):]
                key = frozenset(cyc)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cyc)
            elif not state.get(nxt):
                state[nxt] = 1
                path.append(nxt)
                stack.append((nxt, iter(parents_of(tree, nxt))))
    return cycles


def iter_citations(obj):
    """Toutes les citations d'un objet, à toute profondeur (noms, événements, associations, filiations…)."""
    if isinstance(obj, Citation):
        yield obj
    if isinstance(obj, list):
        for x in obj:
            yield from iter_citations(x)
    elif is_dataclass(obj) and not isinstance(obj, type):
        for f in fields(obj):
            if f.name != "extra":
                yield from iter_citations(getattr(obj, f.name))


def dangling(tree: Tree) -> list[str]:
    """Références vers un objet absent de l'arbre."""
    out = []

    def chk(owner: str, kind: str, ref: str, coll: dict) -> None:
        if ref and ref not in coll:
            out.append(f"{owner} → {kind} {ref} absent")

    for pid, p in tree.personnes.items():
        for f in p.famc + p.fams:
            chk(pid, "famille", f, tree.familles)
        for m in p.medias:
            chk(pid, "média", m, tree.medias)
        for n in p.notes:
            if n.startswith("@") and n.endswith("@") and len(n) > 2:
                chk(pid, "note", n.strip("@"), tree.notes)
        for a in p.associations + [a for e in p.evenements for a in e.associations]:
            chk(pid, "personne", a.personne, tree.personnes)
    for fid, f in tree.familles.items():
        for x in [f.epoux, f.epouse] + [c.enfant for c in f.enfants]:
            chk(fid, "personne", x, tree.personnes)
        for a in (a for e in f.evenements for a in e.associations):
            chk(fid, "personne", a.personne, tree.personnes)
    for sid, s in tree.sources.items():
        chk(sid, "dépôt", s.depot, tree.depots)
        chk(sid, "source", s.original, tree.sources)
    owners = [*tree.personnes.values(), *tree.familles.values(), *tree.medias.values()]
    for o in owners:
        for c in iter_citations(o):
            chk(getattr(o, "id", "?"), "source", c.source, tree.sources)
            for m in c.medias:
                chk(getattr(o, "id", "?"), "média", m, tree.medias)
    return out


def duplicate_event_uids(tree: Tree) -> list[str]:
    seen: dict[str, str] = {}
    dup = []
    for owner in [*tree.personnes.values(), *tree.familles.values()]:
        for e in owner.evenements:
            if e.uid in seen:
                dup.append(f"UID d'événement {e.uid} partagé par {seen[e.uid]} et {owner.id}")
            else:
                seen[e.uid] = owner.id
    return dup


def defects(tree: Tree) -> dict[str, set]:
    return {"cycles": {" → ".join(c) for c in parent_cycles(tree)}, "references": set(dangling(tree)),
            "uid": set(duplicate_event_uids(tree))}


def introduced(before: Tree, after: Tree) -> list[str]:
    """Défauts présents après mais pas avant (ceux d'origine ne bloquent pas une proposition)."""
    b, a = defects(before), defects(after)
    labels = {"cycles": "cycle de parenté (une personne serait son propre ascendant)",
              "references": "référence pendante", "uid": "UID d'événement dupliqué"}
    return [f"{labels[k]} : {x}" for k in a for x in sorted(a[k] - b[k])]
