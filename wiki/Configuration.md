# Configurer selon votre besoin

Commencez sans fichier de configuration pour le mode fichier local. Ajoutez seulement les options
nécessaires au service ou à la fonctionnalité que vous souhaitez utiliser.

## Où placer la configuration

Les variables peuvent être exportées dans le terminal qui lance Claude Code. Pour les conserver dans
un fichier, copier le [modèle .env.example](../.env.example) dans le dossier privé de données.
Pour un dossier personnalisé, exporter d’abord `GENEALOGISTE_DATA_DIR` : le serveur doit savoir où chercher
son `.env`. On peut aussi utiliser `GENEALOGISTE_ENV_FILE` avec un chemin absolu privé.
Les variables déjà présentes dans l’environnement priment sur le fichier. Ce `.env` est un fichier
simple `CLE=valeur` : utiliser des chemins absolus ou `~`, sans expressions shell ni `$HOME` à développer.

```bash
export GENEALOGISTE_DATA_DIR="$HOME/genealogie-privee"
mkdir -p "$GENEALOGISTE_DATA_DIR"
chmod 700 "$GENEALOGISTE_DATA_DIR"
# Depuis votre copie du code public :
cp .env.example "$GENEALOGISTE_DATA_DIR/.env"
chmod 600 "$GENEALOGISTE_DATA_DIR/.env"
```

Le modèle est un point de départ, pas une liste de comptes à créer. Redémarrer le serveur MCP après
modification. Pour inspecter la configuration depuis un checkout : `make check`, avec le même environnement.
Ne publier ni le `.env`, ni la sortie complète d’un diagnostic contenant des données personnelles.

## Arbre et sources

| Variable | Quand la renseigner |
|---|---|
| `GENEALOGISTE_DATA_DIR` | Pour choisir le dossier privé de l’arbre, du journal et des médias |
| `GENEALOGISTE_CACHE` | Pour déplacer le cache SQLite |
| `GENEALOGISTE_BACKEND` | `fichier` par défaut ; `gramps` pour travailler directement dans Gramps Web |
| `GENEALOGISTE_WIKITREE_APPID` | Avant une recherche WikiTree ; identifiant d’application libre, par exemple `genealogiste-mon-pseudo` |
| `GENEALOGISTE_MATCHID_TOKEN` | Si le service matchID le requiert pour un appariement CSV par lot ; inutile pour commencer en local |
| `GENEALOGISTE_OFFLINE` | `1` pour n’utiliser que le cache lors des recherches de sources |
| `GENEALOGISTE_EXIGER_SOURCE` | `1` par défaut : fait ou filiation sans citation refusés sauf exception explicitement motivée |
| `GENEALOGISTE_STRICT` | `1` pour le mode strict de calcul de preuve |

Les règles de citation et de preuve sont expliquées dans le [parcours de recherche](Parcours-de-recherche.md).
Les identifiants FamilySearch ne doivent plus être configurés : l’ancien exporteur est désactivé.

## Fonctions facultatives

| Besoin | Variables et guide |
|---|---|
| Gramps Web | `GENEALOGISTE_GRAMPS_URL`, `GENEALOGISTE_GRAMPS_USER`, `GENEALOGISTE_GRAMPS_PASSWORD` ; [guide Gramps](../docs/gramps-web.md) |
| Miroir Git privé | `GENEALOGISTE_GIT_MIRROR`, `GENEALOGISTE_GIT_REMOTE` ; aucun dépôt public pour l’arbre |
| Notes Markdown/Obsidian | `GENEALOGISTE_NOTES_DIR` ; vide = désactivées ; [guide des notes](../docs/notes.md) |
| Confidentialité des notes | `GENEALOGISTE_NOTES_VIVANTS=masquer` par défaut ; `complet` pour un espace strictement privé |
| Régénération des notes | `GENEALOGISTE_NOTES_AUTO=true` par défaut ; `GENEALOGISTE_SOSA_RACINE` pour la racine de numérotation |
| Autres emplacements de pièces | `GENEALOGISTE_MEDIA_DIR`, `GENEALOGISTE_RAPPORTS_DIR`, `GENEALOGISTE_EXPORTS_DIR`, `GENEALOGISTE_CACHE_IMAGES_DIR` ; [guide des pièces](../docs/pieces.md) |
| Serveur HTTP | `MCP_TOKEN`, en-tête `Authorization: Bearer` ; [Docker/Portainer](Docker-et-Portainer.md) |
| Service de source sur réseau interne | `GENEALOGISTE_HOTES_AUTORISES` ; dérogation ciblée décrite dans la [sécurité technique](../docs/securite.md) |

Le [modèle de configuration](../.env.example) et les guides thématiques donnent les réglages détaillés.
Ne recopier une configuration complète d’une autre installation qu’après avoir vérifié ses chemins,
son backend et ses comptes : chaque foyer et chaque arbre doivent garder leurs propres données.
