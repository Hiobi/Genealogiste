"""#274 : racine Sosa et personne de référence de Gramps (`default_person`).

Diagnostic (tous les états), export Gramps XML (`<people home>`, racine masquée), aller-retour, rapport d'import.
Faux Gramps Web fidèle (`default_person` paramétrable, effacé si la personne est supprimée), données fictives.
"""

from __future__ import annotations

import gzip
import json
import re

import httpx
import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed
from test_gramps_xml_export import erreurs

from genealogiste_mcp import server
from genealogiste_mcp.export import gramps_xml
from genealogiste_mcp.gramps import lecture_xml as lx


@pytest.fixture(autouse=True)
def sans_internet(monkeypatch):
    from genealogiste_mcp import diagnostic as diag
    monkeypatch.setattr(diag, "SOURCES", {})


@pytest.fixture
def fake(tree):
    with FakeGrampsWeb() as f:
        seed(f, tree)
        yield f


def handle(fake, gid):
    return fake.find("Person", gid)["handle"]


def controle(tmp_path, backend="gramps", racine=""):
    a = make_app(tmp_path, backend=backend)
    a.config.sosa_racine = racine
    try:
        res = server.diagnostic()
    finally:
        server.set_app(None)
    return next(c for c in res["controles"] if c["controle"] == "gramps_personne_reference"), res


# ------------------------------------------------------------------ diagnostic

def test_identiques_ok(tmp_path, fake):
    fake.default_person = handle(fake, "I3")
    c, _ = controle(tmp_path, racine="I3")
    assert c["etat"] == "ok" and not c.get("remede") and c["personne_reference"] == "I3" == c["racine_sosa"]


def test_differentes_attention_avec_les_deux_identifiants(tmp_path, fake):
    fake.default_person = handle(fake, "I1")
    c, res = controle(tmp_path, racine="I3")
    assert c["etat"] == "attention" and "I3" in c["detail"] and "I1" in c["detail"]
    assert "Définir la personne de référence" in c["remede"] and "aucun point d'API" in c["remede"]
    assert any(x.startswith("gramps_personne_reference") for x in res["a_corriger"])


def test_meme_numero_complete_de_zeros_par_gramps(tmp_path, fake):
    """Gramps rend I3 « I0003 » à l'import XML : l'écart est signalé avec l'explication et la valeur à régler."""
    cible = fake.find("Person", "I3")
    cible["gramps_id"] = "I0003"
    fake.default_person = cible["handle"]
    c, _ = controle(tmp_path, racine="I3")
    assert c["etat"] == "erreur" and "introuvable" in c["detail"]  # I3 n'existe plus côté Gramps (backend gramps)
    assert "GENEALOGISTE_SOSA_RACINE=I0003" in c["remede"] and "complète les identifiants" in c["remede"]
    c, _ = controle(tmp_path, backend="fichier", racine="I0003")
    assert c["etat"] == "ok"
    fake.find("Person", "I1")["gramps_id"] = "I3"  # une autre personne porte I3 : racine existante, référence I0003
    c, _ = controle(tmp_path, racine="I3")
    assert c["etat"] == "attention" and "I0003" in c["detail"] and "complète les identifiants" in c["remede"]
    assert "GENEALOGISTE_SOSA_RACINE=I0003" in c["remede"]


def test_aucune_personne_de_reference_attention(tmp_path, fake):
    c, _ = controle(tmp_path, racine="I3")
    assert c["etat"] == "attention" and "pas de personne de référence" in c["detail"] and c["remede"]
    assert c["personne_reference"] is None


@pytest.mark.parametrize("ref", ["", "I1"])
def test_racine_non_configuree_information(tmp_path, fake, ref):
    """Information, pas un défaut : état ok, sans remède (donc hors « a_corriger »), suggestion si Gramps en a une."""
    fake.default_person = handle(fake, ref) if ref else ""
    c, res = controle(tmp_path)
    assert c["etat"] == "ok" and not c.get("remede") and "non définie" in c["detail"]
    assert c.get("suggestion") == (f"GENEALOGISTE_SOSA_RACINE={ref}" if ref else None)
    assert not any(x.startswith("gramps_personne_reference") for x in res["a_corriger"])


@pytest.mark.parametrize(("backend", "etat"), [("gramps", "erreur"), ("fichier", "attention")])
def test_racine_introuvable(tmp_path, fake, backend, etat):
    fake.default_person = handle(fake, "I1")
    c, _ = controle(tmp_path, backend, racine="I999")
    assert c["etat"] == etat and "I999" in c["detail"] and "introuvable" in c["detail"]


def test_racine_a_caracteres_etranges_jamais_envoyee(tmp_path, fake):
    fake.default_person = handle(fake, "I1")
    c, _ = controle(tmp_path, racine='I1" or "1"="1')
    assert c["etat"] == "erreur" and "introuvable" in c["detail"]


def test_reference_supprimee_cote_serveur(tmp_path, fake):
    """Supprimer la personne de référence par transaction l'efface (comportement amont) : état « aucune »."""
    from gramps_fake import URL

    from genealogiste_mcp.gramps.client import GrampsClient
    cible = fake.find("Person", "I7")
    fake.default_person = cible["handle"]
    GrampsClient(URL, "sosa", "secret").transaction(
        [{"type": "delete", "handle": cible["handle"], "_class": "Person", "old": cible, "new": None}], "suppression")
    assert fake.default_person == ""
    c, _ = controle(tmp_path, racine="I3")
    assert c["etat"] == "attention" and c["personne_reference"] is None


def test_handle_orphelin_attention(tmp_path, fake):
    fake.default_person = "handle-qui-n-existe-plus"
    c, _ = controle(tmp_path, racine="I3")
    assert c["etat"] == "attention" and "n'existe plus" in c["detail"]


def test_ne_fait_jamais_echouer_le_diagnostic(tmp_path, fake):
    """`/people/<handle>` en panne : le contrôle passe en attention, les autres restent calculés."""
    fake.default_person = handle(fake, "I1")
    cible = fake.router.routes[-1]  # route générique `/<pluriel>/<handle>`
    cible.side_effect = lambda req, **kw: httpx.Response(500, text="boom")
    c, res = controle(tmp_path, racine="I3")
    assert c["etat"] == "attention" and "500" in c["detail"]
    assert next(x for x in res["controles"] if x["controle"] == "gramps_role")["etat"] == "ok"


def test_metadata_indisponible_pas_de_controle_ni_echec(tmp_path, fake):
    fake.router.routes[2].side_effect = lambda req, **kw: httpx.Response(500, text="boom")
    a = make_app(tmp_path)
    a.config.sosa_racine = "I3"
    try:
        res = server.diagnostic()
    finally:
        server.set_app(None)
    assert not [c for c in res["controles"] if c["controle"] == "gramps_personne_reference"]
    assert next(x for x in res["controles"] if x["controle"] == "gramps_version")["etat"] == "attention"


def test_aucun_nom_dans_le_controle(tmp_path, fake):
    fake.default_person = handle(fake, "I1")
    c, _ = controle(tmp_path, racine="I3")
    texte = json.dumps(c, ensure_ascii=False)
    assert fake.default_person not in texte  # ni le handle
    assert not any(p["primary_name"]["first_name"] in texte for p in fake.objects["Person"].values())


def test_lecture_ciblee_sans_charger_l_arbre(tmp_path, fake, monkeypatch):
    from genealogiste_mcp import diagnostic_vivants
    monkeypatch.setattr(diagnostic_vivants, "controles", lambda a, inscription: [])  # #264 : lit l'arbre, à part
    fake.default_person = handle(fake, "I1")
    controle(tmp_path, racine="I3")
    appels = [str(c.request.url) for c in fake.router.calls if "/people/" in str(c.request.url)]
    assert appels and all("keys=gramps_id" in u for u in appels)  # jamais de lecture complète des personnes


# ------------------------------------------------------------------ export

def exporter(app, tmp_path, fmt="gramps", **kw):
    out = tmp_path / f"x.{fmt}"
    r = server.arbre_exporter(fmt, str(out), **kw)
    assert "erreur" not in r, r
    brut = out.read_bytes()
    if fmt == "gpkg":
        import io
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(brut), mode="r:gz") as tar:
            nom = next(n for n in tar.getnames() if n.endswith(".gramps"))
            brut = tar.extractfile(nom).read()
    if brut[:2] == b"\x1f\x8b":
        brut = gzip.decompress(brut)
    return r, brut.decode("utf-8")


def home_de(xml: str) -> str | None:
    m = re.search(r'<people home="_([^"]+)"', xml)
    return m[1] if m else None


@pytest.mark.parametrize("fmt", ["gramps", "gpkg"])
def test_export_ecrit_home_avec_la_racine(app_famille, tmp_path, fmt):
    app_famille.config.sosa_racine = "I1"
    r, xml = exporter(app_famille, tmp_path, fmt)
    h = home_de(xml)
    assert h and r["personne_reference"] == {"ecrite": "I1"}
    assert re.search(rf'<person handle="_{re.escape(h)}"[^>]* id="I1"', xml)
    assert erreurs(xml, "1.7.1") == [] or all("citationref" in e or "eventref" in e for e in erreurs(xml, "1.7.1"))


def test_export_sans_racine_n_invente_rien(app_famille, tmp_path):
    r, xml = exporter(app_famille, tmp_path)
    assert "<people>" in xml and "home=" not in xml
    assert r["personne_reference"]["ecrite"] is None and "non configurée" in r["personne_reference"]["motif"]


def test_export_racine_absente(app_famille, tmp_path):
    app_famille.config.sosa_racine = "I404"
    r, xml = exporter(app_famille, tmp_path)
    assert "home=" not in xml and "absente" in r["personne_reference"]["motif"]


def test_export_172_valide(app_famille, tmp_path):
    app_famille.config.sosa_racine = "I3"
    _, xml = exporter(app_famille, tmp_path, version_xml="1.7.2")
    assert home_de(xml) and erreurs(xml, "1.7.2") == []


def test_export_public_racine_vivante_aucune_trace(app_famille, tmp_path):
    """Lucas (I9) est vivant : masqué, il reste dans l'export sous « Vivant » ; aucun `home`, aucune trace du choix."""
    from genealogiste_mcp.gramps.mapping import tree_to_gramps
    handle_vivant = next(p["handle"] for p in tree_to_gramps(app_famille.store.load()).objects["Person"].values()
                         if p["gramps_id"] == "I9")
    app_famille.config.sosa_racine = "I9"
    r, xml = exporter(app_famille, tmp_path)
    assert "home=" not in xml and "masquée" in r["personne_reference"]["motif"]
    # la personne y figure anonymisée (« Vivant ») ; rien ne la désigne comme personne de référence
    assert f'="_{handle_vivant}"' in xml and f'home="_{handle_vivant}"' not in xml and "Lucas" not in xml


@pytest.mark.parametrize("fmt", ["gramps", "gpkg"])
def test_export_non_masque_ecrit_home_vivant(app_famille, tmp_path, fmt):
    app_famille.config.sosa_racine = "I9"
    r, xml = exporter(app_famille, tmp_path, fmt, masquer_vivants=False)
    assert home_de(xml) and r["personne_reference"] == {"ecrite": "I9"}


# ------------------------------------------------------------------ aller-retour

def test_aller_retour_xml_conserve_home(app_famille, tmp_path):
    app_famille.config.sosa_racine = "I1"
    _, xml = exporter(app_famille, tmp_path)
    lecture = lx.lire_xml(xml.encode("utf-8"))
    assert lecture.meta.personne_reference == home_de(xml)
    assert lecture.db.get("Person", lecture.meta.personne_reference)["gramps_id"] == "I1"
    assert gramps_xml.db_to_xml(lecture.db, "1.7.1", lecture.meta).count(f'<people home="_{home_de(xml)}">') == 1


# ------------------------------------------------------------------ import : rapport de home

def importer(app, tmp_path, xml: str, mode="remplacer", racine=""):
    f = tmp_path / "entree.gramps"
    f.write_text(xml, encoding="utf-8")
    app.config.sosa_racine = racine
    return server.arbre_importer_gedcom(str(f), mode)


@pytest.fixture
def xml_avec_home(app_famille, tmp_path):
    app_famille.config.sosa_racine = "I1"
    return exporter(app_famille, tmp_path)[1]


@pytest.mark.parametrize(("racine", "etat"), [("I1", "identique"), ("I3", "differente"), ("", "racine_non_definie")])
def test_import_rapporte_la_personne_de_reference(app_famille, tmp_path, xml_avec_home, racine, etat):
    res = importer(app_famille, tmp_path, xml_avec_home, racine=racine)
    ref = res["import"]["personne_reference"]
    assert ref["id"] == "I1" and ref["etat"] == etat and ref["racine_sosa"] == (racine or None)
    avert = " ".join(res.get("avertissements", []))
    if etat == "racine_non_definie":
        assert "Racine Sosa suggérée : I1" in ref["suggestion"] and "Racine Sosa suggérée : I1" in avert
    if etat == "differente":
        assert "I1" in ref["suggestion"] and "I3" in ref["suggestion"]
    if etat == "identique":
        assert "suggestion" not in ref
    assert "Lucas" not in json.dumps(ref)


def test_import_ne_modifie_jamais_la_configuration(app_famille, tmp_path, xml_avec_home, monkeypatch):
    monkeypatch.delenv("GENEALOGISTE_SOSA_RACINE", raising=False)
    importer(app_famille, tmp_path, xml_avec_home, racine="")
    assert app_famille.config.sosa_racine == "" and "GENEALOGISTE_SOSA_RACINE" not in __import__("os").environ


def test_import_mode_ajouter_signale_la_renumerotation(app_famille, tmp_path, xml_avec_home):
    ref = importer(app_famille, tmp_path, xml_avec_home, mode="ajouter", racine="I1")["import"]["personne_reference"]
    assert ref["etat"] == "a_verifier" and "renumérotés" in ref["note"]


def test_import_sans_home_pas_de_rapport(app_famille, tmp_path):
    app_famille.config.sosa_racine = ""
    _, xml = exporter(app_famille, tmp_path)
    assert "home=" not in xml
    assert "personne_reference" not in importer(app_famille, tmp_path, xml)["import"]


def test_import_home_inconnu_avertit(app_famille, tmp_path, xml_avec_home):
    xml = re.sub(r'<people home="_[^"]+"', '<people home="_fantome"', xml_avec_home)
    lecture = lx.lire_xml(xml.encode("utf-8"))
    ref = lx.rapport_personne_reference(lecture.db, lecture.meta.personne_reference, "I1")
    assert ref["etat"] == "introuvable" and ref["id"] is None
