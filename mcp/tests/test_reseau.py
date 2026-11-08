"""#42 (SSRF), #50 (POST non rejoués), #52 (jeton du transport HTTP)."""

import asyncio

import httpx
import pytest
import respx

from genealogiste_mcp.auth import BearerAuth, bind_problem
from genealogiste_mcp.cache import Cache
from genealogiste_mcp.http import HttpClient, SourceError
from genealogiste_mcp.reseau import DestinationRefusee, NetworkPolicy


@pytest.fixture
def http(tmp_path):
    return HttpClient(Cache(tmp_path / "c.sqlite"), "tests", sleeper=lambda s: None, max_retries=3)


# ---------------------------------------------------------------- politique réseau (#42)

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x", "http://localhost:8080/", "http://10.1.2.3/", "http://192.168.0.1/", "http://172.17.0.2/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://0.0.0.0/",
    "http://224.0.0.1/", "http://100.64.0.1/", "http://interne.example/", "http://metadata.example/",
    "file:///etc/passwd", "ftp://example.org/", "http:///sans-hote",
])
def test_destinations_internes_refusees(url):
    with pytest.raises(DestinationRefusee):
        NetworkPolicy().check(url)


@pytest.mark.parametrize("url", ["https://gallica.bnf.fr/iiif/x/info.json", "http://8.8.8.8/", "https://exemple.fr"])
def test_destinations_publiques_acceptees(url):
    NetworkPolicy().check(url)


def test_exceptions_configurees():
    p = NetworkPolicy(["grampsweb", "localhost:5055"])
    p.check("http://grampsweb/api")
    p.check("http://localhost:5055/api")
    with pytest.raises(DestinationRefusee):
        p.check("http://localhost:5056/api")


def test_nom_non_resolu_laisse_echouer():
    def boom(host, port):
        raise OSError("nxdomain")
    NetworkPolicy(resolver=boom).check("https://inexistant.example/")


@respx.mock
def test_requete_interne_jamais_envoyee(http):
    route = respx.get("http://127.0.0.1/secret").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(SourceError, match="interne"):
        http.get("http://127.0.0.1/secret", use_cache=False)
    assert not route.called


@respx.mock
def test_redirection_vers_interne_refusee(http):
    respx.get("https://public.example/manifest.json").mock(
        return_value=httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}))
    cible = respx.get("http://169.254.169.254/latest/meta-data/").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(SourceError, match="interne"):
        http.get("https://public.example/manifest.json", use_cache=False)
    assert not cible.called


@respx.mock
def test_redirection_publique_suivie(http):
    respx.get("https://a.example/x").mock(return_value=httpx.Response(301, headers={"Location": "/y?z=1"}))
    respx.get("https://a.example/y").mock(return_value=httpx.Response(200, json={"ok": 1}))
    assert http.get("https://a.example/x", params={"q": "v"}, use_cache=False)[0] == {"ok": 1}


@respx.mock
def test_boucle_de_redirections(http):
    respx.get("https://a.example/x").mock(return_value=httpx.Response(302, headers={"Location": "/x"}))
    with pytest.raises(SourceError, match="redirections"):
        http.get("https://a.example/x", use_cache=False)


@respx.mock
@pytest.mark.parametrize("destination", ["https://autre.example/x", "http://a.example/x"])
def test_redirection_ne_transmet_pas_les_secrets(http, destination):
    respx.get("https://a.example/x").mock(
        return_value=httpx.Response(302, headers={"Location": destination}))
    cible = respx.get(destination).mock(return_value=httpx.Response(200, json={}))
    http.get("https://a.example/x", use_cache=False,
             headers={"Authorization": "Bearer jeton-fictif", "Cookie": "session=fictive",
                      "X-Api-Key": "cle-fictive"})
    assert cible.called
    for nom in ("authorization", "cookie", "x-api-key"):
        assert nom not in cible.calls[0].request.headers


@respx.mock
def test_redirection_meme_origine_conserve_auth(http):
    respx.get("https://a.example/x").mock(
        return_value=httpx.Response(302, headers={"Location": "/y"}))
    cible = respx.get("https://a.example/y").mock(return_value=httpx.Response(200, json={}))
    http.get("https://a.example/x", use_cache=False, headers={"Authorization": "Bearer fictif"})
    assert cible.calls[0].request.headers["authorization"] == "Bearer fictif"


@respx.mock
def test_redirection_ne_transmet_pas_cookie_du_client(http):
    http.client.cookies.set("session", "fictive", domain="a.example")
    respx.get("https://a.example/x").mock(
        return_value=httpx.Response(302, headers={"Location": "http://a.example/y"}))
    cible = respx.get("http://a.example/y").mock(return_value=httpx.Response(200, json={}))
    http.get("https://a.example/x", use_cache=False)
    assert "cookie" not in cible.calls[0].request.headers


@respx.mock
def test_redirection_post_ne_transmet_pas_corps_tiers(http):
    respx.post("https://a.example/x").mock(
        return_value=httpx.Response(307, headers={"Location": "https://tiers.example/x"}))
    cible = respx.post("https://tiers.example/x").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(SourceError, match="origine"):
        http.post("https://a.example/x", json={"donnees": "fictives"}, use_cache=False)
    assert not cible.called


@respx.mock
def test_manifeste_iiif_pointant_vers_interne(app):
    """Un manifeste tiers dont le service d'image vise le réseau interne : aucune requête interne."""
    from genealogiste_mcp import server
    respx.get("https://tiers.example/iiif/manifest.json").mock(return_value=httpx.Response(200, json={
        "@context": "http://iiif.io/api/presentation/2/context.json", "@type": "sc:Manifest",
        "sequences": [{"canvases": [{"label": "1", "images": [{"resource": {
            "service": {"@id": "http://10.0.0.5/iiif/img"}}}]}]}]}))
    interne = respx.route(host="10.0.0.5").mock(return_value=httpx.Response(200, json={}))
    r = server.archive_image("https://tiers.example/iiif/manifest.json", 1)
    assert not interne.called
    assert "interne" in r["erreur"]


# ---------------------------------------------------------------- reprises (#50)

@respx.mock
def test_post_non_rejoue_apres_expiration(http):
    route = respx.post("https://deces.matchid.io/deces/api/v1/search/csv").mock(
        side_effect=httpx.ReadTimeout("lent"))
    with pytest.raises(SourceError, match="indéterminé"):
        http.post("https://deces.matchid.io/deces/api/v1/search/csv", data={"a": "1"}, ttl=0, use_cache=False)
    assert route.call_count == 1


@respx.mock
def test_post_non_rejoue_apres_504(http):
    route = respx.post("https://x.example/job").mock(return_value=httpx.Response(504))
    with pytest.raises(SourceError, match="indéterminé"):
        http.post("https://x.example/job", ttl=0, use_cache=False)
    assert route.call_count == 1


@respx.mock
def test_post_rejoue_si_jamais_parti(http):
    route = respx.post("https://x.example/job").mock(side_effect=[httpx.ConnectError("refus"),
                                                                 httpx.Response(429), httpx.Response(200, json={})])
    assert http.post("https://x.example/job", ttl=0, use_cache=False)[0] == {}
    assert route.call_count == 3


@respx.mock
def test_get_rejoue(http):
    route = respx.get("https://x.example/r").mock(side_effect=[httpx.ReadTimeout("lent"), httpx.Response(503),
                                                              httpx.Response(200, json={})])
    assert http.get("https://x.example/r", use_cache=False)[0] == {}
    assert route.call_count == 3


@respx.mock
def test_post_de_lecture_declare_idempotent(http):
    route = respx.post("https://api.wikitree.com/api.php").mock(
        side_effect=[httpx.ReadTimeout("lent"), httpx.Response(200, json=[])])
    http.post("https://api.wikitree.com/api.php", data={}, idempotent=True, use_cache=False)
    assert route.call_count == 2


# ---------------------------------------------------------------- jeton HTTP (#52)

@pytest.mark.parametrize("host,token,sans,ok", [
    ("127.0.0.1", "", "", True), ("localhost", "", "", True), ("::1", "", "", True),
    ("0.0.0.0", "", "", False), ("192.168.1.10", "", "", False),
    ("0.0.0.0", "s3cret", "", True), ("0.0.0.0", "", "1", True),
])
def test_demarrage(host, token, sans, ok):
    assert (bind_problem(host, token, sans) == "") is ok


async def _app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _call(headers):
    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.request", "body": b""}
    scope = {"type": "http", "headers": headers, "method": "POST", "path": "/mcp"}
    asyncio.run(BearerAuth(_app, "s3cret")(scope, receive, send))
    return sent[0]["status"]


def test_jeton_exige():
    assert _call([]) == 401
    assert _call([(b"authorization", b"Bearer faux")]) == 401
    assert _call([(b"authorization", b"Bearer s3cret")]) == 200


def test_lifespan_passe():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])
    asyncio.run(BearerAuth(app, "t")({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]


@respx.mock
def test_cache_control_no_store_respecte(http):
    route = respx.get("https://public.example/metadata").respond(
        200, json={"ok": 1}, headers={"Cache-Control": "private, no-store"})
    assert http.get("https://public.example/metadata")[1] is False
    assert http.get("https://public.example/metadata")[1] is False
    assert route.call_count == 2


@respx.mock
def test_parametres_url_conserves_sans_params_explicitement_fourni(http):
    url = "https://public.example/image?id=123&format=jpeg"
    route = respx.get(url).respond(200, content=b"image fictive")
    data, _ = http.get(url, parse="bytes")
    assert data == "image fictive" and route.call_count == 1
