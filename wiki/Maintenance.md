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

## Veille et renouvellement des référentiels AD59

Les pages sur l’AD59 décrivent des relevés datés (27 novembre 2026) : les douze formulaires de recherche, le
classeur 3 E (`referentiels/ad59_3e.json`) et l’état de collection des recensements
(`referentiels/ad59_recensements.json`). Le service ajoute des fonds et des années en continu ; sans suivi,
ces référentiels vieillissent et les pages avec eux.

```bash
make veille-ad59   # étape réseau explicite : 15 requêtes au plus, espacées
```

- La veille se lance à la main, hors de `make test` ; aucun outil MCP ne la déclenche. Elle **signale** et ne
  corrige ni ne télécharge rien. Code de sortie : 0 si rien n’est à signaler, 1 dès qu’il y a un signalement
  (un échec réseau en est un, jamais une erreur bloquante).
- Trois volets : dérive des formulaires par rapport à leur contrat, fils d’ajouts du forum du service, lien du
  classeur 3 E millésimé (un nouveau classeur est signalé, jamais téléchargé).
- Le forum est lu **en lecture seule** : titre, date et lien des fils, sans compte ni connexion ; le corps des
  messages n’est ni lu ni conservé. Un titre de fil est une piste à vérifier sur le site du service.
- Sans réseau, un référentiel relevé depuis plus de **365 jours** est « à renouveler » : `diagnostic` le
  reprend (contrôle `referentiels_ad59`, état `attention`). Ce seuil est un choix du plugin, pas une
  périodicité annoncée par le service.

Renouveler le classeur 3 E et l’état de collection des recensements reste une étape manuelle, à prévoir
chaque année ou dès qu’un nouveau classeur est signalé : `scripts/generer_couverture_3e_ad59.py` et
`scripts/generer_couverture_recensements_ad59.py` lisent le PDF publié et écrivent le référentiel avec son
relevé daté (`releve_le`) et l’empreinte SHA-256 du document ; `--check` compare sans écrire. Mettre ensuite à
jour la source déclarée, les chiffres cités, fixtures et tests si des volumes ont changé, régénérer
`docs/couverture-archives.md` (`scripts/generer_couverture_archives.py`), puis republier le wiki.

Détail, états rendus et limites : [veille des AD59](../docs/veille-ad59.md). Procédures de renouvellement :
[classeur 3 E](../docs/recherche-registres-ad59.md#classeur-3-e--cote-et-mise-en-ligne-prévue--374) et
[recensements](../docs/recensements.md#renouvellement-du-référentiel).

Sources : [gestion des pages de wiki GitHub](https://docs.github.com/en/communities/documenting-your-project-with-wikis/adding-or-editing-wiki-pages),
[guide de contribution](../CONTRIBUTING.md).
