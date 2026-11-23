"""#289 : contexte_local, éléments de contexte sourcés, classés et bornés, sur les quatre cas témoins (#292).

Toutes les réponses rejouées sont des réponses réelles enregistrées (tests/fixtures/contexte/reponses/<service>/,
MANIFESTE.json) ; aucun test n'accède au réseau. Les réponses bibliographiques enregistrées portent sur le bassin
minier du Pas-de-Calais : rejouées pour les autres cas, elles ne doivent y produire aucun élément (lieu non cité).
Wikidata : réponses du gabarit ``evenements_commune`` ; toute autre requête Wikidata reçoit un 429 simulé (refus
constaté le 2026-11-21, issue #289), pour vérifier qu'un service en échec n'arrête pas les autres."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote_plus, urlsplit

import httpx
import pytest
import respx
from test_contexte_protocoles import REPONSES

from genealogiste_mcp import server
from genealogiste_mcp.contexte import index_wikidata as wdi
from genealogiste_mcp.contexte import lieux, local
from genealogiste_mcp.contexte import services as srv
from genealogiste_mcp.contexte.modeles import (
    MENTION_TENDANCE,
    ElementContexte,
    Identifiant,
    Reference,
    SourceElement,
)
from genealogiste_mcp.contexte.portee import LieuDeVie, Periode, controler
from genealogiste_mcp.contexte.requete import residus_identite

COG = Path(__file__).parent / "fixtures" / "cog"
WIKIDATA = REPONSES / "WIKIDATA"
BIBLIO = {"https://api.archives-ouvertes.fr/search/": ("hal", "billy-montigny-mines.json"),
          "https://www.sudoc.abes.fr/cbs/sru/": ("sudoc", "billy-montigny-mines.xml"),
          "https://api.isidore.science/resource/search": ("isidore", "courrieres-mines.json"),
          "https://catalogue.bnf.fr/api/SRU": ("bnf-catalogue", "courrieres-mines.xml"),
          "https://theses.fr/api/v1/theses/recherche/": ("theses-fr", "courrieres-mines.json"),
          "https://api.crossref.org/works": ("crossref", "courrieres-mines.json")}
SRU_GALLICA = "https://gallica.bnf.fr/SRU"


def _csv(*chemins: Path) -> str:
    lignes = [p.read_text(encoding="utf-8").splitlines() for p in chemins]
    return "\n".join([lignes[0][0], *(x for f in lignes for x in f[1:])]) + "\n"


def _csw(request: httpx.Request) -> httpx.Response:
    ident = parse_qs(urlsplit(str(request.url)).query)["ID"][0]
    return httpx.Response(200, text=(REPONSES / "IGN-GEOPLATEFORME" / f"csw_{ident}.xml").read_text(encoding="utf-8"))


def _manifeste_wikidata() -> dict:
    return json.loads((WIKIDATA / "MANIFESTE.json").read_text(encoding="utf-8"))


def _enregistrees() -> dict[str, str]:
    """Requête SPARQL exacte -> fichier de réponse enregistré (gabarit evenements_commune et lieu_historique)."""
    out = {}
    for r in _manifeste_wikidata()["reponses"]:
        q = parse_qs(urlsplit(r["url"]).query).get("query") or [unquote_plus(r["url"].split("query=")[1]
                                                                            .rsplit("&format=", 1)[0])]
        out[q[0]] = r["fichier"]
    return out


def _wikidata(request: httpx.Request) -> httpx.Response:
    q = parse_qs(urlsplit(str(request.url)).query)["query"][0]
    fichier = _enregistrees().get(q)
    if fichier is None:
        return httpx.Response(429, text="Too Many Requests")
    return httpx.Response(200, json=json.loads((WIKIDATA / fichier).read_text(encoding="utf-8")))


@pytest.fixture
def services_enregistres(app):
    with respx.mock(assert_all_called=False) as r:
        r.get(app.config.cog_communes_url).respond(200, text=_csv(REPONSES / "COG-INSEE" / "v_commune_depuis_1943.csv",
                                                                  COG / "communes.csv"))
        r.get(app.config.cog_mvt_url).respond(200, text=_csv(REPONSES / "COG-INSEE" / "v_mvt_commune_2024.csv",
                                                             COG / "mouvements.csv"))
        r.get("https://geo.api.gouv.fr/communes/62133").respond(
            200, json=json.loads((REPONSES / "API-GEO" / "communes_62133.json").read_text()))
        r.get(f"{lieux.MELODI}/catalog/{lieux.JEU_POPULATION}").respond(
            200, json=json.loads((REPONSES / "INSEE-MELODI" / "catalog_DS_POPULATIONS_HISTORIQUES.json").read_text()))
        r.get(f"{lieux.MELODI}/data/{lieux.JEU_POPULATION}", params={"GEO": "2025-COM-62133"}).respond(
            200, json=json.loads((REPONSES / "INSEE-MELODI" / "data_DS_POPULATIONS_HISTORIQUES_GEO_2025-COM-62133.json")
                                 .read_text()))
        r.get(lieux.WMTS, params={"REQUEST": "GetCapabilities"}).respond(
            200, text=(REPONSES / "IGN-GEOPLATEFORME" / "GetCapabilities.xml").read_text(encoding="utf-8"))
        r.get("https://data.geopf.fr/csw").mock(side_effect=_csw)
        r.get(url__startswith=wdi.ENDPOINT).mock(side_effect=_wikidata)
        for base, (dossier, fichier) in BIBLIO.items():
            r.get(url__startswith=base).respond(200, text=(REPONSES / dossier / fichier).read_text(encoding="utf-8"))
        r.get(url__startswith=SRU_GALLICA).respond(
            403, text=(REPONSES / "GALLICA" / "sru-403-cloudflare.html").read_text(encoding="utf-8"),
            headers={"content-type": "text/html; charset=UTF-8"})
        r.route().respond(404)  # toute autre requête : visible dans les appels
        yield r


def _elements(out: dict) -> list[dict]:
    return [x for v in out["elements"].values() for x in v]


def _annees(texte: str) -> int:
    import re
    return int(re.findall(r"\d{4}", texte)[0])


# ---------------------------------------------------------------- gabarits Wikidata (réponses réelles)

def test_gabarits_wikidata_livres_ont_une_reponse_enregistree():
    manifeste = _manifeste_wikidata()
    enregistrees = _enregistrees()
    gabarit = wdi.GABARITS["evenements_commune"]
    for r in manifeste["reponses"]:
        assert (WIKIDATA / r["fichier"]).is_file() and r["statut"] == 200, r
        assert srv.url_autorisee("WIKIDATA", r["url"].split("?")[0] + "?x=1")
        if r["fichier"].startswith("evenements_"):
            contenu = (WIKIDATA / r["fichier"]).read_bytes()
            assert r["empreinte"] == "sha256:" + hashlib.sha256(contenu).hexdigest()
    for code, de, a in (("62133", 1881, 1946), ("62250", 1881, 1946), ("80080", 1892, 1916)):
        assert gabarit.requete(code, de, a) in enregistrees, code  # requête livrée = requête enregistrée
    assert set(wdi.GABARITS) == {r["fichier"].split("_P374_")[0] for r in manifeste["reponses"]
                                 if r["fichier"].startswith("evenements_")}
    assert not set(wdi.NON_LIVRES) & set(wdi.GABARITS)  # un gabarit sans réponse n'est pas livré
    assert manifeste["non_verifie"].count("délai dépassé") == 2  # deux formes essayées, aucune livrée


def test_gabarit_leger_borne_et_sans_rayon():
    q = wdi.GABARITS["evenements_commune"].requete("62133", 1881, 1946)
    assert 'wdt:P374 "62133"' in q and "wdt:P131*" in q and q.rstrip().endswith("LIMIT 50")
    assert "?an0 <= 1946 && ?an1 >= 1881" in q
    assert "around" not in q and "geof:" not in q  # rattachement administratif, jamais un rayon
    for mauvais in (("Billy", 1881, 1946), ("62133", 1946, 1881), ("62133", "1881", 1946)):
        with pytest.raises(ValueError):
            wdi.GABARITS["evenements_commune"].requete(*mauvais)


def test_analyseur_index_reponses_reelles():
    lignes = wdi.analyser(json.loads((WIKIDATA / "evenements_commune_P374_62250.json").read_text()))
    assert len(lignes) == 1
    ligne = lignes[0]
    assert (ligne.qid, ligne.de, ligne.a, ligne.classes) == ("Q108101483", 1940, 1940, ["Q3839081"])
    assert ligne.identifiants() == []  # aucune référence externe dans la réponse : jamais un élément
    assert ligne.liens() == ["https://www.wikidata.org/wiki/Q108101483"]
    for vide in ("evenements_commune_P374_62133.json", "evenements_commune_P374_80080.json"):
        assert wdi.analyser(json.loads((WIKIDATA / vide).read_text())) == []
    for mauvais in ({}, [], {"results": {}}, "texte"):
        with pytest.raises(ValueError):
            wdi.analyser(mauvais)


def _reponse_avec_bnf() -> dict:
    """Réponse réelle de Courrières complétée d'une liaison ``bnf`` (forme d'une valeur P268) : le test vérifie la
    lecture de l'identifiant externe, absent des réponses enregistrées."""
    d = json.loads((WIKIDATA / "evenements_commune_P374_62250.json").read_text())
    d["results"]["bindings"][0]["bnf"] = {"type": "literal", "value": "12345678x"}
    return d


def test_identifiant_externe_de_l_index():
    ligne = wdi.analyser(_reponse_avec_bnf())[0]
    assert [i.cle for i in ligne.identifiants()] == ["ark:ark:/12148/cb12345678x"]
    assert ligne.liens()[0] == "https://catalogue.bnf.fr/ark:/12148/cb12345678x"


# ---------------------------------------------------------------- éléments (unité) : registre, portée, mention

def _collecte(app, lieux_vie=None, periode=(1881, 1946), personne="") -> local.Collecte:
    e = local.Entrees(lieux_vie or [LieuDeVie(commune="Billy-Montigny", departement="Pas-de-Calais", pays="France",
                                              de=1881, a=1904)], Periode(*periode), personne=personne)
    return local.Collecte(e, app.registre_references, "iso690", [])


def _ref(app, titre="Billy-Montigny au coeur de la catastrophe minière de 1906", ppn="123456789",
         inscrire=True) -> Reference:
    ref = Reference(identifiant={"type": "ppn", "valeur": ppn}, nature="secondaire", titre=titre, service="SUDOC",
                    requete="https://www.sudoc.abes.fr/cbs/sru/?x=1", consulte_le="2026-11-23")
    if inscrire:
        app.registre_references.enregistrer(ref, statut=200, reponse=f"<x>{ppn}</x>")
    return ref


def test_source_hors_registre_ecartee(app):
    c = _collecte(app)
    ref = _ref(app, inscrire=False)
    c.proposer("SUDOC", ref, ref.titre, "evenement", "Billy-Montigny", "commune", 1906, 1906)
    assert c.elements == {} and c.ecartes[0]["motif"] == "source absente du registre des références consultées"


def test_controle_de_portee_periode_lieu_et_mention(app):
    c = _collecte(app)
    ref = _ref(app)
    c.proposer("SUDOC", ref, ref.titre, "evenement", "Billy-Montigny", "commune", 1906, 1906)
    c.proposer("SUDOC", ref, ref.titre, "evenement", "Billy-Montigny", "commune", 1871, 1871)  # hors période
    c.proposer("SUDOC", ref, ref.titre, "evenement", "Charleroi", "commune", 1906, 1906)  # hors lieu
    autre = _ref(app, titre="Les houillères du Pas-de-Calais", ppn="987654321")
    c.proposer("SUDOC", autre, autre.titre, "economie", "Pas-de-Calais", "departement", 1906, 1906)
    c.proposer("SUDOC", ref, ref.titre, "evenement", "Pas-de-Calais", "departement", 1906, 1906)  # déjà retenue
    c.proposer("SUDOC", ref, ref.titre, "evenement", "Billy-Montigny", "commune", None, None)  # non daté
    commune, = c.elements["commune"]
    assert "mention" not in commune and commune["rattachement"]["niveau"] == "non_demontre"
    assert "hors des années de la période demandée" in commune["rattachement"]["justification"]
    dep, = c.elements["departement"]
    assert dep["mention"] == MENTION_TENDANCE and dep["rattachement"]["niveau"] == "non_demontre"
    motifs = [x["motif"] for x in c.ecartes]
    assert any("hors de la période de vie" in m for m in motifs) and any("hors des lieux de vie" in m for m in motifs)
    assert "élément non daté par la source" in motifs
    for x in (commune, dep):
        el = ElementContexte.from_dict({k: v for k, v in x.items() if k not in ("mention", "origine")})
        assert controler(el, Periode(1881, 1946), c.entrees.lieux)["retenu"]
        assert app.registre_references.est_consultee(el.source.identifiant)


def test_compatible_meme_commune_meme_periode_jamais_atteste_seul(app):
    c = _collecte(app, periode=(1881, 1946), personne="I1")
    ref = _ref(app)
    c.proposer("SUDOC", ref, ref.titre, "evenement", "Billy-Montigny", "commune", 1890, 1890)
    el, = c.elements["commune"]
    assert el["rattachement"]["niveau"] == "compatible" and el["rattachement"]["citation_arbre"] == ""
    assert "aucune source ne relie l'individu" in el["rattachement"]["justification"]


def test_atteste_seulement_par_une_citation_de_l_arbre(app):
    c = _collecte(app, personne="I1")
    c.citations_arbre = [("liste des victimes, ppn 123456789".casefold(), "Liste fictive, p. 3")]
    ref = _ref(app)
    c.proposer("SUDOC", ref, ref.titre, "evenement", "Billy-Montigny", "commune", 1906, 1906)
    el, = c.elements["commune"]
    assert el["rattachement"] == {"personne": "I1", "niveau": "atteste", "citation_arbre": "Liste fictive, p. 3",
                                  "justification": el["rattachement"]["justification"]}


def test_index_wikidata_retenu_seulement_par_sa_reference_consultee(app):
    c = _collecte(app, lieux_vie=[LieuDeVie(commune="Courrières", departement="Pas-de-Calais", pays="France",
                                            de=1881, a=1946)])
    ligne = wdi.analyser(_reponse_avec_bnf())[0]
    local._ligne_index(c, ligne, "Courrières")
    assert c.elements == {} and c.non_sources[0]["statut"] == "non sourcé"
    assert c.non_sources[0]["identifiants"] == ["ark:ark:/12148/cb12345678x"]
    ref = Reference(identifiant=Identifiant("ark", "ark:/12148/cb12345678x"), nature="index",
                    titre="Notice d'autorité (titre lu dans la notice)", service="BNF-CATALOGUE",
                    requete="https://catalogue.bnf.fr/api/SRU?x=1", consulte_le="2026-11-23")
    app.registre_references.enregistrer(ref, statut=200, reponse="<r>ark:/12148/cb12345678x</r>")
    local._ligne_index(c, ligne, "Courrières")
    el, = c.elements["commune"]
    assert el["enonce"] == ref.titre and el["type"] == "evenement"  # énoncé de la référence, jamais du libellé
    assert el["source"]["identifiant"] == "ark:ark:/12148/cb12345678x"
    sans = wdi.analyser(json.loads((WIKIDATA / "evenements_commune_P374_62250.json").read_text()))[0]
    local._ligne_index(c, sans, "Courrières")
    assert "sans référence externe" in c.ecartes[-1]["motif"]


def test_type_lexical():
    assert local.type_lexical("Billy-Montigny au coeur de la catastrophe minière de 1906") == "evenement"
    assert local.type_lexical("Les houillères du Nord") == "economie"
    assert local.type_lexical("Recensement de 1906") == "demographie"
    assert local.type_lexical("Mémoires d'un village") == "culture"


# ---------------------------------------------------------------- outil sur les cas témoins

def _texte_sortie(out: dict) -> str:
    return json.dumps({"elements": out["elements"], "non_sources": out["non_sources"],
                       "resultat": out["resultat"]}, ensure_ascii=False).lower()


def test_cas_temoin(app_contexte, services_enregistres):
    att = app_contexte.attendus
    out = server.contexte_local(personne=att["personne"])
    assert "erreur" not in out and "refus" not in out, out
    tree = app_contexte.tree()
    naissance, deces = _annees(att["vie"]["naissance"]), _annees(att["vie"]["deces"])
    entrees = local.preparer(tree, att["personne"])
    vie = entrees.periode  # années des faits sourcés (« ABT 1722 » : intervalle de la date)
    assert out["requete"]["periode"] == vie.to_dict() and vie.de <= naissance and vie.a == deces
    # aucun élément sans source au registre, hors période ou hors lieu ; mention au-delà de la commune
    for x in _elements(out):
        el = ElementContexte.from_dict({k: v for k, v in x.items() if k not in ("mention", "origine")})
        assert app_contexte.registre_references.est_consultee(el.source.identifiant), x
        assert controler(el, vie, entrees.lieux)["retenu"], x
        assert x["portee"]["de"] <= vie.a and x["portee"]["a"] >= vie.de, x
        assert (x.get("mention") == MENTION_TENDANCE) == (x["portee"]["echelle"] != "commune"), x
        assert x["rattachement"]["niveau"] in ("compatible", "non_demontre") and x["rattachement"]["justification"]
        assert x["enonce"] and x["source"]["citation"]
    # rien de ce que les attendus interdisent
    sortie, tout = _texte_sortie(out), json.dumps(out, ensure_ascii=False).lower()
    ni = att["ne_doit_pas_contenir"]
    for cle in ("causalites", "phrases_generiques", "anachronismes", "hors_lieu"):
        for phrase in ni[cle]:
            assert phrase.lower() not in tout, (cle, phrase)
    for x in ni["hors_periode"]:
        assert x["element"].lower() not in sortie, x
    # aucune donnée d'identité dans les requêtes émises
    assert services_enregistres.calls, "aucune requête"
    for call in services_enregistres.calls:
        assert residus_identite(str(call.request.url), tree, att["personne"]) == [], str(call.request.url)
    # Wikidata en échec (429) n'empêche pas les autres services
    assert any(s["service"] in ("HAL", "SUDOC") for s in out["services_interroges"])
    if not _elements(out):
        assert out["resultat"] == att["sortie_si_non_documente"] and out["elements"] == {}
        assert out["nb_elements"] == 0 and out["recherche_negative"].startswith(att["sortie_si_non_documente"])


@pytest.mark.parametrize("app_contexte", ["lieu_non_documente"], indirect=True)
def test_lieu_non_documente_sortie_vide_explicite(app_contexte, services_enregistres):
    out = server.contexte_local(personne="I1", echelles="commune,departement,region,nation")
    assert out["resultat"] == app_contexte.attendus["sortie_si_non_documente"] == local.NON_DOCUMENTE
    assert out["elements"] == {} and out["nb_elements"] == 0 and out["non_sources"] == []
    assert out["non_documente"] == ["commune", "departement", "region", "nation"]
    assert "Gascogne" not in json.dumps(out, ensure_ascii=False)


@pytest.mark.parametrize("app_contexte", ["mineur_artois_oklahoma"], indirect=True)
def test_mineur_element_sourcé_et_pays_par_lieu(app_contexte, services_enregistres):
    out = server.contexte_local(personne="I1")
    el, = [x for x in out["elements"]["commune"] if x["enonce"].startswith("Billy-Montigny au coeur")]
    assert el["origine"] == "SUDOC" and el["type"] == "evenement"
    assert el["portee"] == {"lieu": "Billy-Montigny", "echelle": "commune", "de": 1906, "a": 1906, "population": ""}
    assert el["source"]["identifiant"].startswith("ppn:") and el["source"]["nature"] in ("secondaire",
                                                                                        "secondaire_savante")
    # 1906 : après le dernier fait sourcé à Billy-Montigny (1904) : rattachement non démontré
    assert el["rattachement"]["niveau"] == "non_demontre" and "1881-1904" in el["rattachement"]["justification"]
    # une source retenue une seule fois, à l'échelle la plus locale
    sources = [x["source"]["identifiant"] for x in _elements(out)]
    assert len(sources) == len(set(sources))
    # États-Unis : seuls les services couvrant le pays (Crossref, INT) ; ni COG, ni Wikidata, ni Gallica
    for call in services_enregistres.calls:
        url = unquote_plus(str(call.request.url))
        if "Krebs" in url or "Charleroi" in url:
            assert call.request.url.host == "api.crossref.org", url
    assert any(x.get("service") == "CHRONICLING-AMERICA" for x in out["services_ecartes"])
    # Gallica bloqué : en échec, avec la tâche manuelle ; Wikidata interrogé pour la commune (réponse enregistrée)
    assert any(x["service"] == "GALLICA" for x in out["services_en_echec"])
    assert any(x["service"] == "WIKIDATA" and x["lieu"] == "Billy-Montigny" for x in out["services_interroges"])
    assert out["taches_manuelles"]
    # carte de l'état-major (1820-1866) proposée par lieu_historique : hors de la vie, écartée avec son motif
    assert any(x["origine"] == "IGN-GEOPLATEFORME" and "hors de la période" in x["motif"] for x in out["ecartes"])


@pytest.mark.parametrize("app_contexte", ["mineur_artois_oklahoma"], indirect=True)
def test_echec_de_tous_les_services_sans_exception(app_contexte):
    with respx.mock(assert_all_called=False) as r:
        r.route().respond(500)
        out = server.contexte_local(personne="I1")
    assert out["resultat"] == local.NON_DOCUMENTE and out["services_en_echec"] and "erreur" not in out


# ---------------------------------------------------------------- arguments, lieu donné, vivants

def test_lieu_et_periode_donnes(app, services_enregistres):
    out = server.contexte_local(lieu="Billy-Montigny, Pas-de-Calais", periode="1900-1910", echelles="commune")
    assert out["requete"]["depuis_personne"] is False and out["requete"]["periode"] == {"de": 1900, "a": 1910}
    el, = [x for x in out["elements"]["commune"] if x["enonce"].startswith("Billy-Montigny au coeur")]
    assert el["rattachement"] == {"personne": "", "niveau": "compatible", "citation_arbre": "",
                                  "justification": el["rattachement"]["justification"]}
    assert "période demandée (1900-1910)" in el["rattachement"]["justification"]


def test_lieu_hors_de_france_services_couvrant_le_pays(app, services_enregistres):
    out = server.contexte_local(lieu="Krebs, Pittsburg, Oklahoma, États-Unis", periode="1917-1946")
    hotes = {c.request.url.host for c in services_enregistres.calls}
    assert hotes == {"api.crossref.org"}, hotes
    assert out["resultat"] == local.NON_DOCUMENTE


@pytest.mark.parametrize("kwargs, motif", [
    ({}, "préciser personne"),
    ({"lieu": "Lille, Nord"}, "periode obligatoire"),
    ({"lieu": "Lille, Nord", "periode": "vers 1900"}, "AAAA"),
    ({"lieu": "Lille, Nord", "periode": "1900", "echelles": "canton"}, "canton"),
])
def test_arguments_invalides_aucune_requete(app, kwargs, motif):
    with respx.mock(assert_all_called=False) as r:
        route = r.route().respond(200, json={})
        out = server.contexte_local(**kwargs)
    assert motif in out["erreur"] and out["requetes_emises"] == 0 and not route.called


def test_personne_et_lieu_exclusifs(app_famille):
    with respx.mock(assert_all_called=False) as r:
        route = r.route().respond(200, json={})
        out = server.contexte_local(personne="I1", lieu="Lille, Nord")
    assert "personne OU lieu" in out["erreur"] and not route.called


def test_vivant_refuse_sans_requete(app_famille):
    with respx.mock(assert_all_called=False) as r:
        route = r.route().respond(200, json={})
        out = server.contexte_local(personne="I9")
        out_lieu = server.contexte_local(lieu="Lucas MARTIN", periode="1900")
        out_theme = server.contexte_local(lieu="Lille, Nord", periode="1900", themes="Lucas MARTIN")
    assert "refus" in out and "refus" in out_lieu and "refus" in out_theme
    assert not route.called


def test_source_url_relue_par_sa_cle():
    """Socle (#321) : la clé « url:https://… » d'un identifiant url est reconnue, comme les autres clés ; un élément
    sourcé par un jeu de données interrogé par son URL se relit donc (vérificateur)."""
    assert Identifiant.depuis_texte("url:https://api.insee.fr/melodi/data/X?GEO=1").cle == \
        "url:https://api.insee.fr/melodi/data/X?GEO=1"
    ref = Reference(identifiant={"type": "url", "valeur": "https://api.insee.fr/melodi/data/X?GEO=1"},
                    nature="primaire", titre="Jeu", service="INSEE-MELODI",
                    requete="https://api.insee.fr/melodi/data/X?GEO=1", consulte_le="2026-11-23")
    el = ElementContexte(enonce="Jeu : 1 (M, 1975)", type="demographie",
                         portee={"lieu": "Billy-Montigny", "echelle": "commune", "de": 1975},
                         source=SourceElement.depuis_reference(ref))
    assert ElementContexte.from_dict(el.to_dict()).source.identifiant == ref.identifiant.cle


def test_population_sourcee_par_le_jeu_interroge(app, services_enregistres):
    out = server.contexte_local(lieu="Billy-Montigny, Pas-de-Calais", periode="1970-1980", echelles="commune")
    pop, = [x for x in out["elements"]["commune"] if x["origine"] == "INSEE-MELODI"]
    assert pop["type"] == "demographie" and pop["portee"]["de"] == pop["portee"]["a"] == 1975
    assert pop["enonce"] == "Populations municipales de 1968 à 2023 : 8834 (PSDC, 1975)"  # valeurs du jeu, telles quelles
    assert pop["source"]["identifiant"] == ("url:https://api.insee.fr/melodi/data/DS_POPULATIONS_HISTORIQUES"
                                            "?GEO=2025-COM-62133")
    assert app.registre_references.est_consultee(pop["source"]["identifiant"])
    assert "2025-01-01" in pop["source"]["localisation"]
