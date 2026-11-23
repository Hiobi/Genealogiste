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
   Contexte historique : seulement des éléments sourcés (`contexte_local`), dans une section `**Contexte**`
   séparée ; rien de sourcé : pas de section. Contrôler le texte rendu :
   `contexte_verifier(texte=<texte>, personne=<id>)`. **`conforme: false` est bloquant** : ne rien proposer, renvoyer
   le texte au `redacteur` avec les signalements (il retire ou documente, jamais il n'invente une référence).
4. Préparer UNE proposition : images éventuelles par `ajouter_media` (avec `ref`, sans `lier_a`), puis
   `{"op": "ajouter_billet", "titre", "auteur", "texte", "format_texte": "markdown", "medias": ["$img", …]}`.
   Texte avec une section « Contexte » : ajouter `"personne": "<id>"` (individu du billet). La proposition
   refait alors le contrôle et **refuse le billet** s'il n'est pas conforme, rapport à l'appui ; sans `"personne"`,
   un tel billet est refusé. Même règle pour `modifier_source` qui change le texte d'un billet ou le rend public.
   Le premier média sert d'aperçu, tous forment la galerie. **Privé par défaut** : `"prive": false` seulement si
   l'utilisateur demande explicitement un billet public, lisible par les comptes Invité (Guest).
5. `arbre_proposer(operations, titre, justification)` → montrer le **résumé (visibilité du billet), le diff et
   les avertissements**. Un billet public qui nomme une personne présumée vivante ou privée (nom ou identifiant)
   est refusé : retirer le nom ou garder le billet privé. Billet privé avec une image publique : l'avertissement
   donne l'opération `modifier_media` (`champs.prive`) à ajouter si l'image doit rester invisible des Invités.
6. Demander : « Publier ce billet ? ». Appeler `arbre_appliquer(jeton)` **uniquement** après un accord explicite ;
   sinon `arbre_annuler_proposition`. Annulation ensuite : `arbre_annuler_modification`.
7. Rappeler : le billet apparaît dans la page Blog de Gramps Web (`/blog`, le plus récemment modifié en tête) ;
   il n'est pas une source de preuve et n'a pas de fiche dans les notes de recherche (vault inchangé).
