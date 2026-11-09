---
description: Inventorier, classer et renommer un dossier de pièces existant (scans, photos, PDF, audio, GeneWeb)
argument-hint: <dossier> [triage]
---
Organisation du dossier : **$ARGUMENTS**

Applique la skill `organisation-pieces` (convention : docs/pieces.md).

1. `pieces_inventaire(dossier)` : présenter les comptes par type, les patronymes principaux, les doublons
   et les fichiers ignorés.
2. `pieces_proposer(dossier)` : présenter la **racine**, le **périmètre**, le **résumé par dossier**, les doublons isolés, le nombre de pièces
   envoyées dans `_À trier/`, les médias de l'arbre non déplacés, et un extrait de l'aperçu. Indiquer le
   chemin du plan complet (TSV).
3. **Attendre l'accord explicite** de l'utilisateur, puis `pieces_appliquer(jeton)`. Rendre le contrôle
   (fichiers avant et après, empreintes identiques) et le nom du journal qui permet d'annuler.
4. S'il reste des pièces dans `_À trier/` ou des noms opaques, proposer le **triage**, ou le lancer si
   l'argument `triage` est donné : agent `trieur` sur ces fichiers (par lots d'une vingtaine), puis
   `pieces_proposer(dossier, renommages=…, seulement_renommages=true)` avec ses propositions de confiance haute ou moyenne, et de nouveau
   un accord avant `pieces_appliquer`.
5. Faits nouveaux relevés pendant le triage : les présenter comme une proposition `arbre_proposer`, jamais
   écrite sans validation. Personnes présumées vivantes : les signaler, sans aucune recherche externe.

Annuler une organisation : `pieces_proposer(dossier, annuler="<journal>.tsv")`, puis accord, puis
`pieces_appliquer`.
