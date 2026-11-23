# Sites tiers de généalogie

Fichier : `mcp/src/genealogiste_mcp/referentiels/sites_tiers.json` (#181), chargé par `sites_tiers.py`.

Le [référentiel des archives](archives.md) décrit les **archives publiques**. Celui-ci décrit tout le reste :
cercles et associations, réseaux de relevés bénévoles, bases thématiques (protestants, déportés, émigrants…),
annuaires, outils de lieux, monuments et cimetières, arbres collaboratifs. Beaucoup sont consultables
librement ou sur simple inscription et comblent les lacunes des AD (contrats de mariage, notaires, BMS
relevés, inscription maritime).

**Un relevé est une source dérivée.** Il donne une piste (date, commune, numéro d'acte) ; il faut ensuite
remonter à l'acte original avant de conclure (méthode GPS). Le plugin ne fait **aucune requête** vers ces sites :
il propose des liens à ouvrir dans le navigateur de l'utilisateur, qui colle ensuite le résultat avec
`source_collee`. Un site protégé (captcha, Cloudflare, adhésion) reste un simple lien, sans contournement.

## Utilisation

| Outil | Apport |
|---|---|
| `sources_catalogue(departement, type, acces, theme)` | tout ce que le plugin connaît : archives publiques, sites tiers, services interrogés par API ; sans argument, le catalogue complet |
| `liens_recherche(…, lieu)` | `sites_tiers` : cercles et relevés couvrant le département du lieu, puis réseaux nationaux de relevés (GeneaBank, FranceGenWeb) |
| `cotes_a_consulter(fait, date, lieu)` | `sites_tiers` : mêmes pistes avant le dépouillement des registres |

Exemples : `sources_catalogue(departement="29")`, `sources_catalogue(theme="ww2")`,
`sources_catalogue(type="lieux")`, `sources_catalogue(acces="libre", type="base_thematique")`.

## Format d'une entrée

```json
{"code": "GENEABANK", "nom": "GeneaBank", "url": "https://www.geneabank.org/frenind.php",
 "type": "releves_benevoles", "zone": ["FR"], "acces": "mixte", "nature": "index",
 "actes": ["BMS", "NMD"],
 "recherche": "https://gbkcouples.geneabank.org?nom={nom}&nomconjoint=&prenom={prenom}&prenomconjoint=",
 "protection": "aucune", "site_repond_le": "2026-11-16", "verifie_le": "",
 "origine": "relevé curl/WebFetch du 2026-11-16 (#181)", "notes": "…"}
```

| Champ | Valeurs |
|---|---|
| `type` | `releves_benevoles`, `annuaire`, `cercle_departemental`, `base_thematique`, `lieux`, `cimetieres_monuments`, `arbre_collaboratif` |
| `zone` | codes de département (`59`, `2A`, `974`) ou `FR` (France entière), `CA` (Canada), `INT` |
| `acces` | `libre`, `inscription_gratuite`, `adhesion`, `points`, `mixte`, `a_determiner` |
| `nature` | `releve_derive`, `index`, `image`, `notice`, `outil` |
| `protection` | `aucune`, `captcha`, `cloudflare`, `connexion` (vaut pour un client automatisé à la date du relevé) |
| `periode` | `{"de": 1940, "a": 1945}` (bornes facultatives) : filtre sur la vie de la personne |
| `themes` | libres : `ww1`, `ww2`, `deportes`, `protestants`, `juifs`, `emigration`, `mariniers`… |
| `recherche` | modèle d'URL **https** avec `{nom}` / `{prenom}`, seulement pour un site sans protection |
| `verifie_le` | date de **contrôle humain** de l'entrée ; vide après tout peuplement automatique |

Les URL acceptent `http` quand le site n'a pas de version https (petits cercles hébergés chez Free, Blogspot…).
`sites_tiers.validate()` contrôle ce schéma ; `tests/test_sites_tiers.py` l'exécute.

## Peuplement

- **Relevé initial du 2026-11-16** (issue #181) : réseaux de relevés, échantillon de cercles, bases
  thématiques et outils de lieux, observés avec `curl`/WebFetch sans contournement.
- **Annuaire de la FFG** (relevé du 2026-11-18) : cercles régionaux et départementaux, extraits des données
  de la carte de <https://www.genefede.eu/associations-federees-par-departements/> par
  `scripts/importer_sites_tiers.py`. La zone est le **département du siège** : la couverture réelle peut être
  plus large (cercle régional) ou plus étroite (cercle local). L'accès est `a_determiner` tant que personne
  n'a lu le site. Sans site propre dans l'annuaire, le lien pointe vers la fiche FFG.
- Couverture : au moins un cercle pour 73 départements. Pour les autres, `sources_catalogue` renvoie les
  annuaires FFG, RFG et Geneawiki. Ne pas deviner de domaines : plusieurs domaines devinés de cercles ne se
  résolvaient pas ou étaient parqués.

- **Émigration** (relevé HTTP du 2026-11-23, #284) : guides de NARA (`NARA-IMMIGRATION`,
  `NARA-NATURALISATION`, `NARA-WW1-DRAFT`, `NARA-RECENSEMENTS`) et recherche d'arrivées de la Statue of Liberty &
  Ellis Island Foundation (`ELLIS-ISLAND`, accès aux images non relevé : `a_determiner`), zone `INT`. Non ajoutés
  faute de réponse pendant le relevé : Bibliothèque et Archives Canada (délai dépassé), à vérifier.

Écartés au relevé : domaines parqués (egmp.fr, cgma.fr, mariniers.fr), sites commerciaux (geopatronyme.com,
genealogiequebec.com), Bigenet (hors service), geneafrance.com (reprend l'INSEE et Mémoire des hommes),
cimetieres-de-france.fr (certificat invalide), jewishgen.org (indisponible, international).

## Vérification

`make verifier-archives` sonde aussi chaque site tiers (HEAD, repli GET sans lecture du corps) : `OK`,
`AVERT` (site présent mais protection relevée ou anti-robots) ou `KO`. Le rapport ne modifie jamais le
référentiel ; `verifie_le` se renseigne à la main après lecture du site dans un navigateur.

Pour ajouter un site : une entrée par site, `origine` et date de relevé obligatoires, `verifie_le` vide sauf
contrôle humain, et `make test`.
