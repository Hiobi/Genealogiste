"""#211, lot D : contact facultatif dans le User-Agent (GENEALOGISTE_CONTACT), fourni par l'utilisateur, jamais
par défaut ; un User-Agent explicite l'emporte tel quel ; valeur invalide ignorée et signalée par diagnostic."""

from __future__ import annotations

import httpx
import pytest
import respx

from genealogiste_mcp import diagnostic
from genealogiste_mcp.cache import Cache
from genealogiste_mcp.config import CONTACT_MAX, contact_valide, load_config, user_agent_par_defaut
from genealogiste_mcp.http import HttpClient

CONTACT = "contact@example.org"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path))
    return monkeypatch


def _configuration(cfg) -> dict:
    return next(c for c in diagnostic.controles_locaux(None, None, cfg) if c["controle"] == "configuration")


def test_sans_contact_user_agent_inchange(env):
    cfg = load_config()
    assert cfg.user_agent == user_agent_par_defaut()
    assert cfg.user_agent.endswith("(plugin Claude Code; usage genealogique personnel)")
    assert "contact" not in cfg.user_agent
    assert (cfg.contact, cfg.etat_contact) == ("", "absent")
    conf = _configuration(cfg)
    assert conf["etat"] == "ok" and conf["valeurs"]["contact_user_agent"] == "absent"


@pytest.mark.parametrize("vide", ["", "   "])
def test_contact_vide_equivaut_a_absent(env, vide):
    env.setenv("GENEALOGISTE_CONTACT", vide)
    cfg = load_config()
    assert cfg.user_agent == user_agent_par_defaut() and cfg.etat_contact == "absent"


@pytest.mark.parametrize("valeur", [CONTACT, "https://exemple.fr/genealogie", "  contact@example.org  "])
def test_contact_ajoute_au_commentaire(env, valeur):
    env.setenv("GENEALOGISTE_CONTACT", valeur)
    cfg = load_config()
    attendu = valeur.strip()
    assert cfg.contact == attendu and cfg.etat_contact == "configure"
    assert cfg.user_agent == user_agent_par_defaut(attendu)
    assert cfg.user_agent.endswith(f"(plugin Claude Code; usage genealogique personnel; contact: {attendu})")
    assert cfg.user_agent.startswith(user_agent_par_defaut().split(" (")[0] + " (")
    conf = _configuration(cfg)
    # Diagnostic : l'état seulement, jamais la valeur (donnée personnelle).
    assert conf["etat"] == "ok" and conf["valeurs"]["contact_user_agent"] == "configuré"
    assert attendu not in repr(conf)


def test_user_agent_explicite_l_emporte_sans_contact(env):
    env.setenv("GENEALOGISTE_USER_AGENT", "MonOutil/1.0")
    env.setenv("GENEALOGISTE_CONTACT", CONTACT)
    cfg = load_config()
    assert cfg.user_agent == "MonOutil/1.0"
    assert cfg.contact == "" and cfg.etat_contact == "ignore"
    conf = _configuration(cfg)
    assert conf["etat"] == "attention" and "GENEALOGISTE_CONTACT ignoré" in conf["detail"]
    assert "GENEALOGISTE_USER_AGENT" in conf["remede"]
    assert CONTACT not in repr(conf)


def test_user_agent_explicite_seul_sans_avertissement(env):
    env.setenv("GENEALOGISTE_USER_AGENT", "MonOutil/1.0")
    cfg = load_config()
    assert cfg.user_agent == "MonOutil/1.0" and cfg.etat_contact == "absent"
    assert _configuration(cfg)["etat"] == "ok"


@pytest.mark.parametrize("valeur, motif", [
    ("contact@example.org\r\nX-Injecte: 1", "contrôle"),
    ("contact@example.org\nsuite", "contrôle"),
    ("contact\t@example.org", "contrôle"),
    ("contact@example.org) (autre", "interdit"),
    ("contact@example.org; autre", "interdit"),
    ("contact\\@example.org", "interdit"),
    ("contâct@example.org", "ASCII"),
    ("a" * (CONTACT_MAX + 1), f"{CONTACT_MAX}"),
])
def test_contact_invalide_ignore_et_signale(env, valeur, motif):
    env.setenv("GENEALOGISTE_CONTACT", valeur)
    cfg = load_config()  # jamais d'exception au démarrage
    assert cfg.user_agent == user_agent_par_defaut()
    assert cfg.contact == "" and cfg.etat_contact == "rejete" and motif in cfg.contact_motif
    conf = _configuration(cfg)
    assert conf["etat"] == "attention" and "GENEALOGISTE_CONTACT ignoré" in conf["detail"]
    assert conf["valeurs"]["contact_user_agent"] == "rejeté"
    assert valeur not in repr(conf)


def test_contact_longueur_maximale_acceptee():
    assert contact_valide("a" * CONTACT_MAX) == ("a" * CONTACT_MAX, "")


def test_avertissements_cumules_avec_variables_retirees(env):
    env.setenv("GENEALOGISTE_BUDGET_DUREE_MIN", "20")
    env.setenv("GENEALOGISTE_CONTACT", "x;y")
    conf = _configuration(load_config())
    assert "GENEALOGISTE_BUDGET_DUREE_MIN" in conf["detail"] and "GENEALOGISTE_CONTACT" in conf["detail"]
    assert "--max-budget-usd" in conf["remede"] and "GENEALOGISTE_CONTACT" in conf["remede"]


@respx.mock
def test_en_tete_envoye_par_le_client_http(env, tmp_path):
    env.setenv("GENEALOGISTE_CONTACT", CONTACT)
    cfg = load_config()
    route = respx.get("https://exemple.fr/x").mock(return_value=httpx.Response(200, text="ok"))
    client = HttpClient(Cache(tmp_path / "c.sqlite"), cfg.user_agent, sleeper=lambda s: None)
    client.get("https://exemple.fr/x", parse="text", use_cache=False)
    ua = route.calls.last.request.headers["User-Agent"]
    assert ua == cfg.user_agent and ua.endswith(f"; contact: {CONTACT})")


@respx.mock
def test_en_tete_sans_contact_inchange(env, tmp_path):
    cfg = load_config()
    route = respx.get("https://exemple.fr/x").mock(return_value=httpx.Response(200, text="ok"))
    client = HttpClient(Cache(tmp_path / "c.sqlite"), cfg.user_agent, sleeper=lambda s: None)
    client.get("https://exemple.fr/x", parse="text", use_cache=False)
    assert route.calls.last.request.headers["User-Agent"] == user_agent_par_defaut()
