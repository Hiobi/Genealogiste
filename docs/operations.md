# Opérations d'édition (`arbre_proposer`)

Chaque opération est un objet `{"op": "...", ...}`. Les créations acceptent `"ref": "x"` ; les opérations
suivantes de la même proposition désignent l'objet par `"$x"`. Dates : GEDCOM 7 ou texte français
(converti). Lieu : chaîne « Commune, Département, France » ou `{nom, code_insee, latitude, longitude, paroisse}`.

Citation : `{source, page, texte, qualite (0-3), type_source, information, preuve, consultation, note}` —
`consultation` : `original` | `image` | `transcription` | `index` | `non_vu`.

Association (témoin, parrain…) : `{personne (id) | nom (tel qu'écrit), role, detail, citations}` — `role` :
`temoin`, `parrain`, `marraine`, `declarant`, `officier`, `maire`, `pretre`, `cure`, `vicaire`, `notaire`,
`voisin`, `ami`, `mentionne`, `present` ou un code GEDCOM 7 (`WITN`, `GODP`, `CLERGY`, `OFFICIATOR`…).

**Règle de métier** (`GENEALOGISTE_EXIGER_SOURCE=1`, défaut) : un événement ou une filiation sans citation
est refusé, sauf `"non_source": true` + `"motif": "…"` (la mention « Non sourcé : motif » est ajoutée).

| op | Paramètres |
|---|---|
| `ajouter_source` | `titre`*, `auteur`, `publication`, `depot`, `cote`, `url`, `ark`, `type_source`, `original`, `note`, `ref` |
| `ajouter_depot` | `nom`, `sigle`, `adresse`, `url`, `ref` |
| `modifier_source` | `id`, `champs` |
| `ajouter_personne` | `noms`* `[{prenoms, nom, surnom, type, citations}]`, `sexe`, `evenements`, `citations`, `notes`, `vivant`, `ref` |
| `modifier_personne` | `id`, `sexe`, `vivant`, `noms` (remplace), `notes_ajout` |
| `supprimer_personne` | `id` |
| `ajouter_nom` | `id`, `nom` |
| `ajouter_evenement` | `cible` (I… ou F…), `evenement` `{type, date, lieu, valeur, type_detail, age, cause, note, citations, associations, non_source, motif}`, `ref` |
| `ajouter_association` | `evenement` (uid) ou `personne` (id), `association` |
| `supprimer_association` | `evenement` ou `personne`, `index` |
| `modifier_evenement` | `uid`, `champs` `{date, lieu, valeur, type_detail, age, cause, note}`, `citations_ajout` |
| `supprimer_evenement` | `uid` |
| `ajouter_famille` | `epoux`, `epouse`, `enfants` `[id | {enfant, filiation, citations}]`, `evenements`, `citations`, `ref` |
| `lier_enfant` / `delier_enfant` | `famille`, `enfant`, (`filiation`, `citations`, `non_source`, `motif`) |
| `lier_conjoint` | `famille`, `personne`, `role` (`epoux`/`epouse`) |
| `ajouter_citation` | `cible` `{type: evenement(uid) | nom(id, index) | filiation(famille, enfant) | personne | famille | media (id)}`, `citation` |
| | Citation : `source`, `page`, `texte`, `qualite`, `type_source`, `information`, `preuve`, `consultation`, `ark`, `medias` (ids ou `$ref` d'`ajouter_media` : images de l'acte), `lier_media` (défaut `true` : voir « Images d'une citation »), `note` |
| `ajouter_media` | `fichier`* (voir « Fichier d'un média »), `format`, `titre`, `citations`, `lier_a` `[ids]` (personnes `I…`, familles `F…`, sources `S…`, événements (uid), ou `$ref` : voir « Médias »), `ref` |
| `modifier_media` | `id`, `champs` `{fichier, titre, format}` (`fichier` contrôlé comme pour `ajouter_media` ; `date` refusée : un `OBJE` GEDCOM 7 ne porte pas de date, dater l'acte dans sa citation ou son événement), `citations_ajout`, `lier_a` `[ids]` (liens ajoutés, mêmes cibles qu'`ajouter_media`) |
| `fusionner_personnes` | `conserver`, `absorber`, `justification`*, `forcer` |
| `scinder_personne` | `id`, `evenements` `[uid]`, `familles_parents`, `familles_conjoint`, `noms`, `sexe`, `justification`*, `ref` |
| `definir_statut` | `cible` `{type: evenement | nom | filiation …}`, `statut` (`refute` \| `contradictoire` \| `""`), `justification`* |
| `marquer_vivant` | `id`, `vivant` (`Y` \| `N` \| `""`) |

### Fichier d'un média (`ajouter_media`)

`fichier` est résolu dès la proposition (#192) :

- une URL distante (`https://…`, tout `fichier` contenant `://`) est gardée telle quelle, sans contrôle ;
- un chemin local est résolu par la **règle commune** ci-dessous ; `documents/État civil/NOM/x.webp` (relatif
  au vault), `État civil/NOM/x.webp` (relatif aux médias) ou le chemin absolu désignent donc le même fichier ;
- la référence enregistrée est normalisée comme celle de `media_enregistrer` (`reference_media`, voir
  « Référence enregistrée ») ;
- la proposition est **refusée** si le fichier local est introuvable (l'enregistrer d'abord par
  `media_enregistrer` ou `piece_archiver`), si le chemin sort de ces racines (absolu ailleurs, `..`, lien
  symbolique sortant) ou s'il est ambigu.

#### Résolution d'un chemin de média (#193)

Une seule règle (`chemins.localiser`, `Config.media_local`), appliquée à la proposition (`ajouter_media`,
`modifier_media`, `gramps_relocaliser_medias`), aux notes (section « Pièces »), à l'envoi vers Gramps Web
(`arbre_appliquer`, `gramps_envoyer_medias`, bascule) et au suivi des pièces (`pieces_proposer`) :

1. Racines autorisées, dans cet ordre : répertoire des données, répertoire des médias
   (`GENEALOGISTE_MEDIA_DIR`, ex. `<vault>/documents`), arborescence des pièces (son parent s'il s'appelle
   `documents`, ex. `<vault>`).
2. Chemin absolu : accepté seulement s'il se trouve sous l'une d'elles (liens symboliques résolus).
3. Chemin relatif : essayé contre chaque racine qui l'admet (sans sortie par `..` ni lien sortant) :
   - présent sous une seule racine : ce fichier ;
   - présent sous plusieurs racines avec un contenu **identique** : la première dans l'ordre ci-dessus ;
   - présent sous plusieurs racines avec des contenus **différents** : **refusé** (« Chemin ambigu », avec la
     liste des fichiers) ; aucun choix silencieux. Lever l'ambiguïté en donnant le chemin absolu ou en
     supprimant le doublon ;
   - absent partout : introuvable (proposition refusée ; listé dans `fichiers_absents` à l'envoi).

À l'envoi vers Gramps Web, une référence ambiguë n'est jamais lue ni envoyée : elle figure dans les fichiers
absents avec le motif. Dans les notes, la pièce est remplacée par une ligne « chemin ambigu » sans image (et
tous les candidats d'un média privé restent masqués).

#### Référence enregistrée (`media_ref`)

- fichier sous le répertoire des données : relative à celui-ci (`medias/…`), comme avant ;
- sinon, avec `GENEALOGISTE_MEDIA_DIR`, fichier sous l'arborescence des pièces : **relative à celle-ci**
  (`documents/État civil/NOM/x.webp`, `photographies/NOM/p.jpg` ; relative au répertoire des médias lui-même
  quand il ne s'appelle pas `documents`). La référence ne dépend plus de la machine ni du point de montage ;
  elle n'est retenue que si elle se résout, par la règle ci-dessus, vers ce même fichier (sinon : absolue) ;
- autres cas : chemin absolu.

### Modifier ou relocaliser un média (`modifier_media`, #193)

- `modifier_media` remplace le fichier (version HD d'un acte, pièce déplacée), corrige le titre ou le format et
  ajoute des citations ; le résumé indique `ancien → nouveau` pour chaque champ et le diff montre le `FILE`.
  Un nouveau `fichier` est résolu et contrôlé exactement comme pour `ajouter_media` ; si son extension change
  sans `format` explicite, le format est déduit de la nouvelle extension.
- En mode gramps, un média dont le fichier a déjà été reçu par Gramps Web garde le chemin et la somme attribués
  par le serveur ; seul l'attribut `Genealogiste-Fichier` (et le titre, le format) change. Si le nouveau fichier a un
  MD5 différent, il apparaît dans `fichiers_a_envoyer` et est envoyé après la transaction ; s'il est identique
  (simple déplacement), rien n'est renvoyé.
- `gramps_relocaliser_medias(ancien_prefixe, nouveau_prefixe)` (changement de machine ou de point de montage)
  remplace le préfixe des fichiers de médias situés sous le dossier `ancien_prefixe` (comparaison par dossier :
  `/a/b` couvre `/a/b/x.jpg`, pas `/a/b2/x.jpg` ; `/` final facultatif). Chaque nouveau chemin doit exister sous les racines autorisées et, si Gramps Web connaît
  la somme du fichier, avoir le même MD5 ; les autres sont listés à part (`introuvables`, `md5_differents`,
  `refuses`) et laissés intacts. Le résultat est une proposition ordinaire (`modifier_media` en lot : diff,
  jeton) : une seule écriture par `arbre_appliquer` après accord, journalisée et annulable
  (`arbre_annuler_modification`). L'outil fonctionne aussi en mode fichier (existence seule, sans MD5).
- Chemins relatifs à `GENEALOGISTE_MEDIA_DIR` : les nouvelles références sont relatives à l'arborescence des
  pièces (voir « Référence enregistrée ») et survivent à un changement de machine. Les références absolues
  existantes restent valides ; pour les convertir, appeler `gramps_relocaliser_medias` avec le **même**
  préfixe des deux côtés (ex. `<vault>` → `<vault>`) : chaque chemin est vérifié puis renormalisé, et la
  proposition liste `absolu → relatif`.

### Intégrité (contrôlée à chaque proposition)

Une proposition est **refusée** si elle introduit :

- un **cycle de parenté** (une personne serait son propre parent ou ascendant), quelle que soit l'opération
  (`lier_enfant`, `ajouter_famille`, `lier_conjoint`, fusion) ;
- une **référence pendante** (personne, famille, source, dépôt, média ou note partagée absents) ;
- un **UID d'événement dupliqué**.

Les défauts déjà présents ne bloquent pas : `arbre_coherence` les signale (`cycle_parente`,
`reference_cassee`, `uid_duplique`). Les parcours d'ascendance s'arrêtent sur un cycle et sont plafonnés
(20 000 entrées Sosa).

**Import en ajout** (`arbre_importer_gedcom(…, "ajouter")`) : personnes, familles, sources, dépôts, médias et
notes partagées renumérotés, y compris les références imbriquées (citations des médias, médias des citations,
renvois `@N…@`) ; UID en collision réattribués.

**Fusion** (`fusionner_personnes`), champ par champ :

- protection la plus restrictive retenue : `vivant` (forcé vivant > déduit > forcé décédé) et `prive` ; le
  conflit est indiqué dans le résumé, à confirmer par `marquer_vivant` ;
- extensions GEDCOM (`extra`) des deux fiches conservées ;
- événements identiques : citations, associations, notes, cause, âge, valeur et statut manuel fusionnés ; une
  valeur divergente est reportée en note, le statut le plus grave (`refute`, puis `contradictoire`) est retenu.

**Médias** (`ajouter_media`, `modifier_media`, `lier_a`) : un média se lie à des personnes (`I…`), des
familles (`F…`), des sources (`S…`) et des événements (uid), mélangeables (`["I1", "I2", "F3"]` pour un acte de
mariage, `["S2", "<uid de la naissance>"]` pour la page du registre qui atteste une naissance), y compris des
objets créés plus tôt dans la proposition (`$ref` d'`ajouter_source` / `ajouter_evenement`). Le lien s'écrit en
GEDCOM 7 `1 OBJE @O…@` sous l'`INDI`, le `FAM` ou l'enregistrement `SOUR`, `2 OBJE @O…@` sous l'événement ; en
Gramps Web, dans la `media_list` de la personne, de la famille, de la source ou de l'événement (`objref` à
l'export Gramps XML). À la lecture, un `OBJE` portant des sous-structures (`CROP`, `TITL`) sous un événement ou une source est
conservé tel quel (non interprété) pour un aller-retour sans perte. Il apparaît dans le diff et le résumé (« liée à S2, I1 naissance ») ; un lien déjà
présent n'est pas dupliqué. La pièce figure dans la section « Pièces » des notes des personnes concernées
(conjoints pour une famille, titulaire du fait pour un événement). `modifier_media` + `lier_a` rattache un média
existant. Un identifiant absent est refusé avec son type (« personne inconnue », « famille inconnue », « source
inconnue », « événement inconnu ») ; `medias` n'est pas accepté directement dans `ajouter_source`,
`modifier_source` ou un événement : passer par `lier_a`. Pour l'image qui fonde une citation précise (page,
acte), `citation.medias` reste le lien le plus fin. Publication : les images d'un événement ou d'une source
privés, ou d'une personne masquée, sont retirées des exports.

**Images d'une citation** (#246) : une citation qui porte `medias` lie aussi, d'elle-même, chaque image à ce
qu'elle prouve, pour qu'elle apparaisse dans l'onglet Médias des fiches (Gramps Web) et dans les `OBJE` GEDCOM :
événement individuel → l'événement, la personne et la source ; événement familial → l'événement, la famille, les
deux conjoints et la source ; citation de la famille → la famille, les conjoints et la source ; nom ou citation
générale d'une personne → la personne et la source ; filiation → l'enfant et la source ; association (témoin,
parrain…) → la source seulement. Seul le titulaire de la citation compte : une vue collective (table décennale,
recensement, table des successions) n'est jamais liée à tout le contenu de la page. Ces liens figurent dans le
diff et le résumé (« Média O3 (image de citation) liée à I1 décès, I1, S4 ») ; un lien déjà présent n'est pas
dupliqué. `lier_media: false` sur la citation garde le seul lien fin. Rattrapage de l'existant :
`arbre_lacunes` (tout l'arbre ou une personne) renvoie `medias_a_lier`, chaque image liée seulement à des
citations avec l'opération `modifier_media` + `lier_a` prête à soumettre par `arbre_proposer` ; rien n'est écrit
sans `arbre_appliquer`.

### ARK (liens pérennes des archives)

- `ajouter_source` avec un `ark` (ou une `url` contenant `ark:/NAAN/…`) : ARK de la ressource enregistré sans
  qualificatif, URL canonique déduite, dépôt déduit du NAAN (créé s'il manque : BnF, AD59, AD62…). Si une
  source porte déjà le même ARK, elle est **réutilisée** (avertissement) au lieu d'être doublée.
- Citation avec un `ark` (ou une `page` contenant un ARK) : ARK complet de l'image enregistré ; `source`
  facultative (retrouvée par l'ARK de la ressource) ; `page` déduite de la vue Gallica (`f12` → « vue 12 »).
- `ark_resoudre(ark)` : service, URL canonique, repli `n2t.net`, disponibilité (HEAD ; repli GET sans lire le
  corps si HEAD renvoie 405 ou 501), manifeste IIIF, citation
  suggérée. NAAN inconnu : registre public de l'ARK Alliance (cache 30 jours).
- `archives_registres(service, commune, annee, type_acte, page, personne, annee_fin)` localise un registre
  (AD59 et les services Mnesys du référentiel (AD14, AD19, AD25, AD27, AD37, AD39, AD51, AD55, AD58, AD69, AD80, AD90, AD91, AD972)) sans ARK initial : cote, ARK, titre, bornes et nombre de vues seulement lorsqu'ils sont affichés par
  le service. Types `N`, `M`, `D` ; `NMD` ou vide = aucun filtre ; `TD` = tables décennales recoupant la
  période. `annee_fin` (≥ `annee`) demande un intervalle. Une page de résultats par appel,
  puis `page_suivante` pour poursuivre explicitement. Un résultat vide est journalisé sans en déduire
  l'absence de l'acte. Les autres services gardent le parcours manuel (docs/archives.md).
- `archive_image(source, page, region, largeur, gris, details)` accepte un lien IIIF (Image API, `info.json`,
  manifeste v2/v3, tous pays), un ARK Gallica, un lien de visionneuse AD59, une image directe ou un fichier.
  Pour AD59 : ARK de vue complet, ou ARK du registre + `page=N` (vues à partir de 1). Les deux outils
  `archive_image` et `piece_archiver` partagent la même résolution ; IIIF est utilisé dès qu'il est annoncé.
  Un PDF (local ou téléchargé) est rendu page par page (`page=N`, à partir de 1) ; pour un PDF dactylographié
  ou imprimé, `pdf_markdown(chemin)` est bien plus économe (voir `docs/pieces.md`).
- `archives_sonder(source, date_cible, type_acte, lecture, conclusion, enquete)` (#156) : sondage guidé, sans
  réseau : propose la vue à lire, le modèle renvoie la date lue, l'outil resserre les bornes (interpolation
  puis dichotomie ; section du bon type d'abord dans un registre à plusieurs séries). Voir `docs/archives.md`.
- `archives_planche(source, de, a, pas, bandeau, largeur, gris, miniatures)` (#124) : **une** image composite de
  4 à 12 vues d'un registre d'une visionneuse Naoned qualifiée (AD59, services Mnesys), numéro de vue incrusté, composée en local (Pillow), pour repérer un acte sans
  lire une image par vue. `pas` : sondage large (une vue sur N), puis planche fine ; `bandeau` (`pct:x,y,l,h`,
  ex. `pct:0,0,100,35`) : ne garde que le haut de chaque vue (date, numéro d'acte). Limites : 12 vues, 1 600 px
  de côté, `a=0` = six vues. Une requête de métadonnées par plage (≤ 100 vues) et **un téléchargement par vue** :
  les originales vont dans le cache partagé avec `archive_image` et `piece_archiver` (jamais retéléchargées) ;
  arrêt à la première erreur ou protection, aucun contournement. La miniature du service (`location.thumb`,
  mesurée à 100 × 100 px) ne permet pas de lire une date : `miniatures=true` ne sert qu'à la mise en page.
  Visionneuses Naoned qualifiées seulement ; autre source : `archives_naviguer` puis `archive_image`. Sortie : `chemin_absolu`,
  `vues`, `grille`, `dimensions_demandees`, `cout_estime_tokens`, `telechargements`.
- Une page HTTP qui déclare un unique manifeste IIIF est inspectée côté Python. Le modèle ne reçoit ni
  HTML/JavaScript, ni manifeste entier, ni liste d'images voisines. Sans lien exploitable ou adaptateur
  qualifié, l'erreur propose « Copier le lien IIIF » ou un téléchargement manuel : **un ARK ne garantit
  pas une image téléchargeable**, et l'accès peut dépendre d'un compte ou d'une API spécifique.
- Aperçu 800 px en gris, puis recadrage `pct:x,y,l,h` jusqu'à 2000 px ; estimation indicative en tokens.
- **Sortie minimale d'`archive_image`** (#124) : `chemin_absolu`, `vue`, `nb_vues`, `ark_vue`,
  `dimensions_originales`, `dimensions_demandees`, `cout_estime_tokens`, `avertissement` éventuel et `registre`
  (ARK du registre). Les clés vides sont omises. `titre_registre`, `cote`, `commune` et `periode` ne sont
  renvoyés qu'au **premier aperçu d'un registre dans la session**, ou avec `details=true`. La **licence** et la
  réutilisation ne sont jamais renvoyées : `piece_archiver` les conserve (`licence`, `reutilisation`, note
  compagnon). Le filtre ne s'applique qu'à l'affichage : la résolution partagée avec `piece_archiver` est intacte.
  Les régions invalides sont refusées avant accès réseau, et une largeur supérieure à la résolution
  disponible est limitée avec avertissement. Aperçus et originales de lecture restent dans
  `<données>/cache-images/`, hors du vault et de Git. Sans IIIF, l'originale est téléchargée une fois,
  puis réutilisée pour le recadrage et l'archivage. Avec IIIF, les zones sont demandées au serveur tant
  qu'une originale locale complète n'est pas disponible.
- La sortie comporte `mode` (`iiif`, `visionneuse:visualizer_api`, `url_directe`, `fichier`), `vue`,
  `nb_vues`, `ark_vue`, `cote`, `titre_registre`, `licence`, `dimensions_originales` et
  `cout_estime_tokens`. Une métadonnée inconnue reste vide/null ; elle n'est pas inventée.
- Le cache des réponses tient compte de `Cache-Control: no-store`. Les appels explicites à
  `catalog.archives.gov` ne sont pas mis en cache ; **l'API NARA n'a pas d'adaptateur livré** et requiert
  une intégration spécifique avec clé et politique de conservation propre.
- Pour conserver la pleine résolution : `piece_archiver`, avec nom conventionnel, note compagnon et
  citation suggérée, voir [pieces.md](pieces.md#archiver-une-pièce-consultée-en-ligne-ark-iiif).
  Les [essais internationaux](telechargement-international.md) distinguent capacités documentées,
  fonctions effectivement essayées et accès manuels ; l'[étude AD59](visionneuse-ad59.md) décrit le contrat.


Exemple :

```json
[
  {"op": "ajouter_depot", "ref": "ad", "nom": "Archives départementales de la Charente-Maritime", "sigle": "AD17"},
  {"op": "ajouter_source", "ref": "ec", "titre": "État civil de Rochefort, naissances 1820",
   "depot": "$ad", "cote": "2 E 299", "type_source": "originale"},
  {"op": "ajouter_personne", "ref": "p", "sexe": "M",
   "noms": [{"prenoms": "Jean", "nom": "MARTIN"}],
   "evenements": [{"type": "BIRT", "date": "12 mars 1820", "lieu": "Rochefort, Charente-Maritime, France",
                   "citations": [{"source": "$ec", "page": "acte n° 45, vue 12/80", "consultation": "image",
                                  "type_source": "originale", "information": "primaire"}],
                   "associations": [{"nom": "Pierre DURAND", "role": "declarant",
                                     "detail": "Déclarant, 32 ans, tonnelier, père de l'enfant"},
                                    {"nom": "Louis ROY", "role": "temoin", "detail": "Témoin, 40 ans, voisin"}]}]},
  {"op": "lier_enfant", "famille": "F2", "enfant": "$p",
   "citations": [{"source": "$ec", "page": "acte n° 45", "information": "primaire"}]}
]
```

## Validation différée

Les mêmes opérations peuvent être déposées dans une file durable (`propositions_deposer`) au lieu d'un jeton
d'une heure, puis reprises sur l'arbre courant (`propositions_reprendre`, diff frais) et appliquées après
accord : voir [la file de propositions](propositions.md) et `/genealogiste:valide`.
