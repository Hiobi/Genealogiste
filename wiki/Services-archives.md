# Services d’archives et compatibilité

**Quel lien fournir et que peut faire Genealogiste ?** Le téléchargement dépend du service et du
document. Un ARK identifie une ressource ; il ne garantit ni sa numérisation, ni l’accès à son image.
Le pays ne détermine pas la compatibilité : un lien IIIF exploitable peut fonctionner sans adaptateur national.

Ce catalogue décrit **Genealogiste 0.19.1**, avec un état de qualification au **8 novembre 2026**.
Il complète le [référentiel des services français](../docs/archives.md), qui indique les lieux et fonds
à rechercher : être dans ce référentiel ne signifie pas disposer d’un téléchargement automatisé.

## Choisir le lien à fournir

| Ce que vous avez | Ce qu’il permet | Exemple ou marche à suivre |
|---|---|---|
| Lien de citation : ARK, permalien ou identifiant de notice | Retrouver et citer la ressource ; parfois résoudre la vue via un adaptateur | Conserver aussi dépôt, cote et numéro de vue ; un ARK de registre ne désigne pas nécessairement une vue précise |
| Lien de visionneuse | Ouvrir le document ; automatisation seulement si le service est reconnu, ou si sa page déclare un manifeste exploitable | AD59 : lien ARK de vue avec UUID, ou ARK du registre et numéro de page |
| Manifeste IIIF | Choisir un canvas (une vue) puis obtenir son service d’image ou l’image déclarée | [Manifeste e-manuscripta](https://www.e-manuscripta.ch/i3f/v20/3192957/manifest) ; `page=1` pour sa première vue |
| `info.json` ou URL Image API IIIF | Travailler sur l’image identifiée ; ce lien ne fournit pas la navigation de tout le registre | [Image LoC](https://tile.loc.gov/image-services/iiif/service:sgp:sgpbatches:batch_dlc_anacostia_ver01:data:sn84025948:0023728866A:1942081001:0202/info.json) |
| URL technique d’image | Télécharger le fichier accessible ; sa pérennité n’est pas affirmée | Lien reconnu : `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff` ou `.webp` ; garder séparément la citation |
| Fichier local | Lire une image ou conserver le fichier téléchargé manuellement, notamment un PDF | Fournir son chemin absolu dans votre espace privé, hors du dépôt du plugin |

`page` commence à **1** ; `0` conserve la vue du lien, ou choisit la première vue d’un manifeste.
Sur une image directe, ce paramètre ne découpe pas un PDF et ne découvre pas les pages voisines.
Un manifeste contenant plusieurs vues ne déclenche pas leur téléchargement complet. Une URL PDF
n’est pas reconnue comme image directe : télécharger le PDF manuellement puis fournir son chemin local.

## Comprendre les niveaux de prise en charge

- **Documenté** : capacité décrite par une institution ; ce n’est pas une intégration livrée.
- **Implémenté** : chemin présent dans la version indiquée du plugin.
- **Simulé** : contrat exercé avec des réponses et images synthétiques, sans réseau.
- **Éprouvé** : recette réseau réussie sur une ressource datée, avec résultat décrit ci-dessous.
- **Manuel / non qualifié** : pas d’adaptateur livré ou de contrat exploitable confirmé ; fournir un
  fichier obtenu auprès du service ou un lien technique explicite. « Non qualifié » ne signifie pas « API inexistante ».

Une réponse HTTP 200 sur une notice ne prouve pas l’accès au document. Un essai sur une image ne valide
pas tous les fonds du portail. Aucun contrôle humain des entrées n’est ajouté par ces recettes.

## Services avec un chemin automatisé livré

| Pays et service | Documents ou périmètre | Mécanisme livré et lien attendu | Fonctions et limites | Preuves |
|---|---|---|---|---|
| France — [AD59, Archives départementales du Nord](https://archivesdepartementales.lenord.fr/) | Vues de registres et tables ; deux ressources qualifiées | Adaptateur `visualizer_api` : ARK de vue avec UUID, ou registre + `page` | Résolution d’une vue, aperçu, recadrage local, original et archivage. IIIF utilisé si annoncé ; absent des deux ressources essayées. API de visionneuse observée, sans contrat public versionné qualifié ; pas un adaptateur pour toutes les AD | Implémenté, simulé, éprouvé sur un registre et une table le 08/11/2026 : [contrat et résultats](../docs/visionneuse-ad59.md) |
| France — [Gallica, BnF](https://gallica.bnf.fr/) | Images de documents numérisés accessibles par IIIF | Résolution de l’ARK Gallica vers Image API ; manifeste, `info.json` ou URL IIIF explicites acceptés | Choix `fN` ou `page`, aperçu, recadrage, original et archivage si accessibles ; protections réseau et conditions propres au document | [API officielle BnF](https://api.bnf.fr/fr/api-iiif-de-recuperation-des-images-de-gallica), implémenté et simulé ; pas de recette réseau Gallica dans le lot 0.19.0 |
| Suisse — [e-manuscripta](https://www.e-manuscripta.ch/) | Documents numérisés ; premier canvas du manifeste `3192957` essayé | IIIF générique, sans adaptateur spécifique ; [API officielle](https://www.e-manuscripta.ch/wiki/apiinfo?lang=de) | Choix de vue, aperçu, recadrage IIIF, original et archivage. PDF proposé par l’institution distinct du parcours image éprouvé | Implémenté, simulé pour le mécanisme générique ; une ressource éprouvée le 08/11/2026 : [résultats](../docs/telechargement-international.md#résultats-natifs) |
| États-Unis — [Library of Congress](https://www.loc.gov/) | Images numérisées ; une page de journal essayée | IIIF générique via `info.json` ; [Image Services officiel](https://www.loc.gov/apis/micro-services/image-services/) | Aperçu, recadrage, original et archivage ; pas de recherche automatique dans l’ensemble des collections par cet outil. Repli `full/full` exercé lorsque `full/max` est refusé | Implémenté, simulé pour le mécanisme générique ; une image éprouvée le 08/11/2026 : [résultats](../docs/telechargement-international.md#résultats-natifs) |
| Tous pays — autre fournisseur IIIF | Document dont le manifeste ou service d’image est accessible | Presentation v2/v3, Image API, ou image déclarée dans un canvas sans service ; une page HTML peut déclarer un unique manifeste | Choix de vue et parcours image selon le contenu réellement fourni. Plusieurs manifestes : demander lequel ; pas d’exécution JavaScript ni de résolution universelle des visionneuses | Implémenté et simulé ; essais réels limités aux services nommés ci-dessus |
| Tous pays — fichier direct ou local | URL d’image reconnue ou fichier local (image/PDF) ; pas de ZIP, audio ou vidéo dans ce parcours | URL directe d’image reconnue ou chemin local ; PDF à télécharger manuellement, aucun adaptateur de portail | Original conservé et note compagnon. Aperçu et recadrage pour les images décodables ; pas de rendu de pages PDF implémenté dans `archive_image` | Implémenté et simulé ; pas de qualification générale des liens de chaque fournisseur |

Pour les autres services français (AD, archives communales, Archives nationales, ANOM, SHD, etc.),
consulter leur fiche via `archives_service`. Les champs `telechargement` exposent le mode et l’adaptateur
connus ; IIIF peut rester inconnu. Ne pas extrapoler l’adaptateur AD59 aux services utilisant une interface semblable.

## Services documentés avec accès manuel ou non qualifié

Ces portails constituent des pistes pour poursuivre la qualification. Aucun adaptateur spécifique de
téléchargement n’est livré pour eux en 0.19.1. Les sources institutionnelles et leurs contraintes détaillées
figurent dans la [matrice documentaire internationale](../docs/telechargement-international.md#matrice-documentaire-par-service).
Aucun appel authentifié ni commande payante n’a été effectué.

| Pays et institution / portail | Périmètre documentaire | Accès documenté, API et limites | Parcours disponible avec le plugin |
|---|---|---|---|
| Belgique — [Archives de l’État, AGATHA](https://agatha.arch.be/fr/help/) | Documents numérisés consultables dans AGATHA | Compte gratuit pour la consultation ; téléchargements limités selon l’aide et le document. API/IIIF non qualifiés | Télécharger dans l’interface, puis fournir le fichier et la référence |
| Allemagne — [Bundesarchiv, invenio](https://www.bundesarchiv.de/im-archiv-recherchieren/archivgut-recherchieren/recherchesysteme/invenio/) | Notices et documents numérisés | Restrictions possibles malgré une notice visible ; API de téléchargement non qualifiée. L’étude datée rapporte aussi des perturbations d’accès | Consultation manuelle selon accès, puis fichier ; état du service à revérifier |
| Italie — [Antenati / ICAR](https://icar.cultura.gov.it/sistemi-e-portali/antenati) | État civil et registres | Consultation gratuite sans inscription documentée ; API/IIIF de téléchargement non qualifiés ici | Fichier manuel, ou lien IIIF explicitement obtenu ; aucun endpoint supposé |
| Espagne — [PARES](https://pares.cultura.gob.es/preguntas-frecuentes.html) | Documents numérisés des fonds décrits | Consultation sans compte, sauvegarde/impression par l’interface ; pas de contrat API de téléchargement qualifié | Fichier sauvegardé depuis la visionneuse, avec provenance |
| Luxembourg — [Archives nationales / Query](https://anlux.public.lu/fr/documents-numerises.html) | Documents numérisés présentés dans Query | Téléchargement annoncé ; contrat API/IIIF non qualifié | Fichier ou URL directe obtenue sur le portail, selon format |
| Royaume-Uni — [The National Archives / Discovery](https://www.nationalarchives.gov.uk/help-with-your-research/discovery-help/understanding-your-search-results/) | Documents proposés au téléchargement ; certaines notices renvoient à d’autres dépôts | Compte, paiement ou offre gratuite selon notice ; ZIP/PDF possibles. API de téléchargement non qualifiée | Connexion et commande manuelles ; extraire manuellement un ZIP puis fournir le fichier utile |
| États-Unis — [NARA Catalog](https://www.archives.gov/research/catalog/help/api) | Descriptions et métadonnées d’objets numériques | API publique documentée avec clé pour chaque requête, 10 000 requêtes/mois par défaut ; demande de ne pas conserver ni mettre en cache les réponses API. Adaptateur non implémenté | Consultation manuelle ; ne pas fournir de clé dans la conversation. Un futur adaptateur doit respecter la politique NARA ; pas de promesse de résolution d’une notice vers son objet |
| Canada — [Bibliothèque et Archives Canada / LAC](https://library-archives.canada.ca/eng/services/public/access-information-privacy/pages/records-request.aspx?wbdisable=true) | Copies numérisées dans Collection Search, selon notice | Accès et reproduction variables ; API/IIIF de téléchargement non qualifiés | Fichier ou lien direct obtenu manuellement ; une demande de reproduction reste une démarche distincte |
| Canada — [BAnQ, Advitam](https://advitam.banq.qc.ca/aide/resultats-filtres) et [BAnQ numérique](https://www.banq.qc.ca/sites/default/files/2022-12/Aide-memoire_BAnQNumerique.pdf) | Archives et patrimoine numérisé, ressources de nature variable | Restrictions par pièce ; certains documents sur postes dédiés, ressources sur abonnement distinctes. API/IIIF de téléchargement non qualifiés | Consultation selon les droits, puis fichier autorisé ; une API bibliographique ne prouve pas l’accès à l’image |

## Fonctions disponibles après résolution d’une image

| Étape | Outil / comportement | Limites à connaître |
|---|---|---|
| Trouver le téléchargement | Résolution et sélection côté Python, via les mécanismes ci-dessus | Pas de recherche autonome de toutes les cotes ou images d’un portail ; la recherche dans les inventaires peut rester manuelle |
| Sélectionner une vue | `page` sur un manifeste ou registre reconnu ; vue portée par le lien AD59/Gallica | Une vue par appel ; `info.json` seul ne donne pas la pagination d’un registre |
| Voir et recadrer | `archive_image` : aperçu 800 px en gris par défaut ; région ciblée ensuite | Largeur bornée à 2000 px, pas d’agrandissement au-delà de la région source ; recadrage local si absence de IIIF |
| Lire / transcrire | Demande de lecture assistée, notamment `/genealogiste:transcris` | Étape du modèle après obtention de l’image ; incertitudes à relire. Les recettes réseau ne valident ni transcription ni exactitude des noms et dates |
| Conserver l’original | `piece_archiver` récupère la vue entière en pleine résolution et couleur, ou le fichier fourni | Ne conserve pas seulement l’aperçu ; un PDF local peut être conservé sans rendre ses pages pour lecture |
| Classer et documenter | Nom conventionnel, classement selon personnes/type, note Markdown compagnon, empreinte SHA-256 et registre local | Sans informations suffisantes : `_À trier/`. Rangement depuis un sous-dossier, renommages ciblés et déplacement de la note avec restauration par journal ; médias déjà liés à l’arbre protégés |
| Conserver la provenance | Liens fournis, ARK de vue et de ressource distincts, URL technique, cote, titre, droits reçus, date de consultation | Champs absents laissés inconnus ; aucune pérennité affirmée pour une simple URL technique. Conserver aussi les références relevées manuellement |
| Rattacher à l’arbre | Opérations et citation suggérées, puis `arbre_proposer` / `arbre_appliquer` après accord | Archiver ne modifie pas l’arbre ; une image téléchargée ne confirme pas seule une filiation |

Voir le [guide des pièces et médias](../docs/pieces.md#archiver-une-pièce-consultée-en-ligne-ark-iiif)
pour les paramètres, le nommage, les emplacements et la note compagnon.

## Exemples de demandes

Les liens publics ci-dessous désignent les exemples techniques des études ; ils ne justifient aucun
rattachement à votre arbre. Les demandes sont à formuler au client qui charge Genealogiste.

**API de visionneuse AD59 :**

> Montre un aperçu de la vue https://archivesdepartementales.lenord.fr/ark:/33518/d31bpqk27xhj/b27563d3-2ef8-4798-832a-d604a4e131dc avec archive_image. Si c’est la bonne vue, conserve son original avec piece_archiver et sa note, sans modifier l’arbre.

Autre sélection éprouvée : ARK de registre `ark:/33518/q0km71zxrv5s`, `page=25`.

**ARK Gallica, résolu vers IIIF :**

> Utilise archive_image sur https://gallica.bnf.fr/ark:/12148/bpt6k5619759j/f12.item pour lire la vue 12 ; conserve ensuite l’original avec piece_archiver si l’accès réussit.

Cet exemple illustre le contrat simulé ; il n’a pas fait partie des quatre recettes réseau.

**Manifeste IIIF, avec choix de vue :**

> Utilise archive_image sur https://www.e-manuscripta.ch/i3f/v20/3192957/manifest, page=1. Montre l’aperçu avant de recadrer une zone utile ; archive la même vue en gardant ses métadonnées.

**Image API sans manifeste :**

> Ouvre avec archive_image l’image désignée par ce [info.json LoC](https://tile.loc.gov/image-services/iiif/service:sgp:sgpbatches:batch_dlc_anacostia_ver01:data:sn84025948:0023728866A:1942081001:0202/info.json), puis conserve son original et sa note avec piece_archiver. N’invente pas d’ARK ni de cote.

**Fichier direct / accès manuel :**

> Utilise le lien direct de cette image publique : https://archivesdepartementales.lenord.fr/images/b27563d3-2ef8-4798-832a-d604a4e131dc.jpg. Montre un aperçu avec archive_image, puis archive l’original avec piece_archiver ; garde séparément son [ARK de vue AD59](https://archivesdepartementales.lenord.fr/ark:/33518/d31bpqk27xhj/b27563d3-2ef8-4798-832a-d604a4e131dc) pour la citation.

> J’ai téléchargé le fichier autorisé dans `/chemin/prive/acte.jpg`. Lis un aperçu, puis conserve-le avec sa note et la provenance que je fournis. Pour `/chemin/prive/acte.pdf`, conserve le PDF ; prépare manuellement une image de la page utile si je veux une lecture assistée.

Le lien d’image AD59 est celui relevé pendant la recette ; c’est une adresse technique, pas un permalien.
Les chemins locaux sont à remplacer par vos propres fichiers.
Les informations de personnes, types, lieux et cotes sont à renseigner uniquement lorsqu’elles sont établies.

**Repli compréhensible :**

> Cette visionneuse n’est pas qualifiée, ou l’image exige une connexion. Fournissez son manifeste IIIF, un lien direct accessible, ou le fichier téléchargé depuis votre compte. Gardez le permalien et la cote pour la citation ; ne transmettez pas votre mot de passe ou votre session.

Un refus, une page HTML de connexion ou un objet non image reste une erreur explicite ; le plugin
ne traite pas une page de connexion comme un original et ne contourne pas le contrôle d’accès.

## Économiser les tokens et conserver les droits

Le résolveur lit et filtre les réponses HTML/JSON côté Python. Il renvoie les informations de la vue
utile et ne transmet pas au modèle le manifeste entier, le bundle JavaScript ou toutes les vues voisines.
Lire d’abord l’aperçu, puis une région ciblée si nécessaire, avant d’archiver l’original.

Sans IIIF, l’original téléchargé sert à l’aperçu, aux recadrages locaux et à l’archivage. Avec IIIF,
aperçu et recadrage peuvent être servis à distance jusqu’à la présence de l’original en cache.
Une pièce déjà archivée et intacte est réutilisée pour la même source et page, sans nouvelle requête.
Cela n’implique pas que tout cache soit permanent ni autorisé par tout fournisseur.

Les réponses HTTP `no-store` ne sont pas placées dans le cache HTTP. Les conditions NARA demandent
de ne pas stocker/cache les réponses API ; l’adaptateur NARA n’existe pas et son éventuelle livraison
devra respecter cette politique spécifique. Le cache d’images et l’archivage d’une pièce sont distincts
du cache de métadonnées ; vérifier les conditions de chaque ressource avant conservation et réutilisation.

Conserver les déclarations de licence et leur provenance quand elles sont reçues, sans inventer un droit
manquant. L’accès à une image ne vaut pas autorisation de publication ou de réutilisation commerciale.
Les estimations de tokens de l’outil sont indicatives, pas une mesure de facturation.

## Vérification et maintenance

Les preuves détaillées restent dans les études [AD59](../docs/visionneuse-ad59.md) et
[internationale](../docs/telechargement-international.md). Les quatre recettes du 08/11/2026 couvrent
résolution, aperçu, recadrage, original, note et répétition sans réseau, sur un arbre vide et un dossier
jetable supprimé ensuite. Elles exercent le module Python ; pas de validation d’un dialogue complet,
de transcription ou d’affichage Obsidian. Les tests ordinaires sont synthétiques et sans réseau.

Pour rejouer explicitement les ressources publiques, hors CI :

```bash
make verifier-telechargements SERVICE=ad59
# autres choix : ad59_td, suisse, loc, tous
```

Pour maintenir une entrée :

1. Vérifier le [référentiel](../docs/archives.md), les adaptateurs livrés et les sources officielles ;
   ajouter version, date, ressource, résultat et limites observées, sans secret ni donnée familiale réelle.
2. Si l’API, la visionneuse, les conditions ou la licence changent, marquer l’entrée **à revérifier**,
   préciser la capacité affectée et ouvrir une issue reproductible. Une panne DNS reste un échec
   d’environnement ; elle ne prouve pas l’absence d’API ou une panne du portail.
3. Contrôler le contrat avec des fixtures synthétiques ; qualifier séparément la recette réseau, qui
   peut réussir, être partielle ou échouer. Ne rétablir « éprouvé » que pour le périmètre effectivement rejoué.
4. Corriger cette source versionnée et ses études si nécessaire ; régénérer les liens, fusionner puis
   publier selon [Maintenir le wiki](Maintenance.md). `releve_le` est automatisé ; `verifie_le` reste humain.

Ce catalogue présente les capacités ; il ne remplace pas les règles de couverture par commune et période,
ni la vérification de l’acte recherché dans l’inventaire du dépôt.
