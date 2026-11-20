# Référentiel des archives publiques françaises

Fichier : `mcp/src/genealogiste_mcp/referentiels/archives_fr.json`, chargé par le serveur MCP.

Il décrit les **services d'archives** eux-mêmes (AD, archives communales, Archives nationales, ANOM, SHD…) :
site, visionneuse, préfixe ARK (NAAN), ce qui est **en ligne**. Les **types** de sources (séries E, M, R…)
restent dans `fr_sources.py` et dans la skill `sources-francaises`.

Pour savoir quelles images le plugin peut résoudre et télécharger, voir le
[catalogue des services et fonctions disponibles](../wiki/Services-archives.md).

## Utilisation

| Outil | Apport du référentiel |
|---|---|
| `archives_service(lieu \| departement \| code, document, annee)` | fiche du service ; `en_ligne_pour_la_demande` : `true`, `false` ou `null` (inconnu) |
| `communicabilite(…, lieu, personne)` | distingue **communicable** et **en ligne** ; si l'acte n'est pas connu en ligne : conseil (mairie, AD, demande à distance) et modèle de courrier ; si non communicable : dérogation |
| `cotes_a_consulter` | nom réel du service et fiche (`service_archives`) au lieu de « AD » |
| `liens_recherche` | lien direct vers le site ou la visionneuse des AD du lieu ; sites tiers du département ([sites-tiers.md](sites-tiers.md)) |
| `sources_catalogue` | liste filtrable de tout ce que le plugin connaît : ce référentiel, les [sites tiers](sites-tiers.md) et les API |
| `ark_resoudre` | les NAAN du référentiel complètent la table ARK |

## Format d'une entrée

```json
{"code": "AD59", "nom": "Archives départementales du Nord", "type": "departementales", "departement": "59",
 "site": "https://archivesdepartementales.lenord.fr", "visionneuse": "", "ark_naan": "33518",
 "en_ligne": {"naissance": {"de": 1792, "a": 1922, "note": "…"}},
 "inscription": false, "demande_a_distance": "", "verifie_le": "2026-11-04", "notes": ""}
```

- `type` : `departementales`, `communales`, `nationales`, `militaires`, `notariales`, `diocesaines`, `autre`.
- `couvertures` : format recommandé pour les règles sourcées, périodes, communes, exceptions et lacunes ;
  voir [le modèle de disponibilité](couvertures-archives.md).
- `en_ligne` (compatibilité) : clés `naissance`, `mariage`, `deces`, `tables_decennales`, `recensement`, `notaire`, `matricule`,
  `cadastre`, `paroissiaux`, `enregistrement` (série 3 Q : tables des successions,
  mutations par décès) ; bornes `de` / `a` en années (une borne absente = ouverte). **Clé absente =
  inconnu** : l'outil répond alors `null`, jamais « en ligne ». L'exemple ci-dessus montre le format, ses
  valeurs ne sont pas des données. Hors d’une ancienne plage, le résultat est désormais inconnu,
  sans en déduire une absence.
- `references` : liste d’URL officielles justifiant les compléments d’une entrée ;
  `releve_le` : date ISO de leur lecture automatisée. Ces champs sont informatifs, exposés dans la fiche,
  et ne remplacent pas `verifie_le` ; ils ne valident pas les autres champs hérités, notamment le NAAN.
- `visionneuse` : point d’accès à la recherche ou à la sélection des fonds conduisant à la consultation ;
  il ne désigne pas nécessairement une image directement ouverte.
- `visionneuse_acces` : accès de visionneuse relevé pour le service (`famille` parmi `iiif_natif`, `editeur_ad`,
  `visionneuse_maison`, `images_statiques`, `authentifie` ; `editeur`, `logiciel`, `iiif`, `protection`,
  `reference`, `releve_le` facultatifs). `protection` vaut `null` ou l'une des valeurs `anubis`, `cloudflare`,
  `cloudflare_hcaptcha`, `hcaptcha`, `recaptcha`, `datadome`, `attente`, `redirection_js` (page qui
  redirige en JavaScript avant tout contenu, relevée par `scripts/sonder_visionneuses.py`) : défi opposé aux requêtes
  automatisées du plugin et constaté sur une ressource précise, même s'il se résout seul dans un navigateur.
  `protection_releve_le` (date ISO), `protection_reference` (URL HTTP(S) observée) et `protection_note`
  documentent ce constat ; `archives.validate()` refuse une autre valeur. `par_type` décrit un accès propre à un type de document quand il
  diffère (ex. matricules sur une autre application que l'état civil) :

  ```json
  "visionneuse_acces": {"famille": "editeur_ad", "editeur": "naoned", "iiif": false,
    "par_type": {"matricule": {"famille": "iiif_natif", "iiif": true,
      "reference": "https://…/matricules", "releve_le": "2026-11-17"}}}
  ```

  Clés de `par_type` : clés canoniques de type (`matricule`, pas `matricules`). Chaque entrée exige une
  `reference` HTTP(S) sans identifiants et une date `releve_le` ; aucun `par_type` imbriqué. Un objet ne
  contenant que `par_type` n'annonce aucun accès général. La fiche expose `visionneuse_pour_la_demande`
  (`origine` : `document`, `service` ou `inconnu`) : l'entrée du type prime, sans fusion de champs ;
  sinon repli sur l'accès général. Une entrée de type invalide donne `inconnu`, jamais un repli.
  Un adaptateur étant propre à un éditeur, l'accès typé **du même éditeur** que l'accès général conserve
  l'adaptateur et la recette du service ; un éditeur différent ou inconnu les écarte pour ce type
  (`telechargement.etat` = `a_qualifier_pour_ce_type`, couverture technique inconnue).
- `verifie_le` : date à laquelle **une personne** a vérifié l'entrée sur le site du service. Absente ou de plus
  de 12 mois : avertissement dans les réponses.
- Entrées importées : `wikidata` (identifiant de l'élément), `origine` (« import : … »), `site_repond_le` (date
  à laquelle le site a répondu au contrôle HTTP (HEAD ou repli GET)). Une entrée importée n'a pas de `verifie_le` tant qu'une
  personne ne l'a pas contrôlée.

## Règles de contribution

- Ne saisir que des valeurs vérifiées sur le site du service (bornes de mise en ligne, NAAN relevé sur un lien
  réel). Une donnée incertaine reste absente.
- Les bornes de mise en ligne diffèrent souvent du délai légal de communicabilité : un registre communicable
  peut ne pas être numérisé.
- `make verifier-archives` : vérifie le format et que chaque site répond (requête HEAD ; si le site refuse HEAD
  ou coupe la connexion, un seul repli GET, redirections suivies sans lire les corps ; respect des CGU, aucun contournement des
  protections). Verdicts : `OK`, `AVERT` (site présent mais non contrôlable automatiquement : protection
  anti-robots, certificat TLS non vérifiable — à vérifier dans un navigateur ; n'échoue pas), `KO`. Le
  script ne modifie jamais `verifie_le`.
- `pytest tests/test_archives.py tests/test_couverture_archives.py tests/test_verifier_archives.py` : format et verdicts HTTP simulés,
  replis, redirections, fermeture des réponses et absence de mutation du référentiel. Ces tests font partie
  de `make test` ; `make lint` couvre déjà `mcp/scripts/`.

## Couverture actuelle

- **Les 101 départements** ont une entrée : AD59, AD62 et Archives de Paris saisies à la main ; les 98 autres
  importées le 2026-11-04 :
  - nom et site officiel : Wikidata (éléments « archives départementales », Q2860456, propriété P856), site
    gardé seulement s'il répond (86 sur 98) ; redirection vers un autre domaine : nouvelle adresse retenue si
    c'est le site des archives, écartée sinon ;
  - NAAN ARK : registre public de l'ARK Alliance, rapproché par département (78 sur 98) ;
  - sites jugés injoignables à l'import (06, 08, 11, 13, 24, 26, 2A, 2B, 50, 974, 976), repris le 2026-11-05 :
    24 et 974 : nouvelle adresse, identité confirmée ; 06, 08, 11, 13, 26, 50 : adresses candidates conservées
    dans les notes, sans champ `site` tant que leur identité n’a pas été confirmée sur le site du service ; 2A, 2B (Archives de la Collectivité de Corse depuis 2020) et
    976 : pas de site retenu, piste dans `notes`.
- Services nationaux et autres : Archives nationales, Léonore, ANOM, SHD, Mémoire des hommes, FranceArchives,
  Gallica (BnF), Retronews, matchID.
- **Reste à faire** (issue #25) : bornes de mise en ligne (`en_ligne`) relevées sur chaque site, site de la
  Corse et de Mayotte, visionneuse et IIIF de chaque AD, vérification humaine (`verifie_le`).

## Relecture du lot de sites (7 novembre 2026)

Les observations des 5–6 novembre ci-dessus proviennent de la PR #76. La relecture automatique du
7 novembre retrouve l’identité des [archives de Dordogne](https://archives.dordogne.fr/) et de la
[page départementale de La Réunion](https://www.departement974.fr/archives-departementales).
Les autres adresses reprises restent à confirmer dans un navigateur : pages demandant JavaScript/cookies
(AD08, AD50), rejet de requête (AD11), accès non obtenu par l’outil de relecture (AD06, AD13, AD26).
Ces résultats ne prouvent ni une panne du service ni la cause TLS rapportée historiquement.
Aucun `verifie_le` ni aucune borne `en_ligne` n’a été ajouté.

Les adresses AD06, AD08, AD11, AD13, AD26 et AD50 sont donc conservées uniquement dans `notes`,
conformément à la règle sur les données incertaines. Leur éventuelle présence dans un annuaire tiers
ne remplace pas la validation sur le site du service. Le champ `site` est rétabli pour AD24 et AD974.

## Complément du lot — 0.14.4

Les sites AD06, AD08, AD13, AD26 et AD50 ont depuis été identifiés par lecture de leurs pages officielles
dans le navigateur. Les observations précédentes restent l’historique du premier contrôle, pas l’état
actuel de ces cinq adresses. Cinq accès aux fonds sont ajoutés (AD08, AD13, AD24, AD26, AD50).
Les sources, dates et limites sont consignées dans le [relevé du 7 novembre](releves-archives-2026-11-07.md).
L’Aude reste candidate ; Corse et Mayotte restent à traiter.

Avant d’ajouter des plages `en_ligne`, tenir compte des exceptions communales et lacunes : une plage
unique n’exprime pas ces cas et la note n’est pas interprétée par le calcul. Aucun intervalle global
n’est donc ajouté dans ce lot ; l’issue #93 suit l’évolution du modèle de couverture. `verifie_le` reste
inchangé sur toutes les entrées.

## Couvertures structurées — 0.15.0

Le modèle de #93 est implémenté : périodes annoncées, couvertures partielles, lacunes, règles par commune,
renvois et indisponibilités explicites. Le [guide de saisie](couvertures-archives.md) décrit les priorités,
la frontière des seuils glissants et la compatibilité des anciennes plages. Les résultats ne prouvent
pas la présence d’un acte. #25 peut poursuivre la saisie de petits lots avec ces règles, sans transformer
les couvertures variables en booléens globaux.

## Complément du lot — 0.15.1

Le [relevé du 8 novembre](releves-archives-2026-11-08.md) confirme l’identité du site de l’Aude,
le portail documentaire commun aux deux départements corses et une page officielle de publications
pour Mayotte. Les anciennes réserves de confirmation ci-dessus sont l’historique des premiers essais.
L’Aude dispose de couvertures `annoncee` (registres jusqu’à 1922, tables sans bornes établies) ; le calcul
reste inconnu. Aucune plage corse n’est déduite du formulaire et aucune visionneuse mahoraise n’est
revendiquée. Les références et `releve_le` sont renseignés, sans modification de `verifie_le`.

## Visionneuses par éditeur — #128

Le [relevé du 10 novembre](releves-archives-2026-11-10.md) classe les 101 services par visionneuse
(sonde `scripts/sonder_visionneuses.py`). L’adaptateur `visualizer_api` (Naoned, logiciel Mnesys Expo) est
générique : 14 services Mnesys Expo (AD14, AD19, AD25, AD37, AD39, AD51, AD55, AD58, AD59, AD69,
AD80, AD90, AD91, AD972) sont déclarés pour l’adaptateur générique. Tous ont une recette de référence réussie enregistrée (`recettes_archives.json`), y compris AD37 depuis le relevé du 18 novembre 2026 (#242). Aucun fonds supplémentaire n’est qualifié par cette déclaration. Ajouter un service Mnesys Expo = renseigner `resolution_image` après recette, sans code.

## Recette depuis un VPS et accès protégé — #150

Un essai réussi depuis une connexion ne garantit pas l'accès depuis une autre. Les résultats peuvent
être enregistrés séparément par environnement :

```bash
GENEALOGISTE_RECETTE_ENVIRONNEMENT=vps make test-archives
```

Exécuter cette commande sur le VPS cible, avec les fixtures publiques de référence et aucun fichier
familial. Pour un essai ailleurs, utiliser `local`, `ci` ou `inconnu` (défaut). Ne pas étiqueter un
environnement déduit de son seul système d'exploitation. Les mesures sont conservées dans
`referentiels/recettes_archives.json`, sous `mesures`, sans adresse IP ni secret.

`archives_service` expose `acces_vps` : `verdict` vaut `oui` (recette complète réussie), `defi`
(protection rencontrée), `echec` (échec technique ou de contrat, sans conclure à sa cause), ou `inconnu`
(aucun essai identifié depuis le VPS). `date_mesure` est en UTC et `detail` indique la limite observée.
Une nouvelle recette locale ne remplace pas la mesure VPS. Chaque mesure concerne seulement la
ressource de référence et le moment de l'essai, pas tout le fonds ni toutes les adresses de VPS.

Un défi reconnu renvoie `statut: bloque_antirobot`, le service, le type de protection, l'heure et une
`tache_manuelle` avec l'URL effective. Le journal conserve la tâche :
`journal_lister(statut="bloque_antirobot")`. Continuer les autres pistes ; fournir ensuite les résultats
avec `source_collee` ou le téléchargement autorisé à `piece_archiver` en fichier local. Aucun
navigateur n'est requis sur le serveur pour conserver cette attente. Les signaux et la décision sur le
proxy sortant sont décrits dans [Sécurité](securite.md#échecs-mémorisés-coupe-circuit-caches-bornés).

Compléments #150 :

- l'enveloppe porte `suite` (ne pas relancer, aucun navigateur côté serveur, lien à ouvrir par
  l'utilisateur, ce qu'il faut relever, outils de reprise, levée explicite) ;
- avec `enquete=<id>`, la consultation est inscrite comme tâche manuelle `a_faire` de l'enquête (une par
  URL bloquée), reprise par `enquete_reprendre` ;
- un défi qui persiste après la pause exclut le service `GENEALOGISTE_EXCLUSION_ANTIROBOT` secondes
  (7 jours par défaut) : `exclusion: true`, `exclu_jusqu_au` ; `cache_purger("coupe_circuit")` la lève ;
- `archives_service` expose `defi_observe` : dernier défi observé **depuis cette installation** sur les
  hôtes du service (protection, détections, première et dernière date, exclusion en cours). Ce constat
  local ne remplace ni `acces_vps` (recette) ni le champ `protection` du référentiel, qui restent à
  valider par une mesure datée ;
- une page de blocage Cloudflare en 403 (`cf-error-details`, ex. erreur 1020) est reconnue comme défi.

### Défi anti-robot et consultation manuelle — #196

Signatures reconnues par `http._protection`, en lecture seule du HTML (aucun script exécuté, aucune
preuve de travail calculée) :

- **Anubis** (TecharoHQ/anubis, gabarit public `web/index.templ`) : script JSON `id="anubis_challenge"`
  **et** ressource sous `/.within.website/x/cmd/anubis/`, dans une réponse HTML, quel que soit le statut
  HTTP (le statut du défi est configurable, 200 par défaut). Une page qui cite Anubis ou son dépôt n'est
  pas un défi ;
- **Cloudflare**, **hCaptcha**, **DataDome**, page d'attente (#150) et **reCAPTCHA** interstitiel :
  `recaptcha/api.js`, bloc `g-recaptcha` et titre de vérification (« Security verification »,
  « Verify you are human », « Vérification de sécurité ») ; un formulaire ordinaire avec reCAPTCHA passe.
- **redirection JS** des visionneuses Arkotheque (#253 ; AD15 et les autres services classés `redirection_js`
  au référentiel) : page minimale qui pose le cookie `bot_mitigation_cookie` et contient **à la fois**
  `window.location.href='/redirect_…'` et le `noscript` « This website requires JS enabled and cookies ».
  Une redirection JavaScript ordinaire n'est pas un défi. Le plugin ne suit pas la redirection ;
- **blocage robots IA** de WikiTree (#253) : page 403 « Error 403 - Access Blocked » citant les
  « AI-scraping bots » (voir [securite.md](securite.md#identification--user-agent-et-contact-facultatif)).

Le service est identifié sans tenir compte du préfixe `www.` (le référentiel note `www.archives.cantal.fr`,
la visionneuse sert `archives.cantal.fr`), de sorte que l'enveloppe nomme bien `AD15`.

L'enveloppe d'erreur ajoute alors `bloque: "anti-robot"` et une `consigne` : ne pas relancer ni résoudre
le défi, demander à l'utilisateur une capture ou l'image téléchargée de la vue, l'enregistrer avec
`media_enregistrer(chemin, nom, classer=true)` (nom proposé par `piece_nommer`), la lire puis tracer le
relevé avec `source_collee`. La tentative est journalisée avec le statut `bloque_antirobot`.

Un service dont la protection est connue au référentiel (ex. AD48, Anubis relevé le 2026-11-17 sur
`https://archives.lozere.fr/`) expose `consultation_manuelle` dans `archives_service` : protection, date et
référence du relevé, consigne et possibilité de réessai. **Choix** : les appels réseau ne sont pas refusés
d'avance, car une protection peut être levée ou ne concerner qu'une partie du site. Le premier défi détecté
met l'hôte en pause (coupe-circuit, `GENEALOGISTE_COUPE_CIRCUIT`, 1800 s) ; `cache_purger("coupe_circuit")`
permet un nouvel essai explicite. Les autres services classés `anubis` par la sonde passive du
[relevé du 2026-11-10](releves-archives-2026-11-10.md) ne sont pas reportés sans constat sur leur site.

## Plafond journalier par service — #157

Chaque hôte d'un service d'archives du référentiel reçoit au plus `GENEALOGISTE_PLAFOND_JOUR_ARCHIVES`
requêtes par jour (1000 par défaut, 0 = aucun plafond), même sans enquête. Les autres hôtes (API,
IIIF tiers) ont leur propre plafond, `GENEALOGISTE_PLAFOND_JOUR_DEFAUT`, et un hôte précis se règle par
`GENEALOGISTE_PLAFONDS_JOUR` ([politique d'accès par service](securite.md#politique-daccès-par-service), #211). Le compteur est persistant (cache
SQLite) ; au plafond, aucune requête ne part et l'outil renvoie une erreur avec `reessayer_apres` (minuit).
Choix et justification du défaut : [securite.md](securite.md#plafond-journalier-par-hôte-et-budget-denquête).
Pour une enquête, le budget (`docs/enquetes.md`) borne en plus les requêtes par hôte et les images lues, sur
tous les outils de collecte appelés avec `enquete=<id>`.

## Accès machine, CGU et limites publiées — #119

[acces-machine-archives.md](acces-machine-archives.md) répertorie, au 2026-11-18, les API et accès machine
des services (clé, licence, CGU, limites publiées, protections, `robots.txt`) et justifie chaque valeur
sourcée de la politique d'accès. `intervalle_requetes` d'ANOM (5 s) reprend le `Crawl-delay` de son
`robots.txt`, cité dans `references`.

## Recherche de registres sur les autres services Mnesys — #128

Les services qui déclarent `recherche_registres` (AD14, AD19, AD25, AD27, AD37, AD39, AD51, AD55, AD58, AD69, AD80, AD90, AD91, AD972) passent par
un chemin générique (`sources/mnesys.py`) : le formulaire public « État civil » est lu (mis en cache une
semaine) pour connaître les noms de champs, la liste des communes et les typologies, puis la recherche GET est
lue avec le même analyseur que pour AD59, contrôlé sur l'hôte et le NAAN du service.

```json
"recherche_registres": {"formulaires": {"etat_civil": "<uuid>", "tables_decennales": "<uuid>",
                                        "matricules": "<uuid>", "successions": "<uuid>"},
                        "champs_annee": {"matricules": "0-title"},
                        "releve_le": "2026-11-18", "reference": "https://<site>/search/form/<uuid>"}
```

Chaque formulaire est facultatif, au moins un est déclaré. AD25 (Doubs) n'a que tables décennales, matricules
et successions : son formulaire « État civil » renvoie un nœud de commune, pas des registres (#242) ; un type
N, M ou D y renvoie une erreur qui liste les types disponibles. `champs_annee` désigne le champ d'année d'un
formulaire qui ne le type pas (AD25 : classe des matricules en texte libre).

- La commune est prise dans le vocabulaire du service (article inversé, forme actuelle préférée à une commune
  ancienne) ; une homonymie renvoie une erreur qui liste les valeurs, à reprendre telles quelles.
- Niveau administratif en suffixe (« Lons-le-Saunier, commune » à AD39, « ARPAJON Commune » et
  « ARPAJON Canton » à AD91) : la commune l'emporte sur le canton ou l'arrondissement de même nom.
- Une année seule est envoyée comme intervalle d'une année quand le formulaire a une période : la date exacte
  manque des volumes pluriannuels (tables des successions AD91). Matricules : classe en date exacte.
- Typologie : la typologie matérielle d'abord ; à défaut de type d'acte, le champ « Type d'acte » en sujet
  (AD39 : BAPTEME, NAISSANCE…). TD retient « Tables décennales » seule quand le formulaire propose d'autres
  tables (AD80 : « Table des familles »).
- Formulaire de tables dédié doté d'une période (AD25) : période envoyée ; sans période (AD59), filtre local.
- Formulaire sans champ de date : recherche par commune seule, période filtrée sur les bornes affichées
  (`registres_hors_periode`).
- Type d'acte non proposé par le formulaire : erreur explicite, relancer sans type.
- **Registres matricules** (`type_acte="RM"`, #112) : `annee` = classe (naissance + 20), `commune` = bureau de
  recrutement si le formulaire le propose (facultatif) ; AD19, AD25, AD27, AD39, AD55, AD58, AD69, AD90, AD972. Le formulaire
  d'AD14 renvoie des fiches individuelles (index nominatif) et n'est pas déclaré.
- **Tables des successions et absences** (`type_acte="SUCC"`, série 3 Q, #112) : `commune` = bureau de
  l'enregistrement (« Nevers », « Bureau de Delle » : le préfixe « Bureau de » est facultatif), `annee` et
  `annee_fin` = période ; AD25, AD27, AD37 (bureau = canton), AD58, AD69, AD90, AD91.
- Relevé et recette : [relevé du 18 novembre 2026](releves-archives-2026-11-18.md).

## Localisation des registres AD59 — #121

`archives_registres(service="AD59", commune="Saint-Vaast-en-Cambrésis", annee=1860, type_acte="N")`
interroge la recherche publique pour obtenir la cote et l'ARK du registre, sans navigateur ni ARK initial.
Une seule page par appel, avec cache ; les pages suivantes sont demandées explicitement. Les tables
décennales (`type_acte="TD"`) et les intervalles d'années (`annee_fin`) sont pris en charge depuis #221. Le serveur
ne cherche pas la vue contenant l'acte : poursuivre avec `archives_naviguer`, puis `archives_sonder`.

## Sondage guidé d'un registre — #156

`archives_sonder(source, date_cible, type_acte, lecture, conclusion, enquete)` remplace le tâtonnement
dans un registre chronologique : l'outil propose la vue à lire, le modèle la lit (`archive_image`, 800 px)
et renvoie ce qu'il y a lu, l'outil resserre les bornes et propose la vue suivante. Aucun réseau, aucune
image : l'outil ne fait que calculer (`sondage.py`) et, avec `enquete`, noter.

- **Lecture** : `{vue, date, date_fin?, type?}` ; `date` = premier acte de la vue (haut de page),
  `date_fin` = dernier acte (resserre d'une vue de plus), `type` = `naissance`, `mariage`, `deces`, `table`
  (alias N/B/baptême, M, D/S/sépulture, T). Dates ISO, françaises (« 14 mars 1862 ») ou républicaines.
- **Méthode** : interpolation sur la période du registre (`periode`, notée par `archives_naviguer`) et les
  dates déjà lues, puis dichotomie quand une interpolation n'a pas divisé l'intervalle par deux (alternance :
  au pire deux fois une dichotomie). Sur un registre simulé de 1 000 vues à densité irrégulière, la date
  est localisée en 10 lectures au plus (3 à 6 le plus souvent ; `tests/test_sondage.py`).
- **Séries** : avec `type_acte`, un registre à plusieurs séries à la suite (naissances, mariages, décès,
  tables en fin de volume ; `ordre_series` pour un autre ordre) est d'abord sondé par **section** : une vue
  d'une autre série borne la section (par son milieu) jusqu'à la première vue du bon type ; la recherche par
  date ne commence qu'ensuite. Actes mêlés (registre paroissial BMS) : `ordre_series=[]`.
- **Date cible** : jour, mois ou année ; une cible partielle vise la première vue de la période.
- **Arrêts** (`arret`) : `localise` (vue(s) à lire recadrées, puis `conclusion="trouve"` ou `"absent"`),
  `absent` (dates lues qui encadrent la cible sans vue entre elles : registre `negatif` dans l'enquête,
  entrée de journal avec les bornes examinées), `budget` (enquête bloquée, images épuisées,
  `max_lectures`, 15 par défaut).
- **Suite** : `action` donne l'appel prêt (`archive_image`, avec `enquete`) ; `alternative` propose une
  planche-contact (`archives_planche`, AD59) quand 2 à 12 vues restent.
- Avec `enquete` (recommandé), lectures, historique du sondage et verdict sont notés dans le registre de
  l'enquête (`docs/enquetes.md`) : un sondage interrompu se reprend au même point. Sans `enquete`, passer
  `nb_vues`, `periode` et toutes les `lectures` dans l'ordre : rien n'est noté.

Le [guide utilisateur](../wiki/Services-archives.md#trouver-un-registre-ad59-sans-ark) décrit les types,
la garde des vivants et les replis. Le [contrat observé](recherche-registres-ad59.md) documente le HTML,
les fixtures et la recette réseau explicite. Les autres services ne sont pas qualifiés par ce lot.

## Couverture réellement testée

Le [tableau généré](couverture-archives.md) distingue capacités implémentées, recettes de référence et environnements. `archives_service` expose ce bilan sous `couverture_technique`, sans extrapoler une recette aux autres fonds.

## Types de documents communs — #129

`types_documents.py` est la table commune des types, alias, séries et règles indicatives. Elle alimente
`archives.DOCUMENTS`, `fr_sources.SERIES` et `fr_sources.RULES`. Les appels `archives_service`,
`communicabilite` et le calcul de couverture acceptent les alias ci-dessous ; les données du référentiel
continuent d'utiliser les clés canoniques.

| Clé canonique | Alias acceptés | Portée |
|---|---|---|
| naissance, mariage, deces | — | état civil |
| tables_decennales | — | index d'état civil |
| recensement | recensements | listes nominatives |
| matricule | matricules | registres militaires |
| notaire | notaires | minutes et répertoires |
| paroissiaux | paroissial | préciser période et statut du fonds |
| enregistrement | — | préciser table ou déclaration |
| cadastre | — | plans et matrices |
| hypotheques | — | ajouté au catalogue, règle historique conservée |
| judiciaire | justice | ajouté au catalogue, clé publique historique conservée |
| insinuation | insinuations | ajouté au catalogue, régime à préciser |

Les accents, espaces extérieurs et majuscules sont normalisés. Les clés historiques de `SERIES`, dont
`etat_civil`, `recensements`, `matricules`, `notaires` et `justice`, restent disponibles.
Le type de pièce `NOT` (acte notarié) est rattaché à `notaire` (`pieces.TYPES_ARCHIVES`) : voir
[pieces.md](pieces.md#codes-de-type) pour la suggestion de cote 3 E (#223). Les types `TSA` (table des
successions et absences) et `MPD` (déclaration de mutation par décès) sont rattachés à `enregistrement`, avec
une cote 3 Q et la communicabilité propre à chacun (#258).
`medical` et `vie_privee` restent des régimes transversaux hors catalogue de fonds ; `etat_civil` est
un regroupement qui exige de choisir naissance, mariage ou décès pour calculer un délai.

`paroissiaux`, `enregistrement` et `insinuation` répondent désormais avec `communicable: null`, un délai
inconnu et une consigne de précision, au lieu d'une erreur « type inconnu ». Aucun délai unique n'est
attribué à ces catégories larges. Les archives de l'Eure distinguent explicitement les tables des
successions, librement communicables, et les déclarations, soumises à un délai de cinquante ans
([guide officiel](https://archives.eure.fr/page/rechercher-une-declaration-de-succession)). Le statut des
archives privées dépend notamment du déposant ; le cadre public et ses exceptions sont décrits par le
[Code du patrimoine](https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006074236/LEGISCTA000006159942/).
Sources consultées le 17 novembre 2026. Les autres règles indicatives préexistantes sont conservées ; ce
lot harmonise les noms sans constituer une revue juridique exhaustive des délais.

Naturalisations et hospitalier restent hors du catalogue de ce lot : ils demandent une description de
sous-types, séries et régimes sourcés avant ajout. L'accès de visionneuse distinct par type est décrit
ci-dessous (`visionneuse_acces.par_type`). Aucun service, fonds, délai de mise en ligne ni capacité réseau n'est ajouté par
l'élargissement du vocabulaire.
