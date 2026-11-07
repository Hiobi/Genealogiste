"""#33 : export « vivants masqués » sans aucune donnée identifiante ;
#37 : marque « privé » conservée (GEDCOM RESN, Gramps private, Gramps XML) et appliquée à la publication."""

from pathlib import Path

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.export.gramps_xml import to_gramps_xml
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom
from genealogiste_mcp.gramps.mapping import gramps_to_tree, tree_to_gramps
from genealogiste_mcp.privacy import identifying_patterns, publication, residues

GED = """0 HEAD
1 GEDC
2 VERS 7.0
0 @I1@ INDI
1 NAME Alice /Secret/
1 SEX F
1 BIRT
2 DATE 12 MAR 1990
2 SOUR @S1@
3 PAGE acte 12
1 FAMC @F1@
1 SNOTE @N1@
1 OBJE @O1@
0 @I2@ INDI
1 NAME Paul /Secret/
1 SEX M
1 BIRT
2 DATE 1900
1 DEAT
2 DATE 1980
2 NOTE Déclaré par sa fille Alice Secret, domiciliée à Lyon.
2 ASSO @VOID@
3 PHRASE Alice SECRET
3 ROLE INFORMANT
2 ASSO @I1@
3 ROLE OTHER
2 SOUR @S2@
3 PAGE acte 40
3 DATA
4 TEXT Décès de Paul SECRET, déclaré par SECRET Alice sa fille.
1 SOUR @S1@
2 PAGE mention marginale
1 FAMS @F1@
1 OBJE @O2@
0 @I3@ INDI
1 NAME Bob /Cache/
1 BIRT
2 DATE 1800
1 RESN PRIVACY
0 @I4@ INDI
1 NAME Jeanne /Ancienne/
1 BIRT
2 DATE 1850
1 RESI
2 DATE 1880
2 RESN PRIVACY
2 NOTE adresse confidentielle rue des Ormes
0 @F1@ FAM
1 HUSB @I2@
1 CHIL @I1@
0 @S1@ SOUR
1 TITL Acte de naissance Alice Secret
0 @S2@ SOUR
1 TITL Registre des décès de Lyon 1980
0 @O1@ OBJE
1 FILE photo-alice.jpg
2 FORM image/jpeg
0 @O2@ OBJE
1 FILE tombe-paul.jpg
2 FORM image/jpeg
0 @N1@ SNOTE Habite 12 rue des Lilas, Lyon
0 TRLR
"""

INTERDITS = ["Alice Secret", "Alice /Secret/", "SECRET Alice", "Alice SECRET", "rue des Lilas", "photo-alice",
             "Bob", "Ormes", "Acte de naissance Alice"]


@pytest.fixture
def arbre():
    return read_gedcom(GED)[0]


def test_projection(arbre):
    t, hidden, rapport = publication(arbre)
    assert hidden == {"I1", "I3"}
    assert rapport["retires"]["sources"] == ["S1"]
    assert rapport["retires"]["medias"] == ["O1"] and rapport["retires"]["notes"] == ["N1"]
    paul = t.personnes["I2"]
    deces = paul.events("DEAT")[0]
    assert deces.associations == []                    # ASSO vers la vivante et PHRASE à son nom
    assert [c.source for c in deces.citations] == ["S2"]
    assert paul.citations == []                         # citation de S1 (source liée à la vivante) retirée
    assert "Vivant" in deces.note and "Vivant" in deces.citations[0].texte
    assert "S2" in t.sources and "O2" in t.medias       # liés seulement à des défunts : conservés
    assert t.personnes["I4"].events("RESI") == []       # événement privé retiré
    assert arbre.personnes["I1"].nom_principal.prenoms == "Alice"  # original intact


@pytest.mark.parametrize("format", ["gedcom7", "gedcom551", "geneweb", "gramps"])
def test_export_sans_chaine_identifiante(app, format):
    app.store.write(read_gedcom(GED)[0])
    r = server.arbre_exporter(format=format)
    assert "erreur" not in r, r
    texte = Path(r["fichier"]).read_text(encoding="utf-8")
    for s in INTERDITS:
        assert s.lower() not in texte.lower(), (format, s)
    assert "Registre des décès de Lyon 1980" in texte
    assert residues(texte, identifying_patterns(read_gedcom(GED)[0], {"I1", "I3"})) == []


def test_export_refuse_si_residu(app, monkeypatch):
    app.store.write(read_gedcom(GED)[0])
    from genealogiste_mcp import privacy
    vraie = privacy.publication
    monkeypatch.setattr(privacy, "publication", lambda t: (t, *vraie(t)[1:]))  # projection défaillante
    r = server.arbre_exporter(format="gedcom7")
    assert "erreur" in r and r["occurrences"]


def test_motifs_accents_et_ordres(arbre):
    pats = identifying_patterns(arbre, {"I1"})
    assert residues("ALICE SECRET", pats) and residues("Secret, Alice", pats) and residues("Alicé  Sécret", pats)
    assert residues("Paul Secret", pats) == [] and residues("Alice", pats) == []


# ---------------------------------------------------------------- #37

def test_gedcom_aller_retour_prive(arbre):
    t2 = read_gedcom(write_gedcom(arbre))[0]
    assert t2.personnes["I3"].prive is True
    assert t2.personnes["I4"].events("RESI")[0].prive is True
    assert t2.personnes["I2"].prive is False
    texte = write_gedcom(t2)
    assert texte.count("RESN PRIVACY") == 2  # pas de doublon via les nœuds conservés


def test_gramps_aller_retour_prive(arbre):
    arbre.sources["S2"].prive = True
    arbre.medias["O2"].prive = True
    arbre.personnes["I2"].citations[0].prive = True
    db = tree_to_gramps(arbre)
    t2, _ = gramps_to_tree(db)
    assert t2.personnes["I3"].prive and t2.personnes["I4"].events("RESI")[0].prive
    assert t2.sources["S2"].prive and t2.medias["O2"].prive
    assert t2.personnes["I2"].citations[0].prive
    xml = to_gramps_xml(arbre)
    assert xml.count('priv="1"') >= 5


def test_note_privee_gramps_conservee_jamais_publiee(arbre):
    db = tree_to_gramps(arbre)
    paul = next(p for p in db.all("Person").values() if p["gramps_id"] == "I2")
    note = {"_class": "Note", "handle": "nprive", "gramps_id": "N9", "change": 0, "private": True, "tag_list": [],
            "text": {"_class": "StyledText", "tags": [], "string": "secret de famille"}, "format": 0,
            "type": {"_class": "NoteType", "string": "Person Note"}}
    db.put(note)
    paul["note_list"].append("nprive")
    t2, _ = gramps_to_tree(db)
    assert "secret de famille" not in write_gedcom(t2)
    db2 = tree_to_gramps(t2, base=db)
    assert "nprive" in db2.all("Note") and "nprive" in next(
        p for p in db2.all("Person").values() if p["gramps_id"] == "I2")["note_list"]


@pytest.mark.parametrize('origine', ['citation', 'evenement', 'source'])
def test_projection_exclut_media_de_provenance_privee_sans_modifier_arbre(origine):
    from genealogiste_mcp.models import Citation, Event, Media

    tree = read_gedcom(GED)[0]
    tree.medias['O99'] = Media(id='O99', fichier='scan-interdit.jpg')
    citation = Citation(source='S2', medias=['O99'], prive=origine == 'citation')
    if origine == 'evenement':
        tree.personnes['I2'].evenements.append(Event(type='EVEN', prive=True, citations=[citation]))
    else:
        tree.personnes['I2'].citations.append(citation)
    if origine == 'source':
        tree.sources['S2'].prive = True
    avant = write_gedcom(tree)
    pub, _, _ = publication(tree)
    contenu = write_gedcom(pub)
    assert 'scan-interdit.jpg' not in contenu
    assert 'tombe-paul.jpg' in contenu
    if origine != 'source':
        assert 'S2' in pub.sources
    assert write_gedcom(tree) == avant


@pytest.mark.parametrize('nom, prenom', [('李', 'Lucas'), ('李', '雷'), ('X', 'Lucas')])
def test_projection_masque_les_mentions_de_noms_courts(nom, prenom):
    tree = read_gedcom(GED)[0]
    tree.personnes['I1'].noms[0].nom = nom
    tree.personnes['I1'].noms[0].prenoms = prenom
    tree.personnes['I2'].notes.append(f'Témoin : {nom} {prenom}. Lieu public : {nom}.')
    pub, _, _ = publication(tree)
    contenu = write_gedcom(pub)
    assert f'{nom} {prenom}' not in contenu
    assert f'Lieu public : {nom}.' in contenu
