"""Notes de recherche Markdown : génération, idempotence, texte libre préservé, vivants masqués, hook."""

import re
import shutil
from datetime import date

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.config import Config


@pytest.fixture
def napp(tmp_path, fixtures):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", notes_dir=tmp_path / "vault",
                 sosa_racine="I3")
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    a.notes.today = lambda: date(2026, 11, 4)
    yield a
    server.set_app(None)


def snapshot(root):
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.md"))}


def test_disabled_without_directory(app):
    assert "GENEALOGISTE_NOTES_DIR" in server.notes_generer()["erreur"]


def test_generate_person_note_with_facts_and_links(napp):
    r = server.notes_generer()
    vault = napp.config.notes_dir
    assert "index.md" in snapshot(vault) and r["ecrites"]
    jean = next((vault / "personnes").glob("I1 - *.md"))
    assert jean.name == "I1 - Jean MARTIN (1820-1885).md"
    text = jean.read_text(encoding="utf-8")
    assert text.startswith("---\nid: \"I1\"\ntype: \"personne\"\n")
    assert "sosa: 2" in text  # père de la racine I3
    assert "<!-- sosa:debut faits -->" in text and "| Naissance |" in text and "Preuve" not in text.split("---")[1]
    assert "## Notes libres" in text
    # tous les wikilinks pointent vers un fichier existant
    names = {p.stem for p in vault.rglob("*.md")}
    for link in re.findall(r"\[\[([^\]|]+)", "".join(snapshot(vault).values())):
        assert link in names, link


def test_regeneration_is_idempotent_and_keeps_free_text(napp):
    server.notes_generer()
    vault = napp.config.notes_dir
    jean = next((vault / "personnes").glob("I1 - *.md"))
    text = jean.read_text(encoding="utf-8")
    fm_end = text.index("\n---\n", 4)  # propriété ajoutée dans Obsidian : en fin de frontmatter
    text = text[:fm_end] + '\nmes_tags: ["à creuser"]' + text[fm_end:]
    text += "\nHypothèse : frère cadet parti à Rochefort.\n"
    jean.write_text(text, encoding="utf-8")
    before = snapshot(vault)
    napp.notes.today = lambda: date(2027, 1, 1)
    r = server.notes_generer()
    assert r["ecrites"] == [] and snapshot(vault) == before  # aucun diff, date inchangée
    # modification de l'arbre : sections régénérées, texte libre et propriété manuelle conservés
    p = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I1", "evenement": {
        "type": "OCCU", "valeur": "charpentier", "non_source": True, "motif": "tradition familiale"}}], "Métier", "j")
    server.arbre_appliquer(p["jeton"])
    after = jean.read_text(encoding="utf-8")
    assert "charpentier" in after and "frère cadet parti à Rochefort" in after
    assert 'mes_tags: ["à creuser"]' in after and 'mis_a_jour: "2027-01-01"' in after


def test_living_masked_by_default(napp):
    server.notes_generer()
    vault = napp.config.notes_dir
    living = [p for p in (vault / "personnes").glob("*.md") if "vivant" in p.name]
    assert living, "la fixture contient une personne présumée vivante"
    t = living[0].read_text(encoding="utf-8")
    assert "vivant: true" in t and "fiche masquée" in t and "| Naissance |" not in t
    assert "erreur" in server.notes_ajouter(living[0].name.split(" - ")[0], "piste", "piste")


def test_add_entry_in_free_text(napp):
    r = server.notes_ajouter("I1", "Écrire à la mairie de Rochefort pour l'acte de 1885", "courrier")
    assert r["section"] == "Courriers"
    server.notes_ajouter("I1", "Deuxième courrier", "courrier")
    server.notes_ajouter("I1", "Vérifier le recensement 1851", "a_faire")
    text = server.notes_lire("I1")["contenu"]
    free = text.split("## Notes libres", 1)[1]
    assert free.index("### Courriers") < free.index("2026-11-04 : Écrire") < free.index("Deuxième courrier") \
        < free.index("### À faire")
    assert "erreur" in server.notes_ajouter("I1", "x", "inconnue")


def test_journal_hook_lists_research(napp):
    server.notes_generer("I1")
    server.journal_ajouter("AD17", "consultation", "negatif", "Rien dans les tables décennales 1883-1892",
                           personne="I1")
    text = server.notes_lire("I1")["contenu"]
    assert "Rien dans les tables décennales" in text and "## Recherches (journal)" in text


def test_unknown_id(napp):
    assert "inconnu" in server.notes_lire("I999")["erreur"]


# ---------------------------------------------------------------- #36 remasquage

def test_remasquage_retire_les_donnees_generees(napp):
    napp.notes.vivants = "complet"
    server.notes_generer()
    vault = napp.config.notes_dir
    f = next((vault / "personnes").glob("I9 - *.md"))
    assert "Lucas" in f.name and "1990" in f.read_text(encoding="utf-8")
    texte = f.read_text(encoding="utf-8").replace("---\n", "---\nma_cle: rencontre 2024\n", 1)
    f.write_text(texte + "\nAppel téléphonique avec Lucas.\n", encoding="utf-8")

    napp.notes.vivants = "masquer"
    r = server.notes_generer()
    apres = f.read_text(encoding="utf-8")
    entete, corps = apres.split("\n---\n", 1)
    assert "vivant: true" in entete
    for s in ("nom:", "naissance:", "1990", "Faits et statut", "Sources"):
        assert s not in entete + corps.split("## Notes libres")[0], s
    assert corps.lstrip().startswith("# I9 (personne vivante)")
    assert "ma_cle: rencontre 2024" in entete and "Appel téléphonique" in corps  # manuel : conservé…
    alertes = "\n".join(r.get("alertes", []))
    assert f.name in alertes and "renommer" in alertes                             # …mais signalé
    assert "saisis à la main" in alertes
    assert f.exists()                                                              # pas de renommage


def test_personne_privee_masquee_dans_les_notes(napp):
    t = napp.tree()
    t.personnes["I1"].prive = True
    napp.store.write(t)
    server.notes_generer()
    f = next((napp.config.notes_dir / "personnes").glob("I1 - *.md"))
    assert "Faits et statut" not in f.read_text(encoding="utf-8")


def test_date_corrigee_renomme_fiche_et_liens_sans_perdre_texte_libre(napp):
    server.notes_generer()
    vault = napp.config.notes_dir
    ancienne = next((vault / "personnes").glob("I1 - *.md"))
    ancien_nom = ancienne.stem
    ancienne.write_text(ancienne.read_text(encoding="utf-8") + "\nNote personnelle à conserver.\n", encoding="utf-8")
    tree = napp.tree()
    tree.personnes["I1"].events("DEAT")[0].date = "BEF 1925"
    napp.store.write(tree)
    server.notes_generer()
    nouvelle = next((vault / "personnes").glob("I1 - *.md"))
    assert "av 1925" in nouvelle.stem
    assert not ancienne.exists()
    assert "Note personnelle à conserver." in nouvelle.read_text(encoding="utf-8")
    assert ancien_nom not in "\n".join(snapshot(vault).values())


def _modifier_deces(napp, value="BEF 1925"):
    tree = napp.tree()
    tree.personnes["I1"].events("DEAT")[0].date = value
    napp.store.write(tree)


def test_ancienne_fiche_1874_migre_meme_sur_generation_ciblee(napp):
    server.notes_generer()
    vault = napp.config.notes_dir
    ancienne = next((vault / "personnes").glob("I1 - *.md"))
    legacy = ancienne.with_name("I1 - Jean MARTIN (1820-~1874).md")
    ancienne.rename(legacy)
    # Reproduit aussi les références présentes dans les anciens vaults.
    for path in vault.rglob("*.md"):
        path.write_text(path.read_text(encoding="utf-8").replace(ancienne.stem, legacy.stem), encoding="utf-8")
    _modifier_deces(napp)
    res = server.notes_generer("I1")
    assert res["renommees"] == [{"ancien": "personnes/" + legacy.name,
                                  "nouveau": "personnes/I1 - Jean MARTIN (1820-av 1925).md"}]
    assert not legacy.exists()
    assert legacy.stem not in "\n".join(snapshot(vault).values())
    avant = snapshot(vault)
    assert server.notes_generer("I1")["ecrites"] == []
    assert snapshot(vault) == avant


def test_renommage_apres_application_maintient_texte_et_proprietes(napp):
    server.notes_generer()
    vault = napp.config.notes_dir
    ancienne = next((vault / "personnes").glob("I1 - *.md"))
    text = ancienne.read_text(encoding="utf-8").replace('type: "personne"', 'type: "personne"\nmes_tags: ["à lire"]')
    ancienne.write_text(text + "\nTexte libre de test.\n", encoding="utf-8")
    uid = napp.tree().personnes["I1"].events("DEAT")[0].uid
    proposition = server.arbre_proposer([{"op": "modifier_evenement", "uid": uid, "champs": {"date": "1887"}}],
                                       "Correction fictive", "Contrôle de recette")
    assert ancienne.exists()  # préparer n'écrit pas les notes
    resultat = server.arbre_appliquer(proposition["jeton"])
    assert not resultat.get("notes", {}).get("erreurs"), resultat
    nouvelle = next((vault / "personnes").glob("I1 - *.md"))
    assert nouvelle.name == "I1 - Jean MARTIN (1820-1887).md"
    assert not ancienne.exists()
    assert 'mes_tags: ["à lire"]' in nouvelle.read_text(encoding="utf-8")
    assert "Texte libre de test." in nouvelle.read_text(encoding="utf-8")
    assert ancienne.stem not in "\n".join(snapshot(vault).values())


def test_collision_renommage_ne_modifie_aucun_fichier(napp):
    server.notes_generer()
    _modifier_deces(napp)
    vault = napp.config.notes_dir
    destination = vault / "personnes/I1 - Jean MARTIN (1820-av 1925).md"
    destination.write_text("Document personnel préexistant", encoding="utf-8")
    avant = snapshot(vault)
    assert "erreur" in server.notes_generer()
    assert snapshot(vault) == avant


def test_renommage_refuse_symlink_source(napp, tmp_path):
    server.notes_generer()
    _modifier_deces(napp)
    path = next((napp.config.notes_dir / "personnes").glob("I1 - *.md"))
    externe = tmp_path / "externe.md"
    externe.write_bytes(path.read_bytes())
    original = externe.read_bytes()
    path.unlink()
    path.symlink_to(externe)
    assert "erreur" in server.notes_generer("I1")
    assert externe.read_bytes() == original and path.is_symlink()


def test_nom_personnalise_conserve(napp):
    server.notes_generer()
    path = next((napp.config.notes_dir / "personnes").glob("I1 - *.md"))
    perso = path.with_name("I1 - Ma fiche personnelle.md")
    path.rename(perso)
    _modifier_deces(napp)
    res = server.notes_generer("I1")
    assert not res.get("renommees")
    assert perso.exists()
    assert "BEF 1925" in perso.read_text(encoding="utf-8")


def test_intervalle_nom_fiche_portable(napp):
    _modifier_deces(napp, "BET 1880 AND 1890")
    server.notes_generer("I1")
    path = next((napp.config.notes_dir / "personnes").glob("I1 - *.md"))
    assert path.name == "I1 - Jean MARTIN (1820-1880 à 1890).md"


def test_echec_mise_a_jour_liens_restaure_fichiers(napp, monkeypatch):
    from genealogiste_mcp import notes

    server.notes_generer()
    _modifier_deces(napp)
    vault = napp.config.notes_dir
    avant = snapshot(vault)
    original = notes.ecrire_atomique
    appels = []

    def echouer_une_fois(path, text):
        appels.append(path)
        if len(appels) == 2:
            raise OSError("Panne simulée sur les liens")
        original(path, text)

    monkeypatch.setattr(notes, "ecrire_atomique", echouer_une_fois)
    resultat = server.notes_generer("I1")
    assert "erreur" in resultat
    assert snapshot(vault) == avant


def test_renommage_indisponible_preserve_originaux(napp, monkeypatch):
    from genealogiste_mcp import notes

    server.notes_generer()
    _modifier_deces(napp)
    avant = snapshot(napp.config.notes_dir)

    def refuser(*args, **kwargs):
        raise OSError("Système de fichiers sans liens physiques")

    monkeypatch.setattr(notes.os, "link", refuser)
    assert "erreur" in server.notes_generer("I1")
    assert snapshot(napp.config.notes_dir) == avant


@pytest.mark.parametrize("prenom, nom", [("", ""), ("A" * 98, "MARTIN"), ("É" * 80, "MARTIN")])
def test_fiche_sans_nom_ou_tronquee_reconnue_comme_generee(napp, prenom, nom):
    tree = napp.tree()
    tree.personnes["I1"].noms[0].prenoms = prenom
    tree.personnes["I1"].noms[0].nom = nom
    napp.store.write(tree)
    server.notes_generer("I1")
    ancienne = next((napp.config.notes_dir / "personnes").glob("I1 - *.md"))
    _modifier_deces(napp)
    attendu = napp.notes.fresh_name(napp.tree(), "personne", "I1") + ".md"
    assert ancienne.name != attendu  # le cas doit réellement nécessiter un renommage
    server.notes_generer("I1")
    nouvelle = next((napp.config.notes_dir / "personnes").glob("I1 - *.md"))
    assert nouvelle.name == attendu
    assert not ancienne.exists()
