---
name: droit-communicabilite
description: Droit des archives et protection des données en généalogie — délais de communicabilité (Code du patrimoine, art. L213-2 : 75 ans, 100 ans, 120 ans), RGPD et personnes vivantes, publication d'un arbre, demande d'acte récent, secret médical, registres matricules, minutes notariales. À utiliser pour « puis-je consulter », « est-ce communicable », « puis-je publier mon arbre », « acte de moins de 75 ans », personnes vivantes, RGPD, CNIL.
---

# Communicabilité et protection des personnes

Outil : `communicabilite(document, date_document, date_naissance, date_deces)` ; statut vivant :
`arbre_vivant`.

## Délais (Code du patrimoine, art. L213-2) — à vérifier auprès du service

| Document | Délai |
|---|---|
| Actes de décès | immédiat |
| Actes de naissance et de mariage | 75 ans après la clôture du registre |
| Minutes et répertoires notariaux | 75 ans |
| Recensements (listes nominatives) | 75 ans (secret statistique) |
| Dossiers judiciaires | 75 ans ; 100 ans si mineurs concernés |
| Documents touchant la vie privée | 50 ans |
| Secret médical (ex. registres matricules) | 25 ans après le décès, ou 120 ans après la naissance si décès inconnu |
| Cadastre | immédiat |

Avant l'échéance : copie intégrale d'un acte de naissance/mariage réservée à la personne, ses ascendants,
descendants, conjoint, représentant légal ; sinon extrait sans filiation. Dérogation possible (art. L213-3).

## Personnes vivantes (RGPD)

- Présomption de vie : pas de décès sourcé et naissance estimée il y a moins de 100 ans (estimation depuis
  naissance, mariage − 25, premier enfant − 25, parent + 25). Sans aucune date : présumée vivante.
- Ne jamais envoyer de données d'une personne vivante à un service externe (les outils refusent avec
  `personne=<id>`). Exports et récits : vivants masqués par défaut.
- Publication d'un arbre en ligne : uniquement les défunts, ou consentement des vivants (CNIL).
- Marquer une personne décédée dont on ignore la date : `marquer_vivant` (vivant = "N") avec justification.

## Sites et CGU
Consultation en lecture seule, dans la session de l'utilisateur ; pas d'extraction massive ni de
contournement d'authentification (Geneanet, AD, Filae…). Citer la source et respecter les licences
de réutilisation des AD.
