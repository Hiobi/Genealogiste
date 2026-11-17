# Repository Guidelines

## Project Structure & Module Organization

Genealogiste combines a Claude Code/Codex plugin with a Python MCP server.

- `mcp/src/genealogiste_mcp/`: server tools, source adapters, GEDCOM tree operations, Gramps integration, and reference datasets under `referentiels/`.
- `mcp/tests/`: pytest suites and synthetic fixtures in `fixtures/`.
- `commands/`, `agents/`, `skills/`, `hooks/`: plugin workflows and permissions.
- `scripts/`, `mcp/scripts/`: validation, packaging, and archive checks.
- `docs/`, `wiki/`: technical references and publishable wiki sources; `wiki/pages.json` maps published pages to their sources.

## Build, Test, and Development Commands

Run from the repository root; Python commands use `uv --directory mcp`.

- `make install`: install dependencies.
- `make test`: run pytest with mocked external services.
- `make lint`: run Ruff checks.
- `make format`: apply `ruff check --fix`, not `ruff format`.
- `make run` / `make run-http`: start stdio / HTTP transport (port 8765).
- `make docker-build`: build the container.
- `make check`: validate configuration and working-tree setup.
- `python3 scripts/verifier_distribution.py`: check tracked files for private-data risks.

## Coding Style & Naming Conventions

Target Python 3.11+, use four-space indentation, and follow existing annotations and module conventions. Ruff targets a 110-character line length; E501 is ignored.

Public MCP tools and business operations use French, accent-free `snake_case`, such as `arbre_proposer`. Preserve established internal names such as `TreeStore.load`. Public renames require compatibility and coordinated documentation, catalogue, hooks, and tests.

## Testing Guidelines

Name tests `test_*.py` and functions `test_*`. Use pytest, `respx`, mocked DNS, and isolated `app`/`app_famille` fixtures. Add behavioral regression tests for fixes; no numerical coverage threshold is configured.

Run one module with `uv --directory mcp run pytest tests/test_tree_ops.py`. `make test-gramps` uses disposable Docker services; `make test-archives` explicitly contacts real archives.

## Commit & Pull Request Guidelines

Write French Conventional Commits, for example `fix(archives): corriger la pagination`. Keep PRs focused, link related issues, explain behavior changes, and report validation results. Update affected documentation and require passing CI.

For documentation changes, validate wiki links with `uv --directory mcp run python ../scripts/preparer_wiki.py --output /tmp/genealogiste-wiki-review`.

## Security & Architecture

Keep family data, credentials, and production exports outside the plugin checkout; contribute synthetic fixtures only. Tree mutations require proposal, displayed diff, explicit approval, then application. Guard external person lookups against disclosing living people.

Read `.claude/CLAUDE.md` for tool-registration invariants, `docs/securite.md` for network changes, and `docs/adaptation-codex.md` before changing Codex packaging or permissions.
