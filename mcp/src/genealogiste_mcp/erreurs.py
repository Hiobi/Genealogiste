"""Erreurs lisibles par le modèle (#146) : toute exception d'outil ou d'initialisation devient
{erreur, cause, remede[, variable]} au lieu du message opaque « Error executing tool … » du SDK MCP."""

from __future__ import annotations

import os
import re

_VARIABLE = re.compile(r"\b(GENEALOGISTE_[A-Z0-9_]+|MCP_[A-Z_]+)=")
FATALES = {"configuration", "donnees_dans_le_plugin", "droits", "git_absent"}
VERIFIER = "Puis redémarrer le serveur MCP ; `make check` (ou `genealogiste-mcp --check`) vérifie la configuration."


def _url_gramps() -> str:
    return os.environ.get("GENEALOGISTE_GRAMPS_URL", "").rstrip("/")


def _vers_gramps(exc: BaseException) -> bool:
    import httpx

    if not isinstance(exc, httpx.HTTPError) or not _url_gramps():
        return False
    try:
        return str(exc.request.url).startswith(_url_gramps())
    except RuntimeError:  # requête non attachée à l'exception
        return False


def decrire(exc: BaseException, outil: str = "") -> dict:
    """Description structurée d'une exception, avec la cause probable et la commande ou le réglage à corriger."""
    from .gramps.client import GrampsError
    from .tree.store import GitError

    message = str(exc) or type(exc).__name__
    out: dict = {"erreur": message, "type": type(exc).__name__}
    if outil:
        out["outil"] = outil
    m = _VARIABLE.search(message)
    if isinstance(exc, ValueError) and m:
        out.update(cause="configuration", variable=m.group(1),
                   remede=f"Corriger {m.group(1)} (valeur attendue indiquée ci-dessus) dans le fichier .env du "
                          f"répertoire de données ou l'environnement du serveur. {VERIFIER}")
    elif isinstance(exc, GitError) and "dépôt du plugin" in message:
        out.update(cause="donnees_dans_le_plugin", variable="GENEALOGISTE_DATA_DIR",
                   remede="Définir GENEALOGISTE_DATA_DIR vers un répertoire privé hors du dépôt du plugin "
                          f"(ex. ~/.local/share/genealogiste). {VERIFIER}")
    elif isinstance(exc, FileNotFoundError) and (exc.filename == "git" or "'git'" in message):
        out.update(cause="git_absent",
                   remede="Installer git sur la machine du serveur (ex. `sudo apt install git`) et vérifier qu'il "
                          f"est dans le PATH du serveur MCP. {VERIFIER}")
    elif isinstance(exc, PermissionError) or (isinstance(exc, OSError) and exc.errno in (13, 30)):
        out.update(cause="droits", variable="GENEALOGISTE_DATA_DIR",
                   remede=f"Le serveur ne peut pas écrire {getattr(exc, 'filename', '') or 'dans ses répertoires'} : "
                          "donner les droits d'écriture à l'utilisateur du serveur ou choisir un autre "
                          f"GENEALOGISTE_DATA_DIR (ou GENEALOGISTE_CACHE, *_DIR). {VERIFIER}")
    elif isinstance(exc, GrampsError) or _vers_gramps(exc):
        out.update(cause="gramps_web",
                   remede="Gramps Web injoignable ou refusé : vérifier qu'il tourne, GENEALOGISTE_GRAMPS_URL, "
                          "GENEALOGISTE_GRAMPS_USER et GENEALOGISTE_GRAMPS_PASSWORD ; ou repasser en "
                          f"GENEALOGISTE_BACKEND=fichier. {VERIFIER}")
    elif isinstance(exc, GitError):
        out.update(cause="git", remede="Opération git du répertoire de données en échec : lire le message, "
                                       "vérifier `git status` dans GENEALOGISTE_DATA_DIR et le miroir distant.")
    else:
        out.update(cause="interne",
                   remede="Erreur inattendue du serveur : réessayer une fois ; si elle persiste, consulter le "
                          "journal du serveur MCP (stderr) et la signaler avec ce message.")
    return out


def fatale(desc: dict) -> bool:
    return desc.get("cause") in FATALES
