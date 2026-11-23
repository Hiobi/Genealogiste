# M7 — Contexte historique sourcé : conception

Date : 2026-11-23. Jalon GitHub n° 7. Issues : #283 à #292, #321 à #325.

## Intention

Situer un individu de l'arbre dans son contexte historique (commune, région, époque, nation) pour deux usages :
orienter la recherche de pistes, et contextualiser notes, récits et billets Gramps Web. Le contexte vient de
sources publiques **consultées** par le plugin, jamais de la mémoire du modèle.

## Buts, non-buts, échecs à éviter

- Buts : pays du lieu connu avant toute piste ; références savantes et de presse normalisées ; éléments de contexte
  bornés au lieu et à la période de vie, avec niveau de rattachement ; pistes formulées comme hypothèses
  réfutables ; contrôle automatique des textes produits.
- Non-buts : rédiger de l'histoire générale ; télécharger des corpus ; contourner une protection anti-robot ;
  couvrir les fonds d'archives étrangers (renvoi générique seulement).
- Échecs même si « ça marche » : une phrase de contexte sans référence consultée ; une causalité « contexte →
  décision de l'individu » présentée comme un fait ; un nom de personne envoyé à un service de contexte ; une
  écriture dans l'arbre issue du contexte.

## Approches considérées

1. **Outils indépendants, un par issue** (plan initial). Simple, mais « référence », « élément de contexte » et
   « identifiant résolu » seraient définis cinq fois, et la règle anti-invention ne serait vérifiable nulle part.
2. **Un outil unique `contexte`** qui fait tout. Moins de surface, mais intestable par morceaux et impossible à
   livrer par lots.
3. **Socle commun + outils spécialisés + contrôle déterministe** (retenu). Un paquet `contexte/` porte les formats,
   le registre des références consultées, la citation et les contrôles de portée ; chaque outil s'y branche ; le
   vérificateur relit les textes contre le registre. Coût : une issue de plus en tête (#321). Gain : une seule
   définition de « consulté », testable sans réseau.

## Architecture

```
arbre (faits sourcés) ──► contexte/requete.py (lieu, période, métier ; jamais de nom)
                                  │
        referentiels/sources_contexte.json (#285) ──► protocoles solr / sru / oai / rest
                                  │
   contexte_bibliographie (#286)  lieu_historique (#287)  presse_recherche (#288)
                                  │  Reference (#321) ──► registre des références consultées
                                  ▼
                        contexte_local (#289) ──► ElementContexte, contrôles de portée
                          │                 │
             pistes_contexte (#290)     rédaction (#291) ──► contexte_verifier (#324)
             (enquête, file : tâches)   (note, récit, billet)   bloquant pour un billet
```

- `normalize/` : `pays_du_lieu` (#283), appelé par toutes les pistes et par la construction des requêtes.
- Registre persistant, distinct du cache purgeable : seule définition de « référence consultée ».
- Réseau : hôtes du référentiel seulement, limites de débit, coupe-circuit, plafonds et cache existants.
- Vivants : `_garde` avant tout appel externe pour tout outil recevant une personne ou un texte libre.
- Permissions : outils réseau en collecte, `contexte_verifier` en lecture ; aucune écriture nouvelle.

## Décisions prises (à corriger si besoin)

- Style de citation par défaut : ISO 690 ; *Evidence Explained* sur option.
- Services bloqués le jour de l'enregistrement : lien seulement, pas d'analyseur.
- Géographie 1790-1943 : selon l'étude #322 ; à défaut, niveaux « inconnu » et lien de consultation.
- Niveau `atteste` : jamais attribué sans citation de l'arbre portant sur l'individu.
- Clé de démonstration Europeana : non embarquée.
- `contexte_verifier` : règles et listes fermées, pas un jugement du modèle ; limites documentées.

## Lots et critères d'arrêt

Voir la description du jalon. Chaque lot : `make test`, `make lint`, `make validate` verts ; cas témoins de #292
respectés ; bilan en commentaire d'issue. Publication (`make version`) seulement sur accord du mainteneur.

## Laissé à l'implémentation

Noms internes des fonctions, schéma de stockage du registre, découpage fin des analyseurs, liste exacte des
gabarits Wikidata, formulation des messages.
