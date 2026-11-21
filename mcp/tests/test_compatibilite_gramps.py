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
    assert set(cas) == {"xml-1.7.1", "xml-1.7.2", "gramps-gzip", "gpkg", "dates", "types", "lieux", "notes", "reference",
                       "groupes", "mediapath", "sans-mediapath", "gpkg-mediapath"}
    assert cas["xml-1.7.2"].refus_attendu == {"5.2"}
    assert all(not c.refus_attendu for n, c in cas.items() if n != "xml-1.7.2")
    assert cas["gpkg"].enrichir and cas["gpkg"].avertissements_admis


def test_cas_desktop_chemin_de_base_des_medias_280(desktop):
    """Arbre exporté avec <mediapath> = racine du vault : fichier retrouvé directement (media_path_full) ; sans
    <mediapath> : non retrouvé ; paquet : <mediapath> ignoré par Gramps. Contrôle branché sur chaque import."""
    cas = {c.nom: c for c in desktop["CAS"]}
    for nom in ("mediapath", "sans-mediapath", "gpkg-mediapath"):
        assert cas[nom].arbres == ("famille.ged",) and cas[nom].enrichir is desktop["avec_media_vault"]
    assert cas["gpkg-mediapath"].avertissements_admis == ("Base path for relative media set",)
    assert not cas["mediapath"].avertissements_admis  # aucun avertissement de Gramps pour un arbre vierge
    assert desktop["controle_chemin_base"] in desktop["CONTROLES"]


def test_cas_reference_274(desktop):
    """#274 : fichier exporté avec racine Sosa, personne de référence relue après l'import de chaque version."""
    cas = {c.nom: c for c in desktop["CAS"]}["reference"]
    assert cas.arbres == ("famille.ged",) and desktop["controle_reference"] in desktop["CONTROLES"]
    assert desktop["RACINE_REFERENCE"] == "I3"


def test_cas_groupes_276(desktop, tmp_path):
    """#276 : <namemaps> relus par db.get_name_group_mapping après l'import de chaque version ; sans regroupement,
    aucun groupe n'est inventé ; le contrôle voit un écart (groupe manquant, groupe inventé)."""
    from genealogiste_mcp.gedcom.mapping import read_gedcom
    from genealogiste_mcp.gramps.lecture_xml import lire_xml

    cas = {c.nom: c for c in desktop["CAS"]}["groupes"]
    assert cas.arbres == ("famille.ged",) and desktop["controle_groupes"] in desktop["CONTROLES"]
    groupes = dict(desktop["REGROUPEMENTS"])
    assert groupes["D'Aubigny"] == "Daubigny" and "Müller" in groupes  # apostrophe et tréma : échappement XML
    origine = read_gedcom((desktop["FIXTURES"] / "famille.ged").read_text(encoding="utf-8"))[0]
    fichier = cas.produire(origine, tmp_path)
    assert dict(lire_xml(fichier.read_bytes()).meta.regroupements) == groupes
    controle = desktop["controle_groupes"]
    assert controle(cas, "6.0", {}, {"regroupements": groupes}) == []
    assert controle(cas, "6.0", {}, {"regroupements": {}})  # groupes absents après l'import
    assert controle(cas, "6.0", {}, {"regroupements": {**groupes, "X": "Y"}})
    autre = {c.nom: c for c in desktop["CAS"]}["xml-1.7.1"]
    assert controle(autre, "6.0", {}, {"regroupements": {}}) == []
    assert controle(autre, "6.0", {}, {"regroupements": {"X": "Y"}})  # invention


def test_cas_notes_279(desktop):
    """#279 : notes stylées et liens internes relus par chaque version ; seul écart de schéma admis : styles
    strikethrough et subscript, absents des DTD et RNG livrés."""
    cas = {c.nom: c for c in desktop["CAS"]}["notes"]
    assert cas.arbres == ("famille.ged",) and set(cas.schema_admis) == {"5.2", "6.0", "6.1"}
    assert desktop["controle_notes"] in desktop["CONTROLES"]


def test_cas_dates_272(desktop):
    """#272 : inventaire des formes de date exporté (un événement par forme), relu après réexport par chaque
    version ; seuls écarts admis, nommés : from/to hors DTD de 5.2 et 6.0, limites du format XML, piège de 5.2."""
    cas = {c.nom: c for c in desktop["CAS"]}["dates"]
    assert cas.arbres == ("famille.ged",) and set(cas.schema_admis) == {"5.2", "6.0"}
    assert desktop["controle_dates"] in desktop["CONTROLES"]
    ecarts = desktop["ECARTS_DATES"]
    assert set(ecarts) == {"*", "5.2"} and len(ecarts["*"]) == 2 and len(ecarts["5.2"]) == 2
    from genealogiste_mcp.gramps.types import date_to_gramps

    plage = date_to_gramps("BET 120 BCE AND 100 BCE")
    assert desktop["date_attendue"](plage, "6.0") == plage
    texte = desktop["date_attendue"](plage, "5.2")
    assert texte["modifier"] == 6 and texte["text"] == '<daterange start="-120" stop="-100"/>'
    double = date_to_gramps("BET JULIAN 1721/22 AND JULIAN 1725")
    assert desktop["date_attendue"](double, "6.1")["dateval"][7] is True
    assert desktop["ecarts_date"](plage, texte)


def test_cas_types_273(desktop, tmp_path):
    """#273 : rôles de Gramps 6.0 (standard en 6.x, personnalisés en 5.2) et types personnalisés français dans
    l'export ; controle_types vérifie le relevé de la sonde puis l'import du réexport par Genealogiste."""
    from genealogiste_mcp.gedcom.mapping import read_gedcom
    from genealogiste_mcp.gramps.lecture_xml import lire_fichier
    from genealogiste_mcp.gramps.types import tname

    cas = {c.nom: c for c in desktop["CAS"]}["types"]
    assert cas.arbres == ("famille.ged",) and desktop["controle_types"] in desktop["CONTROLES"]
    origine = read_gedcom((ROOT / "mcp/tests/fixtures/famille.ged").read_text(encoding="utf-8"))[0]
    fichier = cas.produire(cas.enrichir(origine, tmp_path), tmp_path)
    db = lire_fichier(fichier).db
    roles = {tname(r["role"]) for p in db.all("Person").values() for r in p["event_ref_list"]}
    assert set(desktop["ROLES_60"]) <= roles and "Témoin" in roles
    perso = {(t["_class"], t["string"]) for e in db.all("Event").values() for t in [e["type"]] if t["value"] == 0}
    assert {("EventType", "Baptême"), ("EventType", "Recensement")} <= perso
    # relevé de la sonde simulé : 5.2 lit les rôles de 6.0 comme personnalisés, 6.x comme standard
    rapport = {"types": [[c, s, True] for c, s in desktop["TYPES_FRANCAIS"]]
               + [["EventRoleType", r, True] for r in desktop["ROLES_60"]]}
    ecarts = desktop["controle_types"](cas, "5.2", {}, rapport)
    assert ecarts == ["réexport absent"]
    assert any("Father" in e for e in desktop["controle_types"](cas, "6.0", {}, rapport))
    rapport["reexport"] = str(fichier)
    assert desktop["controle_types"](cas, "5.2", {}, rapport) == []


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
        if forme.retoucher:
            forme.retoucher(db)
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
