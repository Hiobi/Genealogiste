"""#290 : pistes_contexte, hypothèses réfutables tirées des faits de l'arbre et du contexte sourcé.

Règle d'inférence vérifiée ici : le contexte oriente une recherche, il ne conclut jamais. Réponses rejouées :
réponses réelles enregistrées (fixture ``services_enregistres`` de test_contexte_local) ; aucun accès réseau."""

from __future__ import annotations

import json
import subprocess

import pytest
import respx
from test_contexte_local import services_enregistres  # noqa: F401  (fixture)

from genealogiste_mcp import outils, server, taches
from genealogiste_mcp.contexte import pistes as pistes_mod
from genealogiste_mcp.contexte.requete import residus_identite
from genealogiste_mcp.enquetes import est_contexte_seul
from genealogiste_mcp.fr_sources import next_source_hint
from genealogiste_mcp.gedcom.mapping import read_gedcom

CAUSALITES = ("à cause", "a cause", "cause de", "causé", "poussé", "pousse", "fuyant", "fuir", "en raison",
              "suite à", "suite a", "par suite", "provoqu", "entraîn", "entrain", "motivé", "conséquence",
              "parce que", "du fait de", "explique", "lié à", "liée à", "dû à", "due à", "afin de", "pour fuir")
CLES_FAIT = ("op", "operations", "operations_par_type", "typage_propose", "jeton")


def _cles(o) -> set[str]:
    if isinstance(o, dict):
        return set(o) | {k for v in o.values() for k in _cles(v)}
    if isinstance(o, list):
        return {k for v in o for k in _cles(v)}
    return set()


def _etat_arbre(app) -> tuple[bytes, str]:
    log = subprocess.run(["git", "-C", str(app.store.path.parent), "log", "--format=%H"], capture_output=True,
                         text=True).stdout
    return app.store.path.read_bytes(), log


def _verifier_piste(p: dict) -> None:
    assert p["statut"] in pistes_mod.STATUTS and p["cout"] in pistes_mod.COUTS, p
    assert p["regle"] in {r["code"] for r in pistes_mod.REGLES}, p
    assert set(p["fondements"]) == {"arbre", "contexte"} and (p["fondements"]["arbre"] or p["fondements"]["contexte"])
    for f in p["fondements"]["arbre"]:
        assert f["uid"] and f["statut"] and f["fait"], f  # identifiant du fait et statut de preuve
    for f in p["fondements"]["contexte"]:
        assert f["source"]["identifiant"] and f["source"]["citation"], f
    texte = p["hypothese"].lower()
    for c in CAUSALITES:
        assert c not in texte, (c, p["hypothese"])
    if p["statut"] == "contexte_seul":
        assert not p["fondements"]["arbre"] and len(p["fondements"]["contexte"]) == 1
        assert p["fondements"]["contexte"][0]["enonce"] in p["hypothese"]  # l'énoncé sourcé, repris tel quel
        assert p["plafond_gps"] == "hypothese" and p["test"]["sources"] == []
        assert "non démontrée" in p["test"]["motif"]
        assert p["depot"]["file"] is None and p["depot"]["motif_file"]  # jamais une proposition
    else:
        assert p["test"]["sources"], p  # source qui confirme ou réfute
        assert not p["fondements"]["contexte"]  # piste tirée des seuls faits de l'arbre


# ---------------------------------------------------------------- cas témoins

def test_cas_temoins(app_contexte, services_enregistres):  # noqa: F811
    att = app_contexte.attendus
    avant = _etat_arbre(app_contexte)
    out = server.pistes_contexte(personne=att["personne"])
    assert "erreur" not in out and "refus" not in out, out
    assert out["nb_pistes"] == len(out["pistes"])
    for p in out["pistes"]:
        _verifier_piste(p)
    tout = json.dumps(out, ensure_ascii=False).lower()
    ni = att["ne_doit_pas_contenir"]
    for cle in ("causalites", "phrases_generiques", "anachronismes", "hors_lieu"):
        for phrase in ni[cle]:
            assert phrase.lower() not in tout, (cle, phrase)
    assert not _cles(out) & set(CLES_FAIT)  # aucune opération d'arbre, ni jeton
    assert _etat_arbre(app_contexte) == avant
    tree = app_contexte.tree()
    for call in services_enregistres.calls:
        assert residus_identite(str(call.request.url), tree, att["personne"]) == [], str(call.request.url)
    if not out["pistes"]:
        assert out["recherche_negative"]


@pytest.mark.parametrize("app_contexte", ["mineur_artois_oklahoma"], indirect=True)
def test_mineur_criteres_d_acceptation(app_contexte, services_enregistres):  # noqa: F811
    out = server.pistes_contexte(personne="I1")
    pistes = {p["regle"]: [] for p in out["pistes"]}
    for p in out["pistes"]:
        pistes[p["regle"]].append(p)
    # H1 : départ entre juillet 1906 et septembre 1917, testée par les sources du parcours émigration
    h1, = pistes["fenetre_depart"]
    assert h1["statut"] == "a_tester" and h1["hypothese"].startswith("Départ de France entre juillet 1906 et ")
    assert "septembre 1917" in h1["hypothese"]
    assert [f["fait"] for f in h1["fondements"]["arbre"]] == ["RESI", "EVEN"]
    assert {f["statut"] for f in h1["fondements"]["arbre"]} == {"hypothese"}
    tree = app_contexte.tree()
    resi = next(e for e in tree.person("I1").evenements if e.type == "RESI")
    attendu = next_source_hint("EMIG", resi.date, resi.lieu)
    assert [s["source"] for s in h1["test"]["sources"]] == [s["source"] for s in attendu]
    assert {s["versant"] for s in h1["test"]["sources"]} == {"france", "etranger"}
    assert any("Registre matricule" in s["source"] for s in h1["test"]["sources"])
    assert any("passagers" in s["source"] for s in h1["test"]["sources"])
    assert all(s.get("avertissement") for s in h1["test"]["sources"] if s["versant"] == "etranger")
    assert h1["cout"] == "a_determiner"  # aucune source de la chaîne déclarée « en ligne »
    # H3 : même métier à l'arrivée, fondée sur l'OCCU sourcé et le premier fait aux États-Unis
    h3, = pistes["meme_metier_a_l_arrivee"]
    assert h3["statut"] == "a_tester" and "États-Unis" in h3["hypothese"] and "mineur" in h3["hypothese"]
    assert [f["fait"] for f in h3["fondements"]["arbre"]] == ["OCCU", "EVEN"]
    assert h3["test"]["sources"] and {s["versant"] for s in h3["test"]["sources"]} == {"etranger"}
    assert any(s["source"].startswith("Recensements") for s in h3["test"]["sources"])
    assert all("cote connue" in s["cote_typique"] or "source à identifier" in s["cote_typique"]
               for s in h3["test"]["sources"])  # aucune cote étrangère inventée
    # H2 : la notice Sudoc de 1906 (Billy-Montigny) donne une piste contexte seul, jamais à tester
    h2, = [p for p in pistes["element_de_contexte"]
           if p["fondements"]["contexte"][0]["enonce"].startswith("Billy-Montigny au coeur")]
    assert h2["statut"] == "contexte_seul" and h2["recoupe_fenetre_depart"] is True
    assert h2["fondements"]["contexte"][0]["source"]["identifiant"].startswith("ppn:")
    assert h2["fondements"]["contexte"][0]["rattachement"]["niveau"] == "non_demontre"
    # aucune piste de contexte ne devient « à tester », « confirmée » ou « réfutée »
    assert {p["statut"] for p in pistes["element_de_contexte"]} == {"contexte_seul"}
    # population et cartes : situent le lieu, pas de piste
    assert all(p["fondements"]["contexte"][0]["origine"] not in pistes_mod.ORIGINES_DESCRIPTIVES
               for p in pistes["element_de_contexte"])
    # dépôt préparé, rien de déposé
    assert h1["depot"]["enquete_noter"]["piste"]["question"] == h1["hypothese"]
    assert h1["depot"]["enquete_noter"]["personnes"] == ["I1"] and "ajouter_tache" in h1["depot"]["file"]
    assert server.propositions_lister("tous")["propositions"] == []


@pytest.mark.parametrize("app_contexte", ["lieu_non_documente"], indirect=True)
def test_lieu_non_documente_aucune_piste(app_contexte, services_enregistres):  # noqa: F811
    out = server.pistes_contexte(personne="I1")
    assert out["pistes"] == [] and out["nb_pistes"] == 0 and out["recherche_negative"]
    assert {r["regle"] for r in out["regles_non_appliquees"]} == {r["code"] for r in pistes_mod.REGLES}
    assert out["contexte"]["resultat"] == "contexte non documenté"


# ---------------------------------------------------------------- statuts tranchés par l'arbre seulement

def _ajouter(app, lignes: str) -> None:
    """Ajoute des événements au cas du mineur, directement dans le GEDCOM de test (avant l'appel)."""
    texte = app.store.path.read_text(encoding="utf-8").replace("0 @S1@ SOUR", lignes + "0 @S1@ SOUR", 1)
    tree = read_gedcom(texte)[0]
    app.store.write(tree)
    app.store.commit("ajout de test")


SOURCE_FORTE = "2 SOUR @S4@\n3 PAGE Pièce n° {n}\n3 QUAY 3\n3 _TYPE originale\n3 _INFO primaire\n"


SOURCE_INDIRECTE = "2 SOUR @S4@\n3 PAGE Pièce n° {n}\n3 _TYPE originale\n3 _INFO secondaire\n3 _PREUVE indirecte\n"
AJOUTS = ("1 IMMI\n2 DATE 1910\n2 PLAC Krebs, Pittsburg, Oklahoma, États-Unis\n{s1}"
          "1 OCCU mineur\n2 DATE 1920\n2 PLAC Krebs, Pittsburg, Oklahoma, États-Unis\n{s2}")


@pytest.mark.parametrize("app_contexte", ["mineur_artois_oklahoma"], indirect=True)
def test_confirmee_par_un_fait_source_de_l_arbre(app_contexte, services_enregistres):  # noqa: F811
    _ajouter(app_contexte, AJOUTS.format(s1=SOURCE_FORTE.format(n=20), s2=SOURCE_FORTE.format(n=21)))
    out = server.pistes_contexte(personne="I1")
    par_regle = {p["regle"]: p for p in out["pistes"]}
    for regle, fait in (("fenetre_depart", "IMMI"), ("meme_metier_a_l_arrivee", "OCCU")):
        p = par_regle[regle]
        assert p["statut"] == "confirmee", p
        tranche, = [f for f in p["fondements"]["arbre"] if f["role"] == "fait sourcé qui tranche"]
        assert tranche["fait"] == fait and tranche["statut"] == "probable" and tranche["citations"]
        assert p["depot"] is None  # déjà tranchée : rien à déposer
    # le contexte, lui, ne tranche jamais
    assert all(p["statut"] == "contexte_seul" for p in out["pistes"] if p["regle"] == "element_de_contexte")


@pytest.mark.parametrize("app_contexte", ["mineur_artois_oklahoma"], indirect=True)
def test_fait_en_hypothese_ne_tranche_pas(app_contexte, services_enregistres):  # noqa: F811
    _ajouter(app_contexte, AJOUTS.format(s1=SOURCE_INDIRECTE.format(n=20), s2=SOURCE_INDIRECTE.format(n=21)))
    out = server.pistes_contexte(personne="I1")
    for p in out["pistes"]:
        if p["regle"] != "element_de_contexte":
            assert p["statut"] == "a_tester", p
            assert not any(f["role"] == "fait sourcé qui tranche" for f in p["fondements"]["arbre"])
    assert not {p["statut"] for p in out["pistes"]} & {"confirmee", "refutee"}


def test_tranche_exige_citation_et_statut_fort():
    class E:
        citations = ["c"]
    assert pistes_mod._tranche({"statut": "probable"}, E())
    assert not pistes_mod._tranche({"statut": "hypothese"}, E())
    E.citations = []
    assert not pistes_mod._tranche({"statut": "confirme"}, E())


def test_piste_de_contexte_jamais_tranchee():
    el = {"enonce": "Notice X", "type": "evenement", "origine": "SUDOC",
          "portee": {"lieu": "Billy-Montigny", "echelle": "commune", "de": 1906, "a": 1906, "population": ""},
          "source": {"identifiant": "ppn:1", "citation": "Notice X. [Consulté le 23 novembre 2026]. PPN 1."},
          "rattachement": {"personne": "I1", "niveau": "compatible", "justification": "…", "citation_arbre": ""}}
    atteste = {**el, "rattachement": {**el["rattachement"], "niveau": "atteste", "citation_arbre": "x"}}
    carte = {**el, "type": "geographie", "origine": "IGN-GEOPLATEFORME", "source": {"identifiant": "url:https://x"}}
    pistes, non = pistes_mod._regle_contexte({"elements": {"commune": [el, atteste, carte]}}, None)
    p, = pistes
    assert p["statut"] == "contexte_seul" and p["hypothese"].endswith(": Notice X")
    assert len(non) == 2 and {"atteste" in x["motif"] or "descriptive" in x["motif"] for x in non} == {True}


# ---------------------------------------------------------------- aucune écriture, avec ou sans dépôt

@pytest.mark.parametrize("app_contexte", ["mineur_artois_oklahoma"], indirect=True)
def test_aucune_ecriture_ni_operation_d_arbre(app_contexte, services_enregistres):  # noqa: F811
    avant = _etat_arbre(app_contexte)
    eid = server.enquete_ouvrir("Pistes du mineur", personnes=["I1"])["id"]
    out = server.pistes_contexte(personne="I1", enquete=eid)  # avec l'enquête (budget, « déjà fait »)
    assert "erreur" not in out and not _cles(out) & set(CLES_FAIT)
    assert _etat_arbre(app_contexte) == avant
    assert server.enquete_etat(eid)["pistes"] == []  # l'outil ne dépose rien lui-même
    # dépôt par l'appelant, par le chemin d'enquete_noter : l'arbre reste inchangé
    for p in out["pistes"]:
        if p["depot"]:
            assert "refus" not in server.enquete_noter(eid, **p["depot"]["enquete_noter"])
    assert len(server.enquete_etat(eid)["pistes"]) == sum(1 for p in out["pistes"] if p["depot"])
    assert _etat_arbre(app_contexte) == avant
    assert server.propositions_lister("tous")["propositions"] == []
    assert not list(app_contexte.file.dir.glob("*.json"))
    assert not list(app_contexte.config.proposals_dir.glob("*.json"))  # aucun jeton d'arbre_proposer


def test_catalogue_collecte_garde_et_budget():
    assert outils.OUTILS["pistes_contexte"] == (outils.RESEAU, outils.COLLECTE)
    assert "pistes_contexte" in outils.GARDE_VIVANTS and "pistes_contexte" in outils.BUDGET_ENQUETE
    assert outils.GARDE_AVANT_BUDGET["pistes_contexte"] == {"personne": "personne", "texte": "themes"}


def test_vivant_refuse_sans_requete(app_famille):
    with respx.mock(assert_all_called=False) as r:
        route = r.route().respond(200, json={})
        out = server.pistes_contexte(personne="I9")
        out_lieu = server.pistes_contexte(lieu="Lucas MARTIN", periode="1900")
    assert "refus" in out and "refus" in out_lieu and not route.called


def test_arguments_invalides_aucune_requete(app):
    with respx.mock(assert_all_called=False) as r:
        route = r.route().respond(200, json={})
        out = server.pistes_contexte()
    assert "erreur" in out and out["requetes_emises"] == 0 and not route.called


def test_lieu_sans_personne_pistes_de_contexte_seulement(app, services_enregistres):  # noqa: F811
    out = server.pistes_contexte(lieu="Billy-Montigny, Pas-de-Calais", periode="1900-1910", echelles="commune")
    assert out["pistes"] and {p["statut"] for p in out["pistes"]} == {"contexte_seul"}
    assert {r["regle"] for r in out["regles_non_appliquees"]} >= {"fenetre_depart", "meme_metier_a_l_arrivee"}
    for p in out["pistes"]:
        _verifier_piste(p)


# ---------------------------------------------------------------- #325 : marqueur contexte_seul dans le dépôt

@pytest.mark.parametrize("app_contexte", ["mineur_artois_oklahoma"], indirect=True)
def test_depot_marque_contexte_seul_et_l_enquete_n_en_fait_jamais_une_tache(app_contexte,
                                                                            services_enregistres):  # noqa: F811
    eid = server.enquete_ouvrir("Pistes du mineur", personnes=["I1"])["id"]
    out = server.pistes_contexte(personne="I1")
    statuts = []
    for p in out["pistes"]:
        if not p["depot"]:
            continue
        piste = p["depot"]["enquete_noter"]["piste"]
        assert piste.get("contexte_seul", False) is (p["statut"] == "contexte_seul")  # marqueur explicite
        assert "erreur" not in server.enquete_noter(eid, **p["depot"]["enquete_noter"])
        statuts.append(p["statut"])
    assert {"a_tester", "contexte_seul"} <= set(statuts)
    etat = server.enquete_etat(eid)
    notees = dict(zip([p["id"] for p in etat["pistes"]], statuts, strict=True))
    assert all(est_contexte_seul(p) is (notees[p["id"]] == "contexte_seul") for p in etat["pistes"])
    seules = [i for i, s in notees.items() if s == "contexte_seul"]
    # opérations de tâches calculées sur l'état réel : sans sélection, puis en désignant chaque piste
    for elements in (None, list(notees)):
        prop = taches.operations_enquete(etat, app_contexte.tree(), elements)
        assert sorted(o["element"] for o in prop["operations"]) == sorted(set(notees) - set(seules))
        assert [x["element"] for x in prop["refuses"]] == seules
    reprise = server.enquete_reprendre(eid)
    assert {p["id"] for p in reprise["pistes_ouvertes"] if p.get("contexte_seul")} == set(seules)
    assert not {x.get("piste") for x in reprise["a_faire"]} & set(seules)
