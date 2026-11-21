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


def test_chemin_media_apres_envoi_du_vault_relu_tel_quel(client, loaded, tmp_path):
    """#280 (moitié « Web ») : un média du vault envoyé par le plugin. Gramps Web attribue son propre `path`
    (somme + extension, sous son dossier de médias) ; le chemin relatif du vault ne survit que dans l'attribut
    Genealogiste-Fichier, relu tel quel. Un média sans fichier garde le `path` écrit, sans somme, et figure dans
    `filemissing`. Aucune route n'expose le dossier de base des médias du serveur."""
    import hashlib
    import io

    from PIL import Image

    from genealogiste_mcp.gramps.mapping import A_FICHIER
    from genealogiste_mcp.gramps.types import tname
    from genealogiste_mcp.models import Media

    buf = io.BytesIO()
    Image.new("L", (90, 60), 77).save(buf, "JPEG")
    jpeg = buf.getvalue()
    vault = tmp_path / "vault"
    relatif = "documents/État civil/acte-280.jpg"
    (vault / relatif).parent.mkdir(parents=True)
    (vault / relatif).write_bytes(jpeg)
    b = GrampsBackend(client, tmp_path / "donnees", tmp_path / ".propositions", ttl=0,
                      media_dir=(vault / "documents", vault))
    p = b.propose([{"op": "ajouter_media", "ref": "img", "fichier": relatif, "format": "image/jpeg",
                    "titre": "Acte du vault (280)"}], "Média du vault", "Image fictive (280).")
    r = b.apply(p["jeton"])
    assert r["medias"]["envoyes"] and not r["medias"]["erreurs"], r
    db = client.load_all()
    m = next(x for x in db.all("Media").values() if x.get("desc") == "Acte du vault (280)")
    somme = hashlib.md5(jpeg).hexdigest()
    attrs = {tname(a["type"]): a["value"] for a in m["attribute_list"]}
    assert attrs[A_FICHIER] == relatif  # le chemin relatif du vault, seul survivant
    assert m["checksum"] == somme
    assert m["path"] != relatif and m["path"].startswith(somme) and m["path"].rsplit(".", 1)[1] in ("jpg", "jpeg")
    assert "/" not in m["path"]  # le serveur range le fichier sous son dossier, à plat
    # relu tel quel par le plugin : ni le chemin du serveur ni l'attribut ne sont réécrits
    t, _ = gramps_to_tree(db)
    assert next(x for x in t.medias.values() if x.titre == "Acte du vault (280)").fichier == relatif
    assert diff(db, tree_to_gramps(t, base=db)) == []
    # média sans fichier : le path écrit est gardé tel quel, sans somme, signalé « fichier manquant » par le serveur
    t.medias["O280"] = Media(id="O280", fichier="documents/sans-fichier-280.jpg", format="image/jpeg",
                             titre="Sans fichier (280)")
    client.transaction(diff(db, tree_to_gramps(t, base=db)), "Tests d'intégration : média sans fichier (280, fictif)")
    db = client.load_all()
    sans = next(x for x in db.all("Media").values() if x.get("desc") == "Sans fichier (280)")
    assert sans["path"] == "documents/sans-fichier-280.jpg" and not sans.get("checksum")
    manquants = {x["handle"] for x in client.request("GET", "/media/", params={"filemissing": 1}).json()}
    assert sans["handle"] in manquants and m["handle"] not in manquants
    # le dossier de base des médias du serveur n'est exposé par aucune route de métadonnées
    meta = client.request("GET", "/metadata/").json()

    def cles(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k.lower()
                yield from cles(v)
    assert not [k for k in cles(meta) if "media" in k and ("dir" in k or "path" in k or "base" in k)]


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
    direct = invite.request("GET", f"/sources/{pv['handle']}")
    print("billet privé lu par son handle (Invité) :", direct.status_code, direct.text[:600])
    assert direct.status_code in (403, 404) or direct.json() == {}  # API 3.13.0 : 200 et objet vide, rien ne fuit
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

# ---------------------------------------------------------------------------- #276 : groupes de noms

def _historique(client) -> list[int]:
    rep = client.request("GET", "/transactions/history/", params={"sort": "-id", "pagesize": 5})
    return [e["id"] for e in rep.json()]


def test_groupes_de_noms_lecture_ecriture_et_irreversibilite_sur_vrai_gramps_web(client, loaded, tmp_path):
    """Constats sur lesquels repose le choix de ne PAS écrire les groupes de noms (docs/gramps-web.md) : le POST
    n'entre pas dans l'historique des transactions, regrouper un nom sous lui-même laisse la clé listée, aucune
    route ne retire un regroupement ; la lecture est ouverte à tous les rôles, l'écriture exige Editor."""
    from genealogiste_mcp.gramps.compatibilite import FONCTIONS_API, version_api
    assert version_api(client.request("GET", "/metadata/").json()["gramps_webapi"]["version"]) >= \
        FONCTIONS_API["groupes_noms"]
    assert client.name_groups() == {}  # arbre neuf : ni clé, ni regroupement (lecture réelle)
    assert client.request("GET", "/name-groups/").json() == []
    assert client.request("GET", "/name-groups/Dupond").json() == {"surname": "Dupond", "group": "Dupond"}
    avant = _historique(client)
    # écriture (rôle Editor)
    r = client.request("POST", "/name-groups/Dupond/Dupont")
    print("POST /name-groups/Dupond/Dupont :", r.status_code, r.text.strip())
    assert r.status_code == 201 and r.json() == {"surname": "Dupond", "group": "Dupont"}
    assert client.name_groups() == {"Dupond": "Dupont"}
    # segments d'URL encodés : espace et apostrophe
    assert client.request("POST", "/name-groups/LE%20GRAND/Legrand").status_code == 201
    assert client.request("POST", "/name-groups/D%27Aubigny/Daubigny").status_code == 201
    assert client.name_groups() == {"D'Aubigny": "Daubigny", "Dupond": "Dupont", "LE GRAND": "Legrand"}
    # un nom contenant « / » ne peut pas être un segment (convertisseur string de Flask)
    rs = client.request("POST", "/name-groups/A%2FB/C")
    print("POST /name-groups/A%2FB/C :", rs.status_code)
    assert rs.status_code in (404, 400) and "A/B" not in client.name_groups()
    # pas d'entrée dans l'historique : rien à annuler par /transactions/history/<id>/undo
    assert _historique(client) == avant
    # « retour en arrière » : sous lui-même, la clé RESTE listée ; aucune route ne la retire
    assert client.request("POST", "/name-groups/Dupond/Dupond").status_code == 201
    assert client.name_groups()["Dupond"] == "Dupond"
    assert client.request("GET", "/name-groups/Dupond").json() == {"surname": "Dupond", "group": "Dupond"}
    for methode, chemin in (("DELETE", "/name-groups/Dupond"), ("PUT", "/name-groups/Dupond/Dupont"),
                            ("DELETE", "/name-groups/Dupond/Dupond"), ("POST", "/name-groups/Dupond/")):
        rep = client.request(methode, chemin)
        print(methode, chemin, ":", rep.status_code)
        assert rep.status_code in (404, 405), (methode, chemin, rep.status_code)
    assert "Dupond" in client.name_groups() and _historique(client) == avant
    # rôle Member : lecture permise, écriture refusée (EditNameGroup)
    time.sleep(1.1)
    membre = GrampsClient(URL, "sosa-membre", "sosa-membre")
    assert membre.name_groups() == client.name_groups()
    refus = membre.request("POST", "/name-groups/Interdit/Refuse")
    print("POST name-groups, rôle Member :", refus.status_code, refus.text.strip())
    assert refus.status_code == 403 and "Interdit" not in client.name_groups()


def test_groupes_de_noms_outil_export_et_import_sur_vrai_gramps_web(client, loaded, tmp_path):
    """Bilan et export sur le vrai arbre (rien n'est écrit par l'outil) puis procédure manuelle par import XML
    (rôle Owner) : les regroupements du fichier sont posés, un regroupement existant n'est jamais écrasé."""
    from genealogiste_mcp import server
    from genealogiste_mcp.gramps import groupes_noms as gn
    from genealogiste_mcp.gramps import lecture_xml as lx
    a = _app_gramps(tmp_path, "sosa-test", "sosa-test")
    server.set_app(a)
    try:
        avant = dict(client.name_groups())
        histo = _historique(client)
        r = server.gramps_grouper_noms()
        print("gramps_grouper_noms (arbre réel) :", {k: r[k] for k in ("patronymes_examines", "personnes", "conflits")})
        assert "erreur" not in r and "jeton" not in r and r["patronymes_examines"] >= 1
        assert client.name_groups() == avant and _historique(client) == histo  # rien d'écrit
        assert {e["patronyme"]: e["groupe"] for e in r["groupes_existants"]} == avant
        out = tmp_path / "x.gramps"
        e = server.arbre_exporter(format="gramps", chemin=str(out), masquer_vivants=False)
        assert "erreur" not in e and e["groupes_de_noms"]["ecrits"] == len(avant)
        lu = lx.lire_xml(out.read_bytes())
        assert dict(lu.meta.regroupements) == avant
        # procédure manuelle (2) : import d'un Gramps XML qui ne porte que des regroupements
        time.sleep(1.1)
        owner = GrampsClient(URL, "sosa-owner", "sosa-owner")
        xml = gn.regroupements_xml([("SCHMIT", "Schmitt"), ("Dupond", "AUTRE")]).encode()
        rep = owner.request("POST", "/importers/gramps/file", content=xml,
                            headers={"Content-Type": "application/octet-stream"})
        print("import namemaps seuls :", rep.status_code, rep.text[:200])
        assert rep.status_code in (200, 201, 202), rep.text
        groupes = client.name_groups()
        print("groupes après l'import :", groupes)
        assert groupes["SCHMIT"] == "Schmitt"  # posé par l'import
        assert groupes["Dupond"] == "Dupond"  # déjà regroupé : jamais écrasé (Gramps avertit seulement)
    finally:
        server.set_app(None)


# ---------------------------------------------------------------------------- #263 : tâches

_ORDRE_STATUT = {"Open": 1, "In Progress": 2, "Blocked": 3, "Done": 5}  # taskConstants.js : STATUS_ORDER


def _vue_taches(c) -> list[dict]:
    """Requête exacte de la vue Tâches (gramps-web v26.11.0 et v26.11.3, src/views/GrampsjsViewTasks.js:74-89)."""
    regles = {"rules": [{"name": "HasTag", "values": ["ToDo"]}]}
    rep = c.request("GET", "/sources/", params={"rules": json.dumps(regles), "locale": "fr", "sort": "-gramps_id",
                                                 "extend": "tag_list"})
    assert rep.status_code == 200, rep.text
    return rep.json()


def _vue_tache(c, gid: str) -> dict:
    """Page d'une tâche (GrampsjsViewSource.getUrl : gramps_id, profile=all, backlinks, extend=all)."""
    rep = c.request("GET", "/sources/", params={"gramps_id": gid, "locale": "fr", "profile": "all",
                                                 "backlinks": "true", "extend": "all"})
    assert rep.status_code == 200, rep.text
    return rep.json()[0]


def _attribut(tache: dict, typ: str):
    """taskAttribute (taskConstants.js) : valeur du premier attribut de ce type."""
    from genealogiste_mcp.gramps.types import tname
    return next((a["value"] for a in tache.get("attribute_list") or [] if tname(a["type"]) == typ), None)


def _put_comme_l_interface(c, tache: dict, cle: str, valeur: str) -> None:
    """GrampsjsViewTasks._handleUpdateAttribute : objet complet sans extended/profile/backlinks/formatted, attribut
    retiré puis remis en fin, PUT /api/sources/<handle>."""
    corps = {k: v for k, v in tache.items() if k not in ("extended", "profile", "backlinks", "formatted")}
    corps["attribute_list"] = [*[a for a in corps["attribute_list"] if a["type"] != cle],
                               {"_class": "SrcAttribute", "type": cle, "value": valeur}]
    rep = c.request("PUT", f"/sources/{tache['handle']}", json=corps)
    assert rep.status_code == 200, rep.text


def test_taches_sur_vrai_gramps_web(client, loaded, tmp_path):
    """Tâches créées par arbre_proposer/arbre_appliquer (privée par défaut, publique sur demande), vérifiées par
    les requêtes de la vue Tâches et de la page d'une tâche (statut, priorité, description), lues par un compte
    Invité (privée invisible) ; statut et priorité changés comme l'interface (PUT, aussi en lot) relus sans
    réécriture, écart avec l'enquête signalé ; refus d'une tâche publique nommant un vivant ; annulations."""
    from genealogiste_mcp import taches
    from genealogiste_mcp.gramps.types import tname

    b = GrampsBackend(client, tmp_path, tmp_path / ".propositions", ttl=0, taches=True)
    p1 = b.propose([{"op": "ajouter_tache", "ref": "t", "titre": "Mariage MARTIN × DUPONT (263)",
                     "description": "**Table décennale** 1843-1852 d'abord.", "format_texte": "markdown",
                     "priorite": "haute", "personnes": ["I1"], "enquete": "enquete-263", "element": "t1"}],
                   "Tâche", "Plan de recherche (test).")
    print("tâche privée, proposition :", p1["resume"], p1["transaction_gramps"]["bilan"], p1["avertissements"])
    assert "+1 _ETIQUETTE ToDo" in p1["diff"] and "+1 _RESN PRIVACY" in p1["diff"]
    r1 = b.apply(p1["jeton"])
    prive_id = p1["references_creees"]["t"]
    p2 = b.propose([{"op": "ajouter_tache", "ref": "t", "titre": "Relevé public (263)", "description": "Relevé.",
                     "statut": "In Progress", "priorite": "basse", "prive": False}], "Tâche publique", "Plan (test).")
    r2 = b.apply(p2["jeton"])
    public_id = p2["references_creees"]["t"]
    with pytest.raises(ProposalError, match="I9"):  # publique nommant un vivant : refusée avant tout envoi
        b.propose([{"op": "ajouter_tache", "titre": "Refusée", "description": "Lucas MARTIN, né en 1990.",
                    "prive": False}], "Tâche", "Essai (test).")
    # vue Tâches, compte Editor : les deux tâches, statut et priorité lus comme le frontend
    liste = _vue_taches(client)
    print("vue Tâches (Editor) :", [(s["gramps_id"], s["title"], _attribut(s, "Status"), _attribut(s, "Priority"),
                                     s["private"]) for s in liste])
    assert [s["gramps_id"] for s in liste] == sorted([prive_id, public_id], reverse=True)  # -gramps_id
    vus = {s["gramps_id"]: s for s in liste}
    assert (_attribut(vus[prive_id], "Status"), _attribut(vus[prive_id], "Priority")) == ("Open", "1")
    assert (_attribut(vus[public_id], "Status"), _attribut(vus[public_id], "Priority")) == ("In Progress", "9")
    assert [taches.libelle_priorite(_attribut(vus[x], "Priority")) for x in (prive_id, public_id)] == ["haute", "basse"]
    assert all("ToDo" in [t["name"] for t in s["extended"]["tags"]] for s in liste)
    tri = sorted(liste, key=lambda s: _ORDRE_STATUT.get(_attribut(s, "Status"), 4))  # sortTasks (statut)
    assert [s["gramps_id"] for s in tri] == [prive_id, public_id]
    page = _vue_tache(client, prive_id)
    n0 = page["extended"]["notes"][0]  # taskNote : première note de note_list
    print("description :", tname(n0["type"]), n0["private"], n0["text"]["string"][:80])
    assert page["note_list"][0] == n0["handle"] and tname(n0["type"]) == "To Do" and n0["private"] is True
    assert n0["text"]["string"].startswith("Table décennale 1843-1852 d'abord.")
    assert "Jean MARTIN (I1)" in n0["text"]["string"] and "Enquête Genealogiste : enquete-263 · t1" in n0["text"]["string"]
    assert "ToDo" in [client.request("GET", f"/tags/{h}").json()["name"] for h in n0["tag_list"]]
    # compte Invité : la tâche privée et sa description sont invisibles
    time.sleep(1.1)  # /token/ : 1 requête par seconde
    invite = GrampsClient(URL, "sosa-invite", "sosa-invite")
    print("vue Tâches (Invité) :", [s["gramps_id"] for s in _vue_taches(invite)])
    assert [s["gramps_id"] for s in _vue_taches(invite)] == [public_id]
    # relu par le plugin : rien à réécrire
    db = client.load_all()
    t, _ = gramps_to_tree(db, taches=True)
    assert t.sources[prive_id].tache == {"statut": "Open", "priorite": "1"} and t.sources[prive_id].prive
    assert diff(db, tree_to_gramps(t, base=db, taches=True)) == []
    # statut changé comme l'interface (une tâche), puis priorité en lot (deux tâches, une requête chacune)
    _put_comme_l_interface(client, vus[prive_id], "Status", "Done")
    for s in _vue_taches(client):
        _put_comme_l_interface(client, s, "Priority", "5")
    liste = {s["gramps_id"]: s for s in _vue_taches(client)}
    assert [_attribut(liste[x], "Status") for x in (prive_id, public_id)] == ["Done", "In Progress"]
    assert {_attribut(s, "Priority") for s in liste.values()} == {"5"}
    db = client.load_all()
    t, _ = gramps_to_tree(db, taches=True)
    assert t.sources[prive_id].tache == {"statut": "Done", "priorite": "5"}
    assert diff(db, tree_to_gramps(t, base=db, taches=True)) == []  # aucune réécriture parasite
    print("attributs après l'interface :", [(tname(a["type"]), a["value"]) for a in db.get(
        "Source", vus[prive_id]["handle"])["attribute_list"]])
    # écart avec l'enquête : tâche close dans Gramps Web, élément encore ouvert (signalé, rien d'écrit)
    e = {"id": "enquete-263", "pistes": [], "taches_manuelles": [{"id": "t1", "statut": "a_faire",
                                                                  "description": "Table décennale"}]}
    corr = taches.correspondance(e, t)
    print("correspondance :", corr["ecarts"])
    assert [(x["element"], x["tache"]) for x in corr["ecarts"]] == [("t1", prive_id)] and corr["a_memoriser"]
    # le plugin rouvre la tâche (proposition), relue par la vue Tâches
    r3 = b.apply(b.propose([{"op": "modifier_tache", "id": prive_id, "statut": "Open"}], "Réouverture",
                           "Écart (test).")["jeton"])
    assert _attribut({s["gramps_id"]: s for s in _vue_taches(client)}[prive_id], "Status") == "Open"
    # annulations : la réouverture (statut Done de l'interface rétabli) ; une tâche intacte, créée puis annulée ;
    # la création d'une tâche modifiée depuis dans l'interface est en conflit (refus attendu), nettoyée à la main
    b.apply(b.propose_undo(r3["transaction"])["jeton"])
    assert _attribut({s["gramps_id"]: s for s in _vue_taches(client)}[prive_id], "Status") == "Done"
    p4 = b.propose([{"op": "ajouter_tache", "ref": "t", "titre": "Annulée (263)"}], "Tâche", "Plan (test).")
    r4 = b.apply(p4["jeton"])
    assert p4["references_creees"]["t"] in [s["gramps_id"] for s in _vue_taches(client)]
    b.apply(b.propose_undo(r4["transaction"])["jeton"])
    assert sorted(s["gramps_id"] for s in _vue_taches(client)) == sorted([prive_id, public_id])
    for r in (r1, r2):
        with pytest.raises(Exception, match="(?i)conflit|modifi"):
            b.apply(b.propose_undo(r["transaction"])["jeton"])
    db = client.load_all()
    for gid in (prive_id, public_id):
        src = next(s for s in db.all("Source").values() if s["gramps_id"] == gid)
        for cls, h in [("sources", src["handle"])] + [("notes", n) for n in src["note_list"]]:
            assert client.request("DELETE", f"/{cls}/{h}").status_code == 200
    assert _vue_taches(client) == []


# ---------------------------------------------------------------------------- #282 : chercheur, signets, formats de nom

CHERCHEUR_FICTIF = {"name": "Chercheur Fictif", "addr": "1 rue Inventée", "locality": "Lieu-dit Fictif",
                    "city": "Villefictive", "county": "Comtéfictif", "state": "Étatfictif", "country": "Francefictive",
                    "postal": "00000", "phone": "0100000000", "email": "chercheur@example.org",
                    "street": "2 rue Seconde"}


def _app_role(tmp_path, nom, user):
    from genealogiste_mcp import server
    time.sleep(1.1)  # /token/ : 1 requête par seconde
    a = _app_gramps(tmp_path / nom, user, user)
    server.set_app(a)
    return a


def test_reglages_lecture_et_hors_historique_sur_vrai_gramps_web(client, loaded, tmp_path):
    """Constats sur lesquels repose le contrat de #282 : routes de lecture, onze champs du chercheur (vide à l'état
    neuf), signets par espace, formats de nom ; aucune de ces écritures n'entre dans l'historique des transactions."""
    from genealogiste_mcp import server
    from genealogiste_mcp.gramps import reglages as rg
    from genealogiste_mcp.gramps.compatibilite import FONCTIONS_API, version_api
    meta = client.request("GET", "/metadata/").json()
    v = version_api(meta["gramps_webapi"]["version"])
    assert v >= FONCTIONS_API["chercheur_modifier"] and v >= FONCTIONS_API["signets_ecriture"]
    assert sorted(meta["researcher"]) == sorted(rg.CHERCHEUR_CLES)  # les onze champs, chaînes
    assert client.chercheur() == {k: "" for k in rg.CHERCHEUR_CLES} == client.request(
        "GET", "/metadata/researcher/").json()
    assert client.signets_tous() == {e: [] for e in rg.ESPACES.values()}
    assert sorted(client.request("GET", "/bookmarks/").json()) == sorted(rg.ESPACES.values())
    assert client.request("GET", "/bookmarks/gens").status_code == 404
    assert client.formats_noms() == []  # arbre neuf : aucun format personnalisé
    r = client.request("PUT", "/metadata/researcher/", json={"nom": "X"})
    print("clé inconnue :", r.status_code, r.text.strip()[:160])
    assert r.status_code == 422
    # PUT du chercheur : le rôle Editor est refusé
    assert client.request("PUT", "/metadata/researcher/", json={"name": "X"}).status_code == 403
    a = _app_role(tmp_path, "ro", "sosa-owner")
    try:
        r = server.gramps_reglages()
        print("gramps_reglages (réel) :", r)
        assert r["chercheur"] == {"renseigne": False, "champs_renseignes": []} and r["signets"] == {}
        assert r["droits"] == {"chercheur_modifiable": True, "signets_modifiables": True} and "jeton" not in r
        histo = _historique(client)
        owner = a.backend.client
        assert owner.request("PUT", "/metadata/researcher/", json={"name": "Essai"}).status_code == 200
        assert owner.chercheur()["name"] == "Essai"
        assert owner.request("PUT", "/metadata/researcher/", json={k: "" for k in rg.CHERCHEUR_CLES}).status_code == 200
        assert owner.chercheur() == {k: "" for k in rg.CHERCHEUR_CLES}  # « vide » restauré exactement
        assert _historique(client) == histo  # hors transaction : rien dans l'historique du serveur
    finally:
        server.set_app(None)


def test_chercheur_proposition_application_annulation_sur_vrai_gramps_web(client, loaded, tmp_path):
    from genealogiste_mcp import server
    from genealogiste_mcp.gramps import reglages as rg
    vide = {k: "" for k in rg.CHERCHEUR_CLES}
    histo = _historique(client)
    _app_role(tmp_path, "ed", "sosa-test")
    try:  # compte Editor : refusé avant tout calcul
        r = server.gramps_reglages(chercheur=CHERCHEUR_FICTIF)
        assert "Owner" in r["erreur"] and client.chercheur() == vide
    finally:
        server.set_app(None)
    a = _app_role(tmp_path, "ow", "sosa-owner")
    try:
        prop = server.gramps_reglages(chercheur=CHERCHEUR_FICTIF)
        assert {d["champ"] for d in prop["diff"]} == set(CHERCHEUR_FICTIF) and client.chercheur() == vide
        res = server.arbre_appliquer(prop["jeton"])
        print("application :", {k: res[k] for k in ("relecture", "champs_modifies")})
        assert res["relecture"] == "conforme" and client.chercheur() == {**vide, **CHERCHEUR_FICTIF}
        assert _historique(client) == histo
        journal = [e for e in a.backend.transactions() if e["id"] == prop["jeton"]][0]
        assert journal["etat"] == "terminee" and journal["avant"] == vide
        # annulation par Genealogiste : état initial EXACT, y compris les champs vides
        und = server.arbre_annuler_modification(prop["jeton"])
        assert "jeton" in und and client.chercheur() == {**vide, **CHERCHEUR_FICTIF}
        assert "erreur" not in server.arbre_appliquer(und["jeton"]) and client.chercheur() == vide
        # conflit : fiche modifiée dans l'interface entre la proposition et l'application
        prop2 = server.gramps_reglages(chercheur={"name": "Voulu Fictif"})
        a.backend.client.request("PUT", "/metadata/researcher/", json={"name": "Ailleurs Fictif"})
        assert "Conflit" in server.arbre_appliquer(prop2["jeton"])["erreur"]
        assert client.chercheur()["name"] == "Ailleurs Fictif"
        a.backend.client.request("PUT", "/metadata/researcher/", json={"name": ""})
        assert client.chercheur() == vide and _historique(client) == histo
    finally:
        server.set_app(None)


def test_signets_proposition_application_annulation_sur_vrai_gramps_web(client, loaded, tmp_path):
    from genealogiste_mcp import server
    from genealogiste_mcp.gramps import reglages as rg
    db = client.load_all()
    hp = {o["gramps_id"]: h for h, o in db.all("Person").items()}
    hf = {o["gramps_id"]: h for h, o in db.all("Family").items()}
    histo = _historique(client)
    _app_role(tmp_path, "sg", "sosa-test")
    try:
        assert client.signets_tous() == {e: [] for e in rg.ESPACES.values()}
        client.signet_poser("people", hp["I5"])  # signet de l'utilisateur, déjà là
        prop = server.gramps_reglages(signets={"ajouter": [{"cible": "person", "id": "I1"},
                                                            {"cible": "family", "id": "F1"}]})
        assert prop["diff"] == ["+ signet person I1", "+ signet family F1"]
        assert client.signets("people") == [hp["I5"]]  # la proposition n'écrit rien
        res = server.arbre_appliquer(prop["jeton"])
        print("signets appliqués :", res["relecture"], client.signets("people"))
        assert res["relecture"] == "conforme"
        assert client.signets("people") == [hp["I5"], hp["I1"]]  # en fin de liste
        assert client.signets("families") == [hf["F1"]] and _historique(client) == histo
        # l'outil de lecture donne des identifiants, jamais de noms
        lu = server.gramps_reglages()
        assert lu["signets"]["person"] == [{"id": "I5", "handle": hp["I5"]}, {"id": "I1", "handle": hp["I1"]}]
        # conflit : signet ajouté dans l'interface entre la proposition et l'application
        p2 = server.gramps_reglages(signets={"ajouter": [{"cible": "person", "id": "I2"}]})
        client.signet_poser("people", hp["I3"])
        assert "Conflit" in server.arbre_appliquer(p2["jeton"])["erreur"]
        client.signet_retirer("people", hp["I3"])
        # annulation : état initial exact (signet de l'utilisateur intact)
        und = server.arbre_annuler_modification(prop["jeton"])
        assert und["ordre_restitue"] is True
        server.arbre_appliquer(und["jeton"])
        assert client.signets("people") == [hp["I5"]] and client.signets("families") == []
        # retrait puis annulation : mêmes signets, I5 revient en fin de liste
        client.signet_poser("people", hp["I1"])
        p3 = server.gramps_reglages(signets={"retirer": [{"cible": "person", "id": "I5"}]})
        server.arbre_appliquer(p3["jeton"])
        assert client.signets("people") == [hp["I1"]]
        u3 = server.arbre_annuler_modification(p3["jeton"])
        assert u3["ordre_restitue"] is False
        server.arbre_appliquer(u3["jeton"])
        assert client.signets("people") == [hp["I1"], hp["I5"]]
        assert _historique(client) == histo
    finally:
        server.set_app(None)
        for h in client.signets("people"):
            client.signet_retirer("people", h)
        assert client.signets_tous() == {e: [] for e in rg.ESPACES.values()}


def test_signets_d_enquete_sur_vrai_gramps_web(client, loaded, tmp_path):
    from genealogiste_mcp import server
    hp = {o["gramps_id"]: h for h, o in client.load_all().all("Person").items()}
    _app_role(tmp_path, "enq", "sosa-test")
    try:
        client.signet_poser("people", hp["I2"])  # signet de l'utilisateur
        e = server.enquete_ouvrir("Enquête 282", ["I1", "I2"], signets=True)
        assert e["signets"]["diff"] == ["+ signet person I1"] and client.signets("people") == [hp["I2"]]
        server.arbre_appliquer(e["signets"]["jeton"])
        assert client.signets("people") == [hp["I2"], hp["I1"]]
        assert server.enquete_noter(e["id"], statut="close")["signets_a_retirer"]["nombre"] == 1
        ret = server.gramps_reglages(signets={"enquete": e["id"], "action": "retirer"})
        server.arbre_appliquer(ret["jeton"])
        assert client.signets("people") == [hp["I2"]]  # le signet de l'utilisateur reste
    finally:
        server.set_app(None)
        for h in client.signets("people"):
            client.signet_retirer("people", h)


def test_formats_de_nom_chercheur_et_signets_import_export_sur_vrai_gramps_web(client, loaded, tmp_path):
    """Formats de nom : aucune route d'écriture ; un format posé par un import XML (Owner) est lu par
    GET /name-formats/ et réécrit à l'export. Fiche du chercheur d'un fichier : ignorée par Gramps sur un arbre non
    vide (importxml : import_researcher seulement si la base est vide). Export privé relu : signets et formats."""
    from genealogiste_mcp import server
    from genealogiste_mcp.export.gramps_xml import Metadonnees, db_to_xml
    from genealogiste_mcp.gramps import lecture_xml as lx
    from genealogiste_mcp.gramps.mapping import GrampsDb
    for methode, chemin in (("POST", "/name-formats/"), ("PUT", "/name-formats/"), ("DELETE", "/name-formats/")):
        assert client.request(methode, chemin, json={}).status_code in (404, 405)
    time.sleep(1.1)
    owner = GrampsClient(URL, "sosa-owner", "sosa-owner")
    avant_cherch = client.chercheur()
    meta = Metadonnees(chercheur={"resname": "Fichier Fictif"},
                       formats_noms=[(-1, "Prénom NOM", "%f %S", True), (-2, "Nom, prénom", "%s, %f", False)])
    xml = db_to_xml(GrampsDb(), "1.7.1", meta).encode()
    rep = owner.request("POST", "/importers/gramps/file", content=xml,
                        headers={"Content-Type": "application/octet-stream"})
    print("import formats + chercheur :", rep.status_code, rep.text[:160])
    assert rep.status_code in (200, 201, 202)
    formats = client.formats_noms()
    print("formats lus :", formats)
    # importxml.start_format : ``active = bool(attrs.get("active", True))`` : « 0 » est une chaîne non vide, donc vraie ;
    # un format désactivé dans le fichier est activé par l'import de Gramps (constat amont, docs/gramps-web.md)
    assert [(n, f, a) for _, n, f, a in formats][-2:] == [("Prénom NOM", "%f %S", True), ("Nom, prénom", "%s, %f", True)]
    assert client.chercheur() == avant_cherch  # fiche du fichier ignorée : l'arbre n'était pas vide
    _app_role(tmp_path, "exp", "sosa-test")
    try:
        hp = {o["gramps_id"]: h for h, o in client.load_all().all("Person").items()}
        client.signet_poser("people", hp["I3"])
        client.signet_poser("people", hp["I1"])
        out = tmp_path / "prive.gramps"
        r = server.arbre_exporter(format="gramps", chemin=str(out), masquer_vivants=False)
        print("export privé :", {k: r[k] for k in ("signets", "formats_de_noms")})
        lu = lx.lire_xml(out.read_bytes())
        assert [lu.db.get("Person", h)["gramps_id"] for c, h in lu.meta.signets if c == "person"] == ["I3", "I1"]
        assert [(n, f, ac) for _, n, f, ac in lu.meta.formats_noms][-2:] == [("Prénom NOM", "%f %S", True),
                                                                              ("Nom, prénom", "%s, %f", True)]
        assert "Fichier Fictif" not in out.read_text(encoding="utf-8")
        pub = tmp_path / "public.gramps"  # export public : formats écrits, aucune coordonnée
        server.arbre_exporter(format="gramps", chemin=str(pub))
        brut = pub.read_text(encoding="utf-8")
        assert "<name-formats>" in brut and "<researcher/>" in brut
    finally:
        server.set_app(None)
        for h in client.signets("people"):
            client.signet_retirer("people", h)
