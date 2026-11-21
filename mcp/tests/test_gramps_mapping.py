"""Correspondance Sosa <-> Gramps : aller-retour, stabilité, préservation de ce que Sosa ne modélise pas."""

from __future__ import annotations

import copy
import json

import pytest

from genealogiste_mcp.gedcom.mapping import read_gedcom
from genealogiste_mcp.gramps.mapping import (
    A_ASSO,
    A_UID,
    SOSA_AUTO,
    GrampsDb,
    diff,
    gramps_to_tree,
    looks_generated,
    tree_to_gramps,
)
from genealogiste_mcp.gramps.types import date_from_gramps, date_to_gramps, tname, to_raw
from genealogiste_mcp.models import Association, Citation, Event, Place
from genealogiste_mcp.tree.ops import apply_ops

FIXTURES = ["famille.ged", "geneweb7_gwb2ged.ged", "legacy551.ged"]


def normalize(tree) -> dict:
    """Vue comparable d'un arbre, hors champs non mappés (extra) et normalisations documentées."""
    def strip(o):
        if isinstance(o, dict):  # notes de preuve générées (#15) : régénérées en Sosa:auto, hors modèle
            return {k: ([x for x in v if not looks_generated(x)] if k == "notes" and isinstance(v, list)
                        else "" if k == "note" and isinstance(v, str) and looks_generated(v) else strip(v))
                    for k, v in o.items() if k not in ("extra",)}
        if isinstance(o, list):
            return [strip(x) for x in o]
        return o
    d = {"personnes": {k: v.to_dict() for k, v in tree.personnes.items()},
         "familles": {k: v.to_dict() for k, v in tree.familles.items()},
         "sources": {k: v.to_dict() for k, v in tree.sources.items()},
         "depots": {k: v.to_dict() for k, v in tree.depots.items()},
         "medias": {k: v.to_dict() for k, v in tree.medias.items()},
         "notes": dict(tree.notes)}
    for p in d["personnes"].values():
        for n in p["noms"]:
            n["type"] = "" if n["type"] == "BIRTH" else n["type"]
    for f in d["familles"].values():
        for c in f["enfants"]:
            c["filiation"] = "" if c["filiation"] == "BIRTH" else c["filiation"]
    return strip(d)


def merged_places(tree) -> None:
    """Normalisation : un même nom de lieu = un seul objet Gramps (coordonnées / INSEE mis en commun)."""
    best: dict[str, Place] = {}
    events = [e for p in tree.personnes.values() for e in p.evenements] + \
             [e for f in tree.familles.values() for e in f.evenements]
    for e in events:
        if e.lieu and e.lieu.nom:
            b = best.setdefault(e.lieu.nom, copy.deepcopy(e.lieu))
            if not b.code_insee and e.lieu.code_insee:
                b.code_insee = e.lieu.code_insee
            if b.latitude is None and e.lieu.latitude is not None:
                b.latitude, b.longitude = e.lieu.latitude, e.lieu.longitude
    for e in events:
        if e.lieu and e.lieu.nom:
            par = e.lieu.paroisse
            e.lieu = copy.deepcopy(best[e.lieu.nom])
            e.lieu.paroisse = par
            e.lieu.extra = []


@pytest.mark.parametrize("name", FIXTURES)
def test_round_trip_tree_gramps_tree(fixtures, name):
    tree = read_gedcom((fixtures / name).read_text(encoding="utf-8"))[0]
    db = tree_to_gramps(tree)
    back, _ = gramps_to_tree(db)
    merged_places(tree)
    assert json.dumps(normalize(back), sort_keys=True, ensure_ascii=False) == \
        json.dumps(normalize(tree), sort_keys=True, ensure_ascii=False)


@pytest.mark.parametrize("name", FIXTURES)
def test_rewrite_is_stable(fixtures, name):
    """Relire puis réécrire sans modification ne produit aucune transaction."""
    tree = read_gedcom((fixtures / name).read_text(encoding="utf-8"))[0]
    db = tree_to_gramps(tree)
    back, _ = gramps_to_tree(db)
    again = tree_to_gramps(back, base=db)
    assert diff(db, again) == []


def test_ids_uid_and_generated_notes(tree):
    db = tree_to_gramps(tree)
    people = {p["gramps_id"]: p for p in db.all("Person").values()}
    assert set(people) == set(tree.personnes)
    jean = people["I1"]
    assert any(tname(a["type"]) == A_UID and a["value"] == tree.personnes["I1"].uid for a in jean["attribute_list"])
    auto = next(h for h, t in db.all("Tag").items() if t["name"] == SOSA_AUTO)
    research = [n for n in db.all("Note").values() if auto in n["tag_list"]]
    assert research and all(tname(n["type"]) in ("Research", "Source Note") for n in research)
    birth = db.get("Event", next(r["ref"] for r in jean["event_ref_list"]
                                 if tname(db.get("Event", r["ref"])["type"]) == "Birth"))
    # forme canonique : text vide, comme une date lue en Gramps XML (#272)
    assert birth["date"]["dateval"] == [12, 3, 1820, False] and birth["date"]["text"] == ""


def test_named_and_linked_witnesses_round_trip(tree):
    e = tree.personnes["I3"].evenements[0]
    e.associations = [
        Association(nom="Jean DUPONT", role="WITN", detail="Témoin, 40 ans, tonnelier",
                    citations=[Citation(source="S1", page="acte 120")]),
        Association(personne="I1", role="OTHER", detail="Déclarant, père"),
        Association(personne="I6", role="GODP", detail="Parrain | grand-père"),
    ]
    tree.personnes["I3"].associations = [Association(personne="I7", role="GODP", detail="Parrain")]
    db = tree_to_gramps(tree)
    jean = next(p for p in db.all("Person").values() if p["gramps_id"] == "I1")
    roles = [tname(r["role"]) for r in jean["event_ref_list"]]
    assert "Informant" in roles
    pierre = next(p for p in db.all("Person").values() if p["gramps_id"] == "I3")
    assert pierre["person_ref_list"][0]["rel"] == "Parrain"
    back, _ = gramps_to_tree(db)
    got = back.personnes["I3"].evenements[0].associations
    assert [(a.personne, a.nom, a.role) for a in got] == [("", "Jean DUPONT", "WITN"), ("I1", "", "OTHER"),
                                                          ("I6", "", "GODP")]
    assert got[0].citations[0].page == "acte 120" and got[2].detail == "Parrain ¦ grand-père"
    assert [(a.personne, a.role) for a in back.personnes["I3"].associations] == [("I7", "GODP")]
    ev = db.get("Event", next(r["ref"] for r in pierre["event_ref_list"]))
    assert any(tname(a["type"]) == A_ASSO for a in ev["attribute_list"])


def test_manual_status_round_trip(tree):
    ctx = apply_ops(tree, [
        {"op": "definir_statut", "cible": {"type": "evenement", "uid": "33333333-3333-4333-8333-333333333332"},
         "statut": "refute", "justification": "homonyme"},
        {"op": "definir_statut", "cible": {"type": "nom", "id": "I1", "index": 0}, "statut": "contradictoire",
         "justification": "graphies"},
        {"op": "definir_statut", "cible": {"type": "filiation", "famille": "F1", "enfant": "I3"},
         "statut": "refute", "justification": "autre famille"},
        {"op": "marquer_vivant", "id": "I9", "vivant": "N"}])
    back, _ = gramps_to_tree(tree_to_gramps(ctx.tree))
    assert back.personnes["I3"].evenements[1].statut_manuel.justification == "homonyme"
    assert back.personnes["I1"].noms[0].statut_manuel.statut == "contradictoire"
    assert back.familles["F1"].child("I3").statut_manuel.justification == "autre famille"
    assert back.personnes["I9"].vivant == "N"


def test_preserves_unmapped_gramps_data(tree):
    """Ce que Sosa ne modélise pas (adresse, URL, étiquette, attribut, note To Do) n'est jamais perdu."""
    db = tree_to_gramps(tree)
    h, p = next((h, p) for h, p in db.all("Person").items() if p["gramps_id"] == "I1")
    p["urls"] = [{"_class": "Url", "private": False, "path": "https://exemple.org", "desc": "",
                  "type": {"_class": "UrlType", "value": 2, "string": ""}}]
    p["attribute_list"].append({"_class": "Attribute", "private": False,
                                "type": {"_class": "AttributeType", "value": 1, "string": ""}, "value": "x",
                                "citation_list": [], "note_list": []})
    p["tag_list"].append("tag-utilisateur")
    p["primary_name"]["title"] = "Maître"
    db.put({"_class": "Tag", "handle": "tag-utilisateur", "change": 0, "name": "À revoir",
            "color": "#000000000000", "priority": 9})
    back, _ = gramps_to_tree(db)
    # modification Sosa d'une autre personne : la fiche I1 ne bouge pas
    ctx = apply_ops(back, [{"op": "ajouter_evenement", "cible": "I5", "evenement": {
        "type": "DEAT", "date": "1900", "citations": [{"source": "S1", "page": "décès 1900"}]}}])
    new = tree_to_gramps(ctx.tree, base=db)
    items = diff(db, new)
    changed = {(i["_class"], i["handle"]) for i in items if i["type"] == "update"}
    assert ("Person", h) not in changed
    assert new.get("Person", h)["urls"] == p["urls"] and new.get("Person", h)["primary_name"]["title"] == "Maître"
    assert {i["_class"] for i in items if i["type"] == "add"} >= {"Event", "Citation"}
    assert not [i for i in items if i["type"] == "delete"]


def test_gramps_ui_objects_are_read_without_rewrite():
    """Objets créés dans l'interface Gramps (sans attributs Sosa) : lus, puis réécrits à l'identique."""
    simplified = [
        {"_class": "Person", "handle": "h1", "gramps_id": "I0001", "gender": 1, "change": 1,
         "primary_name": {"first_name": "Paul", "surname_list": [{"surname": "Durand", "prefix": "de",
                                                                   "primary": True, "origintype": "",
                                                                   "connector": ""}],
                          "type": "Birth Name", "date": {"dateval": [0, 0, 0, False], "modifier": 0, "quality": 0,
                                                         "calendar": 0, "text": "", "sortval": 0, "newyear": 0,
                                                         "format": None, "year": 0},
                          "citation_list": [], "note_list": [], "private": False, "suffix": "", "title": "",
                          "group_as": "", "sort_as": 0, "display_as": 0, "call": "", "nick": "", "famnick": ""},
         "alternate_names": [], "event_ref_list": [{"ref": "e1", "role": "Primary", "attribute_list": [],
                                                    "citation_list": [], "note_list": [], "private": False}],
         "birth_ref_index": 0, "death_ref_index": -1, "family_list": [], "parent_family_list": [],
         "citation_list": [], "note_list": ["n1"], "media_list": [], "attribute_list": [], "address_list": [],
         "urls": [], "lds_ord_list": [], "person_ref_list": [], "tag_list": [], "private": False},
        {"_class": "Event", "handle": "e1", "gramps_id": "E0001", "type": "Birth", "change": 1,
         "date": {"dateval": [3, 4, 1850, False], "modifier": 0, "quality": 0, "calendar": 0,
                  "text": "3 avril 1850", "sortval": 2396851, "newyear": 0, "format": None, "year": 1850},
         "place": "", "description": "", "citation_list": [], "note_list": [], "media_list": [],
         "attribute_list": [], "tag_list": [], "private": False},
        {"_class": "Note", "handle": "n1", "gramps_id": "N0001", "type": "Person Note", "change": 1,
         "text": {"string": "Note saisie dans Gramps", "tags": []}, "format": 0, "tag_list": [], "private": False},
    ]
    db = GrampsDb.from_objects([to_raw(o) for o in simplified])
    t, _ = gramps_to_tree(db)
    p = t.personnes["I0001"]
    assert p.nom_principal.nom == "de Durand" and p.evenements[0].date == "3 APR 1850"
    assert p.notes == ["Note saisie dans Gramps"]
    new = tree_to_gramps(t, base=db, generated=False)
    assert diff(db, new) == []


@pytest.mark.parametrize("value", ["12 MAR 1820", "ABT 1820", "BEF 1820", "AFT MAR 1820", "EST 1820",
                                   "CAL 1820", "BET 1820 AND 1825", "FROM 1820 TO 1825", "FROM 1820", "TO 1820",
                                   "JULIAN 5 MAR 1700", "FRENCH_R 12 VEND 3", "INT 1820 (vers Pâques)",
                                   "vers la Toussaint", ""])
def test_dates_round_trip(value):
    assert date_from_gramps(date_to_gramps(value)) == value


def test_date_edited_in_gramps_is_rebuilt():
    d = date_to_gramps("12 MAR 1820")
    d["dateval"] = [13, 3, 1820, False]  # modifiée dans l'interface, texte périmé
    assert date_from_gramps(d) == "13 MAR 1820"


def test_event_shared_by_two_people_kept_shared():
    tree = read_gedcom("0 HEAD\n1 GEDC\n2 VERS 7.0\n0 @I1@ INDI\n1 NAME A /X/\n0 @I2@ INDI\n1 NAME B /X/\n"
                       "0 TRLR\n")[0]
    db = tree_to_gramps(tree, generated=False)
    ev = Event(type="CENS", date="1851")
    tree.personnes["I1"].evenements.append(ev)
    db = tree_to_gramps(tree, base=db, generated=False)
    eh = next(iter(db.all("Event")))
    p2 = next(p for p in db.all("Person").values() if p["gramps_id"] == "I2")
    p2["event_ref_list"].append({"_class": "EventRef", "private": False, "citation_list": [], "note_list": [],
                                 "attribute_list": [], "ref": eh,
                                 "role": {"_class": "EventRoleType", "value": 1, "string": ""}})
    back, _ = gramps_to_tree(db)
    assert len(back.personnes["I2"].evenements) == 1
    assert diff(db, tree_to_gramps(back, base=db, generated=False)) == []


# ---------------------------------------------------------------------------- #262 : étiquettes de tout objet

def _tag(handle: str, name: str, priority: int = 0, color: str = "#123412341234") -> dict:
    return {"_class": "Tag", "handle": handle, "change": 0, "name": name, "color": color, "priority": priority}


def _par_id(db, cls: str, gid: str) -> dict:
    return next(o for o in db.all(cls).values() if o.get("gramps_id") == gid)


def base_etiquetee(tree):
    """Base Gramps fictive : étiquettes de l'utilisateur (dont un nom en double), gérées, handle sans objet Tag, sur
    chaque classe modélisée (personne, famille, événement, citation, source, dépôt, média, note partagée)."""
    from genealogiste_mcp.models import Media
    tree.medias["O1"] = Media(id="O1", fichier="medias/acte.jpg", titre="Acte fictif")
    tree.notes["N1"] = "Note partagée fictive"
    db = tree_to_gramps(tree)
    for tg in (_tag("tagblog", "Blog", 1), _tag("tagtodo", "ToDo", 2), _tag("tagblog2", "Blog", 5),
               _tag("tagverif", "À vérifier", 3)):
        db.put(tg)
    auto = next(h for h, t in db.all("Tag").items() if t["name"] == SOSA_AUTO)
    jean = _par_id(db, "Person", "I1")
    jean["tag_list"] = ["tagtodo", "fantome", auto, "tagblog"]  # ordre, handle inconnu et étiquette gérée gardés
    _par_id(db, "Family", "F1")["tag_list"] = ["tagblog2"]  # doublon de nom : lu sans perte
    eh = next(r["ref"] for r in jean["event_ref_list"] if tname(db.get("Event", r["ref"])["type"]) == "Birth")
    db.get("Event", eh)["tag_list"] = ["tagverif", *db.get("Event", eh)["tag_list"]]  # + statut de preuve
    ch = db.get("Event", eh)["citation_list"][0]
    db.get("Citation", ch)["tag_list"] = ["tagtodo"]
    _par_id(db, "Source", "S4")["tag_list"] = ["tagblog"]  # S4 composite : billet sans effet sur la preuve (#261)
    _par_id(db, "Repository", "R1")["tag_list"] = ["tagverif"]
    _par_id(db, "Media", "O1")["tag_list"] = ["tagtodo", "tagblog"]
    _par_id(db, "Note", "N1")["tag_list"] = ["tagtodo"]
    return db, eh, ch


def test_etiquettes_lues_sur_toutes_les_classes(tree):
    db, _, _ = base_etiquetee(tree)
    t, _ = gramps_to_tree(db)
    assert t.personnes["I1"].tags == ["ToDo", "Blog"]  # gérée et handle inconnu hors modèle
    assert t.familles["F1"].tags == ["Blog"]
    naissance = t.personnes["I1"].evenements[0]
    assert naissance.tags == ["À vérifier"] and naissance.citations[0].tags == ["ToDo"]
    assert t.sources["S4"].tags == ["Blog"] and t.depots["R1"].tags == ["À vérifier"]
    assert t.medias["O1"].tags == ["ToDo", "Blog"] and t.notes_tags == {"N1": ["ToDo"]}
    assert t.personnes["I2"].tags == [] and t.sources["S2"].tags == []


def test_etiquettes_aller_retour_sans_perte(tree):
    """Relire puis réécrire : aucune transaction ; ordre, handles, doublon, gérée, inconnue, couleur et priorité
    intacts."""
    db, _, _ = base_etiquetee(tree)
    t, _ = gramps_to_tree(db)
    again = tree_to_gramps(t, base=db)
    assert diff(db, again) == []
    assert again.get("Tag", "tagblog2") == db.get("Tag", "tagblog2")


def test_etiquettes_aller_retour_gedcom_puis_gramps(tree):
    """Gramps -> modèle -> GEDCOM 7 (_ETIQUETTE) -> modèle -> Gramps : aucune étiquette ni tag_list modifiée (les
    uid des noms, absents du GEDCOM, sont régénérés : hors sujet ici)."""
    from genealogiste_mcp.gedcom.mapping import write_gedcom
    db, _, _ = base_etiquetee(tree)
    t, _ = gramps_to_tree(db)
    relu = read_gedcom(write_gedcom(t))[0]
    assert relu.personnes["I1"].tags == ["ToDo", "Blog"] and relu.notes_tags == {"N1": ["ToDo"]}
    items = diff(db, tree_to_gramps(relu, base=db))
    assert not [i for i in items if i["_class"] == "Tag"
                or (i["old"] or {}).get("tag_list") != (i["new"] or {}).get("tag_list")]


def test_etiquettes_ajout_retrait_creation(tree):
    from genealogiste_mcp.gramps.mapping import lignes_etiquettes
    db, eh, ch = base_etiquetee(tree)
    t, _ = gramps_to_tree(db)
    ctx = apply_ops(t, [
        {"op": "modifier_personne", "id": "I1", "tags": ["Généalogie bretonne"], "tags_retrait": ["ToDo"]},
        {"op": "etiqueter", "cible": {"type": "famille", "id": "F1"}, "tags": ["ToDo"], "tags_retrait": ["Blog"]},
        {"op": "etiqueter", "cible": {"type": "depot", "id": "R1"}, "tags": ["Blog"]},
        {"op": "etiqueter", "cible": {"type": "note", "id": "N1"}, "tags_retrait": ["ToDo"]},
        {"op": "etiqueter", "cible": {"type": "citation", "porteur": {"type": "evenement",
                                                                    "uid": t.personnes["I1"].evenements[0].uid},
                                      "source": "S1"}, "tags": ["Blog"]},
    ])
    new = tree_to_gramps(ctx.tree, base=db)
    items = diff(db, new)
    tags_crees = [i for i in items if i["_class"] == "Tag"]
    suivante = max(tg["priority"] for tg in db.all("Tag").values()) + 1  # priorité suivante
    assert [(i["type"], i["new"]["name"], i["new"]["color"], i["new"]["priority"]) for i in tags_crees] == \
        [("add", "Généalogie bretonne", "#000000000000", suivante)]  # couleur par défaut de Gramps
    assert "gramps_id" not in tags_crees[0]["new"]
    hn = tags_crees[0]["handle"]
    auto = _par_id(db, "Person", "I1")["tag_list"][2]
    assert _par_id(new, "Person", "I1")["tag_list"] == ["fantome", auto, "tagblog", hn]
    assert _par_id(new, "Family", "F1")["tag_list"] == ["tagtodo"]  # doublon retiré : l'objet Tag reste
    assert _par_id(new, "Repository", "R1")["tag_list"] == ["tagverif", "tagblog"]  # Blog : priorité la plus haute
    assert _par_id(new, "Note", "N1")["tag_list"] == []
    assert new.get("Citation", ch)["tag_list"] == ["tagtodo", "tagblog"]  # citation mise à jour en place
    assert not [i for i in items if i["type"] == "delete"]  # aucun objet supprimé, aucune étiquette
    assert {"tagblog", "tagtodo", "tagblog2", "tagverif"} <= set(new.all("Tag"))
    lignes = lignes_etiquettes(db, items)
    assert "étiquettes I1 : +Généalogie bretonne −ToDo" in lignes and "étiquettes F1 : +ToDo −Blog" in lignes
    assert len(lignes) == 5


def test_etiquettes_gerees_refusees_et_non_proof_only(tree):
    from genealogiste_mcp.gramps.mapping import etiquettes_gerees, proof_only
    from genealogiste_mcp.tree.ops import OpError
    for nom in (SOSA_AUTO, "Sosa:auto", "genealogiste:AUTO", "Preuve : confirmé", "", " Blog", "a\nb", "x" * 101):
        with pytest.raises(OpError):
            apply_ops(tree, [{"op": "modifier_personne", "id": "I1", "tags": [nom]}])
        with pytest.raises(OpError):
            apply_ops(tree, [{"op": "etiqueter", "cible": {"type": "personne", "id": "I1"}, "tags_retrait": [nom]}])
    db, _, _ = base_etiquetee(tree)
    t, _ = gramps_to_tree(db)
    ctx = apply_ops(t, [{"op": "etiqueter", "cible": {"type": "personne", "id": "I2"}, "tags": ["Blog"]}])
    new = tree_to_gramps(ctx.tree, base=db)
    items = diff(db, new)
    item = next(i for i in items if i["_class"] == "Person")
    assert not proof_only(item, etiquettes_gerees(db, items))  # vraie modification, pas « note de preuve seule »


def test_etiquette_creee_dans_la_transaction_et_reutilisee(tree):
    """Deux objets reçoivent la même étiquette nouvelle : un seul Tag créé ; relecture puis réécriture stables."""
    db = tree_to_gramps(tree)
    t, _ = gramps_to_tree(db)
    ctx = apply_ops(t, [{"op": "etiqueter", "cible": {"type": "personne", "id": "I1"}, "tags": ["Blog", "ToDo"]},
                        {"op": "etiqueter", "cible": {"type": "source", "id": "S1"}, "tags": ["Blog"]}])
    new = tree_to_gramps(ctx.tree, base=db)
    crees = [i["new"] for i in diff(db, new) if i["_class"] == "Tag"]
    assert sorted(x["name"] for x in crees) == ["Blog", "ToDo"]
    assert len({x["priority"] for x in crees}) == 2
    blog = next(x["handle"] for x in crees if x["name"] == "Blog")
    assert blog in _par_id(new, "Source", "S1")["tag_list"]
    back, _ = gramps_to_tree(new)
    assert diff(new, tree_to_gramps(back, base=new)) == []
