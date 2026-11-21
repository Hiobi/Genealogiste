# Exporter et partager un arbre

Un export est une copie destinée à un autre usage. L’arbre de travail et son historique restent privés.
Les exports masquent les personnes présumées vivantes et les objets privés par défaut.

## Choisir le format

| Destination | Format demandé |
|---|---|
| GEDCOM récent | `gedcom7` |
| Logiciel demandant GEDCOM 5.5.1 | `gedcom551` |
| Gramps / Gramps Web | `gramps` : XML natif, préférable à son import GEDCOM 7 pour les détails pris en charge |
| Gramps Desktop avec les images | `gpkg` : XML et fichiers des médias dans une seule archive |
| GeneWeb 7 | `geneweb`, puis suivre le [guide d’import](../docs/geneweb.md) |
| Schéma ascendant/descendant | `mermaid_asc`, `mermaid_desc`, `svg_asc`, `svg_desc` |
| Fiche de recherche | `fiche` |

Dans Claude Code :

```text
/genealogiste:export gedcom7
/genealogiste:export gramps
/genealogiste:export gpkg
/genealogiste:export svg_asc I1 4
```

`I1` est à remplacer par un identifiant présent dans votre arbre. Les formats de schéma et de fiche
nécessitent une personne de départ ; `4` indique le nombre de générations dans cet exemple.
Les fichiers sont créés dans le dossier privé `exports/` par défaut ; leur chemin est renvoyé par l’outil.
Éviter un dossier synchronisé publiquement pour y produire un export de travail.

## Avant de diffuser

1. Conserver le masquage par défaut. Une sortie non masquée est réservée à une demande explicite pour
   un usage strictement privé.
2. Lire le bilan : vivants masqués, objets retirés, éventuels avertissements ou refus d’export.
3. Ouvrir le fichier et vérifier ce qu’il contient avant de le transmettre. Les protections ont un
   périmètre documenté ; une absence d’alerte n’est pas une garantie universelle de confidentialité.

Les sources ou médias partagés avec une personne masquée peuvent aussi être retirés chez les défunts.
Cette réduction est volontaire. Voir la [confidentialité](Confidentialite.md) et la
[description technique du masquage](../docs/securite.md).

## Réimporter ailleurs

Le fichier `gramps` est lu par Gramps 5.2, 6.0 et 6.1 ; demander la version XML 1.7.2 seulement pour
Gramps 6 (Gramps 5.2 la refuse), ou un fichier compressé si besoin. Pour un paquet `gpkg`, lire la liste
des médias manquants : ils ne sont pas dans l’archive. Voir le [guide Gramps Desktop](../docs/gramps.md).

Pour que Gramps Desktop retrouve directement les images du vault, exporter le `gramps` avec le dossier du vault tel que la machine
Desktop le voit (paramètre `chemin_base_medias`, jamais écrit par défaut ni dans un export public) : voir le
[chemin de base des médias](../docs/gramps.md#chemin-de-base-des-médias-280).

Faire le premier essai dans une base vide ou jetable. Un second import dans un arbre Gramps non vide
peut dupliquer les objets. Un export GEDCOM ne conserve pas forcément tous les détails d’un logiciel ;
les [extensions](../docs/gedcom-extensions.md) et les guides Gramps/GeneWeb expliquent les choix.
Ne pas utiliser des imports répétés pour simuler une synchronisation bidirectionnelle.

Dans l’autre sens, `/genealogiste:import` lit un `.gramps` ou un `.gpkg` exporté par Gramps Desktop
(Gramps 5.2 à 6.1) : diff et accord comme pour un GEDCOM, liste de ce que l’arbre ne reprend pas, médias
d’un paquet mis en attente dans le répertoire de données. Voir
l’[import depuis Gramps Desktop](../docs/gramps.md#import-depuis-gramps-desktop).
