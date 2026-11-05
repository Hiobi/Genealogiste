# Sécurité du serveur MCP

Garanties appliquées par le code, indépendamment des consignes données aux agents. Les hooks Claude Code
(`hooks/hooks.json`) ajoutent une confirmation humaine, mais ne s'exécutent pas pour un client MCP tiers :
les protections ci-dessous valent pour tout client.

## Fichiers : rien hors du répertoire de données

Module `chemins.py` (#41, #51). Les chemins sont résolus (liens symboliques compris) **avant** contrôle.

| Outil | Règle |
|---|---|
| `media_enregistrer(chemin, nom)` | `nom` = nom de fichier simple (ni `/`, ni `\`, ni `..`) ; copie confinée à `<données>/medias/` ; un fichier existant au contenu différent n'est pas écrasé (même contenu : sans effet). `chemin` (fichier source) est libre : l'outil n'est pas en lecture seule et demande confirmation. |
| `matchid_appariement_statut(job, sortie)` | `sortie` facultative : fichier `.csv` du répertoire de données (chemin relatif à celui-ci, ou absolu à l'intérieur), hors `.git`. `arbre.ged`, `journal.jsonl` et les autres fichiers internes sont donc inatteignables. Contrôle fait avant l'appel réseau. |
| Envoi des médias vers Gramps Web | Un média dont le chemin est absolu, traversant (`../`) ou un lien symbolique sortant n'est jamais lu ; il est listé comme « hors du répertoire de données, refusé ». |

## Confirmations (hooks)

| Décision | Outils |
|---|---|
| Sans confirmation | recherches, consultations, propositions (`arbre_proposer`, `gramps_bascule_proposer`…) |
| Confirmation demandée | écritures (`arbre_appliquer`, `rapport_enregistrer`, `gramps_bascule_appliquer`, `gramps_tirer`), identifiants (`familysearch_exporter`, `matchid_appariement_csv`) |
| Selon les paramètres | `matchid_appariement_statut` : sans confirmation pour consulter, confirmation si `sortie` est renseignée (écriture d'un fichier) |
| Règle par défaut de Claude Code | tout outil absent des listes (ex. `media_enregistrer`) |

Le test `tests/test_chemins.py::test_hook_statut_matchid` exécute réellement la commande du hook.

## Réseau : seules les adresses publiques

Module `reseau.py` (#42), appliqué par le client HTTP commun (`http.py`) à **toutes** les sources externes
(matchID, WikiTree, Gallica, Wikidata, API Géo, IIIF, ARK…) :

- schémas `http` et `https` uniquement ;
- après résolution DNS, refus des adresses loopback (`127.0.0.0/8`, `::1`), privées (`10/8`, `172.16/12`,
  `192.168/16`, réseaux Docker), link-local (`169.254/16`, dont les services de métadonnées cloud),
  partagées (`100.64/10`), multicast, réservées, non spécifiées (`0.0.0.0`), y compris sous forme IPv4
  mappée en IPv6 ;
- redirections suivies à la main et **revalidées à chaque saut** (5 au plus) : un manifeste IIIF public
  qui redirige vers `127.0.0.1` est refusé avant toute requête interne ;
- un nom non résolu n'est pas bloqué (la requête échouera d'elle-même sans rien atteindre).

Exception voulue (service local, miroir interne) :

```bash
GENEALOGISTE_HOTES_AUTORISES=iiif.local,localhost:8182   # hôte ou hôte:port, séparés par des virgules
```

Le client Gramps Web n'est pas soumis à cette politique : son URL (`GENEALOGISTE_GRAMPS_URL`) vient de la
configuration, pas d'une donnée externe.

## Reprises automatiques : jamais de doublon

`http.py` (#50). Une requête est rejouée (backoff exponentiel, `Retry-After` respecté) :

| Requête | Rejouée après |
|---|---|
| GET, HEAD, OPTIONS, ou POST de pure lecture déclaré `idempotent=True` (WikiTree) | erreur réseau, 429, 502, 503, 504 |
| Autre POST (ex. dépôt d'un lot matchID) | seulement si elle n'est certainement pas partie : connexion impossible, 429 |

Dans les autres cas (délai de réponse dépassé, 502/503/504), l'outil renvoie une erreur
« **résultat indéterminé** » : la requête a pu être traitée ; vérifier côté service avant de recommencer.

## Transport HTTP du serveur MCP : jeton

Module `auth.py` (#52). En `stdio` (plugin Claude Code), rien ne change. En HTTP (`--transport
streamable-http` ou `sse`) :

| Variable | Effet |
|---|---|
| `MCP_TOKEN` | jeton exigé sur chaque requête : `Authorization: Bearer <jeton>` (sinon 401). Générer : `openssl rand -hex 32` |
| `MCP_SANS_AUTH=1` | dérogation explicite : démarrage sans jeton sur une adresse non locale |

Sans jeton ni dérogation, le serveur **refuse de démarrer** s'il écoute ailleurs que sur `127.0.0.1`,
`::1` ou `localhost`.

| Déploiement | Réglage par défaut |
|---|---|
| `make run-http`, `genealogiste-mcp --transport streamable-http` | écoute sur 127.0.0.1, jeton facultatif |
| `docker-compose.yml` | le conteneur écoute sur `0.0.0.0` mais le port n'est publié que sur `127.0.0.1` : `MCP_SANS_AUTH=1` posé ; définir `MCP_TOKEN` dans `.env` pour exiger le jeton |
| `docker-compose.portainer.yml` | `MCP_BIND` configurable : `MCP_TOKEN` exigé (`MCP_SANS_AUTH=0`) |

Client Claude Code avec jeton :

```bash
claude mcp add --transport http genealogiste http://127.0.0.1:8765/mcp --header "Authorization: Bearer $MCP_TOKEN"
```

**Mise à jour d'une stack Portainer existante** : sans `MCP_TOKEN`, le conteneur s'arrête au démarrage avec
le message « Refus de démarrer… ». Définir `MCP_TOKEN` (recommandé) ou, si `MCP_BIND=127.0.0.1` ou derrière
un proxy authentifiant, `MCP_SANS_AUTH=1`.

## Limites connues

- **DNS rebinding** : l'adresse est vérifiée à la résolution, puis httpx résout de nouveau à la connexion.
  Un DNS malveillant à durée de vie nulle pourrait répondre différemment entre les deux. Le blocage complet
  demanderait d'épingler l'adresse vérifiée dans un transport sur mesure (SNI).
- Le jeton HTTP est un secret partagé unique (pas de comptes ni de droits par client). Pour une exposition
  au-delà d'un réseau de confiance, préférer un proxy authentifiant (TLS + SSO).

## Tests

`tests/test_chemins.py` et `tests/test_reseau.py`. Aucune résolution DNS réelle pendant les tests : la
fixture `dns_fictif` (`conftest.py`, autouse) renvoie une adresse publique de documentation pour tout nom,
et des adresses privées pour quelques noms « internes ».
