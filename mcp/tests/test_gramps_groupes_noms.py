"""#276 : groupes de noms de Gramps (name groups) : lecture, proposition prudente, recherche, export et import XML.

Gramps Web pose un groupe de noms hors de ses transactions et ne sait pas revenir à « aucun regroupement » :
Genealogiste ne l'écrit pas (aucun POST /api/name-groups/, vérifié ici), il lit, propose une liste à appliquer à la
main et écrit ``<namemaps>`` dans ses exports. Patronymes fictifs uniquement.
"""

from __future__ import annotations

import json
from urllib.parse import quote

import httpx
import pytest
from test_gramps_xml_export import erreurs

from genealogiste_mcp import privacy
from genealogiste_mcp.export.gramps_xml import Metadonnees, db_to_xml
from genealogiste_mcp.gramps import groupes_noms as gn
from genealogiste_mcp.gramps import lecture_xml as lx
from genealogiste_mcp.gramps.mapping import GrampsDb, gramps_to_tree
from genealogiste_mcp.gramps.types import blank, date_to_gramps, event_ref, surname

# ============================================================================ clés et liens


@pytest.mark.parametrize(("a", "b", "motif"), [
    ("LE GRAND", "Legrand", gn.TYPOGRAPHIE), ("Le-Grand", "LEGRAND", gn.TYPOGRAPHIE),
    ("Lefèvre", "LEFEVRE", gn.TYPOGRAPHIE), ("D'Aubigny", "Daubigny", gn.TYPOGRAPHIE),
    ("de la Fontaine", "Delafontaine", gn.TYPOGRAPHIE), ("Œuvrard", "Oeuvrard", gn.TYPOGRAPHIE),
    ("Müller", "Mueller", gn.TRANSCRIPTION), ("Müller", "Muller", gn.TYPOGRAPHIE),
    ("Strauß", "Strauss", gn.TYPOGRAPHIE), ("Schröder", "Schroeder", gn.TRANSCRIPTION),
    # jamais regroupés : phonétique, diphtongue, finale, latin, noms voisins
    ("Dupont", "Dupond", None), ("Meyer", "Maier", None), ("Schmidt", "Schmitt", None), ("Martin", "Martini", None),
    ("Durand", "Durant", None), ("Muller", "Mueller", None), ("Mueller", "Moller", None), ("", "X", None),
])
def test_lien_retenu_seulement_typographie_et_transcription(a, b, motif):
    assert gn.lien(a, b) == motif and gn.lien(b, a) == motif


# ============================================================================ proposition

def test_proposition_typographie_et_choix_du_groupe():
    p = gn.proposer({"LE GRAND": 2, "Legrand": 5, "LEGRAND": 1, "Dupont": 3}, {})
    (g,) = p["groupes_proposes"]
    assert g["groupe"] == "Legrand" and g["choix_du_groupe"] == "forme la plus portée dans l'arbre"
    assert g["personnes"] == 8
    assert {x["patronyme"]: x["etat"] for x in g["patronymes"]} == {
        "LE GRAND": "à regrouper", "LEGRAND": "à regrouper", "Legrand": "nom du groupe"}
    assert p["a_appliquer"] == [
        {"patronyme": "LE GRAND", "groupe": "Legrand", "route": "POST /api/name-groups/LE%20GRAND/Legrand"},
        {"patronyme": "LEGRAND", "groupe": "Legrand", "route": "POST /api/name-groups/LEGRAND/Legrand"}]
    assert p["conflits"] == [] and p["deja_en_place"] == []


def test_egalite_de_frequence_signalee():
    p = gn.proposer({"Lefèvre": 2, "Lefevre": 2}, {})
    g = p["groupes_proposes"][0]
    assert g["groupe"] == "Lefevre" and "égalité" in g["egalite"] and g["choix_du_groupe"].startswith("égalité")


def test_transcription_germanique():
    p = gn.proposer({"Müller": 1, "Mueller": 4, "Muller": 2}, {})
    (g,) = p["groupes_proposes"]
    assert g["groupe"] == "Mueller"
    assert {x["patronyme"]: x["motif"] for x in g["patronymes"]} == {
        "Müller": gn.TYPOGRAPHIE, "Mueller": gn.TRANSCRIPTION, "Muller": gn.TYPOGRAPHIE}
    # sans la forme à tréma attestée, Muller et Mueller ne sont pas rapprochés (prudence)
    assert gn.proposer({"Mueller": 4, "Muller": 2}, {})["groupes_proposes"] == []


def test_idempotent_apres_application():
    attestes = {"LE GRAND": 2, "Legrand": 5}
    p1 = gn.proposer(attestes, {})
    appliques = {x["patronyme"]: x["groupe"] for x in p1["a_appliquer"]}
    p2 = gn.proposer(attestes, appliques)
    assert p2["a_appliquer"] == [] and p2["groupes_proposes"] == [] and p2["conflits"] == []
    assert p2["deja_en_place"][0]["groupe"] == "Legrand"
    # regroupé sous lui-même (seul état atteignable en revenant en arrière) : toujours rien à proposer de plus
    assert gn.proposer({"Legrand": 5}, {"Legrand": "Legrand"})["a_appliquer"] == []


def test_regroupement_existant_respecte():
    p = gn.proposer({"LE GRAND": 2, "Legrand": 5, "LEGRAND": 1}, {"LE GRAND": "LEGRAND"})
    assert p["groupes_proposes"][0]["groupe"] == "LEGRAND" and p["groupes_proposes"][0]["choix_du_groupe"] == \
        "regroupement existant respecté"
    assert p["a_appliquer"] == [{"patronyme": "Legrand", "groupe": "LEGRAND",
                                 "route": "POST /api/name-groups/Legrand/LEGRAND"}]


def test_conflits_jamais_tranches():
    plusieurs = gn.proposer({"LE GRAND": 2, "Legrand": 5, "LEGRAND": 1},
                            {"LE GRAND": "Legrand", "LEGRAND": "LEGRAND"})
    assert plusieurs["a_appliquer"] == [] and plusieurs["groupes_proposes"] == []
    assert plusieurs["conflits"][0]["motif"] == "regroupements existants vers plusieurs groupes"
    assert "non tranchée" in plusieurs["conflits"][0]["decision"]
    etranger = gn.proposer({"LE GRAND": 2, "Legrand": 5}, {"LE GRAND": "Durand"})
    assert etranger["a_appliquer"] == [] and "étranger" in etranger["conflits"][0]["motif"]


def test_pas_de_regroupement_phonetique_candidats_listes():
    p = gn.proposer({"Dupont": 3, "Dupond": 2, "Meyer": 1, "Maier": 1, "Rare": 1}, {})
    assert p["groupes_proposes"] == [] and p["a_appliquer"] == []
    paires = {tuple(c["patronymes"]) for c in p["candidats_non_retenus"]}
    assert ("Dupond", "Dupont") in paires and ("Maier", "Meyer") in paires
    assert all(c["score"] >= 0.9 for c in p["candidats_non_retenus"])
    assert "candidats_non_retenus" not in gn.proposer({"Dupont": 3, "Dupond": 2}, {}, candidats=False)


def test_patronymes_limite_aux_familles_citees():
    attestes = {"LE GRAND": 1, "Legrand": 1, "Lefèvre": 1, "Lefevre": 1}
    p = gn.proposer(attestes, {}, patronymes=["legrand"])
    assert {x["patronyme"] for g in p["groupes_proposes"] for x in g["patronymes"]} == {"LE GRAND", "Legrand"}


def test_group_as_propre_signale():
    p = gn.proposer({"LE GRAND": 2, "Legrand": 5}, {}, {"LE GRAND": 1})
    assert next(x for x in p["groupes_proposes"][0]["patronymes"] if x["patronyme"] == "LE GRAND")[
        "personnes_group_as_propre"] == 1


def test_routes_encodent_les_segments():
    assert gn.route("D'Aubigny", "Daubigny/X") == "POST /api/name-groups/D%27Aubigny/Daubigny%2FX"


# ============================================================================ lecture (client, faux fidèle)

def personne(h, gid, nom, prenom="Jean", naissance=None, group_as=""):
    p = blank("Person", h, gid)
    p["primary_name"]["first_name"] = prenom
    p["primary_name"]["surname_list"] = [surname(nom)]
    p["primary_name"]["group_as"] = group_as
    if naissance:
        e = blank("Event", f"e{h}", f"E{gid}")
        e["date"] = date_to_gramps(naissance)
        p["event_ref_list"] = [event_ref(e["handle"], "Primary")]
        p["birth_ref_index"] = 0
        return [p, e]
    return [p]


def base_noms() -> list[dict]:
    objs: list[dict] = []
    for h, gid, nom, prenom, n in (("p1", "I1", "LE GRAND", "Anne", "1750"), ("p2", "I2", "Legrand", "Berthe", "1760"),
                                   ("p3", "I3", "LEGRAND", "Zoé", None), ("p4", "I4", "Dupont", "Claude", "1740"),
                                   ("p5", "I5", "Dupond", "Denis", "1745"), ("p6", "I6", "Müller", "Émile", "1700"),
                                   ("p7", "I7", "Mueller", "Fritz", "1705"), ("p8", "I8", "Secret", "Hugo", None)):
        objs += personne(h, gid, nom, prenom, naissance=n)
    return objs


@pytest.fixture
def gfake():
    from gramps_fake import FakeGrampsWeb

    with FakeGrampsWeb() as f:
        for o in base_noms():
            f.put(o)
        yield f


def _gapp(tmp_path):
    from gramps_fake import URL

    from genealogiste_mcp import server
    from genealogiste_mcp.config import Config

    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend="gramps",
                 gramps_url=URL, gramps_user="sosa", gramps_password="secret", gramps_ttl=0)
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    return a


@pytest.fixture
def gapp(tmp_path, gfake):
    from genealogiste_mcp import server

    a = _gapp(tmp_path)
    yield a
    server.set_app(None)


def test_client_lit_les_groupes_et_le_faux_est_fidele(gapp, gfake):
    assert gapp.backend.groupes_noms() == {}
    gfake.name_groups.update({"LE GRAND": "LEGRAND", "Müller": "Mueller"})
    assert gapp.backend.groupes_noms() == {"LE GRAND": "LEGRAND", "Müller": "Mueller"}
    # GET /name-groups/<patronyme> : le groupe, ou le patronyme lui-même sans regroupement (get_name_group_mapping)
    c = gapp.backend.client
    assert c.request("GET", "/name-groups/" + quote("LE GRAND", safe="")).json() == {
        "surname": "LE GRAND", "group": "LEGRAND"}
    assert c.request("GET", "/name-groups/Dupont").json() == {"surname": "Dupont", "group": "Dupont"}


def test_le_faux_reproduit_ce_qui_empeche_l_ecriture(gapp, gfake):
    """Constat amont (docs/gramps-web.md) : le POST n'entre pas dans l'historique, regrouper un nom sous lui-même
    laisse la clé listée, aucune route ne la retire ; rôle Editor requis."""
    c = gapp.backend.client
    n = len(gfake.transactions)
    assert c.request("POST", "/name-groups/Dupond/Dupont").status_code == 201
    assert c.request("POST", "/name-groups/Dupond/Dupond").status_code == 201  # « retour » : la clé reste
    assert gapp.backend.groupes_noms() == {"Dupond": "Dupond"}
    assert len(gfake.transactions) == n and gfake.messages == []
    gfake.role = 1
    c._exp = 0
    c._renew()
    assert c.request("POST", "/name-groups/X/Y").status_code == 403


def test_outil_lecture_seule_rien_n_est_ecrit(gapp, gfake):
    from genealogiste_mcp import server

    avant = (json.dumps(gfake.objects, sort_keys=True), dict(gfake.name_groups), len(gfake.transactions))
    r = server.gramps_grouper_noms()
    assert "jeton" not in r and r["nature"].startswith("lecture") and "erreur" not in r
    assert (json.dumps(gfake.objects, sort_keys=True), gfake.name_groups, len(gfake.transactions)) == avant
    assert not [c for c in gfake.router.calls if c.request.method != "GET" and "/token/" not in str(c.request.url)]
    assert r["patronymes_examines"] == 8 and r["personnes"] == 8
    groupes = {g["groupe"]: {x["patronyme"] for x in g["patronymes"]} for g in r["groupes_proposes"]}
    # chaque patronyme n'a qu'une personne : égalité de fréquence, premier par ordre alphabétique sans accent
    assert groupes == {"LE GRAND": {"LE GRAND", "LEGRAND", "Legrand"}, "Mueller": {"Müller", "Mueller"}}
    assert {x["patronyme"] for x in r["a_appliquer"]} == {"LEGRAND", "Legrand", "Müller"}
    # rien de phonétique : Dupont/Dupond restent des candidats
    assert {tuple(c["patronymes"]) for c in r["candidats_non_retenus"]} >= {("Dupond", "Dupont")}
    assert "fusionne aucune personne" in r["procedure"] and "hors de ses transactions" in r["procedure"]
    # le XML d'import est valide (DTD et RNG, 1.7.1) et ne contient que des regroupements
    assert erreurs(r["xml_import"], "1.7.1") == []
    lu = lx.lire_xml(r["xml_import"].encode())
    assert sorted(lu.meta.regroupements) == sorted((x["patronyme"], x["groupe"]) for x in r["a_appliquer"])
    assert sum(lu.db.count().values()) == 0


def test_outil_idempotent_apres_pose_manuelle(gapp, gfake):
    from genealogiste_mcp import server

    r = server.gramps_grouper_noms()
    for x in r["a_appliquer"]:  # l'utilisateur applique les routes à la main (ici : le faux)
        gfake.name_groups[x["patronyme"]] = x["groupe"]
    r2 = server.gramps_grouper_noms()
    assert r2["a_appliquer"] == [] and r2["groupes_proposes"] == [] and "xml_import" not in r2
    assert len(r2["deja_en_place"]) == len(r["groupes_proposes"])
    assert {e["patronyme"] for e in r2["groupes_existants"]} == {x["patronyme"] for x in r["a_appliquer"]}


def test_outil_conflit_avec_un_groupe_existant(gapp, gfake):
    from genealogiste_mcp import server

    gfake.name_groups["LE GRAND"] = "Dupont"
    r = server.gramps_grouper_noms(candidats=False)
    assert any("étranger" in c["motif"] and "LE GRAND" in c["patronymes"] for c in r["conflits"])
    assert not any(x["patronyme"] in ("LE GRAND", "LEGRAND", "Legrand") for x in r["a_appliquer"])
    assert gfake.name_groups == {"LE GRAND": "Dupont"} and "candidats_non_retenus" not in r


def test_outil_hors_mode_gramps(app):
    from genealogiste_mcp import server

    assert "mode gramps" in server.gramps_grouper_noms()["erreur"]


# ============================================================================ recherche

def test_arbre_recherche_ajoute_les_patronymes_regroupes(gapp, gfake):
    from genealogiste_mcp import server

    sans = server.arbre_recherche(nom="Legrand")
    assert {x["id"] for x in sans} == {"I1", "I2", "I3"} and not any(x.get("via_groupe_noms") for x in sans)
    gfake.name_groups.update({"LE GRAND": "Legrand", "LEGRAND": "Legrand"})
    avec = server.arbre_recherche(nom="Legrand")
    assert {x["id"] for x in sans} <= {x["id"] for x in avec}  # aucun résultat retiré
    # LE GRAND / LEGRAND / Legrand sont déjà proches par la similarité ; un autre patronyme regroupé est ajouté
    gfake.name_groups["Dupont"] = "Legrand"
    via = [x for x in server.arbre_recherche(nom="Legrand") if x.get("via_groupe_noms")]
    assert [x["id"] for x in via] == ["I4"]
    assert not any(x.get("via_groupe_noms") for x in server.arbre_recherche(nom="Legrand", groupes_noms=False))
    # symétrique : chercher le patronyme regroupé trouve le nom de groupe
    assert "I2" in {x["id"] for x in server.arbre_recherche(nom="Dupont") if x.get("via_groupe_noms")}


def test_arbre_recherche_group_as_du_nom_prime(gapp, gfake):
    """group_as d'un NOM (champ propre à ce nom) prime sur le regroupement global, comme dans Gramps : Dupont classé
    sous Legrand par son propre nom est trouvé par « Legrand » même sans aucun groupe global, et un regroupement
    global de Dupont vers un autre groupe ne le retire pas de Legrand."""
    from genealogiste_mcp import server

    gfake.objects["Person"]["p4"]["primary_name"]["group_as"] = "Legrand"
    gapp.backend.snapshot(fresh=True)
    assert [x["id"] for x in server.arbre_recherche(nom="Legrand") if x.get("via_groupe_noms")] == ["I4"]
    gfake.name_groups["Dupont"] = "Autre"
    assert [x["id"] for x in server.arbre_recherche(nom="Legrand") if x.get("via_groupe_noms")] == ["I4"]
    assert [x["id"] for x in server.arbre_recherche(nom="Autre") if x.get("via_groupe_noms")] == []


def test_arbre_recherche_gramps_sans_groupes_inchange(gapp, gfake):
    from genealogiste_mcp import server

    assert gapp.backend.groupes_noms() == {}
    assert server.arbre_recherche(nom="Legrand") == server.arbre_recherche(nom="Legrand", groupes_noms=False)


def test_arbre_recherche_mode_fichier_inchange(app_famille):
    from genealogiste_mcp import server

    assert server.arbre_recherche(nom="Dupont") == server.arbre_recherche(nom="Dupont", groupes_noms=False)


def test_recherche_multi_ne_depasse_pas_le_poste_local(gapp, gfake):
    """Les patronymes regroupés sont une information locale : jamais ajoutés à la requête des sources externes."""
    from genealogiste_mcp import server

    gfake.name_groups.update({"Dupont": "Legrand", "LE GRAND": "Legrand"})
    gfake.router.route().mock(return_value=httpx.Response(200, json={}))
    r = server.recherche_multi("Legrand", prenom="Berthe")
    sortantes = [c for c in gfake.router.calls if c.request.url.host != "gramps.test"]
    assert sortantes, "des requêtes externes sont attendues"
    corps = " ".join(f"{c.request.url} {c.request.content.decode(errors='ignore')}" for c in sortantes).lower()
    assert "legrand" in corps and "dupont" not in corps and "le%20grand" not in corps and "le+grand" not in corps
    assert r["groupe_de_noms"]["apparentes"] == ["Dupont", "LE GRAND"]
    assert r["groupe_de_noms"]["envoyees_aux_sources"] is False
    assert "Dupont" not in json.dumps(r["requete"]) and "Dupont" not in json.dumps(r["sources_secondaires"])


def test_recherche_multi_garde_des_vivants_inchangee(gapp, gfake):
    """Un patronyme regroupé n'ouvre pas la garde : Secret (personne présumée vivante) reste refusé, sans requête."""
    from genealogiste_mcp import server

    gfake.name_groups["Secret"] = "Legrand"
    gfake.router.route().mock(return_value=httpx.Response(200, json={}))
    r = server.recherche_multi("Secret", prenom="Hugo")
    assert "vivant" in r and "groupe_de_noms" not in r
    assert not [c for c in gfake.router.calls if c.request.url.host != "gramps.test"]


def test_recherche_multi_mode_fichier_sans_groupe(app_famille):
    from genealogiste_mcp import server

    r = server.recherche_multi("Dupont", sources=[])
    assert "groupe_de_noms" not in r


# ============================================================================ export Gramps XML / gpkg

def _export(server, tmp_path, **kw):
    out = tmp_path / "x.gramps"
    r = server.arbre_exporter(format="gramps", chemin=str(out), **kw)
    return r, (out.read_text(encoding="utf-8") if out.exists() else "")


def test_export_gramps_ecrit_les_namemaps_de_gramps(gapp, gfake, tmp_path):
    from genealogiste_mcp import server

    gfake.name_groups.update({"LE GRAND": "Legrand", "Müller": "Mueller", "Dupond": "Dupont"})
    r, xml = _export(server, tmp_path, masquer_vivants=False, version_xml="1.7.2")
    assert "erreur" not in r and r["groupes_de_noms"] == {"ecrits": 3, "source": "Gramps"}
    assert ('<namemaps><map type="group_as" key="Dupond" value="Dupont"/><map type="group_as" key="LE GRAND" '
            'value="Legrand"/><map type="group_as" key="Müller" value="Mueller"/></namemaps>') in xml
    assert erreurs(xml, "1.7.2") == []
    lu = lx.lire_xml(xml.encode())
    assert dict(lu.meta.regroupements) == gfake.name_groups
    # aller-retour XML -> objets -> XML conservé
    assert lx.comparer_xml(xml.encode(), db_to_xml(lu.db, lu.version_xml, lu.meta).encode()) == []


def test_export_public_ne_fuit_pas_un_patronyme_masque(gapp, gfake, tmp_path):
    from genealogiste_mcp import server

    # Secret : personne présumée vivante (masquée). Dupond (défunt) est regroupé sous Secret : le groupe est un
    # patronyme masqué ; Secret lui-même est regroupé sous Legrand ; LE GRAND (défunt) sous Legrand : conservé.
    gfake.name_groups.update({"Dupond": "Secret", "Secret": "Legrand", "LE GRAND": "Legrand"})
    r, xml = _export(server, tmp_path)  # masquer_vivants par défaut
    assert "erreur" not in r and r["groupes_de_noms"]["ecrits"] == 1 and r["groupes_de_noms"]["retires_export_public"] == 2
    assert 'key="LE GRAND" value="Legrand"' in xml and "Secret" not in xml
    t = gapp.tree()
    assert privacy.residues(xml, privacy.publication(t)[2]["motifs"]) == []
    assert erreurs(xml, "1.7.1") == []
    # bilan : jamais le nom d'un regroupement retiré
    assert "Secret" not in json.dumps(r, ensure_ascii=False)
    # export complet (privé) : tout est écrit
    r2, xml2 = _export(server, tmp_path, masquer_vivants=False)
    assert r2["groupes_de_noms"]["ecrits"] == 3 and "Secret" in xml2


def test_export_public_regroupement_orphelin_retire(gapp, gfake, tmp_path):
    from genealogiste_mcp import server

    gfake.name_groups["Inconnu"] = "Legrand"  # patronyme porté par personne : pas dans l'export public
    r, xml = _export(server, tmp_path)
    assert r["groupes_de_noms"]["ecrits"] == 0 and "namemaps" not in xml


def test_export_gpkg_ecrit_aussi_les_namemaps(gapp, gfake, tmp_path):
    import gzip
    import tarfile

    from genealogiste_mcp import server

    gfake.name_groups["LE GRAND"] = "Legrand"
    out = tmp_path / "x.gpkg"
    r = server.arbre_exporter(format="gpkg", chemin=str(out), masquer_vivants=False)
    assert "erreur" not in r
    with tarfile.open(out, "r:gz") as t:
        xml = gzip.decompress(t.extractfile("data.gramps").read()).decode()
    assert '<map type="group_as" key="LE GRAND" value="Legrand"/>' in xml


def test_export_mode_fichier_aucun_groupe_invente(app_famille, tmp_path):
    from genealogiste_mcp import server

    r, xml = _export(server, tmp_path)
    assert r["groupes_de_noms"]["ecrits"] == 0 and "fichier" in r["groupes_de_noms"]["source"]
    assert "namemaps" not in xml


def test_export_groupes_illisibles_rien_n_est_ecrit(gapp, gfake, tmp_path):
    from genealogiste_mcp import server

    gapp.tree()
    with gfake.router:
        gfake.router.get("http://gramps.test/api/name-groups/").mock(return_value=httpx.Response(500, text="x"))
        r, xml = _export(server, tmp_path, masquer_vivants=False)
    assert "Groupes de noms illisibles" in r["erreur"] and xml == ""


# ============================================================================ import Gramps XML

def test_import_rapporte_les_namemaps_sans_les_appliquer(app, tmp_path):
    from genealogiste_mcp import server

    db = GrampsDb.from_objects(personne("p1", "I1", "Dupond", naissance="1750"))
    xml = db_to_xml(db, "1.7.1", Metadonnees(regroupements=[("Dupond", "Dupont"), ("Müller", "Mueller")]))
    f = tmp_path / "x.gramps"
    f.write_text(xml, encoding="utf-8")
    r = server.arbre_importer_gedcom(str(f))
    assert "erreur" not in r, r
    reg = r["import"]["regroupements"]
    assert reg["nombre"] == 2 and reg["regroupements"][0] == {"patronyme": "Dupond", "groupe": "Dupont"}
    assert "non appliqués" in reg["consigne"] and "fusionn" in reg["consigne"]
    assert r["import"]["non_repris"]["Métadonnées.regroupements"] == 2
    assert any("groupe(s) de noms" in w for w in r["avertissements"])


def test_import_sans_namemaps_ne_rapporte_rien(app, tmp_path):
    from genealogiste_mcp import server

    f = tmp_path / "x.gramps"
    f.write_text(db_to_xml(GrampsDb.from_objects(personne("p1", "I1", "Dupond", naissance="1750")), "1.7.1"),
                 encoding="utf-8")
    assert "regroupements" not in server.arbre_importer_gedcom(str(f))["import"]


def test_namemaps_seuls_aller_retour_et_validite():
    paires = [("D'Aubigny", "Daubigny"), ("LE GRAND", "Legrand")]
    for version in ("1.7.1", "1.7.2"):
        xml = gn.regroupements_xml(paires, version)
        assert erreurs(xml, version) == []
        lu = lx.lire_xml(xml.encode())
        assert lu.meta.regroupements == paires and sum(lu.db.count().values()) == 0
        assert lx.comparer_xml(xml.encode(), db_to_xml(lu.db, version, lu.meta).encode()) == []
    assert gramps_to_tree(GrampsDb())[0].personnes == {}
