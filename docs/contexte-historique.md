# Contexte historique sourcé

Référence du jalon M7 : situer un individu dans son contexte historique sans inventer l'histoire. Conception :
`docs/superpowers/specs/2026-11-23-m7-contexte-design.md`.

## Parcours d'usage

<!-- #325 -->

De la commande au récit vérifié. Chaque étape affiche ce que rend un outil, tel quel ; rien n'est affirmé de
mémoire, et un élément sans source n'est pas affiché.

| Étape | Commande ou agent | Outils | Ce qui en sort |
|---|---|---|---|
| 1. Situer | `/genealogiste:contexte <personne \| lieu> [--periode] [--echelles] [--themes]` | `contexte_local`, puis `pistes_contexte` | éléments par échelle (énoncé entre guillemets, citation de la source, niveau de rattachement, mention de tendance générale au-delà de la commune) ; « contexte non documenté » le cas échéant ; services en échec ou écartés, tâches manuelles ; pistes (hypothèse, fondements, test, statut). Aucune écriture |
| 2. Approfondir | demande libre, ou agent `chercheur` | `contexte_bibliographie`, `presse_recherche`, `lieu_historique` | références citées et inscrites au registre des références consultées ; niveaux « inconnu » jamais complétés de mémoire |
| 3. Tester | `/genealogiste:enquete`, agent `chercheur` | `pistes_contexte`, `enquete_noter` | pistes à tester versées à l'enquête (proposé à l'utilisateur ; fait par le `chercheur` en mode autonome, dans le budget) ; une piste `contexte_seul` reste une hypothèse non démontrée, jamais une tâche ni une proposition (verrou du code) |
| 4. Rédiger | `/genealogiste:recit`, `/genealogiste:billet`, agent `redacteur` | `contexte_local`, `pistes_contexte` | texte à section « Contexte » séparée, une phrase par élément, citation recopiée ; section absente si rien n'est sourcé |
| 5. Contrôler | la commande, l'agent `verificateur` | `contexte_verifier` | rapport `conforme` ; `conforme: false` bloque un billet de Gramps Web (par le code) ; conforme ne veut pas dire vrai : relire chaque phrase contre sa source |

Les sections suivantes sont la référence : « Méthode » (règles), « Outils » (signatures, sorties, limites),
« Rédaction et contrôle » (format du texte, `contexte_verifier`). Configuration : « Services de contexte »
(`GENEALOGISTE_CONTEXTE_SERVICES`, clés, `GENEALOGISTE_CROSSREF_MAILTO`) et `GENEALOGISTE_CONTEXTE_STYLE_CITATION`.
Exemple de sortie sur le cas témoin du mineur : « pistes_contexte » (pistes) et « Rédaction » (texte conforme).

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

Référentiel `mcp/src/genealogiste_mcp/referentiels/sources_contexte.json`, chargé et validé par
`contexte/services.py` (calqué sur `sites_tiers.py`). Il recense les services publics de contexte historique
(historiographie, bibliothèques, presse, cartes, statistiques), distincts des services d'archives
(`archives_fr.json`, [archives.md](archives.md)) et des sites tiers ([sites-tiers.md](sites-tiers.md)). Ce
contenu tient lieu du `docs/sources-contexte.md` annoncé par l'issue #285.

### Format d'une entrée

| Champ | Valeurs |
|---|---|
| `code` | identifiant en majuscules (`HAL`, `EUROPEANA`…) |
| `nom`, `usage` | libellé ; ce que le service apporte au contexte |
| `mode` | `api` : interrogeable par les outils de contexte s'il est activé ; `lien_seulement` : jamais interrogé, lien à ouvrir par l'utilisateur |
| `protocole` | `rest`, `sru`, `oai-pmh`, `sparql`, `solr`, `wmts` ; `aucun` (pas d'API qualifiée) |
| `url_api`, `site` | point d'accès machine (https) ; page à ouvrir dans le navigateur pour un service en lien seulement |
| `url_sonde` | facultatif : requête minimale du sondage (`verb=Identify`, `operation=explain`, `GetCapabilities`…), sur l'hôte du point d'accès, sans donnée personnelle |
| `cle`, `variable_cle` | `aucune`, `facultative`, `requise` ; variable `GENEALOGISTE_CLE_*` qui la porte |
| `nature` | nature par défaut des références issues du service, alignée sur `Reference.nature` : `primaire`, `secondaire_savante`, `secondaire`, `tertiaire`, `index` |
| `couverture` | `{zone: [FR, EU, US, INT], periode?: {de, a}}` ; période seulement quand elle est relevée |
| `documentation`, `cgu`, `quota` | vides tant qu'ils ne sont pas relevés (à qualifier) : aucune valeur de mémoire |
| `protection` | `aucune`, `cloudflare`, `captcha`, `connexion`, `a_qualifier` |
| `site_repond_le`, `releve` | dernière réponse obtenue par un client automatisé ; résultats datés des sondages |
| `verifie_le`, `origine` | contrôle humain (vide sans lui) ; provenance de l'entrée |

Règles vérifiées par `validate()` (`tests/test_sources_contexte.py`, `make verifier-archives`) : un service `api`
a une `url_api` https, un protocole d'API et aucune protection relevée (sinon `lien_seulement`, sans
contournement) ; une clé facultative ou requise nomme sa variable ; dates ISO ; valeurs dans les listes fermées.

### Services au 2026-11-23

Relevé `curl` du 2026-11-21 (issue #285) et sondage du 2026-11-23 (une requête GET par service, sans clé ni
paramètre personnel). La nature est un classement par défaut du plugin d'après l'usage du service, que
l'analyseur précise notice par notice.

| Code | Service | Protocole | Clé | Nature | Couverture | Statut | Relevés |
|---|---|---|---|---|---|---|---|
| `HAL` | HAL (archive ouverte, API de recherche) | solr | aucune | secondaire_savante | FR | actif par défaut | 2026-11-21 : 200 JSON ; 2026-11-23 : 200 |
| `ISIDORE` | Isidore (Huma-Num) | rest | aucune | index | FR | actif par défaut | 2026-11-21 : 200 JSON ; 2026-11-23 : 200 |
| `PERSEE` | Persée (OAI-PMH) | oai-pmh | aucune | secondaire_savante | FR | actif par défaut | 2026-11-21 : OAI 200, SPARQL sans réponse (45 s, non déclaré) ; 2026-11-23 : 200 |
| `OPENEDITION` | OpenEdition (OAI-PMH) | oai-pmh | aucune | secondaire_savante | FR | actif par défaut | 2026-11-21 : 200 ; 2026-11-23 : 200 ; API de recherche à qualifier |
| `SUDOC` | Sudoc (SRU) | sru | aucune | index | FR | actif par défaut | 2026-11-21 : 200 XML ; 2026-11-23 : 200 |
| `IDREF` | IdRef (Solr) | solr | aucune | index | FR | actif par défaut | 2026-11-21 : 200 JSON ; 2026-11-23 : 200 |
| `THESES-FR` | theses.fr (API) | rest | aucune | secondaire_savante | FR | actif par défaut | 2026-11-21 : 200 JSON ; 2026-11-23 : 200 |
| `BNF-CATALOGUE` | Catalogue général de la BnF (SRU) | sru | aucune | index | FR | actif par défaut | 2026-11-21 : 200 XML ; 2026-11-23 : 200 (6,8 s) |
| `DATA-BNF` | data.bnf.fr (SPARQL) | sparql | aucune | index | FR | actif par défaut | 2026-11-21 : 200 JSON ; 2026-11-23 : 302 sans paramètre |
| `OPENALEX` | OpenAlex (API works) | rest | facultative | index | INT | actif par défaut | 2026-11-21 : 200 JSON (sans clé : budget quotidien partagé par adresse IP) ; 2026-11-23 : 200 |
| `CROSSREF` | Crossref (API works) | rest | aucune (`mailto` facultatif) | index | INT | actif par défaut | 2026-11-21 : 200 JSON ; 2026-11-23 : 200 |
| `EUROPEANA` | Europeana (Search API) | rest | requise | primaire | EU | clé requise, à activer | 2026-11-21 : 200 avec la clé de démonstration (non embarquée) ; 2026-11-23 : 400 sans clé ; 2026-11-24 : la documentation d'Europeana ne publie plus de clé de démonstration, elle n'est pas utilisée ; [clé personnelle](#clé-personnelle-europeana) |
| `NAKALA` | Nakala (Huma-Num) | rest | aucune | index | FR | actif par défaut | 2026-11-21 : 200 JSON ; 2026-11-23 : 200 |
| `WIKIPEDIA` | Wikipédia en français (REST) | rest | aucune | **tertiaire** | FR | actif par défaut | 2026-11-21 : 200 ; 2026-11-23 : 301 sans paramètre ; sert seulement à remonter aux références |
| `WIKIDATA` | Wikidata Query Service (SPARQL) | sparql | aucune | **index** | INT | actif par défaut | 2026-11-21 : 200 simple, délai dépassé en requête géographique, 429 ensuite ; 2026-11-23 : 200 ; jamais source |
| `INSEE-MELODI` | INSEE Melodi | rest | aucune | primaire | FR, 1968-2023 | actif par défaut | 2026-11-21 : 200 (163 jeux) ; 2026-11-23 : 200 ; `DS_POPULATIONS_HISTORIQUES` 1968-2023 seulement |
| `IGN-GEOPLATEFORME` | Géoplateforme IGN (WMTS) | wmts | aucune | primaire | FR | actif par défaut | 2026-11-21 : 200 ; 2026-11-23 : 200 ; couches Cassini, état-major, SCAN50 1950, orthophotos 1950-1965 |
| `CULTURE-DATA` | culture.data.gouv.fr (Explore v2.1) | rest | aucune | secondaire | FR | actif par défaut | 2026-11-21 : 200 ; 2026-11-23 : 200 ; jeux de données à identifier |
| `GALLICA` | Gallica (SRU) | sru | aucune | primaire | FR | lien seulement (sauf `presse_recherche`, qui l'interroge par le client Gallica existant, soumis au coupe-circuit) | 2026-11-21 : 403 Cloudflare ; 2026-11-23 : 403 (voir #150) |
| `CHRONICLING-AMERICA` | Chronicling America (Library of Congress) | rest | aucune | primaire | US | lien seulement | 2026-11-21 : 403 Cloudflare ; 2026-11-23 : 403 |
| `NARA` | NARA Catalog (API v2) | rest | requise | primaire | US | lien seulement | 2026-11-21 : non qualifié ; 2026-11-23 : 200 à la racine de l'API, sans clé |
| `APE` | Archives Portal Europe | aucun | requise | primaire | EU | lien seulement | 2026-11-21 : point d'accès en 404, à qualifier ; 2026-11-23 : 403 sur la page d'accueil (serveur Cloudflare) |
| `FRANCEARCHIVES` | FranceArchives | aucun | aucune | index | FR | lien seulement | 2026-11-21 : redirection JavaScript, pas d'API qualifiée ; 2026-11-23 : 200 |
| `CASSINI-EHESS` | Des villages de Cassini aux communes d'aujourd'hui (EHESS) | aucun | aucune | secondaire_savante | FR, 1793-1999 | lien seulement | sans réponse (30 s) les deux fois ; accès machine à qualifier (#322) |
| `RETRONEWS` | Retronews | aucun | aucune | primaire | FR | lien seulement | 2026-11-21 et 2026-11-23 : 200 ; pas d'API publique connue |

Restent à relever avant les analyseurs (#286 à #289, réponses enregistrées #323) : conditions d'utilisation,
quotas et documentation de chaque service. Un service passe de `lien_seulement` à `api` seulement avec une réponse
réelle enregistrée.

### Configuration

Dans `<données>/.env` (par défaut `~/.local/share/genealogiste/.env`, hors du dépôt et de toute synchronisation) :

| Variable | Effet |
|---|---|
| `GENEALOGISTE_CONTEXTE_SERVICES` | services activés, codes séparés par des virgules. Absente ou vide : services `api` sans clé requise ni protection ; `aucun` : aucun ; `defaut` ajoute les services par défaut (`defaut,EUROPEANA`). Code inconnu : refus au démarrage. |
| `GENEALOGISTE_CLE_EUROPEANA`, `GENEALOGISTE_CLE_OPENALEX`, `GENEALOGISTE_CLE_NARA`, `GENEALOGISTE_CLE_APE` | clés d'API personnelles. Europeana exige la sienne ([comment l'obtenir](#clé-personnelle-europeana) ; aucune clé de démonstration n'est embarquée ni utilisée) ; OpenAlex fonctionne sans ; NARA et APE restent en lien seulement tant que leur API n'est pas qualifiée. |
| `GENEALOGISTE_CROSSREF_MAILTO` | **vide par défaut**. Une adresse courriel est une donnée personnelle : elle n'est envoyée à Crossref que si l'utilisateur la renseigne. |

Plafond journalier et intervalle par hôte : `GENEALOGISTE_PLAFONDS_JOUR` et `GENEALOGISTE_DEBITS` (hôte=valeur),
sinon `GENEALOGISTE_PLAFOND_JOUR_DEFAUT` et `GENEALOGISTE_DEBIT_DEFAUT`.

### Clé personnelle Europeana

Europeana n'est interrogeable qu'avec une clé d'API **personnelle** : chaque utilisateur du plugin demande la
sienne. Le plugin n'en fournit aucune et n'utilise aucune clé partagée ou de démonstration.

**État au 2026-11-24 : la clé n'a pas encore d'effet sur `presse_recherche`.** L'analyseur Europeana n'est pas
livré, faute de réponse réelle de l'API enregistrée (règle de #323, suivi dans #343). Avec une clé et le service
activé, `presse_recherche` rend Europeana en `sans_analyseur`, n'émet aucune requête vers l'API et renvoie au lien
de consultation du site public. Configurer la clé dès maintenant prépare l'installation : quand l'analyseur sera
livré, elle permettra à `presse_recherche` de chercher dans Europeana (presse et patrimoine européens), notamment
quand Gallica est bloqué.

**Obtenir la clé** (démarche décrite par la page « Accessing the APIs » d'Europeana, lue le 2026-11-24) :

1. Avoir un compte Europeana et s'y connecter sur le site europeana.eu (depuis le 28 mai 2025, un compte est
   nécessaire pour accéder aux API).
2. Ouvrir le menu en haut à droite, à côté du pseudonyme, puis « Manage API keys ». Le portail des API
   d'Europeana renvoie pour cela à la page <https://www.europeana.eu/account/api-keys>.
3. Dans la section « Personal API key », cocher « I confirm that I have read and accept the API key terms of
   use » après les avoir lues.
4. Cliquer sur « Request a Personal API key » : la clé s'affiche dans cette section et est utilisable aussitôt.
   Elle reste consultable au même endroit.

Ce que disent les pages lues :

- **Gratuité** : « Europeana gives access to all of its APIs free of charge » (FAQ).
- **Une seule clé personnelle active par compte.**
- **Limites** : les limites d'usage des clés personnelles ont été progressivement réduites jusqu'en avril 2026 ;
  les pages lues ne donnent aucun chiffre, ce document n'en donne donc pas. Les clés de projet (limites plus
  hautes, sur demande motivée) visent les services, pas l'usage personnel du plugin.
- **Usage raisonnable** : nombre raisonnable de requêtes concurrentes, attente entre les appels ; en cas d'abus,
  la clé peut être limitée, suspendue ou révoquée (« Fair use policy & guidelines »). Le débit et le plafond
  journalier du plugin s'appliquent à `api.europeana.eu` comme à tout hôte.
- **Clé confidentielle** : Europeana demande de ne pas la partager avec des tiers ni de l'exposer dans du code
  ou une interface. Elle est personnelle : ne pas la prêter, ne pas la publier, ne pas la committer.

Non lus, donc non décrits ici : le texte des conditions d'usage de la clé (« API key terms of use ») et le
parcours de création du compte ; les lire sur le site d'Europeana avant d'accepter.

**Où la mettre.** Deux variables : la clé, et l'activation du service (Europeana n'est pas actif par défaut).

```
GENEALOGISTE_CLE_EUROPEANA=<votre clé personnelle>
GENEALOGISTE_CONTEXTE_SERVICES=defaut,EUROPEANA
```

- **Claude Code (plugin, serveur stdio)** : dans `<données>/.env` (par défaut
  `~/.local/share/genealogiste/.env`, droits `600`), ou exportées dans le terminal qui lance Claude Code ; puis
  redémarrer le serveur MCP.
- **Conteneur Docker HTTP (`docker-compose.yml`)** : dans le fichier privé transmis au conteneur par `env_file`
  (`serveur.env` du guide [Docker et Portainer](../wiki/Docker-et-Portainer.md)), puis recréer le conteneur.
- **Stack Portainer (`docker-compose.portainer.yml`)** : la composition ne relaie pas ces variables ; les
  écrire dans le fichier `.env` à la racine du volume de données (`/data/.env` dans le conteneur), puis
  redémarrer le conteneur.

**Sans clé** : aucune erreur et aucune requête. Le service est écarté avec un motif qui nomme la variable et
rappelle la démarche ; la presse repose sur Gallica et sur les liens de consultation (tâche manuelle).

**Vérifier** : `/genealogiste:diagnostic` (contrôle `services_contexte`) et `sources_catalogue(type="contexte")`
disent si la clé est « définie » ou « absente », jamais sa valeur. La clé n'est ni journalisée, ni écrite, ni
renvoyée par un outil (`services.masquer_cles`).

**Pour l'analyseur à venir (#343), sans code ici.** La même page indique que l'en-tête `X-Api-Key` est l'option
préférée et que le paramètre d'URL `wskey` est déprécié (une clé dans une URL fuit quand le lien est partagé).
L'analyseur devra envoyer la clé en en-tête, pour qu'elle ne figure dans aucune URL, donc ni au journal, ni dans
la clé de cache, ni dans un manifeste ; à vérifier alors : le traitement des en-têtes par le client HTTP commun.
La réponse réelle exigée par #323 devra être enregistrée avec une clé personnelle, jamais écrite dans le dépôt.

Pages d'Europeana lues le 2026-11-24 (base de connaissances `europeana.atlassian.net`) :

- [Accessing the APIs](https://europeana.atlassian.net/wiki/spaces/EF/pages/2462351393/Accessing+the+APIs)
  (version du 2026-02-06) : niveaux d'accès, démarche, confidentialité, `X-Api-Key` et `wskey` ;
- [Search API Documentation](https://europeana.atlassian.net/wiki/spaces/EF/pages/2385739812/Search+API+Documentation)
  (version du 2026-02-11) : les exemples utilisent une clé à remplacer, aucune clé de démonstration ;
- [API FAQ](https://europeana.atlassian.net/wiki/spaces/EF/pages/2360508417/Europeana+API+FAQ)
  (version du 2026-02-11) : gratuité ;
- [Fair use policy & guidelines](https://europeana.atlassian.net/wiki/spaces/EF/pages/2704146433)
  (version du 2024-09-05) : usage raisonnable.

Les pages `pro.europeana.eu` (dont « Get your API Key here ») répondaient 403 ce jour-là et n'ont pas été lues.
**Clé de démonstration** : le relevé du 2026-11-21 notait une réponse 200 avec une clé de démonstration ; le
2026-11-24, aucune des pages ci-dessus ne publie une telle clé (les exemples demandent une clé personnelle). Elle
n'est ni embarquée ni utilisée, y compris pour enregistrer les réponses de test.

### Interrogeabilité : aucune requête sans service utilisable

Les outils de contexte appellent `services.refus(code, config)` avant tout appel réseau ; une réponse non nulle est
rendue telle quelle (`requetes_emises: 0`, motif, consigne « contexte non documenté par ce service ») et rien
n'est émis. Motifs, dans l'ordre : service inconnu ; `lien_seulement` (avec le lien) ; protection relevée ;
service désactivé (`GENEALOGISTE_CONTEXTE_SERVICES`) ; clé requise absente (la variable est nommée, jamais une
valeur) ; mode hors ligne. API interne :

| Fonction | Rôle |
|---|---|
| `etat(code, config) -> EtatService` | `interrogeable`, `motif`, `actif`, `mode`, `cle` (`sans_objet` / `presente` / `absente`), `variable_cle` |
| `refus(code, config) -> dict \| None` | None si interrogeable, sinon la réponse à rendre sans requête |
| `cle(code, config) -> str` | valeur de la clé, pour l'appel seulement |
| `mailto(config) -> str` | adresse Crossref, vide sauf choix de l'utilisateur |
| `masquer_cles(texte, config) -> str` | remplace clés et `mailto` par `***` dans une URL ou un message avant journal, cache de résultat ou erreur |
| `url_autorisee(code, url) -> bool` | vrai seulement pour une URL https vers un hôte déclaré du service |
| `validate()`, `filtrer(nature, protocole, mode)`, `resume(s, config)`, `description(config)` | format, filtres, entrée du catalogue, synthèse du diagnostic |

Clés et `mailto` ne sont jamais journalisés, écrits dans le coffre (notes), les exports ou le répertoire de
données, ni renvoyés par un outil : `Config` les exclut de sa représentation, le catalogue et le diagnostic
n'indiquent que « définie » ou « absente » (test `test_cles_jamais_renvoyees_journalisees_ni_ecrites`).

### Réseau, catalogue, diagnostic, sondage

- **Politique d'accès** : chaque hôte d'un `url_api` est déclaré dans la politique d'accès (catégorie
  `contexte`, intervalle `GENEALOGISTE_DEBIT_DEFAUT`, plafond `GENEALOGISTE_PLAFOND_JOUR_DEFAUT`, provenance
  « défaut » : aucune limite publiée n'a été relevée) ; Gallica et Wikidata gardent leur entrée existante. Aucun
  hôte hors référentiel n'est interrogé (`url_autorisee`). Coupe-circuit anti-robot, cache et plafonds sont
  ceux du client HTTP commun ; budget d'enquête et garde des vivants restent à la charge de chaque outil
  (#286 à #289).
- **Catalogue** : `sources_catalogue(type="contexte")` liste le référentiel avec, pour chaque service, `actif`,
  `interrogeable`, `motif` et `etat_cle` ; le catalogue complet (sans filtre) l'inclut sous `contexte`.
- **Diagnostic** : contrôle `services_contexte` (services actifs et interrogeables, motifs, clés « définie » ou
  « absente », `mailto` défini ou absent) ; `attention` si un service activé manque de sa clé requise ou si une
  clé est définie pour un service non activé.
- **Sondage** : `make verifier-archives` valide le référentiel et sonde chaque service sur `url_sonde`, sinon
  son point d'accès ou son site (HEAD, repli GET sans lecture du corps, sans clé) : `OK`, `AVERT` (service en lien seulement, protégé ou à clé requise) ou `KO`
  (service actif par défaut qui ne répond pas). Le référentiel n'est jamais modifié par le sondage ;
  `scripts/verifier_archives.py --contexte-seulement` ne sonde que les services de contexte (rapport daté :
  [releves-contexte-2026-11-23.md](releves-contexte-2026-11-23.md)).


### Recette et réponses enregistrées

<!-- #323 -->

Les tests de `make test` n'émettent aucune requête : chaque protocole est testé sur une **réponse réelle
enregistrée** (réduite au strict nécessaire) sous `mcp/tests/fixtures/contexte/reponses/<service>/`. Trois outils
distincts, tous hors CI, mesurent la dérive des services :

| Outil | Commande | Rôle | Écrit |
|---|---|---|---|
| Sondage | `make verifier-archives` (`scripts/verifier_archives.py --contexte-seulement` pour le seul contexte) | le service répond-il ? | rien |
| Rejeu | `make enregistrer-contexte` (`--verifier`), `make enregistrer-contexte ECRIRE=1` (`--ecrire`) ; `SERVICE="HAL SUDOC"` pour restreindre | la réponse réduite a-t-elle encore la forme enregistrée ? | rien, sauf `--ecrire` |
| Recette de contrat | `make test-contexte` (marqueur `contexte_live`, `GENEALOGISTE_TEST_CONTEXTE=1`) | l'analyseur lit-il la réponse réelle d'aujourd'hui ? | rien |

**Manifeste unifié.** Chaque dossier porte un `MANIFESTE.json` de même forme, vérifié pour tous les dossiers par
`tests/test_contexte_reponses.py` :

```json
{
  "service": "HAL",
  "objet": "ce que la réponse sert à tester (outil, issue)",
  "enregistre_par": "#286",
  "reponses": [
    {
      "fichier": "courrieres-mines.json",
      "url": "https://api.archives-ouvertes.fr/search/?q=…",
      "methode": "GET",
      "date": "2026-11-23T10:15:17Z",
      "statut": 200,
      "type": "application/json; charset=utf-8",
      "octets_origine": 4342,
      "reduction": "aucune (JSON réindenté)",
      "empreinte": "sha256:…",
      "client": "httpx, User-Agent générique, sans clé ni mailto"
    }
  ]
}
```

| Champ | Règle |
|---|---|
| `service` | nom du dossier en majuscules (code du référentiel ; `API-GEO` et `COG-INSEE` : services de `sources/geo.py`, hors référentiel) |
| `objet` | obligatoire ; facultatifs : `enregistre_par`, `commune_temoin`, `non_verifie` |
| `fichier` | fichier de la réponse réduite, décrit une seule fois ; tout fichier du dossier est décrit ; `null` si le corps n'est pas conservé (alors `empreinte: null`, `reduction: "corps non conservé"`) |
| `url` | URL https **sans clé, jeton ni adresse courriel** (`mailto`), sans nom de personne : lieux, périodes et sujets seulement |
| `methode`, `date`, `statut`, `type` | GET ; date ISO (`AAAA-MM-JJ` ou `AAAA-MM-JJThh:mm:ssZ`) ; statut HTTP entier ; `Content-Type` reçu |
| `reduction` | ce qui a été retiré (clés, lignes, éléments, couches) ; `aucune` si rien ; la réduction est reproduite par `REDUCTIONS` dans `enregistrer_contexte.py` |
| `empreinte` | `sha256:` du fichier tel qu'enregistré (vérifiée par le test) |
| `client` | client et en-têtes utilisés, sans identifiant d'authentification |
| facultatifs | `octets_origine` (taille avant réduction), `resultat`, `duree_s`, `note`, `rejouable: false` (extrait fait à la main, jamais rejoué) |

Les réponses n'ont jamais été modifiées par l'harmonisation : seuls les manifestes l'ont été (`statut_http` devient
`statut`, `content_type` devient `type`, `octets` devient `octets_origine`, ajout de `methode`, `client` par réponse et
`empreinte`). Une réponse enregistrée en 403 (page de blocage réduite à la main : ni adresse IP ni identifiant de
requête) n'est jamais rejouée.

**Enregistrement** (`mcp/scripts/enregistrer_contexte.py`, réseau réel, hors CI). Rejoue chaque requête décrite par
un manifeste (une tentative, 5 s entre deux requêtes vers un hôte, aucun contournement), applique la réduction
déclarée et compare la **forme** (chemins des clés JSON, des éléments XML, en-tête CSV) à celle de la réponse
enregistrée. Verdicts : `OK`, `DERIVE` (un champ enregistré a disparu : le service a changé, relire l'analyseur),
`AVERT` (403, 429, défi anti-robot, 5xx ou silence : consigné, service laissé de côté pour la suite), `IGNORE`
(non rejoué). Par défaut `--verifier` n'écrit rien ; `--ecrire` réécrit les réponses réduites et les manifestes des
requêtes qui ont répondu 200, puis le diff est relu avant commit. Une URL contenant une clé, un `mailto` ou un nom
des cas témoins n'est jamais émise. Testé sans réseau (`tests/test_enregistrer_contexte.py`, respx).

**Recette de contrat** (`tests/test_contexte_live.py`, `make test-contexte`). Une à deux requêtes par service qui a
un analyseur : les six gabarits de `contexte_bibliographie`, l'OAI-PMH de Persée, les cinq services de
`lieu_historique` (COG INSEE, API Géo, Wikidata, Melodi, Géoplateforme, par un seul appel de l'outil) et Gallica par
`presse_recherche`. Elle vérifie la **forme** que lit l'analyseur (conteneur de la réponse, titre lu sur au moins une
notice, observations, couches), jamais le contenu. Un service protégé, limité, muet ou en panne rend **AVERT** (test
ignoré avec le motif, `-rs`), pas un échec ; seule une réponse reçue mais illisible par l'analyseur échoue. Débit,
coupe-circuit, plafonds et cache du plugin sont ceux du client commun. Ignorée sans `GENEALOGISTE_TEST_CONTEXTE=1` :
`make test` et la CI ne l'exécutent jamais. Voir [integration-continue.md](integration-continue.md).

**Règle : aucun analyseur sans réponse réelle enregistrée.** `test_aucun_analyseur_sans_reponse_reelle_enregistree`
dérive du code la liste des services qu'un outil interroge avec un analyseur (gabarits, services de
`lieu_historique`, services de `presse_recherche` hors repli) et exige pour chacun un dossier avec manifeste et au
moins une réponse 2xx. Exception nommée et motivée : **GALLICA** (analyseur SRU et recherche dans le document du
client existant, antérieurs à #323, testés sur une fixture au format du parseur ; le SRU répond 403 Cloudflare et
ContentSearch n'a jamais été joint). Le test exige que l'exception reste nécessaire : elle disparaît dès qu'une
réponse 200 réelle est enregistrée. Europeana n'a pas d'analyseur (aucune réponse réelle : pas de clé personnelle
à l'enregistrement, clé de démonstration non utilisée, #343), donc pas d'exception.

**Courriels dans les réponses.** Le test refuse toute adresse courriel dans les réponses, sauf trois adresses
institutionnelles de réponses réelles laissées telles quelles (contact du `GetCapabilities` de la Géoplateforme,
contacts de revues dans la réponse d'Isidore), nommées dans le test.

**Fuite de `mailto` et de clés.** Le cache d'échecs du client HTTP, la table des défis anti-robot et les messages
d'erreur ne gardent plus l'URL brute : `HttpClient` masque les secrets (`masque`, branché sur
`services.masquer_cles` par `App`) avant tout message portant une URL (404, défi anti-robot). Constaté par
`tests/test_contexte_fuites.py` : une 404 ou un défi Cloudflare, avec un `mailto` Crossref configuré, laissaient
l'adresse encodée dans le cache d'échecs avant ce correctif ; 403 et 429 n'en portaient pas. Le test lit le cache
SQLite complet, le journal, les données et la sortie de l'outil.

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

### presse_recherche

<!-- #288 -->

`presse_recherche(texte, lieu="", periode="", services="", nombre=10)` (classe collecte, budget d'enquête via
`enquete`) cherche la presse ancienne, source primaire contemporaine, service par service. Code :
`contexte/presse.py` ; l'outil de `server.py` ne fait que la garde et l'appel.

- `texte` : mots cherchés (événement, métier, nom d'un défunt pour un fait divers) ; `lieu` : ajouté aux mots ;
  `periode` : `1906` ou `1900-1910` ; `services` : codes séparés par des virgules (`GALLICA`, `EUROPEANA`,
  `CHRONICLING-AMERICA`, `RETRONEWS`), dans l'ordre voulu ; vide : les quatre dans cet ordre.
- **Vivants** : `_garde` sur `texte` puis sur `lieu` avant toute requête (`GARDE_VIVANTS`, `GARDE_AVANT_BUDGET`).
- **Repli explicite** : chaque service est essayé ou écarté avec son motif (`services[]` : `service`, `statut`,
  `motif`, `journal`) ; un service bloqué n'arrête pas les suivants. Statuts : `interroge`, `bloque_antirobot`
  (coupe-circuit compris), `erreur`, `refuse` (désactivé, clé absente, hors ligne : `services.refus`),
  `lien_seulement`, `sans_analyseur`.
- **Résultats** (`resultats[]`) : une `Reference` sérialisée (`nature: primaire`, `type_document: presse`,
  `publication` = titre du périodique, `date`, `annee`, identifiant ARK, `service`, `requete`, `consulte_le`,
  `citation`), plus `url`, `vue` (numéro de vue Gallica `fN`, pas forcément la page imprimée), `ocr`, `extrait`
  et, si un extrait OCR est donné, `mention: « lecture OCR non vérifiée »`, `au_registre`, `suite`. Chaque
  référence est inscrite au registre des références consultées (réponse 2xx contenant l'ARK) ; `lu` reste
  `notice_seule` : relire l'image (`gallica_iiif`), l'archiver (`piece_archiver`), puis citer numéro et page lus.
- **Sans résultat** : `statut: tache_manuelle` (ou `bloque_antirobot` si Gallica oppose un défi, avec `consigne`,
  `suite` sans navigateur et, avec `enquete`, une tâche manuelle dans l'enquête), `recherche_negative` et
  `tache_manuelle` : motif par service, liens de consultation, ce qu'il faut relever (titre, date, numéro, page,
  extrait lu sur l'image), reprise par `source_collee`, `piece_archiver` ou `media_enregistrer`. Jamais de
  résultat inventé.
- **Journal** : recherche Gallica (`gallica`/`sru`, positive, négative ou bloquée) et synthèse
  `presse`/`presse_recherche` (motifs par service ; statut `positif`, `negatif`, `bloque_antirobot` ou `manuel`).

| Service | Traitement | Lien de consultation |
|---|---|---|
| Gallica | client existant (`sources/gallica.py` : SRU sur les fascicules, puis `ContentSearch` pour la vue et l'extrait OCR des 3 premiers documents) ; coupe-circuit et plafonds du client commun | page d'accueil (recherche en 403 Cloudflare le 2026-11-23, forme non vérifiée) |
| Europeana | `services.refus` (activation, `GENEALOGISTE_CLE_EUROPEANA`) ; **aucun analyseur** : pas de réponse réelle de l'API enregistrée (aucune clé disponible ; clé de démonstration non utilisée, plus publiée par Europeana au 2026-11-24). Avec une clé, `sans_analyseur`, aucune requête : la [clé personnelle](#clé-personnelle-europeana) n'a pas encore d'effet (#343) | recherche du site public (`/fr/search?query=`, vérifiée, HTTP 200) |
| Chronicling America | lien seulement (403 Cloudflare, une tentative le 2026-11-23) | page de la collection |
| Retronews | lien seulement (pas d'API publique) | recherche avancée pré-remplie (`/search?…&q=` : base64 du JSON encodé, forme relevée sur le site) ; période à régler dans le site |

Gallica figure en `lien_seulement` dans le référentiel de contexte (SRU en 403) : c'est le mode des services de
contexte (`contexte_bibliographie`, `lieu_historique`), pour lesquels `services.refus` répond « lien seulement ».
`presse_recherche` n'ouvre pas pour autant un nouvel accès : il passe par le même client que `gallica_recherche`
(`sources/gallica.py`), sans appeler `services.refus("GALLICA")`, avec le coupe-circuit et les plafonds du client
commun, et un blocage est rendu tel quel. Le référentiel le dit dans la `notes` de l'entrée (#323) ; son mode ne
change pas, et la décision de `services.refus` non plus. Son motif dit vrai depuis #325 : pour Gallica, « non
interrogé comme service de contexte ; seul presse_recherche l'interroge, par son client existant » (exception
nommée `services.INTERROGE_HORS_REFERENTIEL`) ; les autres services en lien seulement gardent « jamais interrogé par
le plugin ». Réponses réelles réduites et manifestes :
`mcp/tests/fixtures/contexte/reponses/<code>/MANIFESTE.json` (forme unifiée, voir « Recette et réponses
enregistrées »).

### contexte_bibliographie

<!-- #286 -->

Littérature historique (monographie communale, histoire industrielle ou régionale, thèse, article savant) sur un
lieu, une période et un thème, citée et inscrite au registre des références consultées. Classe de permission
`collecte` ; budget d'enquête (`enquete=<id>`) et « déjà fait » comme les autres outils de collecte.

```
contexte_bibliographie(sujet="", lieu="", periode="", echelle="commune", services=None, personne="", limite=10)
```

| Argument | Rôle |
|---|---|
| `sujet` | thème libre (« mines », « émigration ») ; texte libre : passe par la garde des vivants |
| `lieu` | commune, département ou région, tel qu'envoyé aux services |
| `periode` | `AAAA` ou `AAAA-AAAA` : sert au **classement**, jamais de filtre sur la date de publication |
| `echelle` | `commune`, `departement`, `region`, `pays` (région naturelle), `nation` : choisit les lieux d'une personne |
| `services` | codes du référentiel ; défaut : services bibliographiques actifs |
| `personne` | id de l'arbre : garde des vivants, puis lieux (trois au plus), période de vie et premier métier lus dans ses faits **sourcés** (`requete.depuis_personne`) complètent les arguments absents |
| `limite` | notices demandées par service (25 au plus) |

**Services livrés** (un gabarit par service dans `contexte/gabarits.py`, analyseur d'après une réponse réelle
enregistrée sous `mcp/tests/fixtures/contexte/reponses/<service>/` avec son `MANIFESTE.json`) :

| Code | Protocole | Requête | Lecture |
|---|---|---|---|
| `HAL` | Solr | `("lieu" OR …) AND (mots du sujet)`, types de dépôt textuels | DOI sinon identifiant HAL ; évaluation par les pairs (`peerReviewing_s`) ; thèse ou article évalué : savante |
| `ISIDORE` | REST | lieu principal et sujet | DOI sinon Handle ; titre d'origine, auteurs tels que donnés |
| `SUDOC` | SRU (UNIMARC) | `tou="lieu" … and tou=mot` | PPN ; documents non textuels (cartes, images) écartés ; thèse (zone 328) : savante |
| `BNF-CATALOGUE` | SRU (Dublin Core) | `bib.anywhere all` | ARK ; documents non textuels écartés |
| `THESES-FR` | REST | lieu principal et sujet | DOI ; thèse sans DOI ou non soutenue écartée (motif et lien theses.fr) |
| `CROSSREF` | REST | `query.bibliographic`, types article, chapitre, livre, thèse | DOI ; `mailto` envoyé seulement s'il est renseigné |

Non livrés : `OPENALEX`, `IDREF`, `NAKALA`, `CULTURE-DATA` (pas de gabarit bibliographique) ; `PERSEE` et
`OPENEDITION` (OAI-PMH : pas de recherche, l'analyseur `protocoles/oai.py` lit une notice dont l'identifiant est
connu) ; `WIKIPEDIA` (jamais source de cet outil) ; services en lien seulement ou protégés. Demandés, ils sont
listés dans `services_ecartes` avec leur motif, sans requête.

**Traitement.** Pour chaque service : `services.refus` (inconnu, lien seulement, protection, désactivé, clé
absente, hors ligne) puis contrôle de l'hôte (`url_autorisee`) ; avec `personne`, une URL qui contiendrait un
élément de son identité (`residus_identite`) n'est pas émise. Chaque notice devient une `Reference` (format commun,
`lu: notice_seule`) ; une notice sans identifiant pérenne lisible, non textuelle, ou dont ni le lieu ni le sujet ne
figurent dans le titre, les sujets ou les mots-clés est écartée (`notices_ecartees`, avec le motif). Nature : celle
lue sur la notice (thèse, article évalué par les pairs : `secondaire_savante` ; autre : `secondaire`) ; un imprimé
publié **pendant la période** est une source contemporaine (`primaire`). Dédoublonnage : même DOI, sinon même PPN,
sinon même titre et même année ; la notice gardée est la plus savante puis la plus complète, `trouvee_par` liste les
services. Classement : pertinence géographique (lieu demandé, lieu plus large, aucun), puis temporelle
(contemporaine ou années citées qui recoupent la période, non précisée, hors période), puis nature (savante
d'abord). Chaque référence renvoyée est inscrite au registre des références consultées (réponse 2xx contenant
l'identifiant) ; une référence que le registre refuse n'est pas renvoyée.

**Sortie.**

```json
{"outil": "contexte_bibliographie",
 "requete": {"sujet": "mines", "lieux": ["Courrières"], "echelle": "commune", "periode": {"de": 1880, "a": 1914},
             "depuis_personne": false, "metiers": [], "limite_par_service": 10},
 "style_citation": "iso690", "nb_references": 13,
 "references": [{"citation": "…", "identifiant": {"type": "doi", "valeur": "10.…"}, "nature": "primaire", "…": "…",
                 "trouvee_par": ["CROSSREF"],
                 "pertinence": {"lieu": "demande", "lieu_cite": "Courrières", "sujet": true,
                                "periode": "contemporaine"}}],
 "services_interroges": [{"service": "HAL", "requete": "https://…", "total": 10, "nb_notices": 5, "nb_retenues": 5,
                          "depuis_cache": false, "journal": "…"}],
 "services_en_echec": [{"service": "…", "erreur": "…", "journal": "…"}],
 "services_ecartes": [{"service": "WIKIPEDIA", "motif": "…"}],
 "notices_ecartees": [{"service": "BNF-CATALOGUE", "titre": "…", "motif": "document non textuel …"}],
 "rappel": "…"}
```

Rien trouvé : `references: []` et `recherche_negative` (« contexte non documenté par les services interrogés »),
jamais de remplissage. Un service en échec n'empêche pas les autres ; `erreur` n'apparaît que si aucun service
n'a répondu, ou pour des arguments invalides (`requetes_emises: 0`). Journal : une entrée par requête émise
(source = code du service en minuscules, opération `bibliographie`, statut `positif`, `negatif` ou `erreur`),
URL masquée (clé et `mailto` remplacés par `***`, y compris sous leur forme encodée).

Limites : la période n'est pas envoyée (les services ne distinguent pas période étudiée et date de publication) ;
les services REST reçoivent le seul lieu principal (pas de syntaxe booléenne documentée) ; la pertinence est lue sur
le titre, les sujets et les mots-clés, pas sur le texte ; la nature « savante » n'est attribuée que sur une
indication de la notice (thèse, évaluation par les pairs déclarée) ; `personne` est hors de l'identité « déjà
fait » (deux demandes sans lieu ni sujet pour deux personnes différentes sont signalées comme la même).

### lieu_historique

<!-- #287 -->

`lieu_historique(lieu, date)` (classe collecte, `enquete` facultatif) : géographie historique d'une commune à une
date, **niveau par niveau**, chacun avec `source` et `periode_de_validite`. Code : `contexte/lieux.py`. Périmètre
fixé par l'étude #322 ([etudes/lieux-1790-1943.md](etudes/lieux-1790-1943.md)) : rien n'est déduit, ni par le code
ni par le modèle.

- `lieu` : commune avec son département (`Billy-Montigny, Pas-de-Calais`, `Somain (59)`) ou code INSEE ; `date` :
  GEDCOM ou texte (`1906`, `12 MAR 1906`, `vers 1750`, `an XII`), lue comme un intervalle grégorien.
- Pays (`pays_du_lieu`) : hors de France, réponse `hors_perimetre` sans requête ni extrapolation ; pays inconnu
  (`Billy`), réponse `pays_inconnu` sans requête. Homonymes au COG (`Billy, France`) : `homonymie` et liste des
  `candidats` (code, nom, département, période), sans choix ; préciser le département ou le code INSEE.

| Niveau | Source | Sinon |
|---|---|---|
| `nom`, `departement`, `rattachement_communal` (commune déléguée ou associée), `existence`, `communes_absorbees`, `evenements_depuis_1943` | COG INSEE par `geo_historique` et la chronologie COG de `sources/geo.py` (millésime configuré) ; `debut` 1943-01-01 = début de la couverture (antérieur inconnu) | avant 1943 ou intervalle à cheval sur 1943 : « inconnu » |
| `population` | INSEE Melodi `DS_POPULATIONS_HISTORIQUES` : observation de l'année la plus proche avant la date (`annee`, code de `mesure` tel que servi, `ecart_annees`), géographie de diffusion lue dans le catalogue du jeu (2025-01-01 au relevé) | avant la première année du jeu (1968), commune absente de cette géographie, service non interrogeable : « inconnu » |
| `canton`, `arrondissement`, `district` | aucune (le COG ne date pas ces rattachements) | « inconnu » ; district : lien vers la carte des districts de 1790 (Nakala, ODbL) |
| `province`, `generalite`, `bailliage_ou_senechaussee`, `diocese` | aucune source structurée ouverte par commune | « inconnu » ; lien Cassini et dictionnaire topographique du département |
| `cartes` | Géoplateforme WMTS : `AN-` et `BNF-IGNF_GEOGRAPHICALGRIDSYSTEMS.CASSINI`, `GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR40`, `GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR10`, `GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN50.1950`, `ORTHOIMAGERY.ORTHOPHOTOS.1950-1965` | couche hors emprise du lieu ou période non renseignée : rangée dans `autres` avec son motif |

Chaque niveau « inconnu » porte `source: null`, `periode_de_validite: null`, `statut: "à établir"`, un `motif` et
`consultation` : fiche « Des villages de Cassini aux communes d'aujourd'hui » (EHESS) par son identifiant, trouvé
dans l'index Wikidata (P374 → P8422, jamais source ; site EHESS sans réponse aux relevés), sinon le site ; base
Cassini redéposée sur Nakala (`doi:10.34847/nkl.e0556oog`, CC BY-NC-SA 4.0, ni embarquée ni interrogée ; l'utilisateur
peut l'installer lui-même, voir [Base Cassini locale](#base-cassini-locale-facultative)). Ne jamais compléter un
niveau « inconnu » de mémoire.

Cartes : la période d'une couche est lue dans son titre (`Carte de l'état-major (1820-1866)`), sinon dans
l'étendue temporelle de sa fiche de métadonnées CSW (Cassini : 1756-1815). Sont retenues les couches contemporaines
de la date, à défaut la plus proche avant et la plus proche après. Chaque carte retenue donne un lien `GetTile`
vers la tuile (niveau 14, sinon le plus fin publié) qui contient le centre de la commune actuelle (API Géo), avec
le style, le format et le jeu de tuiles déclarés par la couche, ses fiches et les conditions d'utilisation du
service ; aucune image n'est téléchargée. Commune disparue : pas de centre, pas de lien.

Réseau : seul le code INSEE part vers Melodi et Wikidata ; `services.refus` avant chaque service de contexte
(désactivé, hors ligne : niveau « inconnu » avec le motif, résumé dans `requetes`) ; une entrée de journal par
service et une pour l'ensemble. Réponses réelles enregistrées (Billy-Montigny, 2026-11-23) :
`mcp/tests/fixtures/contexte/reponses/` (`INSEE-MELODI`, `IGN-GEOPLATEFORME`, `WIKIDATA`, `COG-INSEE`, `API-GEO`,
chacun avec `MANIFESTE.json`). Limites : la requête Wikidata a pris 45 s au premier essai (0,7 s ensuite) ; au-delà
du délai HTTP, la fiche Cassini n'est pas identifiée et le lien générique est donné. Les liens `GetTile` suivent
les jeux de tuiles déclarés par les couches (`PM_6_15`…) ; seule une tuile du jeu `PM` a été demandée par l'étude.

#### Base Cassini locale (facultative)

<!-- #349 -->

Avant 1943, aucune source structurée sous licence ouverte n'existe (étude #322). La base Cassini de l'EHESS,
redéposée sur Nakala par G. Bideau et N. Verdier (`doi:10.34847/nkl.e0556oog`), documente cette période, mais sous
**CC BY-NC-SA 4.0** : elle n'est **jamais** dans le dépôt du plugin (GPL-3.0), ni entière, ni en extrait, ni en
fixture de test. Chaque utilisateur peut l'installer à part, pour lui-même, par un geste explicite et tracé. Code :
`contexte/cassini.py`.

| Étape | Outil | Classe | Ce qui se passe |
|---|---|---|---|
| 1. Présenter | `cassini_preparer()` | proposition (sans accord) | lit les **métadonnées** du dépôt Nakala (une requête, aucune donnée de personne, aucun téléchargement du jeu) et rend : source, auteurs et déposant, DOI, version ; licence en clair ; réserve ; taille et empreinte SHA-1 publiées ; URL ; destination ; état de l'installation ; **jeton** à usage unique, valable une heure |
| 2. Installer | `cassini_installer(jeton)` | **écriture** (accord demandé par Claude Code à chaque appel ; refusé avec `GENEALOGISTE_ECRITURE=interdite`) | relit les métadonnées (refus si le fichier publié a changé depuis l'étape 1), télécharge le fichier (25 Mo) par le client HTTP commun, vérifie taille, **empreinte publiée par Nakala** et en-tête, écrit le fichier puis `acceptation.json` |
| 3. Utiliser | `lieu_historique` (et `contexte_local`, `pistes_contexte` qui l'appellent) | collecte | lit le fichier local s'il est présent **et** accepté **et** d'empreinte conforme ; sinon rien ne change |
| 4. Retirer | `cassini_desinstaller()` | **écriture** (accord demandé) | supprime le fichier, l'acceptation et les restes d'un téléchargement interrompu ; un fichier étranger du dossier n'est pas touché |

**Licence, telle que présentée à l'utilisateur avant tout téléchargement** : pas d'usage commercial ; attribution
obligatoire ; toute copie, même modifiée ou extraite, reste sous la même licence. **Réserve** : le dépôt Nakala est
une redéposition par des tiers d'un fichier téléchargé auprès de l'EHESS, dont la licence d'origine n'a pas pu être
lue (site injoignable aux relevés). `cassini_preparer` refuse si la licence publiée par Nakala n'est plus
`CC-BY-NC-SA-4.0`, si le dépôt n'est plus publié ou si le fichier n'y est plus : il ne présente jamais une licence
qu'il n'a pas relue. L'appel de `cassini_installer` vaut acceptation de la licence **par l'utilisateur** ; il ne
se fait qu'après son accord explicite. Attribution à reprendre : « Base Cassini (LaDéHis, EHESS), redéposée par
G. Bideau et N. Verdier, Nakala, doi:10.34847/nkl.e0556oog, CC BY-NC-SA 4.0 ».

**Emplacement.** `<référentiels>/cassini/lieux_cassini_devenus_communes.csv` et, à côté, `acceptation.json` (date,
licence, conditions, réserve, DOI, version du dépôt, taille, empreintes SHA-1 et SHA-256, URL d'origine).
`<référentiels>` : `GENEALOGISTE_REFERENTIELS_DIR`, par défaut `~/.local/share/genealogiste-referentiels`
(`$XDG_DATA_HOME`), `/cache/referentiels` dans l'image Docker. Le dossier est refusé, avant toute requête, s'il se
trouve dans le répertoire de données (dépôt Git de l'arbre), dans un dossier de l'utilisateur géré par le plugin
(médias, pièces, notes, rapports, exports), dans le plugin, ou sous un dépôt Git quel qu'il soit (liens
symboliques résolus) : le fichier ne peut pas être commité, et il n'entre pas dans une sauvegarde de l'arbre. Le
même contrôle est refait à chaque lecture. Écriture atomique (temporaire du même dossier, puis renommage) ;
l'acceptation est écrite après le fichier : un téléchargement ou une écriture qui échoue ne laisse ni fichier
partiel ni acceptation. Le fichier n'est jamais copié dans le cache SQLite.

**Ce que cela change dans `lieu_historique`.** Jointure par code INSEE (colonne `commune_mars_2021`, géographie de
mars 2021). Seuls des niveaux « inconnu » sont complétés ; un niveau sourcé par le COG ou par Melodi n'est jamais
remplacé.

| Niveau | Valeur tirée du fichier | Période de validité rendue |
|---|---|---|
| `nom` (avant 1943) | noms de l'an III, de 1801 et de 1999, et nom sur la carte de Cassini | 1794-1999, « instantanés, pas un historique continu » : le nom à la date demandée n'est pas établi |
| `departement` (avant 1943) | nom du département en l'an III, code en 1999 | 1794-1999, instantanés |
| `district` | district de l'an III | 1794-1795 |
| `generalite` | intendance, type, subdélégations | fin de l'Ancien Régime, date non précisée par le jeu ; rattachement hérité de la carte par traitement automatique, pas un rattachement établi pour la commune |
| `population` (si « inconnu » : avant 1968, ou Melodi non interrogeable) | recensement le plus proche avant la date (`annee`, `recensement`, `ecart_annees`, `annees_disponibles`) ; « an III » = 1794-1795, « an VIII » = 1799-1800 | année du recensement, aucune valeur interpolée |

Chaque valeur porte `statut: "indication"`, un `avertissement` (elle oriente, ne conclut rien, ne remplace pas une
source primaire) et une `source` : `service: "CASSINI-LOCAL"`, `licence`, `conditions`, `attribution`, `reserve`,
`reference: "doi:10.34847/nkl.e0556oog"`, `au_registre`, empreinte et date d'acceptation du fichier local. La
référence suit les règles du registre des références consultées : elle y est inscrite à l'installation (réponse 2xx
des métadonnées Nakala, qui contient le DOI) ; `contexte_local` n'en tire un élément (population, type
`demographie`, origine `NAKALA`, licence et attribution dans `source.localisation`) que si elle y figure. Le
résultat gagne un bloc `cassini` : lieux de la carte rattachés au code INSEE (identifiant, type, noms, chef-lieu
communal en 1999, chefs-lieux de 1789-1790, lien de fiche), 30 au plus, avec leur nombre. Un lieu qui n'est pas
chef-lieu communal en 1999 peut être une ancienne commune réunie : le jeu ne date aucune réunion, il oriente vers
une fusion à établir. `canton`, `arrondissement`, `province`, `bailliage_ou_senechaussee` et `diocese` restent
« inconnu » (le jeu n'a que des booléens de chef-lieu). Rien n'est écrit dans l'arbre.

Sans fichier, ou si le fichier est présent sans acceptation, si l'acceptation est illisible ou d'une autre
licence, si l'empreinte du fichier diffère de celle de l'acceptation, si l'en-tête n'est pas reconnu, ou si le
dossier est devenu un emplacement refusé : le fichier **n'est pas lu** et `lieu_historique` rend exactement sa
réponse habituelle (« inconnu » + lien). `cassini_preparer` donne l'état et le motif (`etat`).

**Lecture.** Aucun index n'est écrit sur disque : au premier appel du processus, une passe lit le fichier, contrôle
son empreinte (ce qui impose de toute façon une lecture complète) et garde en mémoire la position des lignes par
code INSEE ; chaque consultation relit ensuite quelques lignes. Mesures du 2026-11-24 sur le fichier réel
(43 792 lieux, 34 819 codes INSEE) : installation 4,7 s (métadonnées, téléchargement de 25,5 Mo, contrôles,
écriture) ; première lecture 0,41 s (dont 0,03 s d'empreinte), environ 11 Mo retenus en mémoire ; consultations
suivantes 1 à 2 ms, sur un appel de `lieu_historique` de 5 à 6 s (COG, cartes, services). Un fichier modifié ou
remplacé (taille, date) est relu et recontrôlé.

**Limites.** Commune absente du COG depuis 1943 (disparue avant) : pas de code INSEE, donc pas de jointure ; elle
peut apparaître dans le bloc `cassini` de la commune qui l'a absorbée. Code INSEE de 2021 : une commune créée ou
renumérotée depuis n'est pas rejointe. Plusieurs chefs-lieux communaux de 1999 pour un même code (797 codes au
relevé) : celui dont le nom de 1999 égale le nom du COG est retenu, sinon aucun, et les niveaux restent
« inconnu ». Les valeurs sont rendues telles quelles (`non citée`, graphies d'époque). `contexte_local` retient un
seul élément par source et par appel : avec plusieurs communes de vie, une seule population Cassini est rendue.
Les métadonnées Nakala servant aux tests sont fabriquées à l'image de la réponse réelle (aucune réponse réelle
enregistrée dans le dépôt). Recette sur le fichier réel : `make test-cassini` (ignorée si le fichier n'est pas
installé).

### contexte_local

<!-- #289 -->

`contexte_local(personne="", lieu="", periode="", echelles="", themes="")` (classe collecte, budget d'enquête via
`enquete`) rassemble des éléments de contexte **sourcés, classés et bornés** autour d'un individu ou d'un lieu à une
période. Code : `contexte/local.py` (assemblage), `contexte/index_wikidata.py` (gabarits Wikidata) ; l'outil de
`server.py` ne fait que la garde et l'appel. Aucun format nouveau : `ElementContexte`, `portee.controler` et le
registre des références consultées du socle.

| Argument | Rôle |
|---|---|
| `personne` | id de l'arbre : garde des vivants, puis lieux (avec années de présence), période de vie et métiers lus dans ses seuls faits **sourcés** et non réfutés (`requete.depuis_personne`) ; jamais son nom |
| `lieu`, `periode` | sans `personne` : commune avec son département et période `AAAA-AAAA` (obligatoire) ; avec `personne`, `lieu` est refusé et `periode` restreint la période de vie |
| `echelles` | parmi `commune`, `pays`, `departement`, `region`, `nation`, `international` ; défaut `commune,departement` |
| `themes` | mots du sujet (texte libre, passe par la garde des vivants) ; défaut : premier métier sourcé |

**Vivants.** `_garde` sur `personne` et `themes`, puis sur `lieu`, avant toute requête (`GARDE_VIVANTS`,
`GARDE_AVANT_BUDGET`). Avec `personne`, toute requête (URL, requête SPARQL, mots de presse, libellé de lieu) est
contrôlée par `residus_identite` avant l'envoi : une requête qui contiendrait un élément d'identité n'est pas émise
(motif dans `services_en_echec`).

**Collecte**, service par service ; l'échec de l'un n'arrête pas les autres. Hors de France, seuls les services dont
la `couverture` du référentiel inclut le pays (France : `FR`, `EU`, `INT` ; États-Unis : `US`, `INT` ; autre pays ou
pays inconnu : `INT`) ; sinon le service est écarté avec son motif.

| Collecte | Échelle | D'où vient l'élément | `enonce` |
|---|---|---|---|
| géographie historique (`lieux.lieu_historique`, communes françaises, trois au plus, aux années de présence) | commune | population INSEE Melodi ; cartes de la Géoplateforme dont la tuile contient le centre de la commune. Les niveaux « inconnu » ne donnent rien | valeurs du jeu (`titre : valeur (mesure, année)`) ; titre de la couche |
| index Wikidata (`index_wikidata`, gabarits `evenements_commune` et `evenements_departement`) | commune ; département | entrée de l'index dont une référence externe (BnF `P268`, IdRef `P269`, Persée `P8758`) présente dans la réponse est déjà au registre | titre de cette référence, jamais le libellé Wikidata |
| bibliographie (`bibliographie.rechercher`, mêmes services et classement que `contexte_bibliographie`) | chaque échelle demandée, par pays | notice dont le **titre** cite un lieu de vie (sinon le département de ce lieu : échelle `departement`) | titre de la notice |
| presse (`presse.rechercher`, deux communes par pays) | commune | numéro au registre dont l'extrait OCR cite la commune | extrait cité, suivi de « (lecture OCR non vérifiée) » |

Dates d'un élément : années citées par la notice qui recoupent la période (sinon la première citée, rejetée par le
contrôle), ou année de publication d'un imprimé contemporain ; année de l'observation ; période de la couche ;
années de l'entrée de l'index. Élément non daté : écarté. Type (`evenement`, `economie`…) : classement lexical
indicatif des mots du titre ou de l'extrait (`TYPES_LEXIQUE`), `culture` à défaut ; `evenement` pour l'index,
`demographie` et `geographie` pour la géographie historique.

**Contrôles.** Chaque élément passe par `portee.controler` : hors de la période de vie ou des lieux de vie, il est
écarté avec son motif ; au-delà de la commune il porte `mention` (« tendance générale, ne prouve rien pour
l'individu »). Sa source doit être au registre des références consultées (notice récupérée par le plugin ; un jeu de
données ou un service interrogé par son URL y est inscrit avec un identifiant `url` égal à la requête) ; sinon il est
écarté. Une même source n'est retenue qu'une fois, à l'échelle la plus locale.

**Rattachement.** `atteste` seulement si une citation de l'arbre portant sur un fait de la personne (page, texte,
note, ARK, titre ou URL de la source) contient l'identifiant de la source de l'élément : `citation_arbre` la nomme.
Sinon `compatible` (échelle commune, même lieu, années recoupant la présence attestée par l'arbre ou la période
demandée) ou `non_demontre` (autre échelle, ou années hors de la présence attestée), avec une justification
factuelle. Le groupe (métier, âge) n'est pas évalué automatiquement.

**Wikidata, index seulement.** Gabarits SPARQL légers versionnés dans `contexte/index_wikidata.py` :
rattachement administratif à la commune par son code INSEE (`P374`, puis `P276`|`P131` et `P131*`), jamais un
rayon ; classes d'événements fermées (`CLASSES_EVENEMENTS` : catastrophe, accident minier, grève, épidémie,
bataille, inondation, incendie, sous-classes comprises) ; filtre sur l'année (`P585`, sinon `P580` à `P582`) ;
`LIMIT 50` ; délai du client HTTP commun (`GENEALOGISTE_HTTP_TIMEOUT`), limites de débit, coupe-circuit et cache de
30 jours. Seuls un code INSEE et deux années partent. Une entrée sans référence externe est écartée ; une entrée dont
la référence n'est pas consultée est signalée dans `non_sources` (`statut: « non sourcé »`, identifiants et liens de
consultation), jamais présentée comme source. Le code INSEE vient du COG (communes depuis 1943) : sans lui, le
gabarit n'est pas applicable (motif).

<!-- #345 -->

**Gabarit départemental** (`evenements_departement`, échelle `departement` demandée, une requête par département
français des lieux de vie, trois lieux au plus). Le département est désigné par son code INSEE (`P2586`, tiré du nom
du département sans réseau : `62`, `2A`, `971`) ; mêmes classes fermées, même filtre d'années, `LIMIT 100`. Forme
légère, à **profondeur bornée** : l'événement est situé (`P276` ou `P131`) dans le département lui-même ou dans un
lieu rattaché **directement** au département par `P131` (un seul niveau, jamais `P131*`). Trois sous-requêtes
nommées, évaluées une fois chacune et jointes sur le type : les éléments situés dans le département (`%lieux`), les
sous-classes des classes fermées (`%types`, seul parcours de `P279*`), le type des éléments situés (`%situes`). Seuls
le code du département et deux années partent. Les lignes sont lues par le même analyseur et suivent les mêmes
règles que le gabarit communal : index seulement, énoncé tiré de la référence consultée, jamais du libellé ; un
élément retenu est d'échelle `departement` et porte la mention de tendance générale. `limite_atteinte` (dans
`services_interroges`) signale une réponse plafonnée par `LIMIT` : partie des entrées, sans ordre.

Limites du gabarit départemental : un événement situé plus profondément (dans un édifice, un lieu-dit ou une commune
rattachée au département par un seul arrondissement ou canton) n'est pas renvoyé ; deux réponses réelles sont
enregistrées (Pas-de-Calais 1881-1946, Somme 1892-1916, 2,9 s et 2,8 s), et aucune de leurs 26 et 16 entrées ne porte
d'identifiant BnF, IdRef ou Persée : sur ces cas l'index ne produit aucun élément, toutes les entrées sont écartées
avec leur motif. La durée sur un département plus chargé ou une période plus longue n'a pas été mesurée.

| Gabarit | État | Réponses réelles enregistrées (`reponses/WIKIDATA/`) |
|---|---|---|
| `evenements_commune` | livré | 2026-11-23 : Billy-Montigny 1881-1946 (vide, 3,2 s), Courrières 1881-1946 (une entrée sans identifiant externe, 2,6 s), Belloy-en-Santerre 1892-1916 (vide, 2,5 s) |
| `evenements_departement` | livré (#345) | 2026-11-24, forme à profondeur bornée, deux essais, deux réponses : Pas-de-Calais (`62`) 1881-1946 (200 en 2,9 s, 27 lignes, 26 entrées) ; Somme (`80`) 1892-1916 (200 en 2,8 s, 16 entrées) ; aucune entrée avec identifiant externe |
| formes départementales écartées (`NON_LIVRES`) | non livrées, jamais émises | 2026-11-23, une fois chacune : `P2586` puis `P131*` non borné ; communes du département par le préfixe du code INSEE : délai dépassé (60 s) ; consigné dans `MANIFESTE.json` (`non_verifie`) |

**Sortie.**

```json
{"outil": "contexte_local",
 "requete": {"personne": "I1", "depuis_personne": true, "lieux": [{"commune": "…", "departement": "…",
             "pays": "France", "de": 1881, "a": 1904}], "periode": {"de": 1881, "a": 1946}, "metiers": ["mineur"],
             "themes": "", "echelles": ["commune", "departement"]},
 "style_citation": "iso690", "resultat": "2 élément(s) de contexte sourcé(s)", "nb_elements": 2,
 "elements": {"commune": [{"enonce": "…", "type": "evenement", "portee": {"…": "…"}, "source": {"…": "…"},
                           "rattachement": {"…": "…"}, "origine": "SUDOC"}],
              "departement": [{"…": "…", "mention": "tendance générale, ne prouve rien pour l'individu"}]},
 "non_documente": [], "non_sources": [], "nb_ecartes": 12, "ecartes": [{"origine": "…", "enonce": "…", "motif": "…"}],
 "services_interroges": [], "services_en_echec": [], "services_ecartes": [], "taches_manuelles": [],
 "journal": "…", "avertissement": "…", "rappel_index": "…"}
```

Un élément est un `ElementContexte` sérialisé, plus `origine` (service) et, au-delà de la commune, `mention` :
`ElementContexte.from_dict` le relit sans ces deux clés. `ecartes` (100 au plus, `nb_ecartes` les compte tous) donne
le motif de chaque candidat écarté. Rien trouvé : `elements: {}`, `resultat: « contexte non documenté »` et
`recherche_negative`, jamais un texte général ; `non_documente` liste les échelles demandées sans élément. Arguments
insuffisants : `erreur` et `requetes_emises: 0`. Journal : les entrées des modules appelés, plus une synthèse
`contexte`/`contexte_local` (statut `positif` ou `negatif`, identifiants des sources).

Enregistrement dans le coffre (point 6 de l'issue) : hors périmètre de l'outil, qui n'écrit rien (classe
collecte). La fiche de la personne peut recevoir un élément par l'outil de notes existant `notes_ajouter` (classe
écriture : accord de l'utilisateur), en reprenant `enonce` et `source.citation` tels quels ; aucun outil existant
n'écrit de note de lieu (`lieux/…`).

Limites : un lieu cité seulement dans les sujets ou les mots-clés d'une notice (pas dans son titre) n'est pas
retenu ; le type est un classement lexical ; la géographie historique ne donne rien avant 1943 (COG) ni avant 1968
(population), sauf les cartes ; le gabarit Wikidata départemental ne descend que d'un niveau sous le département ;
`personne` est hors de l'identité « déjà
fait » (voir [enquetes.md](enquetes.md)) ; l'outil enchaîne plusieurs services (une collecte complète peut émettre
plusieurs dizaines de requêtes, bornées par le budget d'enquête).

### pistes_contexte

<!-- #290 -->

`pistes_contexte(personne="", lieu="", periode="", echelles="", themes="")` (classe collecte, budget d'enquête via
`enquete`) produit des **hypothèses de recherche réfutables** en combinant les faits sourcés de l'arbre, les éléments
de `contexte_local` (mêmes arguments, même collecte) et les chaînes de sources. Code : `contexte/pistes.py` ; l'outil
de `server.py` ne fait que la garde et l'appel. Règle d'inférence : **le contexte oriente une recherche, il ne
conclut jamais.**

- **Vivants** : `_garde` sur `personne` et `themes`, puis sur `lieu`, avant toute requête (`GARDE_VIVANTS`,
  `GARDE_AVANT_BUDGET`) ; les requêtes sont celles de `contexte_local` (contrôle `residus_identite`).
- **Sans `personne`** (`lieu` et `periode`) : seules des pistes `contexte_seul` ; les deux règles tirées des faits
  sont listées dans `regles_non_appliquees`.

**Règles.** Chaque piste est engendrée par une règle fermée (`REGLES`, rendue dans la sortie) ; aucun intitulé n'est
rédigé librement, aucun fait historique n'est ajouté.

| Règle | Si | Piste (`hypothese`) | `test` | `statut` |
|---|---|---|---|---|
| `fenetre_depart` | fenêtre de départ déterminée par deux faits datés et situés (`emigration.fenetre_depart`) | « Départ de France entre *date du dernier fait en France* et *date du premier fait à l'étranger* » | chaîne du parcours émigration (`next_source_hint("EMIG", début)`, versants français et étranger) | `confirmee` si un `EMIG` ou `IMMI` cité, au statut confirmé ou probable, est daté dans la fenêtre ; sinon `a_tester` |
| `meme_metier_a_l_arrivee` | métier attesté (`OCCU` cité, ni réfuté, ni contradictoire, en France ou sans lieu, au plus tard au premier fait à l'étranger) et premier fait daté situé à l'étranger | « Même profession après l'arrivée (*pays*) : *intitulé du métier dans l'arbre* » | sources nominatives du pays d'arrivée (versant étranger de `next_source_hint("RESI", premier fait à l'étranger)`) | `confirmee` si un `OCCU` situé à l'étranger, cité, au statut confirmé ou probable, porte le même intitulé ; sinon `a_tester` |
| `element_de_contexte` | élément de `contexte_local` retenu, rattachement `compatible` ou `non_demontre`, hors géographie descriptive (population INSEE, cartes) | « Élément de contexte sourcé (*lieu*, *années*) : *`enonce` de l'élément* », sans connecteur causal | aucune source individuelle connue : `sources: []`, `motif` « reste non démontrée » | toujours `contexte_seul`, `plafond_gps: hypothese` |

`refutee` n'est attribué par aucune règle livrée : la fenêtre est tirée de l'arbre (un fait contraire la déplace) et
une autre profession attestée n'exclut pas la première. Un fait de l'arbre au statut « hypothèse » ne tranche
jamais. Un élément `atteste` (déjà porté par une citation de l'arbre) ou de géographie descriptive ne fait pas de
piste (`elements_non_retenus`, avec le motif).

**Piste.**

| Champ | Contenu |
|---|---|
| `id`, `regle`, `hypothese` | `h1`… dans l'ordre des règles ; intitulé du gabarit de la règle |
| `fondements` | `arbre` : faits avec `uid`, `porteur`, `fait`, date, lieu, `statut` de preuve (`evidence`) et citations, `role` (borne, métier attesté, fait qui tranche) ; `contexte` : l'élément tel que rendu par `contexte_local` (`enonce`, `portee`, `source` avec citation et identifiant au registre, `rattachement`, `mention`) |
| `test` | `sources` : entrées des chaînes existantes telles quelles (`source`, `cote_typique`, `versant`, `avertissement`, `pays`), plus `cout` ; aucune cote étrangère, aucun fonds inventé |
| `cout` | `en_ligne` seulement si une source du test est déclarée « en ligne » par la chaîne ; sinon `a_determiner` (`courrier` et `deplacement` : aucun champ du référentiel ne permet de les déduire) |
| `statut`, `statut_libelle` | `a_tester`, `confirmee`, `refutee`, `contexte_seul` |
| `depot` | `null` pour une piste déjà tranchée ; sinon `enquete_noter` (paramètres `piste` et `personnes`, à compléter par `enquete` ; `piste.contexte_seul: true` pour une piste `contexte_seul`) et `file` : chemin vers la file comme **tâche** (`enquete_reprendre(taches=true, elements=…)`, opération `ajouter_tache`, backend gramps et `GENEALOGISTE_GRAMPS_TACHES=true`) ; `contexte_seul` : `file: null` et `motif_file` |
| autres | `contexte_seul` : `plafond_gps`, `echelle`, `recoupe_fenetre_depart` (années de l'élément et de la fenêtre) ; `meme_metier_a_l_arrivee` : `pays_arrivee` |

**Destination.** L'outil n'écrit rien : ni l'arbre, ni l'enquête, ni la file, aucune opération d'arbre ni jeton dans
sa sortie. Le versement à l'enquête passe par `enquete_noter` (classe écriture d'un état local, collecte sans
`budget` ni réouverture : `CONDITIONS`), la file par `propositions_deposer` ou `arbre_proposer` (classe
proposition) : laissé à l'appelant, l'outil reste en collecte. Une piste `contexte_seul` n'est jamais convertie en
proposition d'écriture ni en tâche de la file. Depuis #325 c'est un **verrou du code**, plus une consigne :
`depot.enquete_noter.piste` porte `"contexte_seul": true`, et l'enquête refuse d'en faire une tâche
(`enquete_reprendre(taches=true)` avec ou sans `elements` : rendue dans `refuses` avec le motif ; opération
`ajouter_tache` qui la référence refusée par `arbre_proposer` et `propositions_deposer` ; pas de tâche manuelle ni
de lien de tâche). Détail : [enquetes.md](enquetes.md#tâches-de-gramps-web-263).

**Sortie.** `outil`, `personne`, `regle_inference`, `regles`, `nb_pistes`, `pistes`, `regles_non_appliquees`
(règle et motif), `elements_non_retenus`, `contexte` (résumé de `contexte_local` : `resultat`, `nb_elements`,
`non_documente`, services en échec et écartés, tâches manuelles, `journal`), `fenetre_depart` (déterminée, texte,
avertissement), `journal` (synthèse `contexte`/`pistes_contexte`), `depot` (consigne), `avertissement`. Aucune
piste : `pistes: []` et `recherche_negative`, jamais une hypothèse libre.

Cas témoin du mineur (réponses enregistrées) : `h1` « Départ de France entre juillet 1906 et 17 septembre 1917 »
(`a_tester`, test : registre matricule, passeports, recensements, transcriptions, passagers, recensements,
naturalisation et conscription du pays d'arrivée) ; `h2` « Même profession après l'arrivée (États-Unis) : mineur,
attestée en 1904 » (`a_tester`) ; trois pistes `contexte_seul`, dont la notice Sudoc « Billy-Montigny au coeur de
la catastrophe minière de 1906 » (rattachement `non_demontre`, recoupe la fenêtre). Lieu non documenté : aucune
piste.

Limites : trois règles seulement ; la fenêtre ne couvre que le premier départ attesté (`emigration`) ; la
comparaison de métiers est littérale (casse et accents ignorés) ; `personne` est hors de l'identité « déjà fait »,
comme pour `contexte_local`.

## Rédaction et contrôle

<!-- #291, #324 -->

### Rédaction

<!-- #291 -->

Règle : **aucune phrase de contexte sans référence consultée.** Elle s'applique aux récits (`/genealogiste:recit`),
aux notes du coffre et aux billets de Gramps Web (`/genealogiste:billet`). Elle est portée par l'agent `redacteur`
(`agents/redacteur.md`), relue par le `verificateur`, et contrôlée par `contexte_verifier` ; pour un billet, le
contrôle est aussi fait par le code de la proposition (voir « Sorties »).

Une phrase de contexte n'est écrite que si elle reprend un élément rendu par `contexte_local` (ou une référence
rendue par `contexte_bibliographie` ou `presse_recherche`) dont la source est au registre des références
consultées. À défaut, elle est **omise**, et une ligne « contexte à documenter : … » va dans les questions ouvertes.
Quand aucun élément sourcé n'existe, le texte n'a **pas de section « Contexte »** : jamais de paragraphe de
remplissage.

**Structure du texte**, dans le format que `contexte_verifier` lit :

| Section | Contenu |
|---|---|
| titre, puis « Récit » | faits de l'individu ; chaque phrase factuelle porte son appel de note `[n]` vers une source de l'arbre ; le degré de certitude se lit dans la formulation (confirmé, probable, hypothèse, contradictoire) |
| « Contexte » (séparée ; absente s'il n'y a rien) | une phrase par élément, qui reprend son `enonce` mot pour mot entre guillemets « », avec son appel de note ; formulation selon le niveau de rattachement |
| « Hypothèses » (absente s'il n'y en a pas) | pistes de `pistes_contexte` : `hypothese` tel quel, au conditionnel ou précédé de « Hypothèse : », ce qui la fonde, et la source qui la trancherait (`test.sources`) ; une piste `contexte_seul` reste « non démontrée » |
| « Questions ouvertes » | contradictions, lacunes, prochaines sources ; « contexte à documenter : … » quand un contexte a été cherché sans résultat |
| « Notes et sources » | une note par ligne (`[n] citation`) ; pour une référence de contexte, `source.citation` de l'élément recopiée telle quelle, identifiant pérenne compris, au style de `GENEALOGISTE_CONTEXTE_STYLE_CITATION` : jamais recomposée |

**Formulation selon le niveau de rattachement** (`rattachement.niveau` de l'élément) :

| Niveau | Formulation | Gabarit |
|---|---|---|
| `atteste` | affirmative ; deux appels : la source de l'arbre qui porte sur l'individu (`rattachement.citation_arbre`) et la référence | `<fait de l'individu> [n] : « <enonce> » [m].` |
| `compatible` | « à la même époque et au même endroit… », sans lien causal ni mention de l'individu | `À la même époque et au même endroit : « <enonce> » [n].` |
| `non_demontre`, commune | « plus généralement… », sans mention de l'individu | `Dans la commune, plus généralement : « <enonce> » [n].` |
| `non_demontre`, au-delà de la commune (élément qui porte `mention`) | « plus généralement… », avec la mention de tendance générale | `Dans le département, plus généralement : « <enonce> » (tendance générale, ne prouve rien pour l'individu) [n].` |

**Pertinence.** Un élément n'entre dans le texte que s'il éclaire un fait de l'individu : lieu et date communs avec
un fait cité. Les éléments écartés par `contexte_local` (`ecartes`), les entrées d'index non sourcées
(`non_sources`) et les échelles sans élément (`non_documente`) ne sont jamais écrits comme contexte.

**Interdits**, dans tout le texte :

- causalité non démontrée entre le contexte et une décision de l'individu (connecteurs de la liste `CONNECTEURS`
  ci-dessous) : elle ne s'écrit que comme hypothèse, avec la source qui la trancherait ;
- sentiments, pensées, motifs ou détails de vie non sourcés ;
- généralisation d'une tendance à l'individu (liste `GENERALISATIONS`) ;
- anachronisme : élément hors des lieux de vie ou hors de la période de vie sourcée ;
- référence de mémoire : titre, auteur, date ou identifiant qui ne vient pas d'un outil.

**Vérification avant de rendre.** Le `redacteur` appelle `contexte_verifier(texte=<texte>, personne=<id>)` et
corrige jusqu'à `conforme: true`, en **retirant** la phrase ou en la **documentant** par un élément réellement
rendu, jamais en inventant une référence ni en sortant la phrase de la section « Contexte ». Les commandes
`/genealogiste:recit` et `/genealogiste:billet` refont l'appel sur le texte rendu ; le `verificateur`, quand un
texte lui est confié, contrôle en plus ce que le contrôle lexical ne voit pas (référence résolue, rien d'ajouté à
l'énoncé, portée, niveau de rattachement, anachronisme, phrase de contexte hors de sa section).

**Exemple** (texte conforme du cas témoin du mineur, `mcp/tests/fixtures/contexte/textes/` : les phrases de
contexte sont des titres de notices réelles, repris de `contexte_local` sur les réponses enregistrées ; les sources
de l'arbre sont fictives) :

```markdown
# Anselme WATTECAMPS (1881-1946)

## Récit

Anselme WATTECAMPS naît le 14 février 1881 à Billy-Montigny (Pas-de-Calais) [1]. Il est mineur à Billy-Montigny en 1904 [2]. Il réside à Denain (Nord) en juillet 1906 [3]. Il se trouve à Krebs (Oklahoma, États-Unis) le 17 septembre 1917 [4]. Il meurt le 3 novembre 1946 à Charleroi (Pennsylvanie, États-Unis) [5].

## Contexte

À la même époque et au même endroit : « Notice sur la compagnie des mines de Courrières, société anonyme - capital 6.000.000 de francs : siège social : Billy-Montigny (Pas-de-Calais) » [6].

Dans la commune, plus généralement : « Billy-Montigny au coeur de la catastrophe minière de 1906 : 1099 morts » [7].

Dans le département, plus généralement : « Écopolitiques ouvrières : enquête socio-environnementale dans les mines de charbon du Nord-Pas-de-Calais (fin XIXe-début XXe siècle) » (tendance générale, ne prouve rien pour l'individu) [8].

## Questions ouvertes

- Départ de France : entre juillet 1906 [3] et le 17 septembre 1917 [4] ; aucune source de l'arbre ne le date.
- Lien éventuel de l'individu avec les éléments de contexte ci-dessus : non démontré ; aucune source de l'arbre ne le relie à eux.

## Notes et sources

[1] Registres d'état civil de Billy-Montigny (fictif), Naissances 1881, acte n° 17.
[2] Registres de population de Billy-Montigny (fictif), Registre de population 1904, f° 88.
[3] Registres de population de Denain (fictif), Registre de population 1906, f° 41.
[4] Dossier administratif américain (fictif), Pièce n° 12.
[5] Certificats de décès de Pennsylvanie (fictif), Certificat n° 1946-0412.
[6] Notice sur la compagnie des mines de Courrières, société anonyme - capital 6.000.000 de francs : siège social : Billy-Montigny (Pas-de-Calais). Plouvier-Dekindt, 1900. [Consulté le 23 novembre 2026]. PPN 249145197. [Non renseigné : auteur, lieu d'édition.] [Notice seule, non lu.]
[7] BOURDON, Henri. Billy-Montigny au coeur de la catastrophe minière de 1906 : 1099 morts. Billy-Montigny : H. Bourdon, 1974. 223 p. [Consulté le 23 novembre 2026]. PPN 060478624. [Notice seule, non lu.]
[8] CABOT, Bastien. Écopolitiques ouvrières : enquête socio-environnementale dans les mines de charbon du Nord-Pas-de-Calais (fin XIXe-début XXe siècle). Thèse de doctorat. Paris, EHESS, 2022. [Consulté le 23 novembre 2026]. DOI 10.70675/2dbefc32z7f71z45f9zba14z182f3ef066ff. [Notice seule, non lu.]
```

Sans élément sourcé (cas du lieu non documenté) : aucune section « Contexte », et dans les questions ouvertes :

```markdown
- Contexte à documenter : contexte non documenté pour le lieu-dit des Quatre-Chênes entre 1850 et 1923 (aucune notice trouvée).
```

**Sorties.**

| Sortie | Forme | Contrôle |
|---|---|---|
| récit (`/genealogiste:recit`) | structure ci-dessus, titres `##` | consigne : `contexte_verifier(texte=…, personne=…)` par le `redacteur` puis par la commande ; le rapport est montré avec les phrases à corriger |
| note du coffre | section manuelle `## Contexte` de la fiche de la personne, hors des sections générées et avant `## Notes libres` ; appels en notes de bas de page (`[^c1]`, définies dans la section) ; écrite après accord de l'utilisateur ; hypothèses et « contexte à documenter » par `notes_ajouter` (`hypothese`, `a_faire`) | la régénération conserve la section telle quelle (test) ; consigne : `contexte_verifier(note=<id>)` ; voir [notes.md](notes.md#section-contexte-291) |
| billet de Gramps Web (`/genealogiste:billet`) | même structure, intertitres en gras seuls sur leur ligne (`**Contexte**`, `**Notes et sources**`…) ; privé par défaut, diff puis accord | **code** : la proposition est refusée si la section « Contexte » n'est pas conforme (ci-dessous) |

**Billet : `conforme: false` est bloquant, par le code.** Toute proposition (`arbre_proposer`,
`propositions_deposer`) qui crée un billet, change son texte ou le rend public passe par
`billets.controler_contexte` (appelé par `tree/ops.apply_ops`, pour `ajouter_billet`, `ajouter_source` ou `etiqueter`
avec l'étiquette `Blog`, et `modifier_source`) :

- texte **sans** section « Contexte » : aucun contrôle, aucun changement de comportement ;
- texte **avec** une section « Contexte » : l'opération doit donner `"personne": "<id>"` (individu du billet, sur
  `ajouter_billet`, `ajouter_source` ou `modifier_source`) ; le texte est contrôlé comme par `contexte_verifier`
  (mêmes règles, même registre). Non conforme, personne absente ou inconnue, registre indisponible : **refus**, avec
  le rapport dans le message d'erreur (rubriques signalées, phrases et motifs ; cinq signalements au plus par
  rubrique) ; conforme : le résumé de la proposition porte « section « Contexte » contrôlée … : conforme » ;
- le texte contrôlé est le Markdown donné à l'opération ; pour un billet déjà dans Gramps Web (rendu public sans
  changement de texte), ses intertitres, devenus du gras sans astérisques, sont reconnus quand la ligne est isolée
  et porte le nom d'une section (« Contexte », « Hypothèses », « Questions ouvertes », « Notes et sources »).

Limites de cette garantie : elle tient à la présence d'une section « Contexte » (une phrase de contexte écrite dans
le récit, hors de toute section « Contexte », n'est vue que si elle porte un connecteur causal, une généralisation,
un événement nommé des listes ou un appel vers une référence de contexte, et seulement quand le texte a par
ailleurs une section « Contexte ») ; un billet saisi dans l'interface de Gramps Web n'est pas contrôlé : en backend
`gramps` il est dans l'arbre et dans le miroir (`gramps_synchroniser`) tel quel, et seul son passage en public par
le plugin est contrôlé ; en backend `fichier`, `gramps_tirer` passe par le contrôle sans pouvoir donner `personne`,
si bien qu'un billet à section « Contexte » fait refuser tout le tirage (constat de #348, tests
`test_limite_billet_*` de `tests/test_contexte_recits.py`) ; les limites de `contexte_verifier` s'appliquent
(contrôle lexical : conforme ne veut pas dire vrai).

**Vivants.** Règle existante, inchangée : récit refusé pour une personne présumée vivante, billet public qui en
nomme une refusé, fiche masquée dans le coffre ; `contexte_local` et `pistes_contexte` n'envoient jamais de nom.

### contexte_verifier

<!-- #324 -->

`contexte_verifier(texte="", note="", personne="")` (classe **lecture** : aucune requête, aucune écriture ; code :
`contexte/verifier.py`, l'outil de `server.py` ne fait que lire le texte et appeler le module). Contrôle
**déterministe** d'un texte produit (note du coffre, récit, billet) : règles et listes fermées, jamais un jugement du
modèle.

| Argument | Rôle |
|---|---|
| `texte` | texte Markdown à contrôler |
| `note` | à la place de `texte` : id d'une fiche du coffre (`I1`, `F1`, `S1`) ou chemin relatif dans `GENEALOGISTE_NOTES_DIR` (confiné au répertoire) ; la fiche est lue telle quelle, **jamais générée** (absente : erreur, `notes_generer` la crée) |
| `personne` | id de l'arbre ; défaut : la personne de la fiche. Obligatoire : la portée se mesure sur ses faits **sourcés** (`requete.depuis_personne`, comme `contexte_local`) |

Aucun nom ne sort : l'outil est local, la garde des vivants (`GARDE_VIVANTS`) ne s'applique qu'aux outils réseau.

**Format lu** (celui du `redacteur` et de [notes.md](notes.md)) :

- sections : titre Markdown (`## Contexte`, `## Contexte historique`) ou ligne en gras seule (`**Contexte**`, billet de
  Gramps Web, où seuls gras, italique et liens sont interprétés) ; un intertitre plus profond reste dans la section ;
  autres sections reconnues : `Notes et sources` (ou `Notes`, `Sources`, `Références`, `Bibliographie`),
  `Hypothèses…`, `Questions ouvertes` ;
- appels de note : `[1]`, `[1, 3]`, `[2-4]` ou `[^cle]` ; un lien `[8](https://…)` n'est pas un appel ;
- notes : lignes `[1] citation`, `1. citation` (dans la section des notes) ou `[^cle]: citation` ; lignes de
  continuation indentées ;
- énoncés repris d'une source entre guillemets `« »` : leurs années et lieux comptent pour la portée, mais ils ne sont
  pas lus comme une affirmation du rédacteur (causalité, généralisation, lieu hors périmètre) ;
- ignorés : frontmatter, sections générées (`<!-- genealogiste:debut … -->` ou `sosa:`), commentaires HTML, blocs de
  code.

**Règles.**

| Rubrique | Où | Signalé |
|---|---|---|
| `phrases_sans_reference` | section « Contexte » | phrase sans appel de note ; « Contexte non documenté. » ou « contexte à documenter : … » en est dispensée |
| `references_non_consultees` | notes appelées dans « Contexte » | appel sans note ; note sans identifiant pérenne lisible (DOI, ARK, HAL, PPN, Handle, LCCN, Europeana ; URL seulement à défaut) ; identifiant absent du **registre des références consultées** (référence de mémoire). Une note qui contient le titre d'une source de l'arbre citée pour un fait de la personne est une **source individuelle**, pas une référence de contexte |
| `hors_portee` | « Contexte » | `periode` : année ou intervalle cité hors de la période de vie sourcée (anachronisme ; siècles en chiffres romains et événements nommés de la liste `EVENEMENTS` compris) ; `lieu` : département ou pays cité, hors guillemets, qui n'est pas un lieu de vie ; phrase appuyée sur une référence dont ni le texte ni le titre de la référence (registre) ne citent un lieu de vie (portée géographique non établie) ; période de vie inconnue : portée non vérifiable |
| `causalites` | tout le texte, sauf questions (`?`) et hypothèses déclarées | connecteur causal ou motif prêté (liste `CONNECTEURS`) appliqué à l'individu (prénoms, nom, il, elle, ils, elles, lui, possessif suivi d'un fait de vie de la liste `POSSESSIFS` ; tournures impersonnelles exclues) sans appel vers une source individuelle ; catégorie `causatif` (« le poussa à ») : toujours appliqué à l'individu |
| `formulations` | tout le texte (`generalisation`) ; récit, hors « Contexte », « Hypothèses », « Questions ouvertes » et notes (`hors_section`) ; « Contexte » (autres) | `generalisation` : marqueur de la liste `GENERALISATIONS` ; `hors_section` (#348) : phrase de contexte hors de sa section, reconnue à un appel vers une note de contexte (référence du registre, ou note appelée aussi dans « Contexte » ; une source de l'arbre n'en est pas une) ou à un événement nommé de la liste `EVENEMENTS`, sauf question ; `rattachement` : niveau déclaré `compatible` (« à la même époque et au même endroit ») ou `non_demontre` (« plus généralement », « à l'échelle du département… ») avec une affirmation sur l'individu, `atteste` (« (rattachement : attesté) ») sans source individuelle, ou affirmation sur l'individu appuyée sur une seule référence de contexte ; `mention` : élément d'échelle supérieure à la commune (département, pays de vie cités sans commune de vie) sans « tendance générale, ne prouve rien pour l'individu » |

Hypothèse déclarée : section « Hypothèses », ou phrase au conditionnel (`aurait`, `serait`, `pourrait`, `devrait`),
avec « peut-être », « il est possible que », « hypothèse ». Elle n'est pas contrôlée pour la causalité : c'est la
forme exigée par la méthode (§ 5, 6).

**Listes fermées** (`VERSION_LISTES = "2"`, `contexte/verifier.py`). Chaque entrée porte un exemple qui doit être
signalé et un contre-exemple qui ne doit pas l'être, tous deux testés (`tests/test_contexte_verifier.py` ;
`tests/test_contexte_recits.py` pour `EVENEMENTS` et `POSSESSIFS`). La version 2 (#348) ajoute neuf généralisations,
la liste `EVENEMENTS` et la liste `POSSESSIFS`, d'après des récits réellement rédigés (« Recette du 2026-11-24 »).

- `CONNECTEURS`, causal : à cause de, en raison de, poussé par, fuyant, c'est pourquoi, contraint par / de, fut (a
  été, est…) forcé de, se vit (fut…) obligé de, par conséquent, en conséquence, de ce fait, du fait de, grâce à,
  faute de, chassé par, pour fuir / pour échapper, attiré par, parce que, puisque, « , car », dû à, causé / provoqué
  par, ce qui explique ; causatif : l'amena / le conduisit / le poussa / l'obligea / le força / le contraignit / le
  décida / l'incita à ; motif prêté : dans l'espoir de, espérant, désireux de, rêvant de, par patriotisme
  (conviction, nécessité, ambition, misère, devoir, amour, idéal, désespoir, vocation).
- `GENERALISATIONS` : à cette époque, à l'époque, en ce temps-là, de tout temps, comme tous les, comme beaucoup
  de / la plupart de, comme ses contemporains, beaucoup de, la plupart des, en général, la vie était, était rythmée
  par, dans cette région (ces campagnes), nos ancêtres, typique ; version 2 : louait (vendait) ses bras, toute sa
  vie, jamais (avoir) quitté, traversa (connut) … régimes / guerres / révolutions / règnes, comme les … de son âge
  (temps, époque, condition, village…), cette (sa) génération, fait partie de ces, compte parmi les, tant d'autres.
- `EVENEMENTS` (version 2 ; sensibles à la casse et aux accents, années entre parenthèses quand elles sont fixes) :
  Révolution (française) (1789-1799), Ancien Régime (jusqu'à 1789), la Terreur (1793-1794), guerre(s) de Vendée
  (1793-1796), guerres napoléoniennes / Premier Empire (1803-1815), Code civil (1804), la Restauration (1814-1830),
  monarchie de Juillet (1830-1848), Second Empire (1852-1870), guerre franco-allemande / franco-prussienne
  (1870-1871), Commune de Paris (1871), Grande Guerre / Première Guerre mondiale / guerre de 14 (1914-1918), Front
  populaire (1936-1938), Seconde (Deuxième) Guerre mondiale / l'Occupation / la Libération (1939-1945), guerre de
  Corée (1950-1953), guerre d'Algérie (1954-1962), États généraux (1789) ; sans année : bataille (offensive, siège)
  de + nom propre, entrer (entrée) en guerre. Dans « Contexte », leurs années comptent pour la portée ; dans le
  récit, l'événement est signalé `hors_section`.
- `POSSESSIFS` (version 2) : son, sa, ses, leur(s) + départ, émigration, immigration, migration, exil, fuite,
  installation, arrivée, retour, venue, engagement, enrôlement, choix, décision, mariage, union, métier, décès,
  mort, disparition, parcours, destin, sort : la phrase vise l'individu (« son départ fut provoqué par… »).
- Formules : `FORMULE_COMPATIBLE`, `FORMULE_NON_DEMONTRE`, `FORMULE_ATTESTE`, `MENTION`, `ECHELLE_SUPERIEURE`,
  `HYPOTHESE`, `IMPERSONNELS` ; unités (`UNITES`) qui font d'un nombre autre chose qu'une année (« 1099 morts »).

Ajouter une entrée : la mettre dans la liste avec son exemple et son contre-exemple, incrémenter `VERSION_LISTES`,
relancer `tests/test_contexte_verifier.py` et l'évaluation ci-dessous (aucun faux positif sur les textes conformes).

**Sortie.**

```json
{"outil": "contexte_verifier", "personne": "I1", "version_listes": "2", "conforme": false,
 "contexte": "present | non_documente | absent", "publication_billet": "bloquée (conforme: false)",
 "phrases_sans_reference": [{"phrase": "…", "section": "Contexte"}],
 "references_non_consultees": [{"appel": "6", "identifiant": "doi:10.…", "note": "…", "phrase": "…", "motif": "…"}],
 "hors_portee": [{"phrase": "…", "type": "periode", "annees": [[1950, 1950]], "motif": "…"},
                 {"phrase": "…", "type": "lieu", "lieux": ["Belgique"], "motif": "…"}],
 "causalites": [{"phrase": "…", "section": "Récit", "connecteur": "a_cause_de", "categorie": "causal", "motif": "…"}],
 "formulations": [{"phrase": "…", "type": "generalisation | rattachement | mention | hors_section", "marqueur": "…", "niveau": "…",
                   "motif": "…"}],
 "mesures": {"phrases_contexte": 3, "phrases_sourcees": 3, "part_phrases_sourcees": 1.0, "references_citees": 3,
             "references_consultees": 3, "part_references_consultees": 1.0, "anachronismes": 0,
             "causalites_non_sourcees": 0},
 "periode_de_vie": [1881, 1946], "limites": ["…"], "rappel": "…", "source": {"texte": "fourni"}}
```

`conforme` est vrai seulement si les cinq rubriques sont vides. Les parts valent `null` sans phrase ni référence de
contexte (texte « contexte non documenté »). Arguments invalides, personne inconnue, note absente : `erreur`.

**Contrat de publication.** `conforme: false` est **bloquant** pour la publication d'un billet de Gramps Web : le
billet n'est pas proposé (`ajouter_billet`) tant que le rapport n'est pas conforme, et la proposition elle-même le
refuse (#291, « Rédaction », « Sorties ») ; pour une note du coffre ou un récit, le rapport est montré à
l'utilisateur avec les phrases à corriger. L'appel par le `redacteur`, le `verificateur`, `/genealogiste:recit` et
`/genealogiste:billet` est décrit dans « Rédaction » ; la commande `/genealogiste:contexte` et le branchement du
`chercheur` sont décrits dans « Parcours d'usage », en tête de ce document (#325).

**Limites** (rendues aussi dans `limites`) :

- détection lexicale par listes fermées : une paraphrase absente des listes n'est pas vue ; un mot des listes employé
  au sens propre peut être signalé (« grâce à », « chassé par », « fuyant » adjectif) ;
- découpage en phrases par la ponctuation finale (abréviations courantes, initiales et citations `« »` protégées) ; un
  paragraphe ou un élément de liste compte au moins pour une phrase ;
- « consultée » = présente au registre : le contrôle ne lit pas la source, ni la page citée, ni la pertinence de la
  référence pour la phrase (une notice de 1994 peut appuyer à tort une phrase sur 1914) ;
- période : années à quatre chiffres (1000-2099) et siècles romains ; un nombre suivi d'une unité ou précédé de
  « n° », « p. » n'est pas une année ; une date en lettres n'est pas vue ; un événement nommé sans année n'est vu que
  s'il est dans `EVENEMENTS` (« la guerre », « la catastrophe », un règne, une institution d'époque ne le sont pas) ;
- lieux : seuls les départements français et les pays de la table fermée de `normalize/pays.py` sont reconnus dans le
  texte, sensibles à la casse (« la Somme », rivière ou département ; « Somme toute ») ; une province, une région ou
  une commune étrangère au récit n'est vue que si rien d'autre ne situe la phrase ;
- l'individu est reconnu par ses prénoms, son nom, les pronoms personnels et un possessif suivi d'un fait de vie de
  la liste `POSSESSIFS` ; un autre possessif (« sa trace »), un pronom complément (« le trouver ») ne sont pas vus ;
  un « il » ou un possessif de la liste qui désigne autre chose que l'individu peut faire signaler une phrase ;
- phrase de contexte hors de la section « Contexte » : vue seulement par un appel vers une note de contexte ou un
  événement de `EVENEMENTS` ; un contexte écrit de mémoire dans le récit sans l'un ni l'autre (« loin des siens »,
  « un autre pays noir »), un détail de vie inventé, un fait déformé ne sont pas vus : le contrôle ne lit pas les
  sources de l'arbre, et ne contrôle pas que chaque phrase du récit porte une note ;
- section « Hypothèses » : non contrôlée (une hypothèse d'intuition, absente de `pistes_contexte`, n'est pas vue) ;
- source individuelle : reconnue au titre d'une source de l'arbre ; le contrôle ne vérifie pas que cette source dit
  la cause affirmée ;
- les énoncés entre guillemets ne sont pas lus comme affirmation : une affirmation glissée dans des guillemets échappe
  au contrôle lexical.

Un texte **conforme n'est pas un texte vrai** : le contrôle établit que chaque phrase de contexte renvoie à une notice
réellement récupérée, bornée au lieu et à la période, sans causalité ni généralisation lexicalement repérable. Il ne
remplace pas la relecture de chaque énoncé contre sa source.

### Évaluation « anti-invention »

<!-- #324 -->

Jeu : `mcp/tests/fixtures/contexte/textes/` (`ATTENDUS.json`), testé par `tests/test_contexte_verifier.py`
(`test_evaluation_anti_invention`, sans réseau). Pour chaque cas témoin, `contexte_local` est d'abord rejoué sur les
réponses réelles enregistrées : il inscrit au registre les références qu'il rend. Le texte **conforme** ne contient
aucun fait historique rédigé : chaque phrase de contexte cite **mot pour mot** l'`enonce` d'un élément rendu (titre
de notice réelle), avec la citation et l'identifiant de sa source ; le test le vérifie. Les textes **fautifs** ont un
défaut construit chacun, avec les formulations interdites des attendus (`ne_doit_pas_contenir`) quand le cas en donne.

Mesures sur les textes conformes :

| Cas | Éléments (`contexte_local`) | Phrases de contexte sourcées | Références consultées | Anachronismes | Causalités non sourcées |
|---|---|---|---|---|---|
| mineur (Billy-Montigny, 1881-1946) | 3 | 3/3 (100 %) | 3/3 (100 %) | 0 | 0 |
| cultivateur (Vouillé-les-Marais, 1720-1788) | 2 | 2/2 (100 %) | 2/2 (100 %) | 0 | 0 |
| soldat (Saint-Amand-Montrond, Belloy-en-Santerre, 1892-1916) | 0 : « contexte non documenté » | sans objet (aucune phrase) | sans objet | 0 | 0 |
| lieu non documenté (Gers, 1850-1923) | 0 : « contexte non documenté » | sans objet (aucune phrase) | sans objet | 0 | 0 |

Aucun signalement sur les quatre textes conformes (aucun faux positif). Les deux derniers n'ont pas de section
« Contexte », seulement « contexte à documenter » dans les questions ouvertes.

Défauts détectés sur les textes fautifs (rubriques qui signalent ; le test exige exactement celles-ci) :

| Défaut | mineur | cultivateur | soldat | lieu non documenté |
|---|---|---|---|---|
| phrase sans note | `phrases_sans_reference` | `phrases_sans_reference` | `phrases_sans_reference` (« est mort lors de l'offensive de ») | `phrases_sans_reference` + `formulations` : paragraphe générique (« dans cette région rurale du Sud-Ouest, la vie était rythmée par ») |
| référence absente du registre | `references_non_consultees` | `references_non_consultees` | `references_non_consultees` | `references_non_consultees` |
| anachronisme | `hors_portee` (Guerre de Corée, 1950) | `hors_portee` (Révolution française, 1789) | `hors_portee` (guerre franco-allemande, 1870) | `hors_portee` (Seconde Guerre mondiale, 1939) + `phrases_sans_reference` |
| causalité | `causalites` (« émigre à cause de la catastrophe de Courrières ») | `causalites` (« s'est installé à cause de ») | `causalites` (« s'est engagé par patriotisme ») | `causalites` (« a quitté la terre à cause de l'exode rural ») |
| généralisation | `formulations` (« à cette époque, beaucoup de mineurs émigraient ») | `formulations` (« à cette époque, les paysans vivaient pauvrement ») | `formulations` (« comme tous les poilus ») | voir « phrase sans note » |
| lieu hors périmètre | `hors_portee` (Charleroi (Belgique)) | `hors_portee` (Pas-de-Calais) | `hors_portee` (Pas-de-Calais, portée non établie) | `hors_portee` (Gascogne : portée non établie) + `references_non_consultees` |

23 textes fautifs, 23 détectés. Pour le lieu non documenté, aucune référence n'est consultée : un anachronisme ou un
lieu hors périmètre y est nécessairement aussi une phrase sans note ou une référence hors registre.

**Réponses enregistrées pour le cultivateur et le soldat** (manifestes `sudoc`, `bnf-catalogue`, `theses-fr`, le
2026-11-23, une requête par entrée, sans clé ni nom de personne, réductions déclarées dans `REDUCTIONS`) :

| Cas | Requête (`contexte_local`, échelle commune) | Réponse | Effet |
|---|---|---|---|
| cultivateur | thème par défaut (métier « laboureur »), Sudoc | 0 notice | rien |
| cultivateur | thème « prieur », Sudoc et catalogue de la BnF | une notice chacun : factum imprimé en 1727 (BnF) ou 1729 (Sudoc) dont le titre cite le prieur de Vouillé-les-Marais | deux éléments `compatible`, imprimés contemporains (`primaire`) |
| soldat | thème par défaut (« forgeron »), Sudoc et theses.fr | 0 notice | rien |
| soldat | thème « guerre », Sudoc | 9 notices | toutes écartées (cartes non textuelles, titres sans lieu de vie) ; six références inscrites au registre, aucune bornée |

Les attendus du soldat passent donc de `contexte_documente: true` à `false` (motif dans `contexte_documente_motif`) :
sur ces réponses, la sortie correcte est « contexte non documenté ». Ceux du cultivateur restent `true`, avec le
thème « prieur » ; la requête par défaut, par le métier, ne trouve rien.

**Recette manuelle (b) : récit réellement généré.** Hors CI, sur un arbre de travail contenant un cas témoin (import
du `.ged` de `mcp/tests/fixtures/contexte/` dans un répertoire de données jetable) :

1. `contexte_local(personne="I1")` (réseau réel) : noter les éléments rendus, ou « contexte non documenté ».
2. `/genealogiste:recit I1` : récit rédigé par le `redacteur`.
3. `contexte_verifier(texte=<récit>, personne="I1")` ; relever `conforme`, `mesures` et chaque signalement.
4. Relire à la main : chaque phrase de contexte reprend-elle un `enonce` de l'étape 1, avec la citation de sa
   source ? Aucune formulation des `ne_doit_pas_contenir` du cas ? Un signalement est-il un faux positif (le noter
   avec la phrase) ? Une phrase douteuse a-t-elle échappé au contrôle (le noter : limite de la détection lexicale) ?
5. Reporter dans l'issue : cas, date, version des listes, mesures, faux positifs et défauts manqués. Attendu :
   100 % de phrases sourcées, 100 % de références consultées, 0 anachronisme, 0 causalité non sourcée ; pour le lieu
   non documenté (et le soldat), aucune section « Contexte » et « contexte à documenter » dans les questions
   ouvertes.

### Recette du 2026-11-24 : récits réellement rédigés

<!-- #348 -->

Première exécution de la recette (b), **hors ligne** : pour chaque cas témoin, une `App` isolée sur une copie du
`.ged`, les outils appelés comme le fait `/genealogiste:recit` (`arbre_vivant`, `arbre_fiche`, `contexte_local`,
`pistes_contexte`, `contexte_bibliographie`, `lieu_historique`, `presse_recherche`), le réseau rejoué depuis les
réponses enregistrées (plan de rejeu de `textes/ATTENDUS.json` : thème « prieur » pour le cultivateur, « guerre »
pour le soldat). Écart avec la recette décrite ci-dessus : pas de réseau réel à l'étape 1, et pas de session
Claude Code lançant la commande ; le récit est rédigé par un modèle (claude-fable-5-2) à qui l'on donne
`agents/redacteur.md` et les sorties d'outils, d'un jet, sans retouche après contrôle. `presse_recherche` n'a rien
rendu (Gallica bloqué ou 404 dans les réponses enregistrées) : aucune référence de presse n'a été évaluée.

Jeu : `mcp/tests/fixtures/contexte/recits/` (14 récits, `MESURES.json`), testé par `tests/test_contexte_recits.py`.

| Lot | Récits | Consigne de rédaction |
|---|---|---|
| premier | `naturel` (4), `fluide` (4), `billet` (mineur, cultivateur) | consigne suivie strictement ; consigne suivie en cherchant la fluidité littéraire ; format billet |
| contre-épreuve | `contre_epreuve` (4) | récit volontairement relâché (le style prime sur la consigne), écrit après le dépouillement du premier lot et avant toute modification du code |

Chaque récit est passé à `contexte_verifier`, puis relu à la main phrase par phrase contre les règles du jalon
(référence citée seulement si elle est au registre ; le contexte oriente et ne conclut pas ; aucune généralisation
appliquée à l'individu sans source ; faits, déductions et hypothèses distingués ; consigne du `redacteur`).

**Mesures** (phrases hors notes ; défauts relevés à la main ; « détectés » : la phrase fautive est signalée) :

| Cas | Récits | Phrases | Défauts | Détectés, listes v1 | Détectés après le premier lot d'ajouts | Détectés, listes v2 | Échappés (v2) | Fausses alertes (v1 / v2) |
|---|---|---|---|---|---|---|---|---|
| mineur | 4 | 64 | 11 | 2 | 4 | 6 | 5 | 0 / 0 |
| cultivateur | 4 | 42 | 11 | 1 | 5 | 7 | 4 | 0 / 0 |
| soldat | 3 | 27 | 7 | 0 | 0 | 2 | 5 | 0 / 0 |
| lieu non documenté | 3 | 23 | 6 | 0 | 3 | 5 | 1 | 0 / 0 |
| **total** | 14 | 156 | 35 | 3 | 12 | 20 | 15 | 0 / 0 |

Par lot : premier lot, 20 défauts, 3 détectés en v1, 10 en v2 ; contre-épreuve, 15 défauts, 0 détecté en v1, 2 après
les ajouts tirés du premier lot (seule mesure hors échantillon : les deux appels de référence hors section), 10
après les ajouts tirés de la contre-épreuve elle-même. Avec les listes de la version 1, le contrôle voyait
3 défauts sur 35, et **12 des 14 récits étaient déclarés conformes**, dont les quatre contre-épreuves, les deux
billets et les récits fluides du soldat et du lieu non documenté ; avec la version 2, 20 sur 35, et 5 récits sont
déclarés conformes : les quatre `naturel` (celui du cultivateur porte le défaut de pertinence P1) et le `fluide` du
soldat, qui garde quatre défauts non vus.

Ce qui tient dans tous les récits, y compris relâchés : aucune référence de mémoire (toute note de contexte est au
registre : 100 %), aucune année hors période dans « Contexte », pas de section « Contexte » pour le soldat ni le
lieu non documenté, « contexte à documenter » dans les questions ouvertes. Les défauts sont **dans le récit**, pas
dans la section « Contexte » : c'est là que le contrôle ne regardait que les connecteurs et les généralisations.

**Défauts échappés restants** (version 2 ; identifiants de `MESURES.json`) :

| Nature | Exemples | Pourquoi le contrôle lexical ne les voit pas |
|---|---|---|
| contexte de mémoire dans le récit, sans note ni événement de la liste | « au cœur d'un autre pays noir » (C6), « quatre mois après la catastrophe » (C4), « deux années de guerre » (D15), « l'heure du conseil de révision » (D13) | aucune marque lexicale fermée ; demanderait de contrôler chaque phrase du récit contre les faits de l'arbre |
| détail de vie ou sentiment inventé | « loin des siens » (D16), « il rejoint le front avec les hommes de sa classe » (C11), « a vu son village se vider » (C16) | idem |
| fait déformé | « il tient un enfant sur les fonts d'une sépulture où le curé le qualifie de laboureur » (D7) | le contrôle ne lit pas les sources de l'arbre |
| causalité par paraphrase ou juxtaposition, déduction non fondée | « Rien d'étonnant, dès lors, à le trouver mineur » (C2), « Il n'aura guère le temps d'exercer ce métier : … mobilisé » (D14), « Il ne reviendra sans doute pas en France, puisqu'il s'éteint… [5] » (D1) | paraphrase hors liste ; une note individuelle dans la phrase dispense du contrôle de causalité |
| section « Hypothèses » | hypothèse d'intuition absente de `pistes_contexte` (D11), paraphrase qui ajoute à un énoncé (D4) | section non contrôlée |
| section « Contexte » | phrase hors gabarit, commentaire ajouté à l'énoncé (D10) ; deux notices du même imprimé comptées comme deux éléments sourcés (P1) | la formule de rattachement n'est pas exigée ; la pertinence d'une référence n'est pas jugée |

**Limites examinées** (#348) :

| Limite | Reproduite | Exemple minimal | Sort |
|---|---|---|---|
| paraphrase hors liste | oui (D18, C3, C7, C10, C14, C15 ; C2, D14) | « Journalier, il louait ses bras à la journée. » | partiellement corrigée : neuf généralisations ajoutées ; la causalité par paraphrase ou juxtaposition reste (`test_limite_paraphrase_hors_liste`) |
| événement nommé sans année | oui (D8, D12, C9, C12, C5) | « Il meurt à la veille de la Révolution [3]. » | corrigée pour une liste fermée (`EVENEMENTS`) ; un événement hors liste ou évoqué sans nom reste (`test_limite_evenement_nomme_sans_annee`) |
| possessifs | pas dans les récits (les possessifs y portent des déductions sourcées ou des questions) ; oui sur exemple | « Son départ fut provoqué par la crise minière. » | corrigée pour une liste fermée de faits de vie (`POSSESSIFS`) ; un possessif hors liste reste |
| pertinence d'une référence consultée | oui (P1) | une référence du registre sous un énoncé qu'elle ne porte pas : conforme | laissée : demande de lire la source ou de comparer l'énoncé à ce que l'outil a rendu (issue de suivi) |
| phrase de contexte hors de la section « Contexte » d'un billet | oui (D5, D12 ; C1, C8 dans un récit) | « En 1906, l'année de la catastrophe minière qui endeuille sa commune natale [7], il réside… » | partiellement corrigée : `hors_section` (appel d'une note de contexte, événement nommé) ; un billet sans section « Contexte » n'est toujours pas contrôlé à la proposition (issue de suivi) |
| billet saisi dans Gramps Web ou arrivé par synchronisation | oui, et constat nouveau | billet fautif saisi dans l'interface : présent dans l'arbre et le miroir sans contrôle (backend `gramps`) ; `gramps_tirer` refusé en entier faute de `personne` (backend `fichier`) | laissée : demande une conception (où contrôler, comment désigner la personne, que faire d'un billet non conforme déjà en base) ; issue de suivi |

**Portée de cette recette.** Quatorze récits, un seul modèle, et le même modèle a rédigé, relevé les défauts et
proposé les ajouts : c'est une auto-évaluation. Le rédacteur connaissait les listes de la version 1 (elles sont dans
ce document). Les listes de la version 2 sont ajustées sur ces mêmes récits : « 20 sur 35 » mesure cet ajustement,
pas la détection sur un récit nouveau (la seule mesure hors échantillon est 2 sur 15). Aucune fausse alerte n'a été
relevée, mais sur 14 textes seulement ; les ajouts (« toute sa vie », « tant d'autres », `bataille_de`, `hors_section`)
signaleront aussi des phrases légitimes, par exemple un événement que la source individuelle nomme. La détection
reste lexicale : un récit déclaré conforme n'est pas un récit conforme, il reste à relire phrase par phrase contre
ses sources. La recette avec réseau réel et la commande `/genealogiste:recit` lancée dans une session n'ont pas
été exécutées.
