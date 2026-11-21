# Opérations d'édition (`arbre_proposer`)

Chaque opération est un objet `{"op": "...", ...}`. Les créations acceptent `"ref": "x"` ; les opérations
suivantes de la même proposition désignent l'objet par `"$x"`. Dates : GEDCOM 7 ou texte français
(converti). Lieu : chaîne « Commune, Département, France » ou `{nom, code_insee, latitude, longitude, paroisse}`.

Texte des notes : brut par défaut ; `"format_texte": "markdown"` sur l'opération pour gras, italique et liens
([texte enrichi](#texte-enrichi-des-notes-279)).

Citation : `{source, page, texte, qualite (0-3), type_source, information, preuve, consultation, note, tags}` —
`consultation` : `original` | `image` | `transcription` | `index` | `non_vu`.

**Étiquettes** (`tags`, #262) : `tags` (liste de noms, ajout) sur toutes les opérations d'ajout (au niveau de
l'opération, ou dans l'objet créé pour un événement et une citation) et de modification ; `tags_retrait` (liste
de noms) sur les modifications. `etiqueter` étiquette tout objet existant. Voir « Étiquettes » plus bas.

Association (témoin, parrain…) : `{personne (id) | nom (tel qu'écrit), role, detail, citations}` — `role` :
`temoin`, `parrain`, `marraine`, `declarant`, `officier`, `maire`, `pretre`, `cure`, `vicaire`, `notaire`,
`voisin`, `ami`, `mentionne`, `present` ou un code GEDCOM 7 (`WITN`, `GODP`, `CLERGY`, `OFFICIATOR`…).

**Règle de métier** (`GENEALOGISTE_EXIGER_SOURCE=1`, défaut) : un événement ou une filiation sans citation
est refusé, sauf `"non_source": true` + `"motif": "…"` (la mention « Non sourcé : motif » est ajoutée).

| op | Paramètres |
|---|---|
| `ajouter_source` | `titre`*, `auteur`, `publication`, `depot`, `cote`, `url`, `ark`, `type_source`, `original`, `note`, `prive`, `tags`, `ref` (avec l'étiquette `Blog` : privée sauf `prive: false`, voir « Billets ») |
| `ajouter_billet` | `titre`*, `texte`* (corps), `auteur`, `medias` `[ids | $ref]` (ordre gardé : le premier sert d'aperçu), `prive` (défaut `true`), `tags` (en plus de `Blog`), `ref` ; `format_texte` possible. Backend gramps seulement ([billets](#billets-du-blog-de-gramps-web-261)) |
| `ajouter_tache` | `titre`*, `description` (première note ; `format_texte` possible), `statut` (`Open` défaut, `In Progress`, `Blocked`, `Done` ; ou `ouverte`, `en_cours`, `bloquee`, `terminee`), `priorite` (`haute` 1, `moyenne` 5 défaut, `basse` 9, ou entier 0-9), `prive` (défaut `true`), `tags` (en plus de `ToDo`), `personnes` `[ids]` (nommées dans la description), `enquete` + `element` (`t1`, `p2` : ligne de référence), `ref`. Backend gramps et `GENEALOGISTE_GRAMPS_TACHES=true` seulement ([tâches](#tâches-de-gramps-web-263)) |
| `modifier_tache` | `id`, `statut`, `priorite`, `titre`, `description` (remplace le texte ; la ligne de référence d'enquête est gardée), `prive`, `tags`, `tags_retrait` |
| `ajouter_depot` | `nom`, `sigle`, `adresse`, `url`, `tags`, `ref` |
| `modifier_source` | `id`, `champs` (sauf `tags`), `tags`, `tags_retrait` |
| `supprimer_source` | `id`, `cascade` (défaut `false` : refus si la source est encore citée ; `true` : chaque citation retirée est listée avec son porteur). Médias de la source détachés, jamais supprimés ; refus si elle est la source originale d'une autre |
| `fusionner_sources` | `de` (doublon), `vers` (source gardée) : citations réécrites, citations devenues identiques (même source et page) sur un même porteur fondues (médias réunis), médias et sources dérivées reportés, doublon supprimé |
| `ajouter_personne` | `noms`* `[{prenoms, nom, surnom, type, citations}]`, `sexe`, `evenements`, `citations`, `notes`, `vivant`, `tags`, `ref` |
| `modifier_personne` | `id`, `sexe`, `vivant`, `noms` (remplace), `notes_ajout`, `tags`, `tags_retrait` |
| `supprimer_personne` | `id` |
| `ajouter_nom` | `id`, `nom` |
| `ajouter_evenement` | `cible` (I… ou F…), `evenement` `{type, date, lieu, valeur, type_detail, age, cause, note, citations, associations, tags, non_source, motif}`, `ref` |
| `ajouter_association` | `evenement` (uid) ou `personne` (id), `association` |
| `supprimer_association` | `evenement` ou `personne`, `index` |
| `modifier_evenement` | `uid`, `champs` `{date, lieu, valeur, type_detail, age, cause, note}`, `citations_ajout`, `tags`, `tags_retrait` |
| `supprimer_evenement` | `uid` |
| `ajouter_famille` | `epoux`, `epouse`, `enfants` `[id | {enfant, filiation, citations}]`, `evenements`, `citations`, `tags`, `ref` |
| `lier_enfant` / `delier_enfant` | `famille`, `enfant`, (`filiation`, `citations`, `non_source`, `motif`) |
| `lier_conjoint` | `famille`, `personne`, `role` (`epoux`/`epouse`) |
| `ajouter_citation` | `cible` `{type: evenement(uid) | nom(id, index) | filiation(famille, enfant) | personne | famille | media (id)}`, `citation` |
| | Citation : `source`, `page`, `texte`, `qualite`, `type_source`, `information`, `preuve`, `consultation`, `ark`, `medias` (ids ou `$ref` d'`ajouter_media` : images de l'acte), `lier_media` (défaut `true` : voir « Images d'une citation »), `note`, `tags` |
| `supprimer_citation` | `cible` (même forme qu'`ajouter_citation`), `source`*, `page` (facultatif), `index` (parmi les citations qui correspondent, si plusieurs) : retire cette citation ; ses médias restent dans l'arbre |
| `ajouter_media` | `fichier`* (voir « Fichier d'un média »), `format`, `titre`, `citations`, `lier_a` `[ids]` (personnes `I…`, familles `F…`, sources `S…`, événements (uid), ou `$ref` : voir « Médias »), `tags`, `ref` |
| `modifier_media` | `id`, `champs` `{fichier, titre, format, prive}` (`prive` : `true` / `false`, ex. image d'un billet ou d'une tâche privés, #264 ; `fichier` contrôlé comme pour `ajouter_media` ; `date` refusée : un `OBJE` GEDCOM 7 ne porte pas de date, dater l'acte dans sa citation ou son événement), `citations_ajout`, `lier_a` `[ids]` (liens ajoutés, mêmes cibles qu'`ajouter_media`), `tags`, `tags_retrait` |
| `fusionner_personnes` | `conserver`, `absorber`, `justification`*, `forcer` |
| `scinder_personne` | `id`, `evenements` `[uid]`, `familles_parents`, `familles_conjoint`, `noms`, `sexe`, `justification`*, `ref` |
| `definir_statut` | `cible` `{type: evenement | nom | filiation …}`, `statut` (`refute` \| `contradictoire` \| `""`), `justification`* |
| `marquer_vivant` | `id`, `vivant` (`Y` \| `N` \| `""`), `prive` (`true` seulement, #264 : personne présumée vivante marquée privée avec ses données propres, dans le diff de la proposition ; sans `vivant`, statut inchangé ; [vivants et privé](gramps-web.md#vivants-et-privé-264)) |
| `etiqueter` | `cible`* `{type: personne | famille | source | depot | media | note (id) | evenement (uid)}` ou `{type: citation, porteur (même forme que la cible d'ajouter_citation), source, page, index}`, `tags`, `tags_retrait` (au moins un) |

### Étiquettes (#262)

Une étiquette (tag) se pose sur une personne, une famille, un événement, une citation, une source, un dépôt, un
média ou une note partagée (`N…`). Ce sont les étiquettes de Gramps Web (`Blog` pour les sources publiées,
`ToDo` pour les tâches…) ; en mode fichier, elles s'écrivent en extension GEDCOM `_ETIQUETTE`
([extensions](gedcom-extensions.md)).

- `tags` ajoute (en fin de liste, sans doublon), `tags_retrait` retire ; un nom à la fois ajouté et retiré est
  refusé, un retrait d'une étiquette absente est signalé dans les avertissements. Pour un objet créé, seul `tags`
  est accepté.
- Noms : sensibles à la casse (comme Gramps Web), non vides, sans espace en début ou en fin, sans retour à la
  ligne ni caractère de contrôle, 100 caractères au plus.
- Étiquettes gérées par Genealogiste (`Genealogiste:auto`, `Sosa:auto`, statut de preuve « Preuve : … ») :
  refusées, quelle que soit la casse ; elles restent recalculées par Genealogiste.
- Diff concis : une ligne par objet, `étiquettes I12 : +Blog −ToDo`, dans le résumé, à la fin du diff
  (`@@ étiquettes I12 : +Blog −ToDo @@`) et, en mode gramps, dans `transaction_gramps.etiquettes`.
- Fusions (`fusionner_personnes`, `fusionner_sources`, événements identiques fusionnés, citations fondues) :
  étiquettes réunies.
- Lecture : `arbre_fiche` les affiche (personne, événements, unions), `arbre_recherche` les renvoie
  (`etiquettes`) et filtre par `etiquette` (nom exact). Exports publics : même politique que les notes
  ([sécurité](securite.md)).
- Étiquettes des lieux et des notes « en ligne » (note de personne, d'événement…) : non modélisées, conservées
  dans Gramps Web, y compris quand le texte de la note change (#279 : même note, même handle).

Exemple : `{"op": "etiqueter", "cible": {"type": "citation", "porteur": {"type": "evenement", "uid": "…"},
"source": "S1", "page": "acte n° 45"}, "tags": ["À vérifier"]}`.

### Billets du blog de Gramps Web (#261)

Un billet de la page Blog de Gramps Web est une **source étiquetée `Blog`** : titre et auteur de la source, corps =
**première note** de la source, aperçu = premier média, galerie = tous ses médias ; la page les trie par date de
dernière modification ([Gramps Web](gramps-web.md#blog-261)). `ajouter_billet` compose ces éléments dans une seule
opération, lisible dans le diff comme une source :

```json
[{"op": "ajouter_media", "ref": "img", "fichier": "medias/blog/portrait.jpg", "titre": "Portrait"},
 {"op": "ajouter_billet", "ref": "b", "titre": "Les Martin de Rochefort", "auteur": "Équipe",
  "texte": "**Jean MARTIN**, tisserand [1]…", "format_texte": "markdown", "medias": ["$img"]}]
```

- **Privé par défaut** : source et corps privés (comptes Membre et plus) ; `"prive": false` seulement sur demande
  explicite, le billet devient alors **lisible par tout compte Invité** (Guest). Le résumé de la proposition
  donne la visibilité de chaque billet créé ou modifié (« Billet S5 « … » : privé » / « PUBLIC »). Même défaut
  pour `ajouter_source` avec `tags: ["Blog"]`.
- **Personnes vivantes** : toute proposition qui crée ou modifie un billet (y compris `etiqueter` qui pose `Blog`
  sur une source, `modifier_source` qui le rend public ou change son texte) contrôle titre, auteur, corps et
  titres des médias : prénom et nom accolés d'une personne présumée vivante ou marquée privée (même règle que
  les exports publics, [sécurité](securite.md#billets-du-blog-de-gramps-web-261)) ou lien interne
  `gramps://Person/gramps_id/I…` vers elle, et depuis #264 l'**identifiant seul** (`I9`, mot entier), comme pour
  les tâches. Billet public : **refus** avec la liste des personnes ; billet privé : avertissement.
- **Images** (#264) : un média garde sa propre confidentialité. Billet ou tâche privés avec un média public :
  avertissement par média (lisible par un Invité : objet, fichier, vignette), avec l'opération
  `{"op": "modifier_media", "id": "O…", "champs": {"prive": true}}` et les autres objets qui le lient ;
  `gramps_proteger_vivants` (tout l'arbre) propose de rendre privé un média dont le seul référent est un billet
  ou une tâche privés.
- **Backend fichier** : `ajouter_billet` est refusé (le blog n'existe que dans Gramps Web) ; une source étiquetée
  `Blog` reste possible (`ajouter_source`, `etiqueter`), sans effet hors de Gramps Web.
- **Preuve** : un billet n'est pas une source généalogique ; une citation qui le désigne pèse 0 et ne compte
  jamais comme source indépendante (`billets_cites` dans le statut de preuve). Poser `Blog` sur une source déjà
  citée le signale (statuts recalculés).
- **Notes de recherche** : aucune fiche pour un billet (`notes_generer` l'ignore, l'index aussi) ; rien n'est
  écrit dans le vault.
- **Lecture** : `arbre_recherche(etiquette="Blog", objet="source")` liste les billets (id, titre, auteur,
  `prive`, médias dans l'ordre).
- **Annulation** : `arbre_annuler_modification`, images envoyées comprises (l'état des médias après envoi est
  journalisé et sert de référence à l'annulation).

### Tâches de Gramps Web (#263)

Une tâche de la vue Tâches de Gramps Web est une **source étiquetée `ToDo`** : titre de la source, attributs
`Status` et `Priority`, description = **première note** (type `To Do`, étiquetée `ToDo`)
([Gramps Web](gramps-web.md#tâches-263)). Disponible seulement avec `GENEALOGISTE_GRAMPS_TACHES=true` (backend
gramps) ; désactivé (défaut), rien ne change : `ajouter_tache` et `modifier_tache` sont refusés, une source
étiquetée `ToDo` reste une source ordinaire. **Jamais automatique** : chaque tâche est créée, modifiée ou close
par une proposition (diff, accord, `arbre_appliquer`), annulable.

```json
[{"op": "ajouter_tache", "ref": "t", "titre": "Mariage MARTIN × DUPONT",
  "description": "Table décennale 1843-1852, puis registre des mariages.", "priorite": "haute",
  "personnes": ["I1", "I2"]},
 {"op": "modifier_tache", "id": "S12", "statut": "Done"}]
```

- **Privée par défaut** (source et description) ; `"prive": false` seulement sur demande explicite : la tâche
  devient lisible par tout compte Invité.
- **Personnes vivantes** : même contrôle que les billets, plus l'identifiant seul (`I9`, mot entier) et
  `personnes` : tâche publique qui nomme une personne présumée vivante ou privée **refusée**, privée
  **avertie**.
- **Liens** : l'interface ne relie pas une tâche à d'autres objets ; `personnes` ajoute à la description
  « Personnes concernées : Jean MARTIN (I1), … » et `enquete` + `element` la ligne
  `Enquête Genealogiste : <enquête> · <élément>`, lue par la correspondance avec l'enquête
  ([enquêtes](enquetes.md#tâches-de-gramps-web-263)).
- **Étiquette posée ou retirée** (`etiqueter`, `tags`) : poser `ToDo` sur une source existante en fait une tâche
  sans statut ni priorité (rien n'est inventé) ; `ajouter_source` avec `tags: ["ToDo"]` crée une tâche comme
  l'interface (privée, `Open`, `5`) ; retirer `ToDo` défait la tâche (attributs laissés intacts).
- **Preuve** : une tâche n'est pas une source ; une citation qui la désigne pèse 0 (`taches_citees` dans le
  statut de preuve). **Notes de recherche** : aucune fiche (`notes_generer` l'ignore).
- **Lecture** : `arbre_recherche(etiquette="ToDo", objet="source")` (statut, priorité, libellé).
- **Depuis les lacunes** : `arbre_lacunes(id, taches=true)` → `taches_a_proposer` (une opération par action,
  priorité Gramps calculée de la priorité de lacune : 0 et 1 → haute `1`, 2 → moyenne `5`, 3 → basse `9`) ;
  **depuis une enquête** : `enquete_reprendre(id, taches=true)`. Rien n'est écrit avant `arbre_proposer`.

### Texte enrichi des notes (#279)

`format_texte` (au niveau de l'opération, toute opération qui écrit une note) : `texte` (défaut, rien n'est
interprété : un `*` reste un `*`) ou `markdown`. En `markdown`, les textes de note de l'opération (`note`,
`texte` de citation, `notes`, `notes_ajout`, y compris dans les citations, événements et `champs` imbriqués) sont
lus comme du Markdown simple : `**gras**`, `*italique*` ou `_italique_`, `[texte](https://…)`, `mailto:`, lien
interne `[texte](gramps://Person/handle/<handle>)` ou `gramps://Person/gramps_id/I12` ; `\*`, `\_`, `\[`, `\]`,
`\\` échappent. Rien d'autre n'est interprété (titres, listes, tableaux, HTML restent du texte), un lien à schéma
refusé (`javascript:`…) reste du texte. Le texte de la note est le texte sans marqueurs ; la mise en forme est
écrite dans Gramps Web (mode gramps). En mode fichier, le GEDCOM ne garde que le texte : la perte de mise en forme
est annoncée dans `avertissements`. Détails, règle des plages et liens internes des notes de preuve :
[Gramps Web](gramps-web.md#texte-enrichi-et-liens-internes-279). (Ne pas confondre avec `format` d'un média.)

Exemple : `{"op": "ajouter_source", "titre": "Billet", "note": "**Acte** vu, voir [la fiche](gramps://Person/gramps_id/I1)", "format_texte": "markdown"}`.

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

Le contrôle `medias_chemins` / `gramps_medias_chemins` du diagnostic et le bilan `import.medias.resolution` appliquent cette
même règle à tous les médias de l'arbre (#280 ; chemin de base d'un Gramps Desktop : `docs/gramps.md`).

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
renvois `@N…@`) ; UID en collision réattribués. Même règle pour un fichier de Gramps Desktop (Gramps XML
`.gramps` ou paquet `.gpkg`, reconnus au contenu) : ses `gramps_id` servent d'identifiants avant
renumérotation ; ce que l'arbre ne représente pas est compté dans `import.non_repris` et les médias d'un
paquet attendent dans `<données>/imports/gramps/` ([Gramps Desktop](gramps.md#import-depuis-gramps-desktop)).

**Fusion** (`fusionner_personnes`), champ par champ :

- protection la plus restrictive retenue : `vivant` (forcé vivant > déduit > forcé décédé) et `prive` ; le
  conflit est indiqué dans le résumé, à confirmer par `marquer_vivant` ;
- extensions GEDCOM (`extra`) des deux fiches conservées ;
- événements identiques : citations, associations, notes, cause, âge, valeur et statut manuel fusionnés ; une
  valeur divergente est reportée en note, le statut le plus grave (`refute`, puis `contradictoire`) est retenu ;
- étiquettes des deux fiches (et des événements fusionnés) réunies.

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

### Supprimer une citation ou une source (#248)

Aucune suppression n'est automatique : tout passe par `arbre_proposer` (diff, résumé) puis `arbre_appliquer`
après accord, et s'annule par `arbre_annuler_modification`. `supprimer_citation` vise une citation précise :
`source`, plus `page` ou `index` si plusieurs citations de la même source sont sur le porteur (l'erreur liste
celles présentes). `supprimer_source` refuse une source encore citée et énumère ses porteurs ; avec
`cascade: true`, chaque citation retirée figure dans le résumé avec son porteur. Pour une source en double,
préférer `fusionner_sources` (`de: S352`, `vers: S321`) : aucune citation ne se perd, les citations devenues
identiques sont fondues et aucune source orpheline ne reste. Un porteur qui n'a plus de citation est signalé
dans les avertissements. Notes : la fiche `sources/<S…>.md` d'une source supprimée perd ses sections générées ;
sans texte libre, elle est retirée, sinon conservée avec une alerte ; les fiches des porteurs sont régénérées.

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
