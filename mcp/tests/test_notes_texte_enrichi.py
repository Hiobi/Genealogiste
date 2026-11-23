"""#279 : notes en texte enrichi (StyledText) et liens internes gramps://.

Fonctions pures (gramps/texte.py) : plages en points de code, Markdown simple <-> texte stylé, ajustement des
styles d'une note dont le texte change. Correspondance (gramps/mapping.py) : notes manuelles stylées réécrites à
l'identique, note modifiée qui garde handle, étiquettes, type et styles valides, liens internes des notes de
preuve sur option (GENEALOGISTE_GRAMPS_NOTES_LIENS). Données fictives uniquement.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
import time
import uuid

import pytest
from gramps_fake import FakeGrampsWeb

from genealogiste_mcp import server
from genealogiste_mcp.config import notes_liens
from genealogiste_mcp.gedcom.mapping import read_gedcom
from genealogiste_mcp.gramps.mapping import (
    AUTO_TAG,
    GrampsDb,
    gramps_to_tree,
    looks_generated,
    tree_to_gramps,
)
from genealogiste_mcp.gramps.texte import (
    ajuster,
    cible_interne,
    depuis_markdown,
    normaliser,
    plages_valides,
    tag,
    vers_markdown,
)
from genealogiste_mcp.gramps.types import tname
from genealogiste_mcp.tree.ops import OpError, apply_ops

DEATH = "11111111-1111-4111-8111-111111111113"
BIRTH = "11111111-1111-4111-8111-111111111111"
TOUS = ("bold", "italic", "underline", "fontface", "fontsize", "fontcolor", "highlight", "superscript", "link",
        "strikethrough", "subscript")


def st(texte: str, *tags: dict) -> dict:
    return {"_class": "StyledText", "string": texte, "tags": list(tags)}


def resume(styled: dict) -> list[tuple]:
    return sorted((tname(t["name"]), t["value"], tuple(map(tuple, t["ranges"]))) for t in styled["tags"])


# ============================================================================ plages, Markdown

def test_plages_en_points_de_code_accents_emojis_sauts_de_ligne():
    s = depuis_markdown("🟡 **é🟢**x\n⚠️ *ok*")
    assert s["string"] == "🟡 é🟢x\n⚠️ ok"
    assert resume(s) == [("bold", None, ((2, 4),)), ("italic", None, ((9, 11),))]
    # Gramps découpe la chaîne Python : la plage désigne exactement le texte stylé
    assert s["string"][2:4] == "é🟢" and s["string"][9:11] == "ok"
    assert len("⚠️") == 2 and len("🟡") == 1  # ⚠️ = U+26A0 + U+FE0F (2 points de code) ; 🟡 hors BMP = 1


CAS = [
    "**gras** et *italique* et _souligné en italique_",
    "texte brut sans rien",
    "[Jean MARTIN](gramps://Person/handle/abc123) né à [Rochefort](https://fr.wikipedia.org/wiki/Rochefort_(Charente-Maritime))",
    "***gras italique***",
    "*a **b** c*",
    "**a *b* c**",
    "[**lien gras**](https://exemple.org) suivi de *ital*",
    "échappés : \\*pas italique\\* et \\_ni ça\\_ et \\[pas\\] de lien",
    "snake_case_reste et 2*3 = six",
    "ligne 1 **gras**\nligne 2 *ital*\n\n- liste\n# titre\n| a | b |\n<b>html</b>",
    "émojis ⛔ 🟡 🟢 ✅ ⚠️ ❌ et **accentué éè**",
    "courriel [moi](mailto:moi@exemple.org)",
    "chemin C:\\dossier\\fichier et anti\\\\slash",
]


@pytest.mark.parametrize("md", CAS)
def test_aller_retour_markdown_stable(md):
    s1 = depuis_markdown(md)
    assert plages_valides(s1["string"], s1["tags"])
    md2, pertes = vers_markdown(s1)
    assert pertes == []
    s2 = depuis_markdown(md2)
    assert normaliser(s2) == normaliser(s1)
    md3, _ = vers_markdown(s2)
    assert md3 == md2  # point fixe après une normalisation


@pytest.mark.parametrize("md,texte", [
    ("**non fermé", "**non fermé"),
    ("*non fermé", "*non fermé"),
    ("_non fermé", "_non fermé"),
    ("[texte](sans fin", "[texte](sans fin"),
    ("[texte] (espace)", "[texte] (espace)"),
    ("* puce", "* puce"),
    ("** pas gras **", "** pas gras **"),
    ("[clic](javascript:alert(1))", "[clic](javascript:alert(1))"),
    ("[img](data:text/html;base64,AAAA)", "[img](data:text/html;base64,AAAA)"),
    ("[local](file:///etc/passwd)", "[local](file:///etc/passwd)"),
    ("[x](gramps://Inconnu/handle/a)", "[x](gramps://Inconnu/handle/a)"),
    ("[](https://vide.example)", "[](https://vide.example)"),
    ("**gras\nsur deux lignes**", "**gras\nsur deux lignes**"),
    ("<script>alert(1)</script>", "<script>alert(1)</script>"),
])
def test_cas_hostiles_restent_du_texte(md, texte):
    s = depuis_markdown(md)
    assert s["string"] == texte and s["tags"] == []


def test_schema_refuse_mais_emphase_interne_gardee():
    s = depuis_markdown("[**x**](javascript:void(0))")
    assert s["string"] == "[x](javascript:void(0))"
    assert all(tname(t["name"]) != "link" for t in s["tags"])


def test_url_avec_parentheses_et_imbrication():
    s = depuis_markdown("voir [la page](https://exemple.org/a_(b)_c) et *[lien en italique](https://x.example)*")
    liens = {t["value"]: t["ranges"] for t in s["tags"] if tname(t["name"]) == "link"}
    assert liens["https://exemple.org/a_(b)_c"] == [[5, 12]]
    assert s["string"][slice(*liens["https://x.example"][0])] == "lien en italique"


def test_entree_hostile_rapide():
    for md in ("*a " * 20000, "**" * 20000, "[" * 20000 + "](https://x)", "*_" * 20000, "[a](" * 10000):
        t0 = time.monotonic()
        s = depuis_markdown(md)
        assert time.monotonic() - t0 < 5
        assert plages_valides(s["string"], s["tags"])


def test_vers_markdown_signale_ce_qui_n_est_pas_representable():
    texte = "abcdefghijklmnopqrstuvwxyz"
    tags = [tag(n, [[i, i + 2]], v) for i, (n, v) in enumerate(
        [("underline", None), ("fontface", "Serif"), ("fontsize", 14), ("fontcolor", "#ff0000"),
         ("highlight", "#ffff00"), ("superscript", None), ("strikethrough", None), ("subscript", None),
         ("link", "ftp://exemple.org/x")], start=0)] + [tag("bold", [[20, 22]])]
    md, pertes = vers_markdown(st(texte, *tags))
    assert md.replace("**", "") == texte and "**uv**" in md
    assert len(pertes) == 9
    for mot in ("underline", "fontface Serif", "fontsize 14", "fontcolor #ff0000", "highlight", "superscript",
                "strikethrough", "subscript", "link ftp://"):
        assert any(p.startswith(mot) for p in pertes), mot


def test_vers_markdown_jamais_de_perte_silencieuse_fuzz():
    """Textes stylés aléatoires (gras, italique, liens qui se chevauchent, émojis, marqueurs littéraux) : le texte
    relu est toujours identique, et la mise en forme aussi, sinon la différence est signalée."""
    rnd = random.Random(279)
    alphabet = "ab *_[]()\\\né🟡⚠️"
    signales = 0
    for _ in range(400):
        texte = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 18)))
        tags = []
        for nom in ("bold", "italic", "link"):
            for _ in range(rnd.randint(0, 2)):
                a = rnd.randint(0, len(texte) - 1)
                tags.append(tag(nom, [[a, rnd.randint(a + 1, len(texte))]],
                                rnd.choice(["https://exemple.org/a_(b)", "gramps://Person/handle/h1"])
                                if nom == "link" else None))
        s = st(texte, *tags)
        md, pertes = vers_markdown(s)
        relu = depuis_markdown(md)
        assert relu["string"] == texte, (s, md)
        if normaliser(relu) != normaliser(s):
            assert pertes, (s, md)
            signales += 1
    assert signales < 40  # repli rare (emphases adjacentes ambiguës)


# ============================================================================ texte modifié : styles ajustés

def test_ajuster_prefixe_suffixe_milieu_et_hors_bornes():
    ancien = "Gras au début, milieu modifié, fin 🟢 soulignée"
    tags = [tag("bold", [[0, 4]]), tag("italic", [[15, 21]]), tag("underline", [[37, 45]]),
            tag("fontcolor", [[40, 99]], "#ff0000")]
    nouveau = ancien.replace("milieu modifié", "centre réécrit et allongé")
    garde, retires = ajuster(ancien, tags, nouveau)
    assert plages_valides(nouveau, garde)
    d = {tname(t["name"]): t["ranges"] for t in garde}
    assert nouveau[slice(*d["bold"][0])] == "Gras"
    assert nouveau[slice(*d["underline"][0])] == "soulignée"[:8]
    assert "italic" not in d and "fontcolor" not in d
    assert len(retires) == 2 and any("italic" in r and "milieu" in r for r in retires)
    assert ajuster(ancien, tags, ancien) == (tags, [])


# ============================================================================ notes manuelles : préservation

def _note(h: str, gid: str, texte: str, typ: int, tags: list[dict], tag_list=None, private=False) -> dict:
    return {"_class": "Note", "handle": h, "gramps_id": gid, "change": 1700000000, "private": private,
            "tag_list": tag_list or [], "format": 0, "type": {"_class": "NoteType", "value": typ, "string": ""},
            "text": st(texte, *tags)}


RICHE = "Gras italique souligné Serif 14 rouge surligné x² H₂O barré lien interne"


def _r(mot: str) -> list[list[int]]:
    i = RICHE.index(mot)
    return [[i, i + len(mot)]]


def _tags_riches(cible_handle: str) -> list[dict]:
    return [tag("bold", _r("Gras")), tag("italic", _r("italique")), tag("underline", _r("souligné")),
            tag("fontface", _r("Serif"), "Serif"), tag("fontsize", _r("14"), 14),
            tag("fontcolor", _r("rouge"), "#ffff00000000"), tag("highlight", _r("surligné"), "#ffff00"),
            tag("superscript", _r("²")), tag("subscript", _r("₂")), tag("strikethrough", _r("barré")),
            tag("link", _r("lien"), "https://exemple.org"),
            tag("link", _r("interne"), f"gramps://Person/handle/{cible_handle}")]


@pytest.fixture
def base_stylee(tree):
    """Base Gramps écrite par Genealogiste + notes manuelles stylées « comme l'interface » : note de personne
    (en ligne), note partagée (General, référencée par la famille), note d'événement, note de source, note de
    citation (Transcript)."""
    db = tree_to_gramps(tree)
    jean = next(o for o in db.all("Person").values() if o["gramps_id"] == "I1")
    user = {"_class": "Tag", "handle": "tagperso", "name": "À relire", "color": "#000000000000", "priority": 9,
            "change": 0}
    db.put(user)
    tags = _tags_riches(jean["handle"])
    notes = {"np": (4, "Person"), "ng": (1, "Family"), "ne": (10, "Event"), "ns": (12, "Source"),
             "nc": (3, "Citation")}
    for i, (h, (typ, _)) in enumerate(notes.items()):
        db.put(_note(h, f"N09{i}", RICHE, typ, copy.deepcopy(tags), ["tagperso"]))
    jean["note_list"].append("np")
    fam = next(o for o in db.all("Family").values() if o["gramps_id"] == "F1")
    fam["note_list"].append("ng")
    death = db.get("Event", jean["event_ref_list"][2]["ref"])
    death["note_list"].append("ne")
    src = next(o for o in db.all("Source").values() if o["gramps_id"] == "S1")
    src["note_list"].append("ns")
    cit = db.get("Citation", db.get("Event", jean["event_ref_list"][0]["ref"])["citation_list"][0])
    cit["note_list"].append("nc")
    return db


@pytest.mark.parametrize("op", [
    {"op": "modifier_personne", "id": "I1", "sexe": "F"},
    {"op": "ajouter_citation", "cible": {"type": "evenement", "uid": DEATH},
     "citation": {"source": "S1", "page": "Décès 1885", "consultation": "image"}},
    {"op": "modifier_source", "id": "S1", "champs": {"auteur": "Mairie"}},
    {"op": "etiqueter", "cible": {"type": "famille", "id": "F1"}, "tags": ["Blog"]},
])
def test_notes_manuelles_stylees_reecrites_a_l_identique(base_stylee, op):
    t = gramps_to_tree(base_stylee)[0]
    ctx = apply_ops(t, [op], exiger_source=False)
    out = tree_to_gramps(ctx.tree, base=base_stylee)
    for h in ("np", "ng", "ne", "ns", "nc"):
        assert out.get("Note", h) == base_stylee.get("Note", h), h
        assert {tname(x["name"]) for x in out.get("Note", h)["text"]["tags"]} == set(TOUS)


def test_note_en_ligne_modifiee_garde_handle_etiquettes_type_et_styles_valides(base_stylee):
    t = gramps_to_tree(base_stylee)[0]
    jean = t.personnes["I1"]
    i = jean.notes.index(RICHE)
    jean.notes[i] = RICHE.replace("rouge", "vermillon")
    avis: list[str] = []
    out = tree_to_gramps(t, base=base_stylee, avis=avis)
    n, b = out.get("Note", "np"), base_stylee.get("Note", "np")
    assert "np" in next(o for o in out.all("Person").values() if o["gramps_id"] == "I1")["note_list"]
    assert (n["tag_list"], n["type"], n["private"], n["gramps_id"]) == (b["tag_list"], b["type"], b["private"],
                                                                        b["gramps_id"])
    assert n["text"]["string"] == RICHE.replace("rouge", "vermillon")
    assert plages_valides(n["text"]["string"], n["text"]["tags"])
    noms = {tname(x["name"]): x for x in n["text"]["tags"]}
    assert "fontcolor" not in noms  # plage modifiée : retirée…
    assert any("fontcolor" in a and "rouge" in a and "N090" in a for a in avis)  # … et signalée
    assert n["text"]["string"][slice(*noms["bold"]["ranges"][0])] == "Gras"  # préfixe inchangé
    assert n["text"]["string"][slice(*noms["strikethrough"]["ranges"][0])] == "barré"  # suffixe décalé
    lien = next(x for x in n["text"]["tags"] if str(x["value"]).startswith("gramps://"))
    assert n["text"]["string"][slice(*lien["ranges"][0])] == "interne"


def test_note_partagee_jamais_prise_pour_une_note_en_ligne_modifiee(base_stylee):
    jean_h = next(o for o in base_stylee.all("Person").values() if o["gramps_id"] == "I1")["handle"]
    base_stylee.get("Person", jean_h)["note_list"].insert(0, "ng")  # note partagée (General) avant la note en ligne
    t = gramps_to_tree(base_stylee)[0]
    jean = t.personnes["I1"]
    assert jean.notes == [RICHE, "@N091@"]
    jean.notes = ["Texte entièrement nouveau", "@N091@"]
    out = tree_to_gramps(t, base=base_stylee)
    assert out.get("Note", "ng") == base_stylee.get("Note", "ng")
    assert out.get("Note", "np")["text"]["string"] == "Texte entièrement nouveau"
    assert out.get("Person", jean_h)["note_list"] == base_stylee.get("Person", jean_h)["note_list"]


def test_note_partagee_modifiee_styles_ajustes_et_signales(base_stylee):
    t = gramps_to_tree(base_stylee)[0]
    t.notes["N091"] = "Préfixe ajouté. " + RICHE
    avis: list[str] = []
    out = tree_to_gramps(t, base=base_stylee, avis=avis)
    n = out.get("Note", "ng")
    assert n["tag_list"] == ["tagperso"] and plages_valides(n["text"]["string"], n["text"]["tags"])
    assert len(n["text"]["tags"]) == len(base_stylee.get("Note", "ng")["text"]["tags"])  # tout le suffixe décalé
    assert avis == []


def test_champ_unique_plusieurs_notes_tete_et_queue_gardees(base_stylee):
    db = base_stylee
    death_h = next(o for o in db.all("Person").values() if o["gramps_id"] == "I1")["event_ref_list"][2]["ref"]
    db.put(_note("ne2", "N099", "Deuxième note *manuelle*", 10, [tag("italic", [[0, 8]])]))
    db.get("Event", death_h)["note_list"].append("ne2")
    t = gramps_to_tree(db)[0]
    ev = next(e for e in t.personnes["I1"].evenements if e.uid == DEATH)
    ev.note = ev.note + "\n\nTroisième note ajoutée"
    out = tree_to_gramps(t, base=db)
    nl = out.get("Event", death_h)["note_list"]
    assert out.get("Note", "ne") == db.get("Note", "ne") and out.get("Note", "ne2") == db.get("Note", "ne2")
    nouvelle = [h for h in nl if h not in db.get("Event", death_h)["note_list"]]
    assert [out.get("Note", h)["text"]["string"] for h in nouvelle] == ["Troisième note ajoutée"]
    # texte de la deuxième modifié : handle gardé
    t = gramps_to_tree(db)[0]
    ev = next(e for e in t.personnes["I1"].evenements if e.uid == DEATH)
    ev.note = ev.note.replace("Deuxième", "Seconde")
    out = tree_to_gramps(t, base=db)
    assert out.get("Note", "ne2")["text"]["string"].startswith("Seconde")
    assert out.get("Note", "ne") == db.get("Note", "ne")


# ============================================================================ format_texte : Markdown

def test_format_texte_defaut_brut_et_markdown_explicite(tree):
    op = {"op": "ajouter_evenement", "cible": "I2",
          "evenement": {"type": "OCCU", "valeur": "couturière", "note": "**Acte** vu, voir *registre* 2*3",
                        "non_source": True, "motif": "test"}}
    ctx = apply_ops(tree, [op])
    assert any(e.note.startswith("**Acte** vu, voir *registre* 2*3") for e in ctx.tree.personnes["I2"].evenements)
    assert ctx.tree.styles == {}
    md = dict(op, format_texte="markdown")
    md["evenement"] = dict(op["evenement"], note="**Acte** vu, voir [la fiche](gramps://Person/gramps_id/I1)")
    ctx = apply_ops(tree, [md])
    assert any(e.note.startswith("Acte vu, voir la fiche") for e in ctx.tree.personnes["I2"].evenements)
    out = tree_to_gramps(ctx.tree)
    n = next(n for n in out.all("Note").values() if n["text"]["string"].startswith("Acte vu, voir la fiche"))
    assert resume(n["text"]) == [("bold", None, ((0, 4),)), ("link", "gramps://Person/gramps_id/I1", ((14, 22),))]
    with pytest.raises(OpError, match="format_texte"):
        apply_ops(tree, [dict(op, format_texte="html")])


def test_format_texte_markdown_citations_sources_personnes(tree):
    ops = [{"op": "ajouter_source", "titre": "Registre", "note": "Source *numérisée*", "ref": "s",
            "format_texte": "markdown"},
           {"op": "ajouter_citation", "cible": {"type": "evenement", "uid": DEATH}, "format_texte": "markdown",
            "citation": {"source": "$s", "page": "f° 3", "texte": "Le **quatre** janvier", "note": "_lu_"}},
           {"op": "modifier_personne", "id": "I1", "notes_ajout": ["Voir [AD](https://archives.example)"],
            "format_texte": "markdown"}]
    ctx = apply_ops(tree, ops)
    out = tree_to_gramps(ctx.tree)
    textes = {n["text"]["string"]: resume(n["text"]) for n in out.all("Note").values()}
    assert textes["Source numérisée"] == [("italic", None, ((7, 16),))]
    assert textes["Le quatre janvier"] == [("bold", None, ((3, 9),))]
    assert textes["lu"] == [("italic", None, ((0, 2),))]
    assert textes["Voir AD"] == [("link", "https://archives.example", ((5, 7),))]


def test_lien_interne_markdown_vers_objet_absent_retire_et_signale(tree):
    op = {"op": "modifier_personne", "id": "I1", "format_texte": "markdown",
          "notes_ajout": ["Voir [lui](gramps://Person/handle/absent) et [elle](gramps://Person/gramps_id/I2)"]}
    ctx = apply_ops(tree, [op])
    avis: list[str] = []
    out = tree_to_gramps(ctx.tree, avis=avis)
    n = next(n for n in out.all("Note").values() if n["text"]["string"] == "Voir lui et elle")
    assert [t["value"] for t in n["text"]["tags"]] == ["gramps://Person/gramps_id/I2"]
    assert any("absent" in a for a in avis)


def test_backend_fichier_signale_la_mise_en_forme_non_conservee(app):
    p = server.arbre_proposer([{"op": "ajouter_personne", "noms": [{"prenoms": "Anne", "nom": "TEST"}],
                                "notes": ["**gras**"], "format_texte": "markdown"}], "Essai", "Essai.")
    assert any("format_texte markdown" in w for w in p["avertissements"])
    server.arbre_appliquer(p["jeton"])
    assert "NOTE gras" in app.store.text() and "**" not in app.store.text()


# ============================================================================ non-régression : option désactivée

def _empreintes(fixtures, monkeypatch) -> dict:
    rnd = random.Random(279)
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=rnd.getrandbits(128), version=4))

    def dig(db):
        return hashlib.sha256(json.dumps(db.objects, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]

    out = {}
    for nom in ("famille.ged", "legacy551.ged", "geneweb7_gwb2ged.ged"):
        out[nom] = dig(tree_to_gramps(read_gedcom((fixtures / nom).read_text(encoding="utf-8"))[0]))
    riche = GrampsDb()
    for o in json.loads((fixtures / "gramps-objets-riches.json").read_text(encoding="utf-8")):
        riche.put(o)
    out["riche"] = dig(tree_to_gramps(gramps_to_tree(riche)[0], base=riche))
    t = read_gedcom((fixtures / "famille.ged").read_text(encoding="utf-8"))[0]
    base = tree_to_gramps(t)
    ctx = apply_ops(copy.deepcopy(t), [{"op": "modifier_personne", "id": "I1", "notes_ajout": ["Note *ajoutée*"]}],
                    False)
    out["incremental"] = dig(tree_to_gramps(ctx.tree, base=base))
    return out


def test_option_desactivee_sortie_identique_a_main(fixtures, monkeypatch):
    """Empreintes relevées sur origin/main (a52885c, avant #279) avec le même tirage d'uid : l'option désactivée
    (défaut) ne change aucun objet, octet pour octet. À mettre à jour seulement si une évolution volontaire de la
    correspondance change ces sorties (#315 : « riche » réécrit par-dessus lui-même garde désormais citations de
    références, personref, attributs cités et événement retenu ; les autres empreintes sont inchangées ;
    #283 : « legacy551 » a un lieu sans pays ni département, « Saint-Jean-d'Angély » : sa piste d'AD porte
    désormais « — si le lieu est en France » dans la fiche de preuve générée)."""
    assert _empreintes(fixtures, monkeypatch) == {
        "famille.ged": "8372ea8833f3c9c9", "legacy551.ged": "1238c46ec91d4c86",
        "geneweb7_gwb2ged.ged": "865c4c3928ab0b3b", "riche": "67e04182a6743bca", "incremental": "acafe90ba6787dd1"}


# ============================================================================ liens internes (option activée)

def _non_vu(tree):
    ops = [{"op": "ajouter_citation", "cible": {"type": "evenement", "uid": DEATH},
            "citation": {"source": "S1", "page": "Décès 1885, acte n° 3", "consultation": "non_vu"}}]
    return apply_ops(tree, ops).tree


def _liens(n: dict) -> list[tuple[str, str]]:
    s = n["text"]["string"]
    return [(s[a:b], t["value"]) for t in n["text"]["tags"] if cible_interne(t.get("value"))
            for a, b in t["ranges"]]


def test_option_activee_memes_textes_et_liens_valides(tree):
    t = _non_vu(tree)
    sans, avec = tree_to_gramps(t), tree_to_gramps(t, liens=True)
    assert set(sans.all("Note")) == set(avec.all("Note"))
    n_liens = 0
    for h, n in avec.all("Note").items():
        a = sans.get("Note", h)
        assert n["text"]["string"] == a["text"]["string"]  # texte visible strictement identique
        assert n["text"]["tags"][:len(a["text"]["tags"])] == a["text"]["tags"]  # seuls des liens ajoutés
        for t2 in n["text"]["tags"][len(a["text"]["tags"]):]:
            assert tname(t2["name"]) == "link"
            cls, prop, val = cible_interne(t2["value"])
            assert prop == "handle" and avec.get(cls, val), t2  # jamais vers un objet absent
            assert plages_valides(n["text"]["string"], [t2])
            n_liens += 1
        assert looks_generated(n["text"]["string"]) == looks_generated(a["text"]["string"])
    assert n_liens > 10
    ids = {(c, o["handle"]): o.get("gramps_id") for c in ("Person", "Family", "Source", "Event", "Citation")
           for o in avec.all(c).values()}
    jean = next(o for o in avec.all("Person").values() if o["gramps_id"] == "I1")
    fiche = next(avec.get("Note", h) for h in jean["note_list"]
                 if avec.get("Note", h)["text"]["string"].startswith("Fiche de preuve"))
    liens = _liens(fiche)
    assert ("I1", f"gramps://Person/handle/{jean['handle']}") in liens
    evs = {e["handle"]: e for e in avec.all("Event").values()}
    assert any(txt.startswith("Naissance") and cible_interne(v)[2] in evs for txt, v in liens)
    assert any(txt == "Filiation" and cible_interne(v)[0] == "Family" for txt, v in liens)
    death = evs[jean["event_ref_list"][2]["ref"]]
    note_dc = next(avec.get("Note", h) for h in death["note_list"]
                   if avec.get("Note", h)["text"]["string"].startswith(("⛔", "🟡", "🟢", "✅", "⚠", "❌")))
    lk = dict(_liens(note_dc))
    assert ids[("Source", cible_interne(lk["Registres d'état civil de Rochefort"])[2])] == "S1"
    cit_h = cible_interne(lk["Décès 1885, acte n° 3"])[2]
    assert cit_h in death["citation_list"] and avec.get("Citation", cit_h)["page"] == "Décès 1885, acte n° 3"
    f1 = next(o for o in avec.all("Family").values() if o["gramps_id"] == "F1")
    fil = next(avec.get("Note", h) for h in f1["note_list"])
    assert [x for x, _ in _liens(fil)] == ["Pierre MARTIN", "Louise MARTIN"]


def test_lien_de_source_externe_inchange(tree):
    avec = tree_to_gramps(tree, liens=True)
    n = next(n for n in avec.all("Note").values() if n["text"]["string"].startswith("Lien : "))
    assert n["text"]["tags"] == tree_to_gramps(tree).get("Note", n["handle"])["text"]["tags"]
    assert n["text"]["tags"][0]["value"] == "https://gw.geneanet.org/exemple"


def test_activation_sans_recalcul_ne_change_aucune_note_inchangee(tree):
    base = tree_to_gramps(tree)
    out = tree_to_gramps(tree, base=base, liens=True)
    assert out.all("Note") == base.all("Note")
    rec = tree_to_gramps(tree, base=base, liens=True, recalcul=True)
    changees = [h for h in base.all("Note") if rec.get("Note", h) != base.get("Note", h)]
    assert changees and all(_liens(rec.get("Note", h)) for h in changees)
    # idempotence : deuxième recalcul, rien ; écriture ordinaire : forme entretenue
    assert tree_to_gramps(tree, base=rec, liens=True, recalcul=True).all("Note") == rec.all("Note")
    assert tree_to_gramps(tree, base=rec, liens=True).all("Note") == rec.all("Note")
    # désactivation : rien sans recalcul (liens gardés), recalcul : liens retirés, retour exact à la forme initiale
    assert tree_to_gramps(tree, base=rec).all("Note") == rec.all("Note")
    assert tree_to_gramps(tree, base=rec, recalcul=True).all("Note") == base.all("Note")


# ============================================================================ backend gramps (faux serveur)

@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


def _app(tmp_path, fake, tree, liens: bool, seed: bool = True, notes_auto: str = "true"):
    from test_gramps_backend import make_app
    from test_gramps_backend import seed as seeder
    if seed:
        seeder(fake, tree)
    a = make_app(tmp_path, notes_auto=notes_auto)
    a.backend.notes_liens = liens
    return a


CIT = [{"op": "ajouter_citation", "cible": {"type": "evenement", "uid": DEATH},
        "citation": {"source": "S1", "page": "Décès 1885, acte n° 3", "type_source": "originale",
                     "information": "primaire", "consultation": "non_vu"}}]


def _avec_liens(fake) -> set[str]:
    return {h for h, n in fake.objects["Note"].items() if _liens(n)}


def _sans_change(notes: dict) -> dict:
    return {h: {k: v for k, v in n.items() if k != "change"} for h, n in notes.items()}


def test_recalcul_propose_applique_annule_idempotent(tmp_path, fake, tree):
    _app(tmp_path, fake, tree, liens=True)
    try:
        avant = copy.deepcopy(fake.objects["Note"])
        p = server.arbre_proposer(CIT, "Décès", "Acte cité.")
        server.arbre_appliquer(p["jeton"])
        # écriture ordinaire : une note générée dont le texte ne change pas garde sa forme (sans liens)…
        inchangees = [h for h, n in avant.items() if fake.objects["Note"].get(h, {}).get("text", {}).get("string")
                      == n["text"]["string"]]
        assert inchangees and all(fake.objects["Note"][h] == avant[h] for h in inchangees)
        # … une note réécrite (texte changé) prend la nouvelle forme
        assert _avec_liens(fake) and not _avec_liens(fake) & set(inchangees)
        avant_recalcul = copy.deepcopy(fake.objects["Note"])
        r = server.gramps_recalculer_notes()
        tg = r["transaction_gramps"]
        assert set(tg["bilan"]) == {"Note"} and tg["dont_notes_de_preuve_seules"] == sum(
            sum(v.values()) for v in tg["bilan"].values())
        assert tg["liens_internes"] == {"notes_avec_liens_ajoutes": tg["bilan"]["Note"]["update"]}
        res = server.arbre_appliquer(r["jeton"])
        assert "transaction" in res
        assert "ne modifie rien" in server.gramps_recalculer_notes()["erreur"]  # idempotence
        for n in fake.objects["Note"].values():
            for t in n["text"]["tags"]:
                if cible_interne(t.get("value")):
                    cls, _, h = cible_interne(t["value"])
                    assert h in fake.objects[cls]  # jamais vers un objet absent
        # annulation (journalisée, deux temps) : retour exact à l'état d'avant le recalcul
        u = server.arbre_annuler_modification(res["transaction"])
        server.arbre_appliquer(u["jeton"])
        assert _sans_change(fake.objects["Note"]) == _sans_change(avant_recalcul)
    finally:
        server.set_app(None)


def test_desactivation_passe_par_le_recalcul(tmp_path, fake, tree):
    a = _app(tmp_path, fake, tree, liens=True)
    try:
        server.arbre_appliquer(server.gramps_recalculer_notes()["jeton"])
        lies = copy.deepcopy({h: fake.objects["Note"][h] for h in _avec_liens(fake)})
        assert lies
        a.backend.notes_liens = False
        server.arbre_appliquer(server.arbre_proposer(CIT, "Décès", "Acte cité.")["jeton"])
        # écriture ordinaire, option désactivée : une note inchangée garde ses liens (jamais de retrait silencieux)
        inchangees = [h for h, n in lies.items() if fake.objects["Note"][h]["text"]["string"] == n["text"]["string"]]
        assert inchangees and all(fake.objects["Note"][h] == lies[h] for h in inchangees)
        r = server.gramps_recalculer_notes()
        assert r["transaction_gramps"]["liens_internes"] == {
            "notes_avec_liens_retires": r["transaction_gramps"]["bilan"]["Note"]["update"]}
        server.arbre_appliquer(r["jeton"])
        assert _avec_liens(fake) == set()
        assert "ne modifie rien" in server.gramps_recalculer_notes()["erreur"]
    finally:
        server.set_app(None)


def test_avertissement_massif_mentionne_les_liens(tmp_path, fake, tree):
    from genealogiste_mcp.gramps import backend as gb
    _app(tmp_path, fake, tree, liens=True)
    old = gb.MASSIVE_OBJECTS
    gb.MASSIVE_OBJECTS = 3
    try:
        r = server.gramps_recalculer_notes()
        assert any("GENEALOGISTE_GRAMPS_NOTES_LIENS" in w for w in r["avertissements"])
    finally:
        gb.MASSIVE_OBJECTS = old
        server.set_app(None)


def test_adoption_des_notes_sans_etiquette_avec_liens(tmp_path, fake, tree):
    from test_gramps_backend import seed
    seed(fake, tree)
    auto = next(h for h, t in fake.objects["Tag"].items() if t["name"] == AUTO_TAG)
    del fake.objects["Tag"][auto]
    for n in fake.objects["Note"].values():
        n["tag_list"] = [t for t in n["tag_list"] if t != auto]
    nb = len(fake.objects["Note"])
    _app(tmp_path, fake, tree, liens=True, seed=False)
    try:
        p = server.gramps_recalculer_notes()
        assert p["transaction_gramps"]["bilan"].get("Note", {}).get("add", 0) == 0
        server.arbre_appliquer(p["jeton"])
    finally:
        server.set_app(None)
    assert len(fake.objects["Note"]) == nb and _avec_liens(fake)


def test_note_manuelle_modifiee_signalee_dans_la_proposition(tmp_path, fake, tree):
    """Note d'événement saisie dans l'interface (stylée, étiquetée) puis modifiée par modifier_evenement : même
    handle, étiquettes et type ; style dont la plage est touchée retiré ET annoncé dans les avertissements."""
    _app(tmp_path, fake, tree, liens=False)
    try:
        fake.put({"_class": "Tag", "handle": "tagperso", "name": "À relire", "color": "#000000000000",
                  "priority": 9, "change": 0})
        fake.put(_note("nman", "N0500", "Texte rouge à corriger", 10,
                       [tag("fontcolor", [[6, 11]], "#ff0000"), tag("bold", [[0, 5]])], ["tagperso"]))
        death = next(e for e in fake.objects["Event"].values()
                     if any(x["value"] == DEATH for x in e["attribute_list"]))
        fake.ui_edit("Event", death["gramps_id"], lambda o: o["note_list"].append("nman"))
        p = server.arbre_proposer([{"op": "modifier_evenement", "uid": DEATH,
                                    "champs": {"note": "Texte bleu à corriger"}}], "Note", "Correction.")
        assert any("N0500" in w and "fontcolor" in w and "rouge" in w for w in p["avertissements"])
        server.arbre_appliquer(p["jeton"])
        n = fake.objects["Note"]["nman"]
        assert n["text"]["string"] == "Texte bleu à corriger" and n["tag_list"] == ["tagperso"]
        assert tname(n["type"]) == "Event Note" and resume(n["text"]) == [("bold", None, ((0, 5),))]
        assert "nman" in fake.objects["Event"][death["handle"]]["note_list"]
    finally:
        server.set_app(None)


# ============================================================================ configuration, exports

def test_configuration_notes_liens():
    assert notes_liens(None) is False and notes_liens("") is False
    assert notes_liens("true") is True and notes_liens("Oui") is True and notes_liens("0") is False
    for v in ("modifies", "parfois"):
        with pytest.raises(ValueError, match="GENEALOGISTE_GRAMPS_NOTES_LIENS"):
            notes_liens(v)


def test_variable_d_environnement_lue(monkeypatch, tmp_path):
    from genealogiste_mcp.config import load_config
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path / "d"))
    assert load_config().gramps_notes_liens is False
    monkeypatch.setenv("GENEALOGISTE_GRAMPS_NOTES_LIENS", "true")
    assert load_config().gramps_notes_liens is True


def test_option_transmise_au_backend(tmp_path, fake):
    from gramps_fake import URL

    from genealogiste_mcp.config import Config
    for v in (False, True):
        cfg = Config(data_dir=tmp_path / f"d{v}", cache_path=tmp_path / "c.sqlite", backend="gramps", gramps_url=URL,
                     gramps_user="sosa", gramps_password="secret", gramps_notes_liens=v)
        assert server.App(cfg, sleeper=lambda s: None).backend.notes_liens is v


def test_diagnostic_affiche_l_option(app):
    app.config.gramps_notes_liens = True
    conf = next(c for c in server.diagnostic(reseau=False)["controles"] if c["controle"] == "configuration")
    assert conf["valeurs"]["gramps_notes_liens"] is True and conf["valeurs"]["gramps_notes_auto"] == "true"


def test_exports_publics_sans_lien_interne_ni_residu(app, tree):
    """Les exports partent du modèle (sans mise en forme ni lien interne) et de la projection de publication : aucun
    lien gramps:// ni nom de vivant masqué (garde-fou privacy.residues de arbre_exporter)."""
    app.store.write(tree)
    for fmt in ("gramps", "gedcom7", "gpkg"):
        r = server.arbre_exporter(format=fmt)
        assert "erreur" not in r, r
        contenu = open(r["fichier"], "rb").read()
        if fmt == "gpkg":
            import gzip
            import io
            import tarfile
            with tarfile.open(fileobj=io.BytesIO(contenu)) as tf:
                contenu = gzip.decompress(tf.extractfile("data.gramps").read())
        assert b"gramps://" not in contenu and b"Lucas" not in contenu, fmt


def test_import_xml_signale_la_mise_en_forme_non_reprise(base_stylee):
    from genealogiste_mcp.gramps.lecture_xml import pertes
    relu = gramps_to_tree(base_stylee)[0]
    p = pertes(base_stylee, tree_to_gramps(relu, generated=False))
    assert p.get("Note.text.tags[]", 0) >= 5 * 12, p  # onze styles (douze tags) des cinq notes manuelles
