"""Recherche AD59 sur HTML serveur : fixtures synthétiques issues du relevé public."""

import re

import httpx
import pytest
import respx

from genealogiste_mcp.sources import registres

URL = "https://archivesdepartementales.lenord.fr/search/results"


@respx.mock
def test_registre_trouve_dans_html_sans_resoudre_ni_telecharger(app, fixtures):
    html = (fixtures / "ad59-recherche-positive.html").read_text()
    route = respx.get(URL).respond(200, text=html)
    result = registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1860)
    assert "erreur" not in result, result
    assert result["resultats"] == [{"titre": "COMMUNE-FICTIVE / NMD [1840-1870]",
        "cote": "5 Mi FICTIF R 001", "ark": "ark:/33518/registrefictif121",
        "url": "https://archivesdepartementales.lenord.fr/ark:/33518/registrefictif121",
        "bornes": [1840, 1870], "nb_vues": 321}]
    assert result["total"] == result["nb_renvoyes"] == 1
    assert result["page"] == 1 and result["page_suivante"] is None and result["fin"] is True
    assert result["depuis_cache"] is False
    assert route.call_count == 1 and len(respx.calls) == 1
    assert len(app.journal.entries()) == 1
    assert app.journal.entries()[0]["id"] == result["journal"]


@respx.mock
def test_html_trop_imbrique_renvoie_une_erreur_sans_crash(app, fixtures):
    html = (fixtures / "ad59-recherche-positive.html").read_text()
    html = html.replace('<body id="display-results">', '<body id="display-results">' + '<div>' * 1500)
    respx.get(URL).respond(200, text=html)
    result = registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1860)
    assert "erreur" in result and "profond" in result["erreur"].lower()
    assert len(app.journal.entries(statut="erreur")) == 1


@respx.mock
def test_negatif_explicite_et_cache_traces_par_invocation(app, fixtures):
    html = (fixtures / "ad59-recherche-negative.html").read_text()
    route = respx.get(URL).respond(200, text=html)
    for cached in (False, True):
        result = registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1200, personne="I42")
        assert "erreur" not in result, result
        assert result["resultats"] == [] and result["total"] == 0
        assert result["fin"] is True and result["page_suivante"] is None
        assert "absence générale" in result["recherche_negative"]
        assert result["depuis_cache"] is cached
        entry = app.journal.entries()[-1]
        assert entry["id"] == result["journal"] and entry["statut"] == "negatif"
        assert bool(entry["cache"]) is cached and entry["personne"] == "I42"
    assert len(app.journal.entries()) == 2 and route.call_count == 1
    assert "I42" not in str(route.calls[0].request.url)
    assert route.calls[0].request.content == b""


@respx.mock
def test_dates_et_nombre_de_vues_absents_restent_inconnus(app, fixtures):
    html = (fixtures / "ad59-recherche-positive.html").read_text()
    html = html.replace('<p><span>1840-1870</span></p>', '<p><span>Date non précisée</span></p>')
    html = re.sub(r'<p class="info-list-picture">.*?</p>', '', html, flags=re.S)
    respx.get(URL).respond(200, text=html)
    result = registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1860)
    assert "erreur" not in result, result
    assert result["resultats"][0]["bornes"] is None
    assert result["resultats"][0]["nb_vues"] is None
    assert "1840-1870" in result["resultats"][0]["titre"]  # aucune inférence depuis le titre


@pytest.mark.parametrize("type_acte,facette", [("", None), ("NMD", None), ("N", "Naissances"),
                                             ("M", "Mariages"), ("D", "Décès")])
@respx.mock
def test_parametres_get_observes_et_normalisation_commune(app, fixtures, type_acte, facette):
    route = respx.get(URL).respond(200, text=(fixtures / "ad59-recherche-positive.html").read_text())
    result = registres.rechercher(app.sctx, " ad59 ", "  Commune-Fictivé  ", 1860, type_acte=type_acte)
    assert "erreur" not in result, result
    query = dict(route.calls[0].request.url.params)
    attendu = {"formUuid": "dc4e871d-0b62-41fb-9921-5ded573781b8", "sort": "date_asc", "mode": "list",
               "facet_media": "image", "0-controlledAccessGeographicName[]": "COMMUNE-FICTIVE",
               "2-date": "1860", "page": "1"}
    if facette:
        attendu["facet_typology"] = facette
    assert query == attendu


@respx.mock
def test_pagination_explicitement_demandee_ne_feuillette_pas(app, fixtures):
    html = (fixtures / "ad59-recherche-positive.html").read_text()
    premiere = html.replace('max="1"', 'max="2"').replace('1 résultat', '21 résultats')
    # Vingt copies synthétiques sur la première page ; une sur la dernière, selon le défaut observé de 20.
    debut = premiere.index('<li class="element-list">')
    fin = premiere.index('</ol>', debut)
    bloc = premiere[debut:fin]
    premiere = premiere[:debut] + ''.join(bloc.replace('registrefictif121', f'registrefictif{i}')
                                        for i in range(1, 21)) + premiere[fin:]
    seconde = html.replace('value="1" min="1" max="1"', 'value="2" min="1" max="2"')
    seconde = seconde.replace('1 résultat', '21 résultats')
    route = respx.get(URL).mock(side_effect=[httpx.Response(200, text=premiere), httpx.Response(200, text=seconde)])
    result = registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1860)
    assert "erreur" not in result, result
    assert result["total"] == 21 and result["nb_renvoyes"] == 20
    assert result["page"] == 1 and result["page_suivante"] == 2 and result["fin"] is False
    assert route.call_count == 1
    result = registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1860, page=2)
    assert "erreur" not in result, result
    assert result["total"] == 21 and result["nb_renvoyes"] == 1
    assert result["page"] == 2 and result["page_suivante"] is None and result["fin"] is True
    assert route.call_count == 2 and route.calls[1].request.url.params["page"] == "2"


@pytest.mark.parametrize("modification", ["liste_absente", "liste_vide", "negatif_non_explicite", "titre_absent",
                                          "cote_absente", "ark_de_vue", "tiers", "page_incoherente", "total_absent"])
@respx.mock
def test_format_inattendu_est_une_erreur_pas_un_negatif(app, fixtures, modification):
    html = (fixtures / "ad59-recherche-positive.html").read_text()
    if modification == "liste_absente":
        html = '<html><body>Veuillez vous connecter</body></html>'
    elif modification == "liste_vide":
        html = re.sub(r'<li class="element-list">.*?</ol>', '</ol>', html, flags=re.S)
    elif modification == "negatif_non_explicite":
        html = (fixtures / "ad59-recherche-negative.html").read_text().replace('Aucun résultat ne correspond à votre requête', 'Réponse indisponible')
    elif modification == "titre_absent":
        html = html.replace('<h2>', '<h4>').replace('</h2>', '</h4>')
    elif modification == "cote_absente":
        html = html.replace('referenceCodes', 'autreFormat')
    elif modification == "ark_de_vue":
        html = html.replace('href="https://archivesdepartementales.lenord.fr/ark:/33518/registrefictif121"',
                            'href="https://archivesdepartementales.lenord.fr/ark:/33518/registrefictif121/11111111-1111-4111-8111-111111111111"')
    elif modification == "tiers":
        html = html.replace('href="https://archivesdepartementales.lenord.fr/ark:', 'href="https://tiers.example/ark:')
    elif modification == "page_incoherente":
        html = html.replace('value="1" min="1" max="1"', 'value="2" min="1" max="2"')
    else:
        html = html.replace('class="result"', 'class="autreFormat"')
    respx.get(URL).respond(200, text=html)
    result = registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1860)
    assert "erreur" in result and "recherche_negative" not in result
    assert len(app.journal.entries(statut="erreur")) == 1


@pytest.mark.parametrize("parametres", [{"service": "AD62"}, {"commune": " "}, {"commune": "X" * 201},
                                       {"annee": 0}, {"annee": 10000}, {"annee": True}, {"annee": "1840-1870"},
                                       {"page": 0}, {"page": True}, {"type_acte": "TD"}, {"type_acte": "B"}])
@respx.mock
def test_entrees_non_qualifiees_refusees_avant_http(app, parametres):
    demande = {"service": "AD59", "commune": "Commune-Fictive", "annee": 1860, **parametres}
    result = registres.rechercher(app.sctx, **demande)
    assert "erreur" in result
    assert len(respx.calls) == 0
    assert len(app.journal.entries(statut="erreur")) == 1


@pytest.mark.parametrize("panne", [429, 503, "timeout"])
@respx.mock
def test_une_seule_tentative_sans_modifier_les_autres_sources(app, panne):
    route = respx.get(URL)
    if panne == "timeout":
        route.mock(side_effect=httpx.ReadTimeout("lecture interrompue"))
    else:
        route.respond(panne, headers={"Retry-After": "12"})
    result = registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1860)
    assert "erreur" in result and result["reessayer_apres"] >= 1
    assert route.call_count == 1
    autre = respx.get("https://autre.example/source").mock(side_effect=[httpx.Response(503), httpx.Response(200, text="ok")])
    assert app.http.get("https://autre.example/source", parse="text")[0] == "ok"
    assert autre.call_count == 2


@respx.mock
def test_blocage_conserve_metadonnees_et_ne_relance_pas(app):
    route = respx.get(URL).respond(200, text='<html><title>Just a moment...</title><div id="cf-chl-widget">Défi</div></html>',
                                  headers={"Content-Type": "text/html", "cf-mitigated": "challenge"})
    for cached in (False, True):
        result = registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1860)
        assert result["statut"] == "bloque_antirobot"
        assert result["protection"] == "Cloudflare" and result["service"] == "AD59"
        assert result["url"].startswith(URL) and result["tache_manuelle"]["statut"] == "a_faire"
        assert bool(result.get("coupe_circuit")) is cached
    entries = app.journal.entries(statut="bloque_antirobot")
    assert route.call_count == 1 and len(entries) == 2
    assert entries[-1]["cache"] is True


@respx.mock
def test_negatif_page_suivante_non_qualifie_ne_prouve_pas_zero_registre(app, fixtures):
    respx.get(URL).respond(200, text=(fixtures / "ad59-recherche-negative.html").read_text())
    result = registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1860, page=2)
    assert "erreur" in result and "recherche_negative" not in result
    assert len(app.journal.entries(statut="erreur")) == 1


@pytest.mark.parametrize("modification", ["total_superieur", "pages_fantomes", "taille_contradictoire", "page_tronquee", "classe_nue", "value_nue", "max_nu"])
@respx.mock
def test_metadonnees_html_malformees_ou_contradictoires_refusees(app, fixtures, modification):
    html = (fixtures / "ad59-recherche-positive.html").read_text()
    if modification == "total_superieur":
        html = html.replace('1 résultat', '100 résultats')
    elif modification == "pages_fantomes":
        html = html.replace('max="1"', 'max="999"')
    elif modification in {"taille_contradictoire", "page_tronquee"}:
        total = 100 if modification == "taille_contradictoire" else 21
        html = html.replace('max="1"', 'max="2"').replace('1 résultat', f'{total} résultats')
    elif modification == "classe_nue":
        html = html.replace('class="result"', 'class')
    elif modification == "value_nue":
        html = html.replace('value="1"', 'value')
    else:
        html = html.replace('max="1"', 'max')
    respx.get(URL).respond(200, text=html)
    result = registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1860)
    assert "erreur" in result and "recherche_negative" not in result
    assert len(app.journal.entries(statut="erreur")) == 1
