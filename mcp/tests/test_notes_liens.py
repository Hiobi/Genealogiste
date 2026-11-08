"""Un renommage met à jour les destinations, conserve alias, texte, code et liens externes."""

from urllib.parse import quote

import pytest

from genealogiste_mcp.notes_liens import renommer_liens


@pytest.fixture
def liens(tmp_path):
    old = tmp_path / "personnes/I1 - Jean MARTIN (1820-1885).md"
    new = old.with_name("I1 - Jean MARTIN (1820-av 1925).md")
    return tmp_path, old, new


def test_wikilinks_alias_fragments_et_chemins(liens):
    root, old, new = liens
    text = (f"[[{old.stem}]] [[{old.stem}#Faits|Jean]] "
            f"![[personnes/{old.name}#^bloc]] [[../personnes/{old.stem}|lien]]")
    attendu = (f"[[{new.stem}]] [[{new.stem}#Faits|Jean]] "
               f"![[personnes/{new.name}#^bloc]] [[../personnes/{new.stem}|lien]]")
    assert renommer_liens(text, root / "recherches/note.md", root, {old: new}, {old.stem}) == attendu


def test_markdown_destinations_encodees_seules(liens):
    root, old, new = liens
    url_old, url_new = quote("../personnes/" + old.name), quote("../personnes/" + new.name)
    text = f'[{old.stem}]({url_old}#faits "titre") ![]({url_old})\n'
    text += f'[{old.stem}](https://example.test/{url_old})\n{old.stem}'
    attendu = f'[{old.stem}]({url_new}#faits "titre") ![]({url_new})\n'
    attendu += f'[{old.stem}](https://example.test/{url_old})\n{old.stem}'
    assert renommer_liens(text, root / "recherches/note.md", root, {old: new}, {old.stem}) == attendu


def test_liens_dans_code_conserves(liens):
    root, old, new = liens
    link = f"[[{old.stem}]]"
    for text in (f"`{link}`", f"``code `{link}` code``", f"```markdown\n{link}\n```\n",
                 f"~~~markdown\n{link}\n~~~\n", f"`code\n{link}\ncode`",
                 f"> ```markdown\n> {link}\n> ```\n", f"    {link}\n"):
        assert renommer_liens(text, root / "note.md", root, {old: new}, {old.stem}) == text


def test_bare_wikilink_ambigu_et_homonyme_non_modifies(liens):
    root, old, new = liens
    text = f"[[{old.stem}]] [[autre/{old.stem}]] [homonyme]({quote(old.name)})"
    assert renommer_liens(text, root / "autre/note.md", root, {old: new}, set()) == text
