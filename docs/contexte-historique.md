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
| `EUROPEANA` | Europeana (Search API) | rest | requise | primaire | EU | clé requise, à activer | 2026-11-21 : 200 avec la clé de démonstration (non embarquée) ; 2026-11-23 : 400 sans clé |
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
| `GENEALOGISTE_CLE_EUROPEANA`, `GENEALOGISTE_CLE_OPENALEX`, `GENEALOGISTE_CLE_NARA`, `GENEALOGISTE_CLE_APE` | clés d'API personnelles. Europeana exige la sienne (la clé de démonstration n'est pas embarquée) ; OpenAlex fonctionne sans ; NARA et APE restent en lien seulement tant que leur API n'est pas qualifiée. |
| `GENEALOGISTE_CROSSREF_MAILTO` | **vide par défaut**. Une adresse courriel est une donnée personnelle : elle n'est envoyée à Crossref que si l'utilisateur la renseigne. |

Plafond journalier et intervalle par hôte : `GENEALOGISTE_PLAFONDS_JOUR` et `GENEALOGISTE_DEBITS` (hôte=valeur),
sinon `GENEALOGISTE_PLAFOND_JOUR_DEFAUT` et `GENEALOGISTE_DEBIT_DEFAUT`.

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
réponse 200 réelle est enregistrée. Europeana n'a pas d'analyseur (aucune clé), donc pas d'exception.

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
| Europeana | `services.refus` (activation, `GENEALOGISTE_CLE_EUROPEANA`) ; **aucun analyseur** : pas de réponse réelle de l'API enregistrée (aucune clé disponible, clé de démonstration non utilisée). Avec une clé, `sans_analyseur`, aucune requête | recherche du site public (`/fr/search?query=`, vérifiée, HTTP 200) |
| Chronicling America | lien seulement (403 Cloudflare, une tentative le 2026-11-23) | page de la collection |
| Retronews | lien seulement (pas d'API publique) | recherche avancée pré-remplie (`/search?…&q=` : base64 du JSON encodé, forme relevée sur le site) ; période à régler dans le site |

Gallica figure en `lien_seulement` dans le référentiel de contexte (SRU en 403) : c'est le mode des services de
contexte (`contexte_bibliographie`, `lieu_historique`), pour lesquels `services.refus` répond « lien seulement ».
`presse_recherche` n'ouvre pas pour autant un nouvel accès : il passe par le même client que `gallica_recherche`
(`sources/gallica.py`), sans appeler `services.refus("GALLICA")`, avec le coupe-circuit et les plafonds du client
commun, et un blocage est rendu tel quel. Le référentiel le dit dans la `notes` de l'entrée (#323) ; son mode ne
change pas, et `services.refus` non plus (son motif « jamais interrogé par le plugin » reste vrai pour ces autres
outils seulement). Réponses réelles réduites et manifestes :
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
Cassini redéposée sur Nakala (`doi:10.34847/nkl.e0556oog`, CC BY-NC-SA 4.0, ni embarquée ni interrogée). Ne jamais
compléter un niveau « inconnu » de mémoire.

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
| index Wikidata (`index_wikidata`, gabarit `evenements_commune`) | commune | entrée de l'index dont une référence externe (BnF `P268`, IdRef `P269`, Persée `P8758`) présente dans la réponse est déjà au registre | titre de cette référence, jamais le libellé Wikidata |
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

| Gabarit | État | Réponses réelles enregistrées (`reponses/WIKIDATA/`, 2026-11-23) |
|---|---|---|
| `evenements_commune` | livré | Billy-Montigny 1881-1946 (vide, 3,2 s), Courrières 1881-1946 (une entrée sans identifiant externe, 2,6 s), Belloy-en-Santerre 1892-1916 (vide, 2,5 s) |
| `evenements_departement` | non livré | deux formes essayées une fois chacune (`P2586` puis `P131*` ; communes du département par le préfixe du code INSEE) : délai dépassé (60 s) ; consigné dans `MANIFESTE.json` (`sans_reponse`), aucune requête émise |

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
(population), sauf les cartes ; pas de gabarit Wikidata départemental ; `personne` est hors de l'identité « déjà
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
| `depot` | `null` pour une piste déjà tranchée ; sinon `enquete_noter` (paramètres `piste` et `personnes`, à compléter par `enquete`) et `file` : chemin vers la file comme **tâche** (`enquete_reprendre(taches=true, elements=…)`, opération `ajouter_tache`, backend gramps et `GENEALOGISTE_GRAMPS_TACHES=true`) ; `contexte_seul` : `file: null` et `motif_file` |
| autres | `contexte_seul` : `plafond_gps`, `echelle`, `recoupe_fenetre_depart` (années de l'élément et de la fenêtre) ; `meme_metier_a_l_arrivee` : `pays_arrivee` |

**Destination.** L'outil n'écrit rien : ni l'arbre, ni l'enquête, ni la file, aucune opération d'arbre ni jeton dans
sa sortie. Le versement à l'enquête passe par `enquete_noter` (classe écriture d'un état local, collecte sans
`budget` ni réouverture : `CONDITIONS`), la file par `propositions_deposer` ou `arbre_proposer` (classe
proposition) : laissé à l'appelant, l'outil reste en collecte. Une piste `contexte_seul` n'est jamais convertie en
proposition d'écriture ni en tâche de la file ; notée dans une enquête, ne pas la passer à
`enquete_reprendre(taches=true)` (choisir les éléments par `elements`).

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
