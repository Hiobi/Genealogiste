# Exploiter Sosa et partager le plugin

Le code public se partage ; les données familiales restent dans un espace privé. Cette version vise
un usage personnel ou familial de confiance, avec une instance et des données distinctes par foyer.
Un client MCP autorisé peut lire l’arbre et appeler les outils d’écriture : le jeton de proposition
n’est pas une preuve de consentement humain. Utiliser les hooks Claude et une politique d’approbation
du client. Le serveur HTTP n’est pas un service public multi-utilisateur.

## Installation reproductible

Installer une version publiée du plugin, puis redémarrer le serveur après une mise à jour. Le lancement
stdio respecte `mcp/uv.lock`. Pour Docker, construire `mcp/Dockerfile` ; l’image de base et Gramps Web
sont épinglés par empreinte. `GRAMPSWEB_IMAGE` remplace l’image complète pour une mise à jour validée.
Garder les dépendances à jour avec Dependabot et examiner les résultats des scans hebdomadaires.

## Données et secrets

- Conserver `GENEALOGISTE_DATA_DIR`, caches, médias, notes et sauvegardes hors du dépôt du plugin.
  Le serveur refuse d’initialiser un arbre dans un checkout du plugin.
- Placer les identifiants dans le `.env` privé des données ou dans l’environnement du service, jamais
  dans une issue, un journal de CI ou un fichier partagé. Utiliser `chmod 600` pour le `.env` et
  `chmod 700` pour les dossiers privés existants. Le point d’entrée applique un umask `077` aux créations.
- Les comptes Gramps sont dédiés, avec le rôle minimal nécessaire. L’ancien exporteur FamilySearch
  est désactivé ; supprimer ses identifiants de la configuration et de tout ancien environnement.
- Le miroir Git éventuel contient des données personnelles, même après masquage de l’arbre actuel :
  il doit rester privé. Partager uniquement un export masqué vérifié, jamais l’historique des données.
- Ne pas déposer de données familiales dans les fixtures : elles sont synthétiques et publiques.

## Docker et réseau

Les deux compositions de production exigent `MCP_TOKEN` par défaut. Générer un jeton avec
`openssl rand -hex 32`, le renseigner dans le `.env` privé et le transmettre aux clients en en-tête
`Authorization: Bearer`. Les ports restent publiés sur `127.0.0.1`. Les membres du réseau Docker peuvent
joindre le conteneur : conserver le jeton même lorsque le port hôte est local.

Pour un accès distant, utiliser un tunnel privé ou un proxy TLS authentifié. Ne jamais exposer directement
Redis ni le MCP sans protection. Le token est partagé et donne accès à tous les outils ; aucun cloisonnement
par utilisateur. `MCP_SANS_AUTH=1` est une dérogation réservée à un environnement déjà protégé.
La politique de sortie réseau n’épingle pas les réponses DNS : pour traiter des URL non fiables dans un
environnement sensible, compléter par un filtrage réseau bloquant les réseaux internes et les métadonnées cloud.

Le MCP s’exécute avec l’UID/GID `10001:10001`, sans privilèges supplémentaires. Les volumes nommés neufs
sont prêts à l’emploi. Pour un dossier monté depuis l’hôte ou un ancien volume, sauvegarder puis donner
à cet UID uniquement les droits nécessaires ; ne pas utiliser `chmod 777` ni contourner les contrôles Git.
Le volume de données par défaut est désormais `genealogiste_data`, au lieu de `./data`.
Pour une installation existante, arrêter le service, sauvegarder et copier les données vers le volume
privé avant de redémarrer. Aucune migration ni suppression automatique n’est effectuée.

## Sauvegarde et restauration

Arrêter les écritures pendant une sauvegarde cohérente. Sauvegarder le répertoire des données complet
(y compris `.git`), les médias/notes externes, les volumes Gramps, et les secrets nécessaires à la
restauration. Chiffrer les sauvegardes et conserver une copie indépendante à accès restreint.

Avant une mise à jour, vérifier une restauration dans une instance isolée, sans dépôt Git distant ni
identifiants d’API externes : mêmes effectifs et sources, médias lisibles, historique Git présent,
export masqué sans données de vivants, proposition d’une modification fictive puis application unique.
Ne jamais restaurer en écrasant l’unique copie de production.

## Validation avant partage

`make test`, `make lint` et `python3 scripts/verifier_distribution.py` doivent passer. Le workflow
Sécurité vérifie les secrets et les dépendances ; le workflow d’intégration Gramps utilise exclusivement
un serveur jetable. Ne pas utiliser de compte ni d’export réel pour valider une PR.

Une absence de détection n’est pas une garantie absolue d’absence de données sensibles. Si une fuite est
identifiée, révoquer les secrets, restreindre l’accès si nécessaire puis suivre [SECURITY.md](../SECURITY.md).
