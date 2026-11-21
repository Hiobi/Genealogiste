"""#282 : fiche du chercheur, signets et formats de nom dans les exports, l'import et le diagnostic.

Sortie par défaut inchangée octet pour octet ; export public sans coordonnées du chercheur ; signet d'un objet masqué
retiré ; aller-retour XML -> objets -> XML ; aucune coordonnée vers une source externe ni dans les journaux.
Données fictives uniquement.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed
from test_gramps_xml_export import erreurs

from genealogiste_mcp import privacy, server
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom
from genealogiste_mcp.gramps import lecture_xml as lx
from genealogiste_mcp.gramps import reglages as rg

FICTIF = {"name": "Chercheur Fictif", "addr": "1 rue Inventée", "locality": "Lieu-dit Fictif", "city": "Villefictive",
          "state": "Étatfictif", "country": "France", "postal": "00000", "phone": "0100000000",
          "email": "chercheur@example.org", "street": "2 rue Seconde", "county": "Comtéfictif"}
DISTINCTS = tuple(v for k, v in FICTIF.items() if k not in ("country", "postal"))  # « France », « 00000 » : génériques
FORMATS = [{"number": -1, "name": "Prénom NOM", "format": "%f %S", "active": True},
           {"number": -2, "name": "Nom, prénom", "format": "%s, %f", "active": False}]


@pytest.fixture(autouse=True)
def sans_internet(monkeypatch):
    from genealogiste_mcp import diagnostic as diag
    monkeypatch.setattr(diag, "SOURCES", {})


@pytest.fixture
def fake(tree):
    with FakeGrampsWeb(role=4) as f:
        seed(f, tree)
        yield f


@pytest.fixture
def gapp(tmp_path, fake):
    a = make_app(tmp_path)
    yield a
    server.set_app(None)


def exporter(tmp_path, format, nom="x", **kw) -> str:
    sortie = tmp_path / f"{nom}.{'ged' if format.startswith('gedcom') else format}"
    r = server.arbre_exporter(format=format, chemin=str(sortie), **kw)
    assert "erreur" not in r, r
    return sortie.read_text(encoding="utf-8"), r


def sans_uuid(xml: str) -> str:
    """L'export Gramps écrit un UUID aléatoire par objet (attribut Genealogiste-UUID) : comparé à valeur égale."""
    return re.sub(r'value="[0-9a-f]{8}-[0-9a-f-]{27}"', 'value="UUID"', xml)


def hid(fake, gid, cls="Person"):
    return fake.find(cls, gid)["handle"]


# ============================================================================ sortie par défaut inchangée

@pytest.mark.parametrize("format", ["gedcom7", "gedcom551", "gramps"])
def test_export_public_par_defaut_sans_coordonnees(gapp, fake, tmp_path, format):
    """Défaut (public) : même contenu que la fiche soit vide ou renseignée, aucune coordonnée, pas de SUBM."""
    vide, _ = exporter(tmp_path, format, "vide")
    fake.chercheur.update(FICTIF)
    plein, r = exporter(tmp_path, format, "plein")
    assert sans_uuid(plein) == sans_uuid(vide) and "chercheur" not in r
    for valeur in DISTINCTS:
        assert valeur not in plein
    assert "SUBM" not in plein
    assert format != "gramps" or "<researcher/>" in plein


def test_export_public_gedcom_octet_pour_octet_comme_avant(gapp, fake, tmp_path):
    fake.chercheur.update(FICTIF)
    contenu, _ = exporter(tmp_path, "gedcom7")
    t, _hidden, _rapport = privacy.publication(gapp.tree())
    assert contenu == write_gedcom(t, 7)  # exactement ce qu'écrit l'ancien code
    assert write_gedcom(gapp.tree()) == write_gedcom(gapp.tree(), 7, None) == write_gedcom(gapp.tree(), 7, {})


# ============================================================================ chercheur : GEDCOM

def test_export_prive_gedcom7_porte_le_soumetteur(gapp, fake, tmp_path):
    fake.chercheur.update(FICTIF)
    contenu, r = exporter(tmp_path, "gedcom7", masquer_vivants=False)
    assert "1 SUBM @SUBM@" in contenu and "0 @SUBM@ SUBM" in contenu
    bloc = contenu.split("0 @SUBM@ SUBM\n")[1].split("\n0 ")[0].splitlines()
    assert bloc[0] == "1 NAME Chercheur Fictif"
    assert "1 ADDR 1 rue Inventée" in bloc and "2 CONT Lieu-dit Fictif" in bloc and "2 CONT France" in bloc
    assert "2 ADR1 1 rue Inventée" in bloc and "2 ADR2 Lieu-dit Fictif" in bloc and "2 CITY Villefictive" in bloc
    assert "2 STAE Étatfictif" in bloc and "2 POST 00000" in bloc and "2 CTRY France" in bloc
    assert "1 PHON 0100000000" in bloc and any(x.startswith("1 EMAIL chercheur@") and "example.org" in x for x in bloc)
    assert "2 ADR1 2 rue Seconde" not in contenu  # street : Gramps écrit addr en ADR1, pas street
    assert r["chercheur"]["ecrit"] is True and r["chercheur"]["forme"] == "SUBM" and "name" in r["chercheur"]["champs"]
    arbre, info = read_gedcom(contenu)  # le fichier se relit
    assert set(arbre.personnes) == set(gapp.tree().personnes)


def test_export_prive_gedcom551_et_defaut_prive_sans_fiche(gapp, fake, tmp_path):
    fake.chercheur.update({"name": "Chercheur Fictif", "email": "chercheur@example.org"})
    contenu, _ = exporter(tmp_path, "gedcom551", masquer_vivants=False)
    assert contenu.count("0 @SUBM@ SUBM") == 1 and "1 NAME Chercheur Fictif" in contenu
    assert "ADDR" not in contenu.split("0 @SUBM@ SUBM")[1]  # rien d'inventé : pas d'adresse sans adresse
    # fiche vide : rien d'écrit, motif donné, sortie identique à l'ancienne
    for k in fake.chercheur:
        fake.chercheur[k] = ""
    sans, r = exporter(tmp_path, "gedcom551", "sans", masquer_vivants=False)
    assert "SUBM" not in sans and r["chercheur"] == {"ecrit": False, "motif": "fiche du chercheur vide dans la base Gramps"}
    assert sans == write_gedcom(gapp.tree(), 5)


def test_soumetteur_importe_remplace_par_la_fiche(gapp, fake, tmp_path):
    t = gapp.tree()
    t.extra_records.append({"tag": "SUBM", "xref": "U1", "children": [{"tag": "NAME", "value": "Autre Nom Fictif"}]})
    avec = write_gedcom(t, 7, {"name": "Chercheur Fictif"})
    assert "Autre Nom Fictif" not in avec and avec.count(" SUBM") == 2  # renvoi de l'en-tête + enregistrement
    assert "Autre Nom Fictif" in write_gedcom(t, 7)


def test_parametre_chercheur_explicite(gapp, fake, tmp_path):
    fake.chercheur.update({"name": "Chercheur Fictif"})
    plein, r = exporter(tmp_path, "gedcom7", "p", chercheur=True)  # public, demande explicite
    assert "1 NAME Chercheur Fictif" in plein and "Export public" in r["chercheur"]["avertissement"]
    non, r2 = exporter(tmp_path, "gedcom7", "n", masquer_vivants=False, chercheur=False)
    assert "SUBM" not in non and "chercheur" not in r2
    for format in ("mermaid_asc", "fiche"):
        assert "formats" in server.arbre_exporter(format=format, id="I1", chercheur=True)["erreur"]


def test_chercheur_mode_fichier_refuse(tmp_path, famille_text):
    from genealogiste_mcp.config import Config
    cfg = Config(data_dir=tmp_path / "d", cache_path=tmp_path / "c.sqlite", backend="fichier")
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    try:
        assert "mode gramps" in server.arbre_exporter(format="gedcom7", chercheur=True)["erreur"]
        ok = server.arbre_exporter(format="gedcom7", chemin=str(tmp_path / "o.ged"), masquer_vivants=False)
        assert "erreur" not in ok and "chercheur" not in ok  # rien d'inventé sans base Gramps
        assert "SUBM" not in (tmp_path / "o.ged").read_text(encoding="utf-8")
    finally:
        server.set_app(None)


def test_fiche_illisible_n_empeche_pas_l_export_prive(gapp, fake, tmp_path, monkeypatch):
    from genealogiste_mcp.gramps.client import GrampsError

    def casse(*a, **k):
        raise GrampsError("Gramps Web injoignable")

    monkeypatch.setattr(gapp.backend.client, "chercheur", casse)
    contenu, r = exporter(tmp_path, "gedcom7", masquer_vivants=False)
    assert "SUBM" not in contenu and r["chercheur"]["ecrit"] is False and "illisible" in r["chercheur"]["motif"]
    assert "illisible" in server.arbre_exporter(format="gedcom7", chercheur=True)["erreur"]


# ============================================================================ chercheur : Gramps XML

def test_export_prive_xml_researcher_valide_et_relu(gapp, fake, tmp_path):
    fake.chercheur.update(FICTIF)
    xml, r = exporter(tmp_path, "gramps", masquer_vivants=False)
    assert erreurs(xml, "1.7.1") == []
    assert "<resname>Chercheur Fictif</resname>" in xml and "<resaddr>1 rue Inventée</resaddr>" in xml
    assert "<resemail>chercheur@example.org</resemail>" in xml and "Comtéfictif" not in xml and "2 rue Seconde" not in xml
    assert r["chercheur"]["forme"] == "<researcher>" and r["chercheur"]["champs_absents_du_format"] == ["street",
                                                                                                        "county"]
    meta = lx.lire_xml(xml.encode()).meta
    assert meta.chercheur["resname"] == "Chercheur Fictif" and meta.chercheur["resphone"] == "0100000000"
    assert erreurs(exporter(tmp_path, "gramps", "p")[0], "1.7.1") == []  # public : <researcher/> vide inchangé


def test_xml_public_researcher_vide_et_gpkg_prive_porte_la_fiche(gapp, fake, tmp_path):
    fake.chercheur.update(FICTIF)
    public, _ = exporter(tmp_path, "gramps", "pub")
    assert "<researcher/>" in public and "Fictif" not in public
    r = server.arbre_exporter(format="gpkg", chemin=str(tmp_path / "x.gpkg"), masquer_vivants=False)
    assert r["chercheur"]["ecrit"] is True
    import tarfile
    with tarfile.open(tmp_path / "x.gpkg") as t:
        import gzip
        assert b"<resname>Chercheur Fictif</resname>" in gzip.decompress(t.extractfile("data.gramps").read())


# ============================================================================ signets et formats de nom : export

def charge_signets(fake):
    fake.signets["people"] = [hid(fake, "I3"), hid(fake, "I1")]
    fake.signets["families"] = [hid(fake, "F1", "Family")]
    fake.signets["sources"] = [hid(fake, "S1", "Source")]
    fake.formats_noms = FORMATS


def test_signets_et_formats_dans_l_export_prive(gapp, fake, tmp_path):
    charge_signets(fake)
    xml, r = exporter(tmp_path, "gramps", masquer_vivants=False)
    assert erreurs(xml, "1.7.1") == []
    meta = lx.lire_xml(xml.encode())
    db = meta.db
    gid = lambda cible, h: db.get(rg.CLASSE_DE_CIBLE[cible], h)["gramps_id"]  # noqa: E731
    assert [(c, gid(c, h)) for c, h in meta.meta.signets] == [
        ("person", "I3"), ("person", "I1"), ("family", "F1"), ("source", "S1")]  # ordre de la base conservé
    assert meta.meta.formats_noms == [(-1, "Prénom NOM", "%f %S", True), (-2, "Nom, prénom", "%s, %f", False)]
    assert r["signets"] == {"ecrits": 4, "retires": 0, "non_ecrits": 0}
    assert r["formats_de_noms"] == {"ecrits": 2}


def test_signets_classes_non_conservees_comptes_non_ecrits(gapp, fake, tmp_path):
    ev = next(iter(fake.objects["Event"]))
    fake.signets["events"] = [ev]
    xml, r = exporter(tmp_path, "gramps", masquer_vivants=False)
    assert r["signets"] == {"ecrits": 0, "retires": 0, "non_ecrits": 1} and "<bookmarks>" not in xml


def test_export_public_retire_le_signet_d_un_objet_masque(gapp, fake, tmp_path):
    """Un signet vers une personne masquée (vivante ou privée) disparaît ; aucun résidu identifiant."""
    t = gapp.tree()
    _, hidden, rapport = privacy.publication(t)
    assert hidden, "le jeu de test doit contenir au moins une personne masquée"
    visibles = sorted(set(t.personnes) - hidden)
    fake.signets["people"] = [hid(fake, i) for i in sorted(t.personnes)]
    xml, r = exporter(tmp_path, "gramps")
    meta = lx.lire_xml(xml.encode())
    ecrits = sorted(meta.db.get("Person", h)["gramps_id"] for c, h in meta.meta.signets if c == "person")
    assert ecrits == visibles
    assert r["signets"]["retires"] == len(hidden) and r["signets"]["ecrits"] == len(visibles)
    for pid in hidden:  # la personne masquée reste un « Vivant » anonyme : plus aucun signet ne la désigne
        assert f'<bookmark target="person" hlink="_{hid(fake, pid)}"' not in xml
    assert privacy.residues(xml, rapport["motifs"]) == []
    assert privacy.residues(re.sub(r"<[^>]*>", " ", xml), rapport["motifs"]) == []
    assert erreurs(xml, "1.7.1") == []


def test_export_public_retire_aussi_le_signet_d_une_famille_masquee(gapp, fake, tmp_path):
    fake.ui_edit("Family", "F1", lambda o: o.update(private=True))  # famille privée : masquée à la publication
    gapp.backend.snapshot(fresh=True)
    t = gapp.tree()
    _, hidden, _ = privacy.publication(t)
    masquees = {f.id for f in t.familles.values() if f.prive or f.epoux in hidden or f.epouse in hidden}
    assert masquees and set(t.familles) - masquees, "jeu de test : familles masquées et visibles"
    fake.signets["families"] = [hid(fake, i, "Family") for i in sorted(t.familles)]
    xml, _ = exporter(tmp_path, "gramps")
    lu = lx.lire_xml(xml.encode())
    ecrites = sorted(lu.db.get("Family", h)["gramps_id"] for c, h in lu.meta.signets if c == "family")
    assert ecrites == sorted(set(t.familles) - masquees)


def test_formats_de_nom_aussi_dans_l_export_public(gapp, fake, tmp_path):
    """Un format de nom ne contient aucune donnée de personne : écrit aussi en export public."""
    fake.formats_noms = FORMATS
    xml, r = exporter(tmp_path, "gramps")
    assert lx.lire_xml(xml.encode()).meta.formats_noms[0] == (-1, "Prénom NOM", "%f %S", True)
    assert r["formats_de_noms"]["ecrits"] == 2


def test_sans_signets_ni_formats_sortie_xml_inchangee(gapp, fake, tmp_path):
    """Base sans signet ni format (cas courant) : <bookmarks> et <name-formats> absents."""
    xml, r = exporter(tmp_path, "gramps")
    assert "<bookmarks>" not in xml and "<name-formats>" not in xml and r["signets"]["ecrits"] == 0


def test_aller_retour_xml_objets_xml(gapp, fake, tmp_path):
    fake.chercheur.update(FICTIF)
    charge_signets(fake)
    xml, _ = exporter(tmp_path, "gramps", masquer_vivants=False)
    lu = lx.lire_xml(xml.encode())
    from genealogiste_mcp.export.gramps_xml import db_to_xml
    assert sans_uuid(db_to_xml(lu.db, "1.7.1", lu.meta)) == sans_uuid(xml)
    # un signet vers un objet absent est refusé à l'écriture, jamais écrit
    lu.meta.signets.append(("person", "inconnu"))
    with pytest.raises(ValueError, match="Signet invalide"):
        db_to_xml(lu.db, "1.7.1", lu.meta)


# ============================================================================ import

def test_import_rapporte_chercheur_signets_formats_sans_les_recopier(gapp, fake, tmp_path):
    fake.chercheur.update(FICTIF)
    charge_signets(fake)
    xml, _ = exporter(tmp_path, "gramps", masquer_vivants=False)
    fichier = tmp_path / "entree.gramps"
    fichier.write_text(xml, encoding="utf-8")
    r = server.arbre_importer_gedcom(str(fichier), mode="ajouter")
    meta = r["import"]["metadonnees"]
    assert meta["chercheur"] == {"renseigne": True, "champs": 9} and meta["signets"] == 4 and meta["formats_noms"] == 2
    assert "rapporté seulement" in meta["usage"]
    brut = json.dumps(r, ensure_ascii=False)
    for valeur in ("Chercheur Fictif", "example.org", "rue Inventée"):
        assert valeur not in brut
    for fichier_journal in Path(gapp.config.data_dir).rglob("*.jsonl"):
        assert "Chercheur Fictif" not in fichier_journal.read_text(encoding="utf-8")


def test_import_fichier_sans_chercheur(gapp, fake, tmp_path):
    xml, _ = exporter(tmp_path, "gramps", masquer_vivants=False)
    fichier = tmp_path / "e.gramps"
    fichier.write_text(xml, encoding="utf-8")
    meta = server.arbre_importer_gedcom(str(fichier), mode="ajouter")["import"]["metadonnees"]
    assert meta["chercheur"] == {"renseigne": False, "champs": 0} and meta["signets"] == 0


# ============================================================================ diagnostic

def controle(res, nom="gramps_chercheur"):
    return next(c for c in res["controles"] if c["controle"] == nom)


def test_diagnostic_indique_seulement_renseigne_ou_vide(gapp, fake):
    c = controle(server.diagnostic())
    assert c["etat"] == "ok" and c["renseigne"] is False and "vide" in c["detail"] and c["modifiable"] is True
    fake.chercheur.update(FICTIF)
    res = server.diagnostic()
    c = controle(res)
    assert c["etat"] == "ok" and c["renseigne"] is True and "renseignée" in c["detail"]
    brut = json.dumps(res, ensure_ascii=False)
    for valeur in DISTINCTS:  # jamais le contenu : ni nom, ni adresse, ni courriel
        assert valeur not in brut


def test_diagnostic_indique_si_la_fiche_est_modifiable(tmp_path, tree):
    with FakeGrampsWeb(role=3) as f:
        seed(f, tree)
        make_app(tmp_path)
        try:
            c = controle(server.diagnostic())
            assert c["modifiable"] is False and "Owner" in c["detail"]
        finally:
            server.set_app(None)


def test_diagnostic_fiche_illisible_n_echoue_pas(gapp, fake):
    c = controle(server.diagnostic())
    assert c["etat"] == "ok"
    fake.router.get("http://gramps.test/api/metadata/").mock(return_value=httpx.Response(500, json={}))
    res = server.diagnostic()
    assert controle(res, "gramps_version")["etat"] == "attention"
    assert not [x for x in res["controles"] if x["controle"] == "gramps_chercheur"]


# ============================================================================ garanties : jamais vers l'extérieur

def test_aucune_source_externe_ne_recoit_la_fiche(gapp, fake):
    fake.chercheur.update(FICTIF)
    fake.router.route().mock(return_value=httpx.Response(200, json={}))
    server.recherche_multi("Martin", prenom="Jean")
    server.gramps_reglages()
    sortantes = [c for c in fake.router.calls if c.request.url.host != "gramps.test"]
    assert sortantes, "des requêtes externes sont attendues"
    corps = " ".join(f"{c.request.url} {c.request.content.decode(errors='ignore')} {dict(c.request.headers)}"
                     for c in sortantes)
    for valeur in DISTINCTS:
        assert valeur not in corps
    for mot in ("example.org", "Fictif"):
        assert mot not in corps


def test_la_fiche_n_entre_pas_dans_le_journal_de_recherche(gapp, fake, tmp_path):
    fake.chercheur.update(FICTIF)
    prop = server.gramps_reglages(chercheur={"name": "Nouveau Fictif"})
    server.arbre_appliquer(prop["jeton"])
    server.diagnostic()
    exporter(tmp_path, "gedcom7", masquer_vivants=False)
    exporter(tmp_path, "gramps", "g", masquer_vivants=False)
    journal = Path(gapp.config.data_dir) / "journal.jsonl"
    texte = journal.read_text(encoding="utf-8") if journal.exists() else ""
    for valeur in (*DISTINCTS, "Nouveau Fictif"):
        assert valeur not in texte
    # les valeurs du chercheur ne sont que dans le journal des transactions (nécessaire à l'annulation)
    assert "Nouveau Fictif" in (Path(gapp.config.data_dir) / "gramps-transactions.jsonl").read_text(encoding="utf-8")


def test_le_code_des_sources_externes_ignore_la_fiche():
    """Garantie statique : aucun module de sources/ ne lit la fiche ni ne l'importe."""
    racine = Path(server.__file__).parent
    for f in (racine / "sources").rglob("*.py"):
        texte = f.read_text(encoding="utf-8")
        assert not re.search(r"chercheur|researcher|reglages", texte, re.I), f.name
    appelants = {f.name for f in racine.rglob("*.py")
                 if re.search(r"\.chercheur\(|chercheur_ecrire|propose_chercheur", f.read_text(encoding="utf-8"))}
    assert appelants <= {"server.py", "backend.py", "client.py"}, appelants
