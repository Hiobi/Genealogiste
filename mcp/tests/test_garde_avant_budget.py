"""#211 (suite) : la garde « vivants » passe avant le budget d'enquête.

Pour les outils gardés mesurés par l'enveloppe générique (ServeurMCP.mesure), le contrôle de budget précède
l'exécution de l'outil ; sans pré-contrôle, une enquête bloquée consignerait au reste à faire les paramètres
d'une personne vivante. outils.GARDE_AVANT_BUDGET rejoue la garde de l'outil avant le budget : même refus, rien
consommé ni consigné. Données fictives (fixture famille.ged : I9 Lucas MARTIN, présumé vivant)."""

from __future__ import annotations

import inspect

import pytest
from test_budget_collecte import EXEMPLES, routes  # noqa: F401 — fixture

from genealogiste_mcp import outils, server

VIVANT = {"nom": "Lucas MARTIN", "prenom": "Lucas", "texte": "Lucas MARTIN",
          "requete": 'SELECT ?p { ?p ?l "Lucas Martin" }', "personne": "I9", "commune": "Lucas MARTIN"}


def _brute(nom: str):
    """Fonction d'origine de l'outil, sans l'enveloppe (garde d'écriture, budget, déjà fait)."""
    return getattr(server, nom).__wrapped__


def _appels_vivants():
    for nom, correspondance in sorted(outils.GARDE_AVANT_BUDGET.items()):
        for param in sorted(set(correspondance.values()) & VIVANT.keys()):
            kwargs = dict(EXEMPLES[nom])
            if param == "prenom":
                kwargs.update(nom="Martin", prenom="Lucas")
            else:
                kwargs[param] = VIVANT[param]
            yield pytest.param(nom, kwargs, id=f"{nom}-{param}")


def _bloquer(eid: str) -> None:
    assert "refus" not in server.geo_commune(nom="Lille", enquete=eid)
    server.geo_commune(nom="Douai", enquete=eid)  # 2e requête vers le même hôte : refusée, enquête bloquée
    assert server.enquete_etat(eid)["statut"] == "bloque"


# ---------------------------------------------------------------- invariants

def test_correspondance_couvre_les_outils_gardes_de_l_enveloppe():
    gardes_budgetes = outils.GARDE_VIVANTS & outils.BUDGET_ENQUETE
    enveloppe = {n for n in gardes_budgetes if "enquete" not in inspect.signature(_brute(n)).parameters}
    assert set(outils.GARDE_AVANT_BUDGET) == enveloppe
    # les autres outils gardés et budgétés déclarent enquete et appellent eux-mêmes la garde avant le budget
    assert gardes_budgetes - enveloppe == {"recherche_multi"}


@pytest.mark.parametrize("nom", sorted(outils.GARDE_AVANT_BUDGET))
def test_correspondance_identique_a_la_garde_de_l_outil(app, monkeypatch, nom):
    """L'appel _garde du pré-contrôle reçoit exactement les arguments de l'appel _garde de l'outil."""
    sig_garde = inspect.signature(server._garde)
    vus: list[dict] = []

    class Arret(Exception):
        pass

    def espion(*a, **kw):
        lies = sig_garde.bind(*a, **kw)
        lies.apply_defaults()
        vus.append(dict(lies.arguments))
        raise Arret

    fn = _brute(nom)
    params = inspect.signature(fn).parameters
    obligatoires = {p: EXEMPLES[nom][p] for p, v in params.items() if v.default is inspect.Parameter.empty}
    # valeur distincte par paramètre texte : révèle toute correspondance erronée
    complet = {**obligatoires, **{p: f"<{p}>" for p, v in params.items() if v.annotation == "str"}}
    monkeypatch.setattr(server, "_garde", espion)
    for kwargs in (complet, obligatoires):  # paramètres omis : défauts de la signature, comme dans l'outil
        vus.clear()
        with pytest.raises(Arret):
            fn(**kwargs)
        with pytest.raises(Arret):
            server._garde_avant_budget(nom, fn, kwargs)
        assert len(vus) == 2 and vus[0] == vus[1], vus


# ---------------------------------------------------------------- comportement

@pytest.mark.parametrize("nom,kwargs", list(_appels_vivants()))
def test_enquete_bloquee_refus_vivant_avant_budget(app_famille, routes, nom, kwargs):  # noqa: F811
    eid = server.enquete_ouvrir(f"Vivant {nom}", budget={"requetes_par_hote": 1})["id"]
    _bloquer(eid)
    avant = server.enquete_etat(eid)
    attendu = _brute(nom)(**kwargs)  # refus de la garde interne de l'outil
    assert "refus" in attendu and "statut" not in attendu
    appels = len(routes.calls)
    res = getattr(server, nom)(**kwargs, enquete=eid)
    assert res == attendu  # même refus, sans budget, enquete ni deja_fait
    assert len(routes.calls) == appels
    apres = server.enquete_etat(eid)
    assert apres["reste_a_faire"] == avant["reste_a_faire"]
    assert apres["requetes"] == avant["requetes"]
    assert apres["consomme"] == avant["consomme"]
    assert not [x for x in server.enquete_reprendre(eid)["a_faire"] if x.get("outil") == nom]


@pytest.mark.parametrize("nom", sorted(outils.GARDE_AVANT_BUDGET))
def test_enquete_bloquee_personne_decedee_refus_budget(app_famille, routes, nom):  # noqa: F811
    eid = server.enquete_ouvrir(f"Décédé {nom}", budget={"requetes_par_hote": 1})["id"]
    _bloquer(eid)
    kwargs = dict(EXEMPLES[nom])
    if "personne" in outils.GARDE_AVANT_BUDGET[nom].values():
        kwargs["personne"] = "I1"  # Jean MARTIN, décédé
    appels = len(routes.calls)
    res = getattr(server, nom)(**kwargs, enquete=eid)
    assert len(routes.calls) == appels
    assert res["statut"] == "bloque" and res["motif"] == "budget"
    assert any(x["outil"] == nom for x in server.enquete_etat(eid)["reste_a_faire"])


def test_sans_enquete_pas_de_pre_controle(app_famille, routes, monkeypatch):  # noqa: F811
    """Sans enquete, pas de budget : seule la garde interne de l'outil s'exécute."""
    vus = []
    garde = server._garde
    monkeypatch.setattr(server, "_garde", lambda *a, **kw: vus.append(1) or garde(*a, **kw))
    res = server.wikidata_personne(nom="Martin", prenom="Lucas")
    assert "refus" in res and len(vus) == 1
