# Sources, archives et limites

Le plugin combine des accès automatisés et des pistes à consulter vous-même. Il ne contourne pas
les restrictions d’accès d’un site et ne remplace pas la consultation d’un acte.

| Source ou fonction | Usage et prérequis |
|---|---|
| matchID / décès INSEE | Recherche de décès dans le périmètre de ses fichiers ; l’appariement CSV peut nécessiter un jeton |
| WikiTree | Recherche et profils ; configurer un identifiant d’application avant utilisation. Depuis novembre 2026, WikiTree refuse le User-Agent du plugin (403 « AI-scraping bots ») : le refus est signalé comme blocage, sans contournement ; demander une autorisation à WikiTree, ou consulter le site vous-même puis utiliser `source_collee` ([détails](../docs/securite.md#identification--user-agent-et-contact-facultatif)) |
| Gallica | Recherche documentaire ; certaines protections réseau peuvent bloquer l’accès automatisé |
| Wikidata | Recherche et requêtes de recoupement ; relire les références des résultats |
| API Géo / COG | Normalisation des lieux et historique disponible ; le COG historique ne couvre pas toutes les périodes anciennes |
| ARK / IIIF | Résoudre une référence et consulter/archiver une pièce lorsque le service la rend accessible |
| Geneanet, Filae, archives, Mémoire des hommes | Liens et pistes de consultation selon le service ; pas de promesse d’extraction automatisée des pages protégées |
| FamilySearch | Ancien exporteur désactivé ; importer un GEDCOM obtenu séparément, sans fournir d’identifiants au plugin |

## Associations, relevés et bases thématiques

Le plugin connaît aussi des **sites tiers** : cercles généalogiques (au moins un pour 73 départements, d’après
l’annuaire de la FFG), réseaux de relevés bénévoles (GeneaBank, FranceGenWeb), bases thématiques (protestants,
déportés, Français libres, émigrants vers le Québec…) et outils de lieux (Cassini, DicoTopo). Demander par
exemple « quelles ressources pour le Finistère ? » ou « que connaît le plugin sur la Seconde Guerre mondiale ? »
(`sources_catalogue`). `liens_recherche` ajoute ceux du département du lieu.

Ces sites sont consultés **dans votre navigateur** : le plugin n’y fait aucune requête. Un relevé reste une
source dérivée : noter la référence qu’il donne (commune, date, numéro), puis consulter l’acte original.
Détails : [sites tiers](../docs/sites-tiers.md). Pour 1939-1945 (prisonniers, déportés, STO, résistants,
épuration, incorporés de force) : [Seconde Guerre mondiale](../docs/seconde-guerre-mondiale.md).

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

Pour l’AD59 et quatorze services Mnesys, `archives_registres` retrouve un registre à partir d’une commune et
d’une année, sans connaître sa cote ni son ARK ; certains services, dont l’AD59, couvrent aussi les registres
matricules (`RM`, par classe) et les tables des successions (`SUCC`, par bureau). Pour l’AD59 s’y ajoutent les
recensements (`REC`), les fiches décès (`FD`), les hypothèques (`HYP`) et les plans du cadastre (`CAD`), ainsi
que la cote et la mise en ligne prévue d’un registre d’état civil absent en ligne (classeur 3 E) :
[fonds et limites](Services-archives.md#autres-fonds-numérisés-des-ad59). `archives_planche` montre plusieurs vues
sur une seule image et `archives_sonder` indique la vue à lire pour atteindre une date.

Le [catalogue des services d’archives](Services-archives.md) précise les API, les fonctions de
téléchargement livrées, les essais réels et les cas qui demandent un fichier manuel.

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
