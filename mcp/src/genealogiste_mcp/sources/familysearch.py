"""FamilySearch via getmyancestors (connexion de l'utilisateur) -> fichier GEDCOM à importer."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .base import SourceContext

FS_ID = re.compile(r"^[A-Z0-9]{4}-[A-Z0-9]{3,4}$")


def export_gedcom(ctx: SourceContext, ids: list[str], ascendants: int = 4, descendants: int = 0,
                  conjoints: bool = True, sortie: str = "") -> dict:
    exe = shutil.which("getmyancestors")
    if not exe:
        return {"erreur": "getmyancestors non installé.",
                "installation": "uv sync --extra familysearch (dans mcp/) ou pipx install getmyancestors"}
    user, password = ctx.config.fs_user, ctx.config.fs_password
    if not (user and password):
        return {"erreur": "Identifiants FamilySearch absents : définir GENEALOGISTE_FS_USER et GENEALOGISTE_FS_PASSWORD "
                          "dans le fichier .env du répertoire de données (jamais dans le dépôt)."}
    bad = [i for i in ids if not FS_ID.match(i)]
    if bad:
        return {"erreur": f"Identifiants FamilySearch invalides : {bad} (format XXXX-XXX)"}
    out = Path(sortie).expanduser() if sortie else ctx.config.exports_dir / f"familysearch-{'_'.join(ids)}.ged"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "-u", user, "-p", password, "-a", str(max(0, min(ascendants, 12))),
           "-d", str(max(0, min(descendants, 6))), "-o", str(out), "-i", *ids]
    if conjoints:
        cmd.append("-m")
    params = {"ids": ids, "ascendants": ascendants, "descendants": descendants}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, env={**os.environ})
    except subprocess.TimeoutExpired:
        ctx.journal.add("familysearch", "getmyancestors", params, "erreur", resume="délai dépassé")
        return {"erreur": "getmyancestors : délai dépassé (30 min)"}
    if r.returncode != 0 or not out.exists():
        msg = (r.stderr or r.stdout).replace(password, "***")[-1500:]
        ctx.journal.add("familysearch", "getmyancestors", params, "erreur", resume=msg[:300])
        return {"erreur": f"getmyancestors a échoué : {msg}"}
    n = out.read_text(encoding="utf-8", errors="replace").count("@ INDI")
    ctx.journal.add("familysearch", "getmyancestors", params, "positif" if n else "negatif", nb_resultats=n,
                    references=[str(out)])
    return {"fichier": str(out), "personnes": n,
            "suite": "Importer avec arbre_importer_gedcom(chemin, mode='ajouter') : diff + validation, puis "
                     "/gen:recoupe pour les doublons. FamilySearch est un arbre composite : sources à vérifier."}
