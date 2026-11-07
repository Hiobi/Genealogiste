"""Régressions de relecture et de reprise Gramps (#83), données fictives."""

import json

import httpx
import pytest
from gramps_fake import URL, FakeGrampsWeb
from test_gramps_backend import seed

from genealogiste_mcp.gramps.backend import GitMirror, GrampsBackend
from genealogiste_mcp.gramps.client import GrampsClient, GrampsError
from genealogiste_mcp.tree.store import TreeStore


@pytest.fixture
def fake(tree):
    with FakeGrampsWeb() as fake:
        seed(fake, tree)
        yield fake


@pytest.mark.parametrize("bulk", [False, True])
def test_same_second_edit_and_true_counts(fake, monkeypatch, bulk):
    client = GrampsClient(URL, "sosa", "secret")
    db = client.load_all()
    person = fake.find("Person", "I1")
    # Même seconde pour toute la classe ; aucun changement d'horodatage à l'édition.
    for obj in fake.objects["Person"].values():
        obj["change"] = person["change"]
    db = client.load_all()
    if bulk:
        monkeypatch.setattr("genealogiste_mcp.gramps.client.REFETCH_LIMIT", 0)
    person["primary_name"]["first_name"] = "Jean-Pierre"
    updated, report = client.refresh(db)
    assert updated.get("Person", person["handle"])["primary_name"]["first_name"] == "Jean-Pierre"
    assert db.get("Person", person["handle"])["primary_name"]["first_name"] == "Jean"
    assert report == {"Person": {"modifies": 1, "supprimes": 0}}
    assert client.refresh(updated)[1] == {}  # les relectures seules ne sont pas des modifications


@pytest.mark.parametrize("failure", [502, 503, 504, httpx.ReadError])
def test_read_retry(fake, failure):
    sleeps = []
    client = GrampsClient(URL, "sosa", "secret", sleeper=sleeps.append)
    responses = [failure, 200]

    def reply(request, **kwargs):
        result = responses.pop(0)
        if result == 200:
            return httpx.Response(200, json=[])
        if isinstance(result, int):
            return httpx.Response(result)
        raise result("panne", request=request)

    route = fake.router.routes[-2]
    route.side_effect = reply
    assert client.list("Tag") == []
    assert route.call_count == 2 and sleeps == [2]


@pytest.mark.parametrize("failure", [503, httpx.ReadError])
def test_read_retries_are_bounded(fake, failure):
    sleeps = []
    client = GrampsClient(URL, "sosa", "secret", sleeper=sleeps.append)

    def reply(request, **kwargs):
        if isinstance(failure, int):
            return httpx.Response(failure)
        raise failure("panne", request=request)

    route = fake.router.routes[-2]
    route.side_effect = reply
    with pytest.raises(GrampsError):
        client.list("Tag")
    assert route.call_count == 3 and sleeps == [2, 4]


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
@pytest.mark.parametrize("failure", [401, 503, httpx.ReadError])
def test_write_never_replayed(fake, method, failure):
    sleeps = []
    client = GrampsClient(URL, "sosa", "secret", sleeper=sleeps.append)

    def reply(request, **kwargs):
        if isinstance(failure, int):
            return httpx.Response(failure)
        raise failure("réponse perdue après écriture", request=request)

    route = fake.router.request(method, URL + "/api/test/").mock(side_effect=reply)
    if isinstance(failure, int):
        assert client.request(method, "/test/", json={}).status_code == failure
    else:
        with pytest.raises(GrampsError):
            client.request(method, "/test/", json={})
    assert route.call_count == 1 and sleeps == []


def test_read_401_renews_once_then_transport_retry(fake):
    client = GrampsClient(URL, "sosa", "secret", sleeper=lambda _: None)
    replies = [httpx.Response(401), httpx.ReadError("coupure"), httpx.Response(200, json=[])]
    route = fake.router.routes[-2]
    route.side_effect = replies
    assert client.list("Tag") == []
    assert route.call_count == 3
    assert fake.router.routes[0].call_count == 1  # connexion initiale seulement
    assert fake.router.routes[1].call_count == 1  # renouvellement


def test_mirror_keeps_external_report(fake, tmp_path):
    store = TreeStore(tmp_path / "donnees")
    backend = GrampsBackend(GrampsClient(URL, "sosa", "secret"), tmp_path / "donnees",
                            tmp_path / "propositions", ttl=0, mirror=GitMirror(store))
    backend.load(fresh=True)
    fake.ui_edit("Person", "I1", lambda p: p["primary_name"].update(first_name="Jean-Pierre"))
    backend.snapshot(fresh=True)
    report = {"Person": {"modifies": 1, "supprimes": 0}}
    assert backend.last_refresh == report
    assert json.dumps(report, ensure_ascii=False) in store.log(1)[0]["message"]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500])
def test_permanent_read_errors_not_retried(fake, status):
    sleeps = []
    client = GrampsClient(URL, "sosa", "secret", sleeper=sleeps.append)
    route = fake.router.routes[-2]
    route.side_effect = lambda request, **kwargs: httpx.Response(status)
    with pytest.raises(GrampsError):
        client.list("Tag")
    assert route.call_count == (2 if status == 401 else 1)
    assert sleeps == []


def test_expired_access_token_uses_refresh(fake):
    client = GrampsClient(URL, "sosa", "secret")
    client.list("Tag")
    client._exp = 0
    client.list("Tag")
    assert fake.router.routes[0].call_count == 1
    assert fake.router.routes[1].call_count == 1


def test_explicit_call_after_write_401_renews_token(fake):
    client = GrampsClient(URL, "sosa", "secret")
    route = fake.router.post(URL + "/api/test/").mock(side_effect=[httpx.Response(401), httpx.Response(200)])
    assert client.request("POST", "/test/").status_code == 401
    assert route.call_count == 1 and fake.router.routes[1].call_count == 0
    assert client.request("POST", "/test/").status_code == 200
    assert route.call_count == 2 and fake.router.routes[1].call_count == 1
