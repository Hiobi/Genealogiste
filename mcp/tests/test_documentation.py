"""Contrats de publication du wiki : liens utilisables et sources jamais écrasées."""

import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
prepare = runpy.run_path(str(ROOT / 'scripts/preparer_wiki.py'))['prepare']
REVISION = 'a' * 40


@pytest.fixture
def sources_wiki(tmp_path):
    root = tmp_path / 'code'
    (root / 'wiki').mkdir(parents=True)
    (root / 'docs').mkdir()
    (root / '.claude-plugin').mkdir()
    (root / '.claude-plugin/plugin.json').write_text('{"version":"1.2.3"}')
    (root / 'README.md').write_text('[Guide](https://github.com/Hiobi/Genealogiste/wiki/Guide)')
    pages = [{'slug': 'Home', 'source': 'wiki/Home.md', 'titre': 'Accueil', 'groupe': 'Guides'},
             {'slug': 'Guide', 'source': 'docs/guide.md', 'titre': 'Guide', 'groupe': 'Guides'}]
    (root / 'wiki/pages.json').write_text(json.dumps(pages))
    (root / 'wiki/Home.md').write_text('# Accueil\n[Guide](../docs/guide.md#étape-1)\n', encoding='utf-8')
    (root / 'docs/guide.md').write_text('# Guide\n## Étape `1`\n\n'
                                      '```markdown\n[exemple](absent.md)\n```\n'
                                      '`[autre exemple](absent.md)`\n', encoding='utf-8')
    return root, tmp_path / 'publication'


def test_publication_liens_ancres_et_exemples_preserves(sources_wiki):
    root, output = sources_wiki
    source = (root / 'docs/guide.md').read_bytes()
    assert prepare(root, output, REVISION) == 2
    home = (output / 'Home.md').read_text(encoding='utf-8')
    assert 'https://github.com/Hiobi/Genealogiste/wiki/Guide#étape-1' in home
    assert 'Genealogiste 1.2.3' in home and REVISION in home
    assert '[exemple](absent.md)' in (output / 'Guide.md').read_text()
    assert (root / 'docs/guide.md').read_bytes() == source
    (output / 'Page-manuelle.md').write_text('conserver')
    prepare(root, output, REVISION)
    assert (output / 'Page-manuelle.md').read_text() == 'conserver'


@pytest.mark.parametrize('lien', ['../docs/absent.md', '../docs/guide.md#absente',
                                  'https://github.com/Hiobi/Genealogiste/wiki/Absente'])
def test_lien_invalide_refuse_avant_ecriture(sources_wiki, lien):
    root, output = sources_wiki
    (root / 'wiki/Home.md').write_text(f'# Accueil\n[Guide]({lien})')
    with pytest.raises(ValueError):
        prepare(root, output, REVISION)
    assert not output.exists()


def test_sortie_interdite_dans_sources_et_symlink(sources_wiki):
    root, output = sources_wiki
    with pytest.raises(ValueError, match='hors du checkout'):
        prepare(root, root / 'wiki', REVISION)
    output.mkdir()
    cible = root / 'docs/guide.md'
    original = cible.read_bytes()
    (output / 'Home.md').symlink_to(cible)
    with pytest.raises(ValueError, match='non régulière'):
        prepare(root, output, REVISION)
    assert cible.read_bytes() == original
