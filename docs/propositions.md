# File de propositions (validation différée)

Un jeton d'`arbre_proposer` vit une heure et devient inapplicable si l'arbre change : il convient à un
échange en direct. Pour une recherche sans surveillance (enquête de nuit, agent en arrière-plan), les
conclusions sont **déposées dans une file durable** et validées plus tard, une à une, avec
`/genealogiste:valide`.

## Cycle

| Étape | Outil | Effet |
|---|---|---|
| Dépôt | `propositions_deposer(operations, titre, justification, sources?, pieces?, personnes?, enquete?)` | Valide les opérations **à sec** sur l'arbre courant (règle `EXIGER_SOURCE` comprise) ; un dépôt invalide est refusé. Rien n'est écrit dans l'arbre. |
| Liste | `propositions_lister(statut?)` | Résumé des entrées (sans les opérations) ; par défaut `en_attente` et `a_revoir`, sinon un statut ou `tous`. |
| Reprise | `propositions_reprendre(id)` | Rejoue les opérations sur l'arbre **courant** : diff frais, nouvelles alertes de cohérence, jeton neuf (l'ancien jeton de l'entrée est annulé), avec justification, sources et pièces. |
| Application | `arbre_appliquer(jeton)` | Écriture habituelle, **après accord explicite**. L'entrée passe `appliquee` avec le `commit` (mode fichier) ou la `transaction` (mode gramps). |
| Abandon | `propositions_abandonner(id, motif?)` | Statut `abandonnee` ; l'entrée est conservée pour mémoire, son jeton annulé. |

Dépôt, liste, reprise et abandon ne modifient pas l'arbre : le hook les autorise sans confirmation.
`arbre_appliquer` reste la seule écriture et demande l'accord.

## Statuts

- `en_attente` : déposée, ou reprise avec succès et pas encore appliquée.
- `a_revoir` : la reprise a échoué ; `raison` donne le message (objet supprimé ou modifié, citation exigée,
  proposition devenue sans effet…). Une nouvelle reprise reste possible (après correction de l'arbre) ;
  sinon reformuler avec `arbre_proposer` ou abandonner.
- `appliquee` : écrite par `arbre_appliquer` à partir d'un jeton de reprise.
- `abandonnee` : écartée.

Le diff n'est jamais stocké : il est recalculé à chaque reprise, sur l'état de l'arbre du moment. Un
conflit entre la reprise et `arbre_appliquer` (modification intercalée) suit la règle des jetons : refus,
l'entrée reste `en_attente`, reprendre à nouveau.

## Stockage

Un fichier JSON lisible par entrée dans `<données>/.propositions/file/<id>.json` (exclu de Git comme les
jetons, exclu des sauvegardes de la même façon), écrit atomiquement sous verrou. Champs : `id`, `titre`,
`justification`, `operations`, `sources`, `pieces`, `personnes`, `enquete`, `depose`, `statut`, `raison`,
`jeton` (dernière reprise), `commit` ou `transaction`, `historique` (changements de statut datés). Le même
répertoire sert aux deux backends (`fichier`, `gramps`).

La file est locale : aucun outil ne l'envoie à l'extérieur. Elle contient les mêmes données que les
opérations proposées (noms compris) ; la protéger comme le répertoire de données.

## Jetons expirés

Les jetons expirés (plus d'une heure) sont purgés au démarrage et à chaque lecture de `pending()`
(`arbre_info.propositions_en_attente`) : ils n'y figurent plus. L'entrée de file correspondante, elle,
subsiste et se reprend.
