# Confidentialité et approbations

Votre dossier de données contient des informations familiales, des journaux et parfois des secrets.
Le dépôt GitHub public ne doit contenir que le code, la documentation et les exemples fictifs.

## Séparer code et données

Garder l’arbre, les actes, les notes, les exports, les caches et les sauvegardes hors du checkout du plugin.
Le serveur refuse d’initialiser un arbre dans ce checkout et refuse son dépôt public comme destination
Git des données. Un éventuel dépôt Git distant de l’arbre doit rester privé.

Les anciennes versions d’un arbre et les journaux peuvent contenir des informations retirées de la version
actuelle. Un export masqué ne nettoie pas cet historique : ne pas publier le dépôt Git des données.
Les notes Obsidian peuvent aussi contenir du texte manuel ; il faut le relire indépendamment des sections générées.

## Comprendre les propositions

Pour une édition d’arbre : demander une proposition, lire le diff et les alertes, puis approuver ou refuser.
Le jeton d’application expire après une heure, n’est utilisable qu’une fois et est refusé si l’arbre a changé.
Un jeton démontre qu’une proposition existe ; **il ne démontre pas qu’un humain a donné son accord**.

Dans Claude Code, les hooks ajoutent la demande de confirmation sur les outils concernés.
Avec un autre client MCP, configurer sa propre politique d’approbation. Les écritures auxiliaires
(journal, notes, synchronisation) ne suivent pas toutes le circuit de proposition d’arbre ; le
[catalogue des décisions](../docs/securite.md#confirmations-hooks) précise les cas.
Ne pas exposer le serveur HTTP comme un service public multi-utilisateur.

## Personnes présumées vivantes

Les gardes bloquent certaines recherches externes sur une personne présumée vivante ou privée et
les exports appliquent un masquage par défaut. La présomption prend en compte l’incertitude des dates,
pas seulement une date de naissance exacte. Une identité ou un fait mal renseigné peut fausser une
analyse : vérifier les données avant de décider de ce qui peut être partagé.

Les notes générées utilisent `masquer` par défaut. Le mode `complet` est pour un espace strictement privé.
Revoir le [guide des notes](../docs/notes.md), notamment le traitement des fichiers déjà créés et des médias
confidentiels connus ; les fichiers manuels ne sont pas nettoyés automatiquement.

## Secrets et serveur HTTP

Placer identifiants et jetons dans l’environnement ou dans un `.env` privé. Ne pas les mettre dans
un prompt partagé, une capture, un commit ou une issue. Pour Docker, `MCP_TOKEN` est requis par défaut ;
les clients utilisent le même jeton en en-tête `Authorization: Bearer`.
Le token permet l’accès aux outils ; il n’établit pas des droits distincts pour plusieurs familles.

Pour l’accès distant, utiliser les mesures du [guide d’exploitation](../docs/production.md).
Le contrôle des sources réseau et ses limites sont décrits dans la [sécurité technique](../docs/securite.md).

## Signaler un problème

Une erreur fonctionnelle se décrit dans une [issue](https://github.com/Hiobi/Genealogiste/issues), avec
un exemple fictif. Une faille ou une fuite potentielle se signale en
[privé](https://github.com/Hiobi/Genealogiste/security/advisories/new), sans publier les données exposées.
La [politique de sécurité](../SECURITY.md) détaille le canal à utiliser.
