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

- Depuis 0.23.0 : les marqueurs écrits dans les notes et dans Gramps Web suivent la forme `genealogiste`.
  Les formes antérieures (`<!-- sosa:debut … -->`, `Sosa-*`, `Sosa:auto`) restent lues ; voir les marqueurs historiques
  des [notes](../docs/notes.md#marqueurs-historiques-sosa) et de [Gramps Web](../docs/gramps-web.md#marqueurs-historiques-sosa--sosaauto).
- Depuis 0.17.0 : SDK MCP 2, exécution des outils toujours séquentielle et corps de requêtes HTTP limités à 4 Mio ;
  [détails de migration](../docs/migration-mcp-2.md).

## Ce qui a changé depuis 0.22.0

Après chaque mise à jour : reconnecter le serveur MCP dans chaque session, puis vérifier `version_serveur`.
Le détail est dans chaque note de version.

- [0.23.0](https://github.com/Hiobi/Genealogiste/releases/tag/v0.23.0) : **recherche autonome**. État d’enquête reprenable, budget d’enquête (requêtes par
  site, images), mode `--autonome` et `/genealogiste:campagne` ; file de propositions et `/genealogiste:valide`.
  Classes de permission (lecture, collecte, proposition, écriture). Débit partagé entre sessions, plafond
  journalier par site, contact facultatif (`GENEALOGISTE_CONTACT`), `GENEALOGISTE_ECRITURE=interdite`.
  Types de pièces `NOT`, `CNI`, `PM`, `COUR` ; kit Obsidian ; marqueurs `genealogiste:` (anciens lus).
  **Changement** : `GENEALOGISTE_BUDGET_DUREE_MIN` et `GENEALOGISTE_BUDGET_COUT_TOKENS` sont retirées ;
  plafonner le coût côté client (`--max-budget-usd`).
- [0.24.0](https://github.com/Hiobi/Genealogiste/releases/tag/v0.24.0) : `sources_catalogue` (archives, sites tiers, API) et
  [sites tiers](../docs/sites-tiers.md) ; parcours [Seconde Guerre mondiale](../docs/seconde-guerre-mondiale.md)
  et `variantes_noms` ; guide [organiser un fonds](Organiser-un-fonds.md) ; sondage guidé d’un registre ;
  exclusion durable d’un site après un défi anti-robot. **Changement** : les nouvelles références aux médias
  sont enregistrées en chemin relatif ; les arbres existants gardent leurs chemins.
- [0.25.0](https://github.com/Hiobi/Genealogiste/releases/tag/v0.25.0) : `archives_registres` couvre dix services (AD59 et neuf services Mnesys) ; registres
  matricules (`RM`) et tables des successions (`SUCC`) ; planche-contact sur toute visionneuse Naoned qualifiée.
- [0.26.0](https://github.com/Hiobi/Genealogiste/releases/tag/v0.26.0) : cinq services de plus (AD25, AD37, AD39, AD80, AD91) ; images d’une citation liées à
  ce qu’elles prouvent ; nouvelles opérations `supprimer_citation`, `supprimer_source`, `fusionner_sources`.
- [0.26.1](https://github.com/Hiobi/Genealogiste/releases/tag/v0.26.1) : notes accentuées reconnues sur macOS et Nextcloud ; blocages anti-robot de l’AD15 et
  de WikiTree signalés comme tels.
- [0.27.0](https://github.com/Hiobi/Genealogiste/releases/tag/v0.27.0) : codes de pièces `TSA` et `MPD` (bureaux de l’enregistrement). **Changement** : une
  déclaration de succession est proposée dans `documents/Enregistrement/` ; les pièces déjà rangées ne sont
  pas déplacées.
- [0.28.0](https://github.com/Hiobi/Genealogiste/releases/tag/v0.28.0) : alignement sur Gramps Desktop (5.2 à 6.1) et Gramps Web (API 3.13.0 à 3.26.0) :
  export et import Gramps XML et `.gpkg`, étiquettes, dates et types, noms de lieux datés, texte enrichi,
  billets du blog (`/genealogiste:billet`), tâches, groupes de noms, drapeau privé des vivants, marqueurs en
  double après une fusion (`dedoublonner_marqueurs`). **Changement** : dans Gramps, les rôles sont écrits sous
  leur nom anglais standard (affichés traduits) et `Date.text` reste vide quand il est la forme canonique ;
  seuls les objets modifiés sont réécrits.

Pour la version publiée actuellement, se référer à la page Releases et au numéro du pied de page du wiki.
