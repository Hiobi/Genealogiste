---
description: Contexte historique sourcé d'une personne ou d'un lieu (éléments par échelle, avec source et rattachement) et pistes de recherche réfutables ; rien n'est affirmé de mémoire
argument-hint: <id ou nom | lieu> [--periode AAAA-AAAA] [--echelles commune,departement,…] [--themes mots]
---
Contexte historique : **$ARGUMENTS**

Applique la skill `methodologie-gps` (§ « Contexte historique »). Référence : `docs/contexte-historique.md`.

**Règle.** Rien n'est affirmé de mémoire : tout ce qui est affiché sort des outils, tel quel. Un élément sans
source n'est pas affiché. Le contexte oriente une recherche, il ne conclut pas. Aucune écriture dans l'arbre.

1. **Cible.**
   - Personne (identifiant, ou nom résolu par `arbre_recherche` ; plusieurs réponses : demander laquelle) :
     `arbre_vivant(id)` ; présumée vivante → refuser et s'arrêter. Lieux, période de vie et métier sont lus par
     l'outil dans ses seuls faits sourcés ; son nom ne part jamais.
   - Lieu : commune avec son département (« <commune>, <département> ») **et** `--periode` (`AAAA-AAAA`),
     obligatoire sans personne ; s'il manque, le demander, ne pas le deviner.
   - Options : `--periode` (restreint la période de vie d'une personne), `--echelles` parmi `commune`, `pays`,
     `departement`, `region`, `nation`, `international` (défaut : `commune,departement`), `--themes` (mots du
     sujet ; défaut : premier métier sourcé). Enquête ouverte sur le sujet : passer aussi `enquete=<id>` aux deux
     outils (budget, « déjà fait »).
2. **Collecte** : `contexte_local(personne=<id>, periode=…, echelles=…, themes=…)`, ou
   `contexte_local(lieu=…, periode=…, echelles=…, themes=…)`. Refus (personne vivante, budget) ou `erreur` : le
   rendre tel quel et s'arrêter.
3. **Éléments, par échelle** (`elements`, de la commune vers le plus large). Pour chacun, une ligne :
   - l'énoncé (`enonce`) **mot pour mot entre guillemets « »**, sans rien y ajouter ni le reformuler ;
   - la source : `source.citation` recopiée telle que l'outil la rend, identifiant compris (`source.identifiant`),
     jamais recomposée ; service d'origine (`origine`) ;
   - la portée (`portee` : lieu, échelle, années) et le niveau de rattachement (`rattachement.niveau` : attesté,
     compatible ou non démontré) avec sa `justification` ; pour « attesté », la citation de l'arbre
     (`rattachement.citation_arbre`) ;
   - au-delà de la commune, la `mention` de l'élément : « tendance générale, ne prouve rien pour l'individu ».

   Un extrait de presse garde sa marque « (lecture OCR non vérifiée) » ; une notice « non lu » le reste.
4. **Ce qui n'est pas documenté**, dit clairement :
   - `resultat` vaut « contexte non documenté » : l'écrire tel quel, avec « recherche_negative » ; aucun texte
     général sur la région ou l'époque à la place ;
   - `non_documente` : échelles demandées sans élément ;
   - `non_sources` : entrées d'index sans référence consultée, listées comme « non sourcé » avec leurs liens de
     consultation, jamais comme contexte ;
   - `nb_ecartes` et, si l'utilisateur le demande, `ecartes` avec le motif de chacun (hors période, hors lieu,
     source absente du registre).
5. **Services et tâches manuelles** : `services_en_echec` (service, erreur), `services_ecartes` (service,
   motif : désactivé, clé absente, lien seulement, pays non couvert), `taches_manuelles` (liens de consultation,
   ce qu'il faut relever ; reprise par `source_collee`, `piece_archiver` ou `media_enregistrer`). Un service bloqué
   ne se relance pas et ne se contourne pas.
6. **Pistes** : `pistes_contexte` avec les mêmes arguments. Pour chaque piste de `pistes` : `hypothese` telle
   quelle, ses fondements (`fondements.arbre` : faits avec leur statut de preuve et leurs citations ;
   `fondements.contexte` : élément et sa source), son test (`test.sources` : sources qui la confirmeraient ou la
   réfuteraient, avec leurs avertissements ; `test.motif` s'il n'y en a pas), son coût (`cout`) et son statut
   (`statut_libelle` : à tester, confirmée, réfutée, contexte seul). Une piste « contexte seul » est présentée
   comme telle : hypothèse non démontrée, sans source individuelle connue. Donner aussi `regles_non_appliquees`
   (règle et motif) et, s'il existe, `fenetre_depart.texte`. Aucune piste : rendre « recherche_negative », ne pas
   combler par une hypothèse libre.
7. **Suite, proposée à l'utilisateur, jamais faite d'office** :
   - verser une piste à tester dans une enquête : `enquete_noter(enquete=<id>, …)` avec les paramètres de
     `depot.enquete_noter` de la piste (`enquete_ouvrir` s'il n'y a pas d'enquête), après accord. Une piste
     « contexte seul » peut être notée pour mémoire avec son marqueur ; elle ne devient jamais une tâche ni une
     proposition (le serveur le refuse) ;
   - lire une référence avant de s'y appuyer (« non lu » : notice seule) ; approfondir par
     `contexte_bibliographie`, `presse_recherche` ou `lieu_historique` ;
   - si des niveaux de `lieu_historique` restent « inconnu » avant 1943 et que l'utilisateur le souhaite :
     `cassini_preparer` présente la base Cassini (licence CC BY-NC-SA 4.0, réserve, taille, destination) ;
     `cassini_installer(jeton)` seulement après son accord explicite sur cette licence. Une valeur tirée de cette
     base est une indication à confirmer, à citer avec sa licence et son attribution ;
   - rédiger : `/genealogiste:recit <id>` reprend ces éléments et les contrôle par `contexte_verifier`.
8. Rappeler en une ligne : éléments et pistes viennent des références consultées par le plugin ; rien n'a été
   écrit dans l'arbre ; les recherches, négatives comprises, sont au journal (`journal`).
