---
description: Transcrire un acte ancien (paléographie, latin) et en extraire les données
argument-hint: <chemin de l'image | ARK Gallica | lien IIIF> [type d'acte, lieu, date si connus]
---
Transcription de : **$ARGUMENTS**

Applique la skill `paleographie`.
1. Obtenir l'image :
   - fichier local : le lire directement ;
   - ARK Gallica, manifeste IIIF, `info.json` ou URL d'image IIIF : `archive_image`. Pour les AD, demander le
     lien copié avec « Copier le lien IIIF » dans la visionneuse, ou à défaut le fichier obtenu avec
     « Télécharger » (recadrage local) ; jamais explorer l'API d'un site. Méthode
     économe : **aperçu** (`largeur` 800, `gris`) pour repérer l'acte sur la page, puis **recadrage** de
     l'acte seul (`region` `pct:x,y,l,h`, `largeur` 1500-2000) ; vérifier `cout_estime_tokens` ;
   - Gallica imprimé : essayer d'abord le texte OCR (`gallica_texte`).
   Lire l'image (outil de lecture de fichier). Si elle est floue ou partielle, recadrer plus serré ou demander
   un meilleur cadrage plutôt que deviner.
2. Rendre : description du document → transcription diplomatique (abréviations développées entre [ ],
   incertitudes (?), illisibles […]) → traduction/modernisation → tableau des données extraites avec
   niveau de confiance de lecture par champ → dates converties (`convertir_date`).
3. Classification de la source et des informations (primaire/secondaire par donnée).
4. Signaler que la transcription est produite par le modèle (à vérifier sur l'image). Proposer de conserver
   l'image (déjà dans `medias/iiif/` si elle vient d'`archive_image`, sinon `media_enregistrer`) et d'ajouter source, citation (avec la transcription
   dans `texte`) et faits à l'arbre via `/gen:ajoute` (validation explicite).
