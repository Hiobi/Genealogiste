# Référentiel des archives publiques françaises

Fichier : `mcp/src/genealogiste_mcp/referentiels/archives_fr.json`, chargé par le serveur MCP.

Il décrit les **services d'archives** eux-mêmes (AD, archives communales, Archives nationales, ANOM, SHD…) :
site, visionneuse, préfixe ARK (NAAN), ce qui est **en ligne**. Les **types** de sources (séries E, M, R…)
restent dans `fr_sources.py` et dans la skill `sources-francaises`.

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
- `en_ligne` : clés `naissance`, `mariage`, `deces`, `tables_decennales`, `recensement`, `notaire`, `matricule`,
  `cadastre`, `paroissiaux` ; bornes `de` / `a` en années (une borne absente = ouverte). **Clé absente =
  inconnu** : l'outil répond alors `null`, jamais « en ligne ». L'exemple ci-dessus montre le format, ses
  valeurs ne sont pas des données.
- `verifie_le` : date à laquelle **une personne** a vérifié l'entrée sur le site du service. Absente ou de plus
  de 12 mois : avertissement dans les réponses.

## Règles de contribution

- Ne saisir que des valeurs vérifiées sur le site du service (bornes de mise en ligne, NAAN relevé sur un lien
  réel). Une donnée incertaine reste absente.
- Les bornes de mise en ligne diffèrent souvent du délai légal de communicabilité : un registre communicable
  peut ne pas être numérisé.
- `make verifier-archives` : vérifie le format et que chaque site répond (requête HEAD, aucun contenu
  téléchargé, respect des CGU). Le script ne modifie jamais `verifie_le`.
- `pytest tests/test_archives.py` : validation du format.

## Couverture actuelle

Entrées de départ : AD59, AD62, Archives de Paris, Archives nationales, Léonore, ANOM, SHD, Mémoire des hommes,
FranceArchives, Gallica (BnF), Retronews, matchID. Les autres AD sont renvoyées vers FranceArchives, avec un
avertissement, tant qu'elles ne sont pas saisies.
