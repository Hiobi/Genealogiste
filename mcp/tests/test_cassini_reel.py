"""Recette sur le fichier Cassini RÉEL installé par l'utilisateur (#349, make test-cassini). Ignorée sans
GENEALOGISTE_TEST_CASSINI=1, et ignorée proprement si le fichier n'est pas installé.

Sans réseau : le fichier est lu là où l'utilisateur l'a installé (GENEALOGISTE_TEST_CASSINI_DIR, dossier des
référentiels), le COG et les services viennent des réponses enregistrées. Les assertions portent sur la **forme**
(niveaux, licence, attribution, périodes), jamais sur une valeur du jeu : aucune donnée Cassini n'est écrite ici."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from test_lieu_historique import routes  # noqa: F401  (fixture : réponses enregistrées de lieu_historique)

from genealogiste_mcp import server
from genealogiste_mcp.contexte import cassini

ACTIVE = os.environ.get("GENEALOGISTE_TEST_CASSINI") == "1"
DOSSIER = os.environ.get("GENEALOGISTE_TEST_CASSINI_DIR", "")
pytestmark = [pytest.mark.cassini_local,
              pytest.mark.skipif(not ACTIVE, reason="GENEALOGISTE_TEST_CASSINI=1 non défini (make test-cassini)")]


@pytest.fixture
def base_reelle(app):
    if not DOSSIER:
        pytest.skip("GENEALOGISTE_TEST_CASSINI_DIR non défini (make test-cassini le renseigne)")
    app.config.referentiels_dir_conf = Path(DOSSIER).expanduser()
    cassini._BASES.clear()
    etat = cassini.etat(app.config)
    if not etat["installee"]:
        pytest.skip(f"base Cassini non installée dans {DOSSIER} : {etat['motif']} (cassini_preparer puis "
                    "cassini_installer)")
    yield etat
    cassini._BASES.clear()


def test_fichier_reel_accepte_et_conforme(base_reelle):
    assert base_reelle["licence"] == "CC BY-NC-SA 4.0" and base_reelle["doi"] == cassini.DOI
    assert base_reelle["lieux"] > 40_000 and base_reelle["communes"] > 30_000
    assert len(base_reelle["empreinte_sha1"]) == 40 and base_reelle["accepte_le"]


def test_lieu_historique_lit_le_fichier_reel(app, base_reelle, routes):  # noqa: F811
    debut = time.perf_counter()
    res = server.lieu_historique("Billy-Montigny, Pas-de-Calais", "1906")
    duree = time.perf_counter() - debut
    assert res["requetes"]["cassini_local"] == "positif" and res["cassini"]["nombre_de_lieux"] >= 1
    nom = next(n for n in res["niveaux"] if n["niveau"] == "nom")
    pop = res["population"]
    for n in (nom, pop):
        assert n["statut"] == "indication" and n["source"]["licence"] == "CC BY-NC-SA 4.0"
        assert n["source"]["reference"] == f"doi:{cassini.DOI}" and "Bideau" in n["source"]["attribution"]
    assert 1 <= len(nom["valeur"]) <= 3 and all(x["nom"] and x["instantane"] for x in nom["valeur"])
    assert isinstance(pop["valeur"], int) and pop["annee"] <= 1906
    for niveau in ("canton", "arrondissement", "province", "diocese"):
        assert next(n for n in res["niveaux"] if n["niveau"] == niveau)["valeur"] == "inconnu"
    debut = time.perf_counter()
    assert cassini.consulter(app.config, "62133", "Billy-Montigny")["principal"] is not None
    print(f"\nlieu_historique : {duree:.2f} s ; consultation suivante du fichier : "
          f"{(time.perf_counter() - debut) * 1000:.1f} ms")
