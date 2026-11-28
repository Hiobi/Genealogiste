# Utiliser Genealogiste dans Claude Desktop

L’application Claude Desktop (macOS, Windows, Linux en bêta) comporte plusieurs espaces. Genealogiste
fonctionne dans l’onglet **Code**, qui est Claude Code dans une fenêtre : mêmes commandes, skills,
agents, hooks et serveur MCP qu’au terminal. Le **chat** de l’application ne charge qu’une partie d’un
plugin et n’est pas pris en charge.

| Espace de Claude Desktop | Genealogiste | Pourquoi |
|---|---|---|
| Onglet **Code**, session locale ou SSH | oui | plugins, hooks et serveurs MCP locaux chargés comme dans le CLI |
| Onglet Code, session WSL | non | plugins non disponibles en session WSL |
| Onglet Code, session cloud | non | un plugin installé en portée `user` ou `local` n’y est pas chargé ; l’arbre privé n’y est pas accessible |
| **Chat** | non | agents et serveur MCP local du plugin ignorés, hooks non garantis : sans les outils MCP, les commandes ne servent à rien et la demande d’accord avant écriture ne serait plus assurée |

État constaté dans la documentation d’Anthropic au 2026-11-28 ; le projet n’a pas encore de recette
dans Claude Desktop. Signalez tout écart par une issue.

## 1. Installer le plugin

Le plus sûr est d’installer depuis un terminal, comme pour le CLI. Claude Desktop et le CLI lisent les
mêmes réglages : un plugin installé en portée `user` apparaît aussi dans l’onglet Code.

```bash
claude plugin marketplace add Hiobi/Genealogiste
claude plugin install genealogiste@genealogiste --scope user
```

Sans le CLI : dans une session locale de l’onglet Code, bouton **+** à côté de la zone de saisie, puis
**Plugins > Browse plugins** (ou **Manage plugins**). La façon d’y ajouter une marketplace n’est pas
documentée ; si `genealogiste` n’apparaît pas, passer par le terminal ci-dessus.

Prérequis inchangés : Git et [uv](https://docs.astral.sh/uv/getting-started/installation/) doivent être
installés et trouvés par l’application (voir [Installation](Installation.md)).

## 2. Ouvrir une session

Ouvrir une session **locale** de l’onglet Code sur un **dossier de travail privé**, distinct du dépôt du
plugin, puis demander :

> Utilise arbre_info et donne-moi le backend et le nombre de personnes, sans modifier l’arbre.

En cas d’erreur, lancer `/genealogiste:diagnostic`.

## 3. Variables d’environnement

Une application lancée depuis le menu ou le Dock ne reprend pas forcément les `export` de votre
terminal (`GENEALOGISTE_DATA_DIR`, `GENEALOGISTE_BACKEND`, identifiants de sources). Le serveur
démarre alors avec ses valeurs par défaut, et peut ouvrir un autre arbre que celui attendu.

- Avec le dossier de données par défaut (`~/.local/share/genealogiste`), mettre les réglages dans son
  `.env` (voir [Configuration](Configuration.md)) : il est lu quel que soit le mode de lancement.
- Avec un autre dossier de données, le `.env` ne peut pas désigner ce dossier lui-même (il est lu
  *dans* ce dossier). Déclarer `GENEALOGISTE_DATA_DIR` dans la clé `env` des réglages de Claude Code
  (`~/.claude/settings.json`), communs au CLI et à l’onglet Code :

  ```json
  { "env": { "GENEALOGISTE_DATA_DIR": "/home/vous/genealogie-privee" } }
  ```

- Vérifier le résultat avec `/genealogiste:diagnostic` (dossier de données, backend) avant toute écriture.
- uv introuvable au démarrage du serveur : l’application ne voit pas le `PATH` du terminal ; installer uv
  dans un emplacement standard ou relancer l’application depuis un terminal.

## 4. Vérifier la demande d’accord

Les écritures dans l’arbre passent par `arbre_proposer` puis `arbre_appliquer`, et le hook du plugin
demande votre accord avant chaque outil d’écriture (voir [Confidentialité](Confidentialite.md)). Au
premier usage dans Claude Desktop, faire un essai sur l’arbre fictif du [tutoriel](Demarrage.md) :
l’application doit afficher une demande d’autorisation avant `arbre_appliquer`. Si elle ne s’affiche
pas, arrêter et ouvrir une issue.

## Linux

L’application est en bêta pour Debian 12+ et Ubuntu 22.04+ (x86_64, arm64), via le dépôt apt
d’Anthropic ; elle comprend l’onglet Code. Sur les autres distributions, utiliser le CLI. La
documentation ne précise pas que plugins et hooks s’y comportent comme sous macOS et Windows : faire
la vérification du point 4.

## Références

- [Claude Code dans l’application desktop](https://code.claude.com/docs/en/desktop)
- [Application desktop sous Linux](https://code.claude.com/docs/en/desktop-linux)
- [Prise en charge des plugins selon la plateforme](https://claude.com/docs/plugins/platform-support)
- [Installer des plugins](https://code.claude.com/docs/en/discover-plugins)
