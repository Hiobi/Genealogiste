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

### Émigration

<!-- #284 -->

Parcours émigration / immigration : sources des deux côtés et fenêtre de départ tirée de l'arbre. Aucun outil
ni paramètre nouveau : `prochaine_source`, `cotes_a_consulter`, `arbre_fiche` et `arbre_lacunes` sont enrichis.

**Chaînes de sources** (`fr_sources._migration`). Chaque piste porte `versant` (`france` ou `etranger`) et, si
l'existence du fonds n'est pas vérifiée, un `avertissement` explicite.

| Fait et lieu | Versant français | Versant étranger (générique, sans cote) |
|---|---|---|
| `EMIG` en France, sans lieu ou pays inconnu | registre matricule (1 R, classe = année de naissance + 20, dès 1867), passeports et police des étrangers (4 M, avertissement), recensements avant et après le départ (6 M, dès 1836 ; une absence ne prouve pas l'émigration), transcriptions et état civil consulaire | listes de passagers, recensements, naturalisation, conscription du pays d'arrivée |
| `IMMI`, `NATU` en France | décret et dossier de naturalisation (Archives nationales, avertissement), police des étrangers (4 M, avertissement), recensements (6 M) | état civil et archives, passeports et autorisations de sortie du pays d'origine |
| `EMIG`, `IMMI`, `NATU`, `RESI` hors de France ; `RESI_ETRANGER` | aucune série d'AD : registre matricule, police et recensements « du département du dernier domicile en France », cote à identifier ; transcriptions consulaires | état civil et archives du lieu, puis passagers (`EMIG`, `IMMI`), recensements, naturalisation, conscription (sauf `NATU`), nommés avec le pays |

Pays inconnu : séries d'AD suffixées « si le lieu est en France », comme pour les autres faits. Le versant
étranger renvoie au wiki Services-archives et à `sources_catalogue(theme="emigration")`.

Provenance des affirmations :

| Affirmation | Provenance |
|---|---|
| Registre matricule en série R, sous-série 1 R, classes 1867 et suivantes ; classe = année de naissance + 20 ; adresses successives | déjà affirmé par le dépôt (`types_documents.py`, skill `sources-francaises`) |
| Recensements en 6 M, quinquennaux depuis 1836 | déjà affirmé par le dépôt |
| État civil consulaire au Service central d'état civil (Nantes) ; transcription sur les registres de la commune du dernier domicile | déjà affirmé par le dépôt (#283) |
| Passeports et police des étrangers en sous-série 4 M dans plusieurs services | répertoires de la sous-série 4 M « Police » des AD de la Somme (rubriques « Étrangers », « Passeports à l'étranger ») et d'Indre-et-Loire (« Police des étrangers ») consultés le 23 novembre 2026 ; classement variable : « à vérifier dans l'inventaire » et avertissement |
| Décrets de naturalisation aux Archives nationales, inventaire 1883-1948 partiellement indexé, numéro de dossier porté au décret | document « Devenir français : aide à la saisie » des Archives nationales (Girophares) consulté le 23 novembre 2026 ; cote du dossier non donnée |
| Fonds étrangers | aucune affirmation : intitulés génériques et avertissement |

**Fenêtre de départ** (`emigration.fenetre_depart`), dans `arbre_lacunes(id)` (`fenetre_depart`) et la fiche
(section « Fenêtre de départ »), seulement si un fait de la personne (ou de ses unions) est situé à l'étranger ou
est un fait de migration. Le pays de chaque fait vient de `pays_du_lieu` ; un fait non daté ou de pays inconnu
n'est jamais une borne (`faits_ecartes`).

```json
{"determinee": true,
 "debut": {"fait": "RESI", "date": "JUL 1906", "date_texte": "juillet 1906", "lieu": "Denain, Nord, France",
           "pays": {"code": "FR", "nom": "France", "provenance": "libelle"}, "uid": "…", "porteur": "I1",
           "statut": "hypothese", "statut_libelle": "hypothèse", "sources_independantes": 1,
           "citations": ["Registres de population de Denain (fictif), Registre de population 1906, f° 41 […]."],
           "source_de_la_borne": "fait de l'arbre"},
 "fin": {"fait": "EVEN", "date": "17 SEP 1917", "lieu": "Krebs, Pittsburg, Oklahoma, États-Unis", "…": "…"},
 "texte": "Départ de France entre juillet 1906 (…) et 17 septembre 1917 (…).",
 "pistes": ["next_source_hint(\"EMIG\", date et lieu du début) ; versant étranger avec pays_arrivee"],
 "typage_propose": [{"uid": "…", "operations_par_type": {"IMMI": ["ajouter_evenement", "supprimer_evenement"]}}],
 "avertissement": "Fenêtre tirée des seuls faits datés et situés de l'arbre : elle encadre le départ, …"}
```

- Début : dernier fait daté situé en France dont la date commence au plus tard avec celle du premier fait daté
  situé à l'étranger (fin). Une borne sans citation est dite « non sourcé » ; son statut de preuve est donné.
- Indéterminée (`determinee: false`, `motif`, `texte` « Fenêtre de départ indéterminée : … ») : aucun fait daté à
  l'étranger, ou aucun fait daté en France avant lui. Des faits en France après le premier fait à l'étranger sont
  listés (`faits_en_france_apres`, `remarque` : retour ou séjours multiples possibles).
- Fenêtre déterminée sans événement `EMIG` ni `IMMI` : `arbre_lacunes` ajoute une action « émigration non
  enregistrée » (priorité 2) avec les pistes.
- **Typage** : un événement générique (`EVEN`) situé à l'étranger reçoit `typage_propose` : pour chaque type
  plausible (`IMMI`, `NATU`, `RESI`, `CENS`, `MILI`), `ajouter_evenement` (même date, lieu, citations) puis
  `supprimer_evenement`. Le type se choisit d'après la source ; les opérations passent par `arbre_proposer` et
  `arbre_appliquer` après accord. Rien n'est appliqué automatiquement. Médias et intervenants éventuels sont à
  reporter (`a_reporter`).

Sites relevés (thème `emigration`, `docs/sites-tiers.md`) : guides de NARA (immigrants, naturalisation,
enregistrement militaire de 1917-1918, recensements) et recherche d'arrivées de la Statue of Liberty & Ellis
Island Foundation, en plus de Fichier Origine et du PRDH.

Limites : la fenêtre ne voit que l'arbre ; elle ne déduit aucune date d'un contexte ; un lieu de pays inconnu
(« Charleroi » seul) est écarté, à préciser ; seul le premier départ attesté est encadré.

## Rédaction et contrôle

<!-- #291, #324 -->
