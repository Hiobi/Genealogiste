---
name: sources-francaises
description: Connaissance des sources généalogiques françaises et de leur localisation — état civil (1792+), registres paroissiaux BMS, tables décennales, recensements (1836+), registres matricules (classes 1867+), notaires (contrats de mariage, inventaires), enregistrement (tables des successions), cadastre napoléonien, hypothèques, archives départementales, Gallica, matchID, Mémoire des hommes. À utiliser pour « où trouver », « quelle source », « quelle cote », « quelles archives », plan de recherche, lacunes, prochaine source à consulter.
---

# Sources françaises — quoi, où, pour quoi

Toujours préciser : **type de source** (originale/dérivée), **service** (AD, mairie, SHD…),
**cote typique** (cadre de classement, à vérifier dans l'inventaire), **communicabilité**, **accès en ligne**.
Outils : `cotes_a_consulter`, `prochaine_source`, `liens_recherche`, `sources_catalogue` (tout ce que le plugin connaît, dont les sites tiers : cercles, relevés, bases thématiques), `communicabilite`, `archives_service` (service réel : site, mise en ligne, NAAN ; docs/archives.md), `ark_resoudre`, `archives_registres`,
`archives_naviguer` (vues d'un registre), `archive_image` (lecture d'une vue), `piece_archiver` (conservation).
Pour AD59 et les services Mnesys du référentiel (AD14, AD19, AD25, AD27, AD37, AD39, AD51, AD55, AD58, AD69, AD80, AD90, AD91, AD972), `archives_registres(service=…, commune=…, annee=…, type_acte="N"|"M"|"D", personne=id)`
localise les registres depuis le résultat officiel. Une page par appel ; poursuivre explicitement avec
`page_suivante`. `NMD` ou le type vide ne filtre pas le type ; `type_acte="TD"` donne les tables décennales
couvrant l'année ; `annee_fin` (≥ `annee`) recherche un intervalle (ex. 1790-1802 ou une décennie).
Ensuite `archives_naviguer` parcourt les vues, `archive_image` les lit et `piece_archiver` conserve l'original.
Un résultat vide ne démontre pas que l'acte n'existe pas ; un blocage conserve une tâche manuelle au journal.
Défi anti-robot (`bloque: "anti-robot"`, ex. Anubis aux AD de la Lozère) ou `consultation_manuelle` dans
`archives_service` : ne pas relancer ni contourner ; demander à l'utilisateur une capture ou l'image de la vue,
l'enregistrer avec `media_enregistrer(chemin, nom, classer=true)`, la lire, puis tracer avec `source_collee`.
En mode autonome (aucune personne présente), ce blocage devient une tâche manuelle de l'enquête (`enquete_noter`).

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

## Types acceptés par les outils

Pour `archives_service` et `communicabilite`, utiliser les clés canoniques décrites dans
[le référentiel](../../docs/archives.md#types-de-documents-communs--129). `matricules`, `notaires`,
`recensements` et `justice` sont acceptés comme alias. `judiciaire` est la clé canonique
pour la justice. Les types larges `paroissiaux`, `enregistrement` et `insinuation` demandent de préciser
le fonds et son régime : une réponse `communicable: null` appelle une vérification auprès du service.
Les types naturalisations et hospitalier restent à qualifier. Une clé reconnue n'annonce aucun accès en ligne.
Avec `document`, `archives_service` renvoie `visionneuse_pour_la_demande` : l'accès propre au type
(`origine: document`, ex. matricules sur une autre application que l'état civil), sinon celui du service
(`service`), sinon `inconnu`. Si `telechargement.etat` vaut `a_qualifier_pour_ce_type`, l'adaptateur du
service ne s'applique pas à ce fonds : passer par le lien de consultation, un lien IIIF ou un fichier téléchargé.

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
