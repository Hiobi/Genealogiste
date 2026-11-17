"""#151 (partie D2) : lectures non bloquées par une écriture, battement de progression pour les appels longs,
notes régénérées en arrière-plan après arbre_appliquer, statut de transaction par jeton."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import date

import anyio
import pytest

from genealogiste_mcp import outils, server
from genealogiste_mcp.config import Config
from genealogiste_mcp.serveur_mcp import ServeurMCP


@pytest.fixture
def napp(tmp_path, fixtures):
    import shutil
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite",
                 notes_dir=tmp_path / "vault", sosa_racine="I3")
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    a.notes.today = lambda: date(2026, 11, 4)
    yield a
    a.attendre_notes(30)
    server.set_app(None)


def _proposer(a) -> str:
    r = server.arbre_proposer([{"op": "modifier_personne", "id": "I1",
                                "noms": [{"prenoms": "Jean-Baptiste", "nom": "MARTIN"}]}],
                              "Prénom", "test", None)
    assert "jeton" in r, r
    return r["jeton"]


def test_outil_de_statut_au_catalogue():
    assert outils.OUTILS["arbre_statut_transaction"] == (outils.LECTURE, outils.LECTURE)


def test_lecture_non_bloquee_par_une_ecriture(napp, monkeypatch):
    jeton = _proposer(napp)
    vrai = napp.backend.apply
    en_cours = threading.Event()

    def lent(j):
        en_cours.set()
        time.sleep(2)
        return vrai(j)

    monkeypatch.setattr(napp.backend, "apply", lent)

    async def scenario():
        with anyio.fail_after(20):
            ecriture = asyncio.create_task(server.mcp.call_tool("arbre_appliquer", {"jeton": jeton}))
            while not en_cours.is_set():
                await asyncio.sleep(0.02)
            debut = time.monotonic()
            info = await server.mcp.call_tool("arbre_info", {})
            duree = time.monotonic() - debut
            statut = await server.mcp.call_tool("arbre_statut_transaction", {"jeton": jeton})
            await ecriture
            return duree, info, statut

    duree, info, statut = asyncio.run(scenario())
    assert not info.is_error and duree < 1.5
    assert not statut.is_error


def test_ecritures_toujours_serialisees():
    assert "arbre_appliquer" not in server.mcp.sans_verrou
    assert {"arbre_info", "arbre_statut_transaction", "journal_lister"} <= server.mcp.sans_verrou
    assert all(outils.OUTILS[n][0] == outils.LECTURE for n in server.mcp.sans_verrou)


def test_battement_de_progression():
    service = ServeurMCP("essai")
    service.intervalle_battement = 0.1
    recus = []

    @service.tool()
    def lent() -> dict:
        time.sleep(0.45)
        return {"ok": True}

    class Ctx:
        async def report_progress(self, progress, total=None, message=None):
            recus.append((progress, message))

    asyncio.run(service.call_tool("lent", {}, Ctx()))
    assert len(recus) >= 2 and "lent" in recus[0][1]


def test_notes_en_arriere_plan_puis_statut(napp, monkeypatch):
    napp.config.notes_attente = 0.1
    vrai = napp.notes.generate

    def lent(tree, cible):
        time.sleep(1.5)
        return vrai(tree, cible)

    monkeypatch.setattr(napp.notes, "generate", lent)
    jeton = _proposer(napp)
    debut = time.monotonic()
    res = server.arbre_appliquer(jeton)
    assert time.monotonic() - debut < 1.2
    assert res["commite"] and res["notes"]["etat"] == "en_cours"
    assert "arbre_statut_transaction" in res["notes"]["suivi"]
    napp.attendre_notes(30)
    st = server.arbre_statut_transaction(jeton)
    assert st["etat"] == "appliquee" and st["commit"] == res["commit"]
    assert st["notes"]["etat"] == "terminee" and st["notes"]["ecrites"]


def test_notes_rapides_rendues_dans_la_reponse(napp):
    jeton = _proposer(napp)
    res = server.arbre_appliquer(jeton)
    assert res["notes"]["etat"] == "terminee" and res["notes"]["ecrites"]


def test_statut_jeton_en_attente_et_inconnu(napp):
    jeton = _proposer(napp)
    assert server.arbre_statut_transaction(jeton)["etat"] == "en_attente"
    assert server.arbre_statut_transaction("0123456789abcdef")["etat"] == "inconnue"
