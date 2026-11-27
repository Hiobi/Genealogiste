"""Veille des mises en ligne des AD59 (#380) : dérive des formulaires, fils d'ajouts du forum, classeur 3 E
millésimé, ancienneté des référentiels.

Fixtures ``ad59-veille-*`` : pages publiques relevées le 27 novembre 2026, réduites aux balises lues (formulaires
d'état civil, de tables décennales et de recensements ; page des nouveautés ; flux Atom et page HTML du forum des
ajouts, pseudonymes, jeton de session et corps des messages remplacés). Les neuf autres formulaires sont les
fixtures des chantiers #376 à #379. Aucun réseau : respx, DNS simulé."""

import json
import runpy
from datetime import date
from pathlib import Path

import pytest
import respx

from genealogiste_mcp import couverture_3e, diagnostic, reseau, server
from genealogiste_mcp.politique_acces import PolitiqueAcces
from genealogiste_mcp.sources import registres
from genealogiste_mcp.sources import veille_ad59 as veille

ROOT = Path(__file__).resolve().parents[2]
HOTE = "https://archivesdepartementales.lenord.fr"
FIXTURES = {
    "etat_civil": "ad59-veille-formulaire-etat-civil.html",
    "tables_decennales": "ad59-veille-formulaire-tables-decennales.html",
    "recensements": "ad59-veille-formulaire-recensements.html",
    "matricules_tables": "ad59-matricules-formulaire-tables.html",
    "matricules_fiches": "ad59-matricules-formulaire-fiches.html",
    "successions": "ad59-successions-formulaire.html",
    "fiches_deces": "ad59-fiches-deces-formulaire.html",
    "hypotheques_indicateur": "ad59-hypotheques-formulaire-indicateur.html",
    "hypotheques_tables": "ad59-hypotheques-formulaire-tables.html",
    "hypotheques_repertoires": "ad59-hypotheques-formulaire-repertoires.html",
    "cadastre_consulaire": "ad59-cadastre-formulaire-consulaire.html",
    "cadastre_napoleonien": "ad59-cadastre-formulaire-napoleonien.html",
}
ETAT_CIVIL = registres.FORMULAIRE


def _formulaires(fixtures, **remplacements):
    """Une route par formulaire connu ; ``remplacements`` : clé -> texte servi, ou code HTTP."""
    routes = {}
    for cle, uuid in registres.formulaires_ad59().items():
        servi = remplacements.get(cle, (fixtures / FIXTURES[cle]).read_text(encoding="utf-8"))
        route = respx.get(f"{HOTE}/search/form/{uuid}")
        routes[cle] = route.respond(servi) if isinstance(servi, int) else route.respond(200, text=servi)
    return routes


def _un(resultat: dict, cle: str) -> dict:
    return next(f for f in resultat["formulaires"] if f["cle"] == cle)


def _journal(app, operation: str) -> list[dict]:
    return [e for e in app.journal.entries(source=veille.SOURCE_JOURNAL) if e["operation"] == operation]


# ---------------------------------------------------------------------------- contrat des formulaires

def test_contrat_couvre_les_formulaires_du_code_sans_recopier_d_uuid():
    connus = registres.formulaires_ad59()
    assert len(connus) == len(set(connus.values())) == 12
    assert set(veille.contrat()["formulaires"]) == set(connus)
    brut = veille.PATH.read_text(encoding="utf-8")
    assert not [u for u in connus.values() if u in brut]  # source unique des UUID : registres.py
    assert connus["etat_civil"] == registres.FORMULAIRE and connus["tables_decennales"] == registres.FORMULAIRE_TD
    assert connus["cadastre_napoleonien"] == registres.FORMULAIRES_CAD["napoleonien"]


@pytest.mark.parametrize("cle", sorted(FIXTURES))
def test_fixtures_relevees_conformes_au_contrat(fixtures, cle):
    lu = veille.lire_formulaire((fixtures / FIXTURES[cle]).read_text(encoding="utf-8"))
    assert lu["uuid"] == registres.formulaires_ad59()[cle]
    assert veille.comparer(veille.contrat()["formulaires"][cle], lu) == {}
    assert "0-controlledAccessGeographicName" in lu["champs"]


def test_lecture_du_formulaire_d_etat_civil(fixtures):
    lu = veille.lire_formulaire((fixtures / FIXTURES["etat_civil"]).read_text(encoding="utf-8"))
    assert lu == {"titre": "Actes paroissiaux et d'état civil", "uuid": ETAT_CIVIL,
                  "champs": ["0-controlledAccessGeographicName", "1-controlledAccessPhysicalCharacteristic", "2-date",
                             "3-date_begin", "3-date_end"]}
    assert veille.lire_formulaire("<html><body><p>Vérification en cours</p></body></html>") is None


def test_comparer_rapproche_un_champ_renomme():
    attendu = {"titre": "Titre", "champs": ["0-lieu", "2-date", "3-date_begin"]}
    assert veille.comparer(attendu, {"titre": "titre ", "champs": ["0-lieu", "2-date", "3-date_begin"]}) == {}
    ecarts = veille.comparer(attendu, {"titre": "Autre", "champs": ["0-lieu", "4-date", "5-sujet"]})
    assert ecarts == {"champs_disparus": ["3-date_begin"], "champs_renommes": [{"avant": "2-date", "apres": "4-date"}],
                      "champs_ajoutes": ["5-sujet"], "titre_change": {"attendu": "Titre", "lu": "Autre"}}


# ---------------------------------------------------------------------------- sondage des formulaires

@respx.mock
def test_sondage_conforme_une_requete_par_formulaire_espacees(app, fixtures):
    routes = _formulaires(fixtures)
    r = veille.sonder_formulaires(app.sctx)
    assert r["etat"] == "conforme" and r["derives"] == [] and r["non_verifies"] == []
    assert [f["etat"] for f in r["formulaires"]] == ["conforme"] * 12
    assert all(route.call_count == 1 for route in routes.values()) and len(respx.calls) == 12
    assert app.sleeps.count(veille.PAUSE) == 11  # pause propre à la veille, en plus de l'intervalle de l'hôte
    [entree] = _journal(app, "formulaires")
    assert entree["statut"] == "positif" and entree["nb_resultats"] == 0 and r["journal"] == entree["id"]
    assert "12 formulaire(s) conforme(s) sur 12" in entree["resume"]


@respx.mock
def test_sondage_sans_cache_relit_a_chaque_passage(app, fixtures):
    route = _formulaires(fixtures)["etat_civil"]
    for _ in range(2):
        assert veille.sonder_formulaires(app.sctx, ["etat_civil"])["etat"] == "conforme"
    assert route.call_count == 2


@respx.mock
def test_derive_formulaire_disparu_champ_renomme_champ_ajoute(app, fixtures):
    civil = (fixtures / FIXTURES["etat_civil"]).read_text(encoding="utf-8")
    assert 'name="2-date"' in civil and "</form>" in civil
    td = (fixtures / FIXTURES["tables_decennales"]).read_text(encoding="utf-8")
    _formulaires(
        fixtures, recensements=404,
        etat_civil=civil.replace('"2-date"', '"4-date"'),
        tables_decennales=td.replace("</form>", '<input type="number" name="1-date"/></form>'))
    r = veille.sonder_formulaires(app.sctx)
    assert r["etat"] == "derive" and r["derives"] == ["etat_civil", "tables_decennales", "recensements"]
    civil_lu = _un(r, "etat_civil")
    assert civil_lu["etat"] == "derive" and civil_lu["formulaire"] == ETAT_CIVIL
    assert civil_lu["champs_renommes"] == [{"avant": "2-date", "apres": "4-date"}]
    assert "champs_disparus" not in civil_lu and "4-date" in civil_lu["champs_lus"]
    td_lu = _un(r, "tables_decennales")
    assert td_lu["etat"] == "derive" and td_lu["champs_ajoutes"] == ["1-date"]
    disparu = _un(r, "recensements")
    assert disparu["etat"] == "disparu" and "404" in disparu["message"]
    assert _un(r, "successions")["etat"] == "conforme"  # un 404 ne vaut que pour son formulaire
    [entree] = _journal(app, "formulaires")
    assert entree["nb_resultats"] == 3 and disparu["url"] in entree["references"]
    assert "dérive : etat_civil, tables_decennales, recensements" in entree["resume"]


@respx.mock
def test_derive_champ_disparu_titre_change_et_page_sans_formulaire(app, fixtures):
    civil = (fixtures / FIXTURES["etat_civil"]).read_text(encoding="utf-8")
    assert "Actes paroissiaux" in civil and "3-date_end" in civil
    _formulaires(fixtures, etat_civil=civil.replace("Actes paroissiaux", "Registres paroissiaux")
                 .replace("3-date_end", "3-autre"),
                 fiches_deces="<html><head><title>Site</title></head><body>Page d'accueil</body></html>")
    r = veille.sonder_formulaires(app.sctx, ["etat_civil", "fiches_deces"])
    civil_lu = _un(r, "etat_civil")
    assert civil_lu["champs_disparus"] == ["3-date_end"] and civil_lu["champs_ajoutes"] == ["3-autre"]
    assert civil_lu["titre_change"] == {"attendu": "Actes paroissiaux et d'état civil",
                                        "lu": "Registres paroissiaux et d'état civil"}
    assert _un(r, "fiches_deces")["etat"] == "non_reconnu" and r["derives"] == ["etat_civil", "fiches_deces"]


@respx.mock
def test_formulaire_servi_sous_un_autre_uuid(app, fixtures):
    civil = (fixtures / FIXTURES["etat_civil"]).read_text(encoding="utf-8")
    _formulaires(fixtures, etat_civil=civil.replace(ETAT_CIVIL, "00000000-0000-4000-8000-000000000000"))
    lu = _un(veille.sonder_formulaires(app.sctx, ["etat_civil"]), "etat_civil")
    assert lu["etat"] == "derive" and lu["formulaire_servi"] == "00000000-0000-4000-8000-000000000000"


@respx.mock
def test_echec_de_l_hote_non_verifie_sans_requete_suivante(app, fixtures):
    """Un 503 n'est pas une dérive : rien n'est conclu, et les formulaires suivants ne sont pas demandés."""
    app.http.max_retries = 1
    routes = _formulaires(fixtures, etat_civil=503)
    r = veille.sonder_formulaires(app.sctx)
    assert r["etat"] == "non_verifie" and r["derives"] == [] and len(r["non_verifies"]) == 12
    assert routes["etat_civil"].call_count == 1 and routes["tables_decennales"].call_count == 0
    assert "Non demandé" in _un(r, "tables_decennales")["message"]
    assert _journal(app, "formulaires")[0]["statut"] == "erreur"


@respx.mock
def test_refus_de_la_politique_reseau_aucune_requete(app, fixtures, monkeypatch):
    routes = _formulaires(fixtures)
    monkeypatch.setattr(reseau, "getaddrinfo", lambda host, port: ["10.0.0.5"])
    r = veille.sonder_formulaires(app.sctx)
    assert r["etat"] == "non_verifie" and len(r["non_verifies"]) == 12 and not respx.calls
    assert "refusée" in _un(r, "etat_civil")["message"] and not any(x.called for x in routes.values())
    forum = veille.lire_ajouts_forum(app.sctx)
    assert forum["etat"] == "non_lu" and forum["fils"] == [] and not respx.calls


def test_hors_ligne_aucune_requete(config, fixtures):
    config.offline = True
    a = server.App(config, sleeper=lambda s: None)
    with respx.mock:
        r = veille.veiller(a.sctx, aujourdhui=date(2026, 11, 28))
        assert not respx.calls
    assert r["formulaires"]["etat"] == "non_verifie" and r["forum"]["etat"] == "non_lu"
    assert r["classeur_3e"]["etat"] == "non_verifie" and len(r["signalements"]) == 3


def test_cle_de_formulaire_inconnue_refusee(app):
    with pytest.raises(ValueError, match="inconnu"):
        veille.sonder_formulaires(app.sctx, ["etat-civil"])


# ---------------------------------------------------------------------------- forum des ajouts

def test_flux_atom_titre_date_lien_seulement(fixtures):
    texte = (fixtures / "ad59-veille-forum-flux.xml").read_text(encoding="utf-8")
    fils = veille.lire_flux(texte)
    assert fils[0] == {"titre": "Ajouts juillet 2026", "date": "2026-07-02",
                       "lien": "https://forum-archivesdepartementales.lenord.fr/viewtopic.php?p=38597#p38597"}
    assert [f["titre"] for f in fils] == ["Ajouts juillet 2026", "Dunkerque, mariages cantonaux",
                                          "Re: Ajouts Janvier 2026", "Ajouts Janvier 2026"]
    assert all(set(f) == {"titre", "date", "lien"} for f in fils)
    assert "Corps du message" in texte and "Corps du message" not in json.dumps(fils)  # corps jamais repris
    assert len(veille.lire_flux(texte, 2)) == 2


def test_flux_refuse_s_il_n_est_pas_un_flux_sur():
    with pytest.raises(ValueError, match="racine"):
        veille.lire_flux("<html><body>Maintenance</body></html>")
    with pytest.raises(ValueError, match="illisible"):
        veille.lire_flux('<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY a "aaaa">]><feed>&a;</feed>')
    with pytest.raises(ValueError, match="illisible"):
        veille.lire_flux("<feed><entry>")


def test_flux_ecarte_un_lien_hors_du_forum_et_borne_le_titre():
    flux = ('<feed xmlns="http://www.w3.org/2005/Atom">'
            '<entry><title>Ailleurs</title><link href="https://exemple.invalid/viewtopic.php?t=1"/></entry>'
            '<entry><title type="html"><![CDATA[Forum • ' + "x" * 300 + ']]></title><updated>2026-01-02T03:04:05Z'
            '</updated><link href="https://forum-archivesdepartementales.lenord.fr/viewtopic.php?t=7&amp;sid=abc"/>'
            "</entry></feed>")
    [fil] = veille.lire_flux(flux)
    assert fil["lien"] == "https://forum-archivesdepartementales.lenord.fr/viewtopic.php?t=7"
    assert fil["date"] == "2026-01-02" and len(fil["titre"]) == veille.MAX_TITRE + 1 and fil["titre"].endswith("…")


def test_page_html_du_forum_sans_annonce_globale_ni_jeton_ni_pseudonyme(fixtures):
    texte = (fixtures / "ad59-veille-forum.html").read_text(encoding="utf-8")
    fils = veille.lire_page_forum(texte)
    assert "global-announce" in texte and "pop up" not in json.dumps(fils)
    assert fils[:2] == [
        {"titre": "Suivre les Ajouts", "date": "2021-04-26",
         "lien": "https://forum-archivesdepartementales.lenord.fr/viewtopic.php?t=13339"},
        {"titre": "Ajouts juillet 2026", "date": "2026-07-02",
         "lien": "https://forum-archivesdepartementales.lenord.fr/viewtopic.php?t=24351"}]
    assert len(fils) == 4 and "sid=" not in json.dumps(fils) and "auteur" not in json.dumps(fils)
    with pytest.raises(ValueError, match="non reconnue"):
        veille.lire_page_forum("<html><body>Maintenance</body></html>")


@respx.mock
def test_forum_robots_404_puis_un_flux_consigne_au_journal(app, fixtures):
    robots = respx.get(veille.ROBOTS_FORUM).respond(404, text="<html>Not found</html>")
    flux = respx.get(veille.FLUX).respond(200, text=(fixtures / "ad59-veille-forum-flux.xml").read_text("utf-8"))
    page = respx.get(veille.PAGE_FORUM).respond(200, text="")
    r = veille.lire_ajouts_forum(app.sctx, limite=3)
    assert r["etat"] == "lu" and r["nouveaux"] == 3 and len(r["fils"]) == 3
    assert "404" in r["robots"] and "pas une autorisation" in r["robots"]
    assert robots.call_count == 1 and flux.call_count == 1 and not page.called  # une seule lecture par passage
    [entree] = _journal(app, "forum_ajouts")
    assert entree["statut"] == "positif" and entree["nb_resultats"] == 3 and entree["personne"] is None
    assert "à vérifier" in entree["resume"] and "Ajouts juillet 2026" in entree["resume"]
    assert "Corps du message" not in json.dumps(entree) and "jamais une source" in entree["note"]
    assert entree["references"] == [f["lien"] for f in r["fils"]]
    encore = veille.lire_ajouts_forum(app.sctx, limite=4)  # second passage : seul le quatrième fil est nouveau
    assert [f["nouveau"] for f in encore["fils"]] == [False, False, False, True] and encore["nouveaux"] == 1


@respx.mock
def test_forum_page_html_sur_demande(app, fixtures):
    respx.get(veille.ROBOTS_FORUM).respond(200, text="<!DOCTYPE html><html><body>Le forum</body></html>")
    flux = respx.get(veille.FLUX).respond(200, text="")
    respx.get(veille.PAGE_FORUM).respond(200, text=(fixtures / "ad59-veille-forum.html").read_text("utf-8"))
    r = veille.lire_ajouts_forum(app.sctx, mode="html")
    assert r["etat"] == "lu" and r["mode"] == "html" and len(r["fils"]) == 4 and not flux.called
    assert "page HTML" in r["robots"]


@respx.mock
def test_forum_interdit_par_robots_ou_illisible_signale_sans_erreur(app):
    flux = respx.get(veille.FLUX).respond(200, text="<feed/>")
    respx.get(veille.ROBOTS_FORUM).respond(200, text="User-agent: *\nDisallow: /app.php/\n")
    r = veille.lire_ajouts_forum(app.sctx)
    assert r["etat"] == "non_lu" and "interdit" in r["message"] and not flux.called
    assert _journal(app, "forum_ajouts")[-1]["statut"] == "erreur"
    respx.get(veille.ROBOTS_FORUM).respond(200, text="User-agent: *\nDisallow: /private/\n")
    flux.respond(200, text="<html>Maintenance</html>")
    r = veille.lire_ajouts_forum(app.sctx)
    assert r["etat"] == "non_lu" and "--forum html" in r["message"] and r["fils"] == []


@respx.mock
def test_forum_robots_en_erreur_serveur_pas_de_lecture(app):
    app.http.max_retries = 1
    respx.get(veille.ROBOTS_FORUM).respond(503)
    flux = respx.get(veille.FLUX).respond(200, text="<feed/>")
    r = veille.lire_ajouts_forum(app.sctx)
    assert r["etat"] == "non_lu" and "illisible" in r["message"] and not flux.called


def test_forum_declare_dans_la_politique_d_acces(config):
    pol = PolitiqueAcces.depuis_config(config).politique("forum-archivesdepartementales.lenord.fr")
    assert pol.service and pol.categorie == "archives" and pol.intervalle == 10.0 and pol.plafond_jour == 20
    assert pol.provenance["intervalle"] == "defaut" and not pol.reference  # valeurs prudentes, non sourcées


# ---------------------------------------------------------------------------- classeur 3 E et référentiels

def test_liens_de_la_page_des_nouveautes(fixtures):
    liens = veille.liens_nouveautes((fixtures / "ad59-veille-nouveautes.html").read_text(encoding="utf-8"))
    assert liens["classeurs"] == [couverture_3e.SOURCE]
    assert set(liens["formulaires"]) <= set(registres.formulaires_ad59().values()) and len(liens["formulaires"]) == 6
    assert liens["formulaires"][ETAT_CIVIL] == "Actes paroissiaux et d'état civil"
    hors = veille.liens_nouveautes('<a href="https://exemple.invalid/document/classeur-3e-mars-2027">x</a>')
    assert hors == {"classeurs": [], "formulaires": {}}


@respx.mock
def test_classeur_inchange(app, fixtures):
    page = respx.get(veille.NOUVEAUTES).respond(200, text=(fixtures / "ad59-veille-nouveautes.html").read_text("utf-8"))
    r = veille.rapprocher_classeur(app.sctx)
    assert r["etat"] == "inchange" and r["enregistre"] == couverture_3e.SOURCE and r["formulaires_inconnus"] == []
    assert page.call_count == 1 and _journal(app, "classeur_3e")[0]["statut"] == "negatif"


@respx.mock
def test_nouveau_classeur_millesime_signale_jamais_telecharge(app, fixtures):
    texte = (fixtures / "ad59-veille-nouveautes.html").read_text(encoding="utf-8")
    assert "classeur-3e-janvier-2026" in texte
    nouveau = f"{HOTE}/document/classeur-3e-janvier-2027"
    respx.get(veille.NOUVEAUTES).respond(200, text=texte.replace("classeur-3e-janvier-2026", "classeur-3e-janvier-2027"))
    document = respx.get(nouveau).respond(200, content=b"%PDF-1.7")
    r = veille.rapprocher_classeur(app.sctx)
    assert r["etat"] == "nouveau" and r["classeurs"] == [nouveau] and "Non téléchargé" in r["message"]
    assert "generer_couverture_3e_ad59.py" in r["remede"] and not document.called
    [entree] = _journal(app, "classeur_3e")
    assert entree["statut"] == "positif" and nouveau in entree["references"]


@respx.mock
def test_formulaire_inconnu_et_classeur_absent_signales(app, fixtures):
    inconnu = "11111111-2222-4333-8444-555555555555"
    respx.get(veille.NOUVEAUTES).respond(200, text=(
        f'<main><a href="/search/form/{inconnu}"><h2>Nouveau fonds</h2></a>'
        f'<a href="/search/form/{ETAT_CIVIL}">État civil</a></main>'))
    r = veille.rapprocher_classeur(app.sctx)
    assert r["etat"] == "non_verifie" and "Aucun lien" in r["message"]
    assert r["formulaires_inconnus"] == [{"formulaire": inconnu, "libelle": "Nouveau fonds",
                                          "url": f"{HOTE}/search/form/{inconnu}"}]
    assert inconnu in r["message"]


@respx.mock
def test_page_des_nouveautes_illisible_signalee(app):
    respx.get(veille.NOUVEAUTES).respond(404)
    r = veille.rapprocher_classeur(app.sctx)
    assert r["etat"] == "non_verifie" and "non lue" in r["message"] and "formulaires_inconnus" not in r


def test_anciennete_des_referentiels_seuil_d_un_an():
    refs = {r["referentiel"]: r for r in veille.anciennete(date(2026, 11, 28))}
    assert set(refs) == {"classeur_3e", "recensements"} and veille.SEUIL_JOURS == 365
    assert refs["classeur_3e"]["age_jours"] == 1 and not refs["classeur_3e"]["a_renouveler"]
    assert refs["classeur_3e"]["source"] == couverture_3e.SOURCE and len(refs["classeur_3e"]["sha256"]) == 64
    assert refs["recensements"]["source"].endswith(".pdf") and "remede" not in refs["recensements"]
    assert not any(r["a_renouveler"] for r in veille.anciennete(date(2027, 11, 27)))  # 365 jours : encore admis
    anciens = veille.anciennete(date(2027, 11, 28))
    assert all(r["a_renouveler"] and r["age_jours"] == 366 for r in anciens)
    assert "generer_couverture_3e_ad59.py" in anciens[0]["remede"]
    assert "generer_couverture_recensements_ad59.py" in anciens[1]["remede"]


def test_releve_illisible_a_renouveler(monkeypatch):
    monkeypatch.setattr(couverture_3e, "referentiel", lambda: {"source": "s", "releve_le": "novembre 2026"})
    ref = veille.anciennete(date(2026, 11, 28))[0]
    assert ref["a_renouveler"] and ref["age_jours"] is None


def test_diagnostic_signale_un_referentiel_ancien(config):
    ok = diagnostic._controle_referentiels_ad59(date(2026, 12, 1))
    assert ok["controle"] == "referentiels_ad59" and ok["etat"] == "ok" and "remede" not in ok
    ancien = diagnostic._controle_referentiels_ad59(date(2028, 1, 1))
    assert ancien["etat"] == "attention" and "make veille-ad59" in ancien["remede"]
    assert "classeur_3e relevé le 2026-11-27" in ancien["detail"]
    assert any(c["controle"] == "referentiels_ad59" for c in diagnostic.controles_locaux(None, None, config))


# ---------------------------------------------------------------------------- passage complet et script

def _passage_complet(fixtures, **remplacements):
    _formulaires(fixtures, **remplacements)
    respx.get(veille.NOUVEAUTES).respond(200, text=(fixtures / "ad59-veille-nouveautes.html").read_text("utf-8"))
    respx.get(veille.ROBOTS_FORUM).respond(404)
    respx.get(veille.FLUX).respond(200, text=(fixtures / "ad59-veille-forum-flux.xml").read_text("utf-8"))


@respx.mock
def test_passage_complet_quinze_requetes_sans_image_ni_notice(app, fixtures):
    _passage_complet(fixtures)
    r = veille.veiller(app.sctx, aujourdhui=date(2026, 11, 28))
    assert r["requetes"] == len(respx.calls) == 15
    chemins = [c.request.url.path for c in respx.calls]
    assert all(p.startswith(("/search/form/", "/page/", "/robots.txt", "/app.php/feed/")) for p in chemins)
    assert not [p for p in chemins if "oai" in p or "ark:" in p or "/images/" in p or "/document/" in p]
    assert not any(c.request.url.query for c in respx.calls)  # aucun paramètre, donc aucun nom
    assert r["formulaires"]["etat"] == "conforme" and r["classeur_3e"]["etat"] == "inchange"
    assert r["forum"]["etat"] == "lu" and r["signalements"] == [
        f"4 fil(s) du forum des ajouts à vérifier (journal {r['forum']['journal']})."]
    assert app.sleeps.count(veille.PAUSE) == 14
    assert {e["operation"] for e in app.journal.entries(source=veille.SOURCE_JOURNAL)} == {
        "formulaires", "forum_ajouts", "classeur_3e"}


@respx.mock
def test_passage_signale_derive_et_referentiels_anciens(app, fixtures):
    _passage_complet(fixtures, hypotheques_tables=404)
    r = veille.veiller(app.sctx, forum="", aujourdhui=date(2028, 1, 1))
    assert "forum" not in r and r["requetes"] == 13
    assert len(r["signalements"]) == 3 and "classeur_3e relevé le 2026-11-27" in r["signalements"][0]
    assert "dérive : hypotheques_tables" in r["signalements"][2]


@respx.mock
def test_script_code_de_sortie_et_fichier(app, fixtures, tmp_path, capsys):
    script = runpy.run_path(str(ROOT / "scripts/veiller_ad59.py"))
    _formulaires(fixtures, successions=404)
    respx.get(veille.NOUVEAUTES).respond(200, text=(fixtures / "ad59-veille-nouveautes.html").read_text("utf-8"))
    sortie = tmp_path / "veille.json"
    assert script["main"](["--forum", "non", "--sortie", str(sortie)], app) == 1
    affiche = capsys.readouterr().out
    assert "SIGNALEMENT : Formulaires" in affiche and "13 requête(s)" in affiche and '"etat": "disparu"' in affiche
    assert json.loads(sortie.read_text(encoding="utf-8"))["formulaires"]["derives"] == ["successions"]
    assert script["main"](["--forum", "non", "--sans-formulaires", "--sans-classeur"], app) == 0


def test_aucun_outil_mcp_ajoute_pour_la_veille():
    from genealogiste_mcp import outils

    assert not [nom for nom in outils.OUTILS if "veille" in nom]
    assert "veille_ad59" not in (ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8")


def test_documentation_de_la_veille():
    doc = (ROOT / "docs" / "veille-ad59.md").read_text(encoding="utf-8")
    for attendu in ("robots.txt", "404", "365 jours", "make veille-ad59", "/oai-pmh", "Non vérifié",
                    "ad59_formulaires.json", veille.FLUX, veille.NOUVEAUTES):
        assert attendu in doc, attendu


def test_requetes_par_le_seul_client_http_du_depot():
    source = Path(veille.__file__).read_text(encoding="utf-8")
    assert "import httpx" not in source and "urllib.request" not in source and "ctx.http.get(" in source
