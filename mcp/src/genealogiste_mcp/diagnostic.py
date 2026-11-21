"""Diagnostic d'exploitation (#147) : contrôles « contrôle, état, détail, remède », sans aucun secret.

Utilisable même quand l'application ne s'initialise pas (configuration invalide) : les contrôles qui en
dépendent sont alors sautés et la cause est rapportée."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import erreurs, menage

GO = 1024**3
GUIDE = "https://github.com/Hiobi/Genealogiste/wiki/Serveur"  # installation et exploitation sur un serveur
ESPACE_MIN = 1 * GO
# Points d'entrée publics des sources interrogées par le plugin (une requête GET chacun).
SOURCES = {
    "matchid": "https://deces.matchid.io/deces/api/v1/version",
    "wikitree": "https://api.wikitree.com/api.php",
    "gallica": "https://gallica.bnf.fr/services/engine/search/sru?operation=explain",
    "wikidata": "https://query.wikidata.org/",
    "geo": "https://geo.api.gouv.fr/departements/59",
    "ad59": "https://archivesdepartementales.lenord.fr/",
}


def version_serveur() -> str:
    try:
        return metadata.version("genealogiste-mcp")
    except metadata.PackageNotFoundError:
        return "inconnue"


def ecart_version() -> str:
    """Avertissement si le serveur en cours n'a pas la version du plugin installé sur disque, sinon ''."""
    vs, (vp, chemin) = version_serveur(), version_plugin()
    if vp and vp != vs:
        return (f"Serveur MCP en version {vs}, plugin sur disque en {vp} ({chemin}) : reconnecter le serveur MCP "
                "(/mcp dans Claude Code, ou nouvelle session) pour charger la version installée.")
    return ""


def version_plugin() -> tuple[str, str]:
    """Version du plugin sur disque (CLAUDE_PLUGIN_ROOT, sinon le dépôt contenant ce paquet)."""
    racines = [os.environ.get("CLAUDE_PLUGIN_ROOT", ""), str(Path(__file__).resolve().parents[3])]
    for racine in filter(None, racines):
        for rel in (".claude-plugin/plugin.json", "plugin.json"):
            p = Path(racine) / rel
            try:
                return json.loads(p.read_text(encoding="utf-8")).get("version", ""), str(p)
            except (OSError, ValueError):
                continue
    return "", ""


def _url_sans_identifiants(url: str) -> str:
    if not url:
        return ""
    s = urlsplit(url)
    return urlunsplit((s.scheme, s.hostname + (f":{s.port}" if s.port else "") if s.hostname else "",
                       s.path, "", ""))


def _ctl(controle: str, etat: str, detail: str = "", remede: str = "", **extra) -> dict:
    out = {"controle": controle, "etat": etat, "detail": detail}
    if remede:
        out["remede"] = remede
    out.update(extra)
    return out


def _version_outil(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
        return (r.stdout or r.stderr).strip().splitlines()[0] if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def _taille_dossier(d: Path) -> int:
    total = 0
    if d.is_dir():
        for p in d.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                continue
    return total


def _inscriptible(d: Path) -> bool:
    d = Path(d)
    while not d.exists() and d != d.parent:
        d = d.parent
    return os.access(d, os.W_OK | os.X_OK)


ETATS_CONTACT = {"configure": "configuré", "rejete": "rejeté", "ignore": "ignoré"}
REMEDE_CONTACT = {
    "rejete": "Corriger GENEALOGISTE_CONTACT (adresse ou URL, 200 caractères ASCII au plus, sans parenthèse, "
              "point-virgule, barre oblique inverse ni retour à la ligne).",
    "ignore": "Retirer GENEALOGISTE_USER_AGENT pour que le contact soit ajouté au User-Agent par défaut, ou "
              "inclure le contact dans GENEALOGISTE_USER_AGENT.",
}


def controles_locaux(a, probleme: dict | None, config) -> list[dict]:
    out = []
    vs, (vp, chemin) = version_serveur(), version_plugin()
    if vp and vp != vs:
        out.append(_ctl("version", "attention", f"serveur {vs}, plugin sur disque {vp} ({chemin})",
                        "Le serveur en cours est d'une autre version que le plugin installé : redémarrer le "
                        "serveur MCP (/mcp dans Claude Code) ou mettre à jour le plugin.", serveur=vs, plugin=vp))
    else:
        out.append(_ctl("version", "ok", f"serveur {vs}" + (f", plugin {vp}" if vp else ""), serveur=vs))
    if probleme:
        out.append(_ctl("configuration", "erreur", probleme["erreur"], probleme["remede"],
                        cause=probleme["cause"]))
    elif config is not None:
        valeurs = {
            "backend": config.backend, "repertoire_donnees": str(config.data_dir),
            "cache": str(config.cache_path), "medias": str(config.media_dir), "hors_ligne": config.offline,
            "gramps_url": _url_sans_identifiants(config.gramps_url),
            "gramps_password": "défini" if config.gramps_password else "absent",
            "matchid_token": "défini" if config.matchid_token else "absent",
            "wikitree_app_id": "défini" if config.wikitree_app_id else "absent",
            "mcp_token": "défini" if os.environ.get("MCP_TOKEN") else "absent",
            # Contact du User-Agent (#211, lot D) : donnée personnelle, jamais affichée en clair.
            "contact_user_agent": ETATS_CONTACT.get(getattr(config, "etat_contact", "absent"), "absent"),
        }
        details, remedes = [], []
        if retirees := getattr(config, "variables_retirees", []):
            details.append(f"variable(s) retirée(s) ignorée(s) : {', '.join(retirees)}")
            remedes.append("Les retirer de l'environnement ou du .env : le budget d'enquête ne limite plus la durée "
                           "ni le coût estimé ; plafonner le coût réel côté client (--max-budget-usd).")
        etat_contact = getattr(config, "etat_contact", "absent")
        if etat_contact in ("rejete", "ignore"):
            details.append(f"GENEALOGISTE_CONTACT ignoré : {config.contact_motif}")
            remedes.append(REMEDE_CONTACT[etat_contact])
        out.append(_ctl("configuration", "attention", f"backend {config.backend} ; " + " ; ".join(details),
                        " ".join(remedes), valeurs=valeurs) if details
                   else _ctl("configuration", "ok", f"backend {config.backend}", valeurs=valeurs))
    git = _version_outil(["git", "--version"])
    out.append(_ctl("git", "ok", git) if git else _ctl(
        "git", "erreur", "git introuvable", "Installer git (ex. sudo apt install git) dans le PATH du serveur."))
    uv = _version_outil(["uv", "--version"])
    out.append(_ctl("uv", "ok", uv) if uv else _ctl(
        "uv", "attention", "uv introuvable dans le PATH du serveur",
        "Installer uv (https://docs.astral.sh/uv/) : le plugin le lance pour démarrer le serveur."))
    if config is None:
        return out
    dossiers = {"donnees": config.data_dir, "cache": Path(config.cache_path).parent, "medias": config.media_dir,
                "cache_images": config.cache_images_dir}
    refuses = [f"{n} ({d})" for n, d in dossiers.items() if not _inscriptible(d)]
    out.append(_ctl("droits", "erreur", "non inscriptibles : " + ", ".join(refuses),
                    "Donner l'écriture à l'utilisateur du serveur ou changer GENEALOGISTE_DATA_DIR / "
                    "GENEALOGISTE_CACHE / *_DIR.") if refuses else _ctl("droits", "ok", "répertoires inscriptibles"))
    try:
        libre = shutil.disk_usage(next(d for d in (config.data_dir, *config.data_dir.parents) if d.exists())).free
        out.append(_ctl("espace_disque", "ok", f"{libre / GO:.1f} Go libres") if libre >= ESPACE_MIN else _ctl(
            "espace_disque", "attention", f"{libre / GO:.2f} Go libres",
            "Libérer de l'espace ou abaisser GENEALOGISTE_CACHE_IMAGES_MAX_MO puis cache_purger()."))
    except (OSError, StopIteration):
        out.append(_ctl("espace_disque", "attention", "inconnu", "Vérifier le disque du répertoire de données."))
    sqlite_mo = (a.cache.taille() if a else 0) / menage.MO
    images_mo = _taille_dossier(config.cache_images_dir) / menage.MO
    trop = [n for n, v, cap in (("cache", sqlite_mo, config.cache_max_mo),
                                 ("cache-images", images_mo, config.cache_images_max_mo)) if cap and v > cap]
    out.append(_ctl("caches", "attention" if trop else "ok",
                    f"réponses {sqlite_mo:.1f} Mo / {config.cache_max_mo:g} ; images {images_mo:.1f} Mo / "
                    f"{config.cache_images_max_mo:g}", "cache_purger() applique les plafonds." if trop else ""))
    from . import pdf_markdown as pdf_md
    langues = pdf_md._tesseract_langues(config.tesseract)
    if langues is None:
        out.append(_ctl("ocr", "attention", "Tesseract absent : PDF scannés lus en image (plus de tokens)",
                        pdf_md.commande_installation(["fra"]).get("commande") or "voir docs/pieces.md"))
    else:
        manquantes = [x for x in ("fra", "lat") if x not in langues]
        out.append(_ctl("ocr", "attention" if manquantes else "ok",
                        "langues fra/lat présentes" if not manquantes else f"langues absentes : {', '.join(manquantes)}",
                        (pdf_md.commande_installation(manquantes).get("commande") or "") if manquantes else ""))
    from . import exploitation
    recentes = exploitation.dernieres_erreurs(config)
    out.append(_ctl("journal_exploitation", "attention" if recentes else "ok",
                    f"{exploitation.chemin_journal(config)} ({config.log_niveau}) ; "
                    f"{len(recentes)} erreur(s) récente(s)",
                    "Lire les dernières erreurs ci-dessous (outil, cause) ; corriger puis relancer l'outil concerné."
                    if recentes else "", dernieres_erreurs=recentes))
    if a is not None:
        out.append(_controle_debit(a))
        out.append(_controle_politique(a))
        from .tree.proposals import TTL_SECONDS
        expirees = a.tokens.expirees()  # lecture seule : le diagnostic ne modifie rien
        valides = [p for p in a.tokens._lire_tous() if p[1].get("jeton") not in expirees]
        out.append(_ctl("propositions", "attention" if expirees else "ok",
                        f"{len(valides)} en attente, {len(expirees)} expirée(s) (durée de vie "
                        f"{TTL_SECONDS // 60} min)",
                        "Les propositions expirées ne sont plus applicables : elles seront purgées au prochain "
                        "arbre_info ; reformuler celles à garder (arbre_proposer)." if expirees else ""))
    return out


def _controle_debit(a) -> dict:
    """Hôtes ralentis pour la journée après 429/502/503/504 (#211), partagés par tous les serveurs du cache."""
    jour = a.http.jour().isoformat()
    try:
        lents = a.cache.ralentissements(jour)
    except Exception as exc:  # noqa: BLE001
        return _ctl("debit", "attention", f"ralentissements illisibles : {exc}")
    details = {h: {**r, "intervalle": a.http.intervalle(h)} for h, r in lents.items()}
    if not details:
        return _ctl("debit", "ok", "aucun hôte ralenti aujourd'hui", ralentissements={})
    resume = ", ".join(f"{h} ({d['intervalle']:g} s, {d['incidents']} incident(s), dernier HTTP "
                       f"{d['dernier_statut']})" for h, d in details.items())
    return _ctl("debit", "attention", f"hôte(s) ralenti(s) jusqu'à minuit : {resume}",
                "Le service a signalé une surcharge (429/5xx) : le rythme est réduit pour la journée. "
                "cache_purger('ralentissement') rétablit le rythme normal si la cause est levée.",
                ralentissements=details)


def _controle_politique(a) -> dict:
    """Politique d'accès effective par service (#211) : intervalle, plafond/jour, concurrence, référence et
    provenance de chaque valeur (sourcée / historique / référentiel / environnement / défaut)."""
    pol = a.http.politique
    services = pol.table()
    try:
        consomme = a.cache.compteurs_jour(a.http.jour().isoformat())
    except Exception:  # noqa: BLE001
        consomme = {}
    for s in services:
        s["consomme_aujourd_hui"] = consomme.get(s["hote"], 0)
    resume = ", ".join(f"{s['hote']} ({s['intervalle']:g} s, {s['plafond_jour'] or 'sans'} plafond/j)"
                       for s in services)
    return _ctl("politique_acces", "ok", resume, services=services, defauts=pol.defauts(),
                consomme_aujourd_hui=consomme)


def controles_reseau(a) -> list[dict]:
    from .http import HttpClient, SourceError

    client = HttpClient(a.cache, a.config.user_agent, timeout=8.0, politique=a.http.politique,
                        offline=False, policy=a.http.policy,
                        max_retries=1, duree_max=15.0, echec_ttl=0, coupe_circuit_ttl=a.config.coupe_circuit,
                        sleeper=a.http.sleep, jour=a.http.jour, ralentissement_max=a.http.ralentissement_max)
    out = []
    try:
        for nom, url in SOURCES.items():
            debut = time.monotonic()
            try:
                client.get(url, parse="text", use_cache=False, ttl=0, source="diagnostic")
                ctl = _ctl(f"source:{nom}", "ok", f"{urlsplit(url).hostname} joignable", verdict="joignable")
            except SourceError as exc:
                if exc.bloque_antirobot or exc.coupe_circuit:
                    ctl = _ctl(f"source:{nom}", "attention", str(exc),
                               "Protection anti-robot sur cette adresse : consultation par l'utilisateur depuis son poste ; "
                               "aucun contournement n'est tenté.", verdict="protection")
                elif exc.status and exc.status < 500 and exc.status not in (401, 403):
                    ctl = _ctl(f"source:{nom}", "ok", f"{urlsplit(url).hostname} répond (HTTP {exc.status})",
                               verdict="joignable")
                else:
                    ctl = _ctl(f"source:{nom}", "attention", str(exc),
                               "Service indisponible ou réseau sortant bloqué : réessayer plus tard, vérifier le "
                               "pare-feu / proxy du serveur.", verdict="injoignable")
            ctl["duree_ms"] = round((time.monotonic() - debut) * 1000)
            out.append(ctl)
    finally:
        client.client.close()
    a.journal.add(source="diagnostic", operation="joignabilite", parametres={"sources": list(SOURCES)},
                  statut="positif" if all(c["verdict"] == "joignable" for c in out) else "negatif",
                  nb_resultats=len(out), resume="; ".join(f"{c['controle']}={c['verdict']}" for c in out),
                  references=list(SOURCES.values()))
    if a.config.gramps_url:
        out += controles_gramps(a)
    return out


def _controle_gramps(a) -> dict:
    try:
        a.gramps().search("diagnostic", 1)
        return _ctl("gramps_web", "ok", f"{_url_sans_identifiants(a.config.gramps_url)} joignable")
    except Exception as exc:  # noqa: BLE001
        d = erreurs.decrire(exc)
        return _ctl("gramps_web", "erreur" if a.config.backend == "gramps" else "attention", d["erreur"], d["remede"])


def controles_gramps(a) -> list[dict]:
    """Joignabilité, puis version de l'API, rôle du compte et réglages lisibles sans droit Admin (#265).

    Chaque contrôle échoue seul : un `/api/metadata/` ou `/api/users/-/` en panne donne un contrôle `attention` avec
    le motif, sans empêcher les autres. Ni identifiant, ni jeton, ni nom de personne dans la sortie."""
    out = [_controle_gramps(a)]
    gramps_actif = a.config.backend == "gramps"
    meta, injoignable = None, False
    try:
        meta = a.gramps().request("GET", "/metadata/")
        if meta.status_code >= 400:
            raise RuntimeError(f"HTTP {meta.status_code}")
        meta = meta.json()
        if not isinstance(meta, dict):
            raise ValueError("réponse inattendue")
    except Exception as exc:  # noqa: BLE001
        meta, injoignable = None, "injoignable" in str(exc)
        out.append(_ctl("gramps_version", "attention", f"version de l'API illisible : {_motif(exc)}",
                        "Gramps Web ne renseigne pas /api/metadata/ : vérifier que le compte peut se connecter "
                        "(GENEALOGISTE_GRAMPS_USER / _PASSWORD) puis relancer le diagnostic."))
        out.append(_ctl("gramps_reglages", "attention", f"réglages illisibles : {_motif(exc)}",
                        "Relancer le diagnostic une fois /api/metadata/ rétabli."))
    if meta is not None:
        out.append(_controle_version_gramps(meta, gramps_actif))
    if injoignable:  # inutile de rejouer trois essais et leurs attentes pour chaque contrôle
        out.append(_ctl("gramps_role", "attention", "rôle non vérifié : Gramps Web injoignable",
                        "Rétablir l'accès à Gramps Web puis relancer le diagnostic."))
    else:
        out.append(_controle_role_gramps(a, gramps_actif))
    if meta is not None:
        out.append(_controle_reglages_gramps(a, meta))
    return out


def _motif(exc: BaseException) -> str:
    return (str(exc) or type(exc).__name__)[:200]


def _controle_version_gramps(meta: dict, gramps_actif: bool) -> dict:
    from .gramps import compatibilite as cp

    api = str((meta.get("gramps_webapi") or {}).get("version") or "")
    gramps = str((meta.get("gramps") or {}).get("version") or "")
    plage = f"{cp.texte_version(cp.API_TESTEE_MIN)} à {cp.texte_version(cp.API_TESTEE_MAX)}"
    verdict = cp.verdict_api(api)
    v = cp.version_api(api)
    conditionnelles = {n: m for n, m in cp.FONCTIONS_API.items() if m > cp.API_TESTEE_MIN}
    dispo = sorted(n for n, m in conditionnelles.items() if v and v >= m)
    absentes = sorted((n for n, m in conditionnelles.items() if v and v < m), key=lambda n: conditionnelles[n])
    fonctions = {n: bool(v and v >= m) for n, m in conditionnelles.items()} if v else {}
    detail = f"API {api or 'inconnue'}, Gramps {gramps or 'inconnu'} ; plage testée {plage}"
    if v:
        detail += f" ; fonctions optionnelles disponibles : {', '.join(dispo) or 'aucune'}"
        if absentes:
            detail += f" ; absentes (API plus ancienne) : {', '.join(absentes)}"
    extra = {"api": api, "gramps": gramps, "verdict": verdict, "plage_testee": plage, "fonctions": fonctions}
    if verdict == "testee":
        return _ctl("gramps_version", "ok", detail, **extra)
    if verdict == "trop_ancienne":
        return _ctl("gramps_version", "erreur" if gramps_actif else "attention", detail,
                    f"API {api} sous la plage testée : le paramètre « message » des transactions est refusé (HTTP 422), "
                    f"aucune écriture n'est possible. Mettre à jour Gramps Web (API {cp.texte_version(cp.API_TESTEE_MIN)} "
                    "au moins ; docs/gramps-web.md, « Compatibilité des versions »).", **extra)
    if verdict == "plus_recente":
        return _ctl("gramps_version", "attention", detail,
                    f"API {api} plus récente que la plage testée ({plage}) : lectures et écritures probablement "
                    "compatibles, non vérifiées. Contrôler le diff d'une première proposition avant de l'appliquer ; "
                    "signaler tout écart.", **extra)
    return _ctl("gramps_version", "attention", detail,
                "Version de l'API non reconnue dans /api/metadata/ : compatibilité non vérifiable ; "
                "docs/gramps-web.md, « Compatibilité des versions ».", **extra)


def _controle_role_gramps(a, gramps_actif: bool) -> dict:
    from .gramps.client import ROLE_ECRITURE, nom_role

    try:
        role = a.gramps().role()
    except Exception as exc:  # noqa: BLE001
        return _ctl("gramps_role", "attention", f"rôle du compte illisible : {_motif(exc)}",
                    "Vérifier que le compte peut se connecter puis relancer le diagnostic ; le rôle requis pour "
                    "écrire est Editor.")
    if role is None:
        return _ctl("gramps_role", "attention", "rôle du compte non renseigné par le serveur",
                    "Rôle non vérifiable : s'assurer que le compte dédié est Editor (docs/gramps-web.md).")
    nom = nom_role(role)
    if role < ROLE_ECRITURE:
        return _ctl("gramps_role", "erreur" if gramps_actif else "attention",
                    f"rôle {nom} ({role}) : lecture seule pour Genealogiste, aucune écriture possible",
                    "Donner au compte dédié le rôle Editor dans Gramps Web (Paramètres, Administration, Gérer les "
                    "utilisateurs), puis relancer le diagnostic.", role=role, role_nom=nom, ecriture=False)
    if role > ROLE_ECRITURE:
        return _ctl("gramps_role", "attention",
                    f"rôle {nom} ({role}) : l'écriture est possible, mais le rôle dépasse le besoin",
                    "Déconseillé : préférer un compte Editor (un compte Owner ou Admin gère aussi les utilisateurs, "
                    "les sauvegardes et les réglages ; la fuite des identifiants serait plus grave).",
                    role=role, role_nom=nom, ecriture=True)
    return _ctl("gramps_role", "ok", f"rôle {nom} ({role}) : écriture possible, privilège minimal",
                role=role, role_nom=nom, ecriture=True)


def _controle_reglages_gramps(a, meta: dict) -> dict:
    """Réglages lisibles sans droit Admin (`/api/config/` leur est réservé : jamais appelé)."""
    from .gramps import compatibilite as cp

    serveur = meta.get("server") or {}
    file_taches = serveur.get("task_queue")
    multi = serveur.get("multi_tree")
    v = cp.version_api(str((meta.get("gramps_webapi") or {}).get("version") or ""))
    inscription: bool | None = None
    if v and v >= cp.FONCTIONS_API["inscription_libre"]:
        try:
            tree = a.gramps().tree_id if multi else ""
            r = a.gramps().request("GET", "/register/config/", params={"tree": tree} if tree else None)
            if r.status_code == 200 and isinstance((d := r.json()), dict) and isinstance(d.get("enabled"), bool):
                inscription = d["enabled"]
        except Exception:  # noqa: BLE001
            inscription = None
    if v is None or v < cp.FONCTIONS_API["inscription_libre"]:
        texte_inscription = "non vérifiable sur cette version (API < 3.26.0)"
    elif inscription is None:
        texte_inscription = "illisible"
    else:
        texte_inscription = "ouverte" if inscription else "fermée"
    def oui_non(b):
        return "inconnu" if b is None else "oui" if b else "non"
    detail = (f"file de tâches : {oui_non(file_taches)} ; multi-arbres : {oui_non(multi)} ; "
              f"inscription libre : {texte_inscription}")
    valeurs = {"file_de_taches": file_taches, "multi_arbres": multi, "inscription_libre": inscription}
    if inscription:
        return _ctl("gramps_reglages", "attention", detail,
                    "L'inscription libre est ouverte : toute personne atteignant l'instance peut demander un compte. "
                    "La fermer (REGISTRATION_DISABLED=True) si l'instance n'est pas publique.", valeurs=valeurs)
    note = "" if file_taches else (
        "Sans file de tâches, les grosses transactions s'exécutent dans la requête (délai plus long, pas d'échec).")
    return _ctl("gramps_reglages", "ok", detail + (f" ({note})" if note else ""), valeurs=valeurs)


def executer(app_ou_exc, probleme: dict | None, reseau: bool = True) -> dict:
    a = app_ou_exc if not isinstance(app_ou_exc, BaseException) else None
    if a is None and isinstance(app_ou_exc, BaseException) and not probleme:
        probleme = erreurs.decrire(app_ou_exc)
    controles = controles_locaux(a, probleme, a.config if a else None)
    if reseau and a is not None and not a.config.offline:
        controles += controles_reseau(a)
    etats = {c["etat"] for c in controles}
    etat = "erreur" if "erreur" in etats else "attention" if "attention" in etats else "ok"
    return {"etat": etat, "version": version_serveur(), "guide": GUIDE, "controles": controles,
            "a_corriger": [f"{c['controle']} : {c['remede']}" for c in controles if c["etat"] != "ok"]}
