# Contexte historique sourcé

Référence du jalon M7 : situer un individu dans son contexte historique sans inventer l'histoire. Conception :
`docs/superpowers/specs/2026-11-23-m7-contexte-design.md`.

## Méthode

Le contexte est traité avec la même rigueur que les faits de l'arbre (Genealogical Proof Standard, skill
`methodologie-gps`, § « Contexte historique »). Il situe un individu ; il n'explique ni ne prouve rien sur lui.

1. **Hiérarchie des sources de contexte** : source primaire contemporaine (presse, imprimé administratif,
   statistique d'époque) > historiographie savante évaluée par les pairs (article, thèse, monographie
   universitaire) > synthèse ou vulgarisation sourcée > tertiaire (encyclopédies, Wikipédia). Wikidata est un
   **index**, jamais une source.
2. **Critique externe et interne** : auteur, date, intention, échelle d'observation, sources de l'auteur.
3. **Échelle et portée** : une tendance nationale ou régionale ne prouve rien pour un individu ; chaque
   élément précise la population et le territoire concernés et son niveau de rattachement à l'individu.
   Aucun élément n'est « attesté pour l'individu » sans citation de l'arbre qui le concerne.
4. **Anachronisme** : contexte borné au lieu et à la période de vie, vocabulaire et découpages de l'époque,
   pays lu sur le lieu **à sa date** (homonymes de communes à l'étranger). Un élément hors période ou hors
   pays est écarté.
5. **Causalité** : le contexte n'explique pas une décision individuelle sans source individuelle. Sans elle,
   le rapprochement est une **hypothèse** au conditionnel, jamais un fait.
6. **Réfutabilité** : toute hypothèse contextuelle nomme la source qui la trancherait.
7. **Citation normée** : auteur, titre, publication, date, page, identifiant pérenne (DOI, ARK, HAL, PPN).
   ISO 690 par défaut ; *Evidence Explained* pour les sources généalogiques.
8. **Traçabilité** : chaque recherche de contexte est journalisée, y compris négative. Rien de personnel ne
   part vers un service externe : le contexte se cherche par lieu, période et métier.
9. **Rien trouvé** : sans source, la sortie est « contexte non documenté », pas un texte générique.

Cas témoins (données de test, sans fait historique ni personne vivante) : `mcp/tests/fixtures/contexte/`
(un `.ged` et un `.attendus.json` par cas : mineur du Pas-de-Calais parti aux États-Unis, laboureur d'Ancien
Régime, soldat de 1914-1918, lieu non documenté), chargés par la fixture pytest `app_contexte`. Chaque fichier
d'attendus donne la personne, ses bornes de vie, ses lieux avec pays, son métier, et ce qu'aucune sortie de
contexte ne doit contenir (causalités non sourcées, éléments hors période ou hors lieu, anachronismes, phrases
génériques).


## Pays du lieu

<!-- #283 -->

## Formats communs

<!-- #321 -->

## Services de contexte

<!-- #285 -->

## Outils

<!-- #286 à #290 -->

## Rédaction et contrôle

<!-- #291, #324 -->
