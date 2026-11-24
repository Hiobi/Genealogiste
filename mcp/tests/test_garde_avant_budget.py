"""#211 (suite) : la garde « vivants » passe avant le budget d'enquête.

Pour les outils gardés mesurés par l'enveloppe générique (ServeurMCP.mesure), le contrôle de budget précède
l'exécution de l'outil ; sans pré-contrôle, une enquête bloquée consignerait au reste à faire les paramètres
d'une personne vivante. outils.GARDE_AVANT_BUDGET rejoue la garde de l'outil avant le budget : même refus, rien
consommé ni consigné. #347 : tous les appels _garde de l'outil sont rejoués (lieu compris), pas seulement le
premier. Données fictives (fixture famille.ged : I9 Lucas MARTIN, présumé vivant)."""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
from test_budget_collecte import EXEMPLES, routes  # noqa: F401 — fixture

from genealogiste_mcp import outils, server

VIVANT = {"nom": "Lucas MARTIN", "prenom": "Lucas", "texte": "Lucas MARTIN",
          "requete": 'SELECT ?p { ?p ?l "Lucas Martin" }', "personne": "I9", "commune": "Lucas MARTIN",
          "lieu": "Lucas MARTIN", "themes": "Lucas MARTIN", "sujet": "Lucas MARTIN"}


ARGS_GARDE = list(inspect.signature(server._garde).parameters)  # avant tout espion posé par un test


def _brute(nom: str):
    """Fonction d'origine de l'outil, sans l'enveloppe (garde d'écriture, budget, déjà fait)."""
    return getattr(server, nom).__wrapped__


def _params_gardes(nom: str) -> set[str]:
    """Paramètres de l'outil passés à la garde, tous appels _garde confondus."""
    return {param for appel in outils.GARDE_AVANT_BUDGET[nom] for param in appel.values()}


def _gardes_du_code(nom: str) -> list[dict[str, str]]:
    """Appels _garde écrits dans le corps de l'outil, dans l'ordre : {argument de _garde: paramètre de l'outil}.
    Tout argument doit être un paramètre de l'outil passé tel quel (sinon la déclaration ne peut pas le décrire)."""
    fn = _brute(nom)
    params = set(inspect.signature(fn).parameters)
    arbre = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    appels = sorted((n for n in ast.walk(arbre)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_garde"),
                    key=lambda n: (n.lineno, n.col_offset))
    gardes = []
    for appel in appels:
        lies = [*zip(ARGS_GARDE, appel.args, strict=False), *((k.arg, k.value) for k in appel.keywords)]
        for arg, valeur in lies:
            assert arg in ARGS_GARDE, f"{nom} : argument de _garde inattendu ({arg})"
            assert isinstance(valeur, ast.Name) and valeur.id in params, \
                f"{nom} : _garde({arg}=…) ne reçoit pas un paramètre de l'outil tel quel"
        gardes.append({arg: valeur.id for arg, valeur in lies})
    return gardes


def _appels_vivants():
    for nom in sorted(outils.GARDE_AVANT_BUDGET):
        for param in sorted(_params_gardes(nom) & VIVANT.keys()):
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
def test_correspondance_declare_chaque_garde_du_code(nom):
    """Structurel (#347) : chaque appel _garde du corps de l'outil, avec chacun de ses paramètres, figure dans
    la déclaration, dans le même ordre ; un appel ajouté dans l'outil sans y être déclaré échoue ici."""
    gardes = _gardes_du_code(nom)
    assert gardes, f"{nom} : aucun appel _garde direct dans le corps de l'outil"
    assert list(outils.GARDE_AVANT_BUDGET[nom]) == gardes


@pytest.mark.parametrize("nom", sorted(outils.GARDE_AVANT_BUDGET))
def test_correspondance_identique_a_la_garde_de_l_outil(app, monkeypatch, nom):
    """Les appels _garde du pré-contrôle reçoivent exactement les arguments des appels _garde de l'outil, un
    à un et dans l'ordre (l'espion laisse passer les premiers appels pour atteindre les suivants)."""
    sig_garde = inspect.signature(server._garde)
    vus: list[dict] = []
    limite = 0

    class Arret(Exception):
        pass

    def espion(*a, **kw):
        lies = sig_garde.bind(*a, **kw)
        lies.apply_defaults()
        vus.append(dict(lies.arguments))
        if len(vus) == limite:
            raise Arret
        return None

    def releve(appeler) -> list[dict]:
        vus.clear()
        with pytest.raises(Arret):
            appeler()
        return list(vus)

    fn = _brute(nom)
    params = inspect.signature(fn).parameters
    obligatoires = {p: EXEMPLES[nom][p] for p, v in params.items() if v.default is inspect.Parameter.empty}
    # valeur distincte par paramètre texte : révèle toute correspondance erronée
    complet = {**obligatoires, **{p: f"<{p}>" for p, v in params.items() if v.annotation == "str"}}
    monkeypatch.setattr(server, "_garde", espion)
    for kwargs in (complet, obligatoires):  # paramètres omis : défauts de la signature, comme dans l'outil
        for limite in range(1, len(_gardes_du_code(nom)) + 1):
            outil = releve(lambda: fn(**kwargs))  # noqa: B023 — appelé dans l'itération
            pre = releve(lambda: server._garde_avant_budget(nom, fn, kwargs))  # noqa: B023
            assert len(outil) == limite and outil == pre, (outil, pre)


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
    if "personne" in _params_gardes(nom):
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
