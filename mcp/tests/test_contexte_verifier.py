"""#324 : contexte_verifier (contrôle déterministe d'un texte de contexte) et évaluation « anti-invention ».

Aucun test n'accède au réseau : les références sont inscrites au registre par contexte_local rejoué sur les réponses
réelles enregistrées (tests/fixtures/contexte/reponses/), et le vérificateur lui-même n'émet aucune requête.
Textes de référence et textes volontairement fautifs : tests/fixtures/contexte/textes/ (ATTENDUS.json)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import respx
from test_contexte_local import services_enregistres  # noqa: F401  (fixture du rejeu par service)

from genealogiste_mcp import outils, server
from genealogiste_mcp.contexte import verifier as v
from genealogiste_mcp.contexte.modeles import Identifiant, Reference
from genealogiste_mcp.contexte.registre import RegistreReferences

FIXTURES = Path(__file__).parent / "fixtures" / "contexte"
TEXTES = FIXTURES / "textes"
REPONSES = FIXTURES / "reponses"
ATTENDUS = json.loads((TEXTES / "ATTENDUS.json").read_text(encoding="utf-8"))
RUBRIQUES = ("phrases_sans_reference", "references_non_consultees", "hors_portee", "causalites", "formulations")
CAS = ("mineur_artois_oklahoma", "cultivateur_ancien_regime", "soldat_1914_1918", "lieu_non_documente")


def _signalees(rapport: dict) -> set[str]:
    return {r for r in RUBRIQUES if rapport[r]}


def _inscrire(registre: RegistreReferences, ident: str, titre: str = "Notice", annee: int = 1900) -> None:
    i = Identifiant.depuis_texte(ident)
    ref = Reference(identifiant=i, nature="secondaire", titre=titre, annee=annee, service="TEST",
                    requete="https://example.org/notice", consulte_le="2026-11-23")
    registre.enregistrer(ref, statut=200, reponse=i.valeur)


@pytest.fixture
def mineur(app, fixtures):
    """Arbre du cas témoin du mineur (I1 : Billy-Montigny et Denain, puis États-Unis, 1881-1946)."""
    import shutil
    shutil.copy(fixtures / "contexte" / "mineur_artois_oklahoma.ged", app.store.path)
    app.store.write(app.store.load())
    app.store.commit("cas témoin mineur")
    return app


def _verifier(app, texte: str, personne: str = "I1") -> dict:
    with respx.mock(assert_all_called=False) as r:
        route = r.route().respond(500)
        out = server.contexte_verifier(texte=texte, personne=personne)
    assert not route.called, "contexte_verifier n'émet aucune requête"
    return out


# ---------------------------------------------------------------------------------------- catalogue

def test_classe_lecture_sans_garde_reseau():
    assert outils.OUTILS["contexte_verifier"] == (outils.LECTURE, outils.LECTURE)
    assert "contexte_verifier" not in outils.GARDE_VIVANTS  # aucun appel externe : rien ne sort
    assert "contexte_verifier" in server.mcp.sans_verrou


def test_listes_versionnees_et_uniques():
    assert v.VERSION_LISTES == "2"  # #348 : généralisations ajoutées, EVENEMENTS, POSSESSIFS
    for liste in (v.CONNECTEURS, v.GENERALISATIONS):
        cles = [r.cle for r in liste]
        assert len(cles) == len(set(cles))
        for r in liste:
            re.compile(r.motif)
            assert r.exemple and r.contre_exemple and r.categorie


# ---------------------------------------------------------------------------------------- listes fermées

@pytest.mark.parametrize("regle", v.CONNECTEURS, ids=lambda r: r.cle)
def test_connecteur_causal_exemple_et_contre_exemple(mineur, regle):
    oui = _verifier(mineur, f"## Récit\n\n{regle.exemple}\n")
    assert regle.cle in {c["connecteur"] for c in oui["causalites"]}, oui["causalites"]
    assert oui["conforme"] is False and oui["mesures"]["causalites_non_sourcees"] >= 1
    non = _verifier(mineur, f"## Récit\n\n{regle.contre_exemple}\n")
    assert regle.cle not in {c["connecteur"] for c in non["causalites"]}, non["causalites"]


@pytest.mark.parametrize("regle", v.GENERALISATIONS, ids=lambda r: r.cle)
def test_generalisation_exemple_et_contre_exemple(mineur, regle):
    oui = _verifier(mineur, f"## Récit\n\n{regle.exemple}\n")
    assert regle.cle in {f.get("marqueur") for f in oui["formulations"]}, oui["formulations"]
    non = _verifier(mineur, f"## Récit\n\n{regle.contre_exemple}\n")
    assert regle.cle not in {f.get("marqueur") for f in non["formulations"]}, non["formulations"]


def test_causalite_admise_avec_source_individuelle_question_ou_hypothese(mineur):
    notes = "\n## Notes et sources\n\n[1] Registres de population de Denain (fictif), Registre de population 1906.\n"
    out = _verifier(mineur, "## Récit\n\nIl quitta Denain à cause du chômage [1].\n" + notes)
    assert out["causalites"] == []  # source individuelle : le contrôle ne lit pas ce qu'elle dit (limite)
    out = _verifier(mineur, "## Questions ouvertes\n\n- Est-il parti à cause de la catastrophe ?\n")
    assert out["causalites"] == []
    out = _verifier(mineur, "## Hypothèses\n\nIl serait parti à cause de la catastrophe : hypothèse à vérifier.\n")
    assert out["causalites"] == []
    out = _verifier(mineur, "## Récit\n\nIl aurait pu partir à cause de la crise.\n")
    assert out["causalites"] == []


def test_tournure_impersonnelle_ne_vise_pas_l_individu(mineur):
    out = _verifier(mineur, "## Récit\n\nIl y a peu de sources, à cause de la destruction des archives.\n")
    assert out["causalites"] == []
    out = _verifier(mineur, "## Récit\n\nAnselme partit à cause de la crise.\n")
    assert [c["connecteur"] for c in out["causalites"]] == ["a_cause_de"]


# ---------------------------------------------------------------------------------------- découpage et notes

def test_decoupage_abreviations_citations_et_appel_apres_le_point():
    assert v.decouper("Voir p. 12 et n° 3. Puis la suite.") == ["Voir p. 12 et n° 3.", "Puis la suite."]
    assert v.decouper("« Une tragédie. Été 44 » [1]. Fin.") == ["« Une tragédie. Été 44 » [1].", "Fin."]
    assert v.decouper("Première phrase. [2] Seconde phrase.") == ["Première phrase. [2]", "Seconde phrase."]
    assert v.decouper("Imprimé par A. Knapen en 1729 [1]. Fin.") == ["Imprimé par A. Knapen en 1729 [1].", "Fin."]


def test_appels_de_note():
    assert v.appels("a [1] b [2, 4] c [5-7] d [^ark] e [8](https://x.org)") == ["1", "2", "4", "5", "6", "7", "ark"]
    assert v.appels("« Mémoire pour [Honoré-] François »") == []


def test_analyse_sections_markdown_billet_et_notes_de_bas_de_page():
    a = v.analyser("**Récit**\n\nIl naquit [1].\n\n**Contexte**\n\nÀ Denain : « Titre » [^a].\n\n"
                   "**Notes et sources**\n\n1. Registre.\n\n[^a]: Notice. PPN 123456789.\n")
    assert [(p.genre, p.texte) for p in a.phrases] == [("autre", "Il naquit [1]."),
                                                      ("contexte", "À Denain : « Titre » [^a].")]
    assert a.notes == {"1": "Registre.", "a": "Notice. PPN 123456789."}
    texte = ("---\nid: I1\n---\n<!-- genealogiste:debut faits -->\nÀ cette époque.\n<!-- genealogiste:fin -->\n"
             "## Contexte\n\n### Commune\n\nPhrase [1].\n\n```\nÀ cette époque.\n```\n## Notes\n\n[1] Note\n  suite.\n")
    a = v.analyser(texte)
    assert [(p.genre, p.texte) for p in a.phrases] == [("contexte", "Phrase [1].")]
    assert a.notes == {"1": "Note suite."}


@pytest.mark.parametrize("note,cles", [
    ("DUPONT. Titre. 1975. DOI 10.3406/rnord.1975.3360.", ["doi:10.3406/rnord.1975.3360"]),
    ("Voir https://doi.org/10.3406/rnord.1975.3360 et doi:10.3406/rnord.1975.3360.", ["doi:10.3406/rnord.1975.3360"]),
    ("Titre. 1727. ark:/12148/cb36749755m. [Notice seule, non lu.]", ["ark:ark:/12148/cb36749755m"]),
    ("Thèse. HAL tel-01234567.", ["hal:tel-01234567"]),
    ("Notice. PPN 165560274. Voir https://www.sudoc.fr/165560274", ["ppn:165560274"]),
    ("Disponible à l'adresse : https://example.org/jeu?x=1.", ["url:https://example.org/jeu?x=1"]),
    ("Handle 10670/1.abcd.", ["handle:10670/1.abcd"]),
    ("Registre paroissial (fictif), f° 6.", []),
])
def test_identifiants_d_une_note(note, cles):
    assert [i.cle for i in v.identifiants(note)] == cles


def test_annees_unites_numeros_et_siecles():
    assert v.annees("Billy-Montigny au coeur de la catastrophe minière de 1906 : 1099 morts") == [(1906, 1906)]
    assert v.annees("acte n° 1847, p. 1850, 1200 habitants, capital 1500") == []
    assert v.annees("Les houillères, 1880-1914 (fin XIXe-début XXe siècle) [1904]") == [
        (1880, 1914), (1904, 1904), (1801, 1900), (1901, 2000)]
    assert v.annees("https://example.org/1789/x") == []


# ---------------------------------------------------------------------------------------- règles de contexte

def _ctx(phrase: str, note: str) -> str:
    return f"## Contexte\n\n{phrase}\n\n## Notes et sources\n\n[1] {note}\n"


def test_reference_consultee_ou_non(mineur):
    note = "Notice. PPN 249145197."
    out = _verifier(mineur, _ctx("À la même époque et au même endroit : « Billy-Montigny » [1].", note))
    assert [x["identifiant"] for x in out["references_non_consultees"]] == ["ppn:249145197"]
    assert out["mesures"]["part_references_consultees"] == 0
    _inscrire(mineur.registre_references, "ppn:249145197", "Billy-Montigny")
    out = _verifier(mineur, _ctx("À la même époque et au même endroit : « Billy-Montigny » [1].", note))
    assert out["conforme"] is True, out
    assert out["mesures"] == {"phrases_contexte": 1, "phrases_sourcees": 1, "part_phrases_sourcees": 1.0,
                              "references_citees": 1, "references_consultees": 1,
                              "part_references_consultees": 1.0, "anachronismes": 0,
                              "causalites_non_sourcees": 0}


def test_note_absente_ou_sans_identifiant(mineur):
    out = _verifier(mineur, "## Contexte\n\nÀ Billy-Montigny : « Titre » [3].\n")
    assert out["references_non_consultees"][0]["motif"].startswith("appel sans note")
    assert out["mesures"]["part_phrases_sourcees"] == 0
    out = _verifier(mineur, _ctx("À Billy-Montigny : « Titre » [1].", "Un livre lu autrefois, p. 12."))
    assert "aucun identifiant" in out["references_non_consultees"][0]["motif"]


def test_portee_periode_lieux_et_lieu_non_etabli(mineur):
    _inscrire(mineur.registre_references, "ppn:249145197", "Notice sur la commune")
    note = "Notice. PPN 249145197."
    out = _verifier(mineur, _ctx("À Billy-Montigny, en 1871 : « Notice » [1].", note))
    assert out["hors_portee"][0]["annees"] == [[1871, 1871]] and out["mesures"]["anachronismes"] == 1
    out = _verifier(mineur, _ctx("À Billy-Montigny, de 1870 à 1890 : « Notice » [1].", note))
    assert out["hors_portee"][0]["annees"] == [[1870, 1870]]  # 1890 dans la vie, 1870 non
    out = _verifier(mineur, _ctx("En Gironde, au même endroit et à la même époque : « Notice » [1].", note))
    assert {x["type"] for x in out["hors_portee"]} == {"lieu"} and "Gironde" in out["hors_portee"][0]["motif"]
    out = _verifier(mineur, _ctx("Au même endroit et à la même époque : « Notice » [1].", note))
    assert "portée géographique non établie" in out["hors_portee"][0]["motif"]
    out = _verifier(mineur, _ctx("Aux États-Unis, plus généralement : « Notice » (tendance générale, ne prouve "
                                 "rien pour l'individu) [1].", note))
    assert out["conforme"] is True, out  # pays de vie (Pennsylvanie, Oklahoma)


def test_rattachement_declare_et_mention(mineur):
    _inscrire(mineur.registre_references, "ppn:249145197", "Notice sur Billy-Montigny")
    note = "Notice. PPN 249145197."
    out = _verifier(mineur, _ctx("À la même époque et au même endroit, il travaille à la compagnie [1].", note))
    assert [f["niveau"] for f in out["formulations"]] == ["compatible"]
    out = _verifier(mineur, _ctx("Il figure parmi les mineurs de la compagnie (rattachement : attesté) [1].", note))
    assert [f["niveau"] for f in out["formulations"]] == ["atteste"]
    individuelle = "\n[2] Registres de population de Billy-Montigny (fictif), Registre de population 1904, f° 88.\n"
    out = _verifier(mineur, _ctx("Il figure parmi les mineurs de la compagnie (rattachement : attesté) [1] [2].",
                                 note) + individuelle)
    assert out["formulations"] == [] and out["conforme"] is True, out
    out = _verifier(mineur, _ctx("Il travaille à la compagnie [1].", note))
    assert [f["type"] for f in out["formulations"]] == ["rattachement"]  # affirmation sans source individuelle
    out = _verifier(mineur, _ctx("Dans le département du Pas-de-Calais, plus généralement : « Notice » [1].",
                                 "Thèse. PPN 060478624."))
    assert "mention" in {f["type"] for f in out["formulations"]}


def test_contexte_non_documente_declare(mineur):
    out = _verifier(mineur, "## Contexte\n\nContexte non documenté.\n\n## Questions ouvertes\n\n- Contexte à "
                            "documenter : Billy-Montigny, 1881-1904.\n")
    assert out["conforme"] is True and out["contexte"] == "non_documente"
    assert out["mesures"]["phrases_contexte"] == 0 and out["mesures"]["part_phrases_sourcees"] is None
    assert out["limites"][0].startswith("Aucune phrase de contexte")


# ---------------------------------------------------------------------------------------- outil

def test_arguments(mineur):
    assert "erreur" in server.contexte_verifier()
    assert "erreur" in server.contexte_verifier(texte="x", note="I1")
    assert "personne obligatoire" in server.contexte_verifier(texte="## Contexte\n\nx.\n")["erreur"]
    assert "inconnue" in server.contexte_verifier(texte="x", personne="I999")["erreur"]


def test_note_du_coffre_lue_sans_etre_generee(mineur, tmp_path):
    mineur.notes.dir = tmp_path / "coffre"
    assert "erreur" in server.contexte_verifier(note="I1")  # fiche absente : rien n'est généré
    assert not (tmp_path / "coffre").exists()
    server.notes_generer("I1")
    fiche = next((tmp_path / "coffre" / "personnes").glob("I1 *.md"))
    fiche.write_text(fiche.read_text(encoding="utf-8") + "\n## Contexte\n\nÀ cette époque, la vie était dure.\n",
                     encoding="utf-8")
    avant = fiche.read_text(encoding="utf-8")
    out = server.contexte_verifier(note="I1")
    assert out["personne"] == "I1" and out["source"] == {"note": str(fiche)}
    assert out["conforme"] is False and out["phrases_sans_reference"]
    assert fiche.read_text(encoding="utf-8") == avant
    rel = fiche.relative_to(tmp_path / "coffre").as_posix()
    assert server.contexte_verifier(note=rel, personne="I1")["phrases_sans_reference"]
    assert "erreur" in server.contexte_verifier(note="../hors.md", personne="I1")


# ---------------------------------------------------------------------------------------- évaluation

def _routes_exactes(r) -> None:
    for d in sorted(REPONSES.iterdir()):
        m = d / "MANIFESTE.json"
        if not m.is_file():
            continue
        for e in json.loads(m.read_text(encoding="utf-8"))["reponses"]:
            if e.get("fichier") and 200 <= e["statut"] < 300:
                r.get(e["url"]).respond(200, content=(d / e["fichier"]).read_bytes(),
                                        headers={"content-type": e["type"]})
    r.route().respond(404)


def _elements_du_cas(app, request, cas: str) -> list[dict]:
    """Rejoue contexte_local sur les réponses enregistrées (références inscrites au registre au passage)."""
    plan = ATTENDUS["contexte_local"][cas]
    sorties = []
    if plan["rejeu"] == "par_service":
        request.getfixturevalue("services_enregistres")
        sorties = [server.contexte_local(personne="I1", **x) for x in plan["appels"]]
    else:
        with respx.mock(assert_all_called=False) as r:
            _routes_exactes(r)
            sorties = [server.contexte_local(personne="I1", **x) for x in plan["appels"]]
    for s in sorties:
        assert "erreur" not in s, s
    return [x for s in sorties for v_ in s["elements"].values() for x in v_]


def _texte(nom: str) -> str:
    return (TEXTES / f"{nom}.md").read_text(encoding="utf-8")


def test_jeu_complet():
    noms = {p.stem for p in TEXTES.glob("*.md")}
    defauts = {"sans_note", "hors_registre", "anachronisme", "causalite", "generalisation", "hors_lieu"}
    assert noms == {f"{c}.conforme" for c in CAS} | set(ATTENDUS["fautifs"])
    for c in CAS:
        assert {n.split(".", 1)[1] for n in ATTENDUS["fautifs"] if n.startswith(c + ".")} \
            == defauts - ({"generalisation"} if c == "lieu_non_documente" else set())
    for nom, x in ATTENDUS["fautifs"].items():
        assert set(x["categories"]) <= set(RUBRIQUES), nom


@pytest.mark.parametrize("app_contexte", CAS, indirect=True)
def test_evaluation_anti_invention(app_contexte, request):
    cas, att = app_contexte.cas, app_contexte.attendus
    elements = _elements_du_cas(app_contexte, request, cas)
    assert bool(elements) is att["contexte_documente"], (cas, len(elements))
    enonces = {x["enonce"] for x in elements}
    sources = {x["source"]["identifiant"] for x in elements}

    # texte conforme : aucun signalement, mesures attendues
    texte = _texte(f"{cas}.conforme")
    out = _verifier(app_contexte, texte)
    assert _signalees(out) == set() and out["conforme"] is True, {r: out[r] for r in RUBRIQUES}
    m = out["mesures"]
    assert m["anachronismes"] == 0 and m["causalites_non_sourcees"] == 0
    a = v.analyser(texte)
    contexte = [p for p in a.phrases if p.genre == "contexte"]
    if att["contexte_documente"]:
        assert out["contexte"] == "present"
        assert m["part_phrases_sourcees"] == 1.0 and m["part_references_consultees"] == 1.0
        # aucun fait historique de rédaction : chaque phrase de contexte cite mot pour mot un énoncé de contexte_local
        for p in contexte:
            cites = re.findall(r"«\s*(.*?)\s*»", p.texte)
            assert cites and all(c in enonces for c in cites), p.texte
            for c in p.appels:
                assert {i.cle for i in v.identifiants(a.notes[c])} <= sources, a.notes[c]
        assert m["references_citees"] == len(contexte)
    else:
        assert contexte == [] and out["contexte"] == "non_documente"
        assert m["part_phrases_sourcees"] is None and m["part_references_consultees"] is None
        assert re.search(r"contexte (?:non documenté|à documenter)", texte.lower())

    # textes fautifs : chaque défaut détecté, dans les seules rubriques attendues
    for nom, x in ATTENDUS["fautifs"].items():
        if not nom.startswith(cas + "."):
            continue
        fautif = _texte(nom)
        out = _verifier(app_contexte, fautif)
        assert out["conforme"] is False, nom
        assert _signalees(out) == set(x["categories"]), (nom, {r: out[r] for r in RUBRIQUES})
        if "interdit" in x:
            cle, phrase = x["interdit"]
            permis = [y["element"] if isinstance(y, dict) else y for y in att["ne_doit_pas_contenir"][cle]]
            assert phrase in permis, (nom, phrase)
            assert phrase.casefold() in fautif.casefold(), (nom, phrase)
        if nom.endswith(".anachronisme"):
            assert out["mesures"]["anachronismes"] >= 1
        if nom.endswith(".causalite"):
            assert out["mesures"]["causalites_non_sourcees"] == 1
