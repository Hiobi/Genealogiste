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
Les tests `gramps_live` sont ignorés sans URL de test. Les dépendances sont téléchargées
avant les tests ; uv passe ensuite hors ligne. Aucun secret d'API ni compte Claude n'est requis.

Le validateur Claude Code est installé via l'installateur officiel, en version 2.1.319.
La validation n'invoque pas de modèle. L'icône est `.claude-plugin/icon.png` (PNG carré 1024 px).
Un seul avertissement reste attendu, visible et non bloquant (`--strict` n'est pas activé) : `CLAUDE.md`
à la racine n'est pas chargé comme contexte du plugin. Il y reste volontairement, comme consignes de
développement du dépôt.
Ce contrôle valide la structure, pas le fonctionnement en session, les permissions effectives du client ni l'acceptation dans un annuaire de plugins.

## Protection de main

Après un premier passage réussi, configurer une règle de protection/ruleset pour `main` :
PR obligatoire et contrôles requis `Tests Python 3.11`, `Tests Python 3.13`,
`Ruff et manifestes`. Éviter de renommer ces jobs sans adapter la règle.
L'ajout des workflows ne configure pas automatiquement cette protection GitHub.

## Matrice Gramps (#267)

Le workflow `Intégration Gramps` (`.github/workflows/gramps.yml`) lit `compatibilite-gramps.json` et lance un job
par version : `Gramps Web <image> (API <version>)` pour chaque image épinglée par empreinte (plancher, image par
défaut, plafond ; `make test-gramps` sur un arbre fictif jetable, conteneurs et volumes détruits même après un
échec) et `Gramps Desktop <version>` pour les bibliothèques Gramps 5.2, 6.0 et 6.1 (`make test-gramps-desktop`,
PyGObject des paquets Ubuntu). `fail-fast` est désactivé : chaque version rend son verdict.

Déclenchement : PR et pushes vers `main` qui touchent l'intégration Gramps (liste de chemins du workflow), chaque
mercredi et sur demande (`Run workflow`). Il n'est pas déclaré requis pour les PR : un workflow filtré par chemins
reste en attente sur les PR qu'il ignore. Versions, plage et limites : [Gramps Web](gramps-web.md#compatibilité-des-versions)
et [Gramps Desktop](gramps.md).

## Recette archives planifiée (#143)

`.github/workflows/recette-archives.yml`, chaque mardi et à la demande. `make test-archives` lance
`tests/test_archives_live.py` (marqueur `archives_live`, jamais exécuté par `make test`) : pour chaque service
du référentiel doté d'un champ `recette` (`source` : ARK ou URL de registre de référence, `page`), l'ARK est
résolu sans requête, une fenêtre de 3 vues est listée et une vue téléchargée en 400 px. Quelques requêtes
par service, débit réel du plugin.

| Résultat | Sens | Effet |
|---|---|---|
| `ok` | contrat respecté | `derniere_reussite` mise à jour |
| `protection` | défi anti-robot, coupe-circuit, accès refusé : recette arrêtée, **aucun contournement** | test ignoré (pas un échec de contrat) |
| `echec` | réponse inattendue : le site a changé | test en échec ; le workflow ouvre ou complète l'issue « Recette archives en échec » |

Le résultat de chaque service est inscrit dans `mcp/src/genealogiste_mcp/referentiels/recettes_archives.json`
(`ECRIRE=0` pour ne rien écrire) et exposé par `archives_service` (champ `recette`). Le workflow ne pousse
rien : il publie le fichier en artefact ; le mettre à jour dans le dépôt reste un commit relu.

Lancer la même recette depuis le VPS (`make test-archives ECRIRE=0`) distingue « site changé » (`echec`
partout) de « adresse bloquée » (`protection` depuis le VPS, `ok` ailleurs).

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

Le téléchargement de Gitleaks réessaie l’URL de l’archive puis utilise l’API des releases via `gh`
si cette URL échoue. Les deux chemins sélectionnent la même version et le même fichier ; la vérification
SHA-256 épinglée reste obligatoire avant extraction et exécution. Le jeton fourni à `gh` est celui
de GitHub Actions, avec la permission `contents: read` déjà déclarée, sans secret supplémentaire.
