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

## Logiciel : Mnesys Expo (Naoned)

Vérification dans le code des pages (10 novembre 2026) :

- **12 services sur 14** affichent dans leur page `/page/credits` « Conception et réalisation : Naoned »
  et décrivent le logiciel **Mnesys Expo** (portail public) aux côtés de Mnesys Archives (gestion
  interne) : AD19, AD37, AD39, AD51, AD55, AD58, AD59, AD69, AD80, AD90, AD91, AD972. Exemple :
  [crédits AD37](https://archives.touraine.fr/page/credits).
- **AD14 et AD25** n’ont pas de page de crédits. Ils servent pourtant le même socle : même ressource
  `/assets/common.9810116a885a90cd2023.js` (empreinte identique sur les 14 sites), même arborescence
  `/assets/src/application/Custom/…`, même API. La page [ressources de Naoned](https://naoned.fr/ressources/)
  cite les Archives du Calvados.
- **Version : non exposée.** Ni balise `generator`, ni commentaire, ni en-tête (`Server: nginx`/`Apache`,
  pas de `X-Powered-By`), ni chaîne dans les bundles JS (seules les versions de Bootstrap, Modernizr…),
  ni champ dans le bloc `app` de l’API. Le référentiel garde `version: null` ; les empreintes des
  bundles `front.*.js` diffèrent d’un site à l’autre (personnalisation), seul `common.*.js` est partagé.
- **AD73** sert une génération antérieure : chemins `interfaces/mnesys_cg73portailv1/…` et horodatages
  d’assets de 2017-2018, sans `/visualizer/api`. Elle est notée `Mnesys (portail v1)` ; l’adaptateur
  `visualizer_api` ne s’y applique pas.

Sources secondaires : la [Revue française de généalogie](https://www.rfgenealogie.com/mots-cles/naoned)
mentionne la visionneuse Mnesys Expo de la Somme et des sites Naoned (Nord, Rhône) ; le
[panorama de D. Roegel (2014)](https://locomat.loria.fr/other/roegel2014panorama-archives.pdf) a une
section « Mnesys 2.0 ». Aucune ne donne de numéro de version de Mnesys Expo.

Référentiel : `visionneuse_acces.logiciel` (`Mnesys Expo` ou `Mnesys (portail v1)`), `version: null`,
`reference_logiciel` vers la page de crédits quand elle existe.

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

Recherche des ARK : la recherche générale de Mnesys Expo (`<site>/search/results?q=…`, formulaire
« Moteur de recherche » commun aux 14 sites) avec « naissances mariages décès », « tables décennales »
puis « registre matricule » ; chaque ARK de résultat est essayé sur
`visualizer/api?…&start=0&end=0&group=0` jusqu’au premier qui renvoie une vue (`uuid`). Les fiches
d’inventaire sans images répondent `Group with index 0 not found`. Recette complète
(`verifier_telechargements.verifier`) sur la vue obtenue, dans un dossier jetable.

| Service | État civil / tables décennales | Registre matricule | Recette |
|---|---|---|---|
| AD59 | `ark:/33518/d31bpqk27xhj`, table `q0km71zxrv5s` | — | OK (relevés antérieurs, rejouée) |
| AD25 | [`ark:/25993/7rx3d5cm9tzk`](https://archives.doubs.fr/ark:/25993/7rx3d5cm9tzk) (Baume-les-Dames ; D 1873-1892) | — | OK après correctif (voir plus bas) |
| AD39 | [`ark:/36595/p3rdck27zjbm`](https://archives39.fr/ark:/36595/p3rdck27zjbm) (Goux ; NMD et tables décennales) | — | OK |
| AD14 | [`ark:/52329/4gp0hnm92sbz`](https://archives.calvados.fr/ark:/52329/4gp0hnm92sbz) (La Boissière ; 1793-1866) | [`ark:/52329/p1cb03qln5t2`](https://archives.calvados.fr/ark:/52329/p1cb03qln5t2) (1R/44) | OK |
| AD19 | [`ark:/69090/z19r485ldctn`](https://www.archives.correze.fr/ark:/69090/z19r485ldctn) (Bort-les-Orgues ; NMD 1918-1922 ; 2E/28/24) | [`ark:/69090/9nx41wgfdb5p`](https://www.archives.correze.fr/ark:/69090/9nx41wgfdb5p) (Tulle ; classe 1871 ; R/1285) | OK |
| AD37 | [`ark:/37621/6mgzwc8spr1f`](https://archives.touraine.fr/ark:/37621/6mgzwc8spr1f) (Marcilly-sur-Maulne ; table décennale ; 6NUM2/147/001) | [`ark:/37621/dbq6h2wm8l45`](https://archives.touraine.fr/ark:/37621/dbq6h2wm8l45) (classe 1906 ; 1R742) | OK |
| AD51 | [`ark:/86869/3kpcd0z4mx65`](https://archives.marne.fr/ark:/86869/3kpcd0z4mx65) (Coole ; table décennale 1853-1862 ; 125 M 88) | non trouvé | OK |
| AD55 | [`ark:/52669/bf187l9vsd35`](https://archives.meuse.fr/ark:/52669/bf187l9vsd35) (Bouvigny ; tables décennales 1803-1902 ; 1 E 162) | non trouvé | OK |
| AD58 | [`ark:/60877/vj8cnfkzw916`](https://archives.nievre.fr/ark:/60877/vj8cnfkzw916) (Asnan ; tables décennales ; 5 Mi TD 03) | non trouvé | OK |
| AD69 | [`ark:/28729/bh9t7gpds0vn`](https://archives.rhone.fr/ark:/28729/bh9t7gpds0vn) (Salles ; N-PM-M-D ; 4E7676) | [`ark:/28729/7jpsqh5l4b1g`](https://archives.rhone.fr/ark:/28729/7jpsqh5l4b1g) (Lyon Central ; 1RP888) | OK |
| AD80 | [`ark:/58483/q85zl30vcw2t`](https://archives.somme.fr/ark:/58483/q85zl30vcw2t) (Chuignolles ; NMD ; 5MI_D114) | non trouvé | OK |
| AD90 | [`ark:/12997/1mt6cx54v3dl`](https://archives.territoiredebelfort.fr/ark:/12997/1mt6cx54v3dl) (Beaucourt ; 1 E 9 NDM 14-15) | non trouvé | OK |
| AD91 | [`ark:/28047/ws6n0xqzk29d`](https://archives.essonne.fr/ark:/28047/ws6n0xqzk29d) (Dourdan ; tables décennales des registres paroissiaux ; 1MI/306/3) | non trouvé | OK |
| AD972 | [`ark:/35569/kf79xhdvrjc8`](https://www.patrimoines-martinique.org/ark:/35569/kf79xhdvrjc8) (Le François ; NMD ; 2E11/21) | [`ark:/35569/s3nxzwm6p9tq`](https://www.patrimoines-martinique.org/ark:/35569/s3nxzwm6p9tq) (états signalétiques ; 1R11) | OK |

Pour les matricules, la recherche a aussi renvoyé des « registres matricules » hors série R (enfants
trouvés X 1196 à l’AD58, maison d’arrêt 99Y375 à l’AD80, 3 X 112 à l’AD90) : écartés.

Référentiel : les 14 services ont `resolution_image.type = visualizer_api`. Sites passés en
`https://` quand le `http://` redirige (AD25, AD55, AD58, AD69, AD80, AD91, AD972 : le contrôle
d’origine des URL d’image l’exige). NAAN lus dans les ARK du site et acceptés par l’API : AD39
`36595`, AD972 `35569`. `iiif: true` quand la vue annonce un manifeste (AD25, AD37, AD51, AD80,
AD91).

**Correctif** : l’AD25 annonce dans `location.iiif` le *manifeste* du registre
(`/iiif/ark:/…/manifest.json`), pas un service d’image. L’adaptateur le prenait pour un service et tentait
`…/manifest.json/full/800,/0/gray.jpg` (404). Un manifeste est désormais écarté au profit de l’image
originale (`tests/test_visionneuses.py`).

## Autres éditeurs identifiés

| Service | Éditeur / logiciel | Indice (page lue) |
|---|---|---|
| AD73 | Naoned, Mnesys portail v1 | chemin `interfaces/mnesys_cg73portailv1` sur [recherche-archives.savoie.fr](https://recherche-archives.savoie.fr) ; pas de `/visualizer/api` |
| AD92 | Ligeo Archives | pied de page « Ligeo Archives » sur la [recherche état civil](http://archives.hauts-de-seine.fr/archive/recherche/etatcivil/n:92) |
| AD973 | AvenioWeb | mentions `avenioweb` sur [archives.ctguyane.fr](http://archives.ctguyane.fr/) |
| AD61 | GAIA | page [état civil](https://archives.orne.fr/index.php/etat-civil) ; éditeur non établi, non saisi |
| AD35 | Thot (indice faible) | lien `/thot_internet/` ; visionneuse non ouverte, non saisi |

## Limites

- Registres matricules : lisibles par la même visionneuse sur AD14, AD19, AD37, AD69 et AD972 ;
  non trouvés par la recherche générale ailleurs (pas de conclusion d’absence).
- Un classement `naoned_api` ne garantit pas l’accès aux images (protections possibles à l’image).
- Les relevés par agents de lecture web ont été peu concluants (pages rendues en JavaScript,
  défis anti-robot) ; seules les valeurs vérifiées ci-dessus ont été saisies.

## Suite

1. Qualifier les 46 services protégés avec un navigateur, sans contournement.
2. Rejouer périodiquement les recettes (le CI mocké ne voit pas un changement d’API réelle).
3. Adaptateurs suivants par nombre de services : à décider après l’étape 1 ; Ligeo, AvenioWeb et
   Mnesys ancienne génération n’ont pour l’instant qu’un service chacun.
