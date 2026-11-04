"""Notes de recherche Markdown : génération, idempotence, texte libre préservé, vivants masqués, hook."""

import re
import shutil
from datetime import date

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.config import Config


@pytest.fixture
def napp(tmp_path, fixtures):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", notes_dir=tmp_path / "vault",
                 sosa_racine="I3")
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    a.notes.today = lambda: date(2026, 11, 4)
    yield a
    server.set_app(None)


def snapshot(root):
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.md"))}


def test_disabled_without_directory(app):
    assert "GENEALOGISTE_NOTES_DIR" in server.notes_generer()["erreur"]


def test_generate_person_note_with_facts_and_links(napp):
    r = server.notes_generer()
    vault = napp.config.notes_dir
    assert "index.md" in snapshot(vault) and r["ecrites"]
    jean = next((vault / "personnes").glob("I1 - *.md"))
    assert jean.name == "I1 - Jean MARTIN (1820-1885).md"
    text = jean.read_text(encoding="utf-8")
    assert text.startswith("---\nid: \"I1\"\ntype: \"personne\"\n")
    assert "sosa: 2" in text  # père de la racine I3
    assert "<!-- sosa:debut faits -->" in text and "| Naissance |" in text and "Preuve" not in text.split("---")[1]
    assert "## Notes libres" in text
    # tous les wikilinks pointent vers un fichier existant
    names = {p.stem for p in vault.rglob("*.md")}
    for link in re.findall(r"\[\[([^\]|]+)", "".join(snapshot(vault).values())):
        assert link in names, link


def test_regeneration_is_idempotent_and_keeps_free_text(napp):
    server.notes_generer()
    vault = napp.config.notes_dir
    jean = next((vault / "personnes").glob("I1 - *.md"))
    text = jean.read_text(encoding="utf-8")
    fm_end = text.index("\n---\n", 4)  # propriété ajoutée dans Obsidian : en fin de frontmatter
    text = text[:fm_end] + '\nmes_tags: ["à creuser"]' + text[fm_end:]
    text += "\nHypothèse : frère cadet parti à Rochefort.\n"
    jean.write_text(text, encoding="utf-8")
    before = snapshot(vault)
    napp.notes.today = lambda: date(2027, 1, 1)
    r = server.notes_generer()
    assert r["ecrites"] == [] and snapshot(vault) == before  # aucun diff, date inchangée
    # modification de l'arbre : sections régénérées, texte libre et propriété manuelle conservés
    p = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I1", "evenement": {
        "type": "OCCU", "valeur": "charpentier", "non_source": True, "motif": "tradition familiale"}}], "Métier", "j")
    server.arbre_appliquer(p["jeton"])
    after = jean.read_text(encoding="utf-8")
    assert "charpentier" in after and "frère cadet parti à Rochefort" in after
    assert 'mes_tags: ["à creuser"]' in after and 'mis_a_jour: "2027-01-01"' in after


def test_living_masked_by_default(napp):
    server.notes_generer()
    vault = napp.config.notes_dir
    living = [p for p in (vault / "personnes").glob("*.md") if "vivant" in p.name]
    assert living, "la fixture contient une personne présumée vivante"
    t = living[0].read_text(encoding="utf-8")
    assert "vivant: true" in t and "fiche masquée" in t and "| Naissance |" not in t
    assert "erreur" in server.notes_ajouter(living[0].name.split(" - ")[0], "piste", "piste")


def test_add_entry_in_free_text(napp):
    r = server.notes_ajouter("I1", "Écrire à la mairie de Rochefort pour l'acte de 1885", "courrier")
    assert r["section"] == "Courriers"
    server.notes_ajouter("I1", "Deuxième courrier", "courrier")
    server.notes_ajouter("I1", "Vérifier le recensement 1851", "a_faire")
    text = server.notes_lire("I1")["contenu"]
    free = text.split("## Notes libres", 1)[1]
    assert free.index("### Courriers") < free.index("2026-11-04 : Écrire") < free.index("Deuxième courrier") \
        < free.index("### À faire")
    assert "erreur" in server.notes_ajouter("I1", "x", "inconnue")


def test_journal_hook_lists_research(napp):
    server.notes_generer("I1")
    server.journal_ajouter("AD17", "consultation", "negatif", "Rien dans les tables décennales 1883-1892",
                           personne="I1")
    text = server.notes_lire("I1")["contenu"]
    assert "Rien dans les tables décennales" in text and "## Recherches (journal)" in text


def test_unknown_id(napp):
    assert "inconnu" in server.notes_lire("I999")["erreur"]
