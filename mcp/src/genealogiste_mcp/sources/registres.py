"""Recherche de registres sur le HTML serveur AD59 qualifié (relevés des 16 et 18 novembre 2026).

Une page par appel, sans exploration de JavaScript, de notice, de métadonnées ni d'image.
Les ARK de registre viennent du lien de notice, jamais du lien de miniature (ARK de vue).
"""

from __future__ import annotations

import re
from copy import copy
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .. import ark
from ..normalize.names import strip_accents
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
            raise FormatRegistresError("HTML de recherche AD59 trop profond : format refusé.")
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
        raise FormatRegistresError(f"Format de recherche AD59 non reconnu ({champ}) ; consulter la recherche manuellement.")
    return noeuds[0]


def _registre(bloc: _Noeud) -> dict:
    intitule = _unique(bloc.trouver(classe="intitup"), "intitulé")
    lien = _unique(intitule.trouver("a"), "lien de notice")
    titre = _unique(lien.trouver("h2"), "titre").texte()
    url = urljoin(HOST, lien.attrs.get("href", ""))
    parsed = urlsplit(url)
    identifiant = ark.find(url)
    if (not titre or parsed.scheme != "https" or parsed.hostname != urlsplit(HOST).hostname
            or parsed.port not in (None, 443) or parsed.username is not None or parsed.password is not None
            or not identifiant or identifiant.naan != "33518" or identifiant.qualificatif
            or not re.fullmatch(r"/ark:/33518/[^/]+/?", parsed.path)):
        raise FormatRegistresError("Lien de notice AD59 incohérent ou hors du service : registre refusé.")
    cote = _unique(bloc.trouver("p", classe="referenceCodes"), "cote").texte()
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


def _lire(html: str, page: int) -> tuple[list[dict], int, int | None]:
    if len(html) > MAX_HTML:
        raise FormatRegistresError("Réponse de recherche AD59 trop volumineuse : consultation manuelle nécessaire.")
    parser = _HTML()
    parser.feed(html)
    body = _unique(parser.racine.trouver("body"), "page")
    liste = _unique(body.trouver("section", identifiant="list-container"), "liste de résultats")
    blocs = liste.trouver("li", classe="element-list")
    negatifs = liste.trouver("div", classe="no-result")
    if (body.attrs.get("id") == "display-no-results" and not blocs and len(negatifs) == 1
            and negatifs[0].texte() == "Aucun résultat ne correspond à votre requête"):
        if page != 1:
            raise FormatRegistresError("Page AD59 hors bornes ou résultat négatif de pagination non qualifié.")
        return [], 0, None
    if body.attrs.get("id") != "display-results" or not blocs or negatifs:
        raise FormatRegistresError("Format de recherche AD59 non reconnu : aucun résultat négatif ne peut être déduit.")
    pagination = _unique(body.trouver("input", identifiant="current-page"), "pagination")
    try:
        courante, maximum = int(pagination.attrs["value"]), int(pagination.attrs["max"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FormatRegistresError("Pagination AD59 non reconnue.") from exc
    if pagination.attrs.get("name") != "page" or courante != page or not 1 <= courante <= maximum:
        raise FormatRegistresError("Page AD59 retournée incohérente ou hors bornes : consultation manuelle nécessaire.")
    compteur = _unique(body.trouver("span", classe="result"), "nombre de résultats").texte()
    m = re.fullmatch(r"([\d\s\u00a0\u202f]+)\s+résultats?", compteur)
    if not m:
        raise FormatRegistresError("Nombre de résultats AD59 non reconnu ou incohérent.")
    total = int("".join(m[1].split()))
    # Chaque autre page annoncée doit contenir au moins un résultat ; une page unique est exhaustive.
    if total < len(blocs) + maximum - 1 or (maximum == 1 and total != len(blocs)):
        raise FormatRegistresError("Pagination et nombre de résultats AD59 incohérents.")
    tailles = body.trouver("li", classe="select-results-per-page")
    if tailles:
        taille = _unique(_unique(tailles, "taille de page").trouver("p", classe="placeholder"), "taille de page")
        m = re.fullmatch(r"(\d+) résultats par page", taille.attrs.get("title", ""))
        if not m or int(m[1]) < 1:
            raise FormatRegistresError("Taille de page AD59 non reconnue.")
        taille_page = int(m[1])
        if (maximum != (total + taille_page - 1) // taille_page
                or len(blocs) != min(taille_page, total - (page - 1) * taille_page)):
            raise FormatRegistresError("Fenêtre de résultats AD59 incomplète ou pagination incohérente.")
    return [_registre(bloc) for bloc in blocs], total, page + 1 if page < maximum else None


def _couvre(bornes: list[int] | None, periode: list[int]) -> bool | None:
    """Recouvrement des bornes affichées et de la période demandée ; None si les bornes sont inconnues."""
    return None if bornes is None else bornes[0] <= periode[1] and periode[0] <= bornes[1]


def rechercher(ctx: SourceContext, service: str, commune: str, annee: int, type_acte: str = "", page: int = 1,
               personne: str = "", annee_fin: int = 0) -> dict:
    """Registres candidats d'une commune pour une année ou un intervalle [annee, annee_fin] ; type_acte=TD pour
    les tables décennales (formulaire dédié, filtrées localement sur la période). Aucun nom de personne envoyé."""
    params = {"service": service, "commune": commune, "annee": annee, "type_acte": type_acte, "page": page,
              "annee_fin": annee_fin}
    try:
        service = (service or "").strip().upper()
        commune = " ".join(strip_accents(commune or "").upper().split())
        type_acte = (type_acte or "").strip().upper()
        params.update(service=service, commune=commune, type_acte=type_acte)
        if service != "AD59":
            raise ValueError("Recherche de registres qualifiée uniquement pour AD59 ; préciser service='AD59'.")
        if not commune or len(commune) > 200:
            raise ValueError("commune : nom obligatoire, de 1 à 200 caractères.")
        if type(annee) is not int or not 1 <= annee <= 9999:
            raise ValueError("annee : année précise de 1 à 9999 ; pour un intervalle, préciser aussi annee_fin.")
        if type(annee_fin) is not int or (annee_fin and not annee <= annee_fin <= 9999):
            raise ValueError("annee_fin : 0 (année seule) ou fin d'intervalle, de annee à 9999.")
        if type(page) is not int or page < 1:
            raise ValueError("page : entier à partir de 1.")
        if type_acte not in {"", "NMD", "TD", *TYPES}:
            raise ValueError("type_acte : N, M, D, NMD, TD (tables décennales) ou vide.")
        periode = [annee, annee_fin or annee]
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
        # Copie du wrapper seulement : cache, client, politique et verrou de débit restent partagés.
        # La limite locale n'altère pas les reprises des autres sources ou appels simultanés.
        http = copy(ctx.http)
        http.max_retries = 1
        html, cached = http.get(URL, params=requete, parse="text", ttl=DAY, source="archives")
        resultats, total, suivante = _lire(html, page)
    except (SourceError, ValueError) as exc:
        return error_envelope(ctx, "archives", "registres", params, exc, personne=personne or None)
    extra = {}
    if type_acte == "TD":
        for r in resultats:
            r["couvre_periode"] = _couvre(r["bornes"], periode)
        couvrantes = [r for r in resultats if r["couvre_periode"] is not False]
        extra["tables_hors_periode"] = len(resultats) - len(couvrantes)
        resultats = couvrantes
    out = envelope(ctx, "archives", "registres", params, resultats, total, cached, personne=personne or None,
                   service=service, page=page, page_suivante=suivante, fin=suivante is None, periode=periode,
                   avertissement="Un registre candidat ne prouve pas la présence d'un acte : consulter ses vues.",
                   **extra)
    if not resultats and extra.get("tables_hors_periode"):
        out["recherche_negative"] = (
            f"Aucune table décennale de cette page ne couvre {periode[0]}-{periode[1]} "
            f"({extra['tables_hors_periode']} hors période) ; voir page_suivante s'il y en a une. Cela ne prouve "
            "pas l'absence de l'acte : consulter les registres de la période (archives_registres sans TD).")
    elif not resultats:
        out["recherche_negative"] = ("Aucun registre renvoyé pour cette recherche et cette page ; cela ne prouve pas "
                                      "l'absence générale de fonds numérisés. Vérifier les variantes et le service.")
    return out
