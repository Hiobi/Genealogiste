# Intégration continue

Le workflow `CI` s'exécute pour les PR vers `main`, les pushes sur `main` et sur demande.
Il utilise Python 3.11 (minimum annoncé) et 3.13, uv 0.11.14 et `mcp/uv.lock`.
`uv sync --locked` échoue si le lockfile nécessite une mise à jour ; `UV_LOCKED=true`
empêche aussi les commandes Make de le réécrire silencieusement.

## Contrôles des PR

- `Tests Python 3.11` et `Tests Python 3.13` : `make test`, dont les tests de cohérence
  des versions du plugin, de la marketplace, du paquet Python et du lockfile.
- `Ruff et manifestes` : `make lint`, puis `make validate` pour la marketplace et
  `claude plugin validate .claude-plugin/plugin.json` pour le manifeste du plugin.

Les tests ordinaires utilisent des données fictives, HTTP simulé et DNS simulé.
Les six tests `gramps_live` sont ignorés sans URL de test. Les dépendances sont téléchargées
avant les tests ; uv passe ensuite hors ligne. Aucun secret d'API ni compte Claude n'est requis.

Le validateur Claude Code est installé via l'installateur officiel, en version 2.1.319.
La validation n'invoque pas de modèle. Les avertissements existants (absence d'icône,
`CLAUDE.md` à la racine non chargé comme contexte du plugin) restent visibles et non bloquants :
`--strict` n'est pas activé. Ce contrôle valide la structure, pas le fonctionnement en session,
les permissions effectives du client ni l'acceptation dans un annuaire de plugins.

## Protection de main

Après un premier passage réussi, configurer une règle de protection/ruleset pour `main` :
PR obligatoire et contrôles requis `Tests Python 3.11`, `Tests Python 3.13`,
`Ruff et manifestes`. Éviter de renommer ces jobs sans adapter la règle.
L'ajout des workflows ne configure pas automatiquement cette protection GitHub.

## Gramps Web sur demande

Dans Actions, choisir `Intégration Gramps`, puis `Run workflow`. Ce workflow est disponible
une fois son fichier présent sur la branche par défaut ; il n'est pas requis pour les PR.
Il lance `make test-gramps` sur Docker avec un arbre fictif jetable, puis détruit les conteneurs
et volumes, y compris après un échec. Il reprend l'image du compose de test (épinglée par empreinte) :
il ne certifie pas une version Gramps de production.

## Reproduire localement

Depuis la racine, avec Python, uv, Git et la CLI Claude installés :

```bash
uv --directory mcp sync --locked
UV_LOCKED=true make test
UV_LOCKED=true make lint
make validate
claude plugin validate .claude-plugin/plugin.json
```

`UV_PYTHON=3.11` ou `UV_PYTHON=3.13` sélectionne l'interpréteur pour uv.
Les versions du validateur et de uv sont explicites dans les workflows ; mettre à jour
les commandes et cette documentation ensemble lors d'un changement de version.

Références : [uv dans GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/),
[installation Claude Code](https://code.claude.com/docs/en/setup),
[validation des manifestes](https://code.claude.com/docs/en/plugins-reference#validate-the-manifest).

## Contrôles de sécurité et conteneur (0.13.0)

Le workflow `Sécurité` s’exécute sur les PR, sur `main` et chaque lundi :
`Secrets et distribution` vérifie les chemins suivis par Git et l’historique avec Gitleaks ;
`Dépendances Python` contrôle tous les groupes du lockfile avec pip-audit. Le job `Conteneur MCP`
construit l’image et teste refus sans jeton, HTTP 401, appel MCP autorisé et permissions privées.
Ces trois noms de checks complètent les trois contrôles Python/Ruff à rendre obligatoires sur `main`.
Les avis de dépendances sont interrogés en ligne : une panne de ce service peut faire échouer le contrôle.
