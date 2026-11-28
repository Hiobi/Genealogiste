# Veille des mises en ligne des AD59 — #380

Les Archives départementales du Nord ajoutent des fonds et des années en continu. Trois sources publiques le
disent : la page [Nouveautés du site internet](https://archivesdepartementales.lenord.fr/page/nouveautes-du-site-internet),
le forum du service (phpBB, forum « ANNÉES MANQUANTES AJOUTÉES ») et le classeur 3 E, dont le nom est millésimé
(`/document/classeur-3e-janvier-2026`) et dont le statut « > année » annonce les mises en ligne à venir. Sans
suivi, les référentiels embarqués vieillissent et un négatif d'hier devient faux.

La veille **signale** ; elle ne corrige rien, ne télécharge rien et n'établit aucun fait généalogique.

## Où vit la veille, et pourquoi

| Volet | Où | Réseau |
|---|---|---|
| Ancienneté des référentiels embarqués | `diagnostic`, contrôle `referentiels_ad59` (et chaque passage de veille) | non |
| Dérive des formulaires, forum des ajouts, classeur millésimé | `make veille-ad59` (`scripts/veiller_ad59.py`, module `sources/veille_ad59.py`) | oui, étape explicite |

Aucun outil MCP n'est ajouté. `archives_sonder`, cité par l'issue, est un calcul pur (quelle vue lire dans un
registre) classé sans réseau : lui faire émettre des requêtes aurait changé sa classe de permission. `diagnostic`
émet une requête par source ; y ajouter quinze requêtes vers un seul service aurait alourdi chaque diagnostic.
La veille est un geste de maintenance du plugin, pas une étape d'enquête : comme
`scripts/verifier_telechargements.py` et `make verifier-archives`, elle se lance à la main (ou par une tâche
planifiée du mainteneur), hors de `make test`. Elle passe par le client HTTP du dépôt et la configuration de
l'utilisateur : politique réseau (#42), intervalle et plafond journalier par hôte (#211), coupe-circuit,
mode hors ligne ; aucun robot ad hoc.

```bash
make veille-ad59                 # passage complet : 15 requêtes au plus
make veille-ad59 FORUM=html      # page HTML du forum au lieu du flux Atom
make veille-ad59 FORUM=non OPTIONS="--sans-formulaires"      # classeur seul : 1 requête
uv --directory mcp run python ../scripts/veiller_ad59.py --sortie veille.json
```

Code de sortie : 0 si rien n'est à signaler, 1 s'il y a au moins un signalement. Un échec (réseau, protection,
page changée) est un signalement dans la réponse, jamais une erreur bloquante. Les requêtes ne sont pas mises
en cache (chaque passage relit) et sont espacées de 3 s en plus de l'intervalle de l'hôte. Chaque volet laisse
une entrée au journal de recherche, source `veille_ad59` (`journal_lister(source="veille_ad59")`).

## 1. Dérive des formulaires de recherche

Le plugin interroge douze formulaires AD59 (`/search/form/<uuid>`). Leurs UUID ont une source unique, les
constantes de `sources/registres.py`, réunies par `registres.formulaires_ad59()` :

| Clé | Formulaire | Constante |
|---|---|---|
| `etat_civil` | Actes paroissiaux et d'état civil | `FORMULAIRE` |
| `tables_decennales` | Tables décennales | `FORMULAIRE_TD` |
| `recensements` | Recensements de population | `FORMULAIRE_REC` |
| `matricules_tables`, `matricules_fiches` | Tables et fiches des états signalétiques | `FORMULAIRES_RM` |
| `successions`, `fiches_deces` | Tables des successions et absences, fiches décès | `FORMULAIRES_ENREGISTREMENT` |
| `hypotheques_indicateur`, `hypotheques_tables`, `hypotheques_repertoires` | Sous-série 4 Q | `FORMULAIRES_HYP` |
| `cadastre_consulaire`, `cadastre_napoleonien` | Plans du cadastre | `FORMULAIRES_CAD` |

Le contrat attendu de chacun (titre de la page et noms des champs visibles du formulaire, par exemple
`0-controlledAccessGeographicName`, `2-date`, `3-date_begin`) est dans `referentiels/ad59_formulaires.json`,
relevé le 27 novembre 2026 ; ce fichier ne recopie aucun UUID. Un passage lit chaque page une fois et rend,
par formulaire :

| État | Sens |
|---|---|
| `conforme` | titre et champs identiques au contrat |
| `derive` | `champs_disparus`, `champs_ajoutes`, `champs_renommes` (même nom, autre indice : `2-date` → `4-date`), `titre_change`, ou `formulaire_servi` (la page porte un autre UUID) ; `champs_lus` donne les champs relevés |
| `disparu` | HTTP 404 : UUID retiré ou remplacé |
| `non_reconnu` | page servie sans le formulaire de recherche attendu |
| `non_verifie` | réseau, protection, refus de la politique réseau, mode hors ligne : rien n'est conclu |

Après un échec qui vaut pour l'hôte (défi anti-robot, coupe-circuit, 429, 5xx, réseau), les formulaires
restants ne sont pas demandés. Les options des listes (communes, bureaux) ne sont pas lues ; aucune recherche
n'est lancée, aucun paramètre n'est envoyé.

**Après une dérive** : relire le formulaire sur le site, corriger `sources/registres.py` (et ses tests) si la
recherche est touchée, puis mettre à jour `ad59_formulaires.json` (titre, champs, `releve_le`) d'après
`champs_lus`. Un nouvel UUID se change dans `registres.py` seulement.

## 2. Fils d'ajouts du forum

Le forum `https://forum-archivesdepartementales.lenord.fr` annonce trois flux Atom (relevé du 27 novembre
2026, balises `<link rel="alternate">` de la page du forum 138) : `/app.php/feed` (tout le forum),
`/app.php/feed/topics` (nouveaux sujets) et `/app.php/feed/forum/138`, celui du forum « ANNÉES MANQUANTES
AJOUTÉES » où le service annonce ses ajouts (« Ajouts juillet 2026 », « Ajouts Janvier 2026 », « Suivre les
Ajouts »…). Seul ce dernier est lu :

- `https://forum-archivesdepartementales.lenord.fr/app.php/feed/forum/138` (défaut, 15 entrées au relevé) ;
- ou, sur demande (`FORUM=html`), la page `viewforum.php?f=138`, annonces globales écartées.

Un passage lit `robots.txt` puis **une** de ces deux adresses, jamais les deux : si le flux échoue, le
signalement propose la page HTML pour le passage suivant. Sont extraits, pour dix fils au plus (quinze au
maximum) : le **titre** (borné à 120 caractères, nom du forum retiré), la **date** et le **lien** (sans jeton
de session). Ils sont consignés au journal comme « nouveautés AD59 à vérifier » ; `nouveau` distingue les
liens absents des passages précédents.

**`robots.txt` du forum : HTTP 404** (relevés du 27 novembre 2026). Aucune règle n'est donc déclarée, ce qui
n'est pas une autorisation explicite : la lecture reste modérée (deux requêtes par passage, intervalle de 10 s
et plafond de 20 requêtes par jour dans `politique_acces.py`, valeurs prudentes du plugin, sans référence
publiée). Le fichier est redemandé à chaque passage : s'il apparaît et interdit l'adresse, ou s'il est
illisible (erreur serveur), le forum n'est pas lu.

Le flux Atom transporte aussi l'auteur et le corps de chaque message. Le plugin ne les lit pas, ne les garde
pas et ne les met pas en cache ; seuls titre, date et lien sortent de l'analyse. Aucun compte, aucune
connexion, aucun fil ouvert. Un titre de fil n'est pas une source : c'est une piste à vérifier sur le site du
service avant de relancer une recherche.

## 3. Classeur 3 E et état de collection des recensements

**Ancienneté (sans réseau).** `veille_ad59.anciennete()` compare `releve_le` de `ad59_3e.json` et de
`ad59_recensements.json` à la date du jour : au-delà de **365 jours** (`SEUIL_JOURS`), ou si la date est
illisible, le référentiel est « à renouveler ». Le constat porte la source et l'empreinte SHA-256 du PDF
relevé, pour comparaison manuelle. `diagnostic` le reprend (contrôle `referentiels_ad59`, état `attention`).
Le seuil est un choix du plugin : le service a publié un classeur daté de janvier 2026 et annonce des ajouts
plusieurs fois par an ; aucune périodicité officielle n'a été trouvée.

**Classeur millésimé (une requête).** La page des nouveautés porte le lien du classeur courant. La veille en
extrait les liens `/document/classeur-3e-…` et les compare à la source de `ad59_3e.json` : `inchange`,
`nouveau` (un autre millésime est proposé) ou `non_verifie` (aucun lien : page modifiée). Un nouveau classeur
est **signalé, jamais téléchargé**. La même page lie des formulaires de recherche : un UUID inconnu du plugin
est signalé (`formulaires_inconnus` : fonds nouveau ou formulaire remplacé).

**Renouveler les référentiels** (étapes manuelles, hors veille) :

- classeur 3 E : télécharger le nouveau PDF, puis `scripts/generer_couverture_3e_ad59.py` avec `--source`,
  mettre à jour `couverture_3e.SOURCE` — [procédure](recherche-registres-ad59.md#classeur-3-e--cote-et-mise-en-ligne-prévue--374) ;
- recensements : `scripts/generer_couverture_recensements_ad59.py` — [procédure](recensements.md#renouvellement-du-référentiel) ;
- puis régénérer `docs/couverture-archives.md` (`scripts/generer_couverture_archives.py`).

## Hors périmètre

- `/oai-pmh`, interdit par le `robots.txt` du site des AD59 (qui n'exclut par ailleurs que `/private/` et
  `/user/`) ; aspiration des sitemaps de notices ;
- création de compte ou connexion au forum ; lecture des messages au-delà du titre et de la date ;
- téléchargement automatique d'un classeur ou d'un état de collection ;
- les autres services d'archives.

## Non vérifié

- Un formulaire `conforme` ne prouve pas que la recherche répond comme avant : ni les vocabulaires (communes,
  bureaux), ni les pages de résultats, ni les années réellement en ligne ne sont relus.
- Le `robots.txt` du site des AD59 n'est pas relu à chaque passage (relevé du 27 novembre 2026 : `/search/form/`
  et `/page/` non exclus) ; celui du forum l'est.
- Le contenu des annonces du forum n'est pas lu : ce qu'un fil ajoute exactement reste à lire sur le site.
- L'état de collection des recensements n'a pas de nom millésimé : seul son âge est signalé, pas un nouveau
  document.
- Le lien du classeur n'est cherché que sur la page des nouveautés ; s'il la quitte, la veille rend
  `non_verifie`.
- Les neuf contrats des matricules, de l'enregistrement, des hypothèques et du cadastre viennent des
  formulaires relevés pour #376 à #379 ; les trois autres ont été relevés pour #380. Un passage réel du
  27 novembre 2026 a trouvé les douze formulaires conformes, le classeur inchangé et le `robots.txt` du forum
  en 404 (seize requêtes au total pour l'ensemble du relevé).
- Le flux Atom liste des messages, pas des fils : une réponse (« Re: … ») y apparaît comme une entrée à part.

## Tests

`tests/test_veille_ad59.py`, sans réseau (respx, DNS simulé) : contrat aligné sur les UUID du code, fixtures
relevées conformes, dérives simulées (404, champ renommé, ajouté, disparu, titre, autre UUID), échec de l'hôte
sans requête suivante, refus de la politique réseau, mode hors ligne, flux Atom et page HTML, `robots.txt`
absent, interdit ou en erreur, classeur d'un autre millésime signalé sans téléchargement, référentiel de plus
de 365 jours signalé, passage complet à 15 requêtes sans image, notice ni paramètre. Fixtures
`tests/fixtures/ad59-veille-*` : pages publiques du 27 novembre 2026 réduites aux balises lues ; pseudonymes,
jeton de session et corps des messages du forum remplacés.
