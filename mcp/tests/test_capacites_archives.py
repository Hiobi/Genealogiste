"""La recette d'une référence ne certifie ni les autres fonds ni toute la chaîne."""
from genealogiste_mcp import archives
from genealogiste_mcp.capacites_archives import couverture, tableau


def service():
    return {"code": "AD00", "resolution_image": {"type": "visualizer_api"},
            "recette": {"source": "https://archives.example/registre", "document": "naissance"}}


def test_reference_declaree_ne_vaut_pas_recette_reussie():
    c = couverture(service(), {})
    assert c["niveau"] == 3
    assert c["capacites"]["navigation"] == "implemente_non_eprouve"
    assert not c["chaine_complete"]


def test_succes_ne_valide_ni_autre_fonds_ni_archivage():
    recette = {"resultat": "ok", "dernier_essai": "2026-11-17"}
    c = couverture(service(), recette, "naissance")
    assert c["niveau"] == 3
    assert c["capacites"]["telechargement"] == "teste"
    assert c["capacites"]["archivage"] == "inconnu"
    assert c["mesures"]["inconnu"]["verdict"] == "oui"
    autre = couverture(service(), recette, "matricule")
    assert autre["niveau"] == 3
    assert not autre["recette_applicable"]
    assert autre["capacites"]["telechargement"] == "implemente_non_eprouve"


def test_blocage_recent_supplante_reussite_historique():
    c = couverture(service(), {"resultat": "protection", "derniere_reussite": "2026-11-15"})
    assert c["niveau"] != 5
    assert c["capacites"]["navigation"] == "bloque"


def test_mesures_locales_et_vps_restent_distinctes():
    mesures = {"local": {"verdict": "oui"}, "vps": {"verdict": "defi"}}
    c = couverture(service(), {"resultat": "ok", "mesures": mesures})
    assert c["mesures"] == mesures
    assert not c["chaine_complete"]


def test_service_sans_adaptateur_reste_inconnu():
    c = couverture({"code": "AD00"}, {})
    assert c["niveau"] == 0
    assert set(c["capacites"].values()) == {"inconnu"}


def test_api_et_tableau_partagent_verdict(monkeypatch):
    monkeypatch.setattr(archives, "recette", lambda code: {"resultat": "protection"})
    c = archives.service(code="AD59", document="matricule")["couverture_technique"]
    assert not c["recette_applicable"]
    assert c["niveau"] != 5
    rapport = tableau([service()], {"AD00": {"resultat": "protection"}})
    assert "0 recettes de référence qualifiées" in rapport
    assert "bloque" in rapport


def test_niveau_cinq_exige_preuve_datee_revision_et_environnement():
    mesure = {"verdict": "oui", "date_mesure": "2026-11-17T10:00:00Z", "revision": "a" * 40, "reference": service()["recette"]}
    recette = {"resultat": "ok", "mesures": {"vps": mesure}}
    assert couverture(service(), recette)["niveau"] == 5
    assert couverture(service(), recette, "matricule")["niveau"] == 3
    for champ in ("date_mesure", "revision"):
        incomplet = {k: v for k, v in mesure.items() if k != champ}
        assert couverture(service(), {"resultat": "ok", "mesures": {"vps": incomplet}})["niveau"] == 3
    assert couverture(service(), {"resultat": "ok", "mesures": {"inconnu": mesure}})["niveau"] == 3


def test_reference_modifiee_invalide_qualification():
    mesure = {"verdict": "oui", "date_mesure": "2026-11-17", "revision": "a" * 40,
              "reference": {"source": "https://archives.example/autre", "document": "naissance"}}
    c = couverture(service(), {"resultat": "ok", "mesures": {"vps": mesure}})
    assert c["niveau"] == 3
    assert c["capacites"]["navigation"] == "implemente_non_eprouve"


def test_resultat_autre_reference_ne_contamine_pas_reference_courante():
    recette = {"resultat": "ok", "mesures": {
        "local": {"reference": service()["recette"], "verdict": "echec", "date_mesure": "2026-11-17"},
        "vps": {"reference": {"source": "autre"}, "verdict": "oui", "date_mesure": "2026-11-18"}}}
    c = couverture(service(), recette)
    assert c["capacites"]["navigation"] == "echec_recette"
    assert c["niveau"] == 3


def test_matrice_par_type_conserve_la_portee():
    mesure = {"verdict": "oui", "date_mesure": "2026-11-17", "revision": "a" * 40,
              "reference": service()["recette"]}
    rapport = tableau([service()], {"AD00": {"resultat": "ok", "mesures": {"local": mesure}}},
                      ("naissance", "matricule"))
    assert "| AD00 | 5 | 3 |" in rapport
