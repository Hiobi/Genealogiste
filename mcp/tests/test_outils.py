"""#55 : catalogue unique des outils (effets, décisions du hook) et des statuts de preuve."""

import asyncio
import inspect
import json
import re
from pathlib import Path

from genealogiste_mcp import outils, server, statuts

HOOKS = Path(__file__).resolve().parents[2] / "hooks" / "hooks.json"


def _outils_enregistres() -> dict:
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def _decision_hook(nom: str) -> str:
    hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    outil = f"mcp__plugin_genealogiste_genealogiste__{nom}"
    for h in hooks:
        if re.fullmatch(h["matcher"], outil):
            cmd = h["hooks"][0]["command"]
            if "grep" in cmd:
                return outils.CONDITIONNEL
            return re.search(r'permissionDecision\\?"\s*:\s*\\?"(\w+)', cmd).group(1)
    return outils.DEFAUT


def test_chaque_outil_est_declare():
    assert set(_outils_enregistres()) == set(outils.OUTILS)


def test_hooks_conformes_au_catalogue():
    ecarts = {n: (d, _decision_hook(n)) for n, (_, d) in outils.OUTILS.items() if _decision_hook(n) != d}
    assert ecarts == {}


def test_ecritures_jamais_allow_sauf_liste():
    # Écritures autorisées sans confirmation : héritage documenté (recalcul de notes et synchronisation Gramps,
    # qui ne font que propager l'arbre local validé).
    permises = {"gramps_recalculer_notes", "gramps_synchroniser"}
    allow = {n for n, (e, d) in outils.OUTILS.items() if e in (outils.ECRITURE, outils.IDENTIFIANTS)
             and d == outils.ALLOW}
    assert allow == permises


def test_outils_reseau_avec_personne_gardes():
    for nom, (effet, _) in outils.OUTILS.items():
        if effet != outils.RESEAU or nom in outils.EXEMPTIONS:
            continue
        params = set(inspect.signature(getattr(server, nom)).parameters)
        if params & outils.PARAMS_PERSONNE:
            assert nom in outils.GARDE_VIVANTS, f"{nom} envoie {params & outils.PARAMS_PERSONNE} sans garde"


def test_garde_appelee_dans_le_code():
    for nom in outils.GARDE_VIVANTS:
        src = inspect.getsource(getattr(server, nom))
        assert "_garde(" in src or "external_guard(" in src, nom


def test_statuts_tables_completes():
    for table in (statuts.LABELS, statuts.ICONS, statuts.RANG_VERSION, statuts.GRAVITE, statuts.COULEURS):
        assert set(table) == set(statuts.STATUTS)


def test_statuts_une_seule_definition():
    racine = Path(server.__file__).parent
    for f in racine.rglob("*.py"):
        if f.name == "statuts.py":
            continue
        texte = f.read_text(encoding="utf-8")
        assert not re.search(r'["\']confirme["\']\s*:\s*["\'0-9]', texte), f"table de statuts dupliquée : {f}"
