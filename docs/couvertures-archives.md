# Disponibilité déclarée des fonds

Depuis 0.15.0, `couvertures` complète le format historique `en_ligne`. Le calcul distingue l’étendue
annoncée d’un fonds, son accès déclaré et les exceptions locales. Il ne démontre jamais l’existence
de l’acte recherché : une recherche dans les registres reste nécessaire.

## Saisie

Exemple **synthétique**, sans valeur documentaire :

```json
{"couvertures": {"naissance": [
  {"etat": "en_ligne", "de": 1800, "a": 1900,
   "reference": "https://archives.example/couverture"},
  {"etat": "lacune", "communes": ["Commune fictive"], "de": 1840, "a": 1850,
   "reference": "https://archives.example/lacunes", "note": "Registre à vérifier"}
]}}
```

Chaque type de document utilise une liste non vide de règles, avec un `etat` et une `reference` HTTP(S)
obligatoires. Les types de documents restent ceux du référentiel (naissance, mariage, deces, etc.).
Les liens ne sont pas interrogés par le calcul ; ils justifient la saisie et permettent la vérification.

| Champ | Signification |
|---|---|
| `de`, `a` | Années incluses dans le périmètre de la règle ; borne absente = pas de restriction de ce côté. Une année hors de toutes les règles reste inconnue. |
| `anciennete_min` | Âge strict minimum des registres, en années ; seule une année entièrement au-delà du seuil est retenue. L’année frontière reste inconnue faute de jour précis. |
| `communes` | Liste de communes auxquelles s’applique la règle. Correspondance exacte après normalisation des accents, casse, tirets et Saint/St ; aucun rapprochement flou. |
| `sauf_communes` | Communes exclues de cette règle ; leur exclusion ne prouve pas à elle seule une indisponibilité. |
| `note` | Précision documentaire affichée ; aucune interprétation automatique de son texte. |
| `lien` | Accès au service alternatif, notamment pour `autre_service`. |

| État | Résultat `en_ligne_pour_la_demande` |
|---|---|
| `en_ligne` | `true` : accès au fonds déclaré dans ce périmètre ; aucun acte individuel garanti. |
| `hors_ligne` | `false` : indisponibilité explicitement déclarée chez ce service ; ne concerne pas les autres services. |
| `annoncee` | `null` : période annoncée, accès précis non établi. |
| `partielle` | `null` : couverture incomplète ou variable, à vérifier localement. |
| `lacune` | `null` : lacune signalée sans conclusion sur les autres collections disponibles. |
| `autre_service` | `null` : renvoi vers un autre service ; sa disponibilité n’est pas présumée. |

Une numérisation annoncée peut être consultable uniquement en salle : ne pas la saisir comme `en_ligne`.
Ne saisir `hors_ligne` qu’avec une référence explicitant l’indisponibilité ; ne pas le déduire d’une borne
ou du délai légal de communicabilité.

## Décision et réponse

`archives_service` conserve ses paramètres. Pour les exceptions, fournir `lieu` avec la commune et son
département, même si `code` est aussi renseigné. Un département seul ne vaut pas une commune.
Une incohérence explicite entre le lieu et le département du service donne un résultat inconnu,
y compris avec une plage historique. Les noms et codes de départements seuls sont reconnus ; un département explicite conserve
la commune homonyme (Vienne (38), Paris (75)). Une
précision géographique non reconnue reste inconnue. Aucun périmètre départemental ou pays n’est
inventé pour un service national/autre dépourvu de département, notamment MATCHID.

Les règles temporelles applicables sont filtrées, puis les règles nommant explicitement la commune
priment sur les règles générales. À priorité égale, des états différents donnent `null` ; l’ordre de
la liste ne départage pas les règles. Une commune manquante ou une année frontière pouvant modifier
la décision donne également `null`.

La réponse conserve `en_ligne_pour_la_demande` et ajoute `couverture_pour_la_demande` : résultat,
`motif`, règles retenues (dont références et réserves), état lorsqu’il est unique et rappel de la portée.
Les règles originales figurent aussi dans la fiche sous `couvertures`. Si un renvoi `autre_service`
est résolu sans ambiguïté et possède un lien unique, `lien` pointe vers ce service alternatif.

Une année absente ou invalide est inconnue. Dans `communicabilite`, une période imprécise comportant
plusieurs années ne donne pas artificiellement la disponibilité de sa seule première année. Le conseil
et le lien tiennent compte des mêmes règles que la fiche du service.

## Compatibilité et données livrées

Les anciennes plages `en_ligne` restent lisibles : un résultat positif à l’intérieur est conservé ;
l’extérieur donne désormais `null` plutôt qu’une absence déduite. Les nouvelles règles d’un type de
document priment sur sa plage historique, y compris si ces règles sont invalides (échec prudent en
`null`, signalé par le validateur). Les nouvelles contributions doivent utiliser `couvertures`.

MATCHID conserve sa plage historique à titre de compatibilité des données, avec deux règles explicites
pour préserver les réponses connues depuis 1970 et avant 1970. Le périmètre de ce fichier ne décrit
pas la disponibilité des actes de décès dans les archives.

Les [relevés officiels du 7 novembre 2026](releves-archives-2026-11-07.md) alimentent AD08 (seuil glissant
et lacunes), AD13 (Marseille, couvertures variables et tables incomplètes) et AD26 (Romans-sur-Isère,
annonce jusqu’en 1924 et registres postérieurs annoncés en salle). Les périodes partielles ou annoncées
restent inconnues ; aucun nouveau résultat positif départemental n’est déduit. Aucun `verifie_le` n’est
modifié et aucune consultation humaine n’est revendiquée.

Le modèle utilise des noms de communes normalisés, sans résoudre les changements historiques de nom,
les fusions ni les homonymes d’un même département. Les saisies doivent prévoir les variantes nécessaires
et conserver `null` si le périmètre n’est pas établi.
