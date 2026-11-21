---
description: Diagnostic d'exploitation du serveur (configuration, dépendances, droits, caches, sources joignables)
argument-hint: [local]
---
Diagnostic : **$ARGUMENTS**

1. `diagnostic(reseau=...)` : `reseau=false` si l'argument est « local » (aucune requête externe), sinon `true`
   (une requête par source, tracée au journal).
2. Afficher un tableau « contrôle | état | détail | remède », les contrôles en **erreur** d'abord, puis en
   **attention**. Ne jamais afficher de secret (le diagnostic n'en renvoie pas ; ne pas en demander).
3. Avec Gramps Web configuré, présenter ensemble les contrôles de version (API, Gramps, plage testée, fonctions),
   de rôle (Editor attendu : un rôle plus faible interdit l'écriture, Owner/Admin est déconseillé) et de réglages.
   Ajouter l'accord entre la racine Sosa et la personne de référence de Gramps : en cas d'écart, donner les deux
   identifiants et la procédure manuelle du remède (Gramps Web n'a aucun point d'API pour la modifier).
   Vivants (`gramps_vivants`, `gramps_prive_a_retirer`, `gramps_regle_vivants`) : donner les comptes et les
   identifiants tels quels (jamais de nom) ; remède : `gramps_proteger_vivants` (proposition, accord explicite).
4. Présenter le contrôle des chemins de médias (introuvables, ambigus, hors des racines, nom attribué par Gramps Web) avec son
   échantillon d'identifiants, sans rien déduire d'autre ; pour la procédure, renvoyer à docs/gramps.md (chemin de base des médias).
5. Pour une source au verdict **protection** : le dire tel quel (blocage anti-robot de cette adresse) et
   proposer la consultation dans le navigateur ; aucun contournement.
6. Si la version du serveur diffère de celle du plugin, conseiller de redémarrer le serveur MCP (`/mcp`).
7. Terminer par la liste `a_corriger`, dans l'ordre, avec la commande ou la variable à modifier, et le lien `guide`
   (installation et exploitation sur un serveur).
