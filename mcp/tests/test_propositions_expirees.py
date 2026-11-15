"""#151 (partie C) : une proposition expirée n'est plus listée « en attente » ; elle est purgée."""

from __future__ import annotations

import json

from genealogiste_mcp import server
from genealogiste_mcp.tree.proposals import TTL_SECONDS


def _vieillir(app, jeton: str, secondes: float) -> None:
    path = app.tokens._path(jeton)
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["cree"] -= secondes
    path.write_text(json.dumps(rec), encoding="utf-8")


def test_expirees_purgees_et_non_listees(app):
    vieux = app.tokens.create({"type": "modification", "resume": ["vieux"]})
    recent = app.tokens.create({"type": "modification", "resume": ["récent"]})
    _vieillir(app, vieux, 161 * 3600)
    assert app.tokens.expirees() == [vieux]  # lecture seule : rien n'est supprimé
    attente = server.arbre_info()["propositions_en_attente"]
    assert [p["jeton"] for p in attente] == [recent]
    assert not app.tokens._path(vieux).exists()
    assert app.tokens._path(recent).exists()


def test_purge_au_demarrage(config):
    a = server.App(config, sleeper=lambda s: None)
    jeton = a.tokens.create({"type": "modification"})
    _vieillir(a, jeton, TTL_SECONDS + 60)
    b = server.App(config, sleeper=lambda s: None)
    assert not b.tokens._path(jeton).exists()


def test_diagnostic_compte_les_expirees_sans_purger(app):
    jeton = app.tokens.create({"type": "modification"})
    _vieillir(app, jeton, TTL_SECONDS + 60)
    c = next(c for c in server.diagnostic(reseau=False)["controles"] if c["controle"] == "propositions")
    assert c["etat"] == "attention" and "1 expirée" in c["detail"]
