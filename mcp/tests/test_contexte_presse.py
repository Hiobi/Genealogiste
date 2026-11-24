"""#288, #343 : presse_recherche, presse ancienne multi-services avec repli explicite.

Aucun accès réseau (respx). Europeana : réponses réelles réduites (fixtures/contexte/reponses/EUROPEANA/), clé
factice. Réponse SRU de Gallica : fixture existante du client (fixtures/api/gallica_sru.xml) ;
blocage : page Cloudflare réelle réduite (fixtures/contexte/reponses/GALLICA/). Noms fictifs."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest
import respx
from test_enregistrer_contexte import rec

from genealogiste_mcp import server
from genealogiste_mcp.contexte import presse, services
from genealogiste_mcp.contexte.modeles import MENTION_TENDANCE
from genealogiste_mcp.http import marque_authentification

FIX = Path(__file__).parent / "fixtures"
REPONSES = FIX / "contexte" / "reponses"
SRU = "https://gallica.bnf.fr/SRU"
CONTENT_SEARCH = "https://gallica.bnf.fr/services/ContentSearch"
API_EUROPEANA = "https://api.europeana.eu/record/v2/search.json"
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


# ---------------------------------------------------------------- Europeana : analyseur (#343)

def _europeana_reelle(nom: str = "api-recherche-courrieres-1850-1950.json") -> dict:
    return json.loads((REPONSES / "EUROPEANA" / nom).read_text(encoding="utf-8"))


def _europeana_avec_cle(nom: str = "api-recherche-courrieres-1850-1950.json") -> dict:
    """Réponse enregistrée telle que le service la rend : il y répète la clé reçue (``apikey``, ``link`` avec
    ``wskey``, ``utm_campaign`` de ``guid``) et le compteur du compte. La clé est ici la valeur factice."""
    d = _europeana_reelle(nom)
    d = {"apikey": SECRET, "requestNumber": 999, **d}
    for item in d["items"]:
        item["link"] = f"https://api.europeana.eu/record{item['id']}.json?wskey={SECRET}"
        item["guid"] += f"?utm_source=api&utm_medium=api&utm_campaign={SECRET}"
    return d


def _tout_le_cache(app) -> str:
    """Tout le cache SQLite (toutes tables, clés et valeurs) et tous les fichiers de données, en texte."""
    app.cache._db.commit()
    app.cache._db.execute("PRAGMA wal_checkpoint(FULL)")
    base = sqlite3.connect(str(app.config.cache_path))
    try:
        tables = [r[0] for r in base.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        textes = [json.dumps({t: base.execute(f"SELECT * FROM {t}").fetchall() for t in tables},
                             ensure_ascii=False, default=str)]
    finally:
        base.close()
    textes += [f.read_bytes().decode("utf-8", errors="replace") for f in app.config.data_dir.rglob("*")
               if f.is_file() and ".git" not in f.parts]
    textes.append(app.config.cache_path.read_bytes().decode("utf-8", errors="replace"))
    return "\n".join(textes)


def _activer_europeana(app, cle: str = SECRET) -> None:
    app.config.cles_contexte = {"EUROPEANA": cle} if cle else {}
    app.config.contexte_services = (*services.actifs_par_defaut(), "EUROPEANA")


def test_gallica_bloque_la_recherche_aboutit_par_europeana_cle_jamais_exposee(app):
    _activer_europeana(app)
    arbre = app.config.tree_path.read_bytes() if app.config.tree_path.is_file() else None
    with respx.mock(assert_all_called=False) as router:
        router.get(SRU).respond(403, text=_cloudflare(), headers={"content-type": "text/html; charset=UTF-8"})
        api = router.get(API_EUROPEANA).respond(200, json=_europeana_avec_cle())
        autre = router.route().respond(200, json={})
        res = server.presse_recherche("Courrières", periode="1850-1950", nombre=5)
        encore = server.presse_recherche("Courrières", periode="1850-1950", nombre=5)
        urls = [str(c.request.url) for c in router.calls]
    assert not autre.called and api.call_count == 1  # second appel : cache (Europeana), coupe-circuit (Gallica)
    requete = api.calls[0].request
    assert requete.headers["X-Api-Key"] == SECRET  # la clé part en en-tête…
    assert all(SECRET not in u and "wskey" not in u.lower() for u in urls)  # … jamais dans une URL
    assert dict(requete.url.params) == {"query": "Courrières", "rows": "5", "qf": "YEAR:[1850 TO 1950]"}
    # la recherche aboutit par Europeana, Gallica reste signalé bloqué
    assert res["statut"] == "resultats" and res["nb_resultats"] == 5 and "tache_manuelle" not in res
    etats = _par_service(res)
    assert etats["GALLICA"]["statut"] == "bloque_antirobot"
    eu = etats["EUROPEANA"]
    assert eu["statut"] == "interroge" and eu["total"] == 11 and eu["nb_resultats"] == 5
    assert eu["depuis_cache"] is False and _par_service(encore)["EUROPEANA"]["depuis_cache"] is True
    assert eu["requete"].startswith(API_EUROPEANA + "?query=Courri%C3%A8res")
    # références : identifiant europeana, citation, mention de tendance générale, registre
    r = res["resultats"][0]
    assert r["identifiant"] == {"type": "europeana", "valeur": "/2022038/11088_de_bo133_4205"}
    assert r["titre"] == "Ist ein deutsches Courrières möglich?" and r["annee"] == 1906
    assert r["publication"] == "Library of the Friedrich Ebert Foundation"
    assert r["nature"] == "primaire" and r["type_document"] == "autre" and r["lu"] == "notice_seule"
    assert r["service"] == "EUROPEANA" and r["consulte_le"] and r["requete"] == eu["requete"]
    assert "Europeana /2022038/11088_de_bo133_4205" in r["citation"] and "1906" in r["citation"]
    assert r["mention"] == MENTION_TENDANCE and r["ocr"] is False and r["extrait"] == ""
    assert r["url"] == "https://www.europeana.eu/item/2022038/11088_de_bo133_4205"
    assert r["url_fournisseur"] == "http://hdl.handle.net/11088/de-bo133:4205#1" and r["type_europeana"] == "TEXT"
    assert res["resultats"][1]["auteurs"] == ["Steinlen, Théophile Alexandre (1859-1923). Lithographe"]
    assert all(x["au_registre"] and x["identifiant"]["type"] == "europeana" for x in res["resultats"])
    consultees = app.registre_references.lister()
    assert [x.identifiant.cle for x in consultees] == [f"europeana:{x['identifiant']['valeur']}"
                                                         for x in res["resultats"]]
    assert app.registre_references.est_consultee("europeana:/2022038/11088_de_bo133_4205")
    # journal : recherche Europeana et synthèse ; aucune écriture dans l'arbre
    assert _journal(app, eu["journal"])["source"] == "europeana"
    assert _journal(app, eu["journal"])["statut"] == "positif" and _journal(app, res["journal"])["statut"] == "positif"
    assert (app.config.tree_path.read_bytes() if app.config.tree_path.is_file() else None) == arbre
    # la clé : ni sortie, ni journal, ni registre, ni cache (clés et valeurs), ni fixture
    assert SECRET not in json.dumps([res, encore], ensure_ascii=False, default=str)
    assert SECRET not in _tout_le_cache(app)
    assert all(SECRET.encode() not in f.read_bytes() for f in REPONSES.rglob("*") if f.is_file())


def test_europeana_seul_service_demande_et_sans_resultat(app):
    """Réponse réelle sans résultat : recherche négative tracée, tâche manuelle, rien au registre."""
    _activer_europeana(app)
    with respx.mock(assert_all_called=False) as router:
        api = router.get(API_EUROPEANA).respond(200, json=_europeana_avec_cle("api-presse-greve-mineurs-1906-vide.json"))
        res = server.presse_recherche("grève des mineurs", lieu="Courrières", periode="1906", services="europeana")
    assert api.call_count == 1 and "qf" in api.calls[0].request.url.params
    (eu,) = res["services"]
    assert eu["statut"] == "interroge" and eu["total"] == 0 and eu["nb_resultats"] == 0
    assert res["statut"] == "tache_manuelle" and res["recherche_negative"] and res["resultats"] == []
    assert _journal(app, eu["journal"])["statut"] == "negatif" and _journal(app, res["journal"])["statut"] == "negatif"
    assert app.registre_references.lister() == []
    assert SECRET not in json.dumps(res, ensure_ascii=False) and SECRET not in _tout_le_cache(app)


def test_europeana_sans_cle_ou_desactive_aucune_requete(app):
    with respx.mock(assert_all_called=False) as router:
        route = router.route().respond(200, json={})
        defaut = server.presse_recherche("grève", services="EUROPEANA")  # non activé (défaut)
        _activer_europeana(app, cle="")
        sans_cle = server.presse_recherche("grève", services="EUROPEANA")  # activé, clé absente
    assert not route.called
    for res, mot in ((defaut, "désactivé"), (sans_cle, "GENEALOGISTE_CLE_EUROPEANA")):
        (eu,) = res["services"]
        assert eu["statut"] == "refuse" and eu["requetes_emises"] == 0 and mot in eu["motif"]
        assert res["statut"] == "tache_manuelle"
    assert "Manage API keys" in sans_cle["services"][0]["motif"]  # motif déjà livré : comment obtenir la clé


@pytest.mark.parametrize("statut,corps", [
    (401, {"success": False, "error": "Invalid API key", "apikey": SECRET}),
    (403, {"success": False, "error": f"clé {SECRET} non autorisée"}),
    (400, {"success": False, "error": f"requête invalide pour wskey={SECRET}"}),
    (500, {"error": f"panne {SECRET}"}),
], ids=["401", "403", "400", "500"])
def test_europeana_en_erreur_motif_sans_cle_puis_tache_manuelle(app, statut, corps):
    _activer_europeana(app)
    app.http.max_retries = 1
    with respx.mock(assert_all_called=False) as router:
        router.get(API_EUROPEANA).respond(statut, json=corps)
        res = server.presse_recherche("grève", lieu="Courrières", services="EUROPEANA")
        server.presse_recherche("grève", lieu="Courrières", services="EUROPEANA")  # échec mémorisé éventuel
    (eu,) = res["services"]
    assert eu["statut"] == "erreur" and str(statut) in eu["motif"] and res["statut"] == "tache_manuelle"
    if statut in (401, 403):
        assert "GENEALOGISTE_CLE_EUROPEANA" in eu["motif"]  # clé refusée : la variable est nommée, jamais la valeur
    assert _journal(app, eu["journal"])["statut"] == "erreur"
    assert app.registre_references.lister() == []
    assert SECRET not in json.dumps(res, ensure_ascii=False) and SECRET not in _tout_le_cache(app)


@pytest.mark.parametrize("corps", [{"success": True, "totalResults": 3}, {"success": False, "error": "x"},
                                   ["liste"]], ids=["sans-items", "echec-declare", "pas-un-objet"])
def test_europeana_reponse_illisible_jamais_de_resultat_devine(app, corps):
    _activer_europeana(app)
    with respx.mock(assert_all_called=False) as router:
        router.get(API_EUROPEANA).respond(200, json=corps)
        res = server.presse_recherche("grève", services="EUROPEANA")
    (eu,) = res["services"]
    assert eu["statut"] == "erreur" and "réponse illisible" in eu["motif"] and res["resultats"] == []


def test_europeana_notice_sans_identifiant_ecartee(app):
    _activer_europeana(app)
    d = _europeana_avec_cle()
    del d["items"][0]["id"]
    d["items"][1]["id"] = "identifiant-inattendu"
    with respx.mock(assert_all_called=False) as router:
        router.get(API_EUROPEANA).respond(200, json=d)
        res = server.presse_recherche("Courrières", services="EUROPEANA")
    assert res["nb_resultats"] == 3 and all(r["au_registre"] for r in res["resultats"])


def test_europeana_syntaxe_de_recherche_retiree_de_la_requete(app):
    assert presse._mots_europeana('fulltext:(grève AND "mineurs") -Lens +Billy-Montigny wskey:x*') == \
        "fulltext grève mineurs Lens Billy-Montigny wskey x"
    _activer_europeana(app)
    with respx.mock(assert_all_called=False) as router:
        route = router.route().respond(200, json={})
        res = server.presse_recherche('"(: )"', services="EUROPEANA")
    assert not route.called and res["services"][0]["statut"] == "erreur"


def test_epuration_egale_a_la_reduction_enregistree():
    """La réponse telle que le service la rend, épurée, est exactement le fichier enregistré : même fonction pour
    le cache du plugin et pour la réduction du script d'enregistrement."""
    for nom in ("api-recherche-courrieres-1850-1950.json", "api-presse-greve-mineurs-1906-vide.json"):
        brut = json.dumps(_europeana_avec_cle(nom), ensure_ascii=False).encode("utf-8")
        assert SECRET.encode() in brut
        reduit = rec.reduire("EUROPEANA", nom, brut)
        assert reduit == (REPONSES / "EUROPEANA" / nom).read_bytes()
        assert presse.epurer_europeana(json.loads(brut)) == _europeana_reelle(nom)


def test_cache_http_ne_melange_pas_avec_et_sans_cle(app):
    """Même URL avec et sans en-tête d'authentification : deux entrées de cache, dont la clé ne contient pas la
    valeur de l'en-tête (seule sa présence compte)."""
    url = "https://api.europeana.eu/record/v2/search.json"
    with respx.mock(assert_all_called=False) as router:
        route = router.get(url).mock(side_effect=lambda req: httpx.Response(
            200, json={"avec_cle": "x-api-key" in req.headers}))
        avec, _ = app.http.get(url, params={"query": "mines"}, headers={"X-Api-Key": SECRET})
        sans, cache_sans = app.http.get(url, params={"query": "mines"})
        avec2, cache_avec = app.http.get(url, params={"query": "mines"}, headers={"x-api-key": "autre-" + SECRET})
    assert avec == {"avec_cle": True} and sans == {"avec_cle": False} and cache_sans is False
    assert avec2 == avec and cache_avec is True and route.call_count == 2  # présence de la clé, pas sa valeur
    assert marque_authentification({"X-Api-Key": SECRET, "Accept": "a"}) == ["x-api-key"]
    assert marque_authentification(None) == [] and marque_authentification({"Accept": "a"}) == []
    assert SECRET not in _tout_le_cache(app)


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
