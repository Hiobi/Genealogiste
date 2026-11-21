"""#273 : types standard de Gramps et libellés français — référentiel, reconnaissance des types personnalisés qui
doublonnent un type standard, lecture sans modification, écriture standard, détection et normalisation."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from genealogiste_mcp.gedcom.mapping import write_gedcom
from genealogiste_mcp.gramps.mapping import (
    A_ASSO,
    GrampsDb,
    apply_items,
    diff,
    gramps_to_tree,
    normaliser_types,
    tree_to_gramps,
    types_en_doublon,
)
from genealogiste_mcp.gramps.types import (
    REFERENTIEL,
    TYPES,
    attribute,
    blank,
    candidats,
    cle_libelle,
    event_ref,
    gtype,
    gtype_ecrit,
    tcanon,
    tname,
    type_standard,
)
from genealogiste_mcp.models import Association, Event, Family, Name, Person, Tree

ROOT = Path(__file__).resolve().parents[2]


# ============================================================================ référentiel

def test_referentiel_concorde_avec_les_tables_du_mapping():
    """Les tables de gramps/types.py (valeurs, personnalisé, défaut) sont celles du référentiel généré."""
    for cls, (custom, defaut, table) in TYPES.items():
        r = REFERENTIEL["classes"][cls]
        assert (custom, defaut) == (r["personnalise"], r["defaut"]), cls
        assert table == {x: e["valeur"] for x, e in r["types"].items()}, cls


def test_referentiel_provenance_et_versions():
    prov = REFERENTIEL["_provenance"]
    assert prov["depot"] == "https://github.com/gramps-project/gramps"
    assert [v["version"] for v in prov["versions"]] == ["5.2", "6.0", "6.1"] == REFERENTIEL["versions"]
    assert all(len(v["sha"]) == 40 and v["branche"].startswith("maintenance/gramps") for v in prov["versions"])
    assert "GPL-2.0-or-later" in REFERENTIEL["_licence"]


def test_types_ajoutes_par_version():
    """Seuls ajouts depuis 5.2 : huit rôles d'événement en 6.0 ; rien en 6.1 ; aucun type retiré."""
    nouveaux = {(cls, x, e["depuis"]) for cls, c in REFERENTIEL["classes"].items() for x, e in c["types"].items()
                if e["depuis"] != "5.2"}
    assert nouveaux == {("EventRoleType", r, "6.0") for r in ("Father", "Mother", "Parent", "Child", "Multiple birth",
                                                               "Friend", "Neighbor", "Officiator")}
    assert not any("retire" in e for c in REFERENTIEL["classes"].values() for e in c["types"].values())


def test_libelles_francais_tires_du_catalogue():
    t = REFERENTIEL["classes"]
    assert t["EventType"]["types"]["Baptism"]["fr"] == {"5.2": "Baptême", "6.0": "Baptême", "6.1": "Baptême"}
    assert t["EventRoleType"]["types"]["Primary"]["contexte"]["6.0"] == "Role"  # msgctxt respecté
    assert t["EventRoleType"]["types"]["Officiator"]["fr"] == {"6.0": "Officiant", "6.1": "Officiant"}
    # variantes : contexte absent du catalogue 6.0 (libellé anglais), « Lieu » / « Emplacement »
    assert t["NameOriginType"]["types"]["Unknown "]["fr"] == {"5.2": "Inconnu", "6.0": "Unknown", "6.1": "Inconnue"}
    assert t["NameOriginType"]["types"]["Location"]["fr"]["5.2"] == "Emplacement"


def _generateur():
    spec = importlib.util.spec_from_file_location("generer_types_gramps", ROOT / "scripts" / "generer_types_gramps.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gramps_factice(racine: Path, roles: str, po: str) -> Path:
    lib = racine / "gramps" / "gen" / "lib"
    lib.mkdir(parents=True)
    (racine / "po").mkdir()
    (racine / ("." + "git") / "refs" / "heads" / "maintenance").mkdir(parents=True)
    (racine / ("." + "git") / "HEAD").write_text("ref: refs/heads/maintenance/gramps99\n")
    (racine / ("." + "git") / "refs" / "heads" / "maintenance" / "gramps99").write_text("a" * 40 + "\n")
    (racine / "gramps" / "version.py").write_text('VERSION_TUPLE = (9, 9, 0)\nVERSION_QUALIFIER = ""\n')
    for cls in _generateur().CLASSES:
        corps = roles if cls == "EventRoleType" else '[(CUSTOM, _("Custom"), "Custom")]'
        (lib / f"{cls.lower()}.py").write_text(
            f"class {cls}(GrampsType):\n    CUSTOM = 0\n    UNKNOWN = -1\n    PRIMARY = 1\n    FATHER = 11\n"
            f"    _CUSTOM = CUSTOM\n    _DEFAULT = CUSTOM\n    _DATAMAP = {corps}\n")
    (racine / "po" / "fr.po").write_text(po, encoding="utf-8")
    return racine


def test_generateur_contexte_fuzzy_et_versions(tmp_path):
    """Le générateur lit _DATAMAP sans importer Gramps et applique gettext/pgettext comme Gramps : contexte
    respecté, entrée « fuzzy » ignorée (libellé anglais), type nouveau daté de sa version."""
    po = ('msgid ""\nmsgstr ""\n\nmsgctxt "Role"\nmsgid "Primary"\nmsgstr "Principal"\n\nmsgid "Primary"\n'
          'msgstr "Primaire"\n\n#, fuzzy\nmsgid "Father"\nmsgstr "Papa"\n\nmsgid "Custom"\nmsgstr "Personnalisé"\n')
    v1 = _gramps_factice(tmp_path / "v1", '[(CUSTOM, _("Custom"), "Custom"), (PRIMARY, _("Primary", "Role"), '
                                          '"Primary")]', po)
    v2 = _gramps_factice(tmp_path / "v2", '[(CUSTOM, _("Custom"), "Custom"), (PRIMARY, _("Primary", "Role"), '
                                          '"Primary"), (FATHER, _("Father"), "Father")]', po)
    ref = _generateur().generer({"5.2": v1, "6.0": v2})
    roles = ref["classes"]["EventRoleType"]["types"]
    assert roles["Primary"]["fr"] == {"5.2": "Principal", "6.0": "Principal"}
    assert roles["Father"] == {"valeur": 11, "depuis": "6.0", "en": {"6.0": "Father"}, "fr": {"6.0": "Father"}}
    assert ref["_provenance"]["versions"][0]["sha"] == "a" * 40
    assert ref["_provenance"]["versions"][1]["version_gramps"] == "9.9.0"


# ============================================================================ reconnaissance

@pytest.mark.parametrize(("cls", "chaine", "attendu"), [
    ("EventType", "Baptême", "Baptism"), ("EventType", "BAPTEME", "Baptism"), ("EventType", "  baptême ", "Baptism"),
    ("EventType", "Recensement", "Census"), ("EventType", "Inhumation", "Burial"),
    ("EventType", "Baptême religieux", "Christening"), ("EventType", "Niveau d’instruction", "Education"),
    ("EventType", "niveau d'instruction", "Education"), ("EventType", "Bat Mitzvah", "Bas Mitzvah"),
    ("EventRoleType", "Témoin", "Witness"), ("EventRoleType", "temoin", "Witness"),
    ("EventRoleType", "Principal", "Primary"), ("EventRoleType", "Père", "Father"),
    ("EventRoleType", "Voisin(e)", "Neighbor"), ("EventRoleType", "parrain, marraine", "Godparent"),
    ("EventRoleType", "Déclarant", "Informant"),
    ("EventRoleType", "Ami", "Friend"), ("EventRoleType", "Voisin", "Neighbor"),  # anciens libellés de Genealogiste
    ("EventRoleType", "Plusieurs", "Multiple birth"),
    ("AttributeType", "Âge", "Age"), ("AttributeType", "age", "Age"), ("AttributeType", "Profession", "Occupation"),
    ("NoteType", "Transcription", "Transcript"), ("NoteType", "Note sur l'individu", "Person Note"),
    ("NoteType", "À faire", "To Do"),
    ("PlaceType", "Paroisse", "Parish"), ("PlaceType", "Département", "Department"), ("PlaceType", "Région", "Region"),
    ("PlaceType", "Pays", "Country"), ("PlaceType", "Ville", "City"), ("PlaceType", "Village", "Village"),
    ("PlaceType", "Hameau", "Hamlet"), ("PlaceType", "Lieu-dit", "Locality"), ("PlaceType", "Bourg", "Town"),
    ("PlaceType", "Municipalité", "Municipality"),
    ("NameType", "Alias", "Also Known As"), ("NameType", "Nom de naissance", "Birth Name"),
    ("NameOriginType", "Lieu", "Location"), ("NameOriginType", "Emplacement", "Location"),
    ("NameOriginType", "Inconnue", "Unknown "),
    ("ChildRefType", "Adopté(e)", "Adopted"), ("ChildRefType", "En nourrice", "Foster"),
    ("FamilyRelType", "Mariés", "Married"), ("FamilyRelType", "Union civile", "Civil Union"),
    ("RepositoryType", "Église", "Church"), ("RepositoryType", "Bibliothèque", "Library"),
    ("SourceMediaType", "Livre", "Book"), ("SourceMediaType", "Microfiche", "Fiche"),
    ("UrlType", "Adresse électronique", "E-mail"),
])
def test_libelle_reconnu(cls, chaine, attendu):
    assert type_standard(cls, chaine) == attendu
    assert tcanon({"_class": cls, "value": TYPES[cls][0], "string": chaine}) == attendu


@pytest.mark.parametrize(("cls", "chaine"), [
    ("EventRoleType", "Officiant"), ("SourceMediaType", "fiche"),  # ambigus : jamais tranchés
    ("PlaceType", "Commune"), ("PlaceType", "Canton"), ("PlaceType", "Arrondissement"),  # aucun libellé de Gramps
    ("EventRoleType", "Parrain"), ("EventType", "Événement"), ("EventType", "Personnalisé"),
    ("AttributeType", "Paroisse"),  # libellé d'une AUTRE classe
    ("EventType", "Baptêmes"), ("EventType", ""),
])
def test_libelle_non_reconnu(cls, chaine):
    assert type_standard(cls, chaine) is None
    assert tcanon({"_class": cls, "value": TYPES[cls][0], "string": chaine}) == chaine


def test_ambiguites_listees():
    assert candidats("EventRoleType", "officiant") == ["Celebrant", "Officiator"]
    assert candidats("SourceMediaType", "FICHE") == ["Card", "Fiche"]


def test_cle_tolerante():
    assert cle_libelle("  Niveau  d’Instruction ") == cle_libelle("niveau d'instruction") == "niveau d'instruction"
    assert cle_libelle("Élection") == "election"


def test_type_standard_inchange_et_ecriture():
    assert tcanon(gtype("EventType", "Baptism")) == "Baptism"
    assert gtype_ecrit("EventRoleType", "Témoin") == gtype("EventRoleType", "Witness")
    assert gtype_ecrit("EventType", "Bénédiction") == gtype("EventType", "Blessing")
    assert gtype_ecrit("EventRoleType", "Parrain") == {"_class": "EventRoleType", "value": 0, "string": "Parrain"}
    assert gtype_ecrit("EventRoleType", "Officiant")["value"] == 0  # ambigu : personnalisé tel quel


# ============================================================================ base Gramps « saisie dans l'interface »

def custom(cls: str, s: str) -> dict:
    return {"_class": cls, "value": TYPES[cls][0], "string": s}


def base_francaise() -> GrampsDb:
    """Objets comme les crée un utilisateur francophone (types personnalisés en français), sans marqueur."""
    p1, p2, p3 = blank("Person", "p1", "I1"), blank("Person", "p2", "I2"), blank("Person", "p3", "I3")
    for p, prenom in ((p1, "Jean"), (p2, "Paul"), (p3, "Marie")):
        p["primary_name"]["first_name"] = prenom
    p1["primary_name"]["type"] = custom("NameType", "Nom de naissance")
    alias = copy.deepcopy(p1["primary_name"])
    alias.update(first_name="Jeannot", type=custom("NameType", "Alias"))
    p1["alternate_names"] = [alias]
    bapt = blank("Event", "e1", "E1")
    bapt["type"] = custom("EventType", "Baptême")
    bene = blank("Event", "e2", "E2")
    bene["type"] = custom("EventType", "Bénédiction")
    off = blank("Event", "e3", "E3")
    off["type"] = custom("EventType", "Recensement")
    cens = blank("Event", "e4", "E4")
    cens["type"] = custom("EventType", "Recensement")
    ref_age = event_ref("e1", "Primary")
    ref_age["role"] = custom("EventRoleType", "Principal")
    ref_age["attribute_list"] = [{**attribute("Age", "0"), "type": custom("AttributeType", "Âge")}]
    p1["event_ref_list"] = [ref_age, event_ref("e2", "Primary"), event_ref("e3", "Primary")]
    temoin = event_ref("e1", "Primary")
    temoin["role"] = custom("EventRoleType", "Témoin")
    officiant = event_ref("e1", "Primary")
    officiant["role"] = custom("EventRoleType", "Officiant")  # ambigu
    p2["event_ref_list"] = [temoin, officiant]
    p3["event_ref_list"] = [event_ref("e4", "Primary")]
    note = blank("Note", "n1", "N1")
    note["text"]["string"] = "Note saisie en français"
    note["type"] = custom("NoteType", "Note sur l'individu")
    p1["note_list"] = ["n1"]
    fam = blank("Family", "f1", "F1")
    fam.update(father_handle="p1", mother_handle="p3", type=custom("FamilyRelType", "Mariés"))
    fam["child_ref_list"] = [{"_class": "ChildRef", "private": False, "citation_list": [], "note_list": [],
                              "ref": "p2", "frel": custom("ChildRefType", "Adopté(e)"),
                              "mrel": custom("ChildRefType", "Adopté(e)")}]
    p1["family_list"] = p3["family_list"] = ["f1"]
    p2["parent_family_list"] = ["f1"]
    paroisse = blank("Place", "l1", "P1")
    paroisse.update(title="Saint-Exemple", place_type=custom("PlaceType", "Paroisse"))
    paroisse["name"]["value"] = "Saint-Exemple"
    commune = blank("Place", "l2", "P2")
    commune.update(title="Villefictive", place_type=custom("PlaceType", "Commune"))
    commune["name"]["value"] = "Villefictive"
    bapt["place"] = "l1"
    depot = blank("Repository", "r1", "R1")
    depot.update(name="Archives fictives", type=custom("RepositoryType", "Église"))
    return GrampsDb.from_objects([p1, p2, p3, bapt, bene, off, cens, note, fam, paroisse, commune, depot])


def test_lecture_comprend_les_types_francais():
    t, _ = gramps_to_tree(base_francaise())
    jean = t.personnes["I1"]
    bapteme = next(e for e in jean.evenements if e.uid and e.type == "BAPM")  # « Baptême » -> BAPM
    assert bapteme.age == "0"  # attribut « Âge » de la référence (rôle « Principal » : événement propre)
    assert [(a.personne, a.role, a.detail) for a in bapteme.associations] == [
        ("I2", "WITN", ""), ("I2", "OTHER", "Officiant")]  # « Témoin » -> Witness ; « Officiant » ambigu : tel quel
    assert {(e.type, e.type_detail) for e in jean.evenements} == {("BAPM", ""), ("EVEN", "Blessing"), ("CENS", "")}
    assert t.personnes["I3"].evenements[0].type == "CENS"
    assert [n.type for n in jean.noms] == ["", "AKA"]
    assert jean.notes == ["Note saisie en français"]  # « Note sur l'individu » : note de personne en ligne
    assert t.familles["F1"].enfants[0].filiation == "ADOPTED"


def test_lecture_puis_reecriture_sans_modification():
    """Aucune migration silencieuse : réécrire l'arbre lu ne change aucun objet (types personnalisés gardés)."""
    db = base_francaise()
    t, _ = gramps_to_tree(db)
    assert diff(db, tree_to_gramps(t, base=db, generated=False)) == []


def test_ecriture_standard_pour_le_neuf_et_le_modifie():
    db = base_francaise()
    t, _ = gramps_to_tree(db)
    jean = t.personnes["I1"]
    jean.evenements.append(Event(type="EVEN", type_detail="Bénédiction", uid="neuf-bene"))
    bapteme = next(e for e in jean.evenements if e.type == "BAPM")
    bapteme.associations[0].detail = "Témoin, voisin"  # précision modifiée, rôle inchangé : « Témoin » gardé
    bapteme.associations[1].role, bapteme.associations[1].detail = "GODP", "Parrain"  # rôle modifié : standard
    out = tree_to_gramps(t, base=db, generated=False)
    neuf = next(o for o in out.all("Event").values() if o["handle"] not in db.all("Event"))
    assert neuf["type"] == gtype("EventType", "Blessing")
    paul = next(o for o in out.all("Person").values() if o["gramps_id"] == "I2")
    assert [r["role"] for r in paul["event_ref_list"]] == [custom("EventRoleType", "Témoin"),
                                                          gtype("EventRoleType", "Godparent")]
    assert out.get("Event", "e1")["type"] == custom("EventType", "Baptême")  # inchangé : forme d'origine
    back, _ = gramps_to_tree(out)
    assert [(a.role, a.detail) for a in back.personnes["I1"].evenements[0].associations] == \
        [("WITN", "Témoin, voisin"), ("GODP", "Parrain")]


ROLES_60 = {"FATH": "Father", "MOTH": "Mother", "PARENT": "Parent", "CHIL": "Child", "MULTIPLE": "Multiple birth",
            "FRIEND": "Friend", "NGHBR": "Neighbor", "OFFICIATOR": "Officiator"}


def _arbre_roles(roles: dict[str, str]) -> Tree:
    t = Tree()
    t.personnes["I1"] = Person(id="I1", noms=[Name(prenoms="Jean")], uid="u1", evenements=[
        Event(type="BIRT", uid="naiss", associations=[Association(personne=f"I{i}", role=r)
                                                     for i, r in enumerate(roles, 10)])])
    for i, _ in enumerate(roles, 10):
        t.personnes[f"I{i}"] = Person(id=f"I{i}", noms=[Name(prenoms=f"P{i}")], uid=f"u{i}")
    return t


def _roles_ecrits(db: GrampsDb) -> dict[str, dict]:
    return {p["gramps_id"]: r["role"] for p in db.all("Person").values() for r in p["event_ref_list"]
            if tname(r["role"]) != "Primary"}


def test_roles_du_modele_ecrits_en_types_standard():
    """Avant #273 : « Père », « Mère », « Enfant », « Ami », « Voisin », « Plusieurs », « Parrain » (précision) et
    Celebrant ; désormais le type standard (rôles de Gramps 6.0 compris)."""
    roles = {**ROLES_60, "WITN": "Witness", "CLERGY": "Clergy", "GODP": "Godparent"}
    t = _arbre_roles(roles)
    t.personnes["I1"].evenements[0].associations[-1].detail = "Parrain, oncle"
    ecrits = _roles_ecrits(tree_to_gramps(t, generated=False))
    assert ecrits == {f"I{i}": gtype("EventRoleType", std) for i, std in enumerate(roles.values(), 10)}
    back, _ = gramps_to_tree(tree_to_gramps(t, generated=False))
    assert [(a.role, a.detail) for a in back.personnes["I1"].evenements[0].associations] == \
        [(a.role, a.detail) for a in t.personnes["I1"].evenements[0].associations]


def test_roles_sans_type_standard_restent_personnalises():
    t = _arbre_roles({"HUSB": "", "WIFE": "", "SPOU": "", "OTHER": ""})
    ecrits = _roles_ecrits(tree_to_gramps(t, generated=False))
    assert [ecrits[f"I{i}"] for i in range(10, 14)] == [custom("EventRoleType", s)
                                                       for s in ("Époux", "Épouse", "Conjoint", "Autre")]


def _ancienne_base(roles: dict[str, str]) -> GrampsDb:
    """Base écrite avant #273 : rôles en libellés français ou Celebrant, avec l'attribut Genealogiste-Association."""
    t = _arbre_roles(roles)
    db = tree_to_gramps(t, generated=False)
    for p in db.all("Person").values():
        for r in p["event_ref_list"]:
            if tname(r["role"]) != "Primary":
                ancien = roles[next(a["value"] for a in r["attribute_list"] if tname(a["type"]) == A_ASSO).split(" | ")[1]]
                r["role"] = gtype("EventRoleType", ancien)
    return db


def test_anciens_libelles_toujours_lus_et_jamais_reecrits():
    anciens = {"FATH": "Père", "MOTH": "Mère", "CHIL": "Enfant", "FRIEND": "Ami", "NGHBR": "Voisin",
               "MULTIPLE": "Plusieurs", "OFFICIATOR": "Celebrant", "GODP": "Parrain"}
    db = _ancienne_base(anciens)
    t, _ = gramps_to_tree(db)
    assert [a.role for a in t.personnes["I1"].evenements[0].associations] == list(anciens)
    assert diff(db, tree_to_gramps(t, base=db, generated=False)) == []  # forme écrite d'origine conservée
    # sans l'attribut structuré (référence saisie dans l'interface) : les mêmes libellés donnent le même rôle
    for p in db.all("Person").values():
        for r in p["event_ref_list"]:
            r["attribute_list"] = []
    t2, _ = gramps_to_tree(db)
    assert [a.role for a in t2.personnes["I1"].evenements[0].associations] == \
        ["FATH", "MOTH", "CHIL", "FRIEND", "NGHBR", "MULTIPLE", "OFFICIATOR", "GODP"]
    assert diff(db, tree_to_gramps(t2, base=db, generated=False)) == []  # ni rôle ni attribut ajouté


def test_reference_saisie_dans_l_interface_gardee_telle_quelle():
    """Témoin saisi dans l'interface (rôle personnalisé « Témoin », sans attribut) : relu WITN, réécrit à
    l'identique (avant #273 : rôle remplacé par Witness et attribut Genealogiste-Association ajouté)."""
    db = base_francaise()
    t, _ = gramps_to_tree(db)
    out = tree_to_gramps(t, base=db, generated=False)
    assert out.get("Person", "p2") == db.get("Person", "p2")


# ============================================================================ détection et normalisation

def test_detection_par_classe_avec_nombre_d_objets():
    d = types_en_doublon(base_francaise())
    par = {(x["classe"], x["chaine"]): x for x in d["doublons"]}
    assert par[("EventType", "Recensement")] == {"classe": "EventType", "chaine": "Recensement", "standard": "Census",
                                                 "libelle": "Recensement", "objets": 2, "occurrences": 2}
    assert par[("EventRoleType", "Témoin")]["objets"] == 1
    assert par[("ChildRefType", "Adopté(e)")]["occurrences"] == 2 and par[("ChildRefType", "Adopté(e)")]["objets"] == 1
    assert ("PlaceType", "Paroisse") in par and ("RepositoryType", "Église") in par
    assert ("PlaceType", "Commune") not in par
    assert d["ambigus"] == [{"classe": "EventRoleType", "chaine": "Officiant", "candidats": ["Celebrant", "Officiator"],
                             "objets": 1, "occurrences": 1}]


def _sans_types(o):
    if isinstance(o, dict):
        if o.get("_class") in TYPES:
            return "TYPE"
        return {k: _sans_types(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_sans_types(x) for x in o]
    return o


def test_normalisation_seul_le_type_change_idempotente_et_ambigus_intacts():
    db = base_francaise()
    items, bilan = normaliser_types(db)
    assert all(i["type"] == "update" for i in items)
    for i in items:  # handles, gramps_id, valeurs, citations, positions inchangés : seul le type change
        assert i["new"]["handle"] == i["old"]["handle"] and i["new"].get("gramps_id") == i["old"].get("gramps_id")
        assert _sans_types(i["new"]) == _sans_types(i["old"])
    apres = apply_items(db, items)
    assert apres.get("Event", "e1")["type"] == gtype("EventType", "Baptism")
    assert apres.get("Place", "l1")["place_type"] == gtype("PlaceType", "Parish")
    assert apres.get("Place", "l2")["place_type"] == custom("PlaceType", "Commune")
    roles = [r["role"] for r in apres.get("Person", "p2")["event_ref_list"]]
    assert roles == [gtype("EventRoleType", "Witness"), custom("EventRoleType", "Officiant")]
    assert bilan["ambigus"][0]["chaine"] == "Officiant"
    assert bilan["par_classe"]["EventType"]["Recensement"] == {"standard": "Census", "objets": 2, "occurrences": 2}
    # le modèle ne voit aucune différence : la lecture comprenait déjà ces types
    assert write_gedcom(gramps_to_tree(apres)[0]) == write_gedcom(gramps_to_tree(db)[0])
    assert normaliser_types(apres)[0] == []  # deuxième exécution : rien à faire


def test_normalisation_limitee_aux_classes_demandees():
    items, bilan = normaliser_types(base_francaise(), ["PlaceType"])
    assert {i["handle"] for i in items} == {"l1"} and set(bilan["par_classe"]) == {"PlaceType"}
    with pytest.raises(ValueError, match="Classe de type inconnue"):
        normaliser_types(base_francaise(), ["Lieux"])


def test_detection_et_normalisation_sur_base_ecrite_par_genealogiste_avant_273():
    db = _ancienne_base({"FATH": "Père", "FRIEND": "Ami", "GODP": "Parrain"})
    d = types_en_doublon(db)
    assert {x["chaine"] for x in d["doublons"]} == {"Père", "Ami"}  # « Parrain » : précision libre, non reconnue
    items, _ = normaliser_types(db)
    assert len(items) == 2
    apres = apply_items(db, items)
    assert write_gedcom(gramps_to_tree(apres)[0]) == write_gedcom(gramps_to_tree(db)[0])


def test_structuration_des_lieux_et_types_francais():
    """gramps_structurer_lieux : un lieu à plat « Ville » (personnalisé) est traité comme City ; « Paroisse »
    garde son type ; aucune autre écriture de lieu ne change (#277)."""
    db = base_francaise()
    for h, titre, typ in (("l3", "Villefictive, Nord, France", "Ville"), ("l4", "Saint-Exemple, Nord, France",
                                                                         "Paroisse")):
        lieu = blank("Place", h, h.upper())
        lieu.update(title=titre, place_type=custom("PlaceType", typ))
        db.put(lieu)
    t, _ = gramps_to_tree(db)
    out = tree_to_gramps(t, base=db, generated=False, structure=True)
    assert out.get("Place", "l3")["place_type"] == gtype("PlaceType", "City")
    assert out.get("Place", "l4")["place_type"] == custom("PlaceType", "Paroisse")
    assert out.get("Place", "l4")["placeref_list"]


def test_generateur_verifier_compare_au_fichier(tmp_path):
    gen = _generateur()
    po = 'msgid ""\nmsgstr ""\n\nmsgid "Custom"\nmsgstr "Personnalisé"\n'
    src = _gramps_factice(tmp_path / "v", '[(CUSTOM, _("Custom"), "Custom")]', po)
    sortie = tmp_path / "ref.json"
    assert gen.main(["--source", f"5.2={src}", "--sortie", str(sortie)]) == 0
    assert gen.main(["--source", f"5.2={src}", "--sortie", str(sortie), "--verifier"]) == 0
    sortie.write_text("{}", encoding="utf-8")
    assert gen.main(["--source", f"5.2={src}", "--sortie", str(sortie), "--verifier"]) == 1


def test_famille_neuve_et_types_inchanges_de_la_famille():
    db = base_francaise()
    t, _ = gramps_to_tree(db)
    t.familles["F2"] = Family(id="F2", epoux="I2", uid="fam2")
    t.personnes["I2"].fams.append("F2")
    out = tree_to_gramps(t, base=db, generated=False)
    assert out.get("Family", "f1")["type"] == custom("FamilyRelType", "Mariés")


def test_referentiel_json_valide():
    data = json.loads((ROOT / "mcp" / "src" / "genealogiste_mcp" / "referentiels" / "types_gramps.json")
                      .read_text(encoding="utf-8"))
    assert set(data["classes"]) >= set(TYPES) | {"MarkerType"}


# ============================================================================ outil gramps_normaliser_types

@pytest.fixture
def gfake():
    from gramps_fake import FakeGrampsWeb

    with FakeGrampsWeb() as f:
        for objs in base_francaise().objects.values():
            for o in objs.values():
                f.put(copy.deepcopy(o))
        yield f


def _gapp(tmp_path):
    from gramps_fake import URL

    from genealogiste_mcp import server
    from genealogiste_mcp.config import Config

    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend="gramps",
                 gramps_url=URL, gramps_user="sosa", gramps_password="secret", gramps_ttl=0)
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    return a


def test_outil_normalisation_transaction_journalisee_annulable(tmp_path, gfake):
    from genealogiste_mcp import server

    a = _gapp(tmp_path)
    try:
        avant = copy.deepcopy(gfake.objects)
        ged_avant = write_gedcom(a.tree())
        n = len(gfake.transactions)
        p = server.gramps_normaliser_types()
        assert "jeton" in p and len(gfake.transactions) == n  # rien d'écrit
        assert p["bilan_types"]["EventType"]["Baptême"] == {"standard": "Baptism", "objets": 1, "occurrences": 1}
        assert p["ambigus"][0]["chaine"] == "Officiant" and "jamais tranchés" in p["ambigus_conseil"]
        assert p["transaction_gramps"]["bilan"]["Person"]["update"] >= 2
        assert not any(i["type"] != "update" for i in a.tokens.peek(p["jeton"])["items"])
        r = server.arbre_appliquer(p["jeton"])
        assert "erreur" not in r and len(gfake.transactions) == n + 1
        assert gfake.objects["Event"]["e1"]["type"] == gtype("EventType", "Baptism")
        assert gfake.objects["Place"]["l2"]["place_type"] == custom("PlaceType", "Commune")
        assert {c: set(o) for c, o in gfake.objects.items()} == {c: set(o) for c, o in avant.items()}
        assert all({**_sans_types(gfake.objects[c][h]), "change": 0} == {**_sans_types(o), "change": 0}
                   for c, objs in avant.items() for h, o in objs.items() if c != "Tag")
        assert write_gedcom(a.tree()) == ged_avant  # le modèle ne change pas
        log = [json.loads(x) for x in (a.config.data_dir / "gramps-transactions.jsonl").read_text().splitlines()]
        assert any(e.get("etat") == "terminee" and e["id"] == p["jeton"] for e in log)
        # deuxième exécution : rien à faire (les ambigus restent listés)
        p2 = server.gramps_normaliser_types()
        assert "jeton" not in p2 and p2["bilan_types"] == {} and p2["ambigus"] and "Rien à normaliser" in p2["note"]
        # annulation par le mécanisme existant : types personnalisés d'origine rétablis
        u = server.arbre_annuler_modification(r["transaction"])
        assert "erreur" not in server.arbre_appliquer(u["jeton"])
        assert gfake.objects["Event"]["e1"]["type"] == custom("EventType", "Baptême")
    finally:
        server.set_app(None)


def test_outil_normalisation_par_classe_et_erreurs(tmp_path, gfake):
    from genealogiste_mcp import server

    _gapp(tmp_path)
    try:
        p = server.gramps_normaliser_types(["PlaceType"])
        assert set(p["bilan_types"]) == {"PlaceType"} and p["transaction_gramps"]["bilan"] == {
            "Place": {"add": 0, "update": 1, "delete": 0}}
        assert "inconnue" in server.gramps_normaliser_types(["Lieux"])["erreur"]
    finally:
        server.set_app(None)


def test_outil_normalisation_hors_mode_gramps(app):
    from genealogiste_mcp import server

    assert "mode gramps" in server.gramps_normaliser_types()["erreur"]


def test_arbre_coherence_liste_les_doublons_en_mode_gramps(tmp_path, gfake):
    from genealogiste_mcp import server

    _gapp(tmp_path)
    try:
        res = server.arbre_coherence()
        doublons = {(x["classe"], x["chaine"]): x for x in res if x["code"] == "type_personnalise_doublon"}
        assert doublons[("EventType", "Recensement")]["objets"] == 2
        assert "Census" in doublons[("EventType", "Recensement")]["message"]
        assert [x["chaine"] for x in res if x["code"] == "type_personnalise_ambigu"] == ["Officiant"]
        assert not any(x["code"].startswith("type_personnalise") for x in server.arbre_coherence("I1"))
    finally:
        server.set_app(None)


# ============================================================================ import Gramps XML (backend fichier)

def test_import_gramps_xml_types_francais_en_types_gedcom(tmp_path):
    """Arbre Gramps à types personnalisés français importé dans le modèle GEDCOM 7 : bons types, rien compté comme
    perdu à cause d'un libellé (« Âge » repris comme Age) ; un type sans équivalent reste personnalisé."""
    from genealogiste_mcp.export.gramps_xml import db_to_xml
    from genealogiste_mcp.gramps import lecture_xml as lx

    db = base_francaise()
    autre = blank("Event", "e5", "E5")
    autre["type"] = custom("EventType", "Tirage au sort")
    db.put(autre)
    db.get("Person", "p3")["event_ref_list"].append(event_ref("e5", "Primary"))
    chemin = tmp_path / "francais.gramps"
    chemin.write_text(db_to_xml(db, "1.7.2"), encoding="utf-8")
    tree, info, _ = lx.importer(chemin, tmp_path / "donnees", "t")
    ged = write_gedcom(tree)
    assert "1 BAPM" in ged and "1 CENS" in ged and "2 TYPE Tirage au sort" in ged and "2 TYPE Blessing" in ged
    assert next(e for e in tree.personnes["I1"].evenements if e.type == "BAPM").age == "0"
    assert [a.role for a in next(e for e in tree.personnes["I1"].evenements if e.type == "BAPM").associations] == \
        ["WITN", "OTHER"]
    pertes = info["non_repris"]
    assert not any("Âge" in k or "[Age]" in k for k in pertes), pertes
    assert not any(k.startswith("Event.type") or "role" in k for k in pertes), pertes


def test_pertes_comptent_les_attributs_par_type_reconnu():
    from genealogiste_mcp.gramps import lecture_xml as lx

    db = base_francaise()
    apres = db.copy()
    ref = apres.get("Person", "p1")["event_ref_list"][0]
    ref["attribute_list"] = [attribute("Age", "0")]  # « Âge » réécrit en type standard : rien de perdu
    assert lx.pertes(db, apres) == {}
