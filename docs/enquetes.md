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
| registre | `id` (`r1`…), `source` (ARK, URL de visionneuse ou manifeste), `cle` (ARK du registre sans vue), `service`, `cote`, `titre`, `piste`, `nb_vues`, `bornes` `[de, a]`, `vues_lues` (intervalles fusionnés), `lectures` (`{vue, date, date_fin, type, numero, note}`), `periode` (notée par `archives_naviguer`), `sondages` (`{cible, type_acte, historique, statut}`, #156), `verdict`, `statut`, `journal` |
| tâche manuelle | `id` (`t1`…), `description`, `service`, `piste`, `url` (lien à ouvrir), `statut` (`a_faire` / `faite` / `abandonnee`) ; un défi anti-robot rencontré avec `enquete=<id>` en crée une d'office, une par URL bloquée (#150) |
| requête faite | `outil`, `parametres`, `cle` normalisée, `date`, `resultat` (`positif` / `negatif` / `erreur` / `manuel`), `journal` |
| budget | `budget` (limites), `consomme` (`requetes` par hôte, `images`), `blocage` (`motif`, `limite`, `date`, `message`), `reste_a_faire` (`outil`, `parametres`, `cle`, `date`, `limite`) |

Statuts d'une piste ou d'un registre, sans accents comme les outils : `a_faire`, `en_cours`, `trouve`,
`negatif`, `bloque`, `manuel`. `trouve` et `negatif` ferment l'élément ; `bloque` et `manuel` le gardent
ouvert sans action automatique.

## Outils

| Outil | Effet |
|---|---|
| `enquete_ouvrir(sujet, personnes, id, budget)` | crée l'enquête ; `id` dérivé du sujet si absent ; `budget` facultatif |
| `enquete_noter(enquete, piste, registre, tache, requete, statut, personnes, budget)` | ajoute ou met à jour (par `id`, ou pour un registre par ARK/cote) ; `budget` modifie les limites ; `piste.contexte_seul: true` : piste tirée du seul contexte, jamais une tâche (voir « Tâches de Gramps Web ») |
| `enquete_etat(enquete)` | état complet + `coherence_journal` ; sans argument : liste des enquêtes |
| `archives_sonder(source, date_cible, type_acte, lecture, conclusion, enquete)` | sondage guidé d'un registre (#156) : note la lecture d'une vue et propose la suivante ; arrêt `localise`, `absent` (registre négatif journalisé avec les bornes examinées) ou `budget` ; voir `docs/archives.md` |
| `enquete_reprendre(enquete, taches, elements)` | `a_faire` (outil et paramètres prêts, dans l'ordre ; d'abord le reste à faire refusé faute de budget), pistes ouvertes, registres en cours avec `vues_restantes`, tâches manuelles, `deja_fait`, `budget`, `blocage` |

Pour cadrer une enquête, `/genealogiste:enquete` appelle `arbre_cercle(id, cercle)` (lecture) : le sujet et
ses proches, selon `cercle` = `personne`, `famille` (parents, conjoints, enfants, fratrie, valeur par défaut)
ou `etendu` (en plus grands-parents, beaux-parents, oncles et tantes). Pour chacun : le lien, le statut vivant
(exclu des recherches externes) et le nombre d'actions urgentes tirées des lacunes.

Ces outils sont locaux : lecture (`enquete_etat`, `enquete_reprendre`) ou trace au journal
(`enquete_ouvrir`, `enquete_noter` : classe collecte, état géré par le plugin, ouverture sans écrasement), autorisés
sans confirmation (voir les classes de permission dans `docs/securite.md`), sauf pour fixer ou modifier un
`budget` ou rouvrir une enquête (`statut: "ouverte"`) : confirmation demandée par le hook (#157).

Tous les outils réseau de collecte (catalogue `outils.BUDGET_ENQUETE` : `recherche_multi`,
`archives_naviguer`, `archives_registres`, `archives_planche`, `archive_image`, `piece_archiver`,
`ark_resoudre`, `matchid_recherche`, `wikitree_*`, `gallica_*`, `wikidata_*`, `geo_*`) acceptent un paramètre
facultatif `enquete=<id>` qui les fait compter dans le budget de l'enquête (#211). Exemptés, motif à l'appui
dans `outils.HORS_BUDGET` : `diagnostic` (contrôle de santé) et `gramps_recherche` / `gramps_personne`
(serveur Gramps Web de l'utilisateur). Avec `enquete=<id>`, chacun de ces outils note aussi la demande
aboutie dans l'état (`requetes` : paramètres reçus, clé normalisée, date, résultat `positif` ou `negatif`,
entrée de journal) ; en plus, `archives_naviguer` et `archive_image` notent la fenêtre parcourue, le nombre de
vues et la vue consultée du registre. Sans ce paramètre, rien ne change pour ces outils, sinon l'indication
ci-dessous.

## Budget et arrêt propre

Chaque enquête porte un budget (#157), déclaré à `enquete_ouvrir(..., budget={...})` et modifiable par
`enquete_noter(id, budget={...})`. Il **arrête une boucle d'enquête** ; il ne ménage pas les sites et ne
plafonne pas le coût. Dimensions (0 = illimité) :

| Limite | Défaut | Variable | Compté |
|---|---|---|---|
| `requetes_par_hote` | 200 | `GENEALOGISTE_BUDGET_REQUETES_HOTE` | requêtes réellement émises vers chaque hôte |
| `images` | 40 | `GENEALOGISTE_BUDGET_IMAGES` | `archive_image` réussis (vue ou recadrage lus par le modèle) et `archives_planche` réussies (une planche) |

Trois préoccupations, trois mécanismes (#211) :

| Préoccupation | Où | Actif |
|---|---|---|
| ménager les sites | couche réseau du serveur, tous les outils : intervalle par hôte, ralentissement après 429/503, plafond journalier, coupe-circuit anti-robot ([securite.md](securite.md)) | toujours |
| arrêter une boucle d'enquête | budget d'enquête : `images`, `requetes_par_hote` | avec `enquete=<id>` |
| plafonner le coût réel | client : `claude -p … --max-budget-usd` | à fixer pour toute campagne ([campagne.md](campagne.md)) |

Les anciennes limites `duree_min` et `cout_tokens` sont retirées : la durée ne mesurait que le temps passé
dans les outils, et le coût estimé sous-estimait fortement le coût réel (raisonnement, contexte). Une enquête
existante qui les contient est lue sans erreur : ces clés (et `duree_s`) sont ignorées, un blocage sur l'une
d'elles est levé ; un `budget` reçu avec ces clés les ignore. Les variables `GENEALOGISTE_BUDGET_DUREE_MIN` et
`GENEALOGISTE_BUDGET_COUT_TOKENS` encore définies sont ignorées et signalées par `diagnostic`.
`cout_estime_tokens` reste une **information** dans les réponses d'`archive_image` et d'`archives_planche`,
sans limite.

**Compté côté serveur, pas déclaré** : un appel d'outil de collecte avec `enquete=<id>` s'exécute sous une
mesure ; le client HTTP compte chaque requête émise par hôte (essais et redirections compris). Une réponse
servie par le cache ne consomme aucune requête. Chaque réponse porte `budget` : `limites`, `consomme` et
`reste` (par hôte contacté, `requetes_autre_hote` pour un hôte encore jamais contacté).

**Épuisement** :

1. *Avant l'appel* : enquête déjà bloquée ou image de trop (`images`) : refus immédiat, aucune requête ;
2. *pendant l'appel* : la requête qui dépasserait le budget d'un hôte est refusée **avant l'envoi** ;
   `recherche_multi` n'interroge pas les sources suivantes.

Le refus est explicite (`refus`, `statut: "bloque"`, `motif: "budget"`, `limite`, `budget`), l'enquête passe
au statut `bloque` avec `blocage`, et l'appel refusé (ou, pour `recherche_multi`, les sources non
interrogées) est consigné dans `reste_a_faire`. La réponse contient un `compte_rendu` partiel (requêtes faites,
positives, négatives, pistes et registres ouverts, tâches manuelles). Une enquête bloquée refuse toute
collecte jusqu'à ce que le budget soit relevé (`enquete_noter(id, budget={...})`, avec l'accord de
l'utilisateur) : elle redevient `ouverte` si plus aucune limite n'est atteinte. `enquete_reprendre(id)` place
le reste à faire en tête de `a_faire` ; une demande refaite avec `enquete=<id>` en sort.

Sans `enquete`, rien ne change, hormis le plafond journalier par hôte d'archives
(`GENEALOGISTE_PLAFOND_JOUR_ARCHIVES`, [securite.md](securite.md)). Les personnes vivantes restent filtrées
avant tout (`_garde`) : un refus « vivant » ne consomme rien et n'est pas noté. Avec `enquete`, la garde
passe même avant le contrôle de budget : une enquête bloquée renvoie le refus « vivant » (identique à celui de
l'outil) sans consigner les paramètres au `reste_a_faire`. Pour les outils mesurés par l'enveloppe générique,
`outils.GARDE_AVANT_BUDGET` déclare chaque appel de la garde fait par l'outil, dans l'ordre et avec ses
paramètres (plusieurs appels quand l'outil garde plusieurs textes : `themes` puis `lieu` pour `contexte_local`
et `pistes_contexte`, `texte` puis `lieu` pour `presse_recherche`, #347) ; tous sont rejoués avant le budget.
`tests/test_garde_avant_budget.py` compare la déclaration aux appels `_garde` écrits dans le code de l'outil :
un paramètre gardé dans l'outil sans y être déclaré fait échouer les tests. `recherche_multi` appelle lui-même
la garde avant le budget.

## Tâches de Gramps Web (#263)

Avec le backend gramps et `GENEALOGISTE_GRAMPS_TACHES=true`, les pistes et les tâches manuelles d'une enquête
peuvent devenir des **tâches de Gramps Web** (vue Tâches), visibles des autres comptes de l'instance. Rien n'est
automatique ni caché :

1. **Proposer** : `enquete_reprendre(id, taches=true)` (ou `elements=["t1", "p2"]`) renvoie
   `taches_a_proposer` : une opération `ajouter_tache` par piste ou tâche manuelle ouverte sans tâche liée
   (titre = question ou description, statut dérivé : piste `en_cours` → `In Progress`, `bloque` → `Blocked`,
   sinon `Open` ; priorité moyenne ; privée ; personnes de l'enquête nommées ; ligne de référence
   `Enquête Genealogiste : <id> · <élément>`). Rien n'est écrit : `arbre_proposer`, diff, accord explicite,
   `arbre_appliquer`.
2. **Mémoriser le lien** (local) : `enquete_noter(id, tache={"id": "t1", "tache_gramps": "S12"})` (ou
   `piste=…`) avec l'identifiant de `references_creees` ; `"tache_gramps": ""` délie. Sans lien mémorisé, la
   ligne de référence de la description suffit à retrouver la tâche (`lien: "reference"`, signalé dans
   `a_memoriser`).
3. **Écarts signalés** : `enquete_etat(id)`, `enquete_reprendre(id)` (bloc `taches_gramps` : `liees`, `ecarts`,
   `non_liees`) et `gramps_synchroniser` (`taches_ecarts`, enquêtes non closes) comparent ouvert / terminé :
   tâche `Done` dans Gramps Web mais élément encore ouvert (tâche manuelle `a_faire`, piste ni `trouve` ni
   `negatif`), ou l'inverse ; tâche liée supprimée ou qui a perdu `ToDo`. Chaque écart donne les deux sens,
   **jamais exécutés** : `vers_gramps` (`modifier_tache` à passer par `arbre_proposer`) et `vers_enquete`
   (`enquete_noter`, après accord de l'utilisateur ; pour une piste, choisir `trouve` ou `negatif`).

**Piste « contexte seul » : jamais une tâche (#325).** Une piste de `pistes_contexte` tirée du seul contexte
historique (règle `element_de_contexte`, statut `contexte_seul`) se note dans l'enquête avec le marqueur
`"contexte_seul": true`, que `pistes_contexte` place dans `depot.enquete_noter.piste` et qui ne se retire plus. Une
piste notée avant ce marqueur est reconnue à la note que l'outil lui donnait (« pistes_contexte, règle
element_de_contexte ; statut contexte seul »), et reçoit le marqueur à sa première mise à jour. Verrous, dans le
code (`enquetes.est_contexte_seul`, `taches.operations_enquete`, `server._refus_tache_contexte_seul`) :

| Chemin | Effet |
|---|---|
| `enquete_reprendre(id, taches=true)`, avec ou sans `elements` | aucune opération `ajouter_tache` pour cette piste, même nommée dans `elements` ; elle est rendue dans `taches_a_proposer.refuses` (`element`, `motif`) |
| `enquete_reprendre(id)`, `enquete_etat(id)` | reprise : piste ouverte rendue avec `contexte_seul: true` et son `motif`, sans action dans `a_faire` ; les deux : hors de `taches_gramps.non_liees`, listée dans `taches_gramps.contexte_seul` |
| `arbre_proposer`, `propositions_deposer`, `propositions_reprendre` | une opération `ajouter_tache` qui la référence (`enquete` + `element`) est refusée avant toute proposition (`erreur`, `motif: "contexte_seul"`) : rien n'entre dans la file |
| `enquete_noter` | refus d'une tâche manuelle rattachée à cette piste (`tache.piste`), d'un lien `tache_gramps`, et du retrait du marqueur ; statut et note de la piste restent modifiables |

Une source portant sur l'individu ne « débloque » pas la piste : elle se note dans une nouvelle piste, ordinaire.
Les classes de permission des outils d'enquête sont inchangées.

Correspondance des statuts : tâche manuelle `a_faire` ↔ tâche ouverte (`Open`, `In Progress`, `Blocked`),
`faite` / `abandonnee` ↔ `Done` ; piste `trouve` / `negatif` ↔ `Done`, autres statuts ↔ ouverte. Réglage
désactivé : aucun de ces blocs n'apparaît, les sorties sont inchangées.

## Signets de Gramps (#282)

Avec le backend gramps, les personnes d'une enquête peuvent être mises en **signet de la base Gramps** (menu Signets
de Gramps Desktop ; l'interface de Gramps Web n'affiche pas ces signets : les siens sont un réglage du navigateur,
voir [gramps-web.md](gramps-web.md#signets-fiche-du-chercheur-et-formats-de-nom-282)). Rien n'est automatique :

1. **Proposer la pose** : `enquete_ouvrir(…, signets=True)` ajoute à la réponse la clé `signets` (une proposition :
   `diff`, `jeton`), ou `gramps_reglages(signets={"enquete": id, "action": "poser"})` pour une enquête existante.
   Seules les personnes **absentes** des signets sont proposées ; une personne déjà en signet est un signet de
   l'utilisateur : signalée dans `notes`, jamais comptée, jamais retirée. Rien n'est écrit avant `arbre_appliquer` après
   accord explicite.
2. **Trace locale** : à l'application, `signets_poses` (handle et identifiant Gramps, date ; jamais un nom) est inscrit
   dans le fichier de l'enquête (`enquete_etat`) ; aucun attribut n'est ajouté dans Gramps.
3. **Retrait proposé à la clôture** : `enquete_noter(id, statut="close")` signale `signets_a_retirer` (nombre,
   consigne) sans rien exécuter ; `gramps_reglages(signets={"enquete": id, "action": "retirer"})` propose le retrait des
   **seuls** signets de la trace encore présents (un signet retiré à la main entre-temps n'est pas reproposé), après
   accord. L'annulation d'une pose ou d'un retrait (`arbre_annuler_modification`) met la trace à jour ; un retrait annulé
   remet le signet en fin de liste.

Mode fichier : `signets=True` répond « disponibles en mode gramps » sans rien faire ; sans `signets`, `enquete_ouvrir`
est inchangé.

## « Déjà fait le … »

Tous les outils qui acceptent `enquete` (budget, ci-dessus) ajoutent `deja_fait` (liste avec `enquete`,
`date`, `resultat`, `message`) quand la même demande figure déjà dans l'état d'une enquête, avec ou sans
`enquete` dans l'appel. L'appel n'est **jamais bloqué** ni modifié (seul `deja_fait` est ajouté) ; tout est
local. Seul un appel abouti est signalé et noté : un refus « vivant » (la garde passe avant tout), un refus de
budget ou une erreur ne le sont pas. La correspondance est exacte et prudente :

- `recherche_multi` : mêmes `nom`, `prenom`, `ne_vers`, `lieu`, `decede_vers` (casse, accents et espaces
  ignorés) et même ensemble de sources ; un prénom différent n'est pas « la même demande » ;
- `archives_naviguer` : même registre (ARK sans vue, ou URL) et mêmes `page` et `pas` ; ou fenêtre entièrement
  comprise dans les vues déjà lues du registre ;
- `archive_image` : même registre et même vue, consultée ou notée comme lue (les lectures notées sont
  rappelées). Un recadrage de la même vue est donc signalé : c'est attendu, la consigne reste d'agrandir l'acte.

Pour les autres, l'identité est déclarée par outil dans le catalogue (`outils.IDENTITE_REQUETE`) : tous les
paramètres listés doivent être égaux, après normalisation ; un paramètre omis vaut son défaut. *Texte* : casse,
accents et espaces ignorés ; *exact* : identifiants, ARK, URL, clés et codes comparés tels quels (espaces de
bord retirés) ; entiers et booléens par valeur. La pagination fait partie de la demande.

| Outil | Même demande si mêmes… |
|---|---|
| `matchid_recherche` | texte : `nom`, `prenom`, `ne_vers`, `lieu_naissance`, `decede_vers`, `lieu_deces`, `sexe`, `texte` ; `taille`, `page` |
| `wikitree_recherche` | texte : `nom`, `prenom`, `ne_vers`, `lieu`, `decede_vers` ; `limite` |
| `wikitree_profil`, `wikitree_personne` | `cle` (exacte) |
| `wikitree_ascendants`, `wikitree_descendants` | `cle` (exacte), `profondeur` |
| `gallica_recherche` | texte : `texte`, `titre` ; exacts : `type_doc`, `debut`, `fin` ; `exact`, `nombre`, `depart` |
| `gallica_recherche_document` | `ark` (exact), `texte` (texte) |
| `gallica_texte` | `ark`, `page`, `max_caracteres` |
| `gallica_alto` | `ark`, `page` |
| `ark_resoudre` | `ark`, `verifier`, `titre` (exact : repris dans la citation) |
| `piece_archiver` | `source`, `page` : la même vue archivée, quels que soient le nommage et la note |
| `wikidata_personne` | texte : `nom`, `prenom`, `ne_vers`, `lieu` ; `limite` |
| `wikidata_sparql` | `requete` (exacte : les littéraux SPARQL sont sensibles à la casse) |
| `geo_commune` | `nom` (texte) ; exacts : `code_postal`, `code_insee`, `departement` ; `limite` |
| `geo_historique` | `nom` (texte) ; exacts : `code_insee`, `departement` |
| `contexte_bibliographie` | texte : `sujet`, `lieu` ; exacts : `periode`, `echelle`, `services` ; `limite` (la personne, hors identité, ne distingue pas deux demandes sans lieu ni sujet) |
| `contexte_local` | texte : `lieu`, `echelles`, `themes` ; exact : `periode` (la personne, hors identité, ne distingue pas deux demandes sans lieu : à noter dans l'enquête de chaque individu) |
| `pistes_contexte` | comme `contexte_local` : texte : `lieu`, `echelles`, `themes` ; exact : `periode` (même limite pour la personne) |
| `archives_registres` | `service` (exact), `commune` (texte), `annee`, `annee_fin`, `type_acte` (exact), `page` |
| `archives_planche` | `source`, `de`, `a`, `pas`, `bandeau`, `largeur`, `gris`, `miniatures` (une planche plus fine ou recadrée est une autre demande) |

Hors identité : `personne` (id local de l'arbre, jamais envoyé) et `enquete`. Le résultat noté est `negatif`
quand l'outil ne renvoie aucun résultat (recherche négative, liste vide, aucune ligne SPARQL) et référence
l'entrée du journal de l'appel ; sinon `positif`. Un tableau sans entrée pour un outil budgété fait échouer
`tests/test_deja_fait_collecte.py`.

Hors « déjà fait » : les outils sans paramètre `enquete` (`diagnostic`, `gramps_*`, classe écriture). En
particulier `matchid_appariement_statut` renvoie l'état d'un traitement par lot en cours, qui change d'un appel
à l'autre : redemander le même job n'est pas refaire une demande.

À la reprise, `deja_fait` liste toutes ces demandes ; une source de piste (`{outil, parametres}`) dont la
demande est notée sort de `a_faire`, et un appel refusé faute de budget puis refait avec `enquete=<id>` sort du
reste à faire (clé recalculée depuis ses paramètres, y compris pour un refus consigné avant cette identité).

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
lecture (`registre.lectures`), le verdict et les tâches manuelles avec `enquete_noter`. Pour atteindre une
date dans un registre chronologique, `archives_sonder(…, enquete=<id>)` reprend le sondage là où il s'était
arrêté (même `date_cible` et `type_acte`) et propose la vue suivante.

L'identifiant d'enquête est une chaîne simple et stable : il peut être repris tel quel comme « enquête
d'origine » par d'autres fonctions (file de propositions).

## Mode autonome

Le chercheur travaille sans personne présente (#158) **seulement sur demande explicite** :
`/genealogiste:enquete <personne> --autonome [budget]` ou `/genealogiste:acte <personne> <acte> --autonome
[budget]` (la commande de campagne s'appuie sur le même mode). Sans `--autonome`, le mode interactif reste
inchangé : questions permises, `arbre_proposer` présenté en diff.

**Lancement et budget.** `enquete_ouvrir` et `enquete_noter` sont des outils conditionnels (#157) : fixer ou
modifier un `budget`, ou rouvrir une enquête (`statut: "ouverte"`), demande l'accord de l'utilisateur ; une
note ordinaire reste autorisée. Le budget d'une enquête autonome vient donc :

- des défauts `GENEALOGISTE_BUDGET_*`, fixés par l'utilisateur dans la configuration (aucune confirmation) ;
- ou d'une enquête ouverte au préalable par l'utilisateur (son id est repris) ;
- ou de l'argument `[budget]` de la commande, **seulement quand l'utilisateur est présent au lancement** :
  la commande le passe à `enquete_ouvrir(..., budget={...})`, l'accord est demandé avant toute collecte, puis
  plus aucune question. Un lancement sans surveillance (campagne, tâche planifiée) ne passe jamais `budget`.

Une boucle autonome ne fixe ni ne relève sa propre limite ([securite.md](securite.md)) : budget épuisé =
arrêt et compte rendu, jamais de relèvement ni de réouverture. L'agent `chercheur` reçoit une consigne qui
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
   transcription, archivage (`piece_archiver`), citation ; `enquete=<id>` sur chaque outil réseau de
   collecte (`recherche_multi`, `archives_*`, `archive_image`, `piece_archiver`, sources…) ;
3. aucune question : service protégé ou anti-robot, archives non numérisées, source sans API, capture
   nécessaire, homonymes non départagés deviennent des **tâches manuelles** (`enquete_noter(id, tache=…)`) ;
   `media_enregistrer`, qui demande une confirmation, n'est pas utilisé ;
4. arrêt sur refus `motif: "budget"`, sur `a_faire` vide sans autre source consultable (`prochaine_source`),
   ou sur preuve suffisante (statut « confirmé », `arbre_statut_preuve`) ;
5. conclusions **uniquement** par `propositions_deposer(..., enquete=<id>)`, jamais `arbre_proposer` ni
   `arbre_appliquer` ; une conclusion importante (fusion, filiation, passage à « confirmé ») est déposée
   « à vérifier » et le lanceur sollicite l'agent `verificateur` ;
6. pistes de contexte, en fin de recherche sur une personne et dans le budget :
   `pistes_contexte(personne=<id>, enquete=<id>)`, puis versement des pistes **à tester** par
   `enquete_noter(<id>, …)` avec les paramètres de `depot.enquete_noter` ; les pistes « contexte seul » ne sont
   pas versées et ne deviennent jamais des tâches ; rien n'est écrit dans l'arbre ni déposé dans la file
   ([contexte historique](contexte-historique.md#pistes_contexte)) ;
7. compte rendu à format fixe (ci-dessous).

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
  `requetes_autre_hote`, ou `illimite`), puis ` ; statut=ouverte|bloque`.

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

Budget : images=36 requetes_autre_hote=200 ; statut=ouverte
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
   comme arbre, puis `/genealogiste:enquete I1 personne --autonome budget images=5 requetes=20` ;
2. accepter la seule confirmation du lancement (`enquete_ouvrir` avec `budget`) ; ensuite, **aucune** question
   ni demande de permission ne doit apparaître jusqu'à la fin ;
3. contrôler : compte rendu au format ci-dessus, `propositions_lister()` montre les dépôts avec
   `enquete: <id>`, `arbre_historique` ne montre aucun nouveau commit, `enquete_reprendre(<id>)` donne le budget
   consommé, les tâches manuelles et `deja_fait` ;
4. relancer la même commande : l'enquête est reprise sans refaire `deja_fait`.
