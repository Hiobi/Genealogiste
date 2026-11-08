"""Génère le wiki depuis les sources versionnées, contrôle ses liens ; aucune publication réseau."""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/Hiobi/Genealogiste'
WIKI = REPO + '/wiki'
MARKDOWN = MarkdownIt('commonmark').enable('table')
LINK = re.compile(r'(!?\[[^\]\n]*\]\()([^\s)]+)(\))')
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})')


def anchors(text: str) -> set[str]:
    """Ancres de titres GitHub, y compris les doublons et les titres contenant du code inline."""
    found, counts = set(), {}
    tokens = MARKDOWN.parse(text)
    for i, token in enumerate(tokens):
        if token.type != 'heading_open':
            continue
        title = ''.join(c.content for c in tokens[i + 1].children or [] if c.type in ('text', 'code_inline'))
        slug = re.sub(r'[^\w\- ]', '', html.unescape(title).lower()).replace(' ', '-')
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        found.add(slug + (f'-{count}' if count else ''))
    return found


def links(text: str):
    for token in MARKDOWN.parse(text):
        for child in token.children or []:
            if child.type == 'link_open':
                yield child.attrGet('href')
            elif child.type == 'image':
                yield child.attrGet('src')


def sources(root: Path) -> dict[str, dict]:
    pages = {}
    used = set()
    for entry in json.loads((root / 'wiki/pages.json').read_text(encoding='utf-8')):
        slug = entry['slug']
        source = (root / entry['source']).resolve()
        if not re.fullmatch(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*', slug) or slug in pages:
            raise ValueError(f'Nom de page invalide ou dupliqué : {slug}')
        if not source.is_relative_to(root) or not source.is_file() or source in used:
            raise ValueError(f'Source absente, extérieure ou dupliquée : {source}')
        used.add(source)
        pages[slug] = {**entry, 'path': source}
    if 'Home' not in pages:
        raise ValueError('Page Home manquante')
    return pages


def rewrite(text: str, source: Path, root: Path, mapping: dict[Path, str], revision: str) -> str:
    def replace(match):
        target = urlsplit(match[2])
        if target.scheme or target.netloc or not target.path:
            return match[0]
        path = (source.parent / unquote(target.path)).resolve()
        if not path.is_relative_to(root) or not path.exists():
            raise ValueError(f'{source.name} : lien local absent ou extérieur : {match[2]}')
        if path in mapping:
            base = WIKI + '/' + mapping[path]
        else:
            kind = 'tree' if path.is_dir() else 'blob'
            base = f'{REPO}/{kind}/{revision}/' + quote(path.relative_to(root).as_posix())
        url = urlsplit(base)
        return match[1] + urlunsplit((*url[:3], target.query, target.fragment)) + match[3]

    lines, fence = [], ''
    for line in text.splitlines(keepends=True):
        marker = FENCE.match(line)
        if marker:
            if not fence:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not line[marker.end():].strip():
                fence = ''
            lines.append(line)
        elif fence:
            lines.append(line)
        else:
            # Ne pas transformer les exemples de liens écrits dans du code inline.
            parts = re.split(r'(`+[^`]*`+)', line)
            lines.append(''.join(part if i % 2 else LINK.sub(replace, part) for i, part in enumerate(parts)))
    return ''.join(lines)


def check_links(text: str, source: Path, root: Path, rendered: dict[str, str], published: bool = False) -> None:
    for href in links(text):
        target = urlsplit(href)
        fragment = unquote(target.fragment)
        if href == WIKI or href.startswith(WIKI + '/') or href.startswith(WIKI + '#'):
            slug = unquote(target.path.removeprefix('/Hiobi/Genealogiste/wiki').strip('/')) or 'Home'
            if slug not in rendered:
                raise ValueError(f'{source.name} : page wiki absente : {href}')
            content = rendered[slug]
        elif target.scheme or target.netloc:
            if target.scheme not in ('http', 'https', 'mailto'):
                raise ValueError(f'{source.name} : protocole de lien invalide : {href}')
            continue
        else:
            if published and target.path:
                raise ValueError(f'{source.name} : lien relatif non réécrit : {href}')
            path = (source.parent / unquote(target.path)).resolve() if target.path else source
            if not path.is_relative_to(root) or not path.exists():
                raise ValueError(f'{source.name} : cible absente ou extérieure : {href}')
            if path.is_dir() or path.suffix != '.md':
                continue
            content = path.read_text(encoding='utf-8')
        if fragment and fragment not in anchors(content):
            raise ValueError(f'{source.name} : ancre absente : {href}')


def prepare(root: Path, output: Path, revision: str) -> int:
    root, output = root.resolve(), output.resolve()
    if output == root or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError('La sortie doit être hors du checkout du code, sans en être un parent')
    pages = sources(root)
    mapping = {entry['path']: slug for slug, entry in pages.items()}
    version = json.loads((root / '.claude-plugin/plugin.json').read_text(encoding='utf-8'))['version']
    rendered = {slug: rewrite(entry['path'].read_text(encoding='utf-8'), entry['path'], root, mapping, revision)
                for slug, entry in pages.items()}
    check_links((root / 'README.md').read_text(encoding='utf-8'), root / 'README.md', root, rendered)
    for slug, entry in pages.items():
        # Vérifier avant réécriture afin de contrôler aussi les ancres des références conservées dans docs/.
        check_links(entry['path'].read_text(encoding='utf-8'), entry['path'], root, rendered)
        check_links(rendered[slug], entry['path'], root, rendered, published=True)
    for name in [*(f'{slug}.md' for slug in pages), '_Sidebar.md']:
        destination = output / name
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise ValueError(f'Destination non régulière : {destination}')
    output.mkdir(parents=True, exist_ok=True)
    for slug, entry in pages.items():
        footer = (f'\n\n---\n[Accueil]({WIKI}) · Genealogiste {version} · '
                  f'[Source {revision[:8]}]({REPO}/blob/{revision}/{quote(entry["source"])})\n\n'
                  'Page générée depuis le dépôt du code ; proposer les corrections dans sa source.\n')
        (output / f'{slug}.md').write_text(rendered[slug].rstrip() + footer, encoding='utf-8')
    sidebar, group = ['[Accueil](' + WIKI + ')\n'], None
    for slug, entry in pages.items():
        if slug == 'Home':
            continue
        if entry['groupe'] != group:
            group = entry['groupe']
            sidebar.append(f'\n**{group}**\n')
        sidebar.append(f'- [{entry["titre"]}]({WIKI}/{slug})\n')
    (output / '_Sidebar.md').write_text(''.join(sidebar), encoding='utf-8')
    return len(pages)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    try:
        count = prepare(ROOT, args.output, revision)
    except ValueError as exc:
        parser.exit(1, str(exc) + '\n')
    print(f'Wiki : {count} pages et navigation générées ; liens locaux et ancres vérifiés.')


if __name__ == '__main__':
    main()
