---
description: Fiche complète d'une personne avec le statut de preuve de chaque fait
argument-hint: <id|nom>
---
Fiche de : **$ARGUMENTS**

1. Si l'argument n'est pas un identifiant (I12…), `arbre_recherche` ; en cas d'ambiguïté, lister les candidats
   et demander lequel.
2. `arbre_fiche(id)` puis `arbre_personne(id)` pour les détails.
3. Afficher la fiche : identité, filiation, unions/enfants, tableau des faits avec statut
   (✅ confirmé, 🟢 probable, 🟡 hypothèse, ⚠️ contradictoire, ❌ réfuté, ⛔ non sourcé), sources citées,
   contradictions argumentées, alertes de cohérence.
4. Pour chaque fait non confirmé : la prochaine source (service, cote typique, accès en ligne).
Personne présumée vivante : n'afficher que ce qui est strictement nécessaire et le rappeler.
