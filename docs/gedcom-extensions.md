# Extensions GEDCOM 7 du plugin genealogiste

Déclarées dans `HEAD.SCHMA` ; ignorées sans perte par les logiciels qui ne les connaissent pas. `_ETIQUETTE`
n'y est déclarée que si l'arbre porte au moins une étiquette : un fichier sans étiquette reste identique, octet
pour octet, à celui des versions précédentes.

| Tag | Contexte | Valeur | Rôle |
|---|---|---|---|
| `_TYPE` | citation `SOUR`, enregistrement `SOUR` | `originale` \| `derivee` \| `composite` | nature de la source |
| `_INFO` | citation | `primaire` \| `secondaire` \| `indeterminee` | nature de l'information |
| `_PREUVE` | citation | `directe` (défaut, omis) \| `indirecte` \| `negative` | nature de la preuve |
| `_CONSULT` | citation | date ISO | date de consultation |
| `_VU` | citation | `original` \| `image` \| `transcription` \| `index` \| `non_vu` | ce qui a réellement été consulté (non vu : poids 0 ; index/transcription : traité comme dérivé) |
| `_SIGLE` | `REPO` | texte | sigle du dépôt (AD17, AN, SHD…) pour la citation normalisée |
| `_ORIG` | enregistrement `SOUR` | pointeur `@S…@` | source originale dont celle-ci dérive (indépendance) |
| `_URL` | enregistrement `SOUR` | URL | accès en ligne |
| `_ARK` | enregistrement `SOUR`, citation | `ark:/NAAN/nom[/qualificatif]` | identifiant pérenne : ressource (source, sans qualificatif) ou image / page (citation) |
| `_SOUR` | `FAM.CHIL` | structure de citation | preuve de la filiation (GEDCOM 7 n'autorise pas `SOUR` sous `CHIL`) |
| `_STAT` | événement, `NAME`, `FAM`, `FAM.CHIL` | `refute` \| `contradictoire` (+ `NOTE` justification) | statut **manuel** ; les autres statuts sont calculés |
| `_VIVANT` | `INDI` | `Y` \| `N` | forçage du statut vivant (RGPD) |
| `_RESN` | enregistrements `SOUR` et `SNOTE`, citation `SOUR` | `PRIVACY` | marque « privé » là où GEDCOM 7 n'autorise pas `RESN` (standard, écrit sur `INDI`, `FAM`, événements et `OBJE`) ; un objet privé (Gramps `private`) n'est jamais publié |
| `_PAROISSE` | `PLAC` | texte | paroisse d'Ancien Régime correspondant au lieu |
| `_ETIQUETTE` | `INDI`, `FAM`, événement, citation `SOUR` (y compris `FAM.CHIL._SOUR`), enregistrements `SOUR`, `REPO`, `OBJE`, `SNOTE` | nom de l'étiquette (sensible à la casse) | étiquette (tag) de l'objet, une ligne par étiquette dans l'ordre ; correspond au `tag_list` de Gramps Web (#262, [opérations](operations.md#étiquettes-262)) |

Étiquettes : un nom en double sous un même objet est lu une fois ; une étiquette gérée par Genealogiste
(`Genealogiste:auto`, `Sosa:auto`, « Preuve : … ») n'entre jamais dans le modèle et reste un nœud non interprété
(conservé). Couleur et priorité des étiquettes de Gramps ne sont pas écrites dans le GEDCOM. Export 5.5.1 : écrite
comme les autres extensions ; export GeneWeb : omise, comme toutes les extensions.

Lieux : le code INSEE est stocké en `EXID` avec `TYPE http://id.insee.fr/geo/commune` (`_INSEE` en 5.5.1).
Export 5.5.1 : `UID` → `_UID`, calendriers en échappements `@#DJULIAN@` / `@#DFRENCH R@` / `@#DHEBREW@`.

## Dates Gramps (#272)

Valeur de `DATE` étendue pour ce que Gramps représente et que GEDCOM 7 n'exprime pas ; une date du modèle relue
par Genealogiste redonne exactement la date Gramps d'origine (table complète : [Gramps Web](gramps-web.md#dates-272)).
Aucune n'apparaît dans un arbre qui ne vient pas de Gramps : les fichiers existants ne changent pas. Ces formes
restent lisibles ; un logiciel qui ne les connaît pas les garde comme texte de date.

| Forme | Exemple | Sens (Gramps) |
|---|---|---|
| calendrier d'extension `_PERSIAN`, `_ISLAMIC`, `_SWEDISH` (`calendar` de GEDCOM 7 = `extTag`) | `_PERSIAN 12 FARVA 1300` | calendriers persan, islamique, suédois. Mois persans : `FARVA ORDIB KHORD TIR MORDA SHAHR MEHR ABAN AZAR DEY BAHMA ESFAN` ; islamiques : `MUHAR SAFAR RABIA RABIT JUMAA JUMAT RAJAB SHAAB RAMAD SHAWW DHUAQ DHUAH` ; suédois : `JAN` à `DEC` |
| qualité avant un qualificatif | `EST BEF 1850`, `CAL BET 1850 AND 1860` | qualité estimée / calculée combinée à avant, après, vers, depuis, jusqu'à, entre, de… à (GEDCOM 7 n'admet `EST`/`CAL` que seuls ; forme relue par l'import GEDCOM de Gramps) |
| double datation `AAAA/AA` | `JULIAN 12 FEB 1721/22` | année ancien style / nouveau style (syntaxe GEDCOM 5.5.1) ; l'année retenue est la seconde (1722), comme dans Gramps |
| nouvel an `(Mar1)`, `(Mar25)`, `(Sep1)`, `(M-J)` après la date | `12 FEB 1721 (Mar25)` | année commençant le 1er mars, le 25 mars, le 1er septembre ou au mois-jour donné (grégorien, julien, suédois) ; une phrase éventuelle suit : `1850 (Mar25) (texte)` |
| `?` pour un élément inconnu | `12 ? 1850`, `12 MAR ?`, `BET 1850 AND ?`, `JULIAN ?` | jour sans mois, année inconnue, bout de plage vide, date sans valeur portant un calendrier, un modificateur ou une qualité |
| date textuelle entre parenthèses | `(1850)`, `()` | texte d'une date textuelle de Gramps qui serait sinon relu comme une date (ou vide, ou aux espaces de bord) ; sans parenthèses dans tous les autres cas |

Phrase : `DATE 1850` + `PHRASE texte` (GEDCOM 7) est lu `1850 (texte)` et `DATE` + `PHRASE texte` seul `(texte)` ;
l'écriture GEDCOM 7 garde la chaîne du modèle. Export 5.5.1 : `B.C.` pour `BCE`, `@#DHEBREW@`, et une date
simple avec phrase en `INT 1850 (texte)`.

## Témoins, parrains, intervenants (`ASSO`, standard)

GEDCOM 7 : sous l'événement (ou l'individu) `ASSO @I12@` ou `ASSO @VOID@` + `PHRASE` (nom tel qu'écrit dans
l'acte), `ROLE WITN|GODP|CLERGY|OFFICIATOR|…` + `PHRASE` (détail : « Parrain, oncle paternel, 45 ans »),
citations `SOUR`. GEDCOM 5.5.1 (export `gedcom551`, vocabulaire GeneWeb) : `ASSO @I12@ / TYPE INDI /
RELA Witness|GODP|Civil officer|Religious officer|Informant|Attending|Mentioned|Other` sous l'événement,
`RELA GODF|GODM` au niveau de l'individu ; un intervenant sans fiche est écrit en note.

## Préservation

Toute sous-structure non interprétée (sous un événement, un nom, une citation, un lieu, un individu, une
famille, une source) est conservée et réécrite à l'identique ; les `SOUR` en texte libre (5.5.1) sont
convertis en enregistrements source.
