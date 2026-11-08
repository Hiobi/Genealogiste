# Utiliser Genealogiste dans Codex

Le moteur MCP et les cinq skills métier sont communs à Claude Code et Codex. Le paquet Codex ajoute
les parcours `genealogiste` et `genealogiste-verifier`. Les commandes slash et les agents Claude restent
propres à Claude ; leur syntaxe ne s’applique pas à Codex.

**Surface validée : Codex CLI 0.166.0, app-server local en stdio, backend fichier, données fictives.**
L’app-server est une interface expérimentale. La recette contrôle le vrai moteur d’approbation et simule
les réponses du client ; elle ne constitue pas une validation visuelle du bouton dans Codex desktop.
Codex Cloud, ChatGPT Work et les autres versions ne sont pas couverts par cette recette.

## Installation locale

Prérequis : Codex CLI, Git, uv et Python 3.11 ou plus. Conserver un checkout durable du plugin : le serveur
MCP utilisera ce chemin. Les données doivent se trouver dans un autre répertoire privé.

```bash
git clone --branch v0.18.1 https://github.com/Hiobi/Genealogiste.git
cd Genealogiste
codex plugin marketplace add "$PWD" --json
codex plugin add genealogiste@genealogiste --json
python3 scripts/configurer_codex.py --data-dir "$HOME/genealogie" > /tmp/genealogiste.config.toml
```

Relire le profil produit, puis le placer dans le dossier de configuration Codex sous le nom
`genealogiste.config.toml`. Par défaut, ce dossier est `~/.codex` ; `CODEX_HOME` peut le remplacer.
Conserver un éventuel profil existant avant de le remplacer. Le générateur affiche du TOML et ne modifie
aucune configuration personnelle. Il refuse les données dans le checkout, y compris via un lien symbolique.

Le paquet installé seul fournit les skills, sans démarrer de MCP. **Charger le profil pour chaque session** :

```bash
# Depuis votre dossier de travail privé, distinct du plugin :
codex -p genealogiste
```

Le profil active le plugin, fixe `approvals_reviewer = "user"` et exige
`default_tools_approval_mode = "prompt"` sur le serveur `genealogiste`.
Tous les appels MCP demandent ainsi une confirmation, y compris les lectures. Le serveur est `required` :
une erreur de démarrage fait échouer l’ouverture du chat au lieu de continuer silencieusement sans lui.
Au premier lancement, uv peut installer Python et les dépendances verrouillées.

Ne pas ajouter le même serveur une seconde fois avec `codex mcp add` : sa politique par défaut pourrait
être différente. Conserver `prompt`, sans exemption d’outil ni revue automatique. Une politique ou une
surcharge locale qui remplace ce profil change les garanties décrites ici.

## Premiers pas et approbation

Demander « Utilise arbre_info de Genealogiste ». Approuver la demande native pour cette lecture.
Sur des données neuves, le résultat indique `backend: fichier` et `personnes: 0`.
Le premier accès crée aussi le dépôt Git local, le journal et les structures nécessaires.

Le sélecteur de skills expose notamment `genealogiste:genealogiste` et
`genealogiste:genealogiste-verifier`, en plus des cinq skills métier. Les choisir dans le sélecteur Codex
ou les invoquer par leur nom affiché. Exemple : demander au skill Genealogiste d’importer un GEDCOM fictif,
puis de présenter la fiche et les lacunes d’une personne. Le [tutoriel](../wiki/Demarrage.md) fournit le
fichier de démonstration ; les commandes Claude qui y figurent sont à remplacer par ces demandes.

Pour une édition :

1. Approuver l’appel de proposition/import ; il persiste un jeton et peut tracer une entrée au journal.
2. Relire le bilan, le diff complet et les alertes présentés par le skill.
3. Refuser l’appel `arbre_appliquer` si le diff ne convient pas : l’outil n’est pas exécuté.
   Le jeton reste disponible côté moteur ; le parcours demande de l’abandonner.
4. Pour reprendre, demander une nouvelle proposition et relire son nouveau diff avant l’approbation native.
5. L’application réussit une seule fois. Un jeton expiré ou un arbre modifié impose une nouvelle proposition.

La demande native identifie l’outil et ses arguments (le jeton pour `arbre_appliquer`) ; le diff est présenté
séparément dans le chat. Un jeton ne prouve pas l’accord d’un humain. Une phrase dans un skill ne donne
aucun droit de modification.

Pour une conclusion importante ou une fusion, lancer une **nouvelle conversation** avec le skill de
vérification, l’identifiant et le fait à examiner, sans transmettre les conclusions du chercheur.
Le vérificateur reprend les pièces, cherche les contradictions et rend son rapport ; les modifications
reviennent au parcours d’édition. Une relecture dans le même contexte ne constitue pas une vérification indépendante.

## Effets des outils

La première intégration conserve `prompt` pour tout le catalogue : aucun classement « lecture » ne
permet de contourner l’approbation. Les décisions `ALLOW`, `ASK`, `CONDITIONNEL` et `DEFAUT` de `outils.py`
restent celles des hooks **Claude** ; `DEFAUT` n’est jamais une permission Codex.

| Famille | Effets à prendre en compte |
|---|---|
| Analyses locales, fiches, recherche dans l’arbre | Lecture métier ; l’initialisation peut créer les données privées |
| Sources externes, ARK et images | Réseau, cache et journal ; les gardes des vivants restent actives |
| Propositions, import et annulations | Fichiers de jetons ; l’import écrit aussi au journal avant l’application |
| `arbre_appliquer`, bascule Gramps, classement des pièces | Arbre/fichiers/transac­tions ; certaines opérations rafraîchissent les notes |
| `arbre_exporter`, `rapport_enregistrer`, `media_enregistrer` | Écritures directes, sans proposition ; exports masqués par défaut |
| `notes_generer`, `notes_ajouter`, **`notes_lire`** | Écritures de notes ; `notes_lire` génère une fiche absente |
| `piece_archiver` | Téléchargement, image et note locale |
| `matchid_appariement_statut(sortie=…)` | Requête et écriture conditionnelle d’un fichier |
| Journal, cache, synchronisations Gramps | Écritures auxiliaires ; même les anciens `ALLOW` Claude demandent confirmation |
| Identifiants | Accès aux services configurés ; l’ancien exporteur FamilySearch demeure désactivé |

Le profil configure le backend fichier par défaut. Pour Gramps Web, utiliser la [configuration du backend](gramps-web.md)
dans le dossier privé ; cette recette Codex ne valide pas un serveur Gramps réel.

## Garanties et limites du client

Le manifeste portable `plugin.json` déclare explicitement `hooks: []`, et `mcp.json` ne contient aucun
serveur. Cela empêche la découverte automatique de `hooks/hooks.json` et de la connexion Claude pour Codex.
La connexion Codex est définie séparément par le profil. Claude continue d’utiliser `.claude-plugin/`,
`.mcp.json`, ses commandes et ses confirmations.

Le serveur MCP est un processus de confiance : ses fichiers ne sont pas confinés par le sandbox des
commandes shell Codex. Les protections du moteur (confinement, vivants, jetons, exports) restent nécessaires.
La politique native protège les appels d’outils **du tour Codex**. Le RPC de diagnostic
`mcpServer/tool/call` appelle directement un outil sans cette approbation ; la recette ne l’utilise pas.
Un autre client MCP doit définir sa propre politique. Les hooks Claude utilisant
`permissionDecision: "ask"` ne doivent pas servir d’approbation Codex : cette décision y est non prise en
charge et peut laisser continuer l’appel.

## Vérification reproductible

```bash
make test
make lint
make test-codex
```

`make test-codex` requiert exactement Codex CLI 0.166.0 et uv. Il crée un `CODEX_HOME`, un cache, un arbre,
des notes et des médias temporaires, installe le paquet local puis les supprime à la fin. Aucun compte ni
clé API n’est requis. Un fournisseur HTTP local déterministe émet les appels imposés par la recette :
aucun modèle distant ne choisit les outils.

La recette vérifie la découverte des sept skills et l’absence de serveur implicite, puis passe les appels
par de vrais tours Codex : lecture, diff, refus de l’application sans mutation, nouveau diff accepté,
application unique, expiration, conflit, garde des vivants, export masqué, refus puis accord sur notes et
médias. Les réponses d’approbation sont **simulées par le client de test**. Les tests Python couvrent les
autres invariants du moteur ; la recette native est distincte de pytest et n’est pas exécutée par la CI ordinaire.

## Mise à jour

Mettre à jour le checkout vers une version publiée, puis réinstaller le plugin avec `codex plugin remove`
et `codex plugin add genealogiste@genealogiste`. Le profil conserve le chemin du checkout. Si ce chemin
change, régénérer le profil. Les données restent hors du checkout ; sauvegarder leur dossier normalement.

## Références

Documentation OpenAI consultée le 8 novembre 2026 :

- [Paquet et découverte des hooks](https://developers.openai.com/plugins/build/plugins)
- [Politique native des outils MCP](https://learn.chatgpt.com/docs/extend/mcp)
- [Protocole app-server](https://learn.chatgpt.com/docs/app-server)
- [Limites des hooks PreToolUse](https://learn.chatgpt.com/docs/hooks)
