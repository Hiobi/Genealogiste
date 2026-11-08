# Contribuer

Ne joindre aucune donnée familiale réelle, aucun secret ni export de production à une contribution.
Utiliser les fixtures synthétiques et garder les données de développement hors du checkout du plugin.
Le scan GitHub et le contrôle de distribution complètent cette règle, sans remplacer la relecture.

Outils MCP et opérations métier : français sans accents, snake_case (`arbre_proposer`, `notes_generer`).
Conserver les conventions établies des modules internes (`TreeStore.load`, `Person`, `is_living`) ;
aucune traduction générale. Pour renommer un outil public, prévoir la compatibilité et mettre à jour
commandes, hooks, catalogue, documentation et tests. Messages de commit en français, Conventional Commits.

Depuis la racine : `make install`, `make test`, `make lint`, `python3 scripts/verifier_distribution.py`.
`make format` applique `ruff check --fix` ; il ne lance pas `ruff format`. Pour pytest directement,
se placer dans `mcp/` afin de charger sa configuration. `make test-gramps` utilise Docker et uniquement
des données fictives. Toute régression corrigée doit être vérifiée au niveau du comportement concerné.

Avant publication, synchroniser les versions avec `make version V=x.y.z`, vérifier les manifestes et
les contrôles GitHub. Pour les changements de déploiement, suivre [docs/production.md](docs/production.md).

## Documentation

Le README présente le plugin et le démarrage. Les guides utilisateur sont publiés dans le wiki GitHub
à partir de sources relues dans `wiki/` et des références conservées dans `docs/`.
`wiki/pages.json` indique la source de chaque page ; ne pas modifier directement sa copie publiée.
Les anciens chemins `docs/` restent disponibles pour les outils et les liens existants.

Avant une PR documentaire : `uv --directory mcp run python ../scripts/preparer_wiki.py --output /tmp/genealogiste-wiki-a-relire`.
Le contrôle des liens est aussi exécuté en CI. Après fusion, republier depuis `main` selon
[la procédure de maintenance](wiki/Maintenance.md), avec la version et la révision source.
