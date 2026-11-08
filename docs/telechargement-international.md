# Téléchargement international : résultats et qualification

Le 8 novembre 2026, quatre recettes natives ont réussi avec
[`scripts/verifier_telechargements.py`](../scripts/verifier_telechargements.py) : un registre
et une table AD59, un canvas e-manuscripta et une image de la Library of Congress.
Chaque cas couvre résolution, aperçu, recadrage, `piece_archiver` et répétition de
l'archivage sans réseau. Ces résultats qualifient quatre ressources de trois services,
pas des pays entiers.

## Résultats natifs

Les essais ont utilisé un arbre vide et un dossier jetable supprimé ensuite, sans
écriture dans une généalogie réelle. Aucun acte, image, PDF ou JSON réel n'a été ajouté
au dépôt. La seconde conservation a réussi sans nouvelle requête dans les quatre cas.

| Ressource | Mode | Original → aperçu | Estimation aperçu | Réseau pour le cas complet |
|---|---|---|---|---|
| AD59, registre décrit dans [l'étude AD59](visionneuse-ad59.md) | `visionneuse:visualizer_api` | 2056 × 1456 → 800 × 567 | 605 tokens | API et image : 2 réponses 200 |
| AD59, table décennale `q0km71zxrv5s`, page 25 | `visionneuse:visualizer_api` | 1816 × 2450 → 800 × 1079 | 1151 tokens | Sélection par page, résolution de vue et image : 3 réponses 200 |
| e-manuscripta, premier canvas du manifeste `3192957` | `iiif` | 5170 × 7160 → 800 × 1108 | 1182 tokens | Manifeste, info, aperçu, recadrage, image pleine : 5 réponses 200 |
| LoC, image de l’exemple officiel Image Services | `iiif` | 3156 × 4663 → 800 × 1182 | 1261 tokens | Info, aperçu, recadrage : 200 ; image pleine `full/max` : 400, puis repli `full/full` : 200, soit 5 requêtes |


Le [manifeste suisse](https://www.e-manuscripta.ch/i3f/v20/3192957/manifest) contient quatre
canvases ; la recette choisit le premier, dont le service est
`https://www.e-manuscripta.ch/i3f/v20/3192958`. Son original mesure 5170 × 7160.
Le [service LoC testé](https://tile.loc.gov/image-services/iiif/service:sgp:sgpbatches:batch_dlc_anacostia_ver01:data:sn84025948:0023728866A:1942081001:0202/info.json)
expose Image API v2 : le 400 sur `full/max` a exercé le repli compatible `full/full`.
Les [contrats et liens AD59](visionneuse-ad59.md) détaillent le dictionnaire par page
observé et l'UUID complet de la table obtenu par le pipeline.

Les tokens sont une estimation par surface de pixels, environ 1/750, pas une facture
ou une mesure d'inférence. Aucun LLM distant n'a été appelé : ni transcription ni lecture
humaine ne sont validées. Les recettes exercent le module Python, sans attester une
invocation complète du plugin dans un dialogue. Aucun `verifie_le` n'est revendiqué.

## Matrice documentaire par service

Les liens sont des sources primaires. « Documenté » signifie qu'une fonction est décrite
par l'institution ; seuls les cas du tableau précédent ont subi une recette native.
Les autres accès restent non qualifiés ou manuels, sans compte ni commande effectués.

| Service échantillonné | Accès documenté et contraintes | Voie proposée / état natif |
|---|---|---|
| Belgique — Archives de l'État, AGATHA | [Aide officielle](https://agatha.arch.be/fr/help/) : inscription gratuite obligatoire pour consulter les documents numérisés ; téléchargement depuis la visionneuse, au plus 100 actes/jour ; certaines images iconographiques non téléchargeables. | Authentification/UI : téléchargement manuel puis fichier local. Adaptateur automatique non qualifié ; aucun compte utilisé. |
| Allemagne — Bundesarchiv, invenio | [Présentation officielle](https://www.bundesarchiv.de/im-archiv-recherchieren/archivgut-recherchieren/recherchesysteme/invenio/) : consultation de documents numérisés, avec restrictions possibles même si la notice est visible. [Avis du 15 septembre 2026](https://www.bundesarchiv.de/nachricht/einschraenkungen-bei-online-anwendungen-des-bundesarchivs/) : accès momentanément perturbé et recherche sans connexion limitée. | UI/repli manuel, restrictions par pièce. Aucun contrat de téléchargement API ou IIIF qualifié ici ; ne pas généraliser à tous les services allemands. |
| Suisse — e-manuscripta, bibliothèques et archives | [API officielle](https://www.e-manuscripta.ch/wiki/apiinfo?lang=de) : manifeste IIIF sur la notice, Image API, PDF ; [Zentralbibliothek Zürich](https://data.zb.uzh.ch/map/books/data-map-der-zentralbibliothek-zurich/page/e-manuscripta-iiif) : Presentation 2.0, Image 2.1 et exemples complets. | IIIF générique éprouvé nativement sur le premier canvas d’un manifeste, sans ARK ni adaptateur national ; lecture, recadrage et archivage réussis (détails ci-dessous). |
| Italie — Antenati | [ICAR, propriétaire du portail](https://icar.cultura.gov.it/sistemi-e-portali/antenati) : consultation gratuite sans inscription ; recherches par noms et registres. | Consultation documentée ; téléchargement automatisé/API/IIIF non qualifiés par les sources lues. Lien direct IIIF fourni explicitement ou fichier manuel, sans inventer d'endpoint Antenati. |
| Espagne — PARES | [FAQ officielle](https://pares.cultura.gob.es/preguntas-frecuentes.html) : consultation gratuite sans compte, enregistrement/impression des images depuis la visionneuse ; contraintes de réutilisation selon le document. | UI/repli manuel. Adaptateur automatique non qualifié ; la fonction de sauvegarde ne prouve pas une API publique de téléchargement. |
| Luxembourg — Archives nationales | [Documents numérisés](https://anlux.public.lu/fr/documents-numerises.html) : documents téléchargeables ; l'ensemble des scans et audios est annoncé dans Query. | Téléchargement UI/lien de fichier fourni. Contrat IIIF/API de Query non qualifié ici. |
| Royaume-Uni — The National Archives, Discovery | [Comprendre les résultats](https://www.nationalarchives.gov.uk/help-with-your-research/discovery-help/understanding-your-search-results/) : téléchargements selon la notice, parfois ZIP/PDF et paiement. [Microfilms numériques gratuits](https://www.nationalarchives.gov.uk/help-with-your-research/research-guides/free-online-records-digital-microfilm) : compte Discovery requis et règles d'usage. | Compte/panier/UI : repli manuel, sans connexion automatique ni commande. Une notice Discovery peut décrire un fonds détenu ailleurs. |
| États-Unis — Library of Congress | [Image Services](https://www.loc.gov/apis/micro-services/image-services/) : Image API IIIF avec paramètres région/taille et métadonnées `info.json`. | IIIF générique éprouvé nativement sur une image, indépendamment d’ARK ; lecture, recadrage et archivage réussis, avec repli Image API v2 (détails ci-dessous). |
| États-Unis — NARA Catalog | [API officielle](https://www.archives.gov/research/catalog/help/api) et [démarrage](https://www.archives.gov/research/catalog/help/api-getting-started) : API v2 JSON ; clé `x-api-key` requise ; exemples avec `digitalObjects`, dont `objectUrl`. | API spécifique documentée, adaptateur non implémenté et aucun appel authentifié tenté. Une URL d'objet n'est pas nécessairement une image : vérifier type et format. |
| Canada — Library and Archives Canada / BAC | [Accès aux documents](https://library-archives.canada.ca/eng/services/public/access-information-privacy/pages/records-request.aspx?wbdisable=true) : copies numérisées dans Collection Search ; conditions d'accès dans la notice. [Restrictions](https://library-archives.canada.ca/eng/services/public/using-lac-material/material-restrictions/pages/material-restrictions.aspx) : accès et copie variables. | UI/lien de fichier explicite ; API/IIIF de téléchargement non qualifiés ici. Certaines demandes passent par une procédure distincte, non déclenchée. |
| Canada — BAnQ, Advitam / BAnQ numérique | [Aide Advitam](https://advitam.banq.qc.ca/aide/resultats-filtres) : documents numériques parfois accessibles seulement sur postes dédiés, déclarations de droits par document ; [aide-mémoire BAnQ numérique](https://www.banq.qc.ca/sites/default/files/2022-12/Aide-memoire_BAnQNumerique.pdf) distingue patrimoine et ressources sur abonnement. | UI/fichier manuel selon droits et disponibilité. Aucun contrat de téléchargement IIIF/API qualifié ; ne pas confondre API bibliographique et accès aux images. |


## Contrôles JSON préalables et exemples reproductibles

Avant les recettes natives, des requêtes `curl` ont reçu HTTP 200 et leurs JSON ont été
inspectés : [manifeste suisse](https://www.e-manuscripta.ch/i3f/v20/3192957/manifest),
[Image API suisse indépendante](https://www.e-manuscripta.ch/i3f/v21/3192960/info.json)
et [Image API LoC](https://tile.loc.gov/image-services/iiif/service:sgp:sgpbatches:batch_dlc_anacostia_ver01:data:sn84025948:0023728866A:1942081001:0202/info.json).
Ces exemples proviennent de la [Zentralbibliothek Zürich](https://data.zb.uzh.ch/map/books/data-map-der-zentralbibliothek-zurich/page/e-manuscripta-iiif)
et de la [documentation Image Services LoC](https://www.loc.gov/apis/micro-services/image-services/).

Le manifeste est Presentation v2 ; les deux services image annoncent le profil `level2`.
L'exemple suisse `3192960` mesure 5750 × 7160 et n'est pas le premier canvas `3192958`
utilisé par la recette : il constitue uniquement un contrôle JSON distinct. Les dimensions
LoC sont 3156 × 4663. Des tentatives initiales ont rencontré une restriction DNS de
l'environnement ; les contrôles autorisés et les quatre recettes natives ont ensuite réussi.

## Résolution, coût et accès non gérés

Un identifiant ARK, DOI ou de catalogue sert à référencer une ressource ; il ne fournit
pas à lui seul une URL d'image. Le [projet de spécification ARK](https://arks-org.github.io/arkspec/draft-kunze-ark.html)
précise que la persistance dépend du service et non de la syntaxe. C'est un Internet-Draft,
pas une garantie de téléchargement. Le résolveur doit accepter des sources non ARK et
qualifier les services individuellement.

Le chemin générique traite les liens IIIF explicites et les fichiers directs ; une
visionneuse reconnue nécessite un adaptateur qualifié. Les autres cas proposent un fichier
téléchargé manuellement ou un lien IIIF fourni par l'utilisateur. Les accès avec compte
et les API spécifiques non implémentées, notamment NARA, restent hors recette. Une
notice accessible ne démontre pas que le document est téléchargeable.

Lire et sélectionner les JSON côté Python évite d'envoyer au modèle le HTML des
visionneuses ou des manifestes entiers. Retourner seulement la vue utile, ses dimensions,
sa citation, les métadonnées et les droits reçus. Ne pas précharger les voisins ; borner
les réponses et contrôler les types reçus : une page HTML de connexion n'est pas une image.
Séparer URL de citation et endpoint technique, sans inventer les informations manquantes.

Pour NARA, la [documentation officielle](https://www.archives.gov/research/catalog/help/api)
exige une clé API, annonce 10 000 requêtes mensuelles par défaut et demande de ne pas
conserver ni mettre en cache les réponses. Un futur adaptateur devra appliquer cette
politique propre au fournisseur ; aucune clé ni réponse NARA n'entre dans les fixtures.

Les tests ordinaires restent synthétiques et indépendants du réseau : IIIF v2/v3 sans
ARK, canvas sans service image, objet non image, réponse de connexion, refus et droits
absents. Les recettes réseau sont explicites, hors CI et limitées aux ressources choisies.
Aucune authentification automatique, dépense ou résolution de défi n'a été effectuée.
Les limites d'accès et les déclarations de droits restent propres au service et à la pièce.
