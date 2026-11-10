"""Planche-contact : une seule image composite pour repérer une vue dans un registre.

Remplace N aperçus par une grille de 4 à 12 vues, numéro de vue incrusté, composée en local (Pillow).
Une requête et un téléchargement par vue au plus : les originales vont dans le cache partagé avec
``archive_image`` et ``piece_archiver`` (jamais retéléchargées), les miniatures dans un cache à part.
Pas de moisson : 12 vues maximum, arrêt à la première erreur ou protection, aucun contournement.

Registres AD59 (visionneuse qualifiée) uniquement ; les autres sources renvoient une erreur explicite.
La miniature annoncée par l'API (``location.thumb``) ne fait que 100 px : elle sert au repérage de la mise en
page (option ``miniatures``), pas à lire une date."""

from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path

from ..fichiers import ecrire_atomique
from ..http import SourceError
from . import iiif
from .base import SourceContext, error_envelope
from .visionneuses import VisionneuseError, planche_vues

MAX_VUES = 12
MAX_COTE = 1600  # pixels, côté le plus long de la planche
LARGEUR_DEFAUT = 1200
_COLONNES = {1: 1, 2: 2, 3: 3, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4, 9: 3, 10: 5, 11: 4, 12: 4}


def _positions(de: int, a: int, pas: int) -> tuple[list[int], str]:
    if de < 1:
        raise iiif.IiifError("de : première vue à partir de 1.")
    pas = max(1, int(pas or 1))
    a = int(a or 0) or de + 5 * pas  # défaut : 6 vues
    if a < de:
        raise iiif.IiifError("a : doit être supérieur ou égal à de.")
    positions = list(range(de, a + 1, pas))
    avert = ""
    if len(positions) > MAX_VUES:
        positions = positions[:MAX_VUES]
        avert = f"Planche limitée à {MAX_VUES} vues (jusqu'à la vue {positions[-1]}) ; refaire une planche pour la suite."
    return positions, avert


def _miniature(ctx: SourceContext, url: str) -> bytes:
    dest = ctx.config.cache_images_dir / "miniatures" / (hashlib.sha256(url.encode()).hexdigest() + ".jpg")
    if dest.is_file() and not dest.is_symlink():
        return dest.read_bytes()
    raw, _ = ctx.http.get(url, parse="bytes", use_cache=False, source="visionneuse")
    data = raw.encode("latin-1")
    if not iiif.extension_of(data):
        raise iiif.IiifError("La miniature n'est pas une image (accès refusé ?) ; aucun contournement.")
    ecrire_atomique(dest, data)
    return data


def _image_vue(ctx: SourceContext, vue: dict, miniatures: bool) -> tuple[bytes, bool]:
    """Octets de l'image d'une vue et indicateur de téléchargement réel (False : cache)."""
    if miniatures and vue.get("url_miniature"):
        return _miniature(ctx, vue["url_miniature"]), False
    if not vue.get("url_image"):
        raise iiif.IiifError(f"Vue {vue['vue']} sans image téléchargeable ; fournir le fichier local.")
    chemin, telecharge, _ = iiif._originale(ctx, {"mode": "url_directe", "url_image": vue["url_image"]})
    return Path(chemin).read_bytes(), telecharge


def _police(taille: int):
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=taille)
    except TypeError:  # Pillow < 10.1 : police bitmap fixe
        return ImageFont.load_default()


def composer(images: list[tuple[int, bytes]], largeur: int, gris: bool, bandeau: str) -> tuple[bytes, list[int], list[int]]:
    """Grille des vues [(numéro, octets)] ; renvoie (JPEG, [colonnes, lignes], [largeur, hauteur])."""
    from PIL import Image, ImageDraw

    n = len(images)
    colonnes = _COLONNES[n] if n in _COLONNES else math.ceil(math.sqrt(n))
    lignes = math.ceil(n / colonnes)
    ouvertes = []
    for num, data in images:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            if bandeau:
                im = im.crop(iiif._crop_box(bandeau, *im.size))
            ouvertes.append((num, im.convert("L") if gris else im.convert("RGB")))
    ratio = max(im.height / im.width for _, im in ouvertes)  # cellule adaptée à la vue la plus haute
    cellule_l = max(1, largeur // colonnes)
    cellule_h = max(1, round(cellule_l * ratio))
    if cellule_h * lignes > MAX_COTE:
        cellule_h = MAX_COTE // lignes
        cellule_l = max(1, round(cellule_h / ratio))
    planche = Image.new("L" if gris else "RGB", (cellule_l * colonnes, cellule_h * lignes), 255 if gris else (255, 255, 255))
    dessin = ImageDraw.Draw(planche)
    taille = max(14, round(cellule_h / 9))
    police = _police(taille)
    for i, (num, im) in enumerate(ouvertes):
        im.thumbnail((cellule_l - 2, cellule_h - 2), Image.LANCZOS)
        x, y = (i % colonnes) * cellule_l, (i // colonnes) * cellule_h
        planche.paste(im, (x + 1, y + 1))
        etiquette = str(num)
        boite = dessin.textbbox((x + 3, y + 3), etiquette, font=police)
        dessin.rectangle((x + 1, y + 1, boite[2] + 3, boite[3] + 3), fill=0 if gris else (0, 0, 0))  # pastille au coin
        dessin.text((x + 3, y + 3), etiquette, fill=255 if gris else (255, 255, 255), font=police)
        dessin.rectangle((x, y, x + cellule_l - 1, y + cellule_h - 1), outline=128 if gris else (128, 128, 128))
    sortie = io.BytesIO()
    planche.save(sortie, "JPEG", quality=85)
    return sortie.getvalue(), [colonnes, lignes], list(planche.size)


def planche(ctx: SourceContext, source: str, de: int, a: int = 0, pas: int = 1, bandeau: str = "",
            largeur: int = LARGEUR_DEFAUT, gris: bool = True, miniatures: bool = False) -> dict:
    """Planche-contact d'un registre AD59 ; renvoie le chemin du JPEG composite, les vues et le coût estimé."""
    params = {"source": source, "de": de, "a": a, "pas": pas, "bandeau": bandeau, "miniatures": miniatures}
    telechargees = 0
    try:
        if bandeau and bandeau != "full":
            iiif._valider_region(bandeau)
            if not bandeau.startswith("pct:"):
                raise iiif.IiifError("bandeau : zone en pourcentage, par exemple pct:0,0,100,35.")
        largeur = max(200, min(int(largeur or LARGEUR_DEFAUT), MAX_COTE))
        positions, avertissement = _positions(de, a, pas)
        info = planche_vues(ctx, source, positions)
        if info is None:
            raise iiif.IiifError("Planche-contact disponible pour les registres AD59 (visionneuse qualifiée) ; "
                                 "pour une autre source, utiliser archives_naviguer puis archive_image.")
        images = []
        for vue in info["vues"]:
            data, telecharge = _image_vue(ctx, vue, miniatures)
            telechargees += int(telecharge)
            images.append((vue["vue"], data))
        if not images:
            raise iiif.IiifError("Aucune des vues demandées n'existe dans ce registre.")
        jpeg, grille, dimensions = composer(images, largeur, gris, bandeau if bandeau != "full" else "")
        cle = hashlib.sha256(f"{info['ark_ressource']}|{[v for v, _ in images]}|{bandeau}|{largeur}|{gris}|"
                             f"{miniatures}".encode()).hexdigest()[:16]
        dest = ctx.config.cache_images_dir / "planches" / f"{cle}.jpg"
        ecrire_atomique(dest, jpeg)
    except (iiif.IiifError, VisionneuseError, SourceError, OSError) as exc:
        failure = error_envelope(ctx, "visionneuse", "planche", params, exc)
        return {"erreur": str(exc), "source": source, "telechargements": telechargees,
                "journal": failure["journal"]}
    manquantes = list(info["absentes"])
    out = {"chemin_absolu": str(dest), "vues": [v for v, _ in images], "grille": grille,
           "dimensions_demandees": dimensions,
           "cout_estime_tokens": round(dimensions[0] * dimensions[1] * iiif.TOKENS_PER_PIXEL),
           "registre": info["ark_ressource"], "nb_vues": info["nb_vues"], "telechargements": telechargees,
           "images": "miniatures (100 px : mise en page seulement)" if miniatures else "originaux (cache partagé)"}
    if manquantes:
        out["vues_absentes"] = manquantes
    if avertissement:
        out["avertissement"] = avertissement
    ctx.journal.add(source="visionneuse", operation="planche", parametres=params, statut="positif",
                    resume=f"{len(images)} vues, {telechargees} téléchargement(s)", references=[source])
    return {k: v for k, v in out.items() if v not in (None, "", [])}
