"""Parcours de recette borné : un registre candidat, une vue, aucun acte identifié."""
from pathlib import Path

from genealogiste_mcp import server
from genealogiste_mcp.gedcom.mapping import write_gedcom


def parcourir(app, commune, annee, personne=""):
    avant = write_gedcom(app.tree())
    rapport = {"acte_identifie": False, "etapes": {}}

    def appel(etape, outil, *args, **kwargs):
        resultat = outil(*args, **kwargs)
        rapport["etapes"][etape] = resultat
        return resultat

    recherche = appel("recherche", server.archives_registres, "AD59", commune, annee,
                      type_acte="NMD", personne=personne)
    if "erreur" in recherche or not recherche.get("resultats"):
        return rapport
    # Refuser les choix ambigus ; le contrat ne sait pas identifier un acte.
    assert len(recherche["resultats"]) == 1, "Plusieurs registres candidats : sélection manuelle requise."
    registre = recherche["resultats"][0]
    navigation = appel("navigation", server.archives_naviguer, registre["ark"], page=1, pas=1)
    if "erreur" in navigation:
        return rapport
    assert len(navigation["vues"]) == 1
    vue = navigation["vues"][0]
    assert vue["vue"] == 1 and vue["ark_vue"].startswith(registre["ark"] + "/")
    archive = appel("archivage", server.piece_archiver, vue["ark_vue"], type_piece="NMD")
    if "erreur" in archive:
        return rapport
    fichier = Path(archive["chemin_absolu"])
    assert fichier.is_relative_to(app.config.pieces_root)
    assert fichier.is_file() and fichier.stat().st_size > 0
    note = fichier.with_suffix(".md").read_text(encoding="utf-8")
    for champ in (vue["ark_vue"], "sha256:", "consulte_le:", "url_image:"):
        assert champ in note, champ
    assert archive["cote"] == registre["cote"]
    assert archive["citation_suggeree"]["page"].startswith("vue 1/")
    repetition = appel("repetition", server.piece_archiver, vue["ark_vue"], type_piece="NMD")
    assert repetition["deja_archivee"] and repetition["chemin_absolu"] == str(fichier)
    assert write_gedcom(app.tree()) == avant
    rapport["vue_candidate_archivee"] = True
    return rapport
