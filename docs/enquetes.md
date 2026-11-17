# État d'enquête persistant et reprenable

Le journal de recherche (`journal.jsonl`) dit **qu'une requête a eu lieu**. L'état d'enquête dit **où en
est la recherche** : quelles pistes restent ouvertes, quelles vues d'un registre ont été lues et ce qu'on y a
lu, ce qui attend l'utilisateur. Après une interruption (limite d'usage, contexte résumé, redémarrage du
serveur), `enquete_reprendre` donne la suite sans relire le journal entier et sans refaire une demande déjà
notée.

## Stockage

- Un fichier JSON par enquête : `<données>/enquetes/<id>.json`, indenté, lisible et modifiable à la main
  (un fichier illisible est ignoré, les autres restent utilisables).
- Écriture atomique (fichier temporaire puis renommage) sous le verrou `<données>/.enquetes.lock`
  (plusieurs serveurs sur les mêmes données).
- **Versionné avec le journal** : le dossier `enquetes/` fait partie des fichiers internes du dépôt Git des
  données. Il est commité avec `journal.jsonl`, dans le commit séparé « Journal de recherche » qui précède
  chaque modification de l'arbre (`arbre_appliquer`, miroir Gramps). Une annulation de modification ne touche
  donc jamais l'état d'enquête. Entre deux écritures de l'arbre, l'état est sur disque mais pas encore
  commité, comme le journal.
- Rien n'est envoyé au réseau : l'état est local. Les outils réseau gardent leur contrôle « vivants »
  (`_garde`) ; une demande refusée pour une personne vivante n'est pas notée.

## Contenu

| Élément | Champs |
|---|---|
| enquête | `id` (stable, minuscules, chiffres, `-`, `_`), `sujet`, `personnes` (ids de l'arbre), `statut` (`ouverte` / `bloque` / `close`) |
| piste | `id` (`p1`…), `question`, `hypotheses`, `sources` à consulter dans l'ordre (`{libelle, outil, parametres, fait}`), `statut`, `note`, `journal` |
| registre | `id` (`r1`…), `source` (ARK, URL de visionneuse ou manifeste), `cle` (ARK du registre sans vue), `service`, `cote`, `titre`, `piste`, `nb_vues`, `bornes` `[de, a]`, `vues_lues` (intervalles fusionnés), `lectures` (`{vue, date, type, numero, note}`), `verdict`, `statut`, `journal` |
| tâche manuelle | `id` (`t1`…), `description`, `service`, `piste`, `statut` (`a_faire` / `faite` / `abandonnee`) |
| requête faite | `outil`, `parametres`, `cle` normalisée, `date`, `resultat` (`positif` / `negatif` / `erreur` / `manuel`), `journal` |
| budget | `budget` (limites), `consomme` (`requetes` par hôte, `images`, `duree_s`, `cout_tokens`), `blocage` (`motif`, `limite`, `date`, `message`), `reste_a_faire` (`outil`, `parametres`, `cle`, `date`, `limite`) |

Statuts d'une piste ou d'un registre, sans accents comme les outils : `a_faire`, `en_cours`, `trouve`,
`negatif`, `bloque`, `manuel`. `trouve` et `negatif` ferment l'élément ; `bloque` et `manuel` le gardent
ouvert sans action automatique.

## Outils

| Outil | Effet |
|---|---|
| `enquete_ouvrir(sujet, personnes, id, budget)` | crée l'enquête ; `id` dérivé du sujet si absent ; `budget` facultatif |
| `enquete_noter(enquete, piste, registre, tache, requete, statut, personnes, budget)` | ajoute ou met à jour (par `id`, ou pour un registre par ARK/cote) ; `budget` modifie les limites |
| `enquete_etat(enquete)` | état complet + `coherence_journal` ; sans argument : liste des enquêtes |
| `enquete_reprendre(enquete)` | `a_faire` (outil et paramètres prêts, dans l'ordre ; d'abord le reste à faire refusé faute de budget), pistes ouvertes, registres en cours avec `vues_restantes`, tâches manuelles, `deja_fait`, `budget`, `blocage` |

Ces outils sont locaux : lecture (`enquete_etat`, `enquete_reprendre`) ou trace au journal
(`enquete_ouvrir`, `enquete_noter` : classe collecte, état géré par le plugin, ouverture sans écrasement), autorisés
sans confirmation (voir les classes de permission dans `docs/securite.md`), sauf pour fixer ou modifier un
`budget` ou rouvrir une enquête (`statut: "ouverte"`) : confirmation demandée par le hook (#157).

`recherche_multi`, `archives_naviguer` et `archive_image` acceptent un paramètre facultatif
`enquete=<id>` : la demande est notée dans l'état (fenêtre parcourue et nombre de vues pour une navigation,
vue consultée pour une image, résultat et entrées de journal pour une recherche). Sans ce paramètre, rien ne
change pour ces outils, sinon l'indication ci-dessous.

## Budget et arrêt propre

Chaque enquête porte un budget (#157), déclaré à `enquete_ouvrir(..., budget={...})` et modifiable par
`enquete_noter(id, budget={...})`. Dimensions (0 = illimité) :

| Limite | Défaut | Variable | Compté |
|---|---|---|---|
| `requetes_par_hote` | 200 | `GENEALOGISTE_BUDGET_REQUETES_HOTE` | requêtes réellement émises vers chaque hôte |
| `images` | 40 | `GENEALOGISTE_BUDGET_IMAGES` | `archive_image` réussis (vue ou recadrage lus par le modèle) |
| `duree_min` | 30 | `GENEALOGISTE_BUDGET_DUREE_MIN` | minutes d'**activité cumulée** des outils de collecte |
| `cout_tokens` | 100 000 | `GENEALOGISTE_BUDGET_COUT_TOKENS` | `cout_estime_tokens` des images + texte des réponses (≈ 4 caractères par token) |

**Compté côté serveur, pas déclaré** : un appel de `recherche_multi` (et des sources qu'il interroge),
`archives_naviguer` ou `archive_image` avec `enquete=<id>` s'exécute sous une mesure ; le client HTTP compte
chaque requête émise par hôte (essais et redirections compris). Une réponse servie par le cache ne consomme
aucune requête (son texte reste compté dans le coût). Chaque réponse porte `budget` : `limites`, `consomme`
et `reste` (par hôte contacté, `requetes_autre_hote` pour un hôte encore jamais contacté).

**Durée = activité cumulée**, non le temps écoulé depuis l'ouverture : une enquête reprise après une
interruption (limite d'usage, nuit, redémarrage) ne perd pas son budget pendant l'attente ; seul le temps
passé dans les outils de collecte (attentes de débit et reprises comprises) est décompté.

**Épuisement** :

1. *Avant l'appel* : enquête déjà bloquée, durée atteinte, image de trop (`images`) ou coût prévu dépassé
   (`archive_image` estime le coût d'après `largeur`) : refus immédiat, aucune requête ;
2. *pendant l'appel* : la requête qui dépasserait le budget d'un hôte ou la durée est refusée **avant
   l'envoi** ; `recherche_multi` n'interroge pas les sources suivantes.

Le refus est explicite (`refus`, `statut: "bloque"`, `motif: "budget"`, `limite`, `budget`), l'enquête passe
au statut `bloque` avec `blocage`, et l'appel refusé (ou, pour `recherche_multi`, les sources non
interrogées) est consigné dans `reste_a_faire`. La réponse contient un `compte_rendu` partiel (requêtes faites,
positives, négatives, pistes et registres ouverts, tâches manuelles). Une enquête bloquée refuse toute
collecte jusqu'à ce que le budget soit relevé (`enquete_noter(id, budget={...})`, avec l'accord de
l'utilisateur) : elle redevient `ouverte` si plus aucune limite n'est atteinte. `enquete_reprendre(id)` place
le reste à faire en tête de `a_faire` ; une demande refaite avec `enquete=<id>` en sort.

Sans `enquete`, rien ne change, hormis le plafond journalier par hôte d'archives
(`GENEALOGISTE_PLAFOND_JOUR_ARCHIVES`, [securite.md](securite.md)). Les personnes vivantes restent filtrées
avant tout (`_garde`) : un refus « vivant » ne consomme rien et n'est pas noté.

## « Déjà fait le … »

Les trois outils ajoutent `deja_fait` (liste avec `enquete`, `date`, `resultat`, `message`) quand la même
demande figure déjà dans l'état d'une enquête. L'appel n'est **jamais bloqué** ni modifié. La correspondance
est exacte et prudente :

- `recherche_multi` : mêmes `nom`, `prenom`, `ne_vers`, `lieu`, `decede_vers` (casse, accents et espaces
  ignorés) et même ensemble de sources ; un prénom différent n'est pas « la même demande » ;
- `archives_naviguer` : même registre (ARK sans vue, ou URL) et mêmes `page` et `pas` ; ou fenêtre entièrement
  comprise dans les vues déjà lues du registre ;
- `archive_image` : même registre et même vue, consultée ou notée comme lue (les lectures notées sont
  rappelées). Un recadrage de la même vue est donc signalé : c'est attendu, la consigne reste d'agrandir l'acte.

## Cohérence avec le journal

Toute entrée négative de l'état (piste ou registre `negatif`, requête au résultat `negatif`) référence au
moins une entrée du journal :

- `journal=<id>` fourni à `enquete_noter` : l'entrée doit exister, sinon la notation est refusée ;
- sinon une entrée `source="enquete"`, `statut="negatif"` est créée (identifiants dans `journal_cree`), au nom
  de la première personne de l'enquête ;
- une recherche négative passée par `recherche_multi(..., enquete=<id>)` référence les entrées écrites par
  les sources interrogées.

`enquete_etat(id)` renvoie `coherence_journal: "ok"` ou la liste des éléments négatifs sans trace (cas d'un
fichier édité à la main).

## Reprendre une enquête

```text
enquete_reprendre("naissance-de-jean-dupont")
→ a_faire : [{type: registre, outil: archives_naviguer, parametres: {source, page: 803, pas: 20}}, …]
  deja_fait : [{outil: recherche_multi, date, resultat: negatif}, …]
```

Exécuter `a_faire` dans l'ordre en passant `enquete=<id>` ; ne pas relancer `deja_fait`. Pour un registre,
les vues restantes sont les bornes (ou `1..nb_vues`) moins les vues lues : une vue déjà listée par une
navigation est proposée en `archive_image`, sinon la fenêtre suivante en `archives_naviguer`. Noter chaque
lecture (`registre.lectures`), le verdict et les tâches manuelles avec `enquete_noter`.

L'identifiant d'enquête est une chaîne simple et stable : il peut être repris tel quel comme « enquête
d'origine » par d'autres fonctions (file de propositions).

## Mode autonome

Le chercheur travaille sans personne présente (#158) **seulement sur demande explicite** :
`/genealogiste:enquete <personne> --autonome [budget]` ou `/genealogiste:acte <personne> <acte> --autonome
[budget]` (la commande de campagne s'appuie sur le même mode). Sans `--autonome`, le mode interactif reste
inchangé : questions permises, `arbre_proposer` présenté en diff.

**Lancement.** La commande ouvre ou reprend l'enquête. Un budget indiqué est passé à
`enquete_ouvrir(..., budget={...})` : c'est le seul accord demandé, au lancement, avant toute collecte (une
boucle autonome ne fixe ni ne relève sa propre limite, voir [securite.md](securite.md)) ; sans budget, les
défauts `GENEALOGISTE_BUDGET_*` s'appliquent sans confirmation. L'agent `chercheur` reçoit une consigne qui
commence par :

```text
MODE AUTONOME
enquete: <id>
budget: <budget fixé, ou « défauts »>
```

suivie de la personne et de la question. Sans la ligne `MODE AUTONOME`, l'agent reste interactif.

**Déroulé** (détail dans `agents/chercheur.md`) :

1. `enquete_reprendre(<id>)` si l'enquête existe, sinon `enquete_ouvrir` **sans** `budget` ;
2. pour chaque fait : service et couverture (`archives_service`), registre (`archives_registres`,
   `ark_resoudre`), sondage (`archives_naviguer`, `archives_planche`), lecture (`archive_image`),
   transcription, archivage (`piece_archiver`), citation ; `enquete=<id>` sur `recherche_multi`,
   `archives_naviguer` et `archive_image` ;
3. aucune question : service protégé ou anti-robot, archives non numérisées, source sans API, capture
   nécessaire, homonymes non départagés deviennent des **tâches manuelles** (`enquete_noter(id, tache=…)`) ;
   `media_enregistrer`, qui demande une confirmation, n'est pas utilisé ;
4. arrêt sur refus `motif: "budget"`, sur `a_faire` vide sans autre source consultable (`prochaine_source`),
   ou sur preuve suffisante (statut « confirmé », `arbre_statut_preuve`) ;
5. conclusions **uniquement** par `propositions_deposer(..., enquete=<id>)`, jamais `arbre_proposer` ni
   `arbre_appliquer` ; une conclusion importante (fusion, filiation, passage à « confirmé ») est déposée
   « à vérifier » et le lanceur sollicite l'agent `verificateur` ;
6. compte rendu à format fixe (ci-dessous).

Tous les outils du parcours autonome sont des classes lecture, collecte ou proposition : le hook les autorise
sans confirmation. `tests/test_chercheur_autonome.py` le vérifie sur la section « Mode autonome » de l'agent.

## Compte rendu autonome

Format fixe rendu par le chercheur autonome et par `/genealogiste:enquete --autonome` (fusion des chercheurs),
lu par la commande de lancement. Markdown, dans cet ordre :

- une ligne `Enquête : <id>` ;
- cinq sections aux **titres exacts**, toujours présentes, chacune en liste à puces (`- aucun` si vide) :
  - `## Trouvé` : personne, fait, donnée, référence (service, cote, n° d'acte, vue ou ARK), classification,
    pièce archivée ;
  - `## Négatif` : source et paramètres sans résultat, entrée de journal ;
  - `## Bloqué` : motif (`budget` et limite atteinte, anti-robot, erreur, dépôt refusé) et demande restée en
    `reste_a_faire` ;
  - `## À valider` : un élément par proposition déposée, qui **commence par l'id de la file**
    (`propositions_lister`), puis le titre (« à vérifier » le cas échéant) et le verdict du vérificateur ;
  - `## À faire à la main` : un élément par tâche manuelle, qui commence par son id (`t1`…), puis la description
    et le service ;
- une dernière ligne `Budget : ` suivie du reste en `cle=valeur` séparés par des espaces (`images`,
  `cout_tokens`, `duree_min`, `requetes_autre_hote`, ou `illimite`), puis ` ; statut=ouverte|bloque`.

```markdown
Enquête : deces-jean-martin

## Trouvé
- I1 — décès 4 janvier 1885, Rochefort : AD17, acte n° 3, vue 41 (originale, primaire) ; pièce documents/…
## Négatif
- matchid — MARTIN Jean, décédé vers 1885 : aucun résultat (journal j42)
## Bloqué
- aucun
## À valider
- 20261117-ab12 — Acte de décès de Jean MARTIN (1885) — à vérifier ; vérificateur : probable
## À faire à la main
- t1 — table décennale 1883-1892 non numérisée, consultation sur place (AD17)

Budget : images=4 cout_tokens=61200 duree_min=27 requetes_autre_hote=200 ; statut=ouverte
```

Les valeurs du reste viennent de `budget.reste` de la dernière réponse de collecte ou de
`enquete_reprendre(id).budget`. Une enquête `bloque` se relève avec l'accord de l'utilisateur
(`enquete_noter(id, budget={...})`), puis se reprend avec le même id.

## Recette du mode autonome

Un vrai modèle ne tourne pas en intégration continue. `tests/test_chercheur_autonome.py` rejoue la séquence
d'outils du parcours autonome sur la fixture (`famille.ged`, HTTP simulé) : chaque appel passe d'abord par le
hook réel, qui doit l'autoriser sans confirmation ; la séquence va de `enquete_reprendre` jusqu'à
`propositions_deposer(..., enquete=<id>)` et le test vérifie qu'aucune écriture n'a touché l'arbre, que la
proposition est en file liée à l'enquête, que le budget est consommé et que l'état reste reprenable.

Recette manuelle avec Claude Code, sur une copie des données (jamais sur l'arbre de travail réel) :

1. `GENEALOGISTE_DATA_DIR` vers un répertoire jetable contenant une copie de `mcp/tests/fixtures/famille.ged`
   comme arbre, puis `/genealogiste:enquete I1 personne --autonome budget images=5 duree=10` ;
2. accepter la seule confirmation du lancement (`enquete_ouvrir` avec `budget`) ; ensuite, **aucune** question
   ni demande de permission ne doit apparaître jusqu'à la fin ;
3. contrôler : compte rendu au format ci-dessus, `propositions_lister()` montre les dépôts avec
   `enquete: <id>`, `arbre_historique` ne montre aucun nouveau commit, `enquete_reprendre(<id>)` donne le budget
   consommé, les tâches manuelles et `deja_fait` ;
4. relancer la même commande : l'enquête est reprise sans refaire `deja_fait`.
