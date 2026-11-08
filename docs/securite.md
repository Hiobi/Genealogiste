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
| Sans confirmation | recherches, consultations, propositions (`arbre_proposer`, `gramps_bascule_proposer`…), ainsi que `gramps_recalculer_notes` et `gramps_synchroniser` (écritures auxiliaires déclarées au catalogue) |
| Confirmation demandée | écritures (`arbre_appliquer`, `rapport_enregistrer`, `gramps_bascule_appliquer`, `gramps_tirer`), identifiants (`familysearch_exporter`, `matchid_appariement_csv`) |
| Selon les paramètres | `matchid_appariement_statut` : sans confirmation pour consulter, confirmation si `sortie` est renseignée (écriture d'un fichier) |
| Règle par défaut de Claude Code | tout outil absent des listes (ex. `media_enregistrer`) |

Le test `tests/test_chemins.py::test_hook_statut_matchid` exécute réellement la commande du hook.

Ces décisions sont déclarées une seule fois, outil par outil, dans `mcp/src/genealogiste_mcp/outils.py` (effet :
lecture, réseau, journal, proposition, écriture, identifiants ; décision du hook). `tests/test_outils.py` refuse
un outil enregistré mais non déclaré, et tout écart entre ce catalogue et `hooks/hooks.json`. Ajouter un outil
impose donc de le classer.

## Personnes vivantes : rien vers l'extérieur

**Présomption de vie** (`privacy.is_living`) : une personne est présumée vivante tant qu'une naissance il y a
moins de 100 ans reste possible. La décision porte sur la **borne haute** de l'intervalle de naissance, jamais
sur son milieu : `BEF 1970`, `AFT 1900` ou `BET 1900 AND 1930` laissent une naissance récente possible. Sans
naissance datée, la borne vient du mariage ou d'un enfant (15 ans avant), d'un autre fait daté, ou d'un parent
(50 ans après lui). Un décès, une inhumation ou une crémation **réfutés** (statut manuel) sont ignorés, et la
contradiction est signalée (`contradictions`). Le marquage `_VIVANT Y/N` prime.

**Sorties réseau** (`privacy.external_guard`) : politique unique, appliquée dans le code par tout outil réseau
qui reçoit un nom, un texte libre ou un identifiant de personne (matchID, WikiTree, Gallica, Wikidata dont
SPARQL, recherche multi-sources). Refus sans aucun appel réseau si :

- l'identifiant `personne` est **inconnu** de l'arbre ou désigne une personne présumée vivante ;
- les noms ou le texte désignent un vivant de l'arbre (nom **et** prénom présents), sauf si `ne_vers` est
  incompatible avec sa naissance (homonyme ancien) ou si la requête porte sur la personne décédée désignée
  par `personne`.

Un nom seul (`MARTIN`) n'est pas refusé. L'appariement par lot matchID contrôle **chaque ligne** du CSV : les
lignes désignant un vivant sont retirées du contenu envoyé (`lignes_exclues`, numéros du fichier d'origine) ;
rien n'est envoyé si aucune ligne ne reste.

**Exports** (`privacy.publication`, `arbre_exporter` avec `masquer_vivants`, par défaut) : projection distincte
de l'arbre de travail.

- Personnes présumées vivantes **ou marquées privées** (`RESN PRIVACY`, Gramps `private`) : réduites à
  « Vivant », sans patronyme, fait, note, média ni association.
- Sources, médias et notes partagées liés à au moins une de ces personnes, ou marqués privés : retirés avec
  **toutes** leurs références, y compris chez les défunts. Liés seulement à des défunts : conservés.
- Événements et citations privés, associations désignant une personne masquée (lien ou nom écrit) : retirés.
  Enregistrements non interprétés : exclus (contenu indécidable).
- Passe sur tous les textes : « Prénom Nom », « NOM Prénom », « Prénom /Nom/ » d'une personne masquée remplacés
  par « Vivant » (sans tenir compte des accents ni de la casse).
- Garde-fou : si une de ces chaînes subsiste dans le fichier produit, l'export est refusé et rien n'est écrit.

`tests/test_publication.py` exporte un arbre piégé dans les quatre formats et vérifie qu'aucune chaîne
identifiante ne subsiste.

`tests/test_outils.py` vérifie que tout outil réseau recevant un paramètre de personne figure dans la liste des
outils gardés (exemptions justifiées : communes de l'API Géo, serveur Gramps Web de l'utilisateur), et
`tests/test_vivants.py` qu'aucun de ces outils ne fait d'appel réseau pour un vivant.

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
| `docker-compose.yml` | le conteneur écoute sur `0.0.0.0` mais le port n'est publié que sur `127.0.0.1` : `MCP_TOKEN` exigé par défaut, y compris sur le réseau interne Docker |
| `docker-compose.portainer.yml` | `MCP_BIND` configurable : `MCP_TOKEN` exigé (`MCP_SANS_AUTH=0`) |

Client Claude Code avec jeton :

```bash
claude mcp add --transport http genealogiste http://127.0.0.1:8765/mcp --header "Authorization: Bearer $MCP_TOKEN"
```

**Mise à jour d'une stack Portainer existante** : sans `MCP_TOKEN`, le conteneur s'arrête au démarrage avec
le message « Refus de démarrer… ». Définir `MCP_TOKEN` (recommandé) ou, si `MCP_BIND=127.0.0.1` ou derrière
un proxy authentifiant, `MCP_SANS_AUTH=1`.

## Arbre et dépôt Git : écritures sûres

- **Verrou** : `arbre_appliquer` s'exécute sous un verrou exclusif (`<données>/.genealogiste.lock`, `flock`),
  entre processus et entre fils. Vérification de l'empreinte, écriture, commit et consommation du jeton forment
  un tout : deux applications concurrentes ne peuvent pas réussir sur la même base.
- **Instantané unique** : le diff et l'empreinte d'une proposition sont calculés sur le même texte lu.
- **Écriture atomique** : fichier temporaire du même répertoire, `fsync`, puis `os.replace`. Jamais d'arbre
  tronqué.
- **Reprise** : si le commit échoue, l'arbre précédent est restauré et le jeton reste valable ; le résultat
  distingue `ecrit` et `commite`. Une annulation (`git revert`) en échec est abandonnée (`revert --abort`).
- **Indexation explicite** : jamais de `git add -A`. Un commit d'arbre ne contient que `arbre.ged` ; le journal
  est versionné dans un commit à part (une annulation n'efface pas d'entrées du journal), un rapport dans le
  sien. `.gitignore` est complété à chaque démarrage, même s'il existait (`.env`, `.env.*`, `*.token`, `*.key`,
  `*.pem`, `.propositions/`, `exports/`, `*.sqlite`, verrou, temporaires).
- **Aperçu d'annulation** : `arbre_annuler_modification` montre le diff complet du commit et la liste
  `fichiers_annules` ; `attention` signale tout fichier autre que l'arbre.
- **Journaux JSONL** (`journal.jsonl`, `gramps-transactions.jsonl`) : ajout avec `flush` + `fsync` ; une ligne
  tronquée par un arrêt est ignorée et signalée (`journal_lister` : `avertissement` en tête), les autres entrées
  restent lisibles.

Tests : `tests/test_ecritures.py`.

## Limites connues

- **DNS rebinding** : l'adresse est vérifiée à la résolution, puis httpx résout de nouveau à la connexion.
  Un DNS malveillant à durée de vie nulle pourrait répondre différemment entre les deux. Le blocage complet
  demanderait d'épingler l'adresse vérifiée dans un transport sur mesure (SNI).
- Le jeton HTTP est un secret partagé unique (pas de comptes ni de droits par client). Pour une exposition
  au-delà d'un réseau de confiance, préférer un proxy authentifiant (TLS + SSO).

## Tests

`tests/test_chemins.py`, `tests/test_reseau.py`, `tests/test_outils.py`, `tests/test_vivants.py`,
`tests/test_publication.py`, `tests/test_ecritures.py`, `tests/test_integrite.py` et
`tests/test_garanties.py`. Ce dernier vérifie les propriétés globales : aucun outil réseau gardé n'interroge un
service pour un vivant, quel que soit le paramètre qui le désigne (outils et paramètres découverts dans le
catalogue), et aucun export, graphique, fiche ou note de recherche ne nomme une personne masquée. Aucune résolution DNS réelle pendant les tests : la
fixture `dns_fictif` (`conftest.py`, autouse) renvoie une adresse publique de documentation pour tout nom,
et des adresses privées pour quelques noms « internes ».

## Distribution publique (0.13.0)

Le dépôt du plugin refuse désormais de servir de répertoire de données. Les fichiers privés sont
ignorés et leur suivi forcé est contrôlé en CI. Gitleaks scanne l’historique accessible, pip-audit
contrôle les dépendances et GitHub protège les pushs contenant des secrets reconnus.

Les redirections HTTP vers une autre origine ne transmettent plus Authorization, Cookie,
Proxy-Authorization ni X-Api-Key. Les identifiants de l’ancien exporteur FamilySearch ne sont plus utilisés
et son exécution est désactivée : dépendances imposées vulnérables, dont DiskCache sans correctif connu
lors de l’audit. L’import GEDCOM reste disponible. Voir [production.md](production.md).

## Ressources privées communes aux notes et exports (0.14.1)

`privacy.private_resources` détermine sans mutation les sources, médias et notes exclus selon les
propriétaires masqués et les marques privées. Les notes réutilisent cette règle pour omettre aussi un
média au nom neutre, explicitement privé, partagé avec un vivant, ou rattaché par une citation ou un
événement privé, ainsi que les citations des associations qui désignent une personne masquée.
Le masquage des chaînes identifiantes reconnaît également un patronyme ou prénom
d’un caractère, en exigeant toujours leur couple : un patronyme isolé n’est pas masqué par ce mécanisme.
