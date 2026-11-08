# Dépannage et questions fréquentes

Commencer par identifier le mode utilisé : plugin local en stdio, serveur Docker/HTTP ou backend Gramps.
Les contrôles ci-dessous évitent de réinstaller une autre copie ou de créer un nouvel arbre par erreur.

| Symptôme | Vérification utile |
|---|---|
| Les commandes n’apparaissent pas | `claude plugin list`, portée d’installation, nouvelle session ; utiliser `/genealogiste:…`, pas `/gen:…` |
| Le serveur MCP est déconnecté | Dans `/mcp`, lire l’erreur ; vérifier que `uv` et `git` sont accessibles au processus Claude |
| Premier lancement très long | Python/dépendances peuvent être téléchargés ; vérifier la connexion et l’erreur affichée |
| Un arbre vide apparaît à la place du vôtre | Arrêter les écritures ; vérifier `GENEALOGISTE_DATA_DIR`, `GENEALOGISTE_BACKEND`, le fichier `.env` et les volumes |
| « Répertoire de données dans le dépôt du plugin » | Choisir un dossier privé distinct ; ne pas désactiver cette protection |
| WikiTree signale un appId absent | Renseigner `GENEALOGISTE_WIKITREE_APPID`, puis redémarrer le serveur |
| Le jeton de proposition est refusé | Il peut être expiré, déjà utilisé ou associé à un arbre modifié ; demander une nouvelle proposition et relire le diff |
| Une recherche concernant un vivant est bloquée | C’est une garde de confidentialité ; corriger une donnée erronée avec justification, sans chercher à contourner le contrôle |
| Un site bloque la requête | Consulter la page vous-même selon ses conditions ; conserver URL et citation, puis fournir le contenu autorisé |
| HTTP 401 | Jeton absent ou différent entre serveur et client ; vérifier l’en-tête Bearer sans le publier |
| HTTP 421 | Host/Origin rejeté par le transport ; vérifier l’adresse locale et la configuration du proxy, pas seulement le token |
| HTTP 413 | Message HTTP supérieur à 4 Mio ; réduire le texte envoyé ou utiliser les outils de fichier adaptés |
| Gramps refuse une écriture | Vérifier rôle du compte, arbre sélectionné et conflit ; suivre le [guide Gramps](../docs/gramps-web.md) |
| Un envoi a un « résultat indéterminé » | Contrôler son résultat côté service avant de recommencer |
| Une pièce ne s’affiche pas dans Obsidian | Vérifier le chemin et le nom de fichier ; le rendu natif des cas avec crochets reste suivi dans [#75](https://github.com/Hiobi/Genealogiste/issues/75) |

## Peut-on utiliser Codex ?

Le portage complet n’est pas livré. Le serveur MCP peut être étudié séparément, mais les hooks Claude
ne constituent pas la politique d’approbation d’un autre client. Suivre [#80](https://github.com/Hiobi/Genealogiste/issues/80)
plutôt que de présumer les mêmes garanties sur une surface non validée.

## Faut-il des comptes partout ?

Non. Le mode fichier et la consultation d’un arbre local fonctionnent sans compte de source.
WikiTree demande un identifiant d’application ; certaines opérations ou certains sites ont leurs propres
conditions. Gramps Web n’est nécessaire que pour ce backend. Voir la [configuration](Configuration.md).

## Demander de l’aide sans exposer sa famille

Ouvrir une [issue](https://github.com/Hiobi/Genealogiste/issues/new) avec la version, le mode, la commande,
le résultat attendu et un exemple fictif minimal. Retirer noms réels, dates familiales, jetons, chemins
personnels et liens privés des messages et captures. Ne pas joindre d’export de production.
Une vulnérabilité se signale [en privé](https://github.com/Hiobi/Genealogiste/security/advisories/new).
