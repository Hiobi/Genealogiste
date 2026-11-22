"""#315 : un objet Gramps lu puis réécrit sans modification reste identique, y compris ce que Genealogiste ne
modélise pas (citations et attributs des références, ordre des références, événement retenu, chemin de fichier).

Fixtures synthétiques minimales (objets Gramps fictifs), une par cause relevée sur l'arbre d'exemple de Gramps
(`example.gramps`, non versionné : vérifié par le banc Desktop, ``scripts/verifier_gramps_desktop.py``), puis
propriété sur toutes les bases de fixtures du dépôt : base -> modèle -> Gramps par-dessus elle-même = diff vide.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genealogiste_mcp.gramps.lecture_xml import lire_fichier
from genealogiste_mcp.gramps.mapping import (
    A_ASSO,
    A_FICHIER,
    GrampsDb,
    _attr_value,
    diff,
    gramps_to_tree,
    tree_to_gramps,
)
from genealogiste_mcp.gramps.types import attribute, blank, event_ref, gtype
from genealogiste_mcp.models import Association

FIX = Path(__file__).parent / "fixtures"


def _source() -> list[dict]:
    s = blank("Source", "src1", "S0001")
    s["title"] = "Registre fictif"
    return [s]


def _citation(h: str, gid: str, page: str = "f° 1") -> dict:
    c = blank("Citation", h, gid)
    c.update(source_handle="src1", page=page)
    return c


def _personne(h: str, gid: str, prenom: str) -> dict:
    p = blank("Person", h, gid)
    p["primary_name"]["first_name"] = prenom
    p["gender"] = 1
    return p


def _evenement(h: str, gid: str, typ: str) -> dict:
    e = blank("Event", h, gid)
    e["type"] = gtype("EventType", typ)
    return e


def _neutre(db: GrampsDb) -> list[dict]:
    """Éléments de transaction d'une réécriture sans opération (notes générées désactivées, puis activées
    pour aucun objet : cas d'une proposition qui ne touche pas ces objets)."""
    tree, _ = gramps_to_tree(db)
    return diff(db, tree_to_gramps(tree, base=db, generated=False)) + \
        diff(db, tree_to_gramps(tree, base=db, generated=True, only=set()))


def _resume(items: list[dict]) -> list[str]:
    out = []
    for i in items:
        o, n = i.get("old") or {}, i.get("new") or {}
        champs = sorted(k for k in set(o) | set(n) if k != "change" and o.get(k) != n.get(k))
        out.append(f"{i['type']} {i['_class']} {(n or o).get('gramps_id')} {champs if i['type'] == 'update' else ''}")
    return out


# ---------------------------------------------------------------------------- causes, une fixture chacune

def base_media_interface() -> GrampsDb:
    """Médias ajoutés dans l'interface (chemin Gramps, sans attribut Genealogiste-Fichier), reçu ou non."""
    m1 = blank("Media", "med1", "O0001")
    m1.update(path="photos/portrait.jpg", mime="image/jpeg", checksum="0123abcd", desc="Portrait")
    m2 = blank("Media", "med2", "O0002")
    m2.update(path="cartes/plan.kml", mime="application/vnd.google-earth.kml+xml", desc="Plan")
    return GrampsDb.from_objects([m1, m2])


def base_personref_interface() -> GrampsDb:
    """Parrain saisi dans l'interface : personref seule (sans attribut Genealogiste-Association), citée ; et une
    association sans relation (``rel`` vide)."""
    a, b, c = _personne("per1", "I0001", "Filleul"), _personne("per2", "I0002", "Parrain"), \
        _personne("per3", "I0003", "Voisin")
    a["person_ref_list"] = [
        {"_class": "PersonRef", "private": False, "citation_list": ["cit1"], "note_list": [], "ref": "per2",
         "rel": "Godfather"},
        {"_class": "PersonRef", "private": False, "citation_list": [], "note_list": [], "ref": "per3", "rel": ""}]
    return GrampsDb.from_objects([a, b, c, _citation("cit1", "C0001"), *_source()])


def base_ref_citee() -> GrampsDb:
    """Citations portées par la RÉFÉRENCE d'événement (rôle Primary d'une personne, Family d'une famille)."""
    p = _personne("per1", "I0001", "Jean")
    p["event_ref_list"] = [event_ref("evt1", "Primary", citations=["cit1"])]
    p["birth_ref_index"] = 0
    f = blank("Family", "fam1", "F0001")
    f["father_handle"] = "per1"
    f["event_ref_list"] = [event_ref("evt2", "Family", citations=["cit2"])]
    p["family_list"] = ["fam1"]
    return GrampsDb.from_objects([p, f, _evenement("evt1", "E0001", "Birth"), _evenement("evt2", "E0002", "Marriage"),
                                  _citation("cit1", "C0001"), _citation("cit2", "C0002", "f° 2"), *_source()])


def base_age_familial() -> GrampsDb:
    """Attribut Age (cité) sur la référence d'un événement familial."""
    f = blank("Family", "fam1", "F0001")
    age = attribute("Age", "23")
    age["citation_list"] = ["cit1"]
    f["event_ref_list"] = [event_ref("evt1", "Family", [age])]
    return GrampsDb.from_objects([f, _evenement("evt1", "E0001", "Marriage"), _citation("cit1", "C0001"),
                                  *_source()])


def base_ordre_refs() -> GrampsDb:
    """Référence d'événement d'un rôle personnalisé (non lue comme intervenant) entre deux références Primary."""
    p = _personne("per1", "I0001", "Jean")
    p["event_ref_list"] = [event_ref("evt1", "Primary"), event_ref("evt2", "Rôle perso"),
                           event_ref("evt3", "Primary")]
    p["birth_ref_index"], p["death_ref_index"] = 0, 2
    return GrampsDb.from_objects([p, _evenement("evt1", "E0001", "Birth"), _evenement("evt2", "E0002", "Census"),
                                  _evenement("evt3", "E0003", "Death")])


def base_evenement_retenu() -> GrampsDb:
    """Deux naissances : la seconde est l'événement retenu (``birth_ref_index``) ; décès retenu : une inhumation."""
    p = _personne("per1", "I0001", "Jean")
    p["event_ref_list"] = [event_ref("evt1", "Primary"), event_ref("evt2", "Primary"), event_ref("evt3", "Primary")]
    p["birth_ref_index"], p["death_ref_index"] = 1, 2
    return GrampsDb.from_objects([p, _evenement("evt1", "E0001", "Birth"), _evenement("evt2", "E0002", "Birth"),
                                  _evenement("evt3", "E0003", "Burial")])


def base_attribut_cite() -> GrampsDb:
    """Attribut lu par Genealogiste mais cité, privé ou annoté dans Gramps : Cause d'un décès, chemin de fichier."""
    p = _personne("per1", "I0001", "Jean")
    p["event_ref_list"] = [event_ref("evt1", "Primary")]
    p["death_ref_index"] = 0
    e = _evenement("evt1", "E0001", "Death")
    cause = attribute("Cause", "Fièvre fictive", ["cit1"])
    cause["private"] = True
    e["attribute_list"] = [cause]
    m = blank("Media", "med1", "O0001")
    m.update(path="medias/acte.jpg", mime="image/jpeg", checksum="0123abcd")
    m["attribute_list"] = [attribute("Genealogiste-Fichier", "medias/acte.jpg", ["cit1"])]
    return GrampsDb.from_objects([p, e, m, _citation("cit1", "C0001"), *_source()])


def base_marqueurs_en_double() -> GrampsDb:
    """#311 : fusion native de Gramps : marqueurs à valeur unique côte à côte (Vivant N et Y, deux UID, deux UID noms,
    deux statuts, deux chemins de fichier), ancienne forme comprise."""
    p = _personne("per1", "I0001", "Jean")
    p["attribute_list"] = [attribute("Genealogiste-UID noms", "aaaaaaaa-0000-4000-8000-000000000001"),
                           attribute("Genealogiste-UID", "aaaaaaaa-0000-4000-8000-000000000002"),
                           attribute("Genealogiste-Vivant", "N"),
                           attribute("Genealogiste-UID noms", "aaaaaaaa-0000-4000-8000-000000000003"),
                           attribute("Genealogiste-UID", "aaaaaaaa-0000-4000-8000-000000000004"),
                           attribute("Sosa-Vivant", "Y"), attribute("Merged Gramps ID", "I0002")]
    p["event_ref_list"] = [event_ref("evt1", "Primary")]
    p["death_ref_index"] = 0
    e = _evenement("evt1", "E0001", "Death")
    e["attribute_list"] = [attribute("Genealogiste-Statut", "contradictoire | fictif"),
                           attribute("Genealogiste-Statut", "refute | fictif")]
    m = blank("Media", "med1", "O0001")
    m.update(path="medias/acte.jpg", mime="image/jpeg", checksum="0123abcd")
    m["attribute_list"] = [attribute("Genealogiste-Fichier", "medias/a.jpg"),
                           attribute("Genealogiste-Fichier", "medias/b.jpg")]
    return GrampsDb.from_objects([p, e, m])


CAS = {"media_interface": base_media_interface, "attribut_cite": base_attribut_cite, "personref_interface": base_personref_interface,
       "ref_citee": base_ref_citee, "age_familial": base_age_familial, "ordre_refs": base_ordre_refs,
       "evenement_retenu": base_evenement_retenu, "marqueurs_en_double": base_marqueurs_en_double}


@pytest.mark.parametrize("nom", sorted(CAS))
def test_reecriture_sans_operation_neutre(nom):
    db = CAS[nom]()
    assert _resume(_neutre(db)) == []


def test_media_interface_lu_avec_son_chemin_sans_attribut_pose():
    db = base_media_interface()
    tree, _ = gramps_to_tree(db)
    assert tree.medias["O0001"].fichier == "photos/portrait.jpg"
    assert tree.medias["O0002"].fichier == "cartes/plan.kml"


def test_media_interface_modifie_ou_cree_par_le_plugin_garde_l_attribut():
    """L'attribut reste posé quand le chemin du modèle diffère de celui de Gramps (fichier déplacé, média créé par
    le plugin : le chemin local n'est connu que de Genealogiste)."""
    db = base_media_interface()
    tree, _ = gramps_to_tree(db)
    tree.medias["O0001"].fichier = "medias/actes/portrait.jpg"
    new = tree_to_gramps(tree, base=db, generated=False)
    m1 = new.get("Media", "med1")
    assert _attr_value(m1, A_FICHIER) == "medias/actes/portrait.jpg"
    assert m1["path"] == "photos/portrait.jpg" and m1["checksum"] == "0123abcd"  # chemin du serveur conservé
    assert not _attr_value(new.get("Media", "med2"), A_FICHIER)
    neuf = tree_to_gramps(tree, generated=False)  # média créé par le plugin : attribut posé
    assert all(_attr_value(m, A_FICHIER) for m in neuf.all("Media").values())


def test_personref_interface_modifiee_reprend_la_citation():
    """Association de la personne modifiée : attribut structuré écrit (forme du plugin), mais la citation de la
    personref saisie dans l'interface est conservée (même handle, même gramps_id)."""
    db = base_personref_interface()
    tree, _ = gramps_to_tree(db)
    tree.personnes["I0001"].associations.append(Association(personne="", nom="Marraine Fictive", role="GODP"))
    items = diff(db, tree_to_gramps(tree, base=db, generated=False))
    assert [(i["type"], i["_class"]) for i in items] == [("update", "Person")]
    p = items[0]["new"]
    assert next(r for r in p["person_ref_list"] if r["ref"] == "per2")["citation_list"] == ["cit1"]
    assert any(a["value"].endswith("| I0002") for a in p["attribute_list"] if a["type"]["string"] == A_ASSO)


def test_age_familial_modifie_est_ecrit():
    db = base_age_familial()
    tree, _ = gramps_to_tree(db)
    assert tree.familles["F0001"].evenements[0].age == "23"
    tree.familles["F0001"].evenements[0].age = "24"
    f = tree_to_gramps(tree, base=db, generated=False).get("Family", "fam1")
    assert [a["value"] for a in f["event_ref_list"][0]["attribute_list"]] == ["24"]


# ---------------------------------------------------------------------------- propriété sur toutes les fixtures

def _bases_fixtures() -> dict[str, GrampsDb]:
    out = {f"synthetique:{k}": v() for k, v in CAS.items()}
    out["gramps-objets-riches.json"] = GrampsDb.from_objects(
        json.loads((FIX / "gramps-objets-riches.json").read_text(encoding="utf-8")))
    for chemin in sorted((FIX / "gramps-desktop").glob("gramps-*/famille.*")):
        out[f"{chemin.parent.name}/{chemin.name}"] = lire_fichier(chemin).db
    return out


@pytest.mark.parametrize("nom", sorted(_bases_fixtures()))
def test_propriete_toute_base_de_fixture_reecrite_par_dessus_elle_meme_sans_diff(nom):
    assert _resume(_neutre(_bases_fixtures()[nom])) == []


# ---------------------------------------------------------------------------- proposition sur un autre objet

def _renomme(o, handles: set[str], suffixe: str):
    """Copie d'un objet Gramps dont les handles de ``handles`` (valeurs de références) sont suffixés."""
    if isinstance(o, dict):
        return {k: (f"{v}-{suffixe}" if isinstance(v, str) and v in handles and k in (
            "handle", "ref", "source_handle", "father_handle", "mother_handle") else _renomme(v, handles, suffixe))
                for k, v in o.items()}
    if isinstance(o, list):
        return [f"{x}-{suffixe}" if isinstance(x, str) and x in handles else _renomme(x, handles, suffixe) for x in o]
    return o


def _base_commune() -> list[dict]:
    """Tous les cas dans une même base (handles et identifiants suffixés, source commune) + une personne sans
    rapport."""
    objets = []
    for n, (nom, fab) in enumerate(sorted(CAS.items())):
        db = fab()
        propres = [o for cls in ("Person", "Family", "Event", "Citation", "Media") for o in db.all(cls).values()]
        handles = {o["handle"] for o in propres}
        for o in propres:
            o = _renomme(o, handles, nom)
            o["gramps_id"] = f"{o['gramps_id']}{n}"
            objets.append(o)
    return [*objets, *_source(), _personne("autre", "I9999", "Sans rapport")]


@pytest.mark.parametrize("notes_auto", ["true", "modifies", "false"])
def test_proposition_sur_un_autre_objet_ne_touche_que_lui(tmp_path, notes_auto):
    """Effet réel par arbre_proposer (faux Gramps Web) : une opération sur une personne sans rapport ne fait
    entrer dans la transaction aucun objet des cas ci-dessus (avant #315 : médias, parrain, citations recréées ou
    retirées, Age et ordre des références perdus), hors notes de preuve générées."""
    from gramps_fake import URL, FakeGrampsWeb

    from genealogiste_mcp import server
    from genealogiste_mcp.config import Config
    from genealogiste_mcp.gramps.mapping import etiquettes_gerees, proof_only

    with FakeGrampsWeb() as fake:
        for o in _base_commune():
            fake.put(o)
        cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend="gramps",
                     gramps_url=URL, gramps_user="sosa", gramps_password="secret", gramps_ttl=0,
                     gramps_notes_auto=notes_auto)
        a = server.App(cfg, sleeper=lambda s: None)
        server.set_app(a)
        try:
            p = server.arbre_proposer([{"op": "modifier_personne", "id": "I9999", "sexe": "F"}], "Sexe",
                                      "Correction fictive.")
            items = a.backend.tokens.peek(p["jeton"])["items"]
            db = a.backend.db
        finally:
            server.set_app(None)
    gerees = etiquettes_gerees(db, items)
    reels = [i for i in items if not proof_only(i, gerees)]
    if notes_auto == "true":
        # recalcul de preuve de toute la base (défaut) : l'événement retenu suit la naissance / le décès le mieux
        # prouvé, comportement de preuve antérieur à #315 et laissé tel quel (seul écart toléré, sur ce seul cas)
        retenu = [i for i in reels if i["_class"] == "Person" and i["new"]["gramps_id"].startswith("I0001")
                  and {k for k in i["new"] if i["new"][k] != i["old"][k]} <= {"birth_ref_index", "death_ref_index",
                                                                               "note_list", "change"}]
        assert [i["new"]["handle"] for i in retenu] == ["per1-evenement_retenu"]
        reels = [i for i in reels if i not in retenu]
    assert {(i["_class"], (i.get("new") or i.get("old") or {}).get("gramps_id")) for i in reels} == \
        {("Person", "I9999")}, _resume(reels)

