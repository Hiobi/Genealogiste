"""Sondage guidé d'un registre chronologique (#156) : quelle vue lire ensuite pour atteindre une date.

Calcul pur, sans réseau ni écriture : le modèle lit les vues (``archive_image``) et fournit la date lue ;
``planifier`` resserre les bornes et propose la vue suivante.

- **Lecture d'une vue** : ``{vue, date, date_fin?, type?}``. ``date`` = date du premier acte de la vue (en haut),
  ``date_fin`` (facultative) = date du dernier acte. Sans ``date_fin``, l'acte cherché peut encore être au bas
  d'une vue dont le premier acte précède la cible : la vue reste dans les bornes.
- **Bornes** : la vue de départ de la cible est entre ``L`` (dernière vue commencée avant la cible) et ``R``
  (première vue commencée à la date cible ou après). Une cible partielle (« 1862 », « mars 1862 ») vise la
  première vue de la période.
- **Méthode** : interpolation sur les dates connues (ou la période du registre aux bornes), puis dichotomie
  quand une interpolation n'a pas divisé l'intervalle au moins par deux (alternance : au pire deux fois le
  nombre de lectures d'une dichotomie, en pratique 3 à 5 lectures pour 1 000 vues).
- **Séries** : avec ``type_acte`` (naissance, mariage, deces, table), un registre à plusieurs séries à la suite
  (naissances, mariages, décès, tables en fin de volume ; ordre ``ORDRE_SERIES`` ou ``ordre_series``) est
  d'abord sondé par section : une vue d'une autre série borne la section cherchée, sondée par son milieu
  jusqu'à la première vue du bon type ; la recherche par date ne commence qu'ensuite. ``ordre_series=[]`` :
  types ignorés (registre paroissial aux actes mêlés).
- **Arrêts** : ``localise`` (une vue, ou des vues toutes lues, à examiner pour l'acte), ``absent`` (les dates
  lues encadrent la cible sans vue possible entre elles), ``budget`` (décidé par l'appelant).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .normalize.dates import iso, parse_date
from .normalize.names import strip_accents

ORDRE_SERIES = ("naissance", "mariage", "deces", "table")
_TYPES = {
    "naissance": ("n", "b", "naissance", "naissances", "bapteme", "baptemes", "nai", "bap"),
    "mariage": ("m", "mariage", "mariages", "mar", "publication", "publications"),
    "deces": ("d", "s", "deces", "sepulture", "sepultures", "inhumation", "inhumations", "dec", "sep"),
    "table": ("t", "table", "tables", "table decennale", "tables decennales", "table annuelle", "tables annuelles",
              "td", "tsa"),
}
_ALIAS = {alias: canon for canon, aliases in _TYPES.items() for alias in aliases}
MAX_PLANCHE = 12  # archives_planche : 12 vues au plus


class SondageError(ValueError):
    pass


def type_canonique(valeur) -> str:
    """naissance | mariage | deces | table ; "" si vide ; la valeur normalisée si inconnue."""
    t = re.sub(r"\s+", " ", strip_accents(str(valeur or "")).lower()).strip(" .")
    return _ALIAS.get(t, t)


def intervalle_date(texte, champ: str = "date") -> tuple[int, int]:
    """[début, fin] en jours juliens d'une date lue ou cible (ISO, « 14 mars 1862 », « an XII », année seule)."""
    g = parse_date(str(texte or ""))
    if g is None or g.start is None:
        raise SondageError(f"{champ} illisible : {texte!r} (ex. 1862-03-14, 14 mars 1862, mars 1862, 1862).")
    return g.interval


def intervalle_periode(periode) -> tuple[int, int] | None:
    """Période d'un registre : « 1860-1869 », « 1862 », [début, fin] ; None si vide."""
    if not periode:
        return None
    if isinstance(periode, list | tuple):
        if len(periode) != 2:
            raise SondageError(f"periode : [début, fin] attendu, reçu {periode!r}.")
        return intervalle_date(periode[0], "periode")[0], intervalle_date(periode[1], "periode")[1]
    m = re.fullmatch(r"\s*(\d{3,4})\s*[-–/à]\s*(\d{3,4})\s*", str(periode))
    if m:
        return intervalle_date(m.group(1), "periode")[0], intervalle_date(m.group(2), "periode")[1]
    return intervalle_date(periode, "periode")


@dataclass
class Lecture:
    vue: int
    debut: int | None  # premier acte (jour julien), None si la vue ne porte pas de date (page de titre, table)
    fin: int | None  # dernier acte si lu
    type: str


def lecture(d: dict) -> Lecture:
    if not isinstance(d, dict) or not str(d.get("vue") or "").strip().isdigit() or int(d["vue"]) < 1:
        raise SondageError(f"Lecture invalide : {d!r} ({{vue, date, date_fin?, type?}}, vue à partir de 1).")
    debut = intervalle_date(d["date"])[0] if d.get("date") else None
    fin = intervalle_date(d["date_fin"], "date_fin")[1] if d.get("date_fin") else None
    if fin is not None and debut is not None and fin < debut:
        raise SondageError(f"Vue {d['vue']} : date_fin {d['date_fin']!r} antérieure à date {d['date']!r}.")
    return Lecture(int(d["vue"]), debut, fin, type_canonique(d.get("type")))


@dataclass
class Etat:
    section: list[int]
    bornes: list[int]
    phase: str  # section | date
    ancre_g: tuple[float, int] | None = None  # (vue, jour julien) à gauche
    ancre_d: tuple[float, int] | None = None
    avertissements: list[str] = field(default_factory=list)

    @property
    def taille(self) -> int:
        return max(0, self.bornes[1] - self.bornes[0] + 1)


def _etat(lectures: list[Lecture], nb_vues: int, cible: tuple[int, int], type_acte: str, ordre: list[str],
          periode: tuple[int, int] | None, bornes: list[int] | None) -> Etat:
    lo, hi = bornes or [1, nb_vues]
    avert: list[str] = []
    # -- section de la série cherchée
    if type_acte and ordre and type_acte in ordre:
        rang = ordre.index(type_acte)
        for x in lectures:
            if x.type and x.type != type_acte:
                if x.type not in ordre:
                    avert.append(f"Vue {x.vue} : type {x.type!r} hors de l'ordre des séries {ordre}, ignoré.")
                elif ordre.index(x.type) < rang:
                    lo = max(lo, x.vue + 1)
                else:
                    hi = min(hi, x.vue - 1)
    elif type_acte and ordre:
        avert.append(f"type_acte {type_acte!r} hors de l'ordre des séries {ordre} : types ignorés.")
    section = [lo, hi]
    meme = [x for x in lectures if lo <= x.vue <= hi
            and (not type_acte or not ordre or type_acte not in ordre or not x.type or x.type == type_acte)]
    autres_series = any(x.type and x.type != type_acte for x in lectures) if type_acte and ordre else False
    datees = [x for x in meme if x.debut is not None]
    if autres_series and not any(not x.type or x.type == type_acte for x in datees):
        return Etat(section, [lo, hi], "section", avertissements=avert)
    # -- bornes par date : L = dernière vue commencée avant la cible, R = première commencée à la cible ou après
    c_lo, c_hi = cible
    L, R = lo, hi
    # Ancres virtuelles : la période aux bords du registre ; un bord fixé par une autre série n'est pas le début
    # (ou la fin) de la série cherchée, seulement une borne : pas d'ancre de ce côté (dichotomie).
    debut, fin = bornes or [1, nb_vues]
    ancre_g = (lo - 0.5, periode[0]) if periode and lo == debut else None
    ancre_d = (hi + 0.5, periode[1] + 1) if periode and hi == fin else None
    for x in datees:
        if x.debut < c_lo:
            v = x.vue + 1 if x.fin is not None and x.fin < c_lo else x.vue
            if v >= L and (ancre_g is None or x.vue >= ancre_g[0]):
                L, ancre_g = v, (x.vue, x.debut)
            if x.fin is not None and x.fin >= c_lo and x.vue < R:
                R, ancre_d = x.vue, (x.vue, x.debut)
        else:
            v = x.vue - 1 if x.debut > c_hi else x.vue
            if v <= R and (ancre_d is None or x.vue <= ancre_d[0]):
                R, ancre_d = v, (x.vue, x.debut)
    return Etat(section, [L, R], "date", ancre_g, ancre_d, avert)


def _non_lue(lues: set[int], p: int, lo: int, hi: int) -> int | None:
    """Vue non lue la plus proche de p dans [lo, hi]."""
    for d in range(0, hi - lo + 1):
        for v in (p + d, p - d):
            if lo <= v <= hi and v not in lues:
                return v
    return None


def _interpoler(e: Etat, cible: int) -> int | None:
    if not (e.ancre_g and e.ancre_d) or e.ancre_d[1] <= e.ancre_g[1]:
        return None
    (vg, dg), (vd, dd) = e.ancre_g, e.ancre_d
    p = vg + (cible - dg) * (vd - vg) / (dd - dg)
    return min(max(round(p), e.bornes[0]), e.bornes[1])


def planifier(nb_vues: int, date_cible: str, lectures: list[dict], type_acte: str = "", periode=None,
              bornes: list[int] | None = None, ordre_series: list[str] | None = None) -> dict:
    """Prochaine vue à lire. ``lectures`` dans l'ordre où elles ont été faites (l'ordre choisit la méthode)."""
    if not isinstance(nb_vues, int) or nb_vues < 1:
        raise SondageError("nb_vues inconnu : le fournir, ou parcourir d'abord le registre (archives_naviguer).")
    cible = intervalle_date(date_cible, "date_cible")
    per = intervalle_periode(periode)
    typ = type_canonique(type_acte)
    ordre = list(ORDRE_SERIES) if ordre_series is None else [type_canonique(x) for x in ordre_series]
    if bornes:
        bornes = [max(1, int(min(bornes))), min(nb_vues, int(max(bornes)))]
    lus = [lecture(x) for x in lectures or []]
    hors = [x.vue for x in lus if x.vue > nb_vues]
    if hors:
        raise SondageError(f"Vue(s) {hors} au-delà des {nb_vues} vues du registre.")
    avert = []
    if per and (cible[1] < per[0] or cible[0] > per[1]):
        avert.append(f"Date cible hors de la période du registre ({iso(per[0])} – {iso(per[1])}) : "
                     "vérifier le registre (archives_registres) avant de sonder.")

    # Méthode rejouée sur l'historique : interpolation, sauf si la précédente n'a pas divisé l'intervalle par 2.
    methode_prec, taille_prec, etat = None, None, None
    for k in range(len(lus) + 1):
        etat = _etat(lus[:k], nb_vues, cible, typ, ordre, per, bornes)
        if etat.phase == "section":
            methode = "section"
        elif methode_prec == "interpolation" and taille_prec is not None and etat.taille > taille_prec / 2:
            methode = "dichotomie"
        else:
            methode = "interpolation"
        methode_prec, taille_prec = methode, (etat.taille if etat.phase == "date" else None)
    assert etat is not None
    lues = {x.vue for x in lus}
    L, R = etat.bornes
    out = {"cible": {"date": date_cible, "debut": iso(cible[0]), "fin": iso(cible[1])}, "type_acte": typ,
           "nb_vues": nb_vues, "section": etat.section, "bornes": [L, R], "phase": etat.phase,
           "lectures": len(lus), "vues_lues": sorted(lues), "avertissements": avert + etat.avertissements}
    if etat.phase == "section":
        lo, hi = etat.section
        if lo > hi:
            return {**out, "arret": "absent", "motif": f"Aucune vue de la série {typ!r} entre les autres séries "
                    f"lues (section vide) : série absente de ce registre."}
        v = _non_lue(lues, (lo + hi) // 2, lo, hi)
        if v is None:
            return {**out, "arret": "absent", "motif": f"Toutes les vues de la section {lo}-{hi} sont lues sans "
                    f"acte de la série {typ!r}."}
        return {**out, "arret": "", "prochaine_vue": v, "methode": "section",
                "motif": f"Vue d'une autre série : section {typ!r} cherchée entre les vues {lo} et {hi} (milieu)."}
    if L > R:
        return {**out, "arret": "absent", "encadrement": [R, L],
                "motif": f"Les dates lues encadrent la cible sans vue entre elles (vues "
                f"{R}-{L}) : pas d'acte du {out['cible']['debut']}"
                + (f" au {out['cible']['fin']}" if cible[0] != cible[1] else "") + " dans ce registre."}
    restantes = [v for v in range(L, R + 1) if v not in lues]
    if L == R or not restantes:
        return {**out, "arret": "localise", "vues": list(range(L, R + 1)),
                "motif": (f"Vue {L}" if L == R else f"Vues {L}-{R}") + " : la date cible y commence. Lire l'acte "
                         "(recadrer, largeur 1500-2000), au besoin la vue suivante (actes du même jour)."}
    p = _interpoler(etat, cible[0]) if methode == "interpolation" else None
    if p is None:
        methode = "dichotomie"
        p = (L + R) // 2
    v = _non_lue(lues, p, L, R)
    return {**out, "arret": "", "prochaine_vue": v, "methode": methode,
            "motif": f"Cible entre les vues {L} et {R} ({len(restantes)} non lues) : {methode}."}
