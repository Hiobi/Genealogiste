---
description: Transcrire un acte ancien (paléographie, latin) et en extraire les données
argument-hint: <image | lien de visionneuse/IIIF | ARK> [type d'acte, lieu, date si connus]
---
Transcription de : **$ARGUMENTS**

Applique la skill `paleographie`.
1. Obtenir un aperçu avec `archive_image(source)` : fichier local, lien IIIF international, ARK Gallica
   ou lien de visionneuse qualifiée (AD59). Laisser le serveur résoudre le téléchargement ; ne pas ouvrir
   le HTML/JavaScript ni charger un manifeste entier dans le contexte du modèle.
   - D'abord `largeur=800`, `gris=true`, puis lire seulement le `chemin_absolu` renvoyé.
   - Recadrer l'acte seul (`region='pct:x,y,l,h'`, largeur 1500-2000) avec la même source ; vérifier
     `cout_estime_tokens` et les limites de résolution. L'originale reste dans le cache pour l'archivage.
   - Si le service est inconnu ou demande une connexion, suivre le repli du serveur : lien IIIF explicite
     ou fichier téléchargé manuellement. La présence d'un ARK ne suffit pas à garantir l'accès.
   - Gallica imprimé : essayer d'abord le texte OCR (`gallica_texte`).
   Lire l'image (outil de lecture de fichier). Si elle est floue ou partielle, recadrer plus serré ou demander
   un meilleur cadrage plutôt que deviner.
2. Rendre : description du document → transcription diplomatique (abréviations développées entre [ ],
   incertitudes (?), illisibles […]) → traduction/modernisation → tableau des données extraites avec
   niveau de confiance de lecture par champ → dates converties (`convertir_date`).
3. Classification de la source et des informations (primaire/secondaire par donnée).
4. Signaler que la transcription est produite par le modèle (à vérifier sur l'image). Proposer de conserver
   l'image avec `piece_archiver` (vue en ligne ou fichier téléchargé : pleine résolution, nom selon la
   convention, rangement, note compagnon ; réutiliser le même lien, sans retélécharger à la main), puis
   d'ajouter le média (`operations_suggerees`), la source, la citation (`citation_suggeree`, avec la transcription
   dans `texte`) et faits à l'arbre via `/genealogiste:ajoute` (validation explicite).
5. Si l'image est un fichier local au nom opaque, proposer son **nom selon la convention** :
   `piece_nommer` avec les données lues (personnes, commune, dépôt, type, années, cote, vue, n° d'acte),
   puis le renommage via `pieces_proposer(dossier, renommages=[{actuel, propose}])` après accord. Pour une
   nouvelle pièce : `media_enregistrer(chemin, nom, classer=true)`.
