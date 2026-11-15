# Mettre à jour Genealogiste

Lire les [notes de version](https://github.com/Hiobi/Genealogiste/releases) et faire une
[sauvegarde](Sauvegardes.md) avant une migration ou une modification de votre hébergement.

## Plugin installé depuis la marketplace

Dans un terminal :

```bash
claude plugin marketplace update genealogiste
claude plugin update genealogiste@genealogiste
```

**Reconnecter le serveur MCP** : une session déjà ouverte garde le serveur de l’ancienne version (outils
manquants, commandes qui citent des outils absents). Ouvrir une nouvelle session, ou `/mcp` puis reconnecter
`genealogiste`, dans **chaque** session ouverte. Vérifier ensuite `arbre_info` : `version_serveur` doit être
celle du plugin, et un avertissement « reconnecter le serveur MCP » signale un écart (aussi dans
`/genealogiste:diagnostic`). Les chemins et le backend doivent être ceux de votre installation précédente.

**Anciennes versions** : chaque version reste dans le cache des plugins avec son environnement Python
(environ 100 Mo), sous `~/.claude/plugins/cache/genealogiste/genealogiste/<version>/`. Une fois toutes les
sessions reconnectées, et aucun processus `genealogiste-mcp` d’une ancienne version encore actif
(`pgrep -af genealogiste-mcp`), les dossiers des versions antérieures peuvent être supprimés. Ne jamais
supprimer le dossier de la version en cours ni le répertoire de données.
Une ancienne installation `genealogiste@sosa` suit d’abord le [guide de migration](../docs/renommage-genealogiste.md) :
la redirection GitHub de l’ancien dépôt ne change pas automatiquement le nom de marketplace enregistré.

## Chargement local du code

Mettre à jour le checkout du **plugin**, puis relancer la session qui utilise `--plugin-dir`.
Ne pas exécuter cette opération dans le dépôt Git privé de l’arbre en pensant mettre à jour le plugin.
`uv` suit le verrou des dépendances fourni par la version du plugin.

## Docker et Portainer

Conserver les variables, les chemins et les volumes existants, mettre à jour le code puis reconstruire
l’image et recréer les services selon le [guide d’hébergement](Docker-et-Portainer.md).
Ne pas supprimer les volumes. Une image Gramps épinglée ne doit être remplacée qu’après lecture de ses
notes de migration et validation d’une restauration.

## Repères de compatibilité

- Depuis 0.16.0 : dépôt et marketplace portent le nom Genealogiste ; les anciens marqueurs de notes Sosa sont conservés.
- Depuis 0.17.0 : SDK MCP 2, exécution des outils toujours séquentielle et corps de requêtes HTTP limités à 4 Mio ;
  [détails de migration](../docs/migration-mcp-2.md).

Pour la version publiée actuellement, se référer à la page Releases et au numéro du pied de page du wiki.
