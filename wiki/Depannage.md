# Dépannage et questions fréquentes

Commencer par identifier le mode utilisé : plugin local en stdio, serveur Docker/HTTP ou backend Gramps.
Les contrôles ci-dessous évitent de réinstaller une autre copie ou de créer un nouvel arbre par erreur.

| Symptôme | Vérification utile |
|---|---|
| Les commandes n’apparaissent pas | `claude plugin list`, portée d’installation, nouvelle session ; utiliser `/genealogiste:…`, pas `/gen:…` |
| Le serveur MCP est déconnecté | Dans `/mcp`, lire l’erreur ; vérifier que `uv` et `git` sont accessibles au processus Claude ; `/genealogiste:diagnostic` donne contrôle, état et remède |
| Deux serveurs `genealogiste` dans `/mcp`, dont un en échec (`CONNECTION_CLOSED`, `No such file or directory`) | Jusqu’à 0.21, le dépôt du plugin ouvert comme dossier de travail déclarait aussi le serveur en portée projet ; travailler depuis un dossier privé distinct, ou mettre à jour le checkout (la déclaration est désormais dans le manifeste du plugin) |
| Outils manquants ou avertissement « reconnecter le serveur MCP » | La session utilise encore le serveur d’une version antérieure ; reconnecter le serveur (voir [Mises à jour](Mises-a-jour.md)) |
| Premier lancement très long | Python/dépendances peuvent être téléchargés ; vérifier la connexion et l’erreur affichée |
| Un arbre vide apparaît à la place du vôtre | Arrêter les écritures ; vérifier `GENEALOGISTE_DATA_DIR`, `GENEALOGISTE_BACKEND`, le fichier `.env` et les volumes |
| « Répertoire de données dans le dépôt du plugin » | Choisir un dossier privé distinct ; ne pas désactiver cette protection |
| WikiTree signale un appId absent | Renseigner `GENEALOGISTE_WIKITREE_APPID`, puis redémarrer le serveur |
| WikiTree répond 403 « AI-scraping bots » | Filtre de WikiTree contre les robots d’IA, pas un problème d’identifiants : le plugin ne le contourne pas ; demander une autorisation à WikiTree, ou consulter le site vous-même et utiliser `source_collee` ([détails](../docs/securite.md#identification--user-agent-et-contact-facultatif)) |
| Le jeton de proposition est refusé | Il peut être expiré, déjà utilisé ou associé à un arbre modifié ; demander une nouvelle proposition et relire le diff |
| Une recherche concernant un vivant est bloquée | C’est une garde de confidentialité ; corriger une donnée erronée avec justification, sans chercher à contourner le contrôle |
| Un site bloque la requête (`bloque_antirobot`, `coupe_circuit`, `exclusion`) | Défi anti-robot : le service est mis en pause, puis exclu 7 jours si le défi persiste ; aucun contournement. Consulter la page vous-même selon ses conditions ; conserver URL et citation, puis fournir le contenu autorisé (`source_collee`, ou l’image avec `media_enregistrer`) ; voir les [protections anti-robot](../docs/archives.md) |
| Notes : « fichier préexistant non reconnu pour ce patronyme » | Vault sous macOS ou synchronisé par Nextcloud (noms de fichiers en NFD) : corrigé en 0.26.1 ; mettre à jour le plugin et reconnecter le serveur |
| HTTP 401 | Jeton absent ou différent entre serveur et client ; vérifier l’en-tête Bearer sans le publier |
| HTTP 421 | Host/Origin rejeté par le transport ; vérifier l’adresse locale et la configuration du proxy, pas seulement le token |
| HTTP 413 | Message HTTP supérieur à 4 Mio ; réduire le texte envoyé ou utiliser les outils de fichier adaptés |
| Gramps refuse une écriture | `/genealogiste:diagnostic` affiche le rôle du compte (Editor requis) et la version de l’API (3.13.0 au moins) ; vérifier aussi l’arbre sélectionné et les conflits ; suivre le [guide Gramps](../docs/gramps-web.md) |
| Un envoi a un « résultat indéterminé » | Contrôler son résultat côté service avant de recommencer |
| Une pièce ne s’affiche pas dans Obsidian | Vérifier le chemin et le nom de fichier ; les fiches générées utilisent des liens Markdown encodés, valides même avec des crochets dans le nom ([#75](https://github.com/Hiobi/Genealogiste/issues/75)) |
| Une personne vivante apparaît comme décédée, ou l’inverse, après une fusion faite dans Gramps | Marqueurs `Genealogiste-Vivant` en double : le plugin retient la valeur la plus protectrice et le signale ; `arbre_coherence` ou `/genealogiste:diagnostic vivants`, puis proposition `dedoublonner_marqueurs` ([détails](../docs/gramps-web.md#marqueurs-en-double-après-une-fusion-faite-hors-du-plugin-311)) |

## Peut-on utiliser Codex ?

Oui, en local : le paquet fournit les skills et un profil séparé active le serveur MCP avec l’approbation
native de chaque outil. Les hooks Claude ne s’appliquent pas à Codex. Suivre le [guide Codex](../docs/adaptation-codex.md)
et ne pas présumer les mêmes garanties sur une autre surface.

## Faut-il des comptes partout ?

Non. Le mode fichier et la consultation d’un arbre local fonctionnent sans compte de source.
WikiTree demande un identifiant d’application ; certaines opérations ou certains sites ont leurs propres
conditions. Gramps Web n’est nécessaire que pour ce backend. Voir la [configuration](Configuration.md).

## Demander de l’aide sans exposer sa famille

Ouvrir une [issue](https://github.com/Hiobi/Genealogiste/issues/new) avec la version, le mode, la commande,
le résultat attendu et un exemple fictif minimal. Retirer noms réels, dates familiales, jetons, chemins
personnels et liens privés des messages et captures. Ne pas joindre d’export de production.
Une vulnérabilité se signale [en privé](https://github.com/Hiobi/Genealogiste/security/advisories/new).
