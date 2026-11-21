"""#280 : chemin de base des médias aligné entre le vault, Gramps Desktop et Gramps Web.

- règle de résolution (bilan par cause, confinement aux racines autorisées) ;
- export Gramps XML : ``<mediapath>`` seulement à la demande, chemins relatifs à cette base, sortie par défaut inchangée ;
- import : ``<mediapath>`` d'un fichier tiers rapporté, jamais utilisé ;
- diagnostic : médias dont le chemin ne se résout pas, sans donnée personnelle.
Fixtures synthétiques, aucun accès réseau."""

from __future__ import annotations

import gzip
import hashlib
import re
import shutil
import tarfile
from datetime import date
from pathlib import Path

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app

from genealogiste_mcp import diagnostic, server
from genealogiste_mcp.chemins import LIMITE_MEDIAS, bilan_chemins_medias
from genealogiste_mcp.config import Config
from genealogiste_mcp.export import gramps_xml
from genealogiste_mcp.gedcom.mapping import read_gedcom
from genealogiste_mcp.gramps import lecture_xml as lx
from genealogiste_mcp.gramps.mapping import tree_to_gramps
from genealogiste_mcp.models import Media

ACTE = "documents/État civil/MARTIN/MARTIN Jean -- N [1820].jpg"
JPEG = b"\xff\xd8\xff\xe0image-fictive-acte\xff\xd9"


def _ecrire(p: Path, contenu: bytes = JPEG) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenu)
    return p


@pytest.fixture(autouse=True)
def sans_internet(monkeypatch):
    monkeypatch.setattr(diagnostic, "SOURCES", {})


@pytest.fixture
def vapp(tmp_path, fixtures):
    """Application avec un vault (arborescence des pièces) distinct du répertoire de données."""
    vault = tmp_path / "vault"
    c = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", notes_dir=vault,
               media_dir_conf=vault / "documents")
    a = server.App(c, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    a.notes.today = lambda: date(2026, 11, 4)
    a.vault = vault
    yield a
    server.set_app(None)


def _medias(a, **medias: str) -> None:
    """Médias de l'arbre : identifiant -> fichier ; rattachés à la personne I1 (défunte)."""
    t = a.store.load()
    for mid, fichier in medias.items():
        t.medias[mid] = Media(id=mid, fichier=fichier, titre=f"Titre secret {mid}")
        t.personnes["I1"].medias.append(mid)
    a.store.write(t)
    a.store.commit("medias")


# ---------------------------------------------------------------- bilan de résolution

def test_bilan_par_cause_et_echantillon(tmp_path):
    data, vault = tmp_path / "donnees", tmp_path / "vault"
    _ecrire(vault / ACTE)
    _ecrire(vault / "documents" / "a.jpg", b"A")
    _ecrire(data / "documents" / "a.jpg", b"B")  # même chemin relatif sous deux racines, contenus différents
    racines = (data, vault / "documents", vault)
    entrees = [("O1", ACTE), ("O2", "documents/absent.jpg"), ("O3", "documents/a.jpg"), ("O4", "/etc/hostname"),
               ("O5", "../../x.jpg"), ("O6", "https://exemple.org/i.jpg"), ("O7", ""), ("O8", r"C:\Users\x\a.jpg"),
               ("O9", "0123456789abcdef0123456789abcdef.jpeg"), ("O10", str(vault / ACTE))]
    b = bilan_chemins_medias(entrees, racines, vault)
    assert b["total"] == 10 and b["resolus"] == 2 and b["desktop_direct"] == 1  # O10 : absolu, pas « direct »
    assert (b["introuvables"], b["ambigus"], b["hors_racines"], b["nom_serveur"]) == (1, 1, 3, 1)
    assert (b["distants"], b["sans_chemin"], b["absolus"]) == (1, 1, 3)
    assert b["echantillon"] == {"introuvables": ["O2"], "ambigus": ["O3"], "hors_racines": ["O4", "O5", "O8"],
                                "nom_serveur": ["O9"]}


def test_bilan_borne_et_echantillon_limites(tmp_path):
    racines = (tmp_path,)
    entrees = [(f"O{i}", f"absent-{i}.jpg") for i in range(LIMITE_MEDIAS + 50)]
    b = bilan_chemins_medias(entrees, racines)
    assert b["examines"] == LIMITE_MEDIAS and b["non_verifies"] == 50 and b["introuvables"] == LIMITE_MEDIAS
    assert len(b["echantillon"]["introuvables"]) == 10


def test_bilan_ne_lit_aucun_fichier_hors_ambiguite(tmp_path, monkeypatch):
    f = _ecrire(tmp_path / "x.jpg")
    lus = []
    monkeypatch.setattr(Path, "read_bytes", lambda self: lus.append(self) or b"")
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: lus.append(self))
    b = bilan_chemins_medias([("O1", "x.jpg"), ("O2", str(f))], (tmp_path,), tmp_path)
    assert b["resolus"] == 2 and not lus


@pytest.mark.parametrize("hostile", ["~inconnu_zz_280/x.jpg", "a\0b.jpg", "x" * 5000 + ".jpg", "\\\\nas\\v\\a.jpg"])
def test_bilan_chemin_inutilisable_d_un_fichier_tiers_ne_plante_pas(tmp_path, hostile):
    """Chemin d'un fichier tiers inutilisable (utilisateur inconnu, octet nul, nom trop long, UNC) : compté « hors
    des racines », jamais lu, sans exception."""
    b = bilan_chemins_medias([("O1", hostile), ("O2", "ok.jpg")], (tmp_path,), tmp_path)
    assert b["hors_racines"] == 1 and b["introuvables"] == 1 and b["resolus"] == 0
    assert b["echantillon"]["hors_racines"] == ["O1"]


def test_import_chemins_hostiles_ne_font_pas_echouer_l_import(vapp, tmp_path):
    f = _fichier_gramps(tmp_path, "/etc", ["~inconnu_zz_280/x.jpg", "x" * 5000 + ".jpg", "documents/ok.jpg"])
    p = server.arbre_importer_gedcom(str(f), "remplacer")
    assert "erreur" not in p, p
    r = p["import"]["medias"]["resolution"]
    assert (r["total"], r["hors_racines"], r["introuvables"]) == (3, 2, 1)


def test_bilan_lien_sortant_hors_racines(tmp_path):
    vault = tmp_path / "vault"
    dehors = _ecrire(tmp_path / "dehors.jpg", b"secret")
    (vault / "documents").mkdir(parents=True)
    (vault / "documents" / "lien.jpg").symlink_to(dehors)
    b = bilan_chemins_medias([("O1", "documents/lien.jpg")], (vault,), vault)
    assert b["hors_racines"] == 1 and b["resolus"] == 0


# ---------------------------------------------------------------- export : <mediapath> à la demande

def _xml(chemin: Path) -> str:
    brut = chemin.read_bytes()
    return (gzip.decompress(brut) if brut[:2] == b"\x1f\x8b" else brut).decode("utf-8")


def test_export_par_defaut_sans_mediapath_ni_chemin_de_la_machine(vapp, tmp_path):
    _ecrire(vapp.vault / ACTE)
    _medias(vapp, O1=ACTE)
    sortie = tmp_path / "defaut.gramps"
    r = server.arbre_exporter("gramps", str(sortie))
    xml = _xml(sortie)
    assert "erreur" not in r and "<mediapath>" not in xml and "chemin_base_medias" not in r
    assert str(vapp.vault) not in xml and str(tmp_path) not in xml
    assert f'<file src="{ACTE}"' in xml  # chemin relatif à l'arborescence des pièces, tel qu'enregistré


def _stable(xml: str) -> str:
    """XML sans le seul élément aléatoire de l'export (UID de noms tiré à chaque appel, hors périmètre de #280)."""
    return re.sub(r'(Genealogiste-UID noms" value=")[^"]*', r"\1-", xml)


def test_export_parametre_vide_identique_au_defaut(vapp, tmp_path):
    """Appel existant (sans le paramètre) et paramètre vide : même fichier, octet pour octet une fois masqués les
    UID de noms que chaque export tire au hasard (Genealogiste-UID noms, hors périmètre)."""
    _ecrire(vapp.vault / ACTE)
    _medias(vapp, O1=ACTE)
    a, b = tmp_path / "a.gramps", tmp_path / "b.gramps"
    server.arbre_exporter("gramps", str(a))
    server.arbre_exporter("gramps", str(b), chemin_base_medias="")
    assert _stable(_xml(a)).encode() == _stable(_xml(b)).encode() and b"<mediapath" not in _xml(a).encode()
    g1, g2 = tmp_path / "a.gpkg", tmp_path / "b.gpkg"
    server.arbre_exporter("gpkg", str(g1))
    server.arbre_exporter("gpkg", str(g2), chemin_base_medias="")

    def lire(chemin):
        with tarfile.open(chemin, "r:gz") as tar:
            return {m.name: tar.extractfile(m).read() for m in tar.getmembers()}
    p1, p2 = lire(g1), lire(g2)
    assert set(p1) == set(p2)
    for nom in p1:
        if nom == "data.gramps":
            assert _stable(gzip.decompress(p1[nom]).decode()) == _stable(gzip.decompress(p2[nom]).decode())
        else:
            assert p1[nom] == p2[nom]


def test_export_ecrit_mediapath_et_chemins_relatifs_a_la_base(vapp, tmp_path):
    _ecrire(vapp.vault / ACTE)
    _ecrire(vapp.vault / "photographies" / "p.jpg")
    _ecrire(vapp.config.data_dir / "medias" / "interne.jpg")  # hors de la base (dans les données)
    _medias(vapp, O1=str((vapp.vault / ACTE).resolve()), O2="photographies/p.jpg", O3="medias/interne.jpg",
            O4="medias/absent.jpg", O5="https://archives.example/v.jpg")
    defaut, sortie = tmp_path / "d.gramps", tmp_path / "x.gramps"
    server.arbre_exporter("gramps", str(defaut), masquer_vivants=False)
    r = server.arbre_exporter("gramps", str(sortie), masquer_vivants=False, chemin_base_medias="/mnt/nextcloud/vault/")
    assert "erreur" not in r, r
    xml, ref = _xml(sortie), _xml(defaut)
    # seul changement du fichier : l'élément <mediapath> de l'en-tête et les chemins qui deviennent relatifs
    assert "<mediapath>/mnt/nextcloud/vault</mediapath></header>" in xml and "<mediapath>" not in ref
    assert f'<file src="{ACTE}"' in xml and 'src="photographies/p.jpg"' in xml
    assert str(vapp.vault) not in xml  # le chemin absolu de ce poste n'est plus dans le fichier
    assert 'src="medias/interne.jpg"' in xml and 'src="medias/absent.jpg"' in xml  # inchangés
    assert r["chemin_base_medias"]["ecrit"] == "/mnt/nextcloud/vault"
    m = r["chemin_base_medias"]["medias"]
    assert m == {"relatifs": 2, "distants": 1, "hors_base": ["O3"], "introuvables": ["O4"], "refuses": []}


def test_export_mediapath_relu_par_le_lecteur_et_aller_retour(vapp, tmp_path):
    _ecrire(vapp.vault / ACTE)
    _medias(vapp, O1=ACTE)
    sortie = tmp_path / "x.gramps"
    server.arbre_exporter("gramps", str(sortie), masquer_vivants=False, chemin_base_medias="D:\\Nextcloud\\vault")
    lu = lx.lire_xml(sortie.read_bytes())
    assert lu.meta.mediapath == "D:\\Nextcloud\\vault"


@pytest.mark.parametrize("valeur", ["relatif/vault", "~/vault", "vault", "/a/../b", "/a/{GRAMPS_RESOURCES}",
                                    "/a\nb", "/a\0b", " /a", "/a ", "C:vault", "{USER_HOME}/vault"])
def test_export_chemin_base_invalide_refuse(vapp, tmp_path, valeur):
    sortie = tmp_path / "x.gramps"
    r = server.arbre_exporter("gramps", str(sortie), masquer_vivants=False, chemin_base_medias=valeur)
    assert "chemin_base_medias" in r["erreur"] and not sortie.exists()


@pytest.mark.parametrize("valeur,attendu", [("/", "/"), ("/a/b//", "/a/b"), ("C:\\", "C:\\"), ("C:/vault/", "C:/vault"),
                                            ("\\\\nas\\vault\\", "\\\\nas\\vault")])
def test_chemin_base_valide_normalise(valeur, attendu):
    assert gramps_xml.verifier_chemin_base_medias(valeur) == attendu


def test_export_public_refuse_le_chemin_personnel(vapp, tmp_path):
    sortie = tmp_path / "x.gramps"
    r = server.arbre_exporter("gramps", str(sortie), chemin_base_medias="/mnt/vault")  # masquer_vivants=True
    assert "public" in r["erreur"] and not sortie.exists()


@pytest.mark.parametrize("fmt", ["gpkg", "gedcom7", "geneweb"])
def test_chemin_base_refuse_hors_format_gramps(vapp, tmp_path, fmt):
    sortie = tmp_path / f"x.{fmt}"
    r = server.arbre_exporter(fmt, str(sortie), masquer_vivants=False, chemin_base_medias="/mnt/vault")
    assert "format gramps seulement" in r["erreur"] and not sortie.exists()
    if fmt == "gpkg":
        assert "gpkg.media" in r["erreur"]


def test_gpkg_n_ecrit_jamais_le_mediapath_de_la_machine(vapp, tmp_path):
    _ecrire(vapp.vault / ACTE)
    _medias(vapp, O1=ACTE)
    sortie = tmp_path / "x.gpkg"
    server.arbre_exporter("gpkg", str(sortie))
    with tarfile.open(sortie, "r:gz") as tar:
        xml = gzip.decompress(tar.extractfile("data.gramps").read()).decode()
    assert "<mediapath>" not in xml and str(vapp.vault) not in xml


# ---------------------------------------------------------------- import : <mediapath> tiers

def _fichier_gramps(tmp_path: Path, mediapath: str | None, chemins: list[str]) -> Path:
    tree = read_gedcom((Path(__file__).parent / "fixtures" / "famille.ged").read_text(encoding="utf-8"))[0]
    for i, c in enumerate(chemins):
        tree.medias[f"O{i + 1}"] = Media(id=f"O{i + 1}", fichier=c, titre="Acte")
    db = tree_to_gramps(tree)
    f = tmp_path / "tiers.gramps"
    f.write_text(gramps_xml.db_to_xml(db, "1.7.1", gramps_xml.Metadonnees(mediapath=mediapath)), encoding="utf-8")
    return f


def test_import_rapporte_mediapath_et_resolution_sans_rien_modifier(vapp, tmp_path):
    _ecrire(vapp.vault / ACTE)
    f = _fichier_gramps(tmp_path, str(vapp.vault), [ACTE, "documents/absent.jpg", "/etc/hostname"])
    avant = (vapp.config.media_dir_conf, vapp.config.data_dir)
    p = server.arbre_importer_gedcom(str(f), "remplacer")
    assert "erreur" not in p, p
    med = p["import"]["medias"]
    assert med["mediapath"]["valeur"] == str(vapp.vault) and med["mediapath"]["correspond_au_vault"] is True
    assert "jamais utilisé" in med["mediapath"]["usage"]
    r = med["resolution"]
    assert (r["total"], r["resolus"], r["desktop_direct"], r["introuvables"], r["hors_racines"]) == (3, 1, 1, 1, 1)
    assert r["echantillon"] == {"introuvables": ["O2"], "hors_racines": ["O3"]}
    assert (vapp.config.media_dir_conf, vapp.config.data_dir) == avant  # configuration inchangée
    assert not any("/etc" in str(v) for v in r["echantillon"].values())  # jamais un chemin dans le bilan


def test_import_sans_mediapath(vapp, tmp_path):
    f = _fichier_gramps(tmp_path, None, ["documents/x.jpg"])
    med = server.arbre_importer_gedcom(str(f), "remplacer")["import"]["medias"]
    assert med["mediapath"] is None and med["resolution"]["introuvables"] == 1


@pytest.mark.parametrize("hostile", ["/etc", "..", "../../..", "/", "C:\\Windows", "{GRAMPS_RESOURCES}/../.."])
def test_mediapath_hostile_jamais_utilise_pour_lire(vapp, tmp_path, monkeypatch, hostile):
    """Le mediapath d'un fichier tiers est une donnée non fiable : un média « hostname » ou « passwd » ne se résout
    pas sous lui, et aucun fichier hors des racines n'est ouvert."""
    f = _fichier_gramps(tmp_path, hostile, ["hostname", "passwd", "../etc/passwd"])
    ouverts: list[str] = []
    orig = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda self: ouverts.append(str(self)) or orig(self))
    p = server.arbre_importer_gedcom(str(f), "remplacer")
    assert "erreur" not in p, p
    med = p["import"]["medias"]
    assert med["mediapath"]["valeur"] == hostile[:300] and med["mediapath"]["correspond_au_vault"] is False
    assert med["resolution"]["resolus"] == 0
    assert not [o for o in ouverts if o.startswith("/etc") or "/etc/" in o and "vault" not in o]


def test_mediapath_non_imprimable_et_long_nettoye():
    r = lx.rapport_mediapath("/a\x00b\n" + "x" * 500)
    assert "\x00" not in r["valeur"] and "\n" not in r["valeur"] and len(r["valeur"]) == 300
    assert lx.rapport_mediapath("   ") is None


def test_import_gpkg_rapporte_aussi_la_resolution(vapp):
    desktop = Path(__file__).parent / "fixtures" / "gramps-desktop"
    p = server.arbre_importer_gedcom(str(desktop / "gramps-6.0" / "famille.gpkg"), "remplacer")
    med = p["import"]["medias"]
    assert med["resolution"]["total"] == 1 and med["resolution"]["resolus"] == 1  # extrait en zone d'attente


# ---------------------------------------------------------------- diagnostic

def _ctl(res: dict, nom: str) -> dict | None:
    return next((c for c in res["controles"] if c["controle"] == nom), None)


def test_diagnostic_mode_fichier_medias_ok(vapp):
    _ecrire(vapp.vault / ACTE)
    _medias(vapp, O1=ACTE)
    c = _ctl(server.diagnostic(reseau=False), "medias_chemins")
    assert c["etat"] == "ok" and "1 chemin(s) résolu(s) sur 1" in c["detail"] and c["bilan"]["desktop_direct"] == 1


def test_diagnostic_mode_fichier_causes_sans_donnee_personnelle(vapp, tmp_path):
    _ecrire(vapp.vault / ACTE)
    _ecrire(vapp.vault / "documents" / "a.jpg", b"A")
    _ecrire(vapp.config.data_dir / "documents" / "a.jpg", b"B")
    _medias(vapp, O1=ACTE, O2="documents/absent.jpg", O3="documents/a.jpg", O4="/etc/hostname", O5="../../dehors.jpg")
    res = server.diagnostic(reseau=False)
    c = _ctl(res, "medias_chemins")
    assert c["etat"] == "attention" and c["remede"]
    assert c["bilan"]["introuvables"] == 1 and c["bilan"]["ambigus"] == 1 and c["bilan"]["hors_racines"] == 2
    assert c["bilan"]["echantillon"]["hors_racines"] == ["O4", "O5"]
    sortie = repr(c)
    for secret in ("Titre secret", "MARTIN", "Jean", str(tmp_path), "/etc/hostname", "dehors.jpg"):
        assert secret not in sortie
    assert res["etat"] in ("attention", "erreur")


def test_diagnostic_sans_media(vapp):
    c = _ctl(server.diagnostic(reseau=False), "medias_chemins")
    assert c["etat"] == "ok" and "aucun média" in c["detail"]


@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


def test_diagnostic_mode_gramps_chemin_serveur_et_attribut(tmp_path, fake, tree):
    """Média envoyé par le plugin (chemin du serveur = somme.ext, attribut Genealogiste-Fichier relatif) : résolu ;
    média créé dans l'interface de Gramps Web (aucun attribut) : nom attribué par le serveur, sans fichier ici."""
    vault = tmp_path / "vault"
    _ecrire(vault / ACTE)
    md5 = hashlib.md5(JPEG).hexdigest()
    tree.medias["O1"] = Media(id="O1", fichier=ACTE, format="image/jpeg", titre="Acte")
    tree.medias["O2"] = Media(id="O2", fichier="documents/absent.jpg", format="image/jpeg", titre="Acte absent")
    db = tree_to_gramps(tree)
    for m in db.all("Media").values():
        m.update(checksum=md5, path=f"{md5}.jpeg")  # chemin et somme attribués par le serveur après l'envoi
    web = {"handle": "webmedia000000001", "gramps_id": "O7", "path": "ffffffffffffffffffffffffffffffff.png",
           "mime": "image/png", "checksum": "f" * 32, "desc": "Titre secret web", "attribute_list": [],
           "citation_list": [], "note_list": [], "tag_list": [], "private": False, "date": None,
           "_class": "Media", "change": 1}
    for objs in db.objects.values():
        for o in objs.values():
            fake.put(o)
    fake.put(web)
    a = make_app(tmp_path)
    a.config = Config(**{**a.config.__dict__, "media_dir_conf": vault / "documents", "notes_dir": vault})
    try:
        res = server.diagnostic()
        assert a.backend.db is None  # lecture ciblée des médias : l'arbre entier n'est pas chargé
    finally:
        server.set_app(None)
    c = _ctl(res, "gramps_medias_chemins")
    assert c is not None and _ctl(res, "medias_chemins") is None
    assert c["etat"] == "attention"
    b = c["bilan"]
    assert (b["total"], b["resolus"], b["desktop_direct"], b["introuvables"], b["nom_serveur"]) == (3, 1, 1, 1, 1)
    assert b["echantillon"] == {"introuvables": ["O2"], "nom_serveur": ["O7"]}
    assert "Titre secret" not in repr(c)
