"""Organisation d'un dossier de pièces (#60) : convention de nommage, inventaire, plan de classement,
application réversible.

Principes :
- rien n'est déplacé sans plan accepté (jeton, comme arbre_proposer) ; jamais de suppression ;
- doublons (même SHA-256) isolés dans archives/Doublons/ ;
- journal TSV ancien_chemin → nouveau_chemin écrit au fil des déplacements (annulation) ;
- noms compatibles Windows et Nextcloud ;
- notes générées (personnes/, familles/, sources/, patronymes/), dossiers cachés et notes Markdown jamais touchés ;
- contrôle avant/après : même nombre de fichiers, mêmes empreintes.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .chemins import CheminRefuse, sous

# ---------------------------------------------------------------- convention de nommage

INTERDITS = re.compile(r'[?:*"<>|/\\\x00-\x1f]')
RESERVES_WINDOWS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_NOM = 200  # marge sous la limite de 255 octets de la plupart des systèmes de fichiers


class PieceError(ValueError):
    pass


def nom_compatible(nom: str) -> str:
    """Nom de fichier valable sous Windows et Nextcloud : caractères interdits remplacés, pas d'espace ni de
    point final, pas de nom réservé, longueur bornée (extension conservée)."""
    stem, ext = os.path.splitext(nom.strip())
    stem = INTERDITS.sub("-", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    ext = INTERDITS.sub("", ext).strip(" ")
    if not stem:
        stem = "piece"
    if stem.split(".")[0].upper() in RESERVES_WINDOWS:
        stem = f"_{stem}"
    budget = MAX_NOM - len(ext.encode())
    while len(stem.encode()) > budget:
        stem = stem[:-1]
    return stem.rstrip(" .") + ext.lower()


def _part(v: str) -> str:
    return re.sub(r"\s+", " ", INTERDITS.sub("-", str(v or ""))).strip(" .-")


def _personne(p) -> str:
    if isinstance(p, dict):
        nom, prenom = _part(p.get("nom", "")).upper(), _part(p.get("prenom", "") or p.get("prenoms", ""))
        return f"{nom} {prenom}".strip()
    return _part(p)


def nommer(personnes: list, commune: str = "", depot: str = "", type_piece: str = "", annees: str = "",
           cote: str = "", vue: str = "", acte: str = "", extension: str = "") -> str:
    """NOM Prénom[ + NOM Prénom] -- COMMUNE - DÉPÔT - TYPE [AAAA-AAAA] - cote - p.vue n.acte.ext
    (segments absents omis)."""
    noms = [n for n in (_personne(p) for p in personnes or []) if n]
    if not noms:
        raise PieceError("Au moins une personne (NOM Prénom) est nécessaire.")
    segs = []
    if commune:
        segs.append(_part(commune).upper())
    if depot:
        segs.append(_part(depot))
    t = _part(type_piece).upper()
    a = _part(annees).strip("[]")
    if t or a:
        segs.append(f"{t} [{a}]".strip() if a else t)
    if cote:
        segs.append(_part(cote))
    loc = " ".join(x for x in (f"p.{_part(vue)}" if vue else "", f"n.{_part(acte)}" if acte else "") if x)
    if loc:
        segs.append(loc)
    ext = extension if not extension or extension.startswith(".") else f".{extension}"
    base = " + ".join(noms) + (" -- " + " - ".join(segs) if segs else "")
    return nom_compatible(base + ext.lower())


_TYPE_SEG = re.compile(r"^(?P<type>[A-ZÀ-Ü0-9 ]*?)\s*(?:\[(?P<annees>[\d\s\-–]+)\])?$")


def _est_type(seg: str) -> bool:
    m = _TYPE_SEG.match(seg)
    if not m:
        return False
    code = (m.group("type") or "").split()
    return bool(m.group("annees")) or bool(code and code[0] in _CODES_CONVENTION)


def lire_nom(nom: str) -> dict:
    """Inverse (tolérant) de nommer : personnes, patronyme, commune, dépôt, type, années, cote, vue, acte."""
    stem = os.path.splitext(nom)[0]
    out: dict = {"personnes": [], "patronyme": ""}
    if " -- " not in stem:
        return out
    tete, reste = stem.split(" -- ", 1)
    out["personnes"] = [p.strip() for p in tete.split(" + ") if p.strip()]
    m = re.match(r"([A-ZÀ-Ü][A-ZÀ-Ü'\- ]*[A-ZÀ-Ü])(?:\s|$)", out["personnes"][0]) if out["personnes"] else None
    out["patronyme"] = m.group(1).strip() if m else ""
    segs = [s.strip() for s in reste.split(" - ")]
    if segs and re.match(r"^(p\.\S+)?\s*(n\.\S+)?$", segs[-1]) and segs[-1]:
        loc = segs.pop()
        if v := re.search(r"p\.(\S+)", loc):
            out["vue"] = v.group(1)
        if a := re.search(r"n\.(\S+)", loc):
            out["acte"] = a.group(1)
    # le segment TYPE [années] sert de repère : avant lui commune puis dépôt, après lui la cote
    i = next((k for k, seg in enumerate(segs) if _est_type(seg)), None)
    avant, apres = (segs, []) if i is None else (segs[:i], segs[i + 1:])
    if i is not None:
        m = _TYPE_SEG.match(segs[i])
        out["type"] = (m.group("type") or "").strip()
        if m.group("annees"):
            out["annees"] = m.group("annees").strip()
    for key, val in zip(("commune", "depot"), avant[:2], strict=False):
        out[key] = val
    reste = avant[2:] + apres
    if reste:
        out["cote"] = " - ".join(reste)
    return out


# ---------------------------------------------------------------- types de pièces et classement

IMAGES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif", ".webp", ".heic", ".bmp", ".jp2"}
AUDIO = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus", ".wma"}
VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
DOCS = {".pdf", ".djvu"}
GENEWEB = {".gw", ".gwf", ".gwo"}
GEDCOM = {".ged", ".gedcom"}
DONNEES = {".txt", ".csv"}  # retenus seulement s'ils ressemblent à un fichier brut INSEE

# code -> (libellé, dossier sous documents/)
TYPES = {
    "N": ("naissance", "État civil"), "B": ("baptême", "État civil"), "M": ("mariage", "État civil"),
    "D": ("décès", "État civil"), "S": ("sépulture", "État civil"), "NMD": ("registre NMD", "État civil"),
    "BMS": ("registre BMS", "État civil"), "TD": ("tables décennales", "État civil"),
    "RM": ("registre matricule", "Militaire"), "ANMT": ("fiche de mineur (ANMT)", "Mines (ANMT)"),
    "REC": ("recensement", "Divers"), "SIGN": ("signature", "Signatures"),
    "AUDIO": ("témoignage oral", "Témoignages oraux"), "PHOTO": ("photographie", None),
    "TOMBE": ("sépulture (photo)", None), "LIEU": ("lieu (photo)", None), "CAPTURE": ("capture d'arbre en ligne", "Divers"),
    "GENEWEB": ("base GeneWeb", None), "GEDCOM": ("fichier GEDCOM", None), "INSEE": ("fichier brut INSEE", None),
}

_MOTS = [  # (motif sur nom normalisé, code) — le premier qui correspond l'emporte
    (r"\b(nmd)\b", "NMD"), (r"\b(bms)\b", "BMS"),
    (r"\b(td|tables? decennales?)\b", "TD"),
    (r"\b(registre matricule|fiche matricule|matricule|recrutement)\b", "RM"),
    (r"\b(anmt|mineur|houilleres?)\b", "ANMT"),
    (r"\b(recensements?)\b", "REC"),
    (r"\b(signatures?)\b", "SIGN"),
    (r"\b(capture d ecran|screenshot|capture|geneanet|filae|myheritage|familysearch)\b", "CAPTURE"),
    (r"\b(tombe|tombes|sepultures? photo|cimetiere|findagrave|find a grave|grave)\b", "TOMBE"),
    (r"\b(naissances?|nais|naiss)\b", "N"), (r"\b(baptemes?|bapt)\b", "B"),
    (r"\b(mariages?)\b", "M"), (r"\b(deces|dc)\b", "D"), (r"\b(sepultures?|inhumations?)\b", "S"),
    (r"\b(photos?|portraits?|photographies?)\b", "PHOTO"),
]
_CODES_CONVENTION = {c for c in TYPES} | {"NM", "ND", "MD"}
_PAS_PATRONYME = {*TYPES, "AD", "AM", "AN", "SHD", "ANMT", "NMD", "BMS", "TD", "IMG", "DSC", "DCIM", "SCAN",
                  "PDF", "JPG", "PNG", "COPIE", "COPY", "PXL", "WA", "VID", "PAGE", "VUE", "ACTE", "NOUVEAU"}
_PROTEGES = {"personnes", "familles", "sources", "patronymes", "_organisation"}
CLASSES = ("documents", "photographies", "archives")
A_TRIER = "_À trier"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _patronyme(nom: str) -> str:
    """Patronyme : celui de la convention, sinon premier mot en capitales (≥ 2 lettres) qui n'est pas un code."""
    lu = lire_nom(nom)
    if lu["patronyme"]:
        return lu["patronyme"]
    for tok in re.split(r"[\s_\-.,()\[\]]+", os.path.splitext(nom)[0]):
        if (len(tok) >= 2 and tok.isalpha() and tok.isupper() and tok not in _PAS_PATRONYME
                and not re.fullmatch(r"[NBMDS]+", tok) and not any(re.search(m, _norm(tok)) for m, _ in _MOTS)):
            return tok
    return ""


def detecter(rel: Path) -> dict:
    """Type de pièce (code), patronyme et indices déduits du nom (pas du contenu : voir l'agent trieur)."""
    nom = rel.name
    ext = rel.suffix.lower()
    info: dict = {"type": "", "patronyme": _patronyme(nom), **{k: v for k, v in lire_nom(nom).items()
                                                               if k in ("commune", "depot", "cote", "vue", "acte")}}
    if any(p.lower().endswith(".gwb") for p in rel.parts[:-1]) or ext in GENEWEB:
        info["type"] = "GENEWEB"
        return info
    if ext in GEDCOM:
        info["type"] = "GEDCOM"
        return info
    n = _norm(nom)
    if ext in DONNEES:
        info["type"] = "INSEE" if re.search(r"\b(insee|deces \d{4}|fichier des personnes decedees)\b", n) else ""
        return info
    if ext in AUDIO:
        info["type"] = "AUDIO"
        return info
    conv = lire_nom(nom).get("type", "").split()
    if conv and conv[0] in _CODES_CONVENTION:
        info["type"] = conv[0] if conv[0] in TYPES else "NMD"
        return info
    for motif, code in _MOTS:
        if re.search(motif, n):
            info["type"] = code
            return info
    return info


def pieces_considerees(ext: str, rel: Path) -> bool:
    if any(p.lower().endswith(".gwb") for p in rel.parts[:-1]):
        return True
    return ext in IMAGES | AUDIO | VIDEO | DOCS | GENEWEB | GEDCOM | DONNEES


def destination(info: dict) -> str | None:
    """Dossier cible (relatif) d'après le type et le patronyme ; None = _À trier."""
    t, pat = info.get("type", ""), _part(info.get("patronyme", ""))
    if t == "GENEWEB":
        return "archives/GeneWeb"
    if t == "GEDCOM":
        return "archives/GEDCOM"
    if t == "INSEE":
        return "archives/INSEE"
    if t == "AUDIO":
        return f"documents/Témoignages oraux/{pat}" if pat else "documents/Témoignages oraux"
    if t == "LIEU":
        return "photographies/Lieux"
    if not pat or not t:
        return None
    if t == "PHOTO":
        return f"photographies/{pat}"
    if t == "TOMBE":
        return f"photographies/Sépultures/{pat}"
    return f"documents/{TYPES[t][1]}/{pat}"


# ---------------------------------------------------------------- inventaire

@dataclass
class Fichier:
    rel: Path
    taille: int
    sha256: str
    info: dict = field(default_factory=dict)

    @property
    def classe(self) -> bool:
        return self.rel.parts[0] in CLASSES


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for bloc in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _ignore_dossier(part: str) -> bool:
    return part.startswith(".") or part in _PROTEGES


def parcourir(racine: Path) -> tuple[list[Fichier], dict]:
    """Toutes les pièces du dossier (hors dossiers protégés, cachés, liens symboliques, notes)."""
    racine = Path(racine).resolve()
    fichiers, ignores = [], Counter()
    for dirpath, dirnames, filenames in os.walk(racine):
        d = Path(dirpath)
        rel_dir = d.relative_to(racine)
        dirnames[:] = sorted(n for n in dirnames if not (rel_dir == Path(".") and _ignore_dossier(n))
                             and not n.startswith(".") and not (d / n).is_symlink())
        for name in sorted(filenames):
            p = d / name
            rel = p.relative_to(racine)
            if p.is_symlink():
                ignores["lien symbolique"] += 1
                continue
            if name.startswith("."):
                ignores["fichier caché"] += 1
                continue
            if not pieces_considerees(p.suffix.lower(), rel):
                ignores[p.suffix.lower() or "(sans extension)"] += 1
                continue
            f = Fichier(rel, p.stat().st_size, sha256(p))
            f.info = detecter(rel)
            if f.info["type"] == "" and p.suffix.lower() in DONNEES:
                ignores[p.suffix.lower()] += 1
                continue
            fichiers.append(f)
    return fichiers, dict(ignores)


def inventaire(racine: Path) -> dict:
    fichiers, ignores = parcourir(racine)
    par_type = Counter(f.info["type"] or "inconnu" for f in fichiers)
    par_hash = Counter(f.sha256 for f in fichiers)
    return {
        "dossier": str(Path(racine).resolve()), "pieces": len(fichiers),
        "taille_octets": sum(f.taille for f in fichiers),
        "par_type": {(TYPES[k][0] if k in TYPES else k): v for k, v in par_type.most_common()},
        "deja_classees": sum(f.classe for f in fichiers),
        "sans_patronyme": sum(1 for f in fichiers if not f.info["patronyme"] and f.info["type"] not in
                              ("GENEWEB", "GEDCOM", "INSEE")),
        "doublons": sum(n - 1 for n in par_hash.values() if n > 1),
        "ignores": ignores,
        "patronymes": dict(Counter(f.info["patronyme"] for f in fichiers if f.info["patronyme"]).most_common(30)),
    }


# ---------------------------------------------------------------- plan de classement

def _libre(cible: Path, prises: set[Path], racine: Path, source: Path) -> Path:
    """Chemin cible sans collision (ni fichier existant, ni cible déjà attribuée) : suffixe « (2) », « (3) »…"""
    stem, ext = cible.stem, cible.suffix
    n = 1
    c = cible
    while c in prises or ((racine / c).exists() and c != source):
        n += 1
        c = cible.with_name(f"{stem} ({n}){ext}")
    prises.add(c)
    return c


def planifier(racine: Path, renommages: list[dict] | None = None, references: set[Path] | None = None) -> dict:
    """Plan de déplacements {de, vers, motif} ; ne modifie rien.
    renommages : [{actuel: chemin relatif, propose: nouveau nom de fichier}] (agent trieur, piece_nommer) ;
    le fichier est ensuite classé d'après son nouveau nom.
    references : chemins absolus de médias liés à l'arbre (jamais déplacés)."""
    racine = Path(racine).resolve()
    fichiers, ignores = parcourir(racine)
    par_rel = {f.rel: f for f in fichiers}
    noms: dict[Path, str] = {}
    erreurs = []
    for r in renommages or []:
        rel = Path(r.get("actuel", ""))
        if rel not in par_rel:
            erreurs.append(f"Renommage ignoré : {rel} n'est pas une pièce du dossier")
            continue
        propose = nom_compatible(Path(r.get("propose", "")).name)
        if not Path(propose).suffix:
            propose += rel.suffix.lower()
        noms[rel] = propose
        par_rel[rel].info = detecter(rel.with_name(propose))
    references = {Path(p).resolve() for p in references or ()}

    moves, prises, protegees = [], set(), []
    # doublons : on garde l'exemplaire déjà classé, sinon le premier par ordre de chemin
    groupes: dict[str, list[Fichier]] = {}
    for f in fichiers:
        groupes.setdefault(f.sha256, []).append(f)
    doublons: set[Path] = set()
    for grp in groupes.values():
        grp = [f for f in grp if f.rel.parts[:2] != ("archives", "Doublons")]  # déjà isolés : restent
        if len(grp) > 1:
            grp.sort(key=lambda f: (not f.classe, (racine / f.rel).resolve() not in references, str(f.rel)))
            doublons.update(f.rel for f in grp[1:] if (racine / f.rel).resolve() not in references)

    for f in sorted(fichiers, key=lambda f: str(f.rel)):
        if (racine / f.rel).resolve() in references:
            if f.rel in noms or f.rel in doublons or not f.classe:
                protegees.append(str(f.rel))
            continue
        nom = noms.get(f.rel, nom_compatible(f.rel.name))
        if f.rel in doublons:
            cible_dir, motif = Path("archives/Doublons") / f.rel.parent, "doublon (même SHA-256)"
        elif f.classe and f.rel not in noms:
            if nom == f.rel.name:
                continue  # déjà classé : on n'y touche pas
            cible_dir, motif = f.rel.parent, "nom incompatible Windows/Nextcloud"
        elif f.info["type"] == "GENEWEB" and any(p.lower().endswith(".gwb") for p in f.rel.parts[:-1]):
            i = next(i for i, p in enumerate(f.rel.parts) if p.lower().endswith(".gwb"))
            cible_dir, motif = Path("archives/GeneWeb", *f.rel.parts[i:-1]), "base GeneWeb"
        else:
            dest = destination(f.info)
            if dest is None:
                cible_dir = Path(A_TRIER)
                motif = "patronyme inconnu" if f.info["type"] else "type non reconnu"
            else:
                cible_dir = Path(dest)
                motif = TYPES[f.info["type"]][0]
            if f.rel in noms:
                motif += " (renommée)"
        cible = cible_dir / nom
        if cible == f.rel:
            continue
        cible = _libre(cible, prises, racine, f.rel)
        moves.append({"de": str(f.rel), "vers": str(cible), "motif": motif, "sha256": f.sha256})
    resume = Counter(str(Path(m["vers"]).parent) for m in moves)
    return {
        "dossier": str(racine), "pieces": len(fichiers), "deplacements": moves,
        "resume_par_dossier": dict(sorted(resume.items())),
        "doublons": len(doublons), "a_trier": sum(1 for m in moves if m["vers"].startswith(A_TRIER)),
        "references_arbre_non_deplacees": protegees, "ignores": ignores, "erreurs": erreurs,
        "empreintes": sorted(f.sha256 for f in fichiers),
    }


def plan_annulation(racine: Path, journal: str) -> dict:
    """Plan inverse d'un journal TSV (dernier déplacement annulé en premier)."""
    racine = Path(racine).resolve()
    try:
        path = sous(racine / "_organisation", journal)
    except CheminRefuse as exc:
        raise PieceError(str(exc)) from exc
    if not path.is_file():
        raise PieceError(f"Journal introuvable : {journal}")
    with path.open(encoding="utf-8", newline="") as fh:
        lignes = [r for r in csv.DictReader(fh, delimiter="\t") if r.get("nouveau_chemin")]
    moves = []
    for r in reversed(lignes):
        p = racine / r["nouveau_chemin"]
        if not p.is_file():
            raise PieceError(f"Annulation impossible : {r['nouveau_chemin']} n'existe plus")
        moves.append({"de": r["nouveau_chemin"], "vers": r["ancien_chemin"], "motif": "annulation",
                      "sha256": r.get("sha256") or sha256(p)})
    fichiers, _ = parcourir(racine)
    return {"dossier": str(racine), "pieces": len(fichiers), "deplacements": moves,
            "resume_par_dossier": dict(Counter(str(Path(m["vers"]).parent) for m in moves)),
            "empreintes": sorted(f.sha256 for f in fichiers), "annulation_de": str(path.name)}


# ---------------------------------------------------------------- application

def appliquer(racine: Path, plan: dict) -> dict:
    """Exécute un plan validé. Vérifie avant chaque déplacement (source intacte, cible libre) ; journal TSV
    écrit ligne à ligne ; contrôle final du nombre de fichiers et des empreintes. Jamais de suppression."""
    racine = Path(racine).resolve()
    avant, _ = parcourir(racine)
    if sorted(f.sha256 for f in avant) != plan["empreintes"]:
        raise PieceError("Le dossier a changé depuis le plan : le reformuler (pieces_proposer).")
    for m in plan["deplacements"]:
        try:
            src, dst = sous(racine, m["de"]), sous(racine, m["vers"])
        except CheminRefuse as exc:
            raise PieceError(str(exc)) from exc
        if not src.is_file():
            raise PieceError(f"Source absente : {m['de']}")
        if dst.exists():
            raise PieceError(f"Cible déjà existante : {m['vers']}")
    jdir = racine / "_organisation"
    jdir.mkdir(exist_ok=True)
    journal = jdir / f"{datetime.now().strftime('%Y-%m-%dT%H%M%S')}.tsv"
    faits, erreurs = 0, []
    with journal.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["ancien_chemin", "nouveau_chemin", "motif", "sha256"])
        fh.flush()
        for m in plan["deplacements"]:
            src, dst = racine / m["de"], racine / m["vers"]
            try:
                if sha256(src) != m["sha256"]:
                    raise PieceError("contenu modifié depuis le plan")
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    raise PieceError("cible apparue entre-temps")
                os.rename(src, dst)  # même dossier racine : renommage atomique, jamais de copie + suppression
            except (OSError, PieceError) as exc:
                erreurs.append(f"{m['de']} : {exc}")
                continue
            w.writerow([m["de"], m["vers"], m["motif"], m["sha256"]])
            fh.flush()
            os.fsync(fh.fileno())
            faits += 1
    _vider_dossiers(racine, {Path(m["de"]).parent for m in plan["deplacements"]})
    apres, _ = parcourir(racine)
    controle = {"avant": len(avant), "apres": len(apres),
                "empreintes_identiques": Counter(f.sha256 for f in avant) == Counter(f.sha256 for f in apres)}
    return {"deplaces": faits, "erreurs": erreurs, "journal": f"_organisation/{journal.name}",
            "controle": controle, "annuler": f"pieces_proposer(dossier, annuler='{journal.name}')"}


def _vider_dossiers(racine: Path, dossiers: set[Path]) -> None:
    """Retire les dossiers devenus vides (jamais un fichier)."""
    for d in sorted(dossiers, key=lambda p: len(p.parts), reverse=True):
        p = racine / d
        while p != racine and p.is_dir() and not any(p.iterdir()):
            p.rmdir()
            p = p.parent
