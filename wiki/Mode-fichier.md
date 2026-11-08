# Un arbre local, versionné en Git

C’est le mode par défaut. Il ne nécessite ni Gramps Web, ni serveur Docker, ni compte de généalogie.
Le plugin conserve un GEDCOM 7 dans un dépôt Git privé local, séparé du code public.

## Ce que contient le dossier privé

| Élément | Rôle |
|---|---|
| `arbre.ged` | Arbre de travail : personnes, familles, faits et références |
| `.git/` | Historique des modifications et journaux versionnés |
| `journal.jsonl` | Recherches, y compris négatives |
| `medias/` | Pièces enregistrées localement |
| `.propositions/` | Propositions et jetons d’application |
| `exports/` | Exports produits par défaut, hors historique Git |

Les notes et certains médias peuvent être configurés ailleurs ; ces dossiers doivent eux aussi rester
privés et être inclus dans la stratégie de [sauvegarde](Sauvegardes.md).

## Partir de vos informations

Créer un dossier privé distinct, vérifier `arbre_info`, puis importer une **copie** d’un GEDCOM :

```text
/genealogiste:import /chemin/prive/copie-arbre.ged
```

Le mode d’import par défaut ajoute les objets en adaptant les identifiants. Le mode `remplacer` remplace
l’arbre : lire soigneusement le diff et le bilan avant accord. Ne répéter pas un import approuvé sans
examiner le risque de doublons. Un arbre importé reste à vérifier ; il ne vaut pas un ensemble de preuves.

## Modifier sans perdre la trace

Les commandes `ajoute`, `modifie` et `fusionne` présentent une proposition. `arbre_proposer` renvoie
un diff, des alertes et un jeton. `arbre_appliquer` l’utilise après accord ; le jeton expire après une heure,
ne sert qu’une fois et devient invalide si l’arbre a changé.

Une modification de l’arbre produit un commit Git avec sa justification. Pour annuler, demander une
proposition d’annulation et la relire ; ne pas employer un `git reset` manuel dans le dossier pendant
une session active. Les [opérations](../docs/operations.md) donnent le catalogue précis.
Certaines écritures auxiliaires (journal, notes, synchronisation) ont leur propre politique ; voir
les [approbations](Confidentialite.md).

## Règles de travail

- Utiliser un seul serveur actif sur un même dossier de données.
- Ne pas éditer `arbre.ged` à la main pendant qu’une session travaille dessus.
- Garder la numérotation et les identifiants du fichier réellement chargé ; un exemple `I1` n’est pas
  nécessairement la personne qui vous intéresse dans votre propre arbre.
- Si un dépôt distant est configuré, le garder privé. Le plugin refuse son propre dépôt public comme
  destination de l’arbre. Le masquage d’un export ne nettoie pas l’historique Git des données.

Pour passer à un arbre Gramps Web vide, suivre la [bascule contrôlée](../docs/gramps-web.md#bascule-fichier--gramps-web).
Il n’y a pas de synchronisation bidirectionnelle automatique entre deux arbres maîtres.
