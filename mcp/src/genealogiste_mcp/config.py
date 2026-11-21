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


def user_agent_par_defaut(contact: str = "") -> str:
    """User-Agent dérivé de la version du paquet : les services identifient la version qui les interroge.
    `contact` (GENEALOGISTE_CONTACT, déjà validé par `contact_valide`) est ajouté au commentaire RFC 9110 ;
    vide, l'en-tête est inchangé."""
    from importlib import metadata

    try:
        version = metadata.version("genealogiste-mcp")
    except metadata.PackageNotFoundError:
        version = "inconnue"
    suffixe = f"; contact: {contact}" if contact else ""
    return f"genealogiste-mcp/{version} (plugin Claude Code; usage genealogique personnel{suffixe})"


CONTACT_MAX = 200
# Caractères qui sortiraient du commentaire « (…) » de l'en-tête ou en casseraient la syntaxe (RFC 9110 §5.6.5).
_CONTACT_INTERDITS = set("();\\")


def contact_valide(valeur: str | None) -> tuple[str, str]:
    """GENEALOGISTE_CONTACT (#211, lot D) -> (contact retenu, motif du rejet). Facultatif, jamais de valeur par
    défaut : absent ou vide -> ("", ""). Invalide -> ("", motif) : ignoré, signalé par diagnostic, sans jamais
    empêcher le démarrage. Le motif ne reprend pas la valeur (donnée personnelle)."""
    v = (valeur or "").strip()
    if not v:
        return "", ""
    if len(v) > CONTACT_MAX:
        return "", f"plus de {CONTACT_MAX} caractères"
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in v):
        return "", "caractère de contrôle (retour à la ligne, tabulation…)"
    if not v.isascii():
        return "", "caractère non ASCII (un en-tête HTTP n'en admet pas de façon fiable)"
    if _CONTACT_INTERDITS & set(v):
        return "", "caractère interdit dans un commentaire d'en-tête : ( ) ; \\"
    return v, ""


@dataclass
class Config:
    data_dir: Path
    cache_path: Path
    wikitree_app_id: str = ""
    matchid_token: str = ""
    user_agent: str = field(default_factory=lambda: user_agent_par_defaut())
    backend: str = "fichier"  # fichier (GEDCOM 7 + Git, défaut) | gramps (Gramps Web = source de vérité)
    gramps_url: str = ""
    gramps_user: str = ""
    gramps_password: str = ""
    gramps_ttl: float = 30.0  # secondes entre deux rafraîchissements en lecture (mode gramps)
    gramps_notes_auto: str = "true"  # notes de preuve Genealogiste:auto : true (toute la base) | modifies | false
    gramps_notes_liens: bool = False  # liens internes gramps:// dans ces notes (#279) ; changement : par recalcul
    gramps_taches: bool = False  # tâches de Gramps Web (source + note étiquetées ToDo, #263) ; faux : rien de lu ni écrit
    # vivants marqués privés dans Gramps Web (#264) : off (rien d'ajouté) | propose (ajouté au diff de la proposition)
    gramps_prive_vivants: str = "off"
    git_mirror: bool = False  # mode gramps : miroir GEDCOM 7 versionné de l'arbre Gramps
    git_remote: str = ""  # dépôt distant optionnel (privé !) du répertoire de données
    strict_evidence: bool = False
    exiger_source: bool = True  # règle de métier : pas de fait sans source sauf motif explicite
    # GENEALOGISTE_ECRITURE (#159) : interdite = le serveur refuse tout outil de classe « ecriture » (arbre,
    # Gramps Web, fichiers de l'utilisateur), quel que soit le mode de permission du client.
    ecriture: str = "autorisee"
    notes_dir: Path | None = None  # notes de recherche Markdown (Obsidian) ; None = désactivées
    notes_vivants: str = "masquer"  # masquer | complet
    notes_auto: bool = True  # régénérer les fiches touchées après arbre_appliquer / journal_ajouter
    notes_kit: bool = True  # kit Obsidian (vues, modèles, extrait CSS) déposé par notes_generer « tout »
    marqueurs: str = "genealogiste"  # forme écrite des marqueurs (notes, Gramps) : genealogiste | sosa (#182)
    sosa_racine: str = ""  # personne n° 1 de la numérotation Sosa des notes
    cog_mvt_url: str = "https://www.insee.fr/fr/statistiques/fichier/7766585/v_mvt_commune_2024.csv"
    cog_communes_url: str = "https://www.insee.fr/fr/statistiques/fichier/7766585/v_commune_depuis_1943.csv"
    http_timeout: float = 30.0  # GENEALOGISTE_HTTP_TIMEOUT : délai d'un essai (secondes)
    http_tentatives: int = 5  # GENEALOGISTE_HTTP_TENTATIVES : essais au plus pour une requête idempotente
    http_duree_max: float = 60.0  # GENEALOGISTE_HTTP_DUREE_MAX : plafond d'un appel, attentes comprises
    media_dir_conf: Path | None = None  # GENEALOGISTE_MEDIA_DIR (ex. <vault>/documents) ; défaut <données>/medias
    rapports_dir_conf: Path | None = None  # GENEALOGISTE_RAPPORTS_DIR ; défaut <données>/rapports
    exports_dir_conf: Path | None = None  # GENEALOGISTE_EXPORTS_DIR ; défaut <données>/exports
    cache_images_dir_conf: Path | None = None  # GENEALOGISTE_CACHE_IMAGES_DIR ; défaut <données>/cache-images
    cache_pdf_dir_conf: Path | None = None  # GENEALOGISTE_CACHE_PDF_DIR ; défaut <données>/cache-pdf
    tesseract: str = ""  # GENEALOGISTE_TESSERACT : binaire Tesseract hors du PATH (ou shim Docker)
    hotes_autorises: list[str] = field(default_factory=list)  # exceptions à la politique réseau (hôte[:port])
    cache_max_mo: float = 500.0  # GENEALOGISTE_CACHE_MAX_MO : plafond du cache SQLite (0 = aucun)
    cache_images_max_mo: float = 2000.0  # GENEALOGISTE_CACHE_IMAGES_MAX_MO : plafond de cache-images (0 = aucun)
    cache_echec: float = 900.0  # GENEALOGISTE_CACHE_ECHEC : mémoire d'un échec 403/404 (secondes)
    coupe_circuit: float = 1800.0  # GENEALOGISTE_COUPE_CIRCUIT : pause d'un hôte après blocage anti-robot
    exclusion_antirobot: float = 604800.0  # GENEALOGISTE_EXCLUSION_ANTIROBOT : exclusion si le défi persiste (#150)
    ralentissement_max: float = 60.0  # GENEALOGISTE_RALENTISSEMENT_MAX : intervalle max (s) d'un hôte ralenti
    notes_attente: float = 20.0  # GENEALOGISTE_NOTES_ATTENTE : attente max des notes dans arbre_appliquer (s)
    git_delai: float = 60.0  # GENEALOGISTE_GIT_DELAI : délai maximal d'une commande git (push compris)
    log_niveau: str = "INFO"  # GENEALOGISTE_LOG_NIVEAU : DEBUG | INFO | WARNING | ERROR | AUCUN
    log_fichier: Path | None = None  # GENEALOGISTE_LOG_FICHIER ; défaut <données>/logs/serveur.log
    debit_defaut: float = 1.5  # GENEALOGISTE_DEBIT_DEFAUT : secondes minimum entre deux requêtes vers un même hôte
    debits: dict[str, float] = field(default_factory=dict)  # GENEALOGISTE_DEBITS : hote=secondes,… (priorité)
    # Budget par défaut d'une enquête (#157 ; 0 = illimité), réglable à enquete_ouvrir / enquete_noter.
    budget_requetes_hote: int = 200  # GENEALOGISTE_BUDGET_REQUETES_HOTE : requêtes émises vers un même hôte
    budget_images: int = 40  # GENEALOGISTE_BUDGET_IMAGES : images lues (archive_image)
    # Variables retirées encore définies (#211 : durée et coût estimé ne sont plus des limites) : ignorées,
    # signalées par diagnostic.
    variables_retirees: list[str] = field(default_factory=list)
    plafond_jour_archives: int = 1000  # GENEALOGISTE_PLAFOND_JOUR_ARCHIVES : requêtes/hôte/jour (0 = aucun)
    plafond_jour_defaut: int = 1000  # GENEALOGISTE_PLAFOND_JOUR_DEFAUT : autres hôtes (API…), requêtes/jour (0 = aucun)
    plafonds_jour: dict[str, int] = field(default_factory=dict)  # GENEALOGISTE_PLAFONDS_JOUR : hote=n,… (priorité)
    # GENEALOGISTE_CONTACT (#211, lot D) : contact facultatif ajouté au User-Agent par défaut (donnée personnelle
    # envoyée à chaque hôte externe, jamais journalisée). etat_contact : absent | configure | rejete | ignore
    # (User-Agent explicite) ; contact_motif : raison d'un rejet ou d'une mise à l'écart, sans la valeur.
    contact: str = ""
    etat_contact: str = "absent"
    contact_motif: str = ""
    offline: bool = False
    extra: dict = field(default_factory=dict)

    def budget_defaut(self) -> dict:
        return {"requetes_par_hote": self.budget_requetes_hote, "images": self.budget_images}

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
    def cache_pdf_dir(self) -> Path:
        """Markdown extrait des PDF (pdf_markdown), clé = empreinte du contenu : hors du vault, jamais versionné."""
        return self.cache_pdf_dir_conf or self.data_dir / "cache-pdf"

    @property
    def pieces_registre(self) -> Path:
        """Registre des pièces archivées (source -> fichier, empreinte) : une pièce n'est jamais retéléchargée."""
        return self.data_dir / "pieces-archivees.jsonl"

    def media_ref(self, path: Path) -> str:
        """Référence d'un média enregistrée dans l'arbre (#193) : relative au répertoire de données quand il s'y
        trouve (« medias/… ») ; sinon, avec GENEALOGISTE_MEDIA_DIR, relative à l'arborescence des pièces
        (« documents/État civil/… », « photographies/… » : indépendante de la machine) pourvu qu'elle se résolve
        sans ambiguïté vers ce même fichier ; absolue dans les autres cas."""
        from .chemins import CheminRefuse, localiser

        p = Path(path).resolve()
        base = Path(self.data_dir).resolve()
        if p.is_relative_to(base):
            return p.relative_to(base).as_posix()
        racine = Path(self.pieces_root).resolve()
        if self.media_dir_conf and p.is_relative_to(racine):
            rel = p.relative_to(racine).as_posix()
            try:
                if localiser(self.media_racines, rel) == p:
                    return rel
            except CheminRefuse:  # ambigu (doublon différent sous une autre racine) : chemin absolu
                pass
        return str(p)

    def media_local(self, fichier: str) -> Path:
        """Fichier local désigné par la référence d'un média, selon la règle unique de chemins.localiser (#193) :
        absolu sous une racine autorisée, ou relatif essayé contre données, médias, arborescence des pièces.
        Lève CheminRefuse (hors des racines) ou CheminAmbigu (présent sous plusieurs racines, contenus différents)."""
        from .chemins import localiser

        return localiser(self.media_racines, fichier)

    @property
    def media_racines(self) -> tuple[Path, ...]:
        """Racines où un média local peut se trouver, dans l'ordre d'essai d'un chemin relatif : données,
        répertoire des médias, arborescence des pièces (ex. <vault>/documents puis <vault>)."""
        return self.data_dir, self.media_dir, self.pieces_root

    def media_reference(self, fichier: str) -> str:
        """Référence normalisée d'un média désigné par ajouter_media (#192) : une URL distante est gardée telle
        quelle ; un chemin local (relatif aux données, au répertoire des médias ou à l'arborescence des pièces, ou
        absolu sous l'une d'elles) doit désigner un fichier existant et devient media_ref. Lève CheminRefuse
        (ValueError) pour un chemin hors de ces racines ou un fichier introuvable."""
        from .chemins import CheminRefuse

        if "://" in fichier:
            return fichier
        p = self.media_local(fichier)
        if not p.is_file():
            raise CheminRefuse(f"Fichier de média introuvable : {fichier} (cherché dans "
                               + ", ".join(dict.fromkeys(str(r) for r in self.media_racines))
                               + ") ; l'enregistrer d'abord (media_enregistrer, piece_archiver)")
        return self.media_ref(p)


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


def notes_liens(value: str | None) -> bool:
    """GENEALOGISTE_GRAMPS_NOTES_LIENS (#279) : liens internes gramps:// dans les notes de preuve générées ; faux
    par défaut, valeur inconnue refusée (pas de bascule silencieuse)."""
    v = (value or "").strip().lower()
    if not v:
        return False
    if v not in NOTES_AUTO or NOTES_AUTO[v] == "modifies":
        raise ValueError(f"GENEALOGISTE_GRAMPS_NOTES_LIENS={value!r} : valeurs possibles true | false")
    return NOTES_AUTO[v] == "true"


def taches_mode(value: str | None) -> bool:
    """GENEALOGISTE_GRAMPS_TACHES (#263) : tâches de Gramps Web (source étiquetée ToDo, attributs Status et
    Priority) lues et écrites comme tâches ; faux par défaut (comportement inchangé), valeur inconnue refusée."""
    v = (value or "").strip().lower()
    if not v:
        return False
    if v not in NOTES_AUTO or NOTES_AUTO[v] == "modifies":
        raise ValueError(f"GENEALOGISTE_GRAMPS_TACHES={value!r} : valeurs possibles true | false")
    return NOTES_AUTO[v] == "true"


PRIVE_VIVANTS = ("off", "propose")
REGLE_PRIVE = ("le drapeau privé n'est jamais posé ni retiré sans proposition (diff, accord explicite, "
               "arbre_appliquer, journalisée et annulable)")


def prive_vivants_mode(value: str | None) -> str:
    """GENEALOGISTE_GRAMPS_PRIVE_VIVANTS (#264) : off (défaut, comportement inchangé) | propose (la pose du privé des
    vivants concernés est ajoutée au diff de la proposition en cours). « auto » est refusé : il écrirait le drapeau
    sans proposition, contraire à la règle du plugin ; valeur inconnue refusée (pas de bascule silencieuse)."""
    v = (value or "").strip().lower()
    if not v:
        return "off"
    if v == "auto":
        raise ValueError(f"GENEALOGISTE_GRAMPS_PRIVE_VIVANTS=auto refusé : {REGLE_PRIVE}. Valeurs possibles : off | "
                         "propose (ajouté au diff, appliqué après accord) ; pour tout l'arbre : gramps_proteger_vivants "
                         "(docs/gramps-web.md, « Vivants et privé »).")
    if v not in PRIVE_VIVANTS:
        raise ValueError(f"GENEALOGISTE_GRAMPS_PRIVE_VIVANTS={value!r} : valeurs possibles off | propose")
    return v


ECRITURE = {"autorisee": "autorisee", "autorisée": "autorisee", "interdite": "interdite"}


def ecriture_mode(value: str | None) -> str:
    v = (value or "").strip().lower()
    if not v:
        return "autorisee"
    if v not in ECRITURE:
        raise ValueError(f"GENEALOGISTE_ECRITURE={value!r} : valeurs possibles interdite | autorisee")
    return ECRITURE[v]


def notes_vivants_mode(value: str | None) -> str:
    v = (value or "masquer").strip().lower()
    if v not in ("masquer", "complet"):
        raise ValueError(f"GENEALOGISTE_NOTES_VIVANTS={value!r} : valeurs possibles masquer | complet")
    return v


def marqueurs_mode(value: str | None) -> str:
    """GENEALOGISTE_MARQUEURS (#182) : forme écrite des marqueurs ; les deux formes restent toujours lues."""
    v = (value or "").strip().lower()
    if not v:
        return "genealogiste"
    if v not in ("genealogiste", "sosa"):
        raise ValueError(f"GENEALOGISTE_MARQUEURS={value!r} : valeurs possibles genealogiste | sosa "
                         "(sosa : ancienne forme, pour partager notes ou base Gramps avec une ancienne version)")
    return v


def secondes(value: str | None, default: float, variable: str) -> float:
    if value is None or value.strip() == "":
        return default
    try:
        v = float(value)
    except ValueError:
        v = -1.0
    if not v >= 0:
        raise ValueError(f"{variable}={value!r} : nombre de secondes positif ou nul attendu (ex. 1.5)")
    return v


def niveau_log(value: str | None) -> str:
    v = (value or "INFO").strip().upper()
    if v not in ("DEBUG", "INFO", "WARNING", "ERROR", "AUCUN"):
        raise ValueError(f"GENEALOGISTE_LOG_NIVEAU={value!r} : valeurs possibles DEBUG | INFO | WARNING | ERROR | AUCUN")
    return v


def entier_positif(value: str | None, default: int, variable: str) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        v = int(value)
    except ValueError:
        v = 0
    if v < 1:
        raise ValueError(f"{variable}={value!r} : entier supérieur ou égal à 1 attendu")
    return v


def entier_positif_ou_nul(value: str | None, default: int, variable: str) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        v = int(value)
    except ValueError:
        v = -1
    if v < 0:
        raise ValueError(f"{variable}={value!r} : entier positif ou nul attendu (0 = illimité)")
    return v


def debits_par_hote(value: str | None) -> dict[str, float]:
    """« hote=secondes,hote2=secondes » -> {hote: secondes}."""
    out: dict[str, float] = {}
    for item in (value or "").split(","):
        if not item.strip():
            continue
        hote, sep, val = item.partition("=")
        if not sep or not hote.strip():
            raise ValueError(f"GENEALOGISTE_DEBITS={value!r} : format attendu hote=secondes,hote2=secondes")
        out[hote.strip().lower()] = secondes(val, 0.0, "GENEALOGISTE_DEBITS")
    return out


def plafonds_par_hote(value: str | None) -> dict[str, int]:
    """« hote=n,hote2=n » -> {hote: n} (plafond journalier par hôte, 0 = aucun)."""
    out: dict[str, int] = {}
    for item in (value or "").split(","):
        if not item.strip():
            continue
        hote, sep, val = item.partition("=")
        if not sep or not hote.strip() or not val.strip():
            raise ValueError(f"GENEALOGISTE_PLAFONDS_JOUR={value!r} : format attendu hote=requetes,hote2=requetes")
        out[hote.strip().lower()] = entier_positif_ou_nul(val.strip(), 0, "GENEALOGISTE_PLAFONDS_JOUR")
    return out


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "oui", "yes", "on")


def _dir(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


# Retirées (#211) : le budget d'enquête ne limite plus la durée ni le coût estimé ; le coût réel se plafonne côté
# client (--max-budget-usd). Encore définies : ignorées, signalées par diagnostic.
VARIABLES_RETIREES = ("GENEALOGISTE_BUDGET_DUREE_MIN", "GENEALOGISTE_BUDGET_COUT_TOKENS")


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
        gramps_notes_liens=notes_liens(env("GENEALOGISTE_GRAMPS_NOTES_LIENS")),
        gramps_taches=taches_mode(env("GENEALOGISTE_GRAMPS_TACHES")),
        gramps_prive_vivants=prive_vivants_mode(env("GENEALOGISTE_GRAMPS_PRIVE_VIVANTS")),
        git_mirror=_bool(env("GENEALOGISTE_GIT_MIRROR"), False),
        git_remote=env("GENEALOGISTE_GIT_REMOTE", ""),
        strict_evidence=env("GENEALOGISTE_STRICT", "0") in ("1", "true", "oui"),
        exiger_source=env("GENEALOGISTE_EXIGER_SOURCE", "1") not in ("0", "false", "non"),
        ecriture=ecriture_mode(env("GENEALOGISTE_ECRITURE")),
        offline=env("GENEALOGISTE_OFFLINE", "0") in ("1", "true", "oui"),
        notes_dir=Path(env("GENEALOGISTE_NOTES_DIR")).expanduser() if env("GENEALOGISTE_NOTES_DIR") else None,
        notes_vivants=notes_vivants_mode(env("GENEALOGISTE_NOTES_VIVANTS")),
        notes_auto=_bool(env("GENEALOGISTE_NOTES_AUTO"), True),
        notes_kit=_bool(env("GENEALOGISTE_NOTES_KIT"), True),
        marqueurs=marqueurs_mode(env("GENEALOGISTE_MARQUEURS")),
        sosa_racine=env("GENEALOGISTE_SOSA_RACINE", ""),
        hotes_autorises=[h for h in env("GENEALOGISTE_HOTES_AUTORISES", "").split(",") if h.strip()],
        http_timeout=secondes(env("GENEALOGISTE_HTTP_TIMEOUT"), 30.0, "GENEALOGISTE_HTTP_TIMEOUT") or 30.0,
        http_tentatives=entier_positif(env("GENEALOGISTE_HTTP_TENTATIVES"), 5, "GENEALOGISTE_HTTP_TENTATIVES"),
        http_duree_max=secondes(env("GENEALOGISTE_HTTP_DUREE_MAX"), 60.0, "GENEALOGISTE_HTTP_DUREE_MAX") or 60.0,
        cache_max_mo=secondes(env("GENEALOGISTE_CACHE_MAX_MO"), 500.0, "GENEALOGISTE_CACHE_MAX_MO"),
        cache_images_max_mo=secondes(env("GENEALOGISTE_CACHE_IMAGES_MAX_MO"), 2000.0,
                                     "GENEALOGISTE_CACHE_IMAGES_MAX_MO"),
        cache_echec=secondes(env("GENEALOGISTE_CACHE_ECHEC"), 900.0, "GENEALOGISTE_CACHE_ECHEC"),
        coupe_circuit=secondes(env("GENEALOGISTE_COUPE_CIRCUIT"), 1800.0, "GENEALOGISTE_COUPE_CIRCUIT"),
        exclusion_antirobot=secondes(env("GENEALOGISTE_EXCLUSION_ANTIROBOT"), 604800.0,
                                     "GENEALOGISTE_EXCLUSION_ANTIROBOT"),
        ralentissement_max=secondes(env("GENEALOGISTE_RALENTISSEMENT_MAX"), 60.0,
                                    "GENEALOGISTE_RALENTISSEMENT_MAX"),
        notes_attente=secondes(env("GENEALOGISTE_NOTES_ATTENTE"), 20.0, "GENEALOGISTE_NOTES_ATTENTE"),
        git_delai=secondes(env("GENEALOGISTE_GIT_DELAI"), 60.0, "GENEALOGISTE_GIT_DELAI") or 60.0,
        log_niveau=niveau_log(env("GENEALOGISTE_LOG_NIVEAU")),
        log_fichier=_dir(env("GENEALOGISTE_LOG_FICHIER")),
        debit_defaut=secondes(env("GENEALOGISTE_DEBIT_DEFAUT"), 1.5, "GENEALOGISTE_DEBIT_DEFAUT"),
        debits=debits_par_hote(env("GENEALOGISTE_DEBITS")),
        budget_requetes_hote=entier_positif_ou_nul(env("GENEALOGISTE_BUDGET_REQUETES_HOTE"), 200,
                                                   "GENEALOGISTE_BUDGET_REQUETES_HOTE"),
        budget_images=entier_positif_ou_nul(env("GENEALOGISTE_BUDGET_IMAGES"), 40, "GENEALOGISTE_BUDGET_IMAGES"),
        variables_retirees=sorted(v for v in VARIABLES_RETIREES if env(v) is not None),
        plafond_jour_archives=entier_positif_ou_nul(env("GENEALOGISTE_PLAFOND_JOUR_ARCHIVES"), 1000,
                                                    "GENEALOGISTE_PLAFOND_JOUR_ARCHIVES"),
        plafond_jour_defaut=entier_positif_ou_nul(env("GENEALOGISTE_PLAFOND_JOUR_DEFAUT"), 1000,
                                                  "GENEALOGISTE_PLAFOND_JOUR_DEFAUT"),
        plafonds_jour=plafonds_par_hote(env("GENEALOGISTE_PLAFONDS_JOUR")),
        media_dir_conf=_dir(env("GENEALOGISTE_MEDIA_DIR")),
        rapports_dir_conf=_dir(env("GENEALOGISTE_RAPPORTS_DIR")),
        exports_dir_conf=_dir(env("GENEALOGISTE_EXPORTS_DIR")),
        cache_images_dir_conf=_dir(env("GENEALOGISTE_CACHE_IMAGES_DIR")),
        cache_pdf_dir_conf=_dir(env("GENEALOGISTE_CACHE_PDF_DIR")),
        tesseract=str(Path(env("GENEALOGISTE_TESSERACT")).expanduser()) if env("GENEALOGISTE_TESSERACT") else "",
    )
    contact, motif = contact_valide(env("GENEALOGISTE_CONTACT"))
    if env("GENEALOGISTE_USER_AGENT"):
        # User-Agent explicite : envoyé tel quel, le contact n'y est jamais ajouté.
        cfg.user_agent = env("GENEALOGISTE_USER_AGENT")
        if contact or motif:
            cfg.etat_contact = "ignore"
            cfg.contact_motif = "GENEALOGISTE_USER_AGENT est défini : il est envoyé tel quel, sans le contact"
    elif motif:
        cfg.etat_contact, cfg.contact_motif = "rejete", motif
    elif contact:
        cfg.contact, cfg.etat_contact = contact, "configure"
        cfg.user_agent = user_agent_par_defaut(contact)
    if env("GENEALOGISTE_COG_MVT_URL"):
        cfg.cog_mvt_url = env("GENEALOGISTE_COG_MVT_URL")
    if env("GENEALOGISTE_COG_COMMUNES_URL"):
        cfg.cog_communes_url = env("GENEALOGISTE_COG_COMMUNES_URL")
    return cfg
