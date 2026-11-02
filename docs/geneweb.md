# Publier dans GeneWeb 7

Validé avec **GeneWeb 7.0.0** (`ged2gwb`, `gwu`, `gwb2ged`) : import sans erreur, aller-retour testé
(fixture `mcp/tests/fixtures/geneweb7_gwb2ged.ged` produite par `gwb2ged` 7.0.0).

Circuit : l'arbre GEDCOM 7 du plugin reste la **source de vérité** ; GeneWeb sert à consulter et publier.
Chaque export reconstruit la base GeneWeb.

## 1. Exporter

```
/genealogiste:export geneweb
```
ou `arbre_exporter("geneweb", masquer_vivants=True, temoins_en_personnes=False)`.

| Élément du plugin | Dans GeneWeb |
|---|---|
| citation (dépôt, cote, titre, acte/folio/vue, consulté le, [vu ; classification]) | champ **source** de l'événement (texte complet : `ged2gwb` ignore `PAGE`) |
| statut de preuve, contradiction, acte non vu, prochaine source | **note de l'événement** |
| fiche de preuve (statut de chaque fait, prochaines sources) | **notes de la personne** |
| preuve de chaque filiation | **commentaire de la famille** |
| témoin lié à une fiche (`ASSO`) | **témoin de l'événement** (`wit:`), rôle Witness / GODP / Civil officer / Religious officer / Informant / Attending / Mentioned |
| parrain / marraine au niveau de l'individu | **relation parrain/marraine** (`RELA GODF/GODM`) |
| témoin seulement nommé dans l'acte | note de l'événement ; ou, avec `temoins_en_personnes=True`, une fiche minimale marquée « identité non établie » |
| dates républicaines / juliennes | calendriers natifs GeneWeb (`12/1/3F`) |
| versions concurrentes d'une naissance, d'un décès… | GeneWeb n'en garde qu'une : la mieux prouvée est exportée, les autres sont décrites dans sa note |
| personnes présumées vivantes | « Vivant », sans date (par défaut) |

Les extensions `_…` du plugin ne sont pas exportées.

## 2. Importer

```bash
ged2gwb arbre-geneweb.ged -o mabase -f        # -f : remplace la base existante
```

En conteneur (adapter le nom du conteneur et le chemin des bases) :

```bash
docker cp arbre-geneweb.ged geneweb:/tmp/
docker exec -w /chemin/des/bases geneweb ged2gwb /tmp/arbre-geneweb.ged -o mabase -f
```

Options utiles : `-rs_no_mention` (couples sans mariage connu non affichés « mariés »), `-udi x-y`
(seuils vivant/décédé pour les personnes sans décès, défaut 80-120 ans). Ne pas utiliser `-uin`.
`ged2gwb` signale les incohérences (ex. « born after the death of his/her mother ») : ce sont les mêmes
que `arbre_coherence`, à traiter dans le plugin.

## 3. Sens inverse (reprise d'une base GeneWeb)

```bash
gwb2ged mabase -o mabase.ged
```
puis `/genealogiste:import mabase.ged ajouter` : témoins (`ASSO … RELA witness`), parrains (`GODF/GODM`),
calendriers et notes sont repris ; les sources texte deviennent des enregistrements source. Ensuite
`/genealogiste:recoupe` sur les doublons. Une modification faite directement dans GeneWeb est écrasée au
prochain export : la faire dans le plugin.
