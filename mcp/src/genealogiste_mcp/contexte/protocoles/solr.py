"""Protocole Solr (#286) : expression de requête et lecture d'une réponse JSON (``wt=json``).

Réponse attendue (relevée sur HAL le 2026-11-23) : ``{"response": {"numFound": n, "docs": [...]}}``. Un
champ multivalué est une liste ; un champ absent n'est pas dans le document.
"""

from __future__ import annotations

import re

from . import ReponseInvalide

_SPECIAUX = re.compile(r'[+\-!(){}\[\]^"~*?:\\/&|]')


def phrase(texte: str) -> str:
    """Phrase exacte, guillemets et caractères spéciaux neutralisés : « "Billy-Montigny" »."""
    t = re.sub(r"\s+", " ", (texte or "").replace('"', " ").replace("\\", " ")).strip()
    return f'"{t}"' if t else ""


def mots(texte: str) -> str:
    """Mots d'un texte libre, caractères de syntaxe Solr retirés, reliés par AND : « (mines AND charbon) »."""
    liste = [m for m in _SPECIAUX.sub(" ", texte or "").split() if m.upper() not in ("AND", "OR", "NOT")]
    if not liste:
        return ""
    return liste[0] if len(liste) == 1 else "(" + " AND ".join(liste) + ")"


def expression(lieux: list[str], sujet: str) -> str:
    """(« lieu 1 » OR « lieu 2 ») AND (mots du sujet) ; parties vides omises."""
    lieux_q = [p for p in (phrase(x) for x in lieux) if p]
    parties = []
    if lieux_q:
        parties.append(lieux_q[0] if len(lieux_q) == 1 else "(" + " OR ".join(lieux_q) + ")")
    if s := mots(sujet):
        parties.append(s)
    return " AND ".join(parties)


def documents(contenu) -> tuple[int | None, list[dict]]:
    """(numFound, docs) d'une réponse Solr JSON. ReponseInvalide si la forme n'est pas celle d'une réponse Solr."""
    if not isinstance(contenu, dict):
        raise ReponseInvalide("réponse Solr : objet JSON attendu")
    if "error" in contenu and "response" not in contenu:
        err = contenu.get("error")
        msg = err.get("msg") if isinstance(err, dict) else err
        raise ReponseInvalide(f"erreur Solr : {str(msg)[:200]}")
    rep = contenu.get("response")
    if not isinstance(rep, dict) or not isinstance(rep.get("docs"), list):
        raise ReponseInvalide("réponse Solr sans response.docs")
    total = rep.get("numFound")
    return (total if isinstance(total, int) else None), [d for d in rep["docs"] if isinstance(d, dict)]


def premier(doc: dict, champ: str) -> str:
    """Première valeur textuelle d'un champ simple ou multivalué ; vide si absent."""
    v = doc.get(champ)
    if isinstance(v, list):
        v = next((x for x in v if isinstance(x, (str, int)) and str(x).strip()), "")
    return str(v).strip() if isinstance(v, (str, int)) and not isinstance(v, bool) else ""


def valeurs(doc: dict, champ: str) -> list[str]:
    """Toutes les valeurs textuelles d'un champ (liste vide si absent)."""
    v = doc.get(champ)
    v = v if isinstance(v, list) else [v]
    return [str(x).strip() for x in v if isinstance(x, (str, int)) and not isinstance(x, bool) and str(x).strip()]
