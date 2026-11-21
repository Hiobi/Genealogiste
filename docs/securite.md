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
| Envoi des médias vers Gramps Web | Le fichier d'un média est cherché sous le répertoire des données puis, avec `GENEALOGISTE_MEDIA_DIR`, sous le répertoire des médias et l'arborescence des pièces (vault) : un chemin relatif est essayé contre chacune de ces racines, un chemin absolu doit s'y trouver. Un chemin qui sort de toutes (absolu ailleurs, traversant `../`, lien symbolique sortant) n'est jamais lu ; il est listé comme « hors du répertoire de données, refusé ». Un chemin relatif présent sous deux racines avec des contenus différents n'est ni lu ni envoyé (« Chemin ambigu », #193 ; règle dans `docs/operations.md`). |
| `ajouter_media`, `modifier_media`, `gramps_relocaliser_medias` (propositions) | Même confinement (données, répertoire des médias, arborescence des pièces) : un chemin local hors de ces racines ou introuvable fait refuser la proposition ; une URL distante est gardée sans être lue. |
| `arbre_importer_gedcom` sur un fichier Gramps (#269) | Format reconnu au contenu. **XML** : analyseur expat de la bibliothèque standard (aucune dépendance ajoutée) ; DTD interne, déclaration d'entité (générale, paramètre, non analysée), entité externe et notation refusées avant toute expansion (bombe d'entités, lecture de fichier ou requête réseau impossibles) ; le DOCTYPE externe de Gramps n'est jamais résolu ; XML décompressé borné à 512 Mio, décompression gzip arrêtée à la limite ; espace de noms étranger, préfixe, élément ou attribut inconnu : refus. **Paquet `.gpkg`** : membres inspectés avant toute écriture ; seuls des fichiers réguliers (lien symbolique ou physique, périphérique, FIFO : refus du paquet entier) ; noms relatifs sans `..`, composant caché (`.env`), antislash, NUL ni lecteur, uniques, un seul `data.gramps` ; 100 000 membres, 2 Gio par membre et 8 Gio au total au plus. Les médias sont copiés dans une zone d'attente **neuve** `<données>/imports/gramps/<nom>-<horodatage>/` (création exclusive, jamais d'écrasement, chemin final revérifié sous la zone), retirée si la lecture échoue ; jamais dans le vault ni ailleurs. |

## Confirmations (hooks)

Chaque outil a une **classe de permission** déclarée une seule fois dans
`mcp/src/genealogiste_mcp/outils.py`, d'après ce que fait réellement son code (effet maximal). La décision
du hook Claude **découle de la classe** (table `DECISIONS`) ; aucun outil n'est laissé à la règle par défaut
de Claude Code (#153).

| Classe | Définition | Décision | Exemples |
|---|---|---|---|
| Lecture | aucune écriture hors du cache et du journal internes | sans confirmation | `arbre_*` en lecture, `archives_service`, `sources_catalogue`, `liens_recherche`, `variantes_noms`, `journal_ajouter`, `source_collee`, `pdf_markdown` |
| Collecte | réseau et/ou écriture **additive et réversible** dans un répertoire géré par le plugin (cache, journal, pièce nouvelle archivée avec sa note) ; jamais d'écrasement ni de suppression, jamais l'arbre ni Gramps Web | sans confirmation | sources externes, `ark_resoudre`, `archive_image`, `archives_naviguer`, `archives_planche`, `piece_archiver`, `enquete_ouvrir`, `enquete_noter`, `archives_sonder`, `gramps_synchroniser`, `rapport_campagne_enregistrer` |
| Proposition | prépare une modification sans l'écrire (diff et jeton, file de propositions) | sans confirmation | `arbre_proposer`, `propositions_*`, `pieces_proposer`, `marqueurs_migrer_proposer`, `gramps_bascule_proposer`, `gramps_recalculer_notes`, `gramps_structurer_lieux`, `gramps_dater_lieux`, `gramps_normaliser_types` |
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
- `rapport_campagne_enregistrer` est une collecte (#159) : fichier **nouveau** daté dans
  `<données>/rapports/campagnes/` (suffixe `-2`, `-3`… en cas de collision, jamais d'écrasement), toujours dans
  le répertoire de données (`GENEALOGISTE_RAPPORTS_DIR` ignoré), sans commit, push ni réseau.
  `rapport_enregistrer` reste une écriture : il remplace un rapport existant, peut viser un dossier hors des
  données (vault synchronisé) et commite puis pousse vers `GENEALOGISTE_GIT_REMOTE`.
- `media_enregistrer` reste une écriture : `chemin` désigne n'importe quel fichier lisible, copié dans
  l'arborescence des pièces (souvent synchronisée) ; l'utilisateur fournit d'ailleurs lui-même ce fichier.
  En mode autonome du chercheur (#158), personne ne peut l'approuver : le repli anti-robot devient une tâche
  manuelle de l'enquête ([enquetes.md](enquetes.md#mode-autonome)).
- `notes_lire` est une écriture : une fiche absente est générée, ce qui peut renommer des fiches de personnes,
  retirer des fiches de patronymes et réécrire l'index.
- `cache_purger` est une écriture : suppression, et `coupe_circuit` lève la pause ou l'exclusion anti-robot qui borne la collecte.
- `arbre_exporter` est une écriture : `chemin` libre, un fichier existant est remplacé. Le paquet `gpkg` lit
  les fichiers des médias par la règle commune (`chemins.localiser` : racines autorisées, ni traversée ni lien
  sortant, ambiguïté refusée), refuse en plus tout composant caché (`.env`, `.git`), n'écrit dans l'archive que
  des noms relatifs sûrs et liste les fichiers non empaquetés ([gramps.md](gramps.md#paquet-gpkg)).
- `arbre_importer_gedcom` reste une proposition, y compris pour un fichier Gramps : l'arbre n'est touché qu'à
  `arbre_appliquer`. Pour un paquet `.gpkg`, la seule écriture est la copie additive des médias dans une zone
  d'attente neuve du répertoire de données (rien n'est écrasé, déplacé ni rangé dans le vault : le rangement
  passe par `pieces_proposer` puis `pieces_appliquer`, avec accord). La lecture est locale : aucune donnée
  ne sort, personnes vivantes comprises.
- `gramps_recalculer_notes`, `gramps_structurer_lieux` et `gramps_normaliser_types` ne font que préparer un diff et
  un jeton (proposition) ; l'écriture passe par `arbre_appliquer`.
- `gramps_dater_lieux` (#277) reste une proposition alors qu'il lit le réseau : il télécharge les deux fichiers
  publics du COG de l'INSEE (cache de 180 jours, politique réseau et limites de débit de `www.insee.fr`), sans
  rien envoyer de la base ni d'aucune personne (pas de garde « vivants » : ni nom ni identifiant de personne), et
  trace la requête au journal (source `cog`), y compris négative ou en erreur. Comme toute collecte, ce volet ne
  demande pas d'accord ; la transaction préparée n'est écrite que par `arbre_appliquer`. Aucune classe
  intermédiaire ni condition (`CONDITIONS`) : l'outil n'a pas de branche d'écriture.
- En mode gramps, les propositions (`arbre_proposer`, `gramps_recalculer_notes`, `gramps_structurer_lieux`,
  `gramps_dater_lieux`, `gramps_normaliser_types`, `marqueurs_migrer_proposer`, annulation, bascule) et `arbre_appliquer` refusent tôt un compte sans droit
  d'écriture (rôle sous Editor) ; le diagnostic signale aussi un compte Owner ou Admin (privilège excessif).
  Le contrôle ne lit que les droits du jeton et le rôle du compte, jamais `/api/config/` (réservé aux Admin).
- `gramps_synchroniser` est une collecte : relecture de Gramps Web, sans écriture vers lui ; avec le miroir Git,
  les modifications externes constatées sont commitées (ajout à l'historique), comme lors de toute lecture
  rafraîchie de l'arbre en mode gramps.

La collecte est bornée par les **limites de débit par hôte**, le **coupe-circuit** anti-robot, le
**plafond journalier par hôte** ([politique d'accès par service](#politique-daccès-par-service) :
`GENEALOGISTE_PLAFOND_JOUR_ARCHIVES` pour les archives, `GENEALOGISTE_PLAFOND_JOUR_DEFAUT` pour les API et
tout autre hôte, toujours actif) et, pour
un appel lié à une enquête, son **budget** (requêtes par hôte, images ; refus avant l'envoi) — sections
ci-dessous et [enquetes.md](enquetes.md#budget-et-arrêt-propre) (#157, #211). Trois préoccupations
distinctes : le **ménagement des sites** relève de la couche réseau (intervalle par hôte, ralentissement
après 429/503, plafond journalier, coupe-circuit), toujours active ; le **budget d'enquête** arrête une boucle
(images, requêtes par site) ; le **coût réel** se plafonne côté client par `--max-budget-usd`, à fixer pour
toute campagne ([campagne.md](campagne.md)).

`hooks/hooks.json` est **généré** depuis ce catalogue (`make hooks`, `scripts/generer_hooks.py`) : un motif
par classe, puis un motif par outil en deux temps. Les motifs `mcp__.*genealogiste.*__…` couvrent le plugin
stdio et le serveur HTTP Docker. `tests/test_outils.py` refuse un outil enregistré mais non déclaré ou sans
classe, un `hooks.json` différent du rendu du catalogue, et exécute réellement la commande de chaque hook ; il
vérifie aussi que `/genealogiste:acte` se déroule sans demande d'accord jusqu'à `arbre_proposer` (seuls
`arbre_appliquer` et le repli manuel `media_enregistrer` en demandent). `tests/test_chercheur_autonome.py`
vérifie que les outils cités par le mode autonome du chercheur sont tous autorisés sans confirmation et rejoue
ce parcours jusqu'à `propositions_deposer` à travers les hooks réels. Ajouter un outil impose donc de le classer
puis de lancer `make hooks`.

## Modes d'exécution et garde-fou d'écriture

Les hooks ne sont qu'une **demande** faite au client Claude Code : selon le mode de permission, l'accord
humain exigé pour une écriture peut ne plus être demandé du tout. Le **garde-fou côté serveur** ne dépend
pas du client (#159) :

- `GENEALOGISTE_ECRITURE=autorisee` (défaut) | `interdite` ; toute autre valeur est une erreur de
  configuration (`cause: configuration`, `variable: GENEALOGISTE_ECRITURE`).
- Avec `interdite`, le serveur refuse **avant tout effet** chaque appel de classe *écriture* du catalogue
  (`outils.OUTILS`) : `arbre_appliquer` (donc aussi les écritures Gramps Web en mode gramps),
  `pieces_appliquer`, `marqueurs_migrer_appliquer`, `gramps_tirer`, `gramps_bascule_appliquer`,
  `rapport_enregistrer`, `media_enregistrer`,
  `arbre_exporter`, `notes_*`, `cache_purger`, `matchid_appariement_csv`, `familysearch_exporter`… et, pour
  les outils en deux temps (`CONDITIONS`), **seulement la branche écriture** : `gramps_envoyer_medias` avec
  `appliquer=true`, `matchid_appariement_statut` avec `sortie`, `enquete_ouvrir` / `enquete_noter` qui
  fixent un `budget` ou rouvrent une enquête. Le motif est celui du hook, appliqué aux arguments de l'appel.
  Réponse : `{"erreur": …, "refus": "ecriture_interdite", "outil": …, "remede": …}`.
- La liste n'est écrite nulle part en dur : l'enveloppe est posée par `ServeurMCP.tool` sur **chaque** outil
  enregistré (aussi quand la fonction est appelée directement, hors protocole MCP) et consulte la classe du
  catalogue ; un outil d'écriture ajouté plus tard est couvert dès son classement.
- Lecture, collecte et proposition restent permises : sources, archives, `piece_archiver`, `enquete_*` sans
  budget, `propositions_deposer`, `arbre_proposer`, `journal_ajouter`, `rapport_campagne_enregistrer`.
- Tests : `tests/test_ecriture_interdite.py` appelle chaque outil d'écriture directement (sans hooks) et
  vérifie le refus et l'absence de toute modification de fichier ; il vérifie aussi que les autres classes
  passent, que le serveur et le hook tranchent la même branche des outils en deux temps, et que l'enveloppe ne
  change aucun schéma exposé.

**Tableau des modes.** « Vérifié » : établi par les tests du dépôt (sortie réelle des hooks, refus du
serveur) ou cité de la documentation officielle de Claude Code
([hooks](https://code.claude.com/docs/en/hooks), [permissions](https://code.claude.com/docs/en/permissions),
[mode non interactif](https://code.claude.com/docs/en/headless), consultées le 2026-11-17). « Supposé » :
déduit de cette documentation, **non vérifié en réel** (aucune session `claude` lancée pour ce tableau).

| Mode | Lecture, collecte, proposition | Écriture, sans garde-fou (`autorisee`) | Écriture avec `GENEALOGISTE_ECRITURE=interdite` |
|---|---|---|---|
| Interactif (mode Manual par défaut) | permises sans demande : le hook répond `allow` (vérifié : tests ; doc : le hook passe avant l'invite) | **demandée** : le hook répond `ask`, l'utilisateur voit la raison et accepte ou refuse (vérifié : sortie du hook ; doc) | **refusée** par le serveur, même si l'utilisateur accepte (vérifié : tests) |
| `claude -p` (Manual, sans hôte de permission) | permises (hook `allow`) ; les commandes de plugin `/genealogiste:…` sont développées en `-p` (doc) | **refusée** par le client : en `-p`, un appel qui demande un accord est refusé si rien ne l'approuve (doc) ; qu'un `ask` de hook soit traité ainsi est **supposé** | refusée par le serveur (vérifié) |
| `claude -p --permission-mode dontAsk` + profil minimal (`make profil-campagne`) | permises par les règles `allow` du profil (doc : `dontAsk` laisse passer ce qui est pré-approuvé) | **refusée** : règles `deny` du profil, évaluées quels que soient les hooks (doc) ; outils en deux temps : branche écriture `ask` → refusée par `dontAsk` (**supposé**) | refusée par le serveur (vérifié) |
| Sous-agent (`chercheur`, `verificateur`… lancés par une commande) | mêmes décisions : les hooks de plugin s'exécutent aussi dans les sous-agents (doc) | comme la session parente : demandée en interactif, refusée en `-p` (**supposé** : héritage du mode de la session) | refusée par le serveur (vérifié) |
| Sans confirmation (`--dangerously-skip-permissions`, `bypassPermissions`) | permises | **probablement exécutée sans accord** : le mode saute les invites (doc) ; qu'un `ask` de hook soit lui aussi sauté est **supposé** ; une règle `deny` des réglages devrait encore bloquer (**supposé**) | **refusée** par le serveur : seule garantie dans ce mode (vérifié) |
| `--bare` (scripts) | les hooks d'un plugin ne s'exécutent pas en mode bare (doc) : il faut des règles `allow` | aucun hook : dépend des seules règles et du mode (en `-p`, refus de ce qui demanderait un accord, **supposé**) | refusée par le serveur (vérifié) |
| Autre client MCP (serveur HTTP Docker, Codex) | selon la politique du client | **aucun hook Claude** : selon le client (Codex : approbation native de chaque outil, [adaptation-codex.md](adaptation-codex.md)) | refusée par le serveur (vérifié) |

Le mode plan ignore un `allow` de hook pour tout appel qui n'est pas en lecture seule (doc) ; une extension
(mod) installée peut approuver un appel bloqué par un hook dans certaines configurations (doc). Conséquence :
**toute session sans surveillance** (`claude -p`, cron, `bypassPermissions`, sous-agent d'une telle session)
doit tourner avec `GENEALOGISTE_ECRITURE=interdite` dans l'environnement du **serveur** ; les conclusions vont
dans la file (`propositions_deposer`) et sont appliquées plus tard, après accord, par `/genealogiste:valide`
dans une session surveillée lancée avec `autorisee`. Un budget d'enquête ne peut pas être fixé ni relevé
dans une telle session (branche écriture d'`enquete_ouvrir` / `enquete_noter`) : il vient des défauts
`GENEALOGISTE_BUDGET_*` fixés par l'humain dans l'environnement de la tâche. Ce budget compte tout outil
réseau de collecte appelé avec `enquete=<id>` (`outils.BUDGET_ENQUETE`) ; dans tous les modes, la couche
réseau ménage les sites (débit par hôte, coupe-circuit anti-robot, plafond journalier des archives : côté
serveur, indépendants du client) et le coût réel se plafonne par `--max-budget-usd`. Exemple planifié :
[campagne.md](campagne.md).

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
- Étiquettes (#262) : même politique que les notes. Retirées avec les personnes et familles masquées et avec
  tout objet retiré (note partagée, source, média, événement, citation) ; conservées sur les objets publiés,
  où la passe ci-dessous remplace aussi les noms des masqués (une étiquette « Famille Alice SECRET » devient
  « Famille Vivant »). Une étiquette interne (`ToDo`, `Blog`) d'un défunt publié reste donc visible :
  ne pas mettre d'information confidentielle dans un nom d'étiquette.
- Passe sur tous les textes : « Prénom Nom », « NOM Prénom », « Prénom /Nom/ » d'une personne masquée remplacés
  par « Vivant » (sans tenir compte des accents ni de la casse).
- Garde-fou : si une de ces chaînes subsiste dans le fichier produit, l'export est refusé et rien n'est écrit.
  Gramps XML et `.gpkg` sont aussi relus à plat (balises retirées), car prénom et patronyme y sont dans des
  éléments distincts ; les médias d'une personne masquée ne sont pas empaquetés.

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
3. table des services de `politique_acces.py` (matchID, WikiTree, Gallica, Wikidata : 1 s ; API Géo : 0,1 s ;
   voir [politique d'accès par service](#politique-daccès-par-service)) ;
4. `GENEALOGISTE_DEBIT_DEFAUT` pour tout autre hôte (1,5 s par défaut ; 0 désactive).

Le créneau est réservé sous un verrou court puis l'attente se fait hors verrou : un hôte lent ne retarde
pas les requêtes vers les autres. Une valeur invalide arrête le démarrage avec un message nommant la variable.

### Débit partagé entre processus

`http.py`, `cache.py` (#211). Le créneau de chaque hôte est réservé dans le cache SQLite (table `creneaux`),
pas seulement en mémoire : une transaction `BEGIN IMMEDIATE` lit le dernier créneau de l'hôte, calcule
`max(maintenant, dernier + intervalle)` et l'enregistre ; le client attend ensuite son créneau hors de toute
transaction. L'horloge est l'heure murale (`time.time`), commune aux processus d'une même machine et aux
conteneurs d'un même hôte. Tous les serveurs qui partagent le fichier cache (`GENEALOGISTE_CACHE` : session
interactive et campagne `claude -p`, plusieurs conteneurs Docker sur le même volume) respectent donc
**ensemble** l'intervalle de chaque hôte, au lieu de le multiplier par le nombre de processus.

- Verrou SQLite tenu par un autre processus : attente bornée à 5 s, puis repli sur le créneau en mémoire de
  ce processus (l'espacement local est conservé, aucune requête n'est bloquée indéfiniment).
- Créneau enregistré à plus d'une heure dans le futur (horloge reculée) : ignoré.
- Caches distincts (fichiers différents, machines différentes) : aucun partage ; utiliser le même
  `GENEALOGISTE_CACHE` pour que plusieurs serveurs se coordonnent.

### Ralentissement durable après surcharge

Une réponse 429, 502, 503 ou 504 d'un hôte **double** son intervalle pour le reste de la journée (date
locale : jusqu'à minuit, comme le plafond journalier), dans la limite de `GENEALOGISTE_RALENTISSEMENT_MAX`
secondes (60 par défaut ; 0 désactive). Les incidents se cumulent (×2, ×4, ×8…) jusqu'au plafond ; l'état
est persistant (table `ralentissements` du cache SQLite) et partagé entre processus. Un hôte dont
l'intervalle de base est nul (`GENEALOGISTE_DEBITS=hote=0`) n'est pas ralenti.

**Anti-rebond** : un hôte n'est doublé qu'**une fois par fenêtre de 5 minutes** (`ANTI_REBOND = 300` s
dans `http.py`, comptés depuis le dernier doublement). Une rafale d'erreurs d'un même épisode (requêtes
parallèles de plusieurs serveurs, reprises d'un même appel) ne vaut donc qu'un doublement : les réponses
suivantes de la fenêtre sont comptées (nombre d'incidents, dernier statut) et l'erreur indique toujours
l'intervalle courant, mais le facteur n'augmente pas. L'horodatage du dernier doublement (colonne
`double_a`, ajoutée automatiquement aux caches existants) est lu et écrit dans la même transaction que le
facteur : la règle tient entre processus. Un changement de jour repart de ×1 quelle que soit la fenêtre.

- `Retry-After` continue de primer pour l'attente immédiate ; le ralentissement règle le rythme des
  requêtes suivantes.
- L'enveloppe d'erreur indique l'intervalle courant (`intervalle_actuel`, et dans le message) en plus de
  `reessayer_apres`.
- `diagnostic` liste les hôtes ralentis (contrôle `debit` : intervalle, nombre d'incidents, dernier statut).
- `cache_purger("ralentissement")` rétablit le rythme normal de tous les hôtes (écriture, confirmée) ; une
  purge complète `cache_purger()` ne le lève pas. Le lendemain, le rythme normal revient de lui-même.

## Politique d'accès par service

`politique_acces.py` (#211, lot B). Une seule table donne, pour chaque hôte externe, l'**intervalle** minimal
entre deux requêtes, le **plafond** de requêtes émises par jour, la **concurrence** (requêtes simultanées) et
la **référence** (CGU ou documentation d'API, avec sa date de relevé). Le client HTTP (intervalle) et le
plafond journalier la lisent tous deux : aucune autre valeur n'est codée ailleurs. Le référentiel
`archives_fr.json` reste la source de `intervalle_requetes` des services d'archives (validation inchangée).

Chaque valeur porte sa **provenance** :

| Provenance | Sens |
|---|---|
| `sourcee` | valeur prise dans la référence citée (`reference` + `releve_le` obligatoires, sinon refus au chargement) |
| `historique` | valeur historique du plugin, reprise telle quelle (ancienne table `RATE` de `server.py`) |
| `referentiel` | `intervalle_requetes` d'un service du référentiel des archives |
| `environnement` | surcharge par `GENEALOGISTE_DEBITS` ou `GENEALOGISTE_PLAFONDS_JOUR` |
| `defaut` | défaut prudent du plugin (`GENEALOGISTE_DEBIT_DEFAUT`, `GENEALOGISTE_PLAFOND_JOUR_ARCHIVES`, `GENEALOGISTE_PLAFOND_JOUR_DEFAUT`) |

Aucune valeur n'est présentée comme officielle sans référence vérifiée. Quand la documentation d'un service
publie des limites, elles sont relevées dans `limites_documentees` à titre d'information : la valeur
appliquée reste la valeur historique, plus prudente. Le relevé des accès machine (#119,
[acces-machine-archives.md](acces-machine-archives.md), 2026-11-18) ne marque `sourcee` que les valeurs
appliquées égales à une limite publiée : intervalles de matchID et de l'API Géo. Aucun service relevé ne
publie de plafond journalier ni de concurrence applicables : ces valeurs restent des défauts du plugin.

Table au 2026-11-18 (défauts de configuration : intervalle 1,5 s, plafond 1000 requêtes/jour) :

| Hôte | Service | Intervalle | Plafond/jour | Concurrence | Référence (relevé) |
|---|---|---|---|---|---|
| `deces.matchid.io` | matchID | 1 s (sourcée) | 1000 (défaut) | 1 (défaut) | [matchID, API](https://matchid.io/link-api) (2026-11-18) : recherche limitée à une requête par seconde ; sans jeton, nombre d'appels limité |
| `api.wikitree.com` | WikiTree API | 1 s (historique) | 1000 (défaut) | 1 (défaut) | [README de l'API](https://github.com/wikitree/wikitree-api/blob/main/README.md) (2026-11-17) : limites strictes sans `appId`, aucun chiffre publié |
| `gallica.bnf.fr` | Gallica (BnF) | 1 s (historique) | 1000 (défaut) | 1 (défaut) | — (aucune limite chiffrée trouvée sur [api.bnf.fr](https://api.bnf.fr/fr/api-gallica-de-recherche)) |
| `query.wikidata.org` | Wikidata Query Service | 1 s (historique) | 1000 (défaut) | 1 (défaut) | [User Manual, Query limits](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual#Query_limits) (2026-11-17) : 60 s de calcul/min, 30 erreurs/min, 5 requêtes parallèles par IP |
| `geo.api.gouv.fr` | API Géo | 0,1 s (sourcée) | 1000 (défaut) | 1 (défaut) | [FAQ data.gouv.fr](https://guides.data.gouv.fr/foire-aux-questions) (2026-11-18) : 10 requêtes/s par IP (API Découpage administratif) ; la [fiche data.gouv.fr](https://www.data.gouv.fr/dataservices/672cf6946a8456f417812b0f) annonce 50 appels/s : la plus stricte est retenue |
| `www.insee.fr` | INSEE (fichiers du COG) | 1,5 s (défaut) | 1000 (défaut) | 1 (défaut) | — |
| `n2t.net` | N2T (registre des NAAN ARK) | 1,5 s (défaut) | 1000 (défaut) | 1 (défaut) | — |
| hôtes du référentiel des archives (sous-domaines compris, hors type « autre ») | service du référentiel | `intervalle_requetes` (référentiel ; ANOM : 5 s, `Crawl-delay` de son robots.txt) sinon 1,5 s (défaut) | `GENEALOGISTE_PLAFOND_JOUR_ARCHIVES` (1000) | 1 (défaut) | référentiel ([archives.md](archives.md)) |
| tout autre hôte (IIIF, visionneuses…) | — | `GENEALOGISTE_DEBIT_DEFAUT` (1,5 s) | `GENEALOGISTE_PLAFOND_JOUR_DEFAUT` (1000) | 1 (défaut) | — |

Un test dérive des modules `sources/` (et des URL COG de la configuration) la liste des hôtes réellement
interrogés et exige qu'ils soient tous déclarés (table ou référentiel) ; un hôte dynamique (manifeste IIIF
d'un tiers) tombe sur le défaut explicite.

**Surcharges** (priorité décroissante) :

- intervalle : `GENEALOGISTE_DEBITS=hote=secondes,…` > `intervalle_requetes` du référentiel > table >
  `GENEALOGISTE_DEBIT_DEFAUT` ;
- plafond/jour : `GENEALOGISTE_PLAFONDS_JOUR=hote=requetes,…` > table > `GENEALOGISTE_PLAFOND_JOUR_ARCHIVES`
  (hôtes d'archives) > `GENEALOGISTE_PLAFOND_JOUR_DEFAUT` (tout autre hôte) ; 0 désactive.

**Concurrence** : le serveur sérialise les appels d'outils et le client n'émet jamais deux requêtes en
parallèle ; la valeur 1 est donc la contrainte effective par processus (et l'intervalle partagé espace les
départs entre processus). Elle est consignée pour une éventuelle parallélisation, sans sémaphore aujourd'hui.

**Visibilité** : `diagnostic` (contrôle `politique_acces`) liste la politique effective de chaque service
nommé et des hôtes surchargés, avec la provenance de chaque valeur, les défauts par catégorie et la
consommation du jour ; `archives_service` ajoute `politique_acces` pour le site et la visionneuse du service.

## Identification : User-Agent et contact facultatif

`config.py` (#211, lot D). Chaque requête externe (sources, archives, IIIF, ainsi que Gramps Web) porte
l'en-tête `User-Agent` suivant, de la forme produit + commentaire (RFC 9110) :

```text
genealogiste-mcp/<version> (plugin Claude Code; usage genealogique personnel)
```

**Contact facultatif** : `GENEALOGISTE_CONTACT` (adresse électronique ou URL fournie par l'utilisateur) est
ajouté à la fin du commentaire, pour qu'un service puisse joindre l'utilisateur au lieu de le bloquer :

```text
genealogiste-mcp/<version> (plugin Claude Code; usage genealogique personnel; contact: contact@example.org)
```

- **Opt-in, jamais de valeur par défaut** : absente ou vide, l'en-tête est identique, octet pour octet, à
  celui sans contact. Le plugin n'invente ni ne déduit aucun contact (compte Git, adresse système…).
- **Donnée personnelle** : le contact est envoyé à **chaque hôte externe** interrogé (services d'archives,
  matchID, WikiTree, Gallica, Wikidata, API Géo, INSEE, manifestes IIIF de tiers…), qui peut le conserver
  dans ses journaux. Préférer une adresse dédiée à cet usage plutôt qu'une adresse personnelle principale.
- **Jamais journalisé** : ni dans le journal de recherche, ni dans le journal d'exploitation. `diagnostic`
  n'indique que son état (`valeurs.contact_user_agent` : `absent`, `configuré`, `rejeté`, `ignoré`), et
  `make check` de même ; la valeur n'est jamais affichée.
- **Validation** : espaces de début et de fin retirés ; refus d'une valeur de plus de 200 caractères, non
  ASCII, contenant un caractère de contrôle (dont retour chariot et saut de ligne) ou l'un de `(`, `)`, `;`,
  `\` (qui sortiraient du commentaire de l'en-tête). Une valeur refusée est **ignorée** (User-Agent sans
  contact), sans bloquer le démarrage, et signalée par `diagnostic` (contrôle `configuration`, état
  `attention`, avec le motif mais sans la valeur).
- **User-Agent explicite** : si `GENEALOGISTE_USER_AGENT` est défini, il est envoyé **tel quel** et le contact
  n'y est jamais ajouté ; `diagnostic` signale alors le contact comme ignoré. Pour combiner les deux, inclure
  le contact dans `GENEALOGISTE_USER_AGENT`.

**Filtre de WikiTree contre les robots d'IA (#253)** : depuis novembre 2026, `api.wikitree.com` renvoie une
page 403 « Error 403 - Access Blocked » (« problems with AI-scraping bots ») à tout User-Agent contenant
« claude », donc au User-Agent par défaut. Le plugin la reconnaît comme blocage (`bloque_antirobot`,
protection `blocage robots IA`) : tâche manuelle, coupe-circuit, aucun réessai. **Le User-Agent n'est pas
modifié pour passer ce filtre** : masquer l'outil reviendrait à contourner une décision délibérée du site.
Voie légitime : écrire à WikiTree (info@wikitree.com) en citant l'`appId` pour demander son autorisation ;
en attendant, consulter WikiTree depuis son navigateur et reprendre le relevé avec `source_collee`.

## Plafond journalier par hôte et budget d'enquête

`budget.py`, `http.py`, `cache.py` (#157, étendu à tous les hôtes par #211).

- **Plafond journalier** : au plus `GENEALOGISTE_PLAFOND_JOUR_ARCHIVES` requêtes **émises** par jour (date
  locale) vers chaque hôte d'un service d'archives du référentiel (`site` et `visionneuse`, sous-domaines
  compris ; pas les services de type « autre » : matchID, Gallica, RetroNews, FranceArchives), et au plus
  `GENEALOGISTE_PLAFOND_JOUR_DEFAUT` vers tout autre hôte (API comprises) ; `GENEALOGISTE_PLAFONDS_JOUR`
  règle un hôte précis ([politique d'accès par service](#politique-daccès-par-service)). Défauts
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
  **Pourquoi 1000 pour les API** : une recherche multi-sources émet une requête par source, une fiche
  WikiTree ou une requête Wikidata une ou deux ; le budget d'une enquête est de 200 requêtes par hôte. 1000
  requêtes par jour couvrent donc plusieurs enquêtes complètes, et bien davantage en usage interactif,
  puisque les réponses servies par le cache (30 à 365 jours selon la source) ne comptent pas. Le plafond
  borne en revanche une boucle autonome : à 1 s d'intervalle, 1000 requêtes représentent au moins
  17 minutes de requêtes continues vers le même service. Un usage légitime plus intense (structuration de
  milliers de lieux par l'API Géo) se règle par `GENEALOGISTE_PLAFONDS_JOUR=geo.api.gouv.fr=5000`.
- **Budget d'enquête** : avec `enquete=<id>`, tout outil réseau de collecte du catalogue
  (`outils.BUDGET_ENQUETE`, dérivé de `outils.OUTILS` ; exemptions motivées dans `outils.HORS_BUDGET`) est
  mesuré côté serveur : l'enveloppe de `serveur_mcp.py` ajoute le paramètre facultatif `enquete` et exécute
  l'appel sous la mesure (#211). Une requête qui dépasserait le budget de l'hôte est refusée **avant
  l'envoi** (voir [enquetes.md](enquetes.md#budget-et-arrêt-propre)). Dimensions : `images` et
  `requetes_par_hote` ; la durée et le coût estimé ne sont plus des limites (le coût réel :
  `--max-budget-usd` côté client).

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
| `GENEALOGISTE_RALENTISSEMENT_MAX` | 60 | intervalle maximal (s) d'un hôte ralenti après 429/5xx ; 0 désactive |
| `GENEALOGISTE_EXCLUSION_ANTIROBOT` | 604800 | exclusion (s) d'un hôte dont le défi anti-robot persiste ; 0 = pause seule |

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
  Aucun contournement n'est tenté. Une page de blocage générée par Cloudflare (structure `cf-error-details`,
  ex. erreur 1020) est reconnue en 403 seulement ; servie en 5xx, elle signale une panne de l'origine (#150).
- **Exclusion durable** (#150) : chaque défi est consigné par hôte dans le cache SQLite (table
  `defis_antirobot` : protection, URL, statut HTTP, première et dernière détection, nombre). Un défi
  observé de nouveau dans les 30 jours après le précédent — il a donc persisté après la pause — exclut
  l'hôte `GENEALOGISTE_EXCLUSION_ANTIROBOT` secondes (604800, soit 7 jours, par défaut ; 0 = pause seule) :
  aucune requête n'est émise, l'enveloppe porte `exclusion: true` et `exclu_jusqu_au` (UTC). L'exclusion
  survit au redémarrage et à une purge complète du cache ; `cache_purger("coupe_circuit")` la lève (nouvel
  essai explicite, l'historique reste) et `cache_purger("antirobot")` oublie l'historique. Cet historique
  vaut pour l'adresse réseau de cette installation : `archives_service` l'expose sous `defi_observe`, à
  côté de `acces_vps` (mesure de recette), sans le confondre avec elle. La sonde de `diagnostic` consigne
  ses défis mais n'exclut jamais.
- **Suite sans navigateur** : les enveloppes portent `statut: bloque_antirobot`, `service`, `protection`,
  `date_detection` (UTC), l'URL effective, une `tache_manuelle`, `bloque: "anti-robot"`, une `consigne`
  (vue fournie par l'utilisateur puis `media_enregistrer`) et `suite`, exploitable par le modèle sans
  navigateur côté serveur : `relancer: false`, `navigateur_serveur: false`, lien à `ouvrir` par
  l'utilisateur depuis son poste, ce qu'il faut relever, outils de `reprise` (`source_collee`,
  `piece_archiver`, `media_enregistrer`) et levée explicite. Cette tâche et la provenance du défi
  sont conservées au journal (`journal_lister(statut="bloque_antirobot")`), y compris après passage dans
  un adaptateur ou réutilisation du coupe-circuit. Avec `enquete=<id>`, la consultation devient une tâche
  manuelle `a_faire` de l'enquête (une par URL bloquée, champ `url`), reprise par `enquete_reprendre` ;
  l'enveloppe renvoie son `id`. L'agent poursuit les autres pistes, puis reprend avec `source_collee` ou
  `piece_archiver` sur un fichier local fourni depuis un accès autorisé.
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
