# Sosa — plugin Claude Code « genealogiste »

Un généalogiste professionnel français dans Claude Code : recherche multi-sources (INSEE/matchID,
WikiTree, Gallica, Wikidata, API Géo + COG historique, FamilySearch, liens Geneanet / AD / Mémoire des
hommes), méthode du *Genealogical Proof Standard*, fact-check à sources indépendantes, détection
d'homonymes, et arbre **GEDCOM 7 versionné en Git** — ou directement **Gramps Web** — où rien n'est écrit
sans votre validation.

```
.claude-plugin/   plugin.json, marketplace.json
.mcp.json         serveur MCP lancé par uv (stdio)
commands/         17 commandes slash
skills/           methodologie-gps, sources-francaises, paleographie, droit-communicabilite
agents/           chercheur, verificateur (indépendant), redacteur
hooks/            lecture des sources sans approbation ; écritures soumises à confirmation
mcp/              serveur MCP Python (FastMCP, uv) + tests pytest
docs/             extensions GEDCOM, opérations d'édition, mode Gramps Web
data/             point de montage Docker (contenu ignoré par Git)
docker-compose.yml  MCP en HTTP + Gramps Web (profil optionnel)
```

## Installation

Prérequis : Claude Code, [uv](https://docs.astral.sh/uv/), git, Python ≥ 3.11 (uv l'installe au besoin).

```bash
# depuis Claude Code
/plugin marketplace add hiobi/sosa
/plugin install genealogiste@sosa
```

ou en local : `git clone … && claude --plugin-dir ./Sosa`.

Au premier lancement, `uv` installe les dépendances du serveur MCP (`mcp/`) et le répertoire de données
est créé et initialisé en dépôt Git.

### Configuration

Copier `.env.example` dans le **répertoire de données** (`~/.local/share/genealogiste/.env` par défaut)
et renseigner au minimum :

| Variable | Rôle |
|---|---|
| `GENEALOGISTE_DATA_DIR` | dépôt Git de l'arbre, du journal et des médias (défaut `~/.local/share/genealogiste`) |
| `GENEALOGISTE_WIKITREE_APPID` | identifiant d'application WikiTree (obligatoire pour WikiTree, libre) |
| `GENEALOGISTE_MATCHID_TOKEN` | jeton matchID pour l'appariement CSV par lot (facultatif) |
| `GENEALOGISTE_FS_USER` / `_PASSWORD` | FamilySearch via getmyancestors (facultatif, `uv sync --extra familysearch`) |
| `GENEALOGISTE_BACKEND` | `fichier` (défaut, GEDCOM 7 + Git) ou `gramps` (Gramps Web = arbre de référence) |
| `GENEALOGISTE_GRAMPS_URL` / `_USER` / `_PASSWORD` | Gramps Web : compte local dédié, rôle Editor |
| `GENEALOGISTE_GIT_MIRROR` / `_GIT_REMOTE` | miroir Git de l'arbre Gramps ; dépôt distant **privé** optionnel |
| `GENEALOGISTE_STRICT` | `1` : règle stricte 3/2/1 sources sans pondération |
| `GENEALOGISTE_EXIGER_SOURCE` | `1` (défaut) : pas de fait ni de filiation sans citation, sauf `non_source` + motif |
| `GENEALOGISTE_OFFLINE` | `1` : cache uniquement |

Les variables peuvent aussi être exportées dans l'environnement de Claude Code. `make check` affiche la
configuration effective.

### Docker compose

```bash
cp .env.example .env            # puis compléter
docker compose up -d            # MCP HTTP sur 127.0.0.1:8765/mcp, données dans ./data
docker compose --profile gramps up -d   # + Gramps Web sur 127.0.0.1:5055 (redis + celery)
claude mcp add --transport http genealogiste http://127.0.0.1:8765/mcp
```

En mode Docker, désactiver le serveur stdio du plugin (`/mcp` → genealogiste → disable) pour n'en garder
qu'un. Les hooks d'approbation s'appliquent aux deux (motif `mcp__.*genealogiste.*__…`).
Gramps Web : épingler `GRAMPSWEB_VERSION` pour la production ; créer le compte administrateur au premier
accès, puis renseigner `GENEALOGISTE_GRAMPS_*`.

### Portainer

Stacks → Add stack → Repository : URL `https://github.com/hiobi/sosa`, compose path
`docker-compose.portainer.yml`, variables d'après `portainer/stack.env.example`. La stack démarre le MCP et
Gramps Web ensemble (sans profils). Le MCP n'ayant pas d'authentification, il reste lié à `127.0.0.1` par
défaut. Pour travailler en direct sur Gramps Web : `GENEALOGISTE_BACKEND=gramps` (voir
[docs/gramps-web.md](docs/gramps-web.md), bascule depuis le mode fichier avec `gramps_bascule_proposer`).

## Commandes

Les commandes d'un plugin sont préfixées par son nom : `/genealogiste:cherche` (ou `/cherche` sans conflit).

| Commande | Rôle |
|---|---|
| `enquete <id\|nom> [personne\|famille\|etendu]` | **en une commande** : recherche sur l'individu et ses proches (agents en parallèle), recoupement croisé, vérification indépendante, plan priorisé et proposition d'ajouts unique |
| `cherche <nom> [prénom] [né vers] [lieu]` | recherche multi-sources, résultats classés par score explicite |
| `fiche <id\|nom>` | fiche complète, statut de preuve de chaque fait, prochaines sources |
| `verifie <id> [fait]` | fact-check par l'agent vérificateur, sans les conclusions du chercheur |
| `recoupe <id1> <id2>` | même personne ou homonymes ? analyse argumentée |
| `ascendance <id> [n]` / `descendance <id> [n]` | arbres Sosa / descendants (tableau + Mermaid, SVG) |
| `lacunes <id\|arbre>` | faits manquants ou faibles + plan priorisé (source, cote, archives) |
| `ajoute`, `modifie`, `fusionne` | édition avec diff et validation explicite |
| `import <gedcom\|familysearch>`, `export <format>` | GeneWeb, GEDCOM 5.5.1/7, Gramps XML, Mermaid, SVG, fiche Markdown |
| `transcris <image>` | paléographie, latin, transcription et extraction des données |
| `recit <id>` | biographie dont chaque phrase est sourcée |
| `preuve <id> [fait]` | rapport de preuve rédigé (question, pièces, analyse, contradictions, conclusion) |
| `journal` | historique des recherches (y compris négatives) et des commits |

## Méthode appliquée

- **Classification** de chaque citation : source originale / dérivée / composite ; information primaire /
  secondaire / indéterminée ; preuve directe / indirecte / négative (extensions GEDCOM documentées dans
  [docs/gedcom-extensions.md](docs/gedcom-extensions.md)).
- **Statut de preuve calculé** : les citations sont regroupées par source originale indépendante (acte +
  table décennale = une seule source) ; poids 2 pour un original primaire direct, 1 sinon, 0 pour un arbre
  en ligne. *Confirmé* ≥ 3 points et ≥ 2 sources indépendantes, *probable* 2, *hypothèse* 1 ;
  *contradictoire* détecté automatiquement ; *réfuté* par décision justifiée. Mode strict disponible.
- **Recoupement** : noms (variantes, phonétique française, latin des registres, particules, « dit »),
  dates ±2 ans, calendriers républicain et julien, âges recalculés, lieux normalisés et historiques (COG),
  contrôles biologiques.
- **Homonymes** : score critère par critère ; une contradiction franche l'emporte ; jamais de fusion
  automatique.
- **Journal** : chaque requête (source, paramètres, date, résultat, y compris négatif) est tracée dans
  `journal.jsonl`.

### Habitudes du métier appliquées

Pas de fait sans source (exception explicite et motivée) ; on ne compte que ce qu'on a vu (`consultation` :
original, image, transcription, index, non vu) ; citation normalisée « AD17, 2 E 299, …, acte n° 45,
vue 12/80 ; consulté le … [image numérisée ; source originale ; information primaire] » ; témoins,
parrains, déclarants relevés (`ASSO`) et exploités contre les homonymes (méthode FAN) ; transcription
intégrale des actes clés ; rapport de preuve pour les conclusions difficiles ; du connu vers l'inconnu.

## GeneWeb 7

`/genealogiste:export geneweb` produit un GEDCOM 5.5.1 pour `ged2gwb` : citations complètes en source,
statut de preuve et prochaines sources en notes, témoins et parrains en témoins/relations GeneWeb, versions
concurrentes documentées. Validé par import réel dans GeneWeb 7.0.0 et aller-retour `gwb2ged`.
Détails : [docs/geneweb.md](docs/geneweb.md).

## Arbre et validation

L'arbre de travail est `arbre.ged` (GEDCOM 7, sérialisation déterministe) dans un dépôt Git distinct du
plugin. Toute modification passe par `arbre_proposer` (diff, nouvelles alertes de cohérence, message de
commit) puis `arbre_appliquer(jeton)` : jeton à usage unique, valable 1 h, refusé si l'arbre a changé ;
un hook impose en plus la confirmation de l'utilisateur. Un commit par modification, message =
justification + sources. Opérations disponibles : [docs/operations.md](docs/operations.md).

## Données personnelles

Personne sans décès et née (estimation) il y a moins de 100 ans = présumée vivante : aucune donnée
envoyée à un service externe, masquage à l'export et refus de récit. Délais de communicabilité :
skill `droit-communicabilite` et outil `communicabilite`.

## Développement

```bash
make install   # uv sync
make test      # pytest : fixtures GEDCOM, réponses API mockées, faux Gramps Web, homonymes, contradictions
make test-gramps  # intégration sur un Gramps Web jetable (Docker, données fictives)
make lint      # ruff
make validate  # claude plugin validate .
```

## Limites connues

- Gallica est protégé par Cloudflare : depuis certaines IP (cloud, datacenter) les requêtes sont bloquées ;
  l'outil le signale et propose la consultation dans le navigateur.
- Geneanet, Filae, sites d'AD et Mémoire des hommes n'ont pas d'API ouverte : le plugin fournit l'URL ou
  la cote, l'utilisateur colle le résultat (`source_collee`), sans extraction automatisée (CGU).
- L'appariement CSV matchID peut exiger un compte.
- COG INSEE : historique des communes depuis 1943 ; avant, se reporter au dictionnaire Cassini (EHESS).
- Mode Gramps Web (v1) : pas d'envoi des médias, un seul arbre, pas de fusion native ni de lieux
  hiérarchiques en écriture (issues #8 à #11).
- Les cotes proposées suivent le cadre de classement réglementaire : toujours vérifier l'inventaire du service.
