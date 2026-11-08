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
| `liens_recherche` | lien direct vers le site ou la visionneuse des AD du lieu |
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
  `cadastre`, `paroissiaux` ; bornes `de` / `a` en années (une borne absente = ouverte). **Clé absente =
  inconnu** : l'outil répond alors `null`, jamais « en ligne ». L'exemple ci-dessus montre le format, ses
  valeurs ne sont pas des données. Hors d’une ancienne plage, le résultat est désormais inconnu,
  sans en déduire une absence.
- `references` : liste d’URL officielles justifiant les compléments d’une entrée ;
  `releve_le` : date ISO de leur lecture automatisée. Ces champs sont informatifs, exposés dans la fiche,
  et ne remplacent pas `verifie_le` ; ils ne valident pas les autres champs hérités, notamment le NAAN.
- `visionneuse` : point d’accès à la recherche ou à la sélection des fonds conduisant à la consultation ;
  il ne désigne pas nécessairement une image directement ouverte.
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
