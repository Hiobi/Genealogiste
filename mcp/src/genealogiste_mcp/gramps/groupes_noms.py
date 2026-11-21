"""Groupes de noms de Gramps (« name groups », #276) : lecture, appariement et proposition prudente.

Un groupe de noms est un regroupement d'AFFICHAGE : Gramps classe les personnes de ``Dupond`` sous ``DUPONT`` dans
ses vues par nom, ses index et ses rapports. Ce n'est PAS une fusion de personnes (aucune personne, aucun nom, aucun
événement n'est touché ; ``get_name_group_mapping`` ne renvoie que le nom de groupe). Deux niveaux existent :

- le regroupement GLOBAL, table ``name_group`` de la base (patronyme -> nom de groupe), lu par
  ``GET /api/name-groups/`` ; c'est celui que ce module lit ;
- ``group_as`` d'un NOM particulier (champ ``group`` du nom d'une personne) : il PRIME sur le regroupement global
  (``gramps.gen.display.name.name_grouping_name``) et reste propre à ce nom.

Le module est pur (aucun réseau, aucune écriture) : le client lit, le backend relit l'arbre, le serveur présente.
Les deux regroupements automatiques retenus sont volontairement étroits ; tout le reste est LISTÉ, jamais retenu :

- ``typographie`` : mêmes lettres à la casse, aux accents, aux espaces, tirets et apostrophes près (LE GRAND,
  Legrand, Le-Grand ; Lefèvre, Lefevre) ;
- ``transcription`` : un nom à tréma ou ß et sa transcription (Müller, Mueller, Muller ; Strauß, Strauss).

Ni phonétique (Dupont, Dupond), ni diphtongue (Meyer, Maier), ni finale (Schmidt, Schmitt), ni latin : des familles
distinctes portent ces noms ; ils ressortent en ``candidats_non_retenus`` pour examen humain.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from urllib.parse import quote

TYPOGRAPHIE = "typographie"
TRANSCRIPTION = "transcription"
MAX_CANDIDATS = 50
_TREMAS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
_TREMAS_SIMPLES = {"ä": "a", "ö": "o", "ü": "u", "ß": "ss"}


def _sans_accent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def cle_typographique(nom: str) -> str:
    """Clé d'égalité typographique : casse, accents, espaces, tirets, apostrophes et ligatures ignorés."""
    s = (nom or "").replace("ß", "ss").replace("œ", "oe").replace("Œ", "oe").replace("æ", "ae").replace("Æ", "ae")
    return re.sub(r"[^a-z]", "", _sans_accent(s).lower())


def _a_trema(nom: str) -> bool:
    return any(c in (nom or "").lower() for c in _TREMAS)


def formes_transcrites(nom: str) -> set[str]:
    """Clés typographiques des transcriptions d'un nom à tréma ou ß (Müller -> mueller, muller) ; vide sinon."""
    bas = (nom or "").lower()
    if not _a_trema(bas):
        return set()
    out = set()
    for table in (_TREMAS, _TREMAS_SIMPLES):
        s = bas
        for t, r in table.items():
            s = s.replace(t, r)
        out.add(cle_typographique(s))
    return out


def lien(a: str, b: str) -> str | None:
    """Motif du rapprochement retenu entre deux patronymes (``typographie``, ``transcription``) ; ``None`` sinon."""
    ka, kb = cle_typographique(a), cle_typographique(b)
    if not ka or not kb:
        return None
    if ka == kb:
        return TYPOGRAPHIE
    if kb in formes_transcrites(a) or ka in formes_transcrites(b):
        return TRANSCRIPTION
    return None


# ============================================================================ lecture : table de l'arbre Gramps

def lire_reponse(donnees) -> dict[str, str]:
    """``GET /api/name-groups/`` -> {patronyme: groupe} ; entrées incomplètes ignorées."""
    out: dict[str, str] = {}
    for e in donnees if isinstance(donnees, list) else []:
        if isinstance(e, dict) and e.get("surname") and e.get("group"):
            out[str(e["surname"])] = str(e["group"])
    return out


class Groupes:
    """Regroupements globaux d'un arbre Gramps. Comparaison tolérante à la casse et aux accents : la table de Gramps
    est sensible à la casse (``Dupont`` et ``DUPONT`` sont deux clés), la recherche de l'utilisateur ne l'est pas."""

    def __init__(self, table: dict[str, str] | None = None):
        self.table = dict(table or {})
        self._groupe = {cle_typographique(k): cle_typographique(v) for k, v in self.table.items()}
        self._membres: dict[str, set[str]] = defaultdict(set)
        for k, v in self._groupe.items():
            self._membres[v].add(k)
            self._membres[v].add(v)

    def __bool__(self) -> bool:
        return bool(self.table)

    def cle_groupe(self, nom: str) -> str:
        """Clé du groupe d'un patronyme : son groupe s'il est regroupé, lui-même sinon (comme Gramps)."""
        k = cle_typographique(nom)
        return self._groupe.get(k, k)

    def meme_groupe(self, a: str, b: str) -> bool:
        ka = self.cle_groupe(a)
        return bool(ka) and ka == self.cle_groupe(b)

    def apparentes(self, nom: str) -> list[str]:
        """Écritures de la table (clés et noms de groupe) qui partagent le groupe de ``nom``, ``nom`` lui-même exclu
        (comparaison exacte : « LE GRAND » reste une écriture distincte de « Legrand » dans la table de Gramps)."""
        g = self.cle_groupe(nom)
        if g not in self._membres:
            return []
        return sorted({x for x in [*self.table, *self.table.values()]
                       if cle_typographique(x) in self._membres[g] and x != nom})


def groupe_de_nom(nom: dict, groupes: Groupes) -> str:
    """Nom de groupe d'un nom Gramps brut (``Name`` JSON) : ``group_as`` d'abord, sinon le regroupement global du
    patronyme principal, sinon le patronyme (``name_grouping_name`` de Gramps)."""
    if (nom.get("group_as") or "").strip():
        return nom["group_as"]
    return patronyme_principal(nom)


def patronyme_principal(nom: dict) -> str:
    liste = nom.get("surname_list") or []
    prim = next((s for s in liste if s.get("primary")), liste[0] if liste else {})
    return (prim.get("surname") or "").strip()


def patronymes_attestes(db) -> tuple[dict[str, int], dict[str, int]]:
    """Patronymes PRINCIPAUX des noms principaux des personnes d'une base Gramps : ({patronyme: personnes},
    {patronyme: personnes dont le nom porte son propre ``group_as``}). Seules ces valeurs sont attestées."""
    nb: dict[str, int] = defaultdict(int)
    propres: dict[str, int] = defaultdict(int)
    for p in db.all("Person").values():
        nom = p.get("primary_name") or {}
        s = patronyme_principal(nom)
        if not s:
            continue
        nb[s] += 1
        if (nom.get("group_as") or "").strip():
            propres[s] += 1
    return dict(nb), dict(propres)


# ============================================================================ proposition

def _composantes(noms: list[str]) -> list[tuple[list[str], dict[str, str]]]:
    """Composantes connexes des patronymes reliés par :func:`lien` ; (membres triés, motif de chaque membre :
    ``typographie`` si un autre membre a la même clé typographique, sinon ``transcription``)."""
    parent = {n: n for n in noms}

    def racine(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    par_cle: dict[str, list[str]] = defaultdict(list)
    for n in noms:
        par_cle[cle_typographique(n)].append(n)
    for membres in par_cle.values():
        for m in membres[1:]:
            parent[racine(m)] = racine(membres[0])
    for n in noms:
        for f in formes_transcrites(n):
            for autre in par_cle.get(f, []):
                parent[racine(n)] = racine(autre)
    familles: dict[str, list[str]] = defaultdict(list)
    for n in noms:
        familles[racine(n)].append(n)
    out = []
    for membres in familles.values():
        if len(membres) < 2:
            continue
        motif = {m: TYPOGRAPHIE if len(par_cle[cle_typographique(m)]) > 1 else TRANSCRIPTION for m in membres}
        out.append((sorted(membres, key=lambda x: (_sans_accent(x).lower(), x)), motif))
    return sorted(out, key=lambda c: _sans_accent(c[0][0]).lower())


def route(patronyme: str, groupe: str) -> str:
    """Route de Gramps Web qui poserait ce regroupement ; les deux noms sont des segments d'URL encodés."""
    return f"POST /api/name-groups/{quote(patronyme, safe='')}/{quote(groupe, safe='')}"


def _candidats(noms: list[str], retenus: set[frozenset]) -> list[dict]:
    """Paires de patronymes de composantes distinctes qui se ressemblent (phonétique, diphtongue, finale, latin) :
    à examiner à la main, jamais regroupées. Comparaison limitée aux paires qui partagent une clé phonétique ou
    germanique (pas de produit cartésien sur un grand arbre)."""
    from ..normalize.allemand import cle_germanique
    from ..normalize.names import normalize_surname, surname_similarity

    seaux: dict[tuple[str, str], list[str]] = defaultdict(list)
    for n in noms:
        seaux[("phon", normalize_surname(n)["phonetique"])].append(n)
        seaux[("ger", cle_germanique(cle_typographique(n)))].append(n)
    vus: set[frozenset] = set()
    out: list[dict] = []
    for (_, cle), membres in sorted(seaux.items()):
        if not cle or len(membres) < 2:
            continue
        for i, a in enumerate(membres):
            for b in membres[i + 1:]:
                paire = frozenset((a, b))
                if paire in vus or paire in retenus:
                    continue
                vus.add(paire)
                s = surname_similarity(a, b)
                if s["score"] >= 0.9:
                    out.append({"patronymes": sorted((a, b)), "score": s["score"], "motif": s["raison"]})
    out.sort(key=lambda c: (-c["score"], c["patronymes"]))
    return out[:MAX_CANDIDATS]


def proposer(attestes: dict[str, int], existants: dict[str, str], propres: dict[str, int] | None = None,
             patronymes: list[str] | None = None, candidats: bool = True) -> dict:
    """Groupes à proposer d'après les patronymes ATTESTÉS dans l'arbre (``attestes`` : patronyme -> personnes) et la
    table actuelle de Gramps (``existants``). Idempotent : un groupe déjà en place est rapporté, pas reproposé.

    Pour chaque famille d'écritures (composante de :func:`lien`) :

    - aucun regroupement existant : nom de groupe = forme la plus portée (égalité : ordre alphabétique, signalée) ;
    - tous les regroupements existants visent un même nom de la famille : il est respecté, les autres s'y joignent ;
    - regroupements existants vers plusieurs groupes, ou vers un nom étranger à la famille : CONFLIT, listé, rien
      n'est proposé pour cette famille (jamais tranché).
    """
    propres = propres or {}
    noms = sorted(attestes)
    comps = _composantes(noms)
    if patronymes:
        voulus = {cle_typographique(p) for p in patronymes}
        comps = [c for c in comps if any(cle_typographique(m) in voulus for m in c[0])]
    groupes: list[dict] = []
    en_place: list[dict] = []
    conflits: list[dict] = []
    a_appliquer: list[dict] = []
    retenus: set[frozenset] = set()
    for membres, motif in comps:
        retenus.update(frozenset((a, b)) for a in membres for b in membres if a != b)
        cles_famille = {cle_typographique(m) for m in membres}
        # regroupements existants des membres : clé -> groupe actuel (table de Gramps, sensible à la casse)
        actuels = {m: existants[m] for m in membres if m in existants}
        cibles = set(actuels.values())
        etrangers = {c for c in cibles if cle_typographique(c) not in cles_famille}
        if len(cibles) > 1 or etrangers:
            conflits.append({
                "patronymes": membres,
                "regroupements_existants": {m: g for m, g in sorted(actuels.items())},
                "motif": ("regroupements existants vers plusieurs groupes" if len(cibles) > 1
                          else f"regroupement existant vers « {next(iter(etrangers))} », nom étranger à la famille "
                               "d'écritures"),
                "decision": "non tranchée : rien n'est proposé pour ces patronymes ; à corriger dans Gramps si voulu"})
            continue
        egalite = ""
        if cibles:
            groupe = next(iter(cibles))
            choix = "regroupement existant respecté"
        else:
            top = max(attestes.get(m, 0) for m in membres)
            candidats_nom = [m for m in membres if attestes.get(m, 0) == top]
            groupe = candidats_nom[0]
            choix = "forme la plus portée dans l'arbre"
            if len(candidats_nom) > 1:
                egalite = f"égalité entre {', '.join(candidats_nom)} : premier par ordre alphabétique (à ajuster)"
                choix = "égalité de fréquence, ordre alphabétique"
        lignes = []
        for m in membres:
            deja = actuels.get(m) == groupe
            a_poser = m != groupe and not deja
            lignes.append({"patronyme": m, "personnes": attestes.get(m, 0), "motif": motif.get(m, TYPOGRAPHIE),
                           "etat": ("nom du groupe" if m == groupe else "déjà regroupé" if deja else "à regrouper"),
                           **({"personnes_group_as_propre": propres[m]} if propres.get(m) else {})})
            if a_poser:
                a_appliquer.append({"patronyme": m, "groupe": groupe, "route": route(m, groupe)})
        fiche = {"groupe": groupe, "choix_du_groupe": choix, "patronymes": lignes,
                 "personnes": sum(attestes.get(m, 0) for m in membres)}
        if egalite:
            fiche["egalite"] = egalite
        (en_place if all(x["etat"] != "à regrouper" for x in lignes) else groupes).append(fiche)
    out = {"groupes_proposes": groupes, "deja_en_place": en_place, "conflits": conflits,
           "a_appliquer": a_appliquer}
    if candidats:
        out["candidats_non_retenus"] = _candidats(noms, retenus)
    return out


def regroupements_xml(paires: list[tuple[str, str]], version_xml: str = "1.7.1") -> str:
    """Document Gramps XML minimal (en-tête et ``<namemaps>`` seulement) dont l'import par Gramps (Desktop ou Web)
    pose ces regroupements sans rien créer d'autre. Gramps n'écrase pas un regroupement existant (avertissement)."""
    from ..export.gramps_xml import Metadonnees, db_to_xml
    from .mapping import GrampsDb

    return db_to_xml(GrampsDb(), version_xml, Metadonnees(regroupements=list(paires)))


# ============================================================================ export

def regroupements_exportables(table: dict[str, str], complet, publie, masques: set[str],
                              public: bool) -> tuple[list[tuple[str, str]], dict]:
    """Regroupements à écrire dans ``<namemaps>`` d'un export. Export complet (``public`` faux) : toute la table de
    Gramps. Export public : un regroupement n'est écrit que si son patronyme figure dans l'export (une personne non
    masquée le porte) ET si son groupe n'est pas un patronyme porté seulement par des personnes masquées : ni trace
    d'un patronyme masqué, ni regroupement orphelin. Le bilan ne nomme jamais un regroupement retiré."""
    paires = sorted(table.items(), key=lambda kv: (kv[0].lower(), kv[0]))
    if not public:
        return paires, {"ecrits": len(paires), "source": "Gramps" if paires else "aucun groupe de noms dans Gramps"}
    exportes = {cle_typographique(n.nom) for p in publie.personnes.values() for n in p.noms}
    cache = {cle_typographique(n.nom) for pid in masques if pid in complet.personnes
             for n in complet.personnes[pid].noms} - exportes
    gardes = [(k, v) for k, v in paires if cle_typographique(k) in exportes and cle_typographique(v) not in cache]
    return gardes, {"ecrits": len(gardes), "retires_export_public": len(paires) - len(gardes),
                    "source": "Gramps" if paires else "aucun groupe de noms dans Gramps"}
