"""Sérialise les outils MCP qui partagent l'application, comme le faisait le SDK 1."""

from typing import Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, InputRequiredResult


class ServeurMCP(MCPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._appel_outil = anyio.Lock()

    async def call_tool(self, name: str, arguments: dict[str, Any],
                        context: Context | None = None) -> CallToolResult | InputRequiredResult:
        # Le SDK 2 exécute les fonctions synchrones dans des workers. L'App, ses limiteurs et son
        # backend restent partagés : attendre avant d'envoyer le travail au pool de threads.
        async with self._appel_outil:
            return await super().call_tool(name, arguments, context)
