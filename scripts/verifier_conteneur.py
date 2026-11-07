"""Test du conteneur sur volumes jetables, sans donnée ni secret réel."""

import asyncio
import json
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

TOKEN = 'jeton-fictif-controle-conteneur'


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


async def verifier(url):
    async with httpx.AsyncClient(headers={'Authorization': f'Bearer {TOKEN}'}, timeout=30) as client:
        async with streamable_http_client(url, http_client=client) as (lecture, ecriture, _):
            async with ClientSession(lecture, ecriture) as session:
                await session.initialize()
                result = await session.call_tool('arbre_info', {})
                assert not result.isError, 'arbre_info doit réussir sur un arbre vide synthétique'


def main():
    image = sys.argv[1]
    refus = subprocess.run(['docker', 'run', '--rm', image], capture_output=True, text=True, timeout=30)
    assert refus.returncode != 0 and 'Refus de démarrer' in refus.stderr + refus.stdout
    cid = docker('run', '--rm', '-d', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                 '-p', '127.0.0.1::8765', '-e', f'MCP_TOKEN={TOKEN}', image)
    try:
        port = docker('port', cid, '8765/tcp').rsplit(':', 1)[1]
        url = f'http://127.0.0.1:{port}/mcp'
        for _ in range(30):
            try:
                with urlopen(url, timeout=1):
                    raise AssertionError('Une requête anonyme doit être refusée')
            except HTTPError as exc:
                assert exc.code == 401
                break
            except (URLError, TimeoutError, ConnectionResetError):
                time.sleep(1)
        else:
            raise AssertionError('Le conteneur ne répond pas')
        assert docker('exec', cid, 'id', '-u') == '10001'
        asyncio.run(verifier(url))
        modes = json.loads(docker('exec', cid, 'python', '-c',
                                "import os,json,stat; print(json.dumps([stat.S_IMODE(os.stat(p).st_mode) "
                                "for p in ['/data', '/data/arbre.ged']]))"))
        assert modes == [0o700, 0o600], modes
        print('Conteneur : refus sans jeton, HTTP 401 anonyme, appel MCP autorisé, UID 10001, données privées : OK')
    finally:
        subprocess.run(['docker', 'rm', '-f', '-v', cid], stdout=subprocess.DEVNULL, check=False)


if __name__ == '__main__':
    main()
