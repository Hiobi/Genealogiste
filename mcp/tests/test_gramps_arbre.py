"""#9 : un répertoire de données = un arbre Gramps Web (garde-fou contre le mélange de deux arbres)."""

import json

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed

from genealogiste_mcp import server
from genealogiste_mcp.gramps.backend import TREE_FILE
from genealogiste_mcp.gramps.client import GrampsError, jwt_claims


def test_jwt_claims():
    assert jwt_claims("A1") == {} and jwt_claims("x.!!!.y") == {}


@pytest.mark.parametrize("second_tree, ok", [("arbre-famille", True), ("arbre-client", False)])
def test_data_dir_bound_to_one_tree(tmp_path, tree, second_tree, ok):
    with FakeGrampsWeb(tree="arbre-famille") as fake:
        seed(fake, tree)
        make_app(tmp_path)
        try:
            assert server.arbre_info()["personnes"] == 8
        finally:
            server.set_app(None)
    saved = json.loads((tmp_path / "donnees" / TREE_FILE).read_text(encoding="utf-8"))
    assert saved["tree"] == "arbre-famille" and saved["compte"] == "sosa"
    with FakeGrampsWeb(tree=second_tree) as fake:
        seed(fake, tree)
        make_app(tmp_path)
        try:
            if ok:
                assert server.arbre_info()["personnes"] == 8
            else:  # erreur remontée à l'agent par le serveur MCP, comme une panne de Gramps Web
                with pytest.raises(GrampsError, match="GENEALOGISTE_DATA_DIR"):
                    server.arbre_info()
                r = server.arbre_proposer([{"op": "marquer_vivant", "id": "I7", "vivant": "N"}], "t", "j")
                assert "arbre-famille" in r["erreur"]  # écriture : erreur lisible, rien d'écrit
        finally:
            server.set_app(None)


def test_server_without_tree_claim_is_not_blocked(tmp_path, tree):
    with FakeGrampsWeb() as fake:
        seed(fake, tree)
        make_app(tmp_path)
        try:
            assert server.arbre_info()["personnes"] == 8
        finally:
            server.set_app(None)
    assert not (tmp_path / "donnees" / TREE_FILE).exists()
