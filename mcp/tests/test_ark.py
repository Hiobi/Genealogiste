"""ARK : lecture, normalisation, table NAAN, registre, résolution simulée (respx)."""

import pytest

from genealogiste_mcp import ark
from genealogiste_mcp.sources.gallica import ark_id

AD59 = "https://archivesdepartementales.lenord.fr/ark:/33518/48150m2qjdhb/7deaf652-1c2a-4f1e-9d0b-2b4a6c8e0f11"
AD62 = "http://archivesenligne.pasdecalais.fr/v2/ark:/64297/ea5d8eebcbfdd00a5dc5312b7792f1ea"
GALLICA = "https://gallica.bnf.fr/ark:/12148/bpt6k5619759j/f12.item.r=Rochefort"


def test_parse_ad59_with_qualifier():
    a = ark.parse(AD59)
    assert (a.naan, a.nom) == ("33518", "48150m2qjdhb")
    assert a.qualificatif == "7deaf652-1c2a-4f1e-9d0b-2b4a6c8e0f11"
    assert a.base == "ark:/33518/48150m2qjdhb" and a.service["code"] == "AD59"
    assert a.url() == AD59 and a.vue is None


def test_parse_ad62_http_and_bare():
    a = ark.parse(AD62)
    assert a.service["code"] == "AD62" and a.hote == "http://archivesenligne.pasdecalais.fr/v2"
    assert a.url() == AD62
    bare = ark.parse("ark:/64297/ea5d8eebcbfdd00a5dc5312b7792f1ea")
    assert bare.hote == "" and bare.url() == AD62  # hôte du service connu
    assert ark.same_resource(AD62, "ark:/64297/ea5d8eebcbfdd00a5dc5312b7792f1ea")


def test_parse_gallica_view_and_presentation():
    a = ark.parse(GALLICA)
    assert a.id == "ark:/12148/bpt6k5619759j/f12" and a.vue == 12
    assert ark_id(GALLICA) == "bpt6k5619759j"  # non-régression Gallica


def test_unknown_naan_falls_back_to_n2t():
    a = ark.parse("ark:/99999/abc-def/p1")
    assert a.nom == "abcdef" and a.service is None
    assert a.url() == "https://n2t.net/ark:/99999/abcdef/p1"
    assert a.to_dict()["url_n2t"] == a.url()


def test_parse_errors():
    for bad in ("", "https://exemple.org/registre", "ark:/12/x"):
        with pytest.raises(ark.ArkError):
            ark.parse(bad)
    assert ark.find("pas un ark") is None


def test_naan_registry():
    text = """# commentaire
naa:
who:    Bibliothèque nationale de France (=) BnF
what:   12148
when:   2001.03.01
where:  https://gallica.bnf.fr

naa:
who:    Exemple d'archives
what:   99999
where:  https://archives.exemple.org/
"""
    reg = ark.parse_naan_registry(text)
    assert reg["12148"] == {"nom": "Bibliothèque nationale de France", "sigle": "BnF", "hote": "https://gallica.bnf.fr"}
    assert reg["99999"]["hote"] == "https://archives.exemple.org"


def test_suggested_citation():
    s = ark.suggested_citation(ark.parse(GALLICA), "Journal de Rochefort")
    assert s["source"]["ark"] == "ark:/12148/bpt6k5619759j" and s["citation"]["page"] == "vue 12"


# ---------------------------------------------------------------------------- sources et citations par ARK

UID_DEATH = "11111111-1111-4111-8111-111111111113"


def test_source_from_ark_creates_depot_and_dedupes(app_famille):
    from genealogiste_mcp import server
    ops = [{"op": "ajouter_source", "ref": "s", "titre": "Somain, naissances 1926", "ark": AD59},
           {"op": "ajouter_source", "ref": "s2", "titre": "Somain, naissances 1926 (bis)",
            "url": "https://archivesdepartementales.lenord.fr/ark:/33518/48150m2qjdhb/autre-vue"},
           {"op": "ajouter_citation", "cible": {"type": "evenement", "uid": UID_DEATH},
            "citation": {"ark": AD59, "type_source": "originale", "information": "primaire"}}]
    p = server.arbre_proposer(ops, "Acte AD59", "Image consultée sur le site des AD du Nord.")
    assert "jeton" in p, p
    assert any("même ARK" in w for w in p["avertissements"])
    server.arbre_appliquer(p["jeton"])
    tree = app_famille.store.load()
    srcs = [s for s in tree.sources.values() if s.ark == "ark:/33518/48150m2qjdhb"]
    assert len(srcs) == 1
    s = srcs[0]
    assert s.url == "https://archivesdepartementales.lenord.fr/ark:/33518/48150m2qjdhb"
    assert tree.depots[s.depot].sigle == "AD59"
    ev = next(e for p in tree.personnes.values() for e in p.evenements if e.uid == UID_DEATH)
    c = ev.citations[-1]
    assert c.source == s.id and c.ark == "ark:/33518/48150m2qjdhb/7deaf652-1c2a-4f1e-9d0b-2b4a6c8e0f11"
    assert "_ARK ark:/33518/48150m2qjdhb" in app_famille.store.text()


def test_citation_ark_without_known_source_is_refused(app_famille):
    from genealogiste_mcp import server
    p = server.arbre_proposer([{"op": "ajouter_citation", "cible": {"type": "evenement", "uid": UID_DEATH},
                                "citation": {"ark": GALLICA}}], "t", "j")
    assert "ajouter_source" in p["erreur"]


def test_gallica_view_becomes_page(app_famille):
    from genealogiste_mcp import server
    ops = [{"op": "ajouter_source", "ref": "g", "titre": "Journal de Rochefort", "ark": GALLICA},
           {"op": "ajouter_citation", "cible": {"type": "evenement", "uid": UID_DEATH},
            "citation": {"source": "$g", "ark": GALLICA}}]
    server.arbre_appliquer(server.arbre_proposer(ops, "Presse", "Avis de décès lu sur Gallica.")["jeton"])
    tree = app_famille.store.load()
    ev = next(e for p in tree.personnes.values() for e in p.evenements if e.uid == UID_DEATH)
    assert ev.citations[-1].page == "vue 12"


def test_ark_round_trip_gramps(tree):
    from genealogiste_mcp.gramps.mapping import gramps_to_tree, tree_to_gramps
    from genealogiste_mcp.models import Citation
    s = next(iter(tree.sources.values()))
    s.ark = "ark:/33518/48150m2qjdhb"
    ev = next(e for p in tree.personnes.values() for e in p.evenements if e.uid == UID_DEATH)
    ev.citations.append(Citation(source=s.id, page="vue 3", ark="ark:/33518/48150m2qjdhb/abc"))
    back, _ = gramps_to_tree(tree_to_gramps(tree))
    assert back.sources[s.id].ark == s.ark
    ev2 = next(e for p in back.personnes.values() for e in p.evenements if e.uid == UID_DEATH)
    assert ev2.citations[-1].ark == "ark:/33518/48150m2qjdhb/abc"


# ---------------------------------------------------------------------------- résolution (respx)

import httpx  # noqa: E402
import respx  # noqa: E402


@respx.mock
def test_resolve_known_service_head_only(app):
    from genealogiste_mcp import server
    head = respx.head(AD59).mock(return_value=httpx.Response(200))
    r = server.ark_resoudre(AD59)
    assert head.called and r["disponibilite"] == {"accessible": True}
    assert r["service"]["code"] == "AD59" and r["citation_suggeree"]["source"]["depot"] == "AD59"
    assert server.journal_lister(source="ark")[-1]["operation"] == "resoudre"


@respx.mock
def test_resolve_gallica_iiif_and_fallback(app):
    from genealogiste_mcp import server
    respx.head("https://gallica.bnf.fr/ark:/12148/bpt6k5619759j/f12").mock(return_value=httpx.Response(404))
    respx.head("https://n2t.net/ark:/12148/bpt6k5619759j/f12").mock(return_value=httpx.Response(200))
    r = server.ark_resoudre("ark:/12148/bpt6k5619759j/f12")
    assert r["iiif_manifeste"] == "https://gallica.bnf.fr/iiif/ark:/12148/bpt6k5619759j/manifest.json"
    assert r["disponibilite"]["accessible"] is False and r["disponibilite"]["statut_http"] == 404
    assert r["disponibilite_n2t"] == {"accessible": True}


@respx.mock
def test_resolve_unknown_naan_uses_registry(app):
    from genealogiste_mcp import server
    respx.get(ark.NAAN_REGISTRY).mock(return_value=httpx.Response(
        200, text="naa:\nwho:    Archives d'exemple (=) AEX\nwhat:   99999\nwhere:  https://archives.exemple.org\n"))
    r = server.ark_resoudre("ark:/99999/abc", verifier=False)
    assert r["service"]["code"] == "AEX" and r["url"] == "https://archives.exemple.org/ark:/99999/abc"
    assert "disponibilite" not in r


def test_resolve_invalid(app):
    from genealogiste_mcp import server
    assert "erreur" in server.ark_resoudre("https://exemple.org/pas-d-ark", verifier=False)
