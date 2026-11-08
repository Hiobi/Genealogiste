"""#72 : affichage des dates bornées (BEF/AFT/FROM/TO) dans les arbres et les noms de notes."""

import pytest

from genealogiste_mcp.export.charts import _years
from genealogiste_mcp.models import Event


@pytest.mark.parametrize("deces, attendu", [
    ("BEF 1925", "1880–av. 1925"),
    ("AFT JUN 1810", "1880–ap. 1810"),
    ("AFT 22 NOV 1919", "1880–ap. 1919"),
    ("TO 1907", "1880–av. 1907"),
    ("FROM 1774", "1880–ap. 1774"),
    ("ABT 1950", "1880–~1950"),
    ("BET 1940 AND 1950", "1880–1940/1950"),
    ("1925", "1880–1925"),
])
def test_dates_bornees_non_decalees(tree, deces, attendu):
    pid = next(iter(tree.personnes))
    p = tree.personnes[pid]
    p.evenements = [Event("BIRT", "1880"), Event("DEAT", deces)]
    assert _years(tree, pid) == attendu


def test_naissance_bornee(tree):
    pid = next(iter(tree.personnes))
    p = tree.personnes[pid]
    p.evenements = [Event("BIRT", "BEF 1739")]
    assert _years(tree, pid) == "av. 1739–"


@pytest.mark.parametrize("date, attendu", [
    ("BET 1940 AND 1950", "1880–1940/1950"),
    ("FROM 1940 TO 1950", "1880–1940/1950"),
    ("EST 1950", "1880–~1950"),
    ("CAL 1950", "1880–~1950"),
])
def test_intervalle_et_approximation_restent_explicites(tree, date, attendu):
    pid = next(iter(tree.personnes))
    tree.personnes[pid].evenements = [Event("BIRT", "13 OCT 1880"), Event("DEAT", date)]
    assert _years(tree, pid) == attendu
