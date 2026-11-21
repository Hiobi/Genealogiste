---
description: Billet du blog de Gramps Web (source étiquetée Blog) rédigé et sourcé, privé par défaut (diff + validation)
argument-hint: <id ou sujet> [public]
---
Billet de blog : **$ARGUMENTS**

1. `diagnostic` ou `arbre_info` : le blog est une page de **Gramps Web** ; en backend fichier, l'opération
   `ajouter_billet` est refusée. Expliquer qu'il faut `GENEALOGISTE_BACKEND=gramps` (une simple source étiquetée
   `Blog` ne s'afficherait nulle part hors de Gramps Web) et s'arrêter là.
2. Personne au centre du billet : `arbre_vivant(id)` ; présumée vivante → refuser. Lister les billets existants
   (`arbre_recherche(etiquette="Blog", objet="source")`) pour éviter un doublon.
3. Confier la rédaction à l'agent **`redacteur`** (format « billet ») : récit court, chaque fait sourcé par une
   note `[n]`, aucune personne présumée vivante nommée, Markdown simple (gras, italique, liens) seulement.
4. Préparer UNE proposition : images éventuelles par `ajouter_media` (avec `ref`, sans `lier_a`), puis
   `{"op": "ajouter_billet", "titre", "auteur", "texte", "format_texte": "markdown", "medias": ["$img", …]}`.
   Le premier média sert d'aperçu, tous forment la galerie. **Privé par défaut** : `"prive": false` seulement si
   l'utilisateur demande explicitement un billet public, lisible par les comptes Invité (Guest).
5. `arbre_proposer(operations, titre, justification)` → montrer le **résumé (visibilité du billet), le diff et
   les avertissements**. Un billet public qui nomme une personne présumée vivante ou privée est refusé : retirer
   le nom ou garder le billet privé.
6. Demander : « Publier ce billet ? ». Appeler `arbre_appliquer(jeton)` **uniquement** après un accord explicite ;
   sinon `arbre_annuler_proposition`. Annulation ensuite : `arbre_annuler_modification`.
7. Rappeler : le billet apparaît dans la page Blog de Gramps Web (`/blog`, le plus récemment modifié en tête) ;
   il n'est pas une source de preuve et n'a pas de fiche dans les notes de recherche (vault inchangé).
