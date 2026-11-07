"""Intégration sur un vrai Gramps Web jetable (make test-gramps). Ignoré sans GENEALOGISTE_TEST_GRAMPS_URL.

L'arbre de test est vidé par docker compose down -v : données fictives uniquement (fixture famille.ged).
"""

from __future__ import annotations

import json
import os

import pytest

from genealogiste_mcp.gedcom.mapping import read_gedcom
from genealogiste_mcp.gramps.backend import GrampsBackend
from genealogiste_mcp.gramps.client import GrampsClient
from genealogiste_mcp.gramps.mapping import diff, gramps_to_tree, tree_to_gramps
from genealogiste_mcp.tree.proposals import ProposalError

URL = os.environ.get("GENEALOGISTE_TEST_GRAMPS_URL", "")
pytestmark = [pytest.mark.gramps_live, pytest.mark.skipif(not URL, reason="GENEALOGISTE_TEST_GRAMPS_URL non défini")]


@pytest.fixture(scope="module")
def client():
    c = GrampsClient(URL, os.environ.get("GENEALOGISTE_TEST_GRAMPS_USER", "sosa-test"),
                     os.environ.get("GENEALOGISTE_TEST_GRAMPS_PASSWORD", "sosa-test"))
    db = c.load_all()
    if any(n for cls, n in db.count().items() if cls != "Tag"):
        pytest.skip("l'arbre Gramps Web de test doit être vide (conteneur jetable)")
    return c


@pytest.fixture(scope="module")
def loaded(client, fixtures_dir):
    tree = read_gedcom((fixtures_dir / "famille.ged").read_text(encoding="utf-8"))[0]
    items = diff(client.load_all(), tree_to_gramps(tree, base=client.load_all()))
    client.transaction(items, "Tests d'intégration : chargement de famille.ged (fictif)")
    return tree


@pytest.fixture(scope="module")
def fixtures_dir():
    from pathlib import Path
    return Path(__file__).parent / "fixtures"


def test_round_trip_through_real_api(client, loaded):
    from test_gramps_mapping import merged_places, normalize
    back, _ = gramps_to_tree(client.load_all())
    merged_places(loaded)
    assert json.dumps(normalize(back), sort_keys=True, ensure_ascii=False) == \
        json.dumps(normalize(loaded), sort_keys=True, ensure_ascii=False)


def test_rewrite_without_change_is_empty(client, loaded):
    db = client.load_all()
    t, _ = gramps_to_tree(db)
    assert diff(db, tree_to_gramps(t, base=db)) == []


def test_propose_apply_conflict_undo(client, loaded, tmp_path):
    b = GrampsBackend(client, tmp_path, tmp_path / ".propositions", ttl=0)
    ops = [{"op": "ajouter_citation", "cible": {"type": "evenement", "uid": "11111111-1111-4111-8111-111111111113"},
            "citation": {"source": "S1", "page": "Décès 1885, acte n° 3", "type_source": "originale",
                         "information": "primaire", "consultation": "image"}}]
    r = b.apply(b.propose(ops, "Décès", "Acte lu (test).")["jeton"])
    death = next(e for e in b.load(fresh=True).personnes["I1"].evenements if e.type == "DEAT")
    assert any(c.page == "Décès 1885, acte n° 3" for c in death.citations)
    # modification « dans l'interface » (endpoint objet) entre proposition et accord : refus
    p = b.propose([{"op": "marquer_vivant", "id": "I7", "vivant": "N"}], "Vivant", "Décédé (test).")
    h = next(h for h, o in client.load_all().all("Person").items() if o["gramps_id"] == "I7")
    obj = client.request("GET", f"/people/{h}").json()
    obj["private"] = not obj.get("private", False)
    assert client.request("PUT", f"/people/{h}", json=obj).status_code == 200
    with pytest.raises(ProposalError):
        b.apply(p["jeton"])
    # annulation de la première transaction
    b.apply(b.propose_undo(r["transaction"])["jeton"])
    death = next(e for e in b.load(fresh=True).personnes["I1"].evenements if e.type == "DEAT")
    assert not any(c.page == "Décès 1885, acte n° 3" for c in death.citations)


def test_media_upload_and_citation_link(client, loaded, tmp_path):
    """#8 : image fictive envoyée par PUT /media/{handle}/file, liée à une citation, chemin du serveur conservé."""
    import hashlib
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("L", (120, 80), 128).save(buf, "JPEG")
    jpeg = buf.getvalue()
    (tmp_path / "medias").mkdir()
    (tmp_path / "medias" / "acte-test.jpg").write_bytes(jpeg)
    b = GrampsBackend(client, tmp_path, tmp_path / ".propositions", ttl=0)
    ops = [{"op": "ajouter_media", "ref": "img", "fichier": "medias/acte-test.jpg", "format": "image/jpeg",
            "titre": "Image fictive (test)"},
           {"op": "ajouter_citation", "cible": {"type": "evenement", "uid": "11111111-1111-4111-8111-111111111113"},
            "citation": {"source": "S1", "page": "Image test", "medias": ["$img"]}}]
    p = b.propose(ops, "Média de test", "Image fictive (test).")
    assert p["transaction_gramps"]["fichiers_a_envoyer"]
    r = b.apply(p["jeton"])
    assert r["medias"]["envoyes"] and not r["medias"]["erreurs"], r
    db = client.load_all()
    media = next(m for m in db.all("Media").values() if m.get("desc") == "Image fictive (test)")
    assert media["checksum"] == hashlib.md5(jpeg).hexdigest() and media["path"] != "medias/acte-test.jpg"
    got = client.request("GET", f"/media/{media['handle']}/file")
    assert got.status_code == 200 and got.content == jpeg
    t, _ = gramps_to_tree(db)
    assert any(m.fichier == "medias/acte-test.jpg" for m in t.medias.values())
    assert diff(db, tree_to_gramps(t, base=db)) == []  # rien à réécrire : chemin du serveur conservé
    assert b.media_status()["a_envoyer"] == []


def test_places_are_hierarchical_in_real_gramps(client, loaded):
    """#11 : commune → département → pays acceptés par l'API ; nom relu identique."""
    from genealogiste_mcp.gramps.types import tname
    db = client.load_all()
    commune = next(p for p in db.all("Place").values() if p["name"]["value"] == "Rochefort")
    dep = db.get("Place", commune["placeref_list"][0]["ref"])
    country = db.get("Place", dep["placeref_list"][0]["ref"])
    assert (tname(dep["place_type"]), dep["code"], tname(country["place_type"])) == ("Department", "17", "Country")
    t, _ = gramps_to_tree(db)
    assert any(e.lieu and e.lieu.nom == "Rochefort, Charente-Maritime, France"
               for p in t.personnes.values() for e in p.evenements)


def test_token_carries_tree_and_data_dir_is_bound(client, loaded, tmp_path):
    """#9 : le jeton Gramps Web porte l'arbre du compte ; le répertoire de données lui est lié."""
    from genealogiste_mcp.gramps.backend import TREE_FILE, check_tree
    tree = client.tree()
    print("arbre du compte de test :", tree)
    assert tree
    assert check_tree(client, tmp_path) == tree and (tmp_path / TREE_FILE).exists()
    assert check_tree(client, tmp_path) == tree  # même arbre : accepté


def test_sosa_auto_recalc_and_git_mirror(client, loaded, tmp_path):
    from genealogiste_mcp.gramps.backend import GitMirror
    from genealogiste_mcp.tree.store import TreeStore

    store = TreeStore(tmp_path / "donnees")
    b = GrampsBackend(client, tmp_path / "donnees", tmp_path / "propositions", ttl=0, mirror=GitMirror(store))
    b.load(fresh=True)
    assert store.log(1)[0]["message"].startswith("Miroir de Gramps Web")
    db = client.load_all()
    cit = next(iter(db.all("Citation")))
    eh = next(h for h, event in db.all("Event").items() if not event["citation_list"])
    obj = client.request("GET", f"/events/{eh}").json()
    obj["citation_list"] = [cit]
    assert client.request("PUT", f"/events/{eh}", json=obj).status_code == 200
    b.snapshot(fresh=True)
    msg = store.log(1)[0]["message"]
    assert msg.startswith("Modifications externes") and '"Event"' in msg
    assert b.last_refresh["Event"]["modifies"] >= 1
    r = b.apply(b.propose_notes()["jeton"])
    assert r["objets"]["Note"]["update"] >= 1
    assert r["miroir_git"] is None
    with pytest.raises(ProposalError):
        b.propose_notes()
