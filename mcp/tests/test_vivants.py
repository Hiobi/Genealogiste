"""#34 : présomption de vie prudente (intervalles de dates, décès réfutés) ;
#35 : aucune donnée sur un vivant ne part vers un service externe, quel que soit l'outil ou l'argument."""

from datetime import date

import httpx
import pytest
import respx

from genealogiste_mcp import server
from genealogiste_mcp.models import Assertion, ChildLink, Event, Family, Name, Person, Tree
from genealogiste_mcp.privacy import external_guard, is_living

AUJOURDHUI = date(2026, 11, 5)


def _arbre(*evenements: Event, vivant: str = "") -> tuple[Tree, Person]:
    t = Tree()
    p = Person("I1", noms=[Name(prenoms="Lucas", nom="MARTIN")], evenements=list(evenements), vivant=vivant)
    t.personnes["I1"] = p
    return t, p


def _refute(e: Event) -> Event:
    e.statut_manuel = Assertion(statut="refute", justification="homonyme")
    return e


# ---------------------------------------------------------------- #34 intervalles

@pytest.mark.parametrize("naissance,vivant", [
    ("BEF 1970", True),             # borne haute 1969 : naissance récente possible
    ("AFT 1900", True),             # jusqu'à 2000
    ("BET 1900 AND 1930", True),    # borne haute 1930 : 96 ans
    ("BET 1880 AND 1920", False),   # borne haute 1920 : 106 ans
    ("ABT 1925", True),             # 1925 ± 2 : 1927
    ("ABT 1920", False),            # 1922 : 104 ans
    ("1927", True),
    ("1926", False),
    ("BEF 1900", False),
])
def test_intervalle_de_naissance(naissance, vivant):
    t, p = _arbre(Event("BIRT", date=naissance))
    assert is_living(t, p, AUJOURDHUI)["vivant"] is vivant


def test_deces_refute_ignore():
    t, p = _arbre(Event("BIRT", date="2000"), _refute(Event("DEAT", date="2001")))
    r = is_living(t, p, AUJOURDHUI)
    assert r["vivant"] is True
    assert any("réfuté" in c for c in r["contradictions"])


def test_deces_non_refute_suffit():
    t, p = _arbre(Event("BIRT", date="2000"), Event("DEAT", date="2001"))
    assert is_living(t, p, AUJOURDHUI)["vivant"] is False


def test_naissance_refutee_ignoree():
    t, p = _arbre(_refute(Event("BIRT", date="1800")), Event("OCCU", date="1990"))
    assert is_living(t, p, AUJOURDHUI)["vivant"] is True


def test_vivant_force_avec_deces_signale():
    t, p = _arbre(Event("DEAT", date="1950"), vivant="Y")
    r = is_living(t, p, AUJOURDHUI)
    assert r["vivant"] is True and r["contradictions"]


@pytest.mark.parametrize("mariage,vivant", [("1935", False), ("1945", True), ("BEF 1960", True)])
def test_borne_par_le_mariage(mariage, vivant):
    t, p = _arbre()
    p.fams = ["F1"]
    t.familles["F1"] = Family("F1", epoux="I1", evenements=[Event("MARR", date=mariage)])
    assert is_living(t, p, AUJOURDHUI)["vivant"] is vivant


def test_borne_par_un_parent_prudente():
    t, p = _arbre()
    pere = Person("I2", noms=[Name(prenoms="Jean", nom="MARTIN")], evenements=[Event("BIRT", date="1890")])
    t.personnes["I2"] = pere
    t.familles["F1"] = Family("F1", epoux="I2", enfants=[ChildLink("I1")])
    pere.fams, p.famc = ["F1"], ["F1"]
    # enfant né au plus tard en 1940 : présumé vivant
    assert is_living(t, p, AUJOURDHUI)["vivant"] is True


# ---------------------------------------------------------------- #35 politique (unité)

def test_garde_identifiant_inconnu(tree):
    assert "refus" in external_guard(tree, personne="I404")


def test_garde_nom_d_un_vivant(tree):
    assert external_guard(tree, nom="Martin", prenom="Lucas")["vivant"] == "I9"
    assert external_guard(tree, texte="Lucas MARTIN, cultivateur")["vivant"] == "I9"


def test_garde_laisse_passer(tree):
    assert external_guard(tree, nom="Martin") is None                      # nom seul
    assert external_guard(tree, nom="Martin", prenom="Pierre") is None     # défunts
    assert external_guard(tree, nom="Martin", prenom="Lucas", ne_vers="1820") is None  # homonyme ancien
    assert external_guard(tree, personne="I1", nom="Martin", prenom="Jean") is None


def test_garde_identifiant_defunt_mais_nom_d_un_vivant(tree):
    assert "refus" in external_guard(tree, personne="I1", nom="Martin", prenom="Lucas")


# ---------------------------------------------------------------- #35 outils (aucun appel réseau)

@pytest.fixture
def reseau():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.route().mock(return_value=httpx.Response(200, json={}))
        yield route


@pytest.mark.parametrize("appel", [
    lambda: server.matchid_recherche(nom="Martin", prenom="Lucas"),
    lambda: server.matchid_recherche(texte="Lucas Martin"),
    lambda: server.matchid_recherche(nom="Zzyzx", personne="I404"),
    lambda: server.matchid_recherche(nom="Martin", personne="I9"),
    lambda: server.wikitree_recherche(nom="Martin", prenom="Lucas"),
    lambda: server.gallica_recherche(texte="Lucas MARTIN"),
    lambda: server.gallica_recherche_document("bpt6k1", "Lucas Martin"),
    lambda: server.wikidata_personne(nom="Martin", prenom="Lucas"),
    lambda: server.wikidata_sparql('SELECT ?p WHERE { ?p rdfs:label "Lucas Martin"@fr }'),
    lambda: server.recherche_multi(nom="Martin", prenom="Lucas"),
])
def test_outils_refusent_sans_appel(app_famille, reseau, appel):
    r = appel()
    assert "refus" in r
    assert not reseau.called


def test_outil_homonyme_ancien_autorise(app_famille, reseau):
    reseau.mock(return_value=httpx.Response(200, json={"response": {"total": 0, "persons": []}}))
    r = server.matchid_recherche(nom="Martin", prenom="Lucas", ne_vers="1820")
    assert "refus" not in r and reseau.called


# ---------------------------------------------------------------- #35 appariement CSV ligne par ligne

COLONNES = {"lastName": "Nom", "firstName": "Prenom", "birthDate": "Naissance"}


def test_csv_lignes_vivantes_retirees(app_famille, reseau, tmp_path):
    f = tmp_path / "lot.csv"
    f.write_text("Nom;Prenom;Naissance\nMARTIN;Lucas;1990\nMARTIN;Jean;1820\n", encoding="utf-8")
    reseau.mock(return_value=httpx.Response(200, json={"id": "j1", "msg": "started"}))
    r = server.matchid_appariement_csv(str(f), COLONNES, sep=";")
    assert r["job"] == "j1" and r["lignes_exclues"] == [2]
    corps = reseau.calls[0].request.content
    assert b"Jean" in corps and b"Lucas" not in corps


def test_csv_tout_vivant_rien_envoye(app_famille, reseau, tmp_path):
    f = tmp_path / "lot.csv"
    f.write_text("Nom,Prenom,Naissance\nMARTIN,Lucas,1990\n", encoding="utf-8")
    r = server.matchid_appariement_csv(str(f), COLONNES)
    assert "refus" in r and r["lignes_exclues"] == [2]
    assert not reseau.called


def test_csv_colonne_absente(app_famille, reseau, tmp_path):
    f = tmp_path / "lot.csv"
    f.write_text("Nom,Prenom\nMARTIN,Jean\n", encoding="utf-8")
    r = server.matchid_appariement_csv(str(f), COLONNES)
    assert "erreur" in r and not reseau.called
