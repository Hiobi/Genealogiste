# Services d’archives et compatibilité

**Quel lien fournir et que peut faire Genealogiste ?** Le téléchargement dépend du service et du
document. Un ARK identifie une ressource ; il ne garantit ni sa numérisation, ni l’accès à son image.
Le pays ne détermine pas la compatibilité : un lien IIIF exploitable peut fonctionner sans adaptateur national.

Ce catalogue décrit la version de Genealogiste indiquée en pied de page ; chaque qualification réseau est
datée (recettes du **8 novembre 2026**). La recherche de registres AD59 ci-dessous complète ce périmètre.
Il complète le [référentiel des services français](../docs/archives.md), qui indique les lieux et fonds
à rechercher : être dans ce référentiel ne signifie pas disposer d’un téléchargement automatisé.

## Trouver un registre AD59 sans ARK

Avec une commune et une année précises, demander par exemple :

> Cherche les registres de naissance de Saint-Vaast-en-Cambrésis pour 1860 aux archives du Nord.

L'outil `archives_registres(service="AD59", commune="Saint-Vaast-en-Cambrésis", annee=1860,
type_acte="N")` renvoie les références lues dans la page officielle : titre, cote, ARK, période et,
si affiché, nombre de vues. La même recherche fonctionne pour quatorze autres services, dont le moteur Mnesys
est lu directement : Calvados (AD14), Corrèze (AD19), Doubs (AD25, tables décennales, matricules et successions seulement),
Eure (AD27), Indre-et-Loire (AD37), Jura (AD39), Marne (AD51), Meuse (AD55), Nièvre (AD58), Rhône (AD69), Somme (AD80),
Territoire de Belfort (AD90), Essonne (AD91) et Martinique (AD972). Le nom de commune est pris dans la liste du service
(`commune_service` dans la réponse) ; en cas d'homonymie, l'outil liste les valeurs possibles.
Le filtre par type dépend du formulaire du service (absent pour la Nièvre : rechercher sans type).

Pour ces services Mnesys, comme pour l'AD59 ([plus bas](#autres-fonds-numérisés-des-ad59)), deux autres fonds
se cherchent de la même façon :

> Cherche le registre matricule de la classe 1880 à Tulle (Corrèze).
> Cherche les tables des successions du bureau de Nevers entre 1876 et 1882.

- **Registres matricules** (`type_acte="RM"`) : l'année est la **classe** (naissance + 20) ; la commune est le
  bureau de recrutement, facultatif. Corrèze, Doubs, Eure, Jura, Meuse, Nièvre, Rhône, Territoire de Belfort, Martinique ;
  Nord (AD59) avec ses deux formulaires dédiés.
- **Tables des successions** (`type_acte="SUCC"`, série 3 Q) : la commune est le **bureau de l'enregistrement**
  dont dépendait le défunt, l'année ou l'intervalle la période du décès. Doubs, Eure, Indre-et-Loire, Nièvre, Rhône, Territoire de Belfort, Essonne ;
  Nord (AD59) avec son formulaire dédié.

Pour une personne de l'arbre, ajouter son identifiant local dans `personne` :
la garde des vivants est appliquée avant toute requête ; cet identifiant n'est pas transmis aux archives.

Types pris en charge : `N` (naissances), `M` (mariages), `D` (décès). `NMD` ou vide recherche sans filtre
de type. `TD` renvoie les tables décennales de la commune dont la période recoupe l'année demandée.
Pour un intervalle, ajouter `annee_fin` (ex. `annee=1790, annee_fin=1802`, ou une décennie) : les
registres dont la période recoupe l'intervalle sont renvoyés. Les autres services conservent la
recherche manuelle.
Chaque appel lit une seule page ; `page_suivante` indique comment continuer explicitement.

Choisir un registre, puis utiliser `archives_naviguer(ark_registre)` pour chercher la vue et
`archive_image` / `piece_archiver` pour la consulter et la conserver. Un registre trouvé ne prouve pas
que l'acte y figure. Une recherche vide est journalisée pour ce périmètre uniquement ; une modification
du format de la page est signalée comme erreur. En cas de protection, conserver la tâche manuelle et
poursuivre les autres pistes : un défi anti-robot détecté renvoie une consigne (ouvrir la vue dans le
navigateur, fournir une capture ou l'image téléchargée) et met l'hôte en pause (coupe-circuit,
`GENEALOGISTE_COUPE_CIRCUIT`) ; s'il persiste après la pause, le service est exclu quelques jours
(`GENEALOGISTE_EXCLUSION_ANTIROBOT`). `cache_purger("coupe_circuit")` autorise un nouvel essai explicite. Le [contrat et le relevé technique](../docs/recherche-registres-ad59.md)
précisent les limites observées.

### Autres fonds numérisés des AD59

Depuis les relevés du **27 novembre 2026**, `archives_registres(service="AD59", …)` interroge aussi les
formulaires dédiés de six autres fonds du service. La réponse reste une liste de volumes (titre, cote, ARK,
nombre de vues), une page par appel : le plugin localise ces documents, il ne les lit pas et n'y cherche aucun nom.

- **Recensements de population** (`type_acte="REC"`) : la commune et le millésime. « Cherche le recensement de
  Somain pour 1906 aux archives du Nord. » Une liste nominative est classée par rue ou hameau, pas par nom :
  le foyer se repère ensuite vue par vue. Détail : [recensements](../docs/recensements.md).
- **Registres matricules** (`type_acte="RM"`) : deux formulaires, les tables alphabétiques et les fiches
  (volumes d'états signalétiques et des services). « Cherche le registre matricule de la classe 1890 au bureau
  d'Avesnes (Nord). » La commune est le **bureau de recrutement** (Avesnes, Cambrai, Dunkerque, Lille,
  Valenciennes, Valenciennes-Douai), facultatif ; l'année est la **classe** (naissance + 20). Une classe précise
  interroge les deux formulaires et rend les deux catégories, distinguées ; un intervalle n'interroge que les
  tables. Le formulaire annonce les fiches en ligne pour les classes 1867 à 1923.
- **Tables des successions et absences** (`type_acte="SUCC"`, série 3 Q) : « Cherche les tables des successions
  du bureau de Steenvoorde entre 1791 et 1803 (Nord). » Le **bureau de l'enregistrement** est obligatoire et pris
  dans la liste du service : un bureau inconnu ou ambigu renvoie la liste des valeurs. Période en ligne : au plus
  1791-1968 d'après le service.
- **Fiches décès** (`type_acte="FD"`, AD59 seulement) : la suite des tables, pour les décès de 1969 à 1975.
  « Cherche les fiches décès du bureau de Lille (Centre) pour 1969 (Nord). » Bureau obligatoire, selon un autre
  découpage que celui des tables. **Ne pas tenir ces fiches pour librement communicables** : le délai de 50 ans
  est affirmé par le service et n'a pas été vérifié par le plugin ; la réponse porte
  `avertissement_communicabilite` et écarte tout résultat de moins de 50 ans.
- **Hypothèques** (`type_acte="HYP"`, sous-série 4 Q, de l'an VII à 1955 d'après le service) : « Montre les
  indicateurs des hypothèques du bureau de Cambrai (Nord). » Le **bureau des hypothèques** est obligatoire
  (Avesnes, Cambrai, Douai, Dunkerque, Hazebrouck, Lille, Valenciennes). `HYP` donne la vue d'ensemble des trois
  catégories ; `HYPI` (indicateur), `HYPT` (tables alphabétiques) et `HYPR` (répertoires) n'en interrogent
  qu'une, pour feuilleter. Méthode décrite par le service : indicateur → table alphabétique (numéro de case du
  propriétaire) → répertoire des formalités (volume et acte), puis registres de formalités en salle de lecture.
  Ces formulaires n'ont pas de date. **Le nom cherché n'est jamais envoyé au service** : comparer soi-même son
  initiale à la plage de chaque volume (`plage_alphabetique`), qui reste indicative.
- **Plans du cadastre** (`type_acte="CAD"`) : cadastre dit du Consulat (cotes `P 30`) et cadastre napoléonien
  (cotes `P 31`). « Cherche les plans du cadastre d'Estaires entre 1800 et 1900 (Nord). » La commune est
  obligatoire, parfois sous son nom d'alors (`FIVES`) ; chaque résultat est un lot de plans. Aucun plan
  n'est écarté sur sa date : tous les lots de la commune sont rendus, triés par date et marqués antérieur,
  contemporain ou postérieur à la période demandée (`position_periode`), un plan valant pour les décennies qui
  suivent sa levée. Matrices cadastrales et états de
  sections ne sont pas couverts.

`FD`, `HYP` et `CAD` sont propres à l'AD59 : pour un autre service, l'outil refuse la demande. `REC` vaut
aussi pour treize services Mnesys (AD14, AD19, AD25, AD27, AD37, AD39, AD51, AD55, AD58, AD69, AD80, AD90,
AD91) : « Cherche le recensement de 1906 de Clamecy (Nièvre). » L'état de la collection (en ligne ou salle de
lecture) n'existe que pour l'AD59 ([détail](../docs/recensements.md#autres-services-mnesys-392)).
Le plugin ne rattache aucune commune à un bureau (recrutement, enregistrement, hypothèques) : le relever sur
le site du service ou dans la liste renvoyée par l'erreur.

Limites : ces fonds ont été relevés à la main le 27 novembre 2026 et sont testés sans réseau ; la recette
réelle n'en couvre aucun. Aucune image n'a été téléchargée : `archive_image` et `archives_planche` ne sont **pas
éprouvés** sur ces fonds, et `archives_naviguer` ne l'a été que sur un recensement et un lot de plans
(métadonnées seulement). Détail par fonds : [contrat et relevé technique](../docs/recherche-registres-ad59.md).

### Registre absent en ligne : classeur 3 E et état des recensements

Une recherche vide ne dit pas que le registre n'existe pas. Deux copies datées de documents publiés par le
service (`releve_le`, relevés du 27 novembre 2026) complètent alors la réponse, sans requête supplémentaire :

- **Classeur 3 E** (état civil, hors tables décennales) : quand la recherche est vide ou qu'un volume de la
  période n'est pas en ligne, le champ `classeur_3e` donne sa cote, ses types d'actes, ses bornes et un message,
  par exemple « pas en ligne avant AAAA ; consultation en salle de lecture ». Cas de référence : naissances de
  Somain en 1926, cote `3 E 6298`, pas en ligne avant 2031. **Absent en ligne ne veut pas dire inexistant** :
  un volume hors du classeur est « inconnu du classeur », jamais « inexistant ».
- **Couverture des recensements** (`type_acte="REC"`) : le champ `couverture_recensements` donne la cote et le
  mode d'accès (en ligne ou salle de lecture) d'après l'état de la collection du service. Un millésime absent
  de ce relevé est inconnu du référentiel, jamais inexistant ; le message liste les millésimes connus de la
  commune. La recherche par nom passe par Socface (base de noms de FranceArchives), **en consultation
  manuelle** : la réponse donne le lien et la consigne, le plugin n'y envoie aucun nom. Un index nominatif sert
  à trouver la vue, pas à prouver.

« Salle de lecture » ne veut pas dire « librement consultable » : vérifier le délai avec `communicabilite`
(75 ans pour une liste nominative de recensement). Ces documents sont lus tels quels, sans contrôle de leur
complétude, et vieillissent : un volume annoncé pour plus tard peut avoir été mis en ligne depuis le relevé.
Leur renouvellement est décrit dans [Maintenir le wiki](Maintenance.md#veille-et-renouvellement-des-référentiels-ad59).

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
- **Implémenté** : chemin présent dans la version du plugin indiquée en pied de page.
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
| France — [Gallica, BnF](https://gallica.bnf.fr/) | Images de documents numérisés accessibles par IIIF | Résolution de l’ARK Gallica vers Image API ; manifeste, `info.json` ou URL IIIF explicites acceptés | Choix `fN` ou `page`, aperçu, recadrage, original et archivage si accessibles ; protections réseau et conditions propres au document | [API officielle BnF](https://api.bnf.fr/fr/api-iiif-de-recuperation-des-images-de-gallica), implémenté et simulé ; pas de recette réseau Gallica parmi celles du 08/11/2026 |
| Suisse — [e-manuscripta](https://www.e-manuscripta.ch/) | Documents numérisés ; premier canvas du manifeste `3192957` essayé | IIIF générique, sans adaptateur spécifique ; [API officielle](https://www.e-manuscripta.ch/wiki/apiinfo?lang=de) | Choix de vue, aperçu, recadrage IIIF, original et archivage. PDF proposé par l’institution distinct du parcours image éprouvé | Implémenté, simulé pour le mécanisme générique ; une ressource éprouvée le 08/11/2026 : [résultats](../docs/telechargement-international.md#résultats-natifs) |
| États-Unis — [Library of Congress](https://www.loc.gov/) | Images numérisées ; une page de journal essayée | IIIF générique via `info.json` ; [Image Services officiel](https://www.loc.gov/apis/micro-services/image-services/) | Aperçu, recadrage, original et archivage ; pas de recherche automatique dans l’ensemble des collections par cet outil. Repli `full/full` exercé lorsque `full/max` est refusé | Implémenté, simulé pour le mécanisme générique ; une image éprouvée le 08/11/2026 : [résultats](../docs/telechargement-international.md#résultats-natifs) |
| Tous pays — autre fournisseur IIIF | Document dont le manifeste ou service d’image est accessible | Presentation v2/v3, Image API, ou image déclarée dans un canvas sans service ; une page HTML peut déclarer un unique manifeste | Choix de vue et parcours image selon le contenu réellement fourni. Plusieurs manifestes : demander lequel ; pas d’exécution JavaScript ni de résolution universelle des visionneuses | Implémenté et simulé ; essais réels limités aux services nommés ci-dessus |
| Tous pays — fichier direct ou local | URL d’image reconnue ou fichier local (image/PDF) ; pas de ZIP, audio ou vidéo dans ce parcours | URL directe d’image reconnue ou chemin local ; PDF à télécharger manuellement, aucun adaptateur de portail | Original conservé et note compagnon. Aperçu et recadrage pour les images décodables et les pages de PDF (`page=N`) ; PDF dactylographié ou imprimé : `pdf_markdown` (texte natif ou OCR) | Implémenté et simulé ; pas de qualification générale des liens de chaque fournisseur |

Pour les autres services français (AD, archives communales, Archives nationales, ANOM, SHD, etc.),
consulter leur fiche via `archives_service`. Les champs `telechargement` exposent le mode et l’adaptateur
connus ; IIIF peut rester inconnu. Ne pas extrapoler l’adaptateur AD59 aux services utilisant une interface semblable.

## Services documentés avec accès manuel ou non qualifié

Ces portails constituent des pistes pour poursuivre la qualification. Aucun adaptateur spécifique de
téléchargement n’est livré pour eux à ce jour. Les sources institutionnelles et leurs contraintes détaillées
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
