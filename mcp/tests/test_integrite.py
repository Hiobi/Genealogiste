"""#39, #40 (import), #43 (fusion), #47 (cycles de parenté)."""

from genealogiste_mcp import server
from genealogiste_mcp.coherence import check_tree
from genealogiste_mcp.export.charts import ancestors
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom
from genealogiste_mcp.models import ChildLink
from genealogiste_mcp.tree.integrite import dangling, duplicate_event_uids, parent_cycles


def _prop(ops):
    return server.arbre_proposer(ops, "t", "justification")


# ---------------------------------------------------------------- #47 cycles

def test_auto_parente_refusee(app_famille):
    r = _prop([{"op": "lier_enfant", "famille": "F1", "enfant": "I1", "non_source": True, "motif": "test"}])
    assert "cycle de parenté" in r["erreur"]


def test_cycle_refuse(app_famille):
    # I6 est le père de I1 (F2) ; faire de I6 l'enfant de I1 (F1) fermerait la boucle
    r = _prop([{"op": "lier_enfant", "famille": "F1", "enfant": "I6", "non_source": True, "motif": "test"}])
    assert "cycle de parenté" in r["erreur"]
    r = _prop([{"op": "ajouter_famille", "epoux": "I3", "enfants": [{"enfant": "I6", "non_source": True, "motif": "test"}]}])
    assert "cycle de parenté" in r["erreur"]


def test_cycle_detecte_sans_dates_et_parcours_borne(tree):
    for p in tree.personnes.values():
        p.evenements = []
    tree.familles["F1"].enfants.append(ChildLink("I6"))
    tree.personnes["I6"].famc.append("F1")
    assert parent_cycles(tree)
    assert any(i["code"] == "cycle_parente" for i in check_tree(tree))
    sosa = ancestors(tree, "I3", 30)
    assert len(sosa) < 20  # pas d'explosion combinatoire


# ---------------------------------------------------------------- #39, #40 import en ajout

GED_IMPORT = """0 HEAD
1 GEDC
2 VERS 7.0
0 @I1@ INDI
1 NAME Anne /DURAND/
1 BIRT
2 DATE 1801
2 SOUR @S1@
3 PAGE f° 2
3 OBJE @O1@
2 UID 11111111-1111-4111-8111-111111111111
1 SNOTE @N1@
1 OBJE @O1@
0 @S1@ SOUR
1 TITL Registre importé
0 @O1@ OBJE
1 FILE import-acte.jpg
2 FORM image/jpeg
1 SOUR @S1@
2 PAGE vue 3
0 @N1@ SNOTE Note importée
0 TRLR
"""


def test_import_ajout_references_et_uid(app_famille, tmp_path):
    f = tmp_path / "import.ged"
    existant = app_famille.store.load()
    uid_existants = {e.uid for p in existant.personnes.values() for e in p.evenements}
    # collision volontaire avec un UID d'événement existant
    f.write_text(GED_IMPORT.replace("11111111-1111-4111-8111-111111111111", sorted(uid_existants)[0]),
                 encoding="utf-8")
    p = server.arbre_importer_gedcom(str(f), "ajouter")
    assert "jeton" in p, p
    assert "commit" in server.arbre_appliquer(p["jeton"])
    t = app_famille.store.load()
    anne = next(x for x in t.personnes.values() if x.nom_principal.nom == "DURAND")
    cit = anne.evenements[0].citations[0]
    assert t.sources[cit.source].titre == "Registre importé"
    assert t.medias[cit.medias[0]].fichier == "import-acte.jpg"
    assert t.medias[anne.medias[0]].fichier == "import-acte.jpg"
    media = t.medias[anne.medias[0]]
    assert t.sources[media.citations[0].source].titre == "Registre importé"
    assert t.notes[anne.notes[0].strip("@")] == "Note importée"
    assert duplicate_event_uids(t) == [] and dangling(t) == []


# ---------------------------------------------------------------- #43 fusion

def test_fusion_protection_et_champs(app_famille):
    t = app_famille.store.load()
    t.personnes["I4"].vivant = "Y"
    t.personnes["I4"].extra.append({"tag": "_EXT", "value": "garde-moi", "xref": "", "children": []})
    jean, jean2 = t.personnes["I1"], t.personnes["I4"]
    jean.vivant = "N"
    birth = jean.events("BIRT")[0]
    twin = jean2.events("BIRT")[0]
    twin.date, twin.lieu = birth.date, birth.lieu
    twin.cause, twin.note = "", "note de la fiche absorbée"
    from genealogiste_mcp.models import Assertion
    twin.statut_manuel = Assertion("contradictoire", "deux actes")
    app_famille.store.write(t)
    app_famille.store.commit("prépa")
    r = _prop([{"op": "fusionner_personnes", "conserver": "I1", "absorber": "I4", "justification": "même homme"}])
    assert "jeton" in r, r
    assert any("vivant" in x and "Y retenu" in x for x in r["resume"])
    server.arbre_appliquer(r["jeton"])
    t2 = app_famille.store.load()
    j = t2.personnes["I1"]
    assert j.vivant == "Y"
    assert any(x.get("value") == "garde-moi" for x in j.extra)
    b = j.events("BIRT")[0]
    assert "note de la fiche absorbée" in b.note
    assert b.statut_manuel and b.statut_manuel.statut == "contradictoire"


def test_gedcom_aller_retour_sans_defaut(tree):
    t = read_gedcom(write_gedcom(tree))[0]
    assert parent_cycles(t) == [] and dangling(t) == [] and duplicate_event_uids(t) == []
