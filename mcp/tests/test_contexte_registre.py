"""Registre des références consultées (#321) : seule définition de « référence résolue » du jalon M7."""

from __future__ import annotations

import json

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.contexte.modeles import Identifiant, Reference, ReferenceInvalide
from genealogiste_mcp.contexte.registre import NonConsultee, RegistreReferences


def _ref(**kw) -> Reference:
    d = {"identifiant": {"type": "hal", "valeur": "hal-01234567"}, "titre": "Les houillères du Nord",
         "auteurs": ["Martin, Paul"], "annee": 1998, "nature": "secondaire_savante", "type_document": "these",
         "publication": "Université de Lille", "service": "hal",
         "requete": "https://api.archives-ouvertes.fr/search/?q=houill%C3%A8res+Nord", "consulte_le": "2026-11-23"}
    d.update(kw)
    return Reference.from_dict(d)


REPONSE = json.dumps({"response": {"docs": [{"halId_s": "hal-01234567", "title_s": ["Les houillères"]}]}})


@pytest.fixture
def registre(tmp_path):
    return RegistreReferences(tmp_path / "references-consultees.jsonl")


def test_enregistrer_puis_lire(registre):
    r = _ref()
    registre.enregistrer(r, statut=200, reponse=REPONSE)
    assert registre.est_consultee(r.identifiant)
    assert registre.est_consultee("hal-01234567")
    assert registre.est_consultee("hal:hal-01234567")
    assert registre.lire("hal-01234567") == r
    assert not registre.est_consultee("doi:10.1000/autre")
    assert registre.lire("doi:10.1000/autre") is None
    assert registre.lister() == [r]


def test_identifiant_libre_tous_types(registre):
    r = _ref(identifiant={"type": "doi", "valeur": "10.3406/RNORD.1975.3360"})
    registre.enregistrer(r, statut=200, reponse='{"DOI":"10.3406\\/rnord.1975.3360"}')  # JSON échappé, casse
    assert registre.est_consultee("https://doi.org/10.3406/rnord.1975.3360")
    assert registre.est_consultee("10.3406/rnord.1975.3360")


@pytest.mark.parametrize("statut", [301, 404, 429, 500])
def test_reponse_non_2xx_refusee(registre, statut):
    with pytest.raises(NonConsultee, match="2xx"):
        registre.enregistrer(_ref(), statut=statut, reponse=REPONSE)
    assert not registre.est_consultee("hal-01234567")


def test_identifiant_absent_de_la_reponse_refuse(registre):
    with pytest.raises(NonConsultee, match="absent"):
        registre.enregistrer(_ref(), statut=200, reponse='{"response": {"docs": []}}')
    assert registre.lister() == []


def test_url_identifiant_egale_a_la_requete(registre):
    url = "https://www.persee.fr/doc/rnord_0035-2624_1975_num_57_225_3360"
    r = _ref(identifiant={"type": "url", "valeur": url}, requete=url)
    registre.enregistrer(r, statut=200, reponse="<html>notice</html>")
    assert registre.est_consultee(url)


@pytest.mark.parametrize("champ", ["service", "requete", "consulte_le"])
def test_trace_de_consultation_obligatoire(registre, champ):
    with pytest.raises(ReferenceInvalide, match=champ):
        registre.enregistrer(_ref(**{champ: ""}), statut=200, reponse=REPONSE)


def test_persistant_entre_instances(tmp_path):
    p = tmp_path / "r.jsonl"
    RegistreReferences(p).enregistrer(_ref(), statut=200, reponse=REPONSE)
    assert RegistreReferences(p).est_consultee("hal-01234567")


def test_derniere_consultation_l_emporte(registre):
    registre.enregistrer(_ref(), statut=200, reponse=REPONSE)
    registre.enregistrer(_ref(consulte_le="2026-12-01", pages="12-30"), statut=200, reponse=REPONSE)
    assert registre.lire("hal-01234567").consulte_le == "2026-12-01"
    assert len(registre.lister()) == 1


def test_ligne_corrompue_ignoree(tmp_path):
    p = tmp_path / "r.jsonl"
    RegistreReferences(p).enregistrer(_ref(), statut=200, reponse=REPONSE)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("{tronqué\n")
    reg = RegistreReferences(p)
    assert reg.est_consultee("hal-01234567") and reg.lignes_corrompues == [2]


def test_registre_cable_dans_app_hors_du_cache(app):
    reg = app.registre_references
    assert reg.path == app.config.references_consultees_path
    assert reg.path.parent == app.config.data_dir
    assert reg.path != app.config.cache_path


def test_registre_survit_a_cache_purger(app):
    app.registre_references.enregistrer(_ref(), statut=200, reponse=REPONSE)
    app.cache.set(app.cache.key("x"), {"a": 1}, 3600, source="hal")
    server.cache_purger()
    server.cache_purger("hal")
    for categorie in ("ralentissement", "antirobot", "coupe_circuit", "echec"):
        server.cache_purger(categorie)
    assert app.cache.stats() == {}
    assert app.registre_references.est_consultee("hal-01234567")
    assert server.App(app.config).registre_references.est_consultee(Identifiant("hal", "hal-01234567"))
