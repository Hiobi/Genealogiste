"""#124 : diff d'arbre_proposer confiné aux objets visés (notes hors cible résumées, lignes plafonnées)."""

import hashlib

from genealogiste_mcp import server
from genealogiste_mcp.tree.proposals import MAX_DIFF_LINE_CHARS, tree_diff

LONG = "x" * 2000

AVANT = f"""0 HEAD
1 GEDC
2 VERS 7.0
0 @I1@ INDI
1 NAME Jean /MARTIN/
1 SEX M
0 @I2@ INDI
1 NAME Marie /DURAND/
1 NOTE {LONG}
0 @N1@ SNOTE Ancienne note de preuve
0 @F1@ FAM
1 HUSB @I1@
0 @F2@ FAM
1 WIFE @I2@
0 TRLR"""

APRES = (AVANT.replace("1 SEX M", "1 SEX M\n1 DEAT\n2 DATE 1885")
         .replace("Ancienne note de preuve", "Nouvelle note de preuve " + LONG)
         .replace("1 WIFE @I2@", "1 WIFE @I2@\n1 CHIL @I9@"))


def test_contexte_confine_a_l_enregistrement():
    d = tree_diff(AVANT, APRES, cibles={"I1"})
    assert "@@ @I1@ INDI @@" in d and "+1 DEAT" in d and "+2 DATE 1885" in d
    # le contexte de difflib ne déborde plus sur l'enregistrement voisin (texte long d'une autre personne)
    assert "MARIE" not in d.upper() and LONG not in d


def test_notes_hors_cible_comptees_sans_contenu():
    d = tree_diff(AVANT, APRES, cibles={"I1"})
    assert "1 note(s) hors cible modifiée(s), contenu omis : @N1@" in d
    assert "preuve" not in d


def test_autre_enregistrement_hors_cible_sur_une_ligne():
    d = tree_diff(AVANT, APRES, cibles={"I1"})
    assert "@@ @F2@ FAM (hors cible, détail omis) : +1/-0 @@" in d and "CHIL" not in d
    # une ligne modifiée qui cite une cible rend l'enregistrement détaillé
    assert "+1 CHIL @I9@" in tree_diff(AVANT, APRES, cibles={"I9"})


def test_ligne_plafonnee():
    d = tree_diff(AVANT, APRES)  # sans cibles : tout est détaillé
    ligne = next(x for x in d.splitlines() if x.startswith("+0 @N1@ SNOTE"))
    total = len("+0 @N1@ SNOTE Nouvelle note de preuve " + LONG)
    assert ligne == ("+0 @N1@ SNOTE Nouvelle note de preuve " + LONG)[:MAX_DIFF_LINE_CHARS] \
        + f"… (+{total - MAX_DIFF_LINE_CHARS} car.)"
    assert all(len(x) <= MAX_DIFF_LINE_CHARS + 20 for x in d.splitlines())


def test_evenement_vise_par_uid():
    avant = "0 @I1@ INDI\n1 DEAT\n2 UID u-123\n0 @I2@ INDI\n1 SEX F\n0 TRLR"
    apres = avant.replace("2 UID u-123", "2 UID u-123\n2 SOUR @S1@")
    assert "+2 SOUR @S1@" in tree_diff(avant, apres, cibles={"u-123"})


def test_proposition_fichier_diff_concis_jeton_et_empreinte(app_famille):
    texte = app_famille.store.text()
    p = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I4",
                                "evenement": {"type": "DEAT", "date": "1880", "non_source": True,
                                              "motif": "tradition familiale"}}], "t", "j")
    assert "@@ @I4@ INDI @@" in p["diff"] and "+1 DEAT" in p["diff"]
    assert "@I3@" not in p["diff"] and "@I5@" not in p["diff"]  # voisins absents du diff
    rec = app_famille.backend.tokens.peek(p["jeton"])
    assert rec["empreinte_base"] == hashlib.sha256(texte.encode()).hexdigest()
    assert "1 DEAT\n2 DATE 1880" in rec["resultat"] and rec["resultat"] != texte
    assert server.arbre_appliquer(p["jeton"])["commite"]
