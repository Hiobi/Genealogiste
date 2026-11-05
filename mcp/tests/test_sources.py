import json

import httpx
import pytest
import respx

from genealogiste_mcp import server
from genealogiste_mcp.http import SourceError


@pytest.fixture
def api(fixtures):
    def load(name):
        p = fixtures / "api" / name
        return p.read_text(encoding="utf-8")
    return load


@respx.mock
def test_matchid_normalized_and_ranked(app, api):
    route = respx.get("https://deces.matchid.io/deces/api/v1/search").mock(
        return_value=httpx.Response(200, text=api("matchid_search.json")))
    r = server.matchid_recherche(nom="Martin", prenom="Jean", ne_vers="vers 1920", lieu_naissance="Rochefort")
    assert route.called
    assert route.calls[0].request.url.params["birthDate"] == "01/01/1918-31/12/1922"
    first = r["resultats"][0]
    assert first["id_externe"] == "abc123" and first["naissance"]["date"] == "12 DEC 1920"
    assert first["deces"]["code_insee"] == "17299" and first["deces"]["age"] == "64y"
    assert first["citation_suggeree"]["type_source"] == "derivee"
    assert r["resultats"][0]["score"] > r["resultats"][1]["score"]
    # journal
    j = server.journal_lister(source="matchid")
    assert j[-1]["statut"] == "positif" and j[-1]["nb_resultats"] == 2


@respx.mock
def test_cache_hit(app, api):
    route = respx.get("https://deces.matchid.io/deces/api/v1/search").mock(
        return_value=httpx.Response(200, text=api("matchid_search.json")))
    server.matchid_recherche(nom="Martin")
    r = server.matchid_recherche(nom="Martin")
    assert route.call_count == 1 and r["depuis_cache"] is True


@respx.mock
def test_backoff_on_429(app, api):
    route = respx.get("https://deces.matchid.io/deces/api/v1/search").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "3"}),
        httpx.Response(429),
        httpx.Response(200, text=api("matchid_search.json")),
    ])
    r = server.matchid_recherche(nom="Martin")
    assert route.call_count == 3 and r["nb_renvoyes"] == 2
    assert 3.0 in app.sleeps  # Retry-After respecté


@respx.mock
def test_negative_search_is_logged(app_famille):
    respx.get("https://deces.matchid.io/deces/api/v1/search").mock(
        return_value=httpx.Response(200, json={"response": {"total": 0, "persons": []}}))
    r = server.matchid_recherche(nom="Zzyzx", personne="I1")
    assert "recherche_negative" in r
    e = server.journal_lister(statut="negatif")[-1]
    assert e["parametres"]["lastName"] == "Zzyzx" and e["personne"] == "I1"


@respx.mock
def test_error_is_logged(app):
    respx.get("https://deces.matchid.io/deces/api/v1/search").mock(return_value=httpx.Response(500, text="boom"))
    r = server.matchid_recherche(nom="Martin")
    assert "erreur" in r and server.journal_lister(statut="erreur")


@respx.mock
def test_cloudflare_block_message(app):
    respx.get("https://gallica.bnf.fr/SRU").mock(return_value=httpx.Response(
        403, text="<html>Attention Required! | Cloudflare</html>"))
    r = server.gallica_recherche("jean martin")
    assert "Cloudflare" in r["erreur"]


@respx.mock
def test_wikitree_search(app, api):
    route = respx.post("https://api.wikitree.com/api.php").mock(
        return_value=httpx.Response(200, text=api("wikitree_search.json")))
    r = server.wikitree_recherche("Martin", "Jean", ne_vers="1820", lieu="Rochefort")
    body = route.calls[0].request.content.decode()
    assert "appId=genealogiste-tests" in body and "action=searchPerson" in body
    top = r["resultats"][0]
    assert top["id_externe"] == "Martin-1" and top["naissance"]["date"] == "12 MAR 1820"
    assert top["deces"]["date"] == "1885"
    assert top["citation_suggeree"]["type_source"] == "composite"


def test_wikitree_requires_appid(app):
    app.config.wikitree_app_id = ""
    r = server.wikitree_profil("Martin-1")
    assert "APPID" in r["erreur"]


@respx.mock
def test_wikitree_ancestors_uses_getpeople(app):
    route = respx.post("https://api.wikitree.com/api.php").mock(return_value=httpx.Response(200, json=[
        {"people": {"1": {"Id": 1, "Name": "Martin-1", "FirstName": "Jean", "LastNameAtBirth": "Martin",
                          "BirthDate": "1820-03-12", "Gender": "Male"}}}]))
    r = server.wikitree_ascendants("Martin-1", 2)
    body = route.calls[0].request.content.decode()
    assert "action=getPeople" in body and "ancestors=2" in body
    assert r["resultats"][0]["prenoms"] == "Jean"


@respx.mock
def test_gallica_sru(app, api):
    route = respx.get("https://gallica.bnf.fr/SRU").mock(return_value=httpx.Response(200, text=api("gallica_sru.xml")))
    r = server.gallica_recherche("jean martin", type_doc="presse", debut="1880", fin="1890")
    q = route.calls[0].request.url.params["query"]
    assert 'gallica adj "jean martin"' in q and 'dc.type all "fascicule"' in q and '>="1880"' in q
    doc = r["resultats"][0]
    assert doc["id_externe"] == "bpt6k1234567x" and doc["iiif_manifest"].endswith("/manifest.json")


def test_gallica_iiif_urls():
    r = server.gallica_iiif("https://gallica.bnf.fr/ark:/12148/bpt6k1234567x/f3.item", 3)
    assert r["image"] == "https://gallica.bnf.fr/iiif/ark:/12148/bpt6k1234567x/f3/full/full/0/native.jpg"


@respx.mock
def test_gallica_text(app):
    respx.get("https://gallica.bnf.fr/ark:/12148/bpt6k1234567x/f2.texteBrut").mock(
        return_value=httpx.Response(200, text="<html><body><p>Décès de Jean MARTIN</p><script>x</script></body></html>"))
    r = server.gallica_texte("bpt6k1234567x", 2)
    assert r["texte"] == "Décès de Jean MARTIN"


@respx.mock
def test_wikidata(app, api):
    respx.get("https://query.wikidata.org/sparql").mock(return_value=httpx.Response(200, text=api("wikidata.json")))
    r = server.wikidata_personne("Hugo", "Victor", ne_vers="1802")
    p = r["resultats"][0]
    assert (p["prenoms"], p["nom"], p["naissance"]["date"]) == ("Victor", "Hugo", "26 FEB 1802")


def test_wikidata_readonly(app):
    assert "lecture" in server.wikidata_sparql("DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }")["erreur"]


@respx.mock
def test_geo_and_cog(app):
    respx.get("https://geo.api.gouv.fr/communes").mock(return_value=httpx.Response(200, json=[
        {"nom": "Rochefort", "code": "17299", "codeDepartement": "17", "codesPostaux": ["17300"],
         "departement": {"nom": "Charente-Maritime"}, "centre": {"coordinates": [-0.96, 45.94]}}]))
    r = server.geo_commune("Rochefort (17)")
    assert r["resultats"][0]["lieu_gedcom"] == "Rochefort, Charente-Maritime, France"
    respx.get(app.config.cog_communes_url).mock(return_value=httpx.Response(200, text=(
        '"COM","TNCC","NCC","NCCENR","LIBELLE","DATE_DEBUT","DATE_FIN"\n'
        '"08371","0","RUBECOURT ET LAMECOURT","Rubécourt-et-Lamécourt","Rubécourt-et-Lamécourt","1943-01-01","2017-01-01"\n'
        '"08053","0","BAZEILLES","Bazeilles","Bazeilles","1943-01-01",""\n')))
    respx.get(app.config.cog_mvt_url).mock(return_value=httpx.Response(200, text=(
        '"MOD","DATE_EFF","TYPECOM_AV","COM_AV","TNCC_AV","NCC_AV","NCCENR_AV","LIBELLE_AV","TYPECOM_AP","COM_AP",'
        '"TNCC_AP","NCC_AP","NCCENR_AP","LIBELLE_AP"\n'
        '"32","2017-01-01","COM","08371","0","X","X","Rubécourt-et-Lamécourt","COMD","08371","0","X","X",'
        '"Rubécourt-et-Lamécourt"\n'
        '"32","2017-01-01","COM","08371","0","X","X","Rubécourt-et-Lamécourt","COM","08053","0","B","B","Bazeilles"\n')))
    h = server.geo_historique("Rubécourt-et-Lamécourt")
    rec = h["resultats"][0]
    assert rec["actuelle"] is False and rec["devenue"] == "Bazeilles (08053)"


def test_living_person_never_sent_outside(app_famille):
    r = server.matchid_recherche(nom="Martin", prenom="Lucas", personne="I9")
    assert "refus" in r


def test_secondary_links(app):
    r = server.liens_recherche("Martin", "Jean", "1890", "Rochefort (17)", "1916")
    sites = {x["site"].split(" ")[0] for x in r["liens"]}
    assert {"Geneanet", "FranceArchives", "Mémoire", "Grand", "Archives"} <= sites
    assert all(x["url"].startswith("https://") for x in r["liens"])


def test_source_collee(app):
    r = server.source_collee("geneanet", "Jean MARTIN x Marie DUPONT 1845 (relevé CGSO)", "https://example.org")
    assert server.journal_lister(source="geneanet")[-1]["id"] == r["journal"]


def test_communicability():
    r = server.communicabilite("naissance", "1950")
    assert r["communicable_a_partir_de"] == 2026 and r["communicable"] is True
    assert server.communicabilite("deces", "2020")["communicable"] is True
    assert server.communicabilite("matricule", date_naissance="1910")["communicable"] is False


def test_tool_registry():
    import asyncio
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    for n in ("matchid_recherche", "wikitree_recherche", "gallica_recherche", "wikidata_sparql", "geo_historique",
              "arbre_proposer", "arbre_appliquer", "journal_lister", "recherche_multi"):
        assert n in names


def test_source_error_class():
    assert SourceError("x", 404).status == 404
    assert json.dumps({"a": 1})
