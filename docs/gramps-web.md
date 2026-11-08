# Mode Gramps Web : Genealogiste en direct sur un arbre Gramps Web

Deux backends, choisis par `GENEALOGISTE_BACKEND` (pas de synchronisation bidirectionnelle) :

| Backend | Arbre de référence | Écriture | Historique / annulation |
|---|---|---|---|
| `fichier` (défaut) | `arbre.ged` (GEDCOM 7) dans le dépôt Git des données | un commit par proposition validée | `git log` / `git revert` |
| `gramps` | l'arbre Gramps Web (API) | une transaction `/api/transactions/` par proposition validée | `gramps-transactions.jsonl` local / transaction inverse |

Le contrat est le même dans les deux cas : `arbre_proposer` → diff → **accord explicite** →
`arbre_appliquer`. Rien n'est écrit sans accord, y compris une annulation (`arbre_annuler_modification`
puis `arbre_appliquer`).

## Configuration

Compte **local** Gramps Web dédié à Genealogiste, rôle *Editor* (créé dans Gramps Web : Paramètres >
Administration > Utilisateurs). Identifiants dans l'environnement ou le `.env` du répertoire de données,
jamais dans Git, un journal ou une issue.

| Variable | Rôle |
|---|---|
| `GENEALOGISTE_BACKEND` | `fichier` (défaut) ou `gramps` |
| `GENEALOGISTE_GRAMPS_URL` | ex. `http://localhost:5055` (`http://grampsweb:5000` dans la stack Docker) |
| `GENEALOGISTE_GRAMPS_USER` / `_PASSWORD` | compte local dédié, rôle Editor |
| `GENEALOGISTE_GRAMPS_TTL` | secondes entre deux relectures incrémentales en lecture (défaut 30) |
| `GENEALOGISTE_GRAMPS_NOTES_AUTO` | notes de preuve `Sosa:auto` : `true` (défaut, recalcul sur toute la base à chaque écriture), `modifies` (recalcul limité aux objets touchés), `false` (aucune note ni étiquette générée ; celles qui existent sont conservées telles quelles) |
| `GENEALOGISTE_GIT_MIRROR` | `true` : miroir GEDCOM 7 versionné de l'arbre Gramps (défaut `false`) |
| `GENEALOGISTE_GIT_REMOTE` | dépôt distant optionnel du répertoire de données (**privé**) |

Le mode direct suppose une instance Gramps Web **privée** : les personnes vivantes y sont écrites en clair.
Elles restent masquées par défaut dans les exports publics (`arbre_exporter`).

## Fonctionnement

- **Lecture** : chargement complet au premier besoin (`GET /api/<objets>/`), puis relecture incrémentale
  (`?keys=handle,change`). Les objets modifiés et ceux à l’horodatage le plus récent de chaque classe sont
  relus : Gramps date les modifications à la seconde. Le bilan ne compte que les contenus réellement changés. Preuve, cohérence, ascendance, lacunes
  sont calculées localement.
- **Proposition** : l'arbre est relu, les opérations appliquées sur une copie, puis réécrites en objets
  Gramps **par-dessus** l'état lu ; seuls les objets réellement modifiés entrent dans la transaction. Le
  diff montré est le diff GEDCOM 7 de l'arbre (lisible), avec le bilan des objets Gramps.
- **Accord** : nouvelle relecture ; si un objet de la transaction a été modifié dans l'interface depuis la
  proposition, **refus** (le serveur compare aussi `old` à la base). L'arbre est rechargé : reformuler la
  proposition (nouveau diff, nouvel accord). `force` n'est jamais utilisé.
- **Transaction** : atomique, message = titre + justification + opérations + sources ; gros lots en tâche
  de fond (`background`, suivi de `/api/tasks/`).
- **Annulation** : `arbre_historique` donne la référence de la transaction ; `arbre_annuler_modification`
  prépare la transaction inverse (`undo`), refusée si les objets ont changé depuis.

## Journal d'intention et reprise

`gramps-transactions.jsonl` trace chaque transaction en plusieurs lignes (même `id`, fusionnées à la lecture) :

| État | Écrit |
|---|---|
| `intention` | **avant** l'envoi, avec les objets à écrire |
| `envoyee` | dès la réponse de Gramps Web, avec les objets écrits |
| `terminee` / `complements_en_echec` | après les étapes complémentaires (`etapes` : envoi des médias, miroir Git) |
| `refusee` | conflit ou refus du serveur : rien n'a été écrit |
| `indeterminee` | interruption pendant l'envoi (réseau coupé, arrêt) |

Une transaction acceptée par Gramps Web reste donc annulable même si la suite échoue : le résultat porte un
`avertissement` (relancer `gramps_envoyer_medias` ou `gramps_synchroniser`). Avant toute application ou
annulation, les transactions `intention` ou `indeterminee` sont comparées à l'état de Gramps Web et marquées
`envoyee`, `non_envoyee` ou `partielle`. `arbre_historique` affiche l'état et les étapes.

## Correspondance Genealogiste ↔ Gramps (`mcp/src/genealogiste_mcp/gramps/mapping.py`)

Module unique, utilisé par l'export Gramps XML et par le mode direct, testé aller-retour
(`tests/test_gramps_mapping.py`, et sur un vrai Gramps Web par `make test-gramps`).

| Genealogiste | Gramps |
|---|---|
| xref `I12`, `F3`, `S7`, `R1`, `O2`, note partagée `N4` | `gramps_id` |
| uid de personne, famille, événement | attribut `Sosa-UID` (absent si l'objet vient de l'interface : uid dérivé du handle) |
| uid des noms | attribut de personne `Sosa-UID noms` (dans l'ordre) |
| statut forcé (réfuté, contradictoire) + justification | attribut `Sosa-Statut` « refute \| justification » (événement, famille), `Sosa-Statut nom N`, `Sosa-Statut filiation I3` |
| vivant forcé | attribut `Sosa-Vivant` Y/N |
| témoin, parrain, officier… de l'arbre | référence d'événement sur sa fiche (rôle Witness, Godparent, Celebrant, Informant, ou libellé français) + attribut `Sosa-Association` |
| intervenant seulement nommé | attribut d'événement `Sosa-Association` « rang \| RÔLE \| précision \| nom \| » avec ses citations |
| parrain/marraine de niveau individu | `personref` + attribut de personne `Sosa-Association` « … \| xref » |
| citation | page, confiance (QUAY ; attribut `QUAY` si 2), notes `Transcript` / `Citation`, attributs Consulté, Type de source, Information, Preuve, Date de consultation, ARK |
| source | titre, auteur, publication, dépôt + cote, attributs URL, ARK, Type de source, Dérivée de |
| lieu | titre « Commune, Département, Pays », code INSEE, coordonnées ; paroisse en attribut d'événement |
| âge | attribut `Age` de la référence d'événement |
| cause, précision du type | attributs `Cause`, `Précision` |
| date GEDCOM 7 | date Gramps (calendrier, qualificatif, qualité) ; la chaîne GEDCOM est gardée dans `text` |

Une personne, un événement ou une note créés dans l'interface Gramps sont lus sans attribut historique `Sosa-*` et
réécrits **à l'identique** tant que Genealogiste ne les modifie pas. Ce que Genealogiste ne modélise pas (adresses, URL,
étiquettes, titres et suffixes de nom, noms alternatifs et dates des lieux, médias d'événements, notes isolées…) est
conservé tel quel.

Non mappé : les nœuds GEDCOM non interprétés (`extra`), perdus à l'aller-retour. Normalisations : type de
nom `BIRTH` = nom de naissance, filiation `BIRTH` = filiation biologique, un même nom de lieu = un seul
lieu Gramps (coordonnées et code INSEE mis en commun). Un événement partagé par plusieurs personnes
(rôle *Primary*) reste partagé tant qu'il n'est pas modifié ; modifié pour l'une d'elles, il est dédoublé.

## Notes de preuve générées (`Sosa:auto`)

Statut de preuve de chaque fait (note *Research* + étiquette « Preuve : … » sur l'événement), fiche de preuve
de la personne, filiations de la famille, lien cliquable des sources : notes étiquetées **`Sosa:auto`**,
recalculées à chaque écriture et ignorées à la lecture. Après des modifications faites dans l'interface,
`gramps_recalculer_notes` propose leur recalcul (toute la base, même en mode `modifies` ; refusé en mode
`false`). Les notes manuelles ne sont **jamais** modifiées.

En mode `modifies`, sont recalculées les notes des personnes, familles, événements et sources modifiés par la
proposition, plus les membres des familles modifiées et les familles des personnes modifiées (filiations). Le
statut d'un fait calculé localement (`arbre_fiche`, `arbre_statut_preuve`) reste toujours exact ; seules les
notes de la base Gramps peuvent être en retard.

`arbre_proposer` indique dans `transaction_gramps.dont_notes_de_preuve_seules` combien d'objets ne changent que
par leurs notes ou étiquettes de preuve, et ajoute un avertissement quand la transaction dépasse 50 objets pour
moins de 5 opérations (première écriture, recalcul global).

Les notes de preuve **sans** étiquette (import d'un GEDCOM ou d'un export GeneWeb produit par Genealogiste) sont
reconnues à leur gabarit : `⛔|🟡|🟢|✅|⚠️|❌ Preuve : …`, `Filiation de … : …`,
`Fiche de preuve (plugin genealogiste)…`, `Lien : http…`. Elles sont **adoptées** à la première écriture
(étiquetées `Sosa:auto` et réécrites en place), jamais doublées. Une note manuelle qui commence par l'un de ces
gabarits est donc traitée comme générée : la reformuler si elle doit être conservée.

## Bascule fichier → Gramps Web

1. `gramps_bascule_proposer` : bilan de l'envoi de tout `arbre.ged` dans un arbre Gramps Web **vide** ;
2. `gramps_bascule_appliquer(jeton)` après accord : une transaction, puis `BASCULE.json` et le dernier
   commit « Bascule vers Gramps Web » figent `arbre.ged` (les propositions en mode fichier sont refusées) ;
   `journal.jsonl` reste local ;
3. redémarrer le serveur MCP avec `GENEALOGISTE_BACKEND=gramps`.

## Miroir Git optionnel

`GENEALOGISTE_GIT_MIRROR=true` (mode gramps) : l'arbre Gramps est exporté en GEDCOM 7 dans `arbre.ged`
(même dépôt et même historique qu'en mode fichier), un commit par transaction ; les modifications faites
hors de Genealogiste sont commitées à la synchronisation suivante (« Modifications externes »,
`gramps_synchroniser`).

Le dépôt est local par défaut. `GENEALOGISTE_GIT_REMOTE` ajoute un push après chaque commit : il doit être
**privé** (données de vivants) ; le dépôt du plugin est refusé.

## Tests

- `make test` : faux serveur Gramps Web (`tests/gramps_fake.py`, respx) fidèle au contrat de l'API
  (format des lectures, contrôle de `old`, `undo`, tâches de fond).
- `make test-gramps` : vrai Gramps Web jetable (`docker-compose.test.yml`, sans volume), données fictives.

## Médias (images d'actes)

- `ajouter_media` (`fichier` produit par `piece_archiver` : relatif au répertoire des données, ou absolu
  dans le vault ; l'envoi accepte le répertoire des médias et l'arborescence des pièces) crée l'objet Media ; une citation le référence par `medias` (`media_list` de la citation
  Gramps, `OBJE` sous la citation en GEDCOM) : l'image prouve la citation.
- La proposition annonce les fichiers à envoyer (`transaction_gramps.fichiers_a_envoyer`, ou
  `fichiers_absents`). Après accord, la transaction crée l'objet, puis chaque fichier est envoyé par
  `PUT /api/media/{handle}/file` (`If-Match` = somme MD5 lue) ; le serveur attribue chemin et somme.
- Le chemin local est gardé dans l'attribut `Sosa-Fichier` : le chemin du serveur n'est jamais réécrit.
- `gramps_envoyer_medias` : liste des fichiers absents ou différents dans Gramps Web (médias créés avant cette
  version, bascule), puis envoi avec `appliquer=true` après accord. La bascule envoie aussi les fichiers.

## Lieux hiérarchiques

- Un lieu « Commune, Département, Pays » est écrit en hiérarchie Gramps : commune (type *City*, code INSEE,
  coordonnées) → département (*Department*, code du département) → pays (*Country*). Les lieux englobants sont
  partagés et réutilisés s'ils existent déjà sous le même nom complet.
- Le nom relu (commune, puis lieux englobants) est identique au nom écrit : l'aller-retour GEDCOM ↔ Gramps ne
  change pas. Une forme non canonique (espaces autour des virgules, niveau vide) reste à plat.
- La **région n'est pas ajoutée** : les régions actuelles (2016) seraient anachroniques pour des actes anciens et
  changeraient le nom du lieu. Une région déjà présente dans le nom devient un niveau *Region*.
- `gramps_structurer_lieux` : propose de rattacher les lieux à plat d'une base existante (titre complet, créés
  par une version antérieure ou un import) à cette hiérarchie ; diff puis accord, aucun événement modifié.

## Plusieurs arbres

Dans Gramps Web, **un compte appartient à un seul arbre** : l'arbre est inscrit dans le jeton de connexion
(revendication `tree`) et toutes les requêtes passent par lui. Gérer plusieurs arbres (familles, clients)
demande donc un compte Gramps par arbre et, côté Genealogiste, **un répertoire de données par arbre** (journal,
propositions, miroir Git et notes ne doivent jamais se mélanger).

Garde-fou : à la première connexion, l'arbre du compte est enregistré dans `<données>/GRAMPS_ARBRE.json` ; un
autre arbre est ensuite refusé avec un message explicite (lecture et écriture). Changement voulu : vérifier,
puis supprimer ce fichier.

Exemple : un serveur MCP par arbre (paramètres utilisateur de Claude Code, `.mcp.json`), les identifiants de
chaque arbre dans le `.env` de son répertoire de données :

```json
{
  "mcpServers": {
    "genealogiste-famille": {
      "command": "uv",
      "args": ["run", "--quiet", "--directory", "/chemin/vers/Genealogiste/mcp", "genealogiste-mcp"],
      "env": {"GENEALOGISTE_DATA_DIR": "~/genealogie/famille"}
    },
    "genealogiste-client-dupont": {
      "command": "uv",
      "args": ["run", "--quiet", "--directory", "/chemin/vers/Genealogiste/mcp", "genealogiste-mcp"],
      "env": {"GENEALOGISTE_DATA_DIR": "~/genealogie/client-dupont"}
    }
  }
}
```

```sh
# ~/genealogie/client-dupont/.env
GENEALOGISTE_BACKEND=gramps
GENEALOGISTE_GRAMPS_URL=https://gramps.exemple.org
GENEALOGISTE_GRAMPS_USER=sosa-dupont
GENEALOGISTE_GRAMPS_PASSWORD=…
```

Hors v1 : fusion native de Gramps (la fusion passe par `/fusionne`).

## Reprise des lectures

Les GET sont tentés au plus trois fois sur erreur réseau ou HTTP 502/503/504 (attentes de 2 puis
4 secondes). Un 401 de lecture autorise un renouvellement de jeton et une nouvelle lecture ; les autres
statuts ne déclenchent pas de reprise. Le jeton expiré localement est renouvelé avant tout appel.

POST, PUT et DELETE ne sont jamais rejoués automatiquement, y compris sur 401. Après un refus 401,
un nouvel appel explicite renouvelle d’abord le jeton. Après une réponse perdue pendant une écriture,
relire l’arbre et le journal avant de proposer une nouvelle opération : l’absence de réponse ne prouve
pas que la transaction a échoué.

Le miroir Git utilise l’état qui vient d’être lu, sans nouvelle synchronisation imbriquée : son message
conserve le bilan des modifications externes, même avec un TTL de zéro.
