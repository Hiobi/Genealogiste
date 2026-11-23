# Contexte historique sourcé

Référence du jalon M7 : situer un individu dans son contexte historique sans inventer l'histoire. Conception :
`docs/superpowers/specs/2026-11-23-m7-contexte-design.md`.

## Méthode

<!-- #292 -->

## Pays du lieu

<!-- #283 -->

Une seule fonction, `normalize.pays.pays_du_lieu(lieu)`, résout le pays d'un lieu ; toutes les pistes
l'appellent, et les outils de contexte du jalon la réutilisent pour construire leurs requêtes. Elle accepte un
libellé, un `Place` ou un dict `{nom, code_insee, pays, forme}` et renvoie :

| Clé | Valeur |
|---|---|
| `code` | ISO 3166-1 alpha-2 (`FR`, `BE`, `US`…), `""` si inconnu ou hors de la table |
| `nom` | nom français du pays (libellé de la hiérarchie si le pays est hors de la table), `""` si inconnu |
| `provenance` | `hierarchie`, `code_insee`, `libelle` ou `inconnu` |
| `france` | `true`, `false`, ou `null` si inconnu |
| `detail` | ce qui a décidé, en clair |

Ordre de résolution, le premier qui conclut l'emporte :

1. **Hiérarchie** : niveau de type pays (`Country`) de la hiérarchie Gramps, lu par le backend Gramps ; ou
   segment désigné comme pays (`Country`, `Pays`…) par le `FORM` du `PLAC` GEDCOM. Un pays absent de la table
   garde son nom, avec `code` vide et `france: false`.
2. **Code INSEE** : un code commune (`59220`, `2A004`, `97101`) vaut France ; un code pays du COG (`99xxx`)
   désigne un pays étranger.
3. **Libellé** : dernier segment comparé à une table fermée de noms de pays (français, anglais, langue locale,
   quelques formes historiques : Prusse, Empire allemand, Empire ottoman…) ; sinon un département français
   reconnu après le premier segment (`Fenain, Nord`, ancien nom compris : `Charente-Inférieure`), un numéro entre
   parenthèses (`Somain (59)`) ou un département d'outre-mer (`Guadeloupe`, `La Réunion`) vaut France.
4. **Inconnu** : rien ne conclut. Jamais présumé français.

Le nom de la commune ne décide jamais seul : `Charleroi` reste inconnu, `Charleroi, Nord` est en France,
`Charleroi, Hainaut, Belgique` en Belgique, `Charleroi, Washington, Pennsylvania, États-Unis` aux États-Unis.
Le cas courant d'un arbre français, saisi sans pays (`Fenain, Nord`), reste en France par le département.

### Aiguillage des pistes

| Pays | `prochaine_source`, `cotes_a_consulter`, fiche (« Prochaines sources ») | `archives_service(lieu=…)` | `communicabilite(…, lieu)` |
|---|---|---|---|
| France (DOM compris) | inchangé : cadre de classement des AD | service départemental | délais et mise en ligne chez le service |
| Autre pays | aucune série d'AD ; « État civil et archives du lieu » : source à identifier pour ce pays, renvoi au wiki [Services-archives](../wiki/Services-archives.md) ; pour un acte d'état civil, transcription éventuelle sur les registres de la commune du dernier domicile en France ou état civil consulaire (Service central d'état civil, Nantes), sans garantie d'existence ; sources nationales hors AD conservées (matchID, Mémoire des hommes, Gallica) | aucun service ; `renvoi` et `piste_francaise` | `communicable: null` ; `communicable_si_transcrit_en_france` ; aucun service ni courrier |
| Inconnu | séries d'AD suffixées « si le lieu est en France » (`condition`) ; `cotes_a_consulter` ajoute `pays_a_preciser` | erreur « préciser » avec `pays` | comme aujourd'hui, avec `pays` |

Chaque piste porte `pays` (`code`, `nom`, `provenance`) dès qu'un lieu est donné ; `cotes_a_consulter`,
`archives_service` et `communicabilite` renvoient le résultat complet. Sans lieu (filiation, fait manquant), la
sortie reste celle d'avant : aucune affirmation sur le pays. `liens_recherche` n'ajoute plus de lien d'AD pour un
lieu hors de France (`Delémont, Jura, Suisse`).

Limites : la table de pays est fermée (à compléter au besoin dans `normalize/pays.py`) ; un niveau
intermédiaire étranger seul (`Charleroi, Washington, Pennsylvania`, `Charleroi, Hainaut`) ne suffit pas et reste
inconnu ; un département homonyme sans pays (`Delémont, Jura`) est lu comme français ; le `FORM` de l'en-tête
GEDCOM n'est pas lu, seul celui du lieu.

## Formats communs

<!-- #321 -->

## Services de contexte

<!-- #285 -->

## Outils

<!-- #286 à #290 -->

## Rédaction et contrôle

<!-- #291, #324 -->
