---
name: organisation-pieces
description: Organiser un dossier de pièces généalogiques existant — inventaire, classement par type et patronyme, doublons, renommage selon la convention « NOM Prénom -- COMMUNE - DÉPÔT - TYPE [années] - cote - p.vue n.acte », triage des pièces non identifiables, médias dans le vault. À utiliser pour /organise, « range mes scans », « trie ce dossier », « renomme ces actes », « comment nommer mes fichiers », import d'un dossier de pièces hétérogène.
---

# Organisation des pièces

Référence complète : `docs/pieces.md` du plugin.

## Règles impératives
- **Proposer, puis appliquer.** `pieces_proposer` ne touche à rien. `pieces_appliquer(jeton)` ne s'utilise
  qu'après l'accord explicite de l'utilisateur sur le plan présenté (résumé par dossier, doublons, `_À trier/`).
- **Jamais de suppression**, ni par les outils, ni à la main (pas de `rm`). Les doublons vont dans
  `archives/Doublons/`. Ne jamais déplacer de fichier hors des outils : seuls leur journal TSV et leur contrôle
  d'empreintes garantissent la réversibilité.
- Ne pas toucher `personnes/`, `familles/` et `sources/` (notes générées), ni les dossiers cachés. Les
  outils les excluent d'office.
- Un nom de fichier ne vaut pas une source. Un type ou un patronyme déduit du nom reste une hypothèse de
  classement : en cas de doute, laisser la pièce dans `_À trier/`.
- Personnes présumées vivantes : les noms de fichiers restent locaux, mais aucune recherche externe ni
  aucun envoi ne doit les concerner (`arbre_vivant`).

## Convention
`NOM Prénom[ + NOM Prénom] -- COMMUNE - DÉPÔT - TYPE [AAAA-AAAA] - cote - p.vue n.acte.ext`.
Produire les noms avec `piece_nommer`, jamais à la main : l'outil garantit la compatibilité Windows et
Nextcloud et reprend depuis l'arbre les noms (`I12`), le dépôt et la cote (`S3`).
Codes de type : N, B, M, D, S, NMD, BMS, TD, RM (matricule), ANMT (mineur), REC (recensement), SIGN,
CAPTURE (arbre en ligne), PHOTO, TOMBE, LIEU.

## Déroulé
1. `pieces_inventaire` → 2. `pieces_proposer` → accord → `pieces_appliquer` → 3. triage de `_À trier/`
(agent `trieur`) → `pieces_proposer(renommages=…)` → accord → `pieces_appliquer`.
Gros dossiers : présenter le résumé, jamais la liste complète. Le plan complet est dans le fichier TSV.

## Rattacher une pièce à l'arbre
Une fois la pièce rangée et nommée, l'ajouter comme média d'une citation via `/genealogiste:ajoute`
(opération `ajouter_media`, chemin du fichier). Un fichier référencé par l'arbre ne sera plus déplacé par
les organisations suivantes.

## Vault Obsidian
Pour ranger directement les nouvelles pièces dans le vault : `GENEALOGISTE_MEDIA_DIR=<vault>/documents`
(et au besoin `GENEALOGISTE_RAPPORTS_DIR`, `GENEALOGISTE_EXPORTS_DIR`). Ensuite,
`media_enregistrer(chemin, nom, classer=true)` range selon la convention.
