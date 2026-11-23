"""Citation normée d'une Reference (#321) : ISO 690 par défaut, Evidence Explained en option.

Style choisi par GENEALOGISTE_CONTEXTE_STYLE_CITATION (``iso690`` | ``evidence_explained``). Une référence
incomplète est citée avec ses champs connus, suivis de « [Non renseigné : …] » : aucun champ n'est complété de
mémoire ni remplacé par une valeur conventionnelle (« s. d. », « s. n. »). Une notice dont le texte n'a pas été lu
porte « [Notice seule, non lu.] ».
"""

from __future__ import annotations

from .modeles import Reference

STYLES = ("iso690", "evidence_explained")
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre")
NON_LU = "[Notice seule, non lu.]"

# Champs attendus par type de document : (attribut, libellé du manque)
_PUBLICATION = {"article": "revue", "chapitre": "ouvrage", "monographie": "éditeur", "these": "université",
                "presse": "titre du journal", "autre": "publication"}
_ATTENDUS = {
    "article": ("auteurs", "titre", "publication", "annee", "pages"),
    "chapitre": ("auteurs", "titre", "publication", "annee", "pages"),
    "monographie": ("auteurs", "titre", "publication", "lieu_edition", "annee"),
    "these": ("auteurs", "titre", "publication", "annee"),
    "presse": ("publication", "date"),
    "autre": ("titre", "annee"),
}
_LIBELLES = {"auteurs": "auteur", "titre": "titre", "lieu_edition": "lieu d'édition", "annee": "année",
             "pages": "pages", "date": "date"}
_IDENTIFIANTS = {"doi": "DOI ", "hal": "HAL ", "handle": "Handle ", "ppn": "PPN ", "lccn": "LCCN ",
                 "europeana": "Europeana ", "ark": "", "url": "Disponible à l'adresse : "}


def date_fr(iso: str) -> str:
    """« 2026-11-23 » -> « 23 novembre 2026 » ; « 1906-03 » -> « mars 1906 » ; autre forme inchangée."""
    parties = (iso or "")[:10].split("-")
    try:
        if len(parties) == 3:
            return f"{int(parties[2])} {MOIS[int(parties[1]) - 1]} {int(parties[0])}"
        if len(parties) == 2:
            return f"{MOIS[int(parties[1]) - 1]} {int(parties[0])}"
    except (ValueError, IndexError):
        pass
    return iso


def champs_manquants(ref: Reference) -> list[str]:
    """Libellés des champs attendus pour ce type de document et absents de la notice."""
    out = []
    for champ in _ATTENDUS[ref.type_document]:
        if not getattr(ref, champ):
            out.append(_PUBLICATION[ref.type_document] if champ == "publication" else _LIBELLES[champ])
    return out


def _identifiant(ref: Reference) -> str:
    return _IDENTIFIANTS[ref.identifiant.type] + ref.identifiant.valeur


def _pages(ref: Reference, monographie: bool) -> str:
    p = ref.pages
    if not p or p.lower().startswith(("p.", "f.", "col.")) or not p[0].isdigit():
        return p
    if monographie and p.isdigit():
        return f"{p} p."
    return f"p. {p}"


def _quand(ref: Reference) -> str:
    return date_fr(ref.date) if ref.date else (str(ref.annee) if ref.annee else "")


def _point(s: str) -> str:
    return s if not s or s.endswith((".", "?", "!", "»")) else s + "."


def _fin(ref: Reference, corps: list[str], sep: str) -> str:
    texte = sep.join(x for x in corps if x)
    manque = champs_manquants(ref)
    if manque:
        texte += f" [Non renseigné : {', '.join(manque)}.]"
    if ref.lu == "notice_seule":
        texte += " " + NON_LU
    return texte


def _liste(noms: list[str]) -> str:
    """« A », « A et B », « A, B et C »."""
    if len(noms) <= 1:
        return "".join(noms)
    return ", ".join(noms[:-1]) + " et " + noms[-1]


# -------------------------------------------------------------------------------------------------- ISO 690

def _auteur_iso(a: str) -> str:
    nom, sep, prenom = a.partition(",")
    return f"{nom.strip().upper()}, {prenom.strip()}" if sep and prenom.strip() else a


def _auteurs_iso(auteurs: list[str]) -> str:
    noms = [_auteur_iso(a) for a in auteurs]
    if len(noms) > 3:
        return f"{noms[0]} et al"
    return _liste(noms)


def _editeur(ref: Reference) -> str:
    """« Lieu : Éditeur, année » avec les seules parties connues."""
    lieu_ed = " : ".join(x for x in (ref.lieu_edition, ref.publication) if x)
    return ", ".join(x for x in (lieu_ed, str(ref.annee) if ref.annee else "") if x)


def _iso690(ref: Reference, it) -> list[str]:
    t = ref.type_document
    blocs = [_auteurs_iso(ref.auteurs)]
    if t in ("article", "presse"):
        blocs += [ref.titre, it(ref.publication)]
        details = [_quand(ref), f"vol. {ref.volume}" if ref.volume else "",
                   f"n° {ref.numero}" if ref.numero else "", _pages(ref, False)]
        blocs.append(", ".join(x for x in details if x))
    elif t == "chapitre":
        blocs += [ref.titre, f"In : {it(ref.publication)}" if ref.publication else "",
                  ", ".join(x for x in (_editeur(ref) if ref.lieu_edition else _quand(ref), _pages(ref, False)) if x)]
    elif t == "these":
        blocs += [it(ref.titre), "Thèse de doctorat", _editeur(ref), _pages(ref, True)]
    elif t == "monographie":
        blocs += [it(ref.titre), _editeur(ref), _pages(ref, True)]
    else:
        blocs += [it(ref.titre), _editeur(ref), _pages(ref, False)]
    if ref.consulte_le:
        blocs.append(f"[Consulté le {date_fr(ref.consulte_le)}]")
    blocs.append(_identifiant(ref))
    return [_point(b) for b in blocs if b]


# ------------------------------------------------------------------------------------- Evidence Explained

def _auteur_ee(a: str) -> str:
    nom, sep, prenom = a.partition(",")
    return f"{prenom.strip()} {nom.strip()}" if sep and prenom.strip() else a


def _auteurs_ee(auteurs: list[str]) -> str:
    noms = [_auteur_ee(a) for a in auteurs]
    if len(noms) > 3:
        return f"{noms[0]} et al."
    return _liste(noms)


def _evidence(ref: Reference, it) -> str:
    t = ref.type_document
    if t in ("article", "chapitre", "these") or (t == "presse" and ref.titre):
        titre = f"« {ref.titre} »" if ref.titre else ""
    else:
        titre = it(ref.titre)
    tete = [x for x in (_auteurs_ee(ref.auteurs), titre) if x]
    if t == "article":
        revue = " ".join(x for x in (it(ref.publication), ref.volume) if x)
        if ref.numero:
            revue = ", ".join(x for x in (revue, f"n° {ref.numero}") if x)
        if ref.annee:
            revue += f" ({ref.annee})"
        corps = ", ".join(tete + ([revue.strip()] if revue.strip() else []))
        if ref.pages:
            corps += f" : {ref.pages}"
    elif t == "presse":
        corps = ", ".join(tete + [x for x in (it(ref.publication), _quand(ref),
                                              f"n° {ref.numero}" if ref.numero else "", _pages(ref, False)) if x])
    else:
        parenthese = _editeur(ref)
        if t == "these":
            parenthese = ", ".join(x for x in ("thèse de doctorat", parenthese) if x)
        elif t == "chapitre" and ref.publication:
            parenthese = f"dans {it(ref.publication)}" + (f", {ref.annee}" if ref.annee else "")
        corps = ", ".join(tete)
        if parenthese:
            corps += f" ({parenthese})"
        if ref.pages:
            corps += ", " + _pages(ref, t in ("monographie", "these"))
    morceaux = [corps, _identifiant(ref)]
    if ref.consulte_le:
        morceaux.append(f"consulté le {date_fr(ref.consulte_le)}")
    return " ; ".join(x for x in morceaux if x) + "."


def citer(ref: Reference, style: str = "iso690", italique: bool = False) -> str:
    """Citation normée de ``ref`` dans ``style`` (STYLES). ``italique`` : titres de revue, d'ouvrage et de journal
    entre astérisques (Markdown) ; sinon texte brut."""
    if style not in STYLES:
        raise ValueError(f"style de citation {style!r} : valeurs possibles {' | '.join(STYLES)}")

    def it(s: str) -> str:
        return f"*{s}*" if italique and s else s

    if style == "iso690":
        return _fin(ref, _iso690(ref, it), " ")
    return _fin(ref, [_evidence(ref, it)], " ")
