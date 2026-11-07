"""#61 : notes de patronymes patronymes/<NOM>.md."""

import shutil
from datetime import date

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.config import Config
from genealogiste_mcp.models import Name
from genealogiste_mcp.pieces import parcourir


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


def _pieces(vault):
    ec = vault / "documents" / "État civil" / "MARTIN"
    ph = vault / "photographies" / "MARTIN"
    ec.mkdir(parents=True)
    ph.mkdir(parents=True)
    (ec / "MARTIN Jean -- ROCHEFORT - AD17 - N [1820].jpg").write_bytes(b"x")
    (ph / "MARTIN Lucas -- PHOTO [2010].jpg").write_bytes(b"x")


def test_note_patronyme_generee(napp):
    vault = napp.config.notes_dir
    _pieces(vault)
    r = server.notes_generer()
    assert "patronymes/MARTIN.md" in r["ecrites"]
    t = (vault / "patronymes" / "MARTIN.md").read_text(encoding="utf-8")
    entete = t.split("\n---\n", 1)[0]
    assert 'type: "patronyme"' in entete and 'nom: "MARTIN"' in entete
    assert "Rochefort" in t                                   # berceau
    assert "[[I1 - Jean MARTIN (1820-1885)]]" in t            # personnes liées
    assert 'WHERE patronyme = "MARTIN"' in t                  # requête Dataview
    assert "](../documents/%C3%89tat%20civil/MARTIN/MARTIN%20Jean%20--%20ROCHEFORT" in t  # pièce rangée
    assert "MARTIN Jean -- ROCHEFORT - AD17 - N \\[1820\\].jpg" in t
    assert "## Notes libres" in t
    assert (vault / "patronymes" / "DUPONT.md").exists() and (vault / "patronymes" / "BERNARD.md").exists()
    jean = next((vault / "personnes").glob("I1 - *.md")).read_text(encoding="utf-8")
    assert 'patronyme: "MARTIN"' in jean and "[[MARTIN]]" in jean
    assert "[[MARTIN]]" in (vault / "index.md").read_text(encoding="utf-8")


def test_vivants_absents_de_la_note(napp):
    vault = napp.config.notes_dir
    _pieces(vault)
    server.notes_generer()
    t = (vault / "patronymes" / "MARTIN.md").read_text(encoding="utf-8")
    assert "Lucas" not in t and "I9" not in t and "1990" not in t
    napp.notes.vivants = "complet"
    server.notes_generer()
    t = (vault / "patronymes" / "MARTIN.md").read_text(encoding="utf-8")
    assert "Lucas" in t


def test_patronyme_entierement_vivant_sans_note(napp):
    t = napp.tree()
    t.personnes["I9"].noms[0].nom = "DURAND"   # seul porteur, présumé vivant
    napp.store.write(t)
    server.notes_generer()
    assert not (napp.config.notes_dir / "patronymes" / "DURAND.md").exists()


def test_variantes_et_texte_libre_preserve(napp):
    t = napp.tree()
    t.personnes["I1"].noms.append(Name(prenoms="Joannes", nom="MARTINI", type="AKA"))
    napp.store.write(t)
    server.notes_generer()
    f = napp.config.notes_dir / "patronymes" / "MARTIN.md"
    texte = f.read_text(encoding="utf-8")
    assert "MARTINI" in texte
    f.write_text(texte + "\nOrigine savoyarde probable.\n", encoding="utf-8")
    avant = f.read_text(encoding="utf-8")
    r = server.notes_generer()
    assert "patronymes/MARTIN.md" not in r["ecrites"] and f.read_text(encoding="utf-8") == avant


def test_dossier_patronymes_protege(napp, tmp_path):
    vault = napp.config.notes_dir
    (vault / "patronymes").mkdir(parents=True)
    (vault / "patronymes" / "scan.jpg").write_bytes(b"x")
    fichiers, _ = parcourir(vault)
    assert not any(f.rel.parts[0] == "patronymes" for f in fichiers)


def test_patronyme_devenu_sans_porteur_signale(napp):
    napp.notes.vivants = "complet"
    t = napp.tree()
    t.personnes["I9"].noms[0].nom = "DURAND"
    napp.store.write(t)
    server.notes_generer()
    f = napp.config.notes_dir / "patronymes" / "DURAND.md"
    assert "Lucas" in f.read_text(encoding="utf-8")
    napp.notes.vivants = "masquer"
    r = server.notes_generer()
    texte = f.read_text(encoding="utf-8")
    assert "Lucas" not in texte and "Aucune personne affichable" in texte
    assert any("DURAND.md" in a and "plus aucune personne" in a for a in r["alertes"])


def test_lire_et_generer_un_patronyme(napp):
    r = server.notes_generer("I1")
    assert "patronymes/MARTIN.md" in r["ecrites"]
    assert "## Porteurs" in server.notes_lire("martin")["contenu"]
