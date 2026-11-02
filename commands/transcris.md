---
description: Transcrire un acte ancien (paléographie, latin) et en extraire les données
argument-hint: <chemin de l'image> [type d'acte, lieu, date si connus]
---
Transcription de : **$ARGUMENTS**

Applique la skill `paleographie`.
1. Lire l'image (outil de lecture de fichier). Si elle est floue ou partielle, le dire et demander un
   meilleur cadrage plutôt que deviner.
2. Rendre : description du document → transcription diplomatique (abréviations développées entre [ ],
   incertitudes (?), illisibles […]) → traduction/modernisation → tableau des données extraites avec
   niveau de confiance de lecture par champ → dates converties (`convertir_date`).
3. Classification de la source et des informations (primaire/secondaire par donnée).
4. Proposer de conserver l'image (`media_enregistrer`) et d'ajouter source, citation (avec la transcription
   dans `texte`) et faits à l'arbre via `/gen:ajoute` (validation explicite).
