"""#291 : contexte historique sourcé dans les notes, récits et billets (« aucune phrase de contexte sans référence
consultée »).

Garanties de code : un billet du blog de Gramps Web dont le texte a une section « Contexte » n'est proposé que si
``contexte_verifier`` le déclare conforme ; une section manuelle « Contexte » d'une fiche du coffre survit à la
régénération. Consignes : contenu des fichiers d'agents, de commandes et de skill.

Aucun accès réseau. Textes : tests/fixtures/contexte/textes/ (conformes et volontairement fautifs, #324), dont les
phrases de contexte sont des titres de notices réelles ; aucun fait historique n'est rédigé ici."""

from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed

from genealogiste_mcp import billets, server
from genealogiste_mcp.config import Config
from genealogiste_mcp.contexte import verifier as v
from genealogiste_mcp.contexte.modeles import Reference
from genealogiste_mcp.contexte.registre import RegistreReferences
from genealogiste_mcp.gedcom.mapping import read_gedcom
from genealogiste_mcp.tree.ops import OpError, apply_ops

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "contexte"
TEXTES = FIXTURES / "textes"
ATTENDUS = json.loads((TEXTES / "ATTENDUS.json").read_text(encoding="utf-8"))
CAS = "mineur_artois_oklahoma"
FAUTIFS = sorted(n for n in ATTENDUS["fautifs"] if n.startswith(CAS + "."))


def _texte(nom: str) -> str:
    return (TEXTES / f"{nom}.md").read_text(encoding="utf-8")


def _forme_billet(texte: str) -> str:
    """Forme « billet » d'un texte des fixtures : sans titre de premier niveau, intertitres en gras seul sur leur
    ligne (Gramps Web n'interprète que gras, italique et liens). Aucune phrase n'est changée."""
    texte = re.sub(r"\A# [^\n]*\n+", "", texte)
    return re.sub(r"^## (.*)$", r"**\1**", texte, flags=re.M)


def _inscrire_references(registre: RegistreReferences, texte: str) -> list[str]:
    """Inscrit au registre les références que le texte conforme appelle dans « Contexte » (titre = énoncé cité)."""
    a = v.analyser(texte)
    cles = []
    for p in a.phrases:
        if p.genre != "contexte":
            continue
        titre = re.findall(r"«\s*(.*?)\s*»", p.texte)[0]
        for c in p.appels:
            for i in v.identifiants(a.notes[c]):
                registre.enregistrer(Reference(identifiant=i, nature="secondaire", titre=titre, annee=1900,
                                               service="TEST", requete="https://example.org/notice",
                                               consulte_le="2026-11-23"), statut=200, reponse=i.valeur)
                cles.append(i.cle)
    return cles


@pytest.fixture
def arbre(fixtures):
    """Cas témoin du mineur (I1 : Billy-Montigny et Denain, puis États-Unis, 1881-1946)."""
    return read_gedcom((fixtures / "contexte" / f"{CAS}.ged").read_text(encoding="utf-8"))[0]


@pytest.fixture
def registre(tmp_path):
    r = RegistreReferences(tmp_path / "references-consultees.jsonl")
    assert len(_inscrire_references(r, _texte(f"{CAS}.conforme"))) == 3
    return r


def _billet(texte: str, **kw) -> dict:
    return {"op": "ajouter_billet", "ref": "b", "titre": "Un mineur de Billy-Montigny", "auteur": "Équipe fictive",
            "texte": texte, "format_texte": "markdown", **kw}


# ---------------------------------------------------------------------------- billet : garantie de code

def test_billet_conforme_propose_prive_avec_controle_au_resume(arbre, registre):
    texte = _forme_billet(_texte(f"{CAS}.conforme"))
    ctx = apply_ops(arbre, [_billet(texte, personne="I1")], backend="gramps", registre=registre)
    sid = ctx.refs["b"]
    s = ctx.tree.sources[sid]
    assert s.prive is True and s.tags == ["Blog"]
    assert "Contexte" in s.note and "**" not in s.note  # titres en gras : mise en forme, pas des astérisques
    controle = [x for x in ctx.summary if "section « Contexte » contrôlée" in x]
    assert controle == [f"Billet {sid} : section « Contexte » contrôlée (contexte_verifier, personne I1) : conforme, "
                        "3 phrase(s) de contexte, 3 référence(s) consultée(s)"]


@pytest.mark.parametrize("nom", FAUTIFS)
def test_billet_fautif_refuse_avec_le_rapport(arbre, registre, nom):
    texte = _forme_billet(_texte(nom))
    with pytest.raises(OpError) as exc:
        apply_ops(arbre, [_billet(texte, personne="I1")], backend="gramps", registre=registre)
    message = str(exc.value)
    assert "section « Contexte » non conforme" in message and "conforme: false" in message
    rubriques = {r for r in billets.RUBRIQUES_CONTEXTE if re.search(rf"{r} \(\d+\) : «", message)}
    assert rubriques == set(ATTENDUS["fautifs"][nom]["categories"]), message
    assert "jamais en inventant une référence" in message


def test_billet_fautif_refuse_aussi_en_texte_brut(arbre, registre):
    """Sans format_texte : les titres « ## Contexte » du texte brut sont lus de la même façon."""
    op = _billet(_texte(f"{CAS}.sans_note"), personne="I1")
    del op["format_texte"]
    with pytest.raises(OpError, match="phrases_sans_reference"):
        apply_ops(arbre, [op], backend="gramps", registre=registre)
    op["texte"] = _texte(f"{CAS}.conforme")
    assert apply_ops(arbre, [op], backend="gramps", registre=registre).refs["b"]


def test_billet_avec_contexte_sans_personne_ou_sans_registre_refuse(arbre, registre):
    texte = _forme_billet(_texte(f"{CAS}.conforme"))
    with pytest.raises(OpError, match="aucune personne n'est donnée"):
        apply_ops(arbre, [_billet(texte)], backend="gramps", registre=registre)
    with pytest.raises(OpError, match="registre des références consultées indisponible"):
        apply_ops(arbre, [_billet(texte, personne="I1")], backend="gramps")
    with pytest.raises(OpError, match="personne inconnue"):
        apply_ops(arbre, [_billet(texte, personne="I999")], backend="gramps", registre=registre)
    # registre vide : les références du texte n'ont jamais été consultées
    vide = RegistreReferences(registre.path.with_name("vide.jsonl"))
    with pytest.raises(OpError, match="references_non_consultees"):
        apply_ops(arbre, [_billet(texte, personne="I1")], backend="gramps", registre=vide)


@pytest.mark.parametrize("nom", ["lieu_non_documente.conforme", "soldat_1914_1918.conforme"])
def test_billet_sans_section_contexte_inchange(arbre, registre, nom):
    """Aucune section « Contexte » : ni personne exigée, ni contrôle, ni ligne de résumé, avec ou sans registre."""
    texte = _forme_billet(_texte(nom))
    assert not v.analyser(texte).sections_contexte
    sans = apply_ops(arbre, [_billet(texte)], backend="gramps")
    avec = apply_ops(arbre, [_billet(texte)], backend="gramps", registre=registre)
    assert sans.summary == avec.summary and sans.warnings == avec.warnings
    assert not any("Contexte" in x for x in sans.summary)
    assert sans.tree.sources[sans.refs["b"]].to_dict() == avec.tree.sources[avec.refs["b"]].to_dict()


def test_billet_existant_texte_modifie_ou_rendu_public_recontrole(arbre, registre):
    conforme, fautif = _forme_billet(_texte(f"{CAS}.conforme")), _forme_billet(_texte(f"{CAS}.causalite"))
    ctx = apply_ops(arbre, [_billet(conforme, personne="I1")], backend="gramps", registre=registre)
    sid, base = ctx.refs["b"], ctx.tree
    # texte remplacé par un texte fautif : refus, même avec la personne
    op = {"op": "modifier_source", "id": sid, "champs": {"note": fautif}, "format_texte": "markdown",
          "personne": "I1"}
    with pytest.raises(OpError, match="causalites"):
        apply_ops(base, [op], backend="gramps", registre=registre)
    # texte à section « Contexte » changé sans personne : refus
    with pytest.raises(OpError, match="aucune personne n'est donnée"):
        apply_ops(base, [{"op": "modifier_source", "id": sid, "champs": {"note": conforme + "\nFin.\n"},
                          "format_texte": "markdown"}], backend="gramps", registre=registre)
    # rendu public : recontrôlé (personne exigée), accepté si conforme
    public = {"op": "modifier_source", "id": sid, "champs": {"prive": False}}
    with pytest.raises(OpError, match="aucune personne n'est donnée"):
        apply_ops(base, [public], backend="gramps", registre=registre)
    ok = apply_ops(base, [{**public, "personne": "I1"}], backend="gramps", registre=registre)
    assert ok.tree.sources[sid].prive is False
    assert any("section « Contexte » contrôlée" in x for x in ok.summary)
    # billet inchangé dans une autre proposition : pas de contrôle, rien d'exigé
    autre = apply_ops(base, [{"op": "ajouter_source", "titre": "Source ordinaire"}], backend="gramps")
    assert not any("Contexte" in x for x in autre.summary)


def test_source_etiquetee_blog_meme_controle(arbre, registre):
    """Autres chemins vers un billet : ajouter_source avec l'étiquette Blog, etiqueter une source existante."""
    fautif, conforme = _texte(f"{CAS}.generalisation"), _texte(f"{CAS}.conforme")
    source = {"op": "ajouter_source", "ref": "s", "titre": "Billet", "tags": ["Blog"]}
    with pytest.raises(OpError, match="formulations"):
        apply_ops(arbre, [{**source, "note": fautif, "personne": "I1"}], registre=registre)
    with pytest.raises(OpError, match="aucune personne n'est donnée"):
        apply_ops(arbre, [{**source, "note": conforme}], registre=registre)
    assert apply_ops(arbre, [{**source, "note": conforme, "personne": "I1"}], registre=registre).refs["s"]
    ordinaire = apply_ops(arbre, [{"op": "ajouter_source", "ref": "s", "titre": "Notes", "note": fautif}])
    sid = ordinaire.refs["s"]  # source ordinaire : jamais contrôlée
    with pytest.raises(OpError, match="aucune personne n'est donnée"):
        apply_ops(ordinaire.tree, [{"op": "etiqueter", "cible": {"type": "source", "id": sid}, "tags": ["Blog"]}],
                  registre=registre)
    with pytest.raises(OpError, match="formulations"):
        apply_ops(ordinaire.tree, [{"op": "modifier_source", "id": sid, "tags": ["Blog"], "personne": "I1"}],
                  registre=registre)


# ---------------------------------------------------------------------------- billet : par le serveur (Gramps Web)

@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


def test_serveur_billet_contexte_bloque_puis_propose(tmp_path, fake, arbre):
    seed(fake, arbre)
    a = make_app(tmp_path)
    try:
        conforme = _forme_billet(_texte(f"{CAS}.conforme"))
        # références jamais consultées par cette installation : billet bloqué, rapport dans l'erreur
        r = server.arbre_proposer([_billet(conforme, personne="I1")], "Billet", "Récit sourcé (test).")
        assert "erreur" in r and "references_non_consultees (3)" in r["erreur"] and "ppn:249145197" in r["erreur"]
        assert not fake.transactions
        _inscrire_references(a.registre_references, _texte(f"{CAS}.conforme"))
        r = server.arbre_proposer([_billet(_forme_billet(_texte(f"{CAS}.causalite")), personne="I1")], "Billet",
                                  "Récit sourcé (test).")
        assert "erreur" in r and "causalites (1)" in r["erreur"] and "à cause de" in r["erreur"]
        r = server.propositions_deposer([_billet(_forme_billet(_texte(f"{CAS}.anachronisme")), personne="I1")],
                                        "Billet", "Récit sourcé (test).")
        assert "erreur" in r and "hors_portee (1)" in r["erreur"]
        assert not fake.transactions
        # conforme : proposé (privé), puis appliqué après accord
        p = server.arbre_proposer([_billet(conforme, personne="I1")], "Billet", "Récit sourcé (test).")
        assert "erreur" not in p, p
        sid = p["references_creees"]["b"]
        assert any("section « Contexte » contrôlée" in x and "conforme" in x for x in p["resume"])
        assert any("privé" in x for x in p["resume"])
        assert "erreur" not in server.arbre_appliquer(p["jeton"])
        src = fake.find("Source", sid)
        corps = fake.objects["Note"][src["note_list"][0]]
        assert src["private"] is True and corps["text"]["string"].startswith("Récit\n")
        # le billet relu depuis Gramps Web se contrôle encore (titres en gras rétablis depuis la mise en forme)
        relu = a.tree()
        md = billets.texte_markdown(relu, relu.sources[sid])
        assert "**Contexte**" in md and "[6]" in md
        assert v.verifier(md, relu, "I1", a.registre_references)["conforme"] is True
        r = server.arbre_proposer([{"op": "modifier_source", "id": sid, "champs": {"prive": False}}], "Public",
                                  "Publication (test).")
        assert "erreur" in r and "aucune personne n'est donnée" in r["erreur"]
    finally:
        server.set_app(None)


# ---------------------------------------------------------------------------- note du coffre

@pytest.fixture
def napp(tmp_path, fixtures):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", notes_dir=tmp_path / "vault")
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "contexte" / f"{CAS}.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("cas témoin mineur")
    a.notes.today = lambda: date(2026, 11, 23)
    yield a
    server.set_app(None)


def _section_note(texte: str) -> str:
    """Section « Contexte » pour une fiche du coffre, tirée d'un texte des fixtures : la section telle quelle, ses
    notes en notes de bas de page Obsidian (« [^c6]: … »), lisibles hors d'une section « Notes et sources »."""
    section = re.search(r"^## Contexte\n.*?(?=^## )", texte, flags=re.S | re.M).group(0)
    notes = v.analyser(texte).notes
    appels = sorted({c for p in v.analyser(texte).phrases if p.genre == "contexte" for c in p.appels}, key=int)
    section = re.sub(r"\[(\d+)\]", lambda m: f"[^c{m.group(1)}]", section)
    return section.rstrip("\n") + "\n\n" + "\n".join(f"[^c{c}]: {notes[c]}" for c in appels) + "\n"


def _inserer_avant_notes_libres(fiche: Path, section: str) -> None:
    texte = fiche.read_text(encoding="utf-8")
    assert texte.count("## Notes libres") == 1
    fiche.write_text(texte.replace("## Notes libres", section + "\n## Notes libres"), encoding="utf-8")


def test_note_section_contexte_manuelle_preservee_a_la_regeneration(napp):
    server.notes_generer()
    fiche = next((napp.config.notes_dir / "personnes").glob("I1 - *.md"))
    section = _section_note(_texte(f"{CAS}.conforme"))
    _inserer_avant_notes_libres(fiche, section)
    _inscrire_references(napp.registre_references, _texte(f"{CAS}.conforme"))
    r = server.contexte_verifier(note="I1")
    assert r["conforme"] is True and r["contexte"] == "present" and r["mesures"]["phrases_contexte"] == 3, r
    avant = fiche.read_text(encoding="utf-8")
    # régénération sans changement de l'arbre : aucun octet ne bouge
    assert server.notes_generer()["ecrites"] == [] and fiche.read_text(encoding="utf-8") == avant
    # l'arbre change : blocs générés réécrits, section manuelle intacte, hors des blocs, avant « Notes libres »
    p = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I1", "evenement": {
        "type": "OCCU", "valeur": "houilleur", "non_source": True, "motif": "essai de régénération"}}], "Métier", "j")
    server.arbre_appliquer(p["jeton"])
    server.notes_generer()
    apres = fiche.read_text(encoding="utf-8")
    assert apres != avant and "houilleur" in apres
    assert section in apres
    hors_blocs = re.sub(r"<!-- (?:genealogiste|sosa):debut.*?<!-- (?:genealogiste|sosa):fin -->", "", apres,
                        flags=re.S)
    assert section in hors_blocs and hors_blocs.index("## Contexte") < hors_blocs.index("## Notes libres")
    assert server.contexte_verifier(note="I1")["conforme"] is True
    # une entrée ajoutée par notes_ajouter va sous « Notes libres », jamais dans la section « Contexte »
    server.notes_ajouter("I1", "départ de France à dater", "a_faire")
    final = fiche.read_text(encoding="utf-8")
    assert section in final and final.index("départ de France à dater") > final.index("## Notes libres")
    r = server.contexte_verifier(note="I1")
    assert r["conforme"] is True and r["mesures"]["phrases_contexte"] == 3


def test_note_section_contexte_fautive_signalee(napp):
    server.notes_generer()
    fiche = next((napp.config.notes_dir / "personnes").glob("I1 - *.md"))
    _inserer_avant_notes_libres(fiche, _section_note(_texte(f"{CAS}.sans_note")))
    _inscrire_references(napp.registre_references, _texte(f"{CAS}.conforme"))
    r = server.contexte_verifier(note="I1")
    assert r["conforme"] is False and len(r["phrases_sans_reference"]) == 1
    server.notes_generer()
    assert server.contexte_verifier(note="I1")["conforme"] is False  # la régénération ne « répare » rien


# ---------------------------------------------------------------------------- consignes (agents, commandes, skill)

def _lire(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _plat(texte: str) -> str:
    return " ".join(texte.split())


def test_redacteur_regle_durcie():
    texte = _plat(_lire("agents/redacteur.md"))
    # l'alternative qui autorisait un contexte sans référence a disparu
    assert "présenté comme contexte général" not in texte
    assert "général et prudent" not in texte
    assert not re.search(r"ou\s+présenté\s+comme\s+contexte", texte)
    # règle : référence consultée, sinon omission et « contexte à documenter »
    assert "Aucune phrase de contexte sans référence consultée" in texte
    assert "contexte à documenter : " in texte and "jamais de paragraphe de remplissage" in texte
    for outil in ("`contexte_local", "`contexte_bibliographie`", "`presse_recherche`", "`pistes_contexte"):
        assert outil in texte, outil
    # structure lue par contexte_verifier et formulations par niveau
    for titre in ("Contexte", "Hypothèses", "Questions ouvertes", "Notes et sources"):
        assert f"« {titre} »" in texte or f"**{titre}**" in texte or f"## {titre}" in texte, titre
    for formule in ("à la même époque et au même endroit", "plus généralement",
                    "tendance générale, ne prouve rien pour l'individu"):
        assert formule in texte.lower(), formule
    # interdits
    for interdit in ("causalité", "sentiments", "généralisation", "anachronisme"):
        assert interdit in texte.lower(), interdit
    # vérification avant de rendre, avec les vrais paramètres
    assert "`contexte_verifier(texte=" in texte and "personne=" in texte
    assert "conforme: true" in texte and "jamais en inventant une référence" in texte


def test_verificateur_commandes_et_skill_alignes():
    verificateur = _plat(_lire("agents/verificateur.md"))
    assert "`contexte_verifier(" in verificateur and "phrases de contexte" in verificateur
    recit = _plat(_lire("commands/recit.md"))
    assert "`contexte_verifier(texte=" in recit and "conforme: true" in recit
    billet = _plat(_lire("commands/billet.md"))
    assert "`contexte_verifier(texte=" in billet and '"personne"' in billet and "conforme: false" in billet
    skill = _plat(_lire("skills/methodologie-gps/SKILL.md"))
    assert "`contexte_verifier`" in skill and "contexte à documenter" in skill
    # #325 : la commande /genealogiste:contexte existe et suit la même règle (rien d'affiché sans source)
    contexte = _plat(_lire("commands/contexte.md"))
    assert "`contexte_local(" in contexte and "`pistes_contexte`" in contexte
    assert "contexte non documenté" in contexte and "Rien n'est affirmé de mémoire" in contexte


def test_exemple_de_la_doc_repris_des_textes_conformes():
    """L'exemple de docs/contexte-historique.md (§ Rédaction) ne contient aucune phrase de contexte rédigée : chaque
    ligne de sa section « Contexte » et de ses notes vient mot pour mot d'un texte conforme des fixtures."""
    doc = _lire("docs/contexte-historique.md")
    redaction = doc.split("### Rédaction", 1)[1].split("### contexte_verifier", 1)[0]
    assert "À compléter par #291" not in redaction
    blocs = re.findall(r"```markdown\n(.*?)```", redaction, flags=re.S)
    assert blocs, "exemple attendu dans un bloc ```markdown"
    conformes = "\n".join(p.read_text(encoding="utf-8") for p in sorted(TEXTES.glob("*.conforme.md")))
    lignes_conformes = {x.strip() for x in conformes.splitlines() if x.strip()}
    for bloc in blocs:
        for ligne in bloc.splitlines():
            ligne = ligne.strip()
            if not ligne or "…" in ligne:  # gabarit à trous : pas une phrase
                continue
            assert ligne in lignes_conformes, ligne
