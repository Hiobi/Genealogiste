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
| Gramps Web | `GENEALOGISTE_GRAMPS_URL`, `GENEALOGISTE_GRAMPS_USER`, `GENEALOGISTE_GRAMPS_PASSWORD` ; `GENEALOGISTE_GRAMPS_NOTES_LIENS=true` pour des liens cliquables dans les notes de preuve ; `GENEALOGISTE_GRAMPS_TACHES=true` pour proposer des tâches dans la vue Tâches ; `GENEALOGISTE_GRAMPS_PRIVE_VIVANTS=propose` pour ajouter aux propositions le marquage privé des vivants touchés (`auto` refusé) ; [guide Gramps](../docs/gramps-web.md) |
| Miroir Git privé | `GENEALOGISTE_GIT_MIRROR`, `GENEALOGISTE_GIT_REMOTE` ; aucun dépôt public pour l’arbre |
| Notes Markdown/Obsidian | `GENEALOGISTE_NOTES_DIR` ; vide = désactivées ; [guide des notes](../docs/notes.md) |
| Confidentialité des notes | `GENEALOGISTE_NOTES_VIVANTS=masquer` par défaut ; `complet` pour un espace strictement privé |
| Régénération des notes | `GENEALOGISTE_NOTES_AUTO=true` par défaut ; `GENEALOGISTE_SOSA_RACINE` pour la racine de numérotation |
| Marqueurs des versions antérieures | `GENEALOGISTE_MARQUEURS=sosa` écrit encore les anciens marqueurs (`<!-- sosa:debut … -->`, `Sosa-*`, `Sosa:auto`), pour un vault ou une base Gramps partagés avec une version antérieure à 0.23.0 ; défaut `genealogiste` ; les deux formes sont toujours lues ; `marqueurs_migrer_proposer` puis `marqueurs_migrer_appliquer` convertissent les anciens après accord ([notes](../docs/notes.md#marqueurs-historiques-sosa), [Gramps Web](../docs/gramps-web.md#marqueurs-historiques-sosa--sosaauto)) |
| Kit Obsidian | `GENEALOGISTE_NOTES_KIT=true` par défaut : vues Bases/Dataview, modèles et extrait CSS déposés par `notes_generer("tout")` |
| Autres emplacements de pièces | `GENEALOGISTE_MEDIA_DIR`, `GENEALOGISTE_RAPPORTS_DIR`, `GENEALOGISTE_EXPORTS_DIR`, `GENEALOGISTE_CACHE_IMAGES_DIR` ; [guide des pièces](../docs/pieces.md) |
| Serveur HTTP | `MCP_TOKEN`, en-tête `Authorization: Bearer` ; [Docker/Portainer](Docker-et-Portainer.md) |
| Budget d’enquête et plafond journalier | `GENEALOGISTE_BUDGET_REQUETES_HOTE` (200), `GENEALOGISTE_BUDGET_IMAGES` (40), `GENEALOGISTE_PLAFOND_JOUR_ARCHIVES` (1000 requêtes par service d’archives et par jour), `GENEALOGISTE_PLAFOND_JOUR_DEFAUT` (1000 requêtes par jour vers tout autre hôte : API, IIIF), `GENEALOGISTE_PLAFONDS_JOUR` (`hote=requetes,…`, prioritaire) ; 0 = illimité ; le budget arrête une boucle d’enquête, le coût réel se plafonne côté client (`--max-budget-usd`) ; `GENEALOGISTE_BUDGET_DUREE_MIN` et `GENEALOGISTE_BUDGET_COUT_TOKENS` sont retirées (ignorées, signalées par `diagnostic`) ; [enquêtes](../docs/enquetes.md), [politique d’accès par service](../docs/securite.md#politique-daccès-par-service) |
| Session sans surveillance | `GENEALOGISTE_ECRITURE=interdite` : le serveur refuse toute écriture, quel que soit le client (défaut `autorisee`) ; [campagne planifiée](../docs/campagne.md) |
| Être joignable par les sites interrogés | `GENEALOGISTE_CONTACT` (adresse ou URL, facultatif, jamais par défaut) : ajouté au User-Agent de chaque requête externe ; donnée personnelle envoyée à tous les sites, jamais journalisée ; sans effet si `GENEALOGISTE_USER_AGENT` est défini ; [identification](../docs/securite.md#identification--user-agent-et-contact-facultatif) |
| Ménager les sites interrogés | Défauts prudents, à ne baisser qu’en connaissance de cause : `GENEALOGISTE_DEBIT_DEFAUT` (1,5 s : intervalle entre deux requêtes vers un hôte sans règle propre) et `GENEALOGISTE_DEBITS` (`hote=secondes,…`, prioritaire) ; `GENEALOGISTE_RALENTISSEMENT_MAX` (60 s : intervalle maximal d’un hôte ralenti après une surcharge 429 ou 5xx, 0 désactive) ; `GENEALOGISTE_COUPE_CIRCUIT` (1800 s de pause après un défi anti-robot) ; `GENEALOGISTE_EXCLUSION_ANTIROBOT` (604800 s, soit 7 jours d’exclusion si le défi persiste ; 0 = pause seule) ; aucun contournement n’est tenté ; [débit](../docs/securite.md#débit--jamais-de-requêtes-en-rafale), [anti-robot](../docs/securite.md#échecs-mémorisés-coupe-circuit-caches-bornés) |
| Contexte historique | `GENEALOGISTE_CONTEXTE_SERVICES` (codes séparés par des virgules ; vide : services sans clé requise ni protection ; `aucun` ; `defaut,EUROPEANA` ajoute Europeana) ; clés personnelles `GENEALOGISTE_CLE_EUROPEANA` (requise pour Europeana), `GENEALOGISTE_CLE_OPENALEX` (facultative), `GENEALOGISTE_CLE_NARA`, `GENEALOGISTE_CLE_APE` (services en lien seulement pour l’instant), jamais journalisées ni affichées ; `GENEALOGISTE_CROSSREF_MAILTO` vide par défaut (adresse envoyée à Crossref seulement si elle est renseignée) ; `GENEALOGISTE_CONTEXTE_STYLE_CITATION` (`iso690` par défaut, ou `evidence_explained`) ; état des services : `sources_catalogue(type="contexte")` et `diagnostic` ; [services de contexte](../docs/contexte-historique.md#services-de-contexte) |
| Service de source sur réseau interne | `GENEALOGISTE_HOTES_AUTORISES` ; dérogation ciblée décrite dans la [sécurité technique](../docs/securite.md) |

Le [modèle de configuration](../.env.example) et les guides thématiques donnent les réglages détaillés.
Ne recopier une configuration complète d’une autre installation qu’après avoir vérifié ses chemins,
son backend et ses comptes : chaque foyer et chaque arbre doivent garder leurs propres données.
