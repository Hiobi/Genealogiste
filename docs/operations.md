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
| `ajouter_media` | `fichier`*, `format`, `titre`, `citations`, `lier_a` `[ids]`, `ref` |
| `fusionner_personnes` | `conserver`, `absorber`, `justification`*, `forcer` |
| `scinder_personne` | `id`, `evenements` `[uid]`, `familles_parents`, `familles_conjoint`, `noms`, `sexe`, `justification`*, `ref` |
| `definir_statut` | `cible` `{type: evenement | nom | filiation …}`, `statut` (`refute` \| `contradictoire` \| `""`), `justification`* |
| `marquer_vivant` | `id`, `vivant` (`Y` \| `N` \| `""`) |

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

### ARK (liens pérennes des archives)

- `ajouter_source` avec un `ark` (ou une `url` contenant `ark:/NAAN/…`) : ARK de la ressource enregistré sans
  qualificatif, URL canonique déduite, dépôt déduit du NAAN (créé s'il manque : BnF, AD59, AD62…). Si une
  source porte déjà le même ARK, elle est **réutilisée** (avertissement) au lieu d'être doublée.
- Citation avec un `ark` (ou une `page` contenant un ARK) : ARK complet de l'image enregistré ; `source`
  facultative (retrouvée par l'ARK de la ressource) ; `page` déduite de la vue Gallica (`f12` → « vue 12 »).
- `ark_resoudre(ark)` : service, URL canonique, repli `n2t.net`, disponibilité (HEAD), manifeste IIIF, citation
  suggérée. NAAN inconnu : registre public de l'ARK Alliance (cache 30 jours).
- `archive_image(source, page, region, largeur, gris)` : image d'acte par IIIF (ARK Gallica, manifeste v2/v3,
  `info.json`, URL d'image). Pour les AD, coller le lien obtenu par « Copier le lien IIIF » dans la visionneuse.
  Aperçu 800 px en gris, puis recadrage `pct:x,y,l,h` jusqu'à 2000 px ; coût estimé en tokens ; image gardée
  dans `medias/iiif/`, jamais retéléchargée ; une image par appel. **Sans IIIF** (AD59 par exemple : la
  visionneuse propose seulement « Télécharger ») : passer le chemin du fichier téléchargé ou l'URL directe de
  l'image ; recadrage et réduction faits en local (Pillow), original gardé une fois dans `medias/originaux/`.

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
