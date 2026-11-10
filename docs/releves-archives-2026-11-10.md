# Relevé des visionneuses départementales (10 novembre 2026)

Étape 1 de l’issue #128 : identifier, pour les 101 services départementaux, la visionneuse des
registres afin de regrouper la prise en charge par éditeur. Relevé automatisé, sans contrôle humain
revendiqué : `releve_le` est renseigné, `verifie_le` n’est pas modifié. Aucune protection anti-robot
n’a été contournée.

## Méthode

1. Sonde passive [`scripts/sonder_visionneuses.py`](../scripts/sonder_visionneuses.py) : une requête
   `GET <site>/visualizer/api` par service. L’API Naoned de l’AD59 répond, sans paramètre, par
   HTTP 400 et le JSON `"Unable to handle this request"` ; cette signature sert de détecteur.
2. Pour chaque service détecté, recherche d’un ARK réel de registre, puis requête
   `visualizer/api?naan=…&arkName=…&start=0&end=0&group=0`.
3. Recette réelle complète (`scripts/verifier_telechargements.py`) : résolution, aperçu, recadrage,
   `piece_archiver` et répétition sans réseau, dans un dossier jetable.
4. Lecture de pages publiques (pied de page, chemins de ressources) pour les autres éditeurs.

La visionneuse `/visualizer/api` relève du logiciel **Mnesys**, édité par
[Naoned](https://naoned.fr/ressources/) (indication du mainteneur, cohérente avec la page de l’éditeur).

## Résultats de la sonde

| Classe | Nb | Services |
|---|---|---|
| `naoned_api` | 14 | AD14 AD19 AD25 AD37 AD39 AD51 AD55 AD58 AD59 AD69 AD80 AD90 AD91 AD972 |
| `anubis` (défi anti-robot) | 22 | AD01 AD02 AD05 AD07 AD16 AD31 AD33 AD34 AD41 AD42 AD48 AD57 AD63 AD67 AD70 AD74 AD76 AD79 AD86 AD89 AD93 AD95 |
| `redirection_js` (défi JavaScript) | 20 | AD03 AD04 AD08 AD10 AD15 AD18 AD28 AD36 AD43 AD45 AD46 AD50 AD54 AD65 AD71 AD72 AD78 AD83 AD87 AD94 |
| `cloudflare` | 4 | AD40 AD60 AD2A AD2B |
| `injoignable` | 5 | AD13 AD26 AD27 AD32 AD62 |
| `autre` | 36 | le reste (pas de `/visualizer/api` reconnu) |

Les classes `anubis`, `redirection_js` et `cloudflare` (46 services) ne sont pas qualifiables sans
navigateur ; elles peuvent cacher une visionneuse Naoned. Elles restent inconnues.

## Naoned / Mnesys `/visualizer/api`

| Service | ARK de registre testé | Résultat |
|---|---|---|
| AD59 | `ark:/33518/d31bpqk27xhj`, table `q0km71zxrv5s` | recette complète OK (relevés antérieurs, rejouée) |
| AD25 | [`ark:/25993/7rx3d5cm9tzk`](https://archives.doubs.fr/ark:/25993/7rx3d5cm9tzk) (Baume-les-Dames, D 1873-1892) | recette complète OK après correctif (voir plus bas) |
| AD39 | [`ark:/36595/p3rdck27zjbm`](https://archives39.fr/ark:/36595/p3rdck27zjbm) (Goux, NMD et tables décennales) | recette complète OK |
| AD14, AD19, AD37, AD51, AD58, AD69 | fiches d’inventaire | API présente ; `Group with index 0 not found` ou `No record…` : la fiche n’est pas l’objet numérisé |
| AD55, AD80, AD90, AD91, AD972 | aucun ARK de registre trouvé | API présente, non testée |

Référentiel :

- AD25, AD39 : `resolution_image.type = visualizer_api` et `visionneuse_acces` (éditeur `naoned`).
  AD25 : site passé en `https://` (le `http://` redirige ; le contrôle d’origine des URL d’image
  l’exige). AD39 : NAAN `36595`, lu dans les ARK du site et accepté par l’API.
- Les 11 autres : `visionneuse_acces` seul (éditeur `naoned`, IIIF et protection inconnus), sans
  `resolution_image` tant qu’aucune recette réelle n’a réussi. Pour AD14 (Calvados), la fiche d’un
  registre indique « images consultables via le formulaire de recherche dédié » : les ARK lisibles
  sont à prendre dans ce formulaire.

**Correctif** : l’AD25 annonce dans `location.iiif` le *manifeste* du registre
(`/iiif/ark:/…/manifest.json`), pas un service d’image. L’adaptateur le prenait pour un service et tentait
`…/manifest.json/full/800,/0/gray.jpg` (404). Un manifeste est désormais écarté au profit de l’image
originale (`tests/test_visionneuses.py`).

## Autres éditeurs identifiés

| Service | Éditeur / logiciel | Indice (page lue) |
|---|---|---|
| AD73 | Naoned, Mnesys ancienne génération | chemin `interfaces/mnesys_cg73portailv1` sur [recherche-archives.savoie.fr](https://recherche-archives.savoie.fr) ; pas de `/visualizer/api` |
| AD92 | Ligeo Archives | pied de page « Ligeo Archives » sur la [recherche état civil](http://archives.hauts-de-seine.fr/archive/recherche/etatcivil/n:92) |
| AD973 | AvenioWeb | mentions `avenioweb` sur [archives.ctguyane.fr](http://archives.ctguyane.fr/) |
| AD61 | GAIA | page [état civil](https://archives.orne.fr/index.php/etat-civil) ; éditeur non établi, non saisi |
| AD35 | Thot (indice faible) | lien `/thot_internet/` ; visionneuse non ouverte, non saisi |

## Limites

- Registres matricules : aucun ARK trouvé sur les services testés ; accès non relevé.
- Un classement `naoned_api` ne garantit pas l’accès aux images (protections possibles à l’image).
- Les relevés par agents de lecture web ont été peu concluants (pages rendues en JavaScript,
  défis anti-robot) ; seules les valeurs vérifiées ci-dessus ont été saisies.

## Suite

1. Qualifier les 46 services protégés avec un navigateur, sans contournement.
2. Trouver un ARK de registre pour les 11 services Naoned non testés, puis recette et
   `resolution_image`.
3. Adaptateurs suivants par nombre de services : à décider après l’étape 1 ; Ligeo, AvenioWeb et
   Mnesys ancienne génération n’ont pour l’instant qu’un service chacun.
