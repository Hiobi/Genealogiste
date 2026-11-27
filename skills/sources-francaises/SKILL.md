---
name: sources-francaises
description: Connaissance des sources généalogiques françaises et de leur localisation — état civil (1792+), registres paroissiaux BMS, tables décennales, recensements (1836+), registres matricules (classes 1867+), notaires (contrats de mariage, inventaires), enregistrement (tables des successions), cadastre napoléonien, hypothèques, archives départementales, Gallica, matchID, Mémoire des hommes, émigration et immigration (passeports, police des étrangers, naturalisation, état civil consulaire). À utiliser pour « où trouver », « quelle source », « quelle cote », « quelles archives », plan de recherche, lacunes, prochaine source à consulter.
---

# Sources françaises — quoi, où, pour quoi

Toujours préciser : **type de source** (originale/dérivée), **service** (AD, mairie, SHD…),
**cote typique** (cadre de classement, à vérifier dans l'inventaire), **communicabilité**, **accès en ligne**.
Outils : `cotes_a_consulter`, `prochaine_source`, `liens_recherche`, `sources_catalogue` (tout ce que le plugin connaît, dont les sites tiers : cercles, relevés, bases thématiques), `communicabilite`, `archives_service` (service réel : site, mise en ligne, NAAN ; docs/archives.md), `ark_resoudre`, `archives_registres`,
`archives_naviguer` (vues d'un registre), `archive_image` (lecture d'une vue), `piece_archiver` (conservation).
Ces outils donnent le **pays du lieu** (`pays` : code, nom, provenance) : hors de France, aucune série d'AD
(renvoi générique, transcription éventuelle en France) ; pays inconnu : séries d'AD « si le lieu est en
France » seulement, et demander le pays ou le département à l'utilisateur, sans présumer la France.
Pour AD59 et les services Mnesys du référentiel (AD14, AD19, AD25, AD27, AD37, AD39, AD51, AD55, AD58, AD69, AD80, AD90, AD91, AD972), `archives_registres(service=…, commune=…, annee=…, type_acte="N"|"M"|"D", personne=id)`
localise les registres depuis le résultat officiel. Une page par appel ; poursuivre explicitement avec
`page_suivante`. `NMD` ou le type vide ne filtre pas le type ; `type_acte="TD"` donne les tables décennales
couvrant l'année ; `annee_fin` (≥ `annee`) recherche un intervalle (ex. 1790-1802 ou une décennie).
AD59 : quand la recherche est vide ou qu'un volume n'est pas en ligne, `classeur_3e` donne la cote 3 E et le
statut du classeur du service (« pas en ligne avant AAAA ; consultation en salle de lecture ») ; « inconnu du
classeur » ne veut pas dire que le registre n'existe pas. `prochaine_source` cite ces cotes pour un acte du Nord.
Recensements du Nord : `archives_registres(service="AD59", commune=…, annee=…, type_acte="REC")` localise la
liste nominative (cote, ARK) ; `couverture_recensements` dit si le millésime est en ligne ou seulement en salle
de lecture (communicable après 75 ans) et liste les millésimes connus ; « inconnu du référentiel » ne veut pas
dire inexistant. `cotes_a_consulter` cite ces cotes. Recherche par nom : base Socface de FranceArchives, à
consulter soi-même dans un navigateur (jamais automatisée). L'âge déclaré est une information secondaire ;
une absence dans une liste ne prouve ni décès ni départ (docs/recensements.md).
Matricules du Nord : `archives_registres(service="AD59", commune=<bureau de recrutement ou "">, annee=<classe>,
type_acte="RM")` ; classe = année de naissance + 20 (`cotes_a_consulter` la calcule pour une naissance dans le
Nord : `matricules_ad59`). La réponse distingue `categorie: tables` (table alphabétique de la classe et du
bureau, à lire d'abord pour le numéro matricule) et `categorie: fiches` (volumes des états signalétiques,
classes 1867 à 1923 en ligne, bureau dans `contexte`), avec la cote 1 R réelle ; sans bureau, tous les bureaux
de la classe. Un intervalle (`annee_fin`) ne rend que les tables. Vérifier `communicabilite("matricule")` ;
une absence dans une table ne prouve rien (autre bureau, autre classe, engagé volontaire).
Successions du Nord : `archives_registres(service="AD59", commune=<bureau de l'enregistrement>, annee, annee_fin,
type_acte="SUCC")` pour les tables des successions et absences (3 Q, au plus 1791-1968), puis
`type_acte="FD"` pour les fiches décès qui les prolongent (1969 à 1975). La clé est le bureau, pas la commune :
il n'est pas déduit du lieu, une erreur liste les valeurs du formulaire (`cotes_a_consulter` rappelle l'appel :
`successions_ad59`). Fiches décès : jamais « librement communicables » ; le service affirme un délai de 50 ans,
non vérifié par le plugin : relayer `avertissement_communicabilite`, ne rien publier sur des héritiers vivants.
Une absence dans une table ne prouve pas l'absence de décès (autre bureau, succession non déclarée).
Hypothèques du Nord (4 Q, an VII à 1955 ; bien, vente, dot ou apport immobilier, notaire inconnu) :
`archives_registres(service="AD59", commune=<bureau des hypothèques>, annee, type_acte="HYP")` rend trois
catégories à lire dans l'ordre : `indicateur` (noms de famille, pour s'orienter), `tables` (table alphabétique :
numéro de case du propriétaire), `repertoires` (par numéro de case : volume et numéro des actes, à consulter
ensuite en salle de lecture) ; `HYPI`, `HYPT`, `HYPR` pour feuilleter une seule catégorie (`page`). Le bureau
est celui de l'arrondissement, pas la commune ; aucune date n'est envoyée. **Ne jamais transmettre le nom
cherché** : comparer soi-même son initiale ou son début (capitales sans accents) à `plage_alphabetique.debut`
et `.fin` de chaque volume, bornes comprises ; retenir tous les volumes qui le couvrent (classement
phonétique, plages qui se chevauchent, séries parallèles : `bureau_titre`), puis lire les vues. La recherche se
fait par nom de propriétaire, jamais par adresse (`cotes_a_consulter` rappelle l'appel : `hypotheques_ad59`).
Ensuite `archives_naviguer` parcourt les vues, `archive_image` les lit et `piece_archiver` conserve l'original.
Un résultat vide ne démontre pas que l'acte n'existe pas ; un blocage conserve une tâche manuelle au journal.
Défi anti-robot (`bloque: "anti-robot"`, ex. Anubis aux AD de la Lozère, redirection JS des AD Arkotheque
comme le Cantal, blocage « robots IA » de WikiTree) ou `consultation_manuelle` dans
`archives_service` : ne pas relancer ni contourner ; demander à l'utilisateur une capture ou l'image de la vue,
l'enregistrer avec `media_enregistrer(chemin, nom, classer=true)`, la lire, puis tracer avec `source_collee`.
En mode autonome (aucune personne présente), ce blocage devient une tâche manuelle de l'enquête (`enquete_noter`).

| Source | Période | Série AD typique | Apporte | Remarques |
|---|---|---|---|---|
| Registres paroissiaux (BMS) | XVIᵉ s.–1792 | E / 4 E, GG (dépôt communal), G | baptême, mariage, sépulture ; parrains | latin fréquent ; double collection après 1667 |
| État civil | 1792 → | E / 4 E ; mairie (collection communale) | naissance, mariage, décès ; mentions marginales | calendrier républicain 1792-1805 |
| Tables décennales | 1792 → | avec l'état civil | localiser un acte (dérivée) | une table par commune et décennie |
| Publications de bans | 1792 → | état civil | domiciles, mariage ailleurs | |
| Recensements (listes nominatives) | 1836 → (quinquennaux) | 6 M | foyer, âges, professions | âges approximatifs (information secondaire) |
| Registres matricules | classes 1867 → | 1 R | naissance, parents, signalement, parcours | classe = année de naissance + 20 |
| Notaires (minutes, répertoires) | XVᵉ s. → | 3 E (par étude) | contrats de mariage, inventaires, partages, testaments | répertoire du notaire, tables de l'enregistrement |
| Insinuations, contrôle des actes | 1693–1790 | C | localiser un acte notarié | |
| Enregistrement : tables des successions et absences, mutations par décès | 1791 → | 3 Q | date de décès, héritiers, biens | excellent pour la filiation |
| Hypothèques | 1798 → | 4 Q | transcriptions de ventes, inscriptions | |
| Cadastre napoléonien | 1807–1850 env. | 3 P | propriétés, voisinage | états de sections, matrices |
| Justice de paix, tribunaux | 1790 → | U | tutelles, émancipations, actes de notoriété | |
| Fichier des décès INSEE (matchID) | 1970 → | en ligne | décès, n° d'acte, lieu | dérivée → demander l'acte |
| Presse, annuaires (Gallica) | XVIIᵉ s. → | gallica.bnf.fr | avis de décès, faire-part, annuaires | OCR à vérifier sur l'image |
| Mémoire des hommes | 1914 → | SGA en ligne | morts pour la France, JMO | |
| Grand Mémorial | 14-18 | culture.gouv.fr | matricules indexés | |
| Passeports, police des étrangers | XIXᵉ s. → | 4 M dans plusieurs services (à vérifier dans l'inventaire) | départs, déclarations de résidence des étrangers | classement propre à chaque service |
| Décrets de naturalisation | inventaire 1883-1948 | Archives nationales | n° de dossier, accès au dossier | partiellement indexé ; cote du dossier auprès des AN |
| État civil consulaire | | Service central d'état civil (Nantes) ; transcription en commune du dernier domicile | actes de Français à l'étranger | sans garantie d'existence |

## Types acceptés par les outils

Pour `archives_service` et `communicabilite`, utiliser les clés canoniques décrites dans
[le référentiel](../../docs/archives.md#types-de-documents-communs--129). `matricules`, `notaires`,
`recensements` et `justice` sont acceptés comme alias. `judiciaire` est la clé canonique
pour la justice. Les types larges `paroissiaux`, `enregistrement` et `insinuation` demandent de préciser
le fonds et son régime : une réponse `communicable: null` appelle une vérification auprès du service.
Les types naturalisations et hospitalier restent à qualifier. Une clé reconnue n'annonce aucun accès en ligne.
Avec `document`, `archives_service` renvoie `visionneuse_pour_la_demande` : l'accès propre au type
(`origine: document`, ex. matricules sur une autre application que l'état civil), sinon celui du service
(`service`), sinon `inconnu`. Si `telechargement.etat` vaut `a_qualifier_pour_ce_type`, l'adaptateur du
service ne s'applique pas à ce fonds : passer par le lien de consultation, un lien IIIF ou un fichier téléchargé.

## Stratégies

- **Remonter une génération** : acte de mariage (filiation des deux époux, âges, domiciles) → naissance de
  chaque époux → mariage des parents. Avant 1792 : mariage paroissial, puis baptêmes.
- **Décès introuvable** : tables décennales des communes voisines, table des successions (3 Q ; Nord :
  `archives_registres` `SUCC` par bureau, puis `FD` de 1969 à 1975), recensements
  (dernière présence), matchID (≥ 1970), transcriptions de décès (militaires, hôpitaux).
- **Filiation fragile** : contrat de mariage, inventaire après décès, déclaration de succession, tutelles.
- **Commune disparue ou fusionnée** : `geo_historique` (COG INSEE depuis 1943) ; avant : dictionnaire
  « Des villages de Cassini aux communes d'aujourd'hui » (EHESS). En mode gramps, `gramps_dater_lieux` propose
  les noms anciens et anciens départements datés des communes de l'arbre (Gramps affiche alors le nom d'époque
  à la date de l'événement) : diff, accord, annulable ; jamais de fusion des lieux.
- **Mobilité** : registres matricules (domiciles successifs), recensements, publications de bans.
- **Émigration, immigration** (`EMIG`, `IMMI`, `NATU`, `RESI` à l'étranger, `RESI_ETRANGER`) : `prochaine_source`
  donne les deux versants (`versant` : `france` / `etranger`). Côté français : registre matricule de la classe,
  passeports et police (4 M, à vérifier), recensements avant et après le départ (une absence ne prouve pas
  l'émigration), transcriptions et état civil consulaire ; pour un fait situé à l'étranger, ces pistes visent le
  département du dernier domicile en France, sans série d'AD pour le lieu étranger. Côté étranger : intitulés
  génériques (passagers, recensements, naturalisation, conscription), **aucune cote**, avertissement « existence
  du fonds non vérifiée », sites relevés par `sources_catalogue(theme="emigration")`. La **fenêtre de départ**
  (`arbre_lacunes(id)` → `fenetre_depart`, fiche) se lit sur l'arbre seul : dernier fait daté en France, premier
  fait daté à l'étranger, chacun cité avec son statut ; indéterminée sinon. Un événement générique à l'étranger
  peut être typé d'après sa source (`typage_propose`, puis `arbre_proposer`, accord explicite) ; jamais d'office.
  Détail : `docs/contexte-historique.md`, § « Émigration ».
- **Contexte du lieu et de l'époque** (renvoi, pas une source de l'individu) : `lieu_historique` (commune à une
  date, niveau par niveau ; un niveau « inconnu » ne se complète pas de mémoire), `presse_recherche` (presse
  ancienne, OCR à vérifier sur l'image), `contexte_bibliographie` (littérature citée), `contexte_local` et
  `pistes_contexte` (éléments et pistes d'une personne) ; commande `/genealogiste:contexte`. Méthode :
  `methodologie-gps`, § « Contexte historique » ; détail : `docs/contexte-historique.md`.

Détails par source : [references/sources-detaillees.md](references/sources-detaillees.md).
