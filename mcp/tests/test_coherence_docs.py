"""Cohérence de la documentation avec le code : noms d'outils MCP cités et commandes présentes au wiki (#160).

Les noms d'outils sont extraits de deux formes seulement, pour éviter les faux positifs :
- un identifiant au début d'un code en ligne (`arbre_info` ou `archives_registres(service=…)`) dont le préfixe
  (`arbre_`, `gramps_`, …) est celui d'au moins un outil du catalogue, préfixes dérivés de ``outils.OUTILS`` ;
- le nom complet d'un outil du serveur : ``mcp__…genealogiste…__nom``.
Les opérations d'``arbre_proposer`` (`ajouter_media`…) ne sont pas des outils et ne doivent pas être capturées."""

import inspect
import re
from pathlib import Path

import pytest

from genealogiste_mcp import outils, server
from genealogiste_mcp.tree import ops

ROOT = Path(__file__).resolve().parents[2]
MCP_COMPLET = re.compile(r"mcp__[\w.*-]*genealogiste[\w.*-]*?__([a-z][a-z0-9_]*)")


def prefixes() -> set[str]:
    return {nom.split("_", 1)[0] + "_" for nom in outils.OUTILS if "_" in nom}


def noms_cites(texte: str) -> set[str]:
    alternatives = "|".join(sorted(map(re.escape, prefixes()), key=len, reverse=True))
    en_ligne = re.compile(rf"`((?:{alternatives})[a-z0-9_]*)(?=[`(])")
    return set(en_ligne.findall(texte)) | set(MCP_COMPLET.findall(texte))


def documents() -> list[Path]:
    """Documentation destinée à l'utilisateur et au modèle. Les références techniques de docs/ (champs GEDCOM,
    paramètres, marqueurs pytest : `media_list`, `gramps_id`, `gramps_live`…) sont hors périmètre : leurs
    identifiants partagent les préfixes des outils sans en être."""
    return sorted({*ROOT.glob("commands/*.md"), *ROOT.glob("agents/*.md"), *ROOT.glob("skills/**/*.md"),
                   ROOT / "README.md", *ROOT.glob("wiki/*.md")})


def test_documents_trouves():
    noms = {p.relative_to(ROOT).as_posix() for p in documents()}
    assert {"README.md", "wiki/Commandes.md", "commands/acte.md", "agents/chercheur.md"} <= noms
    assert any(n.startswith("skills/") for n in noms)


def test_extraction_detecte_les_formes_citees():
    texte = ("Appeler `arbre_info`, puis `archives_registres(service=\"AD59\")` et "
             "mcp__plugin_genealogiste_genealogiste__gramps_tirer ; mcp__genealogiste__notes_lire.")
    assert noms_cites(texte) == {"arbre_info", "archives_registres", "gramps_tirer", "notes_lire"}


def test_extraction_ignore_parametres_chemins_et_autres_serveurs():
    texte = ("`archives_naviguer(ark_registre)` ; `cache-images/` ; `cache_images_max_mo/x` ; GENEALOGISTE_CACHE ; "
             "arbre_info hors code ; mcp__autre__arbre_inconnu ; `ajouter_media`")
    assert noms_cites(texte) == {"archives_naviguer"}


@pytest.mark.parametrize("invente", ["`arbre_inexistant`", "`gramps_teleporter(x)`",
                                     "mcp__plugin_genealogiste_genealogiste__notes_effacer_tout"])
def test_nom_invente_detecte(invente):
    cites = noms_cites(f"Utiliser {invente} ici.")
    assert cites and not cites <= outils.OUTILS.keys()


def test_operations_arbre_proposer_jamais_confondues_avec_outils():
    operations = {nom.removeprefix("op_") for nom, _ in inspect.getmembers(ops, inspect.isfunction)
                  if nom.startswith("op_")}
    assert {"ajouter_media", "modifier_media"} <= operations
    assert not operations & outils.OUTILS.keys()
    assert not noms_cites(" ".join(f"`{op}`" for op in operations))


@pytest.mark.parametrize("chemin", documents(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_outils_cites_existent_au_catalogue(chemin):
    inconnus = noms_cites(chemin.read_text(encoding="utf-8")) - outils.OUTILS.keys()
    assert not inconnus, f"{chemin.relative_to(ROOT)} cite des outils absents de outils.OUTILS : {sorted(inconnus)}"


def test_chaque_commande_figure_dans_la_page_wiki():
    page = (ROOT / "wiki/Commandes.md").read_text(encoding="utf-8")
    citees = set(re.findall(r"^\|\s*`([a-z-]+)[\s`]", page, re.M))
    commandes = {f.stem for f in (ROOT / "commands").glob("*.md")}
    assert commandes, "aucune commande trouvée"
    assert not commandes - citees, f"commandes absentes de wiki/Commandes.md : {sorted(commandes - citees)}"
    assert not citees - commandes, f"wiki/Commandes.md cite des commandes inexistantes : {sorted(citees - commandes)}"


# ---------------------------------------------------------------- #325 : commande /genealogiste:contexte

APPEL = re.compile(r"`([a-z][a-z0-9_]*)\(([^`]*)\)`")
OUTILS_CONTEXTE = {"contexte_local", "pistes_contexte", "contexte_bibliographie", "presse_recherche",
                   "lieu_historique", "contexte_verifier"}


def parametres_cites(texte: str) -> dict[str, set[str]]:
    """Paramètres nommés (``nom=``) de chaque appel d'outil écrit en code en ligne : `outil(a=…, b=…)`."""
    out: dict[str, set[str]] = {}
    for nom, args in APPEL.findall(texte):
        if nom in outils.OUTILS:
            out.setdefault(nom, set()).update(re.findall(r"\b([a-z_]+)=", args))
    return out


@pytest.mark.parametrize("rel", ["commands/contexte.md", "agents/chercheur.md", "skills/genealogiste/SKILL.md"])
def test_parametres_cites_existent_dans_la_signature(rel):
    """Chaque paramètre nommé d'un appel cité est un vrai paramètre de l'outil (ou ``enquete``, ajouté par
    l'enveloppe aux outils de collecte budgétés)."""
    for nom, cites in parametres_cites((ROOT / rel).read_text(encoding="utf-8")).items():
        connus = set(inspect.signature(getattr(server, nom)).parameters)
        if nom in outils.BUDGET_ENQUETE:
            connus.add("enquete")
        assert cites <= connus, f"{rel} : {nom}({sorted(cites - connus)}) absent de la signature"


def test_commande_contexte_outils_et_regles():
    texte = (ROOT / "commands/contexte.md").read_text(encoding="utf-8")
    cites = noms_cites(texte)
    assert cites <= outils.OUTILS.keys()
    assert {"contexte_local", "pistes_contexte", "enquete_noter"} <= cites  # collecte, pistes, versement proposé
    assert OUTILS_CONTEXTE <= cites  # les six outils du jalon sont nommés
    # aucune écriture dans l'arbre : la commande ne cite aucun outil qui propose ou applique une modification
    assert not cites & {"arbre_proposer", "arbre_appliquer", "propositions_deposer"}
    appels = parametres_cites(texte)
    assert appels["contexte_local"] >= {"personne", "lieu", "periode", "echelles", "themes"}
    plat = " ".join(texte.split())
    for regle in ("Rien n'est affirmé de mémoire", "Un élément sans source n'est pas affiché",
                  "contexte non documenté", "Aucune écriture dans l'arbre", "entre guillemets « »",
                  "tendance générale, ne prouve rien pour l'individu"):
        assert regle in plat, regle
    for champ in ("services_en_echec", "services_ecartes", "taches_manuelles", "non_documente",
                  "rattachement.niveau", "source.citation"):
        assert f"`{champ}`" in texte, champ
    entete = re.search(r"^argument-hint:.*$", texte, re.M).group(0)
    assert all(option in entete for option in ("--periode", "--echelles", "--themes"))


def test_chercheur_verse_les_pistes_a_tester_jamais_les_pistes_de_contexte_seul():
    texte = " ".join((ROOT / "agents/chercheur.md").read_text(encoding="utf-8").split())
    assert "`pistes_contexte(personne=<id>" in texte and "depot.enquete_noter" in texte
    assert "statut: a_tester" in texte and "statut: contexte_seul" in texte
    assert "ne deviennent **jamais** une tâche" in texte
