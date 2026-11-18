# Seconde Guerre mondiale (1939-1945)

Inventaire des fonds utiles pour retrouver un ancêtre pendant la guerre, de leurs conditions d'accès et de ce que
le plugin automatise (#131). Le parcours par profil est dans la skill `seconde-guerre-mondiale`.

## Ce que fait le plugin

| Besoin | Mise en œuvre |
|---|---|
| Fonds pertinents | `sources_catalogue(theme="ww2")` ; `archives_service(code="SHD"\|"MDH"\|"AN")` ; skill `seconde-guerre-mondiale` (parcours par profil) |
| Variantes françaises et allemandes | `variantes_noms(nom, prenom)` : tréma et transcription, ß/ss, ei/ai/ey/ay, dt/tt/t/d, -mann/-man, C/K ; prénoms germanisés. `comparer_noms` reconnaît ces variantes (« variante germanique ») |
| Recherche dans les bases | liens à ouvrir dans le navigateur ; aucune de ces bases n'est interrogée par le plugin (pas d'API publique documentée relevée, conditions d'usage à respecter) |
| Archives non numérisées | `communicabilite(document, …, lieu)` : délai et modèle de courrier ; demande à adresser au service |
| Transcription, extraction | lecture des images par le modèle (`archive_image`, pièce fournie par l'utilisateur), skill `paleographie` ; dates, lieux, unités et camps relevés dans la note de la pièce |
| Conservation et classement | `piece_archiver` (original + note de provenance) ; code de pièce `SGM`, dossier `documents/Seconde Guerre mondiale/<NOM>/` |
| Arbre | `arbre_proposer` puis `arbre_appliquer` après accord ; citations obligatoires (`EXIGER_SOURCE`) |
| Incertitude | statut de preuve (`arbre_statut_preuve`), homonymes (`comparer_profils`), contradictions ; hypothèses notées comme telles |

## Inventaire des fonds

Accès relevé le 2026-11-18 (HTTP, sans contournement) ; à revérifier avant usage. « Navigateur » : consultation
par l'utilisateur, le plugin fournit le lien et trace la recherche.

| Fonds | Contenu utile | Accès | Automatisation |
|---|---|---|---|
| Service historique de la Défense (SHD), Vincennes | archives des unités ; dossiers de résistants (GR 16 P) ; officiers | salle de lecture, demande écrite | aucune (site injoignable depuis un client automatisé au relevé) |
| SHD, DAVCC (Caen) | dossiers de statut : déportés, internés, personnes contraintes au travail ; fichiers des prisonniers de guerre ; morts pour la France | demande écrite | aucune |
| Mémoire des hommes | Morts pour la France 39-45 ; index des dossiers de résistants (GR 16 P) | libre, navigateur | lien (`liens_recherche`) |
| Archives nationales | Haute Cour de justice ; cour de justice de la Seine (Z/6) ; fonds des administrations de Vichy | salle de lecture, inventaires en ligne (salle des inventaires virtuelle) | lien |
| Archives départementales | série W : cours de justice, chambres civiques, comités de libération, internements, STO ; série R : registres matricules | selon le service (`archives_service`) | registres numérisés selon le service ; série W en salle |
| Arolsen Archives | camps, persécutés, travailleurs forcés, personnes déplacées (ex-ITS) | libre, navigateur ; demande de recherche gratuite | lien ; aucune API publique documentée relevée |
| Bundesarchiv (invenio) | fonds allemands ; fichier central du NSDAP (R 9361) ; dossiers de la Wehrmacht (ex-WASt) sur demande | inventaires en ligne ; dossiers sur demande | lien |
| Volksbund | sépultures de soldats allemands, dont incorporés de force | libre, navigateur | lien |
| USHMM | survivants et victimes de la Shoah (HSV), documents | libre, navigateur (anglais) | lien |
| Mémorial de la Shoah | victimes, listes de convois, documents | navigateur | lien |
| Fondation pour la mémoire de la déportation | Livre-Mémorial des déportés partis de France | libre, navigateur | lien |
| Maitron, Français libres, Musée de la Résistance en ligne | notices biographiques (fusillés, FFL), documents | libre, navigateur | lien |
| Gallica, Retronews | presse (procès, listes de prisonniers publiées), Journal officiel | libre / abonnement | Gallica interrogé (`gallica_recherche`) |

## Droit et précautions

- **Délais** (Code du patrimoine, art. L213-2) : dossiers judiciaires 75 ans (100 ans si un mineur est concerné),
  documents portant atteinte à la vie privée 50 ans, secret médical 120 ans après la naissance ou 25 ans après le
  décès. L'arrêté du 24 décembre 2015 a ouvert par dérogation générale une partie des archives publiques de la
  période (police, justice) : périmètre et exclusions à vérifier auprès du service.
- **Qualification** : jamais de qualification automatique (collaborateur, résistant, déporté). Accusation,
  enquête, jugement, condamnation, amnistie : faits distincts, chacun cité. Un statut administratif (déporté
  résistant, personne contrainte au travail, mort pour la France) est une décision datée, souvent d'après-guerre.
- **Personnes vivantes et tiers** : une personne née après 1920 peut être vivante ; garde « vivants » avant toute
  recherche externe. Les dossiers d'épuration et de spoliation nomment des tiers : ne pas publier sans réflexion.
- **Conditions d'usage** des bases étrangères : consultation personnelle ; pas d'extraction en masse.

## Limites connues

- Aucune base de cette liste n'est interrogée automatiquement : les liens et la méthode sont fournis, la recherche
  reste manuelle. Une intégration par API supposerait une API publique documentée et des conditions d'usage
  compatibles (à relever au cas par cas, comme dans #119).
- Les variantes de noms sont des pistes : elles élargissent la recherche, elles ne prouvent aucune identité.
- L'accès des sites est daté : `make verifier-archives` le relève, `verifie_le` reste réservé au contrôle humain.
