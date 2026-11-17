# État d'enquête persistant et reprenable

Le journal de recherche (`journal.jsonl`) dit **qu'une requête a eu lieu**. L'état d'enquête dit **où en
est la recherche** : quelles pistes restent ouvertes, quelles vues d'un registre ont été lues et ce qu'on y a
lu, ce qui attend l'utilisateur. Après une interruption (limite d'usage, contexte résumé, redémarrage du
serveur), `enquete_reprendre` donne la suite sans relire le journal entier et sans refaire une demande déjà
notée.

## Stockage

- Un fichier JSON par enquête : `<données>/enquetes/<id>.json`, indenté, lisible et modifiable à la main
  (un fichier illisible est ignoré, les autres restent utilisables).
- Écriture atomique (fichier temporaire puis renommage) sous le verrou `<données>/.enquetes.lock`
  (plusieurs serveurs sur les mêmes données).
- **Versionné avec le journal** : le dossier `enquetes/` fait partie des fichiers internes du dépôt Git des
  données. Il est commité avec `journal.jsonl`, dans le commit séparé « Journal de recherche » qui précède
  chaque modification de l'arbre (`arbre_appliquer`, miroir Gramps). Une annulation de modification ne touche
  donc jamais l'état d'enquête. Entre deux écritures de l'arbre, l'état est sur disque mais pas encore
  commité, comme le journal.
- Rien n'est envoyé au réseau : l'état est local. Les outils réseau gardent leur contrôle « vivants »
  (`_garde`) ; une demande refusée pour une personne vivante n'est pas notée.

## Contenu

| Élément | Champs |
|---|---|
| enquête | `id` (stable, minuscules, chiffres, `-`, `_`), `sujet`, `personnes` (ids de l'arbre), `statut` (`ouverte` / `close`) |
| piste | `id` (`p1`…), `question`, `hypotheses`, `sources` à consulter dans l'ordre (`{libelle, outil, parametres, fait}`), `statut`, `note`, `journal` |
| registre | `id` (`r1`…), `source` (ARK, URL de visionneuse ou manifeste), `cle` (ARK du registre sans vue), `service`, `cote`, `titre`, `piste`, `nb_vues`, `bornes` `[de, a]`, `vues_lues` (intervalles fusionnés), `lectures` (`{vue, date, type, numero, note}`), `verdict`, `statut`, `journal` |
| tâche manuelle | `id` (`t1`…), `description`, `service`, `piste`, `statut` (`a_faire` / `faite` / `abandonnee`) |
| requête faite | `outil`, `parametres`, `cle` normalisée, `date`, `resultat` (`positif` / `negatif` / `erreur` / `manuel`), `journal` |

Statuts d'une piste ou d'un registre, sans accents comme les outils : `a_faire`, `en_cours`, `trouve`,
`negatif`, `bloque`, `manuel`. `trouve` et `negatif` ferment l'élément ; `bloque` et `manuel` le gardent
ouvert sans action automatique.

## Outils

| Outil | Effet |
|---|---|
| `enquete_ouvrir(sujet, personnes, id)` | crée l'enquête ; `id` dérivé du sujet si absent |
| `enquete_noter(enquete, piste, registre, tache, requete, statut, personnes)` | ajoute ou met à jour (par `id`, ou pour un registre par ARK/cote) |
| `enquete_etat(enquete)` | état complet + `coherence_journal` ; sans argument : liste des enquêtes |
| `enquete_reprendre(enquete)` | `a_faire` (outil et paramètres prêts, dans l'ordre), pistes ouvertes, registres en cours avec `vues_restantes`, tâches manuelles, `deja_fait` |

Ces outils sont locaux : lecture (`enquete_etat`, `enquete_reprendre`) ou trace au journal
(`enquete_ouvrir`, `enquete_noter` : classe collecte, état géré par le plugin, ouverture sans écrasement), autorisés
sans confirmation (voir les classes de permission dans `docs/securite.md`).

`recherche_multi`, `archives_naviguer` et `archive_image` acceptent un paramètre facultatif
`enquete=<id>` : la demande est notée dans l'état (fenêtre parcourue et nombre de vues pour une navigation,
vue consultée pour une image, résultat et entrées de journal pour une recherche). Sans ce paramètre, rien ne
change pour ces outils, sinon l'indication ci-dessous.

## « Déjà fait le … »

Les trois outils ajoutent `deja_fait` (liste avec `enquete`, `date`, `resultat`, `message`) quand la même
demande figure déjà dans l'état d'une enquête. L'appel n'est **jamais bloqué** ni modifié. La correspondance
est exacte et prudente :

- `recherche_multi` : mêmes `nom`, `prenom`, `ne_vers`, `lieu`, `decede_vers` (casse, accents et espaces
  ignorés) et même ensemble de sources ; un prénom différent n'est pas « la même demande » ;
- `archives_naviguer` : même registre (ARK sans vue, ou URL) et mêmes `page` et `pas` ; ou fenêtre entièrement
  comprise dans les vues déjà lues du registre ;
- `archive_image` : même registre et même vue, consultée ou notée comme lue (les lectures notées sont
  rappelées). Un recadrage de la même vue est donc signalé : c'est attendu, la consigne reste d'agrandir l'acte.

## Cohérence avec le journal

Toute entrée négative de l'état (piste ou registre `negatif`, requête au résultat `negatif`) référence au
moins une entrée du journal :

- `journal=<id>` fourni à `enquete_noter` : l'entrée doit exister, sinon la notation est refusée ;
- sinon une entrée `source="enquete"`, `statut="negatif"` est créée (identifiants dans `journal_cree`), au nom
  de la première personne de l'enquête ;
- une recherche négative passée par `recherche_multi(..., enquete=<id>)` référence les entrées écrites par
  les sources interrogées.

`enquete_etat(id)` renvoie `coherence_journal: "ok"` ou la liste des éléments négatifs sans trace (cas d'un
fichier édité à la main).

## Reprendre une enquête

```text
enquete_reprendre("naissance-de-jean-dupont")
→ a_faire : [{type: registre, outil: archives_naviguer, parametres: {source, page: 803, pas: 20}}, …]
  deja_fait : [{outil: recherche_multi, date, resultat: negatif}, …]
```

Exécuter `a_faire` dans l'ordre en passant `enquete=<id>` ; ne pas relancer `deja_fait`. Pour un registre,
les vues restantes sont les bornes (ou `1..nb_vues`) moins les vues lues : une vue déjà listée par une
navigation est proposée en `archive_image`, sinon la fenêtre suivante en `archives_naviguer`. Noter chaque
lecture (`registre.lectures`), le verdict et les tâches manuelles avec `enquete_noter`.

L'identifiant d'enquête est une chaîne simple et stable : il peut être repris tel quel comme « enquête
d'origine » par d'autres fonctions (file de propositions).
