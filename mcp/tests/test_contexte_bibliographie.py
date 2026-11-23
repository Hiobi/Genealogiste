"""#286 : outil contexte_bibliographie (littérature historique savante, citée et normalisée).

Les services sont simulés par respx avec leurs réponses réelles enregistrées (tests/fixtures/contexte/reponses/) ;
aucun test n'accède au réseau. Cas témoin : commune du bassin minier du Pas-de-Calais, 1880-1914."""

from __future__ import annotations

import json
from urllib.parse import unquote_plus

import httpx
import pytest
import respx
from test_contexte_protocoles import REPONSES

from genealogiste_mcp import server
from genealogiste_mcp.contexte import services as srv
from genealogiste_mcp.contexte.bibliographie import RechercheInvalide, lire_periode, preparer
from genealogiste_mcp.contexte.gabarits import ORDRE
from genealogiste_mcp.contexte.requete import residus_identite

HOTES = {"HAL": "https://api.archives-ouvertes.fr/search/", "ISIDORE": "https://api.isidore.science/resource/search",
         "SUDOC": "https://www.sudoc.abes.fr/cbs/sru/", "BNF-CATALOGUE": "https://catalogue.bnf.fr/api/SRU",
         "THESES-FR": "https://theses.fr/api/v1/theses/recherche/", "CROSSREF": "https://api.crossref.org/works"}
TEMOIN = {"sujet": "mines", "lieu": "Courrières", "periode": "1880-1914"}


def _corps(code: str, cas: str = "courrieres-mines") -> str:
    ext = "xml" if code in ("SUDOC", "BNF-CATALOGUE") else "json"
    return (REPONSES / code.lower() / f"{cas}.{ext}").read_text(encoding="utf-8")


def _vide(code: str) -> str:
    """Réponse sans notice : la réponse négative réelle de HAL ; pour les autres, la réponse enregistrée vidée de
    ses notices (même forme)."""
    if code == "HAL":
        return _corps("HAL", "billy-montigny-mines")
    if code == "ISIDORE":
        d = json.loads(_corps(code))
        d["response"]["replies"]["meta"]["@items"] = "0"
        d["response"]["replies"]["content"] = {}
        return json.dumps(d)
    if code == "THESES-FR":
        return json.dumps({**json.loads(_corps(code)), "totalHits": 0, "theses": []})
    if code == "CROSSREF":
        d = json.loads(_corps(code))
        d["message"].update({"items": [], "total-results": 0})
        return json.dumps(d)
    import re
    t = re.sub(r"<srw:record>.*</srw:record>", "", _corps(code), flags=re.S)
    return re.sub(r"<srw:numberOfRecords>\d+<", "<srw:numberOfRecords>0<", t)


@pytest.fixture
def services_simules():
    with respx.mock(assert_all_called=False) as router:
        routes = {code: router.get(url__startswith=url).respond(200, text=_corps(code)) for code, url in HOTES.items()}
        router.route().respond(599)  # toute autre requête : visible dans les appels, jamais attendue
        router.routes_service = routes
        yield router


def _urls(router) -> list[str]:
    return [str(c.request.url) for c in router.calls]


# ---------------------------------------------------------------- cas témoin

def test_cas_temoin_references_normalisees(app, services_simules):
    r = server.contexte_bibliographie(**TEMOIN)
    assert "erreur" not in r, r
    assert [s["service"] for s in r["services_interroges"]] == list(ORDRE)
    assert r["services_en_echec"] == [] and r["services_ecartes"] == []
    assert r["nb_references"] == len(r["references"]) >= 10
    for ref in r["references"]:
        assert ref["identifiant"]["type"] in ("doi", "ark", "hal", "handle", "ppn")
        assert ref["citation"] and ref["identifiant"]["valeur"] in ref["citation"]
        assert ref["lu"] == "notice_seule" and "[Notice seule, non lu.]" in ref["citation"]
        assert ref["nature"] in ("secondaire_savante", "secondaire", "primaire")
        assert ref["service"] in ORDRE and ref["requete"].startswith("https://") and ref["consulte_le"]
        assert ref["service"] in ref["trouvee_par"]
        assert set(ref) >= {"auteurs", "titre", "publication", "annee", "pages", "evaluation_par_les_pairs", "acces"}
    assert len(services_simules.calls) == len(ORDRE)  # une requête par service


def test_inscription_au_registre_des_references(app, services_simules):
    r = server.contexte_bibliographie(**TEMOIN)
    registre = app.registre_references
    cles = [f"{x['identifiant']['type']}:{x['identifiant']['valeur']}" for x in r["references"]]
    assert all(registre.est_consultee(c) for c in cles)
    assert {x.identifiant.cle for x in registre.lister()} == set(cles)  # rien d'autre n'est inscrit


def test_dedoublonnage_entre_services(app, services_simules):
    r = server.contexte_bibliographie(**TEMOIN)
    tavernier = [x for x in r["references"] if "concession minière" in x["titre"]]
    assert len(tavernier) == 1 and tavernier[0]["trouvee_par"] == ["SUDOC", "BNF-CATALOGUE"]
    cles = [(x["identifiant"]["type"], x["identifiant"]["valeur"]) for x in r["references"]]
    assert len(cles) == len(set(cles))


def test_classement_lieu_et_periode_puis_nature(app, services_simules):
    r = server.contexte_bibliographie(**TEMOIN)
    rangs = [({"demande": 2, "plus_large": 1}.get(x["pertinence"]["lieu"], 0),
              {"contemporaine": 2, "recoupe": 2, "non_precisee": 1}.get(x["pertinence"]["periode"], 0))
             for x in r["references"]]
    assert rangs == sorted(rangs, reverse=True)
    # à pertinence égale, la littérature savante d'abord
    ordre_nature = {"secondaire_savante": 0, "primaire": 1, "secondaire": 2}
    for a, b in zip(r["references"], r["references"][1:], strict=False):
        if (a["pertinence"]["lieu"], a["pertinence"]["periode"]) == (b["pertinence"]["lieu"], b["pertinence"]["periode"]) \
                and a["pertinence"]["periode"] != "contemporaine":
            assert ordre_nature[a["nature"]] <= ordre_nature[b["nature"]], (a["titre"], b["titre"])
    accident = next(x for x in r["references"] if x["identifiant"]["valeur"] == "10.1051/metal/190603120709")
    assert accident["nature"] == "primaire" and accident["pertinence"]["periode"] == "contemporaine"
    hors = [x for x in r["references"] if x["pertinence"]["periode"] == "hors_periode"]
    assert hors and all(r["references"].index(x) > r["references"].index(accident) for x in hors)


def test_notices_hors_sujet_ou_non_textuelles_ecartees(app, services_simules):
    r = server.contexte_bibliographie(**TEMOIN)
    motifs = {(e["service"], e["titre"]): e["motif"] for e in r["notices_ecartees"]}
    assert "non textuel" in motifs[("BNF-CATALOGUE", "[Mines de Courrières] : [photographie]")]
    titres = {x["titre"] for x in r["references"]}
    assert not titres & {t for _, t in motifs}


def test_journal_une_entree_par_requete(app, services_simules):
    r = server.contexte_bibliographie(**TEMOIN)
    lignes = [json.loads(x) for x in app.journal.path.read_text(encoding="utf-8").splitlines() if x.strip()]
    biblio = [x for x in lignes if x["operation"] == "bibliographie"]
    assert {x["source"] for x in biblio} == {c.lower() for c in ORDRE}
    assert {s["journal"] for s in r["services_interroges"]} == {x["id"] for x in biblio}
    for x in biblio:
        assert x["statut"] in ("positif", "negatif") and x["parametres"]["requete"].startswith("https://")


def test_style_evidence_explained(app, services_simules):
    app.config.contexte_style_citation = "evidence_explained"
    r = server.contexte_bibliographie(**TEMOIN)
    assert r["style_citation"] == "evidence_explained"
    iso = server.contexte_bibliographie(**{**TEMOIN, "limite": 5})  # même style : configuration de l'App
    assert iso["references"][0]["citation"] == r["references"][0]["citation"]
    assert "[Consulté le" not in r["references"][0]["citation"]


# ---------------------------------------------------------------- vide, échec, refus

def test_resultat_vide_explicite(app):
    with respx.mock(assert_all_called=False) as router:
        for code, url in HOTES.items():
            router.get(url__startswith=url).respond(200, text=_vide(code))
        r = server.contexte_bibliographie(sujet="mines", lieu="Billy-Montigny", periode="1880-1914")
    assert r["references"] == [] and r["nb_references"] == 0
    assert "contexte non documenté" in r["recherche_negative"]
    assert "erreur" not in r and len(r["services_interroges"]) == len(ORDRE)
    lignes = [json.loads(x) for x in app.journal.path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert [x["statut"] for x in lignes if x["operation"] == "bibliographie"] == ["negatif"] * len(ORDRE)
    assert app.registre_references.lister() == []


def test_echec_d_un_service_les_autres_repondent(app):
    with respx.mock(assert_all_called=False) as router:
        for code, url in HOTES.items():
            route = router.get(url__startswith=url)
            if code == "HAL":
                route.respond(500, text="panne")
            elif code == "SUDOC":
                route.respond(200, text="pas du XML")
            else:
                route.respond(200, text=_corps(code))
        r = server.contexte_bibliographie(**TEMOIN)
    assert {e["service"] for e in r["services_en_echec"]} == {"HAL", "SUDOC"}
    assert all(e["journal"] for e in r["services_en_echec"])
    assert {s["service"] for s in r["services_interroges"]} == set(ORDRE) - {"HAL", "SUDOC"}
    assert r["references"] and "erreur" not in r
    assert not {x["service"] for x in r["references"]} & {"HAL", "SUDOC"}
    lignes = [json.loads(x) for x in app.journal.path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert {x["source"] for x in lignes if x["statut"] == "erreur"} == {"hal", "sudoc"}


def test_tous_les_services_en_echec(app):
    with respx.mock(assert_all_called=False) as router:
        router.route().respond(500, text="panne")
        r = server.contexte_bibliographie(**{**TEMOIN, "services": ["HAL", "CROSSREF"]})
    assert "erreur" in r and r["references"] == [] and len(r["services_en_echec"]) == 2


def test_services_ecartes_sans_requete(app):
    with respx.mock(assert_all_called=False) as router:
        route = router.route().respond(200, json={})
        r = server.contexte_bibliographie(**{**TEMOIN, "services": ["GALLICA", "WIKIPEDIA", "PERSEE", "NAKALA",
                                                                    "INCONNU", "EUROPEANA"]})
    assert not route.called and r["services_interroges"] == []
    motifs = {e["service"]: e["motif"] for e in r["services_ecartes"]}
    assert "lien_seulement" in motifs["GALLICA"]
    assert "Wikipédia n'est pas une source" in motifs["WIKIPEDIA"]
    assert "pas d'analyseur bibliographique" in motifs["PERSEE"] and "oai-pmh" in motifs["PERSEE"]
    assert "pas d'analyseur bibliographique" in motifs["NAKALA"]
    assert "inconnu" in motifs["INCONNU"]
    assert "désactivé" in motifs["EUROPEANA"]  # clé requise et non activé par défaut
    assert r["recherche_negative"]


def test_service_desactive_et_hors_ligne(app, services_simules):
    app.config.contexte_services = ("HAL",)
    r = server.contexte_bibliographie(**{**TEMOIN, "services": ["HAL", "CROSSREF"]})
    assert [s["service"] for s in r["services_interroges"]] == ["HAL"]
    assert "désactivé" in r["services_ecartes"][0]["motif"]
    assert [s["service"] for s in server.contexte_bibliographie(**TEMOIN)["services_interroges"]] == ["HAL"]
    app.config.offline = True
    appels = len(services_simules.calls)
    r = server.contexte_bibliographie(**{**TEMOIN, "sujet": "houille"})
    assert len(services_simules.calls) == appels and "hors ligne" in r["services_ecartes"][0]["motif"]


@pytest.mark.parametrize("kwargs,motif", [
    ({}, "préciser au moins"),
    ({"lieu": "Courrières", "periode": "vers 1900"}, "periode"),
    ({"lieu": "Courrières", "periode": "1914-1880"}, "antérieure"),
    ({"lieu": "Courrières", "echelle": "monde"}, "echelle"),
    ({"lieu": "Courrières", "limite": 0}, "limite"),
])
def test_arguments_invalides_aucune_requete(app, kwargs, motif):
    with respx.mock(assert_all_called=False) as router:
        route = router.route().respond(200, json={})
        r = server.contexte_bibliographie(**kwargs)
    assert motif in r["erreur"] and r["requetes_emises"] == 0 and not route.called


def test_limite_plafonnee_et_periode():
    assert preparer(lieu="X", limite=500).recherche.limite == 25
    assert lire_periode("1880 – 1914").to_dict() == {"de": 1880, "a": 1914}
    assert lire_periode("1906").to_dict() == {"de": 1906, "a": 1906}
    with pytest.raises(RechercheInvalide):
        lire_periode("XIXe")


def test_hotes_du_referentiel_seulement(app, services_simules):
    server.contexte_bibliographie(**TEMOIN)
    for url in _urls(services_simules):
        assert any(srv.url_autorisee(code, url) for code in ORDRE), url


# ---------------------------------------------------------------- personne : vivants et confidentialité

@pytest.mark.parametrize("app_contexte", ["mineur_artois_oklahoma"], indirect=True)
def test_requete_depuis_la_personne_sans_identite(app_contexte, services_simules):
    tree = app_contexte.store.load()
    r = server.contexte_bibliographie(personne="I1")
    assert "erreur" not in r and "refus" not in r, r
    q = r["requete"]
    assert q["depuis_personne"] and q["lieux"] == ["Billy-Montigny", "Denain", "Krebs"]
    assert q["sujet"] == "mineur" and q["metiers"] == ["mineur"]
    assert q["periode"] == {"de": 1881, "a": 1946}
    urls = _urls(services_simules)
    assert urls
    for url in urls:
        assert residus_identite(url, tree, "I1") == [], url
        assert "wattecamps" not in unquote_plus(url).lower() and "anselme" not in unquote_plus(url).lower()
    # le prénom seul peut figurer dans une notice réelle (un témoin de 1906 s'appelle Anselme) : seul le nom est
    # vérifié dans la sortie et le journal ; les URL émises ne contiennent ni l'un ni l'autre (ci-dessus)
    assert "wattecamps" not in json.dumps(r, ensure_ascii=False).lower()
    assert "wattecamps" not in app_contexte.journal.path.read_text(encoding="utf-8").lower()
    for ligne in app_contexte.journal.path.read_text(encoding="utf-8").splitlines():
        assert residus_identite(json.loads(ligne)["parametres"].get("requete", ""), tree, "I1") == []


@pytest.mark.parametrize("app_contexte", ["mineur_artois_oklahoma"], indirect=True)
def test_echelle_departement_depuis_la_personne(app_contexte, services_simules):
    r = server.contexte_bibliographie(personne="I1", echelle="departement", sujet="houillères")
    assert r["requete"]["lieux"] == ["Pas-de-Calais", "Nord"] and r["requete"]["sujet"] == "houillères"
    assert r["requete"]["echelle"] == "departement"


@pytest.mark.parametrize("app_contexte", ["mineur_artois_oklahoma"], indirect=True)
def test_sujet_contenant_le_nom_de_la_personne_jamais_envoye(app_contexte, services_simules):
    r = server.contexte_bibliographie(personne="I1", sujet="Wattecamps mineur")
    assert len(services_simules.calls) == 0
    assert {e["service"] for e in r["services_en_echec"]} == set(ORDRE)
    assert all("élément d'identité" in e["erreur"] for e in r["services_en_echec"])


def test_personne_vivante_refusee(app_famille):
    with respx.mock(assert_all_called=False) as router:
        route = router.route().respond(200, json={})
        par_id = server.contexte_bibliographie(personne="I9", lieu="Lille")
        par_sujet = server.contexte_bibliographie(sujet="Lucas MARTIN", lieu="Lille")
    assert "refus" in par_id and "refus" in par_sujet and not route.called


def test_personne_inconnue_refusee(app):
    assert "refus" in server.contexte_bibliographie(personne="I404", lieu="Lille")


# ---------------------------------------------------------------- mailto et clés

def test_mailto_jamais_journalise_ni_renvoye(app, services_simules):
    app.config.crossref_mailto = "chercheur@exemple.fr"
    r = server.contexte_bibliographie(**{**TEMOIN, "services": ["CROSSREF"]})
    envoyee = [u for u in _urls(services_simules) if "crossref" in u]
    assert envoyee and "mailto=chercheur%40exemple.fr" in envoyee[0]  # choix explicite de l'utilisateur
    assert "chercheur@exemple.fr" not in json.dumps(r, ensure_ascii=False)
    assert "mailto=%2A%2A%2A" in r["services_interroges"][0]["requete"] or "***" in r["services_interroges"][0]["requete"]
    for fichier in (app.journal.path, app.config.references_consultees_path):
        assert "chercheur@exemple.fr" not in fichier.read_text(encoding="utf-8")
        assert "chercheur%40exemple.fr" not in fichier.read_text(encoding="utf-8")


def test_echec_avec_mailto_masque(app):
    app.config.crossref_mailto = "chercheur@exemple.fr"
    with respx.mock(assert_all_called=False) as router:
        router.get(url__startswith=HOTES["CROSSREF"]).mock(
            side_effect=lambda req: httpx.Response(400, text=f"mauvaise requête {req.url}"))
        r = server.contexte_bibliographie(**{**TEMOIN, "services": ["CROSSREF"]})
    assert r["services_en_echec"] and "chercheur" not in json.dumps(r, ensure_ascii=False)
    assert "chercheur" not in app.journal.path.read_text(encoding="utf-8")



def test_masquer_cles_forme_encodee(config):
    config.crossref_mailto = "chercheur@exemple.fr"
    for texte in ("mailto=chercheur@exemple.fr", "mailto=chercheur%40exemple.fr", "mailto=chercheur%40EXEMPLE.fr"):
        assert srv.masquer_cles(texte, config) == "mailto=***", texte
