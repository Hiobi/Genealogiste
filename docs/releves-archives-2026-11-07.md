# Relevé des accès aux archives — 7 novembre 2026

Lot de données pour #25, version 0.14.4. Lecture des pages officielles dans le navigateur, sans compte,
sans téléchargement de registres, sans franchissement de contrôle anti-robots ni désactivation de TLS.
Ce relevé automatisé ne renseigne pas `verifie_le`, réservé à une vérification humaine.

## Valeurs ajoutées et sources

| Code | Identité et accès observés | Référence officielle |
|---|---|---|
| AD06 | Identité confirmée sur l’accueil ; site canonique après redirection : `https://archives06.fr`. Le lien Rechercher présente ensuite un contrôle anti-robots : pas de `visionneuse` ajoutée. | [Accueil des Alpes-Maritimes](https://archives06.fr/) |
| AD08 | Accueil identifié ; accès aux registres et avertissement sur les lacunes, sans déduire d’année du seuil glissant de 100 ans. | [Accueil](https://archives.cd08.fr/), [registres](https://archives.cd08.fr/archives-numerisees/sources-genealogiques/registres-paroissiaux-et-detat-civil) |
| AD13 | Formulaire d’état civil identifié ; couverture différente pour Marseille et les autres communes, tables incomplètes après 1902. | [État civil](https://www.archives13.fr/archive/recherche/etatcivil/) |
| AD24 | Page Généalogie donnant accès au choix des registres et des tables décennales. | [Généalogie](https://archives.dordogne.fr/archives-numerisees/genealogie) |
| AD26 | Portail puis formulaire État civil identifiés ; présentation jusqu’en 1924 avec renvoi de Romans-sur-Isère vers le site municipal. | [Portail](https://archives.ladrome.fr/page/archives-numerisees), [formulaire](https://archives.ladrome.fr/search/form/f6e7c1a1-9bda-40bc-a68b-13ed003eb0e5) |
| AD50 | Accueil et accès aux registres identifiés ; présentation des collections existantes jusqu’en 1892 et pertes signalées. | [Accueil](https://www.archives-manche.fr/), [registres](https://www.archives-manche.fr/recherche/registres-paroissiaux-et-detat-civil) |

Les cinq sites auparavant candidats (06, 08, 13, 26, 50) sont rétablis. Cinq points d’accès aux fonds sont
ajoutés (08, 13, 24, 26, 50) ; le champ historique `visionneuse` peut désigner la page de recherche ou de
sélection qui conduit au lecteur d’images, sans promettre qu’un registre particulier a été ouvert.

Les champs `references` et `releve_le` rendent la provenance et la date du relevé accessibles dans les
fiches du service. Le NAAN importé n’a pas été revérifié sur un lien ARK et reste inchangé. Aucun accès
IIIF ni service de demande à distance n’a été supposé.

## Informations laissées inconnues

Aucune plage `en_ligne` ajoutée : un intervalle départemental unique ne permet pas d’exprimer les
exceptions et lacunes observées. Les indications des services restent dans les notes sourcées ;
`en_ligne_pour_la_demande` continue donc de répondre `null` pour ces six entrées. L’issue #93 décrit
l’évolution nécessaire avant de convertir ces indications en réponses calculées.

L’Aude a renvoyé un rejet à l’outil de lecture Web puis une page sans contenu exploitable dans le
navigateur : son adresse reste candidate dans les notes. La Corse et Mayotte ne sont pas traitées dans
ce lot. #25 reste ouverte pour ces sites, les autres départements, les visionneuses/IIIF, les demandes
à distance et les archives communales/diocésaines.
