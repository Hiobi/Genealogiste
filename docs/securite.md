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
| Envoi des médias vers Gramps Web | Le fichier d'un média est cherché sous le répertoire des données puis, avec `GENEALOGISTE_MEDIA_DIR`, sous l'arborescence des pièces (vault) : un chemin relatif est essayé contre chacune de ces racines, un chemin absolu doit s'y trouver. Un chemin qui sort de toutes (absolu ailleurs, traversant `../`, lien symbolique sortant) n'est jamais lu ; il est listé comme « hors du répertoire de données, refusé ». |
| `ajouter_media`, `modifier_media`, `gramps_relocaliser_medias` (propositions) | Même confinement (données, répertoire des médias, arborescence des pièces) : un chemin local hors de ces racines ou introuvable fait refuser la proposition ; une URL distante est gardée sans être lue. |

## Confirmations (hooks)

Chaque outil a une **classe de permission** déclarée une seule fois dans
`mcp/src/genealogiste_mcp/outils.py`, d'après ce que fait réellement son code (effet maximal). La décision
du hook Claude **découle de la classe** (table `DECISIONS`) ; aucun outil n'est laissé à la règle par défaut
de Claude Code (#153).

| Classe | Définition | Décision | Exemples |
|---|---|---|---|
| Lecture | aucune écriture hors du cache et du journal internes | sans confirmation | `arbre_*` en lecture, `archives_service`, `liens_recherche`, `journal_ajouter`, `source_collee`, `pdf_markdown` |
| Collecte | réseau et/ou écriture **additive et réversible** dans un répertoire géré par le plugin (cache, journal, pièce nouvelle archivée avec sa note) ; jamais d'écrasement ni de suppression, jamais l'arbre ni Gramps Web | sans confirmation | sources externes, `ark_resoudre`, `archive_image`, `archives_naviguer`, `archives_planche`, `piece_archiver`, `enquete_ouvrir`, `enquete_noter`, `gramps_synchroniser` |
| Proposition | prépare une modification sans l'écrire (diff et jeton, file de propositions) | sans confirmation | `arbre_proposer`, `propositions_*`, `pieces_proposer`, `marqueurs_migrer_proposer`, `gramps_bascule_proposer`, `gramps_recalculer_notes`, `gramps_structurer_lieux` |
| Écriture | arbre, Gramps Web, fichiers de l'utilisateur (notes, pièces existantes, exports), suppression, envoi de ses fichiers à un tiers, identifiants | confirmation demandée | `arbre_appliquer`, `pieces_appliquer`, `marqueurs_migrer_appliquer`, `rapport_enregistrer`, `media_enregistrer`, `arbre_exporter`, `notes_*`, `cache_purger`, `gramps_tirer`, `familysearch_exporter`, `matchid_appariement_csv` |

**Outils en deux temps** (table `CONDITIONS`) : classés d'après leur effet maximal, mais le hook lit l'entrée
de l'appel pour ne demander l'accord qu'au moment de l'écriture :

- `matchid_appariement_statut` : collecte pour consulter, écriture (confirmation) si `sortie` est renseignée ;
- `gramps_envoyer_medias` : collecte pour lister (`appliquer=false`), écriture (confirmation) avec `appliquer=true`.
- `enquete_ouvrir` / `enquete_noter` : collecte, écriture (confirmation) quand l'appel fixe ou modifie un
  `budget` ou rouvre une enquête (`statut: "ouverte"`) : une boucle autonome ne relève pas seule la limite
  qui l'arrête (#157).

Cas tranchés d'après le code :

- `piece_archiver` est une collecte : l'image est écrite sous un nom nouveau (suffixe « (n) » en cas de
  collision, jamais d'écrasement), la note compagnon n'est jamais réécrite, le registre des pièces est en ajout
  seul ; l'arbre n'est touché qu'à la proposition.
- `media_enregistrer` reste une écriture : `chemin` désigne n'importe quel fichier lisible, copié dans
  l'arborescence des pièces (souvent synchronisée) ; l'utilisateur fournit d'ailleurs lui-même ce fichier.
  En mode autonome du chercheur (#158), personne ne peut l'approuver : le repli anti-robot devient une tâche
  manuelle de l'enquête ([enquetes.md](enquetes.md#mode-autonome)).
- `notes_lire` est une écriture : une fiche absente est générée, ce qui peut renommer des fiches de personnes,
  retirer des fiches de patronymes et réécrire l'index.
- `cache_purger` est une écriture : suppression, et `coupe_circuit` lève la pause anti-robot qui borne la collecte.
- `arbre_exporter` est une écriture : `chemin` libre, un fichier existant est remplacé.
- `gramps_recalculer_notes` et `gramps_structurer_lieux` ne font que préparer un diff et un jeton (proposition) ;
  l'écriture passe par `arbre_appliquer`.
- `gramps_synchroniser` est une collecte : relecture de Gramps Web, sans écriture vers lui ; avec le miroir Git,
  les modifications externes constatées sont commitées (ajout à l'historique), comme lors de toute lecture
  rafraîchie de l'arbre en mode gramps.

La collecte est bornée par les **limites de débit par hôte**, le **coupe-circuit** anti-robot, le
**plafond journalier par hôte d'archives** (`GENEALOGISTE_PLAFOND_JOUR_ARCHIVES`, toujours actif) et, pour
un appel lié à une enquête, son **budget** (requêtes par hôte, images, durée d'activité, coût estimé ;
refus avant l'envoi) — sections ci-dessous et [enquetes.md](enquetes.md#budget-et-arrêt-propre) (#157).

`hooks/hooks.json` est **généré** depuis ce catalogue (`make hooks`, `scripts/generer_hooks.py`) : un motif
par classe, puis un motif par outil en deux temps. Les motifs `mcp__.*genealogiste.*__…` couvrent le plugin
stdio et le serveur HTTP Docker. `tests/test_outils.py` refuse un outil enregistré mais non déclaré ou sans
classe, un `hooks.json` différent du rendu du catalogue, et exécute réellement la commande de chaque hook ; il
vérifie aussi que `/genealogiste:acte` se déroule sans demande d'accord jusqu'à `arbre_proposer` (seuls
`arbre_appliquer` et le repli manuel `media_enregistrer` en demandent). `tests/test_chercheur_autonome.py`
vérifie que les outils cités par le mode autonome du chercheur sont tous autorisés sans confirmation et rejoue
ce parcours jusqu'à `propositions_deposer` à travers les hooks réels. Ajouter un outil impose donc de le classer
puis de lancer `make hooks`.

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

## Débit : jamais de requêtes en rafale

`http.py` (#140). Chaque hôte a un intervalle minimal entre deux requêtes, y compris un service d'archives
absent de toute liste : un feuilletage vue après vue (`archives_naviguer` puis `archive_image`) reste espacé.
Ordre de priorité, du plus fort au plus faible :

1. `GENEALOGISTE_DEBITS=hote=secondes,hote2=secondes` (configuration de l'utilisateur) ;
2. `intervalle_requetes` (secondes) d'un service du référentiel `archives_fr.json`, appliqué aux hôtes de
   son `site` et de sa `visionneuse` ;
3. valeurs codées pour les API (matchID, WikiTree, Gallica, Wikidata : 1 s ; API Géo : 0,1 s) ;
4. `GENEALOGISTE_DEBIT_DEFAUT` pour tout autre hôte (1,5 s par défaut ; 0 désactive).

Le créneau est réservé sous un verrou court puis l'attente se fait hors verrou : un hôte lent ne retarde
pas les requêtes vers les autres. Une valeur invalide arrête le démarrage avec un message nommant la variable.

## Plafond journalier par hôte d'archives et budget d'enquête

`budget.py`, `http.py`, `cache.py` (#157).

- **Plafond journalier** : au plus `GENEALOGISTE_PLAFOND_JOUR_ARCHIVES` requêtes **émises** par jour (date
  locale) vers chaque hôte d'un service d'archives du référentiel (`site` et `visionneuse`, sous-domaines
  compris ; pas les services de type « autre » : matchID, Gallica, RetroNews, FranceArchives). Défaut
  **1000**, 0 désactive. Indépendant de toute enquête, il s'applique aussi aux appels interactifs.
  Compteur persistant dans la table `compteurs_jour` du cache SQLite (survit aux redémarrages, partagé
  entre serveurs, transaction par requête ; jamais vidé par `cache_purger`). Une réponse servie par le cache
  ne compte pas ; chaque essai et chaque redirection compte. Au plafond, la requête n'est **pas envoyée** :
  enveloppe d'erreur tracée au journal, `reessayer_apres` = secondes jusqu'à minuit.
  **Pourquoi 1000** : une vue lue coûte 1 à 3 requêtes (manifeste ou `info.json`, image) et une fenêtre de
  navigation 1 à 2 ; 1000 requêtes permettent de feuilleter et lire plusieurs centaines de vues dans la
  journée, plus qu'une séance humaine attentive, alors que la visionneuse du service charge elle-même des
  dizaines de tuiles par vue. Le plafond ne gêne donc pas l'usage interactif ; il arrête une boucle
  autonome qui feuilletterait un fonds entier. Avec le débit (1,5 s par défaut), 1000 requêtes
  représentent au moins 25 minutes de requêtes continues.
- **Budget d'enquête** : avec `enquete=<id>`, `recherche_multi` (et ses sources), `archives_naviguer` et
  `archive_image` sont mesurés côté serveur ; une requête qui dépasserait le budget de l'hôte ou la durée est
  refusée **avant l'envoi** (voir [enquetes.md](enquetes.md#budget-et-arrêt-propre)).

## Reprises automatiques : jamais de doublon

`http.py` (#50). Une requête est rejouée (backoff exponentiel, `Retry-After` respecté) :

| Requête | Rejouée après |
|---|---|
| GET, HEAD, OPTIONS, ou POST de pure lecture déclaré `idempotent=True` (WikiTree) | erreur réseau, 429, 502, 503, 504 |
| Autre POST (ex. dépôt d'un lot matchID) | seulement si elle n'est certainement pas partie : connexion impossible, 429 |

Dans les autres cas (délai de réponse dépassé, 502/503/504), l'outil renvoie une erreur
« **résultat indéterminé** » : la requête a pu être traitée ; vérifier côté service avant de recommencer.

**Plafond de durée** (#141) : un appel ne bloque jamais au-delà de `GENEALOGISTE_HTTP_DUREE_MAX` (60 s par
défaut), attentes et essais compris ; le délai de chaque essai est borné par le temps restant. `Retry-After`
est lu en secondes ou en date HTTP. Si l'attente demandée dépasse le temps restant, ou après le dernier essai
(aucune attente inutile), l'outil renvoie aussitôt une enveloppe d'erreur avec `reessayer_apres` (secondes),
tracée au journal : passer à une autre source et revenir plus tard, sans relancer en boucle.

| Variable | Défaut | Rôle |
|---|---|---|
| `GENEALOGISTE_HTTP_TIMEOUT` | 30 | délai d'un essai (s) |
| `GENEALOGISTE_HTTP_TENTATIVES` | 5 | essais au plus (requête rejouable) |
| `GENEALOGISTE_HTTP_DUREE_MAX` | 60 | plafond d'un appel d'outil (s) |

## Échecs mémorisés, coupe-circuit, caches bornés

`http.py`, `cache.py`, `menage.py` (#142).

- **Cache négatif** : un 403, 404 ou 429 d'une requête rejouable est mémorisé par URL
  (`GENEALOGISTE_CACHE_ECHEC`, 900 s ; pour un 429, la durée du `Retry-After`). L'appel suivant échoue sans
  requête ; l'enveloppe porte `echec_memorise: true`, `depuis_cache: true` et `reessayer_apres`.
  `cache_purger(<source>)` oublie aussi les échecs de cette source. Une erreur 5xx n'est pas mémorisée.
- **Coupe-circuit** : après un défi reconnu (Cloudflare, hCaptcha, reCAPTCHA, DataDome, page d'attente ou
  Anubis, ce dernier quel que soit son statut HTTP — #196), même servi en HTTP 200 ou 503, l'hôte entier est mis en pause. La détection précède le décodage, la mise
  en cache du contenu et les reprises HTTP ; un défi 503 ne déclenche donc aucune nouvelle tentative.
  La pause dure `GENEALOGISTE_COUPE_CIRCUIT` secondes (1800 par défaut) : les appels suivants échouent
  aussitôt avec la raison, l'heure de
  reprise et `coupe_circuit: true`, sans retenter le site. `cache_purger("coupe_circuit")` lève la pause.
  Aucun contournement n'est tenté.
- **Suite sans navigateur** : les enveloppes portent `statut: bloque_antirobot`, `service`, `protection`,
  `date_detection` (UTC), l'URL effective, une `tache_manuelle`, `bloque: "anti-robot"` et une `consigne`
  (vue fournie par l'utilisateur puis `media_enregistrer`). Cette tâche et la provenance du défi
  sont conservées au journal (`journal_lister(statut="bloque_antirobot")`), y compris après passage dans
  un adaptateur ou réutilisation du coupe-circuit. L'agent poursuit les autres pistes, puis reprend avec
  `source_collee` ou `piece_archiver` sur un fichier local fourni depuis un accès autorisé. Il n'a pas
  besoin d'un navigateur sur le serveur pour consigner ce travail restant. Il ne s'agit pas encore de
  l'état d'enquête persistant prévu par #155.
- **Proxy sortant** : aucun nouveau mécanisme de proxy résidentiel, rotation d'adresse ou reprise via
  une autre identité n'est ajouté. Les variables proxy standard du transport restent des paramètres de
  déploiement réseau ; elles ne doivent pas servir à contourner un refus. Une éventuelle sortie vers
  la connexion de l'utilisateur reste un chantier distinct, à examiner avec les conditions du service.
- **Taille** : entrées expirées purgées au démarrage et à chaque `cache_purger` ; cache SQLite plafonné à
  `GENEALOGISTE_CACHE_MAX_MO` (500) et `cache-images` à `GENEALOGISTE_CACHE_IMAGES_MAX_MO` (2000), les plus
  anciennes d'abord (0 = aucun plafond). Les pièces archivées (répertoire des médias) ne sont jamais touchées.

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
- **Diff concis** (#124) : le diff est découpé par enregistrement de niveau 0, sans contexte débordant sur
  l'enregistrement voisin. Sont détaillés les enregistrements visés par les opérations (identifiants, `$x`
  résolus, objets créés), ceux qui contiennent un événement visé (UID) et ceux dont une ligne modifiée cite une
  cible. Les autres restent signalés : notes hors cible comptées et nommées sans contenu, autres
  enregistrements sur une ligne `+a/-b`. Chaque ligne est plafonnée à 300 caractères (« … (+N car.) »), le
  tout à 400 lignes. Le contenu écrit reste exactement celui de la proposition (jeton, empreinte inchangés).
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
