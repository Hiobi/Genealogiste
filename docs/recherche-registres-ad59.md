# Recherche de registres AD59

Le module `sources/registres.py` lit une page HTML de recherche AD59, sans lancer le JavaScript ni
interroger une notice, le visualizer ou une image. Il recherche des **registres candidats** : leur présence
ne prouve pas qu'ils contiennent l'acte recherché. Un résultat négatif pour une commune, une année et un
filtre ne prouve pas l'absence générale de fonds numérisés.

## Contrat qualifié

Le [relevé public du 16 novembre 2026](https://archivesdepartementales.lenord.fr/search/results?formUuid=dc4e871d-0b62-41fb-9921-5ded573781b8&sort=date_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=SAINT-VAAST-EN-CAMBRESIS&2-date=1860)
a confirmé un résultat : cote `5 Mi 018 R 024`, ARK de registre `ark:/33518/jq9hpbzxnc72`, période
1831–1864, 954 médias. Le nom de commune et l'année figurent dans les paramètres GET observés :
`0-controlledAccessGeographicName[]` et `2-date`. Le formulaire porte l'identifiant
`dc4e871d-0b62-41fb-9921-5ded573781b8`. Le module conserve les paramètres observés `mode=list`,
`sort=date_asc`, `facet_media=image`.

Seul `AD59` est qualifié. La commune est mise en capitales et sans accents, sans déduire une autre
commune ; les traits d'union fournis sont conservés. L'année doit être un entier précis de 1 à 9999.
Les cases de filtre du formulaire GET portent `name=facet_typology` et les valeurs `Naissances`,
`Mariages`, `Décès` : ce sont les filtres utilisés pour `N`, `M`, `D`. `NMD` et le type vide conservent la
recherche sans filtre de typologie. `TD` (tables décennales) et `annee_fin` (intervalle) sont décrits
ci-dessous ; `REC` (recensements de population, #375), `RM` (registres matricules, #376), `SUCC` et `FD`
(tables des successions et fiches décès de l'enregistrement, #377), `HYP` (hypothèques, sous-série 4 Q, #378),
`CAD` (plans du cadastre, #379) plus bas.
Aucun nom ni identifiant de personne n'est envoyé ; `personne` sert uniquement à la garde de l'outil
et au journal local.

La réponse contient le titre, la cote, l'ARK de registre, son URL, les bornes d'années si le champ de date
les expose, et le nombre de vues s'il est affiché. Une information facultative absente reste `None`.
Les bornes ne sont déduites ni de l'année demandée ni du titre. Le lien ARK de vue sur la miniature
est distinct du lien de notice : il ne sert pas d'identifiant au registre retourné.

## Forme HTML observée

- `body#display-results`, `section#list-container`, puis `li.element-list` pour chaque registre.
- `div.intitup > a[href]` contient le lien de notice et `h2` son titre. Le lien doit désigner un ARK de
  registre AD59 sur l'origine officielle, sans identifiants d'authentification ni qualificatif de vue.
- `p.referenceCodes` contient la cote.
- La partie `div.content-sub-part` dont `h3` vaut `Date` expose la période dans `p`.
- `p.info-list-picture` expose le nombre de médias ; la réponse relevée annonçait 954.
- `span.result` expose le nombre total de résultats.
- `input#current-page[name=page]` expose la page courante et `max` la dernière page. Le champ appartient
  au formulaire GET : l'appel utilise `page=N` explicitement et ne suit aucune page automatiquement.
- `li.select-results-per-page > p.placeholder[title]` annonçait une taille de 20 résultats par page.
  Cette valeur est **lue dans la réponse**, sans constante supposée. Si ce champ est présent, taille,
  compteur, nombre de blocs et dernière page doivent correspondre. Sans ce champ, les contrôles
  minimaux refusent notamment une page unique non exhaustive et les pages fantômes.

La recherche [année 1200 sur la même commune](https://archivesdepartementales.lenord.fr/search/results?formUuid=dc4e871d-0b62-41fb-9921-5ded573781b8&sort=date_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=SAINT-VAAST-EN-CAMBRESIS&2-date=1200)
a confirmé la forme négative : `body#display-no-results`, puis `div.no-result` dans le conteneur de
liste, avec un message explicite. Le compteur et la pagination sont absents. L'absence de blocs de
résultats seule n'autorise donc pas à conclure à zéro résultat. Un négatif sur une page supérieure à 1
reste non qualifié et renvoie une erreur, plutôt qu'une absence globale de registre.

Le relevé du 16 novembre n'avait observé qu'une page positive ; celui du 18 novembre (ci-dessous) a observé
une vraie page 2 avec les mêmes attributs. Les scénarios à plusieurs pages restent testés sur fixtures
synthétiques construites à partir de ces attributs.

## Tables décennales et intervalles d'années — #221

Relevé public du 18 novembre 2026 (robots.txt inchangé, aucune protection rencontrée, une requête par
observation, sans image) :

- **Intervalle.** Le formulaire `dc4e871d-…` expose, à côté de l'année précise `2-date`, une
  « période » : `3-date_begin` et `3-date_end` (années, fin ≥ début). Pour Saint-Vaast-en-Cambrésis,
  [1790-1802](https://archivesdepartementales.lenord.fr/search/results?formUuid=dc4e871d-0b62-41fb-9921-5ded573781b8&sort=date_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=SAINT-VAAST-EN-CAMBRESIS&3-date_begin=1790&3-date_end=1802)
  a renvoyé deux registres dont la période **recoupe** l'intervalle : `5 Mi 018 R 022` BMS 1737-1790
  (`ark:/33518/jdtn31qz28ml`) et `5 Mi 018 R 023` NMD 1791-1830 (`ark:/33518/2klp0snfdtzj`). Le HTML de
  résultat est identique à celui de l'année précise ; la facette `facet_typology` s'y combine.
- **Page 2.** Lille, 1790-1802 : 50 résultats, `max="3"`, 20 par page ; `page=2` renvoie
  `value="2"` et 20 blocs. Une page au-delà de la dernière (Douai, 13 résultats, `page=2`) répond par une
  **redirection 302 vers `page=1`** : la page courante lue (1) diffère de la page demandée et l'outil renvoie
  une erreur, jamais un négatif.
- **Tables décennales.** La page éditoriale « Tables décennales » mène à un formulaire distinct,
  `25905104-0354-4e23-aea0-e3b68cf1f881`, dont le **seul champ est la commune** (ni date, ni type). Pour
  [Saint-Vaast-en-Cambrésis](https://archivesdepartementales.lenord.fr/search/results?formUuid=25905104-0354-4e23-aea0-e3b68cf1f881&sort=date_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=SAINT-VAAST-EN-CAMBRESIS) :
  9 tables, même HTML de liste, titres `COMMUNE / 1853-1862`, cotes `3E TD 547/07`, champ `Date` 1853-1862,
  nombre de médias, ARK de registre sur le lien de notice (`ark:/33518/xwkrg498c6qs`). Une commune sans
  table renvoie la même page négative `body#display-no-results`.

Contrat retenu :

- `annee_fin=0` (défaut) ou égal à `annee` : année précise (`2-date`), comportement inchangé.
  `annee < annee_fin ≤ 9999` : `3-date_begin`/`3-date_end`, sans filtrage local (le service filtre).
- `type_acte="TD"` : formulaire TD, commune et page seulement. La période `[annee, annee_fin or annee]`
  est appliquée **localement** à la page lue : une table est gardée si ses bornes affichées recoupent la
  période (`couvre_periode: true`) ou si ses bornes sont absentes (`couvre_periode: null`, à vérifier) ;
  les autres sont comptées dans `tables_hors_periode`. `total` reste le nombre de tables annoncé par le
  service pour la commune ; `page_suivante` permet de lire les tables suivantes.
- Négatif : aucune table de la page ne couvre la période, ou réponse négative explicite du service. Dans les
  deux cas l'enveloppe commune trace une entrée `negatif` au journal (y compris depuis le cache) et
  `recherche_negative` rappelle que cela ne prouve pas l'absence de l'acte.
- `annee_fin` fait partie de l'identité « déjà fait » des enquêtes et figure dans `requete`.

Reste à vérifier sur le service réel : une commune ayant plus de 20 tables (deuxième page de tables
décennales, non observée : les TD couvrent au plus 1792-1942) ; d'éventuelles tables à bornes non
numériques ; l'effet de paramètres de date ajoutés au formulaire TD (non envoyés, donc non qualifiés).

## Classeur 3 E : cote et mise en ligne prévue — #374

Les AD59 publient un état récapitulatif de leurs registres d'état civil, le « classeur 3 E » :
[`/document/classeur-3e-janvier-2026`](https://archivesdepartementales.lenord.fr/document/classeur-3e-janvier-2026)
(PDF de 195 pages, une ligne par volume). Colonnes lues : commune, cote, types d'actes, date de début / date de
fin, « Mis en ligne » ou « > AAAA » (année de mise en ligne prévue). Le référentiel
`referentiels/ad59_3e.json` en est la copie structurée : relevé du **27 novembre 2026**, empreinte SHA-256 du
PDF `1d54c2a9…5c5791`, 17 681 lignes, 17 679 volumes (2 doublons exacts écartés), 694 libellés de commune,
aucune ligne rejetée. 14 421 lignes sont « Mis en ligne », 3 260 portent une année prévue (2027 à 2051). Le
document ne contient aucune personne.

Malgré son nom, le classeur ne contient pas que des cotes `3 E <numéro>` : on y lit aussi `3 E <COMMUNE> <n>`,
`AC … GG …`, `E DEPOT …`, `EC SUP …`, `6 Mi …`, `J …`, et des types `BMS`, `B`, `S`, `PM`, `TD` à côté de `N`,
`M`, `D`, `NMD`. Cote et types sont gardés tels qu'écrits. Les bornes sont réduites à l'année (`debut`, `fin`) ;
quand la cellule porte un mois, un jour ou une valeur illisible, son texte est conservé dans `dates`. Sept lignes
ont une borne qui n'est pas devinée (`null`) : fin illisible ou antérieure au début (`1882 / 182`,
`1919 / 1914`) et trois volumes de Roubaix dont les dates ressemblent à des numéros de série de tableur
(`17167 / 17295`).

**Usage.** Pour AD59 seulement, et hors tables décennales, `archives_registres` ajoute `classeur_3e` à sa réponse
quand la recherche en ligne est vide ou quand un volume du classeur recoupe la période sans être en ligne.
Les clés d'avant #374 sont inchangées. `classeur_3e` donne `source`, `releve_le`, `communes` (libellés du
classeur retenus), `statut` (`connu` ou `inconnu_du_classeur`), `message`, `limite` et `volumes` : `commune`,
`cote`, `types`, `debut`, `fin`, `en_ligne`, `mise_en_ligne_prevue`, `recoupe_periode` (`null` si une borne est
illisible) et un `message` par volume :

- « pas en ligne avant AAAA ; consultation en salle de lecture » ;
- « en ligne selon le classeur mais absent de la recherche » (recherche vide : vérifier variantes et type) ;
- « en ligne selon le classeur et présent dans la recherche » ou « cote non reconnue parmi les résultats de
  cette page » quand la recherche a des résultats (comparaison des cotes, une page seulement).

Un volume hors couverture est « inconnu du classeur », jamais « inexistant ». Cas de référence : naissances de
Somain en 1926, cote `3 E 6298` (N 1926-1930), « > 2031 ». `prochaine_source` et `cotes_a_consulter` joignent
les mêmes cotes (`classeur_3e`) à la piste de l'acte pour BIRT, MARR et DEAT quand le lieu est dans le Nord
(département reconnu dans le libellé), que l'année est connue et que le classeur a un volume ; la liste des
pistes et leurs `cote_typique` ne changent pas.

La commune est comparée sans accents ni casse, traits d'union, apostrophes et espaces ignorés, `ST`/`STE`
développés ; « BASSEE (LA) » répond à « La Bassée », « LILLE (FIVES) » ou « BAILLEUL - LA CRECHE » répondent
aussi à la commune. Les types `N`, `M`, `D` retiennent aussi `B` et `S` (N : N ou B ; D : D ou S) ; un volume
sans lettre d'acte reconnue (`PM`, `T`) n'apparaît que sans filtre de type.

**Limites, non vérifié.**

- Le classeur est lu tel quel : ni sa complétude ni son exactitude ne sont contrôlées. Les fautes de saisie
  visibles sont conservées, pas corrigées.
- « > AAAA » est compris comme « pas en ligne avant AAAA » d'après l'en-tête « Mise en ligne en : ». Sur 3 253 des
  3 257 volumes concernés à fin connue, AAAA vaut l'année de fin + 101 ; cette règle n'est ni publiée ni utilisée.
- « consultation en salle de lecture » suppose que le volume est communicable : le vérifier avec
  `communicabilite`. Les conditions d'accès en salle n'ont pas été relevées.
- Deux observations du 27 novembre 2026 sur la recherche publique (une requête chacune, sans image, sans
  personne) : Somain, naissances, 1926 → page négative ; 1925 → un registre de cote `3 E 6297`, identique à
  celle du classeur. La correspondance des cotes n'a pas été contrôlée au-delà de ce cas ; les volumes anciens
  sont souvent en ligne sous une cote de microfilm (`5 Mi …`), d'où le message « cote non reconnue ».
- L'extraction repose sur le tableau du PDF (pdfplumber, `extract_tables`) : une autre mise en page du
  prochain classeur fera échouer le script plutôt que produire un référentiel faux.

**Renouvellement.** Le nom du document est millésimé (`classeur-3e-janvier-2026`) : un nouveau classeur aura une
autre URL, que rien ne signale au plugin. Le référentiel dérive donc avec le temps : un volume « > 2027 » peut
être en ligne après le relevé, et `releve_le` est rendu avec chaque constat pour en juger. Pour le renouveler :

```bash
# 1. télécharger (étape explicite : robots.txt contrôlé, une seule requête, fichier neuf)
uv --directory mcp run python -I ../scripts/generer_couverture_3e_ad59.py /tmp/classeur/3e.pdf \
    --telecharger --source https://archivesdepartementales.lenord.fr/document/classeur-3e-<millésime>
# ou, PDF déjà présent (aucun réseau) :
uv --directory mcp run python -I ../scripts/generer_couverture_3e_ad59.py /tmp/classeur/3e.pdf --releve AAAA-MM-JJ
```

puis mettre à jour `couverture_3e.SOURCE`, les chiffres ci-dessus, la fixture et les tests si des volumes cités
ont changé, et régénérer `docs/couverture-archives.md`. Le PDF est une donnée non fiable : il est lu, jamais
exécuté (`python -I`, dossier dédié). Le script refuse le référentiel si plus de 0,5 % des lignes sont
inexploitables (colonnes, cote ou statut non reconnus) ou plus de 1 % ont une borne illisible ; `--check`
compare le PDF au référentiel livré sans l'écrire. L'option `--telecharger` n'a pas été exécutée sur le service
réel : le PDF du relevé a été téléchargé à part, puis lu par le script.

Tests : `tests/test_couverture_3e.py`, sans réseau. `tests/fixtures/ad59-classeur-3e-extrait.pdf` reprend sans
modification les pages 1, 4, 11, 74 et 166 du PDF public (454 lignes).

## Recensements de population : `type_acte="REC"` — #375

Relevé public du 27 novembre 2026 (robots.txt inchangé, aucune protection rencontrée, une requête par
observation, sans image). La page « Recensements de population » mène à un troisième formulaire,
`f0366f8a-2ef6-4cf2-b47b-6dec4a19e99f`, dont le seul champ est la commune (ni date, ni type), comme celui des
tables décennales. Pour
[Somain](https://archivesdepartementales.lenord.fr/search/results?formUuid=f0366f8a-2ef6-4cf2-b47b-6dec4a19e99f&sort=date_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=SOMAIN) :
4 résultats, même HTML de liste ; titre `SOMAIN` (sans millésime), champ `Date` d'une seule année, cotes
`M473 063 / 10 SOMAIN` (1901), `M 474 / 572` (1906, `ark:/33518/h2tprnqlw3dj`, 225 médias), `M474 5 / 19 SOMAIN`
(1931), `M474 7 / 25 SOMAIN` (1946). La ligne « Contexte : Recensement de 1906 » n'est pas lue. Commune
inexistante : même page négative. Buysscheure, `page=2` : 6 résultats sur 26, `max="2"`, 20 par page.

Contrat retenu : `type_acte="REC"` (AD59 seulement) envoie la commune et la page au formulaire des
recensements ; la période est filtrée localement comme pour `TD` (`couvre_periode`, `registres_hors_periode`) ;
titre, cote, ARK, bornes et nombre de vues sont rendus comme pour un registre. Quand la recherche est vide ou
qu'un recensement n'est qu'en salle de lecture, `couverture_recensements` joint la cote et le mode d'accès tirés
de l'état de la collection du service. Référentiel, cotes, Socface, limites et renouvellement :
[recensements](recensements.md).

## Registres matricules : `type_acte="RM"` — #376

Relevé public du 27 novembre 2026 (robots.txt inchangé : `/private/`, `/oai-pmh`, `/user/` ; aucune protection
rencontrée ; une requête par observation, sans image, sans notice, sans nom de personne). La page
[`/page/matricules-militaires`](https://archivesdepartementales.lenord.fr/page/matricules-militaires) mène à deux
formulaires de la série 1 R, lus avec `mnesys.lire_formulaire` :

| | Tables des états signalétiques et des services militaires | Fiches des états signalétiques et des services militaires |
|---|---|---|
| Formulaire | `0d3ab9ff-3258-4541-bf65-c3094fb024a0` | `9d12049e-510c-4c14-ad31-0fc5487c199c` |
| Bureau | `0-controlledAccessGeographicName[]` | `0-controlledAccessGeographicName[]` |
| Vocabulaire | `AVESNES`, `CAMBRAI`, `DUNKERQUE`, `LILLE`, `VALENCIENNES`, `VALENCIENNES-DOUAI`, `VOIR TOUS BUREAUX [1931-1940]` | les six mêmes bureaux, sans « VOIR TOUS BUREAUX » |
| Date | « Période (facultatif) » `1-date_begin` / `1-date_end`, « Ou année précise » `2-date` | `1-date` seul : « Facultatif : Année (entre 1867 et 1923 / Valenciennes-Douai à partir de 1908) » |
| Résultats sans critère | 384 (revu) | 1 762 (relevé de l'issue #376, non revu) |

Aucun champ commune ni typologie : les clés sont le **bureau de recrutement** et la **classe** (année de
naissance + 20). Observations, une requête chacune :

- [tables, classe 1890](https://archivesdepartementales.lenord.fr/search/results?formUuid=0d3ab9ff-3258-4541-bf65-c3094fb024a0&sort=date_asc&mode=list&facet_media=image&2-date=1890) : 5 résultats, une table par bureau, titre `1890 : LILLE`, champ
  `Date` 1890, cotes `1R 02273` (Lille, 121 médias), `1R 02261` (Dunkerque), `1R 02255` (Cambrai), `1R 02249`
  (Avesnes, `ark:/33518/50hrtbnjdvcq`, 79 médias), `1R 02278` (Valenciennes) ; contexte « Tables des registres
  militaires ». Avec le bureau `AVESNES` : la seule table d'Avesnes.
- [tables, Avesnes, 1889-1891](https://archivesdepartementales.lenord.fr/search/results?formUuid=0d3ab9ff-3258-4541-bf65-c3094fb024a0&sort=date_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=AVESNES&1-date_begin=1889&1-date_end=1891) :
  3 tables, `1R 02213`, `1R 02249`, `1R 02283`, dans l'ordre des années.
- [fiches, classe 1890](https://archivesdepartementales.lenord.fr/search/results?formUuid=9d12049e-510c-4c14-ad31-0fc5487c199c&sort=date_asc&mode=list&facet_media=image&1-date=1890) : 30 résultats sur 2 pages de 20 ; titres `Volume 3`,
  `Volume 7 (3001-2500)` (tel qu'affiché), `Volume 11 (5001-5446)` ; cotes de `1R 2244` à `1R 2277` (les numéros des cinq tables s'y intercalent) ; 147 à 686
  médias par volume. Le bureau n'est pas dans le titre mais dans la ligne « Contexte : Registres numérisés des
  matricules militaires (Dunkerque) ». `page=2` : 10 résultats, `value="2"`, `max="2"`. Avec le bureau
  `AVESNES` : 5 volumes, `1R 2244` à `1R 2248` (`ark:/33518/1kcdl289b36g` pour le volume 1, 569 médias).
- Négatif (Avesnes, année 1200) pour chacun des deux formulaires : même page `body#display-no-results`.
- Une liste des tables sans critère (première page, 20 résultats) contenait les classes 1870 à 1930, dont 1928
  (Valenciennes, `1R 03918`) et 1930 (Cambrai, `1R 03986`) : les tables en ligne dépassent donc 1923. L'issue #376
  cite une table de 1865 (Avesnes, `1R 01750`), non revue ici.

Les cotes des tables sont écrites `1R 02249` (cinq chiffres), celles des volumes `1R 2244` : elles sont rendues
telles qu'affichées, sans normalisation.

**Contrat retenu.** `archives_registres(service="AD59", commune=<bureau ou "">, annee=<classe>, type_acte="RM")`
ne change pas de signature ; les clés existantes de la réponse gardent leur sens.

- Les deux formulaires sont lus en ligne (une requête chacun, en cache une semaine) : noms des champs et
  vocabulaire des bureaux viennent du formulaire, pas d'une liste recopiée. Un formulaire sans champ de bureau ou
  d'année est une erreur.
- `commune` = bureau, **facultatif**, mis en capitales sans accents puis choisi dans le vocabulaire de chaque
  formulaire (`mnesys.choisir_commune`). Bureau inconnu des deux formulaires (une commune comme « Somain », ou
  « Douai » seul) ou ambigu : erreur avant toute recherche, qui liste les valeurs proposées. Valeur propre à un
  formulaire (`VOIR TOUS BUREAUX [1931-1940]`) : seul ce formulaire est interrogé.
- **Classe précise** (`annee_fin=0` ou égal à `annee`) : les deux formulaires sont interrogés, une page chacun
  (`2-date` pour les tables, `1-date` pour les fiches). C'est la règle déterministe qui remplace un paramètre de
  choix : la réponse rend les deux catégories, distinguées.
- **Intervalle** (`annee < annee_fin`) : les tables seules (`1-date_begin` / `1-date_end`). Le formulaire des
  fiches n'a pas de période ; un filtre local supposerait de feuilleter des dizaines de pages (1 762 volumes)
  et n'est pas fait : `matricules.fiches.message` demande de relancer classe par classe.
- `resultats` : les tables d'abord, puis les fiches ; chaque résultat garde `titre`, `cote`, `ark`, `url`,
  `bornes`, `nb_vues` et reçoit `categorie` (`tables` ou `fiches`) et `contexte` (texte de la ligne « Contexte »,
  qui porte le bureau des fiches ; `null` si absent). `total` additionne les totaux lus ; `page_suivante` vaut
  `page + 1` dès qu'une catégorie a une page suivante.
- `matricules` (ajout) : `releve_le`, `lecture`, et pour `tables` et `fiches` : `formulaire`, `interroge`,
  `bureau` (valeur envoyée), `total`, `page_suivante`, `bureaux` (vocabulaire lu) et, s'il y a lieu, `message`.
- Page > 1 : les deux formulaires reçoivent `page=N`. Une catégorie dont la réponse ne correspond pas à la page
  demandée est marquée « Aucune page N lue pour cette catégorie », sans rien conclure ; si aucune catégorie ne
  rend la page demandée, l'appel est une erreur, comme pour l'état civil.
- Négatif : `recherche_negative` seulement quand aucune catégorie n'a de résultat ; une catégorie vide porte son
  propre `message`, et celui des fiches rappelle les classes annoncées par le formulaire (1867 à 1923,
  Valenciennes-Douai à partir de 1908). Ce libellé borne ce qui est en ligne, pas ce qui existe.
- Ni `classeur_3e` ni `couverture_recensements` ne sont joints. Aucun nom ni identifiant de personne n'est envoyé.
- Un appel `RM` AD59 fait donc au plus deux recherches (une par formulaire), chacune tentée une seule fois ; une
  panne ou un défi anti-robot sur l'une arrête l'appel.

**Lecture.** D'après les intitulés des résultats seulement : une table alphabétique par classe et par bureau,
et des volumes d'états signalétiques par bureau, parfois titrés d'une tranche de numéros matricules. La démarche
attendue est table, puis numéro matricule, puis volume ; elle n'a pas été vérifiée sur les vues, que ce relevé
n'a pas ouvertes.

**Classe.** `fr_sources.classe_recrutement(annee_naissance)` rend l'année de naissance + 20, règle déjà
affirmée par le dépôt ; engagés volontaires, ajournés et classes appelées par anticipation ne sont pas traités.
Pour un fait de naissance daté dans le Nord, `prochaine_source` et `cotes_a_consulter` joignent
`matricules_ad59` (`classe`, appel `archives_registres` à lancer, note) à la piste « registre matricule ».
Pour un autre fait (MILI, EMIG), la date n'est pas une naissance : aucune classe n'est calculée.

**Cotes.** Aucune cote `1R` n'est ajoutée à `cotes_a_consulter` : il n'existe pas de référentiel daté des cotes
de la sous-série (les 384 tables et 1 762 volumes n'ont pas été relevés, ce qui aurait demandé une centaine de
requêtes). `cote_typique` reste l'orientation générale ; la cote réelle est celle de la réponse d'`archives_registres`.

**Communicabilité.** `communicabilite("matricule")` est inchangé : 120 ans après la naissance (ou 25 ans après
le décès). La dernière classe annoncée pour les fiches, 1923, correspond à des hommes nés en 1903, communicables
depuis 2024 selon cette règle. Les tables alphabétiques en ligne vont au-delà (1928, 1930 observées) : la règle
de l'outil vise le registre matricule, pas sa table ; le régime des tables n'a pas été vérifié auprès du service.

**Non vérifié.**

- Le contenu des tables et des volumes (aucune vue ouverte) ; `archives_naviguer`, `archives_planche` et
  `archive_image` sur ces ARK : non testés.
- Les bornes réelles des tables (première et dernière classe), ce que renvoie `VOIR TOUS BUREAUX [1931-1940]`,
  et les classes de `VALENCIENNES-DOUAI` par rapport à `VALENCIENNES`.
- Une page au-delà de la dernière pour ces deux formulaires : la redirection vers `page=1` n'a été observée que
  sur le formulaire d'état civil (#221).
- Une deuxième page de tables (plus de 20 tables : intervalle large sans bureau).
- La stabilité des identifiants de formulaire et du vocabulaire (suivi : #380) ; le lien entre une commune et
  son bureau de recrutement, que le plugin ne déduit pas.
- La recette réelle (`test_registres_live.py`) n'a pas de cas `RM` ; le relevé a été fait à la main, hors outil.

Tests : `tests/test_matricules_ad59.py`, sans réseau.

## Enregistrement : `type_acte="SUCC"` et `type_acte="FD"` — #377

Relevé public du 27 novembre 2026 (robots.txt relu : `/private/`, `/oai-pmh`, `/user/` ; aucune protection
rencontrée ; une requête par observation, sans image, sans notice, sans nom de personne). La page
[`/page/tables-des-successions-et-absences-fiches-deces`](https://archivesdepartementales.lenord.fr/page/tables-des-successions-et-absences-fiches-deces)
mène à deux formulaires, lus avec `mnesys.lire_formulaire` :

| | Tables des successions et absences (3 Q) | Fiches décès (W) |
|---|---|---|
| Formulaire | `6eaeac65-9e1b-43ea-bc9f-902abd458466` | `4e904e28-8a75-4be1-b9f6-b4138afe4956` |
| Bureau | `0-controlledAccessGeographicName[]` | `0-controlledAccessGeographicName[]` |
| Vocabulaire | 56 valeurs : `ARLEUX` … `WORMHOUT`, dont `LILLE`, `LILLE (1er bureau)`, `LILLE (2e bureau)`, `LILLE (3e bureau)`, `ROUBAIX`, `ROUBAIX (Canton)`, `ROUBAIX (Ville)`, quatre `VALENCIENNES (…)` sans forme nue | 28 valeurs, d'un autre découpage : `LILLE (Centre)`, `LILLE (Est)`, `LILLE (Haubourdin)`, `DOUAI (Nord-Ouest-Est)`, `DENAIN (Canton)`, `AVESNES`… |
| Date | « Période (facultatif) » `1-date_begin` / `1-date_end`, « Année précise (facultatif) » `2-date` | `1-date` seul : « Année précise entre 1969 et 1975 (facultatif) » |
| Tri par défaut du formulaire | `referencecode_asc` | `referencecode_asc` |
| Résultats sans critère | 1 988 (relevé de l'issue #377, non revu) | 1 478 (relevé de l'issue #377, non revu) |

La clé est le **bureau de l'enregistrement**, pas la commune : aucun champ commune ni typologie. Les deux
vocabulaires diffèrent ; ils sont lus en ligne et ne sont pas recopiés dans le code. Observations, une requête
chacune :

- [tables, Steenvoorde, 1791-1803](https://archivesdepartementales.lenord.fr/search/results?formUuid=6eaeac65-9e1b-43ea-bc9f-902abd458466&sort=date_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=STEENVOORDE&1-date_begin=1791&1-date_end=1803) :
  2 résultats, titres `STEENVOORDE / 3Q - 516 / 1 [1791 - An 12]` (cote `3Q - 516 / 1`,
  `ark:/33518/5hnwpt8xqz67`, champ `Date` 1791-1803, 70 médias) et `STEENVOORDE / 3Q - 516 / 2 [An 12 - 1811]`
  (`ark:/33518/jqwc3pfb0285`, 1803-1811, 74 médias) ; contexte « Tables des successions et absences (cote 3Q) ».
- Tables, Steenvoorde, année 1800 : le même volume 1791-An 12, que l'année soit envoyée en `2-date=1800` ou en
  `1-date_begin=1800&1-date_end=1800`. Sur ce cas, l'année précise trouve donc le volume pluriannuel ; ce n'est
  pas vrai partout (AD91, relevé du 18 novembre 2026), et le module envoie la période.
- Tables, Lille, 1791-1969, `page=2` : 20 résultats sur 67, `value="2"`, `max="4"`, 20 par page ; titres datés
  au jour (`LILLE / 3Q - 338 / 29 [01/10/1841 - 15/07/1842]`), champ `Date` réduit aux années (1841-1842), 169 à
  198 médias. La valeur `LILLE` ne renvoie sur cette page que des titres `LILLE / …`.
- Tables, Steenvoorde, 1791-1969, `page=2` : réponse 302 vers `page=1&resultsPerPage=20` (une seule page de
  résultats). Même redirection pour les fiches (Lille Centre, 1969, `page=2`).
- [fiches décès, Lille (Centre), 1969](https://archivesdepartementales.lenord.fr/search/results?formUuid=4e904e28-8a75-4be1-b9f6-b4138afe4956&sort=referencecode_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=LILLE%20%28Centre%29&1-date=1969) :
  6 résultats, un volume par tranche de lettres, `LILLE (Centre) [1969] A - C` (cote `2571 W 01`) à
  `LILLE (Centre) [1969] T - Z` (`2571 W 06`), dont `L - M` : `2571 W 04`, `ark:/33518/qkwfpghmn457`, 296 médias ;
  champ `Date` 1969 ; contexte tronqué par le site : « Fiches Décès (W) : Accès aux fiches de + de 50 ans… ».
  Avec `sort=date_asc`, les six volumes d'une même année sortent dans le désordre ; avec le tri du formulaire
  (`referencecode_asc`), dans l'ordre des lettres.
- Négatif (Steenvoorde 1200 pour les tables, Avesnes 1200 pour les fiches) : même page `body#display-no-results`.

**Ce que dit le service** (textes de la page et du formulaire des tables, relus le 27 novembre 2026, résumés) :
l'ensemble des tables des successions et absences conservées est en ligne, sur une période d'au plus 1791-1968,
l'année de fin variant selon les bureaux ; les tables, alphabétiques, portent selon les époques profession,
domicile et âge du défunt, date du décès, situation de famille et date de la déclaration de succession s'il y
en a une, et couvrent un ressort plus large que la commune ; les fiches décès en sont la suite, classées par
année de décès puis par ordre alphabétique, et renvoient au numéro de la déclaration de succession. Le fil du
forum du service cité par l'issue n'a pas été relu et n'est pas utilisé ici.

**Contrat retenu.** La signature d'`archives_registres` ne change pas ; aucun outil MCP n'est ajouté.

- `type_acte="SUCC"` vaut désormais pour AD59 : `commune` = bureau de l'enregistrement, **obligatoire** comme
  pour `SUCC` sur les autres services ; `annee` et `annee_fin` = période, envoyée dans `1-date_begin` /
  `1-date_end` même pour une seule année (règle déjà suivie ailleurs) ; tri `date_asc`. Aucun filtre local.
- `type_acte="FD"` (fiches décès de l'enregistrement, AD59 seulement) : `commune` = bureau, obligatoire ;
  `annee` = année du décès, envoyée dans `1-date` ; tri `referencecode_asc`. Un intervalle (`annee_fin`) n'envoie
  que le bureau : la période est filtrée localement sur les bornes affichées (`couvre_periode`,
  `registres_hors_periode`), comme pour `TD` et `REC`. Pour un autre service, `FD` est refusé avant toute
  requête, son formulaire n'étant pas relevé.
- Bureau : mis en capitales sans accents, puis pris dans le vocabulaire lu (`mnesys.choisir_commune`) ; une
  valeur du formulaire saisie telle quelle (« Lille (Centre) », « Valenciennes (Ville) ») est reconnue malgré la
  casse. Bureau inconnu (une commune comme « Somain ») : erreur avant toute recherche, avec la liste des bureaux
  du formulaire. Bureau ambigu (« Valenciennes » pour les tables, « Lille » pour les fiches) : erreur qui liste
  les valeurs. « Lille » pour les tables désigne la valeur sans qualificatif `LILLE` ; `autres_bureaux` signale
  alors `LILLE (1er bureau)`, `LILLE (2e bureau)`, `LILLE (3e bureau)`, à interroger à part.
- Mêmes garde-fous que `RM` et `REC` : hôte et NAAN `33518` contrôlés sur chaque lien de notice, une page par
  appel, `page_suivante` explicite, une seule tentative de recherche, page hors bornes en erreur.
- `resultats` : `titre`, `cote`, `ark`, `url`, `bornes`, `nb_vues` et `contexte` (ligne « Contexte »).
  `commune_service` rend la valeur de bureau envoyée. `successions` ou `fiches_deces` (ajouts) : `releve_le`,
  `formulaire`, `bureau`, `autres_bureaux`, `reference`, `periode_annoncee`, `lecture`.
- Négatif : `recherche_negative` rappelle ce que le service annonce en ligne et qu'un résultat vide ne prouve
  ni l'absence d'un décès ni celle d'une succession. Ni `classeur_3e`, ni `couverture_recensements`, ni
  `matricules` ne sont joints. Aucun nom ni identifiant de personne n'est envoyé.

**Communicabilité des fiches décès.** La page du service dit, en substance, que seules les fiches décès de plus
de cinquante ans sont mises en ligne pour respecter les délais de communicabilité du code du patrimoine, d'où
une recherche possible jusqu'en 1975. C'est la seule source de ce délai : elle ne cite pas d'article. Dans le
dépôt, ce délai correspond au type existant `vie_privee` de `communicabilite` (50 ans à compter du document) ;
aucun type n'a été ajouté et `communicabilite` n'est pas modifié. En conséquence :

- une réponse `FD` porte toujours `avertissement_communicabilite` (ne pas tenir les fiches pour librement
  communicables ; délai affirmé par le service, non vérifié par le plugin ; héritiers peut-être vivants, contenu
  non lu) et `fiches_deces.communicabilite` : `type_document` (`vie_privee`), `delai_annees` (50), `source`,
  `releve_le`, `selon_le_service`, `non_verifie`, `periode_demandee_communicable_a_partir_de`,
  `periode_demandee_communicable`, `fiches_ecartees` ;
- chaque résultat reçoit `communicable_a_partir_de` (dernière année affichée + 51, même calcul que
  `communicabilite`) ; un résultat dont ce délai n'est pas échu est **écarté** de la réponse et compté
  (`fiches_ecartees`). Le service n'en publie pas ; la règle protège d'un changement de sa part ;
- un résultat sans date lisible est gardé avec `communicable_a_partir_de: null`.

**Non établi** : l'article du code du patrimoine applicable et le point de départ exact du délai (année du
décès, de la fiche ou de clôture du fichier) ; la nature et l'origine du fichier (les cotes en W indiquent un
versement contemporain, rien de plus n'a été lu) ; le régime des tables des successions elles-mêmes, hors
périmètre (le dépôt les dit librement communicables d'après un autre service, voir
[archives](archives.md)) ; la présence de personnes vivantes sur les fiches.

**Orientation.** Pour un décès ou une filiation dans le Nord, `prochaine_source` et `cotes_a_consulter` joignent
`successions_ad59` à la piste « table des successions et absences » : appel `SUCC` à lancer (décès jusqu'en
1968), `fiches_deces` avec son avertissement (décès de 1969 à 1975), note. Le bureau n'est pas déduit de la
commune ; l'année n'est calculée que pour un fait de décès. Aucune cote 3 Q ou W n'y figure : il n'existe pas de
référentiel local, la cote vient de la réponse d'`archives_registres`.

**Non vérifié.**

- Le contenu des tables et des fiches (aucune vue ouverte) ; `archives_naviguer`, `archives_planche` et
  `archive_image` sur ces ARK : non testés.
- Le ressort de chaque bureau, son évolution, et ce que distinguent `LILLE` et `LILLE (1er bureau)`, ou les
  découpages `(Ville)` / `(Canton)` : le plugin ne rattache aucune commune à un bureau.
- La période réellement couverte par bureau ; les totaux sans critère (1 988 et 1 478, relevé de l'issue).
- Une deuxième page de fiches décès (aucun bureau observé n'en a pour une année) ; le filtre local d'un
  intervalle de fiches n'a été éprouvé que sur la page relevée de 1969.
- Le tri `referencecode_asc` sur plusieurs pages ; la stabilité des identifiants de formulaire et des
  vocabulaires (suivi : #380).
- La recette réelle (`test_registres_live.py`) n'a pas de cas `SUCC` ni `FD` ; le relevé a été fait à la main,
  hors outil.

Tests : `tests/test_successions_ad59.py`, sans réseau.

## Hypothèques : `type_acte="HYP"` — #378

Relevé public du 27 novembre 2026 (robots.txt relu : `/private/`, `/oai-pmh`, `/user/` ; aucune protection
rencontrée ; une requête par observation, sans image, sans notice, sans nom de personne ; quinze requêtes en
tout : robots.txt, la page, trois formulaires, dix pages de résultats). La page
[`/page/tables-et-repertoires-des-hypotheques`](https://archivesdepartementales.lenord.fr/page/tables-et-repertoires-des-hypotheques)
mène à trois formulaires de la sous-série 4 Q, lus avec `mnesys.lire_formulaire` :

| | Indicateur | Tables alphabétiques du répertoire des formalités hypothécaires | Répertoires des formalités hypothécaires |
|---|---|---|---|
| Formulaire | `02ec9ec7-856b-47f7-a59f-f9716d6823a3` | `50d53c90-a6c8-46f9-886c-e75fa91a60cb` | `330c559b-0684-4649-b7e8-7d1123a83433` |
| Bureau | `0-controlledAccessGeographicName[]` (« Bureau ») | idem | idem |
| Vocabulaire | `Avesnes`, `Cambrai`, `Douai`, `Dunkerque`, `Hazebrouck`, `Lille`, `Valenciennes` | les sept mêmes | les sept mêmes |
| Date | aucun champ | aucun champ | aucun champ |
| Tri par défaut du formulaire | `referencecode_asc` | `referencecode_asc` | `referencecode_asc` |
| Résultats sans critère | 64 (relevé de l'issue #378, non revu) | 1 652 (idem) | 3 693 (idem) |

Le seul champ est le **bureau des hypothèques** ; les sept valeurs sont celles des sept conservations que cite
la page. Le vocabulaire ne distingue pas les subdivisions d'un bureau : « Lille (avant 1900) », « Lille (1) »,
« Lille (2) », « Lille 2 (1901-1955) » ou « Cambrai (serie secondaire) » n'existent que dans les titres des
volumes. Observations, une requête chacune, tri `referencecode_asc` :

- [indicateur, Cambrai](https://archivesdepartementales.lenord.fr/search/results?formUuid=02ec9ec7-856b-47f7-a59f-f9716d6823a3&sort=referencecode_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=Cambrai) :
  5 résultats, `Cambrai : 4Q 63 / 001 (ABADEAU - CRETE)` (cote `4Q 63 / 001`, `ark:/33518/jv3qf19tskbh`,
  202 médias) à `Cambrai : 4Q 63 / 005 (SABY - ZYGMONT)` ; contexte « Tableau indicateur (cote 4Q) ». Aucun
  champ `Date` dans les résultats : `bornes` reste `null`.
- Indicateur, Lille : 23 résultats sur 2 pages de 20 ; six volumes `Lille (avant 1900) : 4Q 79 / 001` à `006`
  sans plage, `Lille (1) : 4Q 80 / 001 ((unique) Sociétés)` et `4Q 80 / 002 (PIRET - ZYLBERBERG)`, puis
  `Lille (2) : 4Q 83 / 001 (AAN - BERTAUT)` à `4Q 83 / 015 (VETREZ - ZYWIOL)`. `page=2` : 3 résultats,
  `value="2"`, `max="2"`.
- Indicateur, Valenciennes : 5 résultats, `4Q 86 / 003 (GUERIN - MENET)`, `004 (MENEZ - TESSE)`,
  `005 (TESSIER - ZYDOREK)`, puis `006 (ABADI - FOY)` et `007 (FOYER - LARDENOIS)` : deux suites alphabétiques
  sous le même libellé de bureau, la seconde incomplète en ligne. Rien dans les titres ne les date.
- [tables, Cambrai](https://archivesdepartementales.lenord.fr/search/results?formUuid=50d53c90-a6c8-46f9-886c-e75fa91a60cb&sort=referencecode_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=Cambrai) :
  345 résultats sur 18 pages ; `Cambrai (serie secondaire) : 4Q 64 / 002 (Ai - Bailleux)`
  (`ark:/33518/7rqw24jctvkd`, 198 médias)… ; contexte « Tables alphabétiques du répertoire (cote 4Q) ». Titres
  saisis à la main : `(Baillez- -Basquin)`, `(briatte - Bricout)` ; plages non strictement croissantes :
  `(Baurin - Benit)` puis `(Benicourt - Besnard)`, `(Blutte - Boniface)` puis `(Boniface - Boudin)`.
- Tables, Lille : 626 résultats sur 32 pages ; page 1 : `Lille (avant 1900) : 4Q 78 / 001 (Aa - Alluin)`… ;
  `page=32` : 6 résultats, `Lille 2 (1901-1955) : 4Q 84 / 197 (Vissault - Vrau)` à
  `4Q 84 / 202 (Zuglian - Zywiol)`.
- [répertoires, Avesnes](https://archivesdepartementales.lenord.fr/search/results?formUuid=330c559b-0684-4649-b7e8-7d1123a83433&sort=referencecode_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=Avesnes) :
  570 résultats sur 29 pages ; `Avesnes : 4Q 62 / 001` (`ark:/33518/0tm75kcjfnsv`, 61 médias) à `4Q 62 / 020`
  en page 1, `021` à `040` en page 2 ; une centaine de médias par volume ; aucune plage ; contexte « Répertoires
  des formalités hypothécaires (cote 4Q) ».
- Négatif : obtenu sur l'indicateur avec une valeur de bureau inexistante (`Somain`), même page
  `body#display-no-results`. Aucun bureau réel observé n'est vide.

**Ce que dit le service** (page relue le 27 novembre 2026, résumée). La conservation des hypothèques
enregistrait l'inscription hypothécaire (gage d'un emprunt sur un immeuble) et la transcription des actes, le
plus souvent notariés, de mutation d'un immeuble (achat, vente, donation). Les AD59 conservent les archives des
bureaux de l'an VII (1799) à 1955 ; après 1955, elles sont dans les services de la publicité foncière. Sept
conservations avant 1955, une par arrondissement ; pour Valenciennes, les registres de 1800-1940 ont été détruits
pendant la Seconde Guerre mondiale. La recherche se fait **uniquement par nom de propriétaire** (par adresse du
bien : seulement après 1956, hors des AD ; sinon passer d'abord par le cadastre, en salle de lecture). Deux
familles de registres : registres d'ordre (les trois catégories en ligne) et registres de formalités (en salle
de lecture). Les images en ligne servent à préparer la venue en salle ; qui connaît déjà le volume et le numéro
de la transcription (portés par l'acte notarié) va directement en salle.

**Méthode : indicateur → table alphabétique → répertoire**, d'après cette page :

1. le **registre indicateur** de la table alphabétique donne les noms de famille des propriétaires par ordre
   alphabétique, sans prénoms : il oriente vers la table ;
2. la **table alphabétique** donne les noms classés par ordre alphabétique « et organisés phonétiquement »,
   avec prénoms et parfois date de naissance, conjoint, profession (non pris en compte dans le classement) : on
   y relève le numéro de case du propriétaire ;
3. le **répertoire des formalités** est classé par numéro de case, une case étant le compte d'un propriétaire :
   on y relève les numéros de volume et d'acte ;
4. les registres de transcription et d'inscription se consultent en salle de lecture.

Ce que renvoie exactement l'indicateur (un numéro de volume de table, de page ?) n'est pas dit par la page et
n'a pas été lu sur les vues.

**Contrat retenu.** La signature d'`archives_registres` ne change pas ; aucun outil MCP n'est ajouté ; les clés
existantes gardent leur sens.

- **Code** : `HYP`, dans la lignée de `RM`, `SUCC`, `FD`, `REC` (abréviation du fonds, sans numéro de série).
- **Catégorie, règle déterministe** : `HYP` interroge les trois formulaires, une page chacun, et rend les trois
  catégories distinguées (comme `RM`) : c'est la vue d'ensemble d'un bureau. `HYPI`, `HYPT`, `HYPR`
  n'interrogent que l'indicateur, les tables ou les répertoires. Ces trois variantes existent parce que les
  listes n'ont pas la même longueur (Lille : 2 pages d'indicateur, 32 de tables ; Avesnes : 29 de répertoires) :
  feuilleter les tables de Lille avec `HYP` enverrait à chaque page deux requêtes sans objet. Elles ne changent pas la signature ; ce
  sont des valeurs de `type_acte`.
- **Bureau** : `commune` = bureau des hypothèques, **obligatoire**, mis en capitales sans accents puis pris dans
  le vocabulaire lu en ligne (valeur exacte malgré la casse, sinon `mnesys.choisir_commune`). Bureau inconnu
  (« Somain », « Lille 2 », « Lille (avant 1900) ») : erreur avant toute recherche, qui liste les valeurs et
  rappelle qu'un libellé de titre n'est pas un bureau. Bureau ambigu : erreur qui liste les candidates (cas
  absent du vocabulaire relevé). `autres_bureaux` (par catégorie) signale les autres valeurs de même nom, comme
  pour `SUCC` ; il est vide avec le vocabulaire relevé. Les subdivisions réelles se lisent dans
  `hypotheques.bureaux_titres` (libellés distincts de la page) et `bureau_titre` de chaque résultat.
- **Période** : aucun champ de date, ni dans les formulaires ni dans les résultats. `annee` et `annee_fin` ne
  sont pas envoyées. Elles n'écartent que les volumes dont le titre porte une période, dans les deux formes
  relevées : « (avant 1900) » → `periode_titre: [null, 1899]`, « (1901-1955) » → `[1901, 1955]`. Ces volumes
  reçoivent `couvre_periode` `true` ou sont écartés et comptés (`registres_hors_periode`) ; les autres gardent
  `couvre_periode: null` et sont toujours rendus. « (1) », « (2) » et « serie secondaire » ne sont pas
  interprétés. `bornes` reste `null` (champ `Date` absent) : rien n'est déduit du titre dans cette clé.
- **Résultats** : indicateur, puis tables, puis répertoires ; chaque résultat garde `titre`, `cote`, `ark`,
  `url`, `bornes`, `nb_vues` et reçoit `categorie`, `contexte`, `bureau_titre`, `periode_titre`,
  `plage_alphabetique`, `couvre_periode` et, si le titre porte une période, `communicable_a_partir_de`. `total`
  additionne les totaux lus ; `page_suivante` vaut `page + 1` dès qu'une catégorie a une page suivante.
- **`hypotheques`** (ajout) : `releve_le`, `reference`, `periode_annoncee`, `methode`, `lecture`,
  `bureaux_titres`, `communicabilite`, et pour chaque catégorie interrogée `formulaire`, `interroge`, `bureau`,
  `autres_bureaux`, `total`, `page_suivante`, `bureaux` et, s'il y a lieu, `message`. `commune_service` rend la
  valeur de bureau envoyée.
- **Page > 1** avec `HYP` : les trois formulaires reçoivent `page=N` ; une catégorie qui ne rend pas cette page
  est marquée « Aucune page N lue pour cette catégorie », sans rien conclure ; si aucune ne la rend, l'appel
  est une erreur.
- **Négatif** : `recherche_negative` seulement quand aucun résultat n'est rendu ; il distingue « aucun volume
  renvoyé » de « volumes de la page tous hors période d'après leur titre » et rappelle ce que le service annonce.
- Mêmes garde-fous que `RM` et `SUCC` : hôte et NAAN `33518` contrôlés sur chaque lien de notice, une page par
  formulaire et par appel, une seule tentative par recherche. Ni `classeur_3e`, ni `couverture_recensements`,
  ni `matricules`, ni `successions` ne sont joints. Pour un autre service, `HYP` (et ses variantes) est refusé
  avant toute requête.

**Plage alphabétique.** Le titre d'un volume d'indicateur ou de table porte entre parenthèses la plage des noms
qu'il contient. `registres.titre_hypotheques(titre)` la lit : `plage_alphabetique` = `{texte, debut, fin}`,
`debut` et `fin` en capitales sans accents, lettres seules (« De Fay - Degarnier » → `DEFAY`, `DEGARNIER`). Le
séparateur est un tiret accompagné d'au moins une espace (« A - B », « Baillez- -Basquin »), pour ne pas couper
un nom à trait d'union. Une parenthèse qui n'est pas une plage (« (unique) Sociétés ») est rendue en `texte`,
avec `debut` et `fin` à `null` ; pas de parenthèse : `plage_alphabetique: null`.

`registres.plage_couvre(plage, prefixe)` dit si un nom commençant par `prefixe` (une initiale ou un début de
nom) peut se trouver dans la plage : bornes comprises, comparées sur la longueur du préfixe
(`debut[:n] <= prefixe <= fin[:n]`). `registres.volumes_couvrant(resultats, prefixe)` rend les volumes d'une
réponse qui le couvrent. Ce sont des **fonctions pures, sans paramètre public** : `archives_registres` n'a
aucune entrée pour recevoir une initiale, et il n'en a pas été créé. `personne` désigne la cible locale (garde
des vivants, journal) et n'a pas été détourné ; `commune` est le bureau. L'appelant compare donc lui-même
l'initiale à `debut` et `fin` de chaque résultat, selon la règle ci-dessus ; **le nom cherché n'est jamais
envoyé au service, ni passé à un outil réseau, ni journalisé**. Écart assumé par rapport à une aide intégrée à
la réponse : elle demanderait un paramètre public nouveau.

La plage n'est qu'indicative, pour trois raisons relevées : le service dit les tables « organisées
phonétiquement » ; les plages se chevauchent ou se suivent sans ordre strict (Cambrai) ; un même bureau a
plusieurs séries parallèles (Valenciennes, Lille avant 1900 / 1 / 2). Chaque volume est jugé seul et tous les
volumes couvrants sont rendus. Une page ne dit rien des suivantes : une liste vide pour une initiale sur la
page 1 des tables ne conclut pas.

**Communicabilité.** Le type `hypotheques` du catalogue (#129) porte la règle : délai nul à compter de l'acte,
« Publicité foncière : en principe communicable ; vérifier les délais propres au service. » Elle est inchangée
et `communicabilite` n'est pas modifié. La page du service ne parle d'aucun délai pour ces registres d'ordre :
la règle reste indicative et **n'a pas été vérifiée** auprès du service ni dans un texte. La réponse la porte
dans `hypotheques.communicabilite` (`type_document`, `regle`, `delai_annees`, `source`, `releve_le`,
`non_verifie`, `volumes_non_communicables`). Un volume dont le titre porte une période reçoit
`communicable_a_partir_de`, calculé par `communicabilite("hypotheques")` sur sa dernière année ; si ce délai
n'est pas échu, le volume reste rendu et la réponse porte `avertissement_communicabilite`. Avec la règle
actuelle et des archives closes en 1955, cet avertissement ne se déclenche pas : il suit la règle si elle
change. Les volumes sans période dans le titre (la plupart) ne peuvent pas être jugés. Non établi : le régime
réel de ces registres, qui nomment des propriétaires et, pour les plus récents, peut-être des personnes encore
vivantes (contenu non lu).

**Orientation.** Pour un fait dans le Nord dont les pistes comprennent un acte notarié (contrat de mariage et
dot, filiation, bien ou vente), `prochaine_source` et `cotes_a_consulter` joignent `hypotheques_ad59` à cette
piste : `service`, `releve_le`, `serie` (libellé général de la sous-série 4 Q), appel `HYP` à lancer, `methode`,
`note`. Rien avant l'an VII ; après 1955, la note renvoie à la publicité foncière et aucun appel n'est proposé.
L'année n'est reprise que si la date du fait peut être celle de l'acte (pas pour une naissance ou une
filiation). Ni cote ni bureau n'y figurent : le bureau n'est pas déduit de la commune, la cote vient de la
réponse d'`archives_registres`.

**Non vérifié.**

- Le contenu des indicateurs, des tables et des répertoires (aucune vue ouverte) : la méthode est celle que
  décrit la page, non éprouvée sur un cas. `archives_naviguer`, `archives_planche` et `archive_image` sur ces
  ARK : non testés.
- Le sens de « (1) », « (2) », « serie secondaire », le rapport entre « Lille (2) » (indicateur) et
  « Lille 2 (1901-1955) » (tables), et les périodes des volumes dont le titre n'en porte pas.
- Le ressort de chaque bureau : le plugin ne rattache aucune commune à un bureau des hypothèques.
- Une page au-delà de la dernière pour ces trois formulaires : la redirection vers `page=1` n'a été observée
  que sur d'autres formulaires (#221, #377). Le test correspondant simule ce comportement.
- Les bureaux de Douai, Dunkerque et Hazebrouck (aucune requête) ; les tables et répertoires de Valenciennes ;
  les totaux sans critère (64, 1 652 et 3 693, relevé de l'issue).
- Les titres des pages non relevées : d'autres formes de période ou de séparateur peuvent exister ; elles
  seraient rendues sans période ni plage, jamais devinées.
- La stabilité des identifiants de formulaire et du vocabulaire (suivi : #380).
- La recette réelle (`test_registres_live.py`) n'a pas de cas `HYP` ; le relevé a été fait à la main, hors outil.

Tests : `tests/test_hypotheques_ad59.py`, sans réseau.

## Plans du cadastre : `type_acte="CAD"` — #379

Relevé public du 27 novembre 2026 (robots.txt : `/private/`, `/oai-pmh`, `/user/`, d'après le relevé de l'issue,
non relu ici ; aucune protection rencontrée ; une requête par observation, sans image, sans notice, sans nom de
personne ; douze requêtes en tout : la page, deux formulaires, neuf pages de résultats ; puis une navigation de
métadonnées sur un seul ARK, voir « Planche-contact »). La page
[`/page/plans-du-cadastre-du-consulat-et-napoleonien`](https://archivesdepartementales.lenord.fr/page/plans-du-cadastre-du-consulat-et-napoleonien)
mène à deux formulaires, lus avec `mnesys.lire_formulaire` :

| | Cadastre consulaire | Cadastre napoléonien |
|---|---|---|
| Formulaire | `fff966ed-72a2-47ea-8564-ab533e334daa` | `b57520fe-2768-4335-b138-119f274f0a73` |
| Commune | `0-controlledAccessGeographicName[]` (« Commune ») | idem |
| Vocabulaire | 395 valeurs | 650 valeurs |
| Date | aucun champ | aucun champ |
| Tri par défaut du formulaire | `relevance` | `relevance` |
| Cotes des résultats | `P 30 / <numéro>` | `P 31 / <numéro>`, parfois `_1`, `_2` |
| Contexte des résultats | « Les plans du cadastre du Consulat » | « P31 - Cadastre napoléonien » |
| Résultats sans critère | 395 (relevé de l'issue #379, non revu) | 909 (idem) |

**Ce que dit le service** (page relue le 27 novembre 2026) : la rubrique permet de visualiser les plans du
cadastre dit « du Consulat » et du cadastre dit « napoléonien » ; les premiers concernent le début du XIXe siècle,
les seconds « une plus large période débordant jusqu'au début du XXe siècle pour certaines communes ». La
présentation du formulaire napoléonien liste des ajouts d'octobre 2025 (par exemple « RAMILLIES (1903) »). La
page ne dit rien des matrices cadastrales ni des états de sections.

**Ce qu'est un résultat.** Un lot de plans d'une commune, pas une planche isolée ni une parcelle :

- [napoléonien, Estaires](https://archivesdepartementales.lenord.fr/search/results?formUuid=b57520fe-2768-4335-b138-119f274f0a73&sort=referencecode_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=ESTAIRES) :
  3 résultats, `ESTAIRES - 1889` (cote `P 31 / 035`, 15 médias), `ESTAIRES - 1808` (`P 31 / 035_1`,
  `ark:/33518/4pd9bs0q2cl1`, 2 médias), `ESTAIRES - 1816` (`P 31 / 035_2`, 37 médias) : trois levées, une par
  résultat ; le champ `Date` porte l'année du titre.
- Napoléonien, Marly : 2 résultats sous la **même cote** `P 31 / 602`, `MARLY - 1896` (11 médias) et
  `MARLY - 1826` (5 médias) : la cote ne suffit pas à désigner un lot, l'ARK oui.
- Napoléonien, Lille : 9 résultats, tous `LILLE - 1881` suivis d'une plage de feuilles : `(TA-B12)`,
  `(C1-C31)`, … `(J1-K17)`, cotes `P 31 / 243` à `P 31 / 249`, trois lots sous `P 31 / 246` ; 6 à 42 médias.
  Le champ `Date` y est inexploitable (« B12) », « C31) »… : la fin du titre) : `bornes` reste `null`.
- Napoléonien, Fives : 1 résultat, `FIVES - 1825` (`P 31 / 212_2`, 2 médias).
- [consulaire, Marly](https://archivesdepartementales.lenord.fr/search/results?formUuid=fff966ed-72a2-47ea-8564-ab533e334daa&sort=referencecode_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=MARLY) :
  1 résultat, `MARLY / 222` (cote `P 30 / 222`, `ark:/33518/hl2s6p8q4ntv`, 4 médias) ; aucun champ `Date`.
- Consulaire, Saint-Remy-Mal-Bati : 1 résultat, `SAINT-REMY-MAL-BATI / 324` (`P 30 / 324`, 2 médias).
- Négatif : obtenu sur chaque formulaire avec une valeur inexistante (`ZZZ`), page `body#display-no-results`.
- `page=2` sur la liste de Lille (une page) : redirection 302 vers `page=1`, comme sur les autres formulaires.

Aucune liste relevée ne dépasse une page de 20 résultats. Le sens de « TA » (tableau d'assemblage ?) et des
lettres de section n'est pas dit par le service : les plages de feuilles sont rendues dans le titre, sans
interprétation.

**Deux vocabulaires.** Les deux formulaires n'ont pas les mêmes communes ni les mêmes formes : 363 valeurs
communes aux deux, 287 propres au napoléonien, 32 au consulaire. Anciens noms et communes réunies y figurent
tels quels : `FIVES`, `ROSENDAEL`, `ANNAPPES`, `ASCQ`, `WALLERS-TRELON` (napoléonien) ; `SAINT-REMY-MAL-BATI`,
`CONDE = NORD LIBRE`, `VIEUX NORD LIBRE = VIEUX-CONDE`, `WARNETON-BAS`, `WARNETON-SUD` (consulaire, quand le
napoléonien a `SAINT-REMY-DU-NORD`, `CONDE-SUR-L ESCAUT`, `VIEUX-CONDE`, `WARNETON`). Certaines valeurs sont des
subdivisions : `MARCHIENNES Campagne`, `MARCHIENNES Ville`, `MARCHIENNES Ville + Campagne`,
`BOURBOURG (CAMPAGNE)`, `BOURBOURG (VILLE)`, `SAINGHIN-EN-WEPPES 1`, `SAINGHIN-EN-WEPPES 2`.

**Contrat retenu.** La signature d'`archives_registres` ne change pas ; aucun outil MCP n'est ajouté ; les clés
existantes gardent leur sens.

- **Code** : `CAD`, dans la lignée de `REC`, `RM`, `SUCC`, `FD`, `HYP` (abréviation du fonds, sans numéro de
  série). Pas de variante à une seule catégorie sur le modèle de `HYPI` : aucune liste relevée ne se feuillette.
- **Catégorie** : `CAD` lit les deux formulaires et interroge, une page chacun, ceux dont le vocabulaire connaît
  la commune ; les résultats portent `categorie` (`consulaire`, puis `napoleonien` : ordre des cotes) et
  `contexte`.
- **Commune** : obligatoire, mise en capitales sans accents puis prise dans le vocabulaire de chaque formulaire
  (valeur exacte malgré la casse, sinon `mnesys.choisir_commune` : article inversé, apostrophes). Connue d'un
  seul formulaire : seul celui-là est interrogé, l'autre porte `interroge: false` et un `message`. Ambiguë dans
  un formulaire (« Bourbourg » au consulaire) : ce formulaire n'est pas interrogé et son message liste les
  valeurs ; la valeur exacte (« Bourbourg (ville) ») lève l'ambiguïté. Inconnue des deux (« Marchiennes »,
  « Villeneuve-d'Ascq ») : erreur avant toute recherche, avec les valeurs proches de chaque formulaire, les noms
  liés et la piste `geo_historique` / `lieu_historique`.
- **Période** : aucun champ de date ; `annee` et `annee_fin` ne sont pas envoyées. Elles n'écartent que les
  plans dont le service affiche une date (`bornes`, champ `Date`) qui ne recoupe pas la période : ces plans sont
  comptés (`registres_hors_periode`) et leurs dates rendues (`cadastre.dates_hors_periode`). Un plan sans date
  affichée (tout le consulaire, Lille) garde `couvre_periode: null` et est toujours rendu. `annee_titre` reprend
  l'année du titre (« - 1808 »), pour information seulement : elle ne filtre jamais. **Limite assumée** : un
  plan décrit le territoire pour les décennies qui suivent sa levée ; une année précise écarte donc un plan
  antérieur encore utile. Préférer un intervalle large (`annee=1800, annee_fin=1910`) ; le négatif le rappelle.
- **Résultats** : chaque résultat garde `titre`, `cote`, `ark`, `url`, `bornes`, `nb_vues` et reçoit
  `categorie`, `contexte`, `annee_titre`, `couvre_periode` et, de 2 à 9 vues, `planche_contact`.
- **`cadastre`** (ajout) : `releve_le`, `reference`, `periode_annoncee`, `lecture`, `non_couvert`, `piste_lieu`,
  `communicabilite`, `dates_hors_periode` s'il y a lieu, et pour chaque formulaire `formulaire`, `interroge`,
  `commune`, `total`, `page_suivante`, `nb_communes` et, s'il y a lieu, `message` et `noms_lies`. Le vocabulaire
  entier (650 valeurs) n'est pas rendu. `commune_service` rend la valeur envoyée quand elle est la même partout.
- **Négatif** : `recherche_negative` seulement quand aucun résultat n'est rendu ; il distingue « aucun plan
  renvoyé » de « plans de la page tous écartés par leur date » (dates citées, relance proposée).
- **Page > 1** : chaque formulaire interrogé reçoit `page=N` ; la redirection vers la première page est refusée
  (« Page retournée incohérente ») ; si aucun formulaire ne rend la page, l'appel est une erreur.
- Mêmes garde-fous que `HYP` : hôte et NAAN `33518` contrôlés sur chaque lien de notice, une page par formulaire
  et par appel, une seule tentative par recherche. Ni `classeur_3e`, ni `couverture_recensements` ne sont joints.
  Pour un autre service, `CAD` est refusé avant toute requête.

**Communes réunies, noms anciens.** `geo_historique` (COG INSEE depuis 1943) et `lieu_historique` sont des outils
réseau : `archives_registres` ne les appelle pas. La liaison intégrée est locale : la nouvelle fonction pure
`couverture_3e.noms_lies(commune, valeurs)` lit les libellés à parenthèse du classeur 3 E (#374, référentiel
local) : « LILLE (FIVES) », « SAINT-REMY-DU-NORD (ANC. MAL BATI) », « WARNETON (-BAS) », « WALLERS-EN-FAGNE
(ANC. TRELON) ». Demande = nom du libellé : elle rend les valeurs du vocabulaire qui portent le nom entre
parenthèses, seul ou précédé du début du nom (`lien` « ancien nom ou lieu rattaché ») ; demande = ce nom entre
parenthèses : elle rend la valeur du nom du libellé (`lien` « nom actuel »). Chaque piste cite son libellé
(`d_apres`). Exemples éprouvés sur les vocabulaires relevés :

- « Fives » → napoléonien interrogé sous `FIVES` (plan de 1825), `noms_lies` : `LILLE` (nom actuel) ; « Lille » →
  `noms_lies` : `FIVES` ;
- « Saint-Remy-du-Nord » → napoléonien interrogé ; consulaire non interrogé, message « essayer sous l'ancien
  nom ou lieu rattaché SAINT-REMY-MAL-BATI » ; « Saint-Remy-Mal-Bâti » → l'inverse, « essayer sous le nom actuel
  SAINT-REMY-DU-NORD » ;
- « Wallers-en-Fagne » (inconnue des deux) → erreur qui propose `TRELON` et `WALLERS-TRELON`.

Limites : une parenthèse du classeur peut désigner une paroisse ou un hameau (« LILLE (ST ETIENNE) »,
« MORBECQUE (LA MOTTE AU BOIS) ») : c'est une piste, jamais une preuve de fusion ni de changement de nom. Le
classeur ne connaît qu'une poignée de ces liens : `ROSENDAEL`, `ANNAPPES` ou `CONDE = NORD LIBRE` ne sont liés à
rien, et une commune nouvelle (« Villeneuve-d'Ascq ») ne renvoie pas à ses anciennes communes. Pour ces cas, la
piste est documentée, pas automatisée : `geo_historique(nom=…)` pour les fusions depuis 1943, puis relancer
`CAD` sous le nom d'alors (`cadastre.piste_lieu` et le message d'erreur le disent).

**Planche-contact.** Un lot de 2 à 9 vues reçoit `planche_contact`, l'appel
`archives_planche(source=<ark>, de=1, a=<nb_vues>)` à lancer pour voir tout le lot en une image. Éprouvé le
27 novembre 2026 : `archives_naviguer("ark:/33518/4pd9bs0q2cl1", page=1, pas=1)` (Estaires 1808), hors tests,
répond par la visionneuse `/visualizer/api` déjà qualifiée : titre « ESTAIRES - 1808 », cote `P 31 / 035_1`,
commune, période, 2 vues, ARK de vue et URL d'image de la première vue. **Aucune image n'a été téléchargée** :
`archives_planche` et `archive_image` n'ont pas été lancés sur un plan. Leur lisibilité à 1 600 px (plans de
grand format) n'est donc pas établie ; `planche_contact` est une proposition, pas un résultat éprouvé.

**Communicabilité.** Le type `cadastre` du catalogue (#129) porte la règle : délai nul, « Cadastre : communicable
immédiatement. » Elle est inchangée et `communicabilite` n'est pas modifié. La page du service ne parle d'aucun
délai : la règle reste indicative et n'a pas été vérifiée auprès du service. La réponse la porte dans
`cadastre.communicabilite`. Les plans ne sont pas nominatifs. Le libellé de série du catalogue (« sous-série
3 P », cadre de classement général) n'est pas celui des cotes relevées aux AD59 (`P 30`, `P 31`) : il n'a pas
été modifié, la cote vient toujours de la réponse.

**Orientation.** Pour un fait dans le Nord, `prochaine_source` et `cotes_a_consulter` joignent `cadastre_ad59` à
la piste des recensements pour un domicile (`RESI`, `OCCU`, `CENS`) et à la piste « Actes notariés » pour un
bien, à côté de `hypotheques_ad59` : `service`, `releve_le`, `serie` (libellé général du catalogue), appel `CAD`
à lancer avec la commune du lieu, `note`. Aucune cote n'y figure.

**Non couvert, non vérifié.**

- Les matrices cadastrales et les états de sections (propriétaires) : absents des deux formulaires ; leur mise en
  ligne et leur cote n'ont pas été relevées. Rien n'est affirmé à leur sujet (`cadastre.non_couvert`).
- Le contenu des plans (aucune vue ouverte), la planche-contact et le téléchargement d'un plan.
- Le géoportail « La carte du Nord en documents » cité par l'issue chapeau : non exploré.
- Les communes non interrogées : d'autres formes de titre ou de date peuvent exister ; un titre sans
  « - AAAA » donne `annee_titre: null`, une date illisible `bornes: null`, jamais une valeur devinée.
- Les totaux sans critère (395 et 909, relevé de l'issue) ; une liste de plus d'une page (aucune observée : la
  page 2 réelle n'a pas de fixture, seule la redirection au-delà de la dernière page est simulée d'après le
  relevé).
- La stabilité des identifiants de formulaire et des vocabulaires (suivi : #380).
- La recette réelle (`test_registres_live.py`) n'a pas de cas `CAD` ; le relevé a été fait à la main, hors outil.

Tests : `tests/test_cadastre_ad59.py`, sans réseau.

## HTTP, protection et journal

Un appel effectue au plus une tentative GET de recherche, ou utilise son cache (`RM` : une par formulaire, soit
deux au plus ; `HYP` : trois au plus, une seule pour `HYPI`, `HYPT` ou `HYPR` ; `CAD` : deux au plus ; toujours précédées de la lecture
des formulaires, en cache une semaine). Il n'enchaîne pas les
pages, les registres ou les métadonnées ; la politique commune continue de revalider les redirections.
Une copie du wrapper HTTP partage le client, le cache, la politique et l'état de limitation de débit,
avec une limite locale d'une tentative. Elle ne modifie pas les reprises des autres sources. Chaque
invocation produit une entrée de journal : positive, négative, erreur ou blocage anti-robot, y compris
lorsque la réponse vient du cache.

[robots.txt](https://archivesdepartementales.lenord.fr/robots.txt) a autorisé `/search/results` lors du
relevé ; ses exclusions étaient `/private/`, `/oai-pmh`, `/user/`. Les réponses positives et négatives
étaient des pages serveur complètes sans défi bloquant. Le portail inclut pourtant un attribut de
configuration hCaptcha et un script passif Cloudflare : ces mentions seules ne caractérisent pas un
blocage. Un véritable défi arrête la requête et conserve la tâche manuelle de l'enveloppe commune,
sans autre client ni contournement.

Les changements de structure ou métadonnées incohérentes produisent une erreur journalisée. Le
parseur borne la profondeur HTML et refuse un document de plus de deux millions de caractères pour
éviter une récursion incontrôlée ou une analyse disproportionnée.

## Tests et recette volontaire

`tests/fixtures/ad59-recherche-positive.html` et `ad59-recherche-negative.html` conservent les balises
observées, avec une commune, une cote, un ARK, un UUID et une période synthétiques.
`ad59-recensements-positive.html` et `ad59-recensements-page2.html` (#375) sont, eux, les pages de recensements
relevées le 27 novembre 2026, réduites aux balises lues (registres publics, aucune personne).
Les dix fichiers `ad59-matricules-*.html` (#376) sont de même les deux formulaires et huit pages de résultats
relevés le 27 novembre 2026 (tables et fiches : avec bureau, sans bureau, intervalle, page 2, négatif), réduits
aux balises lues.
Les huit fichiers `ad59-successions-*.html` et `ad59-fiches-deces-*.html` (#377) sont les deux formulaires de
l'enregistrement et six pages de résultats relevés le 27 novembre 2026 (tables : intervalle, année seule,
page 2 sur 4, négatif ; fiches décès : positif, négatif), réduits de la même façon.
Les douze fichiers `ad59-hypotheques-*.html` (#378) sont les trois formulaires de la sous-série 4 Q et neuf
pages de résultats relevés le 27 novembre 2026 (indicateur : Cambrai, Valenciennes, Lille pages 1 et 2, négatif ;
tables : Cambrai, Lille pages 1 et 32 ; répertoires : Avesnes), réduits de la même façon.
Les dix fichiers `ad59-cadastre-*.html` (#379) sont les deux formulaires des plans du cadastre et huit pages de
résultats relevés le 27 novembre 2026 (napoléonien : Estaires, Marly, Lille, Fives, négatif ; consulaire : Marly,
Saint-Remy-Mal-Bati, négatif), réduits de la même façon.
`ad59-tables-decennales.html` (trois tables décennales) et `ad59-recherche-intervalle-page2.html` (page 2 sur
2 d'un intervalle, 25 résultats) en dérivent avec les titres, cotes et compteurs relevés le 18 novembre. Aucun export familial,
HTML complet de production, cookie ou script tiers n'est livré comme fixture.

```bash
uv --directory mcp run --locked --offline pytest tests/test_registres.py
GENEALOGISTE_TEST_REGISTRES=1 uv --directory mcp run --locked --offline pytest tests/test_registres_live.py -rs
```

La recette réelle est ignorée par défaut, y compris en CI. Elle contrôle `robots.txt`, puis effectue
exactement cinq appels d'outil sur Saint-Vaast-en-Cambrésis : NMD pour 1860, filtre N pour 1860, résultat
négatif pour 1200, table décennale (`TD`) pour 1860 et intervalle 1790-1802 (les deux derniers depuis #221).
Elle s'arrête à la première protection, sans télécharger d'image. La recette exécutée le 16 novembre 2026 a
passé les trois premiers cas par le véritable outil MCP Python (`1 passed`, 4,90 s), avec l'ARK et la cote
ci-dessus, sans défi bloquant. Celle du 18 novembre 2026 a passé les cinq cas (`1 passed`, 8,49 s) : table
`3E TD 547/07` (`ark:/33518/xwkrg498c6qs`, 1853-1862) et, pour 1790-1802, les registres `R 022` et `R 023`. Le fichier JSON de preuve reste dans le dossier
temporaire de pytest, hors du dépôt.

La recette native Codex (`make test-codex`, Codex CLI 0.166 à 0.169) vérifie aussi que le refus d'approbation
d'`archives_registres` laisse le journal de recherche intact, puis qu'un appel approuvé visant le
vivant fictif `I9` est refusé par la garde locale. Cette recette utilise le fournisseur déterministe
local et le mode hors ligne ; elle ne recherche aucune personne réelle.

## De la recherche à l’archivage

La [recette de chaîne AD59](recette-chaine-ad59.md) prolonge la recherche jusqu’à l’archivage d’une vue candidate avec sa provenance. Elle ne prétend pas identifier un acte.
