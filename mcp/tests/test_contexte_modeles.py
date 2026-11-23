"""Socle du contexte historique (#321) : formats Reference et ElementContexte."""

from __future__ import annotations

import pytest

from genealogiste_mcp.contexte import modeles as m
from genealogiste_mcp.contexte.modeles import ElementContexte, Identifiant, Reference, ReferenceInvalide


def _ref(**kw) -> dict:
    base = {"identifiant": {"type": "doi", "valeur": "10.3406/rnord.1975.3360"}, "titre": "Les mineurs",
            "auteurs": ["Dupont, Jean"], "publication": "Revue du Nord", "annee": 1975, "nature": "secondaire_savante",
            "type_document": "article", "service": "persee", "requete": "https://www.persee.fr/oai?verb=GetRecord",
            "consulte_le": "2026-11-23"}
    base.update(kw)
    return base


def test_constantes_partagees():
    assert m.ECHELLES == ("commune", "pays", "departement", "region", "nation", "international")
    assert m.NIVEAUX_RATTACHEMENT == ("atteste", "compatible", "non_demontre")
    assert m.NATURES == ("primaire", "secondaire_savante", "secondaire", "tertiaire", "index")
    assert m.TYPES_IDENTIFIANT == ("doi", "ark", "hal", "handle", "ppn", "lccn", "europeana", "url")
    assert set(m.TYPES_ELEMENT) == {"evenement", "economie", "demographie", "institution", "droit", "geographie",
                                    "culture"}


def test_reference_valide_et_aller_retour():
    r = Reference.from_dict(_ref())
    assert r.identifiant == Identifiant("doi", "10.3406/rnord.1975.3360")
    d = r.to_dict()
    assert d["identifiant"] == {"type": "doi", "valeur": "10.3406/rnord.1975.3360"}
    assert d["citation"]  # citation normée calculée, jamais stockée de mémoire
    assert d["lu"] == "notice_seule" and d["evaluation_par_les_pairs"] == "inconnu"
    assert Reference.from_dict(d) == r  # la citation renvoyée est recalculée, pas relue


@pytest.mark.parametrize("ident", [None, {}, {"type": "doi", "valeur": ""}, {"type": "", "valeur": "x"}])
def test_reference_sans_identifiant_refusee(ident):
    d = _ref(identifiant=ident)
    with pytest.raises(ReferenceInvalide, match="identifiant"):
        Reference.from_dict(d)


def test_reference_sans_cle_identifiant_refusee():
    d = _ref()
    del d["identifiant"]
    with pytest.raises(ReferenceInvalide, match="identifiant"):
        Reference.from_dict(d)


@pytest.mark.parametrize("champ, valeur", [
    ("nature", "inventee"), ("evaluation_par_les_pairs", "peut-etre"), ("acces", "payant"), ("lu", "survole"),
    ("type_document", "roman"), ("annee", "1975"), ("annee", 3000), ("consulte_le", "23/11/2026"),
    ("auteurs", "Dupont"), ("champ_inconnu", 1),
])
def test_reference_champ_invalide(champ, valeur):
    with pytest.raises(ReferenceInvalide):
        Reference.from_dict(_ref(**{champ: valeur}))


@pytest.mark.parametrize("brut, attendu", [
    ({"type": "doi", "valeur": "https://doi.org/10.3406/RNORD.1975.3360"}, ("doi", "10.3406/rnord.1975.3360")),
    ({"type": "doi", "valeur": "doi:10.1000/ABC"}, ("doi", "10.1000/abc")),
    ({"type": "ark", "valeur": "https://gallica.bnf.fr/ark:/12148/bpt6k123/f2"}, ("ark", "ark:/12148/bpt6k123/f2")),
    ({"type": "hal", "valeur": "https://hal.science/HAL-01234567v2"}, ("hal", "hal-01234567v2")),
    ({"type": "handle", "valeur": "https://hdl.handle.net/2042/12345"}, ("handle", "2042/12345")),
    ({"type": "ppn", "valeur": "https://www.sudoc.fr/02659968X"}, ("ppn", "02659968X")),
    ({"type": "lccn", "valeur": "sn 83030214"}, ("lccn", "sn83030214")),
    ({"type": "europeana", "valeur": "2048128/item_ABC"}, ("europeana", "/2048128/item_ABC")),
    ({"type": "url", "valeur": "https://www.persee.fr/doc/x"}, ("url", "https://www.persee.fr/doc/x")),
])
def test_identifiant_normalise(brut, attendu):
    i = Identifiant.from_dict(brut)
    assert (i.type, i.valeur) == attendu
    assert Identifiant.depuis_cle(i.cle) == i


@pytest.mark.parametrize("brut", [
    {"type": "doi", "valeur": "11.1/x"}, {"type": "ppn", "valeur": "12"}, {"type": "url", "valeur": "ftp://x"},
    {"type": "isbn", "valeur": "978"}, {"type": "hal", "valeur": "pas un hal"},
])
def test_identifiant_invalide(brut):
    with pytest.raises(ReferenceInvalide):
        Identifiant.from_dict(brut)


@pytest.mark.parametrize("texte, attendu", [
    ("doi:10.1000/abc", ("doi", "10.1000/abc")),
    ("10.1000/ABC", ("doi", "10.1000/abc")),
    ("https://doi.org/10.1000/abc", ("doi", "10.1000/abc")),
    ("ark:/12148/cb32", ("ark", "ark:/12148/cb32")),
    ("hal-01234567", ("hal", "hal-01234567")),
    ("ppn:02659968X", ("ppn", "02659968X")),
    ("https://hdl.handle.net/2042/1", ("handle", "2042/1")),
    ("https://www.persee.fr/doc/x", ("url", "https://www.persee.fr/doc/x")),
])
def test_identifiant_depuis_texte(texte, attendu):
    i = Identifiant.depuis_texte(texte)
    assert (i.type, i.valeur) == attendu


def test_identifiant_depuis_texte_inconnu():
    assert Identifiant.depuis_texte("une phrase") is None


def _element(**kw) -> dict:
    base = {"enonce": "Catastrophe de Courrières (1 099 morts)", "type": "evenement",
            "portee": {"lieu": "Courrières, Pas-de-Calais", "echelle": "commune", "de": 1906, "a": 1906},
            "source": {"citation": "…", "identifiant": "doi:10.3406/rnord.1975.3360",
                       "nature": "secondaire_savante", "consulte_le": "2026-11-23", "localisation": "p. 12"},
            "rattachement": {"personne": "I1", "niveau": "compatible", "justification": "mineur à Courrières"}}
    for k, v in kw.items():
        base[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base


def test_element_valide_et_aller_retour():
    e = ElementContexte.from_dict(_element())
    assert e.portee.de == 1906 and e.portee.a == 1906
    assert ElementContexte.from_dict(e.to_dict()) == e
    assert e.to_dict()["source"]["identifiant"] == "doi:10.3406/rnord.1975.3360"


def test_element_a_par_defaut_egal_a_de():
    d = _element()
    del d["portee"]["a"]
    assert ElementContexte.from_dict(d).portee.a == 1906


@pytest.mark.parametrize("modif", [
    {"enonce": ""}, {"type": "sport"}, {"portee": {"echelle": "canton"}}, {"portee": {"de": 1910, "a": 1900}},
    {"portee": {"de": "1906"}}, {"portee": {"lieu": ""}}, {"source": {"identifiant": ""}},
    {"source": {"identifiant": "sans type"}}, {"source": {"nature": "rumeur"}},
    {"rattachement": {"niveau": "certain"}},
])
def test_element_invalide(modif):
    with pytest.raises(ReferenceInvalide):
        ElementContexte.from_dict(_element(**modif))


def test_atteste_exige_une_citation_de_l_arbre():
    with pytest.raises(ReferenceInvalide, match="atteste"):
        ElementContexte.from_dict(_element(rattachement={"niveau": "atteste"}))
    e = ElementContexte.from_dict(_element(rattachement={"niveau": "atteste", "citation_arbre": "S7, liste des victimes"}))
    assert e.rattachement.niveau == "atteste"


def test_source_depuis_reference():
    r = Reference.from_dict(_ref(pages="45-67"))
    s = m.SourceElement.depuis_reference(r, localisation="p. 50")
    assert s.identifiant == "doi:10.3406/rnord.1975.3360"
    assert s.nature == "secondaire_savante" and s.consulte_le == "2026-11-23" and s.localisation == "p. 50"
    assert "Revue du Nord" in s.citation
