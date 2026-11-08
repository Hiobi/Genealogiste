# Sauvegarder et restaurer

Git conserve un historique local ; il ne remplace pas une sauvegarde indépendante. Une panne, une
suppression ou la perte d’un disque peut toucher simultanément l’arbre et son historique.

## Ce qu’il faut sauvegarder

| Installation | Périmètre |
|---|---|
| Mode fichier | Dossier de données complet, y compris `.git`, arbre, journaux et médias |
| Notes ou médias déplacés | Tous les dossiers configurés séparément et leur contenu manuel |
| Gramps Web | Base et volumes Gramps, médias, comptes/configuration nécessaires et journaux du plugin |
| Toute installation | Secrets utiles à la restauration, conservés séparément et chiffrés |

Pour retrouver les chemins, vérifier votre configuration et `arbre_info`. Les détails des volumes et
de l’exploitation figurent dans le [guide de production](../docs/production.md).

## Avant une sauvegarde

Arrêter les écritures et les sessions pour obtenir un ensemble cohérent. Utiliser des copies chiffrées,
datées, avec une copie indépendante à accès restreint. Pour Gramps, suivre aussi la procédure de sauvegarde
correspondant à votre version du serveur ; un GEDCOM seul ne sauvegarde pas tous ses réglages et médias.

Les sauvegardes contiennent potentiellement des personnes vivantes, d’anciennes données et des jetons.
Ne pas les joindre à une issue et ne pas les envoyer dans le dépôt public.

## Vérifier une restauration

1. Restaurer dans un dossier ou une instance **isolée**, jamais en écrasant votre seule copie.
2. Retirer le dépôt Git distant et les identifiants d’API externes de l’instance de contrôle. Vérifier
   aussi que les chemins de notes/médias ne pointent pas sur les emplacements de production.
3. Lire l’arbre et comparer personnes, familles, sources, médias et historique Git aux valeurs attendues.
4. Vérifier sur une donnée fictive qu’une proposition, son refus, puis une application approuvée
   fonctionnent comme prévu ; contrôler un export masqué.
5. Arrêter l’instance d’essai avant toute reprise de l’exploitation habituelle.

## Pendant une mise à jour

Sauvegarder avant une migration, lire les notes de version et conserver les mêmes chemins privés.
Pour Docker/Portainer, préserver le nom du projet et les volumes ; `docker compose down -v` supprime
les volumes et n’est pas une procédure de mise à jour.
