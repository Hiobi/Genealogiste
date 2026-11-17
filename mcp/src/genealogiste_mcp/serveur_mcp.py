"""Sérialise les outils MCP qui partagent l'application, comme le faisait le SDK 1 — sauf les outils de lecture
déclarés dans sans_verrou, qui ne doivent pas attendre une écriture longue (#151) — et entretient la connexion
par un battement de progression pendant les appels longs."""

import functools
import inspect
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
        # Outils de lecture pure (aucun état partagé modifié) : exécutés sans attendre le verrou d'appel.
        self.sans_verrou: set[str] = set()
        # Battement : notifications de progression (si le client en demande) pendant un appel long, pour qu'il
        # ne l'abandonne pas faute de réponse (cas réel : 1 800 s d'inactivité).
        self.intervalle_battement = 15.0
        # Observateur d'appels (journal d'exploitation, #149) : avant() -> jeton, apres(jeton, ...).
        self.observateur = None
        # Garde-fou d'appel (#159) : garde(nom, fn, args, kwargs) -> réponse de refus ou None, appelé avant la
        # fonction de l'outil, y compris quand elle est appelée directement (hors protocole MCP).
        self.garde = None

    def tool(self, name: str | None = None, *args: Any, **kwargs: Any):
        """Comme MCPServer.tool, en enveloppant la fonction par le garde-fou ; la signature exposée (schéma
        d'entrée, description) est celle de la fonction d'origine (functools.wraps)."""
        if callable(name):
            return super().tool(name)  # usage incorrect : message du SDK
        enregistrer = super().tool(name, *args, **kwargs)

        def decorer(fn):
            nom = name or fn.__name__
            if inspect.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def garde_async(*a, **kw):
                    if self.garde is not None and (refus := self.garde(nom, fn, a, kw)) is not None:
                        return refus
                    return await fn(*a, **kw)
                enveloppe = garde_async
            else:
                @functools.wraps(fn)
                def garde_sync(*a, **kw):
                    if self.garde is not None and (refus := self.garde(nom, fn, a, kw)) is not None:
                        return refus
                    return fn(*a, **kw)
                enveloppe = garde_sync
            enregistrer(enveloppe)
            return enveloppe
        return decorer

    async def call_tool(self, name: str, arguments: dict[str, Any],
                        context: Context | None = None) -> CallToolResult | InputRequiredResult:
        # Le SDK 2 exécute les fonctions synchrones dans des workers. L'App, ses limiteurs et son
        # backend restent partagés : attendre avant d'envoyer le travail au pool de threads.
        if name in self.sans_verrou:
            return await self._avec_battement(name, arguments, context)
        async with self._appel_outil:
            return await self._avec_battement(name, arguments, context)

    async def _avec_battement(self, name: str, arguments: dict[str, Any],
                              context: Context | None) -> CallToolResult | InputRequiredResult:
        if context is None or not self.intervalle_battement:
            return await self._appeler(name, arguments, context)
        resultat: list = []

        async def battre() -> None:
            debut = anyio.current_time()
            while True:
                await anyio.sleep(self.intervalle_battement)
                ecoule = anyio.current_time() - debut
                try:
                    await context.report_progress(round(ecoule), None, f"{name} en cours ({round(ecoule)} s)")
                except Exception:  # noqa: BLE001 — un battement perdu ne doit jamais casser l'appel
                    log.debug("battement de progression non envoyé", exc_info=True)

        async with anyio.create_task_group() as tg:
            tg.start_soon(battre)
            try:
                resultat.append(await self._appeler(name, arguments, context))
            finally:
                tg.cancel_scope.cancel()
        return resultat[0]

    async def _appeler(self, name: str, arguments: dict[str, Any],
                       context: Context | None) -> CallToolResult | InputRequiredResult:
        obs = self.observateur
        jeton = obs.avant(name) if obs else None
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
