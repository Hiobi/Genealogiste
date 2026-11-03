"""Client de l'API Gramps Web : authentification, lecture complète, rafraîchissement incrémental, transactions.

- Authentification par compte local dédié (rôle Editor) : ``POST /api/token/`` puis ``/api/token/refresh/`` ;
  identifiants lus dans l'environnement, jamais écrits dans un journal, un message d'erreur ou Git.
- Lecture : ``GET /api/<objets>/`` (tous les objets, format simplifié) convertis en format brut.
- Rafraîchissement : ``GET /api/<objets>/?keys=handle,change`` puis relecture des seuls objets modifiés.
- Écriture : ``POST /api/transactions/`` (lot atomique, message, détection de conflit : le serveur compare
  ``old`` à la base et refuse « Object has changed ») ; jamais ``force``. Annulation : même endpoint avec
  ``undo=1`` sur la transaction renvoyée par le serveur. Gros lots : ``background=1`` et suivi de la tâche.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from .mapping import GrampsDb
from .types import CLASSES, to_raw

BACKGROUND_THRESHOLD = 200  # objets : au-delà, transaction en tâche de fond (Celery)
REFETCH_LIMIT = 200  # objets modifiés : au-delà, relecture complète de la classe


class GrampsError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ConflictError(GrampsError):
    """L'arbre Gramps a été modifié (interface, autre client) depuis la lecture."""


class GrampsClient:
    def __init__(self, url: str, user: str, password: str, timeout: float = 60.0,
                 transport: httpx.BaseTransport | None = None, sleeper: Callable[[float], None] = time.sleep,
                 user_agent: str = "genealogiste-mcp"):
        if not url:
            raise GrampsError("GENEALOGISTE_GRAMPS_URL non défini (ex. http://localhost:5055).")
        if not user or not password:
            raise GrampsError("GENEALOGISTE_GRAMPS_USER / GENEALOGISTE_GRAMPS_PASSWORD non définis "
                              "(compte local dédié, rôle Editor).")
        self.base = url.rstrip("/") + "/api"
        self._user, self._password = user, password
        self.client = httpx.Client(timeout=timeout, transport=transport, headers={"User-Agent": user_agent})
        self.sleep = sleeper
        self._access = ""
        self._refresh = ""
        self._exp = 0.0

    # ------------------------------------------------------------------ authentification
    def _login(self) -> None:
        r = self.client.post(f"{self.base}/token/", json={"username": self._user, "password": self._password})
        if r.status_code != 200:
            raise GrampsError(f"Gramps Web : authentification refusée (HTTP {r.status_code})", r.status_code)
        data = r.json()
        self._access, self._refresh = data.get("access_token", ""), data.get("refresh_token", "")
        self._exp = time.time() + 600

    def _renew(self) -> None:
        if self._refresh:
            r = self.client.post(f"{self.base}/token/refresh/", headers={"Authorization": f"Bearer {self._refresh}"})
            if r.status_code == 200:
                self._access = r.json().get("access_token", "")
                self._exp = time.time() + 600
                return
        self._login()

    def _headers(self) -> dict:
        if not self._access:
            self._login()
        elif time.time() > self._exp:
            self._renew()
        return {"Authorization": f"Bearer {self._access}"}

    def request(self, method: str, path: str, **kw) -> httpx.Response:
        for attempt in (1, 2):
            try:
                r = self.client.request(method, f"{self.base}{path}", headers=self._headers(), **kw)
            except httpx.HTTPError as exc:
                raise GrampsError(f"Gramps Web injoignable ({type(exc).__name__})") from exc
            if r.status_code == 401 and attempt == 1:
                self._access = ""
                continue
            return r
        return r

    @staticmethod
    def _message(r: httpx.Response) -> str:
        try:
            data = r.json()
            msg = (data.get("error") or {}).get("message") if isinstance(data, dict) else None
            return msg or r.text[:300]
        except ValueError:
            return r.text[:300]

    def _ok(self, r: httpx.Response, what: str) -> httpx.Response:
        if r.status_code >= 400:
            raise GrampsError(f"Gramps Web {what} : HTTP {r.status_code} {self._message(r)}", r.status_code)
        return r

    # ------------------------------------------------------------------ lecture
    def list(self, cls: str, **params) -> list[dict]:
        r = self._ok(self.request("GET", f"/{CLASSES[cls]}/", params=params), f"lecture {CLASSES[cls]}")
        return r.json()

    def get(self, cls: str, handle: str) -> dict | None:
        r = self.request("GET", f"/{CLASSES[cls]}/{handle}")
        if r.status_code == 404:
            return None
        return to_raw(self._ok(r, f"lecture {cls} {handle}").json(), cls)

    def load_all(self) -> GrampsDb:
        db = GrampsDb()
        for cls in CLASSES:
            for o in self.list(cls):
                db.put(to_raw(o, cls))
        return db

    def refresh(self, db: GrampsDb) -> tuple[GrampsDb, dict]:
        """Relit seulement ce qui a changé (champ ``change``) ; renvoie la base à jour et le bilan."""
        out = db.copy()
        report: dict[str, dict[str, int]] = {}
        for cls in CLASSES:
            stamps = {o["handle"]: o.get("change", 0) for o in self.list(cls, keys="handle,change")}
            local = out.all(cls)
            changed = [h for h, c in stamps.items() if h not in local or local[h].get("change") != c]
            gone = [h for h in local if h not in stamps]
            if len(changed) > REFETCH_LIMIT:
                for h in list(local):
                    out.remove(cls, h)
                for o in self.list(cls):
                    out.put(to_raw(o, cls))
            else:
                for h in changed:
                    o = self.get(cls, h)
                    if o is not None:
                        out.put(o)
            for h in gone:
                out.remove(cls, h)
            if changed or gone:
                report[cls] = {"modifies": len(changed), "supprimes": len(gone)}
        return out, report

    def search(self, texte: str, nombre: int = 20) -> list[dict]:
        r = self._ok(self.request("GET", "/search/", params={"query": texte, "pagesize": nombre, "page": 1}),
                     "recherche")
        return r.json()

    def history(self, limite: int = 20) -> list[dict]:
        r = self._ok(self.request("GET", "/transactions/history/",
                                  params={"sort": "-id", "page": 1, "pagesize": limite}), "historique")
        return r.json()

    # ------------------------------------------------------------------ écriture
    def _wait(self, r: httpx.Response, what: str, timeout: float = 600.0) -> list[dict]:
        task = (r.json() or {}).get("task") or {}
        tid = task.get("id")
        if not tid:
            raise GrampsError(f"Gramps Web {what} : tâche de fond sans identifiant")
        waited, delay = 0.0, 0.5
        while waited < timeout:
            st = self._ok(self.request("GET", f"/tasks/{tid}"), "suivi de tâche").json()
            state = st.get("state")
            if state == "SUCCESS":
                res = st.get("result_object")
                return res if isinstance(res, list) else []
            if state in ("FAILURE", "REVOKED"):
                msg = str(st.get("result") or st.get("result_object") or "échec")
                if "changed" in msg.lower():
                    raise ConflictError(f"Gramps Web {what} : l'arbre a changé depuis la lecture ({msg[:200]})")
                raise GrampsError(f"Gramps Web {what} : tâche en échec ({msg[:200]})")
            self.sleep(delay)
            waited += delay
            delay = min(delay * 2, 5.0)
        raise GrampsError(f"Gramps Web {what} : délai dépassé (tâche {tid})")

    def transaction(self, items: list[dict], message: str, undo: bool = False,
                    background: bool | None = None) -> list[dict]:
        """Transaction atomique ; renvoie les éléments réellement écrits (état serveur, pour l'annulation)."""
        if not items:
            return []
        bg = len(items) > BACKGROUND_THRESHOLD if background is None else background
        params = {"message": message[:2000]}
        if undo:
            params["undo"] = "1"
        if bg:
            params["background"] = "1"
        what = "annulation" if undo else "transaction"
        r = self.request("POST", "/transactions/", params=params, json=items)
        if r.status_code == 202:
            return self._wait(r, what)
        if r.status_code == 400 and "changed" in self._message(r).lower():
            raise ConflictError(f"Gramps Web {what} refusée : l'arbre a été modifié depuis la lecture "
                                "(interface ou autre client). Recharger, refaire le diff, redemander l'accord.", 400)
        if r.status_code == 403:
            raise GrampsError(f"Gramps Web {what} : droits insuffisants (compte « Editor » requis)", 403)
        return self._ok(r, what).json()
