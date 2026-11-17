"""Kit Obsidian des notes : vues Bases et Dataview, modèles de recherche et de courrier, extrait CSS.

Déposé par ``notes_generer("tout")`` dans ``<NOTES_DIR>/_genealogiste/`` ; l'extrait CSS va dans
``.obsidian/snippets/`` du vault qui contient les notes (répertoire des notes ou un parent), sinon à côté des vues.

Un fichier du kit n'est remplacé que s'il est absent ou identique à la version déposée précédemment (empreinte
dans ``_genealogiste/.kit.json``) : une copie modifiée par l'utilisateur est conservée et signalée.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .fichiers import ecrire_atomique

SOURCE = Path(__file__).with_name("obsidian")
DOSSIER = "_genealogiste"
MANIFESTE = ".kit.json"
SNIPPET = "genealogiste.css"
FICHIERS = ("vues/Genealogiste.base", "vues/Tableau de bord.md", "modeles/Recherche.md", "modeles/Courrier.md")


def _empreinte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def vault(notes: Path) -> Path | None:
    """Racine du vault Obsidian (répertoire contenant ``.obsidian``) : le répertoire des notes ou un parent."""
    for d in (notes, *notes.parents):
        cfg = d / ".obsidian"
        if cfg.is_dir() and not cfg.is_symlink():
            return d
        if d == Path.home():
            break
    return None


def deployer(notes: Path) -> dict:
    """Dépose ou met à jour le kit ; renvoie ce qui a été écrit, conservé (modifié à la main) ou refusé."""
    notes = notes.resolve()
    kit = notes / DOSSIER
    man_path = kit / MANIFESTE
    try:
        manifeste = json.loads(man_path.read_text(encoding="utf-8")) if man_path.is_file() else {}
    except (OSError, ValueError):
        manifeste = {}
    if not isinstance(manifeste, dict):
        manifeste = {}

    racine = vault(notes)
    cibles = [(f, kit / f, f) for f in FICHIERS]
    if racine:
        cible_css = racine / ".obsidian" / "snippets" / SNIPPET
        cle_css = str(cible_css.relative_to(notes)) if cible_css.is_relative_to(notes) else str(cible_css)
    else:
        cible_css, cle_css = kit / SNIPPET, SNIPPET
    cibles.append((SNIPPET, cible_css, cle_css))

    out: dict = {"dossier": str(kit), "ecrits": [], "inchanges": 0, "conserves": [], "refuses": []}
    for source, cible, cle in cibles:
        texte = (SOURCE / source).read_text(encoding="utf-8")
        if cible.is_symlink() or any(p.is_symlink() for p in cible.parents if p.is_relative_to(racine or notes)):
            out["refuses"].append(f"{cle} : lien symbolique, écriture refusée")
            continue
        if cible.exists():
            actuel = cible.read_text(encoding="utf-8")
            if actuel == texte:
                manifeste[cle] = _empreinte(texte)
                out["inchanges"] += 1
                continue
            if manifeste.get(cle) != _empreinte(actuel):
                out["conserves"].append(f"{cle} : modifié à la main, conservé (supprimer le fichier pour "
                                        "reprendre la version du plugin)")
                continue
        cible.parent.mkdir(parents=True, exist_ok=True)
        ecrire_atomique(cible, texte)
        manifeste[cle] = _empreinte(texte)
        out["ecrits"].append(cle)
    kit.mkdir(parents=True, exist_ok=True)
    nouveau = json.dumps(manifeste, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if not man_path.is_file() or man_path.read_text(encoding="utf-8") != nouveau:
        ecrire_atomique(man_path, nouveau)

    out["extrait_css"] = str(cible_css)
    if racine:
        out["consigne"] = ("Activer l'extrait « genealogiste » dans Réglages → Apparence → Extraits CSS. Ouvrir "
                           f"{DOSSIER}/vues/Genealogiste.base (Bases) ou « Tableau de bord » (Dataview). Modèles : "
                           f"régler le dossier des modèles sur {DOSSIER}/modeles (extension Modèles).")
    else:
        out["consigne"] = ("Aucun dossier .obsidian trouvé au-dessus des notes : copier "
                           f"{DOSSIER}/{SNIPPET} dans .obsidian/snippets/ du vault puis l'activer dans Réglages → "
                           "Apparence → Extraits CSS.")
    for cle in ("conserves", "refuses"):
        if not out[cle]:
            del out[cle]
    return out
