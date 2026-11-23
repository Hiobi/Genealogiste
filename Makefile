# Plugin Claude Code « genealogiste »
MCP := mcp
UV  := uv --directory $(MCP)

.PHONY: version help install hooks profil-campagne test sauvegarde restauration test-archives test-gramps test-gramps-matrice test-gramps-desktop test-codex lint format check run run-http docker-build docker-up docker-gramps docker-down validate clean verifier-archives verifier-telechargements

help: ## Liste des cibles
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

install: ## Installe les dépendances du serveur MCP (uv)
	$(UV) sync

test: ## Lance les tests pytest (APIs mockées, aucun accès réseau)
	$(UV) run pytest

test-codex: ## Recette native Codex CLI 0.166 à 0.169, fournisseur local et données fictives
	python3 scripts/verifier_codex.py

# Image : GRAMPSWEB_IMAGE (défaut : l'image épinglée de docker-compose.test.yml) ; GRAMPSWEB_API = version d'API
# attendue (vérifiée par le test). Port et projet Compose isolables : GW_PORT=5067 COMPOSE_PROJECT_NAME=…
GW_PORT ?= 5056
GW_TEST = GRAMPSWEB_TEST_PORT=$(GW_PORT) $(if $(GRAMPSWEB_IMAGE),GRAMPSWEB_IMAGE=$(GRAMPSWEB_IMAGE)) \
	docker compose -f docker-compose.test.yml

test-gramps: ## Tests d'intégration sur un Gramps Web jetable (Docker, données fictives ; GRAMPSWEB_IMAGE=…)
	$(GW_TEST) up -d --wait
	$(GW_TEST) exec -T grampsweb python3 -m gramps_webapi user add sosa-test sosa-test --role 3 || true
	$(GW_TEST) exec -T grampsweb python3 -m gramps_webapi user add sosa-membre sosa-membre --role 1 || true
	$(GW_TEST) exec -T grampsweb python3 -m gramps_webapi user add sosa-contributeur sosa-contributeur --role 2 || true
	$(GW_TEST) exec -T grampsweb python3 -m gramps_webapi user add sosa-owner sosa-owner --role 4 || true
	$(GW_TEST) exec -T grampsweb python3 -m gramps_webapi user add sosa-invite sosa-invite --role 0 || true
	GENEALOGISTE_TEST_GRAMPS_URL=http://127.0.0.1:$(GW_PORT) GENEALOGISTE_TEST_GRAMPS_API=$(GRAMPSWEB_API) \
	  $(UV) run pytest -m gramps_live tests/test_gramps_live.py; \
	  status=$$?; $(GW_TEST) down -v; exit $$status

test-gramps-matrice: ## test-gramps sur chaque image de compatibilite-gramps.json (ROLES="plancher plafond" pour filtrer)
	python3 scripts/matrice_gramps.py web $(ROLES)

test-gramps-desktop: ## Export Gramps XML relu par Gramps Desktop 5.2/6.0/6.1 sans interface (GRAMPS_DESKTOP=6.0, GI=systeme)
	$(UV) run python ../scripts/verifier_gramps_desktop.py $(foreach v,$(GRAMPS_DESKTOP),--version $(v)) \
	  --gi $(or $(GI),auto) $(if $(PYTHON),--python $(PYTHON))

test-archives: ## Recette de contrat sur les services d'archives réels (réseau, quelques requêtes par service)
	GENEALOGISTE_TEST_ARCHIVES=1 GENEALOGISTE_RECETTE_ECRIRE=$(or $(ECRIRE),1) $(UV) run pytest -m archives_live tests/test_archives_live.py -rs

sauvegarde: ## Archive datée des données, médias et notes (SORTIE=dossier ; secrets exclus, droits 600)
	$(UV) run python -m genealogiste_mcp.sauvegarde sauvegarder --sortie $(or $(SORTIE),$(HOME)/sauvegardes-genealogiste)

restauration: ## Restaure une archive dans un dossier vide et la vérifie (ARCHIVE=… VERS=…)
	$(UV) run python -m genealogiste_mcp.sauvegarde restaurer $(ARCHIVE) --vers $(VERS)

hooks: ## Régénère hooks/hooks.json depuis le catalogue des outils (outils.py)
	$(UV) run python ../scripts/generer_hooks.py

profil-campagne: ## Affiche le profil de permissions d'une campagne sans surveillance (PREFIXE=… pour le serveur HTTP)
	@$(UV) run python ../scripts/generer_hooks.py --profil-campagne $(if $(PREFIXE),--prefixe $(PREFIXE),)

lint: ## Vérifie le style (ruff)
	$(UV) run ruff check src tests scripts ../scripts

format: ## Formate le code (ruff)
	$(UV) run ruff check --fix src tests scripts ../scripts

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

version: ## Affiche la version, ou la fixe partout : make version V=0.3.0 (à faire à chaque publication)
	@python3 scripts/version.py $(V)
	@if [ -n "$(V)" ]; then $(UV) lock -q && echo "uv.lock mis à jour"; fi

validate: ## Valide le manifeste du plugin (nécessite la CLI claude)
	claude plugin validate .

clean: ## Supprime caches et environnements
	rm -rf $(MCP)/.venv $(MCP)/.pytest_cache $(MCP)/.ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

verifier-archives: ## Vérifie que les sites des référentiels (archives, sites tiers, services de contexte) répondent (HEAD, repli GET sans lecture du corps)
	$(UV) run python scripts/verifier_archives.py

verifier-telechargements: ## Recette réseau explicite sur une vue publique (SERVICE=ad59|ad59_td|suisse|loc|tous)
	$(UV) run python ../scripts/verifier_telechargements.py --service $(or $(SERVICE),ad59)
