---
name: paleographie
description: Aide à la lecture des actes anciens — paléographie française (XVIᵉ-XIXᵉ s.), abréviations, latin des registres paroissiaux, formulaires de baptême/mariage/sépulture, dates en lettres, calendrier républicain. À utiliser pour transcrire un acte, lire une image d'acte, déchiffrer une écriture ancienne, traduire un acte en latin, « que dit cet acte ? », extraire les données d'un acte.
---

# Paléographie et lecture d'actes

## Procédure de transcription (/gen:transcris)

1. **Décrire le document** : type d'acte, langue, époque estimée, état (lisibilité, taches, lacunes).
2. **Transcription diplomatique** ligne à ligne : orthographe d'origine conservée, abréviations développées
   entre crochets `[ ]`, mots incertains suivis de `(?)`, illisibles `[…]`. Ne jamais compléter un nom
   par supposition.
3. **Traduction** (latin) ou **mise en français moderne** si utile.
4. **Extraction structurée** : sujet, date (convertir : `convertir_date`), lieu, parents, conjoint,
   témoins/parrains (avec liens déclarés), âges, professions, domiciles, signatures (« a déclaré ne savoir
   signer »), mentions marginales.
5. **Classification** : source originale ; information primaire/secondaire par donnée ; preuve directe.
6. **Niveau de confiance de la lecture** par champ (sûr / probable / incertain) et passages à faire
   relire. Proposer la citation (dépôt, cote, vue) et, sur accord, `arbre_proposer`.

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
