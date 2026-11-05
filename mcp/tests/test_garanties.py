"""#54 : garanties transversales, vérifiées par propriété plutôt que cas par cas.

- aucun outil réseau gardé n'envoie de requête pour un vivant, quel que soit le paramètre qui le désigne
  (catalogue outils.GARDE_VIVANTS, paramètres découverts par introspection) ;
- aucun export, dans aucun format, ni aucune note de recherche ne contient le nom d'un vivant ou d'une personne
  privée ;
- les autres garanties ont leur test dédié : chemins (test_chemins), réseau interne (test_reseau), concurrence
  et pannes (test_ecritures), intégrité après import et fusion (test_integrite), publication (test_publication).
"""

import inspect
from pathlib import Path

import httpx
import pytest
import respx

from genealogiste_mcp import outils, server
from genealogiste_mcp.privacy import hidden_ids, identifying_patterns, residues

VIVANT = {"nom": "Lucas MARTIN", "prenom": "Lucas", "texte": "Lucas MARTIN", "requete": 'SELECT ?p { ?p ?l "Lucas Martin" }',
          "personne": "I9"}
FACTICES = {"ark": "bpt6k1", "cle": "Martin-1", "job": "1", "texte": "registre", "nom": "Durand",
            "requete": "SELECT ?p {}"}


def _appels():
    for nom in sorted(outils.GARDE_VIVANTS - {"matchid_appariement_csv"}):
        sig = inspect.signature(getattr(server, nom))
        for param in sig.parameters.keys() & VIVANT.keys():
            kwargs = {p: FACTICES[p] for p, v in sig.parameters.items()
                      if v.default is inspect.Parameter.empty and p in FACTICES}
            if param == "prenom":
                kwargs.update(nom="Martin", prenom="Lucas")
            else:
                kwargs[param] = VIVANT[param]
            yield pytest.param(nom, kwargs, id=f"{nom}-{param}")


@pytest.mark.parametrize("nom,kwargs", list(_appels()))
def test_aucune_requete_pour_un_vivant(app_famille, nom, kwargs):
    with respx.mock(assert_all_called=False) as mock:
        route = mock.route().mock(return_value=httpx.Response(200, json={}))
        r = getattr(server, nom)(**kwargs)
    assert "refus" in r, (nom, kwargs, r)
    assert not route.called


def test_catalogue_couvre_tous_les_parametres_de_personne():
    assert list(_appels()), "aucun outil gardé"
    couverts = {n for n, *_ in (p.values for p in _appels())}
    assert couverts == outils.GARDE_VIVANTS - {"matchid_appariement_csv"}


@pytest.fixture
def avec_prive(app_famille):
    t = app_famille.store.load()
    t.personnes["I7"].prive = True  # défunt marqué privé : jamais publié non plus
    app_famille.store.write(t)
    app_famille.store.commit("prive")
    return app_famille


@pytest.mark.parametrize("format", ["gedcom7", "gedcom551", "geneweb", "gramps"])
def test_aucun_export_ne_nomme_une_personne_masquee(avec_prive, format):
    t = avec_prive.store.load()
    masques = hidden_ids(t)
    assert {"I9", "I7"} <= masques
    r = server.arbre_exporter(format=format)
    texte = Path(r["fichier"]).read_text(encoding="utf-8")
    assert residues(texte, identifying_patterns(t, masques)) == []


@pytest.mark.parametrize("format", ["mermaid_asc", "svg_asc", "fiche"])
@pytest.mark.parametrize("id", ["I9", "I3", "I1"])
def test_aucun_graphique_ni_fiche(avec_prive, format, id):
    t = avec_prive.store.load()
    r = server.arbre_exporter(format=format, id=id)
    texte = Path(r["fichier"]).read_text(encoding="utf-8")
    assert residues(texte, identifying_patterns(t, hidden_ids(t))) == []


def test_aucune_note_de_recherche(tmp_path, fixtures):
    import shutil

    from genealogiste_mcp.config import Config
    cfg = Config(data_dir=tmp_path / "d", cache_path=tmp_path / "c.sqlite", notes_dir=tmp_path / "vault")
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    try:
        shutil.copy(fixtures / "famille.ged", a.store.path)
        t = a.store.load()
        t.personnes["I7"].prive = True
        a.store.write(t)
        server.notes_generer()
        pats = identifying_patterns(t, hidden_ids(t))
        for f in (tmp_path / "vault").rglob("*.md"):
            assert residues(f.name + "\n" + f.read_text(encoding="utf-8"), pats) == [], f
    finally:
        server.set_app(None)
