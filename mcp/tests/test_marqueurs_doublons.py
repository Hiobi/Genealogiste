"""#311 : marqueurs à valeur unique en double (Genealogiste-Vivant, Genealogiste-UID, Genealogiste-Statut…) après
une fusion native de Gramps ou une synchro faite hors du plugin, et le même cas dans un GEDCOM (backend fichier).

- lecture : la valeur la plus protectrice pour Vivant (forcé vivant > déduit > forcé décédé), la plus grave pour un
  Statut, sinon la première ; les autres valeurs restent dans le modèle (``extra``) ;
- écriture : un objet non modifié est réécrit à l'identique ; une écriture ordinaire ne retire aucun doublon ;
  seules ``marquer_vivant`` et ``dedoublonner_marqueurs`` les retirent, et le diff de la proposition le montre ;
- signalement : ``arbre_coherence`` et ``diagnostic``.

Données fictives uniquement.
"""

from __future__ import annotations

import pytest
from gramps_fake import URL, FakeGrampsWeb

from genealogiste_mcp import coherence, server
from genealogiste_mcp.config import Config
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom
from genealogiste_mcp.gramps.mapping import GrampsDb, diff, gramps_to_tree, tree_to_gramps
from genealogiste_mcp.gramps.types import attribute, blank, event_ref, gtype, tname

UID_A, UID_B = "aaaaaaaa-1111-4111-8111-000000000311", "bbbbbbbb-2222-4222-8222-000000000311"


def _personne(h: str, gid: str, prenom: str, nom: str = "FICTIF", sexe: int = 1) -> dict:
    p = blank("Person", h, gid)
    p["primary_name"]["first_name"] = prenom
    p["primary_name"]["surname_list"] = [{"_class": "Surname", "surname": nom, "prefix": "", "primary": True,
                                          "origintype": gtype("NameOriginType", ""), "connector": ""}]
    p["gender"] = sexe
    return p


def _valeurs(obj: dict, nom: str) -> list[str]:
    return [a["value"] for a in obj.get("attribute_list") or [] if tname(a.get("type")) == nom]


def base_doublons() -> GrampsDb:
    """État d'une base après une fusion native : personne avec deux Vivant (N puis Y), deux UID ; famille avec deux
    UID et deux statuts ; événement avec deux UID ; média avec deux chemins locaux."""
    p = _personne("per1", "I0001", "Jean")
    p["attribute_list"] = [attribute("Genealogiste-UID", UID_A), attribute("Genealogiste-Vivant", "N"),
                           attribute("Genealogiste-UID", UID_B), attribute("Genealogiste-Vivant", "Y"),
                           attribute("Merged Gramps ID", "I0009")]
    p["event_ref_list"] = [event_ref("evt1", "Primary")]
    p["birth_ref_index"] = 0
    e = blank("Event", "evt1", "E0001")
    e["type"] = gtype("EventType", "Birth")
    e["attribute_list"] = [attribute("Genealogiste-UID", "cccccccc-3333-4333-8333-000000000311"),
                           attribute("Genealogiste-UID", "dddddddd-4444-4444-8444-000000000311")]
    f = blank("Family", "fam1", "F0001")
    f["father_handle"] = "per1"
    f["attribute_list"] = [attribute("Genealogiste-UID", "eeeeeeee-5555-4555-8555-000000000311"),
                           attribute("Genealogiste-Statut", "contradictoire | acte fictif A"),
                           attribute("Genealogiste-UID", "ffffffff-6666-4666-8666-000000000311"),
                           attribute("Genealogiste-Statut", "refute | acte fictif B")]
    p["family_list"] = ["fam1"]
    m = blank("Media", "med1", "O0001")
    m.update(path="medias/acte.jpg", mime="image/jpeg", checksum="0123abcd")
    m["attribute_list"] = [attribute("Genealogiste-Fichier", "medias/acte-a.jpg"),
                           attribute("Genealogiste-Fichier", "medias/acte-b.jpg")]
    return GrampsDb.from_objects([p, e, f, m])


# ---------------------------------------------------------------------------- lecture (Gramps)

@pytest.mark.parametrize("valeurs", [["N", "Y"], ["Y", "N"], ["N", "", "Y"], ["", "N"]])
def test_lecture_vivant_en_double_retient_le_plus_protecteur(valeurs):
    p = _personne("per1", "I0001", "Jean")
    p["attribute_list"] = [attribute("Genealogiste-Vivant", v) for v in valeurs]
    t, _ = gramps_to_tree(GrampsDb.from_objects([p]))
    attendu = "Y" if "Y" in valeurs else ""
    assert t.personnes["I0001"].vivant == attendu


def test_lecture_vivant_sous_les_deux_formes_retient_le_plus_protecteur():
    """Ancienne forme Sosa-Vivant comprise : un Y de l'une ou de l'autre forme protège la personne."""
    for attrs in ([attribute("Sosa-Vivant", "Y"), attribute("Genealogiste-Vivant", "N")],
                  [attribute("Genealogiste-Vivant", "N"), attribute("Sosa-Vivant", "Y")]):
        p = _personne("per1", "I0001", "Jean")
        p["attribute_list"] = attrs
        db = GrampsDb.from_objects([p])
        t, _ = gramps_to_tree(db)
        assert t.personnes["I0001"].vivant == "Y"
        assert diff(db, tree_to_gramps(t, base=db, generated=False)) == []  # rien d'effacé à la réécriture


def test_lecture_doublons_valeur_retenue_et_autres_dans_le_modele():
    t, _ = gramps_to_tree(base_doublons())
    p = t.personnes["I0001"]
    assert p.vivant == "Y" and p.uid == UID_A  # Vivant : le plus protecteur ; UID : le premier
    assert {"tag": "_VIVANT", "value": "N"} in p.extra and {"tag": "UID", "value": UID_B} in p.extra
    f = t.familles["F0001"]
    assert f.statut_manuel.statut == "refute"  # le plus grave
    assert f.uid == "eeeeeeee-5555-4555-8555-000000000311"
    e = p.evenements[0]
    assert e.uid == "cccccccc-3333-4333-8333-000000000311"
    assert {"tag": "UID", "value": "dddddddd-4444-4444-8444-000000000311"} in e.extra
    ged = write_gedcom(t)
    assert "1 _VIVANT Y" in ged and "1 _VIVANT N" in ged  # visibles dans le GEDCOM (diff, miroir Git)


# ---------------------------------------------------------------------------- écriture (Gramps)

def test_reecriture_sans_operation_garde_les_doublons_a_l_identique():
    db = base_doublons()
    t, _ = gramps_to_tree(db)
    assert diff(db, tree_to_gramps(t, base=db, generated=False)) == []
    assert diff(db, tree_to_gramps(t, base=db, generated=True, only=set())) == []
    # seconde lecture : mêmes valeurs lues, mêmes doublons
    t2, _ = gramps_to_tree(tree_to_gramps(t, base=db, generated=False))
    assert write_gedcom(t2) == write_gedcom(t)


def test_ecriture_ordinaire_ne_retire_aucun_doublon():
    db = base_doublons()
    t, _ = gramps_to_tree(db)
    t.personnes["I0001"].sexe = "F"
    t.familles["F0001"].evenements = []
    new = tree_to_gramps(t, base=db, generated=False)
    p = new.get("Person", "per1")
    assert p["gender"] == 0
    assert p["attribute_list"] == db.get("Person", "per1")["attribute_list"]
    assert new.get("Family", "fam1")["attribute_list"] == db.get("Family", "fam1")["attribute_list"]
    assert new.get("Media", "med1")["attribute_list"] == db.get("Media", "med1")["attribute_list"]


def test_vivant_modifie_remplace_les_doublons_explicitement():
    """Valeur changée par le modèle (doublons retirés du modèle) : l'écriture ne garde que la nouvelle valeur, ancienne
    forme comprise (elle compte pour la lecture de Vivant)."""
    db = base_doublons()
    p = db.get("Person", "per1")
    p["attribute_list"].append(attribute("Sosa-Vivant", "Y"))
    t, _ = gramps_to_tree(db)
    per = t.personnes["I0001"]
    per.vivant = "N"
    per.extra = [x for x in per.extra if x.get("tag") != "_VIVANT"]
    new = tree_to_gramps(t, base=db, generated=False).get("Person", "per1")
    vals = [(tname(a["type"]), a["value"]) for a in new["attribute_list"] if "Vivant" in tname(a["type"])]
    assert vals == [("Genealogiste-Vivant", "N")]
    assert _valeurs(new, "Genealogiste-UID") == [UID_A, UID_B]  # l'autre doublon reste


# ---------------------------------------------------------------------------- GEDCOM (backend fichier)

GED = """0 HEAD
1 GEDC
2 VERS 7.0
0 @I1@ INDI
1 NAME Jeanne /FICTIF/
1 SEX F
1 BIRT
2 DATE 1950
2 _STAT contradictoire
2 _STAT refute
3 NOTE acte fictif
2 UID 11111111-0311-4111-8111-000000000001
2 UID 11111111-0311-4111-8111-000000000002
1 _VIVANT N
1 _VIVANT Y
1 UID 22222222-0311-4222-8222-000000000001
1 UID 22222222-0311-4222-8222-000000000002
0 @F1@ FAM
1 WIFE @I1@
1 UID 33333333-0311-4333-8333-000000000001
1 _UID 33333333-0311-4333-8333-000000000002
0 TRLR
"""


def test_gedcom_doublons_lus_comme_gramps_et_gardes_a_l_aller_retour():
    t, _ = read_gedcom(GED)
    p = t.personnes["I1"]
    assert p.vivant == "Y" and p.uid == "22222222-0311-4222-8222-000000000001"
    e = p.evenements[0]
    assert e.statut_manuel.statut == "refute" and e.statut_manuel.justification == "acte fictif"
    assert e.uid == "11111111-0311-4111-8111-000000000001"
    assert t.familles["F1"].uid == "33333333-0311-4333-8333-000000000001"
    ged = write_gedcom(t)
    for ligne in ("1 _VIVANT N", "1 _VIVANT Y", "1 UID 22222222-0311-4222-8222-000000000002",
                  "2 _STAT contradictoire", "2 UID 11111111-0311-4111-8111-000000000002",
                  "1 _UID 33333333-0311-4333-8333-000000000002"):
        assert ligne in ged, ligne
    t2, _ = read_gedcom(ged)
    assert write_gedcom(t2) == ged  # stable


def test_gedcom_vers_gramps_doublons_ecrits_comme_attributs():
    """Bascule fichier -> Gramps : les doublons du GEDCOM deviennent des attributs en double (rien de perdu)."""
    t, _ = read_gedcom(GED)
    db = tree_to_gramps(t, generated=False)
    p = next(o for o in db.all("Person").values() if o["gramps_id"] == "I1")
    assert sorted(_valeurs(p, "Genealogiste-Vivant")) == ["N", "Y"]
    assert len(_valeurs(p, "Genealogiste-UID")) == 2
    t2, _ = gramps_to_tree(db)
    assert t2.personnes["I1"].vivant == "Y"


# ---------------------------------------------------------------------------- cohérence (modèle)

def test_coherence_signale_les_marqueurs_en_double():
    t, _ = read_gedcom(GED)
    codes = {(i["code"], i["personne"]) for i in coherence.check_tree(t)}
    assert ("vivant_contradictoire", "I1") in codes
    assert ("marqueur_en_double", "I1") in codes
    assert any(i["code"] == "marqueur_en_double" and i.get("famille") == "F1" for i in coherence.check_tree(t))
    assert {i["code"] for i in coherence.check_person(t, "I1")} >= {"vivant_contradictoire", "marqueur_en_double"}


# ---------------------------------------------------------------------------- backend fichier : outils

@pytest.fixture
def app_doublons(app):
    """Arbre de travail : le GEDCOM ci-dessus, déposé tel quel (fichier modifié à la main ou importé d'un autre
    outil)."""
    app.store.path.write_text(GED, encoding="utf-8")
    app.store.write(app.store.load())  # normalisation par l'écrivain (ordre des lignes), rien de perdu
    app.store.commit("fixture #311")
    ged = app.store.text()
    assert "1 _VIVANT N" in ged and "1 _VIVANT Y" in ged and "2 _STAT contradictoire" in ged
    return app


def test_fichier_ecriture_ordinaire_garde_les_doublons(app_doublons):
    p = server.arbre_proposer([{"op": "ajouter_nom", "id": "I1", "nom": {"prenoms": "Jeanne Marie", "nom": "FICTIF"}}],
                              "Nom", "Nom d'usage fictif.")
    assert "_VIVANT" not in p["diff"]
    assert "erreur" not in server.arbre_appliquer(p["jeton"])
    ged = app_doublons.store.text()
    assert "1 _VIVANT N" in ged and "1 _VIVANT Y" in ged
    assert app_doublons.tree().personnes["I1"].vivant == "Y"


def test_fichier_coherence_et_correction_par_proposition(app_doublons):
    codes = {i["code"] for i in server.arbre_coherence()}
    assert {"vivant_contradictoire", "marqueur_en_double"} <= codes
    p = server.arbre_proposer([{"op": "marquer_vivant", "id": "I1", "vivant": "Y"}], "Vivant", "Confirmé (fictif).")
    assert any(line.startswith("-") and "_VIVANT N" in line for line in p["diff"].splitlines())
    assert any("_VIVANT" in x or "Vivant" in x for x in p["resume"])
    server.arbre_appliquer(p["jeton"])
    ged = app_doublons.store.text()
    assert "1 _VIVANT N" not in ged and "1 _VIVANT Y" in ged
    assert "vivant_contradictoire" not in {i["code"] for i in server.arbre_coherence()}
    d = server.arbre_proposer([{"op": "dedoublonner_marqueurs", "id": "I1"}], "UID", "Doublon fictif.")
    assert any(line.startswith("-") and "UID 22222222-0311-4222-8222-000000000002" in line
               for line in d["diff"].splitlines())
    server.arbre_appliquer(d["jeton"])
    t = app_doublons.tree()
    assert t.personnes["I1"].uid == "22222222-0311-4222-8222-000000000001"
    restes = [i for i in server.arbre_coherence("I1") if i["code"] == "marqueur_en_double"]
    # ceux de l'événement (UID et statut)
    assert {(i.get("evenement"), i["marqueur"]) for i in restes} == {
        ("11111111-0311-4111-8111-000000000001", "Genealogiste-UID"),
        ("11111111-0311-4111-8111-000000000001", "Genealogiste-Statut")}
    ev = server.arbre_proposer([{"op": "dedoublonner_marqueurs", "evenement": restes[0]["evenement"]}], "Événement",
                               "Doublons fictifs.")
    assert any("_STAT" in x or "Statut" in x for x in ev["resume"])
    server.arbre_appliquer(ev["jeton"])
    t = app_doublons.tree()
    assert t.personnes["I1"].evenements[0].statut_manuel.statut == "refute"  # le plus grave gardé
    assert not [i for i in server.arbre_coherence("I1") if i["code"] == "marqueur_en_double"]
    from genealogiste_mcp.tree.ops import OpError, apply_ops
    with pytest.raises(OpError, match="aucun marqueur en double"):
        apply_ops(t, [{"op": "dedoublonner_marqueurs", "id": "I1"}])


# ---------------------------------------------------------------------------- backend gramps (faux serveur)

@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


def _gapp(tmp_path, **kw):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend="gramps",
                 gramps_url=URL, gramps_user="sosa", gramps_password="secret", gramps_ttl=0, **kw)
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    return a


def _deux_fiches(fake) -> None:
    """Deux fiches d'une même personne fictive, créées par le plugin : A forcée décédée (N), B forcée vivante (Y)."""
    a = server.arbre_proposer([
        {"op": "ajouter_personne", "ref": "a", "noms": [{"prenoms": "Lou", "nom": "DOUBLON"}], "sexe": "F",
         "vivant": "N"},
        {"op": "ajouter_personne", "ref": "b", "noms": [{"prenoms": "Lou Anne", "nom": "DOUBLON"}], "sexe": "F",
         "vivant": "Y"}], "Deux fiches", "Fiches fictives.")
    assert "erreur" not in server.arbre_appliquer(a["jeton"])


def test_fusion_native_gramps_personne_reste_vivante_et_doublons_conserves(tmp_path, fake):
    a = _gapp(tmp_path)
    try:
        _deux_fiches(fake)
        ids = {p.noms[0].prenoms: pid for pid, p in a.backend.load(fresh=True).personnes.items()}
        ha, hb = (fake.find("Person", ids[x])["handle"] for x in ("Lou", "Lou Anne"))
        # fusion native faite dans l'interface de Gramps Web (phénix : A, la fiche « décédée »)
        r = a.gramps().request("POST", f"/people/{ha}/merge/{hb}", json={"family_merger": True})
        assert r.status_code == 200 and fake.messages[-1] == "Merge Person"
        phenix = fake.objects["Person"][ha]
        assert sorted(_valeurs(phenix, "Genealogiste-Vivant")) == ["N", "Y"]
        assert len(_valeurs(phenix, "Genealogiste-UID")) == 2
        pid = ids["Lou"]
        t = a.backend.load(fresh=True)
        assert t.personnes[pid].vivant == "Y"  # reste vivante pour le plugin
        from genealogiste_mcp import privacy
        assert privacy.is_living(t, t.personnes[pid])["vivant"]
        # écriture ordinaire sur la personne : aucun marqueur retiré (Genealogiste-UID noms, lui, couvre le nom
        # alternatif ajouté par la fusion : sa valeur lue est complétée, son doublon reste)
        def marqueurs_(o):
            return [(tname(x["type"]), x["value"]) for x in o["attribute_list"]
                    if tname(x["type"]) in ("Genealogiste-Vivant", "Genealogiste-UID", "Merged Gramps ID")]
        avant = marqueurs_(phenix)
        noms_avant = _valeurs(phenix, "Genealogiste-UID noms")
        p = server.arbre_proposer([{"op": "modifier_personne", "id": pid, "notes_ajout": ["Note fictive."]}],
                                  "Note", "Note fictive.")
        assert "_VIVANT" not in "\n".join(x for x in p["diff"].splitlines() if x[:1] in "+-")
        assert "erreur" not in server.arbre_appliquer(p["jeton"])
        assert marqueurs_(fake.objects["Person"][ha]) == avant
        noms = _valeurs(fake.objects["Person"][ha], "Genealogiste-UID noms")
        assert len(noms) == 2 and noms_avant[1] in noms and noms[-1].startswith(noms_avant[0] + " ")
        # écriture ordinaire sur une autre personne : aucun marqueur de la fiche fusionnée retiré
        server.arbre_appliquer(server.arbre_proposer([{"op": "ajouter_personne", "noms": [
            {"prenoms": "Autre", "nom": "FICTIF"}]}], "Autre", "Fictif.")["jeton"])
        assert marqueurs_(fake.objects["Person"][ha]) == avant
        assert a.backend.load(fresh=True).personnes[pid].vivant == "Y"
        # incohérence signalée
        alertes = server.arbre_coherence()
        assert any(i["code"] == "vivant_contradictoire" and i["personne"] == pid for i in alertes)
        assert any(i["code"] == "marqueur_en_double" and i["personne"] == pid for i in alertes)
        # correction proposée, jamais automatique : diff explicite, puis accord
        n = len(fake.transactions)
        c = server.arbre_proposer([{"op": "marquer_vivant", "id": pid, "vivant": "Y"},
                                   {"op": "dedoublonner_marqueurs", "id": pid}], "Doublons", "Fusion vérifiée.")
        assert len(fake.transactions) == n
        assert any(line.startswith("-") and "_VIVANT N" in line for line in c["diff"].splitlines())
        assert any("en double" in x for x in c["diff"].splitlines())
        server.arbre_appliquer(c["jeton"])
        fin = fake.objects["Person"][ha]
        assert _valeurs(fin, "Genealogiste-Vivant") == ["Y"] and len(_valeurs(fin, "Genealogiste-UID")) == 1
        assert _valeurs(fin, "Merged Gramps ID")  # attribut natif de Gramps conservé
        assert not [i for i in server.arbre_coherence() if i["code"] in ("vivant_contradictoire",
                                                                         "marqueur_en_double")]
    finally:
        server.set_app(None)


def test_note_de_preuve_orpheline_signalee(tmp_path, fake):
    a = _gapp(tmp_path)
    try:
        _deux_fiches(fake)
        ids = {p.noms[0].prenoms: pid for pid, p in a.backend.load(fresh=True).personnes.items()}
        ha, hb = (fake.find("Person", ids[x])["handle"] for x in ("Lou", "Lou Anne"))
        assert a.gramps().request("POST", f"/people/{ha}/merge/{hb}").status_code == 200
        a.backend.load(fresh=True)
        alertes = [i for i in server.arbre_coherence() if i["code"] == "note_preuve_orpheline"]
        assert [i["personne"] for i in alertes] == [ids["Lou"]]
        assert ids["Lou Anne"] in alertes[0]["message"] and "gramps_recalculer_notes" in alertes[0]["message"]
    finally:
        server.set_app(None)


def test_diagnostic_gramps_marqueurs_lance_avec_vivants_seulement(tmp_path, fake):
    """Mode gramps : le contrôle lit tout l'arbre, donc lancé seulement par diagnostic(vivants=true), comme le
    contrôle des vivants ; sinon une ligne « non lancé » sans lecture."""
    from genealogiste_mcp import diagnostic
    a = _gapp(tmp_path)
    try:
        _deux_fiches(fake)
        ids = {p.noms[0].prenoms: pid for pid, p in a.backend.load(fresh=True).personnes.items()}
        ha, hb = (fake.find("Person", ids[x])["handle"] for x in ("Lou", "Lou Anne"))
        assert a.gramps().request("POST", f"/people/{ha}/merge/{hb}").status_code == 200
        a2 = _gapp(tmp_path / "autre")
        ctl = next(c for c in diagnostic.controles_gramps(a2) if c["controle"] == "marqueurs")
        assert ctl["etat"] == "ok" and ctl["lance"] is False and a2.backend.db is None
        ctl = next(c for c in diagnostic.controles_gramps(a2, vivants=True) if c["controle"] == "marqueurs")
        assert ctl["etat"] == "attention" and ctl["personnes_vivant_contradictoire"] == [ids["Lou"]]
        assert ctl["fiches_orphelines"] == [ids["Lou"]]
    finally:
        server.set_app(None)


def test_diagnostic_signale_les_marqueurs_en_double(app_doublons):
    from genealogiste_mcp import diagnostic
    ctl = next(c for c in diagnostic.controles_locaux(app_doublons, None, app_doublons.config)
               if c["controle"] == "marqueurs")
    assert ctl["etat"] == "attention" and "I1" in ctl["detail"]
    assert "arbre_proposer" in ctl["remede"]
