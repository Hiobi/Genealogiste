"""Réglages de la base Gramps que Genealogiste lit et, sur accord, écrit (#282) : fiche du chercheur, signets,
formats de nom personnalisés.

Faits amont (gramps-web-api v3.26.0, gramps 6.0, docs/gramps-web.md « Signets, fiche chercheur et formats de nom ») :

- ces trois réglages sont stockés dans la BASE Gramps (table de métadonnées), donc partagés entre Gramps Desktop et
  Gramps Web ; ils ne sont pas inscrits dans l'historique des transactions du serveur (aucun ``DbTxn``) ;
- fiche chercheur : ``GET /api/metadata/`` (clé ``researcher``), ``PUT /api/metadata/researcher/`` (droit EditTree,
  rôle Owner, API >= 3.9.0), mise à jour PARTIELLE ; l'état antérieur est lisible et restaurable exactement, y compris
  « vide » (onze champs chaînes, chaîne vide admise) ;
- signets : ``GET /api/bookmarks/<espace>`` (liste de handles, ordonnée), ``PUT``/``DELETE
  /api/bookmarks/<espace>/<handle>`` (EditObject, Editor, API >= 1.5.0) ; un ajout se place EN FIN de liste ;
- l'interface de Gramps Web n'utilise PAS ces signets : ses signets sont un réglage du navigateur (``localStorage``,
  clé ``bookmarks``, par arbre ; gramps-web ``src/api.js``, v26.5.1, v26.11.0 et v26.11.3, ajout #335 du 2023-12-27) ;
  seuls Gramps Desktop (menu Signets) et les clients de l'API voient ceux de la base ;
- formats de nom : ``GET /api/name-formats/`` seulement (aucune écriture) ; le format PAR DÉFAUT n'est pas dans la
  base : c'est la préférence ``preferences.name-format`` de la configuration de Gramps (poste Desktop, ou processus
  serveur de Gramps Web), illisible par l'API.

Ce module ne contient que de la logique pure (validation, comparaison, correspondance) ; les appels réseau sont dans
``client.py`` et les propositions dans ``backend.py``."""

from __future__ import annotations

# Champs de la fiche : ceux que ``ResearcherUpdateSchema`` accepte et que ``GET`` renvoie (ordre de l'interface).
CHERCHEUR_CLES = ("name", "addr", "street", "locality", "city", "county", "state", "country", "postal", "phone",
                  "email")
LONGUEUR_MAX = 300

# Cibles (noms de l'XML Gramps et de l'outil) -> espace de l'API ``/api/bookmarks/<espace>`` -> classe Gramps.
ESPACES = {"person": "people", "family": "families", "event": "events", "place": "places", "source": "sources",
           "citation": "citations", "repository": "repositories", "media": "media", "note": "notes"}
CIBLES = {v: k for k, v in ESPACES.items()}
CLASSE_DE_CIBLE = {"person": "Person", "family": "Family", "event": "Event", "place": "Place", "source": "Source",
                   "citation": "Citation", "repository": "Repository", "media": "Media", "note": "Note"}
MAX_OPERATIONS = 100  # signets par proposition


class ReglageError(ValueError):
    """Valeur refusée avant toute proposition."""


# ---------------------------------------------------------------------------------------------- fiche chercheur
def chercheur_normalise(brut) -> dict[str, str]:
    """Fiche lue (``researcher`` de ``GET /api/metadata/``) : les onze champs, chaîne vide si absent ou nul."""
    brut = brut if isinstance(brut, dict) else {}
    return {k: v if isinstance(v := brut.get(k), str) else "" for k in CHERCHEUR_CLES}


def chercheur_renseigne(fiche: dict[str, str]) -> bool:
    return any(v for v in fiche.values())


def champs_renseignes(fiche: dict[str, str]) -> list[str]:
    """Noms des champs non vides (jamais leurs valeurs)."""
    return [k for k in CHERCHEUR_CLES if fiche.get(k)]


def valider_chercheur(champs) -> dict[str, str]:
    """Champs fournis EXPLICITEMENT par l'utilisateur : clés connues, chaînes, sans caractère de contrôle ni retour à
    la ligne (une fiche tient sur une ligne par champ), au plus ``LONGUEUR_MAX`` caractères. Chaîne vide : vide le
    champ. Rien n'est déduit de l'environnement, de git ou du système."""
    if not isinstance(champs, dict) or not champs:
        raise ReglageError("chercheur : dictionnaire non vide attendu, par exemple {\"name\": \"…\"} "
                           f"(champs : {', '.join(CHERCHEUR_CLES)}).")
    inconnus = sorted(set(champs) - set(CHERCHEUR_CLES))
    if inconnus:
        raise ReglageError(f"chercheur : champ(s) inconnu(s) {inconnus} (champs : {', '.join(CHERCHEUR_CLES)}).")
    out: dict[str, str] = {}
    for k, v in champs.items():
        if not isinstance(v, str):
            raise ReglageError(f"chercheur.{k} : chaîne attendue (chaîne vide pour vider le champ).")
        if any(ord(c) < 32 or ord(c) == 127 for c in v):
            raise ReglageError(f"chercheur.{k} : retour à la ligne et caractères de contrôle refusés.")
        if len(v) > LONGUEUR_MAX:
            raise ReglageError(f"chercheur.{k} : {LONGUEUR_MAX} caractères au plus.")
        out[k] = v
    return out


def diff_chercheur(avant: dict[str, str], apres: dict[str, str]) -> list[dict]:
    return [{"champ": k, "avant": avant[k], "apres": apres[k]} for k in CHERCHEUR_CLES if avant[k] != apres[k]]


# ---------------------------------------------------------------------------------------------- signets
def cible_valide(cible) -> str:
    if cible not in ESPACES:
        raise ReglageError(f"cible de signet inconnue : {cible!r} ({', '.join(ESPACES)}).")
    return cible


def etat_signets(brut: dict | None) -> dict[str, list[str]]:
    """``GET /api/bookmarks/`` (ou assemblage espace par espace) -> {espace: [handles]} pour les neuf espaces."""
    brut = brut or {}
    return {e: [h for h in brut.get(e, []) if isinstance(h, str)] for e in ESPACES.values()}


def gramps_id_de(db, cible: str, handle: str) -> str | None:
    """Identifiant Gramps d'un objet de la base lue (jamais un nom)."""
    o = db.get(CLASSE_DE_CIBLE[cible], handle)
    return (o.get("gramps_id") or handle) if o else None


def handle_de(db, cible: str, gramps_id: str) -> str | None:
    """Handle de l'objet portant cet identifiant Gramps ; None si absent ou ambigu (jamais deviné)."""
    trouves = [h for h, o in db.all(CLASSE_DE_CIBLE[cible]).items() if o.get("gramps_id") == gramps_id]
    return trouves[0] if len(trouves) == 1 else None


def resoudre_operations(db, ajouter=None, retirer=None) -> list[dict]:
    """Opérations de signets {action, cible, id, handle} d'après des couples {cible, id} (identifiant Gramps).
    Refus avant toute proposition : cible inconnue, objet absent, doublon, plus de ``MAX_OPERATIONS``."""
    ops: list[dict] = []
    vus: set[tuple[str, str]] = set()
    for action, liste in (("ajouter", ajouter or []), ("retirer", retirer or [])):
        if not isinstance(liste, list):
            raise ReglageError(f"signets.{action} : liste de {{cible, id}} attendue.")
        for x in liste:
            if not isinstance(x, dict) or set(x) - {"cible", "id"} or not isinstance(x.get("id"), str):
                raise ReglageError(f"signets.{action} : chaque élément est {{\"cible\": …, \"id\": identifiant Gramps}}.")
            cible = cible_valide(x.get("cible"))
            h = handle_de(db, cible, x["id"])
            if h is None:
                raise ReglageError(f"signets.{action} : {cible} {x['id']!r} introuvable (ou identifiant ambigu) "
                                   "dans l'arbre Gramps.")
            if (cible, h) in vus:
                raise ReglageError(f"signets : {cible} {x['id']!r} cité deux fois.")
            vus.add((cible, h))
            ops.append({"action": action, "cible": cible, "id": x["id"], "handle": h})
    if len(ops) > MAX_OPERATIONS:
        raise ReglageError(f"signets : {MAX_OPERATIONS} opérations au plus par proposition ({len(ops)} demandées).")
    return ops


def appliquer_operations(etat: dict[str, list[str]], ops: list[dict]) -> dict[str, list[str]]:
    """État des signets après les opérations, comme Gramps : un ajout va EN FIN de liste, un retrait enlève sur place.
    Une opération sans effet (ajout d'un signet présent, retrait d'un absent) est une erreur : la proposition la
    refuse avant d'être présentée."""
    out = {e: list(v) for e, v in etat.items()}
    for op in ops:
        liste = out[ESPACES[op["cible"]]]
        present = op["handle"] in liste
        if op["action"] == "ajouter":
            if present:
                raise ReglageError(f"signets : {op['cible']} {op['id']} est déjà en signet.")
            liste.append(op["handle"])
        else:
            if not present:
                raise ReglageError(f"signets : {op['cible']} {op['id']} n'est pas en signet.")
            liste.remove(op["handle"])
    return out


def inverse(ops: list[dict]) -> list[dict]:
    """Opérations qui défont ``ops`` : ajout <-> retrait, dans l'ordre inverse."""
    return [{**op, "action": "retirer" if op["action"] == "ajouter" else "ajouter"} for op in reversed(ops)]


def etats_egaux(a: dict[str, list[str]], b: dict[str, list[str]]) -> bool:
    return all(list(a.get(e, [])) == list(b.get(e, [])) for e in ESPACES.values())


def memes_signets(a: dict[str, list[str]], b: dict[str, list[str]]) -> bool:
    """Mêmes signets, ordre non comparé (ce que l'annulation d'un RETRAIT garantit : le signet revient en fin de liste)."""
    return all(sorted(a.get(e, [])) == sorted(b.get(e, [])) for e in ESPACES.values())


def lignes_signets(ops: list[dict]) -> list[str]:
    """Une ligne par opération, identifiants Gramps seulement (jamais un nom)."""
    return [f"{'+' if op['action'] == 'ajouter' else '-'} signet {op['cible']} {op['id']}" for op in ops]


# ---------------------------------------------------------------------------------------------- formats de nom
def formats_noms_normalises(brut) -> list[tuple[int, str, str, bool]]:
    """``GET /api/name-formats/`` -> [(numéro, nom, format, actif)], dans l'ordre de la base ; un élément illisible est
    ignoré."""
    out = []
    for x in brut if isinstance(brut, list) else []:
        if isinstance(x, dict) and isinstance(x.get("number"), int) and not isinstance(x.get("number"), bool):
            out.append((x["number"], str(x.get("name") or ""), str(x.get("format") or ""), bool(x.get("active"))))
    return out


# ---------------------------------------------------------------------------------------------- export
def signets_pour_export(db_source, db_export, etat: dict[str, list[str]],
                        masques=frozenset()) -> tuple[list[tuple[str, str]], dict]:
    """Signets de la base Gramps traduits dans une base d'export : (cible, handle de l'export).

    Un signet n'est écrit que si l'objet visé existe dans l'export, retrouvé par son identifiant Gramps (les
    objets de l'export sont ceux de l'arbre ; la projection publique garde une personne masquée sous la forme d'un
    « Vivant » anonyme : ``masques`` ({(cible, identifiant Gramps)}) retire explicitement les signets des personnes et
    familles masquées ; les sources, médias et notes privés ne sont plus dans l'export). Classes dont l'identifiant ne se conserve pas à l'export (événements,
    lieux, citations : renumérotés ou reconstruits) : non écrites, comptées."""
    sortants: list[tuple[str, str]] = []
    bilan = {"ecrits": 0, "retires": 0, "non_ecrits": 0}
    index: dict[str, dict[str, str]] = {}
    for cible in CONSERVENT_ID:
        cls = CLASSE_DE_CIBLE[cible]
        par_id: dict[str, list[str]] = {}
        for h, o in db_export.all(cls).items():
            par_id.setdefault(o.get("gramps_id") or "", []).append(h)
        index[cible] = {i: hs[0] for i, hs in par_id.items() if i and len(hs) == 1}
    for espace in ESPACES.values():
        cible = CIBLES[espace]
        for h in etat.get(espace, []):
            if cible not in CONSERVENT_ID:
                bilan["non_ecrits"] += 1
                continue
            gid = gramps_id_de(db_source, cible, h)
            cible_h = index[cible].get(gid or "")
            if cible_h is None or (cible, gid) in masques:
                bilan["retires"] += 1
                continue
            sortants.append((cible, cible_h))
            bilan["ecrits"] += 1
    return sortants, bilan


CONSERVENT_ID = ("person", "family", "source", "repository", "media", "note")

# Champs de la fiche écrits dans le Gramps XML (``<researcher>``) : tous sauf ``street`` et ``county``, que le format
# d'échange de Gramps (exportxml.py) ne porte pas.
XML_DE_CHAMP = {"name": "resname", "addr": "resaddr", "locality": "reslocality", "city": "rescity",
                "state": "resstate", "country": "rescountry", "postal": "respostal", "phone": "resphone",
                "email": "resemail"}


def chercheur_pour_xml(fiche: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """(champs ``res…`` de l'en-tête XML, champs renseignés que le format XML ne porte pas)."""
    xml = {XML_DE_CHAMP[k]: v for k, v in fiche.items() if k in XML_DE_CHAMP and v}
    return xml, [k for k in champs_renseignes(fiche) if k not in XML_DE_CHAMP]

