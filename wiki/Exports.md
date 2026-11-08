# Exporter et partager un arbre

Un export est une copie destinée à un autre usage. L’arbre de travail et son historique restent privés.
Les exports masquent les personnes présumées vivantes et les objets privés par défaut.

## Choisir le format

| Destination | Format demandé |
|---|---|
| GEDCOM récent | `gedcom7` |
| Logiciel demandant GEDCOM 5.5.1 | `gedcom551` |
| Gramps / Gramps Web | `gramps` : XML natif, préférable à son import GEDCOM 7 pour les détails pris en charge |
| GeneWeb 7 | `geneweb`, puis suivre le [guide d’import](../docs/geneweb.md) |
| Schéma ascendant/descendant | `mermaid_asc`, `mermaid_desc`, `svg_asc`, `svg_desc` |
| Fiche de recherche | `fiche` |

Dans Claude Code :

```text
/genealogiste:export gedcom7
/genealogiste:export gramps
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

Faire le premier essai dans une base vide ou jetable. Un second import dans un arbre Gramps non vide
peut dupliquer les objets. Un export GEDCOM ne conserve pas forcément tous les détails d’un logiciel ;
les [extensions](../docs/gedcom-extensions.md) et les guides Gramps/GeneWeb expliquent les choix.
Ne pas utiliser des imports répétés pour simuler une synchronisation bidirectionnelle.
