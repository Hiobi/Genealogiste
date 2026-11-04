"""#11 : lieux hiérarchiques Gramps (commune → département → pays), aller-retour identique, migration."""

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed

from genealogiste_mcp import server
from genealogiste_mcp.gramps.mapping import diff, gramps_to_tree, level_type, place_levels, tree_to_gramps
from genealogiste_mcp.gramps.types import tname
from genealogiste_mcp.models import Event, Place

ROCHEFORT = "Rochefort, Charente-Maritime, France"


def by_name(db, name):
    return [p for p in db.all("Place").values() if p["name"]["value"] == name]


def test_levels_and_types():
    assert place_levels(ROCHEFORT) == ["Rochefort", "Charente-Maritime", "France"]
    assert place_levels("Rochefort,Charente-Maritime") == []  # forme non canonique : reste à plat
    assert place_levels("Rochefort") == []
    parts = ["Saintes", "Charente-Maritime", "Nouvelle-Aquitaine", "France"]
    assert [level_type(parts, i) for i in range(4)] == ["City", "Department", "Region", "Country"]
    assert level_type(["Somain", "Nord"], 1) == "Department"


def test_new_places_are_hierarchical_and_shared(tree):
    db = tree_to_gramps(tree)
    commune = by_name(db, "Rochefort")
    assert len(commune) == 1 and commune[0]["title"] == ""
    dep = db.get("Place", commune[0]["placeref_list"][0]["ref"])
    assert dep["name"]["value"] == "Charente-Maritime" and tname(dep["place_type"]) == "Department" and \
        dep["code"] == "17"
    country = db.get("Place", dep["placeref_list"][0]["ref"])
    assert tname(country["place_type"]) == "Country" and not country["placeref_list"]
    assert len(by_name(db, "France")) == 1  # un seul « France » partagé
    back, _ = gramps_to_tree(db)
    names = {e.lieu.nom for p in back.personnes.values() for e in p.evenements if e.lieu}
    assert ROCHEFORT in names
    assert diff(db, tree_to_gramps(back, base=db)) == []


def test_non_canonical_name_stays_flat(tree):
    p = next(iter(tree.personnes.values()))
    p.evenements.append(Event(type="RESI", lieu=Place(nom="Brouage,Charente-Maritime")))
    db = tree_to_gramps(tree)
    flat = next(x for x in db.all("Place").values() if x.get("title") == "Brouage,Charente-Maritime")
    assert not flat["placeref_list"]
    back, _ = gramps_to_tree(db)
    assert any(e.lieu and e.lieu.nom == "Brouage,Charente-Maritime" for e in back.personnes[p.id].evenements)


def test_existing_parent_place_is_reused(tree):
    base = tree_to_gramps(tree)
    france = by_name(base, "France")[0]
    p = next(iter(tree.personnes.values()))
    p.evenements.append(Event(type="RESI", lieu=Place(nom="Lille, Nord, France")))
    db = tree_to_gramps(tree, base=base)
    nord = by_name(db, "Nord")[0]
    assert nord["placeref_list"][0]["ref"] == france["handle"] and len(by_name(db, "France")) == 1


def flatten(fake):
    """Base produite par une version antérieure : lieux à plat (titre complet, sans lieu englobant)."""
    places = fake.objects["Place"]
    parents = {r["ref"] for p in places.values() for r in p.get("placeref_list") or []}
    titles = {}
    for h, p in places.items():
        if p.get("placeref_list"):
            name, ref = [p["name"]["value"]], p["placeref_list"][0]["ref"]
            while ref:
                up = places[ref]
                name.append(up["name"]["value"])
                ref = (up.get("placeref_list") or [{}])[0].get("ref")
            titles[h] = ", ".join(name)
    for h, title in titles.items():
        places[h].update(title=title, placeref_list=[])
    for h in parents:
        places.pop(h, None)


@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


def test_structure_existing_flat_places(tmp_path, fake, tree):
    seed(fake, tree)
    flatten(fake)
    assert not by_name_fake(fake, "France")
    events_before = {h: dict(e) for h, e in fake.objects["Event"].items()}
    make_app(tmp_path)
    try:
        names_before = sorted(e["lieu"] for e in _event_places())
        p = server.gramps_structurer_lieux()
        assert "jeton" in p, p
        bilan = p["transaction_gramps"]["bilan"]
        assert bilan["Place"]["add"] >= 2 and bilan["Place"]["update"] >= 1 and "Event" not in bilan
        server.arbre_appliquer(p["jeton"])
        assert len(by_name_fake(fake, "France")) == 1
        assert sorted(e["lieu"] for e in _event_places()) == names_before  # noms relus identiques
        assert {h: e["place"] for h, e in fake.objects["Event"].items()} == \
            {h: e["place"] for h, e in events_before.items()}
        assert "ne modifie rien" in server.gramps_structurer_lieux()["erreur"]
    finally:
        server.set_app(None)


def by_name_fake(fake, name):
    return [p for p in fake.objects["Place"].values() if p["name"]["value"] == name]


def _event_places():
    t = server.app().tree()
    return [{"lieu": e.lieu.nom} for p in t.personnes.values() for e in p.evenements if e.lieu]
