"""#159 : garde-fou d'écriture côté serveur (GENEALOGISTE_ECRITURE=interdite) et rapport de campagne.

Le refus est décidé par le serveur, avant tout effet, quel que soit le mode de permission du client : ces tests
appellent directement les fonctions des outils, sans passer par les hooks. La liste des outils refusés est dérivée
du catalogue (outils.OUTILS : classe « ecriture » ; outils.CONDITIONS : seulement la branche écriture)."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from genealogiste_mcp import config as config_mod
from genealogiste_mcp import outils, server

HOOKS = Path(__file__).resolve().parents[2] / "hooks" / "hooks.json"

# Exemple d'arguments qui empruntent la branche écriture de chaque outil conditionnel, et la branche réduite.
BRANCHES = {
    "matchid_appariement_statut": ({"job": "1", "sortie": "lot.csv"}, {"job": "1"}),
    "gramps_envoyer_medias": ({"appliquer": True}, {"appliquer": False}),
    "enquete_ouvrir": ({"sujet": "x", "budget": {"images": 5}}, {"sujet": "x"}),
    "enquete_noter": ({"enquete": "x", "statut": "ouverte"}, {"enquete": "x", "statut": "close"}),
}


def _factices(fn) -> dict:
    """Arguments obligatoires factices : le refus intervient avant toute lecture de leur valeur."""
    valeurs = {"list": [], "dict": {}, "int": 0, "bool": False}
    out = {}
    for nom, p in inspect.signature(fn).parameters.items():
        if p.default is inspect.Parameter.empty:
            out[nom] = valeurs.get(str(p.annotation).split("[")[0], "factice")
    return out


def _empreinte(racine: Path) -> dict:
    return {str(f.relative_to(racine)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(racine.rglob("*")) if f.is_file() and ".git" not in f.parts}


@pytest.fixture
def interdite(app_famille):
    app_famille.config.ecriture = "interdite"
    return app_famille


# ---------------------------------------------------------------- configuration

@pytest.mark.parametrize("valeur,attendu", [("", "autorisee"), ("autorisee", "autorisee"),
                                            ("interdite", "interdite"), (" INTERDITE ", "interdite"),
                                            ("autorisée", "autorisee")])
def test_valeurs_acceptees(valeur, attendu):
    assert config_mod.ecriture_mode(valeur) == attendu


def test_defaut_autorisee(config):
    assert config.ecriture == "autorisee"


def test_valeur_invalide_erreur_de_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path / "donnees"))
    monkeypatch.setenv("GENEALOGISTE_CACHE", str(tmp_path / "cache.sqlite"))
    monkeypatch.delenv("GENEALOGISTE_ENV_FILE", raising=False)
    monkeypatch.setenv("GENEALOGISTE_ECRITURE", "non")
    server.set_app(None)
    try:
        res = asyncio.run(server.mcp.call_tool("arbre_appliquer", {"jeton": "x"}))
    finally:
        server.set_app(None)
    d = json.loads(res.content[0].text)
    assert res.is_error and d["cause"] == "configuration" and d["variable"] == "GENEALOGISTE_ECRITURE"
    assert "interdite | autorisee" in d["erreur"]


def test_lu_depuis_l_environnement(tmp_path, monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path / "donnees"))
    monkeypatch.delenv("GENEALOGISTE_ENV_FILE", raising=False)
    monkeypatch.setenv("GENEALOGISTE_ECRITURE", "interdite")
    assert config_mod.load_config().ecriture == "interdite"


# ---------------------------------------------------------------- garde-fou

def test_chaque_outil_enregistre_passe_par_le_garde_fou():
    """Le garde-fou enveloppe tout outil enregistré : un outil d'écriture ajouté plus tard est couvert."""
    for t in asyncio.run(server.mcp.list_tools()):
        assert hasattr(getattr(server, t.name), "__wrapped__"), t.name
    assert server.mcp.garde is not None


def test_branches_conditionnelles_toutes_couvertes():
    assert set(BRANCHES) == set(outils.CONDITIONS)


def test_ecritures_attendues_derivees_du_catalogue():
    """Les écritures citées par #159 (et celles ajoutées depuis) sont bien couvertes par le catalogue."""
    ecritures = {n for n, (_, c) in outils.OUTILS.items() if c == outils.ECRITURE and n not in outils.CONDITIONS}
    assert {"arbre_appliquer", "pieces_appliquer", "marqueurs_migrer_appliquer", "gramps_tirer",
            "gramps_bascule_appliquer"} <= ecritures


@pytest.mark.parametrize("nom", sorted(n for n, (_, c) in outils.OUTILS.items()
                                       if c == outils.ECRITURE and n not in outils.CONDITIONS))
def test_outil_d_ecriture_refuse_sans_effet(interdite, tmp_path, nom):
    fn = getattr(server, nom)
    avant = _empreinte(tmp_path)
    out = fn(**_factices(fn))
    assert isinstance(out, dict) and out.get("refus") == "ecriture_interdite", out
    assert "GENEALOGISTE_ECRITURE=interdite" in out["erreur"] and nom in out["erreur"]
    assert _empreinte(tmp_path) == avant


@pytest.mark.parametrize("nom", sorted(outils.CONDITIONS))
def test_outil_conditionnel_refuse_seulement_la_branche_ecriture(interdite, nom):
    ecriture, reduite = BRANCHES[nom]
    fn = getattr(server, nom)
    refus = server.mcp.garde(nom, fn, (), ecriture)
    assert refus and refus["refus"] == "ecriture_interdite"
    assert server.mcp.garde(nom, fn, (), reduite) is None


@pytest.mark.parametrize("nom", sorted(n for n, (_, c) in outils.OUTILS.items() if c != outils.ECRITURE))
def test_lecture_collecte_proposition_permises(interdite, nom):
    fn = getattr(server, nom)
    assert server.mcp.garde(nom, fn, (), _factices(fn)) is None


@pytest.mark.skipif(shutil.which("sh") is None or shutil.which("grep") is None, reason="sh et grep requis")
@pytest.mark.parametrize("nom", sorted(outils.CONDITIONS))
def test_meme_branche_que_le_hook(nom):
    """Le serveur et le hook (grep -E sur l'entrée JSON) tranchent la même branche."""
    hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    outil = "mcp__plugin_genealogiste_genealogiste__" + nom
    commande = next(c["command"] for h in hooks if re.fullmatch(h["matcher"], outil) for c in h["hooks"])
    for args, attendu in zip(BRANCHES[nom], ("ask", "allow"), strict=True):
        sortie = subprocess.run(["sh", "-c", commande], input=json.dumps({"tool_name": outil, "tool_input": args}),
                                capture_output=True, text=True, check=True).stdout
        assert json.loads(sortie)["hookSpecificOutput"]["permissionDecision"] == attendu
        assert outils.branche_ecriture(nom, args) is (attendu == "ask")


def test_arbre_appliquer_refuse_puis_accepte(interdite):
    a = interdite
    p = server.arbre_proposer([{"op": "marquer_vivant", "id": "I7", "vivant": "N"}], "Essai", "test")
    jeton = p["jeton"]
    texte = a.store.path.read_text(encoding="utf-8")
    out = server.arbre_appliquer(jeton)
    assert out["refus"] == "ecriture_interdite"
    assert a.store.path.read_text(encoding="utf-8") == texte
    a.config.ecriture = "autorisee"
    assert "erreur" not in server.arbre_appliquer(jeton)  # jeton intact : rien n'a été consommé


def test_refus_par_le_serveur_mcp(interdite):
    res = asyncio.run(server.mcp.call_tool("cache_purger", {}))
    d = json.loads(res.content[0].text)
    assert d["refus"] == "ecriture_interdite"


def test_parcours_autonome_permis(interdite):
    """Ce qu'une campagne appelle reste permis : enquête, file de propositions, journal, rapport de campagne."""
    o = server.enquete_ouvrir("Campagne I1", ["I1"], "camp-i1")
    assert "erreur" not in o and "refus" not in o
    assert "refus" not in server.enquete_noter("camp-i1", piste={"question": "Naissance de I1 ?"})
    assert "refus" not in server.enquete_etat("camp-i1")
    assert "refus" not in server.enquete_reprendre("camp-i1")
    d = server.propositions_deposer([{"op": "marquer_vivant", "id": "I7", "vivant": "N"}], "Essai", "test",
                                    enquete="camp-i1")
    assert "refus" not in d and "erreur" not in d, d
    assert server.propositions_lister()["propositions"]
    assert "refus" not in server.journal_ajouter("campagne", "test", "negatif", "rien")
    r = server.rapport_campagne_enregistrer("Campagne I1", "## Trouvé\nrien\n", ["camp-i1"])
    assert Path(r["fichier"]).is_file()


# ---------------------------------------------------------------- rapport de campagne

def test_rapport_campagne_date_dans_les_donnees(app_famille):
    a = app_famille
    a.config.rapports_dir_conf = a.config.data_dir.parent / "vault-rapports"  # ignoré : reste dans les données
    commits = a.store.log(100)
    r = server.rapport_campagne_enregistrer("Campagne Martin", "corps", ["e1", "e2"])
    f = Path(r["fichier"])
    assert f.parent == a.config.data_dir / "rapports" / "campagnes"
    assert f.name == f"{date.today().isoformat()}-campagne-martin.md"
    texte = f.read_text(encoding="utf-8")
    assert texte.endswith("corps\n") and "e1" in texte and "e2" in texte
    assert not a.config.rapports_dir_conf.exists()
    assert a.store.log(100) == commits  # ni commit ni push
    assert r["commit"] is None


def test_rapport_campagne_jamais_ecrase(app_famille):
    premiers = [server.rapport_campagne_enregistrer("Lot", f"v{i}")["fichier"] for i in range(3)]
    noms = [Path(x).name for x in premiers]
    jour = date.today().isoformat()
    assert noms == [f"{jour}-lot.md", f"{jour}-lot-2.md", f"{jour}-lot-3.md"]
    assert [Path(x).read_text(encoding="utf-8").rstrip().endswith(f"v{i}") for i, x in enumerate(premiers)] \
        == [True] * 3


def test_rapport_campagne_trop_long_refuse(app_famille):
    out = server.rapport_campagne_enregistrer("Lot", "x" * (server.RAPPORT_CAMPAGNE_MAX + 1))
    assert "erreur" in out
    assert not (app_famille.config.data_dir / "rapports" / "campagnes").exists()


def test_rapport_campagne_collecte():
    assert outils.OUTILS["rapport_campagne_enregistrer"][1] == outils.COLLECTE
    assert "rapport_campagne_enregistrer" not in outils.CONDITIONS


def test_schemas_inchanges_par_l_enveloppe():
    """L'enveloppe du garde-fou n'altère ni le schéma d'entrée ni la description exposés au client."""
    from mcp.server.mcpserver import MCPServer

    temoin = MCPServer("temoin")
    for t in asyncio.run(server.mcp.list_tools()):
        temoin.add_tool(getattr(server, t.name).__wrapped__, name=t.name)
    attendus = {t.name: (t.description, t.input_schema, t.output_schema) for t in asyncio.run(temoin.list_tools())}
    obtenus = {t.name: (t.description, t.input_schema, t.output_schema)
               for t in asyncio.run(server.mcp.list_tools())}
    # #211 : l'enveloppe ajoute seulement le paramètre facultatif « enquete » (et sa phrase de description) aux
    # outils de collecte réseau qui ne l'ont pas déjà.
    ajoutes = {n for n in outils.BUDGET_ENQUETE if n in obtenus and "enquete" not in attendus[n][1]["properties"]}
    assert ajoutes
    for nom in ajoutes:
        description, schema, sortie = obtenus[nom]
        assert schema["properties"].pop("enquete") == {"default": "", "title": "Enquete", "type": "string"}, nom
        assert description.startswith(attendus[nom][0]) and description != attendus[nom][0], nom
        obtenus[nom] = (attendus[nom][0], schema, sortie)
    assert obtenus == attendus


def test_budget_et_reouverture_refuses_note_permise(interdite):
    """enquete_ouvrir / enquete_noter : seules la fixation d'un budget et la réouverture sont refusées."""
    assert server.enquete_ouvrir("Avec budget", ["I7"], "avec-budget", budget={"images": 5})["refus"] \
        == "ecriture_interdite"
    assert not (interdite.config.data_dir / "enquetes" / "avec-budget.json").exists()
    assert "refus" not in server.enquete_ouvrir("Sans budget", ["I7"], "sans-budget")
    assert server.enquete_noter("sans-budget", budget={"images": 99})["refus"] == "ecriture_interdite"
    assert server.enquete_noter("sans-budget", statut="ouverte")["refus"] == "ecriture_interdite"
    assert "refus" not in server.enquete_noter("sans-budget", tache={"description": "Voir AD59"})
    assert "refus" not in server.enquete_noter("sans-budget", statut="close")
    assert server.gramps_envoyer_medias(appliquer=True)["refus"] == "ecriture_interdite"


def test_profil_sans_surveillance():
    """Profil minimal : aucun outil d'écriture autorisé hors outils conditionnels (refusés côté serveur pour leur
    branche écriture), toutes les écritures restantes en deny, dontAsk."""
    p = outils.profil_sans_surveillance()["permissions"]
    pre = outils.PREFIXE_PLUGIN
    allow = {x.removeprefix(pre) for x in p["allow"] if x.startswith(pre)}
    deny = {x.removeprefix(pre) for x in p["deny"]}
    assert p["defaultMode"] == "dontAsk"
    assert allow | deny == set(outils.OUTILS) and not allow & deny
    assert {"arbre_appliquer", "pieces_appliquer", "marqueurs_migrer_appliquer", "gramps_bascule_appliquer",
            "gramps_tirer", "rapport_enregistrer", "cache_purger"} <= deny
    assert {"rapport_campagne_enregistrer", "propositions_deposer", "enquete_ouvrir", "enquete_noter",
            "arbre_lacunes"} <= allow
    assert {n for n in allow if outils.OUTILS[n][1] == outils.ECRITURE} == set(outils.CONDITIONS)
    autre = outils.profil_sans_surveillance("mcp__genealogiste__")["permissions"]["deny"]
    assert all(x.startswith("mcp__genealogiste__") for x in autre)
