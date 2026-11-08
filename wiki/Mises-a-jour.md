# Mettre à jour Genealogiste

Lire les [notes de version](https://github.com/Hiobi/Genealogiste/releases) et faire une
[sauvegarde](Sauvegardes.md) avant une migration ou une modification de votre hébergement.

## Plugin installé depuis la marketplace

Dans un terminal :

```bash
claude plugin marketplace update genealogiste
claude plugin update genealogiste@genealogiste
```

Ouvrir une nouvelle session ou reconnecter le serveur MCP, puis vérifier `arbre_info` et les effectifs.
Les chemins et le backend doivent être ceux de votre installation précédente.
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
