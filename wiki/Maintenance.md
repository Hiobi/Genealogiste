# Maintenir la documentation et le wiki

Le README donne l’essentiel pour comprendre et démarrer. Le wiki est la surface de lecture des guides
utilisateur ; son contenu est **généré à partir des sources relues et versionnées dans le dépôt du code**.
Il ne faut pas entretenir une deuxième copie manuelle des mêmes textes dans l’éditeur GitHub du wiki.

## Où corriger une page

Le [manifeste des pages](pages.json) associe chaque titre de wiki à un fichier source :

- `wiki/*.md` contient les parcours utilisateur et la navigation ;
- `docs/*.md` reste la source des références techniques, déjà utilisées par les commandes et outils ;
- le générateur adapte les liens relatifs et ajoute version, révision source et retour à l’accueil.

Chaque page publiée donne un lien vers sa source exacte. Corriger cette source dans une PR et mettre à jour
le manifeste si une page est ajoutée. Garder les anciens noms de pages, ou prévoir des pages de renvoi lors
d’un renommage. Les fichiers techniques de `docs/` restent disponibles pour préserver les liens existants.

## Préparer et vérifier une publication

Depuis un checkout du code, avec les dépendances de développement installées :

```bash
uv --directory mcp run python ../scripts/preparer_wiki.py --output /tmp/genealogiste-wiki-a-relire
```

Le script vérifie les liens locaux du README et des pages, les pages cibles et les ancres. Il ne consulte
pas tous les sites externes. Le dossier de sortie doit être hors du checkout du code. Lire les fichiers
générés et vérifier le rendu GitHub après publication ; les blocs de code des exemples ne sont pas réécrits.
`make lint` et les tests du générateur complètent ce contrôle en CI.

## Publier après fusion

GitHub demande une première page pour initialiser un wiki. Le wiki doit être activé dans les paramètres
du dépôt, puis une page `Home` créée dans l’interface, si le dépôt du wiki n’existe pas encore.
Cette opération n’est nécessaire qu’au premier déploiement.

Ensuite, cloner le dépôt du wiki dans un dossier séparé :

```bash
git clone https://github.com/Hiobi/Genealogiste.wiki.git /tmp/genealogiste-wiki-publication
uv --directory mcp run python ../scripts/preparer_wiki.py --output /tmp/genealogiste-wiki-publication
```

Dans ce dépôt wiki, relire `git diff`, commiter les pages générées avec un message indiquant la version
et la révision source, puis pousser sa branche par défaut. Utiliser un accès GitHub déjà autorisé ;
ne pas mettre de jeton dans l’URL ou le dépôt. Le script ne pousse rien et ne supprime pas les pages
inconnues : examiner séparément une ancienne page à retirer ou à rediriger.

Le pied de page indique la version et le commit du code utilisés. Après une version du plugin ou un
changement de guide, régénérer et republier le wiki depuis le `main` fusionné. Le dépôt du wiki a son
propre historique Git. Sa publication est une étape explicite de la livraison, pas un effet automatique
d’une modification dans l’éditeur du README.

Sources : [gestion des pages de wiki GitHub](https://docs.github.com/en/communities/documenting-your-project-with-wikis/adding-or-editing-wiki-pages),
[guide de contribution](../CONTRIBUTING.md).
