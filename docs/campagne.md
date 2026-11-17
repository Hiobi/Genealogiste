# Campagne de recherche sans surveillance

`/genealogiste:campagne <cible> [enquetes=N]` (#159) enchaîne, sans poser de question, les recherches sur les
lacunes prioritaires de l'arbre et laisse deux traces retrouvables à la session suivante :

- un **rapport daté** `<données>/rapports/campagnes/AAAA-MM-JJ-campagne-<cible>.md` ;
- des **propositions en file** (`propositions_deposer`), à revoir et appliquer après accord avec
  `/genealogiste:valide`.

Rien n'est écrit dans l'arbre pendant la campagne.

## Déroulement

1. `arbre_lacunes` choisit les personnes (vivants exclus) : tout l'arbre (`arbre`) ou le cercle familial d'un
   id ; au plus `enquetes=N` (défaut 3, maximum 6).
2. Pour chacune, la commande reprend l'enquête ouverte qui la couvre ou en ouvre une **sans budget**
   (`enquete_ouvrir(sujet, [id])`) ; une enquête bloquée n'est pas rouverte (écriture soumise à accord) et
   figure sous « Bloqué ».
3. L'agent `chercheur` est lancé en **mode autonome** : consigne commençant par `MODE AUTONOME`, puis
   `enquete: <id>` et le budget restant. Il ne pose aucune question, dépose ses conclusions dans la file
   (`propositions_deposer(..., enquete=<id>)`) et rend un compte rendu à format fixe (`## Trouvé`,
   `## Négatif`, `## Bloqué`, `## À valider`, `## À faire à la main`, ligne `Budget : …` ; voir
   [enquetes.md](enquetes.md)).
4. Les comptes rendus sont agrégés en un rapport enregistré par `rapport_campagne_enregistrer`.

## Rapport de campagne

`rapport_campagne_enregistrer(titre, contenu, enquetes)` est une **collecte** : permise sans accord et avec
`GENEALOGISTE_ECRITURE=interdite`.

- Fichier **nouveau** à chaque appel : en cas de nom déjà pris le jour même, suffixe `-2`, `-3`… ; création
  exclusive, jamais d'écrasement.
- Toujours sous `<données>/rapports/campagnes/`, **même si `GENEALOGISTE_RAPPORTS_DIR` désigne un vault** :
  le rapport ne quitte pas le répertoire de données. Il n'est ni commité ni poussé vers
  `GENEALOGISTE_GIT_REMOTE`, et aucune requête réseau n'est faite.
- Les personnes y sont désignées par leur id d'arbre ; la commande n'y recopie rien d'une personne vivante
  (les vivants ne sont d'ailleurs pas recherchés). Le rapport reste soumis aux mêmes précautions que le
  répertoire de données : si celui-ci est synchronisé (Nextcloud, sauvegarde, `make sauvegarde`), le rapport
  suit le même chemin que l'arbre. Pour le publier dans un vault, le copier soi-même après relecture.
- `rapport_enregistrer` (rapport de preuve) reste une écriture : il remplace un fichier existant, peut écrire
  dans `GENEALOGISTE_RAPPORTS_DIR` et commite.

## Exécution planifiée

Trois réglages, tous fixés par l'humain avant la tâche :

1. **Garde-fou serveur** : `GENEALOGISTE_ECRITURE=interdite` dans l'environnement du serveur MCP. C'est la
   seule protection qui ne dépend pas du mode de permission du client
   ([tableau des modes](securite.md#modes-dexécution-et-garde-fou-décriture)).
2. **Budget** : les défauts `GENEALOGISTE_BUDGET_*` de cet environnement. La campagne ne passe jamais de
   `budget` (fixer ou relever un budget est une écriture : refusée par le serveur en mode `interdite` et par
   le client en `-p`). Le plafond journalier `GENEALOGISTE_PLAFOND_JOUR_ARCHIVES` s'applique en plus.
3. **Profil de permissions minimal** : `make profil-campagne` affiche un fichier de réglages Claude Code
   dérivé du catalogue des outils : `defaultMode: dontAsk`, `allow` pour la lecture, la collecte, la
   proposition et les outils en deux temps (leur branche écriture reste refusée par le serveur), `deny` pour
   toutes les autres écritures. Serveur HTTP Docker : `make profil-campagne PREFIXE=mcp__genealogiste__`.

```bash
mkdir -p ~/.config/genealogiste ~/.local/state/genealogiste
make profil-campagne > ~/.config/genealogiste/campagne-settings.json
```

Script lancé par la tâche, par exemple `~/.local/bin/genealogiste-campagne` (rendu exécutable) :

```bash
#!/bin/sh
# Campagne hebdomadaire sans surveillance : aucune écriture dans l'arbre, rapport daté, propositions en file.
set -eu
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"  # cron fournit un PATH minimal (claude, uv, git)
export GENEALOGISTE_ECRITURE=interdite        # garde-fou serveur (hérité par le serveur MCP stdio)
export GENEALOGISTE_BUDGET_REQUETES_HOTE=100  # budget de chaque enquête, fixé ici par l'humain
export GENEALOGISTE_BUDGET_IMAGES=20
export GENEALOGISTE_BUDGET_DUREE_MIN=20
export GENEALOGISTE_BUDGET_COUT_TOKENS=60000
cd "$HOME/genealogie-campagne"                # dossier de travail sans secrets ni code
exec claude -p "/genealogiste:campagne arbre enquetes=3" \
  --settings "$HOME/.config/genealogiste/campagne-settings.json" \
  --permission-mode dontAsk --permission-prompts none \
  --max-budget-usd 5 --output-format json \
  >> "$HOME/.local/state/genealogiste/campagne-$(date +%F).json" 2>&1
```

Entrée de crontab (`crontab -e`), le lundi à 2 h 30 :

```cron
30 2 * * 1 $HOME/.local/bin/genealogiste-campagne
```

Ne pas ajouter `--bare` : en mode bare, Claude Code ne charge ni le plugin, ni ses commandes, ni ses hooks.
Ne jamais lancer une campagne avec `--dangerously-skip-permissions` sans `GENEALOGISTE_ECRITURE=interdite`.

Points **supposés, non vérifiés en réel** (aucune session `claude` lancée pour cette page) : que le serveur
MCP stdio du plugin hérite de l'environnement de `claude` (les variables du processus priment sur le `.env`
du répertoire de données, qui ne les écrase jamais) ; que `--max-budget-usd` et `--permission-prompts none`
existent dans votre version de Claude Code (`claude --help`). Avec le **serveur HTTP Docker**, la variable
se règle dans l'environnement du conteneur : réserver à la campagne une instance lancée avec `interdite`,
ou laisser `interdite` en permanence et appliquer les propositions depuis une instance `autorisee`.

## Lendemain de campagne

Dans une session surveillée (serveur en `autorisee`) :

1. lire le rapport (`<données>/rapports/campagnes/`) ;
2. `/genealogiste:valide` : chaque proposition est rejouée sur l'arbre courant (diff frais) et appliquée
   seulement après accord ;
3. enquêtes bloquées : `/genealogiste:enquete` pour relever le budget avec accord, puis reprendre.
