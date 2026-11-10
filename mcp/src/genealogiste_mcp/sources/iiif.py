"""Images d'actes par IIIF : aperçu basse définition, puis recadrage de l'acte, avec un coût en tokens maîtrisé.

Entrées : IIIF v2/v3 (tous pays), image directe, fichier local, ARK Gallica, visionneuse qualifiée AD59.
Les pages déclarant un manifeste sont inspectées côté Python ; aucun HTML/JavaScript ni manifeste entier
n'est envoyé au modèle. Les autres interfaces nécessitent un adaptateur qualifié ou un repli manuel.
Les originales sans IIIF sont partagées entre aperçus, recadrages et archivage ; les vues voisines ne sont
jamais téléchargées. Les contraintes de cache restent propres au fournisseur (notamment NARA).

Une image n'est téléchargée qu'une fois (``medias/``) ; une requête = une image, jamais de lot (CGU).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .. import ark
from ..fichiers import ecrire_atomique, verrou
from ..http import SourceError
from .base import DAY, SourceContext, error_envelope
from .visionneuses import VisionneuseError, VueResolue
from .visionneuses import resoudre as resoudre_visionneuse

MAX_WIDTH = 2000  # au-delà, le modèle réduit l'image : des pixels payés pour rien
PREVIEW_WIDTH = 800
TOKENS_PER_PIXEL = 1 / 750  # ordre de grandeur du coût d'une image pour le modèle
_REGION = re.compile(r"^(full|square|\d+,\d+,\d+,\d+|pct:[\d.]+,[\d.]+,[\d.]+,[\d.]+)$")
_IMAGE_URL = re.compile(r"^(?P<base>https?://.+?)/(?P<region>full|square|pct:[^/]+|\d+,\d+,\d+,\d+)/"
                        r"(?P<size>[^/]+)/(?P<rot>!?\d+(?:\.\d+)?)/(?P<q>\w+)\.(?P<fmt>\w+)(?P<query>\?[^#]*)?(?:#.*)?$")
CONSIGNE_AD = ("IIIF de ce service inconnu : ouvrir l'image dans la visionneuse des archives. Si elle propose "
               "« Copier le lien IIIF », rappeler l'outil avec ce lien ; sinon utiliser « Télécharger » et rappeler "
               "l'outil avec le chemin du fichier (ou l'URL directe de l'image) : recadrage fait en local.")
_DIRECT = re.compile(r"^https?://[^?#]+\.(jpe?g|png|tiff?|webp)(\?.*)?$", re.I)


class IiifError(ValueError):
    pass


def _id(o) -> str:
    if isinstance(o, list):
        o = o[0] if o else {}
    if isinstance(o, str):
        return o
    return (o.get("@id") or o.get("id") or "") if isinstance(o, dict) else ""


def canvases(manifest: dict) -> list[dict]:
    """[{label, service}] des vues d'un manifeste IIIF v2 ou v3."""
    out = []
    if "sequences" in manifest:  # Presentation 2
        for c in (manifest["sequences"] or [{}])[0].get("canvases", []):
            res = ((c.get("images") or [{}])[0]).get("resource", {})
            if not isinstance(res, dict) or res.get("@type", "Image") not in {"Image", "dctypes:Image"}:
                res = {}
            view = {"label": _label(c.get("label")), "service": _id(res.get("service")).rstrip("/")}
            if not view["service"]:
                view["url_image"] = _id(res)
            out.append(view)
    else:  # Presentation 3
        for c in manifest.get("items", []):
            body = (((c.get("items") or [{}])[0].get("items") or [{}])[0]).get("body", {})
            if isinstance(body, list):
                body = body[0] if body else {}
            if not isinstance(body, dict) or body.get("type", "Image") not in {"Image", "dctypes:Image"}:
                body = {}
            view = {"label": _label(c.get("label")), "service": _id(body.get("service")).rstrip("/")}
            if not view["service"]:
                view["url_image"] = _id(body)
            out.append(view)
    return out


def _label(v) -> str:
    if isinstance(v, dict):  # v3 : {"fr": ["Vue 12"]}
        vals = next(iter(v.values()), [])
        v = vals
    if isinstance(v, list):
        v = v[0] if v else ""
    return v[:4000] if isinstance(v, str) else ""



def _valider_region(region: str) -> None:
    if not _REGION.fullmatch(region):
        raise IiifError("region : full | square | x,y,l,h | pct:x,y,l,h")
    if region in {"full", "square"}:
        return
    try:
        values = [float(v) for v in region.removeprefix("pct:").split(",")]
    except ValueError as exc:
        raise IiifError("Coordonnées de recadrage invalides.") from exc
    if not all(math.isfinite(v) for v in values) or min(values[:2]) < 0 or min(values[2:]) <= 0:
        raise IiifError("La zone doit avoir des coordonnées finies et une taille strictement positive.")


def _service_url(service: str, suffix: str) -> str:
    value = urlsplit(service)
    return value._replace(path=value.path.rstrip("/") + "/" + suffix, fragment="").geturl()


def image_url(service: str, region: str = "full", largeur: int = PREVIEW_WIDTH, gris: bool = True) -> str:
    _valider_region(region)
    return _service_url(service, f"{region}/{largeur},/0/{'gray' if gris else 'default'}.jpg")


def _resolution_ttl(url: str, default: float) -> float:
    # Conditions de l'API NARA : aucun stockage/cache des réponses (voir étude internationale).
    return 0 if urlsplit(url).hostname == "catalog.archives.gov" else default


def _json(ctx: SourceContext, url: str) -> dict:
    data, _ = ctx.http.get(url, ttl=_resolution_ttl(url, 30 * DAY), source="iiif", headers={"Accept": "application/json"})
    if not isinstance(data, dict):
        raise IiifError(f"Réponse IIIF inattendue : {url}")
    return data



class _ManifestLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        href = a.get("href") or ""
        if tag in {"link", "a"} and href and ("manifest" in (a.get("rel") or "").split()
                or re.search(r"(?:iiif.*manifest|manifest(?:\.json|/|$))", href, re.I)):
            self.links.add(href)


def _document(ctx: SourceContext, url: str) -> dict:
    # Une page HTML au plus : le code filtre les liens déclarés, aucun HTML/JS n'est envoyé au modèle.
    text, _ = ctx.http.get(url, parse="text", ttl=_resolution_ttl(url, 7 * DAY), source="iiif")
    if len(text) > 5_000_000:
        raise IiifError("Document de résolution trop volumineux : fournir le lien IIIF direct.")
    try:
        data = json.loads(text)
    except ValueError:
        parser = _ManifestLinks()
        parser.feed(text)
        links = {urljoin(url, link) for link in parser.links}
        if len(links) != 1:
            raise IiifError("Plusieurs manifestes possibles : fournir le lien IIIF voulu." if links else CONSIGNE_AD) from None
        return _json(ctx, links.pop())
    if not isinstance(data, dict):
        raise IiifError("Document IIIF inattendu : fournir une image ou un manifeste de document.")
    return data


def resoudre_vue(ctx: SourceContext, source: str, page: int = 0) -> dict:
    """Résolution commune aux aperçus et à l'archivage, indépendante de la présence d'un ARK."""
    if page < 0:
        raise IiifError("page : 0 pour la vue du lien, sinon un numéro à partir de 1.")
    src = (source or "").strip()
    if src and not src.startswith(("http://", "https://")) and Path(src).expanduser().is_file():
        return {**VueResolue("fichier", vue=page or None).localisation(), "fichier_source": str(Path(src).expanduser())}
    if _DIRECT.match(src) and not _IMAGE_URL.match(src):
        return VueResolue("url_directe", url_image=src, vue=page or None).localisation()
    explicit_iiif = bool(_IMAGE_URL.match(src) or urlsplit(src).path.endswith("/info.json")
                         or re.search(r"/manifest(?:\.json)?(?:$|[?#])", src, re.I))
    try:
        view = None if explicit_iiif else resoudre_visionneuse(ctx, src, page)
    except VisionneuseError as exc:
        raise IiifError(str(exc)) from exc
    if view:
        return view.localisation()
    loc = locate(ctx, src, page)
    result = VueResolue("iiif", service_iiif=loc.get("service", ""), url_image=loc.get("url_image", ""),
                        vue=loc.get("vue"), nb_vues=loc.get("nb_vues"),
                        titre_registre=loc.get("titre_registre", ""), licence=loc.get("licence", "")).localisation()
    result.update(loc)
    # L'URL Image API contient region/taille/rotation : ces segments ne font pas partie de l'ARK.
    a = ark.find(loc.get("service", "")) or ark.find(src)
    if a:
        if a.naan == "12148" and (loc.get("vue") or a.vue):
            result["vue"] = loc.get("vue") or a.vue
            result["ark_vue"] = a.base + f"/f{result['vue']}"
        else:
            result["ark_vue"] = a.id if a.qualificatif not in {"", "manifest", "manifest.json"} else ""
        result["ark_ressource"] = a.base
        result["depot"] = (a.service or {}).get("code", "")
    return result


def locate(ctx: SourceContext, source: str, page: int = 0) -> dict:
    """Service d'image IIIF d'une vue : {service, vue, nb_vues?, manifeste?}."""
    s = (source or "").strip()
    m = _IMAGE_URL.match(s)
    if m:
        return {"service": m.group("base") + (m.group("query") or ""), "vue": page or None}
    parsed = urlsplit(s)
    if parsed.path.endswith("/info.json"):
        return {"service": parsed._replace(path=parsed.path[:-len("/info.json")], fragment="").geturl(),
                "vue": page or None}
    a = ark.find(s)
    if a and a.naan == "12148" and not s.endswith("manifest.json"):  # Gallica : vue = fNN ou page
        vue = page or a.vue or 1
        return {"service": f"https://gallica.bnf.fr/iiif/{a.base}/f{vue}", "vue": vue,
                "manifeste": f"https://gallica.bnf.fr/iiif/{a.base}/manifest.json"}
    if a and not a.hote and not re.search(r"manifest|iiif", s, re.I):
        raise IiifError(CONSIGNE_AD)
    if not s.startswith(("http://", "https://")):
        raise IiifError("source : ARK Gallica, manifeste IIIF, info.json ou URL d'image IIIF.")
    data = _document(ctx, s)
    if data.get("protocol") == "http://iiif.io/api/image" or "profile" in data and "width" in data:
        return {"service": _id(data).rstrip("/") or s, "vue": page or None}
    views = canvases(data)
    if not views:
        raise IiifError("Document sans vue IIIF exploitable. " + CONSIGNE_AD)
    i = (page or 1) - 1
    if not 0 <= i < len(views):
        raise IiifError(f"Vue {page} hors du manifeste ({len(views)} vues).")
    view = views[i]
    if not view.get("service") and not view.get("url_image"):
        raise IiifError("La vue sélectionnée ne fournit ni service IIIF ni image téléchargeable.")
    return {**view, "vue": i + 1, "nb_vues": len(views), "libelle": view["label"], "manifeste": s,
            "titre_registre": _label(data.get("label")),
            "licence": _label(data.get("rights") or data.get("license") or data.get("attribution"))}


def naviguer(ctx: SourceContext, source: str, page: int = 0, pas: int = 20) -> dict:
    """Fenêtre de vues d'un manifeste IIIF (v2/v3) : métadonnées du document et liste des vues."""
    data = _document(ctx, source)
    views = canvases(data)
    if not views:
        raise IiifError("Document sans vue IIIF exploitable. " + CONSIGNE_AD)
    debut = max(0, page - 1) if page else 0
    fin = min(len(views), debut + max(1, min(int(pas or 20), 100)))
    fenetre = []
    for i in range(debut, fin):
        v = views[i]
        fenetre.append({"vue": i + 1, "libelle": v.get("label", ""), "service_iiif": v.get("service", ""),
                        "url_image": v.get("url_image", "")})
    return {"mode": "iiif:manifeste", "registre": {"titre": _label(data.get("label")), "nb_vues": len(views),
            "licence": _label(data.get("rights") or data.get("license") or data.get("attribution"))},
            "vues": fenetre, "fenetre": {"de": debut + 1, "a": fin},
            "suite": "archive_image(<service_iiif>) ou archive_image(source, page=N) pour lire/archiver une vue."}


def _crop_box(region: str, w: int, h: int) -> tuple[int, int, int, int]:
    if region == "full":
        return 0, 0, w, h
    if region == "square":
        side = min(w, h)
        return (w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side
    if region.startswith("pct:"):
        x, y, rw, rh = (float(v) for v in region[4:].split(","))
        box = (w * x / 100, h * y / 100, w * (x + rw) / 100, h * (y + rh) / 100)
    else:
        x, y, rw, rh = (int(v) for v in region.split(","))
        box = (x, y, x + rw, y + rh)
    left, top, right, bottom = (round(v) for v in box)
    left, top = max(0, min(left, w - 1)), max(0, min(top, h - 1))
    return left, top, max(left + 1, min(right, w)), max(top + 1, min(bottom, h))


def local(ctx: SourceContext, media_dir: Path, source: str, region: str = "full", largeur: int = PREVIEW_WIDTH,
          gris: bool = True) -> dict:
    """Image sans IIIF (fichier local ou URL directe) : originale gardée une fois, zone réduite en local."""
    from PIL import Image

    _valider_region(region)
    path = Path(source).expanduser()
    downloaded = False
    if not path.is_file():
        path, downloaded, _ = _originale(ctx, {"mode": "url_directe", "url_image": source})
    key = hashlib.sha256(f"{path.resolve()}|{region}|{largeur}|{gris}".encode()).hexdigest()[:16]
    dest = media_dir / "iiif" / f"{key}.jpg"
    cached = dest.exists()
    with Image.open(path) as im:
        w, h = im.size
        box = _crop_box(region, w, h)
        if not cached:
            out = im.crop(box)
            out = out.convert("L") if gris else out.convert("RGB")
            if out.width > largeur:
                out = out.resize((largeur, max(1, round(out.height * largeur / out.width))), Image.LANCZOS)
            dest.parent.mkdir(parents=True, exist_ok=True)
            out.save(dest, "JPEG", quality=85)
    with Image.open(dest) as im:
        dw, dh = im.size
    return {"fichier": ctx.config.media_ref(dest), "chemin_absolu": str(dest), "depuis_cache": cached,
            "original": str(path), "original_telecharge": downloaded, "dimensions_originales": [w, h],
            "zone_pixels": list(box), "dimensions_demandees": [dw, dh],
            "cout_estime_tokens": round(dw * dh * TOKENS_PER_PIXEL),
            "largeur_demandee": largeur,
            **({"avertissement": "Largeur limitée à la résolution originale de la zone ; aucun agrandissement."}
               if dw < largeur else {})}


def fetch(ctx: SourceContext, media_dir: Path, source: str, page: int = 0, region: str = "full",
          largeur: int = PREVIEW_WIDTH, gris: bool = True) -> dict:
    """Télécharge (une fois) une vue ou une zone, à la largeur demandée ; renvoie le chemin à lire."""
    largeur = max(100, min(int(largeur or PREVIEW_WIDTH), MAX_WIDTH))
    try:
        _valider_region(region)
        loc = resoudre_vue(ctx, source, page)
        if not loc.get("service") or _chemin_originale(ctx, loc).is_file():
            if loc.get("fichier_source"):
                local_source = loc["fichier_source"]
            else:
                original, downloaded, _ = _originale(ctx, loc)
                local_source = str(original)
            out = local(ctx, media_dir, local_source, region, largeur, gris)
            if not loc.get("fichier_source"):
                out["original_telecharge"] = downloaded
            out.update({k: v for k, v in loc.items() if k not in {"service", "fichier_source"}})
            ctx.journal.add(source="iiif", operation="image_locale", parametres={"source": source, "region": region,
                                    "largeur": largeur}, statut="positif", resume=out["fichier"],
                            references=[source], cache=out["depuis_cache"])
            out["consigne"] = CONSIGNE_LIRE
            return out
        info = {}
        try:
            info = _json(ctx, _service_url(loc["service"], "info.json"))
        except (SourceError, IiifError):
            pass  # dimensions inconnues : pas d'estimation de coût
        demandee = largeur
        if info.get("width") and info.get("height"):
            rw, _ = _region_size(region, int(info["width"]), int(info["height"]))
            largeur = min(largeur, max(1, round(rw)))
        url = image_url(loc["service"], region, largeur, gris)
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        dest = media_dir / "iiif" / f"{key}.jpg"
        cached = dest.exists()
        if not cached:
            try:
                raw, _ = ctx.http.get(url, parse="bytes", use_cache=False, source="iiif")
            except SourceError as exc:
                if not gris or exc.status != 400:
                    raise
                url = image_url(loc["service"], region, largeur, False)  # serveur sans niveau de gris
                raw, _ = ctx.http.get(url, parse="bytes", use_cache=False, source="iiif")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw.encode("latin-1"))
    except (IiifError, SourceError, OSError) as exc:
        failure = error_envelope(ctx, "iiif", "image", {"source": source, "page": page, "region": region}, exc)
        return {"erreur": str(exc), "source": source, "journal": failure["journal"]}
    out = {"fichier": ctx.config.media_ref(dest), "chemin_absolu": str(dest), "url_image": url,
           "depuis_cache": cached, **{k: v for k, v in loc.items() if k not in {"service", "url_image"}}, "service_iiif": loc["service"], "dimensions_originales": None,
           "dimensions_demandees": None, "cout_estime_tokens": None, "largeur_demandee": demandee}
    if largeur < demandee:
        out["avertissement"] = "Largeur limitée à la résolution originale de la zone ; aucun agrandissement."
    if info.get("width") and info.get("height"):
        w, h = int(info["width"]), int(info["height"])
        rw, rh = _region_size(region, w, h)
        height = round(largeur * rh / rw) if rw else 0
        out["dimensions_originales"] = [w, h]
        out["dimensions_demandees"] = [largeur, height]
        out["cout_estime_tokens"] = round(largeur * height * TOKENS_PER_PIXEL)
    ctx.journal.add(source="iiif", operation="image", parametres={"source": source, "vue": loc.get("vue"),
                                                                    "region": region, "largeur": largeur},
                    statut="positif", resume=out["fichier"], references=[url], cache=cached)
    out["consigne"] = CONSIGNE_LIRE
    return out


# ---------------------------------------------------------------------------- sortie d'archive_image

CHAMPS_MINIMAUX = ("chemin_absolu", "vue", "nb_vues", "ark_vue", "dimensions_originales", "dimensions_demandees",
                   "cout_estime_tokens", "avertissement")
CHAMPS_REGISTRE = ("titre_registre", "cote", "commune", "periode")


def sortie_minimale(ctx: SourceContext, out: dict, details: bool = False) -> dict:
    """Réduit la réponse de ``fetch`` à ce que le modèle lit : l'image et sa place dans le registre.

    Filtre d'affichage seulement : la résolution partagée avec ``piece_archiver`` n'est pas modifiée. Les
    métadonnées du registre ne sont données qu'au premier aperçu de ce registre dans la session (ou avec
    ``details``) ; la licence n'est jamais renvoyée ici, ``piece_archiver`` la conserve."""
    if "erreur" in out:
        return out
    res = {k: out[k] for k in CHAMPS_MINIMAUX if out.get(k) not in (None, "", [])}
    registre = out.get("ark_ressource") or ""
    if registre:
        res["registre"] = registre
    premier = bool(registre) and registre not in ctx.registres_vus
    if registre:
        ctx.registres_vus.add(registre)
    if details or premier:
        for k in CHAMPS_REGISTRE:
            if out.get(k):
                res[k] = list(out[k]) if k == "periode" else out[k]
    return res


# ---------------------------------------------------------------------------- archivage (pleine résolution)

_MAGIC = ((b"\xff\xd8", ".jpg"), (b"\x89PNG", ".png"), (b"II*\x00", ".tif"), (b"MM\x00*", ".tif"),
          (b"%PDF", ".pdf"), (b"GIF8", ".gif"))


def extension_of(data: bytes) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return next((ext for magic, ext in _MAGIC if data.startswith(magic)), "")


def _cle(loc: dict) -> str:
    if loc.get("fichier_source"):
        return "fichier:" + hashlib.sha256(Path(loc["fichier_source"]).read_bytes()).hexdigest()
    return "iiif:" + loc["service"] if loc.get("service") else "url:" + loc["url_image"]


def archive_key(ctx: SourceContext, source: str, page: int = 0) -> tuple[str, dict]:
    loc = resoudre_vue(ctx, source, page)
    return _cle(loc), loc


def _chemin_originale(ctx: SourceContext, loc: dict) -> Path:
    root = ctx.config.cache_images_dir.resolve()
    path = root / "originaux" / (hashlib.sha256(_cle(loc).encode()).hexdigest() + ".bin")
    if path.is_symlink() or not path.parent.resolve().is_relative_to(root):
        raise IiifError("Cache d'originale hors du dossier autorisé ou lien symbolique : accès refusé.")
    return path


def _originale(ctx: SourceContext, loc: dict) -> tuple[Path, bool, str]:
    if loc.get("fichier_source"):
        return Path(loc["fichier_source"]), False, ""
    path = _chemin_originale(ctx, loc)
    with verrou(path.parent):
        metadata = path.with_suffix(".json")
        if metadata.is_symlink():
            raise IiifError("Métadonnées du cache liées : accès refusé.")
        if path.is_file():
            try:
                saved = json.loads(metadata.read_text(encoding="utf-8")) if metadata.is_file() else {}
            except ValueError:
                saved = {}
            return path, False, (saved if isinstance(saved, dict) else {}).get("url_image", loc.get("url_image", ""))
        urls = ([_service_url(loc["service"], f"full/{size}/0/default.jpg") for size in ("max", "full")]
                if loc.get("service") else [loc["url_image"]])
        for index, url in enumerate(urls):
            try:
                raw, _ = ctx.http.get(url, parse="bytes", use_cache=False, source="iiif")
                data = raw.encode("latin-1")
                if not extension_of(data):
                    raise IiifError("Le téléchargement n'est pas une image ni un PDF (connexion ou accès refusé ?). "
                                    + CONSIGNE_AD)
                ecrire_atomique(path, data)
                ecrire_atomique(metadata, json.dumps({"url_image": url}))
                return path, True, url
            except SourceError as exc:
                if exc.status != 400 or index == len(urls) - 1:
                    raise IiifError(f"{exc} Télécharger l'image depuis la visionneuse puis fournir le fichier.") from exc
    raise IiifError("Originale indisponible.")


def full_image(ctx: SourceContext, source: str, loc: dict) -> tuple[bytes, dict]:
    path, downloaded, url = _originale(ctx, loc)
    return path.read_bytes(), {"url_image": url, "original_telecharge": downloaded}


CONSIGNE_LIRE = ("Lire l'image avec l'outil de lecture de fichiers (chemin_absolu). Aperçu d'abord "
                 f"(largeur ≈ {PREVIEW_WIDTH}, gris) pour repérer l'acte, puis recadrer l'acte seul "
                 "(region pct:x,y,l,h, largeur 1500-2000). Transcription produite par le modèle : à "
                 "marquer comme telle et à faire vérifier.")


def _region_size(region: str, w: int, h: int) -> tuple[float, float]:
    if region == "full":
        return w, h
    if region == "square":
        return min(w, h), min(w, h)
    if region.startswith("pct:"):
        _, _, pw, ph = (float(x) for x in region[4:].split(","))
        return w * pw / 100, h * ph / 100
    _, _, rw, rh = (int(x) for x in region.split(","))
    return rw, rh
