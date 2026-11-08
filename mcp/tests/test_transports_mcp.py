"""Contrat MCP réel après migration du SDK : démarrage HTTP protégé et protocole stdio isolé."""

import asyncio
import json
import os
import sys
from pathlib import Path

import anyio
import httpx
import pytest
import uvicorn
from mcp import ClientSession, StdioServerParameters, stdio_client

from genealogiste_mcp import outils, server
from genealogiste_mcp.auth import BearerAuth


@pytest.mark.parametrize('transport', ['streamable-http', 'sse'])
@pytest.mark.parametrize('host', ['127.0.0.1', '0.0.0.0'])
def test_demarrage_http_et_protections(monkeypatch, transport, host):
    launches = []
    monkeypatch.setenv('MCP_TOKEN', 'jeton-fictif-transport')
    monkeypatch.setattr(sys, 'argv', ['genealogiste-mcp', '--transport', transport,
                                    '--host', host, '--port', '9876'])
    monkeypatch.setattr(server, 'load_config', lambda: None)
    monkeypatch.setattr(uvicorn, 'run', lambda app, **kw: launches.append((app, kw)))
    original_umask = os.umask(0o077)
    try:
        server.main()
    finally:
        os.umask(original_umask)
    asgi, settings = launches[0]
    assert settings == {'host': host, 'port': 9876, 'log_level': 'warning'}
    assert isinstance(asgi, BearerAuth)
    path = '/mcp' if transport == 'streamable-http' else '/sse'

    async def requests():
        async with asgi.app.router.lifespan_context(asgi.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=asgi, raise_app_exceptions=False),
                                         base_url='http://127.0.0.1:9876') as client:
                assert (await client.get(path)).status_code == 401
                assert (await client.get(path, headers={'Authorization': 'Bearer faux'})).status_code == 401
                auth = {'Authorization': 'Bearer jeton-fictif-transport'}
                # Conserver la protection DNS, y compris lorsque uvicorn écoute sur toutes les interfaces.
                rejected = await client.get(path, headers={**auth, 'Host': 'host-externe.example:9876'})
                assert rejected.status_code == 421
                if transport == 'streamable-http':
                    response = await client.post(path, headers={**auth, 'Accept': 'application/json, text/event-stream'},
                                                 json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                                       'params': {'protocolVersion': '2025-11-25', 'capabilities': {},
                                                                  'clientInfo': {'name': 'test', 'version': '1'}}})
                    assert response.status_code == 200, response.text
                    assert 'genealogiste' in response.text
    asyncio.run(requests())


def test_stdio_protocole_catalogue_et_lecture(tmp_path):
    parameters = StdioServerParameters(
        command=sys.executable, args=['-m', 'genealogiste_mcp.server'], cwd=str(tmp_path),
        env={'GENEALOGISTE_DATA_DIR': str(tmp_path / 'donnees'),
             'GENEALOGISTE_CACHE': str(tmp_path / 'cache.sqlite'),
             'GENEALOGISTE_BACKEND': 'fichier', 'GENEALOGISTE_OFFLINE': '1',
             'PYTHONPATH': str(Path(server.__file__).resolve().parents[1])})

    async def exchange():
        with anyio.fail_after(20):
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    assert initialized.server_info.name == 'genealogiste'
                    assert initialized.instructions == server.INSTRUCTIONS
                    tools = await session.list_tools()
                    assert {tool.name for tool in tools.tools} == set(outils.OUTILS)
                    result = await session.call_tool('arbre_info', {})
                    assert not result.is_error
                    payload = result.structured_content or json.loads(result.content[0].text)
                    assert payload['personnes'] == 0
                    assert payload['backend'] == 'fichier'
    asyncio.run(exchange())
    assert (tmp_path / 'donnees/arbre.ged').exists()
