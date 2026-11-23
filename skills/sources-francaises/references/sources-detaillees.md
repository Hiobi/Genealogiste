# Sources françaises — fiches détaillées

## État civil (depuis 1792)
- Créé par le décret du 20 septembre 1792 ; tenu en double (mairie + greffe → AD).
- Acte de naissance : déclarant (souvent le père), témoins, date/heure ; mentions marginales (mariage depuis
  1897, divorce, décès depuis 1945, reconnaissance, légitimation).
- Acte de mariage : âges, professions, domiciles, parents (vivants/décédés), consentements, contrat de
  mariage (mentionné depuis 1850 : notaire et date), légitimation d'enfants.
- Acte de décès : informations sur le défunt souvent **secondaires** (âge, parents) — déclarants non témoins
  de la naissance.
- Calendrier républicain : de l'an II à l'an XIV (1er janvier 1806). Convertir avec `convertir_date`.

## Registres paroissiaux
- Ordonnance de Villers-Cotterêts (1539, baptêmes), Blois (1579), Saint-Germain-en-Laye (1667, double
  exemplaire). Latin fréquent ; formulaires stéréotypés (voir skill paléographie).
- Baptême ≠ naissance (souvent le jour même ou le lendemain) ; sépulture ≠ décès.
- Protestants : registres de pasteurs, actes du Désert, édit de tolérance (1787).

## Tables décennales
- Dérivées des registres ; utiles pour localiser, jamais suffisantes seules (erreurs de copie).

## Recensements
- Listes nominatives quinquennales depuis 1836 (lacunes : 1916, 1941 ; 1871 partiel). Âges arrondis,
  orthographes variables. Communicables après 75 ans.

## Registres matricules (série R)
- Recrutement par classe (année des 20 ans). Fiche : état civil, parents, domicile, signalement, degré
  d'instruction, parcours, blessures, adresses successives. Tables alphabétiques par classe et bureau.
- En ligne et cherchable par classe : `archives_registres(service, commune=<bureau ou vide>, annee=<classe>,
  type_acte="RM")` pour AD19, AD25, AD27, AD39, AD55, AD58, AD69, AD90, AD972.

## Émigration et immigration
- Départ de France : registre matricule de la classe (adresses successives), passeports et police (sous-série
  4 M dans plusieurs services, ex. AD de la Somme et d'Indre-et-Loire ; à vérifier dans l'inventaire du
  service), recensements avant et après le départ (absence constatée, qui ne prouve pas l'émigration),
  transcriptions sur les registres de la commune du dernier domicile, état civil consulaire (Nantes).
- Étrangers en France : police des étrangers (déclarations de résidence, cartes d'identité d'étranger : 4 M
  dans plusieurs services), décrets de naturalisation aux Archives nationales (inventaire 1883-1948
  partiellement indexé ; le numéro de dossier du décret mène au dossier).
- Pays d'arrivée : intitulés génériques seulement (listes de passagers, recensements, naturalisation,
  conscription) ; aucune cote ni nom de fonds étranger. Guides relevés : `sources_catalogue(theme="emigration")`
  (NARA, Ellis Island, Fichier Origine, PRDH).
- Fenêtre de départ : tirée des seuls faits de l'arbre (`arbre_lacunes(id)` → `fenetre_depart`).

## Notaires (3 E)
- Retrouver l'acte : répertoire de l'étude, tables de l'enregistrement (avant 1790 : contrôle des actes,
  série C). Contrats de mariage, inventaires après décès, partages, testaments, ventes, baux.

## Enregistrement (3 Q)
- Tables des successions et absences (TSA) : date du décès, héritiers, déclaration de mutation par décès
  (biens, liens de parenté). Délai de déclaration : 6 mois.
- Cherchable par bureau et période : `archives_registres(service, commune=<bureau>, annee, annee_fin,
  type_acte="SUCC")` pour AD25, AD27, AD37, AD58, AD69, AD90, AD91 ; ailleurs, inventaire de la série 3 Q.

## Cadastre (3 P) et hypothèques (4 Q)
- Plan, état de sections, matrice des propriétaires ; hypothèques : transcriptions de mutations.

## En ligne
- Archives départementales (état civil, BMS, matricules, recensements numérisés).
- Gallica (presse, annuaires, bulletins), Retronews, FranceArchives (inventaires), Mémoire des hommes,
  Grand Mémorial, matchID (décès ≥ 1970), Geneanet/FamilySearch/WikiTree (arbres = composites).

## Sites tiers (associations, relevés, bases thématiques)
- Cercles départementaux et réseaux de relevés bénévoles (GeneaBank, FranceGenWeb, GenNPdC…) : relevés BMS/NMD,
  contrats, notaires. **Source dérivée** : piste à confirmer sur l'acte original.
- Bases thématiques : protestants (Refuge huguenot), déportés (Livre-Mémorial FMD), FFL, Maitron, émigrants vers le
  Québec (Fichier Origine), prisonniers 14-18 (CICR) ; lieux : DicoTopo, Remonter le temps (IGN), Cassini (EHESS).
- `sources_catalogue(departement=…, theme=…)` liste ces sites ; `liens_recherche` et `cotes_a_consulter` proposent
  ceux du département. Référentiel : `docs/sites-tiers.md`.
- Seconde Guerre mondiale (prisonniers, déportés, STO, résistants, épuration, incorporés de force) : skill
  `seconde-guerre-mondiale` et `docs/seconde-guerre-mondiale.md`.
