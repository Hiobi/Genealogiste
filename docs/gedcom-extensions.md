# Extensions GEDCOM 7 du plugin genealogiste

Déclarées dans `HEAD.SCHMA` ; ignorées sans perte par les logiciels qui ne les connaissent pas.

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

Lieux : le code INSEE est stocké en `EXID` avec `TYPE http://id.insee.fr/geo/commune` (`_INSEE` en 5.5.1).
Export 5.5.1 : `UID` → `_UID`, calendriers en échappements `@#DJULIAN@` / `@#DFRENCH R@`.

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
