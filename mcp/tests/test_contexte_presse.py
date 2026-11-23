"""#288 : presse_recherche, presse ancienne multi-services avec repli explicite.

Aucun accès réseau (respx). Réponse SRU de Gallica : fixture existante du client (fixtures/api/gallica_sru.xml) ;
blocage : page Cloudflare réelle réduite (fixtures/contexte/reponses/GALLICA/). Noms fictifs."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import respx

from genealogiste_mcp import server
from genealogiste_mcp.contexte import presse, services

FIX = Path(__file__).parent / "fixtures"
REPONSES = FIX / "contexte" / "reponses"
SRU = "https://gallica.bnf.fr/SRU"
CONTENT_SEARCH = "https://gallica.bnf.fr/services/ContentSearch"
ARK = "ark:/12148/bpt6k1234567x"
# Réponse ContentSearch au format lu par le client existant (gallica.search_in_document) ; données fictives.
CONTENT = ("<results><item><p_id>PAG_3</p_id><content>la gr&#232;ve des mineurs de "
           "&lt;span class='highlight'&gt;Courri&#232;res&lt;/span&gt; continue</content></item></results>")
SECRET = "cle-europeana-tres-secrete"  # factice, comme tests/test_sources_contexte.py


def _sru() -> str:
    return (FIX / "api" / "gallica_sru.xml").read_text(encoding="utf-8")


def _cloudflare() -> str:
    return (REPONSES / "GALLICA" / "sru-403-cloudflare.html").read_text(encoding="utf-8")


def _par_service(res: dict) -> dict:
    return {e["service"]: e for e in res["services"]}


def _journal(app, jid: str) -> dict:
    return next(e for e in app.journal.entries() if e["id"] == jid)


# ---------------------------------------------------------------- Gallica répond

def test_gallica_repond_references_normalisees_ocr_et_registre(app):
    with respx.mock(assert_all_called=False) as router:
        sru = router.get(SRU).respond(200, text=_sru())
        router.get(CONTENT_SEARCH).respond(200, text=CONTENT)
        autre = router.route().respond(200, json={})
        res = server.presse_recherche("grève", lieu="Courrières", periode="1906")
    q = sru.calls[0].request.url.params["query"]
    assert 'gallica all "grève Courrières"' in q and 'dc.type all "fascicule"' in q
    assert '>="1906"' in q and '<="1906"' in q
    assert not autre.called  # ni Europeana, ni Chronicling America, ni Retronews interrogés
    assert res["statut"] == "resultats" and res["nb_resultats"] == 1 and "tache_manuelle" not in res
    (r,) = res["resultats"]
    assert r["identifiant"] == {"type": "ark", "valeur": ARK}
    assert r["nature"] == "primaire" and r["type_document"] == "presse" and r["lu"] == "notice_seule"
    assert r["publication"] == "L'Écho rochelais" and r["date"] == "1885-01-10" and r["annee"] == 1885
    assert r["service"] == "GALLICA" and r["requete"].startswith(SRU + "?") and r["consulte_le"]
    assert r["ocr"] is True and r["mention"] == "lecture OCR non vérifiée"
    assert r["extrait"] == "la grève des mineurs de Courrières continue"
    assert r["vue"] == 3 and r["url"].endswith("/f3.item")
    assert ARK in r["citation"] and "10 janvier 1885" in r["citation"]
    assert r["au_registre"] is True
    ref = app.registre_references.lire(ARK)
    assert ref is not None and ref.nature == "primaire" and ref.service == "GALLICA"
    # repli explicite : chaque service a son statut et son motif, sans requête pour les services écartés
    etats = _par_service(res)
    assert list(etats) == list(presse.SERVICES_PRESSE)
    assert etats["GALLICA"]["statut"] == "interroge" and etats["GALLICA"]["nb_resultats"] == 1
    assert etats["EUROPEANA"]["statut"] == "refuse" and "désactivé" in etats["EUROPEANA"]["motif"]  # défaut
    for code in ("CHRONICLING-AMERICA", "RETRONEWS"):
        assert etats[code]["statut"] == "lien_seulement" and etats[code]["requetes_emises"] == 0
    # journal : recherche Gallica et synthèse de l'outil
    assert _journal(app, res["journal"])["statut"] == "positif"
    assert _journal(app, etats["GALLICA"]["journal"])["source"] == "gallica"


def test_sans_extrait_ocr_aucune_mention(app):
    with respx.mock(assert_all_called=False) as router:
        router.get(SRU).respond(200, text=_sru())
        router.get(CONTENT_SEARCH).respond(200, text="<results></results>")
        res = server.presse_recherche("grève", services="GALLICA")
    (r,) = res["resultats"]
    assert r["ocr"] is False and r["extrait"] == "" and "mention" not in r and r["vue"] is None


# ---------------------------------------------------------------- Gallica bloqué, Europeana sans clé

def test_gallica_bloque_puis_coupe_circuit_europeana_sans_cle_tache_manuelle(app):
    app.config.contexte_services = (*services.actifs_par_defaut(), "EUROPEANA")  # activé, clé absente
    with respx.mock(assert_all_called=False) as router:
        sru = router.get(SRU).respond(403, text=_cloudflare(), headers={"content-type": "text/html; charset=UTF-8"})
        autre = router.route().respond(200, json={})
        premier = server.presse_recherche("grève", lieu="Courrières", periode="1900-1910")
        second = server.presse_recherche("grève", lieu="Courrières", periode="1900-1910")
    assert sru.call_count == 1 and not autre.called  # coupe-circuit : aucune nouvelle requête
    for res in (premier, second):
        assert res["statut"] == "bloque_antirobot" and res["resultats"] == [] and res["nb_resultats"] == 0
        assert res["service"] == "GALLICA" and res["protection"] == "Cloudflare"
        assert res["suite"]["relancer"] is False and "consigne" in res
        etats = _par_service(res)
        assert etats["GALLICA"]["statut"] == "bloque_antirobot"
        assert etats["EUROPEANA"]["statut"] == "refuse" and etats["EUROPEANA"]["requetes_emises"] == 0
        assert "GENEALOGISTE_CLE_EUROPEANA" in etats["EUROPEANA"]["motif"]
        tache = res["tache_manuelle"]
        assert tache["statut"] == "a_faire" and set(tache["motifs"]) == set(presse.SERVICES_PRESSE)
        assert {x["service"] for x in tache["liens"]} == set(presse.SERVICES_PRESSE)
        assert "source_collee" in tache["reprise"]
        assert _journal(app, res["journal"])["statut"] == "bloque_antirobot"
    assert _par_service(second)["GALLICA"].get("coupe_circuit") is True
    assert app.registre_references.lister() == []  # aucun résultat inventé, rien au registre


def test_aucun_resultat_tache_manuelle_et_journal_negatif(app):
    vide = ('<?xml version="1.0" encoding="UTF-8"?><srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/">'
            "<srw:version>1.2</srw:version><srw:numberOfRecords>0</srw:numberOfRecords></srw:searchRetrieveResponse>")
    with respx.mock(assert_all_called=False) as router:
        router.get(SRU).respond(200, text=vide)
        res = server.presse_recherche("grève", lieu="Courrières")
    assert res["statut"] == "tache_manuelle" and res["resultats"] == [] and res["recherche_negative"]
    assert res["tache_manuelle"]["liens"] and "erreur" not in res
    assert _journal(app, res["journal"])["statut"] == "negatif"
    assert app.registre_references.lister() == []


def test_services_en_lien_seulement_aucune_requete(app):
    with respx.mock(assert_all_called=False) as router:
        route = router.route().respond(200, json={})
        res = server.presse_recherche("strike", lieu="Oklahoma", services="chronicling-america, RETRONEWS")
    assert not route.called
    assert [e["service"] for e in res["services"]] == ["CHRONICLING-AMERICA", "RETRONEWS"]
    assert res["statut"] == "tache_manuelle" and _journal(app, res["journal"])["statut"] == "manuel"


def test_blocage_dans_une_enquete_devient_une_tache(app):
    eid = server.enquete_ouvrir("Presse")["id"]
    with respx.mock(assert_all_called=False) as router:
        router.get(SRU).respond(403, text=_cloudflare(), headers={"content-type": "text/html; charset=UTF-8"})
        res = server.presse_recherche("grève", lieu="Courrières", enquete=eid)
    assert res["tache_manuelle"]["enquete"] == eid
    (t,) = server.enquete_etat(eid)["taches_manuelles"]
    assert t["service"] == "GALLICA" and t["url"] == "https://gallica.bnf.fr/"


# ---------------------------------------------------------------- Europeana : clé jamais exposée

def test_europeana_avec_cle_sans_analyseur_cle_jamais_exposee(app):
    app.config.cles_contexte = {"EUROPEANA": SECRET}
    app.config.contexte_services = (*services.actifs_par_defaut(), "EUROPEANA")
    with respx.mock(assert_all_called=False) as router:
        router.get(SRU).respond(200, text=_sru())
        router.get(CONTENT_SEARCH).respond(200, text=CONTENT)
        router.route().respond(200, json={})
        res = server.presse_recherche("grève", lieu="Courrières")
        hotes = {c.request.url.host for c in router.calls}
    assert hotes == {"gallica.bnf.fr"}  # aucune requête à l'API Europeana sans analyseur enregistré
    eu = _par_service(res)["EUROPEANA"]
    assert eu["statut"] == "sans_analyseur" and eu["requetes_emises"] == 0
    assert SECRET not in json.dumps(res, ensure_ascii=False)
    assert SECRET not in app.config.journal_path.read_text(encoding="utf-8")
    assert SECRET not in app.config.references_consultees_path.read_text(encoding="utf-8")
    assert SECRET.encode() not in app.config.cache_path.read_bytes()
    assert all(SECRET.encode() not in f.read_bytes() for f in REPONSES.rglob("*") if f.is_file())


# ---------------------------------------------------------------- vivants, paramètres

@pytest.mark.parametrize("kwargs", [{"texte": "Lucas MARTIN"}, {"texte": "grève", "lieu": "Lucas MARTIN"}])
def test_vivant_refuse_avant_toute_requete(app_famille, kwargs):
    with respx.mock(assert_all_called=False) as router:
        route = router.route().respond(200, json={})
        res = server.presse_recherche(**kwargs)
    assert "refus" in res and not route.called
    assert app_famille.registre_references.lister() == []


@pytest.mark.parametrize("kwargs,motif", [
    ({"texte": "grève", "periode": "vers 1906"}, "periode"),
    ({"texte": "grève", "periode": "1910-1900"}, "fin antérieure"),
    ({"texte": "grève", "services": "GALLICA,HAL"}, "HAL"),
    ({"texte": "  "}, "texte"),
])
def test_parametres_invalides_aucune_requete(app, kwargs, motif):
    with respx.mock(assert_all_called=False) as router:
        route = router.route().respond(200, json={})
        res = server.presse_recherche(**kwargs)
    assert motif in res["erreur"] and res["requetes_emises"] == 0 and not route.called


# ---------------------------------------------------------------- liens de consultation

def _decoder_retronews(url: str) -> dict:
    """Décodage du paramètre q tel que le fait le site : JSON.parse(decodeURIComponent(atob(q)))."""
    q = parse_qs(urlsplit(url).query)["q"][0]
    return json.loads(unquote(base64.b64decode(q).decode("ascii")))


def test_lien_retronews_meme_forme_que_le_site():
    site = (REPONSES / "RETRONEWS" / "accueil-lien-recherche-avancee.html").read_text(encoding="utf-8")
    href = re.search(r'href="([^"]+)"', site).group(1).replace("&amp;", "&")
    modele = _decoder_retronews("https://www.retronews.fr" + href)
    lien = presse.lien_retronews("grève Courrières")
    assert lien.startswith("https://www.retronews.fr/search?page=1&advanced=true&q=")
    decode = _decoder_retronews(lien)
    assert decode["search"]["criteria"]["allTheseWords"] == "grève Courrières"
    decode["search"]["criteria"]["allTheseWords"] = ""
    assert decode == modele
    assert "decodeURIComponent(atob(t))" in (REPONSES / "RETRONEWS" / "recherche-decodage-q.js").read_text()


def test_liens_recherche_verifies_sinon_accueil():
    liens = {x["service"]: x for x in presse.liens_consultation("grève", "Courrières", "1906", "1906")}
    assert liens["EUROPEANA"]["url"] == "https://www.europeana.eu/fr/search?query=gr%C3%A8ve%20Courri%C3%A8res"
    manifeste = json.loads((REPONSES / "EUROPEANA" / "MANIFESTE.json").read_text(encoding="utf-8"))
    assert liens["EUROPEANA"]["url"] in {r["url"] for r in manifeste["reponses"]}
    for code in ("GALLICA", "CHRONICLING-AMERICA"):
        assert liens[code]["forme"] == "accueil" and liens[code]["url"] == services.par_code(code)["site"]
        assert "grève Courrières" in liens[code]["a_saisir"]
    assert liens["RETRONEWS"]["forme"] == "recherche" and "1906" in liens["RETRONEWS"]["a_saisir"]


def test_reponses_enregistrees_avec_manifeste():
    for code in presse.SERVICES_PRESSE:
        dossier = REPONSES / code
        manifeste = json.loads((dossier / "MANIFESTE.json").read_text(encoding="utf-8"))
        assert manifeste["service"] == code and manifeste["reponses"]
        fichiers = {p.name for p in dossier.iterdir()} - {"MANIFESTE.json"}
        assert fichiers == {r["fichier"] for r in manifeste["reponses"] if r["fichier"]}
        for r in manifeste["reponses"]:
            assert r["date"].startswith("2026-") and isinstance(r["statut"], int)
            assert "wskey" not in r["url"].lower() and "key=" not in r["url"].lower()
            if r["fichier"]:
                contenu = (dossier / r["fichier"]).read_bytes()
                assert r["empreinte"] == "sha256:" + hashlib.sha256(contenu).hexdigest()
                texte = contenu.decode("utf-8")
                assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b|[0-9a-f]{4}:[0-9a-f]{1,4}:[0-9a-f]{1,4}::", texte)
                assert "ray id" not in texte.lower()
