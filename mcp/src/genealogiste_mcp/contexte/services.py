"""Référentiel des services publics de contexte historique (referentiels/sources_contexte.json, #285).

Historiographie, bibliothèques, presse, cartes, statistiques : distincts des services d'archives (archives.py) et
des sites tiers de généalogie (sites_tiers.py). Aucun accès réseau ici : le module dit quels services existent,
lesquels sont activés et si un service est **interrogeable** ; les outils de contexte (#286 à #289) appellent
``refus(code, config)`` avant toute requête et n'émettent rien quand il renvoie un motif.

Règles :

- mode ``lien_seulement`` : jamais interrogé comme service de contexte (protection relevée, pas d'API qualifiée) ;
  lien pour l'utilisateur. Seule exception nommée (``INTERROGE_HORS_REFERENTIEL``) : Gallica, que ``presse_recherche``
  interroge par le client Gallica existant, sans passer par ``refus`` ;
- activation : ``GENEALOGISTE_CONTEXTE_SERVICES`` (défaut : services ``api`` sans clé requise et sans protection) ;
- clé requise absente : aucune requête, le motif nomme la variable (jamais sa valeur) ;
- hôtes : seuls ceux du référentiel sont interrogés (``url_autorisee``) ; chacun est déclaré dans la politique
  d'accès (``entrees_politique``) avec l'intervalle et le plafond journalier par défaut ;
- clés : lues par ``cle()`` pour l'appel seulement ; jamais journalisées, écrites ni renvoyées par un outil
  (``masquer_cles`` pour toute URL ou tout message qui pourrait en contenir).

Format et règles : docs/contexte-historique.md, « Services de contexte ».
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, quote_plus, urlsplit

from .modeles import NATURES

PATH = Path(__file__).resolve().parents[1] / "referentiels" / "sources_contexte.json"

MODES = ("api", "lien_seulement")
PROTOCOLES_API = ("rest", "sru", "oai-pmh", "sparql", "solr", "wmts")
PROTOCOLES = (*PROTOCOLES_API, "aucun")  # « aucun » : pas d'API qualifiée (lien seulement)
CLES = ("aucune", "facultative", "requise")
PROTECTIONS = ("aucune", "cloudflare", "captcha", "connexion", "a_qualifier")
ZONES = ("FR", "EU", "US", "INT")
CHAMPS = ("code", "nom", "mode", "protocole", "url_api", "site", "documentation", "cle", "variable_cle", "nature",
          "couverture", "usage", "cgu", "quota", "protection", "site_repond_le", "verifie_le", "origine")
# Variables des clés d'API (config.cles_contexte) : jamais affichées, journalisées ni écrites.
VARIABLES_CLE = {"EUROPEANA": "GENEALOGISTE_CLE_EUROPEANA", "OPENALEX": "GENEALOGISTE_CLE_OPENALEX",
                 "NARA": "GENEALOGISTE_CLE_NARA", "APE": "GENEALOGISTE_CLE_APE"}
VARIABLE_SERVICES = "GENEALOGISTE_CONTEXTE_SERVICES"
VARIABLE_MAILTO = "GENEALOGISTE_CROSSREF_MAILTO"
MASQUE = "***"
CATEGORIE_POLITIQUE = "contexte"
# Comment obtenir la clé personnelle d'un service (ajouté au motif « clé requise absente ») ; démarche relevée sur
# la documentation du service (docs/contexte-historique.md, « Clé personnelle Europeana »). Pas d'URL ici.
OBTENIR_CLE = {"EUROPEANA": "clé personnelle gratuite, à demander depuis son compte europeana.eu : menu du compte, "
                            "« Manage API keys », « Request a Personal API key » "
                            "(docs/contexte-historique.md, « Clé personnelle Europeana »)"}

AVERTISSEMENT = ("Service de contexte : situe un individu, ne prouve rien sur lui. Citer la référence consultée "
                 "(jamais de mémoire) ; Wikipédia est tertiaire, Wikidata un index.")


@lru_cache(maxsize=1)
def services() -> tuple[dict, ...]:
    return tuple(json.loads(PATH.read_text(encoding="utf-8"))["services"])


def par_code(code: str) -> dict | None:
    c = (code or "").strip().upper()
    return next((s for s in services() if s["code"] == c), None)


def codes() -> tuple[str, ...]:
    return tuple(s["code"] for s in services())


def _url_https(u: str) -> bool:
    p = urlsplit(u or "")
    return p.scheme == "https" and bool(p.hostname)


def _periode_valide(p) -> bool:
    if not isinstance(p, dict) or not p or set(p) - {"de", "a"}:
        return False
    if any(not isinstance(v, int) or isinstance(v, bool) for v in p.values()):
        return False
    return p.get("de", 0) <= p.get("a", 9999)


def validate() -> list[str]:
    """Problèmes de format du référentiel (tests et make verifier-archives)."""
    errs, seen = [], set()
    for s in services():
        c = s.get("code", "")
        if not c or c in seen or c != c.upper():
            errs.append(f"{c!r} : code manquant, en double ou pas en majuscules")
        seen.add(c)
        for champ in CHAMPS:
            if champ not in s:
                errs.append(f"{c} : champ {champ} manquant")
        if not s.get("nom"):
            errs.append(f"{c} : nom vide")
        mode, proto = s.get("mode"), s.get("protocole")
        if mode not in MODES:
            errs.append(f"{c} : mode {mode!r} (valeurs : {', '.join(MODES)})")
        if proto not in PROTOCOLES:
            errs.append(f"{c} : protocole {proto!r} (valeurs : {', '.join(PROTOCOLES)})")
        for champ in ("url_api", "site", "documentation", "cgu"):
            if s.get(champ) and not _url_https(s[champ]):
                errs.append(f"{c} : {champ} = URL https attendue (ou vide)")
        if mode == "api":
            if not s.get("url_api"):
                errs.append(f"{c} : url_api obligatoire en mode api")
            if proto not in PROTOCOLES_API:
                errs.append(f"{c} : protocole d'API attendu en mode api")
            if s.get("protection") != "aucune":
                errs.append(f"{c} : service protégé en mode api (lien_seulement attendu, aucun contournement)")
        elif mode == "lien_seulement" and not (s.get("site") or s.get("url_api")):
            errs.append(f"{c} : site ou url_api attendu pour un lien")
        if sonde := s.get("url_sonde"):  # URL de sondage : même hôte que le point d'accès, sans donnée personnelle
            base = s.get("url_api") or s.get("site") or ""
            if not _url_https(sonde) or urlsplit(sonde).hostname != urlsplit(base).hostname:
                errs.append(f"{c} : url_sonde = URL https sur l'hôte du point d'accès")
        if s.get("url_api") and proto == "aucun":
            errs.append(f"{c} : protocole « aucun » avec une url_api")
        cle, var = s.get("cle"), s.get("variable_cle")
        if cle not in CLES:
            errs.append(f"{c} : cle {cle!r} (valeurs : {', '.join(CLES)})")
        elif cle == "aucune" and var:
            errs.append(f"{c} : variable_cle sans clé")
        elif cle != "aucune" and var != VARIABLES_CLE.get(c):
            errs.append(f"{c} : variable_cle {var!r} (attendue : {VARIABLES_CLE.get(c, 'à déclarer dans VARIABLES_CLE')})")
        if s.get("nature") not in NATURES:
            errs.append(f"{c} : nature {s.get('nature')!r} (valeurs : {', '.join(NATURES)})")
        if s.get("protection") not in PROTECTIONS:
            errs.append(f"{c} : protection {s.get('protection')!r} (valeurs : {', '.join(PROTECTIONS)})")
        couv = s.get("couverture")
        zone = couv.get("zone") if isinstance(couv, dict) else None
        if not isinstance(couv, dict) or set(couv) - {"zone", "periode"} or not isinstance(zone, list) or not zone \
                or any(z not in ZONES for z in zone):
            errs.append(f"{c} : couverture = {{zone: [{', '.join(ZONES)}], periode?}}")
        elif "periode" in couv and not _periode_valide(couv["periode"]):
            errs.append(f"{c} : couverture.periode = {{de, a}} en années entières")
        for champ in ("verifie_le", "site_repond_le"):
            if s.get(champ):
                try:
                    date.fromisoformat(s[champ])
                except ValueError:
                    errs.append(f"{c} : {champ} {s[champ]!r} n'est pas une date ISO")
        if not s.get("origine"):
            errs.append(f"{c} : origine vide")
    return errs


def url_de_sondage(s: dict) -> str:
    """URL sondée par make verifier-archives : url_sonde (requête minimale sans donnée personnelle), sinon le point
    d'accès, sinon le site."""
    return s.get("url_sonde") or s.get("url_api") or s.get("site") or ""


def hotes(s: dict) -> tuple[str, ...]:
    """Hôtes que le service peut interroger : celui de url_api (aucun pour un service sans API)."""
    h = urlsplit(s.get("url_api") or "").hostname
    return (h.lower(),) if h else ()


def tous_les_hotes() -> dict[str, str]:
    """Hôte -> code du service, pour tous les points d'accès déclarés."""
    return {h: s["code"] for s in services() for h in hotes(s)}


def url_autorisee(code: str, url: str) -> bool:
    """Vrai si l'URL vise un hôte déclaré pour ce service (aucun hôte hors référentiel n'est interrogé)."""
    s = par_code(code)
    h = (urlsplit(url or "").hostname or "").lower()
    return bool(s and h and urlsplit(url).scheme == "https" and h in hotes(s))


def actif_par_defaut(s: dict) -> bool:
    return s["mode"] == "api" and s["cle"] != "requise" and s["protection"] == "aucune"


def actifs_par_defaut() -> tuple[str, ...]:
    return tuple(s["code"] for s in services() if actif_par_defaut(s))


def parser_services(valeur: str | None) -> tuple[str, ...] | None:
    """GENEALOGISTE_CONTEXTE_SERVICES -> codes activés. Absente ou vide : None (défaut du référentiel) ;
    « aucun » : aucun service ; liste de codes séparés par des virgules, « defaut » y ajoute les services par
    défaut (ex. « defaut,EUROPEANA »). Code inconnu : ValueError."""
    v = (valeur or "").strip()
    if not v:
        return None
    if v.lower() == "aucun":
        return ()
    out: list[str] = []
    inconnus = []
    for item in v.split(","):
        c = item.strip().upper()
        if not c:
            continue
        if c in ("DEFAUT", "DÉFAUT"):
            out += actifs_par_defaut()
        elif par_code(c):
            out.append(c)
        else:
            inconnus.append(item.strip())
    if inconnus:
        raise ValueError(f"{VARIABLE_SERVICES}={v!r} : service(s) inconnu(s) {', '.join(inconnus)} ; valeurs possibles : "
                         f"aucun, defaut, {', '.join(codes())}")
    return tuple(dict.fromkeys(out))


def parser_mailto(valeur: str | None) -> str:
    """GENEALOGISTE_CROSSREF_MAILTO : vide par défaut ; une adresse courriel est une donnée personnelle, envoyée à
    Crossref seulement si l'utilisateur la renseigne. Le message d'erreur ne reprend jamais la valeur."""
    v = (valeur or "").strip()
    if not v:
        return ""
    local, at, domaine = v.partition("@")
    if (not at or not local or "." not in domaine or len(v) > 200 or not v.isascii()
            or any(ch.isspace() or ord(ch) < 0x20 or ch in "<>()[],;:\\\"'&?=#/" for ch in v)):
        raise ValueError(f"{VARIABLE_MAILTO}=<valeur masquée> : adresse courriel attendue (ex. prenom.nom@exemple.fr) ou vide")
    return v


def cles_depuis_env(env) -> dict[str, str]:
    """Clés d'API présentes dans l'environnement : code -> valeur (absente ou vide : non retenue)."""
    return {code: env(var).strip() for code, var in VARIABLES_CLE.items() if (env(var) or "").strip()}


def actifs(config) -> tuple[str, ...]:
    choisis = getattr(config, "contexte_services", None)
    return actifs_par_defaut() if choisis is None else tuple(choisis)


def cle(code: str, config) -> str:
    """Valeur de la clé d'API du service, pour l'appel seulement : ne jamais la journaliser, l'écrire ni la
    renvoyer (``masquer_cles`` sur toute URL ou tout message)."""
    return (getattr(config, "cles_contexte", None) or {}).get((code or "").strip().upper(), "")


def mailto(config) -> str:
    """Adresse mailto de Crossref, vide sauf choix explicite de l'utilisateur."""
    return getattr(config, "crossref_mailto", "") or ""


def masquer_cles(texte: str, config) -> str:
    """Texte (URL, message d'erreur) dont toute clé d'API et l'adresse mailto sont remplacées par ``***``, sous
    leur forme brute comme encodée dans une URL (``%40``, minuscules comprises)."""
    out = texte or ""
    secrets = [*(getattr(config, "cles_contexte", None) or {}).values(), mailto(config)]
    formes = {f for x in secrets if x for f in (x, quote(x, safe=""), quote_plus(x, safe=""))}  # brute et encodée
    for v in sorted(formes, key=len, reverse=True):
        out = re.sub(re.escape(v), MASQUE, out, flags=re.I) if "%" in v else out.replace(v, MASQUE)
    return out


@dataclass(frozen=True)
class EtatService:
    """État d'un service pour la configuration courante. ``cle`` : sans_objet | presente | absente (jamais la
    valeur). ``motif`` est vide si le service est interrogeable."""

    code: str
    interrogeable: bool
    motif: str
    actif: bool
    mode: str
    cle: str
    variable_cle: str = ""

    def en_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v != ""}


# Service en lien seulement qu'un outil interroge pourtant par un client antérieur au référentiel, sans passer par
# ``refus`` (#288, #323) : le motif de refus le dit, pour ne pas affirmer « jamais interrogé par le plugin ». La
# décision ne change pas : ``refus`` refuse toujours ce service aux outils de contexte.
INTERROGE_HORS_REFERENTIEL = {"GALLICA": "presse_recherche"}


def etat(code: str, config) -> EtatService:
    """Le service peut-il être interrogé maintenant ? Ordre des motifs : inconnu, lien seulement, protection,
    désactivé, clé requise absente, hors ligne."""
    s = par_code(code)
    if s is None:
        return EtatService((code or "").strip().upper(), False,
                           f"service de contexte inconnu : {code!r} (sources_catalogue(type=\"contexte\"))",
                           False, "", "sans_objet")
    c = s["code"]
    est_actif = c in actifs(config)
    etat_cle = "sans_objet" if s["cle"] == "aucune" else ("presente" if cle(c, config) else "absente")
    motif = ""
    if s["mode"] == "lien_seulement":
        hors = INTERROGE_HORS_REFERENTIEL.get(c)
        portee = (f"non interrogé comme service de contexte ; seul {hors} l'interroge, par son client existant"
                  if hors else "jamais interrogé par le plugin")
        motif = (f"{s['nom']} : {portee} (mode lien_seulement). "
                 f"{s.get('notes') or 'Accès machine non qualifié.'} "
                 f"À consulter par l'utilisateur : {s.get('site') or s.get('url_api')}")
    elif s["protection"] != "aucune":
        motif = f"{s['nom']} : protection relevée ({s['protection']}) ; aucun contournement"
    elif not est_actif:
        motif = (f"{s['nom']} : service désactivé ; l'ajouter à {VARIABLE_SERVICES} "
                 "(<données>/.env) pour l'interroger")
    elif s["cle"] == "requise" and etat_cle == "absente":
        motif = f"{s['nom']} : clé d'API requise absente ; définir {s['variable_cle']} (<données>/.env)"
        if c in OBTENIR_CLE:
            motif += f" ; {OBTENIR_CLE[c]}"
    elif getattr(config, "offline", False):
        motif = f"{s['nom']} : mode hors ligne (GENEALOGISTE_OFFLINE) ; aucune requête émise"
    return EtatService(c, not motif, motif, est_actif, s["mode"], etat_cle, s["variable_cle"])


def refus(code: str, config) -> dict | None:
    """None si le service est interrogeable ; sinon la réponse à rendre telle quelle, sans émettre de requête."""
    e = etat(code, config)
    if e.interrogeable:
        return None
    return {"service": e.code, "interrogeable": False, "erreur": e.motif, "requetes_emises": 0,
            "consigne": "Aucune requête n'a été émise vers ce service. Contexte non documenté par ce service."}


def resume(s: dict, config=None) -> dict:
    """Entrée du catalogue (jamais de clé) ; avec la configuration, l'état d'activation."""
    keys = ("code", "nom", "mode", "protocole", "url_api", "url_sonde", "site", "documentation", "cle", "variable_cle", "nature",
            "couverture", "usage", "cgu", "quota", "protection", "site_repond_le", "verifie_le", "origine", "releve",
            "notes")
    out = {k: s[k] for k in keys if s.get(k) not in (None, "", [], {})}
    if config is not None:
        e = etat(s["code"], config)
        out["actif"], out["interrogeable"] = e.actif, e.interrogeable
        if e.cle != "sans_objet":
            out["etat_cle"] = e.cle
        if e.motif:
            out["motif"] = e.motif
    return out


def filtrer(nature: str = "", protocole: str = "", mode: str = "") -> list[dict]:
    return [s for s in services() if (not nature or s["nature"] == nature)
            and (not protocole or s["protocole"] == protocole) and (not mode or s["mode"] == mode)]


def description(config) -> dict:
    """Synthèse pour le diagnostic : services actifs, interrogeables, état des clés (présente/absente)."""
    etats = [etat(c, config) for c in codes()]
    cles = {var: ("définie" if cle(code, config) else "absente") for code, var in VARIABLES_CLE.items()}
    return {"actifs": [e.code for e in etats if e.actif],
            "interrogeables": [e.code for e in etats if e.interrogeable],
            "non_interrogeables": {e.code: e.motif for e in etats if not e.interrogeable},
            "cles": cles,
            "crossref_mailto": "défini" if mailto(config) else "absent",
            "selection": "défaut du référentiel" if getattr(config, "contexte_services", None) is None
            else VARIABLE_SERVICES,
            "cles_sans_activation": [code for code in VARIABLES_CLE
                                     if cle(code, config) and code not in actifs(config)]}


def entrees_politique() -> dict:
    """Entrées de la politique d'accès (politique_acces.Entree) pour chaque hôte du référentiel : intervalle et
    plafond journalier par défaut (GENEALOGISTE_DEBIT_DEFAUT, GENEALOGISTE_PLAFOND_JOUR_DEFAUT), surchargeables
    par GENEALOGISTE_DEBITS / GENEALOGISTE_PLAFONDS_JOUR. Aucune limite publiée n'a été relevée : aucune valeur
    « sourcee »."""
    from ..politique_acces import Entree

    out = {}
    for s in services():
        for h in hotes(s):
            out.setdefault(h, Entree(f"{s['nom']} (contexte)", categorie=CATEGORIE_POLITIQUE))
    return out
