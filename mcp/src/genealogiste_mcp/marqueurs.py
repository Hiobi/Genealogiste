"""Marqueurs de données persistées (#182) : forme historique « sosa » et forme « genealogiste ».

- Notes Markdown : sections générées entre ``<!-- genealogiste:debut NOM -->`` et ``<!-- genealogiste:fin -->``
  (historique : ``<!-- sosa:debut NOM -->`` / ``<!-- sosa:fin -->``) ;
- Gramps Web : étiquette ``Genealogiste:auto`` (historique ``Sosa:auto``) et attributs ``Genealogiste-UID``,
  ``Genealogiste-Statut``… (historique ``Sosa-UID``, ``Sosa-Statut``…).

Les deux formes sont lues sans limite de durée (sauvegardes et exports anciens). L'écriture suit
GENEALOGISTE_MARQUEURS (``genealogiste`` par défaut, ``sosa`` pour partager un vault ou une base Gramps avec une
ancienne version). La numérotation Sosa-Stradonitz (champs ``sosa``) n'est pas concernée.
"""

from __future__ import annotations

import re

GENEALOGISTE, SOSA = "genealogiste", "sosa"
FORMES = (GENEALOGISTE, SOSA)

# ---------------------------------------------------------------- notes Markdown

_PREFIXES_NOTES = {GENEALOGISTE: "genealogiste", SOSA: "sosa"}
# Bloc généré, quelle que soit sa forme ; la fin la plus proche ferme le bloc (début et fin peuvent différer si la
# fiche a été retouchée à la main).
BLOCK = re.compile(r"<!-- (?P<forme>sosa|genealogiste):debut (?P<name>[\w-]+) -->\n(?P<contenu>.*?)"
                   r"<!-- (?:sosa|genealogiste):fin -->", re.S)


def debut(nom: str, forme: str = GENEALOGISTE) -> str:
    return f"<!-- {_PREFIXES_NOTES[forme]}:debut {nom} -->"


def fin(forme: str = GENEALOGISTE) -> str:
    return f"<!-- {_PREFIXES_NOTES[forme]}:fin -->"


def bloc(nom: str, contenu: str, forme: str = GENEALOGISTE) -> str:
    return f"{debut(nom, forme)}\n{contenu}\n{fin(forme)}"


def _forme_bloc(m: re.Match) -> str:
    """Forme d'un bloc : celle de son début et de sa fin s'ils concordent, sinon « mixte »."""
    fin_txt = m.group(0)[m.group(0).rfind("<!-- "):]
    return m.group("forme") if fin_txt == fin(m.group("forme")) else "mixte"


def migrer_texte_notes(texte: str, forme: str = GENEALOGISTE) -> tuple[str, list[str]]:
    """(texte migré, sections laissées en l'état car divergentes). Seules les balises des blocs complets changent :
    contenu des blocs et texte libre restent identiques. Une section présente sous les deux formes avec le même
    contenu n'est gardée qu'une fois ; avec un contenu différent, rien n'est changé pour cette section (la
    régénération de la fiche la résout en gardant le contenu régénéré)."""
    blocs = list(BLOCK.finditer(texte))
    par_nom: dict[str, list[re.Match]] = {}
    for m in blocs:
        par_nom.setdefault(m.group("name"), []).append(m)
    divergents = sorted(n for n, ms in par_nom.items() if len({m.group("contenu") for m in ms}) > 1)
    morceaux, pos = [], 0
    for m in blocs:
        nom = m.group("name")
        morceaux.append(texte[pos:m.start()])
        pos = m.end()
        if nom in divergents:
            morceaux.append(m.group(0))
            continue
        if len(par_nom[nom]) > 1:
            # doublon identique : on garde le bloc déjà dans la forme cible (sinon le premier) ; l'autre est retiré
            # avec au plus deux sauts de ligne qui le suivent
            garde = next((x for x in par_nom[nom] if _forme_bloc(x) == forme), par_nom[nom][0])
            if m.start() != garde.start():
                while pos < len(texte) and texte[pos] == "\n" and pos < m.end() + 2:
                    pos += 1
                continue
        morceaux.append(debut(nom, forme) + "\n" + m.group("contenu") + fin(forme))
    morceaux.append(texte[pos:])
    out = "".join(morceaux)
    return out, divergents


# ---------------------------------------------------------------- Gramps Web

AUTO = {GENEALOGISTE: "Genealogiste:auto", SOSA: "Sosa:auto"}
_PREFIXES_GRAMPS = {GENEALOGISTE: "Genealogiste-", SOSA: "Sosa-"}
# Attributs gérés (forme sans préfixe) ; seuls ceux-ci sont reconnus et migrés, jamais un attribut utilisateur.
_GERES = re.compile(r"^(?P<pre>Sosa-|Genealogiste-)(?P<nom>UID|UID noms|Statut|Statut nom .+|Statut filiation .+|"
                    r"Association|Vivant|Fichier)$")
MULTIPLES = {"Genealogiste-Association"}  # attribut à valeurs multiples (un par intervenant)


def canon(nom: str) -> str:
    """Nom logique (forme genealogiste) d'un attribut ou d'une étiquette gérés ; tout autre nom tel quel."""
    if nom == AUTO[SOSA]:
        return AUTO[GENEALOGISTE]
    m = _GERES.match(nom or "")
    return f"Genealogiste-{m.group('nom')}" if m else nom


def forme_de(nom: str) -> str:
    """Forme d'un nom géré (genealogiste | sosa), « » s'il n'est pas géré."""
    if nom in (AUTO[SOSA],):
        return SOSA
    if nom == AUTO[GENEALOGISTE]:
        return GENEALOGISTE
    m = _GERES.match(nom or "")
    return (SOSA if m.group("pre") == "Sosa-" else GENEALOGISTE) if m else ""


def ecrit(nom: str, forme: str = GENEALOGISTE) -> str:
    """Nom écrit dans la forme demandée pour un nom logique géré ; tout autre nom tel quel."""
    c = canon(nom)
    if c == AUTO[GENEALOGISTE]:
        return AUTO[forme]
    m = _GERES.match(c)
    return f"{_PREFIXES_GRAMPS[forme]}{m.group('nom')}" if m else nom
