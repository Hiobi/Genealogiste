---
description: Trouver le registre d'un acte (naissance, mariage, décès ; recherche automatisée AD59, guidée ailleurs), y repérer la vue, transcrire et archiver
argument-hint: <id|nom> [naissance|mariage|deces]
---
Recherche d'acte : **$ARGUMENTS**

La recherche du registre n'est automatisée que pour AD59 ; ailleurs, l'utilisateur relève la cote ou l'ARK
sur le site du service. La vue de l'acte se repère en parcourant le registre (aucun index nominatif). Le
téléchargement dépend du service (IIIF, visionneuse qualifiée) ; sinon, partir d'une capture fournie.

Applique les skills `methodologie-gps`, `sources-francaises`, `droit-communicabilite` et `paleographie`.

1. **Identifier le fait** : `arbre_recherche` puis `arbre_personne(id)`. Déterminer le type d'acte
   (naissance / mariage / décès, ou déduire de la lacune via `arbre_lacunes`), la commune et la date.
   Refuser toute recherche externe si la personne est présumée vivante (`arbre_vivant`).
2. **Service et couverture** : `archives_service(lieu=commune, document=naissance|mariage|deces, annee=…)`
   pour le service réel et `en_ligne_pour_la_demande` ; compléter avec `communicabilite`. Une couverture
   déclarée ne prouve pas l'existence de l'acte.
3. **Trouver le registre** (cote + ARK) :
   - Si une source `S…` de l'arbre porte déjà un ARK de registre ou de vue, le réutiliser.
   - Pour AD59, appeler `archives_registres(service="AD59", commune=…, annee=…, type_acte="N"|"M"|"D",
     personne=id)` : les cotes et ARK viennent du résultat officiel. Consulter les pages suivantes
     explicitement si nécessaire ; ne pas confondre registre trouvé et acte trouvé. `NMD` ou le type vide
     recherche sans filtre de type ; les tables décennales ne sont pas qualifiées dans ce formulaire.
     Un résultat vide est une recherche négative sur ce périmètre, pas une preuve d'absence de l'acte.
   - Pour les autres services ou fonds non pris en charge, orienter vers la recherche du service
     (`liens_recherche`, `cotes_a_consulter` pour la cote
     typique), relever l'ARK du registre ou la cote + commune + années, puis tracer avec `source_collee`.
     Ne jamais deviner une cote ni contourner un captcha.
   - En cas de `bloque_antirobot`, garder la tâche manuelle au journal et poursuivre les autres pistes.
     Suivre la `consigne` : demander à l'utilisateur une capture ou l'image de la vue, l'enregistrer avec
     `media_enregistrer(chemin, nom, classer=true)`, puis la transcrire (étape 5) sans réessayer le site.
4. **Localiser la vue de l'acte** : `archives_naviguer(ark_registre, page=…)` pour parcourir les vues
   (ou la table décennale pour retrouver année et n° d'acte avant d'aller à l'acte). Pour un registre AD59
   chronologique, `archives_planche(ark_registre, de, a, pas, bandeau="pct:0,0,100,35")` : une seule image de
   4 à 12 vues (sondage large puis fin) au lieu d'un aperçu par vue. Choisir la vue.
5. **Lire, transcrire, archiver** : suivre `/genealogiste:transcris` — aperçu (`archive_image`, 800 px gris)
   puis recadrage de l'acte, transcription diplomatique (niveau de confiance par champ), `piece_archiver`
   (pleine résolution + note compagnon), puis `arbre_proposer` : source, média, citation (`consultation: image`,
   transcription dans `texte`), faits et témoins en `associations`.
6. Journaliser les recherches négatives (`source_collee` avec `negatif=true`). Présenter le diff et ne
   rien appliquer sans accord explicite.
