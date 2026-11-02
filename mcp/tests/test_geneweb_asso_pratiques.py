"""ASSO (témoins, parrains), préservation GEDCOM, export GeneWeb, bonnes pratiques de métier."""

from genealogiste_mcp import server
from genealogiste_mcp.citations import format_citation
from genealogiste_mcp.evidence import assess_citations
from genealogiste_mcp.export.geneweb import to_geneweb
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom
from genealogiste_mcp.matching import compare_profiles
from genealogiste_mcp.models import Citation

MARR = "ffffffff-1111-4111-8111-111111111111"

GED7_ASSO = """0 HEAD
1 GEDC
2 VERS 7.0
0 @I1@ INDI
1 NAME Pierre /MARTIN/
1 BAPM
2 DATE 4 MAY 1846
2 ASSO @I2@
3 ROLE GODP
4 PHRASE Parrain, grand-père
2 ASSO @VOID@
3 PHRASE Anne BERNARD
3 ROLE GODP
4 PHRASE Marraine
2 OBJE @O1@
3 CROP
4 TOP 10
2 SDATE 5 MAY 1846
2 UID aaaaaaaa-0000-4000-8000-000000000001
1 ASSO @I2@
2 ROLE GODP
0 @I2@ INDI
1 NAME Jacques /MARTIN/
2 NPFX Me
0 @O1@ OBJE
1 FILE acte.jpg
2 FORM image/jpeg
0 TRLR
"""


def test_asso_gedcom7_roundtrip_lossless():
    tree, info = read_gedcom(GED7_ASSO)
    e = tree.personnes["I1"].evenements[0]
    assert info["associations"] == 3
    assert [(a.personne, a.nom, a.role, a.detail) for a in e.associations] == [
        ("I2", "", "GODP", "Parrain, grand-père"), ("", "Anne BERNARD", "GODP", "Marraine")]
    # sous-structures non modélisées conservées (OBJE, SDATE sous l'événement ; NPFX sous le nom)
    out = write_gedcom(tree)
    assert "2 OBJE @O1@\n3 CROP\n4 TOP 10" in out and "2 SDATE 5 MAY 1846" in out and "2 NPFX Me" in out
    assert "2 ASSO @VOID@\n3 PHRASE Anne BERNARD\n3 ROLE GODP\n4 PHRASE Marraine" in out
    assert write_gedcom(read_gedcom(out)[0]) == out


def test_import_real_geneweb7_export(fixtures):
    """Fichier produit par gwb2ged de GeneWeb 7.0.0 : témoins d'événement, parrain, renvoi famille."""
    tree, info = read_gedcom((fixtures / "geneweb7_gwb2ged.ged").read_text(encoding="utf-8"))
    pierre = next(p for p in tree.personnes.values() if p.nom_principal.prenoms == "Pierre"
                  and p.nom_principal.nom == "MARTIN")
    bapm = pierre.events("BAPM")[0]
    assert bapm.associations[0].role == "GODP"
    assert pierre.associations[0].detail == "Parrain"
    marr = [a for f in tree.familles.values() for e in f.evenements for a in e.associations]
    assert any(a.role == "WITN" for a in marr)
    jacques = next(p for p in tree.personnes.values() if p.nom_principal.prenoms == "Jacques")
    assert jacques.events("BIRT")[0].date == "FRENCH_R 12 VEND 3"
    # ASSO vers une famille (renvoi GeneWeb) : conservé brut
    assert any(x["tag"] == "ASSO" for p in tree.personnes.values() for x in p.extra)
    assert "1 ASSO @F2@" in write_gedcom(tree)


def test_gedcom551_asso_geneweb_style(tree):
    from genealogiste_mcp.models import Association
    tree.familles["F1"].evenements[0].associations += [
        Association(personne="I7", role="WITN", detail="Témoin"), Association(nom="Louis ROY", role="WITN")]
    out = write_gedcom(tree, 5)
    assert "2 ASSO @I7@\n3 TYPE INDI\n3 RELA Witness\n3 NOTE Témoin" in out
    assert "Louis ROY" in out  # témoin seulement nommé : en note (pas d'ASSO sans pointeur en 5.5.1)


def _add_assos(app):
    p = server.arbre_proposer([
        {"op": "ajouter_depot", "ref": "ad", "nom": "Archives départementales de la Charente-Maritime",
         "sigle": "AD17"},
        {"op": "modifier_source", "id": "S1", "champs": {"depot": "$ad"}},
        {"op": "ajouter_association", "evenement": MARR,
         "association": {"personne": "I7", "role": "temoin", "detail": "Témoin, ami de l'époux"}},
        {"op": "ajouter_association", "evenement": MARR,
         "association": {"nom": "Louis ROY", "role": "temoin", "detail": "Témoin, 40 ans, tonnelier"}},
        {"op": "ajouter_association", "personne": "I3", "association": {"personne": "I6", "role": "parrain"}},
    ], "Témoins", "Acte de mariage n° 30 et baptême")
    assert "jeton" in p, p
    server.arbre_appliquer(p["jeton"])


def test_geneweb_export(app_famille, tmp_path):
    _add_assos(app_famille)
    r = server.arbre_exporter("geneweb", str(tmp_path / "gw.ged"))
    text = (tmp_path / "gw.ged").read_text()
    assert r["statistiques"]["temoins_lies"] == 1 and r["statistiques"]["temoins_nommes"] == 1
    assert "2 VERS 5.5.1" in text and "1 CHAR UTF-8" in text
    assert "2 ASSO @I7@\n3 TYPE INDI\n3 RELA Witness" in text           # témoin d'événement GeneWeb
    assert "1 ASSO @I6@\n2 TYPE INDI\n2 RELA GODF" in text               # parrain GeneWeb
    assert "Témoins et intervenants : Témoin, 40 ans, tonnelier : Louis ROY" in text
    assert "2 SOUR AD17, 2 E 299, Registres d'état civil de Rochefort, Mariages 1845, acte n° 30" in text
    assert "Preuve : probable" in text and "Fiche de preuve" in text
    assert "_TYPE" not in text and "_UID" not in text
    # une seule naissance pour Pierre (I3), la version concurrente en note
    block = text.split("0 @I3@ INDI")[1].split("\n0 ")[0]
    assert block.count("\n1 BIRT") == 1 and "Version concurrente : 1848" in block
    # date républicaine au format GeneWeb/GEDCOM 5.5.1
    assert "@#DFRENCH R@ 12 VEND 3" in text
    # vivants masqués
    assert "Lucas" not in text


def test_geneweb_witness_persons(tree):
    from genealogiste_mcp.models import Association
    tree.familles["F1"].evenements[0].associations.append(Association(nom="Louis ROY", role="WITN"))
    text, stats = to_geneweb(tree, temoins_en_personnes=True)
    assert stats["temoins_crees"] == 1
    assert "0 @T1@ INDI\n1 NAME Louis /ROY/" in text and "2 ASSO @T1@" in text


def test_sourcing_rule(app_famille):
    r = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I4", "evenement": {"type": "DEAT", "date": "1880"}}],
                              "t", "j")
    assert "sans citation" in r["erreur"]
    r = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I4",
                                "evenement": {"type": "DEAT", "date": "1880", "non_source": True}}], "t", "j")
    assert "motif obligatoire" in r["erreur"]
    r = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I4",
                                "evenement": {"type": "DEAT", "date": "1880", "non_source": True,
                                              "motif": "tradition familiale"}}], "t", "j")
    assert "Non sourcé : tradition familiale" in r["diff"] and r["avertissements"]
    r = server.arbre_proposer([{"op": "lier_enfant", "famille": "F3", "enfant": "I5"}], "t", "j")
    assert "Filiation" in r["erreur"]


def test_unseen_and_index_only(tree):
    seen = Citation("S1", "acte 45", type_source="originale", information="primaire", consultation="image")
    index_only = Citation("S1", "acte 45", type_source="originale", information="primaire", consultation="index")
    unseen = Citation("S1", "acte 45", type_source="originale", information="primaire", consultation="non_vu")
    assert assess_citations([seen], tree)["points"] == 2
    assert assess_citations([index_only], tree)["points"] == 1
    r = assess_citations([unseen], tree)
    assert r["points"] == 0 and r["actes_a_voir"]


def test_citation_format(tree):
    tree.depots["R1"].sigle = "AD17"
    c = Citation("S1", "Naissances 1820, acte n° 45, vue 12/80", type_source="originale", information="primaire",
                 consultation="image", date_consultation="2026-11-02")
    assert format_citation(tree, c) == (
        "AD17, 2 E 299, Registres d'état civil de Rochefort, Naissances 1820, acte n° 45, vue 12/80 ; "
        "consulté le 02/11/2026 [image numérisée ; source originale ; information primaire].")


def test_network_criterion():
    a = {"prenoms": "Jean", "nom": "Martin", "reseau": ["Pierre BERNARD", "Louis ROY"]}
    b = {"prenoms": "Jean", "nom": "Martin", "reseau": ["Pierre Bernard"]}
    r = compare_profiles(a, b)
    assert any(d["critere"] == "reseau" for d in r["details"])
    r2 = compare_profiles(a, {"prenoms": "Jean", "nom": "Martin", "reseau": ["Paul DURAND"]})
    assert not any(d["critere"] == "reseau" for d in r2["details"])  # aucune pénalité


def test_proof_report_and_save(app_famille):
    rep = server.arbre_rapport_preuve("I3", "BIRT")
    assert "Rapport de preuve" in rep and "Contradictions" in rep and "acte n° 120" in rep
    r = server.rapport_enregistrer("I3", "Naissance de Pierre", rep)
    assert r["commit"] and r["fichier"].endswith("I3-naissance-de-pierre.md")


def test_fiche_lists_witnesses(app_famille):
    _add_assos(app_famille)
    f = server.arbre_fiche("I1")
    assert "Témoins, parrains et intervenants" in f and "Louis ROY" in f
    assert "## Sources citées" in f


def test_cercle(app_famille):
    r = server.arbre_cercle("I1", "etendu")
    liens = {x["id"]: x["lien"] for x in r["a_enqueter"]}
    assert liens["I1"] == "sujet" and liens["I6"] == "père" and liens["I2"] == "conjoint"
    assert liens["I3"] == "enfant" and liens["I5"] == "enfant"
    assert all(not x["vivant"] for x in r["a_enqueter"])
