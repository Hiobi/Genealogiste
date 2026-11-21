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
    fichier = desktop["produire_xml"]("1.7.1")(tree, tmp_path)
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


def test_cas_desktop_de_l_export_268(desktop):
    """Formes remises à Gramps : 1.7.1, 1.7.2 (refusée par 5.2 seulement), .gramps gzip, .gpkg avec média."""
    cas = {c.nom: c for c in desktop["CAS"]}
    assert set(cas) == {"xml-1.7.1", "xml-1.7.2", "gramps-gzip", "gpkg"}
    assert cas["xml-1.7.2"].refus_attendu == {"5.2"}
    assert all(not c.refus_attendu for n, c in cas.items() if n != "xml-1.7.2")
    assert cas["gpkg"].enrichir and cas["gpkg"].avertissements_admis


def test_cas_desktop_produisent_des_fichiers_lisibles(desktop, tmp_path):
    import tarfile

    from genealogiste_mcp.gedcom.mapping import read_gedcom
    from genealogiste_mcp.gramps.mapping import tree_to_gramps_stats

    origine = read_gedcom((ROOT / "mcp/tests/fixtures/famille.ged").read_text(encoding="utf-8"))[0]
    for forme in desktop["CAS"]:
        dossier = tmp_path / forme.nom
        dossier.mkdir()
        tree = forme.enrichir(origine, dossier) if forme.enrichir else origine
        db, _ = tree_to_gramps_stats(tree, None, False)
        fichier = forme.produire(tree, dossier)
        attendu = {k: sorted(db.all(k)) for k in desktop["CLASSES"]}
        assert desktop["comparer"](attendu, desktop["inventaire_xml"](fichier), forme.nom) == []
        xml = desktop["lire_xml"](fichier)
        assert xml.startswith(b"<?xml") and (b"xml/1.7.2/" in xml) == (forme.nom == "xml-1.7.2")
    with tarfile.open(tmp_path / "gpkg" / "genealogiste.gpkg") as tar:
        assert sorted(tar.getnames()) == ["data.gramps", desktop["MEDIA_TEST"]]


def test_validation_contre_les_schemas_de_la_bibliotheque(desktop):
    schemas = {k: str(ROOT / f"mcp/tests/fixtures/gramps-xml/1.7.2/grampsxml.{k}") for k in ("dtd", "rng")}
    entete = (b'<database xmlns="http://gramps-project.org/xml/1.7.1/"><header><created date="2026-01-01" '
              b'version="5.2.0"/><researcher/></header>')
    assert desktop["valider_schemas"](entete + b"</database>", schemas) == []  # étiquette ramenée au schéma
    assert desktop["valider_schemas"](entete + b"<inconnu/></database>", schemas)


def test_controle_champ_par_champ(desktop):
    date = {"_class": "Date", "modifier": 0, "text": "1 JAN 1800", "sortval": 1, "dateval": [1, 1, 1800, False]}
    modele = [{"_class": "Person", "handle": "a_b", "gramps_id": "I1", "change": 0, "gender": 1,
               "primary_name": {"_class": "Name", "first_name": "Jean", "date": date}}]
    importe = {"_class": "Person", "handle": "ab", "gramps_id": "I0001", "change": 1795000000, "gender": 1,
               "familysearch_sync": {}, "primary_name": {"_class": "Name", "first_name": "Jean",
                                                         "date": {**date, "text": "", "sortval": 2}}}
    cas, controle, cle = desktop["CAS"][0], desktop["controle_champs"], desktop["MODELE"]
    assert controle(cas, "6.0", {cle: modele}, {"objets": [importe]}) == []
    importe["primary_name"]["first_name"] = "Jea"
    assert controle(cas, "6.0", {cle: modele}, {"objets": [importe]})
    assert controle(cas, "5.2", {cle: modele}, {}) == []  # Gramps 5.2 : pas de format JSON


def test_sens_inverse_branche_sur_le_banc(desktop):
    """#269 : le réexport de chaque bibliothèque est relu par Genealogiste puis réimporté (cycle) ; arbre fictif
    écrit par Gramps et arbre d'exemple épinglé au commit de la bibliothèque 6.1."""
    assert desktop["controle_lecture"] in desktop["CONTROLES"]
    six_un = next(e for e in MATRICE["gramps_desktop"] if e["version"] == "6.1")
    assert desktop["EXEMPLE"]["commit"] == six_un["git"]["commit"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in desktop["EXEMPLE"]["fichiers"].values())
    for v in c.GRAMPS_DESKTOP_TESTES:  # fixtures écrites par la vraie bibliothèque, une par version
        assert {p.name for p in (ROOT / f"mcp/tests/fixtures/gramps-desktop/gramps-{v}").iterdir()} == \
            set(desktop["FORMATS_GENERES"])


def test_controle_lecture_et_ecarts_admis(desktop, tmp_path):
    """Relecture du réexport : aller-retour XML et objets champ par champ ; seuls écarts admis, ceux de l'écriture
    de Gramps (espaces de bord retirés par fix, somme de contrôle calculée)."""
    from genealogiste_mcp.export.gramps_xml import db_to_xml
    from genealogiste_mcp.gramps.mapping import GrampsDb

    o = {"_class": "Tag", "handle": "t1", "change": 1, "name": "x", "color": "#000000000000", "priority": 0}
    f = tmp_path / "reexport.gramps"
    f.write_text(db_to_xml(GrampsDb.from_objects([o])), encoding="utf-8")
    rapport = {"reexport": str(f), "objets": [o], "handles": {"Tag": ["t1"]}}
    assert desktop["controle_lecture"](desktop["CAS"][0], "6.0", {}, rapport) == []
    assert Path(rapport["cycle"]).is_file()
    assert desktop["controle_lecture"](desktop["CAS"][0], "6.0", {}, {**rapport, "objets": [{**o, "name": "y"}]})
    ecarts = desktop["_ecarts_stricts"]
    assert list(ecarts({"v": "a "}, {"v": "a"}, "x")) and not list(ecarts({"v": "a "}, {"v": "a"}, "x", True))
    assert not list(ecarts({"checksum": ""}, {"checksum": "abc"}, "x", True))
    assert list(ecarts({"checksum": "abd"}, {"checksum": "abc"}, "x", True))
    assert list(ecarts({"a": 1}, {"a": 1, "b": 2}, "x"))  # clé en trop : écart (comparaison dans les deux sens)
