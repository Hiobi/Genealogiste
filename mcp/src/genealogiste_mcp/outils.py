"""Catalogue des outils MCP : effet de chaque outil et décision du hook PreToolUse (hooks/hooks.json).

Source de vérité unique : test_outils vérifie que chaque outil enregistré est déclaré ici, que hooks.json
applique exactement ces décisions, et que tout outil réseau qui reçoit un nom, un texte ou un identifiant de
personne passe par la politique « vivants » (privacy.external_guard)."""

from __future__ import annotations

# Effets
LECTURE = "lecture"  # local, sans écriture
RESEAU = "reseau"  # requête vers un service externe
JOURNAL = "journal"  # trace au journal de recherche
PROPOSITION = "proposition"  # diff ou plan ; persiste un jeton, peut écrire au journal
ECRITURE = "ecriture"  # arbre, fichiers, Gramps Web
IDENTIFIANTS = "identifiants"  # usage d'identifiants de l'utilisateur

# Décisions du hook
ALLOW, ASK, CONDITIONNEL, DEFAUT = "allow", "ask", "conditionnel", "defaut"

OUTILS: dict[str, tuple[str, str]] = {
    # sources externes
    "matchid_recherche": (RESEAU, ALLOW),
    "matchid_appariement_csv": (RESEAU, ASK),
    "matchid_appariement_statut": (RESEAU, CONDITIONNEL),  # ask seulement si « sortie » écrit un fichier
    "wikitree_recherche": (RESEAU, ALLOW),
    "wikitree_profil": (RESEAU, ALLOW),
    "wikitree_personne": (RESEAU, ALLOW),
    "wikitree_ascendants": (RESEAU, ALLOW),
    "wikitree_descendants": (RESEAU, ALLOW),
    "gallica_recherche": (RESEAU, ALLOW),
    "gallica_recherche_document": (RESEAU, ALLOW),
    "gallica_texte": (RESEAU, ALLOW),
    "gallica_alto": (RESEAU, ALLOW),
    "gallica_iiif": (LECTURE, ALLOW),
    "ark_resoudre": (RESEAU, DEFAUT),
    "archive_image": (RESEAU, DEFAUT),
    "piece_archiver": (RESEAU, DEFAUT),  # écrit l'image et sa note dans le répertoire des médias
    "wikidata_personne": (RESEAU, ALLOW),
    "wikidata_sparql": (RESEAU, ALLOW),
    "geo_commune": (RESEAU, ALLOW),
    "geo_historique": (RESEAU, ALLOW),
    "recherche_multi": (RESEAU, ALLOW),
    "liens_recherche": (LECTURE, ALLOW),
    "cotes_a_consulter": (LECTURE, ALLOW),
    "archives_service": (LECTURE, DEFAUT),
    "source_collee": (JOURNAL, ALLOW),
    "familysearch_exporter": (IDENTIFIANTS, ASK),
    # analyse
    "normaliser_nom": (LECTURE, ALLOW),
    "comparer_noms": (LECTURE, ALLOW),
    "convertir_date": (LECTURE, ALLOW),
    "naissance_depuis_age": (LECTURE, ALLOW),
    "normaliser_lieu": (LECTURE, ALLOW),
    "comparer_profils": (LECTURE, ALLOW),
    "communicabilite": (LECTURE, ALLOW),
    "prochaine_source": (LECTURE, ALLOW),
    # arbre
    "arbre_info": (LECTURE, ALLOW),
    "arbre_recherche": (LECTURE, ALLOW),
    "arbre_personne": (LECTURE, ALLOW),
    "arbre_fiche": (LECTURE, ALLOW),
    "arbre_statut_preuve": (LECTURE, ALLOW),
    "arbre_coherence": (LECTURE, ALLOW),
    "arbre_comparer": (LECTURE, ALLOW),
    "arbre_ascendance": (LECTURE, ALLOW),
    "arbre_descendance": (LECTURE, ALLOW),
    "arbre_lacunes": (LECTURE, ALLOW),
    "arbre_cercle": (LECTURE, ALLOW),
    "arbre_vivant": (LECTURE, ALLOW),
    "arbre_historique": (LECTURE, ALLOW),
    "arbre_rapport_preuve": (LECTURE, ALLOW),
    "arbre_proposer": (PROPOSITION, ALLOW),
    "arbre_annuler_proposition": (PROPOSITION, ALLOW),
    "arbre_annuler_modification": (PROPOSITION, ALLOW),
    "arbre_importer_gedcom": (PROPOSITION, ALLOW),
    "arbre_appliquer": (ECRITURE, ASK),
    "arbre_exporter": (ECRITURE, DEFAUT),
    # fichiers
    "rapport_enregistrer": (ECRITURE, ASK),
    "media_enregistrer": (ECRITURE, DEFAUT),
    "piece_nommer": (LECTURE, ALLOW),
    "pieces_inventaire": (LECTURE, ALLOW),
    "pieces_proposer": (PROPOSITION, ALLOW),
    "pieces_appliquer": (ECRITURE, ASK),
    "journal_lister": (LECTURE, ALLOW),
    "journal_ajouter": (JOURNAL, ALLOW),
    "notes_generer": (ECRITURE, DEFAUT),
    "notes_lire": (ECRITURE, DEFAUT),
    "notes_ajouter": (ECRITURE, DEFAUT),
    "cache_purger": (ECRITURE, DEFAUT),
    # Gramps Web
    "gramps_recherche": (RESEAU, ALLOW),
    "gramps_personne": (RESEAU, ALLOW),
    "gramps_tirer": (ECRITURE, ASK),
    "gramps_bascule_proposer": (PROPOSITION, ALLOW),
    "gramps_bascule_appliquer": (ECRITURE, ASK),
    "gramps_recalculer_notes": (ECRITURE, ALLOW),
    "gramps_structurer_lieux": (ECRITURE, DEFAUT),
    "gramps_envoyer_medias": (ECRITURE, DEFAUT),
    "gramps_synchroniser": (ECRITURE, ALLOW),
}

# Outils réseau qui envoient des noms, un texte libre ou un identifiant de personne : garde « vivants » obligatoire.
GARDE_VIVANTS = {"matchid_recherche", "matchid_appariement_csv", "wikitree_recherche", "gallica_recherche",
                 "gallica_recherche_document", "wikidata_personne", "wikidata_sparql", "recherche_multi"}

# Paramètres qui désignent une personne ; exemptions justifiées (outil réseau, paramètre sans rapport).
PARAMS_PERSONNE = {"nom", "prenom", "texte", "personne", "requete", "chemin_csv"}
EXEMPTIONS = {
    "geo_commune": "nom = nom de commune",
    "geo_historique": "nom = nom de commune",
    "gramps_recherche": "serveur Gramps Web de l'utilisateur (son propre arbre), pas un service tiers",
    "piece_archiver": "nom = nom de fichier local ; seule l'adresse de la vue part sur le réseau",
}
