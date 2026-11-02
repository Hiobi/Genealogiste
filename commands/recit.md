---
description: Biographie rédigée, chaque phrase sourcée, avec contexte historique local
argument-hint: <id> [longueur : courte|longue]
---
Récit de vie : **$ARGUMENTS**

1. `arbre_vivant(id)` : si la personne est présumée vivante, refuser.
2. Confier la rédaction à l'agent **`redacteur`** avec l'identifiant et la longueur souhaitée.
3. Vérifier le résultat avant de le rendre : chaque phrase factuelle a une note ; aucune donnée non sourcée
   n'est présentée comme un fait ; hypothèses formulées comme telles ; contexte historique séparé.
4. Proposer l'enregistrement en Markdown dans le répertoire d'exports si l'utilisateur le souhaite.
