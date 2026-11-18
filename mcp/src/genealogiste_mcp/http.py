"""Client HTTP commun : cache SQLite, limitation de débit par hôte partagée entre processus et ralentissement
durable après 429/502/503/504 (#211), backoff sur 429/503, politique réseau revalidée à chaque redirection (#42),
reprises réservées aux requêtes idempotentes (#50)."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .cache import Cache
from .reseau import DestinationRefusee, NetworkPolicy

MAX_REDIRECTS = 5
IDEMPOTENT = frozenset({"GET", "HEAD", "OPTIONS"})
SURCHARGE = frozenset({429, 502, 503, 504})  # réponses qui ralentissent l'hôte pour la journée (#211)
FACTEUR_MAX = 64.0  # doublements cumulés au plus ; l'intervalle effectif reste borné par ralentissement_max
ANTI_REBOND = 300.0  # (s) au plus un doublement par hôte dans cette fenêtre : une rafale d'erreurs = un épisode
# (s) un défi observé de nouveau dans cette fenêtre après le précédent est un défi persistant : exclusion (#150)
FENETRE_RECIDIVE = 30 * 86400.0


MAX_IMAGE_BYTES = 150 * 1024 * 1024  # plafond d'une vue téléchargée (un TIFF de registre dépasse rarement 80 Mo)


class SourceError(Exception):
    """Erreur lisible renvoyée à l'agent (accès refusé, quota, format inattendu...)."""

    def __init__(self, message: str, status: int | None = None, reessayer_apres: float | None = None,
                 echec_memorise: bool = False, coupe_circuit: bool = False, *,
                 bloque_antirobot: bool = False, protection: str | None = None,
                 url: str | None = None, date_detection: str | None = None, intervalle: float | None = None,
                 exclusion: bool = False, exclu_jusqu_au: str | None = None):
        super().__init__(message)
        self.exclusion = exclusion  # hôte exclu durablement : défi persistant après la pause (#150)
        self.exclu_jusqu_au = exclu_jusqu_au  # fin de l'exclusion (ISO 8601, UTC)
        self.intervalle = intervalle  # intervalle courant (s) entre deux requêtes vers l'hôte, s'il est ralenti
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


# Défi Anubis (TecharoHQ/anubis, gabarit web/index.templ) : scripts JSON `anubis_challenge` et ressources servies
# sous /.within.website/x/cmd/anubis/. Les deux sont exigés : une page citant Anubis n'est pas un défi.
ANUBIS_MARQUEURS = ('id="anubis_challenge"', "/.within.website/x/cmd/anubis/")
TITRES_VERIFICATION = ("<title>security verification</title>", "<title>verify you are human</title>",
                       "<title>vérification de sécurité</title>")


def _protection(resp: httpx.Response) -> str | None:
    """Signatures de défis, sans assimiler une mention de fournisseur à un blocage ; lecture seule du HTML,
    aucun script exécuté ni preuve de travail calculée."""
    if resp.status_code < 200 or resp.status_code in (204, 304) or 300 <= resp.status_code < 400:
        return None
    if resp.status_code in (200, 403, 503) and resp.headers.get("cf-mitigated", "").lower() == "challenge":
        return "Cloudflare"
    if not resp.is_stream_consumed:
        return None
    corps = resp.content[:65536].decode("utf-8", errors="ignore").lower()
    ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if ctype not in ("text/html", "application/xhtml+xml"):
        if ctype or not corps.lstrip().startswith(("<!doctype html", "<html")):
            return None
    # Le statut d'un défi Anubis est configurable (status_codes.CHALLENGE, 200 par défaut).
    if all(m in corps for m in ANUBIS_MARQUEURS):
        return "Anubis"
    if resp.status_code not in (200, 403, 503):
        return None
    if ("window._cf_chl_opt" in corps
            or ("/cdn-cgi/challenge-platform/" in corps
                and any(titre in corps for titre in ("<title>just a moment", "<title>attention required",
                                                     "<title>vérification en cours")))
            or (resp.status_code == 403 and "cloudflare" in corps
                and any(s in corps for s in ("accès refusé", "attention required")))
            # Page de blocage générée par Cloudflare (règle de pare-feu, ex. erreur 1020) : 403 seulement, la
            # même structure servie en 5xx signale une panne de l'origine (#150).
            or (resp.status_code == 403 and 'id="cf-error-details"' in corps and "cloudflare" in corps)):
        return "Cloudflare"
    if ("js.hcaptcha.com/1/api.js" in corps and "h-captcha" in corps
            and any(s in corps for s in TITRES_VERIFICATION)):
        return "hCaptcha"
    if (any(s in corps for s in ("www.google.com/recaptcha/api.js", "www.recaptcha.net/recaptcha/api.js"))
            and "g-recaptcha" in corps and any(s in corps for s in TITRES_VERIFICATION)):
        return "reCAPTCHA"
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
        plafond=None,
        horloge_murale: Callable[[], float] = time.time,
        jour: Callable[[], date] = date.today,
        ralentissement_max: float = 60.0,
        politique=None,
        exclusion_ttl: float = 0.0,
    ):
        from .politique_acces import PolitiqueAcces

        self.cache = cache
        self.exclusion_ttl = exclusion_ttl  # exclusion (s) d'un hôte dont le défi persiste ; 0 = pause seule
        self.plafond = plafond  # budget.PlafondJour : plafond journalier par hôte, selon la politique d'accès (#211)
        self.hotes_contactes: list[str] = []  # relevé par le journal d'exploitation, remis à zéro par appel
        self.echec_ttl = echec_ttl
        self.coupe_circuit_ttl = coupe_circuit_ttl
        self.timeout = timeout
        self.duree_max = duree_max  # plafond d'attente totale d'un appel (essais + reprises)
        self.clock = clock
        # Politique d'accès par service (#211) : seule source de l'intervalle de chaque hôte. Sans politique
        # (clients de test, sondes), elle est construite à partir de min_intervals / default_interval.
        self.politique = politique or PolitiqueAcces(services={}, debits=min_intervals or {},
                                                     debit_defaut=default_interval)
        self.min_intervals = self.politique.intervalles_declares()
        self.default_interval = self.politique.debit_defaut  # tout hôte non listé : jamais en rafale
        self.sleep = sleeper
        self.max_retries = max_retries
        self.offline = offline
        self.policy = policy or NetworkPolicy()
        self.horloge_murale = horloge_murale  # créneaux partagés entre processus : horloge murale, pas monotone
        self.jour = jour  # date locale : un ralentissement dure jusqu'à minuit
        self.ralentissement_max = ralentissement_max  # plafond (s) de l'intervalle ralenti ; 0 = pas de ralentissement
        self._last: dict[str, float] = {}  # repli en mémoire si le cache SQLite est absent ou verrouillé
        self._lock = threading.Lock()
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=False,  # suivies à la main : chaque destination est revalidée
            transport=transport,
        )

    def _intervalle_base(self, host: str) -> float:
        return self.politique.intervalle(host)

    def _facteur(self, name: str) -> float:
        if self.cache is None or not self.ralentissement_max:
            return 1.0
        try:
            return self.cache.ralentissement(name, self.jour().isoformat())
        except sqlite3.Error:
            return 1.0

    def intervalle(self, host: str) -> float:
        """Intervalle effectif (s) entre deux requêtes vers ``host`` : celui de la configuration, multiplié par
        le ralentissement du jour (#211) sans dépasser ``ralentissement_max`` (ni descendre sous la base)."""
        base = self._intervalle_base(host)
        if not base:
            return 0.0
        facteur = self._facteur(self._hote(host))
        if facteur <= 1.0:
            return base
        return max(base, min(base * facteur, self.ralentissement_max))

    def _ralentir(self, host: str, status: int) -> float | None:
        """Après une réponse de surcharge : double le facteur de l'hôte pour la journée (persistant, partagé),
        au plus une fois par fenêtre de ``ANTI_REBOND`` s ; les incidents suivants de la fenêtre sont comptés
        sans doubler. Renvoie l'intervalle effectif s'il est ralenti, sinon None."""
        if self.cache is None or not self.ralentissement_max or not self._intervalle_base(host):
            return None
        try:
            self.cache.ralentir(self._hote(host), self.jour().isoformat(), FACTEUR_MAX, status,
                                self.horloge_murale(), anti_rebond=ANTI_REBOND)
        except sqlite3.Error:
            return None
        return self.intervalle(host)

    def _throttle(self, host: str) -> None:
        """Réserve le prochain créneau de l'hôte, puis attend hors de tout verrou : les requêtes vers un même
        hôte restent espacées, celles vers les autres hôtes ne sont pas retardées. La réservation est atomique
        dans le cache SQLite (transaction BEGIN IMMEDIATE, horloge murale) : plusieurs processus ou conteneurs
        partageant le cache respectent ensemble l'intervalle (#211). Cache absent ou verrouillé au-delà de
        quelques secondes : repli sur le créneau en mémoire de ce processus."""
        name = self._hote(host)
        interval = self.intervalle(host)
        if not interval:
            return
        now = self.horloge_murale()
        slot = None
        if self.cache is not None:
            try:
                slot = self.cache.reserver_creneau(name, interval, now)
            except sqlite3.Error:
                slot = None
        with self._lock:
            if slot is None:
                slot = max(now, self._last.get(name, float("-inf")) + interval)
            self._last[name] = max(slot, self._last.get(name, float("-inf")))
        if slot > now:
            self.sleep(slot - now)

    def _send(self, method: str, url: str, *, params, data, json, files, headers,
              timeout: float | None = None, stream: bool = False) -> httpx.Response:
        """Requête avec redirections suivies manuellement ; chaque URL passe la politique réseau."""
        sans_secrets = False
        sensibles = {"authorization", "proxy-authorization", "cookie", "x-api-key"}
        for _ in range(MAX_REDIRECTS + 1):
            self._verifier_coupe_circuit(urlparse(url).netloc)
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
            self._autoriser_envoi(urlparse(url).netloc)
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
        self._verifier_exclusion(host)
        coupe = self.cache.get(Cache.key("coupe_circuit", self._hote(host)))
        if coupe is None:
            return
        reste = max(0.0, coupe["jusqu_a"] - time.time())
        heure = time.strftime("%H:%M", time.localtime(coupe["jusqu_a"]))
        raise SourceError(
            f"{host} : coupe-circuit actif après blocage anti-robot ({coupe['raison']}) ; reprise à {heure} "
            f"(dans {round(reste)} s). Poursuivre les autres pistes ; la consultation passe par l'utilisateur "
            "(tâche manuelle) ; cache_purger('coupe_circuit') pour lever la pause.", 403,
            reessayer_apres=round(reste, 1), coupe_circuit=True, **coupe.get("antirobot", {}))

    def _verifier_exclusion(self, host: str) -> None:
        """Hôte exclu durablement (#150) : un défi a persisté après la pause ; aucune requête jusqu'à la fin de
        l'exclusion ou sa levée explicite (cache_purger('coupe_circuit'))."""
        try:
            defi = self.cache.defi_antirobot(self._hote(host))
        except sqlite3.Error:
            return
        if not defi or not defi.get("exclu_jusqu_a"):
            return
        reste = defi["exclu_jusqu_a"] - self.horloge_murale()
        if reste <= 0:
            return
        fin = datetime.fromtimestamp(defi["exclu_jusqu_a"], UTC).isoformat(timespec="seconds")
        raise SourceError(
            f"{host} : service exclu après un défi anti-robot persistant ({defi['protection']}, "
            f"{defi['detections']} détections) jusqu'au {fin} ; aucune requête n'est émise. Poursuivre les "
            "autres pistes ; la consultation passe par l'utilisateur (tâche manuelle) ; "
            "cache_purger('coupe_circuit') pour lever l'exclusion.", 403,
            reessayer_apres=round(reste, 1), coupe_circuit=True, bloque_antirobot=True,
            protection=defi["protection"], url=defi["url"],
            date_detection=datetime.fromtimestamp(defi["derniere"], UTC).isoformat(),
            exclusion=True, exclu_jusqu_au=fin)

    def _observer_defi(self, host: str, protection: str, url: str, statut: int) -> dict:
        """Historique durable du défi (#150) ; exclusion si le défi persiste après une pause."""
        try:
            return self.cache.noter_defi(self._hote(host), protection, url, statut, self.horloge_murale(),
                                         self.exclusion_ttl, FENETRE_RECIDIVE)
        except sqlite3.Error:
            return {}

    def _couper(self, host: str, raison: str, exc: SourceError) -> None:
        if self.coupe_circuit_ttl > 0:
            self.cache.set(Cache.key("coupe_circuit", self._hote(host)),
                           {"raison": raison, "jusqu_a": time.time() + self.coupe_circuit_ttl,
                            "antirobot": _metadonnees(exc)},
                           self.coupe_circuit_ttl, "coupe_circuit")

    def _autoriser_envoi(self, host: str) -> None:
        """Juste avant une requête réellement émise (#157) : budget de l'enquête en cours puis plafond journalier
        de l'hôte ; un refus lève une SourceError sans rien envoyer. Sinon la requête est comptée."""
        from . import budget

        hote = self._hote(host)
        budget.avant_envoi(hote)
        if self.plafond is not None:
            self.plafond.consommer(hote)
        budget.compter(hote)

    def _request(self, method: str, url: str, host: str, *, params, data, json, files, headers, ttl, source,
                 parse, cacheable, key, idempotent) -> tuple[Any, bool]:
        replay = method.upper() in IDEMPOTENT if idempotent is None else idempotent
        delay = 1.0
        last_exc: Exception | None = None
        debut = self.clock()

        def attendre(wait: float, attempt: int, cause: str, status: int | None, reessayer: float | None,
                     ralenti: float | None = None) -> None:
            """Attente avant l'essai suivant, sans jamais dépasser le plafond ni attendre après le dernier."""
            restant = self.duree_max - (self.clock() - debut)
            if attempt + 1 >= self.max_retries or wait >= restant:
                apres = reessayer if reessayer is not None else max(wait, ralenti or 0.0)
                raise SourceError(
                    f"{host} : {cause} ; nouvel essai conseillé dans {round(apres)} s "
                    f"(plafond de {self.duree_max:g} s par appel, {attempt + 1} tentative(s))."
                    + self._note_ralenti(ralenti), status,
                    reessayer_apres=round(apres, 1), intervalle=ralenti)
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
                obs = self._observer_defi(hote_blocage, protection, url_blocage, resp.status_code)
                exclu = obs.get("exclu_jusqu_a") if obs.get("recidive") else None
                fin = datetime.fromtimestamp(exclu, UTC).isoformat(timespec="seconds") if exclu else None
                exc = SourceError(
                    f"{hote_blocage} : blocage anti-robot ({protection}, HTTP {resp.status_code}). "
                    f"Consultation par l'utilisateur : {url_blocage} ; aucune tentative de contournement."
                    + (f" Défi persistant ({obs['detections']} détections) : service exclu jusqu'au {fin} "
                       "(cache_purger('coupe_circuit') pour lever l'exclusion)." if fin else ""),
                    resp.status_code, bloque_antirobot=True, protection=protection, url=url_blocage,
                    date_detection=datetime.now(UTC).isoformat(), exclusion=bool(fin), exclu_jusqu_au=fin,
                    reessayer_apres=round(exclu - self.horloge_murale(), 1) if exclu else None)
                self._couper(hote_blocage, f"HTTP {resp.status_code}, {protection}", exc)
                raise exc
            ralenti = self._ralentir(host, resp.status_code) if resp.status_code in SURCHARGE else None
            if resp.status_code in (502, 503, 504) and not replay:
                raise SourceError(self._indetermine(host, f"HTTP {resp.status_code}") + self._note_ralenti(ralenti),
                                  resp.status_code, reessayer_apres=retry_after(resp.headers.get("Retry-After")),
                                  intervalle=ralenti)
            if resp.status_code in SURCHARGE:
                demande = retry_after(resp.headers.get("Retry-After"))
                attendre(delay if demande is None else demande, attempt, f"HTTP {resp.status_code}",
                         resp.status_code, demande, ralenti)
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
    def _note_ralenti(intervalle: float | None) -> str:
        if not intervalle:
            return ""
        return (f" Hôte ralenti jusqu'à minuit : {intervalle:g} s entre deux requêtes "
                "(cache_purger('ralentissement') pour revenir au rythme normal).")

    @staticmethod
    def _indetermine(host: str, cause: str) -> str:
        return (f"{host} : résultat indéterminé ({cause}) — la requête a pu être traitée ; elle n'est pas renvoyée "
                "automatiquement pour éviter un doublon. Vérifier côté service avant de recommencer.")

    def get(self, url: str, **kw) -> tuple[Any, bool]:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> tuple[Any, bool]:
        return self.request("POST", url, **kw)
