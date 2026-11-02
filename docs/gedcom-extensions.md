# Extensions GEDCOM 7 du plugin genealogiste

Déclarées dans `HEAD.SCHMA` ; ignorées sans perte par les logiciels qui ne les connaissent pas.

| Tag | Contexte | Valeur | Rôle |
|---|---|---|---|
| `_TYPE` | citation `SOUR`, enregistrement `SOUR` | `originale` \| `derivee` \| `composite` | nature de la source |
| `_INFO` | citation | `primaire` \| `secondaire` \| `indeterminee` | nature de l'information |
| `_PREUVE` | citation | `directe` (défaut, omis) \| `indirecte` \| `negative` | nature de la preuve |
| `_CONSULT` | citation | date ISO | date de consultation |
| `_ORIG` | enregistrement `SOUR` | pointeur `@S…@` | source originale dont celle-ci dérive (indépendance) |
| `_URL` | enregistrement `SOUR` | URL | accès en ligne |
| `_SOUR` | `FAM.CHIL` | structure de citation | preuve de la filiation (GEDCOM 7 n'autorise pas `SOUR` sous `CHIL`) |
| `_STAT` | événement, `NAME`, `FAM`, `FAM.CHIL` | `refute` \| `contradictoire` (+ `NOTE` justification) | statut **manuel** ; les autres statuts sont calculés |
| `_VIVANT` | `INDI` | `Y` \| `N` | forçage du statut vivant (RGPD) |
| `_PAROISSE` | `PLAC` | texte | paroisse d'Ancien Régime correspondant au lieu |

Lieux : le code INSEE est stocké en `EXID` avec `TYPE http://id.insee.fr/geo/commune` (`_INSEE` en 5.5.1).
Export 5.5.1 : `UID` → `_UID`, calendriers en échappements `@#DJULIAN@` / `@#DFRENCH R@`.
