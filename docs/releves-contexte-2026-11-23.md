# Relevé des services de contexte, 2026-11-23

Sondage et recette de contrat des services de contexte historique (#323), exécutés le 2026-11-23 entre 12 h 30 et
12 h 35 UTC depuis le poste du mainteneur. **Rapport seulement** : ce relevé ne modifie pas
`referentiels/sources_contexte.json`, dont les relevés (`site_repond_le`, `releve`) restent ceux de #285 ; un
changement de mode ou de protection se décide sur plusieurs relevés, pas sur celui-ci.

Trois exécutions, une requête (ou deux) par service, débit, cache et coupe-circuit du plugin ; aucun contournement :

| Exécution | Commande | Ce qu'elle mesure |
|---|---|---|
| Sondage | `uv --directory mcp run python scripts/verifier_archives.py --contexte-seulement` | le service répond-il (HEAD, repli GET sans lecture du corps, sans clé) ; les sites d'archives et les sites tiers ne sont pas sondés |
| Recette de contrat | `make test-contexte` | l'analyseur lit-il la réponse réelle (forme des champs lus, jamais le contenu) |
| Rejeu des réponses | `make enregistrer-contexte` (mode `--verifier`, rien écrit) | la réponse réduite a-t-elle encore la forme de la réponse enregistrée |

## Résultat par service

AVERT : service protégé, limité, muet ou à clé requise (jamais un échec). KO : service actif par défaut qui ne répond
pas. « — » : pas d'analyseur, pas de recette.

| Service | Sondage | Recette de contrat | Rejeu `--verifier` | Observation |
|---|---|---|---|---|
| `HAL` | OK 200 | OK (analyseur Solr) | forme conforme (2 réponses) | |
| `ISIDORE` | OK 200 | OK (analyseur REST) | forme conforme | |
| `PERSEE` | OK 200 (`verb=Identify`) | OK (analyseur OAI-PMH, GetRecord) | forme conforme | OAI-PMH seulement, pas de recherche |
| `OPENEDITION` | OK 200 | — | — | analyseur OAI prêt, pas de réponse enregistrée ni d'outil |
| `SUDOC` | OK 200 (`operation=explain`) | OK (analyseur SRU UNIMARC) | forme conforme (2 réponses) | |
| `IDREF` | OK 200 | — | — | analyseur non livré (#286) |
| `THESES-FR` | OK 200 | OK (analyseur REST) | forme conforme | |
| `BNF-CATALOGUE` | OK 200 | OK (analyseur SRU Dublin Core) | forme conforme (2 réponses) | |
| `DATA-BNF` | OK 200 | — | — | pas d'analyseur |
| `OPENALEX` | OK 200 | — | — | analyseur non livré (#286) |
| `CROSSREF` | OK 200 | OK (analyseur REST) | forme conforme | |
| `EUROPEANA` | AVERT 400, clé requise, sondé sans clé | — | non rejoué (extrait du site public) | aucun analyseur : aucune clé pour enregistrer une réponse réelle de l'API |
| `NAKALA` | OK 200 | — | — | pas d'analyseur |
| `WIKIPEDIA` | OK 200 | — | — | |
| `WIKIDATA` | OK 200 | OK (SPARQL P374 vers P8422 : une liaison lue) | **AVERT 502**, puis **AVERT 429** (`Retry-After: 120`) au second rejeu | service instable ; chaque rejeu supplémentaire a aggravé la limitation, arrêt après deux tentatives |
| `INSEE-MELODI` | **KO** `RemoteProtocolError` (connexion coupée sans réponse) | **AVERT** (même erreur, 2 tentatives) | **AVERT** `RemoteProtocolError` (deux rejeux) | répondait en 200 le 2026-11-21 et le 2026-11-23 à 10 h (curl) ; coupure systématique depuis le client du plugin au moment de ce relevé, cause non établie (aucun contournement tenté) |
| `IGN-GEOPLATEFORME` | OK 200 (`GetCapabilities`) | OK (couches retenues lues) | forme conforme (3 réponses) ; 11 champs nouveaux hors réduction (`OperationsMetadata`) | |
| `CULTURE-DATA` | OK 200 | — | — | pas d'analyseur |
| `GALLICA` | AVERT 403 Cloudflare | AVERT : `bloque_antirobot`, une requête, coupe-circuit | non rejoué (enregistré en 403) | SRU toujours bloqué ; pas de réponse 200 réelle (exception du test, voir ci-dessous) |
| `CHRONICLING-AMERICA` | AVERT 403 Cloudflare | — | non rejoué (enregistré en 403) | lien seulement |
| `NARA` | OK 200 (racine de l'API) | — | — | lien seulement : API non qualifiée |
| `APE` | AVERT 403 (Cloudflare) | — | — | lien seulement |
| `FRANCEARCHIVES` | OK 200 | — | — | lien seulement : pas d'API qualifiée |
| `CASSINI-EHESS` | AVERT `ConnectTimeout` (lien seulement) | — | — | muet comme aux deux relevés précédents (#322) |
| `RETRONEWS` | OK 200 | — | non rejoué (extraits manuels) | lien seulement |
| `API-GEO` (hors référentiel) | — | OK (centre de la commune lu) | forme conforme | |
| `COG-INSEE` (hors référentiel) | — | OK (commune 62133 trouvée dans le COG) | forme conforme (2 fichiers) | |

Recette `make test-contexte` : **11 réussis, 2 ignorés (AVERT)**, 16 s. Les deux AVERT sont INSEE-MELODI (connexion
coupée) et GALLICA (403 Cloudflare, blocage rendu tel quel par `presse_recherche`). Aucun échec de forme : aucun
analyseur n'a reçu de réponse illisible.

Rejeu `make enregistrer-contexte` : 18 requêtes émises pour 25 réponses décrites ; **16 formes conformes** (10
services), aucune dérive ; 2 AVERT (Melodi, Wikidata) ; 7 non rejouées (2 enregistrées en 403 pour des services
protégés, 4 extraits faits à la main, 1 requête Melodi laissée de côté après la coupure). Les réductions du script
reproduisent donc, sur des réponses réelles, celles des manifestes. Un second rejeu limité à Melodi et Wikidata
(une requête chacun) a donné les mêmes AVERT (coupure ; 429).

## Constats

- **Instabilité** : Wikidata (502 puis 429 en rejeu, 200 au sondage et à la recette) et INSEE Melodi (coupure du
  client) sont les services fragiles de ce relevé. Le plugin les traite déjà en AVERT (recette) ou en erreur tracée
  (`lieu_historique` : niveau « inconnu » avec le motif). Rien n'est changé au référentiel : deux services
  `api` actifs par défaut en panne le même jour ne justifient pas le repli « lien seulement » ; à reprendre si la
  panne de Melodi persiste sur plusieurs relevés.
- **Protégés** : Gallica et Chronicling America toujours en 403 Cloudflare, APE en 403 ; Cassini toujours muet.
  Conforme au référentiel.
- **Exception à la règle « aucun analyseur sans réponse réelle »** : Gallica (SRU et ContentSearch), voir la
  sous-section « Recette et réponses enregistrées » de [contexte-historique.md](contexte-historique.md) et
  `EXCEPTIONS_ANALYSEUR` dans `tests/test_contexte_reponses.py`.
- **Limite du sondage** : un `OK` dit que le service répond, pas que l'analyseur lit encore ses champs ; c'est la
  recette qui le vérifie.
- **Charge** : trois exécutions en cinq minutes ont suffi à faire passer Wikidata en 429. La recette n'est pas
  faite pour être enchaînée ; elle s'exécute à la main, rarement, hors CI.

## Sources

- Sondage : `scripts/verifier_archives.py --contexte-seulement`, 25 services du référentiel.
- Recette : `mcp/tests/test_contexte_live.py` (marqueur `contexte_live`).
- Rejeu : `mcp/scripts/enregistrer_contexte.py --verifier`.
- Référentiel de départ : [contexte-historique.md](contexte-historique.md), « Services au 2026-11-23 ».
