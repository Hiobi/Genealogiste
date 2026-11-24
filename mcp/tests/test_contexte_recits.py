"""#348 : recette de bout en bout sur des récits réellement rédigés par un modèle (rôle de l'agent ``redacteur``).

Les récits de ``fixtures/contexte/recits/`` ont été écrits d'un jet à partir des sorties d'outils rejouées hors
ligne, puis figés ; ``MESURES.json`` porte le relevé manuel des défauts, phrase par phrase. Ce test est une
**non-régression des mesures** : chaque défaut déclaré détecté doit l'être par la rubrique indiquée, chaque défaut
déclaré échappé doit encore échapper (sinon : mettre la mesure à jour), et aucun signalement ne doit tomber hors des
défauts relevés (fausse alerte). Il ne prouve pas la conformité d'un récit : auto-évaluation d'un seul modèle,
détection lexicale. Les limites examinées par #348 sont épinglées en fin de fichier. Aucun accès réseau."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from gramps_fake import FakeGrampsWeb
from test_contexte_local import services_enregistres  # noqa: F401  (fixture du rejeu par service)
from test_contexte_verifier import CAS, RUBRIQUES, _elements_du_cas, _inscrire, _verifier, mineur  # noqa: F401
from test_gramps_backend import make_app, seed

from genealogiste_mcp import billets, server
from genealogiste_mcp.contexte import verifier as v
from genealogiste_mcp.gedcom.mapping import read_gedcom
from genealogiste_mcp.models import Source

RECITS = Path(__file__).parent / "fixtures" / "contexte" / "recits"
MESURES = json.loads((RECITS / "MESURES.json").read_text(encoding="utf-8"))
LOT_1, LOT_2 = set(MESURES["ajouts"]["lot_1"]), set(MESURES["ajouts"]["lot_2"])


def _signalements(rapport: dict) -> list[tuple[str, str]]:
    """(phrase, « rubrique[:type[:marqueur]] ») de chaque signalement."""
    out = []
    for r in RUBRIQUES:
        for s in rapport[r]:
            cle = ":".join(x for x in (r, s.get("type") if r == "formulations" else "",
                                       s.get("marqueur", "") if r == "formulations" else "") if x)
            out.append((s["phrase"], cle))
    return out


def _version(cle: str) -> int:
    """Version des listes qui produit ce signalement : 1 (#324), 2 (premier lot #348), 3 (contre-épreuve #348)."""
    parties = cle.split(":")
    marqueur = parties[2] if len(parties) == 3 else ""
    if marqueur in LOT_2:
        return 3
    if marqueur in LOT_1 or (len(parties) > 1 and parties[1] == "hors_section"):
        return 2
    return 1


def test_jeu_de_recits_complet_et_fige():
    noms = {p.stem for p in RECITS.glob("*.md")}
    assert noms == set(MESURES["recits"])
    for cas in CAS:
        assert {f"{cas}.naturel", f"{cas}.fluide", f"{cas}.contre_epreuve"} <= noms, cas
    assert MESURES["version_listes"]["apres"] == v.VERSION_LISTES
    connues = {r.cle for r in v.GENERALISATIONS} | {e.cle for e in v.EVENEMENTS} | {"hors_section:appel", "possessifs"}
    assert LOT_1 | LOT_2 <= connues and not LOT_1 & LOT_2
    ids = [d["id"] for x in MESURES["recits"].values() for d in x["defauts"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("app_contexte", CAS, indirect=True)
def test_mesures_des_recits_generes(app_contexte, request):
    cas = app_contexte.cas
    elements = _elements_du_cas(app_contexte, request, cas)  # inscrit les références au registre, comme /recit
    totaux = {"phrases": 0, "defauts": 0, "detectes_v1": 0, "detectes_lot_1": 0, "detectes": 0, "fausses_alertes": 0}
    for nom, attendu in MESURES["recits"].items():
        if not nom.startswith(cas + "."):
            continue
        texte = (RECITS / f"{nom}.md").read_text(encoding="utf-8")
        rapport = _verifier(app_contexte, texte)
        assert len(v.analyser(texte).phrases) == attendu["phrases"], nom
        signalements = _signalements(rapport)
        expliques = set()
        for d in attendu["defauts"]:
            trouves = {(ph, cle) for ph, cle in signalements if d["extrait"] in ph}
            assert d["extrait"] in texte, (nom, d["id"])
            if d["signale_par"] is None:
                assert not trouves, (nom, d["id"], "défaut déclaré échappé désormais signalé : mettre à jour", trouves)
            else:
                assert {cle for _, cle in trouves} == set(d["signale_par"]), (nom, d["id"], trouves)
                versions = [_version(cle) for _, cle in trouves]
                totaux["detectes_v1"] += min(versions) == 1
                totaux["detectes_lot_1"] += min(versions) <= 2
                totaux["detectes"] += 1
            expliques |= trouves
        fausses = sorted(set(signalements) - expliques)
        assert [list(x) for x in fausses] == attendu["fausses_alertes"], (nom, fausses)
        assert rapport["conforme"] is (not signalements), nom
        totaux["phrases"] += attendu["phrases"]
        totaux["defauts"] += len(attendu["defauts"])
        totaux["fausses_alertes"] += len(fausses)
        # sans élément sourcé : aucune section « Contexte », « contexte à documenter » dans les questions ouvertes
        if not elements:
            assert rapport["contexte"] == "non_documente" and rapport["mesures"]["phrases_contexte"] == 0, nom
        # aucune référence de mémoire : toute référence citée dans « Contexte » est au registre
        assert rapport["references_non_consultees"] == [], nom
        assert rapport["mesures"]["anachronismes"] == 0 and rapport["mesures"]["causalites_non_sourcees"] == 0, nom
    assert totaux == MESURES["totaux"][cas], (cas, totaux)


def test_totaux_publies():
    """Totaux repris dans docs/contexte-historique.md (« Recette du 2026-11-24 »)."""
    t = {k: sum(x[k] for x in MESURES["totaux"].values()) for k in next(iter(MESURES["totaux"].values()))}
    assert t == {"phrases": 156, "defauts": 35, "detectes_v1": 3, "detectes_lot_1": 12, "detectes": 20,
                 "fausses_alertes": 0}
    doc = (Path(__file__).resolve().parents[2] / "docs" / "contexte-historique.md").read_text(encoding="utf-8")
    assert "Recette du 2026-11-24" in doc and "3 défauts sur 35" in doc and "20 sur 35" in doc


# ---------------------------------------------------------------------------------------- listes (#348)

@pytest.mark.parametrize("evenement", v.EVENEMENTS, ids=lambda e: e.cle)
def test_evenement_nomme_exemple_et_contre_exemple(mineur, evenement):  # noqa: F811
    oui = _verifier(mineur, f"## Récit\n\n{evenement.exemple}\n")
    assert (("hors_section", evenement.cle) in {(f["type"], f.get("marqueur")) for f in oui["formulations"]}), oui
    non = _verifier(mineur, f"## Récit\n\n{evenement.contre_exemple}\n")
    assert [f for f in non["formulations"] if f["type"] == "hors_section"] == [], non["formulations"]


def test_listes_348_uniques_et_documentees():
    cles = [e.cle for e in v.EVENEMENTS]
    assert len(cles) == len(set(cles)) and not set(cles) & {r.cle for r in v.GENERALISATIONS + v.CONNECTEURS}
    for e in v.EVENEMENTS:
        assert e.exemple and e.contre_exemple and (e.de is None) == (e.a is None)
    doc = (Path(__file__).resolve().parents[2] / "docs" / "contexte-historique.md").read_text(encoding="utf-8")
    assert f'`VERSION_LISTES = "{v.VERSION_LISTES}"`' in doc and "`EVENEMENTS`" in doc and "`POSSESSIFS`" in doc


# ---------------------------------------------------------------------------------------- limites examinées

NOTES = ("\n## Notes et sources\n\n[2] Registres de population de Billy-Montigny (fictif), Registre de population "
         "1904, f° 88.\n[6] Notice sur la compagnie des mines de Courrières. Plouvier-Dekindt, 1900. PPN 249145197.\n")
ELEMENT = "À la même époque et au même endroit : « Notice sur la compagnie des mines de Courrières » [6]."


@pytest.fixture
def mineur_ref(mineur):  # noqa: F811
    _inscrire(mineur.registre_references, "ppn:249145197",
              titre="Notice sur la compagnie des mines de Courrières : siège social : Billy-Montigny")
    return mineur


def test_limite_possessif_corrigee_par_liste_fermee(mineur):  # noqa: F811
    """« Son départ » désigne l'individu (liste fermée de faits de vie) ; un possessif quelconque, non."""
    out = _verifier(mineur, "## Récit\n\nSon départ fut provoqué par la crise minière.\n")
    assert [c["connecteur"] for c in out["causalites"]] == ["cause_par"]
    out = _verifier(mineur, "## Récit\n\nLa compagnie ferma son puits à cause de la crue.\n")
    assert out["causalites"] == []
    out = _verifier(mineur, "## Récit\n\nLa commune perdit ses habitants en raison de la crise.\n")
    assert out["causalites"] == []
    # limite restante : possessif hors liste
    out = _verifier(mineur, "## Récit\n\nSa trace se perd à cause de la crise.\n")
    assert out["causalites"] == []


def test_limite_evenement_nomme_sans_annee(mineur_ref):
    """Dans « Contexte », l'événement nommé compte pour la portée ; un événement hors liste n'est pas vu."""
    out = _verifier(mineur_ref, f"## Contexte\n\n{ELEMENT[:-5]}, au temps de la Révolution [6].\n" + NOTES)
    assert [h["type"] for h in out["hors_portee"]] == ["periode"] and out["mesures"]["anachronismes"] == 1
    assert out["hors_portee"][0]["annees"] == [[1789, 1799]]
    out = _verifier(mineur_ref, f"## Contexte\n\n{ELEMENT[:-5]}, avant la Grande Guerre [6].\n" + NOTES)
    assert out["hors_portee"] == []  # 1914-1918 : dans la période de vie (1881-1946)
    # limite restante : événement évoqué sans nom de la liste
    out = _verifier(mineur_ref, "## Récit\n\nSuivent deux années de guerre dont l'arbre ne dit rien.\n")
    assert out["conforme"] is True


def test_limite_contexte_hors_section(mineur_ref):
    """Récit ou billet : une référence de contexte appelée hors de « Contexte » est signalée ; pas une source de
    l'arbre, pas une hypothèse ni une question."""
    recit = "En 1904, sa commune est le siège de la compagnie des mines [6] et il y est mineur [2]."
    texte = f"## Récit\n\n{recit}\n\n## Contexte\n\n{ELEMENT}\n" + NOTES
    billet = re.sub(r"^## (.*)$", r"**\1**", texte, flags=re.M)  # forme « billet » : intertitres en gras
    assert "**Contexte**" in billet and "##" not in billet
    for forme in (texte, billet):
        out = _verifier(mineur_ref, forme)
        assert [(f["type"], f["marqueur"]) for f in out["formulations"]] == [("hors_section", "appel [6]")], out
        assert out["mesures"]["part_references_consultees"] == 1.0
    # sans section « Contexte » : la référence du registre suffit à reconnaître la note de contexte
    out = _verifier(mineur_ref, f"## Récit\n\n{recit}\n" + NOTES)
    assert [f["type"] for f in out["formulations"]] == ["hors_section"]
    for ailleurs in ("## Hypothèses\n\nHypothèse : lien avec la compagnie [6], non démontré.",
                     "## Questions ouvertes\n\n- La notice [6] reste à lire.",
                     "## Récit\n\nIl est mineur en 1904 [2]."):
        out = _verifier(mineur_ref, f"{ailleurs}\n\n## Contexte\n\n{ELEMENT}\n" + NOTES)
        assert out["conforme"] is True, (ailleurs, out["formulations"])
    # limite restante : contexte de mémoire dans le récit, sans note ni événement de la liste
    out = _verifier(mineur_ref, "## Récit\n\nIl meurt au cœur d'un autre pays noir [2].\n" + NOTES)
    assert out["conforme"] is True


def test_limite_paraphrase_hors_liste(mineur_ref):
    """Limite assumée : causalité par paraphrase ou juxtaposition, détail de vie inventé."""
    for phrase in ("Rien d'étonnant, dès lors, à le trouver mineur en 1904 [2].",
                   "Il n'aura guère le temps d'exercer ce métier : il est mobilisé [2].",
                   "Il meurt loin des siens [2]."):
        assert _verifier(mineur_ref, f"## Récit\n\n{phrase}\n" + NOTES)["conforme"] is True, phrase


def test_limite_pertinence_d_une_reference_consultee(mineur_ref):
    """Limite assumée : une référence du registre appuie n'importe quel énoncé (le contrôle ne lit pas la source)."""
    out = _verifier(mineur_ref, "## Contexte\n\nÀ la même époque et au même endroit : « La commune de Billy-Montigny "
                                "compte douze forges » [6].\n" + NOTES)
    assert out["conforme"] is True and out["mesures"]["part_references_consultees"] == 1.0


FAUTIF = ("Il émigre à cause de la catastrophe.\n\n**Contexte**\n\nÀ cette époque, beaucoup de mineurs "
          "émigraient.\n")


@pytest.fixture
def gramps_avec_billet_saisi(fixtures):
    """Faux Gramps Web où un billet à section « Contexte » fautive a été saisi dans l'interface (aucune opération du
    plugin : rien n'a pu le contrôler)."""
    arbre = read_gedcom((fixtures / "contexte" / "mineur_artois_oklahoma.ged").read_text(encoding="utf-8"))[0]
    arbre.sources["S9"] = Source(id="S9", titre="Billet saisi dans l'interface", auteur="Équipe fictive",
                                 note=FAUTIF, tags=["Blog"], prive=True)
    assert billets.est_billet(arbre.sources["S9"]) and billets.a_section_contexte(FAUTIF)
    with FakeGrampsWeb() as fake:
        seed(fake, arbre)
        yield fake
    server.set_app(None)


def test_limite_billet_saisi_dans_gramps_web_non_controle(tmp_path, gramps_avec_billet_saisi):
    """Limite assumée (issue de suivi) : backend gramps. Le billet saisi dans l'interface est dans l'arbre et dans
    le miroir (``gramps_synchroniser``) sans être passé par ``contexte_verifier`` ; seul son passage en public par
    le plugin est contrôlé (pas celui fait dans l'interface)."""
    a = make_app(tmp_path, mirror=True)
    lus = [s for s in a.tree().sources.values() if "Blog" in s.tags]
    assert len(lus) == 1 and "à cause de la catastrophe" in lus[0].note
    rapport = v.verifier(billets.texte_markdown(a.tree(), lus[0]), a.tree(), "I1", a.registre_references)
    assert rapport["conforme"] is False and rapport["causalites"] and rapport["phrases_sans_reference"]
    assert "erreur" not in server.gramps_synchroniser()
    miroir = read_gedcom(a.store.text())[0]
    assert [s.id for s in miroir.sources.values() if "Blog" in s.tags] == [lus[0].id]
    r = server.arbre_proposer([{"op": "modifier_source", "id": lus[0].id, "champs": {"prive": False}}], "Public",
                              "Publication (test).")
    assert "erreur" in r and "aucune personne n'est donnée" in r["erreur"]


def test_limite_billet_a_contexte_bloque_gramps_tirer(tmp_path, gramps_avec_billet_saisi, fixtures):
    """Constat de #348 (issue de suivi) : backend fichier. ``gramps_tirer`` passe par les opérations d'import, donc
    par le contrôle des billets, mais sans pouvoir donner ``personne`` : un seul billet à section « Contexte » saisi
    dans Gramps Web fait refuser tout le tirage, que sa section soit conforme ou non."""
    a = make_app(tmp_path, backend="fichier")
    shutil.copy(fixtures / "contexte" / "mineur_artois_oklahoma.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    p = server.gramps_tirer()
    assert "erreur" in p and "Billet S9 refusé" in p["erreur"] and "aucune personne n'est donnée" in p["erreur"]
    assert not [s for s in a.tree().sources.values() if "Blog" in s.tags]
