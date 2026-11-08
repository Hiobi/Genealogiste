# Premiers pas sur un arbre fictif

Ce tutoriel utilise uniquement la famille inventée livrée avec les tests. Il permet de vérifier
l’installation, de comprendre les fiches et de voir le fonctionnement des propositions sans toucher
à votre arbre habituel. Il ne démontre pas l’exhaustivité d’une recherche sur des sources réelles.

## Préparer un espace d’essai

Après l’[installation](Installation.md), télécharger une copie du code puis ouvrir un dossier privé
séparé. Ces commandes créent un nouveau dossier temporaire ; elles ne déplacent aucune donnée existante.

```bash
git clone https://github.com/Hiobi/Genealogiste.git
exemple_genealogiste="$(mktemp -d)"
cp Genealogiste/mcp/tests/fixtures/famille.ged "$exemple_genealogiste/exemple.ged"
unset GENEALOGISTE_ENV_FILE
export GENEALOGISTE_GIT_REMOTE=""
export GENEALOGISTE_NOTES_AUTO=0
export GENEALOGISTE_NOTES_DIR="$exemple_genealogiste/notes"
export GENEALOGISTE_MEDIA_DIR="$exemple_genealogiste/medias"
export GENEALOGISTE_RAPPORTS_DIR="$exemple_genealogiste/rapports"
export GENEALOGISTE_EXPORTS_DIR="$exemple_genealogiste/exports"
export GENEALOGISTE_CACHE_IMAGES_DIR="$exemple_genealogiste/cache-images"
export GENEALOGISTE_DATA_DIR="$exemple_genealogiste/donnees"
export GENEALOGISTE_CACHE="$exemple_genealogiste/cache.sqlite"
export GENEALOGISTE_BACKEND=fichier
export GENEALOGISTE_OFFLINE=1
cd "$exemple_genealogiste"
printf 'GEDCOM fictif à importer : %s\n' "$exemple_genealogiste/exemple.ged"
claude
```

Le cache seul (`GENEALOGISTE_OFFLINE=1`) évite les recherches réseau de sources pendant l’exercice.
Le téléchargement initial des dépendances du serveur peut encore nécessiter une connexion.
Le terminal affiche le chemin absolu du GEDCOM à copier dans la commande d’import.

## 1. Vérifier l’arbre vide

> Utilise arbre_info de Genealogiste, sans modifier l’arbre.

Le serveur doit annoncer le backend `fichier` et zéro personne.

## 2. Proposer l’import

Dans Claude Code, remplacer le chemin ci-dessous par celui affiché dans le terminal (le serveur
ne résout pas forcément les chemins relatifs depuis votre dossier de travail) :

```text
/genealogiste:import /chemin/affiche/exemple.ged
```

Demander le bilan et le diff, puis approuver seulement si le fichier est bien l’exemple fictif.
Le serveur prépare une proposition ; l’application utilise son jeton après accord.
Après import, `arbre_info` doit compter **8 personnes, 3 familles et 4 sources**.
Les informations importées ne deviennent pas des conclusions vérifiées par leur seul import.

## 3. Lire une fiche et choisir une question

```text
/genealogiste:fiche I1
/genealogiste:lacunes I1
```

`I1` est Jean MARTIN dans cet exemple. Relever les faits, leurs citations, les statuts et la prochaine
source suggérée. Une cote suggérée doit toujours être vérifiée dans l’inventaire du service.
Le personnage `I9`, Lucas MARTIN, né en 1990, permet de comprendre la présomption de vie : ne pas lancer
une recherche externe sur ce personnage pour « tester » le dispositif.

## 4. Comprendre la validation

Demander une proposition d’édition fictive et lire le diff. Un refus doit laisser l’arbre inchangé.
Pour continuer, faire une nouvelle proposition si nécessaire puis l’appliquer après accord explicite.
Le jeton n’est utilisable qu’une fois et expire ; un changement concurrent de l’arbre impose de reproposer.
Les [opérations disponibles](../docs/operations.md) et les [approbations](Confidentialite.md) détaillent ce mécanisme.

## 5. Passer à votre propre recherche

Fermer cette session, retirer les exports de l’exercice ou ouvrir un nouveau terminal, puis sélectionner
votre vrai dossier privé. Vérifier à nouveau les effectifs avec `arbre_info` avant un import.
Ne copier ni votre arbre ni vos actes dans le dépôt du plugin.

La suite : [mode fichier](Mode-fichier.md), [parcours de recherche](Parcours-de-recherche.md),
[configuration](Configuration.md) et [exports](Exports.md).
