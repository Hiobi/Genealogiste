"""Référentiel des archives : format, recherche par lieu / département / code, en ligne vs communicable."""

from datetime import date

from genealogiste_mcp import archives, ark, server


def test_referential_is_valid():
    assert archives.validate() == []
    assert archives.by_code("ad59")["ark_naan"] == "33518"


def test_naan_table_fed_by_referential():
    archives.services()
    assert ark.NAANS["33518"]["code"] == "AD59" and ark.NAANS["12148"]["code"] == "BnF"


def test_service_by_place_departement_code():
    assert server.archives_service(lieu="Somain (59)")["code"] == "AD59"
    assert server.archives_service(departement="62")["visionneuse"].startswith("http://archivesenligne")
    assert server.archives_service(code="SHD")["type"] == "militaires"
    imported = server.archives_service(departement="17")
    assert imported["code"] == "AD17" and imported["wikidata"].startswith("Q")
    assert "importée automatiquement" in imported["avertissement"]
    assert server.archives_service(departement="75")["code"] == "AP"


def test_every_department_has_an_entry():
    from genealogiste_mcp.normalize.places import DEPARTEMENTS
    have = {s["departement"] for s in archives.services() if s["type"] == "departementales"}
    assert set(DEPARTEMENTS) <= have


def test_missing_department_falls_back_to_francearchives(monkeypatch):
    monkeypatch.setattr(archives, "departemental", lambda dep: None)
    r = server.archives_service(departement="17")
    assert r["code"] == "AD17" and "absentes du référentiel" in r["avertissement"]
    assert "erreur" in server.archives_service(code="XYZ") and "erreur" in server.archives_service()


def test_visionneuse_acces_classe_les_services():
    acces = server.archives_service(code="AD59")["visionneuse_acces"]
    assert acces["famille"] == "editeur_ad" and acces["iiif"] is False
    assert acces["protection"] == "cloudflare_hcaptcha"


def test_online_unknown_vs_known():
    assert archives.online(archives.by_code("AD59"), "naissance", 1926) is None  # référentiel muet : inconnu
    m = archives.by_code("MATCHID")
    assert archives.online(m, "deces", 1985) is True and archives.online(m, "deces", 1960) is False


def test_staleness():
    s = {"code": "X", "verifie_le": "2024-01-01"}
    assert "plus de 12 mois" in archives.staleness(s, date(2026, 11, 4))
    assert archives.staleness({"code": "X", "verifie_le": "2026-10-01"}, date(2026, 11, 4)) == ""
    assert "jamais vérifiée" in archives.staleness({"code": "X"})


def test_communicable_but_not_known_online_proposes_letter():
    r = server.communicabilite("naissance", "1926", lieu="Somain (59)", personne="Gustave LEGRAND")
    assert r["communicable"] is True and r["en_ligne"] is None
    assert r["service_archives"]["code"] == "AD59"
    assert "mairie" in r["si_pas_en_ligne"]["conseil"]
    assert "Gustave LEGRAND" in r["si_pas_en_ligne"]["courrier"] and "Somain" in r["si_pas_en_ligne"]["courrier"]


def test_not_communicable_mentions_derogation():
    r = server.communicabilite("naissance", "2000", lieu="Somain (59)")
    assert r["communicable"] is False and "L213-3" in r["si_non_communicable"]


def test_communicabilite_without_place_unchanged():
    r = server.communicabilite("deces", "1900")
    assert "service_archives" not in r and r["communicable"] is True


def test_links_and_cotes_use_real_service():
    links = server.liens_recherche("LEGRAND", "Gustave", "1926", "Somain (59)")["liens"]
    ad = next(x for x in links if "Nord" in x["site"])
    assert ad["url"] == "https://archivesdepartementales.lenord.fr"
    c = server.cotes_a_consulter("BIRT", "1926", "Somain (59)")
    assert c["service"] == "Archives départementales du Nord" and c["service_archives"]["code"] == "AD59"
