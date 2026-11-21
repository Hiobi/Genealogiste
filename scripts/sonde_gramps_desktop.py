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

Option ``--dates`` (#272) : inventaire de formes de date soumis à ``Date.set`` de la bibliothèque (acceptée ou
refusée, valeur de tri, affichage anglais ISO), pour comparaison avec la correspondance de Genealogiste.

Usage : python sonde_gramps_desktop.py --rapport r.json [--reexporter DOSSIER] [--dates formes.json]
        f1.gramps [f2.gramps …]
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


def neutraliser_gtk() -> None:
    """`exportpkg` importe Gtk pour une boîte de dialogue commentée : l'écriture du paquet n'en a pas besoin."""
    sys.modules.setdefault("gi.repository.Gtk", types.ModuleType("gi.repository.Gtk"))


MEDIA_GENERE = "actes/acte fictif é.jpg"


def generer(dossier: str, user) -> dict:
    """Arbre FICTIF construit par l'API de la bibliothèque Gramps, puis exporté comme Gramps Desktop le fait :
    `famille.gramps` (Gramps XML gzip, option par défaut « Use Compression ») et `famille.gpkg` (PackageWriter,
    avec un média). Couvre ce que l'import de Genealogiste doit reconnaître : marqueurs Genealogiste-* et forme
    historique Sosa-* / Sosa:auto, privé, témoin, calendriers julien et républicain, et ce qu'il ne représente pas
    (adresse, URL, texte stylé, étiquette, suffixe, nom alternatif daté)."""
    from gramps.gen.db import DbTxn
    from gramps.gen.db.utils import make_database
    from gramps.gen.lib import (
        Address,
        Attribute,
        ChildRef,
        Citation,
        Date,
        Event,
        EventRef,
        EventRoleType,
        EventType,
        Family,
        FamilyRelType,
        Media,
        MediaRef,
        Name,
        NameType,
        Note,
        NoteType,
        Person,
        PersonRef,
        Place,
        PlaceName,
        PlaceRef,
        PlaceType,
        RepoRef,
        Repository,
        RepositoryType,
        Source,
        SourceMediaType,
        SrcAttribute,
        StyledText,
        StyledTextTag,
        StyledTextTagType,
        Surname,
        Tag,
        Url,
        UrlType,
    )
    from gramps.plugins.export.exportxml import XmlWriter

    neutraliser_gtk()
    from gramps.plugins.export.exportpkg import PackageWriter

    # arbre SQLite dans un dossier jetable ; chemin des médias relatif à ce dossier (comme Gramps l'interprète) :
    # aucun chemin de la machine dans les fichiers produits, et Gramps les relit sans variable à développer
    base = os.path.join(dossier, "arbre")
    medias = os.path.join(base, "medias")
    os.makedirs(os.path.join(medias, os.path.dirname(MEDIA_GENERE)), exist_ok=True)
    with open(os.path.join(medias, MEDIA_GENERE), "wb") as f:
        f.write(b"\xff\xd8\xff\xe0 image fictive")
    db = make_database("sqlite")
    db.load(base)
    db.set_mediapath("medias")

    def attr(typ: str, val: str, cls=Attribute):
        a = cls()
        a.set_type(typ)
        a.set_value(val)
        return a

    def date(y=0, m=0, d=0, mod=Date.MOD_NONE, cal=Date.CAL_GREGORIAN):
        x = Date()
        x.set(Date.QUAL_NONE, mod, cal, (d, m, y, False))
        return x

    with DbTxn("Arbre fictif", db) as t:
        def ajouter(obj, handle, gid=None, meth=None):
            obj.set_handle(handle)
            if gid:
                obj.set_gramps_id(gid)
            getattr(db, meth)(obj, t)
            return handle

        verif = Tag()
        verif.set_name("À vérifier")
        verif.set_color("#ef2929ef2929")
        ajouter(verif, "tagverif", meth="add_tag")
        auto = Tag()
        auto.set_name("Sosa:auto")  # forme historique de Genealogiste:auto
        ajouter(auto, "tagauto", meth="add_tag")
        depot = Repository()
        depot.set_name("Archives départementales fictives")
        depot.set_type(RepositoryType.ARCHIVE)
        adr = Address()
        adr.set_city("Villefictive")
        depot.add_address(adr)
        ajouter(depot, "depot001", "R0001", "add_repository")
        src = Source()
        src.set_title("Registres paroissiaux de Villefictive")
        src.set_author("Paroisse Saint-Exemple")
        rr = RepoRef()
        rr.set_reference_handle("depot001")
        rr.set_call_number("5 Mi 999 R 1")
        rr.set_media_type(SourceMediaType.BOOK)
        src.add_repo_reference(rr)
        src.add_attribute(attr("URL", "https://archives.example/registre/1", SrcAttribute))
        ajouter(src, "source01", "S0001", "add_source")
        cit = Citation()
        cit.set_reference_handle("source01")
        cit.set_page("vue 12, acte 3")
        cit.set_confidence_level(Citation.CONF_HIGH)
        ajouter(cit, "citati01", "C0001", "add_citation")
        pays, dep, ville = Place(), Place(), Place()
        for p, nom, typ, h, gid in ((pays, "France", PlaceType.COUNTRY, "lieu0001", "P0001"),
                                    (dep, "Nord", PlaceType.DEPARTMENT, "lieu0002", "P0002"),
                                    (ville, "Villefictive", PlaceType.CITY, "lieu0003", "P0003")):
            n = PlaceName()
            n.set_value(nom)
            p.set_name(n)
            p.set_type(typ)
            p.set_handle(h)
            p.set_gramps_id(gid)
        for enfant, parent in ((dep, "lieu0001"), (ville, "lieu0002")):
            ref = PlaceRef()
            ref.set_reference_handle(parent)
            enfant.add_placeref(ref)
        ville.set_latitude("50.5")
        ville.set_longitude("3.1")
        for p in (pays, dep, ville):
            db.add_place(p, t)
        note_auto = Note("Preuve : généré par Genealogiste (doit être ignoré à l'import).")
        note_auto.add_tag("tagauto")
        ajouter(note_auto, "note0001", "N0001", "add_note")
        note = Note()
        note.set_styledtext(StyledText("Laboureur, cité au rôle de taille.",
                                       [StyledTextTag(StyledTextTagType(StyledTextTagType.BOLD), None, [(0, 9)])]))
        note.set_type(NoteType.PERSON)
        ajouter(note, "note0002", "N0002", "add_note")

        def evenement(h, gid, typ, d, lieu="lieu0003", attrs=(), cit_=True, prive=False):
            e = Event()
            e.set_type(typ)
            e.set_date_object(d)
            e.set_place_handle(lieu)
            e.set_privacy(prive)
            for a in attrs:
                e.add_attribute(a)
            if cit_:
                e.add_citation("citati01")
            return ajouter(e, h, gid, "add_event")

        evenement("even0001", "E0001", EventType.BIRTH, date(1750, 3, 12))
        evenement("even0002", "E0002", EventType.DEATH, date(1810, mod=Date.MOD_ABOUT))
        evenement("even0003", "E0003", EventType.BIRTH, date(1755, 6, 1, cal=Date.CAL_JULIAN))
        evenement("even0004", "E0004", EventType.BIRTH, date(8, 3, 12, cal=Date.CAL_FRENCH),
                  attrs=[attr("Sosa-Statut", "contradictoire | deux dates dans les sources")])
        evenement("even0005", "E0005", EventType.MARRIAGE, date(1775, 1, 20),
                  attrs=[attr("Genealogiste-UID", "uid-mariage-fictif")])

        def personne(h, gid, prenom, nom, genre, refs, attrs=(), prive=False):
            p = Person()
            n = Name()
            n.set_first_name(prenom)
            s = Surname()
            s.set_surname(nom)
            n.add_surname(s)
            n.set_type(NameType.BIRTH)
            p.set_primary_name(n)
            p.set_gender(genre)
            p.set_privacy(prive)
            for eh, role in refs:
                r = EventRef()
                r.set_reference_handle(eh)
                r.set_role(role)
                p.add_event_ref(r)
            for a in attrs:
                p.add_attribute(a)
            return p, h, gid

        jean, *_ = personne("pers0001", "I0001", "Jean", "DUPONT", Person.MALE,
                            [("even0001", EventRoleType.PRIMARY), ("even0002", EventRoleType.PRIMARY)],
                            [attr("Genealogiste-UID", "uid-jean-fictif")])
        jean.get_primary_name().set_suffix("l'aîné")
        alt = Name()
        alt.set_first_name("Jehan")
        s = Surname()
        s.set_surname("DUPOND")
        alt.add_surname(s)
        alt.set_type(NameType.AKA)
        alt.set_date_object(date(1770))
        jean.add_alternate_name(alt)
        jean.add_tag("tagverif")
        jean.add_note("note0002")
        jean.add_note("note0001")
        jean.add_citation("citati01")
        url = Url()
        url.set_path("https://exemple.example/jean")
        url.set_type(UrlType.WEB_HOME)
        jean.add_url(url)
        adr = Address()
        adr.set_street("rue Fictive")
        adr.set_city("Villefictive")
        jean.add_address(adr)
        mref = MediaRef()
        mref.set_reference_handle("media001")
        jean.add_media_reference(mref)
        marie, *_ = personne("pers0002", "I0002", "Marie", "MARTIN", Person.FEMALE,
                             [("even0003", EventRoleType.PRIMARY)], [attr("Sosa-UID", "uid-marie-fictif")],
                             prive=True)
        pierre, *_ = personne("pers0003", "I0003", "Pierre", "DUPONT", Person.MALE,
                              [("even0004", EventRoleType.PRIMARY)])
        paul, *_ = personne("pers0004", "I0004", "Paul", "LEROY", Person.MALE,
                            [("even0005", EventRoleType.WITNESS)])
        pref = PersonRef()
        pref.set_reference_handle("pers0004")
        pref.set_relation("Parrain")
        pierre.add_person_ref(pref)
        media = Media()
        media.set_path(MEDIA_GENERE)
        media.set_mime_type("image/jpeg")
        media.set_description("Acte fictif")
        ajouter(media, "media001", "O0001", "add_media")
        fam = Family()
        fam.set_father_handle("pers0001")
        fam.set_mother_handle("pers0002")
        fam.set_relationship(FamilyRelType.MARRIED)
        r = EventRef()
        r.set_reference_handle("even0005")
        r.set_role(EventRoleType.FAMILY)
        fam.add_event_ref(r)
        cr = ChildRef()
        cr.set_reference_handle("pers0003")
        fam.add_child_ref(cr)
        fam.add_attribute(attr("Sosa-Statut filiation I0003", "probable | ressemblance des signatures"))
        jean.add_family_handle("fami0001")
        marie.add_family_handle("fami0001")
        pierre.add_parent_family_handle("fami0001")
        for p, h, gid in ((jean, "pers0001", "I0001"), (marie, "pers0002", "I0002"), (pierre, "pers0003", "I0003"),
                          (paul, "pers0004", "I0004")):
            ajouter(p, h, gid, "add_person")
        ajouter(fam, "fami0001", "F0001", "add_family")
    sortie = {}
    gramps = os.path.join(dossier, "famille.gramps")
    XmlWriter(db, user, 0, 1).write(gramps)  # compress=1 : comme l'export par défaut de Gramps Desktop
    sortie["famille.gramps"] = gramps
    gpkg = os.path.join(dossier, "famille.gpkg")
    import tarfile

    tarfile.pwd = tarfile.grp = None  # noms d'utilisateur et de groupe de la machine hors du paquet (fixtures)
    if not PackageWriter(db, gpkg, user).export():
        raise RuntimeError("PackageWriter : échec")
    sortie["famille.gpkg"] = gpkg
    db.close()
    return sortie


def dates_reference(chemin: str) -> dict:
    """Formes de date de l'inventaire #272 (fichier JSON [[nom, Date JSON], …]) soumises à la bibliothèque :
    ``Date.set`` (acceptée ou DateError), valeur de tri calculée, affichage anglais au format ISO par défaut
    (``DateDisplayEn``). Une date textuelle passe par ``set(modifier=MOD_TEXTONLY, text=…)``."""
    from gramps.gen.datehandler._datedisplay import DateDisplayEn
    from gramps.gen.errors import DateError
    from gramps.gen.lib import Date

    affichage = DateDisplayEn()
    out = {}
    with open(chemin, encoding="utf-8") as f:
        formes = json.load(f)
    for nom, d in formes:
        x = Date()
        ny = d["newyear"]
        try:
            if d["modifier"] == Date.MOD_TEXTONLY:
                x.set(modifier=Date.MOD_TEXTONLY, text=d["text"])
            else:
                x.set(d["quality"], d["modifier"], d["calendar"], tuple(d["dateval"]),
                      newyear=tuple(ny) if isinstance(ny, list) else ny)
        except DateError:
            out[nom] = {"acceptee": False}
            continue
        out[nom] = {"acceptee": True, "sortval": x.sortval, "affichage": affichage.display(x),
                    "calendar": x.calendar, "dateval": list(x.dateval)}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rapport", required=True)
    parser.add_argument("--reexporter", help="dossier où réécrire chaque fichier importé (Gramps XML)")
    parser.add_argument("--generer", help="dossier où écrire l'arbre fictif exporté par Gramps (.gramps, .gpkg)")
    parser.add_argument("--dates", help="inventaire de formes de date (JSON) : Date.set, tri et affichage (#272)")
    parser.add_argument("fichiers", nargs="*")
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

    fichiers = list(args.fichiers)
    if args.dates:
        rapport["dates"] = dates_reference(args.dates)
    if args.generer:
        user = Utilisateur()
        try:
            rapport["generes"] = generer(args.generer, user)
            fichiers += list(rapport["generes"].values())  # relus aussi : objets de référence
        except Exception:  # noqa: BLE001
            user.erreurs.append(traceback.format_exc(limit=5))
        rapport["generation"] = {"erreurs": user.erreurs, "avertissements": user.avertissements}
    for chemin in fichiers:
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
