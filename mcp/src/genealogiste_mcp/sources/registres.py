"""Recherche de registres sur le HTML serveur Mnesys Expo : AD59 qualifié (relevés des 16, 18 et 27 novembre 2026 ;
registres matricules : tables et fiches des états signalétiques, #376 ; enregistrement : tables des successions
et absences et fiches décès, #377 ; hypothèques, sous-série 4 Q : indicateurs, tables et répertoires, #378 ;
cadastre : plans du Consulat (P 30) et napoléoniens (P 31), #379) et services déclarant
``recherche_registres`` dans le référentiel (formulaire lu en ligne, sources/mnesys.py, #128).

Une page par appel, sans exploration de JavaScript, de notice, de métadonnées ni d'image.
Les ARK de registre viennent du lien de notice, jamais du lien de miniature (ARK de vue).
"""

from __future__ import annotations

import re
from copy import copy
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .. import archives, ark, couverture_3e, couverture_recensements
from ..normalize.names import strip_accents
from . import mnesys
from .base import DAY, SourceContext, SourceError, envelope, error_envelope

HOST = "https://archivesdepartementales.lenord.fr"
URL = HOST + "/search/results"
FORMULAIRE = "dc4e871d-0b62-41fb-9921-5ded573781b8"
FORMULAIRE_TD = "25905104-0354-4e23-aea0-e3b68cf1f881"  # tables décennales (relevé du 18 novembre 2026)
FORMULAIRE_REC = "f0366f8a-2ef6-4cf2-b47b-6dec4a19e99f"  # recensements de population (relevé du 27 novembre 2026)
# Registres matricules (série 1 R, relevé du 27 novembre 2026, #376) : deux formulaires, bureau de recrutement et
# classe. « tables » : une table alphabétique par classe et par bureau (période ou année précise) ; « fiches » :
# volumes des états signalétiques et des services (année précise seulement).
FORMULAIRES_RM = {"tables": "0d3ab9ff-3258-4541-bf65-c3094fb024a0", "fiches": "9d12049e-510c-4c14-ad31-0fc5487c199c"}
RELEVE_RM = "2026-11-27"
# Libellé du champ d'année du formulaire des fiches, tel que relevé : il borne ce qui est en ligne, pas ce qui existe.
PERIODE_FICHES_RM = "classes 1867 à 1923, Valenciennes-Douai à partir de 1908"
LECTURE_RM = ("tables : une table alphabétique par classe et par bureau de recrutement ; fiches : volumes des états "
              "signalétiques et des services de la classe, par bureau (contexte) et parfois par tranche de numéros "
              "matricules (titre). D'après les intitulés des résultats : le contenu des vues n'est pas lu.")
# Enregistrement (relevé du 27 novembre 2026, #377) : tables des successions et absences (3 Q, type SUCC) et
# fiches décès (versements W, type FD), un formulaire chacun, dont la clé est le bureau de l'enregistrement.
FORMULAIRES_ENREGISTREMENT = {"SUCC": "6eaeac65-9e1b-43ea-bc9f-902abd458466",
                              "FD": "4e904e28-8a75-4be1-b9f6-b4138afe4956"}
RELEVE_ENREGISTREMENT = "2026-11-27"
PAGE_ENREGISTREMENT = HOST + "/page/tables-des-successions-et-absences-fiches-deces"
# Ce que la présentation du service annonce (page et formulaires relevés) : cela borne ce qui est en ligne.
PERIODE_SUCC = "au maximum 1791-1968, l'année de fin variant selon les bureaux"
PERIODE_FD = "1969 à 1975"
DELAI_FD = 50  # années, d'après la présentation du service ; type « vie_privee » de communicabilite
LECTURE_SUCC = ("Tables alphabétiques tenues par bureau de l'enregistrement. D'après la présentation du service : "
                "selon les époques, profession, domicile et âge du défunt, date du décès, situation de famille, date "
                "de la déclaration de succession s'il y en a une ; le ressort d'un bureau dépasse la commune. Le "
                "contenu des vues n'est pas lu.")
LECTURE_FD = ("Fiches décès de l'enregistrement, suite des tables des successions d'après la présentation du service : "
              "classées par année de décès puis par ordre alphabétique (tranche de lettres dans le titre), elles "
              "renvoient au numéro de la déclaration de succession. Le contenu des vues n'est pas lu.")
NON_VERIFIE_FD = ("Régime non vérifié par le plugin : le délai de 50 ans est celui qu'affirme le service (« délais de "
                  "communicabilité du code du Patrimoine », sans article cité) ; ni l'article applicable, ni le point "
                  "de départ du délai, ni la nature exacte du fonds n'ont été vérifiés dans un texte ou auprès du "
                  "service.")
# Hypothèques (sous-série 4 Q, relevé du 27 novembre 2026, #378) : trois formulaires dont le seul champ est le bureau
# des hypothèques (aucune date). Ordre de lecture d'après la présentation du service : indicateur, table, répertoire.
FORMULAIRES_HYP = {"indicateur": "02ec9ec7-856b-47f7-a59f-f9716d6823a3",
                   "tables": "50d53c90-a6c8-46f9-886c-e75fa91a60cb",
                   "repertoires": "330c559b-0684-4649-b7e8-7d1123a83433"}
# type_acte -> catégories interrogées : HYP les trois (une page chacune), HYPI, HYPT ou HYPR une seule
TYPES_HYP = {"HYP": tuple(FORMULAIRES_HYP), "HYPI": ("indicateur",), "HYPT": ("tables",), "HYPR": ("repertoires",)}
RELEVE_HYP = "2026-11-27"
PAGE_HYP = HOST + "/page/tables-et-repertoires-des-hypotheques"
PERIODE_HYP = ("archives des conservations des hypothèques de l'an VII (1799) à 1955 ; Valenciennes : registres de "
               "1800-1940 détruits pendant la Seconde Guerre mondiale ; après 1955 : services de la publicité foncière")
METHODE_HYP = ("D'après la présentation du service : 1. indicateur (noms de famille des propriétaires par ordre "
               "alphabétique, sans prénoms) pour s'orienter dans la table ; 2. table alphabétique (noms classés par "
               "ordre alphabétique et organisés phonétiquement, avec prénoms) pour relever le numéro de case du "
               "propriétaire ; 3. répertoire des formalités (classé par numéro de case, un compte par propriétaire) "
               "pour relever volume et numéro des actes ; les registres de transcription et d'inscription se "
               "consultent ensuite en salle de lecture. La recherche se fait par nom de propriétaire, pas par "
               "adresse du bien.")
LECTURE_HYP = ("Titre « bureau (série ou période) : cote (plage alphabétique) » : bureau_titre, periode_titre et "
               "plage_alphabetique en sont tirés, sans rien lire des vues. La plage n'est qu'indicative (classement "
               "phonétique, plages qui se chevauchent, séries parallèles d'un même bureau) : comparer localement "
               "l'initiale ou le début du nom cherché à debut et fin (capitales sans accents), sans jamais "
               "transmettre ce nom ; les répertoires n'ont pas de plage (classement par numéro de case).")
NON_VERIFIE_HYP = ("La page du service relevée ne dit rien d'un délai de communicabilité pour ces registres d'ordre ; "
                   "la règle rendue est celle du type « hypotheques » de communicabilite, indicative et non vérifiée "
                   "auprès du service. Un compte de propriétaire peut citer des personnes encore vivantes (contenu "
                   "non lu).")
# Cadastre (relevé du 27 novembre 2026, #379) : deux formulaires de plans dont le seul champ est la commune (aucune
# date), chacun avec son vocabulaire. Ordre des cotes : P 30 (plans dits du Consulat), P 31 (plans dits napoléoniens).
FORMULAIRES_CAD = {"consulaire": "fff966ed-72a2-47ea-8564-ab533e334daa",
                   "napoleonien": "b57520fe-2768-4335-b138-119f274f0a73"}
RELEVE_CAD = "2026-11-27"
PAGE_CAD = HOST + "/page/plans-du-cadastre-du-consulat-et-napoleonien"
PERIODE_CAD = ("plans du cadastre dit du Consulat : début du XIXe siècle ; plans du cadastre dit napoléonien : une "
               "plus large période, jusqu'au début du XXe siècle pour certaines communes")
LECTURE_CAD = ("Un résultat est un lot de plans d'une commune (plans, non nominatifs) : « COMMUNE / numéro » pour le "
               "cadastre du Consulat, sans date ; « COMMUNE - année » pour le cadastre napoléonien, parfois suivi "
               "d'une plage de feuilles (« (TA-B12) »). Une commune peut avoir plusieurs lots (levées successives, "
               "suffixes de cote _1, _2, cote partagée). annee_titre reprend l'année du titre, pour information : "
               "seule la date affichée par le service (bornes) écarte un plan. Un plan décrit le territoire pour "
               "les décennies qui suivent sa levée. planche_contact : appel proposé pour les lots de 2 à 9 vues. "
               "Le contenu des vues n'est pas lu.")
NON_COUVERT_CAD = ("Matrices cadastrales et états de sections (propriétaires) : absents de ces deux formulaires ; "
                   "leur mise en ligne et leur cote n'ont pas été relevées : consulter l'inventaire du service.")
NON_VERIFIE_CAD = ("La page du service relevée ne dit rien d'un délai de communicabilité ; la règle rendue est celle "
                   "du type « cadastre » de communicabilite, indicative et non vérifiée auprès du service.")
PISTE_LIEU_CAD = ("Commune réunie à une autre ou renommée : les plans sont classés sous le nom porté par le "
                  "formulaire, qui diffère d'un cadastre à l'autre ; geo_historique(nom) donne les fusions et "
                  "changements de nom depuis 1943, lieu_historique(lieu, date) la commune à une date.")
MAX_HTML = 2_000_000
MAX_PROFONDEUR = 128
TYPES = {"N": "Naissances", "M": "Mariages", "D": "Décès"}
_VIDES = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class FormatRegistresError(ValueError):
    """Le document ne permet pas de conclure à une recherche positive ou négative."""


@dataclass
class _Noeud:
    tag: str
    attrs: dict = field(default_factory=dict)
    enfants: list = field(default_factory=list)

    def texte(self) -> str:
        return " ".join(" ".join(e.texte() if isinstance(e, _Noeud) else e for e in self.enfants).split())

    def trouver(self, tag: str = "", classe: str = "", identifiant: str = "") -> list[_Noeud]:
        matches = []
        if ((not tag or self.tag == tag) and (not classe or classe in self.attrs.get("class", "").split())
                and (not identifiant or self.attrs.get("id") == identifiant)):
            matches.append(self)
        for enfant in self.enfants:
            if isinstance(enfant, _Noeud):
                matches.extend(enfant.trouver(tag, classe, identifiant))
        return matches


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.racine = _Noeud("")
        self.pile = [self.racine]

    def handle_starttag(self, tag, attrs):
        if len(self.pile) >= MAX_PROFONDEUR:
            raise FormatRegistresError("HTML de recherche trop profond : format refusé.")
        noeud = _Noeud(tag, {cle: valeur or "" for cle, valeur in attrs})
        self.pile[-1].enfants.append(noeud)
        if tag not in _VIDES:
            self.pile.append(noeud)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VIDES:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.pile) - 1, 0, -1):
            if self.pile[i].tag == tag:
                del self.pile[i:]
                return

    def handle_data(self, data):
        self.pile[-1].enfants.append(data)


def _unique(noeuds: list[_Noeud], champ: str) -> _Noeud:
    if len(noeuds) != 1:
        raise FormatRegistresError(f"Format de recherche non reconnu ({champ}) ; consulter la recherche manuellement.")
    return noeuds[0]


def _registre(bloc: _Noeud, host: str = HOST, naan: str = "33518", contexte: bool = False) -> dict:
    intitule = _unique(bloc.trouver(classe="intitup"), "intitulé")
    lien = _unique(intitule.trouver("a"), "lien de notice")
    titre = _unique(lien.trouver("h2"), "titre").texte()
    url = urljoin(host, lien.attrs.get("href", ""))
    parsed = urlsplit(url)
    identifiant = ark.find(url)
    if (not titre or parsed.scheme != "https" or parsed.hostname != urlsplit(host).hostname
            or parsed.port not in (None, 443) or parsed.username is not None or parsed.password is not None
            or not identifiant or identifiant.naan != naan or identifiant.qualificatif
            or not re.fullmatch(rf"/ark:/{naan}/[^/]+/?", parsed.path)):
        raise FormatRegistresError("Lien de notice incohérent ou hors du service : registre refusé.")
    cotes = bloc.trouver("p", classe="referenceCodes")
    cote = _unique(cotes, "cote").texte() if cotes or naan == "33518" else None  # cote facultative hors AD59
    if cote:  # libellé collé à chaque valeur : « 5MI_D271 (Cote(s)) » (AD80), « 3Q23 (Cote), 6NUM3/001/007 (Cote) » (AD37)
        cote = re.sub(r"\s*\(Cote(?:s|\(s\))?\)(?=\s*(?:,|$))", "", cote) or None
    bornes = None
    for partie in bloc.trouver(classe="content-sub-part"):
        if [h.texte() for h in partie.trouver("h3")] == ["Date"]:
            valeurs = partie.trouver("p")
            date = valeurs[0].texte() if len(valeurs) == 1 else ""
            m = re.fullmatch(r"(\d{1,4})(?:\s*[-–]\s*(\d{1,4}))?", date)
            if m:
                debut, fin = int(m[1]), int(m[2] or m[1])
                if 1 <= debut <= fin <= 9999:
                    bornes = [debut, fin]
    medias = bloc.trouver("p", classe="info-list-picture")
    nb_vues = None
    if len(medias) == 1:
        m = re.fullmatch(r"([\d\s\u00a0\u202f]+)\s+medias", medias[0].texte())
        if m:
            nb_vues = int("".join(m[1].split()))
    registre = {"titre": titre, "cote": cote, "ark": identifiant.base,
                "url": url, "bornes": bornes, "nb_vues": nb_vues}
    if contexte:  # « Contexte : Registres numérisés des matricules militaires (Avesnes) » : bureau des fiches (#376)
        lignes = bloc.trouver("div", classe="context-content")
        registre["contexte"] = re.sub(r"^Contexte\s*:\s*", "", lignes[0].texte()) or None if lignes else None
    return registre


def _lire(html: str, page: int, host: str = HOST, naan: str = "33518",
          contexte: bool = False) -> tuple[list[dict], int, int | None]:
    if len(html) > MAX_HTML:
        raise FormatRegistresError("Réponse de recherche trop volumineuse : consultation manuelle nécessaire.")
    parser = _HTML()
    parser.feed(html)
    body = _unique(parser.racine.trouver("body"), "page")
    liste = _unique(body.trouver("section", identifiant="list-container"), "liste de résultats")
    blocs = liste.trouver("li", classe="element-list")
    negatifs = liste.trouver("div", classe="no-result")
    if (body.attrs.get("id") == "display-no-results" and not blocs and len(negatifs) == 1
            and negatifs[0].texte() == "Aucun résultat ne correspond à votre requête"):
        if page != 1:
            raise FormatRegistresError("Page hors bornes ou résultat négatif de pagination non qualifié.")
        return [], 0, None
    if body.attrs.get("id") != "display-results" or not blocs or negatifs:
        raise FormatRegistresError("Format de recherche non reconnu : aucun résultat négatif ne peut être déduit.")
    pagination = _unique(body.trouver("input", identifiant="current-page"), "pagination")
    try:
        courante, maximum = int(pagination.attrs["value"]), int(pagination.attrs["max"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FormatRegistresError("Pagination non reconnue.") from exc
    if pagination.attrs.get("name") != "page" or courante != page or not 1 <= courante <= maximum:
        raise FormatRegistresError("Page retournée incohérente ou hors bornes : consultation manuelle nécessaire.")
    compteur = _unique(body.trouver("span", classe="result"), "nombre de résultats").texte()
    m = re.fullmatch(r"([\d\s\u00a0\u202f]+)\s+résultats?", compteur)
    if not m:
        raise FormatRegistresError("Nombre de résultats non reconnu ou incohérent.")
    total = int("".join(m[1].split()))
    # Chaque autre page annoncée doit contenir au moins un résultat ; une page unique est exhaustive.
    if total < len(blocs) + maximum - 1 or (maximum == 1 and total != len(blocs)):
        raise FormatRegistresError("Pagination et nombre de résultats incohérents.")
    tailles = body.trouver("li", classe="select-results-per-page")
    if tailles:
        taille = _unique(_unique(tailles, "taille de page").trouver("p", classe="placeholder"), "taille de page")
        m = re.fullmatch(r"(\d+) résultats par page", taille.attrs.get("title", ""))
        if not m or int(m[1]) < 1:
            raise FormatRegistresError("Taille de page non reconnue.")
        taille_page = int(m[1])
        if (maximum != (total + taille_page - 1) // taille_page
                or len(blocs) != min(taille_page, total - (page - 1) * taille_page)):
            raise FormatRegistresError("Fenêtre de résultats incomplète ou pagination incohérente.")
    return [_registre(bloc, host, naan, contexte) for bloc in blocs], total, page + 1 if page < maximum else None


def _couvre(bornes: list[int] | None, periode: list[int]) -> bool | None:
    """Recouvrement des bornes affichées et de la période demandée ; None si les bornes sont inconnues."""
    return None if bornes is None else bornes[0] <= periode[1] and periode[0] <= bornes[1]


def services_registres() -> list[str]:
    """Services dont la recherche de registres par commune et année est disponible."""
    return ["AD59", *sorted(s["code"] for s in archives.services() if s.get("recherche_registres"))]


def _formulaire(http, host: str, uuid: str) -> dict:
    """Champs d'un formulaire public Mnesys, lu en ligne (une requête, en cache une semaine)."""
    form, _ = http.get(f"{host}/search/form/{uuid}", parse="text", ttl=7 * DAY, source="archives")
    if len(form) > MAX_HTML:
        raise FormatRegistresError("Formulaire de recherche trop volumineux : consultation manuelle nécessaire.")
    parser = _HTML()
    parser.feed(form)
    return mnesys.lire_formulaire(parser.racine.trouver())


def _matricules_ad59(http, bureau: str, periode: list[int], page: int) -> tuple[list[dict], int, int | None, bool, dict]:
    """Registres matricules des AD59 (#376) : les deux formulaires sont lus puis interrogés, une page chacun.

    Règle : une classe précise interroge les tables et les fiches ; un intervalle n'interroge que les tables, seul
    formulaire doté d'une période (les fiches, triées par date sur des dizaines de pages, ne se filtrent pas
    localement). Le bureau, facultatif, est pris dans le vocabulaire de chaque formulaire. Les résultats portent
    ``categorie`` (tables, fiches) et ``contexte`` ; l'état de chaque formulaire est rendu à part."""
    etats: dict[str, dict] = {}
    requetes: dict[str, dict] = {}
    for categorie, uuid in FORMULAIRES_RM.items():  # formulaires et bureau contrôlés avant toute recherche
        f = _formulaire(http, HOST, uuid)
        if not f["commune"] or not f["date"]:
            raise mnesys.FormulaireError(f"Formulaire des {categorie} des matricules AD59 non reconnu (bureau ou "
                                         "année absents) : consulter la recherche manuellement.")
        etat = etats[categorie] = {"formulaire": uuid, "interroge": False, "bureau": None, "total": None,
                                   "page_suivante": None, "bureaux": f["communes"]}
        requete = {"formUuid": uuid, "sort": "date_asc", "mode": "list", "facet_media": "image"}
        if bureau:
            try:
                etat["bureau"] = mnesys.choisir_commune(f["communes"], bureau)
            except ValueError as exc:
                etat["message"] = str(exc).replace("Commune «", "Bureau de recrutement «", 1)
                continue
            requete[f["commune"] + "[]"] = etat["bureau"]
        if periode[0] == periode[1]:
            requete[f["date"]] = str(periode[0])
        elif f["debut"] and f["fin"]:
            requete[f["debut"]], requete[f["fin"]] = str(periode[0]), str(periode[1])
        else:
            etat["message"] = ("Formulaire sans période : non interrogé pour un intervalle. Relancer avec annee "
                               "seule (annee_fin=0) pour chaque classe.")
            continue
        requetes[categorie] = {**requete, "page": page}
    if bureau and not any(e["bureau"] for e in etats.values()):
        connus = sorted({b for e in etats.values() for b in e["bureaux"]})
        raise ValueError(f"{next(iter(etats.values()))['message']} Bureaux de recrutement proposés par les "
                         f"formulaires : {', '.join(connus)} ; le bureau est facultatif.")
    if not requetes:  # bureau propre à un formulaire que la période écarte : rien à interroger, rien à conclure
        raise ValueError("Aucun formulaire des matricules AD59 ne peut être interrogé : "
                         + " ; ".join(f"{c} : {e['message']}" for c, e in etats.items()))
    resultats: list[dict] = []
    total, suivante, cached, lues, refus = 0, None, True, 0, None
    for categorie, requete in requetes.items():
        etat = etats[categorie]
        html, cache = http.get(URL, params=requete, parse="text", ttl=DAY, source="archives")
        etat["interroge"] = True
        cached = cached and cache
        try:
            lus, etat["total"], etat["page_suivante"] = _lire(html, page, contexte=True)
        except FormatRegistresError as exc:
            if page == 1:
                raise
            # Page absente d'une catégorie (redirection vers la première observée sur l'état civil, #221 ; non
            # observée ici) : rien n'est conclu pour elle, l'autre catégorie reste lisible.
            refus = exc
            etat["message"] = f"Aucune page {page} lue pour cette catégorie : {exc}"
            continue
        lues += 1
        if not lus:
            etat["message"] = "Aucun résultat pour cette recherche ; cela ne prouve pas l'absence du registre." + (
                f" Le formulaire relevé le {RELEVE_RM} annonçait : {PERIODE_FICHES_RM}." if categorie == "fiches"
                else "") + (" Relancer sans bureau, ou avec une autre valeur de bureaux." if etat["bureau"] else "")
        total += etat["total"]
        if etat["page_suivante"]:
            suivante = etat["page_suivante"]
        resultats.extend({**r, "categorie": categorie} for r in lus)
    if refus and not lues:
        raise refus
    return resultats, total, suivante, cached, {"matricules": {"releve_le": RELEVE_RM, "lecture": LECTURE_RM, **etats}}


def _enregistrement_ad59(http, type_acte: str, bureau: str, periode: list[int],
                         page: int) -> tuple[dict, dict, bool]:
    """Tables des successions et absences (SUCC, 3 Q) ou fiches décès (FD, W) des AD59 (#377) : (requête, ajouts
    à la réponse, filtre local).

    Le formulaire est lu en ligne ; le bureau de l'enregistrement, obligatoire comme pour SUCC ailleurs, est pris
    dans son vocabulaire. SUCC : la période va dans les champs de début et de fin, même pour une seule année
    (comme pour les autres services). FD : le formulaire n'a qu'une année précise ; un intervalle n'envoie que
    le bureau et la période est filtrée localement sur les bornes affichées."""
    uuid = FORMULAIRES_ENREGISTREMENT[type_acte]
    quoi = "tables des successions" if type_acte == "SUCC" else "fiches décès"
    f = _formulaire(http, HOST, uuid)
    if not f["commune"] or not (f["debut"] and f["fin"] if type_acte == "SUCC" else f["date"]):
        raise mnesys.FormulaireError(f"Formulaire des {quoi} AD59 non reconnu (bureau ou date absents) : "
                                     "consulter la recherche manuellement.")
    exactes = [o for o in f["communes"] if mnesys.cle(o) == mnesys.cle(bureau)]  # « LILLE (CENTRE) » saisi tel quel
    try:
        valeur = exactes[0] if len(exactes) == 1 else mnesys.choisir_commune(f["communes"], bureau)
    except ValueError as exc:
        message = str(exc).replace("Commune «", "Bureau de l'enregistrement «", 1).replace(
            "comme commune.", "comme commune (c'est le bureau, pas la commune du décès).")
        if "absente" in message:
            message += f" Bureaux proposés par le formulaire : {', '.join(f['communes'])}."
        raise ValueError(message) from exc
    nom = mnesys.cle(valeur.split(" (")[0])
    etat = {"releve_le": RELEVE_ENREGISTREMENT, "formulaire": uuid, "bureau": valeur,
            # autres valeurs du vocabulaire pour le même nom (« LILLE (1er bureau) »...) : à interroger à part
            "autres_bureaux": [o for o in f["communes"] if o != valeur and mnesys.cle(o.split(" (")[0]) == nom],
            "reference": PAGE_ENREGISTREMENT}
    # tri : chronologique pour les tables ; par cote pour les fiches (défaut du formulaire, ordre des lettres)
    requete = {"formUuid": uuid, "sort": "date_asc" if type_acte == "SUCC" else "referencecode_asc", "mode": "list",
               "facet_media": "image", f["commune"] + "[]": valeur}
    filtre_local = False
    if type_acte == "SUCC":
        requete[f["debut"]], requete[f["fin"]] = str(periode[0]), str(periode[1])
        etat.update(periode_annoncee=PERIODE_SUCC, lecture=LECTURE_SUCC)
        return {**requete, "page": page}, {"commune_service": valeur, "successions": etat}, filtre_local
    if periode[0] == periode[1]:
        requete[f["date"]] = str(periode[0])
    else:
        filtre_local = True
    etat.update(periode_annoncee=PERIODE_FD, lecture=LECTURE_FD)
    return {**requete, "page": page}, {"commune_service": valeur, "fiches_deces": etat}, filtre_local


def _cle_nom(texte: str) -> str:
    """Forme de comparaison d'un nom ou d'un début de nom : capitales sans accents, lettres seules."""
    return re.sub(r"[^A-Z]", "", strip_accents(texte or "").upper())


# séparateur des deux bornes d'une plage : tiret(s) accompagné(s) d'au moins une espace (« A - B », « A- -B »),
# pour ne pas couper un nom à trait d'union
_SEPARATEUR_PLAGE = re.compile(r"(?:\s*-)+\s+(?:-\s*)*|\s+(?:-\s*)+")


def titre_hypotheques(titre: str) -> dict:
    """Lecture d'un titre de volume de la sous-série 4 Q des AD59 (#378), tel qu'affiché :
    « Lille 2 (1901-1955) : 4Q 84 / 045 (De Fay - Degarnier) ». Rend bureau_titre (libellé avant « : »),
    periode_titre ([début ou None, fin] si le libellé porte « avant AAAA » ou « AAAA-AAAA », sinon None) et
    plage_alphabetique ({texte, debut, fin} ; debut et fin en capitales sans accents, None si la parenthèse n'est
    pas une plage ; None s'il n'y a pas de parenthèse). Fonction pure : rien n'est déduit au-delà du titre."""
    out = {"bureau_titre": None, "periode_titre": None, "plage_alphabetique": None}
    bureau, sep, reste = (titre or "").partition(" : ")
    if not sep or not bureau.strip():
        return out
    out["bureau_titre"] = bureau = " ".join(bureau.split())
    if m := re.search(r"\(\s*avant\s+(\d{4})\s*\)", bureau, re.I):
        out["periode_titre"] = [None, int(m[1]) - 1]
    elif (m := re.search(r"\(\s*(\d{4})\s*[-–]\s*(\d{4})\s*\)", bureau)) and int(m[1]) <= int(m[2]):
        out["periode_titre"] = [int(m[1]), int(m[2])]
    if m := re.fullmatch(r"[^()]*\((.*)\)\s*", reste):
        texte = " ".join(m[1].split())
        bornes = [_cle_nom(b) for b in _SEPARATEUR_PLAGE.split(texte)]
        plage = len(bornes) == 2 and all(bornes)
        out["plage_alphabetique"] = {"texte": texte, "debut": bornes[0] if plage else None,
                                     "fin": bornes[1] if plage else None}
    return out


def plage_couvre(plage: dict | None, prefixe: str) -> bool | None:
    """Une plage alphabétique lue dans un titre peut-elle contenir un nom commençant par ``prefixe`` (initiale ou
    début de nom) ? Comparaison locale, capitales sans accents, bornes comprises et tronquées à la longueur du
    préfixe. None si la plage est absente ou illisible, ou le préfixe sans lettre. Indicatif : le service dit les
    tables « organisées phonétiquement », un nom peut donc se trouver dans un volume voisin."""
    cible = _cle_nom(prefixe)
    if not cible or not plage or not plage.get("debut") or not plage.get("fin"):
        return None
    return plage["debut"][:len(cible)] <= cible <= plage["fin"][:len(cible)]


def volumes_couvrant(resultats: list[dict], prefixe: str) -> list[dict]:
    """Volumes d'une réponse HYP dont la plage alphabétique couvre l'initiale ou le début de nom donné (#378).
    Le préfixe n'est comparé que localement : il n'est ni envoyé au service, ni journalisé. Les volumes sans
    plage lisible (répertoires, « (unique) Sociétés ») ne sont pas rendus : ils ne sont ni couverts ni exclus."""
    return [r for r in resultats if plage_couvre(r.get("plage_alphabetique"), prefixe)]


def _hypotheques_ad59(http, type_acte: str, bureau: str, periode: list[int], page: int,
                      aujourdhui: date) -> tuple[list[dict], int, int | None, bool, dict]:
    """Hypothèques des AD59, sous-série 4 Q (#378) : indicateurs, tables alphabétiques et répertoires des
    formalités, un formulaire chacun, dont le seul champ est le bureau des hypothèques (obligatoire).

    Règle : HYP interroge les trois catégories, une page chacune ; HYPI, HYPT ou HYPR une seule (pour feuilleter
    sans requête inutile). Aucune date n'existe dans ces formulaires ni dans les résultats : la période demandée
    n'est pas envoyée ; seuls les volumes dont le titre porte une période (« avant 1900 », « 1901-1955 ») sont
    filtrés localement. Les résultats portent ``categorie``, ``contexte`` et la lecture de leur titre."""
    from ..fr_sources import communicability  # import tardif : fr_sources ne dépend pas des sources réseau
    etats: dict[str, dict] = {}
    requetes: dict[str, dict] = {}
    for categorie in TYPES_HYP[type_acte]:  # formulaires et bureau contrôlés avant toute recherche
        uuid = FORMULAIRES_HYP[categorie]
        f = _formulaire(http, HOST, uuid)
        if not f["commune"]:
            raise mnesys.FormulaireError(f"Formulaire des hypothèques AD59 ({categorie}) non reconnu (bureau "
                                         "absent) : consulter la recherche manuellement.")
        etat = etats[categorie] = {"formulaire": uuid, "interroge": False, "bureau": None, "autres_bureaux": [],
                                   "total": None, "page_suivante": None, "bureaux": f["communes"]}
        exactes = [o for o in f["communes"] if mnesys.cle(o) == mnesys.cle(bureau)]
        try:
            valeur = exactes[0] if len(exactes) == 1 else mnesys.choisir_commune(f["communes"], bureau)
        except ValueError as exc:
            etat["message"] = str(exc).replace("Commune «", "Bureau des hypothèques «", 1).replace(
                "comme commune.", "comme commune (c'est le bureau des hypothèques, pas la commune du bien).")
            continue
        nom = mnesys.cle(valeur.split(" (")[0])
        etat["bureau"] = valeur
        # autres valeurs du vocabulaire pour le même nom : à interroger à part (aucune au relevé)
        etat["autres_bureaux"] = [o for o in f["communes"] if o != valeur and mnesys.cle(o.split(" (")[0]) == nom]
        # tri du formulaire : par cote, soit l'ordre des volumes (et des plages alphabétiques)
        requetes[categorie] = {"formUuid": uuid, "sort": "referencecode_asc", "mode": "list", "facet_media": "image",
                               f["commune"] + "[]": valeur, "page": page}
    if not requetes:
        connus = sorted({b for e in etats.values() for b in e["bureaux"]})
        raise ValueError(f"{next(iter(etats.values()))['message']} Bureaux des hypothèques proposés par le "
                         f"formulaire : {', '.join(connus)}. Un libellé de titre (« Lille 2 (1901-1955) », « Lille "
                         "(avant 1900) ») n'est pas une valeur de bureau : interroger le bureau et lire bureau_titre.")
    resultats: list[dict] = []
    total, suivante, cached, lues, refus, hors = 0, None, True, 0, None, 0
    for categorie, requete in requetes.items():
        etat = etats[categorie]
        html, cache = http.get(URL, params=requete, parse="text", ttl=DAY, source="archives")
        etat["interroge"] = True
        cached = cached and cache
        try:
            lus, etat["total"], etat["page_suivante"] = _lire(html, page, contexte=True)
        except FormatRegistresError as exc:
            if page == 1:
                raise
            # Page absente d'une catégorie (redirection vers la première observée sur d'autres formulaires, #221 et
            # #377 ; non observée ici) : rien n'est conclu pour elle, les autres restent lisibles.
            refus = exc
            etat["message"] = f"Aucune page {page} lue pour cette catégorie : {exc}"
            continue
        lues += 1
        if not lus:
            etat["message"] = ("Aucun résultat pour ce bureau ; cela ne prouve ni l'absence du registre ni celle "
                               "d'une formalité.")
        total += etat["total"]
        if etat["page_suivante"]:
            suivante = etat["page_suivante"]
        for r in lus:
            r.update(categorie=categorie, **titre_hypotheques(r["titre"]))
            p = r["periode_titre"]
            r["couvre_periode"] = None if p is None else p[1] >= periode[0] and (p[0] is None or p[0] <= periode[1])
            if r["couvre_periode"] is False:
                hors += 1
                continue
            if p:  # règle du type « hypotheques » appliquée à la dernière année du titre
                r["communicable_a_partir_de"] = communicability(
                    "hypotheques", date_document=str(p[1]), today=aujourdhui).get("communicable_a_partir_de")
            resultats.append(r)
    if refus and not lues:
        raise refus
    regle = communicability("hypotheques", today=aujourdhui)
    non_echus = [r for r in resultats if (r.get("communicable_a_partir_de") or 0) > aujourdhui.year]
    bureaux = {e["bureau"] for e in etats.values() if e["bureau"]}
    extra = {"commune_service": next(iter(bureaux)) if len(bureaux) == 1 else None,
             "registres_hors_periode": hors,
             "hypotheques": {"releve_le": RELEVE_HYP, "reference": PAGE_HYP, "periode_annoncee": PERIODE_HYP,
                             "methode": METHODE_HYP, "lecture": LECTURE_HYP,
                             "bureaux_titres": sorted({r["bureau_titre"] for r in resultats if r["bureau_titre"]}),
                             "communicabilite": {"type_document": "hypotheques", "regle": regle["regle"],
                                                 "delai_annees": regle["delai_annees"], "source": PAGE_HYP,
                                                 "releve_le": RELEVE_HYP, "non_verifie": NON_VERIFIE_HYP,
                                                 "volumes_non_communicables": len(non_echus)},
                             **etats}}
    if non_echus:
        extra["avertissement_communicabilite"] = (
            f"{len(non_echus)} volume(s) dont la période affichée dépasse la période communicable selon la règle "
            "« hypotheques » de communicabilite (communicable_a_partir_de) : ne pas les tenir pour librement "
            "communicables ; vérifier auprès du service avant toute consultation ou diffusion.")
    return resultats, total, suivante, cached, extra


def _cadastre_ad59(http, commune: str, periode: list[int], page: int,
                   aujourdhui: date) -> tuple[list[dict], int, int | None, bool, dict]:
    """Plans du cadastre des AD59 (#379) : cadastre dit du Consulat (P 30) et cadastre dit napoléonien (P 31), un
    formulaire chacun, dont le seul champ est la commune (obligatoire), avec un vocabulaire propre.

    Règle : les deux formulaires sont lus, puis interrogés (une page chacun) quand leur vocabulaire connaît la
    commune ; une commune inconnue des deux est une erreur avant toute recherche. Aucune date n'est envoyée : la
    période n'écarte que les plans dont le service affiche une date qui ne la recoupe pas. Les résultats portent
    ``categorie``, ``contexte`` et ``annee_titre`` ; les noms liés viennent du classeur 3 E local (aucun réseau)."""
    from ..fr_sources import communicability  # import tardif : fr_sources ne dépend pas des sources réseau
    etats: dict[str, dict] = {}
    requetes: dict[str, dict] = {}
    for categorie, uuid in FORMULAIRES_CAD.items():  # formulaires et commune contrôlés avant toute recherche
        f = _formulaire(http, HOST, uuid)
        if not f["commune"]:
            raise mnesys.FormulaireError(f"Formulaire du cadastre AD59 ({categorie}) non reconnu (commune "
                                         "absente) : consulter la recherche manuellement.")
        etat = etats[categorie] = {"formulaire": uuid, "interroge": False, "commune": None, "total": None,
                                   "page_suivante": None, "nb_communes": len(f["communes"])}
        exactes = [o for o in f["communes"] if mnesys.cle(o) == mnesys.cle(commune)]  # « MARCHIENNES Ville »
        try:
            etat["commune"] = exactes[0] if len(exactes) == 1 else mnesys.choisir_commune(f["communes"], commune)
        except ValueError as exc:
            etat["message"] = str(exc).replace("du service", "de ce formulaire", 1)
        try:
            lies = [n for n in couverture_3e.noms_lies(commune, f["communes"]) if n["valeur"] != etat["commune"]]
        except (OSError, ValueError, KeyError):
            lies = []  # référentiel absent ou illisible : pas d'aide, la recherche reste possible
        if lies:
            etat["noms_lies"] = lies
            if not etat["commune"]:
                essais = [("l'" if n["lien"][0] in "aeiou" else "le ") + f"{n['lien']} {n['valeur']} (« {n['d_apres']} »)"
                          for n in lies]
                etat["message"] += (" D'après le classeur 3 E (référentiel local), essayer sous "
                                    + " ; sous ".join(essais) + ".")
        if etat["commune"]:
            # tri par cote : ordre des lots d'une commune (le tri par défaut du formulaire est la pertinence)
            requetes[categorie] = {"formUuid": uuid, "sort": "referencecode_asc", "mode": "list",
                                   "facet_media": "image", f["commune"] + "[]": etat["commune"], "page": page}
    if not requetes:
        raise ValueError("Aucun des deux formulaires du cadastre AD59 ne connaît cette commune. "
                         + " ".join(f"{c} : {e['message']}" for c, e in etats.items()) + " " + PISTE_LIEU_CAD)
    resultats: list[dict] = []
    total, suivante, cached, lues, refus, hors = 0, None, True, 0, None, []
    for categorie, requete in requetes.items():
        etat = etats[categorie]
        html, cache = http.get(URL, params=requete, parse="text", ttl=DAY, source="archives")
        etat["interroge"] = True
        cached = cached and cache
        try:
            lus, etat["total"], etat["page_suivante"] = _lire(html, page, contexte=True)
        except FormatRegistresError as exc:
            if page == 1:
                raise
            # Page absente d'une catégorie (redirection vers la première, observée sur ce formulaire le 27 novembre
            # 2026) : rien n'est conclu pour elle, l'autre reste lisible.
            refus = exc
            etat["message"] = f"Aucune page {page} lue pour cette catégorie : {exc}"
            continue
        lues += 1
        if not lus:
            etat["message"] = "Aucun plan renvoyé pour cette commune ; cela ne prouve pas qu'aucun plan n'existe."
        total += etat["total"]
        if etat["page_suivante"]:
            suivante = etat["page_suivante"]
        for r in lus:
            m = re.fullmatch(r".*\s-\s(\d{4})(?:\s*\(.*\))?\s*", r["titre"])
            r.update(categorie=categorie, annee_titre=int(m[1]) if m else None,
                     couvre_periode=_couvre(r["bornes"], periode))
            if r["couvre_periode"] is False:
                hors.append(r["bornes"])
                continue
            if r["nb_vues"] and 2 <= r["nb_vues"] <= 9:
                r["planche_contact"] = f'archives_planche(source="{r["ark"]}", de=1, a={r["nb_vues"]})'
            resultats.append(r)
    if refus and not lues:
        raise refus
    regle = communicability("cadastre", today=aujourdhui)
    communes = {e["commune"] for e in etats.values() if e["commune"]}
    cadastre = {"releve_le": RELEVE_CAD, "reference": PAGE_CAD, "periode_annoncee": PERIODE_CAD,
                "lecture": LECTURE_CAD, "non_couvert": NON_COUVERT_CAD, "piste_lieu": PISTE_LIEU_CAD,
                "communicabilite": {"type_document": "cadastre", "regle": regle["regle"],
                                    "delai_annees": regle["delai_annees"], "source": PAGE_CAD,
                                    "releve_le": RELEVE_CAD, "non_verifie": NON_VERIFIE_CAD},
                **etats}
    if hors:  # dates affichées des plans écartés : de quoi relancer sur la bonne période
        cadastre["dates_hors_periode"] = sorted({b[0] if b[0] == b[1] else f"{b[0]}-{b[1]}" for b in hors}, key=str)
    return resultats, total, suivante, cached, {
        "commune_service": next(iter(communes)) if len(communes) == 1 else None,
        "registres_hors_periode": len(hors), "cadastre": cadastre}


def _communicabilite_fd(resultats: list[dict], periode: list[int], aujourdhui: date) -> tuple[list[dict], dict, str]:
    """Fiches décès (#377) : délai affirmé par le service, jamais « librement communicable ». Rend les résultats
    dont le délai est échu (ou dont la date est inconnue, signalée), le constat et l'avertissement."""
    from ..fr_sources import communicability  # import tardif : fr_sources ne dépend pas des sources réseau
    gardes, ecartes = [], 0
    for r in resultats:
        r["communicable_a_partir_de"] = r["bornes"][1] + DELAI_FD + 1 if r["bornes"] else None
        if r["communicable_a_partir_de"] and aujourdhui.year < r["communicable_a_partir_de"]:
            ecartes += 1
        else:
            gardes.append(r)
    regle = communicability("vie_privee", date_document=str(periode[1]), today=aujourdhui)
    constat = {"type_document": "vie_privee", "delai_annees": regle["delai_annees"],
               "periode_demandee_communicable_a_partir_de": regle["communicable_a_partir_de"],
               "periode_demandee_communicable": regle["communicable"],
               "source": PAGE_ENREGISTREMENT, "releve_le": RELEVE_ENREGISTREMENT,
               "selon_le_service": ("Le service dit ne mettre en ligne que les fiches décès de plus de 50 ans, pour "
                                    f"respecter les délais du code du patrimoine ; en ligne : {PERIODE_FD} au relevé."),
               "non_verifie": NON_VERIFIE_FD, "fiches_ecartees": ecartes}
    avertissement = (
        "Fiches décès : ne pas les tenir pour librement communicables. Le service affirme un délai de 50 ans et ne "
        f"publie que {PERIODE_FD} (relevé du {RELEVE_ENREGISTREMENT}) ; ce régime n'a pas été vérifié par le plugin. "
        "Une fiche peut nommer des héritiers encore vivants (contenu non lu) : ne rien publier ni transmettre sur "
        "eux ; en cas de doute, interroger le service." + (
            f" {ecartes} résultat(s) de moins de 50 ans écarté(s) de la réponse." if ecartes else ""))
    return gardes, constat, avertissement


def _requete_mnesys(http, svc: dict, commune: str, periode: list[int], type_acte: str,
                    page: int) -> tuple[dict, str | None, bool]:
    """Requête GET d'un service Mnesys d'après son formulaire public (lu en ligne, mis en cache une semaine).
    RM : registres matricules (annee = classe, commune = bureau de recrutement facultatif) ; SUCC : tables des
    successions (commune = bureau de l'enregistrement) ; sinon formulaire d'état civil."""
    cfg = svc["recherche_registres"]["formulaires"]
    host = svc["site"].rstrip("/")
    dedie = type_acte == "TD" and cfg.get("tables_decennales")
    cle_form = mnesys.TYPES_FONDS.get(type_acte) or ("tables_decennales" if dedie else "etat_civil")
    if not cfg.get(cle_form):
        autres = ", ".join(sorted(k for k in ("TD", *mnesys.TYPES_FONDS)
                                  if cfg.get(mnesys.TYPES_FONDS.get(k, "tables_decennales"))))
        raise ValueError(f"Aucun formulaire « {cle_form} » relevé pour {svc['code']} : chercher dans l'inventaire "
                         "du service (archives_service, lien)" + (f" ; types disponibles : {autres}." if autres
                                                                     else "."))
    uuid = cfg[cle_form]
    f = _formulaire(http, host, uuid)
    # champ d'année déclaré au référentiel quand le formulaire ne le type pas (AD25 : classe en texte libre « 0-title »)
    if annee := svc["recherche_registres"].get("champs_annee", {}).get(cle_form):
        f["date"], f["debut"], f["fin"] = annee, None, None
    requete = {"formUuid": uuid, "sort": "date_asc", "mode": "list", "facet_media": "image"}
    valeur = None
    if commune and f["commune"]:
        valeur = mnesys.choisir_commune(f["communes"], commune)
        requete[f["commune"] + "[]"] = valeur
    elif type_acte != "RM":  # matricules : le bureau de recrutement est facultatif
        raise mnesys.FormulaireError("Formulaire sans liste de lieux : recherche par commune ou bureau impossible.")
    # Formulaire sans date, ou formulaire de tables dédié sans période (AD59) : commune seule, période filtrée
    # localement sur les bornes affichées (filtre_local). Un formulaire de tables dédié doté d'une période (AD25,
    # relevé du 18 novembre 2026) la reçoit ; la typologie reste propre au formulaire d'état civil.
    filtre_local = bool(dedie) and not (f["debut"] and f["fin"]) or not (f["date"] or f["debut"] and f["fin"])
    if dedie and not filtre_local:
        requete[f["debut"]], requete[f["fin"]] = str(periode[0]), str(periode[1])
    if not dedie:
        # L'intervalle d'abord, même pour une année : la date exacte ne trouve pas toujours un volume pluriannuel
        # (AD91, tables des successions 1859-1865 absentes pour « 1-date=1860 », relevé du 18 novembre 2026).
        # Matricules : la classe est une année exacte.
        if filtre_local:
            pass
        elif periode[0] == periode[1] and f["date"] and (type_acte == "RM" or not (f["debut"] and f["fin"])):
            requete[f["date"]] = str(periode[0])
        elif f["debut"] and f["fin"]:
            requete[f["debut"]], requete[f["fin"]] = str(periode[0]), str(periode[1])
        else:
            raise ValueError("Ce formulaire ne permet pas de recherche par intervalle : préciser une seule année.")
        if type_acte in (*TYPES, "TD", *mnesys.TYPES_FONDS):
            champ, options = mnesys.options_typologie(f, type_acte)
            if champ:
                requete[champ + "[]"] = options
            elif type_acte not in mnesys.TYPES_FONDS:  # formulaire dédié : le filtre est facultatif
                raise ValueError(f"Le formulaire du service ne propose pas de filtre pour le type {type_acte} : "
                                 "relancer sans type_acte (NMD) et lire les titres des registres.")
    requete["page"] = page
    return requete, valeur, filtre_local


def rechercher(ctx: SourceContext, service: str, commune: str, annee: int, type_acte: str = "", page: int = 1,
               personne: str = "", annee_fin: int = 0) -> dict:
    """Registres candidats d'une commune pour une année ou un intervalle [annee, annee_fin] ; type_acte=TD pour
    les tables décennales, REC pour les recensements de population des AD59 (#375), tous deux filtrés localement
    sur la période ; RM pour les registres matricules (annee = classe, commune = bureau de recrutement facultatif ;
    AD59 : tables et fiches, #376) ; SUCC pour les tables des successions et absences et, pour AD59 seulement, FD
    pour les fiches décès de l'enregistrement (commune = bureau de l'enregistrement, #377) ; AD59 seulement : HYP
    pour les hypothèques, sous-série 4 Q (commune = bureau des hypothèques ; indicateurs, tables et répertoires ;
    HYPI, HYPT, HYPR pour une seule catégorie, #378) ; CAD pour les plans du cadastre (commune seule ; cadastre du
    Consulat et cadastre napoléonien, #379). Aucun nom de personne envoyé."""
    params = {"service": service, "commune": commune, "annee": annee, "type_acte": type_acte, "page": page,
              "annee_fin": annee_fin}
    svc = None
    extra = {}
    filtre_local = False
    contexte = False
    try:
        service = (service or "").strip().upper()
        type_acte = (type_acte or "").strip().upper()
        if service != "AD59":
            svc = archives.by_code(service)
            if not svc or not svc.get("recherche_registres"):
                raise ValueError(f"Recherche de registres non disponible pour {service or '?'} ; services pris en "
                                 f"charge : {', '.join(services_registres())}.")
            commune = " ".join((commune or "").split())
        else:
            commune = " ".join(strip_accents(commune or "").upper().split())
        params.update(service=service, commune=commune, type_acte=type_acte)
        if len(commune) > 200 or not commune and type_acte != "RM":
            raise ValueError("commune : nom obligatoire (facultatif pour RM), de 1 à 200 caractères.")
        if type(annee) is not int or not 1 <= annee <= 9999:
            raise ValueError("annee : année précise de 1 à 9999 ; pour un intervalle, préciser aussi annee_fin.")
        if type(annee_fin) is not int or (annee_fin and not annee <= annee_fin <= 9999):
            raise ValueError("annee_fin : 0 (année seule) ou fin d'intervalle, de annee à 9999.")
        if type(page) is not int or page < 1:
            raise ValueError("page : entier à partir de 1.")
        if svc and type_acte in ("REC", "FD", "CAD", *TYPES_HYP):
            quoi = {"REC": "REC (recensements de population)", "FD": "FD (fiches décès de l'enregistrement)",
                    "CAD": "CAD (plans du cadastre)"}.get(type_acte, f"{type_acte} (hypothèques, sous-série 4 Q)")
            raise ValueError(f"type_acte {quoi} : disponible pour AD59 seulement ; le "
                             f"formulaire dédié de {service} n'est pas relevé : chercher dans l'inventaire du "
                             "service (archives_service, lien).")
        if type_acte not in {"", "NMD", "TD", *TYPES} | (set(mnesys.TYPES_FONDS) if svc
                                                         else {"REC", "RM", "CAD", *FORMULAIRES_ENREGISTREMENT,
                                                               *TYPES_HYP}):
            raise ValueError("type_acte : N, M, D, NMD, TD (tables décennales) ou vide ; REC (recensements de "
                             "population) pour AD59 ; RM (registres matricules) pour AD59 et les services Mnesys "
                             "qui le déclarent ; SUCC (tables des successions et absences) pour AD59 et les "
                             "services Mnesys qui le déclarent ; FD (fiches décès de l'enregistrement) pour AD59 ; HYP "
                             "(hypothèques, sous-série 4 Q : indicateurs, tables et répertoires ; HYPI, HYPT ou HYPR "
                             "pour une seule catégorie) pour AD59 ; CAD (plans du cadastre du Consulat et "
                             "napoléonien) pour AD59.")
        periode = [annee, annee_fin or annee]
        # Copie du wrapper seulement : cache, client, politique et verrou de débit restent partagés.
        # La limite locale n'altère pas les reprises des autres sources ou appels simultanés.
        http = copy(ctx.http)
        http.max_retries = 1
        matricules_ad59 = svc is None and type_acte == "RM"
        hypotheques_ad59 = svc is None and type_acte in TYPES_HYP
        cadastre_ad59 = svc is None and type_acte == "CAD"
        if matricules_ad59:
            resultats, total, suivante, cached, extra = _matricules_ad59(http, commune, periode, page)
        elif cadastre_ad59:
            resultats, total, suivante, cached, extra = _cadastre_ad59(http, commune, periode, page, date.today())
        elif hypotheques_ad59:
            resultats, total, suivante, cached, extra = _hypotheques_ad59(http, type_acte, commune, periode, page,
                                                                          date.today())
        elif svc:
            requete, extra["commune_service"], filtre_local = _requete_mnesys(http, svc, commune, periode,
                                                                              type_acte, page)
            host, naan = svc["site"].rstrip("/"), svc.get("ark_naan", "")
            url = host + "/search/results"
        elif type_acte in FORMULAIRES_ENREGISTREMENT:
            requete, extra, filtre_local = _enregistrement_ad59(http, type_acte, commune, periode, page)
            host, naan, url, contexte = HOST, "33518", URL, True
        else:
            base = {"sort": "date_asc", "mode": "list", "facet_media": "image",
                    "0-controlledAccessGeographicName[]": commune}
            if type_acte in ("TD", "REC"):
                # Les formulaires TD et REC observés n'ont que la commune : aucune date envoyée, la période est
                # filtrée localement.
                requete = {"formUuid": FORMULAIRE_REC if type_acte == "REC" else FORMULAIRE_TD, **base, "page": page}
            elif periode[0] == periode[1]:
                requete = {"formUuid": FORMULAIRE, **base, "2-date": str(annee), "page": page}
            else:
                requete = {"formUuid": FORMULAIRE, **base, "3-date_begin": str(periode[0]),
                           "3-date_end": str(periode[1]), "page": page}
            if type_acte in TYPES:
                requete["facet_typology"] = TYPES[type_acte]
            host, naan, url = HOST, "33518", URL
            filtre_local = type_acte in ("TD", "REC")
        if not matricules_ad59 and not hypotheques_ad59 and not cadastre_ad59:
            html, cached = http.get(url, params=requete, parse="text", ttl=DAY, source="archives")
            resultats, total, suivante = _lire(html, page, host, naan, contexte)
    except (SourceError, ValueError) as exc:
        return error_envelope(ctx, "archives", "registres", params, exc, personne=personne or None)
    hors = "tables_hors_periode" if type_acte == "TD" else "registres_hors_periode"
    if filtre_local:  # aucune date envoyée : période filtrée sur les bornes affichées
        for r in resultats:
            r["couvre_periode"] = _couvre(r["bornes"], periode)
        couvrantes = [r for r in resultats if r["couvre_periode"] is not False]
        extra[hors] = len(resultats) - len(couvrantes)
        resultats = couvrantes
    enregistrement = svc is None and type_acte in FORMULAIRES_ENREGISTREMENT
    if enregistrement and type_acte == "FD":
        resultats, extra["fiches_deces"]["communicabilite"], extra["avertissement_communicabilite"] = (
            _communicabilite_fd(resultats, periode, date.today()))
    out = envelope(ctx, "archives", "registres", params, resultats, total, cached, personne=personne or None,
                   service=service, page=page, page_suivante=suivante, fin=suivante is None, periode=periode,
                   avertissement="Un registre candidat ne prouve pas la présence d'un acte : consulter ses vues.",
                   **extra)
    if not resultats and hypotheques_ad59:
        out["recherche_negative"] = (
            (f"Aucun volume de cette page ne couvre {periode[0]}-{periode[1]} d'après la période portée par son titre "
             f"({extra[hors]} hors période) ; voir page_suivante s'il y en a une." if extra.get(hors)
             else "Aucun volume des hypothèques renvoyé pour ce bureau et cette page.")
            + " Cela ne prouve ni l'absence du registre ni celle d'une formalité. Le service annonce : "
            f"{PERIODE_HYP} (relevé du {RELEVE_HYP}). Vérifier le bureau des hypothèques (celui de l'arrondissement "
            "du bien) et l'état de chaque catégorie (hypotheques).")
    elif not resultats and cadastre_ad59:
        dates = extra["cadastre"].get("dates_hors_periode")
        out["recherche_negative"] = (
            (f"Aucun plan de cette page ne recoupe {periode[0]}-{periode[1]} d'après la date affichée par le service "
             f"({extra[hors]} écarté(s), datés {', '.join(map(str, dates))}) : un plan décrit le territoire pour les "
             "décennies qui suivent sa levée, relancer avec une de ces années ou un intervalle (annee_fin)." if dates
             else "Aucun plan du cadastre renvoyé pour cette commune et cette page.")
            + " Cela ne prouve pas qu'aucun plan n'existe. Le service annonce : "
            f"{PERIODE_CAD} (relevé du {RELEVE_CAD}). Vérifier l'état de chaque formulaire (cadastre) et le nom de "
            "la commune à l'époque du plan (noms_lies, piste_lieu).")
    elif not resultats and extra.get(hors):
        quoi = {"TD": "Aucune table décennale", "REC": "Aucun recensement en ligne",
                "FD": "Aucun volume de fiches décès"}.get(type_acte, "Aucun registre")
        if enregistrement:
            suite = (f"Cela ne prouve ni l'absence d'un décès ni celle d'une succession ; le service annonce "
                     f"{PERIODE_FD} en ligne.")
        elif type_acte == "REC":
            suite = ("Cela ne prouve pas que le recensement n'existe pas ni l'absence de la personne : voir "
                     "couverture_recensements.")
        else:
            suite = "Cela ne prouve pas l'absence de l'acte" + (
                " : consulter les registres de la période (archives_registres sans TD)." if type_acte == "TD" else ".")
        out["recherche_negative"] = (
            f"{quoi} de cette page ne couvre {periode[0]}-{periode[1]} "
            f"({extra[hors]} hors période) ; voir page_suivante s'il y en a une. {suite}")
    elif not resultats and matricules_ad59:
        out["recherche_negative"] = (
            "Aucune table ni aucun registre matricule renvoyé pour cette classe et cette page ; cela ne prouve ni "
            "l'absence du registre ni celle de la personne. Vérifier la classe (année de naissance + 20), le "
            "bureau de recrutement (facultatif) et l'état de chaque formulaire (matricules).")
    elif not resultats and enregistrement:
        annonce = PERIODE_SUCC if type_acte == "SUCC" else PERIODE_FD
        rien = ("Aucune table des successions et absences renvoyée" if type_acte == "SUCC"
                else "Aucun volume de fiches décès renvoyé")
        out["recherche_negative"] = (
            f"{rien} pour ce bureau, cette période et cette page ; cela ne prouve ni l'absence d'un décès ni celle "
            f"d'une succession. Le service annonce en ligne : {annonce} (relevé du {RELEVE_ENREGISTREMENT}). "
            "Vérifier le bureau (celui de l'enregistrement, dont le ressort dépasse la commune ; voir "
            "autres_bureaux)" + (" et élargir la période (annee_fin)." if type_acte == "SUCC" else "."))
    elif not resultats:
        out["recherche_negative"] = ("Aucun registre renvoyé pour cette recherche et cette page ; cela ne prouve pas "
                                      "l'absence générale de fonds numérisés. Vérifier les variantes et le service.")
    if svc is None and type_acte == "REC":
        # État de la collection des recensements (#375) : ajout seulement, quand la recherche est vide ou qu'un
        # recensement de la période n'est qu'en salle de lecture.
        try:
            constat = couverture_recensements.pour_recherche(commune, periode, resultats)
        except (OSError, ValueError, KeyError):
            constat = None  # référentiel absent ou illisible : la recherche en ligne reste rendue telle quelle
        if constat:
            out["couverture_recensements"] = constat
    elif svc is None and type_acte not in ("TD", "RM", "CAD", *FORMULAIRES_ENREGISTREMENT, *TYPES_HYP):
        # Classeur 3 E (#374) : ajout seulement, quand la recherche est vide ou qu'un volume n'est pas en ligne.
        try:
            constat = couverture_3e.pour_recherche(commune, periode, type_acte, resultats)
        except (OSError, ValueError, KeyError):
            constat = None  # référentiel absent ou illisible : la recherche en ligne reste rendue telle quelle
        if constat:
            out["classeur_3e"] = constat
    return out
