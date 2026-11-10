---
description: Rechercher, transcrire et télécharger l'acte d'un individu (naissance, mariage, décès) depuis les archives
argument-hint: <id|nom> [naissance|mariage|deces]
---
Recherche d'acte : **$ARGUMENTS**

Applique les skills `methodologie-gps`, `sources-francaises`, `droit-communicabilite` et `paleographie`.

1. **Identifier le fait** : `arbre_recherche` puis `arbre_personne(id)`. Déterminer le type d'acte
   (naissance / mariage / décès, ou déduire de la lacune via `arbre_lacunes`), la commune et la date.
   Refuser toute recherche externe si la personne est présumée vivante (`arbre_vivant`).
2. **Service et couverture** : `archives_service(lieu=commune, document=naissance|mariage|deces, annee=…)`
   pour le service réel et `en_ligne_pour_la_demande` ; compléter avec `communicabilite`. Une couverture
   déclarée ne prouve pas l'existence de l'acte.
3. **Trouver le registre** (cote + ARK) :
   - Si une source `S…` de l'arbre porte déjà un ARK de registre ou de vue, le réutiliser.
   - Sinon, orienter vers la recherche du service (`liens_recherche`, `cotes_a_consulter` pour la cote
     typique), relever l'ARK du registre ou la cote + commune + années, puis tracer avec `source_collee`.
     Ne jamais deviner une cote ni contourner un captcha.
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
