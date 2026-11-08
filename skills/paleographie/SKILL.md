---
name: paleographie
description: Aide à la lecture des actes anciens — paléographie française (XVIᵉ-XIXᵉ s.), abréviations, latin des registres paroissiaux, formulaires de baptême/mariage/sépulture, dates en lettres, calendrier républicain. À utiliser pour transcrire un acte, lire une image d'acte, déchiffrer une écriture ancienne, traduire un acte en latin, « que dit cet acte ? », extraire les données d'un acte.
---

# Paléographie et lecture d'actes

## Procédure de transcription

0. **Image** : appeler `archive_image(source)` avec le fichier local ou le lien de document/visionneuse.
   Le serveur résout IIIF et les services qualifiés (AD59) côté Python : conserver le HTML, JavaScript et
   les manifestes hors du contexte du modèle. Lire d'abord le `chemin_absolu` de l'aperçu (800 px, gris),
   puis recadrer l'acte seul avec la même source. Suivre les alertes de résolution et le coût indicatif.
   Un ARK ne garantit pas le téléchargement ; si le serveur ne sait pas résoudre le service ou si une
   connexion est requise, demander un lien IIIF explicite ou un fichier téléchargé manuellement.
   Pour conserver l'originale et ses références, proposer `piece_archiver` avec la même source : le cache
   évite les téléchargements répétés. L'archivage ne valide ni la transcription ni la filiation.
1. **Décrire le document** : type d'acte, langue, époque estimée, état (lisibilité, taches, lacunes).
2. **Transcription diplomatique** ligne à ligne : orthographe d'origine conservée, abréviations développées
   entre crochets `[ ]`, mots incertains suivis de `(?)`, illisibles `[…]`. Ne jamais compléter un nom
   par supposition.
3. **Traduction** (latin) ou **mise en français moderne** si utile.
4. **Extraction structurée** : sujet, date (convertir : `convertir_date`), lieu, parents, conjoint,
   âges, professions, domiciles, signatures (« a déclaré ne savoir signer »), mentions marginales, et
   **tous les intervenants** (témoins, parrain, marraine, déclarant, officier, prêtre) avec âge, profession,
   domicile et lien déclaré → `associations` (rôle + détail), reliés à une fiche existante seulement si
   l'identité est établie.
5. **Classification** : originale/dérivée/composite, information primaire/secondaire par donnée, preuve directe/indirecte selon le document réellement consulté ; le format image ne suffit pas à décider.
6. **Niveau de confiance de la lecture** par champ (sûr / probable / incertain) et passages à faire
   relire. Proposer la citation (dépôt, cote, vue, `consultation: "image"`, transcription dans `texte`)
   et, sur accord, `arbre_proposer`.

## Pièges fréquents

- Lettres : `s` long (ſ) ≠ `f` ; `u`/`v` et `i`/`j` interchangeables ; `y` final = `i` ; `ß`-like `ss`.
- Chiffres et mois : `7bre` = septembre, `8bre` octobre, `9bre` novembre, `Xbre`/`10bre` décembre.
- Dates en lettres (« le vingt-cinq du mois de mars mil sept cent quarante deux »).
- Noms : orthographe instable d'un acte à l'autre ; féminisation (la Martine = femme Martin).
- « feu » / « défunt » = décédé ; « en légitime mariage » ; « fils naturel » ; « veuve de ».
- Âges approximatifs (« âgé d'environ 60 ans ») = information secondaire.

## Latin des registres

Abréviations et formulaires : [references/latin-et-abreviations.md](references/latin-et-abreviations.md).
Prénoms latins → français : outil `normaliser_nom` (Joannes, Joannem, Joannis → Jean ; Petrus → Pierre…).
