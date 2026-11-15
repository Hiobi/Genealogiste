"""#147 : outil diagnostic (contrôle, état, remède), aucun secret dans la sortie, /health sans authentification."""

from __future__ import annotations

import asyncio
import json
import sys

import httpx
import respx
import uvicorn

from genealogiste_mcp import diagnostic, outils, server

SECRETS = ("mdp-gramps-tres-secret", "jeton-matchid-secret", "jeton-mcp-secret", "appid-wikitree-secret",
           "identifiant-cache")


def _controle(res: dict, nom: str) -> dict:
    return next(c for c in res["controles"] if c["controle"] == nom)


def test_catalogue_et_hook():
    assert outils.OUTILS["diagnostic"] == (outils.RESEAU, outils.ALLOW)


def test_diagnostic_hors_reseau(app):
    res = server.diagnostic(reseau=False)
    noms = {c["controle"] for c in res["controles"]}
    assert {"version", "configuration", "git", "uv", "droits", "espace_disque", "caches", "ocr",
            "propositions"} <= noms
    for c in res["controles"]:
        assert c["etat"] in ("ok", "attention", "erreur")
        if c["etat"] != "ok":
            assert c.get("remede"), c
    assert res["etat"] in ("ok", "attention", "erreur")
    assert _controle(res, "configuration")["etat"] == "ok"


def test_propositions_expirees_signalees(app):
    jeton = app.tokens.create({"type": "modification", "resume": ["x"]})
    path = app.tokens._path(jeton)
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["cree"] -= 7 * 3600
    path.write_text(json.dumps(rec), encoding="utf-8")
    c = _controle(server.diagnostic(reseau=False), "propositions")
    assert c["etat"] == "attention" and "expir" in c["detail"] and c["remede"]


def test_aucun_secret(app, monkeypatch):
    app.config.gramps_password = SECRETS[0]
    app.config.matchid_token = SECRETS[1]
    app.config.wikitree_app_id = SECRETS[3]
    app.config.gramps_url = f"https://{SECRETS[4]}:{SECRETS[0]}@gramps.example"
    monkeypatch.setenv("MCP_TOKEN", SECRETS[2])
    monkeypatch.setenv("GENEALOGISTE_GRAMPS_PASSWORD", SECRETS[0])
    texte = json.dumps(server.diagnostic(reseau=False), ensure_ascii=False)
    for s in SECRETS:
        assert s not in texte
    conf = _controle(server.diagnostic(reseau=False), "configuration")["valeurs"]
    assert conf["gramps_password"] == "défini" and conf["matchid_token"] == "défini"
    assert conf["gramps_url"] == "https://gramps.example"


@respx.mock
def test_sources_et_protection(app, monkeypatch):
    monkeypatch.setattr(diagnostic, "SOURCES", {"api_ok": "https://api.exemple.fr/",
                                                "archives_cf": "https://archives.exemple.fr/"})
    respx.get("https://api.exemple.fr/").mock(return_value=httpx.Response(200, text="ok"))
    respx.get("https://archives.exemple.fr/").mock(
        return_value=httpx.Response(403, text="<title>Just a moment...</title> cloudflare"))
    res = server.diagnostic()
    assert _controle(res, "source:api_ok")["etat"] == "ok"
    cf = _controle(res, "source:archives_cf")
    assert cf["etat"] == "attention" and cf["verdict"] == "protection" and cf["remede"]
    assert app.journal.entries(source="diagnostic")  # requêtes tracées


def test_diagnostic_quand_l_initialisation_echoue(tmp_path, monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("GENEALOGISTE_CACHE", str(tmp_path / "c.sqlite"))
    monkeypatch.setenv("GENEALOGISTE_BACKEND", "mauvais")
    server.set_app(None)
    try:
        res = server.diagnostic(reseau=False)
    finally:
        server.set_app(None)
    c = _controle(res, "configuration")
    assert c["etat"] == "erreur" and "GENEALOGISTE_BACKEND" in c["detail"] and c["remede"]
    assert res["etat"] == "erreur"


def test_health_sans_authentification(monkeypatch, tmp_path):
    lancements = []
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("GENEALOGISTE_CACHE", str(tmp_path / "c.sqlite"))
    monkeypatch.setenv("MCP_TOKEN", "jeton-sante")
    monkeypatch.setattr(sys, "argv", ["genealogiste-mcp", "--transport", "streamable-http", "--port", "9877"])
    monkeypatch.setattr(uvicorn, "run", lambda asgi, **kw: lancements.append(asgi))
    server.main()
    asgi = lancements[0]

    async def requetes():
        transport = httpx.ASGITransport(app=asgi, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9877") as client:
            r = await client.get("/health")
            assert r.status_code == 200
            corps = r.json()
            assert corps["statut"] == "ok" and corps["version"]
            assert set(corps) <= {"statut", "version"}
            assert (await client.get("/mcp")).status_code == 401  # le reste reste protégé
    asyncio.run(requetes())


def test_dockerfile_utilise_health():
    from pathlib import Path
    docker = (Path(server.__file__).resolve().parents[2] / "Dockerfile").read_text(encoding="utf-8")
    assert "/health" in docker


def test_diagnostic_n_utilise_que_la_config_de_l_app(app, monkeypatch):
    """Le diagnostic d'une App en place ne relit pas l'environnement (ni le .env du répertoire par défaut)."""
    import os

    import genealogiste_mcp.server as srv

    monkeypatch.setattr(srv, "load_config", lambda: (_ for _ in ()).throw(AssertionError("load_config appelé")))
    avant = dict(os.environ)
    server.diagnostic(reseau=False)
    assert dict(os.environ) == avant
