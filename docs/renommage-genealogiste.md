# Migration de Sosa vers Genealogiste

Depuis 0.16.0, le projet s’appelle **Genealogiste — assistant de recherche familiale**.
Le dépôt devient `Hiobi/Genealogiste` et la marketplace `genealogiste`.
L’installation complète est désormais `genealogiste@genealogiste`.

Le plugin et ses commandes `/genealogiste:…`, le serveur MCP `genealogiste`, le package
`genealogiste-mcp` / `genealogiste_mcp`, les variables `GENEALOGISTE_*` et les chemins privés restent
compatibles. Le nom du projet Compose `genealogiste` et ses volumes sont conservés.
Les hooks d’approbation continuent de reconnaître le même serveur MCP.

## Installation existante avec la marketplace sosa

Il s’agit d’un changement d’identité de marketplace, pas d’une simple mise à jour du plugin.
La redirection GitHub de l’ancienne URL ne remplace pas cette migration dans Claude Code.

1. Arrêter les sessions qui utilisent le plugin. Sauvegarder les données privées, la configuration et
   les éventuelles options du plugin. Repérer sa portée d’installation avec `claude plugin list --json`
   et les marketplaces déclarées avec `claude plugin marketplace list`.
2. Désinstaller l’ancien identifiant **en préservant ses données persistantes**. Exemple pour la portée
   utilisateur ; remplacer `user` par `project` ou `local` si nécessaire, depuis le projet concerné :

   ```bash
   claude plugin uninstall genealogiste@sosa --scope user --keep-data
   claude plugin marketplace remove sosa --scope user
   claude plugin marketplace add Hiobi/Genealogiste --scope user
   claude plugin install genealogiste@genealogiste --scope user
   ```

   Répéter pour les portées où l’ancienne installation est présente. La suppression de la marketplace
   retire également son catalogue pour les autres plugins : vérifier auparavant qu’aucun autre plugin
   installé n’en dépend. Aucune commande de suppression des données familiales n’est nécessaire.
3. Mettre à jour les déclarations partagées ou gérées de marketplace, si présentes, et la clé
   `genealogiste@sosa` dans `enabledPlugins` vers `genealogiste@genealogiste`. Une configuration gérée
   doit être mise à jour par son administrateur. Reprendre les options sauvegardées si elles étaient
   associées à l’ancien identifiant ; les données persistantes conservées ne sont pas transférées
   automatiquement dans un nouvel espace de plugin.
4. Ouvrir une nouvelle session. Vérifier qu’une seule installation et un seul serveur MCP sont actifs,
   que `/genealogiste:…` est disponible et que `arbre_info` retrouve le backend et les effectifs attendus.
   Avant toute écriture, vérifier sur des données fictives qu’une proposition présente son diff et que
   l’approbation est toujours demandée pour l’application.

Les paramètres privés d’environnement et les volumes existants doivent pointer vers les mêmes données.
Pour un serveur HTTP configuré séparément, garder son identifiant MCP `genealogiste` et son jeton privé.
Ne pas copier d’arbre ou de secrets dans le checkout du plugin pendant cette migration.

## Checkout Git, Docker et Portainer

Dans le **dépôt du code du plugin uniquement**, actualiser le remote :

```bash
git remote set-url origin https://github.com/Hiobi/Genealogiste.git
```

Un dossier local peut garder son ancien nom `Sosa` ; aucun déplacement n’est imposé.
Pour Portainer, actualiser l’URL Git du dépôt de code sans recréer la stack ni ses volumes.
Conserver le nom du projet Compose et les chemins de montage privés. Ne pas lancer `down -v`.
Le dépôt Git des données familiales doit rester distinct et privé : le serveur refuse les URL du
dépôt public sous ses deux noms, `Hiobi/Sosa` et `Hiobi/Genealogiste`.

## Compatibilité des données historiques

La numérotation **Sosa-Stradonitz** reste un concept généalogique, avec ses champs et paramètres.
Les marqueurs `Sosa:auto`, `Sosa-*` dans Gramps et `<!-- sosa:debut … -->` / `<!-- sosa:fin -->`
dans les notes restent reconnus et conservés. Ce sont des identifiants de données persistées ;
les remplacer provoquerait des doublons ou une perte de reconnaissance des sections gérées.
Les anciens exports et liens de documentation ne sont pas réécrits. Les nouveaux exports utilisent
la nouvelle URL de documentation GEDCOM.

## Références des commandes

La syntaxe et les portées ci-dessus ont été vérifiées dans l’aide locale de Claude Code
(`plugin install`, `uninstall`, `marketplace add`, `marketplace remove`, version 2.1.319).
La conservation des données persistantes utilise explicitement `--keep-data`.

Le passage de `genealogiste@sosa` en 0.15.1 à `genealogiste@genealogiste` en 0.16.0 a été exécuté
avec le CLI dans une configuration temporaire (`CLAUDE_CONFIG_DIR`), à partir de copies locales
des deux distributions. Une seule installation finale, activée, expose le serveur MCP `genealogiste`.
Ce contrôle ne modifie aucune installation personnelle ni donnée familiale ; il ne simule pas
une configuration administrée ou toutes les versions anciennes de Claude Code.
