"""Matrice de compatibilité Gramps (#267) : fichier des images, constantes, compose, workflow et documentation
concordent ; outillage Gramps Desktop vérifié sans la bibliothèque `gramps` (exécutée par make test-gramps-desktop)."""

import json
import re
import runpy
from pathlib import Path

import pytest

from genealogiste_mcp.gramps import compatibilite as c

ROOT = Path(__file__).resolve().parents[2]
MATRICE = json.loads((ROOT / "compatibilite-gramps.json").read_text(encoding="utf-8"))
WEB = {e["role"]: e for e in MATRICE["gramps_web"]}
DOC_WEB = (ROOT / "docs/gramps-web.md").read_text(encoding="utf-8")
DOC_DESKTOP = (ROOT / "docs/gramps.md").read_text(encoding="utf-8")


def test_images_epinglees_par_empreinte_et_roles():
    assert set(WEB) == {"plancher", "epinglee", "plafond"}
    for e in MATRICE["gramps_web"]:
        assert re.fullmatch(r"ghcr\.io/gramps-project/grampsweb@sha256:[0-9a-f]{64}", e["image"]), e
        assert c.version_api(e["api"]) is not None
    images = [e["image"] for e in MATRICE["gramps_web"]]
    assert len(set(images)) == len(images)


def test_plage_api_concorde_avec_les_images():
    apis = sorted(c.version_api(e["api"]) for e in MATRICE["gramps_web"])
    assert (apis[0], apis[-1]) == (c.API_TESTEE_MIN, c.API_TESTEE_MAX)
    assert c.version_api(WEB["plancher"]["api"]) == c.API_TESTEE_MIN
    assert c.version_api(WEB["plafond"]["api"]) == c.API_TESTEE_MAX
    assert c.version_api(WEB["epinglee"]["api"]) == c.API_EPINGLEE


def test_compose_de_test_utilise_l_image_epinglee():
    compose = (ROOT / "docker-compose.test.yml").read_text(encoding="utf-8")
    assert re.findall(r"^\s+image: (\S+)$", compose, re.M) == ["${GRAMPSWEB_IMAGE:-" + WEB["epinglee"]["image"] + "}"]


def test_workflow_lit_la_matrice():
    wf = (ROOT / ".github/workflows/gramps.yml").read_text(encoding="utf-8")
    assert "matrice_gramps.py github-web" in wf and "matrice_gramps.py github-desktop" in wf
    assert "fail-fast: false" in wf
    for uses in re.findall(r"uses: (\S+)", wf):
        assert re.search(r"@[0-9a-f]{40}$", uses), f"action non épinglée par SHA : {uses}"


def test_matrice_github():
    m = runpy.run_path(str(ROOT / "scripts/matrice_gramps.py"))
    web = m["github_web"]()["include"]
    assert [e["image"] for e in web] == [e["image"] for e in MATRICE["gramps_web"]]
    assert [e["version"] for e in m["github_desktop"]()["include"]] == list(c.GRAMPS_DESKTOP_TESTES)


def test_versions_desktop_concordent_et_sont_epinglees():
    assert tuple(e["version"] for e in MATRICE["gramps_desktop"]) == c.GRAMPS_DESKTOP_TESTES
    for e in MATRICE["gramps_desktop"]:
        assert e["xml"] in ("1.7.1", "1.7.2")
        if "pypi" in e:
            assert re.fullmatch(r"gramps==\d+\.\d+\.\d+", e["pypi"])
        else:
            assert re.fullmatch(r"[0-9a-f]{40}", e["git"]["commit"]) and e["git"]["tag"].startswith("v")


def test_documentation_web_cite_la_matrice():
    for e in MATRICE["gramps_web"]:
        assert f"`{e['tag']}`" in DOC_WEB and e["api"] in DOC_WEB and e["image"].split("@")[1] in DOC_WEB
    assert f"API ≥ {c.texte_version(c.API_TESTEE_MIN)}" in DOC_WEB
    for nom, v in c.FONCTIONS_API.items():
        assert f"`{nom}`" in DOC_WEB and c.texte_version(v) in DOC_WEB, nom


def test_documentation_desktop_cite_les_versions():
    for e in MATRICE["gramps_desktop"]:
        assert e.get("pypi", e.get("git", {}).get("tag", "")) in DOC_DESKTOP
        assert f"Gramps {e['version']}" in DOC_DESKTOP
    assert MATRICE["gramps_desktop"][-1]["git"]["commit"] in DOC_DESKTOP


@pytest.mark.parametrize(("texte", "verdict"), [
    ("3.25.1", "testee"), ("v3.26.0", "testee"), (c.texte_version(c.API_TESTEE_MIN), "testee"),
    ("2.9.2", "trop_ancienne"), ("3.27.0", "plus_recente"), ("4.0.0", "plus_recente"),
    ("3.7.1.1", "testee" if c.API_TESTEE_MIN <= (3, 7, 1) else "trop_ancienne"),
    ("", "inconnue"), (None, "inconnue"), ("inconnue", "inconnue"),
])
def test_verdict_api(texte, verdict):
    assert c.verdict_api(texte) == verdict


@pytest.fixture(scope="module")
def desktop():
    return runpy.run_path(str(ROOT / "scripts/verifier_gramps_desktop.py"))


def test_inventaire_de_l_export_genealogiste(desktop, tmp_path):
    """Les objets attendus (modèle Gramps de Genealogiste) sont ceux que l'export écrit, handles compris."""
    from genealogiste_mcp.gedcom.mapping import read_gedcom
    from genealogiste_mcp.gramps.mapping import tree_to_gramps_stats

    tree = read_gedcom((ROOT / "mcp/tests/fixtures/famille.ged").read_text(encoding="utf-8"))[0]
    db, _ = tree_to_gramps_stats(tree, None, False)
    fichier = desktop["produire_xml_genealogiste"](tree, tmp_path)
    inventaire = desktop["inventaire_xml"](fichier)
    assert inventaire["Person"] and inventaire["Citation"]
    assert desktop["comparer"]({k: sorted(db.all(k)) for k in desktop["CLASSES"]}, inventaire, "x") == []
    inventaire["Note"] = inventaire["Note"][1:]
    assert desktop["comparer"]({k: sorted(db.all(k)) for k in desktop["CLASSES"]}, inventaire, "x")


def test_inventaire_lit_le_gzip_et_les_handles_gramps(desktop, tmp_path):
    import gzip
    f = tmp_path / "a.gramps"
    f.write_bytes(gzip.compress(b'<database xmlns="http://gramps-project.org/xml/1.7.2/"><people>'
                                b'<person handle="_ab_c" id="I1"/></people><tags><tag handle="_t1"/></tags>'
                                b'</database>'))
    inv = desktop["inventaire_xml"](f)
    assert inv["Person"] == ["abc"] and inv["Tag"] == ["t1"] and inv["Family"] == []


def test_version_desktop_inconnue_refusee(desktop):
    with pytest.raises(SystemExit):
        desktop["main"](["--version", "4.2"])
