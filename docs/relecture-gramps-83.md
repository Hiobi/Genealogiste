# Décision sur les deux commits de `feat/genealogiste` (#83)

Base examinée : `169e9f87ee72a0623f5118ad2a466095b6202174` (version 0.14.2).
Les deux commits anciens ne sont pas fusionnés : leurs apports sont repris de façon ciblée.

## `81a77cfa4406fc15f8fd6c9ff47de8e192ba8691` — README Gramps

**Décision : reprise adaptée.** Le README reçoit une présentation courte des deux backends,
de la mise en route et des outils Gramps. Les détails restent dans `docs/gramps-web.md`, déjà présent
sur main. La commande `journal` mentionne les transactions Gramps.

La section ancienne n'est pas recopiée intégralement : le README actuel contient les règles
MCP_TOKEN, Docker et Portainer corrigées depuis sa rédaction ; elles restent en place. Les garanties
et limites des correspondances de données restent celles du guide actuel, sans promesse générale
de conservation de tout champ non modélisé.

## `8ed23c9ce4a4bbad3c977944f7663dde3dc95547` — client, miroir, tests

| Apport ancien | Décision |
|---|---|
| Relecture à la seconde la plus récente | Repris par classe, comparaison du contenu et bilan réel, y compris lors d'une relecture complète au-delà du seuil. |
| Reprises des GET | Repris : trois essais sur erreur réseau ou 502/503/504, attentes 2 puis 4 secondes. |
| Renouvellement après 401 | Repris pour les GET, au plus une fois ; erreur réseau après renouvellement traitée comme les autres erreurs de lecture. |
| Non-rejeu des écritures | Renforcé : aucun rejeu POST/PUT/DELETE, même sur 401 ; le jeton sera renouvelé avant un nouvel appel explicite. |
| Bilan du miroir | Repris en supprimant la relecture imbriquée : le miroir utilise le snapshot courant et conserve `last_refresh`. |
| Image Gramps de test épinglée | Déjà intégré dans main avec la même empreinte ; aucune modification nécessaire. |
| Garde-fou fichiers privés suivis | Déjà couvert par le contrôle de distribution et la CI sécurité actuels ; ancien test redondant non ajouté. |
| Tests jeton/reprise/écritures | Repris avec des cas paramétrés, limites de reprise et erreurs permanentes. |
| Test réel recalcul `Sosa:auto` et miroir | Repris, avec vérification du bilan des modifications externes. |

Le client conserve notamment le paramètre `headers` et l'envoi des médias avec `If-Match`, ajoutés
sur main depuis l'ancien commit. Les métadonnées de session des anciens commits ne sont pas recopiées
dans les nouveaux messages de commit.

## Validation

- Régressions déterministes sur faux Gramps : modification au même horodatage, base d'entrée inchangée,
  bilan vide sans changement, relecture complète, réseau/5xx, 401, jeton expiré et écritures non rejouées.
- Test du miroir avec TTL zéro : bilan conservé dans l'état et dans le message Git.
- `make test-gramps` : **7 tests réussis** sur Gramps Web jetable, image déjà épinglée, données synthétiques ;
  conteneur et volumes de test supprimés après exécution.
- Suite Python complète, Ruff, contrôle de distribution et contrôles CI requis avant intégration.

Une fois cette reprise fusionnée et validée, aucun apport non décidé ne reste sur l'ancienne branche ;
sa référence peut être supprimée. Les contenus examinés restent identifiables par leurs SHA ci-dessus.
