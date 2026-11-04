"""Résolution d'un ARK : service, URL canonique, disponibilité (HEAD, sans téléchargement), manifeste IIIF."""

from __future__ import annotations

from .. import ark
from ..http import SourceError
from .base import DAY, SourceContext


def registry(ctx: SourceContext) -> dict[str, dict]:
    """Registre public des NAAN (ARK Alliance), mis en cache 30 jours ; vide si inaccessible."""
    try:
        text, _ = ctx.http.get(ark.NAAN_REGISTRY, parse="text", ttl=30 * DAY, source="ark")
    except SourceError:
        return {}
    return ark.parse_naan_registry(text)


def _status(ctx: SourceContext, url: str) -> dict:
    try:
        ctx.http.request("HEAD", url, parse="text", ttl=DAY, source="ark")
        return {"accessible": True}
    except SourceError as exc:
        return {"accessible": False, "statut_http": exc.status, "erreur": str(exc)}


def resolve(ctx: SourceContext, value: str, verifier: bool = True, titre: str = "") -> dict:
    try:
        a = ark.parse(value)
    except ark.ArkError as exc:
        return {"erreur": str(exc)}
    out = a.to_dict()
    if not a.service:
        info = registry(ctx).get(a.naan)
        if info:
            out["service"] = {"code": info.get("sigle", ""), "nom": info.get("nom", ""), "hote": info.get("hote", ""),
                              "origine": "registre NAAN (ARK Alliance)"}
            if not a.hote and info.get("hote"):
                out["url"] = f"{info['hote']}/{a.id}"
        else:
            out["service"] = None
            out["avertissement"] = f"NAAN {a.naan} inconnu (table locale et registre) : résolution par n2t.net."
    tpl = (a.service or {}).get("iiif")
    if tpl:
        out["iiif_manifeste"] = tpl.format(nom=a.nom)
    if verifier:
        out["disponibilite"] = _status(ctx, out["url"])
        if not out["disponibilite"]["accessible"] and out["url"] != a.n2t():
            out["disponibilite_n2t"] = _status(ctx, a.n2t())
    ctx.journal.add(source="ark", operation="resoudre", parametres={"ark": value},
                    statut="positif" if out.get("service") else "negatif", resume=a.id, references=[out["url"]])
    out["citation_suggeree"] = ark.suggested_citation(a, titre)
    return out
