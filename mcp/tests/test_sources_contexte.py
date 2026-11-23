"""Référentiel des services de contexte historique (#285) : schéma, activation, clés, politique d'accès,
sources_catalogue(type="contexte"), diagnostic et sondage, sans réseau."""

from __future__ import annotations

import copy
import dataclasses
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from genealogiste_mcp import diagnostic, outils, server
from genealogiste_mcp.config import load_config
from genealogiste_mcp.contexte import services
from genealogiste_mcp.contexte.modeles import NATURES
from genealogiste_mcp.politique_acces import SERVICES, PolitiqueAcces

RACINE = Path(__file__).resolve().parents[2]
SECRETS = {"GENEALOGISTE_CLE_EUROPEANA": "cle-europeana-tres-secrete",
           "GENEALOGISTE_CLE_OPENALEX": "cle-openalex-tres-secrete",
           "GENEALOGISTE_CLE_NARA": "cle-nara-tres-secrete",
           "GENEALOGISTE_CLE_APE": "cle-ape-tres-secrete",
           "GENEALOGISTE_CROSSREF_MAILTO": "chercheur.prive@exemple.fr"}
# Complément du 2026-11-23 : services livrés en « lien seulement » au départ.
LIEN_SEULEMENT = {"GALLICA", "CHRONICLING-AMERICA", "RETRONEWS", "FRANCEARCHIVES", "CASSINI-EHESS", "APE", "NARA"}


def _cfg(tmp_path, **kw):
    from genealogiste_mcp.config import Config

    return Config(data_dir=tmp_path / "d", cache_path=tmp_path / "c.sqlite", **kw)


# ------------------------------------------------------------------------------------------------- schéma


def test_referentiel_valide_et_jamais_verifie_sans_humain():
    assert services.validate() == []
    tous = services.services()
    assert len(tous) >= 25
    assert all(s["verifie_le"] == "" for s in tous)  # aucun contrôle humain consigné
    assert all(s["nature"] in NATURES for s in tous)  # aligné sur Reference.nature (#321)
    assert all(s["origine"] for s in tous)


def test_statuts_de_l_issue():
    par = {s["code"]: s for s in services.services()}
    assert {c for c, s in par.items() if s["mode"] == "lien_seulement"} == LIEN_SEULEMENT
    assert par["EUROPEANA"]["cle"] == "requise" and par["EUROPEANA"]["mode"] == "api"
    assert par["OPENALEX"]["cle"] == "facultative"
    assert par["WIKIPEDIA"]["nature"] == "tertiaire" and par["WIKIDATA"]["nature"] == "index"
    assert par["INSEE-MELODI"]["couverture"]["periode"] == {"de": 1968, "a": 2023}
    defaut = set(services.actifs_par_defaut())
    assert "EUROPEANA" not in defaut and not defaut & LIEN_SEULEMENT
    assert {"HAL", "SUDOC", "THESES-FR", "CROSSREF", "OPENALEX", "WIKIDATA"} <= defaut
    # aucune donnée de service inventée : CGU et documentation restent vides tant qu'elles ne sont pas relevées
    assert all(s["cgu"] == "" and s["documentation"] == "" for s in services.services())


@pytest.mark.parametrize("champ,valeur,attendu", [
    ("mode", "robot", "mode"),
    ("protocole", "graphql", "protocole"),
    ("nature", "primaire_presumee", "nature"),
    ("cle", "oui", "cle"),
    ("protection", "anubis", "protection"),
    ("url_api", "http://api.archives-ouvertes.fr/search/", "url_api"),
    ("couverture", {"zone": ["XX"]}, "couverture"),
    ("couverture", {"zone": ["FR"], "periode": {"de": 2000, "a": 1900}}, "periode"),
    ("site_repond_le", "hier", "site_repond_le"),
    ("protection", "cloudflare", "protégé"),
    ("variable_cle", "GENEALOGISTE_CLE_HAL", "variable_cle"),
    ("origine", "", "origine"),
])
def test_validate_refuse(monkeypatch, champ, valeur, attendu):
    base = copy.deepcopy(services.par_code("HAL"))
    base[champ] = valeur
    monkeypatch.setattr(services, "services", lambda: (base,))
    assert any(attendu in e for e in services.validate()), services.validate()


def test_validate_cle_requise_sans_variable(monkeypatch):
    s = copy.deepcopy(services.par_code("EUROPEANA"))
    s["variable_cle"] = ""
    monkeypatch.setattr(services, "services", lambda: (s,))
    assert any("variable_cle" in e for e in services.validate())


# ------------------------------------------------------------------------------------------- configuration


def test_parser_services():
    assert services.parser_services(None) is None and services.parser_services("  ") is None
    assert services.parser_services("aucun") == ()
    assert services.parser_services("hal, sudoc") == ("HAL", "SUDOC")
    choix = services.parser_services("defaut,EUROPEANA")
    assert set(choix) == set(services.actifs_par_defaut()) | {"EUROPEANA"}
    with pytest.raises(ValueError, match="GENEALOGISTE_CONTEXTE_SERVICES=.*INCONNU"):
        services.parser_services("HAL,INCONNU")


def test_mailto_vide_par_defaut_et_jamais_cite(monkeypatch):
    assert load_config().crossref_mailto == ""
    assert services.parser_mailto("a.b@exemple.fr") == "a.b@exemple.fr"
    for mauvais in ("pas-une-adresse", "a b@exemple.fr", "x@y", "é@exemple.fr"):
        with pytest.raises(ValueError, match="GENEALOGISTE_CROSSREF_MAILTO=<valeur masquée>") as exc:
            services.parser_mailto(mauvais)
        assert mauvais not in str(exc.value)


def test_config_charge_cles_et_selection_sans_les_exposer(monkeypatch):
    for var, val in SECRETS.items():
        monkeypatch.setenv(var, val)
    monkeypatch.setenv("GENEALOGISTE_CONTEXTE_SERVICES", "defaut,EUROPEANA")
    cfg = load_config()
    assert cfg.cles_contexte == {"EUROPEANA": SECRETS["GENEALOGISTE_CLE_EUROPEANA"],
                                 "OPENALEX": SECRETS["GENEALOGISTE_CLE_OPENALEX"],
                                 "NARA": SECRETS["GENEALOGISTE_CLE_NARA"], "APE": SECRETS["GENEALOGISTE_CLE_APE"]}
    assert cfg.crossref_mailto == SECRETS["GENEALOGISTE_CROSSREF_MAILTO"]
    assert "EUROPEANA" in cfg.contexte_services
    texte = repr(cfg)
    assert not any(v in texte for v in SECRETS.values())
    assert {f.name for f in dataclasses.fields(cfg) if not f.repr} >= {"cles_contexte", "crossref_mailto"}


def test_variable_de_services_inconnue_refusee_au_chargement(monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_CONTEXTE_SERVICES", "HAL,NEXISTEPAS")
    with pytest.raises(ValueError, match="NEXISTEPAS"):
        load_config()


# --------------------------------------------------------------------------------------- interrogeabilité


def test_interrogeable_par_defaut(tmp_path):
    cfg = _cfg(tmp_path)
    e = services.etat("hal", cfg)
    assert e.interrogeable and e.actif and e.motif == "" and e.cle == "sans_objet"
    assert services.refus("HAL", cfg) is None
    o = services.etat("OPENALEX", cfg)  # clé facultative absente : interrogeable
    assert o.interrogeable and o.cle == "absente"


@pytest.mark.parametrize("code,kw,mot", [
    ("EUROPEANA", {}, "désactivé"),
    ("EUROPEANA", {"contexte_services": ("EUROPEANA",)}, "GENEALOGISTE_CLE_EUROPEANA"),
    ("HAL", {"contexte_services": ()}, "désactivé"),
    ("GALLICA", {"contexte_services": ("GALLICA",)}, "lien_seulement"),
    ("NARA", {"contexte_services": ("NARA",), "cles_contexte": {"NARA": "x"}}, "lien_seulement"),
    ("RETRONEWS", {}, "jamais interrogé"),
    ("HAL", {"offline": True}, "hors ligne"),
    ("INCONNU", {}, "inconnu"),
])
def test_refus_sans_requete_et_motif(tmp_path, code, kw, mot):
    cfg = _cfg(tmp_path, **kw)
    r = services.refus(code, cfg)
    assert r is not None and r["interrogeable"] is False and r["requetes_emises"] == 0
    assert mot in r["erreur"]
    assert "Aucune requête" in r["consigne"]


def test_motif_gallica_ne_dit_pas_jamais_interroge(tmp_path):
    """#325 (reste de #323) : presse_recherche interroge Gallica par le client existant ; le motif de refus rendu
    aux outils de contexte ne prétend donc plus « jamais interrogé par le plugin ». La décision ne change pas."""
    cfg = _cfg(tmp_path, contexte_services=("GALLICA",))
    r = services.refus("GALLICA", cfg)
    assert r is not None and r["interrogeable"] is False and r["requetes_emises"] == 0  # toujours refusé
    assert "jamais interrogé par le plugin" not in r["erreur"]
    assert "presse_recherche" in r["erreur"] and "lien_seulement" in r["erreur"]
    assert set(services.INTERROGE_HORS_REFERENTIEL) == {"GALLICA"}
    for code in ("RETRONEWS", "CHRONICLING-AMERICA", "NARA", "APE", "FRANCEARCHIVES", "CASSINI-EHESS"):
        assert "jamais interrogé par le plugin" in services.refus(code, cfg)["erreur"]  # inchangé ailleurs


def test_cle_requise_presente_rend_interrogeable_sans_jamais_l_afficher(tmp_path):
    secret = SECRETS["GENEALOGISTE_CLE_EUROPEANA"]
    cfg = _cfg(tmp_path, contexte_services=("EUROPEANA",), cles_contexte={"EUROPEANA": secret})
    e = services.etat("EUROPEANA", cfg)
    assert e.interrogeable and e.cle == "presente"
    assert services.cle("europeana", cfg) == secret
    assert secret not in json.dumps(e.en_dict()) and secret not in json.dumps(services.resume(
        services.par_code("EUROPEANA"), cfg))
    url = f"https://api.europeana.eu/record/v2/search.json?wskey={secret}&query=Lens"
    assert services.masquer_cles(url, cfg) == "https://api.europeana.eu/record/v2/search.json?wskey=***&query=Lens"


def test_url_autorisee_seulement_vers_les_hotes_du_service():
    assert services.url_autorisee("HAL", "https://api.archives-ouvertes.fr/search/?q=houillères")
    assert not services.url_autorisee("HAL", "https://api.crossref.org/works")
    assert not services.url_autorisee("HAL", "http://api.archives-ouvertes.fr/search/")
    assert not services.url_autorisee("RETRONEWS", "https://www.retronews.fr/")  # aucun point d'accès machine
    assert not services.url_autorisee("INCONNU", "https://api.archives-ouvertes.fr/")


# ---------------------------------------------------------------------------------------- politique réseau


def test_chaque_hote_declare_avec_une_limite(tmp_path):
    cfg = _cfg(tmp_path)
    pol = PolitiqueAcces.depuis_config(cfg)
    hotes = services.tous_les_hotes()
    assert hotes and len(hotes) == len({h for s in services.services() for h in services.hotes(s)})
    for h in hotes:
        p = pol.politique(h)
        assert p.intervalle > 0, h
        assert p.plafond_jour == cfg.plafond_jour_defaut, h
        if h in SERVICES:  # Gallica, Wikidata : l'entrée historique reste prioritaire
            assert p.service == SERVICES[h].service
        else:
            assert p.categorie == "contexte" and "(contexte)" in p.service, h
            assert p.provenance == {"intervalle": "defaut", "plafond_jour": "defaut", "concurrence": "defaut"}
    assert {t["hote"] for t in pol.table()} >= set(hotes)
    assert "contexte" in pol.defauts()


def test_surcharges_par_hote(tmp_path):
    cfg = _cfg(tmp_path, plafonds_jour={"api.archives-ouvertes.fr": 50}, debits={"api.archives-ouvertes.fr": 3.0})
    p = PolitiqueAcces.depuis_config(cfg).politique("api.archives-ouvertes.fr")
    assert (p.plafond_jour, p.intervalle) == (50, 3.0)
    assert p.provenance["plafond_jour"] == p.provenance["intervalle"] == "environnement"


def test_client_http_applique_l_intervalle(app):
    assert app.http.intervalle("api.archives-ouvertes.fr") == app.config.debit_defaut > 0


# -------------------------------------------------------------------------------------- sources_catalogue


def test_sources_catalogue_type_contexte(app):
    r = server.sources_catalogue(type="contexte")
    assert r["totaux"]["contexte"] == len(services.services()) == len(r["contexte"])
    par = {s["code"]: s for s in r["contexte"]}
    assert par["HAL"]["interrogeable"] and par["HAL"]["actif"]
    assert not par["EUROPEANA"]["interrogeable"] and "désactivé" in par["EUROPEANA"]["motif"]
    assert par["EUROPEANA"]["etat_cle"] == "absente"
    assert all(not par[c]["interrogeable"] for c in LIEN_SEULEMENT)
    assert "erreur" in server.sources_catalogue(type="contexte", departement="59")
    # compatibilité : catalogue complet et filtres inchangés, contexte ajouté au catalogue complet seulement
    tout = server.sources_catalogue()
    assert tout["totaux"]["contexte"] == len(services.services()) and tout["archives"] and tout["sites_tiers"]
    assert server.sources_catalogue(departement="59")["contexte"] == []
    assert server.sources_catalogue(type="forum")["types_contexte"] == ["contexte"]


def test_sources_catalogue_reste_une_lecture():
    assert outils.OUTILS["sources_catalogue"] == (outils.LECTURE, outils.LECTURE)
    assert "sources_catalogue" not in outils.GARDE_VIVANTS


# ------------------------------------------------------------------------------- secrets : jamais exposés


def test_cles_jamais_renvoyees_journalisees_ni_ecrites(app_famille, monkeypatch):
    a = app_famille
    a.config.cles_contexte = {"EUROPEANA": SECRETS["GENEALOGISTE_CLE_EUROPEANA"],
                              "OPENALEX": SECRETS["GENEALOGISTE_CLE_OPENALEX"],
                              "NARA": SECRETS["GENEALOGISTE_CLE_NARA"], "APE": SECRETS["GENEALOGISTE_CLE_APE"]}
    a.config.crossref_mailto = SECRETS["GENEALOGISTE_CROSSREF_MAILTO"]
    a.config.contexte_services = (*services.actifs_par_defaut(), "EUROPEANA")
    for var, val in SECRETS.items():
        monkeypatch.setenv(var, val)
    sorties = [server.sources_catalogue(), server.sources_catalogue(type="contexte"),
               server.diagnostic(reseau=False), server.arbre_exporter(format="gedcom7"),
               services.refus("NARA", a.config), services.description(a.config)]
    texte = json.dumps(sorties, ensure_ascii=False, default=str)
    for v in SECRETS.values():
        assert v not in texte
    # rien d'écrit : journal, exports, notes, propositions (répertoire de données entier) et cache
    for f in [*a.config.data_dir.rglob("*"), Path(a.config.cache_path)]:
        if f.is_file() and ".git" not in f.parts:
            contenu = f.read_bytes()
            for v in SECRETS.values():
                assert v.encode() not in contenu, f


def test_diagnostic_decrit_les_services_sans_les_cles(app):
    app.config.contexte_services = ("HAL", "EUROPEANA")
    app.config.cles_contexte = {"OPENALEX": SECRETS["GENEALOGISTE_CLE_OPENALEX"]}
    res = server.diagnostic(reseau=False)
    c = next(x for x in res["controles"] if x["controle"] == "services_contexte")
    assert c["etat"] == "attention" and c["remede"]
    assert c["actifs"] == ["HAL", "EUROPEANA"] and c["interrogeables"] == ["HAL"]
    assert c["cles"]["GENEALOGISTE_CLE_OPENALEX"] == "définie" and c["cles"]["GENEALOGISTE_CLE_EUROPEANA"] == "absente"
    assert c["cles_sans_activation"] == ["OPENALEX"] and c["crossref_mailto"] == "absent"
    assert SECRETS["GENEALOGISTE_CLE_OPENALEX"] not in json.dumps(res, ensure_ascii=False)


def test_diagnostic_par_defaut_ok(app):
    c = next(x for x in diagnostic.controles_locaux(app, None, app.config) if x["controle"] == "services_contexte")
    assert c["etat"] == "ok" and c["selection"] == "défaut du référentiel"


# ------------------------------------------------------------------------------------------------ sondage


def _verifier():
    script = RACINE / "mcp" / "scripts" / "verifier_archives.py"
    spec = importlib.util.spec_from_file_location("verifier_archives_ctx", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("code,status,verdict", [
    ("HAL", 200, "OK"), ("HAL", 500, "KO"),
    ("GALLICA", 403, "AVERT"), ("CASSINI-EHESS", 500, "AVERT"), ("EUROPEANA", 400, "AVERT"),
])
def test_sondage_contexte(code, status, verdict):
    v = _verifier()
    vus = []

    def repondre(request):
        vus.append(str(request.url))
        assert not request.url.query or "wskey" not in str(request.url)  # jamais de clé envoyée
        return httpx.Response(status)

    s = services.par_code(code)
    with httpx.Client(transport=httpx.MockTransport(repondre)) as client:
        resultat, _detail, url = v.sonder_contexte(client, s)
    assert resultat == verdict and url == (s.get("url_sonde") or s["url_api"] or s["site"])
    assert vus and all(u.startswith(url.split("?")[0]) for u in vus)


def test_url_de_sondage_sur_l_hote_du_service(monkeypatch):
    assert services.url_de_sondage(services.par_code("PERSEE")) == "https://oai.persee.fr/oai?verb=Identify"
    assert services.url_de_sondage(services.par_code("HAL")) == "https://api.archives-ouvertes.fr/search/"
    s = copy.deepcopy(services.par_code("PERSEE"))
    s["url_sonde"] = "https://ailleurs.example/oai?verb=Identify"
    monkeypatch.setattr(services, "services", lambda: (s,))
    assert any("url_sonde" in e for e in services.validate())


# -------------------------------------------------------------------------------------------- documentation


def test_documentation_et_env_exemple():
    doc = (RACINE / "docs" / "contexte-historique.md").read_text(encoding="utf-8")
    section = doc.split("## Services de contexte", 1)[1].split("\n## ", 1)[0]
    for s in services.services():
        assert f"`{s['code']}`" in section, s["code"]
    env = (RACINE / ".env.example").read_text(encoding="utf-8")
    for var in (*services.VARIABLES_CLE.values(), services.VARIABLE_SERVICES, services.VARIABLE_MAILTO):
        assert var in section and var in env, var
    assert "GENEALOGISTE_CROSSREF_MAILTO=\n" in env  # aucune adresse par défaut
    securite = (RACINE / "docs" / "securite.md").read_text(encoding="utf-8")
    pol = securite.split("## Politique d'accès par service", 1)[1].split("\n## ", 1)[0]
    for h in services.tous_les_hotes():
        assert f"`{h}`" in pol, h


@pytest.mark.parametrize("status,sortie", [(200, 0), (500, 1)])
def test_verifier_archives_sonde_les_services_de_contexte(monkeypatch, capsys, status, sortie):
    v = _verifier()
    creer_client = httpx.Client
    contenu = services.PATH.read_bytes()
    monkeypatch.setattr(v.archives, "services", lambda: [])
    monkeypatch.setattr(v.archives, "validate", lambda: [])
    monkeypatch.setattr(v.sites_tiers, "sites", lambda: ())
    monkeypatch.setattr(v.sites_tiers, "validate", lambda: [])
    monkeypatch.setattr(v.httpx, "Client", lambda **kw: creer_client(
        transport=httpx.MockTransport(lambda r: httpx.Response(status)), **kw))
    assert v.main() == sortie
    lignes = [x for x in capsys.readouterr().out.splitlines() if " contexte " in x]
    assert len(lignes) == len(services.services())
    ko = {x.split()[1] for x in lignes if x.startswith("KO")}
    assert ko == (set(services.actifs_par_defaut()) if status == 500 else set())
    assert services.PATH.read_bytes() == contenu  # rapport seulement


def test_sondage_repli_get_quand_head_rend_400():
    # OAI-PMH de Persée : HEAD refusé en 400, GET de verb=Identify en 200 (sondage du 2026-11-23)
    v = _verifier()
    appels = []

    def repondre(request):
        appels.append(request.method)
        return httpx.Response(400 if request.method == "HEAD" else 200)

    with httpx.Client(transport=httpx.MockTransport(repondre)) as client:
        assert v.sonder_contexte(client, services.par_code("PERSEE"))[:2] == ("OK", "200")
    assert appels == ["HEAD", "GET"]
