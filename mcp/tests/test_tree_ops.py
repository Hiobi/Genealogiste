import pytest

from genealogiste_mcp import server


def test_propose_does_not_write(app_famille):
    before = app_famille.store.text()
    p = server.arbre_proposer(
        [{"op": "ajouter_evenement", "cible": "I4", "evenement": {"type": "DEAT", "date": "vers 1880",
                                                                  "non_source": True, "motif": "tradition familiale"}}],
        "Décès de Jean MARTIN (I4)", "Indice tiré d'un recensement.")
    assert "jeton" in p and "+1 DEAT" in p["diff"] and "ABT 1880" in p["diff"]
    assert app_famille.store.text() == before


def test_apply_commits_with_justification(app_famille):
    p = server.arbre_proposer(
        [{"op": "ajouter_citation", "cible": {"type": "evenement", "uid": "11111111-1111-4111-8111-111111111113"},
          "citation": {"source": "S1", "page": "Décès 1885, acte n° 3", "type_source": "originale",
                       "information": "primaire"}}],
        "Acte de décès de Jean MARTIN", "Acte lu sur le registre des décès de Rochefort, 1885.")
    r = server.arbre_appliquer(p["jeton"])
    assert r["commit"]
    log = server.arbre_historique(1)[0]["message"]
    assert "Justification : Acte lu" in log and "2 E 299, Registres d'état civil de Rochefort" in log
    death = next(f for f in server.arbre_statut_preuve("I1") if f["fait"] == "DEAT")
    assert death["statut"] == "probable"


def test_token_single_use_and_stale(app_famille):
    p1 = server.arbre_proposer([{"op": "marquer_vivant", "id": "I7", "vivant": "N"}], "t", "j")
    p2 = server.arbre_proposer([{"op": "marquer_vivant", "id": "I6", "vivant": "N"}], "t", "j")
    assert "commit" in server.arbre_appliquer(p1["jeton"])
    assert "erreur" in server.arbre_appliquer(p1["jeton"])  # usage unique
    assert "a changé" in server.arbre_appliquer(p2["jeton"])["erreur"]  # base obsolète


def test_justification_required(app_famille):
    assert "erreur" in server.arbre_proposer([{"op": "marquer_vivant", "id": "I7", "vivant": "N"}], "t", " ")


def test_refs_and_validation(app_famille):
    p = server.arbre_proposer([
        {"op": "ajouter_source", "ref": "s", "titre": "Recensement 1856", "type_source": "originale"},
        {"op": "ajouter_personne", "ref": "x", "noms": [{"prenoms": "Anne", "nom": "MARTIN"}], "sexe": "F",
         "evenements": [{"type": "BIRT", "date": "12 vendémiaire an III",
                         "citations": [{"source": "$s", "page": "f° 3"}]}]},
        {"op": "lier_enfant", "famille": "F2", "enfant": "$x", "citations": [{"source": "$s", "page": "f° 3"}]},
    ], "Ajout d'Anne", "Recensement 1856.")
    assert p["references_creees"] == {"s": "S5", "x": "I10"}
    assert "FRENCH_R 12 VEND 3" in p["diff"]
    bad = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I1",
                                  "evenement": {"type": "BIRT", "citations": [{"source": "S99"}]}}], "t", "j")
    assert "source inconnue" in bad["erreur"]
    bad = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I1",
                                  "evenement": {"type": "BIRT", "date": "un jour",
                                                "citations": [{"source": "S1"}]}}], "t", "j")
    assert "Date non reconnue" in bad["erreur"]


def test_manual_status_only_negative(app_famille):
    r = server.arbre_proposer([{"op": "definir_statut", "cible": {"type": "evenement",
                               "uid": "33333333-3333-4333-8333-333333333332"}, "statut": "confirme",
                               "justification": "x"}], "t", "j")
    assert "calculés" in r["erreur"]
    p = server.arbre_proposer([{"op": "definir_statut", "cible": {"type": "evenement",
                               "uid": "33333333-3333-4333-8333-333333333332"}, "statut": "refute",
                               "justification": "Arbre en ligne sans source, contredit par l'acte n° 120"}],
                              "Réfutation", "L'acte de naissance prime.")
    server.arbre_appliquer(p["jeton"])
    births = [f for f in server.arbre_statut_preuve("I3") if f["fait"] == "BIRT"]
    assert {f["statut"] for f in births} == {"probable", "refute"}


def test_merge_never_automatic_and_requires_justification(app_famille):
    r = server.arbre_proposer([{"op": "fusionner_personnes", "conserver": "I1", "absorber": "I4"}], "t", "j")
    assert "justification obligatoire" in r["erreur"]
    p = server.arbre_proposer([{"op": "fusionner_personnes", "conserver": "I1", "absorber": "I4",
                                "justification": "test"}], "Fusion", "test")
    assert "-0 @I4@ INDI" in p["diff"]
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert "I4" not in t.personnes
    assert "F3" in t.personnes["I1"].famc
    assert t.familles["F3"].child("I1")


def test_merge_refuses_different_sex(app_famille):
    r = server.arbre_proposer([{"op": "fusionner_personnes", "conserver": "I1", "absorber": "I2",
                                "justification": "x"}], "t", "j")
    assert "Sexes différents" in r["erreur"]


def test_split(app_famille):
    p = server.arbre_proposer([{"op": "scinder_personne", "id": "I3", "ref": "n",
                                "evenements": ["33333333-3333-4333-8333-333333333332"],
                                "justification": "Deux Pierre distincts : celui de 1848 vient d'un autre arbre"}],
                              "Scission", "voir justification")
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    new = t.personnes[p["references_creees"]["n"]]
    assert [e.date for e in new.evenements] == ["1848"]
    assert [e.date for e in t.personnes["I3"].evenements] == ["3 MAY 1846"]


def test_import_gedcom_add_mode(app_famille, fixtures):
    p = server.arbre_importer_gedcom(str(fixtures / "legacy551.ged"), "ajouter")
    assert p["import"]["personnes"] == 1
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    imported = [x for x in t.personnes.values() if x.nom_principal.nom == "MARTINI"]
    assert imported and imported[0].id == "I10"
    assert imported[0].fams == ["F4"] and t.familles["F4"].epoux == "I10"


def test_new_coherence_alerts_reported(app_famille):
    p = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I4",
                                "evenement": {"type": "DEAT", "date": "1800",
                                              "citations": [{"source": "S1", "page": "x"}]}}], "t", "j")
    assert any(a["code"] == "deces_avant_naissance" for a in p["nouvelles_alertes_coherence"])


@pytest.mark.parametrize("fmt", ["gedcom7", "gedcom551", "gramps", "mermaid_asc", "mermaid_desc", "svg_asc",
                                 "svg_desc", "fiche"])
def test_exports(app_famille, fmt, tmp_path):
    out = server.arbre_exporter(fmt, str(tmp_path / f"x.{fmt}"), id="I1", generations=3)
    assert "erreur" not in out
    content = (tmp_path / f"x.{fmt}").read_text()
    assert content
    if fmt.startswith("gedcom"):
        assert "Lucas" not in content and "Vivant" in content  # vivant masqué
    if fmt == "gramps":
        assert "<people>" in content and 'cformat="French Republican"' in content
    if fmt == "mermaid_asc":
        assert "S2 --> S1" in content


def test_ascendance_sosa(app_famille):
    rows = server.arbre_ascendance("I3", 3)
    assert {r["sosa"]: r["id"] for r in rows} == {1: "I3", 2: "I1", 3: "I2", 4: "I6"}


def test_fiche_and_gaps(app_famille):
    fiche = server.arbre_fiche("I3")
    assert "contradictoire" in fiche and "Prochaines sources" in fiche
    assert "Vivant" in server.arbre_fiche("I9") or "vivante" in server.arbre_fiche("I9")
    lac = server.arbre_lacunes("I1")
    assert lac["plan"][0]["priorite"] <= 1
    assert any(x["fait"] == "DEAT" for x in lac["plan"])
    assert server.arbre_lacunes()["personnes_a_traiter"] > 0
