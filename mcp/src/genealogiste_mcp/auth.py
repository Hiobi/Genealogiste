"""Authentification du transport HTTP MCP (#52) : jeton MCP_TOKEN exigé en « Authorization: Bearer ».
Sans jeton, le serveur ne démarre que sur une adresse locale, ou sur dérogation explicite MCP_SANS_AUTH=1
(conteneur dont le port n'est publié que sur 127.0.0.1)."""

from __future__ import annotations

import hmac
import ipaddress
import json


def is_local(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def bind_problem(host: str, token: str, sans_auth: str = "") -> str:
    """Message d'erreur si l'écoute n'est pas protégée, sinon chaîne vide."""
    if token or is_local(host) or sans_auth.strip().lower() in ("1", "true", "oui"):
        return ""
    return (f"Refus de démarrer : écoute sur {host} sans authentification. Définir MCP_TOKEN (les clients "
            "envoient « Authorization: Bearer <jeton> »), écouter sur 127.0.0.1, ou, si un proxy authentifiant "
            "ou une publication limitée à 127.0.0.1 protège déjà l'accès, poser MCP_SANS_AUTH=1.")


class BearerAuth:
    """Middleware ASGI : toute requête HTTP doit porter le jeton ; le cycle de vie (lifespan) passe."""

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            got = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(got, self.expected):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                body = json.dumps({"erreur": "jeton MCP manquant ou invalide"}).encode()
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"www-authenticate", b'Bearer realm="genealogiste"')]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
