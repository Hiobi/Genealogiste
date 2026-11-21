#!/usr/bin/env python3
"""Génère le référentiel des types standard de Gramps et de leurs libellés français (#273).

Source : les sources de Gramps (https://github.com/gramps-project/gramps), une copie de travail par branche de
maintenance. Pour chaque classe de type (``gramps/gen/lib/*type.py`` : ``_DATAMAP`` lu par analyse syntaxique, sans
importer Gramps), chaque type standard (chaîne XML anglaise canonique) reçoit sa valeur, son libellé anglais affiché,
la version où il apparaît et son libellé français par version, tiré du catalogue ``po/fr.po`` de la même branche
exactement comme le fait Gramps (``sgettext(msgid, contexte)`` : ``pgettext`` si un contexte est donné ; entrée
absente, vide ou « fuzzy » : le libellé reste anglais, comme après ``msgfmt``).

Usage (depuis la racine du dépôt) :

    python3 scripts/generer_types_gramps.py \\
        --source 5.2=<gramps maintenance/gramps52> --source 6.0=<…/gramps60> --source 6.1=<…/gramps61> \\
        [--sortie mcp/src/genealogiste_mcp/referentiels/types_gramps.json] [--verifier]

``--verifier`` : n'écrit rien, échoue si le fichier versionné diffère de ce que donnent les sources.
Gramps est sous GPL-2.0-or-later ; le référentiel (données extraites) est distribué avec ce dépôt (GPL-3.0).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

DEPOT = "https://github.com/gramps-project/gramps"
SORTIE = Path("mcp/src/genealogiste_mcp/referentiels/types_gramps.json")
# Classes retenues : tous les GrampsType de gramps/gen/lib présents dans les trois versions (pas les types ADN de
# la branche master, absents de 6.1). StyledTextTagType n'est jamais saisi par l'utilisateur : gardé pour la
# concordance des tables, sans libellé reconnu.
CLASSES = ("EventType", "EventRoleType", "AttributeType", "SrcAttributeType", "NoteType", "PlaceType", "NameType",
           "NameOriginType", "FamilyRelType", "ChildRefType", "RepositoryType", "SourceMediaType", "UrlType",
           "MarkerType", "StyledTextTagType")


# ============================================================================ catalogue de traduction (.po)

def _chaine(lignes: list[str]) -> str:
    return "".join(ast.literal_eval(x) for x in lignes)


def lire_po(chemin: Path) -> dict[tuple[str, str], str]:
    """(contexte, msgid) -> msgstr, sans les entrées obsolètes (#~), « fuzzy », vides ou plurielles."""
    out: dict[tuple[str, str], str] = {}
    entree: dict = {}
    champ = None

    def fin() -> None:
        if entree.get("msgid") is not None and entree.get("msgstr") and not entree.get("fuzzy"):
            out[(_chaine(entree.get("msgctxt", [])), _chaine(entree["msgid"]))] = _chaine(entree["msgstr"])

    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne:
            fin()
            entree, champ = {}, None
        elif ligne.startswith("#,"):
            entree["fuzzy"] = "fuzzy" in ligne
        elif ligne.startswith("#"):
            continue
        elif ligne.startswith('"'):
            if champ:
                entree[champ].append(ligne)
        else:
            mot, _, reste = ligne.partition(" ")
            if mot in ("msgctxt", "msgid", "msgstr"):
                if mot == "msgctxt" and "msgid" in entree:  # entrée suivante sans ligne vide
                    fin()
                    entree = {}
                champ = mot
                entree[mot] = [reste]
            else:  # msgid_plural, msgstr[n] : hors des types
                champ = None
                entree["pluriel"] = True
                entree.pop("msgstr", None)
    fin()
    return out


# ============================================================================ tables de types (_DATAMAP)

def _texte(n: ast.AST) -> tuple[str, str] | None:
    """Libellé d'une entrée : ``_("x")``, ``_("x", "ctx")`` ou ``"x"`` -> (msgid, contexte) ; None si autre."""
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value, None
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("_", "_T_") and n.args:
        args = [a.value for a in n.args if isinstance(a, ast.Constant)]
        if len(args) == len(n.args) and all(isinstance(a, str) for a in args):
            return args[0], (args[1] if len(args) > 1 else "")
    return None


def _entrees(n: ast.AST, listes: dict[str, ast.AST], f: Path) -> list[ast.Tuple]:
    """Entrées d'un _DATAMAP : liste littérale, concaténation de listes de la classe (``_DATAMAPREAL +
    _DATAMAPIGNORE``) ou compréhension ``[(b[0], _(b[1]), b[2]) for b in _BASEMAP]`` (traduction différée : les
    libellés de _BASEMAP sont marqués par ``_T_``)."""
    if isinstance(n, ast.List):
        return list(n.elts)
    if isinstance(n, ast.Name) and n.id in listes:
        return _entrees(listes[n.id], listes, f)
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
        return _entrees(n.left, listes, f) + _entrees(n.right, listes, f)
    if isinstance(n, ast.ListComp) and len(n.generators) == 1 and isinstance(n.generators[0].iter, ast.Name):
        return _entrees(n.generators[0].iter, listes, f)
    raise SystemExit(f"{f}: forme de _DATAMAP non reconnue : {ast.dump(n)[:200]}")


def lire_types(lib: Path) -> dict[str, dict]:
    """Classe -> {personnalise, defaut, types: [(xml, valeur, msgid, contexte|None)]}."""
    out: dict[str, dict] = {}
    for f in sorted(lib.glob("*type.py")):
        arbre = ast.parse(f.read_text(encoding="utf-8"))
        for cl in (n for n in arbre.body if isinstance(n, ast.ClassDef)):
            if cl.name not in CLASSES:
                continue
            consts: dict[str, int] = {}
            listes: dict[str, ast.AST] = {}
            spec = {}
            for st in cl.body:
                if not isinstance(st, ast.Assign) or len(st.targets) != 1 or not isinstance(st.targets[0], ast.Name):
                    continue
                nom = st.targets[0].id
                v = st.value
                if isinstance(v, ast.Constant) and isinstance(v.value, int):
                    consts[nom] = v.value
                elif isinstance(v, ast.UnaryOp) and isinstance(v.op, ast.USub) and isinstance(v.operand, ast.Constant):
                    consts[nom] = -v.operand.value
                elif isinstance(v, ast.Name) and nom in ("_CUSTOM", "_DEFAULT"):
                    spec[nom] = v.id
                elif nom.startswith("_DATAMAP") or nom == "_BASEMAP":
                    listes[nom] = v
            if "_DATAMAP" not in listes:
                raise SystemExit(f"{f}: {cl.name} sans _DATAMAP")
            types = []
            for t in _entrees(listes["_DATAMAP"], listes, f):
                code, lib_, xml = t.elts
                valeur = consts[code.id] if isinstance(code, ast.Name) else code.value
                texte = _texte(lib_)
                if texte is None or not isinstance(xml, ast.Constant):
                    raise SystemExit(f"{f}: entrée non reconnue dans {cl.name}._DATAMAP : {ast.dump(t)}")
                types.append((xml.value, valeur, texte[0], texte[1]))
            out[cl.name] = {"personnalise": consts.get(spec.get("_CUSTOM", ""), None),
                            "defaut": consts.get(spec.get("_DEFAULT", ""), None), "types": types}
    manquantes = set(CLASSES) - set(out)
    if manquantes:
        raise SystemExit(f"{lib}: classes absentes {sorted(manquantes)}")
    return out


def tete(source: Path) -> tuple[str, str]:
    """(branche, SHA) de la copie de travail, lus dans ses fichiers internes (sans lancer git)."""
    d = source / ("." + "git")
    head = (d / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return "", head
    ref = head[5:]
    f = d / ref
    sha = f.read_text(encoding="utf-8").strip() if f.exists() else ""
    if not sha and (d / "packed-refs").exists():
        sha = next((x.split()[0] for x in (d / "packed-refs").read_text().splitlines() if x.endswith(" " + ref)), "")
    return ref.removeprefix("refs/heads/"), sha


def version_gramps(source: Path) -> str:
    txt = (source / "gramps" / "version.py").read_text(encoding="utf-8")
    tup = re.search(r"VERSION_TUPLE = \((\d+), (\d+), (\d+)\)", txt)
    qual = re.search(r'VERSION_QUALIFIER = "([^"]*)"', txt)
    return ".".join(tup.groups()) + (qual.group(1) if qual else "")


# ============================================================================ référentiel

def generer(sources: dict[str, Path]) -> dict:
    versions = sorted(sources, key=lambda v: tuple(map(int, v.split("."))))
    provenance, par_version = [], {}
    for v in versions:
        src = sources[v]
        branche, sha = tete(src)
        provenance.append({"version": v, "branche": branche, "sha": sha, "version_gramps": version_gramps(src),
                           "fichiers": ["gramps/gen/lib/*type.py", "po/fr.po"]})
        par_version[v] = (lire_types(src / "gramps" / "gen" / "lib"), lire_po(src / "po" / "fr.po"))
    classes: dict[str, dict] = {}
    for cls in CLASSES:
        derniere = par_version[versions[-1]][0][cls]
        entree = {"personnalise": derniere["personnalise"], "defaut": derniere["defaut"], "types": {}}
        for v in versions:
            table, po = par_version[v]
            t = table[cls]
            if (t["personnalise"], t["defaut"]) != (entree["personnalise"], entree["defaut"]):
                raise SystemExit(f"{cls} : valeurs personnalisé/défaut différentes en {v}")
            for xml, valeur, msgid, ctx in t["types"]:
                e = entree["types"].setdefault(xml, {"valeur": valeur, "depuis": v, "en": {}, "fr": {}})
                if e["valeur"] != valeur:
                    raise SystemExit(f"{cls}.{xml} : valeur {e['valeur']} puis {valeur} en {v}")
                # contexte : sgettext(msgid, ctx) -> pgettext si ctx, sinon gettext ; repli sur le msgid anglais
                fr = po.get((ctx or "", msgid), msgid) if msgid else ""
                e["en"][v] = msgid
                e["fr"][v] = fr
                if ctx:
                    e.setdefault("contexte", {})[v] = ctx
            retires = set(entree["types"]) - {x[0] for x in t["types"]}
            for xml in retires:
                entree["types"][xml].setdefault("retire", v)
        classes[cls] = entree
    return {
        "_description": ("Types standard de Gramps par classe (chaîne XML anglaise canonique -> valeur, version "
                         "d'apparition, libellé anglais affiché et libellé français par version). Généré par "
                         "scripts/generer_types_gramps.py ; ne pas modifier à la main."),
        "_licence": ("Données extraites de Gramps (gramps/gen/lib/*type.py, po/fr.po), © projet Gramps et ses "
                     "traducteurs, sous GPL-2.0-or-later ; redistribuées avec Genealogiste sous GPL-3.0."),
        "_provenance": {"depot": DEPOT, "versions": provenance},
        "versions": versions,
        "classes": classes,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", action="append", required=True, metavar="VERSION=CHEMIN",
                    help="copie de travail de Gramps pour une version (5.2=…, 6.0=…, 6.1=…)")
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    ap.add_argument("--verifier", action="store_true", help="comparer au fichier versionné sans l'écrire")
    args = ap.parse_args(argv)
    sources = {}
    for s in args.source:
        v, _, chemin = s.partition("=")
        if not re.fullmatch(r"\d+\.\d+", v) or not chemin:
            ap.error(f"--source attendu sous la forme 5.2=/chemin : {s!r}")
        sources[v] = Path(chemin)
    texte = json.dumps(generer(sources), ensure_ascii=False, indent=1, sort_keys=False) + "\n"
    if args.verifier:
        actuel = args.sortie.read_text(encoding="utf-8") if args.sortie.exists() else ""
        if actuel != texte:
            print(f"{args.sortie} n'est pas à jour : relancer sans --verifier.", file=sys.stderr)
            return 1
        print(f"{args.sortie} à jour.")
        return 0
    args.sortie.write_text(texte, encoding="utf-8")
    print(f"{args.sortie} écrit ({sum(len(c['types']) for c in json.loads(texte)['classes'].values())} types).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
