# Recherche de registres AD59

Le module `sources/registres.py` lit une page HTML de recherche AD59, sans lancer le JavaScript ni
interroger une notice, le visualizer ou une image. Il recherche des **registres candidats** : leur présence
ne prouve pas qu'ils contiennent l'acte recherché. Un résultat négatif pour une commune, une année et un
filtre ne prouve pas l'absence générale de fonds numérisés.

## Contrat qualifié

Le [relevé public du 16 novembre 2026](https://archivesdepartementales.lenord.fr/search/results?formUuid=dc4e871d-0b62-41fb-9921-5ded573781b8&sort=date_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=SAINT-VAAST-EN-CAMBRESIS&2-date=1860)
a confirmé un résultat : cote `5 Mi 018 R 024`, ARK de registre `ark:/33518/jq9hpbzxnc72`, période
1831–1864, 954 médias. Le nom de commune et l'année figurent dans les paramètres GET observés :
`0-controlledAccessGeographicName[]` et `2-date`. Le formulaire porte l'identifiant
`dc4e871d-0b62-41fb-9921-5ded573781b8`. Le module conserve les paramètres observés `mode=list`,
`sort=date_asc`, `facet_media=image`.

Seul `AD59` est qualifié. La commune est mise en capitales et sans accents, sans déduire une autre
commune ; les traits d'union fournis sont conservés. L'année doit être un entier précis de 1 à 9999.
Les cases de filtre du formulaire GET portent `name=facet_typology` et les valeurs `Naissances`,
`Mariages`, `Décès` : ce sont les filtres utilisés pour `N`, `M`, `D`. `NMD` et le type vide conservent la
recherche sans filtre de typologie. Aucun filtre tables décennales n'a été qualifié : `TD` est refusé.
Aucun nom ni identifiant de personne n'est envoyé ; `personne` sert uniquement à la garde de l'outil
et au journal local.

La réponse contient le titre, la cote, l'ARK de registre, son URL, les bornes d'années si le champ de date
les expose, et le nombre de vues s'il est affiché. Une information facultative absente reste `None`.
Les bornes ne sont déduites ni de l'année demandée ni du titre. Le lien ARK de vue sur la miniature
est distinct du lien de notice : il ne sert pas d'identifiant au registre retourné.

## Forme HTML observée

- `body#display-results`, `section#list-container`, puis `li.element-list` pour chaque registre.
- `div.intitup > a[href]` contient le lien de notice et `h2` son titre. Le lien doit désigner un ARK de
  registre AD59 sur l'origine officielle, sans identifiants d'authentification ni qualificatif de vue.
- `p.referenceCodes` contient la cote.
- La partie `div.content-sub-part` dont `h3` vaut `Date` expose la période dans `p`.
- `p.info-list-picture` expose le nombre de médias ; la réponse relevée annonçait 954.
- `span.result` expose le nombre total de résultats.
- `input#current-page[name=page]` expose la page courante et `max` la dernière page. Le champ appartient
  au formulaire GET : l'appel utilise `page=N` explicitement et ne suit aucune page automatiquement.
- `li.select-results-per-page > p.placeholder[title]` annonçait une taille de 20 résultats par page.
  Cette valeur est **lue dans la réponse**, sans constante supposée. Si ce champ est présent, taille,
  compteur, nombre de blocs et dernière page doivent correspondre. Sans ce champ, les contrôles
  minimaux refusent notamment une page unique non exhaustive et les pages fantômes.

La recherche [année 1200 sur la même commune](https://archivesdepartementales.lenord.fr/search/results?formUuid=dc4e871d-0b62-41fb-9921-5ded573781b8&sort=date_asc&mode=list&facet_media=image&0-controlledAccessGeographicName%5B%5D=SAINT-VAAST-EN-CAMBRESIS&2-date=1200)
a confirmé la forme négative : `body#display-no-results`, puis `div.no-result` dans le conteneur de
liste, avec un message explicite. Le compteur et la pagination sont absents. L'absence de blocs de
résultats seule n'autorise donc pas à conclure à zéro résultat. Un négatif sur une page supérieure à 1
reste non qualifié et renvoie une erreur, plutôt qu'une absence globale de registre.

La reconnaissance n'a observé qu'une page positive. Les scénarios à plusieurs pages sont testés sur
fixtures synthétiques à partir des mêmes attributs observés ; aucun relevé réel de page 2 n'est revendiqué.

## HTTP, protection et journal

Un appel effectue au plus une tentative GET de recherche, ou utilise son cache. Il n'enchaîne pas les
pages, les registres ou les métadonnées ; la politique commune continue de revalider les redirections.
Une copie du wrapper HTTP partage le client, le cache, la politique et l'état de limitation de débit,
avec une limite locale d'une tentative. Elle ne modifie pas les reprises des autres sources. Chaque
invocation produit une entrée de journal : positive, négative, erreur ou blocage anti-robot, y compris
lorsque la réponse vient du cache.

[robots.txt](https://archivesdepartementales.lenord.fr/robots.txt) a autorisé `/search/results` lors du
relevé ; ses exclusions étaient `/private/`, `/oai-pmh`, `/user/`. Les réponses positives et négatives
étaient des pages serveur complètes sans défi bloquant. Le portail inclut pourtant un attribut de
configuration hCaptcha et un script passif Cloudflare : ces mentions seules ne caractérisent pas un
blocage. Un véritable défi arrête la requête et conserve la tâche manuelle de l'enveloppe commune,
sans autre client ni contournement.

Les changements de structure ou métadonnées incohérentes produisent une erreur journalisée. Le
parseur borne la profondeur HTML et refuse un document de plus de deux millions de caractères pour
éviter une récursion incontrôlée ou une analyse disproportionnée.

## Tests et recette volontaire

`tests/fixtures/ad59-recherche-positive.html` et `ad59-recherche-negative.html` conservent les balises
observées, avec une commune, une cote, un ARK, un UUID et une période synthétiques. Aucun export familial,
HTML complet de production, cookie ou script tiers n'est livré comme fixture.

```bash
uv --directory mcp run --locked --offline pytest tests/test_registres.py
GENEALOGISTE_TEST_REGISTRES=1 uv --directory mcp run --locked --offline pytest tests/test_registres_live.py -rs
```

La recette réelle est ignorée par défaut, y compris en CI. Elle contrôle `robots.txt`, puis effectue
exactement trois appels d'outil : NMD pour 1860, filtre N pour 1860, et résultat négatif pour 1200, sur
Saint-Vaast-en-Cambrésis. Elle s'arrête à la première protection, sans télécharger d'image. La recette
exécutée le 16 novembre 2026 a passé ces trois cas par le véritable outil MCP Python (`1 passed`, 4,90 s),
avec l'ARK et la cote ci-dessus, sans défi bloquant. Le fichier JSON de preuve reste dans le dossier
temporaire de pytest, hors du dépôt.
