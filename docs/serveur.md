# Installation sur un serveur

Ce guide couvre l'usage de Genealogiste sur une machine sans interface (VPS, serveur domestique) : plugin
Claude Code lancé en ligne de commande, ou serveur MCP en HTTP. La procédure ci-dessous a été déroulée sur
une Debian 12 neuve (conteneur `debian:12`, voir [vérification](#vérification-de-ce-guide)).

Les données d'un arbre contiennent des personnes vivantes : répertoire privé, droits restreints, sauvegardes
chiffrées, jamais dans un dépôt public.

## Prérequis

```bash
sudo apt update
sudo apt install -y git curl ca-certificates make tesseract-ocr tesseract-ocr-fra tesseract-ocr-lat
curl -LsSf https://astral.sh/uv/install.sh | sh   # installe uv dans ~/.local/bin
```

- `git` : obligatoire (historique de l'arbre, une modification = un commit).
- `uv` : lance le serveur MCP et installe Python et les dépendances verrouillées.
- Tesseract avec `fra` et `lat` : facultatif ; sans lui, les PDF scannés sont lus en image (plus de tokens).
  `/genealogiste:diagnostic` signale une langue absente.

## Préparer l'environnement avant le premier lancement

Claude Code laisse un délai limité à la connexion d'un serveur MCP. Au tout premier lancement, `uv` doit
télécharger Python et les dépendances : sur un réseau lent, la connexion échoue (`/mcp` affiche le serveur
déconnecté). Préparer l'environnement une fois, avant d'ouvrir une session :

```bash
claude plugin marketplace add Hiobi/Genealogiste
claude plugin install genealogiste@genealogiste
# chemin du plugin installé (version courante)
PLUGIN=$(ls -d ~/.claude/plugins/cache/genealogiste/genealogiste/*/ | sort -V | tail -1)
uv --directory "$PLUGIN/mcp" sync --locked          # télécharge Python et les dépendances
uv --directory "$PLUGIN/mcp" run genealogiste-mcp --check   # configuration, arbre, OCR ; code 2 si invalide
```

Si la connexion reste trop lente, augmenter le délai de démarrage des serveurs MCP de Claude Code
(`MCP_TIMEOUT`, en millisecondes, par exemple `MCP_TIMEOUT=60000 claude`).

Toujours lancer Claude Code depuis un **dossier de travail privé**, distinct du dépôt du plugin.

## Emplacements et variables utiles

| Élément | Défaut | Variable |
|---|---|---|
| Données (arbre, `.git`, journal, médias) | `~/.local/share/genealogiste` | `GENEALOGISTE_DATA_DIR` |
| Configuration privée | `<données>/.env` | `GENEALOGISTE_ENV_FILE` |
| Cache des réponses (SQLite) | `~/.cache/genealogiste/cache.sqlite` | `GENEALOGISTE_CACHE`, `GENEALOGISTE_CACHE_MAX_MO` |
| Cache des images | `<données>/cache-images` | `GENEALOGISTE_CACHE_IMAGES_DIR`, `GENEALOGISTE_CACHE_IMAGES_MAX_MO` |
| Journal d'exploitation | `<données>/logs/serveur.log` | `GENEALOGISTE_LOG_FICHIER`, `GENEALOGISTE_LOG_NIVEAU` |
| Journal de recherche | `<données>/journal.jsonl` | — |

Sur un serveur, régler aussi : `GENEALOGISTE_HTTP_DUREE_MAX` (plafond d'un appel réseau), `GENEALOGISTE_DEBIT_DEFAUT`
(espacement des requêtes vers un même site), `GENEALOGISTE_GIT_DELAI` (push vers un miroir),
`GENEALOGISTE_NOTES_ATTENTE`. Toutes sont décrites dans `.env.example` et la [sécurité technique](securite.md).
Plusieurs serveurs peuvent partager les mêmes données (cache en WAL, journal verrouillé), mais une seule
version doit tourner : après une mise à jour, reconnecter chaque session ([Mises à jour](../wiki/Mises-a-jour.md)).

## Transport HTTP

Pour un serveur MCP partagé (client distant, Docker), utiliser le transport HTTP avec un jeton :

```bash
export MCP_TOKEN=$(openssl rand -hex 32)          # à conserver hors du dépôt
uv --directory "$PLUGIN/mcp" run genealogiste-mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

- Le serveur refuse d'écouter hors de `127.0.0.1` sans `MCP_TOKEN`.
- `GET /health` répond sans authentification (`statut`, `version`), pour un superviseur ou un healthcheck.
- Une configuration fatale (variable invalide, git absent, données non inscriptibles) arrête le service avec
  le code 2 et la cause sur stderr.

Exposer le service derrière un proxy inverse TLS, le jeton restant exigé. Exemple avec Caddy (certificat
automatique) :

```caddyfile
genealogie.example.org {
    reverse_proxy 127.0.0.1:8765
}
```

Côté client :

```bash
claude mcp add --transport http genealogiste https://genealogie.example.org/mcp \
  --header "Authorization: Bearer $MCP_TOKEN"
```

Avec Docker, suivre [Docker et Portainer](../wiki/Docker-et-Portainer.md) : le conteneur utilise `/health`.

## Sauvegarde et restauration

```bash
make sauvegarde SORTIE=~/sauvegardes-genealogiste       # archive datée .tar.gz, droits 600
make restauration ARCHIVE=~/sauvegardes-genealogiste/genealogiste-AAAAMMJJ-HHMMSS.tar.gz VERS=/tmp/essai-restauration
```

Depuis le plugin installé, sans `make` : `uv --directory "$PLUGIN/mcp" run python -m genealogiste_mcp.sauvegarde …`.

- L'archive contient le répertoire de données complet (historique Git compris) et les médias et notes
  configurés hors de ce répertoire. Elle exclut les caches, exports, journaux d'exploitation, propositions
  temporaires et **les secrets** (`.env`, clés) : les conserver séparément, chiffrés.
- La restauration refuse un dossier non vide et tout chemin dangereux, puis vérifie `git fsck`, l'empreinte
  et la lecture de l'arbre. Contrôler ensuite dans une instance isolée ([Sauvegardes](../wiki/Sauvegardes.md)).
- Chiffrer les archives avant de les copier ailleurs (par exemple `age` ou `gpg`).
- Gramps Web : sauvegarder aussi sa base et ses volumes selon sa propre procédure.

Nettoyage : `cache_purger()` applique les plafonds de cache ; les anciennes versions du plugin se suppriment
selon [Mises à jour](../wiki/Mises-a-jour.md).

## Modes de permission

Relevé avec Claude Code 2.1.325 en `claude -p` (dossier jetable, données fictives) :

| Classe d'outil (hook) | Exemple | `claude -p` par défaut | `--allowedTools <outil>` | `--permission-mode bypassPermissions` ou `acceptEdits` |
|---|---|---|---|---|
| `allow` (lecture, proposition, sources) | `arbre_info`, `matchid_recherche` | exécuté | exécuté | exécuté |
| sans décision du hook | `archives_service`, `archive_image`, `piece_archiver` | **refusé** (personne pour accepter) | exécuté | — |
| `ask` (écriture, identifiants) | `arbre_appliquer` | **refusé** | **refusé** | **refusé** |

- Une écriture dans l'arbre exige toujours un accord humain : en mode non interactif elle est refusée, quel que
  soit le mode de permission (aucune disparition de l'accord constatée en `claude -p`). La proposition reste
  en attente (`arbre_statut_transaction(jeton)` : `en_attente`) jusqu'à expiration.
- En mode interactif, l'outil `ask` affiche la demande d'accord. Un sous-agent hérite des mêmes hooks.
- Profil recommandé pour une recherche sans surveillance (lecture et collecte, aucune écriture d'arbre) :

```bash
claude -p "…" --allowedTools \
  "mcp__plugin_genealogiste_genealogiste__archives_service" \
  "mcp__plugin_genealogiste_genealogiste__ark_resoudre" \
  "mcp__plugin_genealogiste_genealogiste__archive_image"
```

  Ajouter `piece_archiver` seulement si l'archivage des vues dans le répertoire des médias est voulu ; sa
  classe d'autorisation est discutée dans [#153](https://github.com/Hiobi/Genealogiste/issues/153). La
  validation différée des écritures est suivie dans [#154](https://github.com/Hiobi/Genealogiste/issues/154).

## Limites connues

- Plusieurs services d'archives sont derrière un défi anti-robot (Cloudflare, captcha). Le plugin le détecte,
  met l'hôte en pause (coupe-circuit), l'exclut quelques jours si le défi persiste après la pause
  (`GENEALOGISTE_EXCLUSION_ANTIROBOT`, 7 jours par défaut) et ne tente **aucun** contournement. Sans
  navigateur sur le serveur, la réponse porte `suite` (lien à ouvrir par l'utilisateur depuis son poste, ce
  qu'il faut relever, reprise par `source_collee`, `piece_archiver` ou `media_enregistrer`) ; avec
  `enquete=<id>`, la consultation devient une tâche manuelle de l'enquête et la recherche continue sur les
  autres pistes. `archives_service` montre sous `defi_observe` les défis constatés depuis cette machine ;
  `cache_purger("coupe_circuit")` autorise un nouvel essai. Depuis un poste de développement, AD59 répondait
  et Gallica était bloqué ; l'accès réel depuis une adresse de VPS reste à mesurer
  (`GENEALOGISTE_RECETTE_ENVIRONNEMENT=vps make test-archives`, [#150](https://github.com/Hiobi/Genealogiste/issues/150)).
- La recherche d'un registre depuis une commune et une année reste manuelle pour la plupart des services
  ([#121](https://github.com/Hiobi/Genealogiste/issues/121)).
- `/genealogiste:diagnostic` vérifie l'ensemble (configuration, dépendances, droits, disque, caches, sources
  joignables) et donne un remède par problème.

## Vérification de ce guide

Déroulé dans un conteneur `debian:12` neuf : installation des prérequis, `uv sync --locked`, `--check`,
diagnostic local, sauvegarde puis restauration vérifiée. Le relevé des permissions a été fait sur un poste
avec Claude Code 2.1.325 ; il est à refaire après une mise à jour majeure de Claude Code.
