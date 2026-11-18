"""#211 lot A : créneau par hôte réservé atomiquement dans le cache SQLite (partagé entre processus) et
ralentissement durable d'un hôte après 429/502/503/504, persistant pour la journée."""

from __future__ import annotations

import sqlite3
import time
from datetime import date

import httpx
import pytest
import respx

from genealogiste_mcp import diagnostic, server
from genealogiste_mcp.cache import Cache
from genealogiste_mcp.http import ANTI_REBOND, HttpClient, SourceError

URL = "https://archives.exemple.fr/api/vue"
HOTE = "archives.exemple.fr"


class Horloge:
    """Horloge murale simulée partagée entre clients : dormir fait avancer le temps, sans vraie attente."""

    def __init__(self, t: float = 1_000_000.0):
        self.t = t
        self.attentes: list[float] = []

    def __call__(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.attentes.append(round(s, 6))
        self.t += s


def client(chemin, h: Horloge, jour=None, cache: Cache | None = None, **kw) -> HttpClient:
    kw.setdefault("min_intervals", {HOTE: 2.0})
    kw.setdefault("max_retries", 1)
    return HttpClient(cache or Cache(chemin), "test", sleeper=h.dormir, clock=h, horloge_murale=h,
                      jour=jour or (lambda: date(2026, 11, 17)), **kw)


# ---------------------------------------------------------------------------- créneau partagé

def test_deux_clients_partagent_le_creneau(tmp_path):
    """Deux processus (deux Cache sur le même fichier) : le second attend le créneau réservé par le premier."""
    h = Horloge()
    a, b = client(tmp_path / "c.sqlite", h), client(tmp_path / "c.sqlite", h)
    a._throttle(HOTE)
    assert h.attentes == []
    b._throttle(HOTE)
    assert h.attentes == [2.0]
    a._throttle(HOTE)  # le créneau suivant tient compte de celui de b
    assert h.attentes == [2.0, 2.0]


def test_reservations_successives_sans_attente_entre_deux(tmp_path):
    """Deux réservations quasi simultanées (avant toute attente) : créneaux espacés, pas superposés."""
    h = Horloge()
    a, b = client(tmp_path / "c.sqlite", h), client(tmp_path / "c.sqlite", h)
    c = Cache(tmp_path / "c.sqlite")
    s1 = c.reserver_creneau(HOTE, 2.0, h())
    s2 = c.reserver_creneau(HOTE, 2.0, h())
    assert s2 - s1 == pytest.approx(2.0)
    assert a and b


def test_autres_hotes_independants(tmp_path):
    h = Horloge()
    a = client(tmp_path / "c.sqlite", h, min_intervals={HOTE: 2.0, "autre.exemple": 2.0})
    b = client(tmp_path / "c.sqlite", h, min_intervals={HOTE: 2.0, "autre.exemple": 2.0})
    a._throttle(HOTE)
    b._throttle("autre.exemple")
    assert h.attentes == []


def test_creneau_ecoule_pas_d_attente(tmp_path):
    h = Horloge()
    a, b = client(tmp_path / "c.sqlite", h), client(tmp_path / "c.sqlite", h)
    a._throttle(HOTE)
    h.t += 5
    b._throttle(HOTE)
    assert h.attentes == []


def test_horloge_reculee_pas_d_attente_absurde(tmp_path):
    """Un créneau enregistré très loin dans le futur (horloge reculée) est ignoré, pas d'attente d'une heure."""
    h = Horloge()
    c = Cache(tmp_path / "c.sqlite")
    c.reserver_creneau(HOTE, 2.0, h() + 7200)
    client(tmp_path / "c.sqlite", h)._throttle(HOTE)
    assert h.attentes == []


def test_sqlite_verrouille_repli_memoire(tmp_path):
    """Verrou SQLite tenu par un autre processus : attente bornée puis repli sur le créneau en mémoire."""
    chemin = tmp_path / "c.sqlite"
    h = Horloge()
    cache = Cache(chemin)
    cache.attente_creneau = 0.05
    http = client(chemin, h, cache=cache)
    autre = sqlite3.connect(str(chemin), timeout=0.1)
    autre.execute("BEGIN IMMEDIATE")
    try:
        debut = time.monotonic()
        http._throttle(HOTE)
        http._throttle(HOTE)
        assert time.monotonic() - debut < 2.0
        assert h.attentes == [2.0]  # le repli mémoire espace quand même les requêtes du processus
    finally:
        autre.rollback()
        autre.close()


def test_sans_cache_repli_memoire():
    h = Horloge()
    http = HttpClient(None, "test", sleeper=h.dormir, clock=h, horloge_murale=h, min_intervals={HOTE: 2.0})
    http._throttle(HOTE)
    http._throttle(HOTE)
    assert h.attentes == [2.0]


# ---------------------------------------------------------------------------- ralentissement durable

@respx.mock
@pytest.mark.parametrize("statut", [429, 502, 503, 504])
def test_ralentissement_persiste_et_partage(tmp_path, statut):
    h = Horloge()
    respx.get(URL).mock(return_value=httpx.Response(statut))
    a = client(tmp_path / "c.sqlite", h)
    with pytest.raises(SourceError) as exc:
        a.get(URL, use_cache=False)
    assert "ralenti" in str(exc.value) and exc.value.intervalle == 4.0
    b = client(tmp_path / "c.sqlite", h)  # autre processus, même cache
    assert b.intervalle(HOTE) == 4.0
    h.t += 100
    b._throttle(HOTE)
    attentes = list(h.attentes)
    b._throttle(HOTE)
    assert h.attentes[len(attentes):] == [4.0]


@respx.mock
def test_ralentissement_cumule_jusqu_au_plafond(tmp_path):
    h = Horloge()
    respx.get(URL).mock(return_value=httpx.Response(503))
    a = client(tmp_path / "c.sqlite", h, ralentissement_max=10.0)
    vus = []
    for _ in range(5):
        with pytest.raises(SourceError):
            a.get(URL, use_cache=False)
        vus.append(a.intervalle(HOTE))
        h.t += ANTI_REBOND  # épisodes de surcharge distincts
    assert vus == [4.0, 8.0, 10.0, 10.0, 10.0]


@respx.mock
def test_anti_rebond_rafale_un_seul_doublement(tmp_path):
    """Rafale d'erreurs (requêtes parallèles d'autres processus, reprises) dans la fenêtre : un seul
    doublement ; les incidents sont comptés et l'erreur porte toujours l'intervalle courant."""
    h = Horloge()
    respx.get(URL).mock(return_value=httpx.Response(503))
    a = client(tmp_path / "c.sqlite", h)
    b = client(tmp_path / "c.sqlite", h)  # autre processus, même cache
    for c in (a, b, a, b):
        with pytest.raises(SourceError) as exc:
            c.get(URL, use_cache=False)
        assert exc.value.intervalle == 4.0 and "ralenti" in str(exc.value)
    etat = a.cache.ralentissements("2026-11-17")[HOTE]
    assert etat["facteur"] == 2.0 and etat["incidents"] == 4 and etat["dernier_statut"] == 503


@respx.mock
def test_anti_rebond_reprises_d_un_meme_appel(tmp_path):
    h = Horloge()
    respx.get(URL).mock(return_value=httpx.Response(429))
    a = client(tmp_path / "c.sqlite", h, max_retries=4)
    with pytest.raises(SourceError):
        a.get(URL, use_cache=False)
    assert a.intervalle(HOTE) == 4.0
    assert a.cache.ralentissements("2026-11-17")[HOTE]["incidents"] == 4


@respx.mock
def test_anti_rebond_fenetre_ecoulee_double_de_nouveau(tmp_path):
    h = Horloge()
    respx.get(URL).mock(return_value=httpx.Response(503))  # 503 : pas d'échec mémorisé, chaque appel part
    a = client(tmp_path / "c.sqlite", h)
    with pytest.raises(SourceError):
        a.get(URL, use_cache=False)
    debut = h.t
    h.t = debut + ANTI_REBOND - 1
    with pytest.raises(SourceError):
        a.get(URL, use_cache=False)
    assert a.intervalle(HOTE) == 4.0
    h.t = debut + ANTI_REBOND  # la fenêtre court depuis le dernier doublement, pas depuis le dernier incident
    with pytest.raises(SourceError):
        a.get(URL, use_cache=False)
    assert a.intervalle(HOTE) == 8.0


def test_anti_rebond_lendemain_repart_de_un(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    assert c.ralentir("a.exemple", "2026-11-17", 64, 429, 1000.0, anti_rebond=300) == 2.0
    assert c.ralentir("a.exemple", "2026-11-17", 64, 429, 1001.0, anti_rebond=300) == 2.0
    # minuit passé, même dans la fenêtre : nouvelle journée, nouveau doublement depuis 1
    assert c.ralentir("a.exemple", "2026-11-18", 64, 429, 1002.0, anti_rebond=300) == 2.0
    assert c.ralentissements("2026-11-18")["a.exemple"]["incidents"] == 1
    assert c.ralentir("a.exemple", "2026-11-18", 64, 429, 1003.0, anti_rebond=300) == 2.0


def test_migration_ancien_cache_ralentissements(tmp_path):
    chemin = tmp_path / "c.sqlite"
    db = sqlite3.connect(chemin)
    db.execute("CREATE TABLE ralentissements (hote TEXT PRIMARY KEY, jour TEXT NOT NULL,"
               " facteur REAL NOT NULL, incidents INTEGER NOT NULL, statut INTEGER, maj REAL NOT NULL)")
    db.execute("INSERT INTO ralentissements VALUES ('a.exemple', '2026-11-17', 4.0, 2, 503, 900.0)")
    db.commit()
    db.close()
    c = Cache(chemin)
    Cache(chemin)  # réouverture : migration idempotente
    assert c.ralentissement("a.exemple", "2026-11-17") == 4.0  # état existant conservé
    # ligne antérieure sans horodatage de doublement : le prochain incident double, le suivant non
    assert c.ralentir("a.exemple", "2026-11-17", 64, 429, 1000.0, anti_rebond=300) == 8.0
    assert c.ralentir("a.exemple", "2026-11-17", 64, 429, 1010.0, anti_rebond=300) == 8.0


@respx.mock
def test_retry_after_prime_pour_l_attente_immediate(tmp_path):
    h = Horloge()
    respx.get(URL).mock(side_effect=[httpx.Response(429, headers={"Retry-After": "7"}),
                                     httpx.Response(200, json={"ok": 1})])
    a = client(tmp_path / "c.sqlite", h, max_retries=3)
    assert a.get(URL, use_cache=False)[0] == {"ok": 1}
    assert h.attentes[0] == 7.0  # Retry-After d'abord ; l'intervalle ralenti (4 s) est déjà écoulé
    assert len(h.attentes) == 1


@respx.mock
def test_ralentissement_remis_a_zero_le_lendemain(tmp_path):
    h = Horloge()
    jour = [date(2026, 11, 17)]
    respx.get(URL).mock(return_value=httpx.Response(429))
    a = client(tmp_path / "c.sqlite", h, jour=lambda: jour[0])
    with pytest.raises(SourceError):
        a.get(URL, use_cache=False)
    assert a.intervalle(HOTE) == 4.0
    jour[0] = date(2026, 11, 18)
    assert a.intervalle(HOTE) == 2.0
    assert client(tmp_path / "c.sqlite", h, jour=lambda: jour[0]).intervalle(HOTE) == 2.0


@respx.mock
def test_ralentissement_desactive(tmp_path):
    h = Horloge()
    respx.get(URL).mock(return_value=httpx.Response(429))
    a = client(tmp_path / "c.sqlite", h, ralentissement_max=0)
    with pytest.raises(SourceError):
        a.get(URL, use_cache=False)
    assert a.intervalle(HOTE) == 2.0


@respx.mock
def test_hote_sans_intervalle_non_ralenti(tmp_path):
    """Intervalle de base nul (désactivé par l'utilisateur) : aucune attente introduite."""
    h = Horloge()
    respx.get(URL).mock(return_value=httpx.Response(429))
    a = client(tmp_path / "c.sqlite", h, min_intervals={})
    with pytest.raises(SourceError):
        a.get(URL, use_cache=False)
    assert a.intervalle(HOTE) == 0.0


def test_purge_ralentissement(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    c.ralentir("a.exemple", "2026-11-17", 64)
    c.set("k", 1, 3600, "gallica")
    c.purge()  # une purge complète ne lève pas le ralentissement (politesse envers le site)
    assert c.ralentissements("2026-11-17")["a.exemple"]["facteur"] == 2.0
    assert c.purge("ralentissement") == 1
    assert c.ralentissements("2026-11-17") == {}


@respx.mock
def test_cache_purger_ralentissement(app):
    respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(SourceError):
        app.http.get(URL, use_cache=False)
    base = app.http.default_interval
    assert app.http.intervalle(HOTE) > base
    r = server.cache_purger("ralentissement")
    assert r["supprimes"] == 1
    assert app.http.intervalle(HOTE) == base
    assert "ralentissement" in server.cache_purger.__doc__


@respx.mock
def test_diagnostic_signale_le_ralentissement(app):
    respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(SourceError):
        app.http.get(URL, use_cache=False)
    ctl = next(c for c in diagnostic.controles_locaux(app, None, app.config) if c["controle"] == "debit")
    assert ctl["etat"] == "attention" and HOTE in ctl["detail"]
    assert "cache_purger" in ctl["remede"]
    assert ctl["ralentissements"][HOTE]["intervalle"] > app.http.default_interval


@respx.mock
def test_enveloppe_porte_l_intervalle_courant(app):
    from genealogiste_mcp.sources.base import error_envelope

    respx.get(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "3600"}))
    with pytest.raises(SourceError) as exc:
        app.http.get(URL, use_cache=False)
    out = error_envelope(app.sctx, "archives", "test", {}, exc.value)
    assert out["reessayer_apres"] == 3600
    assert out["intervalle_actuel"] == app.http.intervalle(HOTE) > app.http.default_interval


def test_config_ralentissement_max(tmp_path, monkeypatch):
    from genealogiste_mcp.config import load_config

    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path))
    assert load_config().ralentissement_max == 60.0
    monkeypatch.setenv("GENEALOGISTE_RALENTISSEMENT_MAX", "0")
    assert load_config().ralentissement_max == 0.0
    monkeypatch.setenv("GENEALOGISTE_RALENTISSEMENT_MAX", "-3")
    with pytest.raises(ValueError, match="GENEALOGISTE_RALENTISSEMENT_MAX"):
        load_config()


def test_diagnostic_sans_ralentissement(app):
    ctl = next(c for c in diagnostic.controles_locaux(app, None, app.config) if c["controle"] == "debit")
    assert ctl["etat"] == "ok"
