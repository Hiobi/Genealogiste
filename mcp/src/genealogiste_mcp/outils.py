"""Catalogue des outils MCP : effet de chaque outil, classe de permission et décision du hook PreToolUse.

Source de vérité unique (#55, #153) : la décision du hook Claude découle de la classe (DECISIONS), et
hooks/hooks.json est généré depuis ce catalogue (scripts/generer_hooks.py). test_outils vérifie que chaque outil
enregistré est déclaré ici, que hooks.json est exactement le rendu du catalogue, et que tout outil réseau qui reçoit
un nom, un texte ou un identifiant de personne passe par la politique « vivants » (privacy.external_guard)."""

from __future__ import annotations

import json

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
    "ark_resoudre": (RESEAU, COLLECTE),  # requête HEAD, cache
    "archive_image": (RESEAU, COLLECTE),  # téléchargement dans le cache d'images
    "pdf_markdown": (LECTURE, LECTURE),  # fichier local ; écrit seulement dans le cache cache-pdf
    "piece_archiver": (RESEAU, COLLECTE),  # pièce nouvelle + note : suffixe « (n) », rien d'écrasé
    "wikidata_personne": (RESEAU, COLLECTE),
    "wikidata_sparql": (RESEAU, COLLECTE),
    "geo_commune": (RESEAU, COLLECTE),
    "geo_historique": (RESEAU, COLLECTE),
    "recherche_multi": (RESEAU, COLLECTE),
    "liens_recherche": (LECTURE, LECTURE),
    "cotes_a_consulter": (LECTURE, LECTURE),
    "archives_service": (LECTURE, LECTURE),  # référentiel embarqué
    "archives_naviguer": (RESEAU, COLLECTE),
    "archives_registres": (RESEAU, COLLECTE),
    "archives_planche": (RESEAU, COLLECTE),  # écrit une planche dans le cache d'images, comme archive_image
    "source_collee": (JOURNAL, LECTURE),
    "diagnostic": (RESEAU, COLLECTE),  # contrôles locaux + une requête GET par source, sans donnée de personne
    "familysearch_exporter": (IDENTIFIANTS, ECRITURE),
    # analyse
    "normaliser_nom": (LECTURE, LECTURE),
    "comparer_noms": (LECTURE, LECTURE),
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
    "arbre_importer_gedcom": (PROPOSITION, PROPOSITION),
    "arbre_appliquer": (ECRITURE, ECRITURE),
    "arbre_exporter": (ECRITURE, ECRITURE),  # chemin libre, fichier existant remplacé
    # file de propositions (#154) : locale, aucune écriture de l'arbre (arbre_appliquer reste l'écriture)
    "propositions_deposer": (PROPOSITION, PROPOSITION),
    "propositions_lister": (LECTURE, LECTURE),
    "propositions_reprendre": (PROPOSITION, PROPOSITION),
    "propositions_abandonner": (PROPOSITION, PROPOSITION),
    # fichiers
    "rapport_enregistrer": (ECRITURE, ECRITURE),
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
    "cache_purger": (ECRITURE, ECRITURE),  # suppression ; peut lever le coupe-circuit anti-robot
    # Gramps Web
    "gramps_recherche": (RESEAU, COLLECTE),
    "gramps_personne": (RESEAU, COLLECTE),
    "gramps_tirer": (ECRITURE, ECRITURE),
    "gramps_bascule_proposer": (PROPOSITION, PROPOSITION),
    "gramps_bascule_appliquer": (ECRITURE, ECRITURE),
    "gramps_recalculer_notes": (PROPOSITION, PROPOSITION),  # diff + jeton (propose_notes)
    "gramps_structurer_lieux": (PROPOSITION, PROPOSITION),  # diff + jeton (propose_places)
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


# Outils réseau qui envoient des noms, un texte libre ou un identifiant de personne : garde « vivants » obligatoire.
GARDE_VIVANTS = {"matchid_recherche", "matchid_appariement_csv", "wikitree_recherche", "gallica_recherche",
                 "gallica_recherche_document", "wikidata_personne", "wikidata_sparql", "recherche_multi",
                 "archives_registres"}

# Paramètres qui désignent une personne ; exemptions justifiées (outil réseau, paramètre sans rapport).
PARAMS_PERSONNE = {"nom", "prenom", "texte", "personne", "requete", "chemin_csv"}
EXEMPTIONS = {
    "geo_commune": "nom = nom de commune",
    "geo_historique": "nom = nom de commune",
    "gramps_recherche": "serveur Gramps Web de l'utilisateur (son propre arbre), pas un service tiers",
    "piece_archiver": "nom = nom de fichier local ; seule l'adresse de la vue part sur le réseau",
}
