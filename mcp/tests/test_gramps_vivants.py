"""#264 : vivants marqués privés dans Gramps Web (faux serveur fidèle au filtre du privé ; données fictives).

Périmètre (objets propres / partagés), lecture par un compte Invité, idempotence, annulation, retrait proposé au
décès (seulement ce que le plugin a posé), réglage off / propose / auto refusé, marquer_vivant prive, diagnostic
(exposition, divergence des règles bornée), billets et tâches, aller-retour sans réécriture."""

from __future__ import annotations

import pytest
from gramps_fake import URL, FakeGrampsWeb

from genealogiste_mcp import server
from genealogiste_mcp.config import Config, prive_vivants_mode
from genealogiste_mcp.gedcom.mapping import read_gedcom
from genealogiste_mcp.gramps.client import GrampsClient
from genealogiste_mcp.gramps.mapping import diff, gramps_to_tree, tree_to_gramps

AJOUTS = """0 @I10@ INDI
1 NAME Alice /SECRET/
1 SEX F
1 BIRT
2 DATE 1985
2 SOUR @S9@
3 PAGE Livret de famille, page 1
1 NOTE Alice travaille à Lille.
1 OBJE @O9@
1 OBJE @O8@
1 FAMS @F10@
0 @I11@ INDI
1 NAME Hugo /MARTIN/
1 SEX M
1 BIRT
2 DATE 2012
1 FAMC @F10@
0 @I12@ INDI
1 NAME Léa /MARTIN/
1 SEX F
1 BIRT
2 DATE 2013
1 DEAT
2 DATE 2013
1 FAMC @F10@
0 @I13@ INDI
1 NAME Paul /ANCIEN/
1 SEX M
1 BIRT
2 DATE 1930
1 DEAT
2 DATE 2000
1 FAMS @F12@
0 @I14@ INDI
1 NAME Rose /VIVE/
1 SEX F
1 BIRT
2 DATE 1950
1 FAMS @F12@
0 @F10@ FAM
1 HUSB @I9@
1 WIFE @I10@
1 CHIL @I11@
1 CHIL @I12@
1 MARR
2 DATE 2010
0 @F12@ FAM
1 HUSB @I13@
1 WIFE @I14@
1 MARR
2 DATE 1975
0 @S9@ SOUR
1 TITL Livret de famille SECRET
0 @O9@ OBJE
1 FILE medias/portrait-alice.jpg
2 FORM image/jpeg
0 @O8@ OBJE
1 FILE medias/groupe.jpg
2 FORM image/jpeg
"""


def _texte(famille_text: str) -> str:
    t = famille_text.replace("1 FAMS @F1@\n1 UID aaaaaaaa-0000-4000-8000-000000000001",
                             "1 FAMS @F1@\n1 OBJE @O8@\n1 NOTE Ami de Alice SECRET.\n"
                             "1 UID aaaaaaaa-0000-4000-8000-000000000001", 1)
    t = t.replace("0 @I9@ INDI", "0 @I9@ INDI\n1 FAMS @F10@", 1)
    return t.replace("0 TRLR", AJOUTS + "0 TRLR")


@pytest.fixture(autouse=True)
def sans_internet(monkeypatch):
    from genealogiste_mcp import diagnostic as diag
    monkeypatch.setattr(diag, "SOURCES", {})


@pytest.fixture
def arbre(famille_text):
    t = read_gedcom(_texte(famille_text))[0]
    assert {"I9", "I10", "I11", "I14"} <= {p for p in t.personnes if p.startswith("I")}
    return t


@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


def seed(fake, tree) -> None:
    for objs in tree_to_gramps(tree).objects.values():
        for o in objs.values():
            fake.put(o)


def app_gramps(tmp_path, mode="off", **kw):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend="gramps",
                 gramps_url=URL, gramps_user="sosa", gramps_password="secret", gramps_ttl=0,
                 gramps_prive_vivants=mode, **kw)
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    return a


@pytest.fixture
def gapp(tmp_path, fake, arbre):
    seed(fake, arbre)
    a = app_gramps(tmp_path)
    yield a
    server.set_app(None)


def obj(fake, cls, gid):
    return fake.find(cls, gid)


def prives(fake) -> dict:
    return {(c, h): bool(o.get("private")) for c, objs in fake.objects.items() for h, o in objs.items()}


def naissance(fake, gid_personne):
    from genealogiste_mcp.gramps.types import tname
    p = obj(fake, "Person", gid_personne)
    return next(fake.objects["Event"][r["ref"]] for r in p["event_ref_list"]
                if tname(fake.objects["Event"][r["ref"]]["type"]) == "Birth")


def invite(fake) -> GrampsClient:
    fake.role = 0
    return GrampsClient(URL, "sosa", "secret")


# ---------------------------------------------------------------------------- réglage

def test_reglage_off_propose_et_auto_refuse():
    assert prive_vivants_mode(None) == prive_vivants_mode("") == "off"
    assert prive_vivants_mode(" Propose ") == "propose"
    with pytest.raises(ValueError, match="jamais posé ni retiré sans proposition"):
        prive_vivants_mode("auto")
    with pytest.raises(ValueError, match="off | propose"):
        prive_vivants_mode("oui")


def test_auto_refuse_au_demarrage(monkeypatch, tmp_path):
    from genealogiste_mcp.config import load_config
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GENEALOGISTE_GRAMPS_PRIVE_VIVANTS", "auto")
    with pytest.raises(ValueError, match="auto refusé"):
        load_config()


# ---------------------------------------------------------------------------- outil : périmètre

def test_perimetre_objets_propres_et_partages(gapp, fake):
    r = server.gramps_proteger_vivants()
    assert r["jeton"] and r["a_proteger"]["personnes"] == ["I10", "I11", "I14", "I9"]
    poses = set(r["transaction_gramps"]["prive_vivants"])
    lignes = "\n".join(sorted(poses))
    for gid in ("I9", "I10", "I11", "I14"):
        assert f"Person {gid} : privé posé ({gid})" in poses
    assert "Family F10 : privé posé (I10, I9)" in poses  # deux conjoints vivants
    assert "F12 :" not in lignes  # conjoint décédé : famille partagée, laissée visible
    assert f"Event {naissance(fake, 'I10')['gramps_id']} : privé posé (I10)" in poses
    assert f"Source {obj(fake, 'Source', 'S9')['gramps_id']} : privé posé (I10)" in poses  # citée par I10 seule
    assert "Media O9 : privé posé (I10)" in poses and "O8" not in lignes  # O8 aussi lié à I1 (décédé)
    assert "S1 :" not in lignes and not any(x.startswith("Event") and "(I1)" in x for x in poses)
    # notes propres : la note d'Alice ; jamais celle de I1 (qui la nomme : résidu listé)
    assert any(x.startswith("Note ") and "(I10)" in x for x in poses)
    partages = {(p["classe"], p["gramps_id"]): p["raison"] for p in r["partages"]}
    assert "I13" in partages[("Family", "F12")] and ("Media", "O8") in partages
    marr12 = next(e for e in fake.objects["Event"].values() if e["handle"] in
                  [x["ref"] for x in obj(fake, "Family", "F12")["event_ref_list"]])
    assert marr12["gramps_id"] not in lignes  # mariage d'un défunt et d'un vivant : visible avec la famille
    assert {(x["classe"], x["personne"]) for x in r["residus"]} >= {("Note", "I10")}
    masques = {(x["classe"], x["gramps_id"]): x["effet"] for x in r["references_masquees"]}
    assert "I12" in masques[("Family", "F10")]  # enfant décédé : filiation masquée, listée
    assert r["non_masquable"] and r["notes_hors_modele"]
    assert r["retraits"] == {"personnes": [], "objets": 0}
    # seuls les drapeaux changent, et seulement de faux à vrai
    jeton = gapp.backend.tokens.peek(r["jeton"])
    for it in jeton["items"]:
        assert it["type"] == "update" and not it["old"].get("private") and it["new"]["private"] is True
        assert {k: v for k, v in it["new"].items() if k != "private"} == \
            {k: v for k, v in it["old"].items() if k != "private"}
    assert len(jeton["protection"]) == len(jeton["items"])


def test_invite_ne_voit_aucun_vivant_et_annulation_exacte(gapp, fake):
    avant = prives(fake)
    r = server.gramps_proteger_vivants()
    res = server.arbre_appliquer(r["jeton"])
    assert "erreur" not in res, res
    assert "Protection des vivants" in fake.messages[-1]
    vivants = {obj(fake, "Person", g)["handle"]: g for g in ("I9", "I10", "I11", "I14")}
    g = invite(fake)
    gens = g.list("Person")
    assert not {p["gramps_id"] for p in gens} & set(vivants.values())
    assert {p["gramps_id"] for p in gens} >= {"I1", "I12", "I13"}
    for h in vivants:
        assert g.request("GET", f"/people/{h}").status_code == 404
        assert g.request("GET", f"/living/{h}").status_code == 404
        assert g.request("GET", "/people/", params={"gramps_id": vivants[h]}).status_code == 404
    assert g.search("SECRET") == [] and g.search("VIVE") == []
    f12 = g.request("GET", f"/families/{obj(fake, 'Family', 'F12')['handle']}").json()
    assert f12["mother_handle"] in ("", None) and f12["father_handle"] == obj(fake, "Person", "I13")["handle"]
    assert g.request("GET", f"/families/{obj(fake, 'Family', 'F10')['handle']}").status_code == 404
    i12 = g.request("GET", f"/people/{obj(fake, 'Person', 'I12')['handle']}").json()
    assert i12["parent_family_list"] == []  # famille des vivants masquée
    evts = {e["gramps_id"] for e in g.list("Event")}
    assert naissance(fake, "I10")["gramps_id"] not in evts and naissance(fake, "I1")["gramps_id"] in evts
    assert "O9" not in {m["gramps_id"] for m in g.list("Media")}
    assert "Alice travaille à Lille." not in str(g.list("Note"))
    # annulation : tous les drapeaux exactement restaurés
    tx = res["transaction"]
    u = server.arbre_annuler_modification(tx)
    fake.role = 3
    assert "erreur" not in server.arbre_appliquer(u["jeton"])
    assert prives(fake) == avant
    assert server.gramps_proteger_vivants()["jeton"]  # annulée : à refaire


def test_idempotent_et_aller_retour_sans_reecriture(gapp, fake):
    server.arbre_appliquer(server.gramps_proteger_vivants()["jeton"])
    r = server.gramps_proteger_vivants()
    assert "jeton" not in r and r["note"].startswith("Rien à faire") and r["vivants_non_prives"] == 0
    db = gapp.backend.snapshot(fresh=True)
    t, _ = gramps_to_tree(db)
    assert diff(db, tree_to_gramps(t, base=db)) == []  # objets privés non modifiés réécrits à l'identique
    # une proposition ordinaire (mode off) sur un vivant protégé ne retire aucun drapeau
    p = server.arbre_proposer([{"op": "modifier_personne", "id": "I9", "notes_ajout": ["Note (test)."]}], "Sexe",
                              "Test (fictif).")
    items = gapp.backend.tokens.peek(p["jeton"])["items"] if "jeton" in p else []
    assert all(it["new"] is None or it["new"].get("private") == (it["old"] or {}).get("private", it["new"].get(
        "private")) for it in items)


def test_objet_ajoute_depuis_sous_un_objet_deja_prive(gapp, fake):
    """Une note ajoutée dans l'interface à la citation (déjà privée) d'un vivant protégé est trouvée au passage
    suivant : un objet privé transmet le motif de ses référents."""
    server.arbre_appliquer(server.gramps_proteger_vivants()["jeton"])
    cit = next(c for c in fake.objects["Citation"].values() if c["page"] == "Livret de famille, page 1")
    assert cit["private"]
    fake.put({"_class": "Note", "handle": "noteajouteeinterface0001", "gramps_id": "N900", "private": False,
              "text": {"_class": "StyledText", "string": "Ajoutée dans l'interface.", "tags": []}, "format": 0,
              "type": {"_class": "NoteType", "value": 1, "string": ""}, "tag_list": []})
    fake.ui_edit("Citation", cit["gramps_id"], lambda o: o["note_list"].append("noteajouteeinterface0001"))
    r = server.gramps_proteger_vivants()
    assert r["transaction_gramps"]["prive_vivants"] == ["Note N900 : privé posé (I10)"]


def test_limite_par_lot_puis_suite(gapp, fake):
    r = server.gramps_proteger_vivants(limite=2)
    # reste : I14, I9, et I10 (famille F10, masquable quand I9 le sera)
    assert r["a_proteger"]["personnes"] == ["I10", "I11"] and r["a_proteger"]["reste_apres_ce_lot"] == 3
    server.arbre_appliquer(r["jeton"])
    r2 = server.gramps_proteger_vivants(limite=2)
    # second lot : I14, I9, et la famille F10 (ses deux conjoints sont maintenant masqués)
    assert {"I14", "I9"} <= set(r2["a_proteger"]["personnes"]) and r2["a_proteger"]["reste_apres_ce_lot"] == 0
    assert "Family F10 : privé posé (I10, I9)" in r2["transaction_gramps"]["prive_vivants"]


def test_note_generee_de_filiation_sur_famille_partagee(tmp_path, fake, famille_text):
    """Constaté sur Gramps Web réel : la note générée « Filiation de <enfant vivant> » est portée par la famille,
    visible quand un parent est décédé ; elle ne parle que de l'enfant : rendue privée avec lui. Une note saisie par
    l'utilisateur qui le nomme reste intacte (résidu listé)."""
    texte = _texte(famille_text).replace("0 @F12@ FAM\n", "0 @F12@ FAM\n1 CHIL @I15@\n").replace(
        "0 TRLR", "0 @I15@ INDI\n1 NAME Noé /VIVE/\n1 BIRT\n2 DATE 1980\n1 FAMC @F12@\n0 TRLR")
    seed(fake, read_gedcom(texte)[0])
    from genealogiste_mcp.gramps.types import tname
    app_gramps(tmp_path)
    try:
        filiation = [n for n in fake.objects["Note"].values() if "Noé VIVE" in n["text"]["string"]
                     and tname(n["type"]) != "Person Note"]
        assert filiation, "note générée de filiation attendue"
        r = server.gramps_proteger_vivants()
        lignes = r["transaction_gramps"]["prive_vivants"]
        for n in filiation:
            assert f"Note {n['gramps_id']} : privé posé (I15)" in lignes
        assert ("Family", "F12") in {(p["classe"], p["gramps_id"]) for p in r["partages"]}
        server.arbre_appliquer(r["jeton"])
        g = invite(fake)
        assert "Noé" not in str(g.list("Note")) and "Noé" not in str(g.list("Family"))
    finally:
        server.set_app(None)


def test_personnes_ciblees(gapp, fake):
    r = server.gramps_proteger_vivants(personnes=["I14"])
    assert r["a_proteger"]["personnes"] == ["I14"]
    assert all("(I14)" in x for x in r["transaction_gramps"]["prive_vivants"])
    assert "inconnue" in server.gramps_proteger_vivants(personnes=["I99"])["erreur"]


# ---------------------------------------------------------------------------- retrait au décès

def test_retrait_propose_au_deces_seulement_ce_qui_a_ete_pose(gapp, fake):
    # privé voulu par l'utilisateur, avant toute protection : jamais retiré
    fake.ui_edit("Person", "I14", lambda o: o.update(private=True))
    server.arbre_appliquer(server.gramps_proteger_vivants()["jeton"])
    # décès d'Alice saisi (proposition ordinaire), puis de Rose
    for gid in ("I10", "I14"):
        p = server.arbre_proposer([{"op": "ajouter_evenement", "cible": gid, "evenement": {"type": "DEAT", "date": "2020", "non_source": True, "motif": "test fictif"}}], "Décès", "Test (fictif).")
        assert "erreur" not in server.arbre_appliquer(p["jeton"]), p
    alertes = [x for x in server.arbre_coherence() if x["code"] == "prive_vivant_a_retirer"]
    # I14 : son privé de personne est celui de l'utilisateur ; ses données propres ont été marquées par le plugin
    assert {x["personne"] for x in alertes} == {"I10", "I14"}
    r = server.gramps_proteger_vivants()
    assert r["retraits"]["personnes"] == ["I10", "I14"]
    lignes = r["transaction_gramps"]["prive_vivants"]
    retires = [x for x in lignes if "privé retiré" in x]
    assert "Person I10 : privé retiré (I10)" in retires and "Media O9 : privé retiré (I10)" in retires
    assert not any("F10" in x or "I9" in x or "I11" in x or "Person I14" in x for x in retires)  # I9 vivant
    assert f"Event {naissance(fake, 'I14')['gramps_id']} : privé retiré (I14)" in retires
    assert "erreur" not in server.arbre_appliquer(r["jeton"])
    assert not obj(fake, "Person", "I10").get("private") and obj(fake, "Family", "F10")["private"]
    assert obj(fake, "Person", "I14")["private"] and not naissance(fake, "I14").get("private")
    assert [x for x in server.arbre_coherence() if x["code"] == "prive_vivant_a_retirer"] == []
    assert "jeton" not in server.gramps_proteger_vivants()  # idempotent
    # retraits=False : rien proposé
    assert "jeton" not in server.gramps_proteger_vivants(retraits=False)


def test_sans_journal_aucun_retrait(gapp, fake):
    server.arbre_appliquer(server.gramps_proteger_vivants()["jeton"])
    gapp.backend.log_path.unlink()
    p = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I10", "evenement": {"type": "DEAT", "date": "2020", "non_source": True, "motif": "test fictif"}}], "Décès", "Test (fictif).")
    server.arbre_appliquer(p["jeton"])
    r = server.gramps_proteger_vivants()
    assert r["retraits"] == {"personnes": [], "objets": 0}


# ---------------------------------------------------------------------------- réglage propose / marquer_vivant

def test_off_rien_ajoute_au_diff(gapp, fake):
    p = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I9",
                                "evenement": {"type": "OCCU", "valeur": "menuisier", "non_source": True, "motif": "test fictif"}}], "Métier", "Test (fictif).")
    assert "prive_vivants" not in p and "prive_vivants" not in p["transaction_gramps"]
    rec = gapp.backend.tokens.peek(p["jeton"])
    assert "protection" not in rec
    assert not any((it["new"] or {}).get("private") for it in rec["items"])


def test_propose_ajoute_la_pose_au_diff(tmp_path, fake, arbre):
    seed(fake, arbre)
    a = app_gramps(tmp_path, mode="propose")
    try:
        p = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I9",
                                    "evenement": {"type": "OCCU", "valeur": "menuisier", "non_source": True, "motif": "test fictif"}}],
                                  "Métier", "Test (fictif).")
        lignes = p["transaction_gramps"]["prive_vivants"]
        assert "Person I9 : privé posé (I9)" in lignes and p["prive_vivants"]["personnes"] == ["I9"]
        assert any(x.startswith("Event") for x in lignes)  # le nouvel événement aussi
        assert not any("I10" in x for x in lignes)  # seulement les personnes touchées
        res = server.arbre_appliquer(p["jeton"])
        assert obj(fake, "Person", "I9")["private"]
        journal = next(e for e in a.backend.transactions(100) if e["id"] == res["transaction"])
        assert {x["gramps_id"] for x in journal["protection"]} >= {"I9"}
        # proposition sur une personne décédée : rien d'ajouté
        p2 = server.arbre_proposer([{"op": "modifier_personne", "id": "I1", "notes_ajout": ["Note (test)."]}], "x",
                                   "Test (fictif).")
        assert "prive_vivants" not in p2.get("transaction_gramps", {})
    finally:
        server.set_app(None)


def test_marquer_vivant_prive(gapp, fake):
    p = server.arbre_proposer([{"op": "marquer_vivant", "id": "I14", "prive": True}], "Privé",
                              "Vivante (fictif).")
    assert "Person I14 : privé posé (I14)" in p["transaction_gramps"]["prive_vivants"]
    assert any("F12" in x for x in p["avertissements"])  # famille partagée avec un défunt : listée
    assert not any(x.startswith("Rose VIVE (I14) : vivant=") for x in p["resume"])  # statut inchangé
    res = server.arbre_appliquer(p["jeton"])
    assert obj(fake, "Person", "I14")["private"] and naissance(fake, "I14")["private"]
    assert next(e for e in gapp.backend.transactions(100) if e["id"] == res["transaction"])["protection"]
    assert "n'est pas présumé" in server.arbre_proposer(
        [{"op": "marquer_vivant", "id": "I1", "prive": True}], "x", "y")["erreur"]
    assert "true seulement" in server.arbre_proposer(
        [{"op": "marquer_vivant", "id": "I9", "prive": False}], "x", "y")["erreur"]


def test_marquer_vivant_prive_en_mode_fichier(app_famille):
    p = server.arbre_proposer([{"op": "marquer_vivant", "id": "I9", "prive": True}], "Privé", "Vivant (fictif).")
    assert "+1 _RESN PRIVACY" in p["diff"] or "RESN PRIVACY" in p["diff"]


# ---------------------------------------------------------------------------- billets, tâches

def test_media_d_un_billet_prive_rendu_prive_par_l_outil(gapp, fake):
    fake.put({"_class": "Media", "handle": "mediabillet00000000000001", "gramps_id": "O50", "path": "b.jpg",
              "mime": "image/jpeg", "desc": "Image du billet", "checksum": "", "attribute_list": [],
              "citation_list": [], "note_list": [], "tag_list": [], "private": False,
              "date": {"_class": "Date", "calendar": 0, "modifier": 0, "quality": 0, "dateval": [0, 0, 0, False],
                       "text": "", "sortval": 0, "newyear": 0, "format": None, "year": 0}})
    fake.put({"_class": "Tag", "handle": "tagblog00000000000000001", "name": "Blog", "color": "#000000000000",
              "priority": 0})
    fake.put({"_class": "Source", "handle": "sourcebillet000000000001", "gramps_id": "S50", "title": "Billet",
              "author": "", "pubinfo": "", "abbrev": "", "note_list": [], "attribute_list": [],
              "reporef_list": [], "tag_list": ["tagblog00000000000000001"], "private": True,
              "media_list": [{"_class": "MediaRef", "ref": "mediabillet00000000000001", "private": False,
                              "rect": None, "attribute_list": [], "citation_list": [], "note_list": []}]})
    r = server.gramps_proteger_vivants()
    assert "Media O50 : privé posé (billet ou tâche S50)" in r["transaction_gramps"]["prive_vivants"]
    assert "O50" not in str(server.gramps_proteger_vivants(personnes=["I9"])["transaction_gramps"])


def test_billet_prive_avertit_media_public(tree):
    from genealogiste_mcp.models import Media
    from genealogiste_mcp.tree.ops import apply_ops

    tree.medias["O1"] = Media(id="O1", fichier="medias/a.jpg", format="image/jpeg", titre="Portrait")
    tree.personnes["I1"].medias.append("O1")
    ctx = apply_ops(tree, [{"op": "ajouter_billet", "titre": "T", "texte": "Récit.", "medias": ["O1"]}],
                    backend="gramps")
    assert any("média O1 est public" in w and "aussi lié à I1" in w for w in ctx.warnings)
    ctx = apply_ops(ctx.tree, [{"op": "modifier_media", "id": "O1", "champs": {"prive": True}}], backend="gramps")
    assert ctx.tree.medias["O1"].prive and any("privé" in x for x in ctx.summary)


def test_billet_public_nommant_l_identifiant_d_un_vivant_refuse(tree):
    from genealogiste_mcp.tree.ops import apply_ops
    from genealogiste_mcp.tree.proposals import ProposalError, prepare

    with pytest.raises(ProposalError, match="I9"):
        prepare(tree, [{"op": "ajouter_billet", "titre": "Note", "texte": "Voir I9.", "prive": False}], "t", "j",
                None, False, None, "gramps")
    ctx = apply_ops(tree, [{"op": "ajouter_billet", "titre": "Note", "texte": "Voir I9."}], backend="gramps")
    assert any("identifiant I9" in w for w in ctx.warnings)


# ---------------------------------------------------------------------------- diagnostic

def _diag(tmp_path, fake, vivants=True, **kw):
    a = app_gramps(tmp_path, **kw)
    try:
        res = server.diagnostic(vivants=vivants)
    finally:
        server.set_app(None)
    res["_app"] = a
    return {c["controle"]: c for c in res["controles"]}, res


def _appels(fake, motif: str) -> list[str]:
    return [str(c.request.url) for c in fake.router.calls if motif in str(c.request.url)]


def test_diagnostic_par_defaut_ne_lit_pas_l_arbre(tmp_path, fake, arbre):
    """Par défaut : contrôle des vivants non lancé, arbre non chargé, aucune requête /api/living/, une ligne ok."""
    seed(fake, arbre)
    c, res = _diag(tmp_path, fake, vivants=False)
    assert res["_app"].backend.db is None
    assert _appels(fake, "/living/") == [] and not [u for u in _appels(fake, "/people/") if "keys=" not in u]
    v = c["gramps_vivants"]
    assert v["etat"] == "ok" and v["lance"] is False and "diagnostic(vivants=true)" in v["detail"]
    assert "30 requêtes" in v["detail"] and "lecture complète de l'arbre" in v["detail"]
    assert "gramps_regle_vivants" not in c and "gramps_prive_a_retirer" not in c


def test_diagnostic_par_defaut_attention_gratuite_si_inscription_libre(tmp_path, fake, arbre):
    """Inscription libre ouverte (lue par gramps_reglages) et réglage off : attention, toujours sans lire l'arbre."""
    seed(fake, arbre)
    fake.api_version, fake.inscription_libre = "3.26.0", True
    c, res = _diag(tmp_path, fake, vivants=False)
    v = c["gramps_vivants"]
    assert v["etat"] == "attention" and "inscription libre" in v["detail"]
    assert "diagnostic(vivants=true)" in v["remede"] and "gramps_proteger_vivants" in v["remede"]
    assert res["_app"].backend.db is None and _appels(fake, "/living/") == []
    c, _ = _diag(tmp_path / "p", fake, vivants=False, mode="propose")
    assert c["gramps_vivants"]["etat"] == "ok"  # réglage propose : pas d'alerte gratuite


def test_diagnostic_vivants_explicite_lance_les_controles(tmp_path, fake, arbre):
    seed(fake, arbre)
    c, res = _diag(tmp_path, fake)
    assert c["gramps_vivants"].get("lance") is not False and "gramps_regle_vivants" in c
    assert res["_app"].backend.db is not None


def test_diagnostic_exposition_inscription_libre(tmp_path, fake, arbre):
    seed(fake, arbre)
    fake.api_version, fake.inscription_libre = "3.26.0", True
    c, res = _diag(tmp_path, fake)
    v = c["gramps_vivants"]
    assert v["etat"] == "attention" and "4 personne(s)" in v["detail"] and "inscription libre" in v["detail"]
    assert v["valeurs"]["vivants_non_prives"] == 4 and v["valeurs"]["comptes_invites"] is None
    for nom in ("Alice", "SECRET", "Lucas", "VIVE"):
        assert nom not in str(res)


def test_diagnostic_comptes_invites_owner(tmp_path, fake, arbre):
    seed(fake, arbre)
    fake.role = 4
    fake.comptes = [{"name": "proprietaire", "role": 4}, {"name": "visiteur", "role": 0}]
    c, res = _diag(tmp_path, fake)
    assert "1 compte(s) Invité" in c["gramps_vivants"]["detail"] and "visiteur" not in str(res)


def test_diagnostic_non_verifiable_puis_ok_apres_protection(tmp_path, fake, arbre):
    seed(fake, arbre)
    c, _ = _diag(tmp_path, fake)
    assert c["gramps_vivants"]["etat"] == "attention" and "non vérifiable" in c["gramps_vivants"]["detail"]
    a = app_gramps(tmp_path)
    server.arbre_appliquer(server.gramps_proteger_vivants()["jeton"])
    server.set_app(None)
    del a
    c, _ = _diag(tmp_path, fake)
    assert c["gramps_vivants"]["etat"] == "ok" and "toutes privées" in c["gramps_vivants"]["detail"]


def test_diagnostic_divergence_des_regles_bornee(tmp_path, fake, famille_text):
    from datetime import date

    # I20 née il y a ~105 ans, sans décès : morte pour le plugin (100 ans), vivante pour Gramps (110 ans) ; avec
    # max_age_probably_alive=100, Gramps rejoint le plugin : divergence de seuil. I9 : Gramps le juge mort (méthode).
    texte = _texte(famille_text).replace(
        "0 TRLR", f"0 @I20@ INDI\n1 NAME Ancien /SEUIL/\n1 BIRT\n2 DATE {date.today().year - 105}\n0 TRLR")
    seed(fake, read_gedcom(texte)[0])
    h20 = obj(fake, "Person", "I20")["handle"]
    fake.vivants[h20], fake.vivants_100[h20] = True, False
    fake.vivants[obj(fake, "Person", "I9")["handle"]] = False
    c, res = _diag(tmp_path, fake)
    r = c["gramps_regle_vivants"]
    assert r["etat"] == "attention"
    assert r["gramps_vivant_plugin_non"] == ["I20"] and r["cause"]["I20"] == "seuil"
    assert "I9" not in r["plugin_vivant_gramps_non"] or r["cause"]["I9"] == "méthode"
    assert r["requetes"] <= r["plafond"] and "Ancien" not in str(res)
    assert any(p.get("max_age_probably_alive") == "100" for _, p in fake.living_requetes)


def test_diagnostic_plafond_des_requetes(tmp_path, fake, gapp):
    from genealogiste_mcp import diagnostic_vivants as dv
    r = dv.regle(gapp, plafond=2)
    assert r["requetes"] <= 2 and len(fake.living_requetes) <= 2
    assert r["non_examinees"] >= r["zone_incertitude"] - 2


def test_diagnostic_signale_les_retraits(tmp_path, fake, gapp):
    server.arbre_appliquer(server.gramps_proteger_vivants()["jeton"])
    p = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I10", "evenement": {"type": "DEAT", "date": "2020", "non_source": True, "motif": "test fictif"}}], "Décès", "Test (fictif).")
    server.arbre_appliquer(p["jeton"])
    res = server.diagnostic(vivants=True)
    c = {x["controle"]: x for x in res["controles"]}
    assert c["gramps_prive_a_retirer"]["personnes"] == ["I10"]
