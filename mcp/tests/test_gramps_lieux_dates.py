"""#277 : noms et rattachements datés des communes d'après le COG (gramps_dater_lieux).

Fixtures : fixtures/cog/communes.csv et mouvements.csv, extrait réduit des fichiers publics du Code officiel
géographique de l'INSEE (v_commune_depuis_1943, v_mvt_commune_2024 ; lignes des communes citées ci-dessous
seulement). Aucune personne réelle : arbre fictif (famille.ged) et personnes de test.

Règle de Gramps reproduite par ``nom_affiche`` / ``chaine_affichee`` (gramps/gen/utils/location.py,
get_location_list ; Date.match_exact) : premier nom de [principal] + alternatifs dont la date est vide ou
correspond, premier rattachement dont la date est vide ou correspond. Vérifiée sur la vraie bibliothèque par le
banc Desktop (cas « lieux », PlaceDisplay.display_event).
"""

from __future__ import annotations

import copy
import csv
from pathlib import Path

import httpx
import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed

from genealogiste_mcp import server
from genealogiste_mcp.export.gramps_xml import db_to_xml
from genealogiste_mcp.gedcom.mapping import write_gedcom
from genealogiste_mcp.gramps import lecture_xml as lx
from genealogiste_mcp.gramps.mapping import (
    apply_items,
    dater_lieux,
    diff,
    est_commune,
    gramps_to_tree,
    intervalle,
    periode_gramps,
    tree_to_gramps,
)
from genealogiste_mcp.gramps.types import blank_date, date_to_gramps, tname, valeur_tri
from genealogiste_mcp.models import Event, Name, Person, Place
from genealogiste_mcp.sources.geo import IndexCog

COG = Path(__file__).parent / "fixtures" / "cog"
LIEUX = {  # nom écrit par Genealogiste -> code INSEE
    "Charleville-Mézières, Ardennes, France": "08105",
    "Mézières, Ardennes, France": "08290",
    "Boulogne-Billancourt, Hauts-de-Seine, France": "92012",
    "Meythet, Haute-Savoie, France": "74182",
    "Annecy, Haute-Savoie, France": "74010",
    "Valserhône, Ain, France": "01033",
    "Rochefort, Charente-Maritime, France": "17299",
}


def lire(nom: str) -> list[dict]:
    with open(COG / nom, encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def index() -> IndexCog:
    return IndexCog(lire("communes.csv"), lire("mouvements.csv"))


def chronos(index, db) -> dict:
    return {p["code"]: index.chronologie(p["code"]) for p in db.all("Place").values() if est_commune(p)}


def arbre_lieux(tree):
    """Arbre fictif + une personne de test avec un événement par lieu, avant et après les changements."""
    tree = copy.deepcopy(tree)
    p = Person(id="ILIEUX277", noms=[Name(prenoms="Lieux", nom="DATES")], uid="personne-lieux-277")
    for i, (nom, code) in enumerate(LIEUX.items()):
        for an in ("1950", "1980", "2020"):
            p.evenements.append(Event(type="RESI", date=an, lieu=Place(nom=nom, code_insee=code),
                                      uid=f"lieu-277-{i}-{an}"))
    tree.personnes[p.id] = p
    return tree


def par_nom(db, nom):
    return next(p for p in db.all("Place").values() if p["name"]["value"] == nom)


def jour(iso: str) -> int:
    a, m, j = (int(x) for x in iso.split("-"))
    return valeur_tri(date_to_gramps(f"{j} {('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')[m - 1]} {a}"))


def correspond(d, sortval) -> bool:
    i = intervalle(d)
    return i is not None and i[0] <= sortval <= i[1]


def nom_affiche(p: dict, sortval: int) -> str:
    """get_location_list / __get_name de Gramps, langue du format vide : premier nom qui correspond."""
    for n in [p["name"], *p.get("alt_names", [])]:
        if correspond(n.get("date"), sortval):
            return n["value"]
    return "?"


def chaine_affichee(db, p: dict, sortval: int) -> str:
    noms = [nom_affiche(p, sortval)]
    while True:
        ref = next((r for r in p.get("placeref_list") or [] if correspond(r.get("date"), sortval)), None)
        if ref is None:
            return ", ".join(noms)
        p = db.get("Place", ref["ref"])
        noms.append(nom_affiche(p, sortval))


# ---------------------------------------------------------------------------- chronologie COG

def test_chronologie_cog(index):
    ch = index.chronologie("08105")
    assert [(n["nom"], n["debut"], n["fin"]) for n in ch["noms"]] == [
        ("Charleville", "1943-01-01", "1966-10-01"), ("Charleville-Mézières", "1966-10-01", None)]
    assert {a["nom"] for a in ch["absorbees"]} == {"Étion", "Mézières", "Mohon", "Montcy-Saint-Pierre"}
    b = index.chronologie("92012")
    assert b["codes"] == ["75012", "92012"] and len(b["noms"]) == 1
    assert [(d["nom"], d["fin"]) for d in b["departements"]] == [("Seine", "1968-01-01"), ("Hauts-de-Seine", None)]
    assert [(d["nom"], d["code"]) for d in index.chronologie("2A004")["departements"]] == [
        ("Corse", "20"), ("Corse-du-Sud", "2A")]
    assert index.chronologie("74182")["rattachements"] == [
        {"code_insee": "74010", "nom": "Annecy", "statut": "commune déléguée", "debut": "2017-01-01", "fin": None}]
    assert [n["nom"] for n in index.chronologie("01033")["noms"]] == [
        "Bellegarde", "Bellegarde-sur-Valserine", "Valserhône"]
    # commune nouvelle puis rétablissement (Les Hauts-Talican, 2019-2024)
    assert [n["nom"] for n in index.chronologie("60054")["noms"]] == [
        "Beaumont-les-Nonains", "Les Hauts-Talican", "Beaumont-les-Nonains"]
    v = index.chronologie("60694")
    assert v["rattachements"][0]["fin"] == "2024-01-01" and v["rattachements"][0]["code_insee"] == "60054"
    r = index.chronologie("17299")
    assert len(r["noms"]) == 1 and not r["rattachements"] and not r["absorbees"]
    assert not index.chronologie("99999")["connue"]


def test_periodes_contigues_comme_gramps():
    """Règle amont : « avant D » strict, « après D » strict, plage bornes comprises ; aucun jour sans nom."""
    avant, t1 = periode_gramps("1943-01-01", "1966-10-01", True)
    apres, t2 = periode_gramps("1966-10-01", None, False)
    plage, t3 = periode_gramps("1956-10-19", "2019-01-01", False)
    assert (t1, t2, t3) == ("avant 1966-10-01", "après 1966-09-30", "du 1956-10-19 au 2018-12-31")
    assert (avant["modifier"], apres["modifier"], plage["modifier"]) == (1, 2, 5)
    for iso, attendu in (("1966-09-30", (True, False)), ("1966-10-01", (False, True)), ("1966-10-02", (False, True))):
        assert (correspond(avant, jour(iso)), correspond(apres, jour(iso))) == attendu
    assert correspond(avant, 0) and not correspond(apres, 0)  # événement sans date : sortval 0
    assert correspond(plage, jour("1956-10-19")) and correspond(plage, jour("2018-12-31"))
    assert not correspond(plage, jour("2019-01-01"))
    assert correspond(blank_date(), 0)  # date vide : toujours


# ---------------------------------------------------------------------------- correspondance Gramps

def test_noms_et_rattachements_dates(index, tree):
    db = tree_to_gramps(arbre_lieux(tree))
    ged = write_gedcom(gramps_to_tree(db)[0])
    items, rapport = dater_lieux(db, chronos(index, db))
    db2 = apply_items(db, items)
    ch = par_nom(db2, "Charleville-Mézières")
    assert [(a["value"], a["date"]["modifier"]) for a in ch["alt_names"]] == [("Charleville", 1)]
    assert ch["name"]["date"] == date_to_gramps("AFT 30 SEP 1966")
    assert ch["alt_names"][0]["date"] == date_to_gramps("BEF 1 OCT 1966")
    assert ch["placeref_list"][0]["date"] == blank_date()  # département inchangé
    # Valserhône : trois noms, plage intermédiaire
    v = par_nom(db2, "Valserhône")
    assert [(a["value"], a["date"]) for a in v["alt_names"]] == [
        ("Bellegarde", date_to_gramps("BEF 19 OCT 1956")),
        ("Bellegarde-sur-Valserine", date_to_gramps("FROM 19 OCT 1956 TO 31 DEC 2018"))]
    # Boulogne : ancien département créé (Department, code 75, sous France), rattachements datés
    b = par_nom(db2, "Boulogne-Billancourt")
    seine = db2.get("Place", b["placeref_list"][1]["ref"])
    hds = db2.get("Place", b["placeref_list"][0]["ref"])
    assert hds["name"]["value"] == "Hauts-de-Seine" and seine["name"]["value"] == "Seine"
    assert (tname(seine["place_type"]), seine["code"]) == ("Department", "75")
    assert seine["placeref_list"][0]["ref"] == hds["placeref_list"][0]["ref"]  # même pays
    assert b["placeref_list"][0]["date"] == date_to_gramps("AFT 31 DEC 1967")
    assert b["placeref_list"][1]["date"] == date_to_gramps("BEF 1 JAN 1968")
    assert not b["alt_names"] and b["name"]["date"] == blank_date()
    # Meythet, commune déléguée d'Annecy depuis 2017
    m = par_nom(db2, "Meythet")
    assert db2.get("Place", m["placeref_list"][1]["ref"])["name"]["value"] == "Annecy"
    assert [r["date"] for r in m["placeref_list"]] == [date_to_gramps("BEF 1 JAN 2017"),
                                                         date_to_gramps("AFT 31 DEC 2016")]
    # nom affiché à la date de l'événement (règle de Gramps)
    assert chaine_affichee(db2, ch, jour("1950-06-01")) == "Charleville, Ardennes, France"
    assert chaine_affichee(db2, ch, jour("1980-06-01")) == "Charleville-Mézières, Ardennes, France"
    assert chaine_affichee(db2, b, jour("1950-06-01")) == "Boulogne-Billancourt, Seine, France"
    assert chaine_affichee(db2, b, jour("1980-06-01")) == "Boulogne-Billancourt, Hauts-de-Seine, France"
    assert chaine_affichee(db2, m, jour("1980-06-01")) == "Meythet, Haute-Savoie, France"
    assert chaine_affichee(db2, m, jour("2020-06-01")) == "Meythet, Annecy, Haute-Savoie, France"
    assert chaine_affichee(db2, v, jour("1960-01-01")) == "Bellegarde-sur-Valserine, Ain, France"
    # Mézières : lieu distinct listé, jamais fusionné ; Rochefort : rien
    assert any(x.startswith(f"{par_nom(db, 'Mézières')['gramps_id']} Mézières, Ardennes, France")
               for x in rapport["lieux_distincts"])
    touches = {it["handle"] for it in items}
    assert par_nom(db, "Mézières")["handle"] not in touches and par_nom(db, "Rochefort")["handle"] not in touches
    assert {it["_class"] for it in items} == {"Place"}  # aucun événement modifié
    assert [it["type"] for it in items].count("add") == 1  # Seine seulement
    lignes = rapport["lieux"]
    assert any("Charleville-Mézières" in x and "+« Charleville » avant 1966-10-01" in x for x in lignes)
    assert not rapport["conflits"]
    # nom relu inchangé, aller-retour Gramps -> modèle -> Gramps identique, idempotence
    back = gramps_to_tree(db2)[0]
    assert write_gedcom(back) == ged
    assert diff(db2, tree_to_gramps(back, base=db2)) == []
    assert dater_lieux(db2, chronos(index, db2))[0] == []


def test_saisies_manuelles_preservees_conflits_listes(index, tree):
    db = tree_to_gramps(arbre_lieux(tree))
    ch = par_nom(db, "Charleville-Mézières")
    v = par_nom(db, "Valserhône")
    b = par_nom(db, "Boulogne-Billancourt")
    # nom néerlandais sans date (autre langue) : gardé, n'empêche rien ; nom identique déjà là : pas de doublon
    ch["alt_names"] = [{"_class": "PlaceName", "value": "Charleville-sur-Meuse", "date": blank_date(), "lang": "nl"},
                       {"_class": "PlaceName", "value": "Charleville", "date": date_to_gramps("BEF 1 OCT 1966"),
                        "lang": ""}]
    # nom saisi sans date dans la même langue : conflit, Valserhône laissé tel quel
    v["alt_names"] = [{"_class": "PlaceName", "value": "Bellegarde", "date": blank_date(), "lang": ""}]
    # rattachement actuel daté à la main autrement : conflit
    b["placeref_list"][0]["date"] = date_to_gramps("AFT 1970")
    items, rapport = dater_lieux(db, chronos(index, db))
    new = {it["handle"]: it["new"] for it in items}
    c2 = new[ch["handle"]]
    assert [a["value"] for a in c2["alt_names"]] == ["Charleville-sur-Meuse", "Charleville"]
    assert c2["name"]["date"] == date_to_gramps("AFT 30 SEP 1966")
    assert v["handle"] not in new and b["handle"] not in new
    assert any("Valserhône" in c and "non tranché" in c for c in rapport["conflits"])
    assert any("Boulogne-Billancourt" in c and "déjà daté" in c for c in rapport["conflits"])
    assert not any(it["type"] == "add" for it in items)  # Seine non créé : Boulogne non traité


def test_nom_different_du_cog_et_type_commune_personnalise(index, tree):
    db = tree_to_gramps(arbre_lieux(tree))
    ch = par_nom(db, "Charleville-Mézières")
    ch["name"]["value"] = "Charleville"  # le lieu porte l'ancien nom avec le code actuel
    m = par_nom(db, "Meythet")
    m["place_type"] = {"_class": "PlaceType", "value": 0, "string": "Commune"}
    assert est_commune(m)
    items, rapport = dater_lieux(db, chronos(index, db))
    new = {it["handle"]: it["new"] for it in items}
    assert ch["handle"] not in new
    assert any("différent du nom actuel du COG « Charleville-Mézières »" in c for c in rapport["conflits"])
    assert new[m["handle"]]["place_type"] == {"_class": "PlaceType", "value": 0, "string": "Commune"}  # inchangé
    assert len(new[m["handle"]]["placeref_list"]) == 2


def test_lieu_a_plat_et_commune_nouvelle_absente(index, tree):
    t = arbre_lieux(tree)
    t.personnes["ILIEUX277"].evenements = [e for e in t.personnes["ILIEUX277"].evenements
                                           if not e.lieu.nom.startswith("Annecy")]
    db = tree_to_gramps(t)
    b = par_nom(db, "Boulogne-Billancourt")
    b.update(title="Boulogne-Billancourt, Hauts-de-Seine, France", placeref_list=[])
    items, rapport = dater_lieux(db, chronos(index, db))
    assert any("Boulogne-Billancourt" in x and "gramps_structurer_lieux" in x for x in rapport["non_traites"])
    assert any("Meythet" in x and "absent de la base" in x for x in rapport["non_traites"])
    assert b["handle"] not in {it["handle"] for it in items}


def test_export_import_gramps_xml_noms_et_liens_dates(index, tree):
    """pname et placeref datés passent Gramps XML -> objets à l'identique ; l'import dans le modèle (backend
    fichier) les compte toujours dans non_repris : le modèle fichier n'a pas d'objet lieu."""
    from genealogiste_mcp.gramps.mapping import tree_to_gramps as t2g
    db = tree_to_gramps(arbre_lieux(tree))
    db2 = apply_items(db, dater_lieux(db, chronos(index, db))[0])
    xml = db_to_xml(db2)
    assert '<pname value="Charleville">' in xml and '<dateval val="1966-10-01" type="before"/>' in xml
    assert '<dateval val="1967-12-31" type="after"/>' in xml
    lu = lx.lire_xml(xml.encode()).db
    for nom in ("Charleville-Mézières", "Boulogne-Billancourt", "Meythet", "Valserhône", "Seine"):
        a, b = par_nom(db2, nom), par_nom(lu, nom)
        for x in (a, b):
            for n in [x["name"], *x["alt_names"]]:
                n["date"].pop("sortval", None), n["date"].pop("format", None), n["date"].pop("text", None)
            for r in x["placeref_list"]:
                r["date"].pop("sortval", None), r["date"].pop("format", None), r["date"].pop("text", None)
        assert (a["name"], a["alt_names"], a["placeref_list"]) == (b["name"], b["alt_names"], b["placeref_list"])
    pertes = lx.pertes(lu, t2g(gramps_to_tree(lu)[0], generated=False))
    assert pertes.get("Place.alt_names[]", 0) >= 3


# ---------------------------------------------------------------------------- outil (faux Gramps Web, COG simulé)

@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


def cog_routes(fake, app, panne: bool = False):
    for url, nom in ((app.config.cog_communes_url, "communes.csv"), (app.config.cog_mvt_url, "mouvements.csv")):
        rep = httpx.Response(503, text="indisponible") if panne else \
            httpx.Response(200, text=(COG / nom).read_text(encoding="utf-8"))
        fake.router.get(url).mock(return_value=rep)


def test_outil_proposer_appliquer_annuler(tmp_path, fake, tree):
    seed(fake, arbre_lieux(tree))
    a = make_app(tmp_path)
    try:
        cog_routes(fake, a)
        avant = {h: copy.deepcopy(o) for h, o in fake.objects["Place"].items()}
        evts = {h: e["place"] for h, e in fake.objects["Event"].items()}
        ged = write_gedcom(a.tree())
        p = server.gramps_dater_lieux()
        assert "jeton" in p, p
        assert p["transaction_gramps"]["bilan"] == {"Place": {"add": 1, "update": 4, "delete": 0}}
        assert any("Charleville" in x for x in p["lieux"]) and p["lieux_distincts"]
        entree = a.journal.entries(source="cog")[-1]
        assert entree["operation"] == "chronologie" and entree["statut"] == "positif"
        assert len(fake.objects["Place"]) == len(avant)  # rien d'écrit avant l'accord
        r = server.arbre_appliquer(p["jeton"])
        assert "erreur" not in r, r
        ch = next(o for o in fake.objects["Place"].values() if o["name"]["value"] == "Charleville-Mézières")
        assert [x["value"] for x in ch["alt_names"]] == ["Charleville"]
        assert {h: e["place"] for h, e in fake.objects["Event"].items()} == evts  # événements inchangés
        server.gramps_synchroniser()
        assert write_gedcom(server.app().tree()) == ged  # noms relus inchangés
        deux = server.gramps_dater_lieux()
        assert "jeton" not in deux and "Rien à dater" in deux["note"]  # idempotent
        assert "#277" in fake.messages[-1]
        u = server.arbre_annuler_modification(r["transaction"])
        assert "jeton" in u, u
        server.arbre_appliquer(u["jeton"])
        assert {h: o["alt_names"] for h, o in fake.objects["Place"].items()} == \
            {h: o["alt_names"] for h, o in avant.items()}
        assert set(fake.objects["Place"]) == set(avant)
    finally:
        server.set_app(None)


def test_outil_cog_injoignable_rien_ecrit(tmp_path, fake, tree):
    seed(fake, arbre_lieux(tree))
    a = make_app(tmp_path)
    try:
        cog_routes(fake, a, panne=True)
        r = server.gramps_dater_lieux()
        assert "COG injoignable" in r["erreur"] and "jeton" not in r
        assert a.journal.entries(source="cog")[-1]["statut"] == "erreur"
        assert not fake.transactions
    finally:
        server.set_app(None)


def test_outil_mode_fichier(app):
    assert "mode gramps" in server.gramps_dater_lieux()["erreur"]
