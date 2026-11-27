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
ci-dessous ; `REC` (recensements de population, #375) et `RM` (registres matricules, #376) plus bas.
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

## HTTP, protection et journal

Un appel effectue au plus une tentative GET de recherche, ou utilise son cache (`RM` : une par formulaire, soit
deux au plus, précédées de la lecture des formulaires, en cache une semaine). Il n'enchaîne pas les
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
