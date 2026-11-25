"""Jeton d'un autre outil en deux temps : erreur explicite, aucun effet, jeton intact (#364)."""

import re

import pytest
from gramps_fake import URL, FakeGrampsWeb

from genealogiste_mcp import server
from genealogiste_mcp.gramps.backend import GrampsBackend, bascule_apply
from genealogiste_mcp.gramps.client import GrampsClient
from genealogiste_mcp.tree.proposals import APPLICATEURS, ProposalError, TokenStore, exiger_type

# Type de jeton → outil qui l'applique côté serveur (backend fichier).
APPLIQUER = {
    "arbre_appliquer": server.arbre_appliquer,
    "pieces_appliquer": server.pieces_appliquer,
    "marqueurs_migrer_appliquer": server.marqueurs_migrer_appliquer,
    "gramps_bascule_appliquer": server.gramps_bascule_appliquer,
    "cassini_installer": server.cassini_installer,
}
# Types acceptés par chaque outil en mode fichier (transaction : mode gramps seulement).
ACCEPTES = {
    "arbre_appliquer": {"modification", "annulation"},
    "pieces_appliquer": {"organisation"},
    "marqueurs_migrer_appliquer": {"marqueurs"},
    "gramps_bascule_appliquer": {"bascule"},
    "cassini_installer": {"cassini"},
}
GRAMPS = {"transaction", "annulation", "reglage", "annulation_reglage"}  # acceptés par le backend gramps


def test_chaque_type_a_un_applicateur():
    assert {v.removesuffix(" (mode gramps)") for v in APPLICATEURS.values()} == set(APPLIQUER)


def test_exiger_type_message():
    with pytest.raises(ProposalError, match=r"organisation, à appliquer avec pieces_appliquer.*reste valable"):
        exiger_type({"type": "organisation"}, "modification")
    with pytest.raises(ProposalError, match="type inconnu : None"):
        exiger_type({}, "modification")
    exiger_type({"type": "bascule"}, "bascule")


@pytest.mark.parametrize("outil", sorted(APPLIQUER))
@pytest.mark.parametrize("kind", sorted(APPLICATEURS))
def test_jeton_d_un_autre_type_refuse_sans_effet(app_famille, outil, kind):
    if kind in ACCEPTES[outil]:
        pytest.skip("type accepté par cet outil")
    avant = app_famille.store.text()
    jeton = app_famille.tokens.create({"type": kind})
    out = APPLIQUER[outil](jeton)
    assert isinstance(out, dict), out
    assert out["erreur"] == (f"Jeton d'un autre type ({kind}, à appliquer avec {APPLICATEURS[kind]}) : rien "
                             "n'a été écrit, le jeton reste valable.")
    assert app_famille.tokens.peek(jeton)["type"] == kind  # non consommé
    assert app_famille.store.text() == avant


@pytest.mark.parametrize("kind", sorted(set(APPLICATEURS) - GRAMPS))
def test_backend_gramps_refuse_jeton_d_un_autre_type(tree, tmp_path, kind):
    from test_gramps_backend import seed

    with FakeGrampsWeb() as fake:
        seed(fake, tree)
        backend = GrampsBackend(GrampsClient(URL, "sosa", "secret"), tmp_path / "donnees",
                                tmp_path / "propositions", ttl=0)
        jeton = backend.tokens.create({"type": kind})
        with pytest.raises(ProposalError, match=f"à appliquer avec {re.escape(APPLICATEURS[kind])}"):
            backend.apply(jeton)
        assert backend.tokens.peek(jeton)["type"] == kind


def test_bascule_refuse_jeton_d_un_autre_type(app_famille, tmp_path):
    tokens = TokenStore(tmp_path / "propositions")
    jeton = tokens.create({"type": "modification"})
    with pytest.raises(ProposalError, match="à appliquer avec arbre_appliquer"):
        bascule_apply(None, app_famille.store, tokens, jeton)
    assert tokens.peek(jeton)["type"] == "modification"
