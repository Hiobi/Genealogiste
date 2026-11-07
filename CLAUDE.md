# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projet

Plugin Claude Code « genealogiste » (marketplace `sosa`) : commandes slash, skills, agents et hooks à la
racine, plus un serveur MCP Python (FastMCP) dans `mcp/`. Code, docs, identifiants et messages de commit en
français (Conventional Commits : `feat(pieces): …`, `fix(arbre): …`).

## Commandes

Toutes passent par `uv --directory mcp` (lancer depuis la racine) :

```bash
make install        # uv sync
make test           # pytest, APIs mockées, aucun accès réseau
make lint           # ruff check src tests   (make format pour --fix)
make test-gramps    # intégration sur Gramps Web jetable (Docker, docker-compose.test.yml)
make check          # configuration effective + état de l'arbre
make run / run-http # serveur MCP stdio / HTTP :8765
make validate       # claude plugin validate .
make version V=x.y.z  # publication : voir plus bas

# un seul test
uv --directory mcp run pytest tests/test_tree_ops.py::test_nom -q
```

Le marqueur `gramps_live` n'est exécuté que via `make test-gramps`.

## Architecture

- `mcp/src/genealogiste_mcp/server.py` : tous les outils MCP (`@mcp.tool()`), câblés sur un singleton `App`
  (`app()` / `set_app()`) qui assemble config, cache SQLite, `HttpClient` (limites de débit par hôte,
  `NetworkPolicy`), `TreeStore`, `Journal`, `Proposals`/`TokenStore`, `Notes` et le backend.
- **Deux backends d'arbre** selon `GENEALOGISTE_BACKEND` : `fichier` (défaut — `tree/store.py` +
  `tree/proposals.py`, `arbre.ged` GEDCOM 7 dans un dépôt Git séparé du plugin, un commit par modification)
  ou `gramps` (`gramps/backend.py`, Gramps Web comme référence, miroir Git optionnel). `App.tree()` charge
  depuis le backend actif ; le modèle commun est dans `models.py`.
- **Écritures en deux temps** : `arbre_proposer(operations)` applique les ops (`tree/ops.py`, sur copie) et
  renvoie diff + nouvelles alertes de cohérence + jeton ; `arbre_appliquer(jeton)` (usage unique, 1 h, refusé
  si l'arbre a changé) commit. Catalogue des ops : `docs/operations.md`. Règle `EXIGER_SOURCE` : pas
  d'événement/filiation sans citation sauf `non_source` + `motif`.
- **Sources externes** (`sources/`) : chaque module reçoit un `SourceContext` (http + journal + config) et
  renvoie une enveloppe (`sources/base.py` : `envelope`, `error_envelope`, `rank`) ; toute requête est tracée
  au journal, y compris négative.
- **Preuve** : `evidence.py` / `statuts.py` calculent le statut (confirmé/probable/hypothèse/contradictoire/
  réfuté) en regroupant les citations par source originale indépendante. `matching.py` + `normalize/`
  (noms, dates républicaines/juliennes, lieux COG) pour le recoupement d'homonymes.
- **Vivants** (`privacy.py`) : tout outil réseau recevant un nom ou un id de personne doit appeler
  `_garde(...)` (→ `privacy.external_guard`) avant l'appel externe.

## Invariants vérifiés par les tests

- `outils.py` est le catalogue unique des outils (effet : lecture/réseau/écriture/identifiants, décision du
  hook). Ajouter un outil = l'enregistrer dans `server.py`, le déclarer dans `outils.OUTILS`, l'ajouter au
  bon matcher de `hooks/hooks.json` (allow pour lecture/proposition, ask pour écriture/identifiants), et, s'il
  envoie des paramètres de personne, l'inscrire dans `GARDE_VIVANTS` et appeler `_garde`
  (`tests/test_outils.py`, `tests/test_garanties.py`).
- Les hooks matchent `mcp__.*genealogiste.*__…` pour couvrir le plugin stdio et le serveur HTTP Docker.
- Tests : fixtures `app` / `app_famille` (`tests/conftest.py`) créent une `App` isolée en tmp ; DNS simulé
  (aucune résolution réelle) ; HTTP mocké avec `respx` ; faux Gramps Web dans `tests/gramps_fake.py` ;
  GEDCOM de test dans `tests/fixtures/`.

## Publication

Claude Code ne propose une mise à jour que si la version change. `make version V=x.y.z` met à jour
`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `mcp/pyproject.toml` et `uv.lock` ensemble ;
`test_version.py` échoue si elles divergent.

## Docs de référence

`docs/` : `operations.md` (ops d'édition), `gedcom-extensions.md` (classification des citations),
`securite.md` (confinement fichiers, politique réseau, vivants, `MCP_TOKEN`), `gramps-web.md`, `pieces.md`,
`notes.md`, `geneweb.md`. Variables d'environnement : `README.md` et `.env.example`.
