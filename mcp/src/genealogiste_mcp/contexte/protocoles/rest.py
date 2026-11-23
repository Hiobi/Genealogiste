"""Protocole REST/JSON (#286) : lecture prudente d'une réponse JSON quelconque.

Les API REST n'ont pas de forme commune : chaque gabarit de service lit ses champs avec ces fonctions, qui ne
lèvent jamais sur une valeur absente ou d'un autre type (vide renvoyé), sauf ``exiger`` (forme attendue manquante :
``ReponseInvalide``). Convention de chemin : clés et indices séparés par des points (``message.items``,
``title.0``).
"""

from __future__ import annotations

from typing import Any

from . import ReponseInvalide

_ABSENT = object()


def chemin(obj: Any, voie: str, defaut: Any = None) -> Any:
    """Valeur à ``voie`` (« a.b.0.c ») ou ``defaut``."""
    cur = obj
    for part in voie.split(".") if voie else []:
        if isinstance(cur, dict):
            cur = cur.get(part, _ABSENT)
        elif isinstance(cur, list) and part.lstrip("-").isdigit() and -len(cur) <= int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return defaut
        if cur is _ABSENT:
            return defaut
    return cur


def exiger(obj: Any, voie: str, type_: type | tuple[type, ...]) -> Any:
    """Valeur obligatoire à ``voie``, du type attendu ; sinon ReponseInvalide (réponse de forme inattendue)."""
    v = chemin(obj, voie, _ABSENT)
    if v is _ABSENT or not isinstance(v, type_):
        raise ReponseInvalide(f"réponse JSON sans {voie or 'racine'} du type attendu")
    return v


def liste(v: Any) -> list:
    """Liste : une valeur seule devient une liste d'un élément ; None devient []."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def texte(v: Any) -> str:
    """Texte d'une valeur JSON : chaîne ou nombre ; pour un objet, sa clé « $ » (convention JSON-LD/Isidore) ;
    pour une liste, la première valeur non vide. Vide sinon."""
    if isinstance(v, bool) or v is None:
        return ""
    if isinstance(v, (str, int, float)):
        return str(v).strip()
    if isinstance(v, dict):
        return texte(v.get("$"))
    if isinstance(v, list):
        return next((t for t in (texte(x) for x in v) if t), "")
    return ""


def textes(v: Any) -> list[str]:
    """Tous les textes non vides d'une valeur (liste ou valeur seule), sans doublon, dans l'ordre."""
    return list(dict.fromkeys(t for t in (texte(x) for x in liste(v)) if t))


def entier(v: Any) -> int | None:
    """Entier d'une valeur JSON (nombre ou texte de chiffres) ; None sinon."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None
