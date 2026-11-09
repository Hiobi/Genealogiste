"""Archivage d'une pièce d'archives en ligne dans le vault (#70).

Une vue (ARK Gallica, manifeste ou service IIIF, URL d'image directe, fichier téléchargé depuis une visionneuse)
est conservée en pleine résolution et en couleur, nommée selon la convention (docs/pieces.md), rangée dans
documents/<type>/<NOM>/ et accompagnée d'une note Markdown (ARK, URL, vue, consultation, personnes, source).
Le registre <données>/pieces-archivees.jsonl garantit qu'une vue n'est jamais retéléchargée."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from . import pieces
from .chemins import nom_simple, sous
from .fichiers import ajouter_jsonl, ecrire_atomique, lire_jsonl
from .markdown import lien_fichier

MIME = {".jpg": "image/jpeg", ".png": "image/png", ".tif": "image/tiff", ".pdf": "application/pdf",
        ".gif": "image/gif", ".webp": "image/webp"}


class ArchivageError(ValueError):
    pass


def registre(path: Path) -> list[dict]:
    return lire_jsonl(path)[0]


def deja_archivee(path: Path, cle: str = "", empreinte: str = "", source: str = "", page_demandee: int = 0) -> dict | None:
    """Entrée du registre dont le fichier existe encore avec la même empreinte (par clé de vue ou contenu)."""
    for e in reversed(registre(path)):
        meme_source = source and e.get("source") == source and e.get("page_demandee") == page_demandee
        if meme_source or (cle and e.get("cle") == cle) or (empreinte and e.get("sha256") == empreinte):
            f = Path(e.get("chemin_absolu", ""))
            if f.is_file() and pieces.sha256(f) == e.get("sha256"):
                return e
    return None


def nom_piece(personnes: list[str], extension: str, nom: str = "", **segments) -> str:
    """Nom selon la convention ; sans personne connue : « DÉPÔT - cote - p.vue », rangé dans _À trier."""
    if nom:
        n = pieces.nom_compatible(nom_simple(nom))
        return n if Path(n).suffix.lower() in set(MIME) | {".jpeg", ".tiff"} else n + extension
    if personnes:
        return pieces.nommer(personnes, extension=extension, **segments)
    parts = [segments.get("depot") or "Archive", segments.get("cote", ""),
             f"p.{segments['vue']}" if segments.get("vue") else ""]
    return pieces.nom_compatible(" - ".join(x for x in parts if x) + extension)


def emplacement(racine: Path, nom: str, contenu: bytes, dossier: str = "") -> tuple[Path, bool]:
    """(chemin, existe déjà avec ce contenu) : dossier de la convention sous la racine des pièces, suffixe
    « (n) » si collision."""
    sub = dossier or pieces.destination(pieces.detecter(Path(nom))) or pieces.A_TRIER
    cible = sous(racine, Path(sub) / nom)
    stem, ext = cible.stem, cible.suffix
    n = 1
    while cible.exists():
        if cible.read_bytes() == contenu:
            return cible, True
        n += 1
        cible = cible.with_name(f"{stem} ({n}){ext}")
    return cible, False


def _yaml(v) -> str:
    import json
    if isinstance(v, list):
        return "[" + ", ".join(_yaml(x) for x in v) + "]"
    if isinstance(v, int):
        return str(v)
    return json.dumps(str(v), ensure_ascii=False)


def note_compagnon(image: Path, meta: dict, personnes_liens: list[str], source_lien: str) -> Path:
    """Note Markdown à côté de l'image : propriétés (Obsidian) et image affichée ; liens vers personnes et source
    (vue graphique). Jamais réécrite si elle existe (texte ajouté à la main préservé)."""
    note = image.with_suffix(".md")
    if note.exists():
        return note
    fm = {"type": "piece", "fichier": image.name, **{k: v for k, v in meta.items() if v not in ("", None, [])}}
    if personnes_liens:
        fm["personnes"] = personnes_liens
    if source_lien:
        fm["source"] = source_lien
    lignes = ["---", *(f"{k}: {_yaml(v)}" for k, v in fm.items()), "---", "", f"# {image.stem}", "",
              lien_fichier(image.name, image=True), ""]
    if personnes_liens:
        lignes.append("- **Personnes** : " + ", ".join(personnes_liens))
    if source_lien:
        lignes.append(f"- **Source** : {source_lien}")
    lien = meta.get("ark") or meta.get("url") or meta.get("url_image")
    if lien:
        label = "Lien pérenne" if meta.get("ark") else "Lien fourni (pérennité non établie)"
        lignes.append(f"- **{label}** : {lien}" + (f" (vue {meta['vue']})" if meta.get("vue") else ""))
    if meta.get("reutilisation"):
        lignes.append(f"- **Réutilisation** : {meta['reutilisation']}")
    lignes += ["", "## Notes", "", "<!-- Transcription, remarques : texte libre, jamais modifié par l'outil. -->", ""]
    ecrire_atomique(note, "\n".join(lignes))
    return note


def enregistrer(path_registre: Path, entree: dict) -> None:
    ajouter_jsonl(path_registre, {**entree, "date": date.today().isoformat()})


def empreinte(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relocaliser(path: Path, racine: Path, mouvements: list[dict], media_ref) -> None:
    """Ajouter les nouvelles localisations au registre sans réécrire son historique."""
    par_chemin = {str(racine / m["de"]): m for m in mouvements}
    derniers = {(e.get("cle"), e.get("source"), e.get("page_demandee")): e for e in registre(path)}
    for entree in derniers.values():
        mouvement = par_chemin.get(entree.get("chemin_absolu"))
        if not mouvement or mouvement["sha256"] != entree.get("sha256"):
            continue
        nouveau = racine / mouvement["vers"]
        nouvelle = {**entree, "chemin_absolu": str(nouveau), "fichier": media_ref(nouveau)}
        note = par_chemin.get(str((racine / mouvement["de"]).with_suffix(".md")))
        if note:
            nouvelle["note"] = media_ref(racine / note["vers"])
        enregistrer(path, nouvelle)
