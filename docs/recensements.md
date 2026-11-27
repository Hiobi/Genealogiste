# Recensements de population — AD59 (#375)

Les listes nominatives de recensement donnent, pour une commune et un millésime, la composition des foyers :
noms, âges ou années de naissance déclarés, professions, liens au chef de ménage, nationalité selon les années.
Le plugin sait localiser le recensement d'une commune du Nord, dire s'il est en ligne ou seulement en salle de
lecture, et citer sa cote. Il ne lit pas les listes (ni OCR ni HTR) et ne cherche aucun nom.

Seul le service **AD59** est couvert. Tout ce qui suit vient de relevés publics du **27 novembre 2026**
(`robots.txt` : seuls `/private/`, `/oai-pmh`, `/user/` sont exclus ; une requête par observation, sans image,
agent générique, aucun nom de personne).

## Ressources du service

| Ressource | Adresse | Usage par le plugin |
|---|---|---|
| Formulaire « Recensements de population » | [`/page/recensements-de-population`](https://archivesdepartementales.lenord.fr/page/recensements-de-population), `formUuid=f0366f8a-2ef6-4cf2-b47b-6dec4a19e99f` | `archives_registres(type_acte="REC")` |
| « Recensements de population, État de la collection » (PDF, 64 pages) | notice [`ark:/33518/c7r0j89k6phb`](https://archivesdepartementales.lenord.fr/ark:/33518/c7r0j89k6phb) | référentiel local `ad59_recensements.json` |
| Socface, base de noms (FranceArchives) | [`/page/socface-et-les-recensements-de-population`](https://archivesdepartementales.lenord.fr/page/socface-et-les-recensements-de-population) → <https://francearchives.gouv.fr/fr/basedenoms> | lien et consigne seulement, consultation manuelle |

## Recherche en ligne : `type_acte="REC"`

```
archives_registres(service="AD59", commune="Somain", annee=1906, type_acte="REC")
```

Le formulaire dédié n'a qu'un champ, la commune (`0-controlledAccessGeographicName[]`, capitales sans accents
comme pour l'état civil), sans champ de date. La requête envoyée est donc la même que pour les tables
décennales, avec un autre `formUuid` : `sort=date_asc`, `mode=list`, `facet_media=image`, commune, `page`.
Les facettes `facet_decade` et `facet_century` du service ne sont pas utilisées. La période `[annee, annee_fin
or annee]` est appliquée **localement** aux bornes affichées (`couvre_periode`, `registres_hors_periode`), une
page par appel (`page_suivante`). La signature de l'outil et les clés de la réponse ne changent pas.

Le HTML de résultat est celui que lit déjà `sources/registres.py` (voir le
[contrat observé](recherche-registres-ad59.md)). Ce que l'analyseur en tire réellement :

| Champ | Valeur observée (Somain) | Remarque |
|---|---|---|
| `titre` | `SOMAIN` | le titre est la commune seule, sans millésime |
| `cote` | `M473 063 / 10 SOMAIN`, `M 474 / 572`, `M474 5 / 19 SOMAIN`, `M474 7 / 25 SOMAIN` | telle qu'affichée en ligne ; l'écriture diffère de celle du PDF (`M 474 572`, `M 474 5 19 SOMAIN`) |
| `bornes` | `[1901, 1901]`, `[1906, 1906]`, `[1931, 1931]`, `[1946, 1946]` | champ « Date » : un millésime |
| `nb_vues` | 5, 225, 197, 223 | nombre de médias affiché |
| `ark` | `ark:/33518/h2tprnqlw3dj` pour 1906 | ARK de registre (lien de notice) |

La ligne « Contexte : Recensement de 1906 » ou « Contexte : Recensements (série M 474 / 5) » n'est pas lue : le
millésime vient du champ « Date ». Observations : Somain → 4 résultats, une page ; une commune inexistante →
la page négative habituelle (`body#display-no-results`, identique octet pour octet, une fois réduite, à celle de
l'état civil) ; Buysscheure, `page=2` → 6 résultats sur 26, 20 par page, `max="2"`.

`REC` est réservé à AD59. Pour un autre service Mnesys, l'outil refuse avec un message explicite : le
formulaire dédié de ce service n'a pas été relevé (extension prévue une fois relevé, hors de #375).

## État de la collection : `couverture_recensements`

`referentiels/ad59_recensements.json` est la copie structurée du PDF : relevé du **27 novembre 2026**,
empreinte SHA-256 `fe1e2e3d…f3bbef`, 4 041 lignes, 4 039 volumes (2 doublons exacts écartés), 765 libellés de
commune, aucune ligne rejetée, millésimes de 1699 à 1975. **2 852 volumes sont « Mis en ligne », 1 187 en
« Salle de lecture »** seulement. Dans ce relevé, tous les volumes de 1954, 1962, 1968 et 1975 sont en salle de
lecture et tous les millésimes antérieurs sont en ligne, à une exception près (Escaudœuvres 1946, « avec
retombes 1954 ») : c'est un constat, pas une règle utilisée par le code. Le document ne contient aucune personne.

Colonnes lues : `COMMUNE`, `ANNEE`, `COTE`, `Mis en ligne`, `Salle de lecture`. Le mode d'accès ne tient qu'à
la colonne où se trouve la croix. Par commune, chaque volume porte `debut`, `fin` (le millésime ; deux années
pour les recensements de l'an VIII à l'an XI, `1799-1800`), `cote`, `acces` (`en_ligne` ou `salle_de_lecture`)
et, quand la cellule n'est pas une année simple, son texte dans `annee`.

Cotes rencontrées, gardées telles qu'écrites (fautes de saisie comprises) :

| Forme | Volumes | Millésimes |
|---|---|---|
| `M 473 063 <n°> <COMMUNE>` | 178 | 1901 |
| `M 474 <n°>` | 683 | 1906, un numéro par commune |
| `M 474 2\|4\|5\|6\|7\|8\|9\|11\|13 <n°> <COMMUNE>` | 2 306 | 1896, 1911, 1926, 1931, 1936, 1946, 1954, 1962, 1968, 1975 |
| `E DEPOT <n°> …` | 676 | dépôts communaux, 1794-1962 selon les communes |
| `5Z <n°> <COMMUNE> <année>` | 152 | 1825, 1826, 1830, 1831, 1918, 1921 |
| `1MI` / `2MI <n°> R <n°> …` | 33 | 1699 (Valenciennes), 1841-1954 |
| `7Z 035 <COMMUNE> 1831` | 11 | 1831 |

Les libellés de commune sont ceux du document : `LE CATEAU CAMBRESIS`, `SAINT ANDRE`, mais aussi des quartiers,
cantons ou tomes (`ROUBAIX (Canton Est)`, `LILLE CANTON SUD EST`, `CROIX (Lille) (Tome1)`, `BOURBOURG Campagne`,
`Lille : non versé`). La commune demandée est comparée sans accents ni casse, tirets, apostrophes et espaces
ignorés, `ST`/`STE` développés, article initial facultatif ; un libellé de quartier répond aussi à sa commune
(« Lille » rend les cantons de Lille). Le libellé d'origine est rendu avec chaque volume (`commune`).

**Dans `archives_registres`.** Pour `type_acte="REC"`, la réponse porte en plus `couverture_recensements`
quand la recherche est vide (réponse négative, ou aucun résultat de la page dans la période) ou quand un
recensement de la période n'est qu'en salle de lecture. Le constat donne `source`, `releve_le`, `communes`,
`commune_connue`, `periode`, `statut` (`connu` ou `inconnu_du_referentiel`), `volumes` (avec `recoupe_periode`
et un `message`), `millesimes_connus` (par mode d'accès, pour toute la commune), `message`, `limite` et
`recherche_nominative` (Socface, ci-dessous). Messages par volume :

- « pas en ligne : consultation en salle de lecture seulement selon l'état de la collection, sous réserve de
  communicabilité (75 ans) » ;
- « en ligne selon l'état de la collection mais absent de la recherche » (recherche vide : vérifier le nom de la
  commune et la page) ;
- « … et présent dans la recherche » ou « cote non reconnue parmi les résultats de cette page » quand la
  recherche a des résultats (cotes comparées sans espaces ni ponctuation, au nom de commune final près).

Un millésime absent du référentiel est **inconnu du référentiel**, jamais inexistant : le message liste alors
les millésimes connus de la commune (Somain 1911 → « 1901, 1906, 1931, 1946 (en ligne) ; 1954 (salle de
lecture) ») et la recherche reste un négatif non concluant, tracé au journal.

**Dans `cotes_a_consulter` et `prochaine_source`.** Quand le lieu est dans le Nord (département reconnu dans le
libellé), que l'année est connue et que le référentiel connaît la commune, la piste « Listes nominatives de
recensement » reçoit `couverture_recensements` : le recensement de l'année (`position: "annee"`) et les
recensements connus les plus proches avant et après (`avant`, `apres` ; après seulement pour une naissance ou
une filiation). La liste des pistes et leur `cote_typique` (6 M) ne changent pas ; ailleurs, rien n'est ajouté.

## De la cote à la vue

`archives_naviguer` accepte l'ARK de registre rendu par la recherche. Relevé du 27 novembre 2026, un appel,
fenêtre d'une vue, aucune image téléchargée : `ark:/33518/h2tprnqlw3dj` (Somain 1906) → cote `M 474 / 572`,
commune `SOMAIN`, période 1906, 225 vues, ARK de vue et adresse d'image de la vue 1. `archive_image` et
`archives_planche` n'ont **pas été testés** sur un recensement (ils téléchargent des images) ; rien ne les
distingue a priori des autres registres de la même visionneuse, mais ce n'est pas vérifié. Une liste nominative
est classée par rue ou hameau, pas par nom : le repérage d'un foyer reste une lecture vue par vue.

## Socface : recherche par nom

La page du service renvoie à la base de noms de FranceArchives, <https://francearchives.gouv.fr/fr/basedenoms>.
FranceArchives répond aux clients automatiques « This website requires JS enabled and cookies » (défi
JavaScript) : le plugin ne l'interroge pas, n'y envoie aucun nom et ne tente aucun contournement.
`recherche_nominative` rend la page, le lien et la consigne : consulter soi-même dans un navigateur, puis
vérifier sur la liste nominative. Non vérifié : la couverture réelle du Nord et des millésimes par Socface.
Un index nominatif est une source dérivée (`_VU index`) : il sert à trouver la vue, pas à prouver.

## Preuve

Un recensement est une source originale, mais l'information dépend du fait : la présence au foyer et le domicile
à la date du recensement sont de première main ; l'âge ou l'année de naissance déclarés sont une information
**secondaire** et, pour une naissance, une preuve **indirecte** (`naissance_depuis_age` donne l'intervalle).
L'absence d'une personne dans une liste ne prouve ni son décès ni son départ. La classification reste celle
que porte chaque citation (`_TYPE`, `_INFO`, `_PREUVE`, [extensions GEDCOM](gedcom-extensions.md)) : `evidence.py`
n'a pas de règle propre à `CENS` et n'en déduit rien automatiquement.

## Communicabilité

Listes nominatives : 75 ans (`communicabilite(document="recensement", date_document=…)`). « Salle de lecture »
dans l'état de la collection ne veut donc pas dire « librement consultable » : en 2026, un recensement de 1954
n'est communicable qu'à partir de 2030 selon cette règle. Les conditions d'accès en salle n'ont pas été relevées.

## Limites, non vérifié

- L'état de la collection est lu tel quel : ni sa complétude ni son exactitude ne sont contrôlées. Il compte
  2 852 volumes en ligne ; l'issue #375 relève 2 859 résultats sur le formulaire le même jour : l'écart n'est
  pas expliqué.
- La correspondance entre cote du PDF et cote affichée en ligne n'a été contrôlée que sur Somain (4 volumes).
- Le vocabulaire de communes du formulaire n'a pas été relevé : une commune à article ou à quartiers peut
  demander le libellé exact du service (essayer la forme du site). Une commune de plus de 20 recensements en
  ligne a une deuxième page (26 au plus pour un libellé du relevé).
- Seules les pages citées ont été observées ; aucune facette, aucune notice, aucune image.

## Renouvellement du référentiel

Le PDF est attaché à la notice `ark:/33518/c7r0j89k6phb` ; l'adresse du média
(`/media/318b224b-e7f9-4b64-a1cd-c3b6e8cac76f.pdf` au relevé) porte un UUID qui peut changer à chaque nouvelle
version, sans que rien ne le signale au plugin. `releve_le` est rendu avec chaque constat pour juger de la
fraîcheur. Pour renouveler :

```bash
# 1. télécharger (étape explicite : robots.txt contrôlé, une seule requête, fichier neuf, hôte officiel seulement)
uv --directory mcp run python -I ../scripts/generer_couverture_recensements_ad59.py /tmp/recensements/etat.pdf \
    --telecharger --document https://archivesdepartementales.lenord.fr/media/<uuid>.pdf
# ou, PDF déjà présent (aucun réseau) :
uv --directory mcp run python -I ../scripts/generer_couverture_recensements_ad59.py /tmp/recensements/etat.pdf \
    --releve AAAA-MM-JJ
# contrôle sans écriture
uv --directory mcp run python -I ../scripts/generer_couverture_recensements_ad59.py /tmp/recensements/etat.pdf \
    --releve AAAA-MM-JJ --check
```

puis mettre à jour `couverture_recensements.DOCUMENT`, les chiffres de cette page, la fixture et les tests si
des volumes cités ont changé, et régénérer `docs/couverture-archives.md`
(`scripts/generer_couverture_archives.py`). Le PDF est une donnée non fiable : il est lu, jamais exécuté
(`python -I`, dossier dédié).

Garde-fous de l'extraction (pdfplumber, `extract_tables`) : une page sans tableau, un en-tête absent ou
différent, ou des colonnes d'accès permutées font échouer le script ; sur chaque page, le nombre de croix de
chaque colonne du tableau est recoupé avec la position des croix lue dans les mots de la page (de part et
d'autre de la frontière des deux colonnes, prise sur l'en-tête) ; une ligne sans croix, à deux croix ou à
contenu inattendu est rejetée, et le référentiel est refusé au-delà de 0,5 % de lignes rejetées ou de 1 % de
millésimes illisibles. Il n'y a pas de repli sur les seules coordonnées : une autre mise en page fera échouer
le script plutôt que produire un référentiel faux. `--telecharger` n'a pas été exécuté sur le service réel :
le PDF du relevé a été téléchargé à part, puis lu par le script.

## Tests

`tests/test_couverture_recensements.py`, sans réseau : `fixtures/ad59-recensements-extrait.pdf` reprend sans
modification les pages 1, 20, 33, 54 et 64 du PDF public (310 lignes) ; `ad59-recensements-positive.html`
(Somain) et `ad59-recensements-page2.html` (Buysscheure, page 2 sur 2) sont les pages relevées, réduites aux
balises lues (ni script, ni cookie, ni formulaire) ; le négatif réutilise `ad59-recherche-negative.html`.
