---
description: Trouver le registre d'un acte (naissance, mariage, décès ; recherche automatisée AD59, guidée ailleurs), y repérer la vue, transcrire et archiver ; --autonome pour une recherche sans question déposée dans la file de propositions
argument-hint: <id|nom> [naissance|mariage|deces] [--autonome] [budget images=… duree=…]
---
Recherche d'acte : **$ARGUMENTS**

La recherche du registre n'est automatisée que pour AD59 ; ailleurs, l'utilisateur relève la cote ou l'ARK
sur le site du service. La vue de l'acte se repère en parcourant le registre (aucun index nominatif). Le
téléchargement dépend du service (IIIF, visionneuse qualifiée) ; sinon, partir d'une capture fournie.

Applique les skills `methodologie-gps`, `sources-francaises`, `droit-communicabilite` et `paleographie`.

**Mode autonome** (`--autonome` dans `$ARGUMENTS`, `docs/enquetes.md`) : après l'étape 1, ouvrir ou reprendre
l'enquête de l'acte (`enquete_reprendre()`, sinon `enquete_ouvrir(sujet, personnes=[id], budget=…)` si un budget
est indiqué : accord demandé au lancement, donc seulement avec l'utilisateur présent ; sans surveillance,
pas de budget : défauts de la configuration ou enquête ouverte au préalable), puis confier les étapes 2 à 6 à l'agent **`chercheur`** avec une
consigne commençant par `MODE AUTONOME`, `enquete: <id>`, `budget: …`, suivie de la personne et de l'acte
cherché. Aucune question : ce qui demande l'utilisateur (cote ou ARK à relever, anti-robot, capture, archives
hors ligne) devient une tâche manuelle (`enquete_noter`), la conclusion est déposée par
`propositions_deposer(..., enquete=<id>)` « à vérifier » si elle établit une filiation, puis l'agent
**`verificateur`** est sollicité sur ce fait. Rendre le compte rendu à format fixe du chercheur. Sans
`--autonome`, suivre les étapes ci-dessous en mode interactif.

1. **Identifier le fait** : `arbre_recherche` puis `arbre_personne(id)`. Déterminer le type d'acte
   (naissance / mariage / décès, ou déduire de la lacune via `arbre_lacunes`), la commune et la date.
   Refuser toute recherche externe si la personne est présumée vivante (`arbre_vivant`).
2. **Service et couverture** : `archives_service(lieu=commune, document=naissance|mariage|deces, annee=…)`
   pour le service réel et `en_ligne_pour_la_demande` ; compléter avec `communicabilite`. Une couverture
   déclarée ne prouve pas l'existence de l'acte.
3. **Trouver le registre** (cote + ARK) :
   - Si une source `S…` de l'arbre porte déjà un ARK de registre ou de vue, le réutiliser (`ark_resoudre`
     pour le vérifier).
   - Pour AD59, appeler `archives_registres(service="AD59", commune=…, annee=…, type_acte="N"|"M"|"D",
     personne=id)` : les cotes et ARK viennent du résultat officiel. Consulter les pages suivantes
     explicitement si nécessaire ; ne pas confondre registre trouvé et acte trouvé. `NMD` ou le type vide
     recherche sans filtre de type. `type_acte="TD"` renvoie les tables décennales dont la période recoupe
     l'année ou l'intervalle (`annee_fin`) ; `annee_fin` recherche aussi les registres d'un intervalle
     (ex. 1790-1802).
     Un résultat vide est une recherche négative sur ce périmètre, pas une preuve d'absence de l'acte.
   - Pour les autres services ou fonds non pris en charge, orienter vers la recherche du service
     (`liens_recherche`, `cotes_a_consulter` pour la cote
     typique), relever l'ARK du registre ou la cote + commune + années, puis tracer avec `source_collee`.
     Ne jamais deviner une cote ni contourner un captcha. En mode autonome : tâche manuelle.
   - En cas de `bloque_antirobot`, garder la tâche manuelle au journal et poursuivre les autres pistes.
     En mode interactif, suivre la `consigne` : demander à l'utilisateur une capture ou l'image de la vue,
     l'enregistrer avec `media_enregistrer(chemin, nom, classer=true)` (confirmation demandée), puis la
     transcrire (étape 5) sans réessayer le site. En mode autonome, la tâche manuelle suffit.
4. **Localiser la vue de l'acte** : `archives_naviguer(ark_registre, page=…)` pour parcourir les vues
   (ou la table décennale pour retrouver année et n° d'acte avant d'aller à l'acte). Pour un registre AD59
   chronologique, `archives_planche(ark_registre, de, a, pas, bandeau="pct:0,0,100,35")` : une seule image de
   4 à 12 vues (sondage large puis fin) au lieu d'un aperçu par vue. Pour atteindre une date connue,
   `archives_sonder(ark_registre, date_cible, type_acte, enquete=<id>)` propose la vue à lire ; après chaque
   lecture, le rappeler avec `lecture={vue, date, date_fin, type}` jusqu'à `arret` (`localise` : lire l'acte
   puis `conclusion="trouve"|"absent"` ; `absent` : négatif journalisé). Choisir la vue. Avec une enquête, passer
   `enquete=<id>` à chaque outil de collecte (`archives_naviguer`, `archives_planche`, `archive_image`,
   `piece_archiver`… : budget compté).
5. **Lire, transcrire, archiver** : suivre `/genealogiste:transcris` — aperçu (`archive_image`, 800 px gris)
   puis recadrage de l'acte, transcription diplomatique (niveau de confiance par champ), `piece_archiver`
   (pleine résolution + note compagnon), puis la citation : source, média, citation (`consultation: image`,
   transcription dans `texte`), faits et témoins en `associations`, en `arbre_proposer` (mode interactif) ou
   `propositions_deposer(..., enquete=<id>)` (mode autonome).
6. Journaliser les recherches négatives (`source_collee` avec `negatif=true`, ou `enquete_noter` dans une
   enquête). En mode interactif, présenter le diff et ne rien appliquer sans accord explicite.
