"""API /visualizer/api qualifiée pour AD59 (docs/visionneuse-ad59.md)."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit
from uuid import UUID

from ... import ark
from ...http import SourceError
from ..base import DAY
from . import VisionneuseError, VueResolue

REPLI = "Télécharger la vue dans la visionneuse, puis fournir le fichier local ; aucun contournement d'accès."


def _json(ctx, host, params):
    try:
        data, _ = ctx.http.get(host + "/visualizer/api", params=params, ttl=7 * DAY,
                               source="visionneuse", headers={"Accept": "application/json"})
    except SourceError as exc:
        raise VisionneuseError(f"Visionneuse indisponible : {exc}. {REPLI}") from exc
    if not isinstance(data, (dict, list)):
        raise VisionneuseError(f"Réponse de visionneuse inattendue. {REPLI}")
    return data


def _url(value, host):
    """Les URL techniques annoncées doivent rester sur l'origine officielle qualifiée."""
    if not isinstance(value, str) or not value:
        return ""
    value = urljoin(host, value)
    try:
        u, h = urlsplit(value), urlsplit(host)
        ports = u.port, h.port
    except ValueError as exc:
        raise VisionneuseError("URL technique invalide.") from exc
    if (u.scheme, u.hostname, ports[0]) != (h.scheme, h.hostname, ports[1]) or u.username or u.password:
        raise VisionneuseError("URL d'image hors du service d'archives : résolution refusée.")
    return value


def _uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise VisionneuseError("Identifiant de vue non reconnu ; fournir un ARK de vue ou page=N.") from exc


def _premier(value):
    if isinstance(value, list):
        value = value[0] if value else ""
    return value[:512] if isinstance(value, str) else ""


def _objet(parent, key):
    value = parent.get(key) if isinstance(parent, dict) else None
    return value if isinstance(value, dict) else {}


def resoudre(ctx, a: ark.Ark, service: dict, page: int) -> VueResolue:
    host = service["site"].rstrip("/")  # jamais l'hôte fourni dans l'URL utilisateur
    params = {"naan": a.naan, "arkName": a.nom}
    if page < 0:
        raise VisionneuseError("page : numéro de vue à partir de 1 (0 = vue du lien).")
    if page:
        batch = _json(ctx, host, {**params, "start": page - 1, "end": page - 1, "group": 0})
        media = batch[0] if isinstance(batch, list) and len(batch) == 1 else (
            batch.get(str(page - 1)) if isinstance(batch, dict) else None)
        if not isinstance(media, dict):
            raise VisionneuseError(f"Vue {page} absente ou hors du registre. {REPLI}")
        uuid = _uuid(media.get("uuid"))
    elif a.qualificatif:
        uuid = _uuid(a.qualificatif)
    else:
        raise VisionneuseError("ARK de registre sans vue : préciser page=N (numérotation à partir de 1).")
    data = _json(ctx, host, {**params, "uuid": uuid})
    if not isinstance(data, dict):
        raise VisionneuseError(f"Métadonnées de vue inattendues. {REPLI}")
    count, position = _objet(data, "counts").get("media"), _objet(data, "positions").get("media")
    if type(count) is not int or type(position) is not int or not 0 <= position < count:
        raise VisionneuseError("Nombre de vues ou position incohérent : résolution refusée.")
    if page and page != position + 1:
        raise VisionneuseError("La vue retournée ne correspond pas au numéro demandé.")
    media = _objet(data, "media").get(str(position))
    if not isinstance(media, dict) or media.get("uuid") != uuid or media.get("type") != "image":
        raise VisionneuseError("La réponse ne contient pas l'image de la vue demandée.")
    record = _objet(media, "record")
    identity = _objet(record, "arkId")
    if str(identity.get("naan")) != a.naan or identity.get("arkName") != a.nom:
        raise VisionneuseError("Le registre retourné ne correspond pas à l'ARK demandé.")
    link = ark.find(media.get("url", ""))
    if not link or link.base != a.base or link.qualificatif != uuid:
        raise VisionneuseError("ARK de vue incohérent : résolution refusée.")
    location = _objet(media, "location")
    image, iiif = _url(location.get("original"), host), _url(location.get("iiif"), host)
    if not image and not iiif:
        raise VisionneuseError(f"La vue n'annonce aucun téléchargement exploitable. {REPLI}")
    license = _objet(_objet(_objet(data, "app"), "licenses"), "visualizer")
    rights = license.get("text", "") if license.get("enabled") else ""
    bounds = _objet(record, "period").get("boundaries")
    return VueResolue(mode="visionneuse:visualizer_api", service_iiif=iiif.rstrip("/"), url_image=image,
                      vue=position + 1, nb_vues=count, ark_vue=link.id, ark_ressource=a.base,
                      cote=_premier(record.get("referenceCode")), titre_registre=_premier(record.get("title")),
                      periode=tuple(bounds) if isinstance(bounds, list) and len(bounds) == 2 and all(isinstance(x, str) for x in bounds) else None,
                      licence=rights[:4000] if isinstance(rights, str) else "", depot=service["code"])
