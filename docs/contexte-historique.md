# Contexte historique sourcé

Référence du jalon M7 : situer un individu dans son contexte historique sans inventer l'histoire. Conception :
`docs/superpowers/specs/2026-11-23-m7-contexte-design.md`.

## Méthode

Le contexte est traité avec la même rigueur que les faits de l'arbre (Genealogical Proof Standard, skill
`methodologie-gps`, § « Contexte historique »). Il situe un individu ; il n'explique ni ne prouve rien sur lui.

1. **Hiérarchie des sources de contexte** : source primaire contemporaine (presse, imprimé administratif,
   statistique d'époque) > historiographie savante évaluée par les pairs (article, thèse, monographie
   universitaire) > synthèse ou vulgarisation sourcée > tertiaire (encyclopédies, Wikipédia). Wikidata est un
   **index**, jamais une source.
2. **Critique externe et interne** : auteur, date, intention, échelle d'observation, sources de l'auteur.
3. **Échelle et portée** : une tendance nationale ou régionale ne prouve rien pour un individu ; chaque
   élément précise la population et le territoire concernés et son niveau de rattachement à l'individu.
   Aucun élément n'est « attesté pour l'individu » sans citation de l'arbre qui le concerne.
4. **Anachronisme** : contexte borné au lieu et à la période de vie, vocabulaire et découpages de l'époque,
   pays lu sur le lieu **à sa date** (homonymes de communes à l'étranger). Un élément hors période ou hors
   pays est écarté.
5. **Causalité** : le contexte n'explique pas une décision individuelle sans source individuelle. Sans elle,
   le rapprochement est une **hypothèse** au conditionnel, jamais un fait.
6. **Réfutabilité** : toute hypothèse contextuelle nomme la source qui la trancherait.
7. **Citation normée** : auteur, titre, publication, date, page, identifiant pérenne (DOI, ARK, HAL, PPN).
   ISO 690 par défaut ; *Evidence Explained* pour les sources généalogiques.
8. **Traçabilité** : chaque recherche de contexte est journalisée, y compris négative. Rien de personnel ne
   part vers un service externe : le contexte se cherche par lieu, période et métier.
9. **Rien trouvé** : sans source, la sortie est « contexte non documenté », pas un texte générique.

Cas témoins (données de test, sans fait historique ni personne vivante) : `mcp/tests/fixtures/contexte/`
(un `.ged` et un `.attendus.json` par cas : mineur du Pas-de-Calais parti aux États-Unis, laboureur d'Ancien
Régime, soldat de 1914-1918, lieu non documenté), chargés par la fixture pytest `app_contexte`. Chaque fichier
d'attendus donne la personne, ses bornes de vie, ses lieux avec pays, son métier, et ce qu'aucune sortie de
contexte ne doit contenir (causalités non sourcées, éléments hors période ou hors lieu, anachronismes, phrases
génériques).


## Pays du lieu

<!-- #283 -->

## Formats communs

<!-- #321 -->

Socle interne `mcp/src/genealogiste_mcp/contexte/`, partagé par tous les outils de contexte. Aucun outil MCP n'y
est défini.

### Référence (`modeles.Reference`)

Notice bibliographique **récupérée** par le plugin, jamais reconstituée de mémoire.

| Champ | Valeurs |
|---|---|
| `identifiant` | **obligatoire** : `{type, valeur}`, type `doi`, `ark`, `hal`, `handle`, `ppn`, `lccn`, `europeana` ou `url` ; valeur normalisée (DOI en minuscules, `ark:/…`, PPN nu…). Sa clé `type:valeur` (`doi:10.3406/…`) est la forme stockée et citée. Une référence sans identifiant est refusée. |
| `nature` | **obligatoire** : `primaire`, `secondaire_savante`, `secondaire`, `tertiaire`, `index` |
| `auteurs` | liste, telle que la notice la donne (`Nom, Prénom` ou collectivité) |
| `titre`, `publication`, `annee`, `pages` | `publication` : revue, éditeur, université ou titre du journal selon `type_document` |
| `type_document` | `article`, `chapitre`, `monographie`, `these`, `presse`, `autre` (défaut) |
| `volume`, `numero`, `lieu_edition`, `date` | compléments de citation ; `date` : date ISO d'un numéro de presse |
| `evaluation_par_les_pairs` | `oui`, `non`, `inconnu` (défaut) |
| `acces` | `libre`, `restreint`, ou vide (non renseigné par le service) |
| `lu` | `oui` (texte lu) ou `notice_seule` (défaut : signalé « non lu ») |
| `service`, `requete`, `consulte_le` | trace de la consultation : service, URL ou requête émise (sans nom de personne), date ISO |

La forme sérialisée (`to_dict`) ajoute `citation`, toujours recalculée.

### Élément de contexte (`modeles.ElementContexte`)

```json
{"enonce": "…", "type": "evenement|economie|demographie|institution|droit|geographie|culture",
 "portee": {"lieu": "…", "echelle": "commune|pays|departement|region|nation|international", "de": 1906, "a": 1906,
            "population": "…"},
 "source": {"citation": "…", "identifiant": "doi:…", "nature": "…", "consulte_le": "…", "localisation": "p. …"},
 "rattachement": {"personne": "I…", "niveau": "atteste|compatible|non_demontre", "justification": "…",
                  "citation_arbre": "…"}}
```

- `portee.de` est obligatoire (`a` vaut `de` par défaut) : un élément est toujours daté.
- `source.identifiant` est obligatoire et doit être un identifiant reconnu ; il désigne une référence du registre.
- `atteste` exige `personne` et `citation_arbre` (citation de l'arbre portant sur l'individu) : un outil ne
  l'attribue jamais seul. Sinon `compatible` (même lieu, même période, même groupe) ou `non_demontre`.
- Échelle « pays » : région naturelle ou bassin ; échelle « nation » : l'État.

### Registre des références consultées (`registre.RegistreReferences`)

Seule définition de « référence résolue » du jalon. Une référence n'y entre que si sa notice a été récupérée par
une requête du plugin : `enregistrer(reference, statut=…, reponse=…)` exige une réponse HTTP 2xx dont le corps
contient l'identifiant (ou, pour un identifiant `url`, l'URL égale à la requête), ainsi que `service`, `requete`
et `consulte_le` ; sinon rien n'est inscrit. `est_consultee(identifiant)` et `lire(identifiant)` acceptent un
identifiant, sa clé ou une forme libre (`10.…`, `https://doi.org/…`, `hal-…`). Un élément de contexte dont la
source n'est pas au registre est écarté.

Stockage : `<données>/references-consultees.jsonl` (une ligne par consultation, la dernière l'emporte), hors du
cache SQLite : `cache_purger` ne le vide jamais. Accessible dans le serveur par `App.registre_references`.

### Citation normée (`citation.citer`)

ISO 690 par défaut, *Evidence Explained* en option, choisi par `GENEALOGISTE_CONTEXTE_STYLE_CITATION`
(`iso690` | `evidence_explained`). Exemples ISO 690 :

- article : `DUPONT, Jean et MARTIN, Paul. Les mineurs de Courrières. Revue du Nord. 1975, vol. 57, n° 225,
  p. 45-67. [Consulté le 23 novembre 2026]. DOI 10.3406/rnord.1975.3360.`
- thèse : `MARTIN, Paul. Les houillères du Nord, 1880-1914. Thèse de doctorat. Lille : Université de Lille, 1998.
  [Consulté le 23 novembre 2026]. HAL tel-01234567.`
- numéro de presse : `Le Grand Écho du Nord de la France. 12 mars 1906, n° 71, p. 2. [Consulté le 23 novembre
  2026]. ark:/12148/bpt6k4659837. [Notice seule, non lu.]`

Une référence incomplète est citée avec ses champs connus, suivis de `[Non renseigné : auteur, année.]` : aucun
champ n'est complété de mémoire ni remplacé par « s. d. » ou « s. n. ».

### Contrôles de portée (`portee`)

Fonctions pures, sans réseau : `dans_la_periode(element, vie)` (recoupement des années, bornes incluses),
`dans_les_lieux(element, lieux)` (correspondance à l'échelle de l'élément ; un lieu de vie qui ne renseigne pas
cette échelle n'est jamais compatible), `mention(element)` (« tendance générale, ne prouve rien pour l'individu »
pour toute échelle supérieure à la commune) et `controler(element, vie, lieux)` qui renvoie
`{retenu, motifs, mention}`.

### Requêtes depuis l'arbre (`requete`)

`depuis_personne(arbre, personne)` construit une `RequeteContexte` (lieux de vie avec années de présence, période
de vie, métiers attestés) à partir des seuls faits **sourcés** et non réfutés de la personne et de ses unions ; le
pays et la région peuvent être fournis par une fonction (`pays_du_lieu`). Une requête ne contient jamais le nom,
le prénom, le surnom ni l'identifiant de la personne ; `residus_identite(texte, arbre, personne)` le vérifie sur
une URL émise. Construire une requête ne dispense pas de la garde des vivants : tout outil de contexte recevant
`personne` appelle `_garde` avant le premier appel externe.

## Services de contexte

<!-- #285 -->

## Outils

<!-- #286 à #290 -->

## Rédaction et contrôle

<!-- #291, #324 -->
