"""#286 : analyseurs de protocole (Solr, SRU, OAI-PMH, REST) et gabarits des services bibliographiques.

Toutes les réponses lues ici sont des réponses réelles enregistrées (tests/fixtures/contexte/reponses/<service>/,
MANIFESTE.json : URL, date, statut HTTP, réduction). Aucun accès réseau."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genealogiste_mcp.config import Config
from genealogiste_mcp.contexte import services as srv
from genealogiste_mcp.contexte.gabarits import GABARITS, ORDRE, Recherche
from genealogiste_mcp.contexte.modeles import Reference
from genealogiste_mcp.contexte.protocoles import ReponseInvalide, oai, rest, solr, sru

REPONSES = Path(__file__).parent / "fixtures" / "contexte" / "reponses"


def lire(service: str, fichier: str):
    texte = (REPONSES / service / fichier).read_text(encoding="utf-8")
    return json.loads(texte) if fichier.endswith(".json") else texte


def analyser(code: str, fichier: str):
    return GABARITS[code].analyser(lire(code.lower(), fichier))


def retenues(code: str, fichier: str) -> list:
    return [n for n in analyser(code, fichier)[1] if not n.ecart]


# ---------------------------------------------------------------- réponses enregistrées

def test_chaque_service_livre_a_une_reponse_enregistree_et_un_manifeste():
    for code in ORDRE:
        dossier = REPONSES / code.lower()
        manifeste = json.loads((dossier / "MANIFESTE.json").read_text(encoding="utf-8"))
        assert manifeste["service"] == code
        for r in manifeste["reponses"]:
            assert (dossier / r["fichier"]).is_file(), r
            assert r["statut"] == 200 and r["date"] and r["url"].startswith("https://")
            assert srv.url_autorisee(code, r["url"]), r["url"]
            assert "mailto" not in r["url"] and "api_key" not in r["url"]
        assert srv.par_code(code)["protocole"] == GABARITS[code].protocole.replace("oai", "oai-pmh")
    persee = json.loads((REPONSES / "persee" / "MANIFESTE.json").read_text(encoding="utf-8"))
    assert all((REPONSES / "persee" / r["fichier"]).is_file() for r in persee["reponses"])


def test_protocole_de_chaque_famille_couvert():
    assert {g.protocole for g in GABARITS.values()} == {"solr", "sru", "rest"}  # OAI : analyseur seul (Persée)


# ---------------------------------------------------------------- Solr

def test_solr_documents_reponse_hal():
    total, docs = solr.documents(lire("hal", "courrieres-mines.json"))
    assert total == 10 and len(docs) == 5
    assert all("halId_s" in d for d in docs)


def test_solr_reponse_vide_et_forme_inattendue():
    assert solr.documents(lire("hal", "billy-montigny-mines.json")) == (0, [])
    for mauvais in ({}, [], {"response": {}}, "texte"):
        with pytest.raises(ReponseInvalide):
            solr.documents(mauvais)


def test_solr_expression_neutralise_la_syntaxe():
    assert solr.expression(["Courrières"], "mines") == '"Courrières" AND mines'
    assert solr.expression(["A", "B"], "") == '("A" OR "B")'
    assert solr.expression(['Saint-"Pol" (62)'], "mines AND charbon:*") == '"Saint- Pol (62)" AND (mines AND charbon)'
    assert solr.expression([], "") == ""


# ---------------------------------------------------------------- SRU

def test_sru_unimarc_sudoc():
    total, recs = sru.enregistrements(lire("sudoc", "courrieres-mines.xml"))
    assert total == 21 and len(recs) == 5
    n = sru.unimarc(recs[0])
    assert len(n.leader) >= 24 and n.leader[6] == "a"  # positions du leader conservées (espaces de tête)
    assert n.controles["001"].isdigit() or n.controles["001"][-1] == "X"


def test_sru_dublin_core_bnf():
    total, recs = sru.enregistrements(lire("bnf-catalogue", "courrieres-mines.xml"))
    assert total == 30 and len(recs) == 5
    dc = sru.dublin_core(recs[0])
    assert any("ark:/12148/" in v for v, _ in dc["identifier"])


def test_sru_diagnostic_reel_leve():
    with pytest.raises(ReponseInvalide, match="Index non supporté"):
        sru.enregistrements(lire("bnf-catalogue", "diagnostic-index-inconnu.xml"))


def test_xml_avec_dtd_refuse():
    with pytest.raises(ReponseInvalide, match="DTD"):
        sru.enregistrements('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>')


def test_cql_neutralise_la_syntaxe():
    assert sru.cql_phrase('Billy "Montigny"') == '"Billy Montigny"'
    assert sru.cql_mots('mines and (charbon) or prox="x"') == ["mines", "charbon", "x"]


# ---------------------------------------------------------------- OAI-PMH

def test_oai_getrecord_persee():
    notices = oai.notices(lire("persee", "getrecord-rnord-1982-3879.xml"))
    assert len(notices) == 1
    n = notices[0]
    assert n.identifiant == "oai:persee:article/rnord_0035-2624_1982_num_64_253_3879"
    assert "doi:10.3406/rnord.1982.3879" in n.valeurs("identifier")
    assert n.valeurs("creator") == ["Thiébault, Jean-Louis", "Wallon-Leducq, Christian-Marie"]
    assert n.valeurs("coverage") == ["pp. 603-635"]


def test_oai_autre_reponse_refusee():
    with pytest.raises(ReponseInvalide):
        oai.notices(lire("bnf-catalogue", "courrieres-mines.xml"))


# ---------------------------------------------------------------- REST

def test_rest_chemins_et_textes():
    d = lire("isidore", "courrieres-mines.json")
    assert rest.entier(rest.chemin(d, "response.replies.meta.@items")) > 0
    assert rest.chemin(d, "response.inexistant.0", "x") == "x"
    assert rest.texte({"$": " a "}) == "a" and rest.texte([{"$": ""}, "b"]) == "b" and rest.texte(True) == ""
    assert rest.liste(None) == [] and rest.liste(1) == [1]
    with pytest.raises(ReponseInvalide):
        rest.exiger(d, "message.items", list)


# ---------------------------------------------------------------- gabarits : notices normalisées

def test_hal_notices():
    total, notices = analyser("HAL", "courrieres-mines.json")
    assert total == 10 and len(notices) == 5 and not [n for n in notices if n.ecart]
    fortunet = next(n.champs for n in notices if "police des mines" in n.champs["titre"])
    assert fortunet["identifiant"].cle.startswith("hal:halshs-")
    assert fortunet["type_document"] == "chapitre" and fortunet["auteurs"] == ["Fortunet, Françoise"]
    assert fortunet["publication"] and fortunet["pages"] == "138-144" and fortunet["annee"] == 2007
    revue = next(n.champs for n in notices if n.champs["type_document"] == "article")
    assert revue["evaluation_par_les_pairs"] == "oui" and revue["nature"] == "secondaire_savante"
    assert not revue["numero"].lower().startswith("n")  # préfixe « n° » du service retiré


def test_isidore_notices():
    total, notices = analyser("ISIDORE", "courrieres-mines.json")
    assert total and total > 1000 and len(notices) == 5
    for n in notices:
        assert n.champs["identifiant"].type in ("doi", "handle")
        assert n.champs["titre"]
    assert any(n.champs["identifiant"].type == "doi" for n in notices)


def test_sudoc_notices():
    total, notices = analyser("SUDOC", "courrieres-mines.xml")
    assert total == 21 and len(notices) == 5
    tavernier = next(n.champs for n in notices if n.champs.get("identifiant") and
                     n.champs["identifiant"].valeur == "000798495")
    assert tavernier["auteurs"] == ["Tavernier, André"] and tavernier["annee"] == 1981
    assert tavernier["type_document"] == "monographie"
    _, billy = analyser("SUDOC", "billy-montigny-mines.xml")
    assert [n.ecart for n in billy if n.ecart] == ["document non textuel (carte, image, son, objet…)"]  # plan IGN
    notice_1900 = next(n.champs for n in billy if not n.ecart and n.champs["annee"] == 1900)
    assert notice_1900["lieu_edition"] == ""  # « Lieu d'impression inconnu » n'est pas un lieu


def test_bnf_notices():
    total, notices = analyser("BNF-CATALOGUE", "courrieres-mines.xml")
    assert total == 30 and len(notices) == 5
    photo = [n for n in notices if n.ecart]
    assert [n.titre_brut for n in photo] == ["[Mines de Courrières] : [photographie]"]
    tavernier = next(n.champs for n in notices if not n.ecart and "concession" in n.champs["titre"])
    assert tavernier["identifiant"].cle == "ark:ark:/12148/cb347626502"
    assert tavernier["auteurs"] == ["Tavernier, André"] and tavernier["titre"].endswith("concession minière")
    assert tavernier["annee"] == 1981


def test_theses_notices():
    total, notices = analyser("THESES-FR", "courrieres-mines.json")
    assert total == 5 and len(notices) == 5
    for n in notices:
        if n.ecart:
            assert "DOI" in n.ecart or "non soutenue" in n.ecart
        else:
            assert n.champs["identifiant"].type == "doi" and n.champs["type_document"] == "these"
            assert n.champs["nature"] == "secondaire_savante" and n.champs["publication"]


def test_crossref_notices():
    total, notices = analyser("CROSSREF", "courrieres-mines.json")
    assert total and len(notices) == 5
    accident = next(n.champs for n in notices if n.champs["identifiant"].valeur == "10.1051/metal/190603120709")
    assert accident["annee"] == 1906 and accident["type_document"] == "article" and accident["pages"] == "709-716"
    assert accident["auteurs"][0].startswith("Cunynghame")


@pytest.mark.parametrize("code", ORDRE)
def test_chaque_notice_retenue_construit_une_reference(code):
    fichier = "courrieres-mines.json" if GABARITS[code].parse == "json" else "courrieres-mines.xml"
    for n in retenues(code, fichier):
        ref = Reference(service=code, requete="https://x.example/", consulte_le="2026-11-23", **n.champs)
        assert ref.identifiant and ref.lu == "notice_seule"


@pytest.mark.parametrize("code", ORDRE)
def test_parametres_sans_donnee_personnelle(code):
    """Seuls lieux, sujet et paramètres techniques ; mailto seulement si l'utilisateur l'a renseigné."""
    cfg = Config(data_dir=Path("/tmp/x"), cache_path=Path("/tmp/x.sqlite"))
    p = GABARITS[code].parametres(Recherche(("Courrières",), "mines", 5), cfg)
    texte = json.dumps(p, ensure_ascii=False)
    assert "Courrières" in texte and "mines" in texte and "mailto" not in texte
    cfg.crossref_mailto = "moi@exemple.fr"
    assert ("mailto" in GABARITS[code].parametres(Recherche(("X",), "", 5), cfg)) == (code == "CROSSREF")
