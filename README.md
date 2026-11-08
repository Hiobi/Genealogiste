# Genealogiste

**Un assistant de recherche familiale dans Claude Code et Codex.**

Partez d’une personne ou d’un acte, croisez les sources et construisez un arbre documenté.
Genealogiste vous aide à distinguer les faits étayés, les hypothèses et les homonymes.

[Premiers pas](https://github.com/Hiobi/Genealogiste/wiki/Demarrage) · [Documentation](https://github.com/Hiobi/Genealogiste/wiki) · [Commandes](https://github.com/Hiobi/Genealogiste/wiki/Commandes) · [Dépannage](https://github.com/Hiobi/Genealogiste/wiki/Depannage)

## Ce que vous pouvez faire

| Votre besoin | Ce que le plugin apporte |
|---|---|
| Retrouver une personne | Recherche dans plusieurs sources, variantes de noms et comparaison des candidats |
| Vérifier une filiation | Citations, analyse des contradictions et vérification indépendante |
| Exploiter un acte | Aide à la transcription, relevé des témoins et classement des pièces |
| Organiser votre travail | Fiches Markdown/Obsidian, journal et prochaines recherches prioritaires |
| Construire et partager un arbre | GEDCOM versionné en Git ou connexion à Gramps Web ; exports masqués par défaut |

Les sources sont principalement françaises. Certains sites sont consultés par API ; d’autres nécessitent
une consultation manuelle. Pour les actes, vous pouvez fournir un lien IIIF international, un lien de
visionneuse AD59 ou un fichier : [lecture et archivage des pièces](https://github.com/Hiobi/Genealogiste/wiki/Pieces-et-medias).
[Services d’archives : fonctions et limites](https://github.com/Hiobi/Genealogiste/wiki/Services-archives).
**Une correspondance trouvée n’est pas une preuve.**

## Installer et démarrer

Il vous faut **Claude Code**, **Git** et **[uv](https://docs.astral.sh/uv/getting-started/installation/)**.
Le serveur utilise Python **3.11 ou plus** ; uv peut installer une version compatible au premier lancement.

Dans un terminal, installez le plugin pour votre compte :

```bash
claude plugin marketplace add Hiobi/Genealogiste
claude plugin install genealogiste@genealogiste --scope user
```

Ouvrez une nouvelle session Claude Code depuis un **dossier de travail privé**, distinct du dépôt du plugin.
Au premier lancement, uv installe les dépendances ; le premier accès à l’arbre crée un GEDCOM vide local. Aucun compte de source externe
n’est nécessaire pour commencer à consulter un arbre local.

Demandez ensuite :

> Utilise l’outil arbre_info de Genealogiste et indique le backend et le nombre de personnes.

Un arbre neuf doit indiquer le mode `fichier` et **0 personne**. Dans `/mcp`, vérifiez que le serveur
`genealogiste` est connecté. Si une erreur apparaît, suivez le [dépannage](https://github.com/Hiobi/Genealogiste/wiki/Depannage).

**Vous aviez installé `genealogiste@sosa` ?** Suivez la [migration](https://github.com/Hiobi/Genealogiste/wiki/Migration) avant de changer de marketplace.
Pour un autre dossier de données, Gramps Web ou Docker : [installation détaillée](https://github.com/Hiobi/Genealogiste/wiki/Installation).

## Un premier parcours

Avec un **GEDCOM fictif ou une copie privée** de votre arbre, dans Claude Code :

```text
/genealogiste:import /chemin/prive/exemple.ged
/genealogiste:fiche I1
/genealogiste:lacunes I1
```

Relisez le bilan et le diff de l’import avant de l’approuver. Utilisez ensuite les identifiants réellement
présents dans votre arbre. Le [tutoriel avec les données fictives du projet](https://github.com/Hiobi/Genealogiste/wiki/Demarrage)
détaille ce parcours et le résultat attendu.

## Vos données et vos décisions

- Arbres, actes, notes et identifiants restent dans des emplacements privés **hors du dépôt du plugin**.
  Par défaut : `~/.local/share/genealogiste` (ou le dossier XDG configuré).
- Les éditions de l’arbre passent par une proposition et un diff, puis par l’application après accord.
  Les hooks Claude ajoutent la confirmation ; un autre client MCP doit avoir sa propre politique d’approbation.
- Des gardes limitent les recherches externes sur les personnes présumées vivantes ; les exports masquent
  les vivants et les objets privés par défaut. Relisez toujours ce que vous comptez partager.

[Confidentialité et limites](https://github.com/Hiobi/Genealogiste/wiki/Confidentialite) · [Sauvegarder et restaurer](https://github.com/Hiobi/Genealogiste/wiki/Sauvegardes)

## Pour aller plus loin

[Wiki : tous les guides](https://github.com/Hiobi/Genealogiste/wiki) · [Signaler un problème](https://github.com/Hiobi/Genealogiste/issues) · [Proposer une amélioration](https://github.com/Hiobi/Genealogiste/issues/new) · [Signaler une vulnérabilité en privé](https://github.com/Hiobi/Genealogiste/security/advisories/new)

Pour **Codex CLI**, suivre le [guide d’installation et d’approbation](https://github.com/Hiobi/Genealogiste/wiki/Codex) :
le paquet fournit les skills ; un profil séparé active le MCP avec confirmation native de chaque outil.
Le mode fichier fonctionne sans Gramps Web ni Obsidian. L’ancien exporteur FamilySearch est désactivé ;
un GEDCOM obtenu séparément peut être importé.

Pour contribuer : [CONTRIBUTING.md](CONTRIBUTING.md), [architecture et conventions](CLAUDE.md),
[tests et CI](docs/integration-continue.md). Licence déclarée dans le manifeste : MIT.
