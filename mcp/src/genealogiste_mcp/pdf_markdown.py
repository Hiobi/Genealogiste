"""Conversion d'un PDF dactylographié ou imprimé en Markdown compact, avant lecture par le modèle (#132).

Pile permissive : pdfplumber (MIT) pour le texte natif, les titres (taille de police) et les tableaux ;
pypdfium2 (Apache-2.0/BSD) pour rendre les pages scannées ; pytesseract (Apache-2.0) + Tesseract pour l'OCR.
Une page sans texte exploitable (manuscrit, OCR absent ou peu fiable) n'est pas devinée : elle est signalée
pour lecture par la vision (archive_image). Le Markdown est rangé dans un cache dont la clé est l'empreinte du
contenu : un PDF inchangé, même renommé ou déplacé, n'est jamais reconverti."""

from __future__ import annotations

import functools
import hashlib
import json
import re
import statistics
from pathlib import Path

from .fichiers import ecrire_atomique

VERSION = 1  # à incrémenter quand la sortie change : invalide le cache
SEUIL_TEXTE = 25  # caractères en dessous desquels une page est considérée sans texte natif
SEUIL_IMAGE_TEXTE = 200  # page couverte d'images avec peu de texte (tampon, en-tête) : OCR
COUVERTURE_IMAGE = 0.5
CONFIANCE_OCR_MIN = 60  # confiance moyenne Tesseract (0-100) sous laquelle la page part en vision
DPI_OCR = 300
LARGEUR_IMAGE_REF = 1500  # largeur de lecture d'une page en image (cf. /genealogiste:transcris)
TOKENS_PER_PIXEL = 1 / 750
CARACTERES_PAR_TOKEN = 3.5  # ordre de grandeur pour du français
LANGUE_RE = re.compile(r"^[a-z_]{3,}(\+[a-z_]{3,})*$")


class PdfErreur(ValueError):
    pass


@functools.lru_cache(maxsize=1)
def _tesseract_langues() -> frozenset[str] | None:
    """Langues Tesseract installées, ou None si le binaire est absent."""
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return frozenset(pytesseract.get_languages(config=""))
    except Exception:  # binaire absent, PATH incomplet, tessdata illisible
        return None


def ocr_disponible(langue: str) -> tuple[bool, str]:
    langues = _tesseract_langues()
    if langues is None:
        return False, "tesseract_absent"
    manquantes = [x for x in langue.split("+") if x not in langues]
    if manquantes:
        return False, f"langue_tesseract_absente:{'+'.join(manquantes)}"
    return True, ""


# --- texte natif -----------------------------------------------------------------------------------------

def _cellule(x: object) -> str:
    return " ".join(str(x or "").split()).replace("|", "\\|")


def table_markdown(rows: list[list]) -> str:
    rows = [r for r in rows if r and any(c not in (None, "") for c in r)]
    if len(rows) < 2 or max(len(r) for r in rows) < 2:
        return ""
    n = max(len(r) for r in rows)
    lignes = [[_cellule(c) for c in r] + [""] * (n - len(r)) for r in rows]
    out = ["| " + " | ".join(lignes[0]) + " |", "|" + " --- |" * n]
    out += ["| " + " | ".join(r) + " |" for r in lignes[1:]]
    return "\n".join(out)


def _dans(mot: dict, bbox: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox
    cx, cy = (mot["x0"] + mot["x1"]) / 2, (mot["top"] + mot["bottom"]) / 2
    return x0 <= cx <= x1 and top <= cy <= bottom


def _lignes(mots: list[dict]) -> list[dict]:
    """Regroupe les mots en lignes (même ordonnée, tolérance proportionnelle à la taille)."""
    lignes: list[dict] = []
    for m in sorted(mots, key=lambda w: (round(w["top"]), w["x0"])):
        if lignes and abs(m["top"] - lignes[-1]["top"]) <= max(2.0, 0.3 * lignes[-1]["taille"]):
            lignes[-1]["mots"].append(m)
            continue
        lignes.append({"top": m["top"], "taille": m.get("size") or 10.0, "mots": [m]})
    for li in lignes:
        li["mots"].sort(key=lambda w: w["x0"])
        li["texte"] = " ".join(w["text"] for w in li["mots"])
        li["taille"] = statistics.median(w.get("size") or 10.0 for w in li["mots"])
        li["bottom"] = max(w["bottom"] for w in li["mots"])
    return lignes


PUCE_RE = re.compile(r"^([-•–*·▪●○■□➢►✓]|\d{1,3}[.)°]|[a-z][.)])\s")
PRIVE_RE = re.compile("[\ue000-\uf8ff]")  # glyphes Symbol/Wingdings (puces) sans équivalent Unicode


def _nettoyer(texte: str) -> str:
    """Puce en glyphe privé → « - » ; autres glyphes privés supprimés."""
    texte = texte.strip()
    if PRIVE_RE.match(texte):
        texte = "- " + texte[1:].lstrip()
    return " ".join(PRIVE_RE.sub("", texte).split())


def _paragraphes(lignes: list[dict], corps: float) -> list[tuple[float, str]]:
    """Blocs (ordonnée, markdown) : titres par taille relative, paragraphes par interligne, césures recollées."""
    blocs: list[tuple[float, str]] = []
    courant: list[str] = []
    debut = 0.0
    precedente: dict | None = None

    def vider() -> None:
        if courant:
            texte = ""
            for morceau in courant:
                if texte.endswith("-") and morceau[:1].islower():
                    texte = texte[:-1] + morceau
                else:
                    texte = f"{texte} {morceau}" if texte else morceau
            blocs.append((debut, texte))
            courant.clear()

    titre_prec: dict | None = None
    for li in lignes:
        texte = _nettoyer(li["texte"])
        if not texte:
            continue
        ratio = li["taille"] / corps if corps else 1
        if ratio >= 1.2 and len(texte) <= 150:
            vider()
            niveau = "## " if ratio >= 1.5 else "### "
            suite = (titre_prec is not None and blocs and blocs[-1][1].startswith(niveau)
                     and abs(li["taille"] - titre_prec["taille"]) < 0.5
                     and li["top"] - titre_prec["bottom"] <= 0.8 * li["taille"])
            if suite:  # titre sur plusieurs lignes : un seul titre
                blocs[-1] = (blocs[-1][0], f"{blocs[-1][1]} {texte}")
            else:
                blocs.append((li["top"], niveau + texte))
            titre_prec, precedente = li, None
            continue
        titre_prec = None
        saut = precedente is not None and li["top"] - precedente["bottom"] > 0.8 * li["taille"]
        if precedente is None or saut or PUCE_RE.match(texte):
            vider()
            debut = li["top"]
        courant.append(texte)
        precedente = li
    vider()
    return blocs


def taille_corps(pages: list) -> float:
    """Taille de police du corps du texte : la plus fréquente, pondérée par le nombre de caractères."""
    compte: dict[float, int] = {}
    for p in pages:
        for c in p.chars:
            t = round(c.get("size") or 0, 1)
            if t:
                compte[t] = compte.get(t, 0) + 1
    return max(compte, key=compte.get) if compte else 10.0


def page_native(page, corps: float) -> str:
    tables = []
    try:
        for t in page.find_tables():
            md = table_markdown(t.extract())
            if md:
                tables.append((t.bbox, md))
    except Exception:  # pdfminer peut échouer sur une page mal formée : texte seul
        tables = []
    mots = page.extract_words(extra_attrs=["size"], keep_blank_chars=False, use_text_flow=False)
    mots = [m for m in mots if not any(_dans(m, bbox) for bbox, _ in tables)]
    blocs = _paragraphes(_lignes(mots), corps) + [(bbox[1], md) for bbox, md in tables]
    return "\n\n".join(md for _, md in sorted(blocs, key=lambda b: b[0]))


def _couverture_images(page) -> float:
    aire = float(page.width * page.height) or 1.0
    total = 0.0
    for im in page.images:
        x0, x1 = max(0.0, float(im["x0"])), min(float(page.width), float(im["x1"]))
        top, bottom = max(0.0, float(im["top"])), min(float(page.height), float(im["bottom"]))
        total += max(0.0, x1 - x0) * max(0.0, bottom - top)
    return min(1.0, total / aire)


# --- OCR -------------------------------------------------------------------------------------------------

def ocr_image(image, langue: str) -> tuple[str, float]:
    """OCR Tesseract d'une image PIL : paragraphes reconstitués et confiance moyenne des mots (0-100)."""
    import pytesseract

    data = pytesseract.image_to_data(image, lang=langue, output_type=pytesseract.Output.DICT)
    paras: dict[tuple[int, int], list[list[str]]] = {}
    confs: list[float] = []
    derniere: dict[tuple[int, int], int] = {}
    for i, mot in enumerate(data["text"]):
        mot = (mot or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if not mot or conf < 0:
            continue
        confs.append(conf)
        cle = (data["block_num"][i], data["par_num"][i])
        lignes = paras.setdefault(cle, [])
        if derniere.get(cle) != data["line_num"][i]:
            lignes.append([])
            derniere[cle] = data["line_num"][i]
        lignes[-1].append(mot)
    blocs = []
    for lignes in paras.values():
        texte = ""
        for ligne in (" ".join(m) for m in lignes):
            if texte.endswith("-") and ligne[:1].islower():
                texte = texte[:-1] + ligne
            else:
                texte = f"{texte} {ligne}" if texte else ligne
        blocs.append(texte)
    return "\n\n".join(blocs), (sum(confs) / len(confs) if confs else 0.0)


def nb_pages(pdf: Path) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        return len(doc)
    finally:
        doc.close()


def rendre_page(pdf: Path, index: int, dpi: int = DPI_OCR, gris: bool = True):
    """Page d'un PDF (index 0) en image PIL : OCR ici, lecture par la vision dans archive_image."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        return doc[index].render(scale=dpi / 72, grayscale=gris).to_pil()
    finally:
        doc.close()


# --- conversion ------------------------------------------------------------------------------------------

def _tokens_image(largeur: float, hauteur: float) -> int:
    h = LARGEUR_IMAGE_REF * (hauteur / largeur) if largeur else LARGEUR_IMAGE_REF
    return round(LARGEUR_IMAGE_REF * h * TOKENS_PER_PIXEL)


def _chemins(cache_dir: Path, sha: str, langue: str, forcer_ocr: bool) -> tuple[Path, Path]:
    stem = f"{sha[:32]}-{langue.replace('+', '_')}-v{VERSION}" + ("-ocr" if forcer_ocr else "")
    return cache_dir / f"{stem}.md", cache_dir / f"{stem}.json"


def convertir(chemin: str, cache_dir: Path, langue: str = "fra", forcer_ocr: bool = False,
              reconvertir: bool = False) -> dict:
    """Convertit un PDF en Markdown (une section par page) dans le cache ; renvoie chemin et statistiques."""
    import pdfplumber

    langue = (langue or "fra").strip().lower()
    if not LANGUE_RE.match(langue):
        raise PdfErreur("langue : code Tesseract attendu (fra, lat, fra+lat…).")
    pdf = Path(chemin).expanduser()
    if not pdf.is_file():
        raise PdfErreur(f"Fichier introuvable : {pdf}")
    data = pdf.read_bytes()
    if not data.startswith(b"%PDF"):
        raise PdfErreur("Le fichier n'est pas un PDF (signature %PDF absente).")
    sha = hashlib.sha256(data).hexdigest()
    cache_dir = Path(cache_dir)
    md_path, meta_path = _chemins(cache_dir, sha, langue, forcer_ocr)
    if not reconvertir and md_path.is_file() and meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return {**meta, "chemin_absolu": str(md_path), "source": str(pdf), "deja_converti": True}
        except (OSError, ValueError):
            pass

    ok_ocr, motif_ocr = ocr_disponible(langue)
    sections: list[str] = []
    pages_info: list[dict] = []
    tokens_images = 0
    try:
        with pdfplumber.open(pdf) as doc:
            corps = taille_corps(doc.pages)
            n = len(doc.pages)
            for i, page in enumerate(doc.pages):
                num = i + 1
                tokens_images += _tokens_image(float(page.width), float(page.height))
                texte_natif = "" if forcer_ocr else (page.extract_text() or "")
                nb = len(texte_natif.strip())
                scan = nb < SEUIL_TEXTE or (nb < SEUIL_IMAGE_TEXTE and _couverture_images(page) >= COUVERTURE_IMAGE)
                if not scan:
                    sections.append(f"<!-- page {num}/{n} · texte natif -->\n\n{page_native(page, corps)}")
                    pages_info.append({"page": num, "mode": "natif"})
                    continue
                if not ok_ocr:
                    motif = motif_ocr
                    texte, conf = "", None
                else:
                    try:
                        texte, conf = ocr_image(rendre_page(pdf, i), langue)
                        motif = ""
                        if len(texte.strip()) < SEUIL_TEXTE:
                            motif = "ocr_vide"
                        elif conf < CONFIANCE_OCR_MIN:
                            motif = "ocr_peu_fiable"
                    except Exception as e:  # rendu ou OCR en échec : la vision prend le relais
                        texte, conf, motif = "", None, f"ocr_echec:{type(e).__name__}"
                if motif:
                    sections.append(f"<!-- page {num}/{n} · à lire en image ({motif}) -->\n\n"
                                    f"_Page non convertie : lire l'image (archive_image, page={num})._")
                    pages_info.append({"page": num, "mode": "vision", "motif": motif,
                                       **({"confiance_ocr": round(conf)} if conf is not None else {})})
                else:
                    sections.append(f"<!-- page {num}/{n} · OCR {langue}, confiance {round(conf)} -->\n\n{texte}")
                    pages_info.append({"page": num, "mode": "ocr", "confiance_ocr": round(conf)})
    except PdfErreur:
        raise
    except Exception as e:
        raise PdfErreur(f"PDF illisible ({type(e).__name__}) : chiffré, corrompu ou non pris en charge.") from e

    entete = f"<!-- {pdf.name} · sha256 {sha[:16]} · {len(pages_info)} page(s) · genealogiste pdf_markdown v{VERSION} -->"
    markdown = entete + "\n\n" + "\n\n".join(sections) + "\n"
    a_lire = [p["page"] for p in pages_info if p["mode"] == "vision"]
    tokens_md = round(len(markdown) / CARACTERES_PAR_TOKEN)
    meta = {
        "sha256": sha, "langue": langue, "version": VERSION, "nb_pages": len(pages_info),
        "pages_natives": [p["page"] for p in pages_info if p["mode"] == "natif"],
        "pages_ocr": [p["page"] for p in pages_info if p["mode"] == "ocr"],
        "pages_a_lire_en_image": a_lire, "pages": pages_info,
        "tokens_estimes_markdown": tokens_md, "tokens_estimes_images": tokens_images,
        "economie_estimee": (f"{round(100 * (1 - tokens_md / tokens_images))} %" if tokens_images else None),
        "ocr": "disponible" if ok_ocr else motif_ocr,
    }
    ecrire_atomique(md_path, markdown)
    ecrire_atomique(meta_path, json.dumps(meta, ensure_ascii=False, indent=1))
    return {**meta, "chemin_absolu": str(md_path), "source": str(pdf), "deja_converti": False}
