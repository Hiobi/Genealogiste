"""Recherche de registres sur un service Mnesys générique (#128) : formulaire lu en ligne, fixtures synthétiques
(relevés du 18 novembre 2026), aucun réseau."""

from urllib.parse import parse_qs, urlsplit

import pytest
import respx

from genealogiste_mcp import archives, server
from genealogiste_mcp.sources import mnesys, registres

HOTE = "https://archives.exemple.fr"
FORM = "11111111-2222-4333-8444-555555555555"
TD = "66666666-7777-4888-8999-000000000000"
SERVICE = {"code": "AD99", "nom": "Archives fictives", "type": "departementales", "departement": "99",
           "site": HOTE, "ark_naan": "99999",
           "recherche_registres": {"formulaires": {"etat_civil": FORM}, "releve_le": "2026-11-18",
                                   "reference": f"{HOTE}/search/form/{FORM}"}}


@pytest.fixture
def service(monkeypatch):
    svc = {**SERVICE, "recherche_registres": {**SERVICE["recherche_registres"],
                                              "formulaires": dict(SERVICE["recherche_registres"]["formulaires"])}}
    reel = archives.by_code
    monkeypatch.setattr(archives, "by_code", lambda c: svc if (c or "").upper() == "AD99" else reel(c))
    return svc


def _form(fixtures, nom="mnesys-formulaire.html", uuid=FORM):
    return respx.get(f"{HOTE}/search/form/{uuid}").respond(200, text=(fixtures / nom).read_text())


def _resultats(fixtures, nom="mnesys-recherche-positive.html"):
    return respx.get(f"{HOTE}/search/results").respond(200, text=(fixtures / nom).read_text())


def _params(route):
    return parse_qs(urlsplit(str(route.calls[-1].request.url)).query)


# ------------------------------------------------------------------- choix de la commune

OPTIONS = ["Commune-Fictive (Département, France)", "Commune-Fictive (Département, France ; jusqu'en 1833)",
           "Lamentin (Le)", "VILLE-FICTIVE", "Lons-le-Saunier, canton", "Lons-le-Saunier, commune",
           "ARPAJON Canton", "ARPAJON Commune", "FERTE-ALAIS (LA) Commune", "VILLE-FICTIVE (Saint-Jean)", "Doublon (Département, France)",
           "Doublon (Autre, France)", "Andelys (Les) (Eure, France)", "Amfreville_La_Campagne (Eure, France)"]


@pytest.mark.parametrize("saisie,attendu", [
    ("Commune-Fictive (Département, France)", "Commune-Fictive (Département, France)"),  # valeur exacte
    ("commune fictive", "Commune-Fictive (Département, France)"),  # forme actuelle avant l'ancienne
    ("Le Lamentin", "Lamentin (Le)"),  # article inversé
    ("Ville-Fictive", "VILLE-FICTIVE"),  # sans qualificatif de paroisse
    ("Les Andelys", "Andelys (Les) (Eure, France)"),  # article et qualificatif (AD27)
    ("Amfreville-la-Campagne", "Amfreville_La_Campagne (Eure, France)"),  # tirets bas (AD27)
    ("Lons-le-Saunier", "Lons-le-Saunier, commune"),  # niveau en suffixe, commune avant canton (AD39)
    ("Arpajon", "ARPAJON Commune"),  # idem (AD91)
    ("La Ferté-Alais", "FERTE-ALAIS (LA) Commune"),  # article et niveau (AD91)
])
def test_choisir_commune(saisie, attendu):
    assert mnesys.choisir_commune(OPTIONS, saisie) == attendu


def test_commune_ambigue_ou_absente_est_une_erreur_explicite():
    with pytest.raises(ValueError, match="ambiguë"):
        mnesys.choisir_commune(OPTIONS, "Doublon")
    with pytest.raises(ValueError, match="absente.*Commune-Fictive"):
        mnesys.choisir_commune(OPTIONS, "Fictive")


@pytest.mark.parametrize("option,code", [("Naissances", "N"), ("Baptêmes", "N"), ("baptêmes - naissances", "N"),
                                         ("Mariages", "M"), ("Publications de mariage", ""), ("Sépultures", "D"),
                                         ("Décès", "D"), ("Tables décennales", "TD"), ("Table cantonale", "TD"),
                                         ("Registre de catholicité", None)])
def test_typologie(option, code):
    assert mnesys.typologie(option) == code


# ------------------------------------------------------------------- recherche

@respx.mock
def test_recherche_generique_construit_la_requete_depuis_le_formulaire(app, fixtures, service):
    form, res = _form(fixtures), _resultats(fixtures)
    r = registres.rechercher(app.sctx, "ad99", "commune fictive", 1860, "N", personne="I7")
    assert "erreur" not in r, r
    assert r["service"] == "AD99" and r["commune_service"] == "Commune-Fictive (Département, France)"
    assert r["resultats"][0]["ark"] == "ark:/99999/registrefictif121"
    assert r["resultats"][0]["url"] == f"{HOTE}/ark:/99999/registrefictif121"
    q = _params(res)
    # année seule : intervalle d'une année plutôt que la date exacte (volume pluriannuel, AD91)
    assert q["formUuid"] == [FORM] and q["3-date_begin"] == ["1860"] == q["3-date_end"] and "2-date" not in q
    assert q["0-controlledAccessGeographicName[]"] == ["Commune-Fictive (Département, France)"]
    assert q["1-controlledAccessPhysicalCharacteristic[]"] == ["Baptêmes", "Naissances"]
    assert "I7" not in str(res.calls[0].request.url)
    # formulaire en cache : une seconde recherche ne le relit pas
    registres.rechercher(app.sctx, "AD99", "Commune-Fictive", 1861)
    assert form.call_count == 1 and res.call_count == 2


@respx.mock
def test_intervalle_et_noms_sans_indice(app, fixtures, service):
    _form(fixtures, "mnesys-formulaire-periode.html")
    res = _resultats(fixtures)
    r = registres.rechercher(app.sctx, "AD99", "Le Lamentin", 1850, annee_fin=1860)
    assert "erreur" not in r, r
    q = _params(res)
    assert q["period_begin"] == ["1850"] and q["period_end"] == ["1860"]
    assert q["controlledAccessGeographicName[]"] == ["Lamentin (Le)"]
    # année seule sans champ « date » : intervalle d'une année
    registres.rechercher(app.sctx, "AD99", "Le Lamentin", 1855)
    assert _params(res)["period_begin"] == ["1855"] == _params(res)["period_end"]


@respx.mock
def test_formulaire_sans_date_filtre_localement(app, fixtures, service):
    _form(fixtures, "mnesys-formulaire-sans-date.html")
    res = _resultats(fixtures)  # registre fictif 1840-1870
    dedans = registres.rechercher(app.sctx, "AD99", "Ville-Fictive", 1860)
    assert len(dedans["resultats"]) == 1 and dedans["resultats"][0]["couvre_periode"] is True
    assert not any(k.endswith("date") for k in _params(res))
    hors = registres.rechercher(app.sctx, "AD99", "Ville-Fictive", 1900)
    assert hors["resultats"] == [] and hors["registres_hors_periode"] == 1
    assert "Aucun registre de cette page" in hors["recherche_negative"]


@respx.mock
def test_formulaire_de_tables_dedie(app, fixtures, service):
    service["recherche_registres"]["formulaires"]["tables_decennales"] = TD
    _form(fixtures, "mnesys-formulaire-sans-date.html", TD)
    res = _resultats(fixtures)
    r = registres.rechercher(app.sctx, "AD99", "Ville-Fictive", 1860, "TD")
    assert "erreur" not in r and _params(res)["formUuid"] == [TD]


@respx.mock
def test_type_sans_filtre_ou_commune_inconnue_sans_requete_de_resultats(app, fixtures, service):
    _form(fixtures, "mnesys-formulaire-sans-date.html")
    res = _resultats(fixtures)
    r = registres.rechercher(app.sctx, "AD99", "Ville-Fictive", 1860, "M")
    assert "pas de filtre pour le type M" in r["erreur"]
    r = registres.rechercher(app.sctx, "AD99", "Inconnue", 1860)
    assert "absente" in r["erreur"] and res.call_count == 0
    assert len(app.journal.entries(statut="erreur")) == 2


@respx.mock
def test_lien_hors_naan_du_service_refuse(app, fixtures, service):
    _form(fixtures)
    html = (fixtures / "mnesys-recherche-positive.html").read_text().replace("ark:/99999/", "ark:/12345/")
    respx.get(f"{HOTE}/search/results").respond(200, text=html)
    r = registres.rechercher(app.sctx, "AD99", "Commune-Fictive", 1860)
    assert "erreur" in r and "recherche_negative" not in r


def test_service_sans_recherche_liste_les_services_pris_en_charge(app):
    r = registres.rechercher(app.sctx, "AD62", "Arras", 1860)
    assert "AD59" in r["erreur"] and "AD58" in r["erreur"]


def test_referentiel_declare_des_services_mnesys_avec_recette():
    codes = registres.services_registres()
    assert {"AD14", "AD19", "AD51", "AD55", "AD58", "AD69", "AD90", "AD972"} <= set(codes)
    for c in codes[1:]:
        s = archives.by_code(c)
        assert s["recette"]["source"].startswith(s["site"].rstrip("/") + "/ark:/" + s["ark_naan"] + "/")


def test_outil_mentionne_les_services(app):
    assert "AD58" in server.archives_registres.__doc__ or "recherche_registres" in server.archives_registres.__doc__


# ------------------------------------------------------------------- matricules et successions (#112)

MAT = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
SUC = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"


@respx.mock
def test_registres_matricules_par_classe_bureau_facultatif(app, fixtures, service):
    service["recherche_registres"]["formulaires"]["matricules"] = MAT
    _form(fixtures, "mnesys-formulaire-matricules.html", MAT)
    res = _resultats(fixtures)
    r = registres.rechercher(app.sctx, "AD99", "", 1880, "RM")
    assert "erreur" not in r, r
    q = _params(res)
    assert q["formUuid"] == [MAT] and q["0-date[]"] == ["1880"]  # année en liste : paramètre multiple
    assert q["2-controlledAccessPhysicalCharacteristic[]"] == ["Registre matricule"]
    assert not any("Title" in k for k in q) and r["commune_service"] is None
    r = registres.rechercher(app.sctx, "AD99", "Ville-Fictive Nord", 1880, "RM")
    assert _params(res)["1-controlledAccessTitle[]"] == ["Ville-Fictive Nord"]


@respx.mock
def test_tables_des_successions_par_bureau(app, fixtures, service):
    service["recherche_registres"]["formulaires"]["successions"] = SUC
    _form(fixtures, "mnesys-formulaire-successions.html", SUC)
    res = _resultats(fixtures)
    r = registres.rechercher(app.sctx, "AD99", "Ville-Fictive", 1876, "SUCC", annee_fin=1882)
    assert "erreur" not in r, r
    assert r["commune_service"] == "Bureau de Ville-Fictive"
    q = _params(res)
    assert q["0-title[]"] == ["Bureau de Ville-Fictive"] and q["1-controlledAccessPhysicalCharacteristic[]"] == [
        "Table de successions"]
    assert q["2-date_begin"] == ["1876"] and q["2-date_end"] == ["1882"]
    # bureau obligatoire pour les successions
    assert "commune" in registres.rechercher(app.sctx, "AD99", "", 1880, "SUCC")["erreur"]


def test_types_de_fonds_sans_formulaire_ou_sur_ad59(app, service):
    r = registres.rechercher(app.sctx, "AD99", "Ville-Fictive", 1880, "RM")
    assert "Aucun formulaire « matricules »" in r["erreur"]
    assert "RM" in registres.rechercher(app.sctx, "AD59", "Lille", 1880, "RM")["erreur"]


def test_referentiel_declare_matricules_et_successions():
    rm = [c for c in registres.services_registres()[1:]
          if "matricules" in archives.by_code(c)["recherche_registres"]["formulaires"]]
    succ = [c for c in registres.services_registres()[1:]
            if "successions" in archives.by_code(c)["recherche_registres"]["formulaires"]]
    assert {"AD19", "AD55", "AD58", "AD69", "AD90", "AD972"} <= set(rm)
    assert {"AD58", "AD69", "AD90"} <= set(succ)


# ------------------------------------------------------------------- formulaires relevés pour #242

@respx.mock
def test_type_d_acte_en_sujet_et_tables_decennales(app, fixtures, service):
    """AD39 : typologie matérielle sans type d'acte, « Type d'acte » en sujet ; AD80 : « Tables décennales »
    retenue seule parmi d'autres tables."""
    _form(fixtures, "mnesys-formulaire-sujet.html")
    res = _resultats(fixtures)
    assert "erreur" not in registres.rechercher(app.sctx, "AD99", "Ville-Fictive", 1860, "N")
    q = _params(res)
    assert q["2-controlledAccessSubject[]"] == ["BAPTEME", "NAISSANCE"]
    assert not any("PhysicalCharacteristic" in k for k in q)
    registres.rechercher(app.sctx, "AD99", "Ville-Fictive", 1860, "TD")
    q = _params(res)
    assert q["1-controlledAccessPhysicalCharacteristic[]"] == ["table décennale"] and not any("Subject" in k for k in q)


@respx.mock
def test_tables_dediees_avec_periode_et_etat_civil_absent(app, fixtures, service):
    """AD25 : formulaire de tables doté d'une période, sans formulaire d'état civil par commune."""
    formulaires = service["recherche_registres"]["formulaires"]
    del formulaires["etat_civil"]
    formulaires["tables_decennales"] = TD
    _form(fixtures, "mnesys-formulaire-periode.html", TD)
    res = _resultats(fixtures)
    r = registres.rechercher(app.sctx, "AD99", "Le Lamentin", 1860, "TD")
    assert "erreur" not in r and "tables_hors_periode" not in r, r
    q = _params(res)
    assert q["formUuid"] == [TD] and q["period_begin"] == ["1860"] == q["period_end"]
    r = registres.rechercher(app.sctx, "AD99", "Le Lamentin", 1860, "N")
    assert "« etat_civil »" in r["erreur"] and "types disponibles : TD" in r["erreur"] and res.call_count == 1


@respx.mock
def test_champ_d_annee_declare_pour_les_matricules(app, fixtures, service):
    """AD25 : classe saisie en texte libre « 0-title », déclarée au référentiel (champs_annee)."""
    service["recherche_registres"]["formulaires"]["matricules"] = MAT
    service["recherche_registres"]["champs_annee"] = {"matricules": "0-title"}
    _form(fixtures, "mnesys-formulaire-classe-texte.html", MAT)
    res = _resultats(fixtures)
    r = registres.rechercher(app.sctx, "AD99", "", 1880, "RM")
    assert "erreur" not in r, r
    q = _params(res)
    assert q["0-title"] == ["1880"] and "registres_hors_periode" not in r


def test_cote_sans_libelle_colle(fixtures):
    html = (fixtures / "mnesys-recherche-positive.html").read_text()
    debut = html.index('class="referenceCodes">') + len('class="referenceCodes">')
    fin = html.index("<", debut)
    valeur = html[debut:fin].strip()
    for colle, attendu in ((f"{valeur} (Cote(s))", valeur),  # AD80
                           (f"3Q23 (Cote), {valeur} (Cote)", f"3Q23, {valeur}")):  # AD37
        resultats, _, _ = registres._lire(html[:debut] + colle + html[fin:], 1, HOTE, "99999")
        assert resultats[0]["cote"] == attendu


def test_referentiel_declare_les_services_du_releve_242():
    codes = set(registres.services_registres())
    assert {"AD25", "AD37", "AD39", "AD80", "AD91"} <= codes
    ad25 = archives.by_code("AD25")["recherche_registres"]
    assert "etat_civil" not in ad25["formulaires"] and ad25["champs_annee"] == {"matricules": "0-title"}
    assert "successions" in archives.by_code("AD91")["recherche_registres"]["formulaires"]
