"""Client HTTP commun : cache SQLite, limitation de débit par hôte, backoff sur 429/503,
politique réseau revalidée à chaque redirection (#42), reprises réservées aux requêtes idempotentes (#50)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .cache import Cache
from .reseau import DestinationRefusee, NetworkPolicy

MAX_REDIRECTS = 5
IDEMPOTENT = frozenset({"GET", "HEAD", "OPTIONS"})


MAX_IMAGE_BYTES = 150 * 1024 * 1024  # plafond d'une vue téléchargée (un TIFF de registre dépasse rarement 80 Mo)


class SourceError(Exception):
    """Erreur lisible renvoyée à l'agent (accès refusé, quota, format inattendu...)."""

    def __init__(self, message: str, status: int | None = None, reessayer_apres: float | None = None,
                 echec_memorise: bool = False, coupe_circuit: bool = False, *,
                 bloque_antirobot: bool = False, protection: str | None = None,
                 url: str | None = None, date_detection: str | None = None):
        super().__init__(message)
        self.status = status
        self.reessayer_apres = reessayer_apres  # secondes avant de réessayer (429/503, plafond atteint)
        self.echec_memorise = echec_memorise  # échec servi par le cache négatif, sans requête
        self.coupe_circuit = coupe_circuit  # hôte en pause après un blocage anti-robot
        self.bloque_antirobot = bloque_antirobot
        self.protection = protection
        self.url = url
        self.date_detection = date_detection


def _metadonnees(exc: SourceError) -> dict:
    return {nom: getattr(exc, nom) for nom in ("bloque_antirobot", "protection", "url", "date_detection")}


def _protection(resp: httpx.Response) -> str | None:
    """Signatures de défis, sans assimiler une mention de fournisseur à un blocage."""
    if resp.status_code not in (200, 403, 503):
        return None
    if resp.headers.get("cf-mitigated", "").lower() == "challenge":
        return "Cloudflare"
    corps = resp.content[:65536].decode("utf-8", errors="ignore").lower()
    if ("/cdn-cgi/challenge-platform/" in corps or "cf-chl-" in corps
            or (resp.status_code == 403 and "cloudflare" in corps
                and any(s in corps for s in ("accès refusé", "attention required")))):
        return "Cloudflare"
    if "js.hcaptcha.com/1/api.js" in corps and "h-captcha" in corps:
        return "hCaptcha"
    if "geo.captcha-delivery.com/captcha/" in corps or "datadome.co/captcha/" in corps:
        return "DataDome"
    if "challenge-running" in corps and "checking your browser" in corps:
        return "attente"
    return None


MEMORISES = (403, 404, 429)  # échecs mémorisés par URL (cache négatif)


def retry_after(value: str | None, now: float | None = None) -> float | None:
    """Retry-After en secondes : nombre (« 120 ») ou date HTTP (« Wed, 21 Oct 2026 07:28:00 GMT »)."""
    if not value or not value.strip():
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, when.timestamp() - (time.time() if now is None else now))


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
        default_interval: float = 0.0,
        duree_max: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        echec_ttl: float = 900.0,
        coupe_circuit_ttl: float = 1800.0,
    ):
        self.cache = cache
        self.hotes_contactes: list[str] = []  # relevé par le journal d'exploitation, remis à zéro par appel
        self.echec_ttl = echec_ttl
        self.coupe_circuit_ttl = coupe_circuit_ttl
        self.timeout = timeout
        self.duree_max = duree_max  # plafond d'attente totale d'un appel (essais + reprises)
        self.clock = clock
        self.min_intervals = min_intervals or {}
        self.default_interval = default_interval  # tout hôte non listé (archives, IIIF…) : jamais en rafale
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
        """Réserve le prochain créneau de l'hôte sous le verrou, puis attend hors du verrou : les requêtes vers
        un même hôte restent espacées, celles vers les autres hôtes ne sont pas retardées."""
        name = (urlparse(f"//{host}").hostname or host).lower()
        interval = self.min_intervals.get(host, self.min_intervals.get(name, self.default_interval))
        if not interval:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._last.get(name, float("-inf")) + interval)
            self._last[name] = slot
        if slot > now:
            self.sleep(slot - now)

    def _send(self, method: str, url: str, *, params, data, json, files, headers,
              timeout: float | None = None, stream: bool = False) -> httpx.Response:
        """Requête avec redirections suivies manuellement ; chaque URL passe la politique réseau."""
        sans_secrets = False
        sensibles = {"authorization", "proxy-authorization", "cookie", "x-api-key"}
        for _ in range(MAX_REDIRECTS + 1):
            try:
                self.policy.check(url)
            except DestinationRefusee as exc:
                raise SourceError(str(exc)) from exc
            requete = self.client.build_request(method, url, params=params, data=data, json=json, files=files,
                                                headers=headers,
                                                **({"timeout": timeout} if timeout is not None else {}))
            if sans_secrets:
                for nom in sensibles:
                    requete.headers.pop(nom, None)
            resp = self.client.send(requete, stream=stream)
            location = resp.headers.get("Location")
            if resp.status_code not in (301, 302, 303, 307, 308) or not location:
                return resp
            resp.close()  # le corps des redirections ne sert jamais à la résolution
            destination = urljoin(str(resp.url), location)
            origine = httpx.URL(str(resp.url))
            cible = httpx.URL(destination)
            if resp.status_code == 303 or (resp.status_code in (301, 302) and method == "POST"):
                method, data, json, files = "GET", None, None, None
            if (origine.scheme, origine.host, origine.port) != (cible.scheme, cible.host, cible.port):
                # Les secrets de la source ne doivent pas suivre une redirection tierce,
                # ni une dégradation HTTPS -> HTTP. Comparaison insensible à la casse.
                if method.upper() not in IDEMPOTENT:
                    raise SourceError("Redirection vers une autre origine refusée pour une requête avec écriture.")
                sans_secrets = True
            url = destination
            params = None  # la cible de redirection porte déjà sa requête
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
        """Renvoie (contenu, depuis_cache). parse = json | text | bytes | image (bytes contrôlés : type, taille)
        | status (en-têtes seuls, corps jamais lu, y compris lors des redirections).
        idempotent : par défaut selon la méthode (GET, HEAD, OPTIONS) ; True pour un POST de pure lecture.
        Une requête non idempotente n'est rejouée que si elle n'a certainement pas été traitée
        (connexion impossible, 429) ; sinon le résultat est signalé indéterminé, sans nouvel envoi."""
        params = {k: v for k, v in params.items() if v not in (None, "")} if params is not None else None
        cacheable = use_cache and files is None and ttl > 0
        key = Cache.key(method, url, params, data, json, parse)
        if cacheable:
            hit = self.cache.get(key)
            if hit is not None:
                return hit, True
        if self.offline:
            raise SourceError(f"Mode hors-ligne et pas de cache pour {url}")
        host = urlparse(url).netloc
        self.hotes_contactes.append(self._hote(host))
        self._verifier_coupe_circuit(host)
        memorisable = files is None and (method.upper() in IDEMPOTENT if idempotent is None else idempotent)
        cle_echec = Cache.key("echec", method.upper(), url, params) if memorisable else ""
        if cle_echec:
            echec = self.cache.get(cle_echec)
            if echec is not None:
                reste = max(0.0, echec["jusqu_a"] - time.time())
                raise SourceError(f"(échec mémorisé, sans nouvelle requête) {echec['message']}", echec["status"],
                                  reessayer_apres=round(reste, 1), echec_memorise=True,
                                  **echec.get("antirobot", {}))
        try:
            return self._request(method, url, host, params=params, data=data, json=json, files=files,
                                 headers=headers, ttl=ttl, source=source, parse=parse, cacheable=cacheable,
                                 key=key, idempotent=idempotent)
        except SourceError as exc:
            if cle_echec and (exc.status in MEMORISES or exc.bloque_antirobot):
                duree = exc.reessayer_apres if exc.status == 429 and exc.reessayer_apres else self.echec_ttl
                if duree > 0:
                    self.cache.set(cle_echec, {"message": str(exc), "status": exc.status,
                                               "jusqu_a": time.time() + duree,
                                               "antirobot": _metadonnees(exc)}, duree, source or "echec")
            raise

    def _hote(self, host: str) -> str:
        return (urlparse(f"//{host}").hostname or host).lower()

    def _verifier_coupe_circuit(self, host: str) -> None:
        coupe = self.cache.get(Cache.key("coupe_circuit", self._hote(host)))
        if coupe is None:
            return
        reste = max(0.0, coupe["jusqu_a"] - time.time())
        heure = time.strftime("%H:%M", time.localtime(coupe["jusqu_a"]))
        raise SourceError(
            f"{host} : coupe-circuit actif après blocage anti-robot ({coupe['raison']}) ; reprise à {heure} "
            f"(dans {round(reste)} s). Consulter le site dans le navigateur en attendant ; "
            "cache_purger('coupe_circuit') pour lever la pause.", 403,
            reessayer_apres=round(reste, 1), coupe_circuit=True, **coupe.get("antirobot", {}))

    def _couper(self, host: str, raison: str, exc: SourceError) -> None:
        if self.coupe_circuit_ttl > 0:
            self.cache.set(Cache.key("coupe_circuit", self._hote(host)),
                           {"raison": raison, "jusqu_a": time.time() + self.coupe_circuit_ttl,
                            "antirobot": _metadonnees(exc)},
                           self.coupe_circuit_ttl, "coupe_circuit")

    def _request(self, method: str, url: str, host: str, *, params, data, json, files, headers, ttl, source,
                 parse, cacheable, key, idempotent) -> tuple[Any, bool]:
        replay = method.upper() in IDEMPOTENT if idempotent is None else idempotent
        delay = 1.0
        last_exc: Exception | None = None
        debut = self.clock()

        def attendre(wait: float, attempt: int, cause: str, status: int | None, reessayer: float | None) -> None:
            """Attente avant l'essai suivant, sans jamais dépasser le plafond ni attendre après le dernier."""
            restant = self.duree_max - (self.clock() - debut)
            if attempt + 1 >= self.max_retries or wait >= restant:
                apres = reessayer if reessayer is not None else wait
                raise SourceError(
                    f"{host} : {cause} ; nouvel essai conseillé dans {round(apres)} s "
                    f"(plafond de {self.duree_max:g} s par appel, {attempt + 1} tentative(s)).", status,
                    reessayer_apres=round(apres, 1))
            self.sleep(wait)

        for attempt in range(self.max_retries):
            self._throttle(host)
            restant = self.duree_max - (self.clock() - debut)
            if restant <= 0:
                raise SourceError(f"{host} : plafond de {self.duree_max:g} s atteint ({last_exc})",
                                  reessayer_apres=delay)
            try:
                resp = self._send(method, url, params=params, data=data, json=json, files=files, headers=headers,
                                  timeout=min(self.timeout, restant), stream=parse == "status")
            except httpx.TransportError as exc:
                if not replay and not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                    raise SourceError(self._indetermine(host, type(exc).__name__)) from exc
                last_exc = exc
                attendre(delay, attempt, f"{type(exc).__name__} ({exc})", None, None)
                delay *= 2
                continue
            if parse == "status":
                resp.close()  # disponibilité : ne jamais consommer le corps
            protection = _protection(resp)
            if protection:
                url_blocage = str(resp.url)
                hote_blocage = urlparse(url_blocage).netloc
                exc = SourceError(
                    f"{hote_blocage} : blocage anti-robot ({protection}, HTTP {resp.status_code}). "
                    f"Consulter manuellement {url_blocage} ; aucune tentative de contournement.",
                    resp.status_code, bloque_antirobot=True, protection=protection, url=url_blocage,
                    date_detection=datetime.now(UTC).isoformat())
                self._couper(hote_blocage, f"HTTP {resp.status_code}, {protection}", exc)
                raise exc
            if resp.status_code in (502, 503, 504) and not replay:
                raise SourceError(self._indetermine(host, f"HTTP {resp.status_code}"), resp.status_code,
                                  reessayer_apres=retry_after(resp.headers.get("Retry-After")))
            if resp.status_code in (429, 502, 503, 504):
                demande = retry_after(resp.headers.get("Retry-After"))
                attendre(delay if demande is None else demande, attempt, f"HTTP {resp.status_code}",
                         resp.status_code, demande)
                delay *= 2
                last_exc = SourceError(f"{host} : HTTP {resp.status_code} (tentative {attempt + 1})", resp.status_code)
                continue
            if resp.status_code in (401, 403):
                raise SourceError(f"{host} : accès refusé (HTTP {resp.status_code}) — identifiants requis ?", resp.status_code)
            if resp.status_code == 404:
                raise SourceError(f"{host} : ressource introuvable (404) : {resp.url}", 404)
            if resp.status_code >= 400:
                detail = "" if parse == "status" else resp.text[:300]
                raise SourceError(f"{host} : HTTP {resp.status_code} : {detail}", resp.status_code)
            if parse == "status":
                content = resp.status_code
            elif parse == "json":
                try:
                    content = resp.json()
                except ValueError as exc:
                    raise SourceError(f"{host} : réponse non JSON : {resp.text[:200]}") from exc
            elif parse == "bytes":
                content = resp.content.decode("latin-1")
            elif parse == "image":
                content = self._image(host, resp).decode("latin-1")
            else:
                content = resp.text
            if cacheable and "no-store" not in resp.headers.get("Cache-Control", "").lower():
                self.cache.set(key, content, ttl, source)
            return content, False
        raise SourceError(f"{host} : échec après {self.max_retries} tentatives ({last_exc})")

    @staticmethod
    def _image(host: str, resp: httpx.Response) -> bytes:
        """Corps d'une réponse annoncée comme image : refuse une page (HTML, JSON, XML, texte) servie en 200,
        typiquement une page d'erreur ou un défi anti-robot, et un corps au-delà de MAX_IMAGE_BYTES."""
        ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype.startswith("text/") or any(t in ctype for t in ("html", "json", "xml")):
            raise SourceError(f"{host} : réponse {ctype} au lieu d'une image (page d'erreur ou défi anti-robot ?)",
                              resp.status_code)
        if len(resp.content) > MAX_IMAGE_BYTES:
            raise SourceError(f"{host} : image trop volumineuse ({len(resp.content)} octets, plafond "
                              f"{MAX_IMAGE_BYTES}) : demander une zone ou une taille réduite.", resp.status_code)
        return resp.content

    @staticmethod
    def _indetermine(host: str, cause: str) -> str:
        return (f"{host} : résultat indéterminé ({cause}) — la requête a pu être traitée ; elle n'est pas renvoyée "
                "automatiquement pour éviter un doublon. Vérifier côté service avant de recommencer.")

    def get(self, url: str, **kw) -> tuple[Any, bool]:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> tuple[Any, bool]:
        return self.request("POST", url, **kw)
