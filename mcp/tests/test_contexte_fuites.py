"""#323 : un échec de requête ne laisse jamais une clé ou un `mailto` (Crossref) en clair dans le cache d'échecs du
client HTTP, le journal, le registre ni la sortie d'un outil. Valeurs factices ; réseau simulé par respx."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest
import respx

from genealogiste_mcp import server

MAILTO = "chercheur@exemple.fr"
CROSSREF = "https://api.crossref.org/works"
FORMES = (MAILTO, "chercheur%40exemple.fr", "chercheur%40EXEMPLE.fr", "chercheur")
CLOUDFLARE = (Path(__file__).parent / "fixtures" / "contexte" / "reponses" / "GALLICA"
              / "sru-403-cloudflare.html").read_text(encoding="utf-8")


def _contenu_cache(chemin) -> str:
    """Tout le contenu du cache SQLite (toutes tables, clés et valeurs), en texte."""
    base = sqlite3.connect(str(chemin))
    try:
        tables = [r[0] for r in base.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return json.dumps({t: base.execute(f"SELECT * FROM {t}").fetchall() for t in tables},
                          ensure_ascii=False, default=str)
    finally:
        base.close()


def _fichiers_ecrits(app) -> str:
    app.cache._db.commit()
    app.cache._db.execute("PRAGMA wal_checkpoint(FULL)")
    textes = [_contenu_cache(app.config.cache_path)]
    for f in app.config.data_dir.rglob("*"):
        if f.is_file() and ".git" not in f.parts:
            textes.append(f.read_bytes().decode("utf-8", errors="replace"))
    return "\n".join(textes)


def _reponse(statut: int, corps: str, entetes: dict | None = None):
    return lambda req: httpx.Response(statut, text=f"{corps} {req.url}", headers=entetes or {})


@pytest.mark.parametrize("statut,corps,entetes", [
    (404, "introuvable", None),
    (403, "refusé", None),
    (429, "trop de requêtes", {"Retry-After": "120"}),
    (403, CLOUDFLARE, {"Content-Type": "text/html"}),
], ids=["404", "403", "429", "defi-cloudflare"])
def test_echec_memorise_ne_garde_ni_mailto_ni_url_brute(app, statut, corps, entetes):
    app.config.crossref_mailto = MAILTO
    app.http.max_retries = 1
    with respx.mock(assert_all_called=False) as router:
        route = router.get(url__startswith=CROSSREF).mock(side_effect=_reponse(statut, corps, entetes))
        sorties = []
        for _ in range(2):  # le second appel est servi par le cache d'échecs (sans requête) quand il le mémorise
            sorties.append(server.contexte_bibliographie(sujet="mines", lieu="Courrières", services=["CROSSREF"]))
        assert route.called
        assert any(MAILTO.split("@")[0] in str(c.request.url) or "%40" in str(c.request.url)
                   for c in route.calls)  # le choix explicite de l'utilisateur part bien vers Crossref
    assert sorties[0]["services_en_echec"]
    sortie = json.dumps(sorties, ensure_ascii=False, default=str)
    ecrit = _fichiers_ecrits(app)
    for forme in FORMES:
        assert forme not in sortie, ("sortie", forme)
        assert forme.lower() not in ecrit.lower(), ("cache, journal ou données", forme)
