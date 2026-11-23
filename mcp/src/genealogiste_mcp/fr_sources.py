"""Connaissance des sources françaises : prochaine source à consulter, cotes typiques, communicabilité.

Les cotes indiquées suivent le cadre de classement réglementaire des archives départementales ;
leur numérotation exacte varie d'un service à l'autre : toujours vérifier dans l'inventaire.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .normalize.dates import parse_date
from .normalize.pays import pays_du_lieu, pays_resume
from .types_documents import RULES, SERIES, normaliser

# Aiguillage par pays (#283) : séries des AD seulement en France ; ailleurs, renvoi générique sans cote inventée.
SI_FRANCE = "si le lieu est en France"
RENVOI_INTERNATIONAL = ("source à identifier pour ce pays (aucune série d'archives départementales françaises) ; "
                        "parcours internationaux : wiki Services-archives")
PISTE_TRANSCRIPTION = ("Pour un Français à l'étranger : transcription éventuelle de l'acte sur les registres de la "
                       "commune du dernier domicile en France, ou état civil consulaire (Service central d'état "
                       "civil, Nantes), sans garantie d'existence.")
FAITS_ETAT_CIVIL = {"BIRT", "CHR", "BAPM", "FILIATION", "DEAT", "BURI", "MARR", "MARB", "MARC", "ENGA"}
_COTES_AD = frozenset(SERIES.values())


def lieu_texte(lieu: Any) -> str:
    """Libellé d'un lieu donné en texte ou en objet (Place)."""
    return lieu if isinstance(lieu, str) else (getattr(lieu, "nom", "") or "") if lieu else ""


def _lieu_renseigne(lieu: Any) -> bool:
    return bool(lieu_texte(lieu).strip() or (not isinstance(lieu, str) and getattr(lieu, "code_insee", "")))


def _year(d: str) -> int | None:
    g = parse_date(d) if d else None
    if not g:
        return None
    lo, hi = g.interval
    from .normalize.dates import jdn_to_gregorian
    return (jdn_to_gregorian(lo)[0] + jdn_to_gregorian(hi)[0]) // 2


def next_source_hint(fact: str, when: str = "", where: Any = "") -> list[dict]:
    """Sources à consulter pour étayer un fait, par ordre de priorité, aiguillées par le pays du lieu (#283).

    ``where`` : libellé ou ``Place`` (code INSEE et hiérarchie pris en compte). Lieu en France : cotes du cadre
    de classement des AD. Hors de France : aucune série des AD, renvoi générique et piste de transcription.
    Pays inconnu : séries des AD avec la condition « si le lieu est en France ». Chaque piste porte ``pays``
    quand un lieu est donné ; sans lieu, la sortie est celle d'avant #283."""
    if not _lieu_renseigne(where):
        return _hints(fact, when, "")
    pays = pays_du_lieu(where)
    out = _hints(fact, when, lieu_texte(where))
    if pays["france"] is False:
        out = _hors_france(fact, out, pays)
    elif pays["france"] is None:
        for d in out:
            if d["cote_typique"] in _COTES_AD:
                d["cote_typique"] = f"{d['cote_typique']} — {SI_FRANCE}"
                d["condition"] = SI_FRANCE
    court = pays_resume(pays)
    return [{**d, "pays": dict(court)} for d in out]


def _hors_france(fact: str, sources: list[dict], pays: dict) -> list[dict]:
    nom = pays["nom"] or "pays étranger"
    out = [{"source": f"État civil et archives du lieu ({nom})", "cote_typique": RENVOI_INTERNATIONAL,
            "pourquoi": "lieu hors de France : les séries des archives départementales françaises ne s'appliquent "
                        "pas ; chercher l'état civil ou les registres locaux du pays",
            "en_ligne": "wiki Services-archives (https://github.com/Hiobi/Genealogiste/wiki/Services-archives)"}]
    if fact in FAITS_ETAT_CIVIL:
        out.append({"source": "Transcription de l'acte en France (commune du dernier domicile) ou état civil "
                              "consulaire", "cote_typique": "registres d'état civil de la commune française ; "
                              "Service central d'état civil (Nantes) pour l'état civil consulaire",
                    "pourquoi": PISTE_TRANSCRIPTION})
    return out + [d for d in sources if d["cote_typique"] not in _COTES_AD]


def _hints(fact: str, when: str = "", where: str = "") -> list[dict]:
    y = _year(when)
    lieu = f" de {where.split(',')[0]}" if where else ""
    out: list[dict] = []

    def add(source: str, cote: str, pourquoi: str, en_ligne: str = ""):
        d = {"source": source, "cote_typique": cote, "pourquoi": pourquoi}
        if en_ligne:
            d["en_ligne"] = en_ligne
        out.append(d)

    civil = y is None or y >= 1792
    if fact in ("CHR", "BAPM") and (y is None or y >= 1792):
        add(f"Registre de catholicité (baptême){lieu}", "archives diocésaines ou paroisse (registres après 1792)",
            "acte religieux : parrain, marraine, date du baptême (distinct de l'état civil)")
    if fact in ("BIRT", "CHR", "BAPM", "FILIATION"):
        if civil:
            add(f"Acte de naissance{lieu}", SERIES["etat_civil"],
                "source originale, information primaire (déclarant présent) ; mentions marginales",
                "site des AD (état civil numérisé, > 75 ans)")
            add(f"Table décennale{lieu}", SERIES["tables_decennales"], "localiser l'acte (date exacte, orthographe)")
        if y is None or y < 1800:
            add(f"Registre paroissial (baptême){lieu}", SERIES["paroissiaux"],
                "avant 1792 : baptême, parrain/marraine, filiation", "site des AD")
        add("Acte de mariage de la personne", SERIES["etat_civil"],
            "rappelle âge/date et lieu de naissance, noms des parents (information secondaire)")
        if fact == "FILIATION":
            add("Contrat de mariage / inventaire après décès des parents", SERIES["notaires"],
                "énumère les enfants et héritiers")
            add("Table des successions et absences", SERIES["enregistrement"], "liste des héritiers au décès d'un parent")
        if y and 1847 <= y <= 1921:
            add("Registre matricule (classe = année de naissance + 20)", SERIES["matricules"],
                "date et lieu de naissance, parents, signalement", "AD (en ligne pour les classes anciennes)")
        if y and y >= 1816:
            add("Listes nominatives de recensement", SERIES["recensements"], "âge déclaré (indirect), foyer", "AD")
    elif fact in ("DEAT", "BURI"):
        if civil:
            add(f"Acte de décès{lieu}", SERIES["etat_civil"],
                "date/lieu de décès primaires ; âge et parents secondaires", "AD (décès communicables sans délai)")
            add(f"Table décennale{lieu}", SERIES["tables_decennales"], "localiser l'acte")
        if y is None or y < 1800:
            add(f"Registre paroissial (sépulture){lieu}", SERIES["paroissiaux"], "avant 1792")
        if y is None or y >= 1970:
            add("Fichier des décès INSEE (matchID)", "deces.matchid.io", "décès depuis 1970 (source dérivée)", "en ligne")
        if y is None or y >= 1791:
            add("Table des successions et absences / mutation par décès", SERIES["enregistrement"],
                "date de décès, héritiers, biens")
        if y and 1914 <= y <= 1921:
            add("Mémoire des hommes (Morts pour la France)", "SGA / Mémoire des hommes", "décès militaires 14-18", "en ligne")
        add("Transcription de décès / jugement déclaratif", SERIES["justice"], "décès hors commune ou disparu")
    elif fact in ("MARR", "MARB", "MARC", "ENGA"):
        if civil:
            add(f"Acte de mariage{lieu}", SERIES["etat_civil"],
                "information primaire pour le mariage ; filiation des époux, consentements", "AD")
            add("Publications de bans", SERIES["etat_civil"], "domiciles, mariage célébré ailleurs")
        if y is None or y < 1800:
            add(f"Registre paroissial (mariage){lieu}", SERIES["paroissiaux"], "dispenses de consanguinité")
        add("Contrat de mariage (notaire)", SERIES["notaires"], "date, parents, dot ; cité dans l'acte civil après 1850",
            "répertoire du notaire ; tables de l'enregistrement")
    elif fact in ("OCCU", "RESI", "CENS"):
        add("Listes nominatives de recensement", SERIES["recensements"], "profession, domicile, composition du foyer")
        add("Actes d'état civil (naissance des enfants, mariage)", SERIES["etat_civil"], "profession et domicile déclarés")
        add("Annuaires et presse (Gallica)", "Gallica / Retronews", "annuaires professionnels, avis", "gallica.bnf.fr")
    elif fact == "MILI":
        add("Registre matricule", SERIES["matricules"], "parcours militaire complet")
        add("Mémoire des hommes", "SGA", "fiches MPF, JMO, sépultures de guerre", "en ligne")
    else:
        add("Actes d'état civil liés", SERIES["etat_civil"], "corroboration")
        add("Actes notariés", SERIES["notaires"], "biens, famille")
    return out


# ---------------------------------------------------------------------------- communicabilité



def communicability(document: str, date_document: str = "", date_naissance: str = "",
                    date_deces: str = "", today: date | None = None) -> dict:
    today = today or date.today()
    key = normaliser(document)
    if key not in RULES:
        return {"erreur": f"Type inconnu. Types : {', '.join(RULES)}"}
    years, base, text = RULES[key]
    if years is None:
        return {"document": document, "type_document": key, "regle": text,
                "delai_annees": None, "communicable": None,
                "note": "Régime à préciser auprès du service ; aucune disponibilité en ligne déduite."}
    ref = date_naissance if base == "naissance" else date_document
    y = _year(ref) if ref else None
    res = {"document": document, "type_document": key, "regle": text, "delai_annees": years}
    if base == "naissance" and date_deces:
        yd = _year(date_deces)
        if yd:
            res["communicable_des_deces"] = yd + 25
    if y is None:
        res["communicable"] = None
        res["note"] = "Date de référence inconnue."
        return res
    year_ok = y + years + (1 if years else 0)
    res["communicable_a_partir_de"] = year_ok
    res["communicable"] = today.year >= year_ok or (
        "communicable_des_deces" in res and today.year >= res["communicable_des_deces"])
    res["rgpd"] = ("Ne jamais publier de données sur des personnes vivantes sans leur consentement "
                   "(RGPD, recommandations CNIL).")
    return res
