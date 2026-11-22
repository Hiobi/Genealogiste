# Du fait connu à la conclusion sourcée

Prenons un cas fictif : Jean MARTIN serait né vers 1820 près de Rochefort. La question n’est pas seulement
« trouver ce nom », mais établir quel acte concerne la bonne personne et ce qu’il permet de conclure.

## 1. Formuler une question précise

Partir d’une fiche et des informations déjà connues : conjoint, enfants, profession, lieu, dates.
Une question utile : « Quel acte permet d’établir la naissance de cette personne ? »
Lister les faits établis, les hypothèses et les contradictions avant de chercher.

`/genealogiste:fiche I1` lit la fiche ; `/genealogiste:lacunes I1` aide à choisir le prochain travail.
Les identifiants dépendent de l’arbre chargé.

## 2. Chercher et garder les résultats négatifs

Pour une personne historique, `/genealogiste:cherche` lance une recherche multi-sources.
Pour une enquête plus large, `/genealogiste:enquete` coordonne recherche, recoupement et vérification.
Lire les [sources disponibles et leurs limites](Sources.md) avant d’interpréter une absence de résultat.
Une requête sans résultat est une observation à dater et à conserver, pas une preuve d’absence.

Une enquête garde son état : pistes, demandes faites, registres en cours et tâches à faire à la main
([état d’enquête](../docs/enquetes.md)). Après une interruption, relancer la même commande la reprend ;
une demande déjà faite est signalée « déjà fait le … » (un signal, jamais un blocage). Un budget (requêtes
par site, images lues) arrête l’enquête proprement et dit ce qui reste à faire. Avec `--autonome`, l’enquête
avance sans question : ce qui demande une personne devient une tâche manuelle, et les conclusions attendent
dans la file de propositions. `/genealogiste:campagne` enchaîne ces enquêtes sur les lacunes prioritaires,
par exemple dans une tâche planifiée ([campagne sans surveillance](../docs/campagne.md)).

Pour les vivants, rester sur les données privées dont vous disposez et respecter les
[gardes de confidentialité](Confidentialite.md).

## 3. Lire l’acte et citer ce que vous avez réellement consulté

Un index et l’image du même acte ne constituent pas deux preuves indépendantes.
Noter le service d’archives, la cote, la commune, la date, le numéro d’acte, la vue, le lien et la date de consultation.
Indiquer si vous avez lu l’original, une image, une transcription, un index ou seulement une mention.

La transcription peut relever parents, témoins, parrains, professions et lieux. Distinguer le texte lu,
les passages incertains et les déductions ; ne pas compléter un mot illisible comme s’il était certain.
La commande `/genealogiste:transcris` apporte une aide, à relire face à l’image.

Pour trouver l’acte lui-même, `/genealogiste:acte` cherche le registre par commune et année (AD59 et quatorze
services Mnesys ; ailleurs, la cote ou l’ARK est à relever sur le site du service), repère la vue, aide à la
transcrire et archive la pièce ([services d’archives](Services-archives.md)).

## 4. Comparer les candidats

Vérifier dates, lieux, relations et réseau de témoins ; une similitude de nom ne suffit pas.
`/genealogiste:recoupe` argumente la comparaison. Une contradiction forte ne disparaît pas parce que
plusieurs arbres en ligne recopient la même information.
Faire appel à `/genealogiste:verifie` pour une relecture indépendante, sans lui présenter seulement
la conclusion du chercheur. Les sources originales indépendantes sont plus utiles que leur nombre brut.

## 5. Lire le statut de preuve comme une aide

| Statut | Lecture pratique |
|---|---|
| Non sourcé | Il manque une citation exploitable |
| Hypothèse | Une piste existe ; rechercher les éléments qui la confirmeraient ou l’infirmeraient |
| Probable | Faisceau d’indices encore insuffisant pour la règle de confirmation |
| Confirmé | Les citations satisfont les règles de calcul ; relire leur contenu et leur indépendance |
| Contradictoire | Des faits ou sources incompatibles demandent une analyse |
| Réfuté | Rejet explicite et justifié d’une proposition |

Le calcul regroupe les citations d’une même source originale. Il pondère leur nature et leur consultation ;
il ne vérifie pas magiquement la vérité du contenu saisi. Le mode strict est configurable.
En mode pondéré, un groupe vaut au plus 2 points pour une source originale, primaire et directe,
1 sinon ; un arbre en ligne composite, une citation non vue ou une preuve négative ne comptent pas.
Une consultation par index ou transcription reste au plus à 1 point. « Confirmé » exige au moins
3 points et 2 groupes indépendants ; « probable » 2 points ; « hypothèse » 1 point. En mode strict,
les groupes admissibles valent chacun 1 : seuils de 3, 2 et 1 groupes respectivement.

Les classifications sont décrites dans les [extensions GEDCOM](../docs/gedcom-extensions.md).

## 6. Proposer, décider, puis conserver la conclusion

Demander une proposition d’ajout avec citation et justification. Lire le diff et les nouvelles alertes.
Refuser ou corriger tant que l’identité ou la lecture de l’acte reste incertaine. Appliquer après accord,
puis vérifier la fiche et le journal. Il n’y a pas de fusion automatique d’homonymes.
Les propositions d’une enquête autonome sont déposées dans une [file](../docs/propositions.md) :
`/genealogiste:valide` les présente une à une, avec un diff recalculé sur l’arbre courant, et n’applique
qu’après votre accord. Une citation ou une source erronée se corrige de la même façon : retrait d’une
citation, suppression ou fusion de sources ([opérations](../docs/operations.md#supprimer-une-citation-ou-une-source-248)).

`/genealogiste:preuve` aide à rédiger un rapport ; `/genealogiste:recit` un récit sourcé qui distingue
faits, déductions et hypothèses. Conserver les pièces et les questions non résolues pour reprendre l’enquête.
