"""Recherche de registres sur le HTML serveur Mnesys Expo : AD59 qualifié (relevés des 16 et 18 novembre 2026)
et services déclarant ``recherche_registres`` dans le référentiel (formulaire lu en ligne, sources/mnesys.py, #128).

Une page par appel, sans exploration de JavaScript, de notice, de métadonnées ni d'image.
Les ARK de registre viennent du lien de notice, jamais du lien de miniature (ARK de vue).
"""

from __future__ import annotations

import re
from copy import copy
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .. import archives, ark
from ..normalize.names import strip_accents
from . import mnesys
from .base import DAY, SourceContext, SourceError, envelope, error_envelope

HOST = "https://archivesdepartementales.lenord.fr"
URL = HOST + "/search/results"
FORMULAIRE = "dc4e871d-0b62-41fb-9921-5ded573781b8"
FORMULAIRE_TD = "25905104-0354-4e23-aea0-e3b68cf1f881"  # tables décennales (relevé du 18 novembre 2026)
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


def _registre(bloc: _Noeud, host: str = HOST, naan: str = "33518") -> dict:
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
    return {"titre": titre, "cote": cote, "ark": identifiant.base,
            "url": url, "bornes": bornes, "nb_vues": nb_vues}


def _lire(html: str, page: int, host: str = HOST, naan: str = "33518") -> tuple[list[dict], int, int | None]:
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
    return [_registre(bloc, host, naan) for bloc in blocs], total, page + 1 if page < maximum else None


def _couvre(bornes: list[int] | None, periode: list[int]) -> bool | None:
    """Recouvrement des bornes affichées et de la période demandée ; None si les bornes sont inconnues."""
    return None if bornes is None else bornes[0] <= periode[1] and periode[0] <= bornes[1]


def services_registres() -> list[str]:
    """Services dont la recherche de registres par commune et année est disponible."""
    return ["AD59", *sorted(s["code"] for s in archives.services() if s.get("recherche_registres"))]


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
    form, _ = http.get(f"{host}/search/form/{uuid}", parse="text", ttl=7 * DAY, source="archives")
    if len(form) > MAX_HTML:
        raise FormatRegistresError("Formulaire de recherche trop volumineux : consultation manuelle nécessaire.")
    parser = _HTML()
    parser.feed(form)
    f = mnesys.lire_formulaire(parser.racine.trouver())
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
    les tables décennales (filtrées localement sur la période). Aucun nom de personne envoyé."""
    params = {"service": service, "commune": commune, "annee": annee, "type_acte": type_acte, "page": page,
              "annee_fin": annee_fin}
    svc = None
    extra = {}
    filtre_local = False
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
        if len(commune) > 200 or not commune and not (svc and type_acte == "RM"):
            raise ValueError("commune : nom obligatoire (facultatif pour RM), de 1 à 200 caractères.")
        if type(annee) is not int or not 1 <= annee <= 9999:
            raise ValueError("annee : année précise de 1 à 9999 ; pour un intervalle, préciser aussi annee_fin.")
        if type(annee_fin) is not int or (annee_fin and not annee <= annee_fin <= 9999):
            raise ValueError("annee_fin : 0 (année seule) ou fin d'intervalle, de annee à 9999.")
        if type(page) is not int or page < 1:
            raise ValueError("page : entier à partir de 1.")
        if type_acte not in {"", "NMD", "TD", *TYPES} | (set(mnesys.TYPES_FONDS) if svc else set()):
            raise ValueError("type_acte : N, M, D, NMD, TD (tables décennales) ou vide ; RM (registres matricules) "
                             "et SUCC (tables des successions) pour les services Mnesys qui les déclarent.")
        periode = [annee, annee_fin or annee]
        # Copie du wrapper seulement : cache, client, politique et verrou de débit restent partagés.
        # La limite locale n'altère pas les reprises des autres sources ou appels simultanés.
        http = copy(ctx.http)
        http.max_retries = 1
        if svc:
            requete, extra["commune_service"], filtre_local = _requete_mnesys(http, svc, commune, periode,
                                                                              type_acte, page)
            host, naan = svc["site"].rstrip("/"), svc.get("ark_naan", "")
            url = host + "/search/results"
        else:
            base = {"sort": "date_asc", "mode": "list", "facet_media": "image",
                    "0-controlledAccessGeographicName[]": commune}
            if type_acte == "TD":
                # Le formulaire TD observé n'a que la commune : aucune date envoyée, la période est filtrée localement.
                requete = {"formUuid": FORMULAIRE_TD, **base, "page": page}
            elif periode[0] == periode[1]:
                requete = {"formUuid": FORMULAIRE, **base, "2-date": str(annee), "page": page}
            else:
                requete = {"formUuid": FORMULAIRE, **base, "3-date_begin": str(periode[0]),
                           "3-date_end": str(periode[1]), "page": page}
            if type_acte in TYPES:
                requete["facet_typology"] = TYPES[type_acte]
            host, naan, url = HOST, "33518", URL
            filtre_local = type_acte == "TD"
        html, cached = http.get(url, params=requete, parse="text", ttl=DAY, source="archives")
        resultats, total, suivante = _lire(html, page, host, naan)
    except (SourceError, ValueError) as exc:
        return error_envelope(ctx, "archives", "registres", params, exc, personne=personne or None)
    hors = "tables_hors_periode" if type_acte == "TD" else "registres_hors_periode"
    if filtre_local:  # aucune date envoyée : période filtrée sur les bornes affichées
        for r in resultats:
            r["couvre_periode"] = _couvre(r["bornes"], periode)
        couvrantes = [r for r in resultats if r["couvre_periode"] is not False]
        extra[hors] = len(resultats) - len(couvrantes)
        resultats = couvrantes
    out = envelope(ctx, "archives", "registres", params, resultats, total, cached, personne=personne or None,
                   service=service, page=page, page_suivante=suivante, fin=suivante is None, periode=periode,
                   avertissement="Un registre candidat ne prouve pas la présence d'un acte : consulter ses vues.",
                   **extra)
    if not resultats and extra.get(hors):
        quoi = "Aucune table décennale" if type_acte == "TD" else "Aucun registre"
        out["recherche_negative"] = (
            f"{quoi} de cette page ne couvre {periode[0]}-{periode[1]} "
            f"({extra[hors]} hors période) ; voir page_suivante s'il y en a une. Cela ne prouve "
            "pas l'absence de l'acte" + (" : consulter les registres de la période (archives_registres sans TD)."
                                          if type_acte == "TD" else "."))
    elif not resultats:
        out["recherche_negative"] = ("Aucun registre renvoyé pour cette recherche et cette page ; cela ne prouve pas "
                                      "l'absence générale de fonds numérisés. Vérifier les variantes et le service.")
    return out
