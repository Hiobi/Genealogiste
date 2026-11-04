---
name: sources-francaises
description: Connaissance des sources généalogiques françaises et de leur localisation — état civil (1792+), registres paroissiaux BMS, tables décennales, recensements (1836+), registres matricules (classes 1867+), notaires (contrats de mariage, inventaires), enregistrement (tables des successions), cadastre napoléonien, hypothèques, archives départementales, Gallica, matchID, Mémoire des hommes. À utiliser pour « où trouver », « quelle source », « quelle cote », « quelles archives », plan de recherche, lacunes, prochaine source à consulter.
---

# Sources françaises — quoi, où, pour quoi

Toujours préciser : **type de source** (originale/dérivée), **service** (AD, mairie, SHD…),
**cote typique** (cadre de classement, à vérifier dans l'inventaire), **communicabilité**, **accès en ligne**.
Outils : `cotes_a_consulter`, `prochaine_source`, `liens_recherche`, `communicabilite`, `archives_service` (service réel : site, mise en ligne, NAAN ; docs/archives.md), `ark_resoudre`.

| Source | Période | Série AD typique | Apporte | Remarques |
|---|---|---|---|---|
| Registres paroissiaux (BMS) | XVIᵉ s.–1792 | E / 4 E, GG (dépôt communal), G | baptême, mariage, sépulture ; parrains | latin fréquent ; double collection après 1667 |
| État civil | 1792 → | E / 4 E ; mairie (collection communale) | naissance, mariage, décès ; mentions marginales | calendrier républicain 1792-1805 |
| Tables décennales | 1792 → | avec l'état civil | localiser un acte (dérivée) | une table par commune et décennie |
| Publications de bans | 1792 → | état civil | domiciles, mariage ailleurs | |
| Recensements (listes nominatives) | 1836 → (quinquennaux) | 6 M | foyer, âges, professions | âges approximatifs (information secondaire) |
| Registres matricules | classes 1867 → | 1 R | naissance, parents, signalement, parcours | classe = année de naissance + 20 |
| Notaires (minutes, répertoires) | XVᵉ s. → | 3 E (par étude) | contrats de mariage, inventaires, partages, testaments | répertoire du notaire, tables de l'enregistrement |
| Insinuations, contrôle des actes | 1693–1790 | C | localiser un acte notarié | |
| Enregistrement : tables des successions et absences, mutations par décès | 1791 → | 3 Q | date de décès, héritiers, biens | excellent pour la filiation |
| Hypothèques | 1798 → | 4 Q | transcriptions de ventes, inscriptions | |
| Cadastre napoléonien | 1807–1850 env. | 3 P | propriétés, voisinage | états de sections, matrices |
| Justice de paix, tribunaux | 1790 → | U | tutelles, émancipations, actes de notoriété | |
| Fichier des décès INSEE (matchID) | 1970 → | en ligne | décès, n° d'acte, lieu | dérivée → demander l'acte |
| Presse, annuaires (Gallica) | XVIIᵉ s. → | gallica.bnf.fr | avis de décès, faire-part, annuaires | OCR à vérifier sur l'image |
| Mémoire des hommes | 1914 → | SGA en ligne | morts pour la France, JMO | |
| Grand Mémorial | 14-18 | culture.gouv.fr | matricules indexés | |

## Stratégies

- **Remonter une génération** : acte de mariage (filiation des deux époux, âges, domiciles) → naissance de
  chaque époux → mariage des parents. Avant 1792 : mariage paroissial, puis baptêmes.
- **Décès introuvable** : tables décennales des communes voisines, table des successions (3 Q), recensements
  (dernière présence), matchID (≥ 1970), transcriptions de décès (militaires, hôpitaux).
- **Filiation fragile** : contrat de mariage, inventaire après décès, déclaration de succession, tutelles.
- **Commune disparue ou fusionnée** : `geo_historique` (COG INSEE depuis 1943) ; avant : dictionnaire
  « Des villages de Cassini aux communes d'aujourd'hui » (EHESS).
- **Mobilité** : registres matricules (domiciles successifs), recensements, publications de bans.

Détails par source : [references/sources-detaillees.md](references/sources-detaillees.md).
