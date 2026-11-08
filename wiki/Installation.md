# Installer Genealogiste

Le parcours recommandé utilise le plugin Claude Code et un arbre local. Gramps Web, Docker et Obsidian
sont des options : ne les installez pas pour un premier essai si vous n’en avez pas besoin.

## 1. Vérifier les prérequis

Dans un terminal :

```bash
claude --version
git --version
uv --version
```

Installer [Claude Code](https://code.claude.com/docs/en/setup), [Git](https://git-scm.com/downloads)
et [uv](https://docs.astral.sh/uv/getting-started/installation/) si une commande manque.
Le serveur nécessite Python 3.11 ou plus. uv peut télécharger Python au premier lancement ; ce premier
lancement nécessite donc une connexion pour Python et les dépendances non encore disponibles.
Les commandes shell de ce guide sont destinées à un terminal POSIX (Linux/macOS ; adapter sous Windows).

## 2. Installer le plugin

```bash
claude plugin marketplace add Hiobi/Genealogiste
claude plugin install genealogiste@genealogiste --scope user
claude plugin list
```

`user` le rend disponible dans vos projets. Pour un seul projet, choisir `--scope local` depuis ce projet ;
`project` partage la déclaration avec ses collaborateurs. Ne mettez jamais de paramètres privés dans
une configuration partagée. La [documentation Claude Code](https://code.claude.com/docs/en/discover-plugins)
détaille les portées.

Dans une session interactive Claude Code, les équivalents sont `/plugin marketplace add Hiobi/Genealogiste`
puis `/plugin install genealogiste@genealogiste` : suivre les choix de portée du panneau.
Ouvrir une nouvelle session après l’installation évite de garder une ancienne instance du serveur.

## 3. Choisir où garder l’arbre

Par défaut, le mode fichier utilise `~/.local/share/genealogiste` (ou `$XDG_DATA_HOME/genealogiste`).
Le cache utilise `~/.cache/genealogiste` (ou `$XDG_CACHE_HOME/genealogiste`).
Aucun compte de source externe n’est requis pour lire ou importer un arbre local.

Pour choisir explicitement un autre dossier **avant de démarrer Claude Code** :

```bash
export GENEALOGISTE_DATA_DIR="$HOME/genealogie-privee"
mkdir -p "$GENEALOGISTE_DATA_DIR"
chmod 700 "$GENEALOGISTE_DATA_DIR"
claude
```

L’environnement doit atteindre le processus Claude qui démarre le serveur. Une application lancée depuis
un menu peut ne pas reprendre les exports de votre terminal. Ne choisissez pas le checkout du plugin
comme dossier de données : le serveur refuse cette configuration.

## 4. Vérifier le premier lancement

Dans `/mcp`, vérifier que `genealogiste` est connecté. Demander :

> Utilise arbre_info et donne-moi le backend et le nombre de personnes, sans modifier l’arbre.

Sur un dossier neuf : `backend` vaut `fichier`, `personnes` vaut `0` et un `arbre.ged` privé est créé.
Si un arbre existe déjà, comparer avec les effectifs attendus au lieu d’attendre zéro.
Passer ensuite au [tutoriel fictif](Demarrage.md).

## Autres parcours

- [Configuration](Configuration.md) pour les options et les sources nécessitant un identifiant.
- [Gramps Web](../docs/gramps-web.md) pour travailler sur un serveur existant.
- [Docker/Portainer](Docker-et-Portainer.md) pour un serveur MCP HTTP.
- [Migration depuis Sosa](../docs/renommage-genealogiste.md) pour une ancienne installation.

Pour développer ou charger le plugin depuis une copie du code :

```bash
git clone https://github.com/Hiobi/Genealogiste.git
claude --plugin-dir ./Genealogiste
```

Le checkout contient le code public ; les données demeurent dans leur dossier privé distinct.
Les contributeurs disposent aussi de `make install`, `make check`, `make test` et `make lint`.
