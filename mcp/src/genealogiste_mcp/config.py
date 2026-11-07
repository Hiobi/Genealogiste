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
    gramps_notes_auto: str = "true"  # notes de preuve Sosa:auto : true (toute la base) | modifies | false
    git_mirror: bool = False  # mode gramps : miroir GEDCOM 7 versionné de l'arbre Gramps
    git_remote: str = ""  # dépôt distant optionnel (privé !) du répertoire de données
    strict_evidence: bool = False
    exiger_source: bool = True  # règle de métier : pas de fait sans source sauf motif explicite
    notes_dir: Path | None = None  # notes de recherche Markdown (Obsidian) ; None = désactivées
    notes_vivants: str = "masquer"  # masquer | complet
    notes_auto: bool = True  # régénérer les fiches touchées après arbre_appliquer / journal_ajouter
    sosa_racine: str = ""  # personne n° 1 de la numérotation Sosa des notes
    cog_mvt_url: str = "https://www.insee.fr/fr/statistiques/fichier/7766585/v_mvt_commune_2024.csv"
    cog_communes_url: str = "https://www.insee.fr/fr/statistiques/fichier/7766585/v_commune_depuis_1943.csv"
    http_timeout: float = 30.0
    media_dir_conf: Path | None = None  # GENEALOGISTE_MEDIA_DIR (ex. <vault>/documents) ; défaut <données>/medias
    rapports_dir_conf: Path | None = None  # GENEALOGISTE_RAPPORTS_DIR ; défaut <données>/rapports
    exports_dir_conf: Path | None = None  # GENEALOGISTE_EXPORTS_DIR ; défaut <données>/exports
    cache_images_dir_conf: Path | None = None  # GENEALOGISTE_CACHE_IMAGES_DIR ; défaut <données>/cache-images
    hotes_autorises: list[str] = field(default_factory=list)  # exceptions à la politique réseau (hôte[:port])
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
        return self.media_dir_conf or self.data_dir / "medias"

    @property
    def rapports_dir(self) -> Path:
        return self.rapports_dir_conf or self.data_dir / "rapports"

    @property
    def exports_dir(self) -> Path:
        return self.exports_dir_conf or self.data_dir / "exports"

    @property
    def pieces_root(self) -> Path:
        """Racine de l'arborescence des pièces (documents/, photographies/, archives/, _À trier/) : le dossier
        parent quand le répertoire des médias est lui-même « documents » (ex. <vault>/documents), sinon lui."""
        m = self.media_dir
        return m.parent if m.name.lower() == "documents" else m

    @property
    def cache_images_dir(self) -> Path:
        """Aperçus et recadrages de lecture (archive_image) : hors du vault, jamais versionnés."""
        return self.cache_images_dir_conf or self.data_dir / "cache-images"

    @property
    def pieces_registre(self) -> Path:
        """Registre des pièces archivées (source -> fichier, empreinte) : une pièce n'est jamais retéléchargée."""
        return self.data_dir / "pieces-archivees.jsonl"

    def media_ref(self, path: Path) -> str:
        """Référence d'un média enregistrée dans l'arbre : relative au répertoire de données quand il s'y trouve
        (« medias/… »), absolue sinon (GENEALOGISTE_MEDIA_DIR hors des données, ex. un vault Obsidian)."""
        p = Path(path).resolve()
        base = Path(self.data_dir).resolve()
        return p.relative_to(base).as_posix() if p.is_relative_to(base) else str(p)


BACKENDS = {"fichier": "fichier", "file": "fichier", "gedcom": "fichier", "": "fichier",
            "gramps": "gramps", "grampsweb": "gramps", "gramps-web": "gramps"}


def backend_name(value: str) -> str:
    v = (value or "").strip().lower()
    if v not in BACKENDS:
        raise ValueError(f"GENEALOGISTE_BACKEND={value!r} : valeurs possibles fichier | gramps")
    return BACKENDS[v]


NOTES_AUTO = {"true": "true", "1": "true", "oui": "true", "yes": "true", "on": "true",
              "false": "false", "0": "false", "non": "false", "no": "false", "off": "false",
              "modifies": "modifies", "modifiés": "modifies", "modifie": "modifies"}


def notes_auto_mode(value: str | None) -> str:
    v = (value or "").strip().lower()
    if not v:
        return "true"
    if v not in NOTES_AUTO:
        raise ValueError(f"GENEALOGISTE_GRAMPS_NOTES_AUTO={value!r} : valeurs possibles true | modifies | false")
    return NOTES_AUTO[v]


def notes_vivants_mode(value: str | None) -> str:
    v = (value or "masquer").strip().lower()
    if v not in ("masquer", "complet"):
        raise ValueError(f"GENEALOGISTE_NOTES_VIVANTS={value!r} : valeurs possibles masquer | complet")
    return v


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "oui", "yes", "on")


def _dir(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


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
        gramps_notes_auto=notes_auto_mode(env("GENEALOGISTE_GRAMPS_NOTES_AUTO")),
        git_mirror=_bool(env("GENEALOGISTE_GIT_MIRROR"), False),
        git_remote=env("GENEALOGISTE_GIT_REMOTE", ""),
        strict_evidence=env("GENEALOGISTE_STRICT", "0") in ("1", "true", "oui"),
        exiger_source=env("GENEALOGISTE_EXIGER_SOURCE", "1") not in ("0", "false", "non"),
        offline=env("GENEALOGISTE_OFFLINE", "0") in ("1", "true", "oui"),
        notes_dir=Path(env("GENEALOGISTE_NOTES_DIR")).expanduser() if env("GENEALOGISTE_NOTES_DIR") else None,
        notes_vivants=notes_vivants_mode(env("GENEALOGISTE_NOTES_VIVANTS")),
        notes_auto=_bool(env("GENEALOGISTE_NOTES_AUTO"), True),
        sosa_racine=env("GENEALOGISTE_SOSA_RACINE", ""),
        hotes_autorises=[h for h in env("GENEALOGISTE_HOTES_AUTORISES", "").split(",") if h.strip()],
        media_dir_conf=_dir(env("GENEALOGISTE_MEDIA_DIR")),
        rapports_dir_conf=_dir(env("GENEALOGISTE_RAPPORTS_DIR")),
        exports_dir_conf=_dir(env("GENEALOGISTE_EXPORTS_DIR")),
        cache_images_dir_conf=_dir(env("GENEALOGISTE_CACHE_IMAGES_DIR")),
    )
    if env("GENEALOGISTE_USER_AGENT"):
        cfg.user_agent = env("GENEALOGISTE_USER_AGENT")
    if env("GENEALOGISTE_COG_MVT_URL"):
        cfg.cog_mvt_url = env("GENEALOGISTE_COG_MVT_URL")
    if env("GENEALOGISTE_COG_COMMUNES_URL"):
        cfg.cog_communes_url = env("GENEALOGISTE_COG_COMMUNES_URL")
    return cfg
