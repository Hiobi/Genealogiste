---
description: Enquête complète sur un individu et ses proches en une commande (recherche, vérification, plan, propositions)
argument-hint: <id|nom> [personne|famille|etendu]
---
Enquête généalogique : **$ARGUMENTS**

Applique les skills `methodologie-gps` et `sources-francaises`.

0. **État d'enquête** (`docs/enquetes.md`) : `enquete_reprendre()` liste les enquêtes ouvertes. Si l'une
   porte sur ce sujet, `enquete_reprendre(id)` et repartir de `a_faire` (ne jamais relancer `deja_fait`) ;
   sinon `enquete_ouvrir(sujet, personnes)` et garder l'`id`.
1. **Cadrage** : identifier le sujet (`arbre_recherche` si un nom est donné), puis `arbre_cercle(id, cercle)`
   (défaut `famille`). Les personnes présumées vivantes sont exclues de toute recherche externe.
   Annoncer en une ligne le périmètre (n personnes) avant de lancer.
2. **Recherche en parallèle** : lancer un agent **`chercheur`** par personne du cercle (en commençant par
   celles qui ont le plus d'actions urgentes), dans le même message pour qu'ils travaillent en parallèle.
   Consigne à chacun : id d'enquête (`enquete=<id>` sur `recherche_multi`, `archives_naviguer`,
   `archive_image` ; pistes, lectures, verdicts et tâches manuelles par `enquete_noter`), id, lien avec le sujet, lacunes (`arbre_lacunes`), sources à interroger, rendre un
   dossier de pièces classées + opérations `arbre_proposer` suggérées (non appliquées). Au-delà de 6
   personnes, procéder par vagues et demander s'il faut continuer.
3. **Recoupement croisé** : confronter les dossiers entre eux — un acte trouvé pour un proche documente
   souvent le sujet (mariage d'un enfant = parents nommés ; témoins et parrains communs = même famille ;
   décès d'un parent = héritiers). Signaler les homonymes et contradictions (`arbre_comparer`, `arbre_coherence`).
4. **Vérification** : pour toute conclusion qui ferait passer un fait à « confirmé », une fusion ou une
   nouvelle filiation, lancer l'agent **`verificateur`** (sans lui transmettre les conclusions).
5. **Rendu** (concis) :
   - tableau par personne : faits nouveaux (statut, source), contradictions, homonymes écartés ;
   - recherches négatives (notées dans l'enquête, tracées au journal) ;
   - tâches manuelles en attente (`enquete_reprendre(id).taches_manuelles`) ;
   - plan de recherche priorisé et regroupé par service d'archives (cotes typiques) ;
   - une **proposition unique** `arbre_proposer` regroupant les ajouts sourcés (citations complètes,
     `consultation` précisée, témoins et parrains en `associations`), présentée en diff.
6. N'appliquer (`arbre_appliquer`) qu'après accord explicite de l'utilisateur ; proposer ensuite
   `/genealogiste:export geneweb` pour publier dans GeneWeb.
