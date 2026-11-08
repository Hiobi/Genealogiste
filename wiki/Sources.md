# Sources, archives et limites

Le plugin combine des accès automatisés et des pistes à consulter vous-même. Il ne contourne pas
les restrictions d’accès d’un site et ne remplace pas la consultation d’un acte.

| Source ou fonction | Usage et prérequis |
|---|---|
| matchID / décès INSEE | Recherche de décès dans le périmètre de ses fichiers ; l’appariement CSV peut nécessiter un jeton |
| WikiTree | Recherche et profils ; configurer un identifiant d’application avant utilisation |
| Gallica | Recherche documentaire ; certaines protections réseau peuvent bloquer l’accès automatisé |
| Wikidata | Recherche et requêtes de recoupement ; relire les références des résultats |
| API Géo / COG | Normalisation des lieux et historique disponible ; le COG historique ne couvre pas toutes les périodes anciennes |
| ARK / IIIF | Résoudre une référence et consulter/archiver une pièce lorsque le service la rend accessible |
| Geneanet, Filae, archives, Mémoire des hommes | Liens et pistes de consultation selon le service ; pas de promesse d’extraction automatisée des pages protégées |
| FamilySearch | Ancien exporteur désactivé ; importer un GEDCOM obtenu séparément, sans fournir d’identifiants au plugin |

## Accès aux archives

Le [référentiel](../docs/archives.md) identifie les services et des accès aux fonds. Les informations sont
partielles et datées. Il distingue la communicabilité légale, la disponibilité déclarée en ligne et
l’existence de l’acte précis, qui nécessite encore une recherche.

Un résultat de disponibilité peut être **oui**, **non** ou **inconnu**. Une période annoncée, une couverture
partielle ou une exception communale ne devient pas une certitude. Fournir la commune et le département
pour exploiter les exceptions. Le [modèle de couverture](../docs/couvertures-archives.md) détaille ces règles.

Une date `releve_le` décrit un relevé automatisé ; `verifie_le` est réservé au contrôle humain.
Un site qui répond n’est pas un inventaire intégralement vérifié. Les cotes proposées sont des pistes
à confronter à l’inventaire du service.

## Quand vous consultez un site vous-même

Garder l’URL et une citation précise, puis fournir au plugin le contenu que vous avez le droit de réutiliser.
`source_collee` permet de documenter une information consultée manuellement. Indiquer sa provenance et
sa nature ; une transcription copiée demeure distincte de l’acte original.

Ne pas déposer une page ou une image privée dans une issue publique pour obtenir de l’aide.
Décrire le problème avec un exemple inventé, sans nom, identifiant ou lien familial réel.

## Pourquoi une recherche peut ne rien donner

L’absence peut venir d’une période non couverte, d’une variante de nom, d’un classement communal ancien,
d’un fonds lacunaire, d’un index incomplet, d’une protection anti-robots ou d’un service indisponible.
Consulter le journal et les messages d’erreur ; ne pas réessayer un envoi signalé comme indéterminé
avant d’avoir vérifié son résultat auprès du service.
