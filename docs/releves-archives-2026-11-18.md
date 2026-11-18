# Relevé des archives du 18 novembre 2026 — recherche de registres Mnesys (#128)

Relevé fait depuis l'hôte de travail, une machine **hébergée en centre de données** (précision de l'utilisateur,
18 novembre 2026). Les recettes restent enregistrées avec l'environnement `inconnu` : cette machine n'est pas
identifiée comme le VPS cible de #150, mais ses résultats valent pour une adresse IP de centre de données,
en HTTP simple, débit du plugin respecté (une requête toutes les 2 s environ pendant l'exploration). Aucun
défi anti-robot n'a été rencontré ; aucun n'aurait été contourné. Les `robots.txt` des services ne
contiennent aucune règle `Disallow` sur `/search`. Aucune donnée familiale n'a été utilisée : communes
chefs-lieux et année 1860.

## Méthode

1. Accueil de chacun des 12 services Naoned sans recette, puis pages « aide à la recherche » / « archives en
   ligne » : relevé des formulaires `/search/form/<uuid>` et de leur intitulé.
2. Lecture du formulaire « État civil » : champs (`0-controlledAccessGeographicName`, `2-date`,
   `3-date_begin`… ; sans indice à AD14 : `controlledAccessGeographicName`, `period_begin`), liste des communes
   (`data-options`), typologies (`controlledAccessPhysicalCharacteristic`).
3. Recherche réelle par l'outil `archives_registres` (chemin générique `sources/mnesys.py`), puis
   `archives_naviguer` (3 vues) et `archive_image` (largeur 400) sur la première vue du premier registre.
4. `GENEALOGISTE_RECETTE_ENVIRONNEMENT=inconnu make test-archives ECRIRE=1` : **11 réussis, 1 ignoré**
   (BnF : Cloudflare 403 sur le manifeste IIIF Gallica, recette arrêtée sans contournement).

## Résultats de bout en bout

| Service | Recherche | Premier registre (cote, ARK, période, vues) | Navigation et vue |
|---|---|---|---|
| AD14 Calvados | Bayeux, 1860, N | sans cote affichée, `ark:/52329/n1lc50f2vz8d`, 1853-1862, 42 | OK |
| AD19 Corrèze | Tulle, 1860, N | 2E/272/50, `ark:/69090/j6pl1tkd52mb`, 1860, 205 | OK |
| AD27 Eure | Évreux, 1860 | 28 Mi 50, `ark:/26335/q962nct0xfkp`, 1843-1862, 464 | OK |
| AD51 Marne | Épernay, 1860, D | 2 E 258/408, `ark:/86869/trh5nx2l10vs`, 1860, 62 | OK |
| AD55 Meuse | Verdun, 1860 | sans cote, `ark:/52669/985mlvpj2t0x` (tables décennales 1853-1862), 152 | OK |
| AD58 Nièvre | Nevers, 1860 | 5Mi1 89, `ark:/60877/r5dwqfj1k26p`, 1853-1860, 1 309 | OK |
| AD69 Rhône | Villefranche-sur-Saône, 1860 | 4E11628, `ark:/28729/sfwm2qtlk70n`, 1853-1862, 89 | OK |
| AD90 Territoire de Belfort | Delle, 1860, N | 1 E 33 TD 1 - 9, `ark:/12997/ws6xb0jv5rqm`, 1792-1862, 126 | OK |
| AD972 Martinique | Le Lamentin, 1860 | 2E14/29, `ark:/35569/2p4wv0sfxbcl`, 1858-1863, 128 | OK |

Ces registres servent de **recette de référence** (`recette` dans `archives_fr.json`).

## Registres matricules et tables des successions (#112)

Même chaîne (recherche → navigation → vue), formulaires dédiés relevés sur les pages publiques :

| Service | Type | Recherche | Premier registre (cote, ARK, période, vues) | Navigation et vue |
|---|---|---|---|---|
| AD19 Corrèze | RM | classe 1880, Tulle | R/1300, `ark:/69090/wkv0bgn7hrx9`, 1880, 520 | OK |
| AD27 Eure | RM | classe 1880 | 41 R 21-T (répertoire), `ark:/26335/8zx0493krbsf`, 1880, 5 | OK |
| AD55 Meuse | RM | classe 1880 | 1 R 421, `ark:/52669/sztqn28673dl`, 1880, 536 | OK |
| AD58 Nièvre | RM | classe 1880 | R 77, `ark:/60877/6mq2gwxps9fv`, 1880, 91 | OK |
| AD69 Rhône | RM | classe 1880, Lyon Central | 1RP811, `ark:/28729/j1xkg954mthr`, 1880, 393 | OK |
| AD90 Territoire de Belfort | RM | classe 1880 | 1 R 115, `ark:/12997/bqv7mgk28594`, 222 | OK |
| AD972 Martinique | RM | classe 1910 (aucun registre pour 1880) | 1R71, `ark:/35569/3wnlr5sg410m`, 1910, 464 | OK |
| AD27 Eure | SUCC | Évreux, 1860-1900 | 261 Q 21, tables 1857-1861 (navigation non essayée) | — |
| AD58 Nièvre | SUCC | bureau de Nevers, 1880 | 3 Q 19/1504, `ark:/60877/slvtmkxqhz0w`, 1876-1881, 174 | OK |
| AD69 Rhône | SUCC | bureau de Beaujeu, 1880 | 3Q5/906, `ark:/28729/4vn1hd92msj5`, 1875-1882, 173 | OK |
| AD90 Territoire de Belfort | SUCC | bureau de Delle, 1880 | 3 Q 27/19, `ark:/12997/j467gqb9f1r2`, 204 | OK |

- Une année proposée en liste (classes) doit être envoyée sous la forme `0-date[]` : la forme simple
  `0-date=1880` renvoie une erreur HTTP 500 (AD58, AD19).
- AD14 : le formulaire « Registres matricules » renvoie des **fiches individuelles** de soldats (index
  nominatif), non des registres ; il n'est pas déclaré.
- AD69 et AD90 nomment les bureaux « Bureau de … » dans un champ titre ou collectivité ; AD58 et AD25 dans le
  champ géographique.

## Particularités observées

- **AD27 (Eure)** n'était pas déclaré Naoned : la sonde passive (`scripts/sonder_visionneuses.py`) l'a
  classé `naoned_api` ce jour ; site passé en https, visionneuse et recherche déclarées après l'essai réel.
  Son vocabulaire contient « Amfreville_La_Campagne » et « Andelys (Les) (Eure, France) ».
- **Sonde passive des 101 services** : 15 API Naoned (AD14, AD19, AD25, AD27, AD37, AD39, AD51, AD55, AD58,
  AD59, AD69, AD80, AD90, AD91, AD972), 43 derrière un défi anti-robot (22 Anubis, 20 redirections JavaScript,
  1 Cloudflare : AD60), 6 injoignables (AD06, AD13, AD26, AD32, AD62, AD82), 37 autres moteurs. Les services
  protégés restent à qualifier dans un navigateur par une personne, sans contournement.

- **Vocabulaire des communes** propre à chaque site : « NEVERS », « Delle (Territoire de Belfort, France) »,
  « Lamentin (Le) », « VERDUN » à côté de « VERDUN (Saint-Amand) », communes anciennes « (… ; jusqu'en 1833) ».
  L'outil choisit la valeur exacte du formulaire et la renvoie (`commune_service`).
- **Typologie** : libellés différents (« Naissances », « baptêmes - naissances », « Naissance »…) ; absente à
  AD58 et AD55 (recherche sans type), et à AD972 hors du formulaire lu.
- **Cote** parfois non affichée dans la liste (AD14, AD55) : `cote` vaut alors `None`.
- **AD25 (Doubs)** : le formulaire « État civil » n'a qu'un champ commune et renvoie un nœud de commune
  (« Besançon », 2 médias, sans bornes), pas des registres : recherche par commune non déclarée. La recette par
  ARK connu reste valable. Formulaires « Tables décennales », « Matricules militaires » et « Tables des
  successions et absences » relevés pour la suite (#112).
- **Sans formulaire d'état civil trouvé** sur les pages publiques parcourues : AD37 (Indre-et-Loire), AD39
  (Jura), AD80 (Somme), AD91 (Essonne, seulement « tous les fonds »). AD73 (Savoie) n'utilise pas Mnesys Expo
  (moteur Eolas).
- **Planche-contact** (`archives_planche`) : essai réel réussi sur AD51 (4 vues) ; elle n'est donc pas propre
  à AD59, contrairement à ce qu'indiquait sa documentation.
- Les formulaires portent un attribut `data-captcha="hcaptcha"` ; aucune requête GET de recherche n'a déclenché
  de captcha pendant ce relevé.

## Limites

Relevé ponctuel, depuis une seule adresse : un service peut activer une protection plus tard. Une recherche
positive ne prouve pas la présence d'un acte, une négative ne prouve pas son absence. `verifie_le` n'est pas
modifié.

## Référentiel des archives (#25)

### Couvertures sourcées

Le texte d'aide des formulaires « État civil » annonce les bornes de mise en ligne. Elles sont saisies dans
`couvertures`, avec ce formulaire pour référence :

| Service | Saisie |
|---|---|
| AD19 Corrèze | `partielle` (dates variables) : naissances 1792-1922, mariages et décès 1792-1932, paroissiaux avant 1792 ; Brive-la-Gaillarde : `autre_service` (archives.brive.fr) |
| AD27 Eure | `en_ligne` 1792-1925 et paroissiaux jusqu'en 1792, toutes communes ; note sur l'arrondissement des Andelys |
| AD55 Meuse | `en_ligne` 1792-1901 ; `hors_ligne` à partir de 1902 (numérisation reprogrammée 2026-2027) |
| AD58 Nièvre | `en_ligne` 1792-1925 ; `hors_ligne` 1926-1946 (salle de lecture) ; tables décennales 1802-1902 ; paroissiaux `partielle` |
| AD69 Rhône | `partielle` hors Lyon : naissances jusqu'en 1925, mariages 1950, décès 1953, tables 1982 ; naissances et mariages postérieurs `hors_ligne` ; Lyon : `autre_service` (Archives municipales) |
| AD90 Territoire de Belfort | `en_ligne` 1792-1920 sauf Belfort ; Belfort `en_ligne` 1792-1912, puis `autre_service` (archives municipales) ; paroissiaux `partielle` |

Non saisis faute de bornes précises : AD14 (« jusqu'aux années 1990 », sous réserve des délais légaux),
AD51 (« deux ou trois premières décennies du XXe siècle en général »), AD972 (actes jusqu'en 1926 sans
périmètre par type).

### Protections relevées

`visionneuse_acces.protection` est renseigné pour les 42 services trouvés derrière un défi par la sonde
(`protection_releve_le` 2026-11-18, `protection_reference` = leur `/visualizer/api`) : `archives_service`
conseille alors la consultation manuelle, sans interdire un nouvel essai. Nouvelle valeur admise :
`redirection_js`.

### Corse, Mayotte, Alpes-Maritimes

- **AD2A, AD2B** : le portail commun `https://archives.isula.corsica/` oppose un défi Cloudflare (HTTP 403,
  « Attention Required! ») ; pas de `robots.txt`. Protection consignée ; les périodes par fonds restent à établir
  par une consultation humaine.
- **AD976** : l'adresse relevée le 8 novembre renvoie 404 ; le guide des Archives départementales est publié à
  `https://publications.mayotte.fr/publications/guide-des-archives-departementales-de-mayotte` (publication, pas
  une visionneuse). Aucun portail de registres identifié.
- **AD06** : `https://archives06.fr/` présente une chaîne de certificats TLS incomplète pour un client HTTP
  (`CERTIFICATE_VERIFY_FAILED`) ; la vérification n'a pas été désactivée. L'accès aux fonds reste non validé.

## Portée pour #150 (adresse de centre de données)

Depuis cette adresse de centre de données : les 13 services Mnesys essayés (AD14, AD19, AD25, AD27, AD39, AD51,
AD55, AD58, AD59, AD69, AD90, AD91, AD972) ont répondu sans défi, recherche, navigation et image comprises ;
Gallica (Cloudflare 403), le portail des Archives de Corse (Cloudflare 403) et 43 visionneuses
départementales (Anubis, redirection JavaScript, Cloudflare) ont opposé un défi. Ces protections peuvent
viser les adresses de centre de données plutôt que les clients automatisés en général : la comparaison avec
une adresse résidentielle (relevé du 2026-11-10 : aucun défi sur AD59) reste à faire service par service.
