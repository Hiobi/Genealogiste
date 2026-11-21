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
REFETCH_LIMIT = 200  # objets à relire : au-delà, relecture complète de la classe
READ_ATTEMPTS = 3
PAUSE_LIMITE_JETON = 1.1  # /token/ et /token/refresh/ : 1 requête par seconde côté Gramps Web (429 au-delà)
RENOUVELLEMENT_MIN = 5.0  # secondes : écart minimal entre deux renouvellements décidés par le contrôle des droits
MARGE_JETON = 30.0  # secondes : jeton d'accès renouvelé un peu avant son expiration (15 min côté Gramps Web)

# Rôles Gramps Web (gramps_webapi/auth/const.py). POST /api/transactions/ exige AddObject + EditObject +
# DeleteObject, soit le rôle Editor (3) au moins.
ROLES = {0: "Guest", 1: "Member", 2: "Contributor", 3: "Editor", 4: "Owner", 5: "Admin"}
ROLE_ECRITURE = 3
DROITS_ECRITURE = ("AddObject", "EditObject", "DeleteObject")
CORRECTIF_ROLE = ("Corriger : dans Gramps Web (Paramètres, Administration, Gérer les utilisateurs), donner au compte "
                  "dédié le rôle Editor, ou utiliser un autre compte ; puis relancer le diagnostic.")


def nom_role(role: int | None) -> str:
    return ROLES.get(role, "inconnu") if role is not None else "inconnu"


class GrampsError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ConflictError(GrampsError):
    """L'arbre Gramps a été modifié (interface, autre client) depuis la lecture."""


def jwt_claims(token: str) -> dict:
    """Revendications d'un jeton JWT (lecture seule, sans vérification de signature : information locale)."""
    import base64
    import json as _json
    parts = (token or "").split(".")
    if len(parts) != 3:
        return {}
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = _json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


class GrampsClient:
    def __init__(self, url: str, user: str, password: str, timeout: float = 60.0,
                 transport: httpx.BaseTransport | None = None, sleeper: Callable[[float], None] = time.sleep,
                 user_agent: str = "genealogiste-mcp",
                 horloge: Callable[[], float] = time.time):
        if not url:
            raise GrampsError("GENEALOGISTE_GRAMPS_URL non défini (ex. http://localhost:5055).")
        if not user or not password:
            raise GrampsError("GENEALOGISTE_GRAMPS_USER / GENEALOGISTE_GRAMPS_PASSWORD non définis "
                              "(compte local dédié, rôle Editor).")
        self.base = url.rstrip("/") + "/api"
        self._user, self._password = user, password
        self.client = httpx.Client(timeout=timeout, transport=transport, headers={"User-Agent": user_agent})
        self.sleep = sleeper
        self._horloge = horloge  # injectable : expiration du jeton testée sans attendre 15 minutes
        self._access = ""
        self._refresh = ""
        self._exp = 0.0
        self._emis = float("-inf")  # instant du dernier appel à /token/ ou /token/refresh/
        self.tree_id = ""  # arbre du compte (revendication « tree » du jeton Gramps Web)

    # ------------------------------------------------------------------ authentification
    def _poster_jeton(self, chemin: str, **kw) -> httpx.Response:
        """POST sur /token/ ou /token/refresh/ ; sur 429 (limite d'une requête par seconde), une seule nouvelle
        tentative après une pause."""
        r = self.client.post(f"{self.base}{chemin}", **kw)
        if r.status_code == 429:
            r.close()
            self.sleep(PAUSE_LIMITE_JETON)
            r = self.client.post(f"{self.base}{chemin}", **kw)
        self._emis = self._horloge()
        return r

    def _login(self) -> None:
        r = self._poster_jeton("/token/", json={"username": self._user, "password": self._password})
        if r.status_code != 200:
            raise GrampsError(f"Gramps Web : authentification refusée (HTTP {r.status_code})", r.status_code)
        data = r.json()
        self._access, self._refresh = data.get("access_token", ""), data.get("refresh_token", "")
        self._exp = self._expiration()
        self.tree_id = jwt_claims(self._access).get("tree") or ""

    def _expiration(self) -> float:
        """Instant de renouvellement : revendication ``exp`` du jeton d'accès moins une marge, sinon 10 minutes."""
        exp = jwt_claims(self._access).get("exp")
        if isinstance(exp, (int, float)) and not isinstance(exp, bool):
            return float(exp) - MARGE_JETON
        return self._horloge() + 600

    def _renew(self) -> None:
        if self._refresh:
            r = self._poster_jeton("/token/refresh/", headers={"Authorization": f"Bearer {self._refresh}"})
            if r.status_code == 200:
                self._access = r.json().get("access_token", "")
                self._exp = self._expiration()
                return
        self._login()

    def _headers(self) -> dict:
        if not self._access:
            self._login()
        elif self._horloge() > self._exp:
            self._renew()
        return {"Authorization": f"Bearer {self._access}"}

    def request(self, method: str, path: str, headers: dict | None = None, **kw) -> httpx.Response:
        """Seuls les GET sont repris : 401 une fois, panne réseau/502/503/504 sur trois essais.

        Une écriture n'est jamais rejouée, même sur 401 ; le jeton est renouvelé avant l'appel si expiré.
        """
        method = method.upper()
        attempts = READ_ATTEMPTS if method == "GET" else 1
        renewed = False
        for attempt in range(1, attempts + 1):
            try:
                while True:
                    r = self.client.request(method, f"{self.base}{path}",
                                            headers={**self._headers(), **(headers or {})}, **kw)
                    if r.status_code != 401 or method != "GET" or renewed:
                        break
                    r.close()
                    renewed = True
                    self._renew()
            except httpx.HTTPError as exc:
                if attempt < attempts:
                    self.sleep(2 ** attempt)
                    continue
                raise GrampsError(f"Gramps Web injoignable ({type(exc).__name__})") from exc
            if r.status_code == 401:
                self._exp = 0  # nouvel appel explicite : renouveler avant d'envoyer, sans rejouer cette écriture
            if r.status_code in (502, 503, 504) and attempt < attempts:
                r.close()
                self.sleep(2 ** attempt)
                continue
            return r
        raise AssertionError("Nombre d'essais de lecture invalide")

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

    def _refus_ecriture(self, r: httpx.Response, what: str) -> httpx.Response:
        """403 (droits) et 422 sur ``message`` (API trop ancienne) en messages actionnables, sinon réponse intacte."""
        if r.status_code == 403:
            raise GrampsError(
                f"Gramps Web {what} refusé (HTTP 403) : le compte n'a pas le droit d'écrire. Écrire exige le rôle "
                f"Editor ou plus. {CORRECTIF_ROLE}", 403)
        if r.status_code == 422 and "message" in r.text and "unknown field" in r.text.lower():
            from .compatibilite import API_TESTEE_MIN, texte_version
            raise GrampsError(
                f"Gramps Web {what} refusé (HTTP 422) : cette version de l'API ne connaît pas le paramètre « message » "
                f"des transactions. Mettre à jour Gramps Web vers l'API {texte_version(API_TESTEE_MIN)} au moins "
                "(docs/gramps-web.md, « Compatibilité des versions ») ; aucune écriture n'est possible avant.", 422)
        return r

    def permissions(self) -> set[str] | None:
        """Droits portés par le jeton d'accès courant (connexion ou renouvellement si besoin) ; None si illisibles."""
        self._headers()
        perms = jwt_claims(self._access).get("permissions")
        return {str(p) for p in perms} if isinstance(perms, list) else None

    def role(self) -> int | None:
        """Rôle du compte (GET /api/users/-/) ; None si le serveur ne l'indique pas."""
        data = self._ok(self.request("GET", "/users/-/"), "lecture du compte").json()
        role = data.get("role") if isinstance(data, dict) else None
        return role if isinstance(role, int) and not isinstance(role, bool) else None

    def exiger_ecriture(self) -> None:
        """Refuse tôt, avant tout calcul, un compte qui ne peut pas écrire (la lecture n'est pas concernée).

        Droits du jeton ; s'ils manquent, le jeton est renouvelé une fois (le rôle a pu changer depuis la connexion)
        puis relu. Jeton sans revendication de droits : rôle du compte. Indéterminé : on laisse passer, un 403
        à l'écriture est de toute façon converti en message actionnable."""
        perms = self.permissions()
        if perms is not None and not set(DROITS_ECRITURE) <= perms and \
                self._horloge() - self._emis >= RENOUVELLEMENT_MIN:  # pas de rafale sur la limite d'une requête/s
            self._renew()
            perms = self.permissions()
        role: int | None = None
        if perms is None or not set(DROITS_ECRITURE) <= perms:
            try:
                role = self.role()
            except GrampsError:
                pass
        if perms is not None and set(DROITS_ECRITURE) <= perms:
            return
        if perms is None and (role is None or role >= ROLE_ECRITURE):
            return
        manque = [d for d in DROITS_ECRITURE if d not in perms] if perms is not None else []
        raise GrampsError(
            "Écriture impossible : le compte Gramps Web ne peut pas écrire"
            + (f" (rôle {nom_role(role)}, {role}" + (f" ; droits manquants : {', '.join(manque)}" if manque else "") + ")"
               if role is not None else f" (droits manquants : {', '.join(manque)})")
            + f". Il faut le rôle Editor ou plus ; la lecture reste possible. {CORRECTIF_ROLE}", 403)

    def upload_media(self, handle: str, data: bytes, mime: str, checksum: str = "") -> None:
        """Envoie le fichier d'un objet Media existant (PUT /media/{handle}/file) ; If-Match = somme actuelle."""
        headers = {"Content-Type": mime or "application/octet-stream"}
        if checksum:
            headers["If-Match"] = f'"{checksum}"'
        r = self.request("PUT", f"/media/{handle}/file", headers=headers, content=data)
        if r.status_code == 412:
            raise ConflictError("Conflit : le fichier du média a été modifié dans Gramps Web depuis la lecture.")
        self._ok(self._refus_ecriture(r, f"envoi du fichier du média {handle}"), f"envoi du fichier du média {handle}")

    def tree(self) -> str:
        """Identifiant de l'arbre Gramps Web du compte (connexion si nécessaire)."""
        if not self._access:
            self._login()
        return self.tree_id

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
            # Gramps date les modifications à la seconde. Relire la seconde la plus récente de chaque
            # classe même si son horodatage n'a pas changé ; comparer le contenu avant de compter.
            horizon = max((o.get("change", 0) for o in local.values()), default=0)
            check = [h for h, c in stamps.items() if h not in local or local[h].get("change") != c or c >= horizon]
            if len(check) > REFETCH_LIMIT:
                fresh = {o["handle"]: to_raw(o, cls) for o in self.list(cls)}
            else:
                fresh = {h: o for h, o in local.items() if h in stamps}
                for h in check:
                    o = self.get(cls, h)
                    if o is None:
                        fresh.pop(h, None)
                    else:
                        fresh[h] = o
            gone = local.keys() - fresh.keys()
            changed = [h for h, o in fresh.items() if local.get(h) != o]
            for h in gone:
                out.remove(cls, h)
            for h in changed:
                out.put(fresh[h])
            if changed or gone:
                report[cls] = {"modifies": len(changed), "supprimes": len(gone)}
        return out, report

    def search(self, texte: str, nombre: int = 20) -> list[dict]:
        r = self._ok(self.request("GET", "/search/", params={"query": texte, "pagesize": nombre, "page": 1}),
                     "recherche")
        return r.json()

    def name_groups(self) -> dict[str, str]:
        """Regroupements globaux de patronymes (``GET /api/name-groups/``, #276) : {patronyme: nom de groupe}.

        Lecture seule, ouverte à tout compte authentifié. L'API ne liste que les patronymes REGROUPÉS (table
        ``name_group`` de Gramps) : un patronyme absent est son propre groupe. Genealogiste n'écrit jamais ces
        regroupements (``POST /api/name-groups/<patronyme>/<groupe>`` n'entre pas dans l'historique des transactions
        et ne sait pas revenir à « aucun regroupement » : docs/gramps-web.md, « Groupes de noms »)."""
        from .groupes_noms import lire_reponse

        return lire_reponse(self._ok(self.request("GET", "/name-groups/"), "lecture des groupes de noms").json())

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
        return self._ok(self._refus_ecriture(r, what), what).json()
