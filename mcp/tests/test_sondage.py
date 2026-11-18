"""#156 : sondage guidé d'un registre (interpolation puis dichotomie sur les dates lues par le modèle).

Registres simulés : une date de premier acte par vue, densité irrégulière (mois creux et chargés). Le
« modèle » lit la vue proposée et renvoie sa date ; aucun réseau."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from genealogiste_mcp import server, sondage

ARK = "ark:/33518/registresimule"


def registre(n: int, debut: date, fin: date, graine: int) -> list[date]:
    """Date du premier acte de chaque vue : vues de densité irrégulière (rapport 1 à 10)."""
    r = random.Random(graine)
    poids = [r.uniform(0.3, 3) for _ in range(n)]
    total, jours, acc, out = sum(poids), (fin - debut).days, 0.0, []
    for p in poids:
        out.append(debut + timedelta(days=int(acc / total * jours)))
        acc += p
    return out


def trois_series(graine: int) -> tuple[list[str], list[date | None]]:
    """Registre de 1 000 vues : naissances, mariages, décès de 1862 à la suite, tables en fin de volume."""
    r = random.Random(graine)
    n, m, d = r.randint(300, 500), r.randint(100, 200), r.randint(250, 400)
    types = ["naissance"] * n + ["mariage"] * m + ["deces"] * d + ["table"] * (1000 - n - m - d)
    an = (date(1862, 1, 1), date(1862, 12, 31))
    dates = registre(n, *an, graine) + registre(m, *an, graine + 1) + registre(d, *an, graine + 2)
    return types, dates + [None] * (1000 - n - m - d)


def lire(dates, v, types=None) -> dict:
    d = dates[v - 1]
    out = {"vue": v, "date": d.isoformat() if d else ""}
    if types:
        out["type"] = types[v - 1]
    return out


def premiere_vue(dates, cible: date) -> int:
    return next(i + 1 for i, d in enumerate(dates) if d and d >= cible)


# ---------------------------------------------------------------------------- calcul pur

@pytest.mark.parametrize("graine", range(40))
def test_registre_de_1000_vues_localise_en_10_lectures(graine):
    dates = registre(1000, date(1860, 1, 1), date(1869, 12, 31), graine)
    cible = dates[random.Random(graine + 1000).randrange(1000)]
    lectures: list[dict] = []
    while True:
        plan = sondage.planifier(1000, cible.isoformat(), lectures, periode="1860-1869")
        if plan["arret"]:
            break
        assert plan["prochaine_vue"] not in {x["vue"] for x in lectures}  # jamais une vue déjà lue
        lectures.append(lire(dates, plan["prochaine_vue"]))
        assert len(lectures) <= 10, plan
    assert plan["arret"] == "localise"
    assert premiere_vue(dates, cible) in plan["vues"] or premiere_vue(dates, cible) - 1 in plan["vues"]


def test_interpolation_puis_dichotomie():
    """Interpolation d'abord ; dichotomie quand une interpolation n'a pas divisé l'intervalle par deux."""
    # registre très irrégulier : 900 vues pour 1860, 100 vues pour 1861-1869
    dates = registre(900, date(1860, 1, 1), date(1860, 12, 31), 1) + registre(100, date(1861, 1, 1),
                                                                               date(1869, 12, 31), 2)
    cible, lectures, methodes = date(1860, 6, 15), [], []
    while not (plan := sondage.planifier(1000, cible.isoformat(), lectures, periode="1860-1869"))["arret"]:
        methodes.append(plan["methode"])
        lectures.append(lire(dates, plan["prochaine_vue"]))
    assert methodes[0] == "interpolation" and "dichotomie" in methodes
    assert plan["arret"] == "localise" and len(lectures) <= 20  # garde-fou : au pire deux fois la dichotomie


def test_sans_periode_dichotomie_d_abord():
    plan = sondage.planifier(1000, "1862-03-14", [])
    assert plan["methode"] == "dichotomie" and plan["prochaine_vue"] == 500


@pytest.mark.parametrize("graine", range(30))
def test_trois_series_section_trouvee_avant_la_dichotomie(graine):
    types, dates = trois_series(graine)
    debut_m = types.index("mariage") + 1
    cible = dates[debut_m - 1 + random.Random(graine).randrange(types.count("mariage"))]
    lectures, methodes = [], []
    while not (plan := sondage.planifier(1000, cible.isoformat(), lectures, "mariage", "1862"))["arret"]:
        methodes.append(plan["methode"])
        lectures.append(lire(dates, plan["prochaine_vue"], types))
        assert len(lectures) <= 15
    premiere = next(i for i, x in enumerate(lectures) if x["type"] == "mariage")
    assert "dichotomie" not in methodes[:premiere + 1], methodes  # section d'abord
    assert plan["arret"] == "localise"
    vues = plan["vues"]
    assert all(types[v - 1] == "mariage" for v in vues)
    attendue = next(i + 1 for i in range(debut_m - 1, 1000) if types[i] == "mariage" and dates[i] >= cible)
    assert attendue in vues or attendue - 1 in vues


def test_section_bornee_par_les_autres_series():
    plan = sondage.planifier(1000, "1862-06-01", [{"vue": 300, "date": "1862-08-01", "type": "N"},
                                                  {"vue": 800, "date": "1862-02-01", "type": "décès"}], "mariage")
    assert plan["phase"] == "section" and plan["section"] == [301, 799] and plan["prochaine_vue"] == 550
    absente = sondage.planifier(10, "1862", [{"vue": 5, "type": "naissance"}, {"vue": 6, "type": "deces"}], "M")
    assert absente["arret"] == "absent" and "section vide" in absente["motif"]


def test_types_ignores_pour_les_actes_meles():
    lectures = [{"vue": 500, "date": "1862-06-01", "type": "bapteme"}]
    meles = sondage.planifier(1000, "1862-03-01", lectures, "sepulture", "1860-1869", ordre_series=[])
    assert meles["phase"] == "date" and meles["bornes"] == [1, 499]


def test_absent_quand_les_dates_encadrent_la_cible():
    lectures = [{"vue": 40, "date": "1862-03-02", "date_fin": "1862-03-12"}, {"vue": 41, "date": "1862-03-16"}]
    plan = sondage.planifier(100, "1862-03-14", lectures, periode="1862")
    assert plan["arret"] == "absent" and plan["encadrement"] == [40, 41]


def test_date_dans_la_vue_et_actes_du_meme_jour():
    dans = sondage.planifier(100, "14 mars 1862", [{"vue": 40, "date": "1862-03-10", "date_fin": "1862-03-20"}],
                             periode="1862")
    assert dans["arret"] == "localise" and dans["vues"] == [40]
    # premier acte de la vue 41 le jour cible : l'acte peut finir la vue 40, déjà lue (sans date_fin)
    jour = sondage.planifier(100, "1862-03-14", [{"vue": 40, "date": "1862-03-10"}, {"vue": 41, "date": "1862-03-14"}],
                             periode="1862")
    assert jour["arret"] == "localise" and jour["vues"] == [40, 41]


def test_lectures_et_dates_illisibles_refusees():
    with pytest.raises(sondage.SondageError, match="date_cible"):
        sondage.planifier(100, "bientôt", [])
    with pytest.raises(sondage.SondageError, match="nb_vues"):
        sondage.planifier(0, "1862", [])
    with pytest.raises(sondage.SondageError, match="au-delà"):
        sondage.planifier(100, "1862", [{"vue": 101, "date": "1862"}])
    with pytest.raises(sondage.SondageError, match="antérieure"):
        sondage.lecture({"vue": 3, "date": "1862-05-01", "date_fin": "1862-04-01"})
    assert sondage.planifier(100, "an XII", [], periode=["an XI", "an XIII"])["prochaine_vue"]


# ---------------------------------------------------------------------------- outil et état d'enquête

def sonder(eid, cible, **kw):
    return server.archives_sonder(ARK, cible, enquete=eid, **kw)


def test_sondage_note_dans_l_enquete_et_repris(app):
    dates = registre(1000, date(1860, 1, 1), date(1869, 12, 31), 7)
    cible = dates[612]
    eid = server.enquete_ouvrir("Naissance simulée")["id"]
    plan = sonder(eid, cible.isoformat(), type_acte="naissance", nb_vues=1000, periode="1860-1869")
    assert plan["action"]["outil"] == "archive_image"
    assert plan["action"]["parametres"] == {"source": ARK, "page": plan["prochaine_vue"], "largeur": 800,
                                            "gris": True, "enquete": eid}
    assert sonder(eid, cible.isoformat(), type_acte="N")["prochaine_vue"] == plan["prochaine_vue"]  # reprise
    n = 0
    while not plan["arret"]:
        lecture = {**lire(dates, plan["prochaine_vue"]), "type": "naissance"}
        plan = sonder(eid, cible.isoformat(), type_acte="naissance", lecture=lecture)
        n += 1
    assert plan["arret"] == "localise" and n <= 10
    assert plan["action"]["parametres"]["page"] == plan["vues"][0] and "conclusion" in plan["consigne"]
    reg = server.enquete_etat(eid)["registres"][0]
    assert reg["nb_vues"] == 1000 and reg["periode"] == "1860-1869"
    assert len(reg["lectures"]) == n and reg["sondages"][0]["historique"] == plan["sondage"]["historique"]
    assert reg["sondages"][0]["type_acte"] == "naissance"
    fin = sonder(eid, cible.isoformat(), type_acte="naissance", conclusion="trouve",
                 lecture={"vue": plan["vues"][0], "date": cible.isoformat(), "type": "naissance", "numero": "45"})
    assert fin["arret"] == "trouve"
    reg = server.enquete_etat(eid)["registres"][0]
    assert reg["statut"] == "trouve" and "acte trouvé" in reg["verdict"]


def test_negatif_journalise_avec_les_bornes(app):
    eid = server.enquete_ouvrir("Mariage absent")["id"]
    sonder(eid, "1862-03-14", nb_vues=100, periode="1862",
           lecture={"vue": 40, "date": "1862-03-02", "date_fin": "1862-03-12"})
    plan = sonder(eid, "1862-03-14", lecture={"vue": 41, "date": "1862-03-16"})
    assert plan["arret"] == "absent" and plan["journal_cree"] and "négatif journalisé" in plan["consigne"]
    etat = server.enquete_etat(eid)
    reg = etat["registres"][0]
    assert reg["statut"] == "negatif" and "bornes examinées [40, 41]" in reg["verdict"]
    assert reg["sondages"][0]["statut"] == "negatif" and reg["sondages"][0]["journal"] == reg["journal"]
    entree = next(x for x in server.journal_lister() if x["id"] == plan["journal_cree"][0])
    assert entree["statut"] == "negatif" and "bornes examinées" in entree["resume"] and "40, 41" in entree["resume"]
    assert etat["coherence_journal"] == "ok"


def test_arret_budget(app):
    eid = server.enquete_ouvrir("Sondage borné")["id"]
    sonder(eid, "1865", nb_vues=1000, periode="1860-1869")
    plan = sonder(eid, "1865", lecture={"vue": 10, "date": "1860-02-01"}, max_lectures=1)
    assert plan["arret"] == "budget" and "action" not in plan and "accord" in plan["consigne"]
    server.enquete_noter(eid, statut="bloque")
    plan = sonder(eid, "1865")
    assert plan["arret"] == "budget" and "bloquée" in plan["motif"]
    images = server.enquete_ouvrir("Sans image", budget={"images": 1})["id"]
    app.enquetes.apres_collecte(images, {}, 1)
    assert sonder(images, "1865", nb_vues=1000)["arret"] == "budget"


def test_sans_enquete_rien_n_est_note(app):
    plan = server.archives_sonder(ARK, "1862-03-14", nb_vues=100, periode="1862",
                                  lectures=[{"vue": 20, "date": "1862-02-20"}], lecture={"vue": 30, "date": "1862-04-01"})
    assert plan["bornes"] == [20, 29] and "enquete" not in plan["action"]["parametres"]
    assert plan["alternative"]["outil"] == "archives_planche"
    assert plan["alternative"]["parametres"] == {"source": ARK, "de": 20, "a": 29, "bandeau": "pct:0,0,100,35"}
    assert server.enquete_etat()["enquetes"] == []
    assert "erreur" in server.archives_sonder(ARK, "1862")  # nb_vues inconnu
    assert "erreur" in server.archives_sonder(ARK, "1862", nb_vues=10, lecture={"vue": 2, "date": "demain"})


def test_erreurs_enquete(app):
    assert "erreur" in sonder("inconnue", "1862", nb_vues=10)
    eid = server.enquete_ouvrir("Erreurs")["id"]
    assert "nb_vues" in sonder(eid, "1862")["erreur"]
    assert "au-delà" in sonder(eid, "1862", nb_vues=10, lecture={"vue": 11, "date": "1862"})["erreur"]
    assert "conclusion" in sonder(eid, "1862", nb_vues=10, conclusion="peut-etre")["erreur"]
    assert "date_cible" in sonder(eid, "jamais", nb_vues=10)["erreur"]


def test_periode_du_registre(app):
    eid = server.enquete_ouvrir("Période")["id"]
    assert "periode" in sonder(eid, "1862", nb_vues=100, periode="autrefois")["erreur"]
    # période notée par archives_naviguer (bornes de la visionneuse) : reprise pour l'interpolation
    server.enquete_noter(eid, registre={"source": ARK, "nb_vues": 100, "periode": ["1860-01-01", "1869-12-31"]})
    plan = sonder(eid, "1865-01-01")
    assert plan["methode"] == "interpolation" and 45 <= plan["prochaine_vue"] <= 55
    server.enquete_noter(eid, registre={"source": ARK, "periode": "illisible"})
    plan = sonder(eid, "1865-01-01")
    assert plan["methode"] == "dichotomie" and any("Période" in x for x in plan["avertissements"])
