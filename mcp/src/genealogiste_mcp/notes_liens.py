"""Mise à jour ciblée des liens vers les fiches renommées, sans toucher au texte ni au code."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from markdown_it import MarkdownIt

_WIKI = re.compile(r"\[\[([^\]\n]+)\]\]")
_MARKDOWN = re.compile(r'(?<=\]\()(<[^>\n]+>|[^()\s]+)(?=\)|[ \t]+[\"\x27])')
_INLINE = re.compile(r"(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)")


def renommer_liens(text: str, source: Path, root: Path, renames: dict[Path, Path],
                   uniques: set[str]) -> str:
    """Réécrit les cibles wikilink/Markdown résolues vers une fiche ; alias et fragments conservés.

    ``uniques`` contient les noms de fiches non ambigus dans le vault, pour les wikilinks sans dossier.
    Les chemins du plan sont absolus ; les dossiers des fiches ne changent pas.
    """
    def destination(target: str, wiki: bool) -> str:
        path, sep, fragment = target.partition("#")
        decoded = unquote(path)
        if not decoded or urlsplit(decoded).scheme or decoded.startswith("//"):
            return target
        suffix = ".md" if not decoded.endswith(".md") and wiki else ""
        value = Path(decoded + suffix)
        if wiki and "/" not in decoded and value.stem in uniques:
            old = next((p for p in renames if p.stem == value.stem), None)
        else:
            candidates = [(source.parent / value).resolve(), (root / value).resolve()] if wiki else [
                (source.parent / value).resolve()]
            old = next((p for p in candidates if p in renames), None)
        if old is None:
            return target
        new = renames[old].stem if suffix else renames[old].name
        parent = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
        return parent + (new if wiki else quote(new, safe="")) + sep + fragment

    def prose(part: str) -> str:
        def wikilink(m):
            target, sep, label = m[1].partition("|")
            return "[[" + destination(target, True) + sep + label + "]]"

        def markdown(m):
            raw = m[1]
            angled = raw.startswith("<") and raw.endswith(">")
            value = destination(raw[1:-1] if angled else raw, False)
            return "<" + value + ">" if angled else value

        return _MARKDOWN.sub(markdown, _WIKI.sub(wikilink, part))

    def sans_code(chunk: str) -> str:
        cursor, parts = 0, []
        for match in _INLINE.finditer(chunk):
            parts.extend((prose(chunk[cursor:match.start()]), match[0]))
            cursor = match.end()
        parts.append(prose(chunk[cursor:]))
        return "".join(parts)

    # Les cartes de lignes CommonMark protègent aussi les blocs imbriqués dans une liste/citation.
    protected = {line for token in MarkdownIt("commonmark").parse(text)
                 if token.type in {"fence", "code_block", "html_block"} and token.map
                 for line in range(*token.map)}
    out, pending = [], []
    for number, line in enumerate(text.splitlines(keepends=True)):
        if number in protected:
            out.extend((sans_code("".join(pending)), line))
            pending = []
        else:
            pending.append(line)
    out.append(sans_code("".join(pending)))
    return "".join(out)
