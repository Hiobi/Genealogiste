"""Faux serveur Gramps Web (respx) fidèle au contrat de l'API utilisé par Sosa.

- lectures au format simplifié (types en chaîne XML, pas de ``_class``, ``Date.year``, handles vides en "") ;
- ``POST /api/transactions/`` : lot atomique, ``old`` comparé à la base (clés de ``old`` seulement, ``change``
  ignoré, comme ``gramps.gen.merge.diff.diff_items``) -> HTTP 400 « Object has changed » ; ``undo`` inverse
  le lot ; ``background`` -> 202 + ``/api/tasks/<id>`` ; ``force`` jamais attendu (vérifié) ;
- historique des messages de transaction, pour vérifier la traçabilité.
Données fictives uniquement.
"""

from __future__ import annotations

import copy
import json
import re

import httpx
import respx

from genealogiste_mcp.gramps.types import CLASSES, tname

URL = "http://gramps.test"
PLURAL = {v: k for k, v in CLASSES.items()}


def simplify(o):
    """Format brut -> format des lectures de l'API (GrampsJSONEncoder)."""
    if isinstance(o, list):
        return [simplify(x) for x in o]
    if not isinstance(o, dict):
        return o
    cls = o.get("_class", "")
    if cls.endswith("Type") and "value" in o:
        return tname(o)
    out = {}
    for k, v in o.items():
        if k == "_class":
            continue
        if k in ("father_handle", "mother_handle", "famc") and v is None:
            v = ""
        if k == "rect" and v is None:
            v = []
        if k == "thumb":
            continue
        out[k] = simplify(v)
    if cls == "Date":
        out["year"] = (o.get("dateval") or [0, 0, 0])[2]
    return out


def differs(old, cur) -> bool:
    if old == cur:
        return False
    if isinstance(old, list) and isinstance(cur, list):
        return len(old) != len(cur) or any(differs(a, b) for a, b in zip(old, cur, strict=False))
    if isinstance(old, dict) and isinstance(cur, dict):
        return any(k != "change" and (k not in cur or differs(v, cur[k])) for k, v in old.items())
    return True


class FakeGrampsWeb:
    def __init__(self, user: str = "sosa", password: str = "secret"):
        self.user, self.password = user, password
        self.objects: dict[str, dict[str, dict]] = {c: {} for c in CLASSES}
        self.clock = 1_000
        self.messages: list[str] = []
        self.transactions: list[list[dict]] = []
        self.forced = False
        self.tasks: dict[str, dict] = {}
        self.files: dict[str, bytes] = {}  # fichiers des médias, par handle
        self.router = respx.mock(assert_all_called=False)
        api = URL + "/api"
        r = self.router
        r.post(api + "/token/").mock(side_effect=self._token)
        r.post(api + "/token/refresh/").mock(side_effect=lambda req: httpx.Response(200, json={"access_token": "A2"}))
        r.post(api + "/transactions/").mock(side_effect=self._transaction)
        r.put(url__regex=re.escape(api) + r"/media/(?P<handle>[^/?]+)/file(\?.*)?$").mock(side_effect=self._file)
        r.get(api + "/search/").mock(side_effect=self._search)
        r.get(url__regex=re.escape(api) + r"/tasks/(?P<tid>[^/?]+)(\?.*)?$").mock(side_effect=self._task)
        r.get(url__regex=re.escape(api) + r"/(?P<plural>[a-z]+)/(\?.*)?$").mock(side_effect=self._list)
        r.get(url__regex=re.escape(api) + r"/(?P<plural>[a-z]+)/(?P<handle>[^/?]+)(\?.*)?$").mock(side_effect=self._get)

    # ------------------------------------------------------------------ outils de test
    def __enter__(self):
        self.router.__enter__()
        return self

    def __exit__(self, *exc):
        self.router.__exit__(*exc)

    def tick(self) -> int:
        self.clock += 1
        return self.clock

    def put(self, obj: dict) -> None:
        obj = copy.deepcopy(obj)
        obj["change"] = self.tick()
        self.objects[obj["_class"]][obj["handle"]] = obj

    def ui_edit(self, cls: str, gramps_id: str, fn) -> dict:
        """Modification faite dans l'interface Gramps Web."""
        o = next(x for x in self.objects[cls].values() if x.get("gramps_id") == gramps_id)
        fn(o)
        o["change"] = self.tick()
        return o

    def find(self, cls: str, gramps_id: str) -> dict:
        return next(x for x in self.objects[cls].values() if x.get("gramps_id") == gramps_id)

    # ------------------------------------------------------------------ routes
    def _auth(self, req) -> httpx.Response | None:
        if not req.headers.get("Authorization", "").startswith("Bearer A"):
            return httpx.Response(401, json={"error": {"code": 401, "message": "unauthorized"}})
        return None

    def _token(self, req):
        data = json.loads(req.content)
        if (data.get("username"), data.get("password")) != (self.user, self.password):
            return httpx.Response(403, json={"error": {"code": 403, "message": "Wrong username or password"}})
        return httpx.Response(200, json={"access_token": "A1", "refresh_token": "R1"})

    def _list(self, req, plural):
        if (r := self._auth(req)) is not None:
            return r
        objs = [simplify(o) for o in self.objects[PLURAL[plural]].values()]
        keys = req.url.params.get("keys")
        if keys:
            ks = keys.split(",")
            objs = [{k: o[k] for k in ks if k in o} for o in objs]
        return httpx.Response(200, json=objs)

    def _get(self, req, plural, handle):
        if (r := self._auth(req)) is not None:
            return r
        o = self.objects[PLURAL[plural]].get(handle)
        return httpx.Response(200, json=simplify(o)) if o else httpx.Response(404, json={})

    def _search(self, req):
        q = req.url.params.get("query", "").lower()
        hits = [{"object_type": "person", "handle": h, "object": simplify(p)} for h, p in self.objects["Person"].items()
                if q in json.dumps(p["primary_name"], ensure_ascii=False).lower()]
        return httpx.Response(200, json=hits)

    def _file(self, req, handle):
        """PUT /media/{handle}/file (Gramps Web 26.11) : If-Match, somme MD5, chemin attribué par le serveur."""
        import hashlib
        if (r := self._auth(req)) is not None:
            return r
        obj = self.objects["Media"].get(handle)
        if obj is None:
            return httpx.Response(404, json={})
        for etag in [e.strip().strip('"') for e in req.headers.get("If-Match", "").split(",") if e.strip()]:
            if etag != obj.get("checksum"):
                return httpx.Response(412, json={"error": {"code": 412, "message": "ETag mismatch."}})
        md5 = hashlib.md5(req.content).hexdigest()
        if md5 == obj.get("checksum"):
            return httpx.Response(409, json={"error": {"code": 409, "message": "same checksum"}})
        mime = req.headers.get("Content-Type", "")
        self.files[handle] = req.content
        obj.update(checksum=md5, path=f"{md5}.{mime.split('/')[-1]}", mime=mime, change=self.tick())
        return httpx.Response(200, json=[])

    def _task(self, req, tid):
        return httpx.Response(200, json=self.tasks[tid])

    def _transaction(self, req):
        if (r := self._auth(req)) is not None:
            return r
        params = req.url.params
        if params.get("force") in ("1", "true"):
            self.forced = True
        payload = json.loads(req.content)
        if params.get("undo") in ("1", "true"):
            rev = {"add": "delete", "delete": "add", "update": "update"}
            payload = [{"type": rev[i["type"]], "handle": i["handle"], "_class": i["_class"], "old": i["new"],
                        "new": i["old"]} for i in reversed(payload)]
        for it in payload:  # tout ou rien
            cur = self.objects[it["_class"]].get(it["handle"])
            old = it["old"]
            unchanged = (not old) if cur is None else (old is not None and not differs(old, cur))
            if not unchanged:
                return httpx.Response(400, json={"error": {"code": 400, "message": "Object has changed"}})
        out = []
        for it in payload:
            before = copy.deepcopy(self.objects[it["_class"]].get(it["handle"]))
            if it["type"] == "delete":
                self.objects[it["_class"]].pop(it["handle"], None)
                new = None
            else:
                new = copy.deepcopy(it["new"])
                new["change"] = self.tick()
                if new["_class"] != "Tag":
                    assert isinstance(new.get("gramps_id"), str), "gramps_id doit être une chaîne"
                self.objects[it["_class"]][it["handle"]] = new
            out.append({"type": it["type"], "handle": it["handle"], "_class": it["_class"], "old": before,
                        "new": copy.deepcopy(new)})
        self.messages.append(params.get("message", "Raw transaction"))
        self.transactions.append(out)
        if params.get("background") in ("1", "true"):
            tid = f"t{len(self.tasks) + 1}"
            self.tasks[tid] = {"state": "SUCCESS", "result_object": out}
            return httpx.Response(202, json={"task": {"href": f"/api/tasks/{tid}", "id": tid}})
        return httpx.Response(200, json=out)


def handle_of(path: str) -> str:
    return re.sub(r".*/", "", path)
