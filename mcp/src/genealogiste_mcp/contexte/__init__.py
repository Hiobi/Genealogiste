"""Socle commun du contexte historique sourcé (jalon M7, #321) — interne, sans outil MCP.

- ``modeles`` : formats ``Reference`` et ``ElementContexte``, constantes (échelles, natures, rattachements) ;
- ``registre`` : registre persistant des références consultées (``App.registre_references``), seule définition
  de « référence résolue » ;
- ``citation`` : citation normée (ISO 690 par défaut, Evidence Explained ; GENEALOGISTE_CONTEXTE_STYLE_CITATION) ;
- ``portee`` : contrôles purs de lieu et de période ;
- ``requete`` : requêtes depuis l'arbre (lieux, période, métiers ; jamais l'identité de la personne).

Référence : docs/contexte-historique.md, « Formats communs ».
"""
