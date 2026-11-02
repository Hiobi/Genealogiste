"""Client HTTP commun : cache SQLite, limitation de débit par hôte, backoff sur 429/503."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from .cache import Cache


class SourceError(Exception):
    """Erreur lisible renvoyée à l'agent (accès refusé, quota, format inattendu...)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class HttpClient:
    def __init__(
        self,
        cache: Cache,
        user_agent: str,
        timeout: float = 30.0,
        min_intervals: dict[str, float] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        max_retries: int = 5,
        offline: bool = False,
        transport: httpx.BaseTransport | None = None,
    ):
        self.cache = cache
        self.min_intervals = min_intervals or {}
        self.sleep = sleeper
        self.max_retries = max_retries
        self.offline = offline
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
            transport=transport,
        )

    def _throttle(self, host: str) -> None:
        interval = self.min_intervals.get(host, 0.0)
        if not interval:
            return
        with self._lock:
            wait = self._last.get(host, 0.0) + interval - time.monotonic()
            if wait > 0:
                self.sleep(wait)
            self._last[host] = time.monotonic()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        data: dict | None = None,
        json: Any = None,
        files: Any = None,
        headers: dict | None = None,
        ttl: float = 86400.0,
        source: str = "",
        parse: str = "json",
        use_cache: bool = True,
    ) -> tuple[Any, bool]:
        """Renvoie (contenu, depuis_cache). parse = json | text | bytes."""
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        cacheable = use_cache and files is None and ttl > 0
        key = Cache.key(method, url, params, data, json, parse)
        if cacheable:
            hit = self.cache.get(key)
            if hit is not None:
                return hit, True
        if self.offline:
            raise SourceError(f"Mode hors-ligne et pas de cache pour {url}")
        host = urlparse(url).netloc
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle(host)
            try:
                resp = self.client.request(
                    method, url, params=params, data=data, json=json, files=files, headers=headers
                )
            except httpx.TransportError as exc:
                last_exc = exc
                self.sleep(delay)
                delay *= 2
                continue
            if resp.status_code in (429, 502, 503, 504):
                retry_after = resp.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else delay
                except ValueError:
                    wait = delay
                self.sleep(min(wait, 60.0))
                delay *= 2
                last_exc = SourceError(f"{host} : HTTP {resp.status_code} (tentative {attempt + 1})", resp.status_code)
                continue
            if resp.status_code == 403 and "cloudflare" in resp.text[:3000].lower():
                raise SourceError(
                    f"{host} bloque cette adresse IP (protection Cloudflare). "
                    "Réessayer depuis une connexion résidentielle ou consulter le site dans le navigateur.",
                    403,
                )
            if resp.status_code in (401, 403):
                raise SourceError(f"{host} : accès refusé (HTTP {resp.status_code}) — identifiants requis ?", resp.status_code)
            if resp.status_code == 404:
                raise SourceError(f"{host} : ressource introuvable (404) : {resp.url}", 404)
            if resp.status_code >= 400:
                raise SourceError(f"{host} : HTTP {resp.status_code} : {resp.text[:300]}", resp.status_code)
            if parse == "json":
                try:
                    content = resp.json()
                except ValueError as exc:
                    raise SourceError(f"{host} : réponse non JSON : {resp.text[:200]}") from exc
            elif parse == "bytes":
                content = resp.content.decode("latin-1")
            else:
                content = resp.text
            if cacheable:
                self.cache.set(key, content, ttl, source)
            return content, False
        raise SourceError(f"{host} : échec après {self.max_retries} tentatives ({last_exc})")

    def get(self, url: str, **kw) -> tuple[Any, bool]:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> tuple[Any, bool]:
        return self.request("POST", url, **kw)
