"""#55 : catalogue unique des outils (effets, décisions du hook) et des statuts de preuve."""

import asyncio
import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from genealogiste_mcp import outils, server, statuts

HOOKS = Path(__file__).resolve().parents[2] / "hooks" / "hooks.json"


def _outils_enregistres() -> dict:
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


PREFIXES = ("mcp__plugin_genealogiste_genealogiste__", "mcp__genealogiste__")  # plugin stdio, serveur HTTP Docker
ROOT = HOOKS.parents[1]


def _decisions_hook(outil: str, tool_input: dict) -> list[str]:
    """Décision réellement produite par chaque hook dont le motif couvre l'outil (commande exécutée)."""
    hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    payload = json.dumps({"tool_name": outil, "tool_input": tool_input})
    decisions = []
    for h in hooks:
        if re.fullmatch(h["matcher"], outil):
            for cmd in h["hooks"]:
                out = subprocess.run(["sh", "-c", cmd["command"]], input=payload, capture_output=True, text=True,
                                     check=True).stdout
                decisions.append(json.loads(out)["hookSpecificOutput"]["permissionDecision"])
    return decisions


def test_chaque_outil_est_declare():
    assert set(_outils_enregistres()) == set(outils.OUTILS)


def test_chaque_outil_a_une_classe():
    """#153 : plus de décision « par défaut » ; chaque outil a une classe de permission explicite."""
    assert not hasattr(outils, "DEFAUT")
    sans_classe = {n: c for n, (_, c) in outils.OUTILS.items() if c not in outils.CLASSES}
    assert sans_classe == {}
    assert set(outils.CONDITIONS) <= set(outils.OUTILS)
    for nom, (_, reduite, _) in outils.CONDITIONS.items():
        assert outils.OUTILS[nom][1] == outils.ECRITURE and reduite in outils.CLASSES, nom


def test_decision_deduite_de_la_classe():
    assert outils.DECISIONS == {outils.LECTURE: "allow", outils.COLLECTE: "allow", outils.PROPOSITION: "allow",
                                outils.ECRITURE: "ask"}
    for nom, (_, classe) in outils.OUTILS.items():
        assert outils.decision(nom) == outils.DECISIONS[classe]


def test_classe_coherente_avec_effet():
    """Une écriture n'est jamais classée lecture ou proposition ; le réseau n'est jamais « lecture »."""
    for nom, (effet, classe) in outils.OUTILS.items():
        attendues = {outils.LECTURE: {outils.LECTURE}, outils.JOURNAL: {outils.LECTURE, outils.COLLECTE},
                     outils.RESEAU: {outils.COLLECTE, outils.ECRITURE},
                     outils.PROPOSITION: {outils.PROPOSITION},
                     outils.ECRITURE: {outils.COLLECTE, outils.ECRITURE},
                     outils.IDENTIFIANTS: {outils.ECRITURE}}[effet]
        assert classe in attendues, f"{nom} : effet {effet}, classe {classe}"


def test_hooks_generes_depuis_le_catalogue():
    """hooks/hooks.json est exactement le rendu du catalogue (scripts/generer_hooks.py)."""
    assert json.loads(HOOKS.read_text(encoding="utf-8")) == outils.hooks_json()
    assert HOOKS.read_text(encoding="utf-8") == outils.hooks_texte()


@pytest.mark.skipif(shutil.which("sh") is None or shutil.which("grep") is None, reason="sh et grep requis")
@pytest.mark.parametrize("prefixe", PREFIXES)
def test_hooks_appliquent_la_decision_de_chaque_outil(prefixe):
    ecarts = {}
    for nom, (_, classe) in outils.OUTILS.items():
        attendu = outils.DECISIONS[outils.CONDITIONS[nom][1] if nom in outils.CONDITIONS else classe]
        obtenu = _decisions_hook(prefixe + nom, {})
        if obtenu != [attendu]:
            ecarts[nom] = (attendu, obtenu)
    assert ecarts == {}
    assert _decisions_hook(prefixe + "outil_inconnu", {}) == []
    assert _decisions_hook("mcp__autre_serveur__arbre_info", {}) == []


@pytest.mark.skipif(shutil.which("sh") is None or shutil.which("grep") is None, reason="sh et grep requis")
@pytest.mark.parametrize("nom,tool_input,attendu", [
    ("gramps_envoyer_medias", {}, "allow"),
    ("gramps_envoyer_medias", {"appliquer": False}, "allow"),
    ("gramps_envoyer_medias", {"appliquer": True}, "ask"),
    ("matchid_appariement_statut", {"job": "1", "sortie": "lot.csv"}, "ask"),
    ("matchid_appariement_statut", {"job": "1", "sortie": ""}, "allow"),
])
def test_hooks_conditionnels(nom, tool_input, attendu):
    assert _decisions_hook(PREFIXES[0] + nom, tool_input) == [attendu]


@pytest.mark.parametrize("nom,classe", [
    # chaîne /genealogiste:acte (#153)
    ("archives_service", "lecture"), ("ark_resoudre", "collecte"), ("archive_image", "collecte"),
    ("archives_planche", "collecte"), ("piece_archiver", "collecte"), ("archives_naviguer", "collecte"),
    # cas tranchés d'après le code
    ("gramps_recalculer_notes", "proposition"), ("gramps_structurer_lieux", "proposition"),
    ("gramps_synchroniser", "collecte"), ("gramps_envoyer_medias", "ecriture"),
    ("media_enregistrer", "ecriture"), ("arbre_exporter", "ecriture"), ("cache_purger", "ecriture"),
    ("notes_generer", "ecriture"), ("notes_ajouter", "ecriture"), ("notes_lire", "ecriture"),
    ("matchid_appariement_csv", "ecriture"), ("familysearch_exporter", "ecriture"),
])
def test_classes_tranchees(nom, classe):
    assert outils.OUTILS[nom][1] == classe


# /genealogiste:acte : outils appelés après accord explicite ou avec un fichier fourni par l'utilisateur.
ACTE_HORS_PARCOURS_AUTOMATIQUE = {
    "arbre_appliquer": "après la proposition, sur accord explicite",
    "media_enregistrer": "repli manuel (anti-robot) : l'utilisateur fournit lui-même la capture",
}


def test_acte_sans_accord_jusqu_a_la_proposition():
    """#153 : /genealogiste:acte (et /genealogiste:transcris qu'il suit à l'étape 5) se déroule sans demande
    d'accord jusqu'à arbre_proposer."""
    cites = set()
    for f in ("commands/acte.md", "commands/transcris.md"):
        cites |= set(re.findall(r"`([a-z_]+)", (ROOT / f).read_text(encoding="utf-8"))) & set(outils.OUTILS)
    chaine = {"arbre_recherche", "arbre_personne", "arbre_vivant", "archives_service", "archives_registres",
              "archives_naviguer", "archives_planche", "archive_image", "ark_resoudre", "piece_archiver",
              "source_collee", "arbre_proposer"}
    assert chaine - {"ark_resoudre"} <= cites
    demandes = {n for n in (cites | chaine) - set(ACTE_HORS_PARCOURS_AUTOMATIQUE)
                if outils.DECISIONS[outils.CONDITIONS[n][1] if n in outils.CONDITIONS else outils.OUTILS[n][1]]
                != "allow"}
    assert demandes == set()


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
