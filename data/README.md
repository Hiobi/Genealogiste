# data/

Point de montage des données pour `docker compose` (`./data:/data`). Contenu ignoré par Git : l'arbre
(`arbre.ged`), le journal (`journal.jsonl`), les médias et le cache SQLite contiennent des données
personnelles et vivent dans **leur propre dépôt Git**, initialisé automatiquement par le serveur MCP.

En usage local (sans Docker), le répertoire par défaut est `~/.local/share/genealogiste`
(variable `GENEALOGISTE_DATA_DIR`).
