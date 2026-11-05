"""Client HTTP commun : cache SQLite, limitation de débit par hôte, backoff sur 429/503,
politique réseau revalidée à chaque redirection (#42), reprises réservées aux requêtes idempotentes (#50)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .cache import Cache
from .reseau import DestinationRefusee, NetworkPolicy

MAX_REDIRECTS = 5
IDEMPOTENT = frozenset({"GET", "HEAD", "OPTIONS"})


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
        policy: NetworkPolicy | None = None,
    ):
        self.cache = cache
        self.min_intervals = min_intervals or {}
        self.sleep = sleeper
        self.max_retries = max_retries
        self.offline = offline
        self.policy = policy or NetworkPolicy()
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=False,  # suivies à la main : chaque destination est revalidée
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

    def _send(self, method: str, url: str, *, params, data, json, files, headers) -> httpx.Response:
        """Requête avec redirections suivies manuellement ; chaque URL passe la politique réseau."""
        for _ in range(MAX_REDIRECTS + 1):
            try:
                self.policy.check(url)
            except DestinationRefusee as exc:
                raise SourceError(str(exc)) from exc
            resp = self.client.request(method, url, params=params, data=data, json=json, files=files, headers=headers)
            location = resp.headers.get("Location")
            if resp.status_code not in (301, 302, 303, 307, 308) or not location:
                return resp
            url = urljoin(str(resp.url), location)
            params = None  # la cible de redirection porte déjà sa requête
            if resp.status_code == 303 or (resp.status_code in (301, 302) and method == "POST"):
                method, data, json, files = "GET", None, None, None
        raise SourceError(f"Trop de redirections ({MAX_REDIRECTS}) depuis {url}")

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
        idempotent: bool | None = None,
    ) -> tuple[Any, bool]:
        """Renvoie (contenu, depuis_cache). parse = json | text | bytes.
        idempotent : par défaut selon la méthode (GET, HEAD, OPTIONS) ; True pour un POST de pure lecture.
        Une requête non idempotente n'est rejouée que si elle n'a certainement pas été traitée
        (connexion impossible, 429) ; sinon le résultat est signalé indéterminé, sans nouvel envoi."""
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
        replay = method.upper() in IDEMPOTENT if idempotent is None else idempotent
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle(host)
            try:
                resp = self._send(method, url, params=params, data=data, json=json, files=files, headers=headers)
            except httpx.TransportError as exc:
                if not replay and not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                    raise SourceError(self._indetermine(host, type(exc).__name__)) from exc
                last_exc = exc
                self.sleep(delay)
                delay *= 2
                continue
            if resp.status_code in (502, 503, 504) and not replay:
                raise SourceError(self._indetermine(host, f"HTTP {resp.status_code}"), resp.status_code)
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

    @staticmethod
    def _indetermine(host: str, cause: str) -> str:
        return (f"{host} : résultat indéterminé ({cause}) — la requête a pu être traitée ; elle n'est pas renvoyée "
                "automatiquement pour éviter un doublon. Vérifier côté service avant de recommencer.")

    def get(self, url: str, **kw) -> tuple[Any, bool]:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> tuple[Any, bool]:
        return self.request("POST", url, **kw)
