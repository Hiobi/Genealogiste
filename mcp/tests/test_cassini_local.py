"""#349 : base Cassini installée par l'utilisateur (CC BY-NC-SA 4.0), jamais embarquée.

AUCUNE donnée réelle du jeu n'est ici : le CSV et les métadonnées de dépôt sont fabriqués par le test (lieux
« Factice », valeurs inventées), avec les seuls noms de colonnes que l'analyseur lit. Le code INSEE 62133 n'est là
que pour rejoindre les réponses enregistrées du COG (cas témoin de test_lieu_historique)."""

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from pathlib import Path

import httpx
import pytest
import respx
from test_contexte_local import services_enregistres  # noqa: F401  (fixture du rejeu par service)
from test_lieu_historique import routes  # noqa: F401  (fixture : réponses enregistrées de lieu_historique)

from genealogiste_mcp import outils, server
from genealogiste_mcp.config import Config, load_config
from genealogiste_mcp.contexte import cassini

DEPOT = f"{cassini.API}/datas/{cassini.DOI}"
COLONNES = [*cassini.REQUISES, *cassini.CHEFS_LIEUX, "pop_an3_info", "pop_an3_val", "pop_1806_info", "pop_1806_val",
            "pop_1906_info", "pop_1906_val", "pop_1975_info", "pop_1975_val", "colonne_factice"]


def _ligne(**valeurs) -> str:
    defaut = {c: "f" if c.startswith("est_chef_lieu") else "" for c in COLONNES}
    defaut.update(valeurs)
    return ",".join('"' + defaut[c].replace('"', '""') + '"' if "," in defaut[c] or "\n" in defaut[c] else defaut[c]
                    for c in COLONNES)


def csv_factice() -> bytes:
    lignes = [
        ",".join(COLONNES),
        _ligne(noacass="900001", nom_cassini="Factice, le Vieux", nom_an3="Factice-la-Montagne", nom_1801="Factice",
               nom_1999="Factice-Montigny", commune_mars_2021="62133", est_chef_lieu_communal_1999="t",
               district_an_3="District-Factice", departement_an_3="Département-Factice", departement_1999="62",
               subdelegations="Subdélégation-Factice", intendances="Intendance-Factice",
               intendances_types="intendance", est_chef_lieu_district_1790="t", pop_an3_info="pop",
               pop_an3_val="111", pop_1806_info="abs.", pop_1806_val="", pop_1906_info="pop", pop_1906_val="2222",
               pop_1975_info="pop", pop_1975_val="3333", colonne_factice="champ sur\ndeux lignes"),
        _ligne(noacass="900002", nom_cassini="Hameau-Factice", nom_an3="Hameau-Factice", nom_1999="Hameau-Factice",
               commune_mars_2021="62133", est_chef_lieu_communal_1999="f"),
        _ligne(noacass="900003", nom_cassini="Ailleurs-Factice", nom_1999="Ailleurs-Factice",
               commune_mars_2021="99998", est_chef_lieu_communal_1999="t"),
    ]
    return ("\r\n".join(lignes) + "\r\n").encode("utf-8")


def depot_factice(donnees: bytes, licence: str = cassini.LICENCE, **extra) -> dict:
    """Forme des métadonnées d'un dépôt Nakala (clés relevées sur la réponse réelle), contenu inventé."""
    return {"version": 7, "status": "published", "identifier": cassini.DOI, "uri": f"https://doi.org/{cassini.DOI}",
            "creDate": "2001-02-03T00:00:00+00:00", "modDate": "2002-03-04T00:00:00+00:00",
            "depositor": {"name": "Déposant Factice"},
            "files": [{"name": "autre-fichier-factice.txt", "size": "12", "sha1": "0" * 40},
                      {"name": cassini.FICHIER, "size": str(len(donnees)),
                       "sha1": hashlib.sha1(donnees, usedforsecurity=False).hexdigest()}],
            "metas": [{"value": "Dépôt factice de test", "propertyUri": "http://nakala.fr/terms#title"},
                      {"value": licence, "propertyUri": "http://nakala.fr/terms#license"},
                      {"value": {"givenname": "Autrice", "surname": "Factice", "fullName": "Autrice Factice"},
                       "propertyUri": "http://nakala.fr/terms#creator"}], **extra}


@pytest.fixture
def referentiels(app, tmp_path):
    app.config.referentiels_dir_conf = tmp_path / "referentiels"
    cassini._BASES.clear()
    yield tmp_path / "referentiels" / "cassini"
    cassini._BASES.clear()


def _nakala(r, donnees: bytes, corps: bytes | None = None, depot: dict | None = None):
    d = depot or depot_factice(donnees)
    sha1 = next(f["sha1"] for f in d["files"] if f["name"] == cassini.FICHIER)
    meta = r.get(DEPOT).respond(200, json=d)
    fichier = r.get(f"{cassini.API}/data/{cassini.DOI}/{sha1}").respond(
        200, content=donnees if corps is None else corps, headers={"content-type": "text/csv; charset=UTF-8"})
    return meta, fichier


def _installer(donnees: bytes | None = None) -> dict:
    donnees = donnees or csv_factice()
    with respx.mock(assert_all_called=False) as r:
        _nakala(r, donnees)
        prep = server.cassini_preparer()
        return server.cassini_installer(prep["jeton"])


def _contenu(dossier: Path) -> list[str]:
    return sorted(p.name for p in dossier.iterdir()) if dossier.exists() else []


def _niveau(res: dict, nom: str) -> dict:
    return next(n for n in res["niveaux"] if n["niveau"] == nom)


# ---------------------------------------------------------------- catalogue et garde-fous

def test_catalogue_classes_et_decisions():
    assert outils.OUTILS["cassini_preparer"] == (outils.PROPOSITION, outils.PROPOSITION)
    assert outils.OUTILS["cassini_installer"] == (outils.RESEAU, outils.ECRITURE)
    assert outils.OUTILS["cassini_desinstaller"] == (outils.ECRITURE, outils.ECRITURE)
    assert outils.decision("cassini_preparer") == "allow"
    assert outils.decision("cassini_installer") == outils.decision("cassini_desinstaller") == "ask"
    profil = outils.profil_sans_surveillance()["permissions"]
    assert outils.PREFIXE_PLUGIN + "cassini_installer" in profil["deny"]
    assert outils.PREFIXE_PLUGIN + "cassini_desinstaller" in profil["deny"]


def test_aucun_parametre_de_personne():
    """Aucune donnée de personne ne part vers Nakala : pas de garde « vivants » à poser."""
    for nom in ("cassini_preparer", "cassini_installer", "cassini_desinstaller"):
        params = set(inspect.signature(getattr(server, nom)).parameters)
        assert not params & outils.PARAMS_PERSONNE, nom
        assert params <= {"jeton"} and nom not in outils.GARDE_VIVANTS and nom not in outils.BUDGET_ENQUETE


def test_hote_et_liens():
    from genealogiste_mcp.contexte import services
    from genealogiste_mcp.politique_acces import PolitiqueAcces

    assert services.url_autorisee("NAKALA", DEPOT)
    assert services.url_autorisee("NAKALA", f"{cassini.API}/data/{cassini.DOI}/{'a' * 40}")
    cfg = Config(data_dir=Path("d"), cache_path=Path("c"))
    assert PolitiqueAcces.depuis_config(cfg).politique("api.nakala.fr").service
    assert set(cassini.LIENS) == {"doi", "licence", "fiche_cassini"}


# ---------------------------------------------------------------- emplacement

def test_emplacement_par_defaut_hors_des_donnees(configuration_isolee, monkeypatch):
    cfg = load_config()
    assert cfg.referentiels_dir == configuration_isolee / ".local/share" / "genealogiste-referentiels"
    assert not cfg.referentiels_dir.resolve().is_relative_to(cfg.data_dir.resolve())
    assert cassini.refus_emplacement(cfg) is None
    monkeypatch.setenv("GENEALOGISTE_REFERENTIELS_DIR", str(configuration_isolee / "ailleurs"))
    assert load_config().referentiels_dir == configuration_isolee / "ailleurs"


@pytest.mark.parametrize("cas", ["donnees", "sous_donnees", "depot_git", "medias", "notes", "plugin", "lien"])
def test_emplacement_refuse_sans_requete(app, tmp_path, cas):
    depot = tmp_path / "depot-tiers"
    (depot / ".git").mkdir(parents=True)
    vers_donnees = tmp_path / "lien-vers-donnees"
    vers_donnees.symlink_to(app.config.data_dir, target_is_directory=True)
    app.config.notes_dir = tmp_path / "coffre"
    app.config.referentiels_dir_conf = {
        "donnees": app.config.data_dir, "sous_donnees": app.config.data_dir / "referentiels",
        "depot_git": depot / "sous" / "dossier", "medias": app.config.media_dir / "x",
        "notes": tmp_path / "coffre" / "annexes", "plugin": Path(cassini.__file__).resolve().parents[4] / "data",
        "lien": vers_donnees,
    }[cas]
    assert cassini.refus_emplacement(app.config)
    with respx.mock(assert_all_called=False) as r:
        route = r.route().respond(200, json={})
        prep = server.cassini_preparer()
        assert "erreur" in prep and "jeton" not in prep and prep["requetes_emises"] == 0
        assert server.cassini_installer("abcdef0123456789")["installe"] is False
        assert route.call_count == 0
    assert cassini.consulter(app.config, "62133") is None
    assert not (cassini.dossier(app.config) / cassini.FICHIER).exists()


def test_fichier_installe_impossible_a_commiter(app, referentiels):
    """Preuve : le fichier installé n'est sous aucun dépôt Git, et le dépôt de l'arbre ne le voit pas."""
    assert _installer()["installe"] is True
    fichier = (referentiels / cassini.FICHIER).resolve()
    assert not fichier.is_relative_to(app.config.data_dir.resolve())
    assert not any((p / ".git").exists() for p in fichier.parents)
    hors = subprocess.run(["git", "-C", str(fichier.parent), "rev-parse", "--is-inside-work-tree"],
                          capture_output=True, text=True)
    assert hors.returncode != 0
    git = ["git", "-C", str(app.config.data_dir)]
    subprocess.run([*git, "add", "-A"], check=True)
    suivis = subprocess.run([*git, "ls-files"], capture_output=True, text=True, check=True).stdout
    assert "cassini" not in suivis.lower() and cassini.ACCEPTATION not in suivis
    ajout = subprocess.run([*git, "add", "--", str(fichier)], capture_output=True, text=True)
    assert ajout.returncode != 0  # hors du dépôt : Git lui-même refuse le chemin


# ---------------------------------------------------------------- préparer

def test_preparer_presente_sans_telecharger(app, referentiels):
    donnees = csv_factice()
    with respx.mock(assert_all_called=False) as r:
        meta, fichier = _nakala(r, donnees)
        out = server.cassini_preparer()
        assert meta.call_count == 1 and fichier.call_count == 0
    assert out["source"]["doi"] == cassini.DOI and out["source"]["auteurs"] == ["Autrice Factice"]
    assert out["source"]["deposant"] == "Déposant Factice" and out["source"]["version"]["numero"] == 7
    assert out["licence"]["code"] == "CC-BY-NC-SA-4.0" and len(out["licence"]["conditions"]) == 3
    conditions = " ".join(out["licence"]["conditions"]).lower()
    assert "usage commercial" in conditions and "attribution" in conditions and "même licence" in conditions
    assert "EHESS" in out["reserve"] and "non vérifiée" in out["reserve"]
    assert out["fichier"]["taille_octets"] == len(donnees) and out["fichier"]["empreinte"]["algorithme"] == "sha1"
    assert out["destination"]["fichier"] == str(referentiels / cassini.FICHIER)
    assert out["etat"]["installee"] is False
    assert out["jeton"].isalnum() and "enregistrement" not in out and "accord explicite" in out["consigne"]
    assert _contenu(referentiels) == []
    assert app.journal.entries(source="nakala")[0]["operation"] == "cassini_preparer"


@pytest.mark.parametrize("depot, motif", [
    ({"licence": "CC-BY-4.0"}, "licence publiée"),
    ({"status": "pending"}, "non publié"),
    ({"identifier": "10.34847/nkl.autredepot"}, "n'est pas doi"),
    ({"files": []}, "fichier unique"),
])
def test_preparer_refuse_un_depot_inattendu(app, referentiels, depot, motif):
    d = depot_factice(csv_factice(), **depot)
    with respx.mock(assert_all_called=False) as r:
        r.get(DEPOT).respond(200, json=d)
        out = server.cassini_preparer()
    assert motif in out["erreur"] and "jeton" not in out


def test_preparer_service_desactive_ou_hors_ligne(app, referentiels):
    app.config.contexte_services = ()
    with respx.mock(assert_all_called=False) as r:
        route = r.route().respond(200, json={})
        out = server.cassini_preparer()
        assert route.call_count == 0
    assert "erreur" in out and out["requetes_emises"] == 0 and "jeton" not in out


@pytest.mark.parametrize("panne", [httpx.Response(500, text="erreur"), httpx.Response(404),
                                   httpx.ConnectTimeout("délai dépassé"), httpx.Response(200, text="pas du JSON")])
def test_preparer_panne_enveloppee(app, referentiels, panne):
    with respx.mock(assert_all_called=False) as r:
        if isinstance(panne, Exception):
            r.route().mock(side_effect=panne)
        else:
            r.route().mock(return_value=panne)
        out = server.cassini_preparer()
    assert "erreur" in out and "jeton" not in out and out.get("journal")


# ---------------------------------------------------------------- installer

def test_installer_verifie_ecrit_et_trace_l_acceptation(app, referentiels):
    donnees = csv_factice()
    with respx.mock(assert_all_called=False) as r:
        meta, fichier = _nakala(r, donnees)
        jeton = server.cassini_preparer()["jeton"]
        out = server.cassini_installer(jeton)
        assert meta.call_count == 2 and fichier.call_count == 1  # empreinte publiée relue à l'installation
        rejeu = server.cassini_installer(jeton)
        assert fichier.call_count == 1
    assert out["installe"] is True and out["au_registre"] is True and out["reference"] == f"doi:{cassini.DOI}"
    assert "déjà utilisé" in rejeu["erreur"] and rejeu["installe"] is False
    assert _contenu(referentiels) == [cassini.ACCEPTATION, cassini.FICHIER]
    assert (referentiels / cassini.FICHIER).read_bytes() == donnees
    a = json.loads((referentiels / cassini.ACCEPTATION).read_text(encoding="utf-8"))
    assert a["licence"] == "CC-BY-NC-SA-4.0" and a["doi"] == cassini.DOI and a["accepte_le"].startswith("20")
    assert a["empreinte"] == {"sha1": hashlib.sha1(donnees, usedforsecurity=False).hexdigest(),
                              "sha256": hashlib.sha256(donnees).hexdigest()}
    assert a["version"]["numero"] == 7 and a["taille_octets"] == len(donnees) and "EHESS" in a["reserve"]
    ref = app.registre_references.lire(f"doi:{cassini.DOI}")
    assert ref.service == "NAKALA" and ref.requete == DEPOT and ref.auteurs == ["Autrice Factice"]
    etat = cassini.etat(app.config)
    assert etat["installee"] is True and etat["lieux"] == 3 and etat["communes"] == 2
    assert app.journal.entries(source="nakala")[0]["statut"] == "positif"
    # Rien dans le cache SQLite : le jeu n'est jamais copié ailleurs que dans son dossier.
    assert not [k for k in app.cache.stats() if "nakala" in str(k).lower()]


@pytest.mark.parametrize("cas, motif", [
    ("empreinte", "empreinte SHA-1"), ("taille", "taille reçue"), ("http_500", ""), ("timeout", ""),
    ("page_html", "taille reçue"),
])
def test_installer_echec_sans_fichier_a_moitie_ecrit(app, referentiels, cas, motif):
    donnees = csv_factice()
    corps = {"empreinte": donnees[:-3] + b"X\r\n", "taille": donnees[:100], "page_html": b"<html>defi</html>"}
    with respx.mock(assert_all_called=False) as r:
        r.get(DEPOT).respond(200, json=depot_factice(donnees))
        fichier = r.get(url__startswith=f"{cassini.API}/data/")
        if cas == "http_500":
            fichier.respond(500, text="erreur")
        elif cas == "timeout":
            fichier.mock(side_effect=httpx.ReadTimeout("coupure"))
        else:
            fichier.respond(200, content=corps[cas])
        out = server.cassini_installer(server.cassini_preparer()["jeton"])
    assert out["installe"] is False and motif in out["erreur"] and out.get("journal")
    assert _contenu(referentiels) == []
    assert cassini.consulter(app.config, "62133") is None
    assert not app.registre_references.est_consultee(f"doi:{cassini.DOI}")


def test_installer_refuse_un_en_tete_inconnu(app, referentiels):
    donnees = b"colonne_a,colonne_b\r\n1,2\r\n"
    out = _installer(donnees)
    assert out["installe"] is False and "en-tête" in out["erreur"] and "noacass" in out["erreur"]
    assert _contenu(referentiels) == []


def test_installer_refuse_si_le_depot_a_change(app, referentiels):
    donnees = csv_factice()
    with respx.mock(assert_all_called=False) as r:
        r.get(DEPOT).respond(200, json=depot_factice(donnees))
        jeton = server.cassini_preparer()["jeton"]
    with respx.mock(assert_all_called=False) as r:
        r.get(DEPOT).respond(200, json=depot_factice(donnees + b"x\r\n"))
        fichier = r.get(url__startswith=f"{cassini.API}/data/").respond(200, content=donnees)
        out = server.cassini_installer(jeton)
        assert fichier.call_count == 0
    assert "a changé depuis la préparation" in out["erreur"] and _contenu(referentiels) == []


def test_installer_refuse_un_jeton_d_un_autre_type(app, referentiels):
    jeton = app.tokens.create({"type": "organisation", "dossier": "x", "plan": {"deplacements": []}})
    out = server.cassini_installer(jeton)
    assert "n'est pas une préparation" in out["erreur"]
    assert "Relancer cassini_preparer" in server.cassini_installer("inconnu123")["erreur"]
    assert "erreur" in server.cassini_installer("../pas-un-jeton")


def test_ecriture_atomique_une_panne_d_ecriture_ne_laisse_rien(app, referentiels, monkeypatch):
    donnees = csv_factice()

    def panne(src, dst, *a, **k):
        assert Path(src).read_bytes() == donnees  # le temporaire était complet : seul le renommage échoue
        raise OSError("disque plein (simulé)")

    with respx.mock(assert_all_called=False) as r:
        _nakala(r, donnees)
        jeton = server.cassini_preparer()["jeton"]
        monkeypatch.setattr("genealogiste_mcp.fichiers.os.replace", panne)
        out = server.cassini_installer(jeton)
    assert out["installe"] is False and "écriture impossible" in out["erreur"]
    assert _contenu(referentiels) == []
    assert cassini.etat(app.config)["installee"] is False


def test_acceptation_impossible_a_ecrire_rien_ne_reste_installe(app, referentiels, monkeypatch):
    donnees = csv_factice()
    reel = cassini.ecrire_atomique

    def ecrire(chemin, contenu):
        if Path(chemin).name == cassini.ACCEPTATION:
            raise OSError("quota dépassé (simulé)")
        reel(chemin, contenu)

    with respx.mock(assert_all_called=False) as r:
        _nakala(r, donnees)
        jeton = server.cassini_preparer()["jeton"]
        monkeypatch.setattr(cassini, "ecrire_atomique", ecrire)
        out = server.cassini_installer(jeton)
    assert out["installe"] is False and "écriture impossible" in out["erreur"]
    assert _contenu(referentiels) == [] and cassini.consulter(app.config, "62133") is None


def test_jeton_cassini_refuse_par_pieces_appliquer(app, referentiels):
    with respx.mock(assert_all_called=False) as r:
        _nakala(r, csv_factice())
        jeton = server.cassini_preparer()["jeton"]
    assert "erreur" in server.pieces_appliquer(jeton)
    assert _contenu(referentiels) == []


# ---------------------------------------------------------------- lecture par lieu_historique

def test_sans_installation_rien_ne_change(app, routes, referentiels):  # noqa: F811
    res = server.lieu_historique("Billy-Montigny, Pas-de-Calais", "1906")
    assert "cassini" not in res and "cassini_local" not in res["requetes"]
    assert _niveau(res, "nom")["valeur"] == "inconnu" and res["population"]["valeur"] == "inconnu"
    assert "ni embarquée ni interrogée" in res["consultation"][-1]["titre"]
    assert not referentiels.exists()


def test_avec_installation_indications_marquees(app, routes, referentiels):  # noqa: F811
    avant = server.lieu_historique("Billy-Montigny, Pas-de-Calais", "1906")
    assert _installer()["installe"] is True
    res = server.lieu_historique("Billy-Montigny, Pas-de-Calais", "1906")
    assert res["requetes"]["cassini_local"] == "positif"
    assert {k: v for k, v in res["requetes"].items() if k != "cassini_local"} == avant["requetes"]
    nom = _niveau(res, "nom")
    assert [x["nom"] for x in nom["valeur"]] == ["Factice-la-Montagne", "Factice", "Factice-Montigny"]
    assert nom["nom_sur_la_carte_de_cassini"] == "Factice, le Vieux"
    assert _niveau(res, "district")["valeur"] == "District-Factice"
    assert _niveau(res, "district")["periode_de_validite"]["debut"] == "1794"
    gen = _niveau(res, "generalite")
    assert gen["valeur"] == "Intendance-Factice" and gen["subdelegations"] == "Subdélégation-Factice"
    assert "pas un rattachement établi" in gen["periode_de_validite"]["note"]
    pop = res["population"]
    assert (pop["valeur"], pop["annee"], pop["recensement"]) == (2222, 1906, "1906")
    assert pop["annees_disponibles"] == ["an III", "1906", "1975"]
    for n in (nom, _niveau(res, "departement"), _niveau(res, "district"), gen, pop):
        s = n["source"]
        assert n["statut"] == "indication" and "ne conclut" in n["avertissement"]
        assert s["licence"] == "CC BY-NC-SA 4.0" and "Bideau" in s["attribution"] and "EHESS" in s["reserve"]
        assert s["reference"] == f"doi:{cassini.DOI}" and s["au_registre"] is True
        assert n["periode_de_validite"] and n["consultation"]
    # niveaux que le jeu ne documente pas : toujours « inconnu », jamais complétés
    for niveau in ("canton", "arrondissement", "province", "bailliage_ou_senechaussee", "diocese"):
        assert _niveau(res, niveau)["valeur"] == "inconnu"
    bloc = res["cassini"]
    assert bloc["nombre_de_lieux"] == 2 and bloc["principal"] == "900001"
    assert bloc["lieux"][0]["chef_lieu_de"] == ["district (1790)"]
    assert bloc["lieux"][1]["chef_lieu_communal_1999"] is False and "ne l'établit pas" in bloc["note"]
    assert "lue en local" in res["consultation"][-1]["titre"]


def test_population_la_plus_proche_avant_la_date_et_an_iii(app, routes, referentiels):  # noqa: F811
    _installer()
    pop = server.lieu_historique("62133", "1850")["population"]
    assert (pop["valeur"], pop["annee"], pop["recensement"], pop["ecart_annees"]) == (111, 1794, "an III", 55)
    assert pop["periode_de_validite"]["fin"] == "1795"
    assert server.lieu_historique("62133", "1790")["population"]["valeur"] == "inconnu"


def test_niveaux_du_cog_et_de_melodi_jamais_remplaces(app, routes, referentiels):  # noqa: F811
    sans = server.lieu_historique("Billy-Montigny, Pas-de-Calais", "1975")
    _installer()
    avec = server.lieu_historique("Billy-Montigny, Pas-de-Calais", "1975")
    for niveau in ("nom", "departement", "rattachement_communal"):
        assert _niveau(avec, niveau) == _niveau(sans, niveau)
        assert _niveau(avec, niveau)["source"]["service"] == "COG INSEE"
    assert {k: v for k, v in avec["population"].items() if k != "source"} == \
           {k: v for k, v in sans["population"].items() if k != "source"}
    assert avec["population"]["source"]["service"] == "INSEE-MELODI"


def test_commune_absente_du_fichier_ou_sans_chef_lieu(app, routes, referentiels):  # noqa: F811
    lignes = [",".join(COLONNES),
              _ligne(noacass="900010", nom_1999="Double-Factice-A", commune_mars_2021="62133",
                     est_chef_lieu_communal_1999="t", district_an_3="District-A"),
              _ligne(noacass="900011", nom_1999="Double-Factice-B", commune_mars_2021="62133",
                     est_chef_lieu_communal_1999="t", district_an_3="District-B")]
    _installer(("\n".join(lignes) + "\n").encode("utf-8"))
    res = server.lieu_historique("62133", "1906")
    assert res["cassini"]["principal"] is None and "aucun n'est choisi" in res["cassini"]["motif"]
    assert _niveau(res, "district")["valeur"] == "inconnu" and res["population"]["valeur"] == "inconnu"
    assert cassini.consulter(app.config, "01001")["bloc"]["nombre_de_lieux"] == 0


def test_plusieurs_chefs_lieux_departages_par_le_nom_du_cog(app, referentiels):
    lignes = [",".join(COLONNES),
              _ligne(noacass="900020", nom_1999="Autre-Factice", commune_mars_2021="62133",
                     est_chef_lieu_communal_1999="t"),
              _ligne(noacass="900021", nom_1999="Billy Montigny", commune_mars_2021="62133",
                     est_chef_lieu_communal_1999="t")]
    _installer(("\n".join(lignes) + "\n").encode("utf-8"))
    assert cassini.consulter(app.config, "62133", "Billy-Montigny")["bloc"]["principal"] == "900021"
    assert cassini.consulter(app.config, "62133", "Nom-Inconnu")["bloc"]["principal"] is None


@pytest.mark.parametrize("cas", ["sans_acceptation", "acceptation_illisible", "autre_licence", "fichier_modifie",
                                 "depose_a_la_main"])
def test_fichier_non_lu_sans_acceptation_ou_empreinte_conforme(app, routes, referentiels, cas):  # noqa: F811
    if cas == "depose_a_la_main":
        referentiels.mkdir(parents=True)
        (referentiels / cassini.FICHIER).write_bytes(csv_factice())
    else:
        _installer()
        acc = referentiels / cassini.ACCEPTATION
        if cas == "sans_acceptation":
            acc.unlink()
        elif cas == "acceptation_illisible":
            acc.write_text("{", encoding="utf-8")
        elif cas == "autre_licence":
            acc.write_text(json.dumps({**json.loads(acc.read_text(encoding="utf-8")), "licence": "CC0-1.0"}),
                           encoding="utf-8")
        else:
            with (referentiels / cassini.FICHIER).open("ab") as fh:
                fh.write(_ligne(noacass="900099", commune_mars_2021="62133").encode("utf-8") + b"\n")
    assert cassini.consulter(app.config, "62133") is None
    etat = cassini.etat(app.config)
    assert etat["installee"] is False and etat["motif"]
    res = server.lieu_historique("Billy-Montigny, Pas-de-Calais", "1906")
    assert "cassini" not in res and "cassini_local" not in res["requetes"]
    assert _niveau(res, "nom")["valeur"] == "inconnu" and res["population"]["valeur"] == "inconnu"


def test_fichier_remplace_puis_reinstalle_est_relu(app, referentiels):
    _installer()
    assert cassini.consulter(app.config, "62133")["bloc"]["nombre_de_lieux"] == 2
    lignes = [",".join(COLONNES), _ligne(noacass="900030", nom_1999="Seul-Factice", commune_mars_2021="62133",
                                         est_chef_lieu_communal_1999="t")]
    _installer(("\n".join(lignes) + "\n").encode("utf-8"))
    assert cassini.consulter(app.config, "62133")["bloc"]["nombre_de_lieux"] == 1


# ---------------------------------------------------------------- désinstaller

def test_desinstaller_supprime_fichier_et_acceptation_seulement(app, routes, referentiels):  # noqa: F811
    _installer()
    (referentiels / f".{cassini.FICHIER}.abc123.tmp").write_bytes(b"reste d'un essai interrompu")
    (referentiels / "note-de-l-utilisateur.txt").write_text("à garder", encoding="utf-8")
    out = server.cassini_desinstaller()
    assert out["desinstalle"] is True and len(out["supprimes"]) == 3
    assert _contenu(referentiels) == ["note-de-l-utilisateur.txt"]
    res = server.lieu_historique("Billy-Montigny, Pas-de-Calais", "1906")
    assert "cassini" not in res and res["population"]["valeur"] == "inconnu"
    encore = server.cassini_desinstaller()
    assert encore["desinstalle"] is False and encore["supprimes"] == []
    (referentiels / "note-de-l-utilisateur.txt").unlink()
    _installer()
    server.cassini_desinstaller()
    assert not referentiels.exists()  # dossier vide retiré


# ---------------------------------------------------------------- contexte_local

@pytest.fixture
def installee(app, referentiels):
    """Base factice installée avant l'ouverture du rejeu par service (son routeur répond 404 à tout le reste)."""
    assert _installer()["installe"] is True


def test_contexte_local_cite_la_reference_doi_et_la_licence(app, installee, services_enregistres):  # noqa: F811
    out = server.contexte_local(lieu="Billy-Montigny, Pas-de-Calais", periode="1900-1910", echelles="commune")
    els = [x for v in out["elements"].values() for x in v if x["origine"] == "NAKALA"]
    assert len(els) == 1, out["ecartes"]
    el = els[0]
    assert el["type"] == "demographie" and el["source"]["identifiant"] == f"doi:{cassini.DOI}"
    assert "2222" in el["enonce"] and "à confirmer" in el["enonce"]
    assert "CC BY-NC-SA 4.0" in el["source"]["localisation"] and "Bideau" in el["source"]["localisation"]
    assert el["rattachement"]["niveau"] != "atteste"


def test_contexte_local_ecarte_si_la_reference_n_est_pas_au_registre(app, installee,
                                                                    services_enregistres):  # noqa: F811
    app.config.references_consultees_path.unlink()
    out = server.contexte_local(lieu="Billy-Montigny, Pas-de-Calais", periode="1900-1910", echelles="commune")
    assert not [x for v in out["elements"].values() for x in v if x["origine"] == "NAKALA"]
    assert any(e["origine"] == "NAKALA" and "registre" in e["motif"] for e in out["ecartes"])


# ---------------------------------------------------------------- écriture interdite

def test_ecriture_interdite_refuse_installer_et_desinstaller(app, referentiels):
    _installer()
    app.config.ecriture = "interdite"
    assert server.mcp.garde("cassini_preparer", server.cassini_preparer, (), {}) is None
    for nom, args in (("cassini_installer", {"jeton": "abc"}), ("cassini_desinstaller", {})):
        refus = server.mcp.garde(nom, getattr(server, nom), (), args)
        assert refus and refus["refus"] == "ecriture_interdite"
    assert _contenu(referentiels) == [cassini.ACCEPTATION, cassini.FICHIER]
