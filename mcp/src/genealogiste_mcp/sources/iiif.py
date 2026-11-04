"""Images d'actes par IIIF : aperçu basse définition, puis recadrage de l'acte, avec un coût en tokens maîtrisé.

Entrées acceptées : ARK Gallica (modèle connu), manifeste IIIF (Presentation v2 ou v3), ``info.json`` ou URL
d'image IIIF (``{service}/{region}/{taille}/{rotation}/{qualite}.{format}``). Pour une visionneuse d'archives
dont l'IIIF n'est pas connu (AD), l'utilisateur copie le lien IIIF depuis la visionneuse (bouton « Copier le
lien IIIF ») : l'outil n'explore jamais l'API interne d'un site ni ne contourne une protection.

Une image n'est téléchargée qu'une fois (``medias/iiif/``) ; une requête = une image, jamais de lot (CGU).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .. import ark
from ..http import SourceError
from .base import DAY, SourceContext

MAX_WIDTH = 2000  # au-delà, le modèle réduit l'image : des pixels payés pour rien
PREVIEW_WIDTH = 800
TOKENS_PER_PIXEL = 1 / 750  # ordre de grandeur du coût d'une image pour le modèle
_REGION = re.compile(r"^(full|square|\d+,\d+,\d+,\d+|pct:[\d.]+,[\d.]+,[\d.]+,[\d.]+)$")
_IMAGE_URL = re.compile(r"^(?P<base>https?://.+?)/(?P<region>full|square|pct:[^/]+|\d+,\d+,\d+,\d+)/"
                        r"(?P<size>[^/]+)/(?P<rot>!?\d+)/(?P<q>\w+)\.(?P<fmt>\w+)$")
CONSIGNE_AD = ("IIIF de ce service inconnu : ouvrir l'image dans la visionneuse des archives, cliquer sur « Copier "
               "le lien IIIF » (barre d'outils) et rappeler l'outil avec ce lien (manifeste, info.json ou image). "
               "Sinon, enregistrer une capture d'écran et l'ajouter avec media_enregistrer.")


class IiifError(ValueError):
    pass


def _id(o) -> str:
    if isinstance(o, list):
        o = o[0] if o else {}
    return (o or {}).get("@id") or (o or {}).get("id") or ""


def canvases(manifest: dict) -> list[dict]:
    """[{label, service}] des vues d'un manifeste IIIF v2 ou v3."""
    out = []
    if "sequences" in manifest:  # Presentation 2
        for c in (manifest["sequences"] or [{}])[0].get("canvases", []):
            res = ((c.get("images") or [{}])[0]).get("resource", {})
            out.append({"label": _label(c.get("label")), "service": _id(res.get("service")).rstrip("/")})
    else:  # Presentation 3
        for c in manifest.get("items", []):
            body = (((c.get("items") or [{}])[0].get("items") or [{}])[0]).get("body", {})
            if isinstance(body, list):
                body = body[0] if body else {}
            out.append({"label": _label(c.get("label")), "service": _id(body.get("service")).rstrip("/")})
    return out


def _label(v) -> str:
    if isinstance(v, dict):  # v3 : {"fr": ["Vue 12"]}
        vals = next(iter(v.values()), [])
        return vals[0] if vals else ""
    return v or ""


def image_url(service: str, region: str = "full", largeur: int = PREVIEW_WIDTH, gris: bool = True) -> str:
    if not _REGION.match(region):
        raise IiifError("region : full | x,y,l,h (pixels) | pct:x,y,l,h (pourcentages)")
    return f"{service}/{region}/{largeur},/0/{'gray' if gris else 'default'}.jpg"


def _json(ctx: SourceContext, url: str) -> dict:
    data, _ = ctx.http.get(url, ttl=30 * DAY, source="iiif", headers={"Accept": "application/json"})
    if not isinstance(data, dict):
        raise IiifError(f"Réponse IIIF inattendue : {url}")
    return data


def locate(ctx: SourceContext, source: str, page: int = 0) -> dict:
    """Service d'image IIIF d'une vue : {service, vue, nb_vues?, manifeste?}."""
    s = (source or "").strip()
    m = _IMAGE_URL.match(s)
    if m:
        return {"service": m.group("base"), "vue": page or None}
    if s.endswith("/info.json"):
        return {"service": s[: -len("/info.json")], "vue": page or None}
    a = ark.find(s)
    if a and a.naan == "12148" and not s.endswith("manifest.json"):  # Gallica : vue = fNN ou page
        vue = page or a.vue or 1
        return {"service": f"https://gallica.bnf.fr/iiif/{a.base}/f{vue}", "vue": vue,
                "manifeste": f"https://gallica.bnf.fr/iiif/{a.base}/manifest.json"}
    if a and not re.search(r"manifest|iiif", s, re.I):
        raise IiifError(CONSIGNE_AD)
    if not s.startswith(("http://", "https://")):
        raise IiifError("source : ARK Gallica, manifeste IIIF, info.json ou URL d'image IIIF.")
    data = _json(ctx, s)
    if data.get("protocol") == "http://iiif.io/api/image" or "profile" in data and "width" in data:
        return {"service": _id(data).rstrip("/") or s, "vue": page or None}
    views = canvases(data)
    if not views:
        raise IiifError("Manifeste IIIF sans vue exploitable.")
    i = (page or 1) - 1
    if not 0 <= i < len(views):
        raise IiifError(f"Vue {page} hors du manifeste ({len(views)} vues).")
    return {"service": views[i]["service"], "vue": i + 1, "nb_vues": len(views), "libelle": views[i]["label"],
            "manifeste": s}


def fetch(ctx: SourceContext, media_dir: Path, source: str, page: int = 0, region: str = "full",
          largeur: int = PREVIEW_WIDTH, gris: bool = True) -> dict:
    """Télécharge (une fois) une vue ou une zone, à la largeur demandée ; renvoie le chemin à lire."""
    try:
        largeur = max(100, min(int(largeur or PREVIEW_WIDTH), MAX_WIDTH))
        loc = locate(ctx, source, page)
        info = {}
        try:
            info = _json(ctx, loc["service"] + "/info.json")
        except (SourceError, IiifError):
            pass  # dimensions inconnues : pas d'estimation de coût
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
    except (IiifError, SourceError) as exc:
        return {"erreur": str(exc), "source": source}
    out = {"fichier": f"medias/iiif/{dest.name}", "chemin_absolu": str(dest), "url_image": url,
           "depuis_cache": cached, **{k: v for k, v in loc.items() if k != "service"}, "service_iiif": loc["service"]}
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
    out["consigne"] = ("Lire l'image avec l'outil de lecture de fichiers (chemin_absolu). Aperçu d'abord "
                       f"(largeur ≈ {PREVIEW_WIDTH}, gris) pour repérer l'acte, puis recadrer l'acte seul "
                       "(region pct:x,y,l,h, largeur 1500-2000). Transcription produite par le modèle : à "
                       "marquer comme telle et à faire vérifier.")
    return out


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
