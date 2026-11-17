# Recette des archives du 17 novembre 2026

Révision testée : `e64c926804907e1b315326686dc71b4bb5864c53`.
Exécution le 17 novembre 2026 vers 07:38 UTC, depuis l'hôte de travail disponible.
Environnement déclaré : **inconnu**. L'identité du VPS cible n'est pas établie ; ce relevé ne valide
donc aucun accès depuis ce VPS. Aucun fichier familial ni identifiant de personne n'a été utilisé.

## Commande et résultat

```bash
GENEALOGISTE_RECETTE_ENVIRONNEMENT=inconnu make test-archives ECRIRE=0
```

Résultat : **3 passed, 1 skipped in 14.07s**, code de sortie 0. Le cas ignoré correspond à une
protection détectée, pas à une réussite. Le référentiel `recettes_archives.json` n'a pas été modifié.

| Service | Ressource publique de référence | Résultat observé |
|---|---|---|
| AD25 — Doubs | `https://archives.doubs.fr/ark:/25993/7rx3d5cm9tzk/0cb0200e-150f-426e-958f-68ce8f04f9a2`, page 0 | Navigation et téléchargement d'une vue réussis. |
| AD39 — Jura | `https://archives39.fr/ark:/36595/p3rdck27zjbm/6e6facba-b9d7-4672-9c7c-ea86f058a89b`, page 0 | Navigation et téléchargement d'une vue réussis. |
| AD59 — Nord | `ark:/33518/q0km71zxrv5s`, page 25 ; tables décennales selon la référence du catalogue | Navigation et téléchargement d'une vue réussis. |
| BnF — Gallica | `https://gallica.bnf.fr/ark:/12148/bpt6k5619759j`, page 12 | Défi Cloudflare HTTP 403 pendant `archives_naviguer`, sur `https://gallica.bnf.fr/iiif/ark:/12148/bpt6k5619759j/manifest.json`. Arrêt du cas sans contournement. |

## Portée de la vérification

La recette `mcp/tests/test_archives_live.py` part d'une ressource connue : résolution ARK sans
vérification réseau, navigation sur une fenêtre de trois vues, puis téléchargement à largeur 400
et contrôle de l'existence du fichier. Les données et caches de test sont temporaires.

Elle ne valide pas la recherche d'un registre depuis une commune et une année, l'identification de
l'acte voulu, l'archivage durable avec citation, ni tous les fonds d'un service. Les cas négatifs et
la pagination complète ne font pas partie de cette exécution. Les fonds AD25, AD39 et BnF n'ont pas
été qualifiés par ce relevé. Aucun champ `verifie_le` n'a été modifié.

Les sept tests de `tests/test_recettes_archives.py` passent également : ils vérifient notamment que
les mesures locales ne remplacent pas une mesure VPS et que l'accès VPS reste inconnu sans mesure.

Le journal d'exécution brut a été conservé temporairement hors du dépôt sous
`/tmp/genealogiste-m1-recette-20261117.log` ; ce chemin local n'est pas un artefact pérenne publié.
La prochaine validation de #150 reste la même recette exécutée depuis le VPS cible identifié,
avec l'environnement `vps` et les résultats enregistrés séparément.
