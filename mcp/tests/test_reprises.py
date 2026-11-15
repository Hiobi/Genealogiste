"""#141 : reprises HTTP plafonnées dans le temps — Retry-After (secondes ou date HTTP) respecté sans bloquer
l'appel d'outil, aucune attente après le dernier essai, délai d'essai borné par le temps restant."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
import respx

from genealogiste_mcp import server
from genealogiste_mcp.cache import Cache
from genealogiste_mcp.config import load_config
from genealogiste_mcp.http import HttpClient, SourceError

URL = "https://archives.exemple.fr/api/vue"


class Horloge:
    def __init__(self):
        self.t = 0.0
        self.attentes: list[float] = []

    def __call__(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.attentes.append(s)
        self.t += s


def client(tmp_path, h: Horloge, **kw) -> HttpClient:
    kw.setdefault("duree_max", 60.0)
    return HttpClient(Cache(tmp_path / "c.sqlite"), "test", sleeper=h.dormir, clock=h, **kw)


@respx.mock
def test_retry_after_long_pas_d_attente(tmp_path):
    h = Horloge()
    route = respx.get(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "3600"}))
    with pytest.raises(SourceError) as e:
        client(tmp_path, h).get(URL, use_cache=False)
    assert route.call_count == 1 and h.attentes == []
    assert e.value.reessayer_apres == 3600


@respx.mock
def test_retry_after_date_http(tmp_path):
    h = Horloge()
    date = format_datetime(datetime.now(UTC) + timedelta(seconds=600), usegmt=True)
    respx.get(URL).mock(return_value=httpx.Response(503, headers={"Retry-After": date}))
    with pytest.raises(SourceError) as e:
        client(tmp_path, h).get(URL, use_cache=False)
    assert 590 <= e.value.reessayer_apres <= 601 and h.attentes == []


@respx.mock
def test_retry_after_date_proche_respectee(tmp_path):
    h = Horloge()
    date = format_datetime(datetime.now(UTC) + timedelta(seconds=5), usegmt=True)
    respx.get(URL).mock(side_effect=[httpx.Response(429, headers={"Retry-After": date}),
                                     httpx.Response(200, json={"ok": 1})])
    assert client(tmp_path, h).get(URL, use_cache=False)[0] == {"ok": 1}
    assert len(h.attentes) == 1 and 3 <= h.attentes[0] <= 6


@respx.mock
def test_pas_d_attente_apres_dernier_essai(tmp_path):
    h = Horloge()
    route = respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(SourceError):
        client(tmp_path, h, max_retries=3).get(URL, use_cache=False)
    assert route.call_count == 3 and len(h.attentes) == 2


@respx.mock
def test_timeouts_repetes_dans_le_plafond(tmp_path):
    h = Horloge()
    delais = []

    def lent(request):
        delais.append(request.extensions["timeout"]["read"])
        h.t += delais[-1]  # le délai d'essai s'écoule entièrement
        raise httpx.ReadTimeout("lent", request=request)

    respx.get(URL).mock(side_effect=lent)
    with pytest.raises(SourceError) as e:
        client(tmp_path, h, timeout=30.0, max_retries=5).get(URL, use_cache=False)
    assert h.t <= 60.0 + 1e-6  # plafond jamais dépassé
    assert delais[0] == 30.0 and delais[-1] < 30.0  # dernier essai borné par le temps restant
    assert "plafond" in str(e.value) or "tentatives" in str(e.value)


@respx.mock
def test_enveloppe_reessayer_apres(app):
    respx.get("https://deces.matchid.io/deces/api/v1/search").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "3600"}))
    r = server.matchid_recherche(nom="Martin")
    assert r["reessayer_apres"] == 3600 and "erreur" in r
    entree = app.journal.entries(statut="erreur")[-1]
    assert "3600" in entree["resume"]
    assert app.sleeps == []


def test_config_reprises_par_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GENEALOGISTE_HTTP_TIMEOUT", "12")
    monkeypatch.setenv("GENEALOGISTE_HTTP_TENTATIVES", "2")
    monkeypatch.setenv("GENEALOGISTE_HTTP_DUREE_MAX", "40")
    cfg = load_config()
    assert (cfg.http_timeout, cfg.http_tentatives, cfg.http_duree_max) == (12.0, 2, 40.0)
    a = server.App(cfg, sleeper=lambda s: None)
    assert (a.http.max_retries, a.http.duree_max) == (2, 40.0)
    monkeypatch.setenv("GENEALOGISTE_HTTP_TENTATIVES", "0")
    with pytest.raises(ValueError, match="GENEALOGISTE_HTTP_TENTATIVES"):
        load_config()
