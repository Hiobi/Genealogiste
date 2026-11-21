"""#265 : version de l'API, rôle du compte et réglages Gramps Web au diagnostic ; refus d'écriture anticipé ;
403 et 422 converties en messages actionnables ; renouvellement du jeton. Faux serveur, données fictives."""

import json

import httpx
import pytest
from gramps_fake import URL, FakeGrampsWeb, jwt_payload
from test_gramps_backend import CIT_DEATH, make_app, seed

from genealogiste_mcp import server
from genealogiste_mcp.gramps.client import GrampsClient, GrampsError


@pytest.fixture
def fake(tree):
    with FakeGrampsWeb() as f:
        seed(f, tree)
        yield f


def ctl(res: dict, nom: str) -> dict:
    return next(c for c in res["controles"] if c["controle"] == nom)


def diagnostic(tmp_path, backend="gramps"):
    make_app(tmp_path, backend=backend)
    try:
        return server.diagnostic()
    finally:
        server.set_app(None)


@pytest.fixture(autouse=True)
def sans_internet(monkeypatch):
    """Les sources publiques ne sont pas l'objet de ces tests : aucune requête réelle."""
    from genealogiste_mcp import diagnostic as diag
    monkeypatch.setattr(diag, "SOURCES", {})


# ------------------------------------------------------------------ jeton du faux serveur fidèle au contrat réel

def test_le_faux_jeton_porte_droits_arbre_et_expiration_mais_pas_le_role(fake):
    fake.tree = "arbre-1"
    fake.role = 4
    c = GrampsClient(URL, "sosa", "secret")
    assert c.tree() == "arbre-1"
    claims = jwt_payload(c._access)
    assert set(claims) == {"permissions", "tree", "exp"} and "role" not in claims
    assert "ImportFile" in claims["permissions"] and "AddObject" in claims["permissions"]


def test_le_jeton_rafraichi_garde_arbre_et_droits(fake):
    fake.tree = "arbre-1"
    c = GrampsClient(URL, "sosa", "secret")
    c.tree()
    c._exp = 0
    c.list("Tag")
    claims = jwt_payload(c._access)
    assert c._access.startswith("A2.") and claims["tree"] == "arbre-1" and "EditObject" in claims["permissions"]


# ------------------------------------------------------------------ diagnostic : version, rôle, réglages

def test_diagnostic_editor_et_api_testee(tmp_path, fake):
    res = diagnostic(tmp_path)
    v, r, g = ctl(res, "gramps_version"), ctl(res, "gramps_role"), ctl(res, "gramps_reglages")
    assert (v["etat"], r["etat"], g["etat"]) == ("ok", "ok", "ok")
    assert v["api"] == "3.25.1" and v["gramps"] == "6.0.8" and v["verdict"] == "testee"
    assert "3.13.0 à 3.26.0" in v["detail"] and "fusion" in v["detail"]
    assert v["fonctions"]["fusion"] is True and v["fonctions"]["edit_by_handle"] is False
    assert "edit_by_handle" in v["detail"].split("absentes")[1]
    assert r["role"] == 3 and "Editor" in r["detail"] and r["ecriture"] is True
    assert "file de tâches : non" in g["detail"] and "non vérifiable sur cette version" in g["detail"]


@pytest.mark.parametrize(("api", "backend", "etat", "verdict"), [
    ("3.12.2", "gramps", "erreur", "trop_ancienne"), ("3.12.2", "fichier", "attention", "trop_ancienne"),
    ("3.27.0", "gramps", "attention", "plus_recente"), ("n'importe quoi", "gramps", "attention", "inconnue"),
    ("3.13.0", "gramps", "ok", "testee"), ("3.26.0", "gramps", "ok", "testee"),
])
def test_diagnostic_verdict_de_version(tmp_path, fake, api, backend, etat, verdict):
    fake.api_version = api
    v = ctl(diagnostic(tmp_path, backend), "gramps_version")
    assert v["etat"] == etat and v["verdict"] == verdict
    assert (etat == "ok") == (not v.get("remede"))


def test_diagnostic_api_3_26_expose_l_inscription_libre(tmp_path, fake):
    fake.api_version = "3.26.0"
    g = ctl(diagnostic(tmp_path), "gramps_reglages")
    assert g["etat"] == "ok" and "inscription libre : fermée" in g["detail"]
    fake.inscription_libre = True
    g = ctl(diagnostic(tmp_path), "gramps_reglages")
    assert g["etat"] == "attention" and "ouverte" in g["detail"] and g["remede"]


def test_diagnostic_reglages_file_de_taches_et_multi_arbres(tmp_path, fake):
    fake.task_queue, fake.multi_tree = True, True
    g = ctl(diagnostic(tmp_path), "gramps_reglages")
    assert "file de tâches : oui" in g["detail"] and "multi-arbres : oui" in g["detail"]


@pytest.mark.parametrize(("role", "backend", "etat"), [
    (0, "gramps", "erreur"), (1, "gramps", "erreur"), (2, "gramps", "erreur"),
    (2, "fichier", "attention"), (3, "gramps", "ok"), (4, "gramps", "attention"), (5, "gramps", "attention"),
])
def test_diagnostic_role(tmp_path, fake, role, backend, etat):
    fake.role = role
    r = ctl(diagnostic(tmp_path, backend), "gramps_role")
    assert r["etat"] == etat and r["role"] == role
    if role < 3:
        assert "Editor" in r["remede"] and r["ecriture"] is False
    if role > 3:
        assert "préférer un compte Editor" in r["remede"] and r["ecriture"] is True


@pytest.mark.parametrize("route", ["metadata", "users"])
def test_diagnostic_continue_si_une_route_echoue(tmp_path, fake, route):
    cible = {"metadata": fake.router.routes[2], "users": fake.router.routes[3]}[route]
    cible.side_effect = lambda req: httpx.Response(500, text="boom")
    res = diagnostic(tmp_path)
    assert ctl(res, "gramps_web")["etat"] == "ok"
    if route == "metadata":
        assert ctl(res, "gramps_version")["etat"] == "attention" and "500" in ctl(res, "gramps_version")["detail"]
        assert ctl(res, "gramps_reglages")["etat"] == "attention"
        assert ctl(res, "gramps_role")["etat"] == "ok"
    else:
        assert ctl(res, "gramps_role")["etat"] == "attention" and "500" in ctl(res, "gramps_role")["detail"]
        assert ctl(res, "gramps_version")["etat"] == "ok"


def test_diagnostic_sans_secret_ni_personne(tmp_path, fake):
    texte = json.dumps(diagnostic(tmp_path), ensure_ascii=False)
    gramps = json.dumps([c for c in json.loads(texte)["controles"] if c["controle"].startswith("gramps_")])
    assert "secret" not in gramps and "Bearer" not in gramps and "signature" not in gramps
    assert not any(p["primary_name"]["first_name"] in gramps for p in fake.objects["Person"].values())


def test_diagnostic_sans_url_gramps_ne_cherche_rien(app):
    assert not [c for c in server.diagnostic()["controles"] if c["controle"].startswith("gramps_")]


# ------------------------------------------------------------------ refus d'écriture anticipé

@pytest.mark.parametrize("role", [0, 1, 2])
def test_arbre_proposer_refuse_tot_un_compte_sans_droit_d_ecriture(tmp_path, fake, role):
    fake.role = role
    a = make_app(tmp_path)
    try:
        res = server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")
        assert "erreur" in res and "Editor" in res["erreur"] and "lecture reste possible" in res["erreur"]
        assert "jeton" not in res and not fake.transactions
        # aucune lecture de l'arbre ni calcul de diff avant le refus
        assert a.backend.db is None
        # la lecture reste possible avec un rôle faible
        assert server.arbre_info()["personnes"] == 8
        assert server.gramps_recherche("MARTIN")["source"] == "grampsweb"
    finally:
        server.set_app(None)


@pytest.mark.parametrize("outil", ["gramps_recalculer_notes", "gramps_structurer_lieux", "marqueurs_migrer_proposer"])
def test_les_autres_propositions_partagent_le_refus(tmp_path, fake, outil):
    fake.role = 2
    make_app(tmp_path)
    try:
        res = getattr(server, outil)()
        assert "Editor" in res["erreur"] and not fake.transactions
    finally:
        server.set_app(None)


def test_annulation_refusee_tot(tmp_path, fake):
    a = make_app(tmp_path)
    try:
        r = server.arbre_appliquer(server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")["jeton"])
        fake.role = 1
        a.gramps()._exp = 0  # le jeton expire : le renouvellement relit le rôle courant
        assert "Editor" in server.arbre_annuler_modification(r["transaction"])["erreur"]
    finally:
        server.set_app(None)


def test_apply_refuse_avant_de_consommer_le_jeton(tmp_path, fake):
    a = make_app(tmp_path)
    try:
        jeton = server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")["jeton"]
        fake.role = 2
        a.gramps()._exp = 0
        assert "Editor" in server.arbre_appliquer(jeton)["erreur"]
        fake.role = 3
        a.gramps()._exp = 0
        assert "transaction" in server.arbre_appliquer(jeton)  # jeton intact
    finally:
        server.set_app(None)


def test_role_releve_en_cours_de_session(tmp_path, fake):
    """Compte promu Editor pendant la session : le jeton est renouvelé une fois avant de refuser."""
    fake.role = 2
    make_app(tmp_path)
    try:
        assert "Editor" in server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")["erreur"]
        fake.role = 3
        assert "jeton" in server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")
    finally:
        server.set_app(None)


def test_jeton_opaque_se_replie_sur_le_role(fake):
    """Serveur dont le jeton ne porte pas de droits : le rôle de /users/-/ décide."""
    fake.role = 1
    c = GrampsClient(URL, "sosa", "secret")
    c._access, c._exp = "A-opaque", 1e18
    with pytest.raises(GrampsError, match=r"rôle Member"):
        c.exiger_ecriture()
    fake.role = 3
    c.exiger_ecriture()


# ------------------------------------------------------------------ 403 et 422 convertis

def test_403_a_l_ecriture_est_un_message_actionnable(fake):
    fake.role = 2  # client appelé sans passer par le refus anticipé : c'est le serveur qui refuse
    c = GrampsClient(URL, "sosa", "secret")
    items = [{"type": "add", "_class": "Tag", "handle": "t1", "old": None,
              "new": {"_class": "Tag", "handle": "t1", "name": "x", "color": "#000000", "priority": 0}}]
    with pytest.raises(GrampsError) as exc:
        c.transaction(items, "essai")
    msg = str(exc.value)
    assert exc.value.status == 403 and "Editor" in msg and "Corriger" in msg
    assert "Forbidden" not in msg and "{" not in msg  # pas de corps brut


def test_envoi_de_fichier_refuse_en_403(fake):
    fake.role = 1
    fake.put({"_class": "Media", "handle": "m1", "gramps_id": "O1", "checksum": "", "path": "", "mime": ""})
    c = GrampsClient(URL, "sosa", "secret")
    with pytest.raises(GrampsError, match="Editor"):
        c.upload_media("m1", b"x", "image/jpeg")


def test_422_message_inconnu_des_api_trop_anciennes(fake):
    fake.api_version = "3.12.2"
    c = GrampsClient(URL, "sosa", "secret")
    items = [{"type": "add", "_class": "Tag", "handle": "t1", "old": None,
              "new": {"_class": "Tag", "handle": "t1", "name": "x", "color": "#000000", "priority": 0}}]
    with pytest.raises(GrampsError) as exc:
        c.transaction(items, "essai")
    assert exc.value.status == 422 and "3.13.0" in str(exc.value) and "Unknown field" not in str(exc.value)
    assert not fake.transactions


def test_lecture_avec_un_role_faible_n_est_pas_bloquee(fake):
    fake.role = 0
    c = GrampsClient(URL, "sosa", "secret")
    assert c.load_all().count()
    assert c.role() == 0


# ------------------------------------------------------------------ renouvellement du jeton (enquête longue)

class Horloge:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def test_expiration_pendant_une_enquete_longue(fake):
    h = Horloge()
    fake.horloge = h
    fake.tree = "arbre-1"
    c = GrampsClient(URL, "sosa", "secret", horloge=h)
    c.list("Tag")
    assert fake.logins == 1 and fake.refreshes == 0
    h.t += 14 * 60 + 40  # moins de 30 s avant l'expiration (15 min) : renouvelé avant l'appel
    c.list("Tag")
    assert (fake.logins, fake.refreshes) == (1, 1)
    claims = jwt_payload(c._access)
    assert claims["tree"] == "arbre-1" and claims["exp"] > h.t + 800 and c.tree_id == "arbre-1"
    h.t += 3600  # enquête longue : une heure sans appel, le jeton est expiré côté serveur
    c.list("Tag")
    assert (fake.logins, fake.refreshes) == (1, 2)


def test_ecriture_apres_expiration_renouvelle_sans_rejouer(fake):
    h = Horloge()
    fake.horloge = h
    c = GrampsClient(URL, "sosa", "secret", horloge=h)
    c.list("Tag")
    h.t += 3600
    items = [{"type": "add", "_class": "Tag", "handle": "t1", "old": None,
              "new": {"_class": "Tag", "handle": "t1", "name": "x", "color": "#000000", "priority": 0}}]
    c.transaction(items, "après une heure")
    assert fake.refreshes == 1 and len(fake.transactions) == 1


def test_jeton_expire_cote_serveur_ne_rejoue_pas_l_ecriture(fake):
    """L'horloge du client retarde sur celle du serveur : 401 sur l'écriture, jamais rejouée (docs/gramps-web.md)."""
    h = Horloge()
    fake.horloge = h
    c = GrampsClient(URL, "sosa", "secret", horloge=lambda: h() - 3600)  # le client croit le jeton encore valide
    c.list("Tag")
    h.t += 3600
    items = [{"type": "add", "_class": "Tag", "handle": "t1", "old": None,
              "new": {"_class": "Tag", "handle": "t1", "name": "x", "color": "#000000", "priority": 0}}]
    with pytest.raises(GrampsError) as exc:
        c.transaction(items, "écriture")
    assert exc.value.status == 401 and not fake.transactions and fake.refreshes == 0
    c.transaction(items, "écriture explicite")  # l'appel suivant renouvelle d'abord
    assert fake.refreshes == 1 and len(fake.transactions) == 1


def test_exp_absent_ou_illisible_garde_le_delai_par_defaut(fake):
    h = Horloge()
    c = GrampsClient(URL, "sosa", "secret", horloge=h)
    c._access = "A1"
    assert c._expiration() == h.t + 600


def test_diagnostic_gramps_injoignable_ne_multiplie_pas_les_essais(tmp_path, fake):
    appels = []

    def coupure(req):
        appels.append(req.url.path)
        raise httpx.ConnectError("refus")
    fake.router.routes[2].side_effect = coupure
    res = diagnostic(tmp_path)
    assert ctl(res, "gramps_version")["etat"] == "attention"
    assert "injoignable" in ctl(res, "gramps_role")["detail"] and ctl(res, "gramps_reglages")["etat"] == "attention"
    assert len(appels) == 3  # trois essais de lecture, pas davantage
