# Migration du serveur vers MCP 2

La version 0.17.0 utilise le SDK Python `mcp` 2.3.0, verrouillé dans `mcp/uv.lock`.
La dépendance requiert désormais `mcp[cli]>=2.3,<3` : conserver une borne minimale en 1.x permettrait
une installation incompatible avec le serveur migré. Python 3.11 reste pris en charge.

## Adaptations

- `FastMCP` est remplacé par `MCPServer`, depuis `mcp.server.mcpserver`. Le nom du serveur et ses
  instructions sont conservés ; les noms, paramètres et décisions des hooks des outils restent identiques.
- Le SDK 2 exécute les fonctions synchrones dans des workers concurrents. Le point d’entrée
  `ServeurMCP.call_tool` les sérialise avec un verrou asynchrone avant leur exécution : l’initialisation
  de l’App, ses limiteurs et l’état partagé du backend gardent le fonctionnement séquentiel du SDK 1.
- Le démarrage HTTP ne modifie plus `mcp.settings.host` et `port`, supprimés par le SDK. L’écoute est
  toujours configurée sur uvicorn par `--host` et `--port`. Les fabriques ASGI gardent leurs valeurs
  locales par défaut et leur protection contre les en-têtes Host/Origin externes, comme avant la migration.
  Le jeton `MCP_TOKEN` est toujours vérifié par le middleware du plugin avant l’accès au transport.
- Le client du contrôle Docker utilise `httpx2`, requis par le transport MCP 2, et lit `is_error`.
  Le transport client renvoie désormais deux flux, sans ancien rappel d’identifiant de session.
  `httpx` reste le client des sources généalogiques : leurs limites de débit, politiques réseau et
  règles de confidentialité ne changent pas.

Les transports stdio, Streamable HTTP (`/mcp`) et SSE (`/sse`) restent disponibles.
Le client de contrôle vérifie l’initialisation historique (`initialize`) et la négociation moderne
(`server/discover`) pour couvrir les deux générations de clients. Le catalogue reçu sur stdio est comparé au catalogue des hooks.

## Effets du SDK à connaître

MCP 2 applique une limite de 4 Mio aux corps de requêtes HTTP. Un corps trop volumineux est refusé
avec HTTP 413 ; cela concerne les messages envoyés au serveur, pas la taille d’un fichier local lu
par un outil. Aucun agrandissement de cette limite n’est ajouté par le plugin.

Le SDK ajoute l’API OpenTelemetry et sa propagation de traces. Sans SDK/exporteur OpenTelemetry
configuré, les traces sont inactives. Le plugin ne configure aucun exporteur ; une application hôte
qui en configure un doit examiner les règles de collecte de sa propre infrastructure.

## Validation

Un test de deux appels simultanés au serveur vérifie qu’un seul outil synchrone entre à la fois.
Les tests de transport vérifient le démarrage des deux modes HTTP sur écoute locale et toutes
interfaces, le refus sans jeton ou avec un mauvais jeton, le rejet d’un Host externe, et une
initialisation HTTP autorisée. Un serveur stdio lancé en sous-processus avec des données temporaires
vérifie l’identité, les instructions, le catalogue et une lecture d’arbre vide.
Le contrôle Docker complète ces tests avec une vraie connexion MCP et les permissions de fichiers.
Les données et jetons utilisés pour ces contrôles sont fictifs.

Source de migration : [guide officiel du SDK Python, version 2.3.0](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/docs/migration.md).
