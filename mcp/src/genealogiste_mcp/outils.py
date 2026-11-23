"""Catalogue des outils MCP : effet de chaque outil, classe de permission et décision du hook PreToolUse.

Source de vérité unique (#55, #153) : la décision du hook Claude découle de la classe (DECISIONS), et
hooks/hooks.json est généré depuis ce catalogue (scripts/generer_hooks.py). test_outils vérifie que chaque outil
enregistré est déclaré ici, que hooks.json est exactement le rendu du catalogue, et que tout outil réseau qui reçoit
un nom, un texte ou un identifiant de personne passe par la politique « vivants » (privacy.external_guard)."""

from __future__ import annotations

import json
import re

# Effets (ce que fait l'outil : verrou de lecture, gardes, tests d'enveloppe)
LECTURE = "lecture"  # local, sans écriture
RESEAU = "reseau"  # requête vers un service externe
JOURNAL = "journal"  # trace au journal de recherche
PROPOSITION = "proposition"  # diff ou plan ; persiste un jeton, peut écrire au journal
ECRITURE = "ecriture"  # arbre, fichiers, Gramps Web
IDENTIFIANTS = "identifiants"  # usage d'identifiants de l'utilisateur

# Classes de permission (#153), d'après l'effet maximal de l'outil :
# - lecture : aucune écriture hors du cache et du journal internes ;
# - collecte : réseau et/ou écriture additive et réversible dans un répertoire géré par le plugin (cache, journal,
#   pièce nouvelle archivée avec sa note) ; jamais d'écrasement ni de suppression, jamais l'arbre ni Gramps Web.
#   Bornée par les limites de débit par hôte, le coupe-circuit anti-robot, le plafond journalier par hôte
#   d'archives et, avec enquete=<id>, le budget de l'enquête (#157) ; fixer ou relever ce budget, ou rouvrir une
#   enquête bloquée, demande l'accord de l'utilisateur (CONDITIONS) ;
# - proposition : prépare une modification sans l'écrire (diff + jeton, file de propositions) ;
# - ecriture : arbre, Gramps Web, fichiers de l'utilisateur, suppression, envoi de ses fichiers, identifiants.
COLLECTE = "collecte"
CLASSES = (LECTURE, COLLECTE, PROPOSITION, ECRITURE)

# Décisions du hook Claude, déduites de la classe
ALLOW, ASK = "allow", "ask"
DECISIONS = {LECTURE: ALLOW, COLLECTE: ALLOW, PROPOSITION: ALLOW, ECRITURE: ASK}

OUTILS: dict[str, tuple[str, str]] = {  # nom -> (effet, classe)
    # sources externes
    "matchid_recherche": (RESEAU, COLLECTE),
    "matchid_appariement_csv": (RESEAU, ECRITURE),  # envoie un fichier de l'utilisateur ; jeton possible
    "matchid_appariement_statut": (RESEAU, ECRITURE),  # CONDITIONS : collecte sans « sortie »
    "wikitree_recherche": (RESEAU, COLLECTE),
    "wikitree_profil": (RESEAU, COLLECTE),
    "wikitree_personne": (RESEAU, COLLECTE),
    "wikitree_ascendants": (RESEAU, COLLECTE),
    "wikitree_descendants": (RESEAU, COLLECTE),
    "gallica_recherche": (RESEAU, COLLECTE),
    "gallica_recherche_document": (RESEAU, COLLECTE),
    "gallica_texte": (RESEAU, COLLECTE),
    "gallica_alto": (RESEAU, COLLECTE),
    "gallica_iiif": (LECTURE, LECTURE),  # construit des URL, sans requête
    "presse_recherche": (RESEAU, COLLECTE),  # Gallica (client existant) ; registre des références consultées
    "ark_resoudre": (RESEAU, COLLECTE),  # requête HEAD, cache
    "archive_image": (RESEAU, COLLECTE),  # téléchargement dans le cache d'images
    "pdf_markdown": (LECTURE, LECTURE),  # fichier local ; écrit seulement dans le cache cache-pdf
    "piece_archiver": (RESEAU, COLLECTE),  # pièce nouvelle + note : suffixe « (n) », rien d'écrasé
    "wikidata_personne": (RESEAU, COLLECTE),
    "wikidata_sparql": (RESEAU, COLLECTE),
    "geo_commune": (RESEAU, COLLECTE),
    "geo_historique": (RESEAU, COLLECTE),
    # géographie historique (#287) : COG, API Géo, Melodi, Géoplateforme, index Wikidata ; lieu et date seulement
    "lieu_historique": (RESEAU, COLLECTE),
    "recherche_multi": (RESEAU, COLLECTE),
    "contexte_bibliographie": (RESEAU, COLLECTE),  # littérature savante (#286) ; registre des références
    # contexte d'un individu (#289) : assemble géographie, index Wikidata, bibliographie, presse ; aucune écriture
    "contexte_local": (RESEAU, COLLECTE),
    # contrôle déterministe d'un texte de contexte (#324) : registre et arbre lus, aucune requête ni écriture
    "contexte_verifier": (LECTURE, LECTURE),
    # pistes réfutables (#290) : contexte_local + faits de l'arbre + chaînes de sources ; rien n'est écrit (le
    # dépôt dans l'enquête ou la file reste à l'appelant : enquete_noter, propositions_deposer)
    "pistes_contexte": (RESEAU, COLLECTE),
    "liens_recherche": (LECTURE, LECTURE),
    "cotes_a_consulter": (LECTURE, LECTURE),
    "sources_catalogue": (LECTURE, LECTURE),  # référentiels embarqués (archives, sites tiers, API)
    "archives_service": (LECTURE, LECTURE),  # référentiel embarqué
    "archives_naviguer": (RESEAU, COLLECTE),
    "archives_registres": (RESEAU, COLLECTE),
    "archives_planche": (RESEAU, COLLECTE),  # écrit une planche dans le cache d'images, comme archive_image
    # sondage guidé (#156) : sans réseau ; avec enquete, note lectures, historique et verdict dans l'état
    # d'enquête (registre négatif : entrée de journal), jamais le budget ni la réouverture
    "archives_sonder": (ECRITURE, COLLECTE),
    "source_collee": (JOURNAL, LECTURE),
    "diagnostic": (RESEAU, COLLECTE),  # contrôles locaux + une requête GET par source, sans donnée de personne
    "familysearch_exporter": (IDENTIFIANTS, ECRITURE),
    # analyse
    "normaliser_nom": (LECTURE, LECTURE),
    "comparer_noms": (LECTURE, LECTURE),
    "variantes_noms": (LECTURE, LECTURE),  # graphies françaises et allemandes, sans réseau (#131)
    "convertir_date": (LECTURE, LECTURE),
    "naissance_depuis_age": (LECTURE, LECTURE),
    "normaliser_lieu": (LECTURE, LECTURE),
    "comparer_profils": (LECTURE, LECTURE),
    "communicabilite": (LECTURE, LECTURE),
    "prochaine_source": (LECTURE, LECTURE),
    # arbre
    "arbre_info": (LECTURE, LECTURE),
    "arbre_recherche": (LECTURE, LECTURE),
    "arbre_personne": (LECTURE, LECTURE),
    "arbre_fiche": (LECTURE, LECTURE),
    "arbre_statut_preuve": (LECTURE, LECTURE),
    "arbre_coherence": (LECTURE, LECTURE),
    "arbre_comparer": (LECTURE, LECTURE),
    "arbre_ascendance": (LECTURE, LECTURE),
    "arbre_descendance": (LECTURE, LECTURE),
    "arbre_lacunes": (LECTURE, LECTURE),
    "arbre_cercle": (LECTURE, LECTURE),
    "arbre_vivant": (LECTURE, LECTURE),
    "arbre_historique": (LECTURE, LECTURE),
    "arbre_statut_transaction": (LECTURE, LECTURE),  # sans verrou : consultable pendant une écriture longue
    "arbre_rapport_preuve": (LECTURE, LECTURE),
    "arbre_proposer": (PROPOSITION, PROPOSITION),
    "arbre_annuler_proposition": (PROPOSITION, PROPOSITION),
    "arbre_annuler_modification": (PROPOSITION, PROPOSITION),
    "arbre_importer_gedcom": (PROPOSITION, PROPOSITION),  # GEDCOM, Gramps XML, .gpkg (médias en zone d'attente)
    "arbre_appliquer": (ECRITURE, ECRITURE),
    "arbre_exporter": (ECRITURE, ECRITURE),  # chemin libre, fichier existant remplacé
    # file de propositions (#154) : locale, aucune écriture de l'arbre (arbre_appliquer reste l'écriture)
    "propositions_deposer": (PROPOSITION, PROPOSITION),
    "propositions_lister": (LECTURE, LECTURE),
    "propositions_reprendre": (PROPOSITION, PROPOSITION),
    "propositions_abandonner": (PROPOSITION, PROPOSITION),
    # fichiers
    "rapport_enregistrer": (ECRITURE, ECRITURE),  # écrase, peut viser GENEALOGISTE_RAPPORTS_DIR, commit et push
    # rapport de campagne (#159) : fichier nouveau daté dans <données>/rapports/campagnes/, suffixe « -n » en cas
    # de collision, jamais d'écrasement ; ni commit, ni push, ni réseau
    "rapport_campagne_enregistrer": (ECRITURE, COLLECTE),
    "media_enregistrer": (ECRITURE, ECRITURE),  # copie un fichier quelconque (chemin libre) dans le vault
    "piece_nommer": (LECTURE, LECTURE),
    "pieces_inventaire": (LECTURE, LECTURE),
    "pieces_proposer": (PROPOSITION, PROPOSITION),
    "pieces_appliquer": (ECRITURE, ECRITURE),
    "journal_lister": (LECTURE, LECTURE),
    "journal_ajouter": (JOURNAL, LECTURE),
    # état d'enquête (#155) : <données>/enquetes/<id>.json, géré par le plugin, hors arbre ; ouverture sans
    # écrasement (id existant refusé), notes ajoutées à l'état et au journal
    "enquete_ouvrir": (ECRITURE, ECRITURE),  # état local ; CONDITIONS : collecte sans « budget »
    "enquete_noter": (ECRITURE, ECRITURE),  # état local ; CONDITIONS : collecte sans « budget » ni réouverture
    "enquete_etat": (LECTURE, LECTURE),
    "enquete_reprendre": (LECTURE, LECTURE),
    "notes_generer": (ECRITURE, ECRITURE),  # réécrit les sections générées, renomme, retire des fiches
    "notes_lire": (ECRITURE, ECRITURE),  # fiche absente : génération partielle (renommages, index)
    "notes_ajouter": (ECRITURE, ECRITURE),  # modifie le texte libre de l'utilisateur
    # migration des marqueurs sosa -> genealogiste (#182) : fichiers et objets + diff + jeton, puis écriture
    # (fiches de notes + commit, transaction Gramps Web journalisée et annulable)
    "marqueurs_migrer_proposer": (PROPOSITION, PROPOSITION),
    "marqueurs_migrer_appliquer": (ECRITURE, ECRITURE),
    "cache_purger": (ECRITURE, ECRITURE),  # suppression ; peut lever le coupe-circuit anti-robot
    # Gramps Web
    "gramps_recherche": (RESEAU, COLLECTE),
    "gramps_personne": (RESEAU, COLLECTE),
    "gramps_tirer": (ECRITURE, ECRITURE),
    "gramps_bascule_proposer": (PROPOSITION, PROPOSITION),
    "gramps_bascule_appliquer": (ECRITURE, ECRITURE),
    "gramps_recalculer_notes": (PROPOSITION, PROPOSITION),  # diff + jeton (propose_notes)
    "gramps_structurer_lieux": (PROPOSITION, PROPOSITION),  # diff + jeton (propose_places)
    "gramps_normaliser_types": (PROPOSITION, PROPOSITION),  # diff + jeton (propose_types, #273)
    # diff + jeton (propose_place_history, #277) ; lit aussi les fichiers publics du COG (réseau sans donnée de
    # personne, cache, journal) : la proposition l'emporte, rien n'est écrit sans arbre_appliquer
    "gramps_dater_lieux": (PROPOSITION, PROPOSITION),
    # diff + jeton (propose_protection, #264) : pose ou retrait du drapeau privé, écrit seulement par arbre_appliquer
    "gramps_proteger_vivants": (PROPOSITION, PROPOSITION),
    # groupes de noms (#276) : LECTURE SEULE. Lit l'arbre Gramps (comme arbre_*) et GET /api/name-groups/ ; aucun
    # jeton, rien d'écrit : l'écriture d'un groupe n'est ni journalisée par Gramps ni annulable (docs/gramps-web.md)
    "gramps_grouper_noms": (LECTURE, LECTURE),
    "gramps_reglages": (PROPOSITION, PROPOSITION),  # lecture ; fiche du chercheur et signets : diff + jeton (#282)
    "gramps_envoyer_medias": (ECRITURE, ECRITURE),  # CONDITIONS : collecte sans « appliquer »
    "gramps_relocaliser_medias": (PROPOSITION, PROPOSITION),  # proposition seulement : écrite par arbre_appliquer
    "gramps_synchroniser": (ECRITURE, COLLECTE),  # relecture forcée ; miroir Git : commit additif
}


# Outils en deux temps que le hook distingue d'après l'entrée JSON de l'appel : classe maximale (ecriture) dans
# OUTILS, classe réduite quand le motif (grep -E, sans apostrophe) est absent.
CONDITIONS: dict[str, tuple[str, str, str]] = {
    "matchid_appariement_statut": ('"sortie"[[:space:]]*:[[:space:]]*"[^"]', COLLECTE, "écrit un fichier (sortie)"),
    "gramps_envoyer_medias": ('"appliquer"[[:space:]]*:[[:space:]]*true', COLLECTE,
                              "envoie des fichiers à Gramps Web (appliquer)"),
    # Budget d'enquête (#157) : une boucle autonome ne relève pas seule la limite qui l'arrête.
    "enquete_ouvrir": ('"budget"[[:space:]]*:[[:space:]]*[{]', COLLECTE, "fixe un budget de collecte (budget)"),
    "enquete_noter": ('"budget"[[:space:]]*:[[:space:]]*[{]|"statut"[[:space:]]*:[[:space:]]*"ouverte"', COLLECTE,
                      "modifie le budget ou rouvre une enquête (budget, statut ouverte)"),
}


def decision(nom: str) -> str:
    """Décision du hook pour l'effet maximal de l'outil."""
    return DECISIONS[OUTILS[nom][1]]


def branche_ecriture(nom: str, arguments: dict) -> bool:
    """Vrai si l'appel relève de la classe « ecriture » : outil de cette classe, et pour un outil conditionnel,
    arguments (JSON, comme l'entrée que reçoit le hook) qui correspondent au motif de CONDITIONS. Sert au
    garde-fou côté serveur (GENEALOGISTE_ECRITURE=interdite, #159), qui tranche ainsi comme le hook."""
    if nom not in OUTILS or OUTILS[nom][1] != ECRITURE:
        return False
    if nom not in CONDITIONS:
        return True
    motif = CONDITIONS[nom][0].replace("[[:space:]]", r"\s")  # classe POSIX (grep -E) -> re
    return re.search(motif, json.dumps(arguments, ensure_ascii=False, default=str)) is not None


# ---------------------------------------------------------------- hooks/hooks.json (généré)

MOTIF = "mcp__.*genealogiste.*__({})$"  # plugin stdio et serveur HTTP Docker
RAISONS = {
    LECTURE: "sans écriture",
    COLLECTE: "réseau, cache, journal ou pièce nouvelle archivée, sans écriture dans l’arbre",
    PROPOSITION: "modification préparée sans écriture (diff et jeton à valider)",
    ECRITURE: "arbre, Gramps Web, fichiers de l’utilisateur, suppression ou identifiants : "
              "validation explicite requise (vérifiez le diff présenté)",
}


def _printf(decision_: str, raison: str) -> str:
    texte = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision_,
                                               "permissionDecisionReason": f"genealogiste : {raison}"}},
                       ensure_ascii=False)
    if "'" in texte:
        raise ValueError(f"apostrophe interdite dans la sortie du hook : {texte}")
    return f"printf '%s' '{texte}'"


def hooks_json() -> dict:
    """Rendu de hooks/hooks.json : un motif par classe, puis un motif par outil conditionnel."""
    entrees = []
    for classe in CLASSES:
        noms = sorted(n for n, (_, c) in OUTILS.items() if c == classe and n not in CONDITIONS)
        if noms:
            commande = _printf(DECISIONS[classe], f"{classe} : {RAISONS[classe]}")
            entrees.append({"matcher": MOTIF.format("|".join(noms)),
                            "hooks": [{"type": "command", "command": commande}]})
    for nom, (motif, reduite, libelle) in sorted(CONDITIONS.items()):
        if "'" in motif:
            raise ValueError(f"apostrophe interdite dans le motif de {nom}")
        maxi = _printf(decision(nom), f"{nom} {libelle} : validation explicite requise")
        sinon = _printf(DECISIONS[reduite], f"{nom} : {reduite}, {RAISONS[reduite]}")
        entrees.append({"matcher": MOTIF.format(nom), "hooks": [
            {"type": "command", "command": f"if grep -Eq '{motif}'; then {maxi}; else {sinon}; fi"}]})
    return {"description": "Généré depuis mcp/src/genealogiste_mcp/outils.py (make hooks) : lecture, collecte et "
                           "proposition sans approbation ; écriture (arbre, Gramps Web, fichiers de l'utilisateur), "
                           "suppression ou identifiants : accord explicite.",
            "hooks": {"PreToolUse": entrees}}


def hooks_texte() -> str:
    return json.dumps(hooks_json(), ensure_ascii=False, indent=2) + "\n"


PREFIXE_PLUGIN = "mcp__plugin_genealogiste_genealogiste__"  # plugin stdio ; serveur HTTP : mcp__genealogiste__


def profil_sans_surveillance(prefixe: str = PREFIXE_PLUGIN) -> dict:
    """Profil de permissions Claude Code minimal d'une campagne sans surveillance (#159, docs/campagne.md) :
    allow = lecture, collecte, proposition et outils conditionnels (leur branche écriture reste refusée par le
    serveur avec GENEALOGISTE_ECRITURE=interdite) ; deny = tout autre outil de classe « ecriture » ; dontAsk :
    tout ce qui demanderait un accord est refusé."""
    allow = sorted(prefixe + n for n, (_, c) in OUTILS.items() if c != ECRITURE or n in CONDITIONS)
    deny = sorted(prefixe + n for n, (_, c) in OUTILS.items() if c == ECRITURE and n not in CONDITIONS)
    return {"permissions": {"defaultMode": "dontAsk", "allow": ["Agent", *allow], "deny": deny}}


# Budget d'enquête (#157, #211) : tout outil réseau de classe collecte accepte enquete=<id> et ses requêtes émises
# comptent dans le budget de l'enquête (requêtes par hôte ; images lues). Exemptions motivées :
HORS_BUDGET = {
    "diagnostic": "contrôle de santé (une requête par source, sans donnée de personne), hors boucle d'enquête",
    "gramps_recherche": "serveur Gramps Web de l'utilisateur, client HTTP distinct (requêtes non mesurées)",
    "gramps_personne": "serveur Gramps Web de l'utilisateur, client HTTP distinct (requêtes non mesurées)",
}
BUDGET_ENQUETE = frozenset(n for n, (effet, classe) in OUTILS.items()
                           if effet == RESEAU and classe == COLLECTE and n not in HORS_BUDGET)

# Outils réseau qui envoient des noms, un texte libre ou un identifiant de personne : garde « vivants » obligatoire.
GARDE_VIVANTS = {"matchid_recherche", "matchid_appariement_csv", "wikitree_recherche", "gallica_recherche",
                 "gallica_recherche_document", "wikidata_personne", "wikidata_sparql", "recherche_multi",
                 "archives_registres", "contexte_bibliographie", "presse_recherche", "contexte_local",
                 "pistes_contexte"}

# Garde « vivants » avant le budget d'enquête (#211) : pour les outils gardés dont l'enveloppe générique
# (ServeurMCP.mesure) contrôle le budget avant d'exécuter l'outil, paramètres de l'appel passés à _garde, comme
# dans l'outil lui-même ({argument de _garde: paramètre de l'outil}). Un refus « vivant » est ainsi renvoyé avant
# tout contrôle de budget : rien consommé, rien consigné au reste à faire. La garde interne de l'outil reste en
# place. recherche_multi déclare lui-même enquete (garde, puis budget) ; matchid_appariement_csv est hors budget
# (pas d'enquete) et exclut les lignes vivantes du CSV au lieu de refuser. Correspondance vérifiée par
# test_garde_avant_budget (couverture et identité avec l'appel _garde de chaque outil).
GARDE_AVANT_BUDGET: dict[str, dict[str, str]] = {
    "matchid_recherche": {"personne": "personne", "nom": "nom", "prenom": "prenom", "ne_vers": "ne_vers",
                          "texte": "texte"},
    "wikitree_recherche": {"personne": "personne", "nom": "nom", "prenom": "prenom", "ne_vers": "ne_vers"},
    "gallica_recherche": {"personne": "personne", "texte": "texte"},
    "gallica_recherche_document": {"texte": "texte"},
    "wikidata_personne": {"personne": "personne", "nom": "nom", "prenom": "prenom", "ne_vers": "ne_vers"},
    "wikidata_sparql": {"texte": "requete"},
    "archives_registres": {"personne": "personne", "texte": "commune"},
    "presse_recherche": {"texte": "texte"},
    "contexte_bibliographie": {"personne": "personne", "texte": "sujet"},
    "contexte_local": {"personne": "personne", "texte": "themes"},
    "pistes_contexte": {"personne": "personne", "texte": "themes"},
}

# Paramètres qui désignent une personne ; exemptions justifiées (outil réseau, paramètre sans rapport).
PARAMS_PERSONNE = {"nom", "prenom", "texte", "personne", "requete", "chemin_csv"}
EXEMPTIONS = {
    "geo_commune": "nom = nom de commune",
    "geo_historique": "nom = nom de commune",
    "gramps_recherche": "serveur Gramps Web de l'utilisateur (son propre arbre), pas un service tiers",
    "piece_archiver": "nom = nom de fichier local ; seule l'adresse de la vue part sur le réseau",
}

# « Déjà fait le … » (#211) : identité d'une demande pour chaque outil budgété. Deux appels sont « la même
# demande » si leurs paramètres d'identité, normalisés, sont égaux (enquetes.cle_requete) : correspondance exacte
# et prudente ; tout paramètre qui change le résultat en fait partie (pagination comprise). Normalisations :
# texte = casse, accents et espaces ignorés (noms, lieux, dates libres) ; exact = espaces de bord seulement
# (identifiants, ARK, URL, clés WikiTree, codes, SPARQL) ; entier ; booleen. Le défaut est celui de la signature
# (vérifié par test_deja_fait_collecte) : un paramètre omis vaut son défaut. Les outils de enquetes.OUTILS_SUIVIS
# (recherche_multi, archives_naviguer, archive_image) ont une identité dédiée (registre, fenêtre, vues lues).
TEXTE, EXACT, ENTIER, BOOLEEN = "texte", "exact", "entier", "booleen"
_NOM = {"nom": (TEXTE, ""), "prenom": (TEXTE, ""), "ne_vers": (TEXTE, ""), "lieu": (TEXTE, "")}
IDENTITE_REQUETE: dict[str, dict[str, tuple[str, object]]] = {
    "matchid_recherche": {"nom": (TEXTE, ""), "prenom": (TEXTE, ""), "ne_vers": (TEXTE, ""),
                          "lieu_naissance": (TEXTE, ""), "decede_vers": (TEXTE, ""), "lieu_deces": (TEXTE, ""),
                          "sexe": (TEXTE, ""), "texte": (TEXTE, ""), "taille": (ENTIER, 20), "page": (ENTIER, 1)},
    "wikitree_recherche": {**_NOM, "decede_vers": (TEXTE, ""), "limite": (ENTIER, 20)},
    "wikitree_profil": {"cle": (EXACT, "")},
    "wikitree_personne": {"cle": (EXACT, "")},
    "wikitree_ascendants": {"cle": (EXACT, ""), "profondeur": (ENTIER, 3)},
    "wikitree_descendants": {"cle": (EXACT, ""), "profondeur": (ENTIER, 2)},
    "gallica_recherche": {"texte": (TEXTE, ""), "type_doc": (EXACT, ""), "titre": (TEXTE, ""), "debut": (EXACT, ""),
                          "fin": (EXACT, ""), "exact": (BOOLEEN, True), "nombre": (ENTIER, 20),
                          "depart": (ENTIER, 1)},
    "gallica_recherche_document": {"ark": (EXACT, ""), "texte": (TEXTE, "")},
    "presse_recherche": {"texte": (TEXTE, ""), "lieu": (TEXTE, ""), "periode": (TEXTE, ""), "services": (TEXTE, ""),
                         "nombre": (ENTIER, 10)},
    "gallica_texte": {"ark": (EXACT, ""), "page": (ENTIER, 0), "max_caracteres": (ENTIER, 20000)},
    "gallica_alto": {"ark": (EXACT, ""), "page": (ENTIER, 0)},
    "ark_resoudre": {"ark": (EXACT, ""), "verifier": (BOOLEEN, True), "titre": (EXACT, "")},
    "piece_archiver": {"source": (EXACT, ""), "page": (ENTIER, 0)},
    "wikidata_personne": {**_NOM, "limite": (ENTIER, 20)},
    "wikidata_sparql": {"requete": (EXACT, "")},
    "geo_commune": {"nom": (TEXTE, ""), "code_postal": (EXACT, ""), "code_insee": (EXACT, ""),
                    "departement": (EXACT, ""), "limite": (ENTIER, 10)},
    "geo_historique": {"nom": (TEXTE, ""), "code_insee": (EXACT, ""), "departement": (EXACT, "")},
    "lieu_historique": {"lieu": (TEXTE, ""), "date": (TEXTE, "")},
    "archives_registres": {"service": (EXACT, ""), "commune": (TEXTE, ""), "annee": (ENTIER, 0),
                           "type_acte": (EXACT, ""), "page": (ENTIER, 1), "annee_fin": (ENTIER, 0)},
    "contexte_bibliographie": {"sujet": (TEXTE, ""), "lieu": (TEXTE, ""), "periode": (EXACT, ""),
                               "echelle": (EXACT, "commune"), "services": (EXACT, None), "limite": (ENTIER, 10)},
    "contexte_local": {"lieu": (TEXTE, ""), "periode": (EXACT, ""), "echelles": (TEXTE, ""),
                       "themes": (TEXTE, "")},
    "pistes_contexte": {"lieu": (TEXTE, ""), "periode": (EXACT, ""), "echelles": (TEXTE, ""),
                        "themes": (TEXTE, "")},
    "archives_planche": {"source": (EXACT, ""), "de": (ENTIER, 0), "a": (ENTIER, 0), "pas": (ENTIER, 1),
                         "bandeau": (EXACT, ""), "largeur": (ENTIER, 1200), "gris": (BOOLEEN, True),
                         "miniatures": (BOOLEEN, False)},
}
# Paramètres hors identité (sans effet sur la demande envoyée ni sur ce qui est obtenu), motif à l'appui ; tout
# autre paramètre de la signature doit figurer dans IDENTITE_REQUETE (test_deja_fait_collecte).
HORS_IDENTITE: dict[str, str] = {
    "personne": "id local de l'arbre (garde des vivants, journal), jamais envoyé au service",
    "enquete": "enquête où noter la demande, sans effet sur le résultat",
}
HORS_IDENTITE_OUTIL: dict[str, dict[str, str]] = {
    "piece_archiver": {p: "nommage et note de la pièce : la vue archivée est la même (source, page)"
                       for p in ("personnes", "type_piece", "commune", "depot", "annees", "cote", "acte",
                                 "source_arbre", "nom", "nom_fichier")},
}
# Hors « déjà fait » : les outils sans paramètre enquete (HORS_BUDGET, classe écriture). En particulier
# matchid_appariement_statut renvoie l'état d'un traitement en cours, qui change d'un appel à l'autre : redemander
# le même job n'est pas refaire une demande.
