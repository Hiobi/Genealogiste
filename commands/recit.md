---
description: Biographie rédigée, chaque phrase sourcée, contexte historique tiré des seules références consultées
argument-hint: <id> [longueur : courte|longue]
---
Récit de vie : **$ARGUMENTS**

1. `arbre_vivant(id)` : si la personne est présumée vivante, refuser.
2. Confier la rédaction à l'agent **`redacteur`** avec l'identifiant et la longueur souhaitée. Structure rendue :
   « Récit » (faits de l'individu, chaque phrase avec sa note), « Contexte » (séparé ; une phrase par élément de
   `contexte_local`, chacune avec sa note, formulée selon son niveau de rattachement ; **section absente** si rien
   de sourcé n'existe), « Hypothèses » (celles de `pistes_contexte`, avec la source qui les trancherait),
   « Questions ouvertes » (dont « contexte à documenter : … » le cas échéant), « Notes et sources ».
3. Vérifier le résultat avant de le rendre : `contexte_verifier(texte=<récit>, personne=<id>)`. Tant que le
   rapport n'est pas `conforme: true`, renvoyer le texte au `redacteur` avec les signalements (il retire ou
   documente, jamais il n'invente une référence). Contrôler aussi : chaque phrase factuelle a une note ; aucune
   donnée non sourcée n'est présentée comme un fait ; hypothèses formulées comme telles ; aucune phrase de
   contexte hors de la section « Contexte » ; aucune causalité entre le contexte et une décision de l'individu.
4. Rendre le récit avec le résultat du contrôle (`conforme`, `mesures`). S'il reste des signalements, les montrer
   avec les phrases à corriger : « conforme » ne veut pas dire « vrai », le contrôle est lexical.
5. Proposer l'enregistrement en Markdown dans le répertoire d'exports si l'utilisateur le souhaite. Note du
   coffre : proposer la section « Contexte » de la fiche (format « note du coffre » du `redacteur`), écrite
   seulement après accord, puis `contexte_verifier(note=<id>)`.
