# Recette AD59 : du registre à une vue candidate archivée

Ce lot de #112 valide le raccordement entre les outils existants : recherche par commune et année,
registre candidat unique, navigation sur la première vue, archivage de l'original et de sa note compagnon,
puis répétition sans nouveau téléchargement. **La première vue est une vue candidate, pas un acte identifié.**
Aucun nom de personne réelle, export familial, rattachement d'acte ni modification d'arbre n'est nécessaire.

## Exécution volontaire

Depuis la racine du dépôt :

```bash
GENEALOGISTE_TEST_CHAINE_AD59=1 uv --directory mcp run pytest tests/test_chaine_archives_live.py -rs
```

La suite ordinaire ignore cette recette réseau. Elle utilise uniquement des données et médias temporaires,
contrôle `robots.txt`, effectue une recherche NMD pour Saint-Vaast-en-Cambrésis en 1860, refuse un résultat
ambigu, demande une fenêtre d'une vue, puis archive cette vue une fois. Les appels HTTP n'ont qu'une tentative.
Un défi interrompt la chaîne, conserve l'enveloppe et la tâche manuelle ; aucune autre piste ni adresse n'est
essayée. Un résultat vide arrête le parcours sans affirmer l'absence d'acte.

Le JSON `recette-chaine-ad59.json` est écrit dans le dossier temporaire du test, avec les résultats d'étape,
la date UTC, la révision de base, l'état modifié du checkout et les empreintes du code de recette.
L'environnement reste `inconnu` : ce test ne qualifie pas le VPS. Les fichiers temporaires contiennent
l'image publique et sa note ; ils ne sont pas publiés dans le dépôt.

## Vérifications

Les tests synthétiques suivent le même helper : depuis les lieu et année d'une personne fictive décédée,
les outils trouvent le registre sans ARK fourni, puis archivent la vue. Le nom et l'identifiant restent
absents des requêtes distantes. Une personne vivante fictive bloque la recherche avant tout réseau.

Le parcours vérifie l'ARK de vue issu du registre découvert, le numéro de vue, la cote cohérente entre
recherche et archivage, la citation suggérée, l'original dans le dossier de médias temporaire et la note
compagnon (ARK, URL image, date de consultation, SHA-256). Les octets et l'empreinte sont vérifiés sur l'image
synthétique. La répétition est idempotente et l'arbre reste identique. Les cas négatifs couvrent une recherche
vide et un défi à chacune des trois étapes recherche, navigation et archivage.

## Relevé du 17 novembre 2026

Premier essai réel à 08:06 UTC sur la base `76130bc`, checkout modifié par les fichiers de ce lot :
`1 passed in 7.32s`. Environnement réseau non qualifié. Résultat : registre
`ark:/33518/jq9hpbzxnc72`, cote `5 Mi 018 R 024`, période 1831–1864, 954 vues.
La première vue retournée est `ark:/33518/jq9hpbzxnc72/789fb8c6-4b17-4414-8659-5cb9635edc85`.
Son original et la note compagnon ont été archivés dans le dossier jetable ; la répétition a reconnu la
pièce déjà archivée. Aucun acte nominatif n'a été lu ni identifié.

Second essai à **08:09:32 UTC**, depuis le checkout propre à
`83c148705043e04b8726ad673ddc522f0469a550` : **`1 passed in 7.50s`**.
Le rapport confirme `checkout_modifie: false`, `environnement: inconnu`,
`acte_identifie: false` et `vue_candidate_archivee: true`. La recherche a renvoyé un registre ;
la même vue 1/954 a été archivée (254 138 octets), avec sa cote, son ARK et sa note compagnon.
La répétition a renvoyé `deja_archivee: true`. Cette preuve concerne seulement la ressource publique
indiquée et ne qualifie toujours pas un accès depuis le VPS.

Ce relevé ne qualifie ni les tables décennales, ni les matricules, ni les successions, ni les autres services.
Il ne clôt pas #112 et ne change pas `chaine_complete` du tableau de couverture : l'identification de l'acte
et les autres fonds restent à éprouver.
