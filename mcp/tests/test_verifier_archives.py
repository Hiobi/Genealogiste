"""Sondes HTTP des archives : aucun DNS, corps GET interdit, rapport sans écriture."""

import copy
import importlib.util
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verifier_archives.py"
spec = importlib.util.spec_from_file_location("verifier_archives", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
URL = "https://archives.example/"


class CorpsInterdit(httpx.SyncByteStream):
    def __init__(self):
        self.ferme = False

    def __iter__(self):
        raise AssertionError("Le corps GET ne doit jamais être lu")

    def close(self):
        self.ferme = True


@pytest.mark.parametrize("status", [200, 204])
def test_head_reussi_sans_get(status):
    appels = []

    def repondre(request):
        appels.append(request.method)
        return httpx.Response(status)

    with httpx.Client(transport=httpx.MockTransport(repondre)) as client:
        assert verifier.sonder(client, URL) == ("OK", str(status))
    assert appels == ["HEAD"]


@pytest.mark.parametrize("head", [403, 405, 501, httpx.ReadError, httpx.RemoteProtocolError])
@pytest.mark.parametrize("get", [200, 403, 503])
def test_repli_unique_sans_lecture_et_fermeture(head, get):
    appels = []
    corps = CorpsInterdit()
    reponses = []

    def repondre(request):
        appels.append(request.method)
        if request.method == "HEAD":
            if isinstance(head, int):
                return httpx.Response(head)
            raise head("connexion coupée", request=request)
        response = httpx.Response(get, stream=corps)
        reponses.append(response)
        return response

    with httpx.Client(transport=httpx.MockTransport(repondre)) as client:
        assert verifier.sonder(client, URL) == ("OK" if get < 400 else "KO", str(get))
    assert appels == ["HEAD", "GET"]
    assert corps.ferme and reponses[0].is_closed
    assert not reponses[0].is_stream_consumed


@pytest.mark.parametrize("status,headers,verdict", [
    (403, {"cf-mitigated": "challenge"}, "AVERT"),
    (503, {"server": "cloudflare"}, "AVERT"),
    (503, {"server": "Cloudflare"}, "AVERT"),
    (403, {}, "KO"),
    (503, {}, "KO"),
    (404, {"server": "cloudflare"}, "KO"),
    (500, {}, "KO"),
])
def test_statuts_et_protection(status, headers, verdict):
    def repondre(request):
        return httpx.Response(status, headers=headers)

    with httpx.Client(transport=httpx.MockTransport(repondre)) as client:
        resultat, detail = verifier.sonder(client, URL)
    assert resultat == verdict
    assert str(status) in detail


@pytest.mark.parametrize("methode", ["HEAD", "GET"])
@pytest.mark.parametrize("erreur,message,verdict", [
    (httpx.ConnectError, "[SSL: CERTIFICATE_VERIFY_FAILED]", "AVERT"),
    (httpx.ConnectError, "connection refused", "KO"),
    (httpx.ReadTimeout, "timeout", "KO"),
    (httpx.ReadError, "connection reset", "KO"),
    (httpx.RemoteProtocolError, "disconnected", "KO"),
    (httpx.TooManyRedirects, "redirect loop", "KO"),
])
def test_erreurs_http(methode, erreur, message, verdict):
    def repondre(request):
        if methode == "GET" and request.method == "HEAD":
            return httpx.Response(405)
        raise erreur(message, request=request)

    with httpx.Client(transport=httpx.MockTransport(repondre)) as client:
        resultat, detail = verifier.sonder(client, URL)
    assert resultat == verdict
    if verdict == "AVERT":
        assert "TLS" in detail
    else:
        assert detail == erreur.__name__


@pytest.mark.parametrize("status,headers,erreurs,attendu", [
    (200, {}, [], 0),
    (503, {"server": "cloudflare"}, [], 0),
    (404, {}, [], 1),
    (200, {}, ["entrée invalide"], 1),
])
def test_rapport_et_code_sortie_sans_mutation(monkeypatch, capsys, status, headers, erreurs, attendu):
    services = [{"code": "X", "site": URL, "visionneuse": URL + "images",
                 "demande_a_distance": URL + "contact", "verifie_le": "2020-01-01"},
                {"code": "Y"}]
    avant = copy.deepcopy(services)
    referentiel = Path(verifier.archives.__file__).parent / "referentiels" / "archives_fr.json"
    contenu = referentiel.read_bytes()
    appels = []
    creer_client = httpx.Client

    def repondre(request):
        appels.append((request.method, str(request.url)))
        return httpx.Response(status, headers=headers)

    monkeypatch.setattr(verifier.archives, "services", lambda: services)
    monkeypatch.setattr(verifier.archives, "validate", lambda: erreurs)
    monkeypatch.setattr(verifier.httpx, "Client", lambda **kwargs: creer_client(
        transport=httpx.MockTransport(repondre), **kwargs))
    assert verifier.main() == attendu
    rapport = capsys.readouterr().out
    assert all(url in rapport for url in (URL, URL + "images", URL + "contact"))
    assert "VIEUX" in rapport
    assert ("FORMAT" in rapport) == bool(erreurs)
    assert ("AVERT" in rapport) == (status == 503)
    assert services == avant
    assert referentiel.read_bytes() == contenu
    assert len(appels) == 3


@pytest.mark.parametrize("boucle", [False, True])
def test_redirections_get_sans_lire_les_corps_intermediaires(boucle):
    corps = []
    appels = []

    def repondre(request):
        appels.append((request.method, request.url.path))
        if request.method == "HEAD":
            return httpx.Response(405)
        stream = CorpsInterdit()
        corps.append(stream)
        if boucle or request.url.path == "/":
            return httpx.Response(302, headers={"location": "/final"}, stream=stream)
        return httpx.Response(200, stream=stream)

    with httpx.Client(transport=httpx.MockTransport(repondre), follow_redirects=True,
                      max_redirects=2) as client:
        assert verifier.sonder(client, URL) == (("KO", "TooManyRedirects") if boucle else ("OK", "200"))
    assert len(appels) == (4 if boucle else 3)
    assert corps and all(stream.ferme for stream in corps)
