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
| Pays du lieu (#283) | `archives_service(lieu=…)`, `communicabilite(…, lieu)`, `cotes_a_consulter`, `prochaine_source` et la fiche renvoient le pays et sa provenance ; hors de France, aucun service ni série d'AD (renvoi générique, piste de transcription) ; pays inconnu : séries d'AD « si le lieu est en France » ([contexte-historique.md](contexte-historique.md#pays-du-lieu)) |
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
  d'AD14 renvoie des fiches individuelles (index nominatif) et n'est pas déclaré. AD59 : deux formulaires
  dédiés, hors de ce référentiel (#376, ci-dessous).
- **Tables des successions et absences** (`type_acte="SUCC"`, série 3 Q, #112) : `commune` = bureau de
  l'enregistrement (« Nevers », « Bureau de Delle » : le préfixe « Bureau de » est facultatif), `annee` et
  `annee_fin` = période ; AD25, AD27, AD37 (bureau = canton), AD58, AD69, AD90, AD91. AD59 : formulaire dédié,
  hors de ce référentiel, et fiches décès `FD` (#377, ci-dessous).
- Relevé et recette : [relevé du 18 novembre 2026](releves-archives-2026-11-18.md).

## Localisation des registres AD59 — #121

`archives_registres(service="AD59", commune="Saint-Vaast-en-Cambrésis", annee=1860, type_acte="N")`
interroge la recherche publique pour obtenir la cote et l'ARK du registre, sans navigateur ni ARK initial.
Une seule page par appel, avec cache ; les pages suivantes sont demandées explicitement. Les tables
décennales (`type_acte="TD"`) et les intervalles d'années (`annee_fin`) sont pris en charge depuis #221. Le serveur
ne cherche pas la vue contenant l'acte : poursuivre avec `archives_naviguer`, puis `archives_sonder`.

Depuis #374, la réponse AD59 porte en plus `classeur_3e` quand la recherche est vide ou qu'un volume n'est pas en
ligne : cote, types, bornes et année de mise en ligne prévue tirés du « classeur 3 E » publié par le service
(`referentiels/ad59_3e.json`, relevé du 27 novembre 2026, généré par `scripts/generer_couverture_3e_ad59.py`).
« Pas en ligne avant AAAA » et « inconnu du classeur » ne veulent jamais dire « inexistant ». Source, limites et
renouvellement : [classeur 3 E](recherche-registres-ad59.md#classeur-3-e--cote-et-mise-en-ligne-prévue--374).

Depuis #375, `type_acte="REC"` interroge le formulaire des recensements de population : commune
seule, période filtrée localement, mêmes sorties (`archives_registres(service="AD59", commune="Somain",
annee=1906, type_acte="REC")` → `M 474 / 572`). `couverture_recensements` joint, quand la recherche est vide ou
qu'un recensement n'est qu'en salle de lecture, la cote et le mode d'accès tirés de l'état de la collection du
service (`referentiels/ad59_recensements.json`, relevé du 27 novembre 2026, généré par
`scripts/generer_couverture_recensements_ad59.py`) ; un millésime inconnu du référentiel n'est pas inexistant.
Depuis #392, `REC` vaut aussi pour AD14, AD19, AD25, AD27, AD37, AD39, AD51, AD55, AD58, AD69, AD80, AD90 et
AD91 (formulaire relevé le 28 novembre 2026, période envoyée ou filtrée localement selon ses champs, sans état
de la collection) ; refusé pour AD972 (pas de formulaire) et les autres services ([détail](recensements.md#autres-services-mnesys-392)). Détail, Socface et
limites : [recensements](recensements.md).

Depuis #376, `type_acte="RM"` vaut aussi pour AD59 (série 1 R) : `annee` = classe (année de naissance + 20),
`commune` = bureau de recrutement, facultatif, pris dans le vocabulaire lu en ligne (Avesnes, Cambrai, Dunkerque,
Lille, Valenciennes, Valenciennes-Douai au relevé du 27 novembre 2026). Une classe précise interroge deux
formulaires, une page chacun : les tables alphabétiques et les fiches des états signalétiques (classes 1867 à
1923 en ligne d'après le formulaire). Chaque résultat porte `categorie` (`tables`, `fiches`) et `contexte` ;
`matricules` donne l'état de chaque formulaire. Un intervalle (`annee_fin`) n'interroge que les tables.
`archives_registres(service="AD59", commune="Avesnes", annee=1890, type_acte="RM")` → table `1R 02249` et cinq
volumes `1R 2244` à `1R 2248`. Aucun référentiel local des cotes 1 R : `cotes_a_consulter` donne la classe et
l'appel à lancer (`matricules_ad59`), pas de cote. Détail et limites :
[registres matricules](recherche-registres-ad59.md#registres-matricules--type_acterm--376).

Depuis #377, `type_acte="SUCC"` vaut aussi pour AD59 (tables des successions et absences, série 3 Q, au plus
1791-1968 d'après le service) et `type_acte="FD"`, propre à AD59, interroge les fiches décès de l'enregistrement
(versements W, 1969 à 1975 en ligne), qui en sont la suite. Dans les deux cas `commune` = bureau de
l'enregistrement, obligatoire, pris dans le vocabulaire lu en ligne : un bureau inconnu ou ambigu est une
erreur qui liste les valeurs, et `autres_bureaux` signale les bureaux de même nom (`LILLE (1er bureau)`…).
`archives_registres(service="AD59", commune="Steenvoorde", annee=1791, annee_fin=1803, type_acte="SUCC")` →
`3Q - 516 / 1` et `3Q - 516 / 2` ; `archives_registres(service="AD59", commune="Lille (Centre)", annee=1969,
type_acte="FD")` → six volumes `2571 W 01` à `2571 W 06`. **Les fiches décès ne sont pas présentées comme
librement communicables** : le service affirme un délai de 50 ans (type `vie_privee` de `communicabilite`),
que le plugin n'a pas vérifié ; la réponse porte `avertissement_communicabilite` et
`fiches_deces.communicabilite`, et écarte tout résultat de moins de 50 ans. Aucun référentiel local des cotes ;
`prochaine_source` joint `successions_ad59` à la piste des successions pour le Nord. Détail et limites :
[enregistrement](recherche-registres-ad59.md#enregistrement--type_actesucc-et-type_actefd--377).

Depuis #378, `type_acte="HYP"`, propre à AD59, interroge les trois formulaires de la sous-série 4 Q (conservation
des hypothèques, de l'an VII à 1955 d'après le service) : indicateurs, tables alphabétiques du répertoire et
répertoires des formalités hypothécaires. `commune` = bureau des hypothèques, obligatoire, pris dans le
vocabulaire lu en ligne (Avesnes, Cambrai, Douai, Dunkerque, Hazebrouck, Lille, Valenciennes au relevé du
27 novembre 2026) ; un bureau inconnu est une erreur qui liste les valeurs. `HYP` interroge les trois
formulaires, une page chacun ; `HYPI`, `HYPT` et `HYPR` n'en interrogent qu'un, pour feuilleter sans requête
inutile. Chaque résultat porte `categorie` (`indicateur`, `tables`, `repertoires`), `contexte` et la lecture de
son titre : `bureau_titre` (« Lille (avant 1900) », « Lille 2 (1901-1955) »), `periode_titre` et
`plage_alphabetique` (`texte`, `debut`, `fin`). Ces formulaires n'ont aucune date : `annee` n'est pas envoyée et
n'écarte que les volumes dont le titre porte une autre période. La méthode du service est rendue dans
`hypotheques.methode` : indicateur, puis table alphabétique (numéro de case du propriétaire), puis répertoire
(volume et numéro des actes), les registres de formalités se consultant en salle de lecture. **Le nom cherché
n'est jamais envoyé** : il se compare localement à `debut` et `fin` (`registres.plage_couvre`,
`registres.volumes_couvrant`). `archives_registres(service="AD59", commune="Cambrai", annee=1850,
type_acte="HYPI")` → cinq volumes `4Q 63 / 001` à `4Q 63 / 005`. `prochaine_source` joint `hypotheques_ad59`
aux pistes notariales du Nord. Détail et limites :
[hypothèques](recherche-registres-ad59.md#hypothèques--type_actehyp--378).

Depuis #379, `type_acte="CAD"`, propre à AD59, interroge les deux formulaires des plans du cadastre : cadastre
dit du Consulat (cotes `P 30`, début du XIXe siècle d'après le service) et cadastre dit napoléonien (cotes
`P 31`, jusqu'au début du XXe siècle pour certaines communes). `commune` est obligatoire et prise dans le
vocabulaire de chaque formulaire, lu en ligne ; les deux vocabulaires diffèrent (anciens noms, communes réunies,
subdivisions) : seul le formulaire qui connaît la commune est interrogé, une commune inconnue des deux est une
erreur qui liste les valeurs proches. Chaque résultat est un lot de plans (non nominatifs) et porte `categorie`
(`consulaire`, `napoleonien`), `contexte`, `annee_titre` et, de 2 à 9 vues, `planche_contact` (appel
`archives_planche` proposé, non éprouvé sur un plan). Aucune date n'est envoyée et, depuis #391, aucun plan n'est
écarté sur sa date (un plan vaut pour les décennies qui suivent sa levée) : les lots de la commune sont triés
par date et `position_periode` situe chacun (`anterieur`, `contemporain`, `posterieur` à la période demandée,
`null` sans date). `cadastre.noms_lies` propose, d'après le classeur 3 E local et sans réseau, le nom
actuel ou l'ancien nom sous lequel relancer (Fives et Lille, Saint-Remy-du-Nord et Saint-Remy-Mal-Bati) ; pour
les autres communes réunies, `geo_historique` puis une relance sous le nom d'alors. Matrices cadastrales et
états de sections : non couverts. `archives_registres(service="AD59", commune="Estaires", annee=1800,
annee_fin=1900, type_acte="CAD")` → trois lots `P 31 / 035`, `035_1`, `035_2`. `prochaine_source` joint
`cadastre_ad59` aux pistes de domicile et de bien du Nord. Détail et limites :
[plans du cadastre](recherche-registres-ad59.md#plans-du-cadastre--type_actecad--379).

### Cadastre des autres services Mnesys (#392)

Depuis #392, `type_acte="CAD"` vaut aussi pour AD14, AD19, AD25, AD39, AD55, AD58, AD69, AD90 et AD91, dont le formulaire dédié aux plans
du cadastre a été relevé le **28 novembre 2026** (`robots.txt` contrôlé, formulaire puis une recherche par
service, aucune image ; déclaration `recherche_registres.formulaires.cadastre`, date `releves.cadastre`). Règles
communes avec AD59 : commune obligatoire prise dans le vocabulaire du formulaire lu en ligne, aucune date
envoyée, aucun plan écarté sur sa date, lots de la page triés par date et situés par `position_periode`. Quand
le formulaire a une typologie (AD14, AD19, AD39, AD69, AD90), seules ses options de plans sont envoyées (plan
cadastral, de finage, parcellaire, par masses de culture, du livre foncier, de remembrement, tableau
d'assemblage : `cadastre.typologie_envoyee`) ; matrices, états de section et autres documents du formulaire sont
listés dans `cadastre.autres_documents`, non interrogés. AD69 range la commune en « collectivité » après un titre
(type de cadastre) : le champ est déclaré au référentiel (`recherche_registres.champs_lieu`).

| Service | Commune du relevé | Plans (page 1 / total) | Exemple |
|---|---|---|---|
| AD14 | Bayeux | 20 / 36 | sections de 1812 (`3P/1923`), cadastre rénové de 1970 |
| AD19 | Tulle | 20 / 28 | tableau d'assemblage de 1824 (`7P/272/TA`) |
| AD25 | Pontarlier | 1 / 1 | `3P463`, 1826, 23 vues |
| AD39 | Dole | 16 / 16 | sections de 1813 (`3Pplan2187`…) |
| AD55 | Verdun | 20 / 31 | sections de 1831-1832 (`139 FI 259`) |
| AD58 | Clamecy | 20 / 20 | plan par masses de cultures (sans date), sections de 1833 |
| AD69 | Tarare | 20 / 65 | sections de 1819 (`3P2001`…) |
| AD90 | Delle | 2 / 2 | plan d'intendance (`1 C 69`, sans date), cadastre de 1823 (`3 P 55`) |
| AD91 | Étampes | 20 / 45 | sections de 1824 (`3P/4309`…) |

Non ouverts : **AD27** (formulaire « Plans cadastraux » relevé, mais ses 44 plans de Bernay ne sont pas marqués
comme images : le filtre d'images en ligne du plugin n'en rend aucun ; type de média à étudier) ; les autres
services Mnesys n'exposent pas de formulaire de cadastre sur leur page des fonds. Matricules d'**AD14** : le
formulaire indexe chaque fiche individuelle par le nom du soldat ; sans nom envoyé, la recherche ne ferait que
feuilleter des centaines de fiches : non ouvert, en attente d'une décision.

Depuis #380, ces relevés AD59 sont suivis : `make veille-ad59` (étape réseau explicite du mainteneur, hors
`make test`, aucun outil MCP) signale la dérive des douze formulaires de recherche, les fils du forum des ajouts
du service et un classeur 3 E d'un autre millésime ; `diagnostic` (contrôle `referentiels_ad59`) signale, sans
réseau, un référentiel embarqué relevé depuis plus d'un an. Rien n'est téléchargé ni corrigé automatiquement :
[veille des AD59](veille-ad59.md).

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
| cadastre | — | plans et matrices ; recherche des plans pour AD59 (`CAD`, #379) et neuf services Mnesys (#392), matrices non couvertes |
| hypotheques | — | ajouté au catalogue, règle historique conservée ; recherche de volumes pour AD59 (`HYP`, #378) |
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
