"""Adaptateurs de visionneuses qualifiées ; aucune exploration de JavaScript par le modèle."""

from __future__ import annotations

from dataclasses import asdict, dataclass


class VisionneuseError(ValueError):
    pass


@dataclass
class VueResolue:
    mode: str
    service_iiif: str = ""
    url_image: str = ""
    vue: int | None = None
    nb_vues: int | None = None
    ark_vue: str = ""
    ark_ressource: str = ""
    cote: str = ""
    titre_registre: str = ""
    commune: str = ""
    periode: tuple[str, str] | None = None
    licence: str = ""
    depot: str = ""

    def localisation(self) -> dict:
        out = asdict(self)
        if self.service_iiif:
            out["service"] = self.service_iiif
        return out


def resoudre(ctx, source: str, page: int = 0) -> VueResolue | None:
    from ... import archives, ark
    from . import visualizer

    a = ark.find(source)
    if a is None:
        return None
    service = next((s for s in archives.services() if s.get("ark_naan") == a.naan), None)
    spec = (service or {}).get("resolution_image") or {}
    if spec.get("type") == "visualizer_api":
        return visualizer.resoudre(ctx, a, service, page)
    return None


def naviguer(ctx, source: str, page: int = 0, pas: int = 20) -> dict | None:
    """Fenêtre de vues d'un registre servi par une visionneuse qualifiée ; None sinon (essayer IIIF)."""
    from ... import archives, ark
    from . import visualizer

    a = ark.find(source)
    if a is None:
        return None
    service = next((s for s in archives.services() if s.get("ark_naan") == a.naan), None)
    spec = (service or {}).get("resolution_image") or {}
    if spec.get("type") == "visualizer_api":
        return visualizer.naviguer(ctx, a, service, page, pas)
    return None
