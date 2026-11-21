"""Intégration sur un vrai Gramps Web jetable (make test-gramps). Ignoré sans GENEALOGISTE_TEST_GRAMPS_URL.

L'arbre de test est vidé par docker compose down -v : données fictives uniquement (fixture famille.ged).
"""

from __future__ import annotations

import json
import os
import time

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


def test_version_api_de_l_image(client):
    """#267 : l'image testée sert bien l'API annoncée par compatibilite-gramps.json, dans la plage testée."""
    from genealogiste_mcp.gramps.compatibilite import verdict_api
    meta = client.request("GET", "/metadata/").json()
    version = meta["gramps_webapi"]["version"]
    print("gramps-web-api", version, "gramps", meta.get("gramps", {}).get("version"))
    attendu = os.environ.get("GENEALOGISTE_TEST_GRAMPS_API")
    if attendu:
        assert version == attendu
        assert verdict_api(version) == "testee"


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



# ---------------------------------------------------------------------------- #265 : version, rôle, refus d'écriture

COMPTES_FAIBLES = [("sosa-membre", 1, "Member"), ("sosa-contributeur", 2, "Contributor")]


def _app_gramps(tmp_path, user, password):
    from genealogiste_mcp import server
    from genealogiste_mcp.config import Config
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend="gramps",
                 gramps_url=URL, gramps_user=user, gramps_password=password, gramps_ttl=0)
    # vraie pause : /token/ est limité à 1 requête par seconde et par adresse, tous comptes confondus
    return server.App(cfg, sleeper=time.sleep)


def test_diagnostic_sur_le_vrai_gramps_web(tmp_path):
    """Version de l'API, de Gramps, rôle Editor (ok) et réglages lisibles sans droit Admin."""
    from genealogiste_mcp import diagnostic
    from genealogiste_mcp.gramps.compatibilite import FONCTIONS_API, version_api
    ctl = {c["controle"]: c for c in diagnostic.controles_gramps(_app_gramps(tmp_path, "sosa-test", "sosa-test"))}
    print("diagnostic réel :", {k: (v["etat"], v["detail"]) for k, v in ctl.items()})
    assert ctl["gramps_web"]["etat"] == "ok"
    v = ctl["gramps_version"]
    attendu = os.environ.get("GENEALOGISTE_TEST_GRAMPS_API")
    if attendu:
        assert v["api"] == attendu and v["verdict"] == "testee" and v["etat"] == "ok"
    assert v["api"] and v["gramps"].startswith("6.")
    assert (ctl["gramps_role"]["etat"], ctl["gramps_role"]["role"]) == ("ok", 3)
    g = ctl["gramps_reglages"]
    assert "file de tâches : non" in g["detail"] and "multi-arbres : non" in g["detail"]
    if version_api(v["api"]) >= FONCTIONS_API["inscription_libre"]:
        # le serveur déclare l'inscription ouverte dès qu'un compte Owner existe (`is_registration_disabled`, amont) :
        # le compte `sosa-owner` du banc (#274, rôle requis par l'import) la rend ouverte, et le diagnostic le dit
        assert g["etat"] == "attention" and "inscription libre : ouverte" in g["detail"] and g["remede"]
    else:
        assert g["etat"] == "ok" and "non vérifiable sur cette version" in g["detail"]
    texte = json.dumps(list(ctl.values()), ensure_ascii=False)
    assert "sosa-test" not in texte and "Bearer" not in texte


@pytest.mark.parametrize(("compte", "role", "nom"), COMPTES_FAIBLES)
def test_compte_sans_droit_d_ecriture(compte, role, nom, tmp_path):
    """Diagnostic en erreur, refus anticipé de arbre_proposer, forme réelle du 403, lecture toujours possible."""
    from genealogiste_mcp import diagnostic
    from genealogiste_mcp.gramps.client import GrampsError
    a = _app_gramps(tmp_path, compte, compte)
    r = next(c for c in diagnostic.controles_gramps(a) if c["controle"] == "gramps_role")
    assert (r["etat"], r.get("role"), r.get("role_nom")) == ("erreur", role, nom), r
    assert "Editor" in r["remede"]
    c = a.gramps()
    assert c.role() == role and "EditObject" not in (c.permissions() or set())
    with pytest.raises(GrampsError, match="Editor"):
        c.exiger_ecriture()
    with pytest.raises(ProposalError, match="lecture reste possible"):
        a.backend.propose([{"op": "marquer_vivant", "id": "I7", "vivant": "N"}], "Vivant", "Essai (test).")
    assert a.backend.db is None  # refus avant la lecture de l'arbre
    assert c.load_all().count()  # la lecture reste possible
    tag = {"_class": "Tag", "handle": "t403", "name": "essai-403", "color": "#000000", "priority": 0}
    item = {"type": "add", "_class": "Tag", "handle": "t403", "old": None, "new": tag}
    # forme réelle d'un 403 (flask-smorest) : consignée dans docs/gramps-web.md
    rep = c.request("POST", "/transactions/", params={"message": "essai"}, json=[item])
    print("403 réel", compte, rep.status_code, rep.headers.get("content-type"), rep.text)
    assert rep.status_code == 403 and rep.json().get("code") == 403
    with pytest.raises(GrampsError) as exc:
        c.transaction([item], "essai")
    assert exc.value.status == 403 and "Editor" in str(exc.value) and "Corriger" in str(exc.value)


# ---------------------------------------------------------------------------- #262 : étiquettes

def test_etiquettes_pose_relecture_retrait_annulation(client, loaded, tmp_path):
    """Étiquette existante (et en double) + nouvelle sur plusieurs classes, relue ; retrait ; annulations qui
    restaurent les tag_list et retirent le Tag créé. Tag sans gramps_id et noms non uniques acceptés par l'API."""
    existante = {"_class": "Tag", "handle": "tag262existante", "name": "Existante-262", "color": "#ef29ef29ef29",
                 "priority": 40}
    double = {**existante, "handle": "tag262double", "priority": 41, "color": "#000000000000"}
    client.transaction([{"type": "add", "_class": "Tag", "handle": t["handle"], "old": None, "new": t}
                        for t in (existante, double)], "Tests d'intégration : étiquettes existantes (#262)")
    db0 = client.load_all()
    assert {"tag262existante", "tag262double"} <= set(db0.all("Tag"))  # deux Tag de même nom acceptés
    avant = {cls: {h: o.get("tag_list") for h, o in db0.all(cls).items()} for cls in db0.objects if cls != "Tag"}
    b = GrampsBackend(client, tmp_path, tmp_path / ".propositions", ttl=0)
    naissance = "11111111-1111-4111-8111-111111111111"
    ops = [{"op": "etiqueter", "cible": {"type": "personne", "id": "I1"}, "tags": ["Existante-262", "Nouvelle-262"]},
           {"op": "etiqueter", "cible": {"type": "famille", "id": "F1"}, "tags": ["Nouvelle-262"]},
           {"op": "etiqueter", "cible": {"type": "evenement", "uid": naissance}, "tags": ["Existante-262"]},
           {"op": "etiqueter", "cible": {"type": "citation", "porteur": {"type": "evenement", "uid": naissance},
                                         "source": "S2"}, "tags": ["Nouvelle-262"]},
           {"op": "etiqueter", "cible": {"type": "source", "id": "S1"}, "tags": ["Nouvelle-262"]},
           {"op": "etiqueter", "cible": {"type": "depot", "id": "R1"}, "tags": ["Existante-262"]}]
    p = b.propose(ops, "Étiquettes", "Essai d'étiquettes (test).")
    tg = p["transaction_gramps"]
    print("étiquettes, bilan réel :", tg["bilan"], tg["etiquettes"], p["avertissements"])
    assert tg["bilan"]["Tag"]["add"] == 1 and len(tg["etiquettes"]) == 6
    assert any("présente 2 fois" in w for w in p["avertissements"])
    r = b.apply(p["jeton"])
    db = client.load_all()
    nouvelle = next(h for h, t in db.all("Tag").items() if t["name"] == "Nouvelle-262")
    assert "gramps_id" not in db.get("Tag", nouvelle) or not db.get("Tag", nouvelle).get("gramps_id")
    assert db.get("Tag", "tag262existante")["color"] == "#ef29ef29ef29"  # jamais touchée
    t = b.load(fresh=True)
    assert t.personnes["I1"].tags == ["Existante-262", "Nouvelle-262"] and t.familles["F1"].tags == ["Nouvelle-262"]
    ev = next(e for e in t.personnes["I1"].evenements if e.uid == naissance)
    assert ev.tags == ["Existante-262"] and [c.tags for c in ev.citations if c.source == "S2"] == [["Nouvelle-262"]]
    assert t.sources["S1"].tags == ["Nouvelle-262"] and t.depots["R1"].tags == ["Existante-262"]
    jean = next(o for o in db.all("Person").values() if o["gramps_id"] == "I1")
    assert "tag262existante" in jean["tag_list"] and "tag262double" not in jean["tag_list"]  # priorité 40 d'abord
    assert diff(db, tree_to_gramps(t, base=db)) == []  # relu puis réécrit : rien
    # retrait : l'objet Tag reste
    r2 = b.apply(b.propose([{"op": "modifier_personne", "id": "I1", "tags_retrait": ["Nouvelle-262"]}],
                           "Retrait", "Essai (test).")["jeton"])
    assert b.load(fresh=True).personnes["I1"].tags == ["Existante-262"] and nouvelle in client.load_all().all("Tag")
    # annulations : retrait puis pose
    u2 = b.propose_undo(r2["transaction"])
    assert u2["transaction_inverse"]["etiquettes"] == ["étiquettes I1 : +Nouvelle-262"]
    b.apply(u2["jeton"])
    assert b.load(fresh=True).personnes["I1"].tags == ["Existante-262", "Nouvelle-262"]
    b.apply(b.propose_undo(r["transaction"])["jeton"])
    db2 = client.load_all()
    apres = {cls: {h: o.get("tag_list") for h, o in db2.all(cls).items()} for cls in db2.objects if cls != "Tag"}
    assert apres == avant and nouvelle not in db2.all("Tag")
    assert {"tag262existante", "tag262double"} <= set(db2.all("Tag"))


# ---------------------------------------------------------------------------- #272 : dates

def test_dates_aller_retour_sur_vrai_gramps_web(client, loaded):
    """Échantillon de l'inventaire des formes de date (dates_gramps.py) écrit par l'API puis relu : objet Date
    identique (valeur de tri comprise) ; relu par Genealogiste et réécrit sans modification : aucune transaction ;
    passé par le modèle sans état lu : même date. Puis dates du modèle (GEDCOM 7 et extensions) écrites par la
    correspondance et relues : même chaîne, texte vide pour une forme canonique."""
    from dates_gramps import ecarts, inventaire
    from test_dates_gramps import CANONIQUES

    from genealogiste_mcp.gramps.types import blank, date_reprise, event_ref, valeur_tri
    from genealogiste_mcp.models import Event, Name, Person

    formes = [(n, d) for i, (n, d) in enumerate(inventaire())
              if i % 9 == 0 or n.startswith(("double", "ny4", "texte", "vide"))]
    objets = []
    for i, (nom, d) in enumerate(formes):
        e = blank("Event", f"date272e{i:04d}", f"E272{i:04d}")
        e.update(date=d, description=f"Forme {nom}")
        objets.append(e)
    p = blank("Person", "date272personne", "I272")
    p["primary_name"]["first_name"] = "Formes"
    p["event_ref_list"] = [event_ref(e["handle"], "Primary") for e in objets]
    client.transaction([{"type": "add", "_class": o["_class"], "handle": o["handle"], "old": None, "new": o}
                        for o in [*objets, p]], "Tests d'intégration : formes de date (#272, fictif)")
    db = client.load_all()
    relues = {o["handle"]: db.get("Event", o["handle"])["date"] for o in objets}
    # Écart connu de Gramps Web (API >= 3.25, gramps-web-api#869) : le serveur recalcule sortval par
    # Date.recalc_sort_value, sans le décalage de nouvel an que Date.set applique (Gramps Desktop, Genealogiste).
    recalcul, ecarts_vus = 0, []
    for (nom, d), o in zip(formes, objets, strict=True):
        r = relues[o["handle"]]
        e = ecarts(d, r)
        if e == [f"sortval: {d['sortval']!r} -> {r['sortval']!r}"] and r["sortval"] == valeur_tri({**d, "newyear": 0}):
            recalcul += 1
        elif e:
            ecarts_vus.append((nom, e))
    assert ecarts_vus == []
    assert all(date_reprise(r) for r in relues.values())
    t, _ = gramps_to_tree(db)
    # relu puis réécrit : aucun événement touché (la personne créée hors Genealogiste reçoit ses marqueurs)
    assert [x for x in diff(db, tree_to_gramps(t, base=db, generated=False)) if x["_class"] == "Event"] == []
    print(f"dates #272 : {len(formes)} formes écrites et relues à l'identique sur Gramps Web "
          f"(dont {recalcul} au sortval recalculé par le serveur sans nouvel an)")

    # GEDCOM 7 (et extensions) -> Gramps Web -> GEDCOM 7
    t.personnes["I272G7"] = Person(id="I272G7", noms=[Name(prenoms="Dates", nom="MODELE")], uid="personne-272-g7",
                                   evenements=[Event(type="EVEN", type_detail="Forme", date=s, uid=f"g7-272-{i}")
                                               for i, s in enumerate(CANONIQUES)])
    client.transaction(diff(db, tree_to_gramps(t, base=db)), "Tests d'intégration : dates du modèle (#272)")
    t2, _ = gramps_to_tree(client.load_all())
    assert [e.date for e in t2.personnes["I272G7"].evenements] == CANONIQUES


# ---------------------------------------------------------------------------- #273 : types personnalisés français

def test_types_francais_lus_normalises_annules(client, loaded, tmp_path):
    """Objets créés comme l'interface de Gramps Web (POST au format simplifié, type « personnalisé » saisi en
    français) : le serveur (locale anglaise) en fait des types personnalisés ; Genealogiste les lit comme les types
    standard, les réécrit à l'identique, puis les normalise (transaction, accord) et l'annulation les rétablit."""
    from genealogiste_mcp.gedcom.mapping import write_gedcom
    from genealogiste_mcp.gramps.types import TYPES, blank, tname

    def simplifie(o):  # types en chaîne, comme les envoie l'interface
        if isinstance(o, dict):
            if o.get("_class") in TYPES:
                return tname(o)
            return {k: simplifie(v) for k, v in o.items()}
        if isinstance(o, list):
            return [simplifie(x) for x in o]
        return o

    lieu = blank("Place", "type273lieu", "P273")
    lieu.update(title="Saint-Exemple-273", place_type="Paroisse")
    lieu["name"]["value"] = "Saint-Exemple-273"
    bapteme = blank("Event", "type273bapteme", "E2731")
    bapteme.update(type="Baptême", place="type273lieu", description="test #273")
    recens = blank("Event", "type273recens", "E2732")
    recens.update(type="Recensement")
    enfant = blank("Person", "type273enfant", "I2731")
    enfant["primary_name"]["first_name"] = "Baptisé"
    enfant["event_ref_list"] = [{**blank_ref(), "ref": "type273bapteme", "role": "Primary",
                                 "attribute_list": [{"_class": "Attribute", "private": False, "type": "Âge",
                                                     "value": "1 jour", "citation_list": [], "note_list": []}]},
                                {**blank_ref(), "ref": "type273recens", "role": "Primary"}]
    temoin = blank("Person", "type273temoin", "I2732")
    temoin["primary_name"]["first_name"] = "Témoin"
    temoin["event_ref_list"] = [{**blank_ref(), "ref": "type273bapteme", "role": "Témoin"},
                                {**blank_ref(), "ref": "type273bapteme", "role": "Officiant"}]  # ambigu
    for chemin, o in (("places", lieu), ("events", bapteme), ("events", recens), ("people", enfant),
                      ("people", temoin)):
        rep = client.request("POST", f"/{chemin}/", json=simplifie(o))
        assert rep.status_code in (200, 201), rep.text
    db = client.load_all()
    assert db.get("Event", "type273bapteme")["type"] == {"_class": "EventType", "value": 0, "string": "Baptême"}
    assert db.get("Place", "type273lieu")["place_type"]["string"] == "Paroisse"
    roles = [r["role"] for r in db.get("Person", "type273temoin")["event_ref_list"]]
    assert [r["string"] for r in roles] == ["Témoin", "Officiant"] and {r["value"] for r in roles} == {0}
    t, _ = gramps_to_tree(db)
    ev = next(e for e in t.personnes["I2731"].evenements if e.valeur == "test #273")
    assert ev.type == "BAPM" and ev.age == "1 jour"
    assert [(a.personne, a.role, a.detail) for a in ev.associations] == [("I2732", "WITN", ""),
                                                                        ("I2732", "OTHER", "Officiant")]
    assert {e.type for e in t.personnes["I2731"].evenements} == {"BAPM", "CENS"}
    nouveaux = {"type273lieu", "type273bapteme", "type273recens", "type273enfant", "type273temoin"}
    assert [x for x in diff(db, tree_to_gramps(t, base=db, generated=False)) if x["handle"] in nouveaux] == []
    ged = write_gedcom(t)

    b = GrampsBackend(client, tmp_path, tmp_path / ".propositions", ttl=0)
    p = b.propose_types()
    print("types #273, bilan réel :", p["bilan_types"], p["ambigus"])
    assert p["bilan_types"]["EventType"]["Baptême"]["standard"] == "Baptism"
    assert p["bilan_types"]["PlaceType"]["Paroisse"]["standard"] == "Parish"
    assert p["bilan_types"]["EventRoleType"]["Témoin"]["standard"] == "Witness"
    assert any(x["chaine"] == "Officiant" for x in p["ambigus"])
    r = b.apply(p["jeton"])
    db2 = client.load_all()
    assert db2.get("Event", "type273bapteme")["type"] == {"_class": "EventType", "value": 15, "string": ""}
    assert db2.get("Place", "type273lieu")["place_type"] == {"_class": "PlaceType", "value": 5, "string": ""}
    assert [x["value"] for x in (r_["role"] for r_ in db2.get("Person", "type273temoin")["event_ref_list"])] == [7, 0]
    assert write_gedcom(gramps_to_tree(db2)[0]) == ged  # le modèle ne change pas
    assert "jeton" not in b.propose_types()  # deuxième exécution : rien à faire
    b.apply(b.propose_undo(r["transaction"])["jeton"])
    db3 = client.load_all()
    assert db3.get("Event", "type273bapteme")["type"]["string"] == "Baptême"
    assert db3.get("Place", "type273lieu")["place_type"]["string"] == "Paroisse"


def blank_ref() -> dict:
    return {"_class": "EventRef", "private": False, "citation_list": [], "note_list": [], "attribute_list": []}


def test_lieux_dates_sur_vrai_gramps_web(client, loaded, tmp_path):
    """#277 : noms et rattachements datés acceptés par l'API, relus à l'identique, noms relus inchangés ; profil
    d'événement de Gramps Web (``place`` = PlaceDisplay.display_event, ``place_name`` si l'API le fournit) au nom
    d'époque ; deuxième proposition vide ; annulation. Chronologies COG tirées de l'extrait des tests (aucun appel
    réseau hors du conteneur)."""
    from test_gramps_lieux_dates import arbre_lieux, lire

    from genealogiste_mcp.gedcom.mapping import write_gedcom
    from genealogiste_mcp.gramps.mapping import est_commune
    from genealogiste_mcp.sources.geo import IndexCog

    db = client.load_all()
    t, _ = gramps_to_tree(db)
    items = diff(db, tree_to_gramps(arbre_lieux(t), base=db))
    client.transaction(items, "Tests d'intégration #277 : lieux fictifs datables")
    index = IndexCog(lire("communes.csv"), lire("mouvements.csv"))
    b = GrampsBackend(client, tmp_path, tmp_path / ".propositions", ttl=0)
    avant = b.snapshot(fresh=True)
    ged = write_gedcom(b.load(fresh=True))

    def cog(codes):
        return {"journal": "test", "resultats": [index.chronologie(c) for c in codes]}
    p = b.propose_place_history(cog)
    print("lieux #277 :", p.get("lieux"), p.get("transaction_gramps", {}).get("bilan"))
    assert "jeton" in p, p
    r = b.apply(p["jeton"])
    db2 = client.load_all()
    places = {o["name"]["value"]: o for o in db2.all("Place").values() if est_commune(o) or o["name"]["value"] == "Seine"}
    ch = places["Charleville-Mézières"]
    assert [(a["value"], a["date"]["modifier"], a["date"]["dateval"][:3]) for a in ch["alt_names"]] == \
        [("Charleville", 1, [1, 10, 1966])]
    assert (ch["name"]["date"]["modifier"], ch["name"]["date"]["dateval"][:3]) == (2, [30, 9, 1966])
    bo = places["Boulogne-Billancourt"]
    assert [(db2.get("Place", x["ref"])["name"]["value"], x["date"]["modifier"]) for x in bo["placeref_list"]] == \
        [("Hauts-de-Seine", 2), ("Seine", 1)]
    assert write_gedcom(b.load(fresh=True)) == ged  # noms relus inchangés
    assert diff(db2, tree_to_gramps(gramps_to_tree(db2)[0], base=db2)) == []
    # profil d'événement de Gramps Web : nom d'époque à la date de l'événement
    vus = {}
    for e in db2.all("Event").values():
        if e.get("description") or not e.get("place") or e["place"] not in (ch["handle"], bo["handle"]):
            continue
        prof = client.request("GET", f"/events/{e['handle']}", params={"profile": "all"}).json()["profile"]
        vus[(e["place"], e["date"]["dateval"][2])] = (prof.get("place"), prof.get("place_name"))
    print("profils #277 :", vus)
    assert vus[(ch["handle"], 1950)][0] == "Charleville, Ardennes, France"
    assert vus[(ch["handle"], 1980)][0] == "Charleville-Mézières, Ardennes, France"
    assert vus[(bo["handle"], 1950)][0] == "Boulogne-Billancourt, Seine, France"
    assert vus[(bo["handle"], 1980)][0] == "Boulogne-Billancourt, Hauts-de-Seine, France"
    # place_name (ce qu'affichent les listes de l'interface) : nom principal jusqu'à l'API 3.25 (place.get_name()),
    # nom à la date de l'événement ensuite (get_location_list) ; relevé par image, voir docs/gramps-web.md
    version = client.request("GET", "/metadata/").json()["gramps_webapi"]["version"]
    nom_liste = vus[(ch["handle"], 1950)][1]
    print(f"place_name #277 (API {version}) :", nom_liste)
    from genealogiste_mcp.gramps.compatibilite import FONCTIONS_API, version_api
    if version_api(version) >= FONCTIONS_API["nom_lieu_date"]:
        assert nom_liste == "Charleville"
    else:
        assert nom_liste in (None, "Charleville-Mézières")
    assert "jeton" not in b.propose_place_history(cog)  # deuxième exécution : rien à faire
    b.apply(b.propose_undo(r["transaction"])["jeton"])
    db3 = client.load_all()
    assert {h: (o["name"], o["alt_names"], o["placeref_list"]) for h, o in db3.all("Place").items()} == \
        {h: (o["name"], o["alt_names"], o["placeref_list"]) for h, o in avant.all("Place").items()}


# ---------------------------------------------------------------------------- #279 : texte enrichi, liens internes

def _html(client, h: str, link_format: str | None = None) -> str:
    params = {"formats": "html"}
    if link_format:
        params["format_options"] = json.dumps({"link_format": link_format})
    return client.request("GET", f"/notes/{h}", params=params).json()["formatted"]["html"]


def test_notes_texte_enrichi_sur_vrai_gramps_web(client, loaded, tmp_path):
    """Note manuelle stylée créée comme l'interface (tags sans _class, name en chaîne : GrampsjsEditor), relue,
    porteur modifié : note identique. Note écrite en Markdown (format_texte) : HTML rendu par l'API. Liens internes
    (GENEALOGISTE_GRAMPS_NOTES_LIENS) : recalcul proposé, appliqué, idempotent, rendu par link_format, annulé."""
    from genealogiste_mcp.gramps.texte import cible_interne

    db = client.load_all()
    jean = next(o for o in db.all("Person").values() if o["gramps_id"] == "I1")
    texte = "Gras italique souligné Serif 14 rouge surligné x² H₂O barré lien interne 🟡 é⚠️ fin"

    def r(mot):
        i = texte.index(mot)
        return [[i, i + len(mot)]]
    ui = [{"name": "bold", "ranges": r("Gras"), "value": None}, {"name": "italic", "ranges": r("italique"), "value": None},
          {"name": "underline", "ranges": r("souligné"), "value": None},
          {"name": "fontface", "ranges": r("Serif"), "value": "Serif"},
          {"name": "fontsize", "ranges": r("14"), "value": 14},
          {"name": "fontcolor", "ranges": r("rouge"), "value": "#FF0000"},
          {"name": "highlight", "ranges": r("surligné"), "value": "#FFFF00"},
          {"name": "superscript", "ranges": r("²"), "value": None},
          {"name": "subscript", "ranges": r("₂"), "value": None},
          {"name": "strikethrough", "ranges": r("barré"), "value": None},
          {"name": "link", "ranges": r("lien"), "value": "https://exemple.org/page"},
          {"name": "link", "ranges": r("interne"), "value": f"gramps://Person/handle/{jean['handle']}"},
          {"name": "bold", "ranges": r("🟡 é⚠️"), "value": None}]
    rep = client.request("POST", "/notes/", json={"_class": "Note", "type": "Person Note",
                                                  "text": {"_class": "StyledText", "string": texte, "tags": ui}})
    assert rep.status_code in (200, 201), rep.text
    nh = next(h for h, n in client.load_all().all("Note").items() if n["text"]["string"] == texte)
    obj = client.request("GET", f"/people/{jean['handle']}").json()
    obj["note_list"].append(nh)
    assert client.request("PUT", f"/people/{jean['handle']}", json=obj).status_code == 200
    avant = client.load_all().get("Note", nh)
    print("note stylée relue (#279) :", json.dumps(avant["text"], ensure_ascii=False))
    assert avant["text"]["string"] == texte and len(avant["text"]["tags"]) == len(ui)
    html = _html(client, nh)
    print("HTML de la note de l'interface (#279) :", html)
    assert "<strong>Gras</strong>" in html and "<em>italique</em>" in html and "<s>barré</s>" in html
    b = GrampsBackend(client, tmp_path, tmp_path / ".propositions", ttl=0)
    t = b.load(fresh=True)
    assert texte in t.personnes["I1"].notes
    # porteur modifié par ailleurs (étiquette) : note identique
    r1 = b.apply(b.propose([{"op": "modifier_personne", "id": "I1", "tags": ["Riche-279"]}], "Porteur",
                           "Essai (test).")["jeton"])
    assert client.load_all().get("Note", nh) == avant
    # note écrite en Markdown
    md = ("**Acte** de *naissance* : [registre](https://archives.exemple.org/a_(b)) et [Jean](gramps://Person/handle/"
          f"{jean['handle']}) ; 2*3 \\*littéral\\*")
    p = b.propose([{"op": "ajouter_source", "titre": "Billet 279", "note": md, "format_texte": "markdown"}],
                  "Markdown", "Essai (test).")
    r2 = b.apply(p["jeton"])
    db = client.load_all()
    src = next(o for o in db.all("Source").values() if o["title"] == "Billet 279")
    note_md = db.get("Note", src["note_list"][0])
    assert note_md["text"]["string"] == "Acte de naissance : registre et Jean ; 2*3 *littéral*"
    html = _html(client, note_md["handle"])
    print("HTML d'une note Markdown (#279) :", html)
    assert "<strong>Acte</strong>" in html and "<em>naissance</em>" in html and "<em>3</em>" not in html
    assert '<a href="https://archives.exemple.org/a_(b)">registre</a>' in html
    html_lien = _html(client, note_md["handle"], "/{obj_class}/{gramps_id}")
    print("HTML avec link_format (#279) :", html_lien)
    assert '<a href="/person/I1">Jean</a>' in html_lien
    # liens internes dans les notes de preuve : recalcul seulement
    b.notes_liens = True
    rec = b.propose_notes()
    print("recalcul avec liens (#279) :", rec["transaction_gramps"]["bilan"], rec["transaction_gramps"].get(
        "liens_internes"))
    assert set(rec["transaction_gramps"]["bilan"]) == {"Note"}
    r3 = b.apply(rec["jeton"])
    with pytest.raises(ProposalError):
        b.propose_notes()  # idempotent sur le vrai serveur (forme relue identique)
    db = client.load_all()
    fiche = next(db.get("Note", h) for h in db.get("Person", jean["handle"])["note_list"]
                 if db.get("Note", h)["text"]["string"].startswith("Fiche de preuve"))
    print("fiche de preuve avec liens (#279) :", json.dumps(fiche["text"], ensure_ascii=False))
    for n in db.all("Note").values():
        for tg in n["text"]["tags"]:
            c = cible_interne(tg.get("value"))
            if c:
                assert db.get(c[0], c[2]), tg  # jamais vers un objet absent
    html = _html(client, fiche["handle"], "/{obj_class}/{gramps_id}")
    print("HTML de la fiche de preuve (#279) :", html)
    assert '<a href="/person/I1">I1</a>' in html and 'href="/event/' in html
    # annulations : liens, Markdown, porteur
    for r in (r3, r2, r1):
        b.apply(b.propose_undo(r["transaction"])["jeton"])
    db = client.load_all()
    assert not any(cible_interne(tg.get("value")) for h, n in db.all("Note").items() if h != nh
                   for tg in n["text"]["tags"])
    assert db.get("Note", nh) == avant


# ---------------------------------------------------------------------------- #274 : personne de référence

def _xml_deux_personnes(a: str, b: str, home: str) -> bytes:
    """Gramps XML minimal et fictif : deux personnes d'identifiants neufs, `home` désignant l'une d'elles."""
    def personne(h, gid, prenom):
        return (f'<person handle="_{h}" change="1" id="{gid}"><gender>M</gender>'
                f'<name type="Birth Name"><first>{prenom}</first><surname>REFERENCE</surname></name></person>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE database PUBLIC "-//Gramps//DTD Gramps XML 1.7.1//EN"\n'
            '"http://gramps-project.org/xml/1.7.1/grampsxml.dtd">\n'
            '<database xmlns="http://gramps-project.org/xml/1.7.1/">'
            '<header><created date="2026-01-01" version="5.2.0"/><researcher/></header>'
            f'<people home="_{home}">{personne(a, "I9001", "Essai")}{personne(b, "I9002", "Autre")}</people>'
            '</database>').encode()


def _diag_reference(tmp_path, racine):
    from genealogiste_mcp import diagnostic
    a = _app_gramps(tmp_path, "sosa-test", "sosa-test")
    a.config.sosa_racine = racine
    time.sleep(1.1)  # /token/ : 1 requête par seconde
    return next(c for c in diagnostic.controles_gramps(a) if c["controle"] == "gramps_personne_reference")


def test_personne_de_reference_vide_sur_arbre_neuf(client, tmp_path):
    """Sur un arbre sans personne de référence, `default_person` est vide et le diagnostic le dit."""
    meta = client.request("GET", "/metadata/").json()
    print("default_person d'un arbre neuf :", repr(meta.get("default_person")))
    assert not meta.get("default_person")
    c = _diag_reference(tmp_path, "I3")
    print("diagnostic (racine I3, aucune référence) :", c)
    assert c["etat"] == "attention" and c["personne_reference"] is None
    assert "Définir la personne de référence" in c["remede"]
    c = _diag_reference(tmp_path, "")
    assert c["etat"] == "ok" and "non définie" in c["detail"] and not c.get("remede")
    c = _diag_reference(tmp_path, "I999999")
    assert c["etat"] == "erreur" and "introuvable" in c["detail"]


def test_import_xml_avec_home_definit_la_personne_de_reference(tmp_path):
    """Voie légitime pour définir la référence sur le Gramps Web jetable : import d'un Gramps XML portant
    `<people home>` (rôle Owner : `ImportFile`). Règle amont : `home` est appliqué à chaque import qui en porte un,
    même si l'arbre en a déjà une (importxml.py, `parse`). Donne les états « identiques » et « différentes »."""
    time.sleep(1.1)
    owner = GrampsClient(URL, "sosa-owner", "sosa-owner")

    def importer(a, b, home):
        r = owner.request("POST", "/importers/gramps/file", content=_xml_deux_personnes(a, b, home),
                          headers={"Content-Type": "application/octet-stream"})
        print("import /importers/gramps/file :", r.status_code, r.text[:300])
        assert r.status_code in (200, 201, 202), r.text

    def reference():
        h = owner.request("GET", "/metadata/").json().get("default_person")
        gid = owner.request("GET", f"/people/{h}", params={"keys": "gramps_id"}).json()["gramps_id"] if h else None
        return h, gid

    importer("a274a", "a274b", "a274b")
    h1, gid1 = reference()
    print("référence après le 1er import :", h1, gid1)
    assert h1 and gid1 == "I9002"  # le serveur attribue ses propres handles : seul le gramps_id est comparable
    c = _diag_reference(tmp_path, "I9002")
    assert c["etat"] == "ok" and c["personne_reference"] == "I9002" == c["racine_sosa"]
    c = _diag_reference(tmp_path, "I3")
    assert c["etat"] == "attention" and "I3" in c["detail"] and "I9002" in c["detail"]
    c = _diag_reference(tmp_path, "")
    assert c["etat"] == "ok" and c["suggestion"] == "GENEALOGISTE_SOSA_RACINE=I9002"
    # second import (mêmes identifiants, personnes en double renumérotées) : `home` écrase la référence existante
    importer("a274a", "a274b", "a274a")
    h2, gid2 = reference()
    print("référence après le 2e import (home vers l'autre personne) :", h2, gid2)
    assert h2 and h2 != h1 and gid2 != "I9002"
    assert _diag_reference(tmp_path, gid2)["etat"] == "ok"


# ---------------------------------------------------------------------------- #261 : blog

def _page_blog(c, pagesize: int = 6) -> tuple[list[dict], str]:
    """Requête exacte de la page Blog (gramps-web v26.11.0, src/views/GrampsjsViewBlog.js:174-190)."""
    regles = {"rules": [{"name": "HasTag", "values": ["Blog"]}]}
    rep = c.request("GET", "/sources/", params={"rules": json.dumps(regles), "page": 1, "pagesize": pagesize,
                                                 "sort": "-change", "locale": "fr", "profile": "all",
                                                 "extend": "all"})
    assert rep.status_code == 200, rep.text
    return rep.json(), rep.headers.get("X-Total-Count", "")


def _corps_blog(c, source: dict) -> list[dict]:
    """Corps affiché (GrampsjsViewBlogPost.js:75-88) : première note de la source, formats=html et link_format."""
    gid = source["extended"]["notes"][0]["gramps_id"]
    rep = c.request("GET", "/notes/", params={"locale": "fr", "profile": "all", "extend": "all", "formats": "html",
                                               "gramps_id": gid,
                                               "format_options": json.dumps({"link_format": "/{obj_class}/{gramps_id}"})})
    assert rep.status_code == 200, rep.text
    return rep.json()


def test_billet_blog_sur_vrai_gramps_web(client, loaded, tmp_path):
    """Billet créé par arbre_proposer/arbre_appliquer (privé par défaut, Markdown, deux images) et billet public :
    vérifiés par les requêtes de la page Blog (titre, auteur, corps HTML, aperçu, tri), lus par un compte Invité
    (privé invisible, public visible) ; billet saisi comme l'interface relu sans réécriture ; annulations."""
    import io

    from PIL import Image

    from genealogiste_mcp.gramps.types import tname
    (tmp_path / "medias").mkdir()
    for nom, gris in (("blog-261-a.jpg", 90), ("blog-261-b.jpg", 200)):
        buf = io.BytesIO()
        Image.new("L", (160, 120), gris).save(buf, "JPEG")
        (tmp_path / "medias" / nom).write_bytes(buf.getvalue())
    b = GrampsBackend(client, tmp_path, tmp_path / ".propositions", ttl=0)
    corps = ("**Jean MARTIN**, tisserand, épouse *Marie DUPONT* : [registre](https://archives.exemple.org/r) et "
             "[sa fiche](gramps://Person/gramps_id/I1).")
    p1 = b.propose([{"op": "ajouter_media", "ref": "a", "fichier": "medias/blog-261-a.jpg", "format": "image/jpeg",
                     "titre": "Portrait fictif (261)"},
                    {"op": "ajouter_media", "ref": "b", "fichier": "medias/blog-261-b.jpg", "format": "image/jpeg",
                     "titre": "Maison fictive (261)"},
                    {"op": "ajouter_billet", "ref": "billet", "titre": "Billet privé 261", "auteur": "Équipe fictive",
                     "texte": corps, "format_texte": "markdown", "medias": ["$a", "$b"]}], "Billet", "Récit (test).")
    print("billet privé, proposition :", p1["resume"], p1["transaction_gramps"]["bilan"], p1["avertissements"])
    assert "+1 _RESN PRIVACY" in p1["diff"] and "+1 _ETIQUETTE Blog" in p1["diff"]
    r1 = b.apply(p1["jeton"])
    assert r1["medias"]["envoyes"] and not r1["medias"]["erreurs"], r1
    prive_id, img_a = p1["references_creees"]["billet"], p1["references_creees"]["a"]
    time.sleep(1.1)  # date de modification distincte : tri -change
    p2 = b.propose([{"op": "ajouter_billet", "ref": "billet", "titre": "Billet public 261", "texte": "Texte public.",
                     "prive": False, "medias": [img_a]}], "Billet public", "Récit (test).")
    r2 = b.apply(p2["jeton"])
    public_id = p2["references_creees"]["billet"]
    with pytest.raises(ProposalError, match="I9"):  # public nommant un vivant : refusé avant tout envoi
        b.propose([{"op": "ajouter_billet", "titre": "Refusé", "texte": "Lucas MARTIN, né en 1990.", "prive": False}],
                  "Billet", "Essai (test).")
    # page Blog, compte Editor (voit le privé)
    billets, total = _page_blog(client)
    print("page Blog (Editor) :", total, [(s["gramps_id"], s["title"], s["private"], s["change"]) for s in billets])
    assert [s["gramps_id"] for s in billets] == [public_id, prive_id] and total == "2"  # -change : récent d'abord
    pv = billets[1]
    assert (pv["title"], pv["author"], pv["private"]) == ("Billet privé 261", "Équipe fictive", True)
    n0 = pv["extended"]["notes"][0]
    assert n0["text"]["string"].startswith("Jean MARTIN, tisserand") and n0["private"] is True
    print("type de la note du billet :", n0["type"])
    note = _corps_blog(client, pv)[0]
    print("corps HTML (Editor) :", note["formatted"]["html"])
    assert "<strong>Jean MARTIN</strong>" in note["formatted"]["html"]
    assert '<a href="https://archives.exemple.org/r">registre</a>' in note["formatted"]["html"]
    assert '<a href="/person/I1">sa fiche</a>' in note["formatted"]["html"]
    apercu = pv["extended"]["media"][0]
    assert pv["media_list"][0]["ref"] == apercu["handle"] and apercu["gramps_id"] == img_a  # aperçu = premier
    assert [m["gramps_id"] for m in pv["extended"]["media"]] == [img_a, p1["references_creees"]["b"]]
    vignette = client.request("GET", f"/media/{apercu['handle']}/thumbnail/200")
    assert vignette.status_code == 200 and vignette.headers["content-type"].startswith("image/")
    dernier, _ = _page_blog(client, pagesize=1)  # « Latest Blog Post » du tableau de bord
    assert [s["gramps_id"] for s in dernier] == [public_id]
    # compte Invité (rôle 0) : billet privé et son corps invisibles, billet public lisible
    time.sleep(1.1)  # /token/ : 1 requête par seconde
    invite = GrampsClient(URL, "sosa-invite", "sosa-invite")
    vus, total_invite = _page_blog(invite)
    print("page Blog (Invité) :", total_invite, [(s["gramps_id"], s["title"]) for s in vus])
    assert [s["gramps_id"] for s in vus] == [public_id]
    assert _corps_blog(invite, vus[0])[0]["formatted"]["html"].strip()
    rep = invite.request("GET", "/notes/", params={"gramps_id": n0["gramps_id"]})
    assert rep.status_code == 404 or rep.json() == []  # 404 relevé sur 3.25.1 : note privée introuvable
    assert invite.request("GET", f"/sources/{pv['handle']}").status_code in (403, 404)
    # relecture par le plugin : corps du billet privé dans le modèle, rien à réécrire
    db = client.load_all()
    t, _ = gramps_to_tree(db)
    assert t.sources[prive_id].note.startswith("Jean MARTIN") and t.sources[prive_id].prive
    assert diff(db, tree_to_gramps(t, base=db)) == []
    # billet saisi comme l'interface (GrampsjsViewNewBlogPost.js:143-176 : note sans type, étiquetée Blog)
    blog = next(h for h, tg in db.all("Tag").items() if tg["name"] == "Blog")
    hs, hn = "blog261uisource00000000", "blog261uinote0000000000"
    rep = client.request("POST", "/objects/", json=[
        {"_class": "Source", "handle": hs, "title": "Billet de l'interface 261", "author": "Moi",
         "note_list": [hn], "tag_list": [blog], "media_list": [], "private": False},
        {"_class": "Note", "handle": hn, "text": {"_class": "StyledText", "string": "Saisi dans l'interface."},
         "tag_list": [blog], "private": False}])
    assert rep.status_code in (200, 201), rep.text
    db = client.load_all()
    print("note créée par l'interface : type", db.get("Note", hn)["type"])
    assert tname(db.get("Note", hn)["type"]) == "General"
    t, _ = gramps_to_tree(db)
    ui = next(s for s in t.sources.values() if s.titre == "Billet de l'interface 261")
    assert ui.tags == ["Blog"] and ui.note == "Saisi dans l'interface."
    assert diff(db, tree_to_gramps(t, base=db)) == []
    for cls, h in (("sources", hs), ("notes", hn)):
        assert client.request("DELETE", f"/{cls}/{h}").status_code == 200
    # annulations (images envoyées comprises)
    for r in (r2, r1):
        b.apply(b.propose_undo(r["transaction"])["jeton"])
    assert _page_blog(client)[0] == []
    db = client.load_all()
    assert not [m for m in db.all("Media").values() if (m.get("desc") or "").endswith("(261)")]
    assert "Blog" not in {tg["name"] for tg in db.all("Tag").values()}
