---
name: seconde-guerre-mondiale
description: Recherche généalogique sur un ancêtre pendant la Seconde Guerre mondiale (1939-1945) — mobilisé, prisonnier de guerre (Stalag, Oflag), déporté, interné, travailleur forcé (STO), résistant (FFI, FFL, GR 16 P), incorporé de force (malgré-nous d'Alsace-Moselle), mis en cause à l'épuration (cour de justice, chambre civique), soldat de la Wehrmacht ou de la Waffen-SS, membre du NSDAP, victime civile. Sources : SHD (Vincennes, DAVCC Caen), Mémoire des hommes, Archives nationales, archives départementales (série W), Arolsen Archives, Bundesarchiv, Volksbund, USHMM, Mémorial de la Shoah, FMD. À utiliser pour « mon grand-père prisonnier », « déporté », « STO », « résistant », « malgré-nous », « épuration », « collaborateur », « Wehrmacht », « 39-45 ».
---

# Seconde Guerre mondiale — parcours de recherche

Référence détaillée (fonds, accès, droit) : `docs/seconde-guerre-mondiale.md`. Appliquer aussi
`methodologie-gps`, `sources-francaises` et `droit-communicabilite`.

## Règles propres à cette période

1. **Ne jamais qualifier un ancêtre** (collaborateur, résistant, déporté…) sans pièce qui le dise. Écrire ce que
   dit le document, avec son vocabulaire et sa date : « dénoncé », « arrêté », « poursuivi », « jugé »,
   « condamné à… », « acquitté », « relaxé », « amnistié », « homologué FFI ». Une accusation, une enquête, un
   jugement et une condamnation sont quatre faits distincts, chacun avec sa source. Une rumeur familiale reste
   une **hypothèse**.
2. Un **statut** (déporté résistant, interné politique, personne contrainte au travail, mort pour la France) est
   une décision administrative datée, souvent postérieure : la citer comme telle, pas comme un fait de 1940-1945.
3. **Homonymes** : listes allemandes, graphies phonétiques, prénoms germanisés. Produire les graphies avec
   `variantes_noms(nom, prenom)`, comparer avec `comparer_noms` / `comparer_profils`, et rattacher par la date et le
   lieu de naissance, jamais par le nom seul.
4. **Personnes vivantes** : une personne née après 1920 peut être vivante. `arbre_vivant` avant toute recherche
   externe ; rien d'une personne vivante vers un site ou un outil réseau. Prudence aussi pour les descendants
   nommés dans les dossiers d'épuration ou de spoliation.
5. **Communicabilité** : dossiers judiciaires 75 ans (100 ans si mineurs), vie privée 50 ans, médical 120 ans
   (`communicabilite`). L'arrêté du 24 décembre 2015 a ouvert par dérogation générale une partie des archives
   publiques de la période (police, justice) : vérifier son périmètre auprès du service, ne pas le présumer.
6. Aucun contournement : Arolsen, Bundesarchiv, Volksbund, Mémoire des hommes se consultent dans le navigateur
   de l'utilisateur ; les dossiers non numérisés se **demandent** (courrier ou formulaire du service).

## Outils

- `sources_catalogue(theme="ww2")` : fonds connus du plugin (FMD, Mémorial de la Shoah, Maitron, Français libres,
  Arolsen, Bundesarchiv, Volksbund, USHMM, Musée de la Résistance) ; `archives_service(code="SHD"|"MDH"|"AN")`.
- `variantes_noms(nom, prenom)` : Müller/Mueller/Muller, Meyer/Maier, Schmidt/Schmitt, Jean/Johann/Hans.
- `liens_recherche`, `cotes_a_consulter` (série W et R), `communicabilite`, `journal_ajouter` (chaque recherche,
  y compris négative), `source_collee` (résultat consulté par l'utilisateur).
- Pièces : code `SGM` (`piece_nommer(type_piece="SGM fiche Arolsen", …)`), classées sous
  `documents/Seconde Guerre mondiale/<NOM>/` ; `piece_archiver` pour un original avec sa provenance.

## Parcours par profil

Pour chaque profil : **point de départ** → **fonds** → **pièce attendue**. Commencer toujours par l'état civil
(mentions marginales « mort pour la France », « mort en déportation ») et le registre matricule (série R, classe
= naissance + 20).

| Profil | Où chercher d'abord | Ensuite |
|---|---|---|
| Mobilisé 1939-1940 | registre matricule (AD, série R) | SHD Vincennes (archives des unités) ; carnet ou livret militaire de la famille |
| Prisonnier de guerre | registre matricule ; fichiers des PG au SHD-DAVCC (Caen) | Arolsen ; listes officielles de prisonniers publiées en 1940-1941 (presse, Gallica) ; CICR sur demande |
| Mort pour la France | mention en marge de l'acte de décès ; base « Morts pour la France » 39-45 (Mémoire des hommes) | dossier au SHD-DAVCC ; MemorialGenWeb (monument) |
| Déporté, interné | Livre-Mémorial FMD ; Mémorial de la Shoah ; Arolsen | dossier de statut au SHD-DAVCC (Caen) ; AD (série W : internements, camps) |
| Travailleur forcé (STO) | AD (série W : office de placement, recensements de classes) | dossier de statut « personne contrainte au travail » (SHD-DAVCC) ; Arolsen (travailleurs étrangers) |
| Résistant, FFI, FFL | index GR 16 P (Mémoire des hommes) puis dossier au SHD Vincennes | Français libres, Maitron (fusillés), Musée de la Résistance ; AD (comités de libération) |
| Mis en cause à l'épuration | AD, série W : cour de justice, chambre civique, comité de libération | AN (Haute Cour ; Z/6 : cour de justice de la Seine) ; presse (Gallica, Retronews) |
| Incorporé de force (Alsace-Moselle) | registre matricule ; AD 67, 68, 57 | Bundesarchiv (ex-WASt, dossiers de la Wehrmacht) ; Volksbund (sépultures) ; Arolsen |
| Soldat de la Wehrmacht, Waffen-SS ; NSDAP | Bundesarchiv (demande ; fichier central du NSDAP, R 9361) | Volksbund ; état civil allemand (Standesamt) |
| Victime civile (bombardement, exécution) | acte de décès et sa mention ; base « Morts pour la France » si la mention a été attribuée | presse locale ; Maitron (fusillés) |

## Restitution

Chaque fait : source (dépôt, cote, date de consultation), nature (originale, dérivée, index), statut de preuve.
Signaler les dossiers à **demander** (non numérisés) avec le service et le modèle de courrier
(`communicabilite(..., lieu=...)`). Proposer les ajouts à l'arbre par `arbre_proposer`, jamais directement.
