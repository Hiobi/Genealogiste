# Visionneuse AD59 : contrat observé et recettes

Le 8 novembre 2026, quatre recettes natives ont réussi avec
[`scripts/verifier_telechargements.py`](../scripts/verifier_telechargements.py) : deux
ressources AD59, une ressource suisse et une de la Library of Congress. Pour AD59,
la résolution, l'aperçu, le recadrage, `piece_archiver` et la répétition de l'archivage
sans accès réseau ont réussi sur un registre et une table décennale. Le
[relevé international](telechargement-international.md) détaille les quatre cas.

## Recettes AD59

| Ressource | Sélection | Original → aperçu | Estimation aperçu | Requêtes du cas complet |
|---|---|---|---|---|
| Registre `d31bpqk27xhj` | UUID de vue, vue 287 | 2056 × 1456 → 800 × 567 | 605 tokens | API et image : 2 réponses HTTP 200 |
| Table décennale `q0km71zxrv5s` | `page=25` | 1816 × 2450 → 800 × 1079 | 1151 tokens | Sélection par page, résolution de vue et image : 3 réponses HTTP 200 |

Les deux cas utilisent le mode `visionneuse:visualizer_api`. La seconde conservation
n'a produit aucune requête réseau. Les essais ont utilisé un arbre vide et un dossier
jetable supprimé ensuite, sans écriture dans une généalogie réelle ni ajout d'image
ou de JSON réel au dépôt.

La table est celle du [compte rendu initial de l'issue #101](https://github.com/Hiobi/Genealogiste/issues/101#issuecomment-6723821795),
« ERRE TD 1883-1892 », cote `3E TD 203/10`. Son UUID, tronqué dans ce compte rendu,
a été obtenu intégralement par le pipeline depuis l'API officielle. Le
[lien de vue complet](https://archivesdepartementales.lenord.fr/ark:/33518/q0km71zxrv5s/70c8ed68-98db-43f4-acc2-862a0b6ce1ae)
est donc identifié sans reconstruction par supposition.

## Contrat JSON observé

Des requêtes HTTP directes avec `curl` ont confirmé les deux formes d'accès avant
les essais du module Python. Leurs réponses officielles ont été inspectées.

| Endpoint officiel | Résultat du 8 novembre 2026 |
|---|---|
| [Sélection par UUID](https://archivesdepartementales.lenord.fr/visualizer/api?naan=33518&arkName=d31bpqk27xhj&uuid=b27563d3-2ef8-4798-832a-d604a4e131dc) | HTTP 200 ; objet contenant `counts`, `positions`, `media` et `app` |
| [Sélection par page](https://archivesdepartementales.lenord.fr/visualizer/api?naan=33518&arkName=d31bpqk27xhj&start=286&end=286&group=0) | HTTP 200 ; dictionnaire indexé `{"286": media}` |

Pour la réponse UUID, `counts.media=1024`, `positions.media=286` et le média sélectionné
est `media["286"]`. La vue publique 287 correspond donc à l'indice 286. Pour une page
`N`, la requête utilise `start=end=N-1` et `group=0`. La réponse par page ne fournit pas
à elle seule le nombre total de vues : ne pas l'inventer.

**Écart avec l'étude initiale :** le compte rendu utilisateur décrivait une liste pour
`start/end` ; la réponse actuelle est un dictionnaire indexé par position. Les tests
doivent couvrir ce dictionnaire ; la forme liste constitue une compatibilité avec le
format rapporté, pas le format observé lors de la recette.

Le média contient notamment `url` (ARK de vue), `uuid`, `record`, `location`, `type` et
`format`. Son `record.arkId` est un objet
`{"arkName": "d31bpqk27xhj", "naan": 33518}` : le NAAN est numérique.
`location.original` est une URL HTTPS d'image sur le même service ; `location.iiif=null`
pour les ressources étudiées. Cela ne qualifie pas l'ensemble des fonds AD59.
`app.licenses.visualizer` contient `text`, `enabled=true`, `uuid` et `locale`.

Le [compte rendu utilisateur](https://github.com/Hiobi/Genealogiste/issues/101#issuecomment-6723821795)
rapporte aussi une API découverte dans le bundle JavaScript, des vues voisines dans la
réponse UUID, et un HTTP 400 pour `naan+arkName` sans sélection de vue. Ces observations
restent attribuées à cette étude lorsqu'elles ne sont pas exercées par les recettes.
Aucune documentation officielle versionnée de cette API interne n'a été qualifiée :
son contrat peut changer.

## Licence et provenance

Le texte intégral de `app.licenses.visualizer.text`, lu dans la
[réponse officielle par UUID](https://archivesdepartementales.lenord.fr/visualizer/api?naan=33518&arkName=d31bpqk27xhj&uuid=b27563d3-2ef8-4798-832a-d604a4e131dc),
mentionne la délibération départementale du 27 mars 2017, une redevance et une licence
pour la réutilisation commerciale. Les autres réutilisations sont annoncées gratuites
avec citation du service, de la cote et de la date de dernière mise à jour, ainsi que
préservation du sens et de l'intégrité de l'information. Le texte rappelle aussi la
responsabilité relative aux données personnelles. Ce résumé n'en fournit pas une
interprétation juridique ni une garantie pour toutes les pièces.

Conserver la déclaration effectivement reçue et sa provenance. Une licence absente
d'une réponse par page ne doit pas être inventée. L'ARK de vue sert à la citation ;
l'URL technique `/images/...jpg` reste une adresse de téléchargement.
La [précision du besoin](https://github.com/Hiobi/Genealogiste/issues/101#issuecomment-6723853010)
demande de privilégier IIIF s'il est exposé, sinon de traiter l'image originale en local.
La présence de voisins dans le JSON ne justifie pas leur téléchargement.

## Portée et limites

Les chiffres de tokens sont des estimations par surface de pixels, environ un token
pour 750 pixels, pas une facture ni une mesure d'inférence. Aucun modèle distant n'a
été appelé : ces recettes ne valident ni transcription, ni rendu dans un LLM, ni lecture
humaine. Elles exercent le module Python, sans attester une invocation complète du plugin.
Aucun contrôle humain ni `verifie_le` n'est revendiqué. Des tentatives préalables ont
rencontré une restriction DNS d'environnement ; les essais autorisés ont ensuite réussi.

Les tests ordinaires emploient des fixtures synthétiques : objet UUID, dictionnaire par
page actuel, ancienne liste, table, IIIF exposé, 400, réponse vide et registre incohérent.
Les tests réseau restent explicites, hors CI, avec une seule vue par ressource. Aucun
compte, défi ou contournement n'a été utilisé. Un service non qualifié conserve un repli
manuel ; ces deux ressources AD59 ne constituent pas une validation de tous ses fonds.
