"""Recette native Codex 0.166.0 : fournisseur déterministe local, aucune clé API.

Lance le vrai app-server et le vrai MCP sur une famille fictive. Simule les réponses du client aux
approbations natives ; ne démontre pas qu'une personne a cliqué dans l'interface desktop.
Usage : UV_CACHE_DIR=/tmp/sosa-uv-cache python3 scripts/verifier_codex.py
"""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from configurer_codex import ROOT, profil


def diff_outil(value):
    """Retrouve le diff dans l'enveloppe Responses/MCP, pour le présenter dans le chat natif."""
    if isinstance(value, str):
        try:
            return diff_outil(json.loads(value))
        except ValueError:
            return None
    if isinstance(value, dict):
        if isinstance(value.get("diff"), str):
            return value["diff"]
        value = value.values()
    elif not isinstance(value, list):
        return None
    for item in value:
        if diff := diff_outil(item):
            return diff
    return None


class Fournisseur(ThreadingHTTPServer):
    """Une sortie outil imposée par le test, puis un message final ; aucun modèle distant."""

    appel: dict
    requetes: int


class Reponse(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        fixture = self.server
        fixture.requetes += 1
        if fixture.requetes > 3:
            self.send_error(500, "Boucle inattendue")
            return
        item = fixture.appel
        output = next((i for i in body["input"] if i.get("type") == "function_call_output"
                       and i.get("call_id") == item["call_id"]), None)
        if output:
            diff = diff_outil(output.get("output"))
            text = "Diff à relire avant application :\n" + diff if diff else "Recette terminée."
            item = {"type": "message", "id": "msg_final", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": text}]}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        events = [
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": "resp_fixture", "status": "completed",
             "output": [item], "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}},
        ]
        for event in events:
            self.wfile.write(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode())
            self.wfile.flush()


class Client:
    def __init__(self, env, cwd, log):
        self.log = log
        cmd = ["codex", "app-server", "--stdio", "--strict-config"]
        self.process = subprocess.Popen(cmd, env=env,
                                        cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
        self.buffer = b""
        self.numero = 0
        self.approbations = []

    def send(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        self.process.stdin.flush()

    def receive(self, timeout=60):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise TimeoutError("Codex n'a pas répondu dans le délai")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("Arrêt inattendu de Codex : " + Path(self.log.name).read_text()[-3000:])
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(line)

    def rpc(self, method, params):
        self.numero += 1
        identifiant = self.numero
        self.send({"id": identifiant, "method": method, "params": params})
        while True:
            message = self.receive()
            if message.get("id") == identifiant:
                if "error" in message:
                    raise RuntimeError(str(message["error"]) + "\n" + Path(self.log.name).read_text()[-6000:])
                return message["result"]

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def outil(self, provider, thread, name, arguments, action="accept", avant=None):
        """Le tool call vient du tour natif ; jamais de mcpServer/tool/call (RPC sans approbation)."""
        call = f"recette_{self.numero}"
        provider.appel = {"type": "function_call", "namespace": "mcp__genealogiste", "name": name,
                          "id": call, "call_id": call, "arguments": json.dumps(arguments), "status": "completed"}
        provider.requetes = 0
        self.rpc("turn/start", {"threadId": thread, "input": [{"type": "text", "text": f"Recette {name}"}]})
        prompts = 0
        result = None
        presentation = []
        while True:
            message = self.receive()
            if message.get("method") == "mcpServer/elicitation/request":
                params = message["params"]
                assert params["_meta"]["codex_approval_kind"] == "mcp_tool_call", params
                assert params["_meta"]["tool_params"] == arguments, params
                assert f'"{name}"' in params["message"], params
                prompts += 1
                if avant:
                    avant()
                self.approbations.append({"outil": name, "decision": action})
                self.send({"id": message["id"], "result": {"action": action, "content": {} if action == "accept" else None}})
            elif "id" in message and "method" in message:
                raise AssertionError(f"Demande native inattendue : {message['method']}")
            elif message.get("method") == "item/completed":
                item = message["params"]["item"]
                if item["type"] == "agentMessage":
                    presentation.append(item["text"])
                if item["type"] == "mcpToolCall":
                    result = item
            elif message.get("method") == "turn/completed":
                assert message["params"]["turn"]["status"] == "completed", message
                assert prompts == 1, (name, prompts)
                assert result is not None, name
                if action != "accept":
                    assert result["error"], result
                    return result
                assert not result["error"], result
                content = result["result"]["content"]
                payload = json.loads(next(c["text"] for c in content if c["type"] == "text"))
                if payload.get("diff"):
                    assert payload["diff"] in "\n".join(presentation), "Diff absent des messages assistant"
                return payload


def verifier(base: Path):
    home = base / "codex"
    home.mkdir()
    data = base / "donnees"
    env = {k: v for k, v in os.environ.items() if not k.startswith("GENEALOGISTE_")
           and k not in {"OPENAI_API_KEY", "OPENAI_BASE_URL", "MCP_TOKEN"}}
    env.update(CODEX_HOME=str(home), XDG_CACHE_HOME=str(base / "cache"), UV_CACHE_DIR=os.environ.get(
        "UV_CACHE_DIR", str(base / "uv-cache")))
    version = subprocess.check_output(["codex", "--version"], env=env, text=True).strip()
    if version != "codex-cli 0.166.0":
        raise RuntimeError(f"Recette figée sur codex-cli 0.166.0 ; version reçue : {version}")
    for command in (["marketplace", "add", str(ROOT)], ["add", "genealogiste@genealogiste"]):
        subprocess.run(["codex", "plugin", *command, "--json"], env=env, check=True, capture_output=True)
    provider = Fournisseur(("127.0.0.1", 0), Reponse)
    worker = threading.Thread(target=provider.serve_forever, daemon=True)
    worker.start()
    common = f'''model = "fixture-codex"
model_provider = "fixture"
[model_providers.fixture]
name = "Recette locale sans modèle"
base_url = "http://127.0.0.1:{provider.server_port}/v1"
wire_api = "responses"
requires_openai_auth = false
'''
    # Le paquet seul expose les skills, jamais le serveur Claude ou ses hooks.
    (home / "config.toml").write_text(common + '\n[plugins."genealogiste@genealogiste"]\nenabled = true\n')
    with (base / "codex-stderr.log").open("wb") as log:
        client = Client(env, base, log)
        try:
            client.rpc("initialize", {"clientInfo": {"name": "genealogiste_recette", "version": "1"},
                                      "capabilities": {"experimentalApi": True}})
            client.send({"method": "initialized"})
            skills = client.rpc("skills/list", {"cwds": [str(base)], "forceReload": True})
            names = {s["name"].removeprefix("genealogiste:") for row in skills["data"] for s in row["skills"] if s["enabled"]}
            attendus = {p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")}
            assert attendus <= names, (attendus, names)
            inventory = client.rpc("mcpServerStatus/list", {})
            assert not inventory["data"], inventory
        finally:
            client.close()
    # La même politique que le profil public, avec chemins de cache/notes exclusivement jetables.
    (home / "config.toml").write_text(common)
    (home / "genealogiste.config.toml").write_text(profil(data) +
        f'GENEALOGISTE_NOTES_DIR = {json.dumps(str(base / "notes"))}\nGENEALOGISTE_OFFLINE = "1"\n'
        f'GENEALOGISTE_CACHE = {json.dumps(str(base / "cache.sqlite"))}\n'
        f'UV_CACHE_DIR = {json.dumps(env["UV_CACHE_DIR"])}\n')
    # app-server n'accepte pas -p ; valider le profil via la CLI, puis matérialiser sa même config.
    subprocess.run(["codex", "-p", "genealogiste", "mcp", "get", "genealogiste", "--json"],
                   env=env, check=True, capture_output=True)
    config_profile = (home / "genealogiste.config.toml").read_text()
    (home / "config.toml").write_text(config_profile.replace("[plugins.", common + "\n[plugins.", 1))
    with (base / "codex-stderr.log").open("ab") as log:
        client = Client(env, base, log)
        try:
            client.rpc("initialize", {"clientInfo": {"name": "genealogiste_recette", "version": "1"},
                                      "capabilities": {"experimentalApi": True}})
            client.send({"method": "initialized"})
            thread = client.rpc("thread/start", {"cwd": str(base), "ephemeral": True})["thread"]["id"]
            def outil(name, args=None, **kwargs):
                return client.outil(provider, thread, name, args or {}, **kwargs)
            assert outil("arbre_info")["personnes"] == 0
            arbre = data / "arbre.ged"
            original = arbre.read_bytes()
            def intact():
                assert arbre.read_bytes() == original
            def importer():
                p = outil("arbre_importer_gedcom", {"chemin": str(ROOT / "mcp/tests/fixtures/famille.ged"), "mode": "remplacer"})
                assert p["diff"] and p["jeton"], p
                intact()
                return p
            p = importer()
            outil("arbre_appliquer", {"jeton": p["jeton"]}, action="decline", avant=intact)
            intact()
            assert (data / ".propositions" / (p["jeton"] + ".json")).is_file()
            outil("arbre_annuler_proposition", {"jeton": p["jeton"]})
            ancien_jeton = p["jeton"]
            p = importer()
            assert p["jeton"] != ancien_jeton
            applied = outil("arbre_appliquer", {"jeton": p["jeton"]}, avant=intact)
            assert "erreur" not in applied, applied
            assert arbre.read_bytes() != original
            original = arbre.read_bytes()
            assert "déjà utilisé" in outil("arbre_appliquer", {"jeton": p["jeton"]})["erreur"]
            intact()
            assert outil("arbre_info")["personnes"] == 8
            # Token expiré puis conflit : injection d'état synthétique, pas de permission simulée côté MCP.
            args = {"operations": [{"op": "modifier_personne", "id": "I1", "sexe": "U"}],
                    "titre": "Recette", "justification": "Test fictif"}
            p = outil("arbre_proposer", args)
            token = data / ".propositions" / (p["jeton"] + ".json")
            record = json.loads(token.read_text())
            record["cree"] = 0
            token.write_text(json.dumps(record))
            assert "expirée" in outil("arbre_appliquer", {"jeton": p["jeton"]})["erreur"]
            intact()
            p = outil("arbre_proposer", args)
            arbre.write_bytes(original + b"\n")
            modified = arbre.read_bytes()
            err = outil("arbre_appliquer", {"jeton": p["jeton"]})
            assert "arbre a changé" in err.get("erreur", ""), err
            assert arbre.read_bytes() == modified
            arbre.write_bytes(original)
            living = outil("matchid_recherche", {"personne": "I9", "nom": "MARTIN", "prenom": "Lucas"})
            assert "vivant" in json.dumps(living).lower(), living
            export = outil("arbre_exporter")
            public = Path(export["fichier"]).read_text()
            assert "Lucas" not in public and "Vivant" in public
            for name, arguments, destination in [
                ("notes_ajouter", {"id": "I1", "texte": "Note fictive de recette"}, base / "notes"),
                ("media_enregistrer", {"chemin": str(base / "acte.pdf")}, data / "medias"),
            ]:
                (base / "acte.pdf").write_bytes(b"%PDF-1.4\nrecette fictive\n")
                before = {str(p): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
                outil(name, arguments, action="decline")
                assert before == {str(p): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
                res = outil(name, arguments)
                assert "erreur" not in res, res
                assert {str(p): p.read_bytes() for p in destination.rglob("*") if p.is_file()} != before
            intact()
            print(json.dumps({"codex": version, "skills": sorted(attendus),
                              "approbations_natives": client.approbations, "resultat": "OK"}, ensure_ascii=False, indent=2))
        finally:
            client.close()
            provider.shutdown()
            provider.server_close()


if __name__ == "__main__":
    if not shutil.which("codex") or not shutil.which("uv"):
        raise SystemExit("codex 0.166.0 et uv sont nécessaires")
    with tempfile.TemporaryDirectory(prefix="genealogiste-codex-") as folder:
        verifier(Path(folder))
