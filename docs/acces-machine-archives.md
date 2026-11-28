# Accès machine aux services d'archives et aux API

Relevé du **18 novembre 2026** (#119). Pour chaque service interrogé par le plugin ou utile à la recherche
française : protocole d'accès machine, clé, licence ou CGU, limites **publiées**, protections observées et
source. Complète la [politique d'accès par service](securite.md#politique-daccès-par-service) (#211) et le
[référentiel des archives](archives.md).

## Règles de ce relevé

- **Rien n'est déduit.** Une limite n'est portée que si la page officielle la publie en chiffres ; sinon
  « non publiée » ou « non trouvée ». Une page bloquée est notée « inaccessible » avec le motif, sans
  contournement.
- Lecture de pages de documentation, de CGU et de `robots.txt` uniquement ; aucune donnée personnelle ni
  requête de recherche nominative n'a été envoyée aux services.
- Les citations sont prises sur la page indiquée, consultée le 2026-11-18. Celles marquées **(relu)** ont
  été relues une seconde fois mot à mot ; les autres proviennent d'une lecture automatisée unique et sont à
  relire avant d'en faire une valeur appliquée.
- Une valeur de `politique_acces.py` n'est `sourcee` que si la valeur **appliquée** est publiée par le
  service. Une limite publiée plus permissive que la valeur appliquée reste information
  (`limites_documentees`), la valeur prudente du plugin est conservée.

## Synthèse pour le plugin

| Hôte | Valeur appliquée | Provenance (2026-11-18) | Justification |
|---|---|---|---|
| `deces.matchid.io` | 1 s | **sourcée** | « L'API unitaire est limité à une requête par seconde. » ([matchID](https://matchid.io/link-api), relu) |
| `geo.api.gouv.fr` | 0,1 s | **sourcée** | « 10 requêtes par seconde et par IP pour l'API Découpage administratif » ([FAQ data.gouv.fr](https://guides.data.gouv.fr/foire-aux-questions), relu) ; contradiction avec la [fiche data.gouv.fr](https://www.data.gouv.fr/dataservices/672cf6946a8456f417812b0f) (« 50 appels / seconde / IP », relu) : la plus stricte est retenue |
| `recherche-anom.culture.gouv.fr` | 5 s | **référentiel** (`intervalle_requetes` d'ANOM) | `Crawl-delay: 5` dans [robots.txt](https://recherche-anom.culture.gouv.fr/robots.txt) (relu) |
| `query.wikidata.org` | 1 s | historique | Limites publiées exprimées en temps de calcul, pas en requêtes/s (voir plus bas) |
| `api.wikitree.com` | 1 s | historique | Aucun chiffre lisible sur une page officielle accessible |
| `gallica.bnf.fr` | 1 s | historique | Aucune limite chiffrée publiée sur api.bnf.fr |
| `www.insee.fr`, `n2t.net` | 1,5 s | défaut | Aucune limite chiffrée publiée |
| tous | plafond 1000/jour, concurrence 1 | défaut | Aucun service relevé ne publie de plafond journalier applicable ; la concurrence 1 est une contrainte du plugin, inférieure aux 5 requêtes parallèles admises par Wikidata |

**Bilan** : sur les 21 valeurs de la table `SERVICES` (7 hôtes × intervalle, plafond, concurrence), **2 sont
sourcées** (intervalles matchID et API Géo), 19 restent historiques ou par défaut. Côté référentiel, un
`intervalle_requetes` sourcé est ajouté (ANOM).

## API et sources interrogées par le plugin

| Service | Accès machine | Clé | Licence / CGU | Limites publiées | Protections, robots.txt | Source |
|---|---|---|---|---|---|---|
| matchID (`deces.matchid.io`) | API REST (Swagger `deces/api/v1/docs`), recherche unitaire et appariement `search/csv` | Aucune pour un « nombre limité d'appels » ; jeton gratuit « au-dela d'une centaine d'appels » (une réponse de l'éditeur sur data.gouv.fr du 2024-06-04 parle de 20 requêtes : non concordant), valable 30 jours, renouvelable 12 mois | Site : etalab-2.0 ; code : LGPL-3.0 ; données INSEE : Licence Ouverte 2.0, exclusion du fichier d'opposition | Recherche : 1 requête/s, avec ou sans jeton (relu) ; avec jeton, nombre d'appels illimité ; `search/csv` : 50 à 100 requêtes/s ; data.gouv.fr : « burst à 20 requêtes » | `robots.txt` : seul `AhrefsBot` exclu | [link-api](https://matchid.io/link-api), [réutilisation data.gouv.fr](https://www.data.gouv.fr/reuses/api-des-personnes-decedees), [jeu INSEE](https://www.data.gouv.fr/datasets/fichier-des-personnes-decedees) |
| WikiTree (`api.wikitree.com`) | API REST en lecture | Non ; `appId` conseillé (« API queries without an id will be subject to strict rate limits ») ; connexion seulement pour les profils privés | Non trouvée (pages d'aide : HTTP 403) | Aucun chiffre dans le README. Un extrait de moteur de recherche attribue 200 requêtes/min et 4000/heure à `Help:App_Policies` : **non sourcé** (page en 403) | `robots.txt` : HTTP 202 corps vide (défi probable) | [README](https://github.com/wikitree/wikitree-api/blob/main/README.md) |
| Gallica (`gallica.bnf.fr`) | SRU 1.2 (`maximumRecords` ≤ 50), API Document (Issues, Pagination, ContentSearch, texteBrut, ALTO), IIIF Image et Presentation, OAI-PMH (`oai.bnf.fr/oai2/OAIHandler`) | Aucune mentionnée | Métadonnées : Licence Ouverte depuis le 2014-01-01 ; contenus : [conditions d'utilisation](https://gallica.bnf.fr/edit/und/conditions-dutilisation-des-contenus-de-gallica) inaccessibles (403) | Non publiées | Cloudflare : `robots.txt` et CGU bloqués (« Sorry, you have been blocked ») ; défi 403 sur un manifeste IIIF le 2026-11-17 ([relevé](releves-archives-2026-11-17.md)) | [API de recherche](https://api.bnf.fr/fr/api-gallica-de-recherche), [API Document](https://api.bnf.fr/fr/api-document-de-gallica), [IIIF](https://api.bnf.fr/fr/api-iiif-de-recuperation-des-images-de-gallica), [OAI-NUM](https://www.bnf.fr/fr/recuperer-des-notices-descriptives-de-documents-numerises-en-dublin-core-oai-num) |
| Wikidata Query Service (`query.wikidata.org`) | SPARQL | Non | Données structurées : CC0 | Par client (User-Agent + IP) : 60 s de calcul par 60 s, 30 requêtes en erreur/min, 5 requêtes parallèles par IP, délai maximal 60 s ; 429 + `Retry-After`, bannissement temporaire en cas de récidive (relu) | User-Agent conforme exigé, sinon blocage ; `robots.txt` : `Disallow: /sparql` (relu) — vise les robots d'indexation, l'usage d'API est documenté par le manuel | [User Manual](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual#Query_limits), [User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy), [Licensing](https://www.wikidata.org/wiki/Wikidata:Licensing) |
| API Géo (`geo.api.gouv.fr`) | REST (découpage administratif) | Non (« Ouvert ») | Fiche : « Licence non renseignée » ; [CGU](https://geo.api.gouv.fr/cgu) : refus d'accès possible « en cas d'usage abusif » | 10 requêtes/s/IP (FAQ) **ou** 50 appels/s/IP (fiche) : contradictoire (relu) | `robots.txt` sans restriction | [FAQ](https://guides.data.gouv.fr/foire-aux-questions), [fiche](https://www.data.gouv.fr/dataservices/672cf6946a8456f417812b0f) |
| INSEE, fichiers du COG (`www.insee.fr`) | Téléchargement de fichiers CSV | Non | Licence Ouverte 2.0, mention « Source : Insee » ; extraction automatique admise si elle « ne porte pas atteinte au bon fonctionnement du site », l'INSEE pouvant limiter fréquence et nombre de requêtes | Aucun chiffre | `robots.txt` : `Disallow: *.csv`, `*.zip`, `*.xls(x)`, `/*/ddl/` (relu) ; les URL COG par défaut (`…/fichier/7766585/*.csv`) sont dans ce périmètre : **à arbitrer** (téléchargement ponctuel déclenché par l'utilisateur, mis en cache) | [mentions légales](https://www.insee.fr/fr/information/2008466) |
| N2T (`n2t.net`) | Résolveur ARK, registre des NAAN | Non trouvée | Non trouvée | Non trouvées | `robots.txt` absent (404) | [n2t.net](https://n2t.net/) |

## Services d'archives

| Service | Accès machine | Clé | Licence / CGU | Limites publiées | Protections, robots.txt | Source |
|---|---|---|---|---|---|---|
| FranceArchives | SPARQL et dump RDF semestriel annoncés (source secondaire : [SWIB23](https://swib.org/swib23/slides/07_Fabien%20Amarger_Slides.pdf)) | Non trouvée | « Licence ouverte (type Etalab) » selon un extrait de moteur de recherche de la page open data, non lue | Non trouvées | **Inaccessible** : site, `robots.txt`, `sparql.` et `data-dump.` répondent par une page exigeant JavaScript et cookies | [open data](https://francearchives.gouv.fr/fr/open_data) (non lue) |
| Archives nationales — Garance | SPARQL `https://sparql.archives-nationales.culture.gouv.fr/garance/sparql` | Non trouvée | Réutilisation libre et gratuite, commerciale ou non, avec mention « Archives nationales de France », Garance et date des données ; documentation CC BY-NC-SA 4.0 | Non trouvées | `robots.txt` absent (404) | [SPARQL](https://rdf.archives-nationales.culture.gouv.fr/garance/pages/en/sparql), [mentions](https://rdf.archives-nationales.culture.gouv.fr/garance/pages/en/legal) |
| Archives nationales — SIV | Pas d'API publiée | Compte pour l'espace sécurisé | Réutilisation libre et gratuite des documents communicables, mention d'origine ; espace sécurisé : usage personnel, diffusion internet interdite | Non trouvées | `robots.txt` : `Disallow: /` (tout le site exclu des robots) | [CGU SIV](https://www.siv.archives-nationales.culture.gouv.fr/siv/conditions-generales-d-utilisation), [réutilisation](https://www.archives-nationales.culture.gouv.fr/quelles-sont-les-modalites-de-reproduction-et-de-reutilisation) |
| ANOM | Pas d'API publiée | Non trouvée | Non lues | `Crawl-delay: 5` (relu) → `intervalle_requetes` = 5 s | Défi **Anubis** sur la page d'accueil (observé, curl) ; `robots.txt` : `Disallow` `/data/`, `/img/`, vues `/archive(s)/*/view:*`, recherches et résultats paramétrés | [robots.txt](https://recherche-anom.culture.gouv.fr/robots.txt) |
| Mémoire des hommes | Non trouvé | Non trouvée | Licences gratuite et payante (documents `.doc`) repérées, non lues | Non trouvées | **Inaccessible** : certificat TLS expiré le 2026-11-18 | — |
| AD59 Nord (Naoned, Mnesys) | `/visualizer/api` interne non documentée (voir [visionneuse-ad59.md](visionneuse-ad59.md)) ; `/oai-pmh` présent, non documenté | Non pour la consultation ; espace personnel avec hCaptcha | CGU : « ne pas télécharger massivement des Documents » ; « Aucune extraction intégrale ou substantielle […] sans l'accord préalable et écrit de l'éditeur » ; réutilisation fixée par délibération du 27 mars 2017 (licence non nommée sur la page) | Non publiées | `robots.txt` : `Disallow` `/private/`, `/oai-pmh`, `/user/` (relu) ; `/visualizer` non exclu ; Cloudflare + hCaptcha relevés (référentiel) | [CGU](https://archivesdepartementales.lenord.fr/page/conditions-generales-d-utilisation), [réutilisation](https://archivesdepartementales.lenord.fr/page/reutilisation-des-informations-publiques) |
| AD25 Doubs | Même plateforme que AD59 | Non trouvée | Licence de réutilisation à souscrire pour tout usage « non exclusivement personnel » ; même clause d'extraction substantielle | Non publiées | `robots.txt` : `/private/`, `/oai-pmh`, `/user/` | [CGU](https://archives.doubs.fr/page/conditions-generales-d-utilisation) |
| AD39 Jura | Même plateforme que AD59 | Non trouvée | Etalab 2.0 hors droit d'auteur ; CGU : pas de téléchargement massif, usage non marchand et personnel ; demande au service pour les « cotes entières de plus de 100 fichiers par cote » (procédure, pas un quota) | Non publiées | `robots.txt` : `/private/`, `/oai-pmh`, `/user/` | [CGU](https://archives39.fr/page/conditions-generales-d-utilisation), [réutilisation](https://archives39.fr/page/reproduire-les-archives-reutiliser-les-donnees) |

## Plateformes généalogiques et données ouvertes

| Service | Accès machine | Clé | Licence / CGU | Limites publiées | Protections, robots.txt | Source |
|---|---|---|---|---|---|---|
| data.gouv.fr | API `https://www.data.gouv.fr/api/1/` | Clé (`X-API-KEY`) pour l'écriture | Licence propre à chaque jeu | API principale : aucun chiffre, HTTP 423 en cas d'activité suspecte ; FAQ : Découpage administratif 10 req/s/IP, API Adresse 50 req/s/IP, géocodage de masse 2 requêtes simultanées/IP | `robots.txt` : recherches paramétrées, exports et `/api/1/datasets/r/` exclus | [prise en main](https://guides.data.gouv.fr/api-de-data.gouv.fr/prise-en-main), [FAQ](https://guides.data.gouv.fr/foire-aux-questions) |
| Geneanet | Aucune API publique officielle trouvée | Session utilisateur | CGU **inaccessibles** ; un extrait de la page des changements mentionne une section 4.2.3 sur « l'utilisation de robots » (clause exacte non lue) | Non trouvées | Cloudflare (« Just a moment… », 403) sur `robots.txt` et CGU | [changements des CGU](https://www.geneanet.org/legal/cgu-changes) (extrait) |
| FamilySearch | API REST | Compte développeur et clé d'application ; production après le Compatible Solution Program | Non trouvée sur les pages lues | Débit par utilisateur (ou par clé sans connexion) en temps de traitement ; seul chiffre : un **exemple** de 18 s d'exécution par fenêtre d'une minute ; 429 + `Retry-After`, en-tête `X-PROCESSING-TIME` | `robots.txt` : arbres, recherches et ARK de notices exclus | [getting started](https://developers.familysearch.org/main/docs/getting-started), [throttling](https://developers.familysearch.org/main/docs/throttling) |

FamilySearch et Geneanet restent hors automatisation (authentification, pas de contournement), comme indiqué
dans le [référentiel](archives.md).

## Décisions

- **INSEE, fichiers du COG** (décision du mainteneur, 2026-11-28, #350) : le `robots.txt` de www.insee.fr
  contient `Disallow: *.csv` (vérifié le 2026-11-28), mais les mentions légales admettent l'extraction
  automatique qui ne porte pas atteinte au site, et data.gouv.fr ne fait que renvoyer vers insee.fr (aucune
  copie ailleurs). Le plugin **garde** le téléchargement des deux fichiers du millésime configuré : à la
  demande, mis en cache, sans répétition. Les réponses enregistrées des tests ne sont pas retéléchargées
  automatiquement. Une installation peut pointer `GENEALOGISTE_COG_MVT_URL` et `GENEALOGISTE_COG_COMMUNES_URL`
  vers ses propres copies.

## Points à arbitrer

- **Wikidata** : `Disallow: /sparql` vise les robots d'indexation ; le manuel du service documente l'usage
  programmatique et ses limites. Le plugin respecte la politique User-Agent.
- **matchID** : sans jeton, nombre d'appels limité (« une centaine » ou 20 selon la source) ; le plafond
  journalier du plugin (1000) n'en tient pas compte. Configurer un jeton pour un usage soutenu.
- **WikiTree** : confirmer à la main les 200 requêtes/min et 4000/heure de `Help:App_Policies` avant de
  les porter en `sourcee`.
- **Pages inaccessibles** (FranceArchives, conditions Gallica, Geneanet, Mémoire des hommes, ANOM) : à relire
  dans un navigateur ; ne pas en déduire d'absence de clause.
- Reste de #119 : champ `acces_machine` par service dans le référentiel, sonde de `make verifier-archives`,
  relevé par éditeur (Arkothèque/Anaphore, Ligeo) et adaptateurs de référence.
