"""Configuration : variables d'environnement GENEALOGISTE_* (+ fichier .env optionnel)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_env_file(path: Path) -> None:
    """Charge un fichier .env simple (CLE=valeur) sans écraser l'environnement existant."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


@dataclass
class Config:
    data_dir: Path
    cache_path: Path
    wikitree_app_id: str = ""
    matchid_token: str = ""
    user_agent: str = "genealogiste-mcp/0.1 (plugin Claude Code; usage genealogique personnel)"
    backend: str = "fichier"  # fichier (GEDCOM 7 + Git, défaut) | gramps (Gramps Web = source de vérité)
    gramps_url: str = ""
    gramps_user: str = ""
    gramps_password: str = ""
    gramps_ttl: float = 30.0  # secondes entre deux rafraîchissements en lecture (mode gramps)
    git_mirror: bool = False  # mode gramps : miroir GEDCOM 7 versionné de l'arbre Gramps
    git_remote: str = ""  # dépôt distant optionnel (privé !) du répertoire de données
    fs_user: str = ""
    fs_password: str = ""
    strict_evidence: bool = False
    exiger_source: bool = True  # règle de métier : pas de fait sans source sauf motif explicite
    cog_mvt_url: str = "https://www.insee.fr/fr/statistiques/fichier/7766585/v_mvt_commune_2024.csv"
    cog_communes_url: str = "https://www.insee.fr/fr/statistiques/fichier/7766585/v_commune_depuis_1943.csv"
    http_timeout: float = 30.0
    offline: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def tree_path(self) -> Path:
        return self.data_dir / "arbre.ged"

    @property
    def journal_path(self) -> Path:
        return self.data_dir / "journal.jsonl"

    @property
    def proposals_dir(self) -> Path:
        return self.data_dir / ".propositions"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "medias"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"


BACKENDS = {"fichier": "fichier", "file": "fichier", "gedcom": "fichier", "": "fichier",
            "gramps": "gramps", "grampsweb": "gramps", "gramps-web": "gramps"}


def backend_name(value: str) -> str:
    v = (value or "").strip().lower()
    if v not in BACKENDS:
        raise ValueError(f"GENEALOGISTE_BACKEND={value!r} : valeurs possibles fichier | gramps")
    return BACKENDS[v]


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "oui", "yes", "on")


def load_config() -> Config:
    env_file = os.environ.get("GENEALOGISTE_ENV_FILE")
    if env_file:
        _load_env_file(Path(env_file).expanduser())
    data_dir = Path(
        os.environ.get("GENEALOGISTE_DATA_DIR") or _xdg("XDG_DATA_HOME", ".local/share") / "genealogiste"
    ).expanduser()
    _load_env_file(data_dir / ".env")
    cache = Path(
        os.environ.get("GENEALOGISTE_CACHE")
        or _xdg("XDG_CACHE_HOME", ".cache") / "genealogiste" / "cache.sqlite"
    ).expanduser()
    env = os.environ.get
    cfg = Config(
        data_dir=data_dir,
        cache_path=cache,
        wikitree_app_id=env("GENEALOGISTE_WIKITREE_APPID", ""),
        matchid_token=env("GENEALOGISTE_MATCHID_TOKEN", ""),
        backend=backend_name(env("GENEALOGISTE_BACKEND", "fichier")),
        gramps_url=env("GENEALOGISTE_GRAMPS_URL", "").rstrip("/"),
        gramps_user=env("GENEALOGISTE_GRAMPS_USER", ""),
        gramps_password=env("GENEALOGISTE_GRAMPS_PASSWORD", ""),
        gramps_ttl=float(env("GENEALOGISTE_GRAMPS_TTL", "30") or 30),
        git_mirror=_bool(env("GENEALOGISTE_GIT_MIRROR"), False),
        git_remote=env("GENEALOGISTE_GIT_REMOTE", ""),
        fs_user=env("GENEALOGISTE_FS_USER", ""),
        fs_password=env("GENEALOGISTE_FS_PASSWORD", ""),
        strict_evidence=env("GENEALOGISTE_STRICT", "0") in ("1", "true", "oui"),
        exiger_source=env("GENEALOGISTE_EXIGER_SOURCE", "1") not in ("0", "false", "non"),
        offline=env("GENEALOGISTE_OFFLINE", "0") in ("1", "true", "oui"),
    )
    if env("GENEALOGISTE_USER_AGENT"):
        cfg.user_agent = env("GENEALOGISTE_USER_AGENT")
    if env("GENEALOGISTE_COG_MVT_URL"):
        cfg.cog_mvt_url = env("GENEALOGISTE_COG_MVT_URL")
    if env("GENEALOGISTE_COG_COMMUNES_URL"):
        cfg.cog_communes_url = env("GENEALOGISTE_COG_COMMUNES_URL")
    return cfg
