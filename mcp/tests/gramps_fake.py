"""Faux serveur Gramps Web (respx) fidèle au contrat de l'API utilisé par Sosa.

- lectures au format simplifié (types en chaîne XML, pas de ``_class``, ``Date.year``, handles vides en "") ;
- ``POST /api/transactions/`` : lot atomique, ``old`` comparé à la base (clés de ``old`` seulement, ``change``
  ignoré, comme ``gramps.gen.merge.diff.diff_items``) -> HTTP 400 « Object has changed » ; ``undo`` inverse
  le lot ; ``background`` -> 202 + ``/api/tasks/<id>`` ; ``force`` jamais attendu (vérifié) ;
- historique des messages de transaction, pour vérifier la traçabilité ;
- comptes à rôle paramétrable (Guest 0 à Admin 5) : le jeton est un JWT à la forme réelle
  ``{"permissions": [...], "tree": ..., "exp": ...}`` (gramps_webapi ``token.py`` ; le rôle n'y figure pas), valable
  15 minutes (horloge injectable), rafraîchi avec les mêmes revendications relues d'après le rôle courant ;
  transactions et envoi de fichier refusés en 403 sans AddObject/EditObject/DeleteObject (corps flask-smorest
  ``{"code": 403, "status": "Forbidden"}``) ;
- ``GET /api/metadata/`` (versions, ``server.task_queue``…), ``GET /api/users/-/`` (rôle), ``GET /api/register/config/``
  (API >= 3.26.0 seulement) ; ``limite_jeton=True`` : ``/token/`` et ``/token/refresh/`` limités à 1 requête par
  seconde (429), sur l'horloge injectable ; version d'API paramétrable, ``message=`` refusé en 422 avant 3.13.0 ;
- groupes de noms (#276) : ``GET /api/name-groups/`` (seuls les patronymes regroupés, par ordre de nom),
  ``GET /api/name-groups/<patronyme>`` (le groupe, ou le patronyme lui-même sans regroupement, comme
  ``get_name_group_mapping``), ``POST /api/name-groups/<patronyme>/<groupe>`` (droit EditNameGroup, 201) ;
  comme Gramps, un POST n'entre PAS dans l'historique des transactions et regrouper un nom sous lui-même laisse la
  clé listée : aucune route ne retire un regroupement.
- signets, fiche chercheur, formats de nom (#282) : ``GET /api/bookmarks/<namespace>`` (404 hors des neuf espaces),
  ``PUT``/``DELETE /api/bookmarks/<namespace>/<handle>`` (EditObject ; PUT ajoute EN FIN de liste, 404 si l'objet
  n'existe pas, DELETE 404 si le signet n'existe pas ; corps vide), ``GET /api/metadata/`` -> ``researcher`` (onze
  clés), ``PUT /api/metadata/researcher/`` (EditTree, Owner ; mise à jour PARTIELLE : seules les clés envoyées,
  clés inconnues refusées en 422), ``GET /api/name-formats/`` (lecture seule). Comme Gramps, aucune de ces écritures
  n'entre dans l'historique des transactions.
- privé (#264) : un jeton sans ``ViewPrivate`` (rôle Invité) lit la base à travers le filtre du privé de
  gramps-web-api (``api/access/sanitize.py``, ``db.py``) : objet principal privé introuvable (liste, handle,
  ``gramps_id``, recherche : 404 sur une lecture directe), sous-objets privés retirés, références vers un objet
  invisible retirées (``father_handle``/``mother_handle`` vidés, enfants, événements, médias, citations, notes),
  citation d'une source invisible masquée, nom principal privé remplacé par « Private » ;
- ``GET /api/living/<handle>`` (``probably_alive`` ; ``vivants`` : handle -> booléen, sinon vivant sans référence
  de décès ; ``max_age_probably_alive`` et les autres paramètres sont relevés dans ``living_requetes`` ; réponse
  selon ``vivants_100`` quand ``max_age_probably_alive=100``) ; ``GET /api/users/`` (droit ViewOtherUser, rôle Owner :
  ``comptes``, liste de ``{"name", "role"}``).
Défauts : compte Editor, API épinglée de docker-compose.test.yml. Données fictives uniquement.
"""

from __future__ import annotations

import base64
import copy
import json
import re
import time
from urllib.parse import unquote

import httpx
import respx

from genealogiste_mcp.gramps.types import CLASSES, tname

URL = "http://gramps.test"
PLURAL = {v: k for k, v in CLASSES.items()}

# gramps_webapi/auth/const.py : droits cumulés par rôle (seuls ceux utiles aux tests sont énumérés).
ROLE_NOMS = {0: "Guest", 1: "Member", 2: "Contributor", 3: "Editor", 4: "Owner", 5: "Admin"}
_MEMBER = {"EditOwnUser", "ViewPrivate"}
_CONTRIBUTOR = _MEMBER | {"AddObject"}
_EDITOR = _CONTRIBUTOR | {"EditObject", "DeleteObject", "EditNameGroup", "EditCustomFilter"}
_OWNER = _EDITOR | {"AddUser", "DeleteUser", "EditOtherUser", "EditUserRole", "ViewOtherUser", "ImportFile",
                    "ManageBackups", "TriggerReindex", "EditTree", "RepairTree", "UpgradeSchema",
                    "EditTreeMinRoleAI", "BatchDeleteObjects"}
PERMISSIONS = {0: {"EditOwnUser"}, 1: _MEMBER, 2: _CONTRIBUTOR, 3: _EDITOR, 4: _OWNER,
               5: _OWNER | {"ViewSettings", "EditSettings", "AddTree", "MakeAdmin"}}
CHERCHEUR_CLES = ("name", "addr", "street", "locality", "city", "county", "state", "country", "postal", "phone",
                  "email")  # ResearcherUpdateSchema (gramps_webapi/api/resources/metadata.py)
ESPACES_SIGNETS = ("citations", "events", "families", "media", "notes", "people", "places", "repositories",
                   "sources")  # _BOOKMARK_TYPES (bookmarks.py)
ESPACE_CLASSE = {"people": "Person", "families": "Family", "events": "Event", "places": "Place", "sources": "Source",
                 "citations": "Citation", "repositories": "Repository", "media": "Media", "notes": "Note"}
DUREE_JETON = 900  # JWT_ACCESS_TOKEN_EXPIRES = 15 min


def version_tuple(v: str) -> tuple[int, int, int]:
    n = [int(x) for x in v.split(".")[:3]]
    return (n[0], n[1], n[2] if len(n) > 2 else 0)


def jwt_payload(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    try:
        return json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError:
        return {}


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
    def __init__(self, user: str = "sosa", password: str = "secret", tree: str = "", role: int = 3,
                 api_version: str = "3.25.1", gramps_version: str = "6.0.8", task_queue: bool = False,
                 multi_tree: bool = False, inscription_libre: bool = False, horloge=time.time,
                 limite_jeton: bool = False, default_person: str = ""):
        self.user, self.password = user, password
        self.tree = tree  # si défini : le jeton porte la revendication « tree » (toujours présente en réalité)
        self.role = role  # modifiable en cours de test : relu au renouvellement du jeton, pas avant
        self.api_version, self.gramps_version = api_version, gramps_version
        self.task_queue, self.multi_tree, self.inscription_libre = task_queue, multi_tree, inscription_libre
        self.horloge = horloge  # injectable : expiration du jeton (15 min) sans attendre
        self.logins = self.refreshes = 0
        self.default_person = default_person  # handle de la personne de référence (« » : aucune), #274
        self.limite_jeton, self._dernier_jeton = limite_jeton, float("-inf")
        self.objects: dict[str, dict[str, dict]] = {c: {} for c in CLASSES}
        self.clock = 1_000
        self.name_groups: dict[str, str] = {}  # table name_group de Gramps : patronyme -> groupe (#276)
        self.chercheur: dict[str, str] = {k: "" for k in CHERCHEUR_CLES}  # fiche du chercheur (#282), vide par défaut
        self.signets: dict[str, list[str]] = {n: [] for n in ESPACES_SIGNETS}  # signets de la base (#282)
        self.formats_noms: list[dict] = []  # formats de nom personnalisés de la base (#282) : number, name, format, active
        self.messages: list[str] = []
        self.transactions: list[list[dict]] = []
        self.forced = False
        self.tasks: dict[str, dict] = {}
        self.files: dict[str, bytes] = {}  # fichiers des médias, par handle
        self.vivants: dict[str, bool] = {}  # /api/living/<handle> (#264) : réponse imposée par handle
        self.vivants_100: dict[str, bool] = {}  # réponse avec max_age_probably_alive=100
        self.living_requetes: list[tuple[str, dict]] = []
        self.comptes: list[dict] = [{"name": user, "role": role}]  # GET /api/users/ (Owner)
        self.router = respx.mock(assert_all_called=False)
        api = URL + "/api"
        r = self.router
        r.post(api + "/token/").mock(side_effect=self._token)
        r.post(api + "/token/refresh/").mock(side_effect=self._refresh)
        r.get(api + "/metadata/").mock(side_effect=self._metadata)
        r.get(api + "/users/-/").mock(side_effect=self._me)
        r.get(api + "/register/config/").mock(side_effect=self._register_config)
        r.get(api + "/metadata/researcher/").mock(side_effect=self._chercheur_lire)
        r.put(api + "/metadata/researcher/").mock(side_effect=self._chercheur_ecrire)
        r.get(api + "/name-formats/").mock(side_effect=self._formats)
        r.get(url__regex=re.escape(api) + r"/bookmarks/(?P<ns>[^/?]+)$").mock(side_effect=self._signets_lire)
        r.put(url__regex=re.escape(api) + r"/bookmarks/(?P<ns>[^/?]+)/(?P<handle>[^/?]+)$").mock(
            side_effect=self._signet_poser)
        r.delete(url__regex=re.escape(api) + r"/bookmarks/(?P<ns>[^/?]+)/(?P<handle>[^/?]+)$").mock(
            side_effect=self._signet_retirer)
        r.get(api + "/name-groups/").mock(side_effect=self._groupes)
        r.get(url__regex=re.escape(api) + r"/name-groups/(?P<surname>[^/?]+)$").mock(side_effect=self._groupe)
        r.post(url__regex=re.escape(api) + r"/name-groups/(?P<surname>[^/?]+)/(?P<group>[^/?]+)$").mock(
            side_effect=self._poser_groupe)
        r.post(api + "/transactions/").mock(side_effect=self._transaction)
        r.put(url__regex=re.escape(api) + r"/media/(?P<handle>[^/?]+)/file(\?.*)?$").mock(side_effect=self._file)
        r.get(api + "/search/").mock(side_effect=self._search)
        r.get(api + "/users/").mock(side_effect=self._users)
        r.get(url__regex=re.escape(api) + r"/living/(?P<handle>[^/?]+)(\?.*)?$").mock(side_effect=self._living)
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
        bearer = req.headers.get("Authorization", "")
        if not bearer.startswith("Bearer A"):
            return httpx.Response(401, json={"error": {"code": 401, "message": "unauthorized"}})
        exp = jwt_payload(bearer.removeprefix("Bearer ")).get("exp")
        if exp is not None and self.horloge() >= exp:  # flask-jwt-extended : jeton expiré = 401
            return httpx.Response(401, json={"msg": "Token has expired"})
        return None

    def _jeton(self, prefixe: str) -> str:
        """JWT à la forme réelle : droits du rôle courant, arbre, expiration (rôle absent du jeton)."""
        claims = {"permissions": sorted(PERMISSIONS.get(self.role, set())), "exp": int(self.horloge()) + DUREE_JETON}
        if self.tree:
            claims["tree"] = self.tree
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        return f"{prefixe}.{payload}.signature"

    def _droits(self, req, *exiges: str) -> httpx.Response | None:
        """403 (abort(403) de flask-smorest) si le jeton ne porte pas tous les droits exigés."""
        perms = set(jwt_payload(req.headers.get("Authorization", "").removeprefix("Bearer ")).get("permissions", []))
        if not set(exiges) <= perms:
            return httpx.Response(403, json={"code": 403, "status": "Forbidden"})
        return None

    def _limite(self) -> httpx.Response | None:
        """flask-limiter ``1/second`` sur les deux routes de jeton (réponse 429)."""
        if not self.limite_jeton:
            return None
        maintenant, depuis = self.horloge(), self._dernier_jeton
        self._dernier_jeton = maintenant
        if maintenant - depuis < 1:
            return httpx.Response(429, json={"code": 429, "status": "Too Many Requests"})
        return None

    def _refresh(self, req):
        if (r := self._limite()) is not None:
            return r
        self.refreshes += 1
        return httpx.Response(200, json={"access_token": self._jeton("A2")})

    def _metadata(self, req):
        if (r := self._auth(req)) is not None:
            return r
        counts = {c.lower(): len(o) for c, o in self.objects.items() if c != "Tag"}
        return httpx.Response(200, json={
            "database": {"id": "fake", "name": "Sosa-tests", "type": "sqlite"},
            "default_person": self.default_person,
            "gramps": {"version": self.gramps_version},
            "gramps_webapi": {"schema": self.api_version, "version": self.api_version},
            "object_counts": counts, "researcher": dict(self.chercheur),
            "server": {"multi_tree": self.multi_tree, "task_queue": self.task_queue, "ocr": False,
                       "semantic_search": False, "chat": False, "email": False, "backups": False}})

    def _me(self, req):
        if (r := self._auth(req)) is not None:
            return r
        return httpx.Response(200, json={"name": self.user, "email": "", "full_name": "", "role": self.role,
                                         "tree": self.tree, "user_id": "u1"})

    def _chercheur_lire(self, req):
        if (r := self._auth(req)) is not None:
            return r
        return httpx.Response(200, json=dict(self.chercheur))

    def _chercheur_ecrire(self, req):
        """PUT /metadata/researcher/ : ``require_permissions([EditTree])`` puis mise à jour PARTIELLE (seules les clés
        du corps), clés inconnues refusées (``unknown = RAISE`` : 422) ; hors transaction, pas d'historique."""
        if (r := self._auth(req)) is not None:
            return r
        corps = json.loads(req.content or b"{}")
        if set(corps) - set(CHERCHEUR_CLES) or not all(isinstance(v, str) for v in corps.values()):
            inconnues = {k: ["Unknown field."] for k in corps if k not in CHERCHEUR_CLES}
            return httpx.Response(422, json={"error": {"code": 422, "message": "json: " + ", ".join(
                f"{k}: Unknown field." for k in inconnues), "messages": {"json": inconnues}}})
        if (r := self._droits(req, "EditTree")) is not None:
            return r
        self.chercheur.update(corps)
        return httpx.Response(200, json=dict(self.chercheur))

    def _formats(self, req):
        if (r := self._auth(req)) is not None:
            return r
        return httpx.Response(200, json=copy.deepcopy(self.formats_noms))

    def _signets_lire(self, req, ns):
        if (r := self._auth(req)) is not None:
            return r
        ns = unquote(ns)
        if ns not in ESPACES_SIGNETS:
            return httpx.Response(404, json={"code": 404, "status": "Not Found"})
        return httpx.Response(200, json=list(self.signets[ns]))

    def _signet_poser(self, req, ns, handle):
        """PUT : ajoute EN FIN de liste (``bookmarks.append``) si absent, 404 si l'objet n'existe pas ; corps vide."""
        if (r := self._auth(req)) is not None:
            return r
        if (r := self._droits(req, "EditObject")) is not None:
            return r
        ns, handle = unquote(ns), unquote(handle)
        if ns not in ESPACES_SIGNETS:
            return httpx.Response(404, json={"code": 404, "status": "Not Found"})
        if handle not in self.signets[ns]:
            if handle not in self.objects[ESPACE_CLASSE[ns]]:
                return httpx.Response(404, json={"error": {"code": 404, "message": "Object does not exist"}})
            self.signets[ns].append(handle)
        return httpx.Response(200, content=b"")

    def _signet_retirer(self, req, ns, handle):
        if (r := self._auth(req)) is not None:
            return r
        if (r := self._droits(req, "EditObject")) is not None:
            return r
        ns, handle = unquote(ns), unquote(handle)
        if ns not in ESPACES_SIGNETS:
            return httpx.Response(404, json={"code": 404, "status": "Not Found"})
        if handle not in self.signets[ns]:
            return httpx.Response(404, json={"error": {"code": 404, "message": "Bookmark does not exist"}})
        self.signets[ns].remove(handle)
        return httpx.Response(200, content=b"")

    def _groupes(self, req):
        if (r := self._auth(req)) is not None:
            return r
        return httpx.Response(200, json=[{"surname": k, "group": v} for k, v in sorted(self.name_groups.items())])

    def _groupe(self, req, surname):
        if (r := self._auth(req)) is not None:
            return r
        surname = unquote(surname)
        return httpx.Response(200, json={"surname": surname, "group": self.name_groups.get(surname, surname)})

    def _poser_groupe(self, req, surname, group):
        """POST /name-groups/<patronyme>/<groupe> : ``set_name_group_mapping``, hors transaction (pas d'historique)."""
        if (r := self._auth(req)) is not None:
            return r
        if (r := self._droits(req, "EditNameGroup")) is not None:
            return r
        surname, group = unquote(surname), unquote(group)
        self.name_groups[surname] = group
        return httpx.Response(201, json={"surname": surname, "group": group})

    def _register_config(self, req):
        """Ajouté en API 3.26.0 ; sans authentification ; route absente avant."""
        if version_tuple(self.api_version) < (3, 26, 0):
            return httpx.Response(404, json={"code": 404, "status": "Not Found"})
        return httpx.Response(200, json={"enabled": self.inscription_libre})

    def _token(self, req):
        if (r := self._limite()) is not None:
            return r
        data = json.loads(req.content)
        if (data.get("username"), data.get("password")) != (self.user, self.password):
            return httpx.Response(403, json={"error": {"code": 403, "message": "Invalid username or password"}})
        self.logins += 1
        return httpx.Response(200, json={"access_token": self._jeton("A1"), "refresh_token": "R1"})

    # ------------------------------------------------------------------ privé (#264)
    def _voit_prive(self, req) -> bool:
        perms = jwt_payload(req.headers.get("Authorization", "").removeprefix("Bearer ")).get("permissions", [])
        return "ViewPrivate" in perms

    def _visible(self, cls: str, handle) -> bool:
        if cls == "Tag":
            return True
        o = self.objects.get(cls, {}).get(handle) if handle else None
        if o is None or o.get("private"):
            return False
        if cls == "Citation" and o.get("source_handle"):
            return self._visible("Source", o["source_handle"])
        return True

    _LISTES = {"note_list": "Note", "citation_list": "Citation", "family_list": "Family",
               "parent_family_list": "Family"}
    _REFS = {"event_ref_list": "Event", "child_ref_list": "Person", "person_ref_list": "Person",
             "media_list": "Media", "reporef_list": "Repository", "placeref_list": "Place"}
    _CHAMPS = {"father_handle": "Person", "mother_handle": "Person", "source_handle": "Source"}

    def _assainir(self, o):
        """Comme ``sanitize`` de gramps-web-api : sous-objets privés et références vers l'invisible retirés."""
        if isinstance(o, list):
            return [self._assainir(x) for x in o if not (isinstance(x, dict) and x.get("private"))]
        if not isinstance(o, dict):
            return o
        out = {}
        for k, v in o.items():
            if k in self._LISTES and isinstance(v, list):
                out[k] = [h for h in v if self._visible(self._LISTES[k], h)]
            elif k in self._CHAMPS:
                out[k] = v if not v or self._visible(self._CHAMPS[k], v) else None
            elif k in self._REFS and isinstance(v, list):
                out[k] = [self._assainir(x) for x in v if isinstance(x, dict) and not x.get("private")
                          and self._visible(self._REFS[k], x.get("ref"))]
            else:
                out[k] = self._assainir(v)
        if o.get("_class") == "Person" and (o.get("primary_name") or {}).get("private"):
            out["primary_name"] = {"_class": "Name", "first_name": "", "surname_list": [
                {"_class": "Surname", "surname": "Private", "primary": True}], "private": False}
        return out

    def _lisibles(self, req, cls: str) -> dict[str, dict]:
        objs = self.objects[cls]
        if self._voit_prive(req):
            return objs
        return {h: self._assainir(o) for h, o in objs.items() if self._visible(cls, h)}

    def _users(self, req):
        if (r := self._auth(req)) is not None:
            return r
        if (r := self._droits(req, "ViewOtherUser")) is not None:
            return r
        return httpx.Response(200, json=[{"name": c["name"], "email": "", "full_name": "", "role": c["role"]}
                                         for c in self.comptes])

    def _living(self, req, handle):
        if (r := self._auth(req)) is not None:
            return r
        params = dict(req.url.params)
        self.living_requetes.append((handle, params))
        if handle not in self._lisibles(req, "Person"):
            return httpx.Response(404, json={"code": 404, "status": "Not Found"})
        if params.get("max_age_probably_alive") == "100" and handle in self.vivants_100:
            return httpx.Response(200, json={"living": self.vivants_100[handle]})
        if handle in self.vivants:
            return httpx.Response(200, json={"living": self.vivants[handle]})
        p = self.objects["Person"][handle]
        return httpx.Response(200, json={"living": p.get("death_ref_index", -1) < 0})

    def _list(self, req, plural):
        if (r := self._auth(req)) is not None:
            return r
        objs = [simplify(o) for o in self._lisibles(req, PLURAL[plural]).values()]
        if (gid := req.url.params.get("gramps_id")) is not None:  # comme gramps-web-api : 404 si aucun objet
            objs = [o for o in objs if o.get("gramps_id") == gid]
            if not objs:
                return httpx.Response(404, json={"error": {"code": 404, "message": "Not found"}})
        keys = req.url.params.get("keys")
        if keys:
            ks = keys.split(",")
            objs = [{k: o[k] for k in ks if k in o} for o in objs]
        return httpx.Response(200, json=objs)

    def _get(self, req, plural, handle):
        if (r := self._auth(req)) is not None:
            return r
        o = self._lisibles(req, PLURAL[plural]).get(handle)
        if not o:
            return httpx.Response(404, json={})
        o = simplify(o)
        if keys := req.url.params.get("keys"):
            o = {k: o[k] for k in keys.split(",") if k in o}
        return httpx.Response(200, json=o)

    def _search(self, req):
        q = req.url.params.get("query", "").lower()
        hits = [{"object_type": "person", "handle": h, "object": simplify(p)}
                for h, p in self._lisibles(req, "Person").items()
                if q in json.dumps(p["primary_name"], ensure_ascii=False).lower()]
        return httpx.Response(200, json=hits)

    def _file(self, req, handle):
        """PUT /media/{handle}/file (Gramps Web 26.11) : If-Match, somme MD5, chemin attribué par le serveur."""
        import hashlib
        if (r := self._auth(req)) is not None:
            return r
        if (r := self._droits(req, "EditObject")) is not None:
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
        if (r := self._droits(req, "AddObject", "EditObject", "DeleteObject")) is not None:
            return r
        params = req.url.params
        if "message" in params and version_tuple(self.api_version) < (3, 13, 0):
            return httpx.Response(422, json={"code": 422, "errors": {"query": {"message": ["Unknown field."]}},
                                             "status": "Unprocessable Entity"})
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
                if it["_class"] == "Person" and it["handle"] == self.default_person:
                    self.default_person = ""  # comme gramps-web-api (tasks.py) : la référence supprimée est effacée
                new = None
            else:
                new = copy.deepcopy(it["new"])
                new["change"] = self.tick()
                if new["_class"] == "Media":
                    new.setdefault("thumb", None)  # comme gramps-web-api : stocké, renvoyé ici, absent des lectures
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
