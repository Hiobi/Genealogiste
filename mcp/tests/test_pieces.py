"""#60 : organisation d'un dossier de pièces existant (convention, inventaire, plan, application réversible)
et répertoire des médias configurable."""

import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import httpx
import pytest
import respx
from PIL import Image

from genealogiste_mcp import pieces, server
from genealogiste_mcp.gramps.backend import media_pending
from genealogiste_mcp.gramps.mapping import GrampsDb
from genealogiste_mcp.models import Media

HOOKS = Path(__file__).resolve().parents[2] / "hooks" / "hooks.json"
EXEMPLE = "DUPONT Jean + MARTIN Marie -- ERRE - AD59 - NMD [1829-1870] - 5 Mi 023 R 008 - p.466 n.36.jpg"


# ---------------------------------------------------------------- convention

def test_nommer_exemple_de_la_doc():
    assert pieces.nommer(["DUPONT Jean", {"nom": "Martin", "prenom": "Marie"}], "Erre", "AD59", "NMD",
                         "1829-1870", "5 Mi 023 R 008", "466", "36", "jpg") == EXEMPLE


def test_nommer_segments_absents_omis():
    assert pieces.nommer(["DUPONT Jean"], type_piece="photo", extension=".JPG") == "DUPONT Jean -- PHOTO.jpg"
    assert pieces.nommer(["DUPONT Jean"]) == "DUPONT Jean"
    with pytest.raises(pieces.PieceError):
        pieces.nommer([])


def test_lire_nom_inverse():
    lu = pieces.lire_nom(EXEMPLE)
    assert lu["personnes"] == ["DUPONT Jean", "MARTIN Marie"] and lu["patronyme"] == "DUPONT"
    assert (lu["commune"], lu["depot"], lu["type"], lu["annees"]) == ("ERRE", "AD59", "NMD", "1829-1870")
    assert (lu["cote"], lu["vue"], lu["acte"]) == ("5 Mi 023 R 008", "466", "36")


@pytest.mark.parametrize("brut", ['Capture d\'écran 2024-01-01 à 10:22:33.png', 'a?b*c"d<e>f|g.jpg',
                                  "CON.jpg", "fin. .jpg", "x" * 300 + ".jpg", "cote 3 E 12/45.pdf"])
def test_noms_compatibles_windows_nextcloud(brut):
    n = pieces.nom_compatible(Path(brut).name if "/" not in brut else brut)
    assert not re.search(r'[?:*"<>|/\\]', n)
    assert n.split(".")[0].upper() not in pieces.RESERVES_WINDOWS
    assert not Path(n).stem.endswith((" ", ".")) and len(n.encode()) <= pieces.MAX_NOM
    assert Path(n).suffix in (".png", ".jpg", ".pdf")


@pytest.mark.parametrize("nom,type_,pat", [
    ("acte naissance DUPONT 1850.jpg", "N", "DUPONT"),
    ("MARIAGE DURAND Pierre.jpg", "M", "DURAND"),
    ("deces LEROY.pdf", "D", "LEROY"),
    ("registre matricule BERNARD 1890.jpg", "RM", "BERNARD"),
    ("fiche ANMT PETIT.jpg", "ANMT", "PETIT"),
    ("photo famille MOREAU.jpg", "PHOTO", "MOREAU"),
    ("tombe FAURE cimetière.jpg", "TOMBE", "FAURE"),
    ("Capture d'écran 2024-01-01.png", "CAPTURE", ""),
    ("3f2a9c1e-77aa-4c1b-9d0e-1234567890ab.jpg", "", ""),
    ("123456789.jpg", "", ""),
    ("entretien mamie.m4a", "AUDIO", ""),
    ("arbre.ged", "GEDCOM", ""),
    (EXEMPLE, "NMD", "DUPONT"),
])
def test_detection(nom, type_, pat):
    info = pieces.detecter(Path(nom))
    assert (info["type"], info["patronyme"]) == (type_, pat)


# ---------------------------------------------------------------- dossier de test

def _ecrire(racine: Path, rel: str, contenu: bytes) -> None:
    p = racine / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenu)


def _etat(racine: Path) -> dict[str, str]:
    """Tous les fichiers (y compris non-pièces) : chemin relatif -> SHA-256."""
    return {str(p.relative_to(racine)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(racine.rglob("*")) if p.is_file() and "_organisation" not in p.parts}


@pytest.fixture
def dossier(tmp_path):
    r = tmp_path / "vault"
    _ecrire(r, "scans/acte naissance DUPONT 1850.jpg", b"naissance-dupont")
    _ecrire(r, "scans/copie/acte naissance DUPONT 1850 (1).jpg", b"naissance-dupont")  # doublon
    _ecrire(r, "MARIAGE DURAND Pierre.jpg", b"mariage-durand")
    _ecrire(r, "Capture d'écran 2024-01-01 à 10:22:33.png", b"capture")
    _ecrire(r, "3f2a9c1e-77aa-4c1b-9d0e-1234567890ab.jpg", b"inconnu")
    _ecrire(r, "photo famille MOREAU.jpg", b"photo-moreau")
    _ecrire(r, "tombe FAURE.jpg", b"tombe-faure")
    _ecrire(r, "entretien mamie.m4a", b"audio")
    _ecrire(r, "anciens/famille.gwb/base", b"gw-base")
    _ecrire(r, "anciens/famille.gwb/notes_d/x.txt", b"gw-note")
    _ecrire(r, "anciens/export.ged", b"0 HEAD")
    _ecrire(r, "personnes/I1 - Jean DUPONT.md", b"note generee")  # #18 : jamais touche
    _ecrire(r, "personnes/scan oublie DUPONT naissance.jpg", b"dans personnes")
    _ecrire(r, "index.md", b"# index")
    _ecrire(r, ".obsidian/app.json", b"{}")
    _ecrire(r, "notes.txt", b"liste de courses")  # texte non INSEE : ignore
    return r


def test_inventaire(dossier):
    inv = pieces.inventaire(dossier)
    assert inv["pieces"] == 11 and inv["doublons"] == 1
    assert inv["par_type"]["base GeneWeb"] == 2 and inv["par_type"]["naissance"] == 2
    assert inv["ignores"][".md"] == 1 and inv["ignores"][".txt"] == 1


def test_proposer_ne_deplace_rien(app, dossier):
    avant = _etat(dossier)
    r = server.pieces_proposer(str(dossier))
    assert r["jeton"] and _etat(dossier) == avant
    vers = {m.split("  →  ")[0]: m.split("  →  ")[1].split("  (")[0] for m in r["apercu"]}
    assert vers["scans/acte naissance DUPONT 1850.jpg"] == "documents/État civil/DUPONT/acte naissance DUPONT 1850.jpg"
    assert vers["scans/copie/acte naissance DUPONT 1850 (1).jpg"].startswith("archives/Doublons/scans/copie/")
    assert vers["MARIAGE DURAND Pierre.jpg"] == "documents/État civil/DURAND/MARIAGE DURAND Pierre.jpg"
    assert vers["Capture d'écran 2024-01-01 à 10:22:33.png"] == "_À trier/Capture d'écran 2024-01-01 à 10-22-33.png"
    assert vers["photo famille MOREAU.jpg"] == "photographies/MOREAU/photo famille MOREAU.jpg"
    assert vers["tombe FAURE.jpg"] == "photographies/Sépultures/FAURE/tombe FAURE.jpg"
    assert vers["entretien mamie.m4a"] == "documents/Témoignages oraux/entretien mamie.m4a"
    assert vers["anciens/famille.gwb/base"] == "archives/GeneWeb/famille.gwb/base"
    assert vers["anciens/export.ged"] == "archives/GEDCOM/export.ged"
    assert not any(k.startswith(("personnes/", ".obsidian", "index.md")) for k in vers)
    assert Path(r["plan_complet"]).read_text(encoding="utf-8").count("\n") == r["nb_deplacements"] + 1


def test_appliquer_puis_annuler(app, dossier):
    avant = _etat(dossier)
    r = server.pieces_proposer(str(dossier))
    out = server.pieces_appliquer(r["jeton"])
    assert out["erreurs"] == [] and out["deplaces"] == r["nb_deplacements"]
    assert out["controle"] == {"avant": 11, "apres": 11, "empreintes_identiques": True}
    apres = _etat(dossier)
    assert Counter(apres.values()) == Counter(avant.values())  # aucun fichier perdu ni modifié
    assert (dossier / "archives/Doublons/scans/copie/acte naissance DUPONT 1850 (1).jpg").exists()
    assert (dossier / "personnes/I1 - Jean DUPONT.md").exists() and (dossier / "index.md").exists()
    assert not (dossier / "scans").exists()  # dossiers vidés retirés, jamais de fichier supprimé
    journal = dossier / out["journal"]
    lignes = journal.read_text(encoding="utf-8").splitlines()
    assert lignes[0] == "ancien_chemin\tnouveau_chemin\tmotif\tsha256" and len(lignes) == out["deplaces"] + 1
    # idempotence
    assert server.pieces_proposer(str(dossier))["note"] == "Rien à déplacer."
    # jeton à usage unique
    assert "erreur" in server.pieces_appliquer(r["jeton"])
    # annulation
    u = server.pieces_proposer(str(dossier), annuler=journal.name)
    assert server.pieces_appliquer(u["jeton"])["controle"]["empreintes_identiques"]
    assert _etat(dossier) == avant


def test_dossier_modifie_entre_plan_et_application(app, dossier):
    r = server.pieces_proposer(str(dossier))
    _ecrire(dossier, "nouveau DUPONT deces.jpg", b"nouveau")
    avant = _etat(dossier)
    assert "a changé" in server.pieces_appliquer(r["jeton"])["erreur"]
    assert _etat(dossier) == avant


def test_renommage_reclasse(app, dossier):
    nom = server.piece_nommer(["DUPONT Jean"], "Erre", "AD59", "D", "1880", "5 Mi 023", "12", "4")["nom"]
    r = server.pieces_proposer(str(dossier), renommages=[
        {"actuel": "3f2a9c1e-77aa-4c1b-9d0e-1234567890ab.jpg", "propose": nom},
        {"actuel": "../hors.jpg", "propose": "x.jpg"}])
    assert any(f"documents/État civil/DUPONT/{nom}" in m for m in r["apercu"])
    assert r["erreurs"] and "ignoré" in r["erreurs"][0]


def test_renommage_traversant_neutralise(app, dossier):
    r = server.pieces_proposer(str(dossier), renommages=[
        {"actuel": "3f2a9c1e-77aa-4c1b-9d0e-1234567890ab.jpg", "propose": "../../evasion.jpg"}])
    server.pieces_appliquer(r["jeton"])
    assert not (dossier.parent / "evasion.jpg").exists() and not (dossier.parent.parent / "evasion.jpg").exists()
    assert (dossier / "_À trier/evasion.jpg").exists()


def test_collision_suffixee(app, tmp_path):
    r0 = tmp_path / "p"
    _ecrire(r0, "a/naissance DUPONT.jpg", b"un")
    _ecrire(r0, "b/naissance DUPONT.jpg", b"deux")
    _ecrire(r0, "documents/État civil/DUPONT/naissance DUPONT.jpg", b"trois")
    out = server.pieces_appliquer(server.pieces_proposer(str(r0))["jeton"])
    d = r0 / "documents/État civil/DUPONT"
    assert sorted(p.name for p in d.iterdir()) == ["naissance DUPONT (2).jpg", "naissance DUPONT (3).jpg",
                                                   "naissance DUPONT.jpg"]
    assert out["controle"]["empreintes_identiques"]


def test_media_de_l_arbre_jamais_deplace(app_famille, tmp_path):
    r0 = tmp_path / "p"
    _ecrire(r0, "acte naissance DUPONT.jpg", b"lie")
    t = app_famille.tree()
    t.medias["O99"] = Media(id="O99", fichier=str(r0 / "acte naissance DUPONT.jpg"))
    app_famille.store.write(t)
    r = server.pieces_proposer(str(r0))
    assert r.get("note") == "Rien à déplacer."
    assert r["references_arbre_non_deplacees"] == ["acte naissance DUPONT.jpg"]


@pytest.mark.parametrize("cible", ["/", "~"])
def test_dossier_trop_large_refuse(app, cible):
    assert "erreur" in server.pieces_proposer(cible)


def test_piece_nommer_depuis_arbre(app_famille):
    t = app_famille.tree()
    pid = next(iter(t.personnes))
    n = t.personnes[pid].noms[0]
    r = server.piece_nommer([pid], type_piece="N", annees="1850")
    assert r["nom"].startswith(f"{n.nom.upper()} {n.prenoms}".strip())
    assert r["dossier_convention"].startswith("documents/État civil/")


# ---------------------------------------------------------------- répertoire des médias configurable

@pytest.fixture
def vault_medias(app, tmp_path):
    v = tmp_path / "vault" / "documents"
    app.config.media_dir_conf = v
    return v


def test_media_enregistrer_dans_media_dir(app, vault_medias, tmp_path):
    src = tmp_path / "scan.jpg"
    src.write_bytes(b"img")
    r = server.media_enregistrer(str(src), "acte.jpg")
    assert Path(r["chemin_absolu"]) == vault_medias / "acte.jpg" and r["fichier"] == str(vault_medias / "acte.jpg")
    assert "erreur" in server.media_enregistrer(str(src), "../evasion.jpg")
    c = server.media_enregistrer(str(src), "naissance DUPONT.jpg", classer=True)
    assert Path(c["chemin_absolu"]) == vault_medias / "État civil/DUPONT/naissance DUPONT.jpg"  # pas de documents/documents
    assert Path(server.media_enregistrer(str(src), "zz.jpg", classer=True)["chemin_absolu"]).parent.name == "_À trier"


def test_media_enregistrer_defaut_relatif(app, tmp_path):
    src = tmp_path / "scan.jpg"
    src.write_bytes(b"img")
    assert server.media_enregistrer(str(src), "a.jpg")["fichier"] == "medias/a.jpg"


def test_archive_image_hors_du_vault(app, vault_medias, tmp_path):
    """#70 : aperçus et recadrages de lecture dans le cache, jamais dans le vault."""
    img = tmp_path / "acte.png"
    Image.new("RGB", (100, 80), "white").save(img)
    r = server.archive_image(str(img))
    chemin = Path(r["chemin_absolu"])
    assert chemin.exists() and chemin.is_relative_to(app.config.cache_images_dir)
    assert not chemin.is_relative_to(vault_medias)


def test_media_pending_accepte_media_dir(tmp_path):
    data, med = tmp_path / "donnees", tmp_path / "vault"
    data.mkdir()
    med.mkdir()
    (med / "a.jpg").write_bytes(b"img")
    db = GrampsDb()
    db.put({"_class": "Media", "handle": "h", "gramps_id": "O1", "path": str(med / "a.jpg"), "mime": "image/jpeg",
            "checksum": "", "attribute_list": []})
    assert media_pending(db, data)[0] == []  # sans media_dir : hors périmètre
    todo, _ = media_pending(db, data, None, med)
    assert [t["id"] for t in todo] == ["O1"]


def test_rapport_hors_donnees_non_commite(app_famille, tmp_path):
    app_famille.config.rapports_dir_conf = tmp_path / "vault" / "rapports"
    pid = next(iter(app_famille.tree().personnes))
    r = server.rapport_enregistrer(pid, "Essai", "# rapport")
    assert r["commit"] is None and Path(r["fichier"]).is_relative_to(tmp_path / "vault")


def test_config_env(monkeypatch, tmp_path):
    from genealogiste_mcp.config import load_config
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("GENEALOGISTE_MEDIA_DIR", str(tmp_path / "v" / "documents"))
    monkeypatch.setenv("GENEALOGISTE_EXPORTS_DIR", str(tmp_path / "v" / "exports"))
    c = load_config()
    assert c.media_dir == tmp_path / "v" / "documents" and c.exports_dir == tmp_path / "v" / "exports"
    assert c.rapports_dir == tmp_path / "d" / "rapports"


# ---------------------------------------------------------------- hooks

def _decision(tool: str) -> str | None:
    for h in json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]:
        if re.fullmatch(h["matcher"], tool):
            out = subprocess.run(["sh", "-c", h["hooks"][0]["command"]], input="{}", capture_output=True,
                                 text=True, check=True).stdout
            return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    return None


@pytest.mark.parametrize("tool,attendu", [("pieces_inventaire", "allow"), ("pieces_proposer", "allow"),
                                          ("piece_nommer", "allow"), ("pieces_appliquer", "ask")])
def test_hooks_pieces(tool, attendu):
    assert _decision(f"mcp__plugin_genealogiste_genealogiste__{tool}") == attendu


# ---------------------------------------------------------------- #101 : périmètre, note et annulation

@pytest.mark.parametrize("origine", ["configuration", "obsidian", "exterieur"])
def test_sous_dossier_racine_et_annulation(app, tmp_path, origine):
    vault = tmp_path / "fonds"
    scope = vault / pieces.A_TRIER
    _ecrire(vault, f"{pieces.A_TRIER}/scan.jpg", b"selection")
    _ecrire(vault, f"{pieces.A_TRIER}/opaque.jpg", b"non identifie")
    _ecrire(vault, "ailleurs/naissance MARTIN.jpg", b"hors perimetre")
    if origine == "configuration":
        app.config.media_dir_conf = vault / "documents"
    elif origine == "obsidian":
        (vault / ".obsidian").mkdir()
    racine = scope if origine == "exterieur" else vault
    avant = _etat(vault)
    nom = pieces.nommer(["DUPONT Jean"], type_piece="N", extension="jpg")
    r = server.pieces_proposer(str(scope), renommages=[{"actuel": "scan.jpg", "propose": nom}])
    assert r["racine"] == str(racine) and r["perimetre"] == str(scope)
    if origine != "exterieur":
        assert r["nb_deplacements"] == 1
        assert r["apercu"][0].startswith("_À trier/scan.jpg  →  documents/")
    out = server.pieces_appliquer(r["jeton"])
    assert not out["erreurs"] and out["controle"]["empreintes_identiques"]
    assert (racine / "documents/État civil/DUPONT" / nom).exists()
    assert (racine / out["journal"]).exists()
    assert not (scope / "_À trier/_À trier").exists()
    assert server.pieces_proposer(str(scope))["note"] == "Rien à déplacer."
    undo = server.pieces_proposer(str(scope), annuler=Path(out["journal"]).name)
    assert not server.pieces_appliquer(undo["jeton"])["erreurs"]
    assert _etat(vault) == avant


def test_seulement_renommages_ignore_doublons_et_autres_pieces(app, dossier):
    avant = _etat(dossier)
    nom = pieces.nommer(["DUPONT Jean"], type_piece="N", extension="jpg")
    r = server.pieces_proposer(str(dossier), seulement_renommages=True,
                              renommages=[{"actuel": "scans/copie/acte naissance DUPONT 1850 (1).jpg", "propose": nom}])
    assert r["nb_deplacements"] == 1 and r["doublons"] == 0
    assert "archives/Doublons" not in r["apercu"][0]
    assert not server.pieces_appliquer(r["jeton"])["erreurs"]
    apres = _etat(dossier)
    change = "scans/copie/acte naissance DUPONT 1850 (1).jpg"
    assert all(apres.get(p) == h for p, h in avant.items() if p != change)
    assert server.pieces_proposer(str(dossier), seulement_renommages=True)["note"] == "Rien à déplacer."


@pytest.mark.parametrize("legacy", [False, True])
def test_note_compagnon_liens_texte_libre_et_retour_exact(app, tmp_path, legacy):
    from genealogiste_mcp import archivage
    from genealogiste_mcp.markdown import lien_fichier

    vault = tmp_path / "fonds"
    app.config.media_dir_conf = vault
    image = vault / "_À trier/scan [1].jpg"
    _ecrire(vault, "_À trier/scan [1].jpg", b"image")
    note = archivage.note_compagnon(image, {"ark": "ark:/12345/test", "vue": 12}, ["[[personnes/I1]]"], "[[sources/S1]]")
    texte = note.read_text()
    if legacy:
        texte = texte.replace(lien_fichier(image.name, image=True), f"![[{image.name}]]")
    libre = '\nTexte personnel : scan [1].jpg\n![[scan [1].jpg]]\n'
    note.write_text(texte + libre)
    avant = _etat(vault)
    nom = pieces.nommer(["DUPONT Jean"], type_piece="N", annees="1850", extension="jpg")
    r = server.pieces_proposer(str(image.parent), seulement_renommages=True,
                              renommages=[{"actuel": image.name, "propose": nom}])
    assert r["nb_deplacements"] == 2 and _etat(vault) == avant
    out = server.pieces_appliquer(r["jeton"])
    assert not out["erreurs"] and out["controle"]["empreintes_identiques"]
    cible = vault / "documents/État civil/DUPONT" / nom
    texte_apres = cible.with_suffix(".md").read_text()
    assert f'fichier: "{nom}"' in texte_apres
    assert lien_fichier(nom, image=True) in texte_apres
    assert texte_apres.endswith(libre) and '[[personnes/I1]]' in texte_apres
    assert not note.exists() and not image.exists()
    undo = server.pieces_proposer(str(vault), annuler=Path(out["journal"]).name)
    assert not server.pieces_appliquer(undo["jeton"])["erreurs"]
    assert _etat(vault) == avant


def test_note_modifiee_refuse_tout_le_plan(app, tmp_path):
    from genealogiste_mcp import archivage
    vault = tmp_path / "fonds"
    _ecrire(vault, "scan.jpg", b"image")
    note = archivage.note_compagnon(vault / "scan.jpg", {}, [], "")
    r = server.pieces_proposer(str(vault))
    note.write_text(note.read_text() + "\nSaisie récente\n")
    avant = _etat(vault)
    assert "modifiée" in server.pieces_appliquer(r["jeton"])["erreur"]
    assert _etat(vault) == avant


def test_collision_note_suffixe_image_et_note(app, tmp_path):
    from genealogiste_mcp import archivage
    vault = tmp_path / "fonds"
    _ecrire(vault, "scan.jpg", b"image")
    archivage.note_compagnon(vault / "scan.jpg", {}, [], "")
    _ecrire(vault, "_À trier/scan.md", b"note manuelle a preserver")
    r = server.pieces_proposer(str(vault))
    assert r["nb_deplacements"] == 2
    assert not server.pieces_appliquer(r["jeton"])["erreurs"]
    assert (vault / "_À trier/scan (2).jpg").exists()
    assert (vault / "_À trier/scan (2).md").exists()
    assert (vault / "_À trier/scan.md").read_bytes() == b"note manuelle a preserver"


def test_echec_deplacement_restaure_paire(app, tmp_path, monkeypatch):
    from genealogiste_mcp import archivage
    vault = tmp_path / "fonds"
    _ecrire(vault, "scan.jpg", b"image")
    archivage.note_compagnon(vault / "scan.jpg", {}, [], "")
    avant = _etat(vault)
    r = server.pieces_proposer(str(vault))
    rename = pieces.os.rename
    def echec(src, dst):
        if src.name == "scan.jpg":
            raise OSError("échec simulé")
        return rename(src, dst)
    monkeypatch.setattr(pieces.os, "rename", echec)
    out = server.pieces_appliquer(r["jeton"])
    assert out["erreurs"] and out["deplaces"] == 0
    assert _etat(vault) == avant


def test_registre_archivage_suit_rangement_et_annulation(app, tmp_path, monkeypatch):
    from genealogiste_mcp.sources import iiif
    image = tmp_path / "original.jpg"
    Image.new("RGB", (20, 30), "white").save(image)
    vault = tmp_path / "fonds"
    app.config.media_dir_conf = vault
    archive = server.piece_archiver(str(image))
    fichier = Path(archive["chemin_absolu"])
    nom = pieces.nommer(["DUPONT Jean"], type_piece="N", extension="jpg")
    plan = server.pieces_proposer(str(fichier.parent), seulement_renommages=True,
                                 renommages=[{"actuel": fichier.name, "propose": nom}])
    out = server.pieces_appliquer(plan["jeton"])
    assert not out["erreurs"]
    def interdit(*args, **kwargs):
        raise AssertionError("aucun nouveau téléchargement")
    monkeypatch.setattr(iiif, "full_image", interdit)
    hit = server.piece_archiver(str(image))
    cible = vault / "documents/État civil/DUPONT" / nom
    assert hit["deja_archivee"] and hit["chemin_absolu"] == str(cible)
    assert hit["fichier"] == app.config.media_ref(cible)
    assert hit["note"] == app.config.media_ref(cible.with_suffix(".md"))
    undo = server.pieces_proposer(str(vault), annuler=Path(out["journal"]).name)
    assert not server.pieces_appliquer(undo["jeton"])["erreurs"]
    assert server.piece_archiver(str(image))["chemin_absolu"] == str(fichier)


@pytest.mark.parametrize("dossier", ["personnes", ".obsidian", "sources"])
def test_perimetre_protege_refuse(app, tmp_path, dossier):
    app.config.media_dir_conf = tmp_path
    (tmp_path / dossier).mkdir()
    assert "protégé" in server.pieces_proposer(str(tmp_path / dossier))["erreur"]


def test_note_sur_place_si_seule_casse_extension_change(app, tmp_path):
    from genealogiste_mcp import archivage
    vault = tmp_path / "fonds"
    _ecrire(vault, "_À trier/scan.JPG", b"image")
    app.config.media_dir_conf = vault
    archivage.note_compagnon(vault / "_À trier/scan.JPG", {}, [], "")
    avant = _etat(vault)
    r = server.pieces_proposer(str(vault))
    out = server.pieces_appliquer(r["jeton"])
    assert not out["erreurs"] and out["notes_compagnons"] == {"verifiees": 1, "conformes": True}
    assert 'fichier: "scan.jpg"' in (vault / "_À trier/scan.md").read_text()
    undo = server.pieces_proposer(str(vault), annuler=Path(out["journal"]).name)
    assert not server.pieces_appliquer(undo["jeton"])["erreurs"]
    assert _etat(vault) == avant


def test_note_ordinaire_et_lien_symbolique_restent_intacts(app, tmp_path):
    vault = tmp_path / "fonds"
    _ecrire(vault, "scan.jpg", b"image")
    _ecrire(vault, "scan.md", b"---\ntype: personne\n---\nContenu manuel")
    _ecrire(vault, "autre.jpg", b"autre")
    externe = tmp_path / "externe.md"
    externe.write_text('---\ntype: piece\n---\n')
    (vault / "autre.md").symlink_to(externe)
    out = server.pieces_appliquer(server.pieces_proposer(str(vault))["jeton"])
    assert not out["erreurs"] and out["notes_compagnons"]["verifiees"] == 0
    assert (vault / "scan.md").read_bytes().endswith(b"Contenu manuel")
    assert (vault / "autre.md").is_symlink() and externe.read_text() == '---\ntype: piece\n---\n'


def test_note_partagee_refuse_meme_en_mode_cible(app, tmp_path):
    from genealogiste_mcp import archivage
    vault = tmp_path / "fonds"
    _ecrire(vault, "scan.jpg", b"jpg")
    _ecrire(vault, "scan.png", b"png")
    archivage.note_compagnon(vault / "scan.jpg", {}, [], "")
    avant = _etat(vault)
    r = server.pieces_proposer(str(vault), seulement_renommages=True,
                              renommages=[{"actuel": "scan.jpg", "propose": "autre.jpg"}])
    assert "partagée" in r["erreur"] and _etat(vault) == avant


def test_note_editee_apres_rangement_annulation_refusee(app, tmp_path):
    from genealogiste_mcp import archivage
    vault = tmp_path / "fonds"
    _ecrire(vault, "scan.jpg", b"image")
    archivage.note_compagnon(vault / "scan.jpg", {}, [], "")
    out = server.pieces_appliquer(server.pieces_proposer(str(vault))["jeton"])
    note = vault / "_À trier/scan.md"
    note.write_text(note.read_text() + "\nTexte postérieur\n")
    avant = _etat(vault)
    undo = server.pieces_proposer(str(vault), annuler=Path(out["journal"]).name)
    assert "modifiée" in server.pieces_appliquer(undo["jeton"])["erreur"]
    assert _etat(vault) == avant


@respx.mock
def test_url_archivee_deplacee_reconnue_sans_reseau(app, tmp_path, monkeypatch):
    import io

    from genealogiste_mcp.sources import iiif
    buf = io.BytesIO()
    Image.new("RGB", (20, 30), "red").save(buf, "JPEG")
    source = "https://archives.example/acte.jpg"
    respx.get(source).mock(return_value=httpx.Response(200, content=buf.getvalue()))
    app.config.media_dir_conf = tmp_path / "fonds"
    archive = server.piece_archiver(source)
    image = Path(archive["chemin_absolu"])
    nom = pieces.nommer(["DUPONT Jean"], type_piece="N", extension="jpg")
    plan = server.pieces_proposer(str(image.parent), seulement_renommages=True,
                                 renommages=[{"actuel": image.name, "propose": nom}])
    assert not server.pieces_appliquer(plan["jeton"])["erreurs"]
    def interdit(*args, **kwargs):
        raise AssertionError("ni résolution ni téléchargement attendus")
    monkeypatch.setattr(iiif, "resoudre_vue", interdit)
    hit = server.piece_archiver(source)
    assert hit["deja_archivee"] and Path(hit["chemin_absolu"]).name == nom
    assert len(respx.calls) == 1
