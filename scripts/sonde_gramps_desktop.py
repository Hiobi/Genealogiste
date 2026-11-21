"""Sonde exécutée DANS l'environnement isolé d'une bibliothèque Gramps Desktop (5.2, 6.0, 6.1).

Bibliothèque standard + `gramps` uniquement : aucun import de genealogiste_mcp. Pilotée par
`verifier_gramps_desktop.py`, qui lui passe une liste de fichiers à importer et lit son rapport JSON.

Pour chaque fichier (`.gramps` brut ou gzip, paquet `.gpkg` : plugin d'import choisi par Gramps selon
l'extension) : import dans une base SQLite en mémoire (`import_as_dict`, comme Gramps en ligne de commande),
relevé des handles par classe d'objets, des médias (chemin, fichier trouvé), des schémas DTD/RNG livrés avec la
bibliothèque, erreurs et avertissements de Gramps, puis (option
`--reexporter`) réexport en Gramps XML non compressé par `GrampsXmlWriter`, pour l'aller-retour.

Gramps sans interface : 5.2 et 6.0 importent `gi.repository.GLib` dès `gramps.gen.const` ; l'export XML importe
`gramps.gui.plug.export` (GTK) sur toutes les versions, pour des boîtes d'options inutilisées ici. La sonde
utilise le vrai PyGObject s'il est importable (paquets système `python3-gi`, venv `--system-site-packages`),
sinon un module `GLib` factice limité aux fonctions de chemins ; `gramps.gui.plug.export` est toujours
remplacé par un module factice (les classes d'options ne servent qu'à l'interface). Le rapport indique le
mode utilisé.

Usage : python sonde_gramps_desktop.py --rapport r.json [--reexporter DOSSIER] f1.gramps [f2.gramps …]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import types

CLASSES = {
    "Person": "get_person_handles", "Family": "get_family_handles", "Event": "get_event_handles",
    "Source": "get_source_handles", "Citation": "get_citation_handles", "Place": "get_place_handles",
    "Note": "get_note_handles", "Repository": "get_repository_handles", "Media": "get_media_handles",
    "Tag": "get_tag_handles",
}


def preparer_gi() -> str:
    """Vrai PyGObject si disponible, sinon GLib factice. Renvoie le mode retenu."""
    try:
        from gi.repository import GLib  # noqa: F401
        return "systeme"
    except ImportError:
        pass
    gi = types.ModuleType("gi")
    repo = types.ModuleType("gi.repository")

    class GLib:
        class UserDirectory:
            DIRECTORY_PICTURES = 0
            DIRECTORY_DOCUMENTS = 1

        class GError(Exception):
            pass

        get_user_data_dir = staticmethod(lambda: os.path.expanduser("~/.local/share"))
        get_user_config_dir = staticmethod(lambda: os.path.expanduser("~/.config"))
        get_user_cache_dir = staticmethod(lambda: os.path.expanduser("~/.cache"))
        get_user_special_dir = staticmethod(lambda _d: os.path.expanduser("~"))
        get_home_dir = staticmethod(lambda: os.path.expanduser("~"))

    repo.GLib = GLib
    gi.repository = repo
    gi.require_version = lambda *a, **k: None
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repo
    return "factice"


def neutraliser_gui_export() -> None:
    """`exportxml` importe ses boîtes d'options GTK ; elles ne servent pas à l'écriture du fichier."""
    for nom in ("gramps.gui.plug", "gramps.gui.plug.export"):
        module = types.ModuleType(nom)
        module.__path__ = []
        sys.modules[nom] = module
    export = sys.modules["gramps.gui.plug.export"]
    export.WriterOptionBox = object
    export.WriterOptionBoxWithCompression = object


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rapport", required=True)
    parser.add_argument("--reexporter", help="dossier où réécrire chaque fichier importé (Gramps XML)")
    parser.add_argument("fichiers", nargs="+")
    args = parser.parse_args()
    # Gramps réécrit sys.argv pendant son initialisation (constfunc.has_display) : arguments déjà lus.
    rapport: dict = {"gi": preparer_gi(), "gui_export": "factice", "fichiers": {}}
    neutraliser_gui_export()
    from gramps.cli.user import User
    from gramps.gen.db.utils import import_as_dict
    from gramps.plugins.lib import libgrampsxml
    from gramps.version import VERSION

    rapport["gramps"] = VERSION
    rapport["xml"] = libgrampsxml.GRAMPS_XML_VERSION
    from gramps.gen.const import DATA_DIR, USER_PICTURES

    # import .gpkg : médias extraits sous le dossier d'images de l'arbre, à défaut celui de l'utilisateur
    # (GLib réel ou factice, selon la version : HOME, HOME/Pictures, GRAMPSHOME/gramps…) ; il doit exister.
    os.makedirs(USER_PICTURES, exist_ok=True)
    from gramps.gen.utils.file import media_path_full

    # schémas livrés avec la bibliothèque : le banc valide les fichiers remis contre eux (#268)
    rapport["schemas"] = {k: os.path.join(DATA_DIR, f"grampsxml.{k}") for k in ("dtd", "rng")}
    try:
        from gramps.gen.lib.json_utils import object_to_dict
    except ImportError:  # Gramps 5.2 : pas de format JSON
        object_to_dict = None

    class Utilisateur(User):
        def __init__(self) -> None:
            super().__init__()
            self.erreurs: list[str] = []
            self.avertissements: list[str] = []

        def notify_error(self, title, error=""):
            self.erreurs.append(f"{title} | {error}".strip(" |"))

        def warn(self, title, warning=""):
            self.avertissements.append(f"{title} | {warning}".strip(" |"))

    for chemin in args.fichiers:
        nom = os.path.basename(chemin)
        user = Utilisateur()
        res: dict = {"erreurs": user.erreurs, "avertissements": user.avertissements}
        rapport["fichiers"][nom] = res
        try:
            db = import_as_dict(chemin, user, skp_imp_adds=True)
        except Exception:  # noqa: BLE001 - tout échec d'import est un résultat de la sonde
            user.erreurs.append(traceback.format_exc(limit=3))
            db = None
        if db is None:
            res["importe"] = False
            if not user.erreurs:
                user.erreurs.append("import_as_dict a renvoyé None")
            continue
        res["importe"] = True
        res["handles"] = {cls: sorted(getattr(db, meth)()) for cls, meth in CLASSES.items()}
        # médias : chemin enregistré et fichier trouvé par Gramps (paquet .gpkg : extrait à côté de l'arbre)
        res["medias"] = [{"chemin": m.get_path(), "fichier": os.path.isfile(media_path_full(db, m.get_path()))}
                         for m in (db.get_media_from_handle(h) for h in db.get_media_handles())]
        if object_to_dict:  # Gramps ≥ 6.0 : objets importés au format JSON, comparés champ par champ
            res["objets"] = [object_to_dict(getattr(db, f"get_{cls.lower()}_from_handle")(h))
                             for cls, meth in CLASSES.items() for h in getattr(db, meth)()]
        if args.reexporter:
            from gramps.plugins.export.exportxml import GrampsXmlWriter

            sortie = os.path.join(args.reexporter, nom)
            try:
                GrampsXmlWriter(db, 0, 0, VERSION, user).write(sortie)
                res["reexport"] = sortie
            except Exception:  # noqa: BLE001
                user.erreurs.append("réexport : " + traceback.format_exc(limit=3))
        db.close()
    with open(args.rapport, "w", encoding="utf-8") as f:
        json.dump(rapport, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
