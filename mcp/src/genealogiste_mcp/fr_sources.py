"""Connaissance des sources françaises : prochaine source à consulter, cotes typiques, communicabilité.

Les cotes indiquées suivent le cadre de classement réglementaire des archives départementales ;
leur numérotation exacte varie d'un service à l'autre : toujours vérifier dans l'inventaire.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import couverture_3e, couverture_recensements
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

# Parcours émigration / immigration (#284). Provenance des affirmations : docs/contexte-historique.md, § Émigration.
# Série R et classe = année de naissance + 20, recensements 6 M, état civil consulaire : déjà affirmés par le dépôt.
# 4 M (police : passeports, police des étrangers) : répertoires de la sous-série 4 M des AD de la Somme et
# d'Indre-et-Loire consultés le 2026-11-23 ; le classement varie d'un service à l'autre. Décrets de naturalisation
# aux Archives nationales : document « Devenir français » des Archives nationales consulté le 2026-11-23.
# Côté étranger : intitulés génériques seulement, aucune cote ni nom de fonds.
FAITS_MIGRATION = frozenset({"EMIG", "IMMI", "NATU", "RESI_ETRANGER"})
POLICE_PASSEPORTS = ("série M, sous-série 4 M (police : passeports, police des étrangers) dans plusieurs services ; "
                     "classement propre à chaque service, à vérifier dans l'inventaire")
DECRETS_NATURALISATION = ("Archives nationales : collection des décrets de naturalisation (inventaire 1883-1948 "
                          "partiellement indexé, salle de lecture virtuelle) ; le numéro de dossier porté au décret "
                          "donne accès au dossier, cote à identifier auprès des Archives nationales")
AVERT_FONDS_FR = ("Existence et classement du fonds non vérifiés pour ce service : à vérifier auprès du service "
                  "d'archives avant de conclure.")
AVERT_FONDS_ETRANGER = ("Existence du fonds non vérifiée par le plugin : intitulé générique, sans cote ; à confirmer "
                        "auprès du service d'archives du pays.")
AVERT_TRANSCRIPTION = "Transcription ou acte consulaire sans garantie d'existence."
SITES_EMIGRATION = 'sources_catalogue(theme="emigration") : sites relevés (guides, index, sources dérivées)'
_COTES_AD = frozenset(SERIES.values()) | {POLICE_PASSEPORTS}


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
        return _migration(fact, when, None) if fact in FAITS_MIGRATION else _hints(fact, when, "")
    pays = pays_du_lieu(where)
    migration = fact in FAITS_MIGRATION or (fact == "RESI" and pays["france"] is False)
    out = _migration(fact, when, pays) if migration else _hints(fact, when, lieu_texte(where))
    if pays["france"] is False and not migration:
        out = _hors_france(fact, out, pays)
    elif pays["france"] is None:
        for d in out:
            if d["cote_typique"] in _COTES_AD:
                d["cote_typique"] = f"{d['cote_typique']} — {SI_FRANCE}"
                d["condition"] = SI_FRANCE
    if pays["france"] is True and not migration:
        _cotes_3e(fact, when, lieu_texte(where), out)
    if pays["france"] is True:
        _cotes_recensements(fact, when, lieu_texte(where), out)
        _matricules_nord(fact, when, lieu_texte(where), out)
        _successions_nord(fact, when, lieu_texte(where), out)
        _hypotheques_nord(fact, when, lieu_texte(where), out)
        _cadastre_nord(fact, lieu_texte(where), out)
    court = pays_resume(pays)
    return [{**d, "pays": dict(court)} for d in out]


def _cotes_3e(fact: str, when: str, lieu: str, sources: list[dict]) -> None:
    """Nord : cotes 3 E connues du classeur des AD59 (#374), jointes à la piste de l'acte ; ajout seulement."""
    document = {"BIRT": "naissance", "MARR": "mariage", "DEAT": "deces"}.get(fact)
    if not document or not lieu:
        return
    from .normalize.places import normalize_place
    place = normalize_place(lieu)
    if place.get("departement_code") != "59":
        return
    try:
        volumes = couverture_3e.pour_fait(document, _year(when), place.get("commune") or "")
    except (OSError, ValueError, KeyError):
        return
    for d in sources:
        if volumes and d["cote_typique"] == SERIES["etat_civil"] and d["source"].startswith("Acte de "):
            d["classeur_3e"] = volumes
            return


def _cotes_recensements(fact: str, when: str, lieu: str, sources: list[dict]) -> None:
    """Nord : cotes de recensement connues de l'état de la collection des AD59 (#375), jointes aux pistes
    « listes nominatives » ; ajout seulement. Millésime de l'année et recensements connus les plus proches, avant
    et après (après seulement pour une naissance ou une filiation)."""
    pistes = [d for d in sources if d["cote_typique"] == SERIES["recensements"]]
    if not pistes or not lieu:
        return
    from .normalize.places import normalize_place
    place = normalize_place(lieu)
    if place.get("departement_code") != "59":
        return
    try:
        volumes = couverture_recensements.pour_fait(_year(when), place.get("commune") or "",
                                                    avant=fact not in ("BIRT", "CHR", "BAPM", "FILIATION"))
    except (OSError, ValueError, KeyError):
        return
    for d in pistes:
        if volumes:
            d["couverture_recensements"] = volumes


def classe_recrutement(annee_naissance: int) -> int:
    """Classe de recrutement d'un registre matricule : année de naissance + 20 (règle déjà affirmée par le dépôt).
    Règle générale seulement : engagés volontaires, ajournés ou classes appelées par anticipation ne sont pas
    traités ; en cas de doute, chercher aussi les classes voisines."""
    if type(annee_naissance) is not int or not 1 <= annee_naissance <= 9979:
        raise ValueError("annee_naissance : année précise (entier de 1 à 9979).")
    return annee_naissance + 20


def _matricules_nord(fact: str, when: str, lieu: str, sources: list[dict]) -> None:
    """Nord : la piste « registre matricule » reçoit la recherche des AD59 (#376) et, pour une naissance datée,
    la classe ; ajout seulement. Aucune cote 1 R n'est donnée ici : elle vient de la réponse du service."""
    pistes = [d for d in sources if d["cote_typique"] == SERIES["matricules"]]
    if not pistes or not lieu:
        return
    from .normalize.places import normalize_place
    if normalize_place(lieu).get("departement_code") != "59":
        return
    y = _year(when) if fact in ("BIRT", "CHR", "BAPM", "FILIATION") else None  # seule date qui soit une naissance
    aide: dict = {"service": "AD59"}
    if y and 1 <= y <= 9979:
        aide["classe"] = classe_recrutement(y)
    aide["recherche"] = (f'archives_registres(service="AD59", commune="", annee={aide.get("classe", "<classe>")}, '
                         'type_acte="RM")')
    aide["note"] = ("Classe = année de naissance + 20. La réponse distingue les tables alphabétiques et les volumes "
                    "des états signalétiques, avec leur cote 1 R réelle : aucune cote n'est proposée ici (pas de "
                    "référentiel local). Le bureau de recrutement (commune, facultatif) n'est pas déduit du lieu : "
                    "sans bureau, la réponse liste ceux de la classe. Vérifier communicabilite(\"matricule\").")
    for d in pistes:
        d["matricules_ad59"] = dict(aide)


# Enregistrement des AD59 (#377) : ce que la présentation du service annonce en ligne au relevé du 27 novembre 2026.
SUCCESSIONS_AD59 = (1791, 1968)
FICHES_DECES_AD59 = (1969, 1975)
AVERT_FICHES_DECES = ("Fiches décès : ne pas les tenir pour librement communicables. Le service affirme un délai de "
                      "50 ans (seules les fiches de plus de 50 ans sont en ligne) ; ce régime n'a pas été vérifié "
                      "par le plugin : voir communicabilite(\"vie_privee\") et interroger le service en cas de doute.")


def _successions_nord(fact: str, when: str, lieu: str, sources: list[dict]) -> None:
    """Nord : la piste « table des successions et absences » reçoit la recherche des AD59 (#377) ; ajout
    seulement. Aucune cote 3 Q ou W n'est donnée ici : elle vient de la réponse du service. Le bureau de
    l'enregistrement n'est pas déduit de la commune."""
    pistes = [d for d in sources if d["cote_typique"] == SERIES["enregistrement"]]
    if not pistes or not lieu:
        return
    from .normalize.places import normalize_place
    if normalize_place(lieu).get("departement_code") != "59":
        return
    y = _year(when) if fact in ("DEAT", "BURI") else None  # seule date qui soit celle du décès
    annee = y if y else "<année du décès>"
    aide: dict = {"service": "AD59", "releve_le": "2026-11-27"}
    appel = 'archives_registres(service="AD59", commune="<bureau de l\'enregistrement>", annee={}, type_acte="{}")'
    if y is None or y <= SUCCESSIONS_AD59[1]:
        aide["recherche"] = appel.format(annee, "SUCC")
    if y is None or FICHES_DECES_AD59[0] <= y <= FICHES_DECES_AD59[1]:
        aide["fiches_deces"] = {"recherche": appel.format(annee, "FD"), "avertissement": AVERT_FICHES_DECES}
    aide["note"] = (f"D'après le service : tables des successions et absences en ligne pour {SUCCESSIONS_AD59[0]}-"
                    f"{SUCCESSIONS_AD59[1]} au plus (fin variable selon les bureaux), fiches décès pour "
                    f"{FICHES_DECES_AD59[0]}-{FICHES_DECES_AD59[1]}. La clé est le bureau de l'enregistrement, pas la "
                    "commune : il n'est pas déduit du lieu ; un bureau inconnu ou ambigu rend la liste des valeurs "
                    "du formulaire. Élargir avec annee_fin si le décès est mal daté. Aucune cote n'est proposée ici "
                    "(pas de référentiel local) : elle vient de la réponse. Une absence dans une table ne prouve "
                    "pas l'absence de décès (autre bureau, décès non déclaré)."
                    + (" Décès postérieur à ce que le service annonce en ligne : aucune recherche proposée."
                       if y and y > FICHES_DECES_AD59[1] else ""))
    for d in pistes:
        d["successions_ad59"] = {k: dict(v) if isinstance(v, dict) else v for k, v in aide.items()}


# Hypothèques des AD59 (#378) : ce que la présentation du service annonce au relevé du 27 novembre 2026.
HYPOTHEQUES_AD59 = (1799, 1955)


def _hypotheques_nord(fact: str, when: str, lieu: str, sources: list[dict]) -> None:
    """Nord : les pistes notariales (contrat de mariage et dot, vente, bien) reçoivent la recherche des hypothèques
    des AD59, sous-série 4 Q (#378) ; ajout seulement. Ni cote ni bureau ne sont proposés : la cote vient de la
    réponse du service, le bureau des hypothèques n'est pas déduit de la commune."""
    pistes = [d for d in sources if d["cote_typique"] == SERIES["notaires"]]
    if not pistes or not lieu:
        return
    # la date d'une naissance ou d'une filiation n'est pas celle de l'acte notarié : aucune année calculée
    y = None if fact in ("BIRT", "CHR", "BAPM", "FILIATION") else _year(when)
    if y and y < HYPOTHEQUES_AD59[0]:
        return
    from .normalize.places import normalize_place
    if normalize_place(lieu).get("departement_code") != "59":
        return
    aide: dict = {"service": "AD59", "releve_le": "2026-11-27", "serie": SERIES["hypotheques"]}
    if y is None or y <= HYPOTHEQUES_AD59[1]:
        annee = y or "<année de l'acte>"
        aide["recherche"] = ('archives_registres(service="AD59", commune="<bureau des hypothèques>", '
                             f'annee={annee}, type_acte="HYP")')
    aide["methode"] = ("indicateur, puis table alphabétique du bureau (numéro de case du propriétaire), puis "
                       "répertoire des formalités (volume et numéro des actes) ; les registres de transcription et "
                       "d'inscription se consultent ensuite en salle de lecture")
    aide["note"] = (f"D'après le service : archives des conservations des hypothèques de {HYPOTHEQUES_AD59[0]} "
                    f"(an VII) à {HYPOTHEQUES_AD59[1]}, recherche par nom de propriétaire seulement ; piste pour un "
                    "bien, une vente ou un mariage avec dot ou apport immobilier, quand le notaire est inconnu. La "
                    "clé est le bureau des hypothèques (arrondissement), pas la commune : il n'est pas déduit du "
                    "lieu ; un bureau inconnu rend la liste des valeurs du formulaire. Aucune cote n'est proposée "
                    "ici (pas de référentiel local) : elle vient de la réponse. Le nom cherché n'est jamais envoyé : "
                    "il sert à choisir, localement, le volume dont la plage alphabétique le couvre. Vérifier "
                    "communicabilite(\"hypotheques\")."
                    + (" Acte postérieur à 1955 : services de la publicité foncière, aucune recherche proposée."
                       if y and y > HYPOTHEQUES_AD59[1] else ""))
    for d in pistes:
        d["hypotheques_ad59"] = dict(aide)


def _cadastre_nord(fact: str, lieu: str, sources: list[dict]) -> None:
    """Nord : plans du cadastre des AD59 (#379) pour situer un lieu-dit ou une parcelle ; ajout seulement. Joint
    à la piste des recensements pour un domicile (RESI, OCCU, CENS), sinon à la piste « Actes notariés » (bien).
    Aucune cote n'est proposée : elle vient de la réponse du service."""
    if fact in ("RESI", "OCCU", "CENS"):
        pistes = [d for d in sources if d["cote_typique"] == SERIES["recensements"]]
    else:
        pistes = [d for d in sources if d["source"] == "Actes notariés"]
    if not pistes or not lieu:
        return
    from .normalize.places import normalize_place
    place = normalize_place(lieu)
    if place.get("departement_code") != "59":
        return
    commune = place.get("commune") or "<commune>"
    aide = {"service": "AD59", "releve_le": "2026-11-27", "serie": SERIES["cadastre"],
            "recherche": (f'archives_registres(service="AD59", commune="{commune}", annee=<année>, '
                          'annee_fin=<année>, type_acte="CAD")'),
            "note": ("Plans du cadastre dit du Consulat et du cadastre dit napoléonien (plans seulement, non "
                     "nominatifs) : situer un lieu-dit, une section ou une parcelle cités par un acte ou un "
                     "recensement. D'après le service : début du XIXe siècle pour les premiers, jusqu'au début du "
                     "XXe siècle pour certaines communes pour les seconds. Un plan vaut pour les décennies qui "
                     "suivent sa levée : aucun n'est écarté sur sa date, tous les lots de la commune sont rendus, "
                     "triés par date et situés par position_periode (anterieur, contemporain, posterieur à la "
                     "période demandée) ; lire d'abord le dernier plan antérieur au fait. Aucune cote n'est proposée ici (pas de "
                     "référentiel local) : elle vient de la réponse. La commune est celle du plan : une commune "
                     "réunie ou renommée se cherche sous son nom d'alors (noms_lies ; geo_historique). Matrices et "
                     "états de sections (propriétaires) : non couverts, à chercher dans l'inventaire du service.")}
    for d in pistes:
        d["cadastre_ad59"] = dict(aide)


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


def _migration(fact: str, when: str, pays: dict | None) -> list[dict]:
    """Chaîne de sources d'un fait de migration (#284), versant français et versant étranger.

    Lieu en France (ou sans lieu, ou pays inconnu) : EMIG = départ de France (séries des AD du lieu, puis pays
    d'arrivée) ; IMMI, NATU = arrivée en France d'un étranger. Lieu hors de France (et RESI, RESI_ETRANGER) :
    Français à l'étranger, aucune série d'AD pour ce lieu ; les pistes françaises renvoient au département du
    dernier domicile en France. Versant étranger : intitulés génériques avec avertissement, aucune cote."""
    y = _year(when)
    out: list[dict] = []
    nom = (pays or {}).get("nom") or ""

    def add(versant: str, source: str, cote: str, pourquoi: str, avertissement: str = "", en_ligne: str = ""):
        d = {"source": source, "cote_typique": cote, "pourquoi": pourquoi, "versant": versant}
        if avertissement:
            d["avertissement"] = avertissement
        if en_ligne:
            d["en_ligne"] = en_ligne
        out.append(d)

    def etranger(source: str, pourquoi: str, ou: str = "pays d'arrivée", pays_nom: str = ""):
        add("etranger", source + (f" ({pays_nom})" if pays_nom else ""),
            f"aucune cote connue du plugin : service d'archives du {ou}" + (f" ({pays_nom})" if pays_nom else "")
            + " ; parcours internationaux : wiki Services-archives", pourquoi, AVERT_FONDS_ETRANGER,
            SITES_EMIGRATION)

    matricule = y is None or y >= 1867
    recensement = y is None or y >= 1836
    if pays is not None and pays["france"] is False or fact == "RESI_ETRANGER":
        if pays is not None and pays["france"] is False:
            out.append({"source": f"État civil et archives du lieu ({nom or 'pays étranger'})",
                        "cote_typique": RENVOI_INTERNATIONAL, "versant": "etranger",
                        "pourquoi": "lieu hors de France : les séries des archives départementales françaises ne "
                                    "s'appliquent pas ; chercher l'état civil ou les registres locaux du pays",
                        "en_ligne": "wiki Services-archives (https://github.com/Hiobi/Genealogiste/wiki/"
                                    "Services-archives)"})
        if matricule:
            add("france", "Registre matricule (classe = année de naissance + 20) du département du dernier "
                          "domicile en France",
                "archives départementales du département de recrutement (dernier domicile en France) : registres "
                "matricules, cote à identifier dans l'inventaire",
                "homme recensé pour le recrutement : adresses successives déclarées, parcours")
        if fact in ("EMIG", "IMMI"):
            add("france", "Passeports et police du département de départ",
                "archives départementales du département de départ (dernier domicile en France) : fonds de police, "
                "cote à identifier dans l'inventaire", "passeport ou visa de départ, surveillance des départs",
                AVERT_FONDS_FR)
        if recensement:
            add("france", "Listes nominatives de recensement de la commune du dernier domicile en France",
                "archives départementales de ce département : recensements, cote à identifier dans l'inventaire",
                "dernière présence au foyer, puis absence au recensement suivant : encadre le départ (une absence "
                "ne prouve pas l'émigration)")
        add("france", "Transcriptions consulaires et état civil consulaire",
            "registres d'état civil de la commune du dernier domicile en France ; Service central d'état civil "
            "(Nantes) pour l'état civil consulaire", PISTE_TRANSCRIPTION, AVERT_TRANSCRIPTION)
        if fact in ("EMIG", "IMMI"):
            etranger("Listes de passagers à l'arrivée", "date d'arrivée, port, âge et lieu d'origine déclarés", "pays", nom)
        etranger("Recensements", "présence et date d'arrivée déclarée dans le pays", "pays", nom)
        etranger("Naturalisation", "déclarations et dossiers de naturalisation : origine, date d'arrivée", "pays",
                 nom)
        if fact != "NATU":
            etranger("Conscription et registres militaires", "enregistrement militaire des résidents", "pays", nom)
        return out
    if fact == "EMIG":
        if matricule:
            add("france", "Registre matricule (classe = année de naissance + 20)", SERIES["matricules"],
                "adresses successives déclarées, parcours ; homme recensé pour le recrutement")
        add("france", "Passeports et police des étrangers", POLICE_PASSEPORTS,
            "passeport ou visa de départ, surveillance des départs", AVERT_FONDS_FR)
        if recensement:
            add("france", "Listes nominatives de recensement avant et après le départ", SERIES["recensements"],
                "dernière présence au foyer, puis absence au recensement suivant : encadre le départ (une absence "
                "ne prouve pas l'émigration)", en_ligne="AD")
        add("france", "Transcriptions consulaires et état civil consulaire",
            "registres d'état civil de la commune du dernier domicile en France ; Service central d'état civil "
            "(Nantes) pour l'état civil consulaire", PISTE_TRANSCRIPTION, AVERT_TRANSCRIPTION)
        etranger("Listes de passagers à l'arrivée", "date d'arrivée, port, âge et lieu d'origine déclarés")
        etranger("Recensements du pays d'arrivée", "présence et date d'arrivée déclarée")
        etranger("Naturalisation dans le pays d'arrivée", "déclarations et dossiers : origine, date d'arrivée")
        etranger("Conscription et registres militaires du pays d'arrivée", "enregistrement militaire des résidents")
        return out
    # IMMI, NATU en France : un étranger arrive ou est naturalisé
    if fact == "NATU":
        add("france", "Décret et dossier de naturalisation", DECRETS_NATURALISATION,
            "décret publié, puis dossier : origine, date d'arrivée, famille", AVERT_FONDS_FR)
    add("france", "Police des étrangers (déclarations de résidence, cartes d'identité d'étranger)", POLICE_PASSEPORTS,
        "déclaration de résidence, nationalité, date d'arrivée", AVERT_FONDS_FR)
    if recensement:
        add("france", "Listes nominatives de recensement", SERIES["recensements"],
            "première présence au foyer, nationalité déclarée selon les années", en_ligne="AD")
    if fact == "IMMI":
        add("france", "Décret et dossier de naturalisation (si demandée)", DECRETS_NATURALISATION,
            "décret publié, puis dossier : origine, date d'arrivée, famille", AVERT_FONDS_FR)
    etranger("État civil et archives du pays d'origine", "naissance et famille avant le départ", "pays d'origine")
    etranger("Passeports et autorisations de sortie du pays d'origine", "date et motif du départ", "pays d'origine")
    return out


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
