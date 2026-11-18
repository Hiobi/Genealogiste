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
| | Citation : `source`, `page`, `texte`, `qualite`, `type_source`, `information`, `preuve`, `consultation`, `ark`, `medias` (ids ou `$ref` d'`ajouter_media` : images de l'acte), `note` |
| `ajouter_media` | `fichier`* (voir « Fichier d'un média »), `format`, `titre`, `citations`, `lier_a` `[ids]` (personnes `I…` et familles `F…`, ou `$ref` : un acte de mariage se lie à la famille), `ref` |
| `modifier_media` | `id`, `champs` `{fichier, titre, format}` (`fichier` contrôlé comme pour `ajouter_media` ; `date` refusée : un `OBJE` GEDCOM 7 ne porte pas de date, dater l'acte dans sa citation ou son événement), `citations_ajout` |
| `fusionner_personnes` | `conserver`, `absorber`, `justification`*, `forcer` |
| `scinder_personne` | `id`, `evenements` `[uid]`, `familles_parents`, `familles_conjoint`, `noms`, `sexe`, `justification`*, `ref` |
| `definir_statut` | `cible` `{type: evenement | nom | filiation …}`, `statut` (`refute` \| `contradictoire` \| `""`), `justification`* |
| `marquer_vivant` | `id`, `vivant` (`Y` \| `N` \| `""`) |

### Fichier d'un média (`ajouter_media`)

`fichier` est résolu dès la proposition (#192) :

- une URL distante (`https://…`, tout `fichier` contenant `://`) est gardée telle quelle, sans contrôle ;
- un chemin local est cherché, dans cet ordre, sous le répertoire des données, le répertoire des médias
  (`GENEALOGISTE_MEDIA_DIR`, ex. `<vault>/documents`) puis l'arborescence des pièces (ex. `<vault>`) ;
  `documents/État civil/NOM/x.webp` (relatif au vault), `État civil/NOM/x.webp` (relatif aux médias) ou le
  chemin absolu désignent donc le même fichier ;
- la référence enregistrée est normalisée comme celle de `media_enregistrer` (`reference_media`) : relative
  aux données (`medias/…`) quand le fichier s'y trouve, absolue sinon ;
- la proposition est **refusée** si le fichier local est introuvable (l'enregistrer d'abord par
  `media_enregistrer` ou `piece_archiver`) ou si le chemin sort de ces racines (absolu ailleurs, `..`, lien
  symbolique sortant).

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
- Chemins relatifs à `GENEALOGISTE_MEDIA_DIR` : non retenus pour l'instant. La référence stockée reste relative
  aux données (`medias/…`) ou absolue ; un chemin relatif au répertoire des médias serait ambigu (le même
  chemin relatif est d'abord cherché sous les données) et n'est pas encore relu par tous les consommateurs
  (notes, organisation des pièces). Après un changement de machine, `gramps_relocaliser_medias` corrige les
  chemins absolus.

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

**Médias** (`ajouter_media`, `lier_a`) : un média se lie à des personnes (`I…`) et à des familles (`F…`),
mélangeables (`["I1", "I2", "F3"]` pour un acte de mariage) ; le lien famille s'écrit `1 OBJE @O…@` sous le
`FAM` (GEDCOM 7) ou dans la `media_list` de la famille (Gramps Web), apparaît dans le diff et le résumé, et la
pièce figure dans la section « Pièces » des notes des deux conjoints. Un identifiant absent est refusé avec
son type (« personne inconnue : I… », « famille inconnue : F… ») ; tout autre identifiant (source `S…`, uid
d'événement) est refusé : pour rattacher l'image à une source ou à un événement, la passer dans
`citation.medias` de la citation correspondante.

### ARK (liens pérennes des archives)

- `ajouter_source` avec un `ark` (ou une `url` contenant `ark:/NAAN/…`) : ARK de la ressource enregistré sans
  qualificatif, URL canonique déduite, dépôt déduit du NAAN (créé s'il manque : BnF, AD59, AD62…). Si une
  source porte déjà le même ARK, elle est **réutilisée** (avertissement) au lieu d'être doublée.
- Citation avec un `ark` (ou une `page` contenant un ARK) : ARK complet de l'image enregistré ; `source`
  facultative (retrouvée par l'ARK de la ressource) ; `page` déduite de la vue Gallica (`f12` → « vue 12 »).
- `ark_resoudre(ark)` : service, URL canonique, repli `n2t.net`, disponibilité (HEAD ; repli GET sans lire le
  corps si HEAD renvoie 405 ou 501), manifeste IIIF, citation
  suggérée. NAAN inconnu : registre public de l'ARK Alliance (cache 30 jours).
- `archives_registres(service, commune, annee, type_acte, page, personne, annee_fin)` localise un registre AD59
  sans ARK initial : cote, ARK, titre, bornes et nombre de vues seulement lorsqu'ils sont affichés par
  le service. Types `N`, `M`, `D` ; `NMD` ou vide = aucun filtre ; `TD` = tables décennales recoupant la
  période. `annee_fin` (≥ `annee`) demande un intervalle. Une page de résultats par appel,
  puis `page_suivante` pour poursuivre explicitement. Un résultat vide est journalisé sans en déduire
  l'absence de l'acte. Les autres services gardent le parcours manuel.
- `archive_image(source, page, region, largeur, gris, details)` accepte un lien IIIF (Image API, `info.json`,
  manifeste v2/v3, tous pays), un ARK Gallica, un lien de visionneuse AD59, une image directe ou un fichier.
  Pour AD59 : ARK de vue complet, ou ARK du registre + `page=N` (vues à partir de 1). Les deux outils
  `archive_image` et `piece_archiver` partagent la même résolution ; IIIF est utilisé dès qu'il est annoncé.
  Un PDF (local ou téléchargé) est rendu page par page (`page=N`, à partir de 1) ; pour un PDF dactylographié
  ou imprimé, `pdf_markdown(chemin)` est bien plus économe (voir `docs/pieces.md`).
- `archives_planche(source, de, a, pas, bandeau, largeur, gris, miniatures)` (#124) : **une** image composite de
  4 à 12 vues d'un registre AD59, numéro de vue incrusté, composée en local (Pillow), pour repérer un acte sans
  lire une image par vue. `pas` : sondage large (une vue sur N), puis planche fine ; `bandeau` (`pct:x,y,l,h`,
  ex. `pct:0,0,100,35`) : ne garde que le haut de chaque vue (date, numéro d'acte). Limites : 12 vues, 1 600 px
  de côté, `a=0` = six vues. Une requête de métadonnées par plage (≤ 100 vues) et **un téléchargement par vue** :
  les originales vont dans le cache partagé avec `archive_image` et `piece_archiver` (jamais retéléchargées) ;
  arrêt à la première erreur ou protection, aucun contournement. La miniature du service (`location.thumb`,
  mesurée à 100 × 100 px) ne permet pas de lire une date : `miniatures=true` ne sert qu'à la mise en page.
  Registres AD59 uniquement ; autre source : `archives_naviguer` puis `archive_image`. Sortie : `chemin_absolu`,
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
