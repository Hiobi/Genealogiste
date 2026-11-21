"""Plage de versions Gramps testée en CI : source de vérité pour le code (diagnostic, #265).

Concordance vérifiée par `tests/test_compatibilite_gramps.py` avec `compatibilite-gramps.json` (images épinglées
de `make test-gramps-matrice`, bibliothèques de `make test-gramps-desktop`) et avec `docs/gramps-web.md`.
Élargir la plage seulement après un passage réel de la matrice sur la nouvelle borne.
"""

from __future__ import annotations

import re

Version = tuple[int, int, int]

# gramps-web-api (champ `gramps_webapi.version` de GET /api/metadata/)
# Plancher : image grampsweb 26.5.1. Les API 3.0.0 à 3.12.x (Gramps 6.0 aussi) refusent le paramètre `message`
# que Genealogiste envoie à POST /api/transactions/ (HTTP 422 « Unknown field », ajouté en 3.13.0).
API_TESTEE_MIN: Version = (3, 13, 0)
API_TESTEE_MAX: Version = (3, 26, 0)  # image grampsweb 26.11.3
API_EPINGLEE: Version = (3, 25, 1)    # image par défaut de docker-compose.test.yml (26.11.0)

# Gramps Desktop dont la bibliothèque relit l'export Gramps XML (make test-gramps-desktop)
GRAMPS_DESKTOP_TESTES: tuple[str, ...] = ("5.2", "6.0", "6.1")

# Version minimale de l'API pour les fonctions utilisées ou prévues (relevé des commits gramps-web-api).
FONCTIONS_API: dict[str, Version] = {
    "transactions": (0, 2, 0),             # POST /api/transactions/
    "transactions_undo": (1, 0, 0),        # ?undo=1
    "transactions_historique": (2, 2, 0),  # GET /api/transactions/history/
    "transactions_fond": (2, 7, 0),        # ?background=1
    "objets_json_gramps6": (3, 0, 0),      # format JSON des objets Gramps 6.0
    "historique_annuler": (3, 4, 0),       # POST /api/transactions/history/<id>/undo
    "chercheur_modifier": (3, 9, 0),       # PUT /api/metadata/researcher/
    "transactions_message": (3, 13, 0),    # ?message= (message de la transaction) : requis par Genealogiste
    "arbre_config": (3, 13, 0),            # /api/trees/<id>/config
    "fusion": (3, 15, 0),                  # /api/<objets>/merge/
    "verification": (3, 17, 0),            # /api/trees/-/verify
    "requete_objets": (3, 21, 0),          # POST /api/<objets>/query/
    "historique_objet": (3, 22, 0),        # historique par objet (onglet Révisions)
    "regle_matches_query": (3, 23, 0),     # règle MatchesQuery ; `oql` retiré
    "verrous_taches": (3, 24, 0),          # 409 task_locked
    "edit_by_handle": (3, 26, 0),          # /api/objects/edit-by-handle/ ; `gql` retiré
    "inscription_libre": (3, 26, 0),       # GET /api/register/config/ (sans authentification)
    "nom_lieu_date": (3, 26, 0),           # profil d'événement : place_name au nom de la date (#277)
    "groupes_noms": (0, 1, 0),             # GET /api/name-groups/ et /<patronyme> (lecture, #276)
    "signets": (0, 1, 0),                  # GET /api/bookmarks/<espace> (lecture, #282)
    "signets_ecriture": (1, 5, 0),         # PUT / DELETE /api/bookmarks/<espace>/<handle> : droit EditObject (Editor)
    "formats_noms": (0, 1, 0),             # GET /api/name-formats/ (lecture seule, #282)
    "groupes_noms_ecriture": (0, 6, 0),    # POST /api/name-groups/<patronyme>/<groupe> : droit EditNameGroup (Editor)
}

_VERSION = re.compile(r"^\s*v?(\d+)\.(\d+)(?:\.(\d+))?")


def version_api(texte: str | None) -> Version | None:
    """« 3.25.1 », « v3.26.0 », « 3.7.1.1 » -> tuple à trois nombres ; None si illisible."""
    m = _VERSION.match(texte or "")
    if not m:
        return None
    return int(m[1]), int(m[2]), int(m[3] or 0)


def verdict_api(texte: str | None) -> str:
    """`testee`, `trop_ancienne` (non prise en charge), `plus_recente` (non testée) ou `inconnue`."""
    v = version_api(texte)
    if v is None:
        return "inconnue"
    if v < API_TESTEE_MIN:
        return "trop_ancienne"
    if v > API_TESTEE_MAX:
        return "plus_recente"
    return "testee"


def texte_version(v: Version) -> str:
    return ".".join(map(str, v))
