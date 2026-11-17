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

## Lots archives : contribution et revue

Les lots de la [milestone M2](https://github.com/Hiobi/Genealogiste/milestone/2) doivent rester
traçables par service et par fonds, même lorsque plusieurs sites partagent un adaptateur.
Chaque commit nomme les services concernés et référence l'issue précise du lot, par exemple :

```text
feat(archives): adapter la recherche de registres AD25 et AD39

Refs #<issue-du-lot>
```

Chaque PR liste les sites et fonds concernés, les capacités ajoutées (recherche, navigation,
téléchargement, archivage), les tests exécutés et les limites restantes. Utiliser `Closes #…`
uniquement lorsque toute l'issue est satisfaite. La revue vérifie cette traçabilité et la concordance
du référentiel, du tableau de couverture et de la documentation ; cette règle n'est pas encore
un contrôle automatique.

Après chaque lot, publier un bilan dans les issues concernées, avec un détail pour chaque site.
Le commentaire contient la date et le fuseau, les liens vers les issues, la PR et les commits,
la révision testée et l'environnement (local, VPS ou CI). Pour chaque service, préciser :

- le code, le nom, l'URL officielle et le logiciel observé ;
- le fonds testé et une référence reproductible (commune, période, cote ou ARK) ;
- les formulaires, paramètres, API et règles de pagination observés ;
- l'adaptateur ou la configuration modifiés, les capacités ajoutées et les limites ;
- les commandes et résultats des tests simulés, puis les paramètres et résultats des essais réels
  de recherche, navigation, téléchargement et archivage, ainsi que des cas négatifs et de pagination ;
  indiquer explicitement chaque vérification non testée ;
- le verdict (`testé`, `partiel`, `bloqué` ou `inconnu`), les preuves et liens, et la prochaine action.

Un développement vérifié uniquement sur données simulées porte la mention **« implémenté, non éprouvé »**.
Chaque essai réel indique sa date, son environnement et la révision testée : un essai local ne valide
pas le VPS. Garder visibles les protections, erreurs et tâches manuelles. Un résultat vide ou un
blocage ne constitue jamais une preuve d'absence d'acte. L'inventaire des 101 départements ne vaut
pas automatisation de leurs services ni validation de leurs fonds.

## Documentation

Le README présente le plugin et le démarrage. Les guides utilisateur sont publiés dans le wiki GitHub
à partir de sources relues dans `wiki/` et des références conservées dans `docs/`.
`wiki/pages.json` indique la source de chaque page ; ne pas modifier directement sa copie publiée.
Les anciens chemins `docs/` restent disponibles pour les outils et les liens existants.

Avant une PR documentaire : `uv --directory mcp run python ../scripts/preparer_wiki.py --output /tmp/genealogiste-wiki-a-relire`.
Le contrôle des liens est aussi exécuté en CI. Après fusion, republier depuis `main` selon
[la procédure de maintenance](wiki/Maintenance.md), avec la version et la révision source.
