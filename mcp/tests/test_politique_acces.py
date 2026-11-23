"""#211 lot B : politique d'accès par service (intervalle, plafond/jour, concurrence, référence), appliquée à tous
les hôtes externes depuis un seul point d'entrée, avec provenance de chaque valeur."""

from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import respx

from genealogiste_mcp import archives, politique_acces, server
from genealogiste_mcp.budget import PlafondJour
from genealogiste_mcp.cache import Cache
from genealogiste_mcp.config import Config, load_config
from genealogiste_mcp.http import HttpClient, SourceError
from genealogiste_mcp.politique_acces import PROVENANCES, SERVICES, Entree, PolitiqueAcces

SRC = Path(politique_acces.__file__).parent


def _cfg(**kw) -> Config:
    return Config(data_dir=Path("donnees"), cache_path=Path("cache.sqlite"), **kw)


def _hotes_sources() -> dict[str, str]:
    """Hôtes réellement interrogés : constantes URL des modules qui appellent le client HTTP (sources/, contexte/,
    ark.py) et URL par défaut des fichiers COG (config). Dérivé du code, pas d'une liste tenue à la main."""
    out: dict[str, str] = {}
    fichiers = sorted((SRC / "sources").rglob("*.py")) + sorted((SRC / "contexte").rglob("*.py")) + [SRC / "ark.py"]
    for f in fichiers:
        texte = f.read_text(encoding="utf-8")
        if f.name != "ark.py" and not re.search(r"\bhttp\.(get|post|request)\(", texte):
            continue  # module de liens (aucune requête émise)
        for noeud in ast.parse(texte).body:
            if (isinstance(noeud, ast.Assign) and isinstance(noeud.value, ast.Constant)
                    and isinstance(noeud.value.value, str) and noeud.value.value.startswith("http")):
                out[urlsplit(noeud.value.value).hostname] = f.name
    for champ in ("cog_mvt_url", "cog_communes_url"):
        out[urlsplit(getattr(Config, champ)).hostname] = "config.py"
    from genealogiste_mcp.contexte import (
        services as services_contexte,  # outils de contexte : hôtes du référentiel
    )
    for hote in services_contexte.tous_les_hotes():
        out.setdefault(hote, "sources_contexte.json")
    return out


def test_hotes_derives_couvrent_les_sources():
    hotes = _hotes_sources()
    assert {"query.wikidata.org", "gallica.bnf.fr", "deces.matchid.io", "api.wikitree.com", "geo.api.gouv.fr",
            "archivesdepartementales.lenord.fr", "n2t.net", "www.insee.fr"} <= set(hotes)


def test_table_complete_pour_chaque_hote_interroge():
    """Chaque hôte interrogé par le plugin est déclaré : table des services ou référentiel des archives."""
    p = PolitiqueAcces.depuis_config(_cfg())
    manquants = {h: f for h, f in _hotes_sources().items() if not p.politique(h).service}
    assert not manquants, f"hôtes sans politique déclarée : {manquants}"


# Hôtes fixes contactés par chaque outil de collecte du budget d'enquête (#211, lot C). Les hôtes dynamiques
# (visionneuse ou manifeste IIIF d'un service, résolution ARK) sont couverts par le référentiel et ark.NAANS.
HOTES_OUTILS = {
    "archive_image": {"archivesdepartementales.lenord.fr", "gallica.bnf.fr"},
    "archives_naviguer": {"archivesdepartementales.lenord.fr", "gallica.bnf.fr"},
    "archives_planche": {"archivesdepartementales.lenord.fr", "gallica.bnf.fr"},
    "archives_registres": {"archivesdepartementales.lenord.fr"},
    "piece_archiver": {"archivesdepartementales.lenord.fr", "gallica.bnf.fr"},
    "ark_resoudre": {"n2t.net"},
    "gallica_alto": {"gallica.bnf.fr"}, "gallica_recherche": {"gallica.bnf.fr"},
    "gallica_recherche_document": {"gallica.bnf.fr"}, "gallica_texte": {"gallica.bnf.fr"},
    "geo_commune": {"geo.api.gouv.fr"}, "geo_historique": {"www.insee.fr"},
    "lieu_historique": {"www.insee.fr", "geo.api.gouv.fr", "api.insee.fr", "data.geopf.fr", "query.wikidata.org"},
    "matchid_recherche": {"deces.matchid.io"},
    "recherche_multi": {"deces.matchid.io", "api.wikitree.com", "gallica.bnf.fr", "query.wikidata.org"},
    "wikidata_personne": {"query.wikidata.org"}, "wikidata_sparql": {"query.wikidata.org"},
    "contexte_bibliographie": {"api.archives-ouvertes.fr", "api.isidore.science", "www.sudoc.abes.fr",
                               "catalogue.bnf.fr", "theses.fr", "api.crossref.org"},
    **{f"wikitree_{n}": {"api.wikitree.com"} for n in ("ascendants", "descendants", "personne", "profil",
                                                        "recherche")},
}


def test_politique_couvre_les_outils_du_budget_d_enquete():
    from genealogiste_mcp import ark, outils

    assert set(HOTES_OUTILS) == set(outils.BUDGET_ENQUETE), "outil de collecte ajouté : déclarer ses hôtes"
    p = PolitiqueAcces.depuis_config(_cfg())
    archives.services()  # complète ark.NAANS depuis le référentiel
    hotes = set().union(*HOTES_OUTILS.values()) | {v["hote"] for v in ark.NAANS.values()}
    assert set().union(*HOTES_OUTILS.values()) <= set(_hotes_sources())
    manquants = sorted(h for h in hotes if not p.politique(h).service)
    assert not manquants, f"hôtes sans politique déclarée : {manquants}"


def test_hote_inconnu_tombe_sur_un_defaut_explicite():
    p = PolitiqueAcces.depuis_config(_cfg(debit_defaut=1.5, plafond_jour_defaut=1000))
    pol = p.politique("iiif.inconnu.example")
    assert pol.service == "" and pol.categorie == "autre"
    assert pol.intervalle == 1.5 and pol.plafond_jour == 1000 and pol.concurrence == 1
    assert set(pol.provenance.values()) == {"defaut"}
    assert pol.reference == "" and pol.releve_le == ""


def test_aucune_valeur_sourcee_sans_reference_ni_date():
    for hote, e in SERVICES.items():
        assert e.provenance_intervalle in PROVENANCES and e.provenance_plafond in PROVENANCES
        sourcees = "sourcee" in (e.provenance_intervalle, e.provenance_plafond, e.provenance_concurrence)
        if sourcees or e.reference:
            assert e.reference.startswith("https://") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.releve_le), hote
        if e.releve_le:
            date.fromisoformat(e.releve_le)
        assert e.concurrence >= 1


def test_entree_sourcee_sans_reference_refusee():
    with pytest.raises(ValueError, match="reference"):
        Entree("Service", intervalle=1.0, provenance_intervalle="sourcee")
    with pytest.raises(ValueError, match="releve_le"):
        Entree("Service", intervalle=1.0, provenance_intervalle="sourcee", reference="https://exemple.org/cgu")
    Entree("Service", intervalle=1.0, provenance_intervalle="sourcee", reference="https://exemple.org/cgu",
           releve_le="2026-11-17")


def test_valeurs_historiques_reprises_telles_quelles():
    p = PolitiqueAcces.depuis_config(_cfg())
    attendu = {"deces.matchid.io": 1.0, "api.wikitree.com": 1.0, "gallica.bnf.fr": 1.0, "query.wikidata.org": 1.0,
               "geo.api.gouv.fr": 0.1}
    sourcees = {"deces.matchid.io", "geo.api.gouv.fr"}  # #119 : valeur historique égale à la limite publiée
    for hote, v in attendu.items():
        pol = p.politique(hote)
        assert pol.intervalle == v, hote
        assert pol.provenance["intervalle"] == ("sourcee" if hote in sourcees else "historique"), hote


def test_intervalles_sources_119():
    """Seules les valeurs publiées par le service sont « sourcee », avec la page citée et sa date de relevé
    (docs/acces-machine-archives.md). Plafonds et concurrences restent des défauts du plugin."""
    m, g = SERVICES["deces.matchid.io"], SERVICES["geo.api.gouv.fr"]
    assert (m.reference, m.releve_le) == ("https://matchid.io/link-api", "2026-11-18")
    assert "une requête par seconde" in m.limites_documentees
    assert (g.reference, g.releve_le) == ("https://guides.data.gouv.fr/foire-aux-questions", "2026-11-18")
    assert "10 requêtes par seconde" in g.limites_documentees and "contradictoires" in g.limites_documentees
    for e in SERVICES.values():
        assert e.provenance_plafond == "defaut" and e.provenance_concurrence == "defaut", e.service


def test_intervalle_anom_issu_du_crawl_delay():
    s = next(x for x in archives.services() if x["code"] == "ANOM")
    assert s["intervalle_requetes"] == 5 and "https://recherche-anom.culture.gouv.fr/robots.txt" in s["references"]
    pol = PolitiqueAcces.depuis_config(_cfg()).politique("recherche-anom.culture.gouv.fr")
    assert pol.intervalle == 5.0 and pol.provenance["intervalle"] == "referentiel"


def test_referentiel_reste_la_source_des_archives(monkeypatch):
    monkeypatch.setattr(archives, "intervalles", lambda: {"archives.ad99.fr": 3.0, "gallica.bnf.fr": 5.0})
    monkeypatch.setattr(archives, "hotes", lambda: frozenset({"archives.ad99.fr"}))
    p = PolitiqueAcces.depuis_config(_cfg(plafond_jour_archives=300, plafond_jour_defaut=50))
    ad = p.politique("archives.ad99.fr")
    assert ad.intervalle == 3.0 and ad.provenance["intervalle"] == "referentiel"
    assert ad.categorie == "archives" and ad.plafond_jour == 300
    assert ad.variable_plafond == "GENEALOGISTE_PLAFOND_JOUR_ARCHIVES"
    sous = p.politique("vues.archives.ad99.fr")  # sous-domaine : même catégorie (plafond), intervalle par défaut
    assert sous.categorie == "archives" and sous.plafond_jour == 300
    g = p.politique("gallica.bnf.fr")
    assert g.intervalle == 5.0 and g.provenance["intervalle"] == "referentiel"  # référentiel > valeur codée
    assert g.plafond_jour == 50 and g.variable_plafond == "GENEALOGISTE_PLAFOND_JOUR_DEFAUT"


def test_surcharges_environnement(monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_DEBITS", "gallica.bnf.fr=4")
    monkeypatch.setenv("GENEALOGISTE_PLAFONDS_JOUR", "api.wikitree.com=20, Gallica.bnf.fr=0")
    monkeypatch.setenv("GENEALOGISTE_PLAFOND_JOUR_DEFAUT", "250")
    cfg = load_config()
    assert cfg.plafond_jour_defaut == 250
    assert cfg.plafonds_jour == {"api.wikitree.com": 20, "gallica.bnf.fr": 0}
    p = PolitiqueAcces.depuis_config(cfg)
    g = p.politique("gallica.bnf.fr")
    assert g.intervalle == 4.0 and g.provenance["intervalle"] == "environnement"
    assert g.plafond_jour == 0 and g.provenance["plafond_jour"] == "environnement"
    w = p.politique("api.wikitree.com")
    assert w.plafond_jour == 20 and w.variable_plafond == "GENEALOGISTE_PLAFONDS_JOUR"
    assert p.politique("deces.matchid.io").plafond_jour == 250


def test_surcharges_mal_formees(monkeypatch):
    for var, valeur in (("GENEALOGISTE_PLAFONDS_JOUR", "a.fr"), ("GENEALOGISTE_PLAFONDS_JOUR", "a.fr=-2"),
                        ("GENEALOGISTE_PLAFOND_JOUR_DEFAUT", "-1")):
        monkeypatch.setenv(var, valeur)
        with pytest.raises(ValueError, match=var):
            load_config()
        monkeypatch.delenv(var)


def test_ancienne_variable_archives_honoree(monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_PLAFOND_JOUR_ARCHIVES", "7")
    cfg = load_config()
    assert cfg.plafond_jour_archives == 7 and cfg.plafond_jour_defaut == 1000
    p = PolitiqueAcces.depuis_config(cfg)
    assert p.politique("archivesdepartementales.lenord.fr").plafond_jour == 7
    assert p.politique("deces.matchid.io").plafond_jour == 1000


def test_plafond_applique_a_un_hote_d_api(tmp_path):
    jour = [date(2026, 11, 17)]
    pol = PolitiqueAcces.depuis_config(_cfg(plafond_jour_defaut=2))
    with respx.mock(assert_all_called=False) as routes:
        api = routes.get(url__startswith="https://deces.matchid.io/").respond(200, json={})
        http = HttpClient(Cache(tmp_path / "c.sqlite"), "test", politique=pol, sleeper=lambda s: None,
                          plafond=PlafondJour(Cache(tmp_path / "c.sqlite"), politique=pol, jour=lambda: jour[0]))
        http.get("https://deces.matchid.io/a")
        http.get("https://deces.matchid.io/b", use_cache=False)
        with pytest.raises(SourceError, match="GENEALOGISTE_PLAFOND_JOUR_DEFAUT") as exc:
            http.get("https://deces.matchid.io/c", use_cache=False)
        assert exc.value.reessayer_apres > 0 and api.call_count == 2
        http.get("https://deces.matchid.io/a")  # servi par le cache : pas de requête, pas de refus
        jour[0] = date(2026, 11, 18)
        http.get("https://deces.matchid.io/d", use_cache=False)
        assert api.call_count == 3


def test_plafond_zero_desactive(tmp_path):
    pol = PolitiqueAcces.depuis_config(_cfg(plafond_jour_defaut=0))
    with respx.mock() as routes:
        api = routes.get(url__startswith="https://deces.matchid.io/").respond(200, json={})
        http = HttpClient(Cache(tmp_path / "c.sqlite"), "test", politique=pol, sleeper=lambda s: None,
                          plafond=PlafondJour(Cache(tmp_path / "c.sqlite"), politique=pol))
        for i in range(5):
            http.get(f"https://deces.matchid.io/{i}", use_cache=False)
        assert api.call_count == 5


def test_client_lit_l_intervalle_dans_la_table(config):
    config.debits = {"exemple.org": 9.0}
    a = server.App(config, sleeper=lambda s: None)
    assert a.http.politique is not None
    assert a.http.intervalle("query.wikidata.org") == a.http.politique.politique("query.wikidata.org").intervalle
    assert a.http.intervalle("exemple.org") == 9.0
    assert a.http.plafond.politique is a.http.politique


def test_diagnostic_expose_la_politique(app):
    ctl = next(c for c in server.diagnostic(reseau=False)["controles"] if c["controle"] == "politique_acces")
    hotes = {h["hote"]: h for h in ctl["services"]}
    assert hotes["query.wikidata.org"]["provenance"]["intervalle"] == "historique"
    assert hotes["query.wikidata.org"]["reference"]
    assert ctl["defauts"]["archives"]["plafond_jour"] == app.config.plafond_jour_archives
    assert ctl["defauts"]["autre"]["plafond_jour"] == app.config.plafond_jour_defaut


def test_archives_service_expose_la_politique(app):
    r = server.archives_service(code="AD59")
    pol = r["politique_acces"]["archivesdepartementales.lenord.fr"]
    assert pol["categorie"] == "archives" and pol["plafond_jour"] == app.config.plafond_jour_archives
    assert set(pol["provenance"]) == {"intervalle", "plafond_jour", "concurrence"}


def test_doc_securite_liste_chaque_service():
    doc = (Path(__file__).parents[2] / "docs" / "securite.md").read_text(encoding="utf-8")
    section = doc.split("## Politique d'accès par service", 1)[1].split("\n## ", 1)[0]
    for hote, e in SERVICES.items():
        assert f"`{hote}`" in section, hote
        if e.reference:
            assert e.reference in section and e.releve_le in section, hote
