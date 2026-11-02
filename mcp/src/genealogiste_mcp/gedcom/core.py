"""Lecture/écriture bas niveau des lignes GEDCOM (5.5.1 et 7) en arbre de nœuds."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LINE_RE = re.compile(r"^\s*(\d+)\s+(?:(@[^@\s]+@)\s+)?([A-Za-z0-9_]+)(?:\s(.*))?$")


@dataclass
class Node:
    tag: str
    value: str = ""
    xref: str = ""
    children: list[Node] = field(default_factory=list)

    def first(self, tag: str) -> Node | None:
        return next((c for c in self.children if c.tag == tag), None)

    def all(self, tag: str) -> list[Node]:
        return [c for c in self.children if c.tag == tag]

    def val(self, tag: str, default: str = "") -> str:
        n = self.first(tag)
        return n.value if n else default

    def add(self, tag: str, value: str = "", xref: str = "") -> Node:
        n = Node(tag, value, xref)
        self.children.append(n)
        return n

    def add_if(self, tag: str, value) -> Node | None:
        if value in (None, "", []):
            return None
        return self.add(tag, str(value))

    def to_dict(self) -> dict:
        d = {"tag": self.tag}
        if self.value:
            d["value"] = self.value
        if self.xref:
            d["xref"] = self.xref
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Node:
        return cls(d["tag"], d.get("value", ""), d.get("xref", ""),
                   [cls.from_dict(c) for c in d.get("children", [])])


def strip_xref(v: str) -> str:
    return v.strip().strip("@") if v else ""


def parse_lines(text: str) -> list[Node]:
    """Analyse un texte GEDCOM en liste d'enregistrements de niveau 0 (CONT/CONC fusionnés)."""
    text = text.lstrip("﻿")
    roots: list[Node] = []
    stack: list[tuple[int, Node]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        m = LINE_RE.match(raw)
        if not m:
            raise ValueError(f"Ligne GEDCOM invalide ({lineno}) : {raw!r}")
        level = int(m.group(1))
        xref = strip_xref(m.group(2) or "")
        tag = m.group(3).upper() if not m.group(3).startswith("_") else m.group(3)
        value = m.group(4) or ""
        if value.startswith("@@"):
            value = value[1:]
        if tag in ("CONT", "CONC") and stack:
            parent = stack[-1][1] if stack[-1][0] == level - 1 else None
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else parent
            if parent is not None:
                parent.value += ("\n" if tag == "CONT" else "") + value
            continue
        node = Node(tag, value, xref)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if level == 0:
            roots.append(node)
        elif stack:
            stack[-1][1].children.append(node)
        else:
            raise ValueError(f"Niveau incohérent ligne {lineno}")
        stack.append((level, node))
    return roots


def _esc(value: str, version: int) -> str:
    if version >= 7 and value.startswith("@") and not re.fullmatch(r"@[^@\s]+@", value):
        return "@" + value
    return value


def serialize(nodes: list[Node], version: int = 7, max_len: int = 240) -> str:
    out: list[str] = []

    def emit(node: Node, level: int) -> None:
        xref = f"@{node.xref}@ " if node.xref else ""
        lines = node.value.split("\n") if node.value else [""]
        first = _esc(lines[0], version)
        if version < 7 and len(first) > max_len:
            chunks = [first[i:i + max_len] for i in range(0, len(first), max_len)]
            out.append(f"{level} {xref}{node.tag} {chunks[0]}".rstrip())
            for c in chunks[1:]:
                out.append(f"{level + 1} CONC {c}")
        else:
            out.append(f"{level} {xref}{node.tag} {first}".rstrip())
        for extra in lines[1:]:
            out.append(f"{level + 1} CONT {_esc(extra, version)}".rstrip())
        for c in node.children:
            emit(c, level + 1)

    for n in nodes:
        emit(n, 0)
    return "\n".join(out) + "\n"
