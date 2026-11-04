# Plugin Claude Code « genealogiste »
MCP := mcp
UV  := uv --directory $(MCP)

.PHONY: help install test test-gramps lint format check run run-http docker-build docker-up docker-gramps docker-down validate clean verifier-archives

help: ## Liste des cibles
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

install: ## Installe les dépendances du serveur MCP (uv)
	$(UV) sync

test: ## Lance les tests pytest (APIs mockées, aucun accès réseau)
	$(UV) run pytest

GW_TEST := docker compose -f docker-compose.test.yml
GW_PORT ?= 5056

test-gramps: ## Tests d'intégration sur un Gramps Web jetable (Docker, données fictives)
	$(GW_TEST) up -d --wait
	$(GW_TEST) exec -T grampsweb python3 -m gramps_webapi user add sosa-test sosa-test --role 3 || true
	GENEALOGISTE_TEST_GRAMPS_URL=http://127.0.0.1:$(GW_PORT) $(UV) run pytest -m gramps_live tests/test_gramps_live.py; \
	  status=$$?; $(GW_TEST) down -v; exit $$status

lint: ## Vérifie le style (ruff)
	$(UV) run ruff check src tests

format: ## Formate le code (ruff)
	$(UV) run ruff check --fix src tests

check: ## Vérifie la configuration et l'arbre de travail
	$(UV) run genealogiste-mcp --check

run: ## Lance le serveur MCP en stdio (comme Claude Code)
	$(UV) run genealogiste-mcp

run-http: ## Lance le serveur MCP en HTTP streamable sur :8765
	$(UV) run genealogiste-mcp --transport streamable-http --port 8765

docker-build: ## Construit l'image du serveur MCP
	docker compose build

docker-up: ## Démarre le serveur MCP (HTTP :8765)
	docker compose up -d

docker-gramps: ## Démarre le serveur MCP + Gramps Web (:5055)
	docker compose --profile gramps up -d

docker-down: ## Arrête la pile
	docker compose --profile gramps down

validate: ## Valide le manifeste du plugin (nécessite la CLI claude)
	claude plugin validate .

clean: ## Supprime caches et environnements
	rm -rf $(MCP)/.venv $(MCP)/.pytest_cache $(MCP)/.ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

verifier-archives: ## Vérifie que les sites du référentiel des archives répondent (HEAD)
	$(UV) run python scripts/verifier_archives.py
