---
description: Enquête complète sur un individu et ses proches en une commande (recherche, archives, vérification, plan, propositions) ; --autonome pour une enquête sans question, bornée par son budget
argument-hint: <id|nom> [personne|famille|etendu] [--autonome] [budget images=… requetes=…]
---
Enquête généalogique : **$ARGUMENTS**

Applique les skills `methodologie-gps` et `sources-francaises`.

**Mode** : interactif par défaut (questions permises). Si `$ARGUMENTS` contient `--autonome`, mode autonome
(`docs/enquetes.md`, section « Mode autonome ») : aucune question pendant l'enquête, arrêt sur budget,
conclusions déposées dans la file de propositions, compte rendu à format fixe.

0. **État d'enquête** (`docs/enquetes.md`) : `enquete_reprendre()` liste les enquêtes ouvertes. Si l'une
   porte sur ce sujet, `enquete_reprendre(id)` et repartir de `a_faire` (ne jamais relancer `deja_fait`) ;
   sinon `enquete_ouvrir(sujet, personnes)` et garder l'`id`. Budget (images lues, requêtes par
   hôte : il arrête une boucle, il ne plafonne pas le coût) : défauts `GENEALOGISTE_BUDGET_*` ; si
   l'utilisateur en indique un dans $ARGUMENTS (ex. « budget images=20 requetes=50 »), le passer à
   `enquete_ouvrir(..., budget={"images": 20, "requetes_par_hote": 50})` : l'accord est demandé au lancement, avant toute collecte, donc seulement si
   l'utilisateur est présent ; un lancement sans surveillance n'indique pas de budget (défauts de la
   configuration ou enquête ouverte au préalable par l'utilisateur). Chaque réponse de
   collecte donne `budget.reste`. Au refus `motif: "budget"` (enquête `bloque`) : s'arrêter proprement, rendre
   le `compte_rendu` partiel ; en mode interactif, demander à l'utilisateur s'il relève le budget
   (`enquete_noter(id, budget={...})`) avant `enquete_reprendre(id)` ; en mode autonome, ne rien relever.
   Mode gramps : `enquete_ouvrir(..., signets=True)` propose (jamais n'applique) de mettre en signet de la base Gramps les
   personnes de l'enquête ; à la clôture (`enquete_noter(id, statut="close")`), `signets_a_retirer` signale ceux que le plugin a
   posés, à retirer par `gramps_reglages(signets={"enquete": id, "action": "retirer"})` après accord (docs/enquetes.md).
1. **Cadrage** : identifier le sujet (`arbre_recherche` si un nom est donné), puis `arbre_cercle(id, cercle)`
   (défaut `famille`). Les personnes présumées vivantes sont exclues de toute recherche externe.
   Annoncer en une ligne le périmètre (n personnes) avant de lancer.
2. **Recherche en parallèle** : lancer un agent **`chercheur`** par personne du cercle (en commençant par
   celles qui ont le plus d'actions urgentes), dans le même message pour qu'ils travaillent en parallèle.
   Consigne à chacun : id d'enquête (`enquete=<id>` sur chaque outil réseau de collecte :
   `recherche_multi`, `archives_registres`, `archives_naviguer`, `archives_planche`, `archive_image`,
   `piece_archiver`, sources… ; pistes, lectures, verdicts et tâches manuelles par `enquete_noter`), id, lien avec le
   sujet, lacunes (`arbre_lacunes`), sources à interroger et **parcours d'archives** pour chaque fait à établir :
   service et couverture (`archives_service`), registre (`archives_registres` pour AD59 et les services Mnesys du référentiel, `ark_resoudre` pour un
   ARK déjà connu), sondage (`archives_naviguer`, `archives_planche`, `archives_sonder`), lecture (`archive_image`), transcription,
   archivage (`piece_archiver`), citation. En mode interactif : rendre un dossier de pièces classées +
   opérations `arbre_proposer` suggérées (non appliquées) ; au-delà de 6 personnes, procéder par vagues et
   demander s'il faut continuer. En mode autonome : la consigne commence par
   ```text
   MODE AUTONOME
   enquete: <id>
   budget: <budget fixé, ou « défauts »>
   ```
   puis la personne et la question ; les vagues s'enchaînent sans question jusqu'au refus `motif: "budget"`.
3. **Recoupement croisé** : confronter les dossiers entre eux — un acte trouvé pour un proche documente
   souvent le sujet (mariage d'un enfant = parents nommés ; témoins et parrains communs = même famille ;
   décès d'un parent = héritiers). Signaler les homonymes et contradictions (`arbre_comparer`, `arbre_coherence`).
4. **Vérification** : pour toute conclusion qui ferait passer un fait à « confirmé », une fusion ou une
   nouvelle filiation (en mode autonome : chaque proposition déposée « à vérifier »), lancer l'agent
   **`verificateur`** (sans lui transmettre les conclusions). Son verdict accompagne l'id de la proposition.
5. **Rendu** :
   - en mode autonome : un seul compte rendu à format fixe (`docs/enquetes.md`, « Compte rendu autonome »)
     fusionnant ceux des chercheurs : `## Trouvé`, `## Négatif`, `## Bloqué`, `## À valider` (ids de la file,
     verdict du vérificateur), `## À faire à la main` (`enquete_reprendre(id).taches_manuelles`), puis
     `Budget : …` (reste, d'après `enquete_reprendre(id).budget`). Rien n'est appliqué : la validation se fait
     plus tard avec `/genealogiste:valide`.
   - en mode interactif (concis) :
     - tableau par personne : faits nouveaux (statut, source), contradictions, homonymes écartés ;
     - recherches négatives (notées dans l'enquête, tracées au journal) ;
     - tâches manuelles en attente (`enquete_reprendre(id).taches_manuelles`) ;
     - plan de recherche priorisé et regroupé par service d'archives (cotes typiques) ;
     - pistes de contexte rendues par les chercheurs (`pistes_contexte`) : pistes à tester proposées au
       versement dans l'enquête (`enquete_noter`, après accord), pistes « contexte seul » présentées comme
       telles, jamais comme des tâches ; détail par `/genealogiste:contexte <id>` ;
     - une **proposition unique** `arbre_proposer` regroupant les ajouts sourcés (citations complètes,
       `consultation` précisée, témoins et parrains en `associations`), présentée en diff.
       Si la validation est différée, la déposer avec `propositions_deposer(..., enquete=<id>)` (file durable,
       au lieu d'un jeton d'une heure) : l'enquête d'origine reste liée.
   - **tâches de Gramps Web** (mode interactif, backend gramps, `GENEALOGISTE_GRAMPS_TACHES=true`, sur demande) :
     `enquete_reprendre(id, taches=true)` → `taches_a_proposer` (pistes et tâches manuelles ouvertes sans tâche) ;
     `arbre_proposer` (diff, accord), puis mémoriser chaque lien `enquete_noter(id, tache|piste={id,
     tache_gramps})`. Les écarts (`taches_gramps.ecarts` : tâche close dans Gramps Web, élément ouvert, ou
     l'inverse) sont montrés à l'utilisateur, qui choisit le sens (`vers_gramps` par `arbre_proposer`,
     `vers_enquete` par `enquete_noter`) ; jamais en mode autonome.
6. N'appliquer (`arbre_appliquer`) qu'après accord explicite de l'utilisateur, jamais en mode autonome ;
   proposer ensuite `/genealogiste:export geneweb` pour publier dans GeneWeb.
