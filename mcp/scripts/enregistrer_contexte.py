"""Enregistrement des réponses réelles des services de contexte historique (#323), HORS CI, sur le réseau réel.

Rejoue la liste des requêtes décrites par les ``MANIFESTE.json`` de ``tests/fixtures/contexte/reponses/<service>/``
(lieux, périodes et sujets seulement : jamais un nom de personne, jamais une clé ni une adresse courriel), applique
à chaque réponse la réduction déclarée par le manifeste et compare la **forme** de la réponse réduite à celle de la
réponse enregistrée.

Modes :

- ``--verifier`` (par défaut) : compare la forme, n'écrit rien ;
- ``--ecrire`` : réécrit les réponses réduites et les manifestes (date, statut, type, taille d'origine, empreinte)
  des requêtes qui ont répondu 200 ; une réponse en échec ou bloquée n'est jamais écrite.

Règles : une seule tentative par requête, un intervalle entre deux requêtes vers le même hôte (``--intervalle``),
aucun contournement. Un 403, un 429, un défi anti-robot, un 5xx ou un silence est consigné (AVERT) et le service
est laissé de côté pour le reste de l'exécution ; une requête enregistrée avec un statut d'échec (service protégé
le jour de l'enregistrement) n'est pas rejouée. Les réductions de ``REDUCTIONS`` reproduisent celles des manifestes
(clés retirées, lignes filtrées, couches extraites) ; une réponse sans réducteur (extrait fait à la main) n'est pas
rejouée.

Clé d'API (#343) : un service de ``EN_TETES_CLE`` (Europeana) n'est rejoué qu'avec la clé personnelle de
l'utilisateur, lue par la configuration du plugin (``<données>/.env``) et envoyée en en-tête, jamais dans l'URL ni
dans un fichier. Sans clé : IGNORE. La réduction retire les champs où le service répète la clé ; une réponse
réduite qui la contiendrait encore n'est jamais écrite (DERIVE). Une entrée de manifeste dont le fichier n'existe
pas encore est enregistrée par ``--ecrire`` (premier enregistrement).

Usage : uv run python scripts/enregistrer_contexte.py [--verifier | --ecrire] [--service CODE]... [--intervalle S]

Verdicts : OK (forme conforme), DERIVE (champ de la réponse enregistrée absent de la réponse actuelle : le service
a changé, relire l'analyseur), AVERT (service muet, protégé ou limité), IGNORE (non rejoué). Code de sortie 1 s'il
y a une dérive, 0 sinon (un AVERT n'est pas un échec).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote, quote_plus, urlsplit

import httpx

from genealogiste_mcp.contexte.lieux import COUCHES
from genealogiste_mcp.contexte.presse import epurer_europeana

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "contexte"
REPONSES = FIXTURES / "reponses"
MANIFESTE = "MANIFESTE.json"
UA = "genealogiste-mcp (enregistrement des reponses de contexte ; hors CI, une requete par entree)"
INTERVALLE = 5.0  # (s) entre deux requêtes vers le même hôte
DELAI = 60.0  # (s) d'attente d'une réponse (le service SPARQL de Wikidata a mis 45 s le 2026-11-23)
CODES_COG = ("03029", "14005", "14074", "41016", "62132", "62133")  # communes du jeu de test (lieu_historique)
COUCHE_ETAT_MAJOR_1900 = "GEOGRAPHICALGRIDSYSTEMS.1900TYPEMAPS"
INTERDITS_URL = re.compile(r"(?i)(?:^|[?&;])(?:api[_-]?key|wskey|key|token|apikey|mailto|access[_-]?token)=|@")
STATUTS_CONSIGNES = (401, 403, 429)
# Service -> en-tête qui porte la clé d'API personnelle (jamais un paramètre d'URL : ``wskey`` est déprécié par
# Europeana et une URL se retrouve dans les manifestes). La valeur vient de la configuration du plugin.
EN_TETES_CLE = {"EUROPEANA": "X-Api-Key"}


# --------------------------------------------------------------------------------------------- noms de personnes

def noms_cas_temoins() -> list[str]:
    """Noms de famille des personnes fictives des cas témoins (fixtures *.ged) : ils ne doivent figurer dans aucune
    requête ni aucune réponse enregistrée."""
    noms: set[str] = set()
    for ged in FIXTURES.glob("*.ged"):
        noms |= {m.upper() for m in re.findall(r"^\d+ SURN (.+)$", ged.read_text(encoding="utf-8"), flags=re.M)}
    return sorted(noms)


def controle_url(url: str) -> str:
    """Motif de refus d'une URL d'enregistrement, ou chaîne vide : https, aucune clé ni adresse courriel, aucun nom de
    personne des cas témoins."""
    p = urlsplit(url or "")
    if p.scheme != "https" or not p.hostname:
        return "URL https attendue"
    if INTERDITS_URL.search(url):
        return "clé, jeton ou adresse courriel dans l'URL"
    haut = url.upper()
    if (nom := next((n for n in noms_cas_temoins() if n in haut), "")):
        return f"nom de personne des cas témoins dans l'URL ({nom})"
    return ""


# --------------------------------------------------------------------------------------------------- réductions

def _json(corps: bytes):
    return json.loads(corps.decode("utf-8"))


def _ecrire_json(d, nouvelle_ligne: bool = False) -> bytes:
    return (json.dumps(d, indent=1, ensure_ascii=False) + ("\n" if nouvelle_ligne else "")).encode("utf-8")


def _json_reindente(corps: bytes) -> bytes:
    return _ecrire_json(_json(corps), True)


def _sans_cles(objet, cles: set[str]) -> None:
    if isinstance(objet, dict):
        for k in [k for k in objet if k in cles]:
            del objet[k]
        for v in objet.values():
            _sans_cles(v, cles)
    elif isinstance(objet, list):
        for v in objet:
            _sans_cles(v, cles)


def _isidore(corps: bytes) -> bytes:
    d = _json(corps)
    reponses = ((d.get("response") or {}).get("replies") or {}).get("content", {})
    liste = reponses.get("reply", []) if isinstance(reponses, dict) else []
    for r in liste if isinstance(liste, list) else [liste]:
        i = r.get("isidore") if isinstance(r, dict) else None
        if isinstance(i, dict):
            for cle in ("abstract", "extraction", "enrichment"):
                i.pop(cle, None)
            if isinstance(i.get("source"), dict):
                for cle in ("description", "scope"):
                    i["source"].pop(cle, None)
    return _ecrire_json(d, True)


def _theses(corps: bytes) -> bytes:
    d = _json(corps)
    for t in d.get("theses", []):
        for cle in ("directeurs", "rapporteurs", "examinateurs", "president", "ecolesDoctorale",
                    "partenairesDeRecherche"):
            t.pop(cle, None)
    return _ecrire_json(d, True)


def _europeana(corps: bytes) -> bytes:
    """Search API d'Europeana : ``apikey`` (la clé, répétée par le service), ``requestNumber`` (compteur du compte)
    et tout champ ``link`` (URL de la notice JSON portant ``wskey=<clé>``) retirés, paramètres d'URL de ``guid``
    retirés (``utm_campaign`` reprend la clé). Même épuration que celle du plugin avant sa mise en cache."""
    return _ecrire_json(epurer_europeana(_json(corps)), True)


def contient_secret(corps: bytes, secret: str) -> bool:
    """Vrai si ``corps`` contient ``secret`` sous forme brute ou encodée pour une URL."""
    if not secret:
        return False
    return any(f.encode("utf-8") in corps for f in {secret, quote(secret, safe=""), quote_plus(secret, safe="")})


def _melodi_catalogue(corps: bytes) -> bytes:
    d = _json(corps)
    gardees = ("identifier", "title", "abstract", "description", "temporal", "spatialTemporal", "spatialResolution",
               "issued", "modified", "creator", "uri")
    return _ecrire_json({k: d[k] for k in gardees if k in d})


def _melodi_donnees(corps: bytes) -> bytes:
    d = _json(corps)
    d.pop("publisher", None)
    return _ecrire_json(d)


def _sudoc(corps: bytes) -> bytes:
    """Champs locaux UNIMARC 9XX (exemplaires des bibliothèques) retirés."""
    texte = corps.decode("utf-8")
    return re.sub(r'<datafield tag="9\d\d"[^>]*>.*?</datafield>\s*', "", texte, flags=re.S).encode("utf-8")


def _persee(corps: bytes) -> bytes:
    """Éléments dc:description (résumés) retirés."""
    return re.sub(r"<dc:description[^>]*>.*?</dc:description>", "", corps.decode("utf-8"), flags=re.S).encode("utf-8")


def _csv_filtre(corps: bytes, colonnes: tuple[str, ...]) -> bytes:
    lignes = corps.decode("utf-8-sig").splitlines(keepends=True)
    if not lignes:
        return b""
    entete = next(csv.reader([lignes[0]]))
    rangs = [entete.index(c) for c in colonnes]
    gardees = [lignes[0]]
    for ligne in lignes[1:]:
        champs = next(csv.reader([ligne]), [])
        if any(len(champs) > r and champs[r] in CODES_COG for r in rangs):
            gardees.append(ligne)
    return "".join(gardees).encode("utf-8")


WMTS = "http://www.opengis.net/wmts/1.0"
OWS = "http://www.opengis.net/ows/1.1"


def _capacites(corps: bytes) -> bytes:
    """ServiceIdentification, ServiceProvider, les couches retenues par lieu_historique (et l'état-major 1900) et les
    jeux de tuiles qu'elles utilisent."""
    ET.register_namespace("", WMTS)
    ET.register_namespace("ows", OWS)
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    racine = ET.fromstring(corps)
    contenu = racine.find(f"{{{WMTS}}}Contents")
    gardees = {*COUCHES, COUCHE_ETAT_MAJOR_1900}
    jeux: set[str] = set()
    if contenu is not None:
        for couche in contenu.findall(f"{{{WMTS}}}Layer"):
            if couche.findtext(f"{{{OWS}}}Identifier") not in gardees:
                contenu.remove(couche)
            else:
                jeux |= {x.findtext(f"{{{WMTS}}}TileMatrixSet") or ""
                         for x in couche.findall(f"{{{WMTS}}}TileMatrixSetLink")}
        for tms in contenu.findall(f"{{{WMTS}}}TileMatrixSet"):
            if tms.findtext(f"{{{OWS}}}Identifier") not in jeux:
                contenu.remove(tms)
    return ET.tostring(racine, encoding="utf-8", xml_declaration=True)


CSW = """<?xml version='1.0' encoding='utf-8'?>
<ns0:GetRecordByIdResponse xmlns:ns0="http://www.opengis.net/cat/csw/2.0.2" xmlns:ns1="http://standards.iso.org/iso/19115/-3/mdb/2.0" xmlns:ns2="http://standards.iso.org/iso/19115/-3/mcc/1.0" xmlns:ns3="http://standards.iso.org/iso/19115/-3/gco/1.0" xmlns:ns4="http://standards.iso.org/iso/19115/-3/mri/1.0" xmlns:ns5="http://standards.iso.org/iso/19115/-3/gex/1.0" xmlns:ns6="http://www.opengis.net/gml/3.2">
  <ns1:MD_Metadata uuid="{uuid}">
    <ns1:metadataIdentifier>
      <ns2:MD_Identifier>
        <ns2:code>
          <ns3:CharacterString>{uuid}</ns3:CharacterString>
        </ns2:code>
      </ns2:MD_Identifier>
    </ns1:metadataIdentifier>
    <ns1:identificationInfo>
      <ns4:MD_DataIdentification>
        <ns4:extent>
          <ns5:EX_Extent>
            <ns5:temporalElement>
              <ns5:EX_TemporalExtent>
                <ns5:extent>
                  <ns6:TimePeriod ns6:id="{ident}">
                    <ns6:beginPosition>{debut}</ns6:beginPosition>
                    <ns6:endPosition>{fin}</ns6:endPosition>
                  </ns6:TimePeriod>
                </ns5:extent>
              </ns5:EX_TemporalExtent>
            </ns5:temporalElement>
          </ns5:EX_Extent>
        </ns4:extent>
        </ns4:MD_DataIdentification>
    </ns1:identificationInfo>
    </ns1:MD_Metadata>
</ns0:GetRecordByIdResponse>"""


def _local(balise: str) -> str:
    return balise.rsplit("}", 1)[-1]


def _csw(corps: bytes) -> bytes:
    """Identifiant de la fiche et étendue temporelle (gml:TimePeriod) seulement."""
    racine = ET.fromstring(corps)
    uuid = next((e.get("uuid") for e in racine.iter() if _local(e.tag) == "MD_Metadata"), "") or ""
    periode = next((e for e in racine.iter() if _local(e.tag) == "TimePeriod"), None)
    if periode is None:
        raise ValueError("fiche CSW sans gml:TimePeriod")
    debut = next((e.text or "" for e in periode if _local(e.tag) == "beginPosition"), "")
    fin = next((e.text or "" for e in periode if _local(e.tag) == "endPosition"), "")
    ident = next((v for k, v in periode.attrib.items() if _local(k) == "id"), "")
    return CSW.format(uuid=uuid, ident=ident, debut=debut, fin=fin).encode("utf-8")


# (SERVICE, fichier) -> réduction. Pas de réducteur : extrait manuel, non rejoué.
REDUCTIONS: dict[tuple[str, str], Callable[[bytes], bytes]] = {
    ("API-GEO", "communes_62133.json"): lambda c: _ecrire_json(_json(c)),
    ("WIKIDATA", "sparql_P374_62133.json"): lambda c: _ecrire_json(_json(c)),
    ("WIKIDATA", "evenements_commune_P374_62133.json"): lambda c: _ecrire_json(_json(c)),  # contexte_local (#289)
    ("WIKIDATA", "evenements_commune_P374_62250.json"): lambda c: _ecrire_json(_json(c)),  # contexte_local (#289)
    ("WIKIDATA", "evenements_commune_P374_80080.json"): lambda c: _ecrire_json(_json(c)),  # contexte_local (#289)
    ("WIKIDATA", "evenements_departement_P2586_62.json"): lambda c: _ecrire_json(_json(c)),  # contexte_local (#345)
    ("WIKIDATA", "evenements_departement_P2586_80.json"): lambda c: _ecrire_json(_json(c)),  # contexte_local (#345)
    ("COG-INSEE", "v_commune_depuis_1943.csv"): lambda c: _csv_filtre(c, ("COM",)),
    ("COG-INSEE", "v_mvt_commune_2024.csv"): lambda c: _csv_filtre(c, ("COM_AV", "COM_AP")),
    ("IGN-GEOPLATEFORME", "GetCapabilities.xml"): _capacites,
    ("IGN-GEOPLATEFORME", "csw_ARCHIVES-NATIONALES_CASSINI-ROI.xml"): _csw,
    ("IGN-GEOPLATEFORME", "csw_BNF_CASSINI-MARIE-ANTOINETTE.xml"): _csw,
    ("INSEE-MELODI", "catalog_DS_POPULATIONS_HISTORIQUES.json"): _melodi_catalogue,
    ("INSEE-MELODI", "data_DS_POPULATIONS_HISTORIQUES_GEO_2025-COM-62133.json"): _melodi_donnees,
    ("HAL", "courrieres-mines.json"): _json_reindente,
    ("HAL", "billy-montigny-mines.json"): _json_reindente,
    ("CROSSREF", "courrieres-mines.json"): _json_reindente,
    ("ISIDORE", "courrieres-mines.json"): _isidore,
    ("THESES-FR", "courrieres-mines.json"): _theses,
    ("BNF-CATALOGUE", "courrieres-mines.xml"): lambda c: c,
    ("BNF-CATALOGUE", "diagnostic-index-inconnu.xml"): lambda c: c,
    ("SUDOC", "courrieres-mines.xml"): _sudoc,
    ("SUDOC", "billy-montigny-mines.xml"): _sudoc,
    ("PERSEE", "getrecord-rnord-1982-3879.xml"): _persee,
    # cas témoins du cultivateur et du soldat (#324)
    ("SUDOC", "vouille-les-marais-prieur.xml"): _sudoc,
    ("SUDOC", "vouille-les-marais-laboureur.xml"): _sudoc,
    ("SUDOC", "saint-amand-belloy-forgeron.xml"): _sudoc,
    ("SUDOC", "saint-amand-belloy-guerre.xml"): _sudoc,
    ("BNF-CATALOGUE", "vouille-les-marais-prieur.xml"): lambda c: c,
    ("THESES-FR", "saint-amand-montrond-forgeron.json"): _theses,
    # presse_recherche : analyseur Europeana (#343), enregistré avec une clé personnelle en en-tête
    ("EUROPEANA", "api-recherche-courrieres-1850-1950.json"): _europeana,
    ("EUROPEANA", "api-presse-greve-mineurs-1906-vide.json"): _europeana,
}


def reduire(service: str, fichier: str, corps: bytes) -> bytes:
    return REDUCTIONS[(service.upper(), fichier)](corps)


# ------------------------------------------------------------------------------------------------------ forme

def _chemins_json(v, prefixe: str, sortie: set[str]) -> None:
    if isinstance(v, dict):
        for k, x in v.items():
            chemin = f"{prefixe}.{k}" if prefixe else k
            sortie.add(chemin)
            _chemins_json(x, chemin, sortie)
    elif isinstance(v, list):
        for x in v:
            _chemins_json(x, prefixe + "[]", sortie)


def forme(fichier: str, corps: bytes) -> set[str] | None:
    """Forme d'une réponse : chemins des clés (JSON), des éléments et attributs (XML), en-tête (CSV) ; None si la
    forme n'est pas comparable (HTML, JavaScript)."""
    nom = fichier.lower()
    try:
        if nom.endswith(".json"):
            sortie: set[str] = set()
            _chemins_json(_json(corps), "", sortie)
            return sortie
        if nom.endswith(".xml"):
            sortie = set()

            def parcourir(e, chemin):
                c = f"{chemin}/{_local(e.tag)}" if chemin else _local(e.tag)
                sortie.add(c)
                sortie.update(f"{c}/@{_local(a)}" for a in e.attrib)
                for f in e:
                    parcourir(f, c)

            parcourir(ET.fromstring(corps), "")
            return sortie
        if nom.endswith(".csv"):
            return {"colonne:" + c for c in next(csv.reader(io.StringIO(corps.decode("utf-8-sig"))), [])}
    except (ValueError, ET.ParseError):
        return None
    return None


# ----------------------------------------------------------------------------------------------- requêtes

class Resultat(NamedTuple):
    service: str
    fichier: str
    verdict: str  # OK | DERIVE | AVERT | IGNORE
    detail: str
    ecrit: bool = False


class Enregistreur:
    """Rejeu des requêtes d'un ensemble de manifestes : intervalle par hôte, une tentative, service laissé de côté
    au premier refus ou silence."""

    def __init__(self, client: httpx.Client, racine: Path, *, ecrire: bool, intervalle: float = INTERVALLE,
                 dormir: Callable[[float], None] = time.sleep, horloge: Callable[[], float] = time.monotonic,
                 maintenant: Callable[[], datetime] = lambda: datetime.now(UTC),
                 cles: dict[str, str] | None = None):
        self.cles = {k.upper(): v for k, v in (cles or {}).items() if v}  # jamais affichées ni écrites
        self.client, self.racine, self.ecrire, self.intervalle = client, Path(racine), ecrire, intervalle
        self.dormir, self.horloge, self.maintenant = dormir, horloge, maintenant
        self.derniere: dict[str, float] = {}
        self.de_cote: dict[str, str] = {}  # service -> motif

    def _attendre(self, hote: str) -> None:
        if hote in self.derniere:
            reste = self.intervalle - (self.horloge() - self.derniere[hote])
            if reste > 0:
                self.dormir(reste)
        self.derniere[hote] = self.horloge()

    def _obtenir(self, url: str, en_tetes: dict | None = None) -> tuple[httpx.Response | None, str]:
        """(réponse, motif de consignation) : motif non vide pour un silence, un défi anti-robot, 401/403/429, 5xx."""
        from genealogiste_mcp.http import _protection

        self._attendre(urlsplit(url).hostname or "")
        try:
            # Une clé en en-tête ne suit aucune redirection (elle partirait vers une autre origine).
            suivre = {"follow_redirects": False} if en_tetes else {}
            reponse = self.client.get(url, headers={"User-Agent": UA, **(en_tetes or {})}, timeout=DELAI, **suivre)
        except httpx.HTTPError as exc:
            return None, f"pas de réponse ({type(exc).__name__})"
        if protection := _protection(reponse):
            return reponse, f"protection anti-robot ({protection}, HTTP {reponse.status_code}) : aucun contournement"
        if reponse.status_code in STATUTS_CONSIGNES or reponse.status_code >= 500:
            retry = reponse.headers.get("Retry-After")
            return reponse, f"HTTP {reponse.status_code}" + (f" (Retry-After {retry})" if retry else "")
        return reponse, ""

    def traiter(self, dossier: Path, manifeste: dict) -> list[Resultat]:
        service = manifeste["service"]
        resultats: list[Resultat] = []
        modifie = False
        for entree in manifeste["reponses"]:
            fichier = entree.get("fichier") or ""
            r = self._une(service, dossier, entree, fichier)
            resultats.append(r)
            modifie = modifie or r.ecrit
        if modifie:
            (dossier / MANIFESTE).write_text(json.dumps(manifeste, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
        return resultats

    def _une(self, service: str, dossier: Path, entree: dict, fichier: str) -> Resultat:
        def res(verdict: str, detail: str, ecrit: bool = False) -> Resultat:
            return Resultat(service, fichier or entree["url"][:60], verdict, detail, ecrit)

        if service in self.de_cote:
            return res("IGNORE", f"service laissé de côté : {self.de_cote[service]}")
        if entree["statut"] >= 400:
            return res("IGNORE", f"enregistré avec le statut {entree['statut']} (service protégé) : non rejoué")
        if not fichier or entree.get("rejouable") is False or (service, fichier) not in REDUCTIONS:
            return res("IGNORE", "extrait manuel ou corps non conservé : non rejoué")
        if motif := controle_url(entree["url"]):
            return res("IGNORE", f"requête refusée : {motif}")
        en_tete, secret = EN_TETES_CLE.get(service.upper()), self.cles.get(service.upper(), "")
        if en_tete and not secret:
            return res("IGNORE", f"clé d'API personnelle absente (en-tête {en_tete}) : non rejoué")
        nouveau = not (dossier / fichier).is_file()
        if nouveau and not self.ecrire:
            return res("IGNORE", "réponse pas encore enregistrée (--ecrire pour le premier enregistrement)")
        debut = self.horloge()
        reponse, motif = self._obtenir(entree["url"], {en_tete: secret} if en_tete else None)
        duree = round(self.horloge() - debut, 1)
        if motif:
            self.de_cote[service] = motif
            return res("AVERT", f"{motif} ; service laissé de côté, consigné")
        if reponse.status_code != entree["statut"]:
            self.de_cote[service] = f"HTTP {reponse.status_code}"
            return res("AVERT", f"HTTP {reponse.status_code} au lieu de {entree['statut']} : consigné, rien écrit"
                       + _message_erreur(reponse, secret))
        try:
            reduit = reduire(service, fichier, reponse.content)
        except (ValueError, KeyError, ET.ParseError) as exc:
            return res("DERIVE", f"réduction impossible, la réponse n'a plus la forme attendue ({exc})")
        if contient_secret(reduit, secret):
            return res("DERIVE", "la réponse réduite contient encore la clé d'API : rien écrit, compléter la réduction")
        avant = None if nouveau else forme(fichier, (dossier / fichier).read_bytes())
        apres = forme(fichier, reduit)
        if nouveau:
            verdict, detail = "OK", "premier enregistrement"
        elif avant is None or apres is None:
            verdict, detail = "OK", "forme non comparable (statut seul)"
        elif avant - apres:
            manque = sorted(avant - apres)
            verdict, detail = "DERIVE", (f"{len(manque)} champ(s) enregistré(s) absent(s) : "
                                         + ", ".join(manque[:8]) + (" …" if len(manque) > 8 else ""))
        else:
            en_plus = sorted(apres - avant)
            verdict = "OK"
            detail = "forme conforme" + (f" ({len(en_plus)} champ(s) nouveau(x) : {', '.join(en_plus[:5])})"
                                         if en_plus else "")
        ecrit = False
        if self.ecrire:
            (dossier / fichier).write_bytes(reduit)
            entree.update(date=self.maintenant().strftime("%Y-%m-%dT%H:%M:%SZ"), statut=reponse.status_code,
                          type=reponse.headers.get("Content-Type", entree.get("type", "")),
                          octets_origine=len(reponse.content),
                          empreinte="sha256:" + hashlib.sha256(reduit).hexdigest())
            if "duree_s" in entree:
                entree["duree_s"] = duree
            ecrit = True
            detail += " ; réécrit"
        return res(verdict, detail, ecrit)


def _message_erreur(reponse: httpx.Response, secret: str) -> str:
    """Message d'erreur JSON du service (champs ``error`` / ``message``), clé masquée ; vide sinon."""
    try:
        d = reponse.json()
    except ValueError:
        return ""
    if not isinstance(d, dict):
        return ""
    texte = " ; ".join(str(d[k]) for k in ("error", "message") if isinstance(d.get(k), str | int))[:300]
    for forme_ in {secret, quote(secret, safe=""), quote_plus(secret, safe="")} - {""}:
        texte = texte.replace(forme_, "***")
    return f" ({texte})" if texte else ""


def manifestes(racine: Path, services: list[str] | None = None) -> list[tuple[Path, dict]]:
    out = []
    for d in sorted(Path(racine).iterdir()):
        p = d / MANIFESTE
        if not p.is_file():
            continue
        m = json.loads(p.read_text(encoding="utf-8"))
        if not services or m["service"].upper() in services:
            out.append((d, m))
    return out


def cles_configurees() -> dict[str, str]:
    """Clés d'API personnelles de la configuration du plugin (environnement, ``<données>/.env``), pour les seuls
    services de ``EN_TETES_CLE``. Jamais affichées."""
    from genealogiste_mcp.config import load_config

    cles = load_config().cles_contexte
    return {code: cles[code] for code in EN_TETES_CLE if cles.get(code)}


def main(argv: list[str] | None = None, *, client: httpx.Client | None = None, racine: Path = REPONSES,
         dormir: Callable[[float], None] = time.sleep, cles: dict[str, str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--verifier", action="store_true", help="compare la forme, n'écrit rien (défaut)")
    mode.add_argument("--ecrire", action="store_true", help="réécrit les réponses réduites et les manifestes")
    ap.add_argument("--service", action="append", default=[], help="limiter à un service (répétable)")
    ap.add_argument("--intervalle", type=float, default=INTERVALLE, help="secondes entre deux requêtes vers un hôte")
    args = ap.parse_args(argv)
    choisis = [s.strip().upper() for s in args.service]
    liste = manifestes(racine, choisis)
    inconnus = set(choisis) - {m["service"].upper() for _, m in liste}
    if inconnus:
        print(f"service(s) sans manifeste : {', '.join(sorted(inconnus))}", file=sys.stderr)
        return 2
    propre = client is None
    if cles is None:  # exécution réelle : clés de la configuration ; client fourni (tests) : aucune clé lue
        cles = cles_configurees() if propre else {}
    client = client or httpx.Client(follow_redirects=True, max_redirects=5)
    derives = 0
    try:
        rec = Enregistreur(client, racine, ecrire=args.ecrire, intervalle=args.intervalle, dormir=dormir,
                           cles=cles)
        for dossier, manifeste in liste:
            for r in rec.traiter(dossier, manifeste):
                derives += r.verdict == "DERIVE"
                print(f"{r.verdict:<7} {r.service:<20} {r.fichier:<58} {r.detail}")
    finally:
        if propre:
            client.close()
    if args.ecrire:
        print("Réponses et manifestes réécrits : relire le diff avant de valider.")
    return 1 if derives else 0


if __name__ == "__main__":
    sys.exit(main())
