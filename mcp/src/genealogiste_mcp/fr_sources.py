"""Connaissance des sources françaises : prochaine source à consulter, cotes typiques, communicabilité.

Les cotes indiquées suivent le cadre de classement réglementaire des archives départementales ;
leur numérotation exacte varie d'un service à l'autre : toujours vérifier dans l'inventaire.
"""

from __future__ import annotations

from datetime import date

from .normalize.dates import parse_date

SERIES = {
    "etat_civil": "série E / sous-série 4 E ou E-dépôt (collection du greffe) ; mairie pour la collection communale",
    "paroissiaux": "registres BMS : série E / 4 E (collection du greffe) ou G (clergé séculier), parfois GG en dépôt communal",
    "tables_decennales": "série E / 4 E (souvent en ligne avec l'état civil), une table par commune et par décennie depuis 1792",
    "recensements": "série M, sous-série 6 M (listes nominatives quinquennales depuis 1836)",
    "matricules": "série R, sous-série 1 R (registres matricules, classes 1867 et suivantes ; bureau de recrutement)",
    "notaires": "série E, sous-série 3 E (minutes notariales, par étude) — répertoires pour localiser l'acte",
    "enregistrement": "série Q, sous-série 3 Q (bureaux de l'enregistrement : tables des successions et absences, mutations par décès)",
    "hypotheques": "série Q, sous-série 4 Q (conservation des hypothèques : transcriptions, inscriptions)",
    "cadastre": "série P, sous-série 3 P (cadastre napoléonien : plans, états de sections, matrices)",
    "justice": "série U (tribunaux civils, justices de paix : tutelles, émancipations, actes de notoriété)",
    "insinuation": "série C (contrôle des actes, insinuations, centième denier — avant 1790)",
}


def _year(d: str) -> int | None:
    g = parse_date(d) if d else None
    if not g:
        return None
    lo, hi = g.interval
    from .normalize.dates import jdn_to_gregorian
    return (jdn_to_gregorian(lo)[0] + jdn_to_gregorian(hi)[0]) // 2


def next_source_hint(fact: str, when: str = "", where: str = "") -> list[dict]:
    """Sources à consulter pour étayer un fait, par ordre de priorité."""
    y = _year(when)
    lieu = f" de {where.split(',')[0]}" if where else ""
    out: list[dict] = []

    def add(source: str, cote: str, pourquoi: str, en_ligne: str = ""):
        d = {"source": source, "cote_typique": cote, "pourquoi": pourquoi}
        if en_ligne:
            d["en_ligne"] = en_ligne
        out.append(d)

    civil = y is None or y >= 1792
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

RULES = {
    "naissance": (75, "acte", "Registres de naissance : 75 ans après la clôture du registre (art. L213-2 Code du patrimoine)."),
    "mariage": (75, "acte", "Registres de mariage : 75 ans après la clôture du registre."),
    "deces": (0, "acte", "Actes de décès : communicables immédiatement."),
    "tables_decennales": (75, "acte", "Suivent en pratique le régime des actes qu'elles indexent : vérifier auprès du service."),
    "recensement": (75, "acte", "Listes nominatives : 75 ans (secret statistique)."),
    "notaire": (75, "acte", "Minutes et répertoires notariaux : 75 ans à compter de la date de l'acte."),
    "matricule": (120, "naissance",
                  "Registres matricules (données médicales) : 120 ans après la naissance ou 25 ans après le décès ; "
                  "en pratique mis en ligne par classes anciennes."),
    "judiciaire": (75, "acte", "Dossiers judiciaires : 75 ans (100 ans si mineurs concernés)."),
    "vie_privee": (50, "acte", "Documents portant atteinte à la vie privée (ex. enregistrement, successions) : 50 ans."),
    "medical": (120, "naissance", "Secret médical : 120 ans après la naissance ou 25 ans après le décès."),
    "cadastre": (0, "acte", "Cadastre : communicable immédiatement."),
    "hypotheques": (0, "acte", "Publicité foncière : en principe communicable ; vérifier les délais propres au service."),
}


def communicability(document: str, date_document: str = "", date_naissance: str = "",
                    date_deces: str = "", today: date | None = None) -> dict:
    today = today or date.today()
    key = document.lower().replace("é", "e").replace("è", "e").replace(" ", "_")
    if key not in RULES:
        return {"erreur": f"Type inconnu. Types : {', '.join(RULES)}"}
    years, base, text = RULES[key]
    ref = date_naissance if base == "naissance" else date_document
    y = _year(ref) if ref else None
    res = {"document": document, "regle": text, "delai_annees": years}
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
