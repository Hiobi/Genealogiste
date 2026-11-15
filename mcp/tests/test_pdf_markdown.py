"""Conversion PDF → Markdown (#132) : texte natif, OCR (Tesseract simulé), repli vision, cache par empreinte."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from genealogiste_mcp import pdf_markdown as pm
from genealogiste_mcp import server


def _pdf(pages: list[bytes]) -> bytes:
    """PDF minimal valide (Helvetica) à partir des flux de contenu de chaque page."""
    objets: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    police = 3
    objets.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for flux in pages:
        n_page, n_flux = len(objets) + 1, len(objets) + 2
        kids.append(f"{n_page} 0 R".encode())
        objets.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 "
                      + f"{police} 0 R".encode() + b" >> >> /Contents " + f"{n_flux} 0 R".encode() + b" >>")
        objets.append(b"<< /Length " + str(len(flux)).encode() + b" >>\nstream\n" + flux + b"\nendstream")
    objets[1] = b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count " + str(len(pages)).encode() + b" >>"
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objets, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _texte(x: float, y: float, taille: float, s: str) -> bytes:
    s = s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"BT /F1 {taille} Tf {x} {y} Td ({s}) Tj ET\n".encode("cp1252")


def _page_natif(titre: str, paragraphes: list[str], tableau: bool = False) -> bytes:
    flux = _texte(72, 780, 20, titre)
    y = 740
    for p in paragraphes:
        flux += _texte(72, y, 11, p)
        y -= 14
    if tableau:  # grille 2 x 3 tracée (stratégie « lines » de pdfplumber)
        x0, x1, x2, haut = 72, 250, 430, 600
        flux += b"0.5 w\n"
        for k in range(4):
            flux += f"{x0} {haut - 20 * k} m {x2} {haut - 20 * k} l S\n".encode()
        for x in (x0, x1, x2):
            flux += f"{x} {haut} m {x} {haut - 60} l S\n".encode()
        for k, (a, b) in enumerate([("Nom", "Commune"), ("Durand", "Lille"), ("Martin", "Douai")]):
            flux += _texte(x0 + 4, haut - 20 * k - 14, 11, a) + _texte(x1 + 4, haut - 20 * k - 14, 11, b)
    return flux


@pytest.fixture
def natif(tmp_path) -> Path:
    p = tmp_path / "jugement.pdf"
    p.write_bytes(_pdf([
        _page_natif("Tribunal civil de Lille", ["Le tribunal, vu la requete presentee par Jean Durand,",
                                                "cultivateur demeurant a Lille, ordonne la rectification."], True),
        _page_natif("Dispositif", ["Dit que l'acte de naissance sera rectifie en marge."]),
    ]))
    return p


@pytest.fixture
def scan(tmp_path) -> Path:
    p = tmp_path / "scan.pdf"
    Image.new("L", (600, 800), 255).save(p, "PDF", resolution=72)
    return p


def test_texte_natif_titres_tableau_pages(natif, tmp_path):
    r = pm.convertir(str(natif), tmp_path / "cache")
    md = Path(r["chemin_absolu"]).read_text(encoding="utf-8")
    assert r["pages_natives"] == [1, 2] and r["pages_ocr"] == [] and r["pages_a_lire_en_image"] == []
    assert "<!-- page 1/2 · texte natif -->" in md and "<!-- page 2/2 · texte natif -->" in md
    assert "## Tribunal civil de Lille" in md and "## Dispositif" in md
    assert "| Nom | Commune |" in md and "| Durand | Lille |" in md
    assert "Le tribunal, vu la requete presentee par Jean Durand, cultivateur demeurant a Lille" in md
    assert md.count("Durand | Lille") == 1  # le tableau n'est pas répété dans le texte courant
    assert r["tokens_estimes_markdown"] < r["tokens_estimes_images"] / 5
    assert Path(r["chemin_absolu"]).parent == tmp_path / "cache"


def test_cache_par_empreinte(natif, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    premier = pm.convertir(str(natif), cache)
    assert premier["deja_converti"] is False
    copie = tmp_path / "renomme.pdf"
    copie.write_bytes(natif.read_bytes())

    def interdit(*a, **k):
        raise AssertionError("reconversion d'un PDF inchangé")

    monkeypatch.setattr(pm, "page_native", interdit)
    second = pm.convertir(str(copie), cache)
    assert second["deja_converti"] is True and second["chemin_absolu"] == premier["chemin_absolu"]
    assert second["source"] == str(copie)
    monkeypatch.undo()
    natif.write_bytes(_pdf([_page_natif("Autre jugement", ["Texte different de la premiere version."])]))
    troisieme = pm.convertir(str(natif), cache)
    assert troisieme["deja_converti"] is False and troisieme["chemin_absolu"] != premier["chemin_absolu"]
    assert pm.convertir(str(natif), cache, reconvertir=True)["deja_converti"] is False


def test_scan_sans_tesseract_part_en_vision(scan, tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "_tesseract_langues", lambda *a: None)
    r = pm.convertir(str(scan), tmp_path / "cache")
    assert r["pages_a_lire_en_image"] == [1] and r["ocr"] == "tesseract_absent"
    assert r["pages"][0]["motif"] == "tesseract_absent"
    assert "archive_image, page=1" in Path(r["chemin_absolu"]).read_text(encoding="utf-8")


def test_langue_tesseract_absente(scan, tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "_tesseract_langues", lambda *a: frozenset({"eng", "osd"}))
    r = pm.convertir(str(scan), tmp_path / "cache")
    assert r["pages"][0]["motif"] == "langue_tesseract_absente:fra"


def test_scan_ocr_et_confiance(scan, tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "_tesseract_langues", lambda *a: frozenset({"fra", "lat"}))
    vus = []

    def faux_ocr(image, langue):
        vus.append((image.size, langue))
        return "Acte de deces de Pierre Martin, ne a Douai.", 91.0

    monkeypatch.setattr(pm, "ocr_image", faux_ocr)
    r = pm.convertir(str(scan), tmp_path / "cache", langue="fra+lat")
    assert r["pages_ocr"] == [1] and r["pages"][0]["confiance_ocr"] == 91
    assert vus[0][1] == "fra+lat" and vus[0][0][0] == round(600 * pm.DPI_OCR / 72)
    md = Path(r["chemin_absolu"]).read_text(encoding="utf-8")
    assert "OCR fra+lat, confiance 91" in md and "Pierre Martin" in md

    monkeypatch.setattr(pm, "ocr_image", lambda image, langue: ("griffonnage illisible ou manuscrit", 31.0))
    r = pm.convertir(str(scan), tmp_path / "cache", langue="fra+lat", reconvertir=True)
    assert r["pages_a_lire_en_image"] == [1] and r["pages"][0]["motif"] == "ocr_peu_fiable"


def test_forcer_ocr_sur_texte_natif(natif, tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "_tesseract_langues", lambda *a: frozenset({"fra"}))
    monkeypatch.setattr(pm, "ocr_image", lambda image, langue: ("Texte relu par OCR sur la page.", 88.0))
    r = pm.convertir(str(natif), tmp_path / "cache", forcer_ocr=True)
    assert r["pages_ocr"] == [1, 2] and r["chemin_absolu"].endswith("-ocr.md")


def test_ocr_image_reconstitue_paragraphes(monkeypatch):
    import pytesseract

    data = {"text": ["Acte", "de", "nais-", "sance", "", "Fin"], "conf": ["90", "80", "70", "60", "-1", "95"],
            "block_num": [1, 1, 1, 1, 1, 2], "par_num": [1, 1, 1, 1, 1, 1], "line_num": [1, 1, 1, 2, 2, 1]}
    monkeypatch.setattr(pytesseract, "image_to_data", lambda *a, **k: data)
    texte, conf = pm.ocr_image(Image.new("L", (10, 10)), "fra")
    assert texte == "Acte de naissance\n\nFin" and conf == pytest.approx(79.0)


def test_table_markdown_echappe_et_ignore_degeneres():
    assert pm.table_markdown([["a|b", None], ["c\nd", "e"]]) == "| a\\|b |  |\n| --- | --- |\n| c d | e |"
    assert pm.table_markdown([["seule"], ["colonne"]]) == ""
    assert pm.table_markdown([["une", "ligne"]]) == ""


def test_outil_pdf_markdown(app, natif, tmp_path):
    r = server.pdf_markdown(str(natif))
    assert Path(r["chemin_absolu"]).is_relative_to(app.config.cache_pdf_dir)
    pas_pdf = tmp_path / "x.pdf"
    pas_pdf.write_text("<html>refus</html>")
    assert "pas un PDF" in server.pdf_markdown(str(pas_pdf))["erreur"]
    assert "introuvable" in server.pdf_markdown(str(tmp_path / "absent.pdf"))["erreur"]
    assert "langue" in server.pdf_markdown(str(natif), langue="fra; rm")["erreur"]


def test_paragraphes_puces_privees_et_titre_multiligne():
    def li(top, taille, texte):
        return {"top": top, "bottom": top + taille, "taille": taille, "texte": texte}

    blocs = pm._paragraphes([li(10, 16, "Note sur l'etat civil, dans Guide"), li(28, 16, "des recherches, 1981"),
                             li(60, 11, "\uf06c Premier point de la note,"), li(73, 11, "suite du point."),
                             li(86, 11, "\uf06c Second point.")], corps=11)
    assert [b for _, b in blocs] == ["### Note sur l'etat civil, dans Guide des recherches, 1981",
                                     "- Premier point de la note, suite du point.", "- Second point."]


def test_archive_image_lit_une_page_de_pdf(app, natif):
    """Repli vision : une page de PDF local (manuscrit, OCR peu fiable) se lit avec archive_image(page=n)."""
    r = server.archive_image(str(natif), page=2, largeur=500)
    assert r["pdf"] == str(natif) and r["page_pdf"] == 2 and "pdf_markdown" in r["conseil"]
    assert r["dimensions_demandees"][0] == 500 and Path(r["chemin_absolu"]).is_file()
    assert r["original"].endswith("-p2.png")
    assert server.archive_image(str(natif), page=2, largeur=500)["depuis_cache"] is True
    assert "absente" in str(server.archive_image(str(natif), page=9))


@pytest.fixture
def debian(monkeypatch):
    monkeypatch.setattr(pm.platform, "system", lambda: "Linux")
    monkeypatch.setattr(pm, "_os_release", lambda: {"ID": "debian", "PRETTY_NAME": "Debian GNU/Linux 12"})


def test_sans_tesseract_propose_installation(scan, tmp_path, monkeypatch, debian):
    monkeypatch.setattr(pm, "_tesseract_langues", lambda *a: None)
    r = pm.convertir(str(scan), tmp_path / "cache")
    inst = r["installation"]
    assert inst["commande"] == "sudo apt install -y tesseract-ocr tesseract-ocr-fra"
    assert inst["pages_concernees"] == [1] and inst["surcout_vision_tokens"] == r["tokens_estimes_images"]
    assert "proposer à l'utilisateur" in inst["consigne"] and "! sudo apt" in inst["consigne"]
    assert any("GENEALOGISTE_TESSERACT" in x for x in inst["alternatives"])


def test_langue_absente_propose_seulement_la_langue(scan, tmp_path, monkeypatch, debian):
    monkeypatch.setattr(pm, "_tesseract_langues", lambda *a: frozenset({"fra"}))
    r = pm.convertir(str(scan), tmp_path / "cache", langue="fra+lat")
    assert r["installation"]["commande"] == "sudo apt install -y tesseract-ocr-lat"


def test_pas_de_conseil_quand_ocr_present_ou_texte_natif(natif, scan, tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "_tesseract_langues", lambda *a: None)
    assert "installation" not in pm.convertir(str(natif), tmp_path / "cache")
    monkeypatch.setattr(pm, "_tesseract_langues", lambda *a: frozenset({"fra"}))
    monkeypatch.setattr(pm, "ocr_image", lambda image, langue: ("Acte de bapteme de Marie Durand.", 90.0))
    assert "installation" not in pm.convertir(str(scan), tmp_path / "cache")


@pytest.mark.parametrize(("systeme", "rel", "attendu"), [
    ("Linux", {"ID": "arch"}, "sudo pacman -S --needed tesseract tesseract-data-fra"),
    ("Linux", {"ID": "linuxmint", "ID_LIKE": "ubuntu debian"}, "sudo apt install -y tesseract-ocr tesseract-ocr-fra"),
    ("Linux", {"ID": "fedora"}, "sudo dnf install -y tesseract tesseract-langpack-fra"),
    ("Darwin", {}, "brew install tesseract tesseract-lang"),
    ("Windows", {}, "winget install UB-Mannheim.TesseractOCR"),
    ("Linux", {"ID": "alpine"}, ""),
])
def test_commande_installation_selon_systeme(systeme, rel, attendu):
    out = pm.commande_installation(["fra"], systeme=systeme, os_release=rel)
    assert out["commande"] == attendu
    if not attendu:
        assert "fra" in out["note"]


def test_cache_reconverti_quand_ocr_installe(scan, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setattr(pm, "_tesseract_langues", lambda *a: None)
    assert pm.convertir(str(scan), cache)["pages_a_lire_en_image"] == [1]
    assert pm.convertir(str(scan), cache)["deja_converti"] is True  # toujours sans OCR : cache
    monkeypatch.setattr(pm, "_tesseract_langues", lambda *a: frozenset({"fra"}))
    monkeypatch.setattr(pm, "ocr_image", lambda image, langue: ("Acte de bapteme de Marie Durand.", 90.0))
    r = pm.convertir(str(scan), cache)
    assert r["deja_converti"] is False and r["pages_ocr"] == [1] and "installation" not in r
    assert pm.convertir(str(scan), cache)["deja_converti"] is True


def test_absence_de_tesseract_non_memorisee(monkeypatch):
    import pytesseract

    pm.oublier_detection()
    etat = {"installe": False}

    def version():
        if not etat["installe"]:
            raise pytesseract.TesseractNotFoundError()
        return "5.3.0"

    monkeypatch.setattr(pytesseract, "get_tesseract_version", version)
    monkeypatch.setattr(pytesseract, "get_languages", lambda config="": ["eng", "fra"])
    assert pm.ocr_disponible("fra", "/opt/tess/bin/tesseract") == (False, "tesseract_absent")
    etat["installe"] = True
    assert pm.ocr_disponible("fra", "/opt/tess/bin/tesseract") == (True, "")
    assert pytesseract.pytesseract.tesseract_cmd == "/opt/tess/bin/tesseract"
    assert pm.ocr_disponible("lat", "/opt/tess/bin/tesseract") == (False, "langue_tesseract_absente:lat")
    pm.oublier_detection()
    pm._commande("")


def test_outil_transmet_genealogiste_tesseract(app, scan, monkeypatch):
    vus = []
    monkeypatch.setattr(pm, "_tesseract_langues", lambda tesseract="": vus.append(tesseract))
    app.config.tesseract = "/opt/shim/tesseract"
    server.pdf_markdown(str(scan))
    assert vus == ["/opt/shim/tesseract"]
