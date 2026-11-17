---
description: Campagne de recherche sans surveillance sur les lacunes prioritaires (enquêtes autonomes, rapport daté, propositions en file)
argument-hint: <id|nom|arbre> [enquetes=N]
---
Campagne de recherche : **$ARGUMENTS**

Commande prévue pour tourner **sans personne devant l'écran** (`claude -p`, tâche planifiée : voir
`docs/campagne.md`). Elle ne pose **aucune question**, n'écrit jamais dans l'arbre et finit toujours par un
rapport daté. Recommandé pour toute exécution sans surveillance : `GENEALOGISTE_ECRITURE=interdite` dans
l'environnement du serveur (le serveur refuse alors toute écriture, quel que soit le mode de permission ;
`docs/securite.md`, « Modes d'exécution »).

Applique les skills `methodologie-gps` et `sources-francaises`.

Règles de la campagne :
- jamais `arbre_appliquer`, `pieces_appliquer`, `rapport_enregistrer`, `notes_*`, `media_enregistrer` ni
  aucun autre outil d'écriture : les conclusions vont dans la file (`propositions_deposer`) ;
- jamais de question à l'utilisateur : une décision qui en demanderait une est consignée sous « À valider » ou
  « À faire à la main » et la campagne continue ;
- un refus (`refus: "ecriture_interdite"`, permission refusée, `motif: "budget"`, anti-robot) n'est pas une
  erreur fatale : il est consigné sous « Bloqué » et la campagne passe à la suite ;
- ne jamais fixer ni relever un budget (`budget` d'`enquete_ouvrir` / `enquete_noter`) ni rouvrir une enquête
  bloquée : ce sont des écritures soumises à accord. Le budget de chaque enquête est celui des défauts
  `GENEALOGISTE_BUDGET_*` que l'humain a fixés dans l'environnement de la tâche ;
- aucune recherche externe sur une personne présumée vivante (`arbre_vivant`) ; dans le rapport, désigner les
  personnes par leur id d'arbre et ne rien recopier d'un vivant.

1. **Arguments** : cible = id, nom (`arbre_recherche`, premier résultat sans ambiguïté, sinon consigner
   « cible ambiguë » et s'arrêter à l'étape 6 avec un rapport court) ou `arbre`. `enquetes=N` : nombre
   maximal d'enquêtes de la campagne (défaut 3, maximum 6).
2. **Lacunes prioritaires** : `arbre` → `arbre_lacunes()` (classement de l'arbre, vivants exclus) ; id →
   `arbre_cercle(id, "famille")` puis `arbre_lacunes(pid)` pour le sujet et chaque proche non vivant. Retenir
   les N personnes qui ont le plus d'actions urgentes (priorité ≤ 1) ; annoncer le périmètre en une ligne.
3. **Enquêtes** : `enquete_reprendre()` liste les enquêtes ouvertes ou bloquées. Pour chaque personne retenue :
   - enquête ouverte qui la couvre → la reprendre (`enquete_reprendre(id)`) ;
   - enquête bloquée → ne pas la rouvrir ; la consigner sous « Bloqué » (relève du budget à faire par
     l'utilisateur) et passer à la suivante ;
   - sinon `enquete_ouvrir(sujet, [pid])` **sans** `budget`, et garder l'`id`.
4. **Recherche autonome** : pour chaque enquête, lancer l'agent **`chercheur`** (au plus 3 à la fois, dans le
   même message) avec une consigne qui commence exactement ainsi :

   ```text
   MODE AUTONOME
   enquete: <id>
   budget: <reste de enquete_reprendre(id).budget, ou « défauts GENEALOGISTE_BUDGET_* »>
   ```

   suivie de l'id de la personne, des lacunes retenues et des actions `a_faire` de l'enquête. Le chercheur ne
   pose aucune question, dépose ses conclusions par `propositions_deposer(..., enquete=<id>)` et rend un compte
   rendu à format fixe (`docs/enquetes.md`, « Compte rendu autonome ») : ligne `Enquête : <id>`, puis
   `## Trouvé`, `## Négatif`, `## Bloqué`, `## À valider` (id de file en tête de ligne), `## À faire à la main`
   (id de tâche en tête) et une ligne `Budget : cle=valeur … ; statut=ouverte|bloque`. Un compte rendu absent
   ou hors format est consigné sous « Bloqué » pour cette enquête.
   Seuls `recherche_multi`, `archives_naviguer` et `archive_image` (avec `enquete=<id>`) comptent dans le
   budget de l'enquête ; les autres outils sont bornés par le débit par hôte, le coupe-circuit anti-robot et le
   plafond journalier des archives.
5. **Vérification** : un sous-agent ne peut pas lancer d'agent ; c'est donc la campagne qui, pour chaque
   conclusion que le chercheur marque « à vérifier » sous `## À valider` (fait passant à « confirmé », nouvelle
   filiation, identité), lance l'agent **`verificateur`** sans lui transmettre les conclusions (au plus 3 par
   campagne). Son verdict est ajouté à l'élément dans le rapport ; au-delà, ou s'il échoue, consigner
   l'élément sous « À valider » avec la mention « vérification indépendante à faire ».
6. **Rapport** : agréger les comptes rendus en un seul document Markdown, puis
   `rapport_campagne_enregistrer(titre="Campagne <cible>", contenu, enquetes=[ids])` (fichier nouveau daté
   dans `<données>/rapports/campagnes/`, jamais d'écrasement). Contenu :
   - `# Campagne <cible> — <date>` puis une ligne de périmètre (personnes, enquêtes, N demandé) ;
   - les cinq sections `## Trouvé`, `## Négatif`, `## Bloqué`, `## À valider`, `## À faire à la main`,
     chaque élément préfixé de `[<id d'enquête>]` (en gardant l'id de file ou de tâche en tête) ; sous
     « À valider », le verdict du `verificateur` ou « vérification indépendante à faire » ;
   - `## Propositions en file` : id, titre et personnes de chaque dépôt (`propositions_lister()`) ;
   - `## Budget` : la ligne `Budget : …` de chaque enquête.
7. **Fin, sans question** : afficher le chemin du rapport, le nombre de propositions déposées et rappeler
   qu'elles attendent une revue : **`/genealogiste:valide`** (rien n'a été écrit dans l'arbre). Rappeler les
   enquêtes bloquées (relever leur budget se fait dans une session surveillée : `/genealogiste:enquete`).
