"""#307 : export public sans chemin absolu de la machine dans les formats textuels (GEDCOM 7, 5.5.1…), règle commune
avec Gramps XML (#280) ; garde-fou étendu à tous les formats textuels ; miroir Git et gramps_tirer inchangés.
Données fictives ; le répertoire personnel est simulé (Path.home patché)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import test_gramps_chemin_base as base
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed
from test_gramps_chemin_base import ACTE

from genealogiste_mcp import privacy, server
from genealogiste_mcp.export import chemins_medias, gramps_xml
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom
from genealogiste_mcp.gramps.backend import GitMirror
from genealogiste_mcp.models import Media

vapp = base.vapp  # fixtures partagées avec test_gramps_chemin_base
sans_internet = base.sans_internet

TEXTUELS = ["gedcom7", "gedcom551", "geneweb", "mermaid_asc", "mermaid_desc", "svg_asc", "svg_desc", "fiche"]
GED = ["gedcom7", "gedcom551"]


@pytest.fixture
def perso(tmp_path, monkeypatch):
    home = tmp_path / "home" / "jeanne"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _medias(a, **medias: str) -> None:
    t = a.store.load()
    for mid, fichier in medias.items():
        t.medias[mid] = Media(id=mid, fichier=fichier, titre=f"Titre {mid}")
        t.personnes["I1"].medias.append(mid)
    a.store.write(t)
    a.store.commit("medias")


def _arbre_a_chemins(vapp, perso):
    _medias(vapp, O1=str(perso / "scans" / "acte.jpg"), O2="../../jeanne/secret/x.jpg", O3=ACTE,
            O4=r"C:\Users\jeanne\a.jpg", O5="https://archives.example/v.jpg", O6="~/scans/b.jpg",
            O7=r"\\serveur\partage\jeanne\c.jpg")


def _export(fmt, sortie, **kw):
    r = server.arbre_exporter(fmt, str(sortie), id="I1", **kw)
    assert "erreur" not in r, r
    return r, sortie.read_text(encoding="utf-8")


@pytest.mark.parametrize("fmt", GED)
def test_export_public_ged_sans_chemin_absolu(vapp, perso, tmp_path, fmt):
    _arbre_a_chemins(vapp, perso)
    r, txt = _export(fmt, tmp_path / "pub.ged")
    for secret in ("jeanne", str(perso), str(vapp.config.data_dir), "serveur", "secret", "Users", ".."):
        assert secret not in txt, secret
    fichiers = [ligne.split(" ", 2)[2] for ligne in txt.splitlines() if " FILE " in ligne]
    assert fichiers == ["acte.jpg", "x.jpg", ACTE, "a.jpg", "https://archives.example/v.jpg", "b.jpg", "c.jpg"]
    assert r["chemins_absolus_reduits"] == {"nombre": 5, "medias": ["O1", "O2", "O4", "O6", "O7"]}


@pytest.mark.parametrize("fmt", GED)
def test_export_prive_ged_strictement_inchange(vapp, perso, tmp_path, fmt):
    _arbre_a_chemins(vapp, perso)
    r, txt = _export(fmt, tmp_path / "priv.ged", masquer_vivants=False)
    assert txt == write_gedcom(vapp.tree(), 7 if fmt == "gedcom7" else 5)
    assert str(perso / "scans" / "acte.jpg") in txt and "chemins_absolus_reduits" not in r


@pytest.mark.parametrize("fmt", GED)
def test_export_public_sans_chemin_absolu_inchange_octet_pour_octet(vapp, perso, tmp_path, fmt):
    _medias(vapp, O3=ACTE, O5="https://archives.example/v.jpg", O8="medias/blog/p.jpg")
    r, txt = _export(fmt, tmp_path / "pub.ged")
    attendu = write_gedcom(privacy.publication(vapp.tree())[0], 7 if fmt == "gedcom7" else 5)
    assert txt == attendu and "chemins_absolus_reduits" not in r


def test_export_public_fixture_famille_inchange(vapp, tmp_path):
    for fmt, v in (("gedcom7", 7), ("gedcom551", 5)):
        _, txt = _export(fmt, tmp_path / f"{fmt}.ged")
        assert txt == write_gedcom(privacy.publication(vapp.tree())[0], v)


@pytest.mark.parametrize("fmt", [f for f in TEXTUELS if f not in GED])
def test_autres_formats_textuels_sans_chemin(vapp, perso, tmp_path, fmt):
    """Non concernés : aucun chemin de média dans ces sorties (verrou)."""
    _arbre_a_chemins(vapp, perso)
    r, txt = _export(fmt, tmp_path / "sortie.txt")
    for secret in ("jeanne", str(perso), str(vapp.config.data_dir), "secret/x.jpg", "serveur"):
        assert secret not in txt, secret
    assert "chemins_absolus_reduits" not in r


@pytest.mark.parametrize("fmt", GED)
def test_champs_libres_porteurs_de_chemin_arretes_par_le_garde_fou(vapp, perso, tmp_path, fmt):
    """Texte libre (titre, URL, cote) : non réductible mécaniquement ; le garde-fou global le refuse."""
    t = vapp.store.load()
    t.sources[next(iter(t.sources))].url = f"file://{perso}/scans/registre.pdf"
    vapp.store.write(t)
    vapp.store.commit("url")
    sortie = tmp_path / "pub.ged"
    r = server.arbre_exporter(fmt, str(sortie))
    assert "répertoire" in r.get("erreur", "") and not sortie.exists()
    assert "erreur" not in server.arbre_exporter(fmt, str(tmp_path / "priv.ged"), masquer_vivants=False)


def test_titre_de_media_avec_repertoire_personnel_refuse(vapp, perso, tmp_path):
    t = vapp.store.load()
    t.medias["O1"] = Media(id="O1", fichier="a.jpg", titre=f"Scan {perso}/a.jpg")
    t.personnes["I1"].medias.append("O1")
    vapp.store.write(t)
    vapp.store.commit("titre")
    for fmt in GED:  # geneweb et fiche n'écrivent pas les titres de médias
        sortie = tmp_path / f"{fmt}.txt"
        r = server.arbre_exporter(fmt, str(sortie), id="I1")
        assert "répertoire" in r.get("erreur", "") and not sortie.exists(), fmt


@pytest.mark.parametrize("fmt", TEXTUELS)
def test_garde_fou_tous_formats_textuels_si_la_reduction_echoue(vapp, perso, tmp_path, monkeypatch, fmt):
    _medias(vapp, O1=str(vapp.config.data_dir / "ailleurs" / "a.jpg"))
    monkeypatch.setattr(chemins_medias, "reduire_chemins_arbre", lambda t: (t, {"nombre": 0, "medias": []}))
    sortie = tmp_path / "pub.out"
    r = server.arbre_exporter(fmt, str(sortie), id="I1")
    if fmt in GED:
        assert "répertoire" in r["erreur"] and not sortie.exists()
    else:  # les autres formats n'écrivent aucun chemin de média : pas de faux refus
        assert "erreur" not in r, r


@pytest.mark.parametrize("fmt", TEXTUELS)
def test_garde_fou_sans_faux_positif_chemin_de_sortie_dans_le_repertoire_de_donnees(vapp, perso, tmp_path, fmt):
    """Le chemin de SORTIE (sous le répertoire de données et le répertoire personnel) n'est pas du contenu."""
    sortie = vapp.config.data_dir / "exports" / "pub.out"
    r = server.arbre_exporter(fmt, str(sortie), id="I1")
    assert "erreur" not in r, r
    assert sortie.exists()


def test_regle_commune_gramps_et_gedcom(tmp_path):
    for c in ("/home/x/a.jpg", "~/a.jpg", r"C:\u\a.jpg", r"\\s\p\a.jpg", "../a.jpg", "a/../b.jpg"):
        assert chemins_medias.reduire(c) == c.replace("\\", "/").split("/")[-1], c
    for c in ("docs/a.jpg", "a.jpg", "https://x.example/../a.jpg", "file:///home/x/a.jpg", ""):
        assert chemins_medias.reduire(c) == c, c
    assert gramps_xml.nom_fichier is chemins_medias.nom_fichier and gramps_xml.sensible is chemins_medias.sensible


# ------------------------------------------------ hors périmètre : GEDCOM privé local inchangé

def test_miroir_git_ecrit_le_gedcom_prive_tel_quel(tmp_path, tree, perso, vapp):
    tree.medias["O1"] = Media(id="O1", fichier=str(perso / "scans" / "acte.jpg"))
    GitMirror(vapp.store).sync(tree, "essai")
    assert str(perso / "scans" / "acte.jpg") in vapp.store.text()


def test_gramps_tirer_garde_le_chemin_tel_quel(tmp_path, tree, fixtures, perso):
    tree.medias["O1"] = Media(id="O1", fichier=str(perso / "scans" / "acte.jpg"))
    with FakeGrampsWeb() as fake:
        seed(fake, tree)
        a = make_app(tmp_path, backend="fichier")
        shutil.copy(fixtures / "famille.ged", a.store.path)
        a.store.write(a.store.load())
        a.store.commit("fixture")
        server.gramps_tirer()
        ged = next(a.config.exports_dir.glob("grampsweb-*.ged")).read_text(encoding="utf-8")
    server.set_app(None)
    assert str(perso / "scans" / "acte.jpg") in ged
    assert read_gedcom(ged)[0].medias["O1"].fichier == str(perso / "scans" / "acte.jpg")
