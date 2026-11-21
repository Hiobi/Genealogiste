"""Billets du blog de Gramps Web (#261) : source étiquetée Blog, corps en première note, privé par défaut, garde
des vivants, synchronisation, notes de recherche, preuve. Données fictives uniquement (famille.ged : I9 Lucas
MARTIN, né en 1990, présumé vivant)."""

from __future__ import annotations

import copy
import shutil

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import URL, make_app, seed

from genealogiste_mcp import evidence, server
from genealogiste_mcp.config import Config
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom
from genealogiste_mcp.gramps.mapping import AUTO_TAG, diff, gramps_to_tree, tree_to_gramps
from genealogiste_mcp.gramps.types import tname
from genealogiste_mcp.models import Citation, Media
from genealogiste_mcp.notes import Notes, NotesError, touched
from genealogiste_mcp.tree.ops import OpError, apply_ops

CORPS = "Jean MARTIN, tisserand à Rochefort, épouse Marie DUPONT en 1850."
NAISSANCE_I1 = "11111111-1111-4111-8111-111111111111"


def _billet(**kw) -> dict:
    return {"op": "ajouter_billet", "ref": "b", "titre": "Les Martin de Rochefort", "auteur": "Équipe fictive",
            "texte": CORPS, **kw}


def _medias(tree):
    tree.medias["O1"] = Media(id="O1", fichier="medias/blog/portrait.jpg", format="image/jpeg", titre="Portrait")
    tree.medias["O2"] = Media(id="O2", fichier="medias/blog/maison.jpg", format="image/jpeg", titre="Maison")
    return tree


# ---------------------------------------------------------------------------- opérations

def test_ajouter_billet_compose_source_note_etiquette_medias_prive(tree):
    ctx = apply_ops(_medias(tree), [_billet(medias=["O2", "O1"], tags=["Famille"])], backend="gramps")
    sid = ctx.refs["b"]
    s = ctx.tree.sources[sid]
    assert (s.titre, s.auteur, s.note) == ("Les Martin de Rochefort", "Équipe fictive", CORPS)
    assert s.tags == ["Blog", "Famille"] and s.prive is True and s.medias == ["O2", "O1"]
    assert any(f"Billet {sid} : Les Martin de Rochefort, par Équipe fictive ; aperçu O2, galerie O2, O1" == x
               for x in ctx.summary)
    assert any(x.startswith(f"Billet {sid} « Les Martin de Rochefort » : privé") for x in ctx.summary)
    assert ctx.warnings == []
    text = write_gedcom(ctx.tree)
    back = read_gedcom(text)[0].sources[sid]  # aller-retour GEDCOM : étiquettes, RESN, note, ordre des médias
    assert back.to_dict() == s.to_dict()
    assert "1 _RESN PRIVACY" in text.split(f"0 @{sid}@ SOUR")[1].split("\n0 ")[0]


def test_ajouter_billet_public_sur_demande_et_markdown(tree):
    ctx = apply_ops(tree, [_billet(prive=False, texte="**Acte** lu", format_texte="markdown")], backend="gramps")
    s = ctx.tree.sources[ctx.refs["b"]]
    assert s.prive is False and s.note == "Acte lu" and ctx.tree.styles["Acte lu"]
    assert any("PUBLIC" in x and "Invité" in x for x in ctx.summary)
    assert any("public" in w and "Invité" in w for w in ctx.warnings)


@pytest.mark.parametrize(("op", "message"), [
    ({"titre": ""}, "titre requis"), ({"texte": " "}, "texte requis"), ({"prive": "non"}, "prive"),
    ({"medias": ["O7"]}, "média inconnu"), ({"medias": "O1"}, "medias"), ({"note": "x"}, "champs inconnus"),
    ({"tags": ["Genealogiste:auto"]}, "gérée par Genealogiste"),
])
def test_ajouter_billet_parametres_refuses(tree, op, message):
    with pytest.raises(OpError, match=message):
        apply_ops(tree, [_billet(**op)], backend="gramps")


def test_ajouter_billet_refuse_en_backend_fichier(tree):
    with pytest.raises(OpError, match="backend fichier"):
        apply_ops(tree, [_billet()], backend="fichier")


def test_ajouter_source_etiquetee_blog_privee_par_defaut(tree):
    ctx = apply_ops(tree, [{"op": "ajouter_source", "ref": "s", "titre": "Billet", "note": "Texte", "tags": ["Blog"]},
                           {"op": "ajouter_source", "ref": "p", "titre": "Public", "note": "Texte", "tags": ["Blog"],
                            "prive": False},
                           {"op": "ajouter_source", "ref": "n", "titre": "Ordinaire", "tags": ["ToDo"]}])
    src = ctx.tree.sources
    assert src[ctx.refs["s"]].prive is True and src[ctx.refs["p"]].prive is False
    assert src[ctx.refs["n"]].prive is False  # étiquette autre que Blog : rien ne change


# ---------------------------------------------------------------------------- vivants

def test_billet_public_nommant_un_vivant_refuse_prive_averti(tree):
    texte = "Souvenirs de Lucas Martin, avec Jean MARTIN."
    with pytest.raises(OpError, match=r"Billet S\d+ public refusé.*I9 Lucas MARTIN.*présumé\(e\) vivant"):
        apply_ops(tree, [_billet(texte=texte, prive=False)], backend="gramps")
    ctx = apply_ops(tree, [_billet(texte=texte)], backend="gramps")
    assert any("I9 Lucas MARTIN" in w and "ne doit pas devenir public" in w for w in ctx.warnings)
    # titre, auteur et titres des médias comptent aussi ; ordre inverse et accents ignorés
    tree.medias["O1"] = Media(id="O1", fichier="x.jpg", titre="MARTIN, Lucas en 2001")
    for op in (_billet(titre="Pour Martin Lucas", prive=False), _billet(auteur="lucas martin", prive=False),
               _billet(medias=["O1"], prive=False)):
        with pytest.raises(OpError, match="I9"):
            apply_ops(tree, [op], backend="gramps")


def test_billet_public_lien_interne_vers_un_vivant_refuse(tree):
    op = _billet(texte="Voir [sa fiche](gramps://Person/gramps_id/I9)", format_texte="markdown", prive=False)
    with pytest.raises(OpError, match="lien interne vers I9"):
        apply_ops(tree, [op], backend="gramps")


def test_billet_rendu_public_ou_etiquete_controle(tree):
    tree.sources["S3"].note = "Recensement : Lucas Martin y figure."
    with pytest.raises(OpError, match="I9"):  # source publique qui devient billet
        apply_ops(tree, [{"op": "etiqueter", "cible": {"type": "source", "id": "S3"}, "tags": ["Blog"]}])
    ctx = apply_ops(tree, [_billet()], backend="gramps")
    sid = ctx.refs["b"]
    ctx2 = apply_ops(ctx.tree, [{"op": "modifier_source", "id": sid, "champs": {"prive": False}}])
    assert any(f"Billet {sid} rendu public" in w for w in ctx2.warnings)
    with pytest.raises(OpError, match="I9"):
        apply_ops(ctx.tree, [{"op": "modifier_source", "id": sid,
                              "champs": {"prive": False, "note": CORPS + " Lucas Martin."}}])
    # billet inchangé : aucun contrôle ni ligne de résumé
    ctx3 = apply_ops(ctx.tree, [{"op": "marquer_vivant", "id": "I7", "vivant": "N"}])
    assert not any("Billet" in x for x in ctx3.summary)


# ---------------------------------------------------------------------------- preuve, notes de recherche

def test_billet_cite_ne_compte_jamais_comme_preuve(tree):
    ctx = apply_ops(tree, [_billet()], backend="gramps")
    t = ctx.tree
    sid = ctx.refs["b"]
    c = Citation(source=sid, page="billet", type_source="originale", information="primaire", preuve="directe",
                 consultation="original")
    assert evidence.citation_weight(c, t) == 0.0
    r = evidence.assess_citations([c], t)
    assert r["statut"] == "non_source" and r["sources_independantes"] == 0
    assert r["billets_cites"] and sid in r["billets_cites"][0]
    s1 = Citation(source="S1", page="acte 1", type_source="originale", information="primaire", preuve="directe",
                  consultation="original")
    assert evidence.assess_citations([s1, c], t)["sources_independantes"] == 1


def test_notes_generer_ignore_les_billets(tmp_path, tree):
    ctx = apply_ops(tree, [_billet()], backend="gramps")
    sid = ctx.refs["b"]
    notes = Notes(tmp_path / "vault")
    r = notes.generate(ctx.tree)
    assert not list((tmp_path / "vault" / "sources").glob(f"{sid} - *.md"))
    assert list((tmp_path / "vault" / "sources").glob("S1 - *.md")) and r["ecrites"]
    assert f"[[{sid} - " not in (tmp_path / "vault" / "index.md").read_text(encoding="utf-8")
    assert sid not in touched(tree, ctx.tree)
    with pytest.raises(NotesError, match="billet"):
        notes.generate(ctx.tree, sid)
    assert notes.generate(ctx.tree, [sid, "I1"])["erreurs"]


# ---------------------------------------------------------------------------- correspondance Gramps

def _ecrire(tree, ops, base=None, only=None):
    ctx = apply_ops(tree, ops, backend="gramps")
    avis: list[str] = []
    db = tree_to_gramps(ctx.tree, base=base, only=only, avis=avis)
    return ctx, db, avis


def _src(db, sid):
    return next(o for o in db.all("Source").values() if o["gramps_id"] == sid)


def _tag(db, nom):
    return next(h for h, t in db.all("Tag").items() if t["name"] == nom)


def test_gramps_corps_premiere_note_privee_et_notes_generees_apres(tree):
    ctx, db, _ = _ecrire(_medias(tree), [_billet(medias=["O2", "O1"]),
                                         {"op": "modifier_source", "id": "$b", "champs": {"url": "https://ex.org/b"}}])
    src = _src(db, ctx.refs["b"])
    corps, lien = (db.get("Note", h) for h in src["note_list"])
    assert src["private"] is True and src["tag_list"] == [_tag(db, "Blog")]
    assert corps["text"]["string"] == CORPS and corps["private"] is True and _tag(db, "Blog") in corps["tag_list"]
    assert lien["text"]["string"] == "Lien : https://ex.org/b" and lien["private"] is True
    assert _tag(db, AUTO_TAG) in lien["tag_list"]
    media = {db.get("Media", m["ref"])["gramps_id"] for m in src["media_list"][:1]}
    assert media == {"O2"}  # premier média = aperçu
    # relu : le corps privé d'un billet privé reste dans le modèle ; réécriture sans changement : rien
    back, _ = gramps_to_tree(db)
    assert back.sources[ctx.refs["b"]].note == CORPS and back.sources[ctx.refs["b"]].prive
    assert diff(db, tree_to_gramps(back, base=db)) == []
    assert diff(db, tree_to_gramps(back, base=db, only=set())) == []  # mode « modifies »


def test_gramps_billet_de_l_interface_corps_apres_une_note_generee(tree):
    """Billet saisi dans l'interface (note sans type, étiquetée Blog) dont une note générée précède le corps :
    intact tant qu'il ne change pas ; modifié par Genealogiste, corps remis en tête (avertissement)."""
    db = tree_to_gramps(tree)
    blog = {"_class": "Tag", "handle": "tagblog", "name": "Blog", "color": "#000000000000", "priority": 0}
    db.put(blog)
    auto = next(h for h, t in db.all("Tag").items() if t["name"] == AUTO_TAG)
    db.put({"_class": "Note", "handle": "nlien", "gramps_id": "N900", "private": False, "type": "Source Note",
            "text": {"_class": "StyledText", "string": "Lien : https://ex.org/ui", "tags": []},
            "tag_list": [auto], "change": 1})
    db.put({"_class": "Note", "handle": "ncorps", "gramps_id": "N901", "private": True, "type": "General",
            "text": {"_class": "StyledText", "string": "Corps saisi dans l'interface", "tags": []},
            "tag_list": ["tagblog"], "change": 1})
    db.put({"_class": "Source", "handle": "sui", "gramps_id": "S90", "title": "Billet UI", "author": "Moi",
            "pubinfo": "", "abbrev": "", "private": True, "note_list": ["nlien", "ncorps"], "media_list": [],
            "reporef_list": [], "attribute_list": [{"_class": "SrcAttribute", "private": False, "type": "URL",
                                                     "value": "https://ex.org/ui"}],
            "tag_list": ["tagblog"], "change": 1})
    t, _ = gramps_to_tree(db)
    assert t.sources["S90"].note == "Corps saisi dans l'interface" and t.sources["S90"].tags == ["Blog"]
    assert not [i for i in diff(db, tree_to_gramps(t, base=db)) if i["handle"] in ("sui", "ncorps")]  # intact
    ctx, new, avis = _ecrire(t, [{"op": "modifier_source", "id": "S90", "champs": {"titre": "Billet UI (revu)"}}],
                             base=db)
    assert _src(new, "S90")["note_list"] == ["ncorps", "nlien"]
    assert new.get("Note", "ncorps") == db.get("Note", "ncorps")  # corps intact (handle, type, étiquette)
    assert any("Billet S90 : corps remis en première note" in a for a in avis)


def test_gramps_corps_d_un_billet_prive_modifie_en_place_puis_retire(tree):
    ctx, db, _ = _ecrire(tree, [_billet()])
    sid = ctx.refs["b"]
    h = _src(db, sid)["note_list"][0]
    t, _ = gramps_to_tree(db)
    _, db2, _ = _ecrire(t, [{"op": "modifier_source", "id": sid, "champs": {"note": "Nouveau corps"}}], base=db)
    assert _src(db2, sid)["note_list"] == [h]  # même note, réécrite, toujours privée
    assert db2.get("Note", h)["text"]["string"] == "Nouveau corps" and db2.get("Note", h)["private"] is True
    # rendu public : corps public ; repassé privé : corps privé
    t2, _ = gramps_to_tree(db2)
    _, db3, _ = _ecrire(t2, [{"op": "modifier_source", "id": sid, "champs": {"prive": False}}], base=db2)
    assert _src(db3, sid)["private"] is False and db3.get("Note", h)["private"] is False
    t3, _ = gramps_to_tree(db3)
    _, db4, _ = _ecrire(t3, [{"op": "modifier_source", "id": sid, "champs": {"prive": True}}], base=db3)
    assert db4.get("Note", h)["private"] is True
    # corps vidé : note retirée
    t4, _ = gramps_to_tree(db4)
    _, db5, _ = _ecrire(t4, [{"op": "modifier_source", "id": sid, "champs": {"note": ""}}], base=db4)
    assert _src(db5, sid)["note_list"] == [] and db5.get("Note", h) is None


def test_gramps_note_privee_d_un_billet_public_reste_hors_modele(tree):
    ctx, db, _ = _ecrire(tree, [_billet(prive=False)])
    sid = ctx.refs["b"]
    src = _src(db, sid)
    db.put({"_class": "Note", "handle": "nsecret", "gramps_id": "N950", "private": True, "type": "General",
            "text": {"_class": "StyledText", "string": "Brouillon privé", "tags": []}, "tag_list": [], "change": 1})
    src["note_list"] = ["nsecret", *src["note_list"]]
    t, _ = gramps_to_tree(db)
    assert t.sources[sid].note == CORPS  # le brouillon privé n'entre pas dans le modèle (billet public)
    _, db2, _ = _ecrire(t, [{"op": "modifier_source", "id": sid, "champs": {"titre": "Revu"}}], base=db)
    nl = _src(db2, sid)["note_list"]
    assert nl[0] != "nsecret" and "nsecret" in nl and db2.get("Note", "nsecret")["private"] is True
    assert db2.get("Note", nl[0])["text"]["string"] == CORPS and db2.get("Note", nl[0])["private"] is False


# ---------------------------------------------------------------------------- serveur (faux Gramps Web)

@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


def _bapp(tmp_path, fake, tree, notes_auto="true", mirror=False, vault=False):
    seed(fake, tree)
    if not vault:
        a = make_app(tmp_path, mirror=mirror, notes_auto=notes_auto)
    else:
        cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend="gramps",
                     gramps_url=URL, gramps_user="sosa", gramps_password="secret", gramps_ttl=0,
                     gramps_notes_auto=notes_auto, git_mirror=mirror, notes_dir=tmp_path / "vault")
        a = server.App(cfg, sleeper=lambda s: None)
        server.set_app(a)
    (a.config.media_dir / "blog").mkdir(parents=True)
    (a.config.media_dir / "blog" / "portrait.jpg").write_bytes(b"\xff\xd8\xff\xe0portrait-fictif\xff\xd9")
    return a


OPS = [{"op": "ajouter_media", "ref": "img", "fichier": "medias/blog/portrait.jpg", "format": "image/jpeg",
        "titre": "Portrait fictif"},
       {"op": "ajouter_billet", "ref": "b", "titre": "Les Martin de Rochefort", "auteur": "Équipe fictive",
        "texte": "**Jean** et *Marie*, [registre](https://archives.exemple.org/r)", "format_texte": "markdown",
        "medias": ["$img"]}]


@pytest.mark.parametrize("notes_auto", ["true", "modifies"])
def test_serveur_billet_de_bout_en_bout_puis_annulation(tmp_path, fake, tree, notes_auto):
    _bapp(tmp_path, fake, tree, notes_auto)
    before = copy.deepcopy(fake.objects)
    p = server.arbre_proposer(OPS, "Billet", "Récit sourcé (test).")
    assert "erreur" not in p, p
    sid = p["references_creees"]["b"]
    assert "+1 _ETIQUETTE Blog" in p["diff"] and "+1 _RESN PRIVACY" in p["diff"]
    assert any("privé" in x for x in p["resume"]) and f"@@ étiquettes {sid} : +Blog @@" in p["diff"]
    r = server.arbre_appliquer(p["jeton"])
    src = fake.find("Source", sid)
    notes = [fake.objects["Note"][h] for h in src["note_list"]]
    assert src["private"] is True and notes[0]["private"] is True
    assert notes[0]["text"]["string"] == "Jean et Marie, registre"
    assert {tname(t["name"]) for t in notes[0]["text"]["tags"]} \
        == {"bold", "italic", "link"}
    assert [fake.objects["Media"][m["ref"]]["gramps_id"] for m in src["media_list"]] == [p["references_creees"]["img"]]
    assert fake.objects["Tag"][src["tag_list"][0]]["name"] == "Blog"
    # lecture : billets listés par la recherche par étiquette
    lus = server.arbre_recherche(etiquette="Blog", objet="source")
    assert [(x["id"], x["billet"], x["prive"]) for x in lus] == [(sid, True, True)]
    assert server.arbre_recherche(texte="martin de roche", objet="source")[0]["id"] == sid
    assert server.arbre_recherche(etiquette="Blog") == []  # personnes : inchangé
    assert "erreur" in server.arbre_recherche(objet="lieu")[0]
    # autre proposition, puis recalcul des notes : le billet ne bouge pas
    corps = copy.deepcopy(fake.find("Source", sid))
    p2 = server.arbre_proposer([{"op": "marquer_vivant", "id": "I7", "vivant": "N"}], "Vivant", "Décédé (test).")
    server.arbre_appliquer(p2["jeton"])
    assert fake.find("Source", sid) == corps  # objet intact (change compris : jamais réécrit)
    rec = server.gramps_recalculer_notes()
    if "jeton" in rec:
        server.arbre_appliquer(rec["jeton"])
    assert fake.find("Source", sid) == corps
    # annulation
    u = server.arbre_annuler_modification(r["transaction"])

    assert "erreur" not in server.arbre_appliquer(u["jeton"])
    assert not any(o.get("gramps_id") == sid for o in fake.objects["Source"].values())
    assert set(fake.objects["Media"]) == set(before["Media"])
    assert set(fake.objects["Note"]) == set(before["Note"])


def test_serveur_billet_public_vivant_refuse(tmp_path, fake, tree):
    _bapp(tmp_path, fake, tree)
    r = server.arbre_proposer([_billet(texte="Lucas MARTIN, mon cousin.", prive=False)], "Billet", "Essai (test).")
    assert "erreur" in r and "I9" in r["erreur"] and not fake.transactions
    r = server.arbre_proposer([_billet(texte="Lucas MARTIN, mon cousin.")], "Billet", "Essai (test).")
    assert any("I9" in w for w in r["avertissements"])


def test_serveur_backend_fichier_billet_refuse(app_famille):
    r = server.arbre_proposer([_billet()], "Billet", "Essai (test).")
    assert "erreur" in r and "backend fichier" in r["erreur"] and "GENEALOGISTE_BACKEND=gramps" in r["erreur"]
    r = server.propositions_deposer([_billet()], "Billet", "Essai (test).")
    assert "erreur" in r and "backend fichier" in r["erreur"]


def test_serveur_miroir_synchro_et_vault_inchanges(tmp_path, fake, tree):
    a = _bapp(tmp_path, fake, tree, mirror=True, vault=True)
    server.notes_generer()
    vault = a.config.notes_dir
    avant = {str(p.relative_to(vault)): p.read_text(encoding="utf-8") for p in vault.rglob("*.md")}
    r = server.arbre_appliquer(server.arbre_proposer(OPS, "Billet", "Récit (test).")["jeton"])
    sid = next(s for s in a.tree().sources if a.tree().sources[s].tags == ["Blog"])
    apres = {str(p.relative_to(vault)): p.read_text(encoding="utf-8") for p in vault.rglob("*.md")}
    assert apres == avant, r.get("notes")  # aucune fiche écrite ni modifiée dans le vault
    miroir = read_gedcom(a.store.text())[0]
    billets = [s for s in miroir.sources.values() if "Blog" in s.tags]
    assert len(billets) == 1 and billets[0].id == sid and billets[0].prive and billets[0].note
    # modification « dans l'interface » puis synchronisation : ni doublon ni écrasement
    fake.ui_edit("Source", sid, lambda o: o.update(title="Titre revu dans l'interface"))
    server.gramps_synchroniser()
    miroir = read_gedcom(a.store.text())[0]
    billets = [s for s in miroir.sources.values() if "Blog" in s.tags]
    assert [b.titre for b in billets] == ["Titre revu dans l'interface"]
    assert len(fake.objects["Source"]) == len(tree.sources) + 1


def test_gramps_tirer_en_mode_fichier_garde_le_billet(tmp_path, fake, tree, fixtures):
    """Mode fichier : gramps_tirer importe le billet (étiquette, RESN, corps, médias) une fois."""
    ctx = apply_ops(_medias(tree), [_billet(medias=["O1"])], backend="gramps")
    seed(fake, ctx.tree)
    a = make_app(tmp_path, backend="fichier")
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    p = server.gramps_tirer()
    server.arbre_appliquer(p["jeton"])
    t = a.tree()
    billets = [s for s in t.sources.values() if "Blog" in s.tags]
    assert len(billets) == 1 and billets[0].prive and billets[0].note == CORPS and billets[0].medias
