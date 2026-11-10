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
        data, cached = ctx.http.get(host + "/visualizer/api", params=params, ttl=7 * DAY,
                               source="visionneuse", headers={"Accept": "application/json"})
    except SourceError as exc:
        cause = str(exc)
        # Distinguer une protection (Cloudflare/captcha) d'un simple échec technique, sans contournement.
        if exc.status in (401, 403) or "cloudflare" in cause.lower() or "captcha" in cause.lower():
            cause = "accès protégé (Cloudflare/captcha) : le service refuse ce client."
        ctx.journal.add(source="visionneuse", operation="resolution_api", parametres=params,
                        statut="negatif", references=[host + "/visualizer/api"], resume=cause[:500])
        raise VisionneuseError(f"Visionneuse indisponible : {cause} {REPLI}") from exc
    ctx.journal.add(source="visionneuse", operation="resolution_api", parametres=params,
                    statut="positif", references=[host + "/visualizer/api"], cache=cached)
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


def _par_position(value, debut: int = 0) -> dict[int, dict] | None:
    """Normalise les médias renvoyés par l'API en `{position: média}`.

    Le serveur encode un tableau PHP en liste JSON quand les clés vont de 0 à n (fenêtre qui commence
    à l'indice 0), et en dictionnaire `{"286": média}` sinon. Une liste commence donc à `debut`
    (0 pour une réponse complète, `start` pour une plage). Retourne None si la forme est inconnue."""
    if isinstance(value, list):
        return {debut + i: m for i, m in enumerate(value) if isinstance(m, dict)}
    if isinstance(value, dict):
        try:
            return {int(k): m for k, m in value.items() if isinstance(m, dict)}
        except (TypeError, ValueError):
            return None
    return None


def naviguer(ctx, a: ark.Ark, service: dict, page: int, pas: int) -> dict:
    """Fenêtre de vues d'un registre AD59 : métadonnées du registre + vues (vue, ARK de vue, image).

    Utilise la sélection par plage (`start`/`end`), relevée sur le service : une fenêtre de `pas` vues
    (au plus 100) autour de `page` (1 = début). Le total de vues est obtenu par une résolution de vue
    (`counts.media`), sans inventer de borne."""
    host = service["site"].rstrip("/")
    params = {"naan": a.naan, "arkName": a.nom}
    if page < 0:
        raise VisionneuseError("page : numéro de vue à partir de 1 (0 = début du registre).")
    debut = max(0, page - 1) if page else 0
    fin = debut + max(1, min(int(pas or 20), 100)) - 1
    batch = _json(ctx, host, {**params, "start": debut, "end": fin, "group": 0})
    positions = _par_position(batch, debut)
    if positions is None:
        raise VisionneuseError(f"Réponse de pagination inattendue. {REPLI}")
    items = sorted(positions.items())
    registre: dict = {}
    vues: list[dict] = []
    for idx, media in items:
        record = _objet(media, "record")
        if not registre:
            period = _objet(record, "period").get("boundaries")
            registre = {
                "titre": _premier(record.get("title")),
                "cote": _premier(record.get("referenceCode")),
                "commune": _premier(record.get("locationKeywords")),
                "periode": tuple(period) if isinstance(period, list) else None,
            }
        link = ark.find(media.get("url", ""))
        vues.append({"vue": idx + 1, "ark_vue": link.id if link else "",
                     "url_image": _objet(media, "location").get("original", "")})
    nb_vues = None
    if items:
        uuid = _uuid(items[0][1].get("uuid"))
        data = _json(ctx, host, {**params, "uuid": uuid})
        nb_vues = _objet(data, "counts").get("media") if isinstance(data, dict) else None
    registre["nb_vues"] = nb_vues
    return {"mode": "visionneuse:visualizer_api", "depot": service["code"], "registre": registre,
            "vues": vues, "fenetre": {"de": (items[0][0] + 1) if items else debut + 1,
                                      "a": (items[-1][0] + 1) if items else fin + 1},
            "suite": ("archive_image(<ark_vue>) pour lire une vue, piece_archiver(<ark_vue>) pour l'archiver. "
                      "page=N pour une autre fenêtre.")}


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
        media = (_par_position(batch, page - 1) or {}).get(page - 1)
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
    media = (_par_position(data.get("media")) or {}).get(position)
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
    if iiif.rstrip("/").endswith(("/manifest", "/manifest.json")):
        iiif = ""  # manifeste de registre (AD25), pas un service d'image : l'original suffit

    if not image and not iiif:
        raise VisionneuseError(f"La vue n'annonce aucun téléchargement exploitable. {REPLI}")
    license = _objet(_objet(_objet(data, "app"), "licenses"), "visualizer")
    rights = license.get("text", "") if license.get("enabled") else ""
    bounds = _objet(record, "period").get("boundaries")
    return VueResolue(mode="visionneuse:visualizer_api", service_iiif=iiif.rstrip("/"), url_image=image,
                      vue=position + 1, nb_vues=count, ark_vue=link.id, ark_ressource=a.base,
                      cote=_premier(record.get("referenceCode")), titre_registre=_premier(record.get("title")),
                      commune=_premier(record.get("locationKeywords")),
                      periode=tuple(bounds) if isinstance(bounds, list) and len(bounds) == 2 and all(isinstance(x, str) for x in bounds) else None,
                      licence=rights[:4000] if isinstance(rights, str) else "", depot=service["code"])
