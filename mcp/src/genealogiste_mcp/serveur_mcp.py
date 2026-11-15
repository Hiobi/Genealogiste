"""Sérialise les outils MCP qui partagent l'application, comme le faisait le SDK 1."""

import json
import logging
from typing import Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import UnexpectedToolError
from mcp.types import CallToolResult, InputRequiredResult, TextContent

from .erreurs import decrire

log = logging.getLogger("genealogiste")


class ServeurMCP(MCPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._appel_outil = anyio.Lock()
        # Observateur d'appels (journal d'exploitation, #149) : avant() -> jeton, apres(jeton, ...).
        self.observateur = None

    async def call_tool(self, name: str, arguments: dict[str, Any],
                        context: Context | None = None) -> CallToolResult | InputRequiredResult:
        # Le SDK 2 exécute les fonctions synchrones dans des workers. L'App, ses limiteurs et son
        # backend restent partagés : attendre avant d'envoyer le travail au pool de threads.
        async with self._appel_outil:
            obs = self.observateur
            jeton = obs.avant() if obs else None
            try:
                res = await super().call_tool(name, arguments, context)
            except UnexpectedToolError as exc:
                if obs:
                    obs.apres(jeton, name, arguments, exception=exc.__cause__ or exc)
                # Le SDK masque la cause (« Error executing tool … ») : la rendre exploitable par le modèle.
                cause = exc.__cause__ or exc
                desc = decrire(cause, name)
                log.error("outil %s : %s (%s)", name, desc["erreur"], desc["cause"], exc_info=cause)
                return CallToolResult(content=[TextContent(type="text", text=json.dumps(desc, ensure_ascii=False))],
                                      is_error=True)
            except BaseException as exc:
                if obs:
                    obs.apres(jeton, name, arguments, exception=exc)
                raise
            if obs:
                obs.apres(jeton, name, arguments, resultat=res)
            return res
