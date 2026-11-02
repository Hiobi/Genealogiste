"""Backend alternatif : API Gramps Web (lecture, export GEDCOM, import GEDCOM)."""

from __future__ import annotations

import time

import httpx

from .base import SourceContext


class GrampsWeb:
    def __init__(self, ctx: SourceContext, transport: httpx.BaseTransport | None = None):
        self.ctx = ctx
        cfg = ctx.config
        if not cfg.gramps_url:
            raise RuntimeError("GENEALOGISTE_GRAMPS_URL non défini (ex. http://localhost:5055).")
        self.base = cfg.gramps_url + "/api"
        self.client = httpx.Client(timeout=60, transport=transport)
        self._token = ""
        self._exp = 0.0

    def _auth(self) -> dict:
        if not self._token or time.time() > self._exp:
            r = self.client.post(f"{self.base}/token/", json={"username": self.ctx.config.gramps_user,
                                                              "password": self.ctx.config.gramps_password})
            if r.status_code != 200:
                raise RuntimeError(f"Gramps Web : authentification refusée ({r.status_code})")
            self._token = r.json()["access_token"]
            self._exp = time.time() + 600
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, path: str, **params):
        r = self.client.get(f"{self.base}{path}", params=params, headers=self._auth())
        if r.status_code >= 400:
            raise RuntimeError(f"Gramps Web {path} : HTTP {r.status_code} {r.text[:200]}")
        return r

    def search(self, texte: str, nombre: int = 20) -> dict:
        data = self._get("/search/", query=texte, pagesize=nombre, page=1).json()
        out = []
        for hit in data:
            obj = hit.get("object", {})
            if hit.get("object_type") != "person":
                continue
            name = obj.get("primary_name", {})
            surname = (name.get("surname_list") or [{}])[0].get("surname", "")
            out.append({"source": "grampsweb", "id_externe": obj.get("gramps_id"), "handle": obj.get("handle"),
                        "prenoms": name.get("first_name", ""), "nom": surname})
        self.ctx.journal.add("grampsweb", "search", {"texte": texte}, "positif" if out else "negatif",
                             nb_resultats=len(out))
        return {"source": "grampsweb", "resultats": out}

    def person(self, handle: str) -> dict:
        data = self._get(f"/people/{handle}", extend="all", profile="all").json()
        prof = data.get("profile", {})
        return {"source": "grampsweb", "gramps_id": data.get("gramps_id"), "handle": handle,
                "nom": prof.get("name_given", "") + " " + prof.get("name_surname", ""),
                "naissance": prof.get("birth", {}), "deces": prof.get("death", {}),
                "familles": prof.get("families", []), "parents": prof.get("primary_parent_family", {}),
                "evenements": prof.get("events", [])}

    def export_gedcom(self) -> str:
        return self._get("/exporters/ged/file").text

    def import_gedcom(self, text: str) -> dict:
        r = self.client.post(f"{self.base}/importers/ged/file", content=text.encode("utf-8"),
                             headers={**self._auth(), "Content-Type": "application/octet-stream"})
        if r.status_code >= 400:
            raise RuntimeError(f"Gramps Web import : HTTP {r.status_code} {r.text[:200]}")
        return {"statut": r.status_code, "reponse": r.text[:500]}
