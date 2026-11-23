"""Presse ancienne multi-services avec repli explicite (#288) : logique de l'outil ``presse_recherche``.

Services, dans l'ordre par défaut : Gallica, Europeana, Chronicling America, Retronews. Chacun est essayé ou
écarté avec son motif ; si aucun ne rend de résultat, la réponse est une **tâche manuelle** (liens de
consultation construits pour la requête, règle de #150), jamais un silence.

- **Gallica** : client existant (``sources/gallica.py`` : requête SRU, analyseur ``parse_sru``, recherche dans
  le document ``search_in_document``), client HTTP commun (coupe-circuit anti-robot, plafonds, cache, journal).
  Le référentiel de contexte classe GALLICA en lien seulement (SRU en 403) ; ce module n'ouvre pas un second
  accès : il passe par le même client que ``gallica_recherche``, et un blocage y est rendu tel quel
  (``bloque_antirobot``, coupe-circuit) avant de passer aux services suivants.
- **Europeana** : ``services.refus`` avant toute requête (clé requise ``GENEALOGISTE_CLE_EUROPEANA``, activation).
  Aucun analyseur livré : aucune réponse réelle de l'API n'a pu être enregistrée (#323) ; même avec une clé, le
  service est signalé « sans analyseur » et renvoyé au lien de consultation. La clé n'est jamais lue ici.
- **Chronicling America**, **Retronews** : lien seulement (``services.refus`` donne le motif).

Résultats : ``Reference`` (``nature: primaire``, ``type_document: presse``) inscrites au registre des références
consultées (preuve : corps 2xx contenant l'ARK), avec l'extrait OCR éventuel (``ocr: true`` et la mention
« lecture OCR non vérifiée »). Liens de consultation : forme vérifiée par une requête réelle (manifestes de
``tests/fixtures/contexte/reponses/``), sinon page d'accueil du service.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import date
from urllib.parse import quote, urlencode

from ..sources import gallica
from ..sources.base import (
    DAY,
    SourceContext,
    consigne_antirobot,
    envelope,
    error_envelope,
    suite_sans_navigateur,
)
from . import services
from .modeles import Identifiant, Reference, ReferenceInvalide
from .registre import NonConsultee, RegistreReferences

SERVICES_PRESSE = ("GALLICA", "EUROPEANA", "CHRONICLING-AMERICA", "RETRONEWS")
MENTION_OCR = "lecture OCR non vérifiée"
EXTRAITS_MAX = 3  # documents Gallica dont on cherche la page et l'extrait OCR (une requête chacun)
NOMBRE_MAX = 50

AVERTISSEMENT = ("Presse ancienne : source primaire contemporaine, qui situe un fait sans le prouver pour un "
                 "individu. Un extrait OCR porte la mention « " + MENTION_OCR + " » jusqu'à relecture de l'image "
                 "(gallica_iiif, piece_archiver) ; citer le numéro, la date et la page lus sur l'image.")

# Liens de consultation. Forme de recherche vérifiée le 2026-11-23 (tests/fixtures/contexte/reponses/<code>/
# MANIFESTE.json) : Retronews (paramètre q = base64 d'un JSON encodé, décodé par le site) et le site public
# d'Europeana (query=). Gallica et Chronicling America répondent 403 (Cloudflare) : page d'accueil seulement.
# Regroupés dans un dictionnaire : liens de consultation, jamais interrogés par le plugin (voir
# tests/test_politique_acces.py, qui prend toute constante URL de module pour un hôte interrogé).
LIENS = {"retronews_recherche": "https://www.retronews.fr/search",
         "europeana_recherche": "https://www.europeana.eu/fr/search"}
VERIFICATIONS = {
    "RETRONEWS": "forme relevée le 2026-11-23 (lien « Recherche avancée » du site, HTTP 200)",
    "EUROPEANA": "forme relevée le 2026-11-23 (site public, HTTP 200, requête reprise par la page)",
    "GALLICA": "recherche non vérifiable le 2026-11-23 (HTTP 403 Cloudflare) : page d'accueil",
    "CHRONICLING-AMERICA": "recherche non vérifiable le 2026-11-23 (HTTP 403 Cloudflare) : page de la collection",
}
ACCUEILS = {"EUROPEANA": "https://www.europeana.eu/"}


class PresseInvalide(ValueError):
    """Paramètre de presse_recherche invalide (période, service) : aucune requête émise."""


def lire_periode(periode: str) -> tuple[str, str]:
    """« 1906 », « 1900-1910 » (ou « 1900/1910 », « 1900–1910 ») -> (début, fin) ; vide -> ("", "")."""
    p = (periode or "").strip()
    if not p:
        return "", ""
    m = re.fullmatch(r"(\d{4})(?:\s*[-–/]\s*(\d{4}))?", p)
    if not m:
        raise PresseInvalide(f"periode={periode!r} : année (« 1906 ») ou intervalle (« 1900-1910 ») attendu")
    de, a = m.group(1), m.group(2) or m.group(1)
    if int(a) < int(de):
        raise PresseInvalide(f"periode={periode!r} : fin antérieure au début")
    return de, a


def lire_services(valeur: str) -> tuple[str, ...]:
    """Codes séparés par des virgules (casse indifférente), dans l'ordre donné ; vide : tous, ordre par défaut."""
    codes = [c.strip().upper() for c in (valeur or "").split(",") if c.strip()]
    if not codes:
        return SERVICES_PRESSE
    inconnus = [c for c in codes if c not in SERVICES_PRESSE]
    if inconnus:
        raise PresseInvalide(f"services : {', '.join(inconnus)} inconnu(s) ; valeurs possibles : "
                             f"{', '.join(SERVICES_PRESSE)}")
    return tuple(dict.fromkeys(codes))


def _mots(texte: str, lieu: str) -> str:
    return " ".join(x for x in ((texte or "").strip(), (lieu or "").strip()) if x)


def lien_retronews(mots: str) -> str:
    """Recherche avancée Retronews : q = base64(encodeURIComponent(JSON)), comme le lien du site."""
    critere = {"search": {"type": "advanced", "criteria": {
        "allTheseWords": mots, "someOfTheseWords": "", "noneOfTheseWords": "", "expression": "",
        "wordProximity": "MIN", "exactSearch": False, "onlyHeadlines": False, "onlyTitles": False,
        "dateParticle": "EXACT", "includedFields": {}, "excludedFields": {},
        "selectedFacets": {"date": {}, "location": {"data": [], "size": 5}, "organization": {"data": [], "size": 5},
                           "person": {"data": [], "size": 5}, "publicationId": {"size": 5}, "workId": {"size": 5},
                           "publicationLocation": {"data": {}, "size": 5}, "thematic": {}}}}}
    brut = json.dumps(critere, ensure_ascii=False, separators=(",", ":"))
    q = base64.b64encode(quote(brut, safe="-_.!~*'()").encode("ascii")).decode("ascii")
    return f"{LIENS['retronews_recherche']}?page=1&advanced=true&q={quote(q, safe='')}"


def lien_europeana(mots: str) -> str:
    return f"{LIENS['europeana_recherche']}?{urlencode({'query': mots}, quote_via=quote)}"


def liens_consultation(texte: str, lieu: str, debut: str, fin: str) -> list[dict]:
    """Liens à ouvrir par l'utilisateur, un par service de presse ; recherche pré-remplie seulement quand sa forme
    a été vérifiée, sinon page d'accueil avec les termes à saisir."""
    mots = _mots(texte, lieu)
    periode = f"{debut}-{fin}" if debut and fin and debut != fin else debut
    a_saisir = f"mots : {mots}" + (f" ; période : {periode}" if periode else "")
    out = []
    for code in SERVICES_PRESSE:
        s = services.par_code(code) or {}
        if code == "RETRONEWS":
            url, forme = lien_retronews(mots), "recherche"
        elif code == "EUROPEANA":
            url, forme = lien_europeana(mots), "recherche"
        else:
            url, forme = s.get("site") or ACCUEILS.get(code, ""), "accueil"
        lien = {"service": code, "nom": s.get("nom", code), "url": url, "forme": forme,
                "verification": VERIFICATIONS[code]}
        if forme == "accueil":
            lien["a_saisir"] = a_saisir
        elif periode:
            lien["a_saisir"] = f"période : {periode} (filtre du site, non pré-rempli)"
        out.append(lien)
    return out


def _date_iso(valeur: str) -> tuple[str, int | None]:
    """Date d'un fascicule Gallica (dc:date) -> (date ISO ou "", année ou None) ; rien n'est deviné."""
    v = (valeur or "").split(",")[0].strip()
    m = re.fullmatch(r"(\d{4})(?:-(\d{2})-(\d{2}))?", v)
    if not m:
        return "", None
    annee = int(m.group(1))
    if m.group(2):
        try:
            date.fromisoformat(v)
            return v, annee
        except ValueError:
            return "", annee
    return "", annee


def _reference_gallica(rec: dict, requete: str) -> Reference | None:
    if not rec.get("id_externe"):
        return None
    iso, annee = _date_iso(rec.get("date", ""))
    try:
        return Reference(identifiant=Identifiant("ark", f"ark:/12148/{rec['id_externe']}"), nature="primaire",
                         publication=rec.get("titre", ""), type_document="presse", annee=annee, date=iso,
                         lu="notice_seule", service="GALLICA", requete=requete,
                         consulte_le=date.today().isoformat())
    except ReferenceInvalide:
        return None


def _gallica(ctx: SourceContext, registre: RegistreReferences, texte: str, lieu: str, debut: str, fin: str,
             nombre: int) -> tuple[dict, list[dict]]:
    """Gallica par le client existant : SRU (fascicules de presse), puis page et extrait OCR des premiers
    documents (ContentSearch). Renvoie (état du service, résultats)."""
    query = gallica.build_query(_mots(texte, lieu), "presse", "", debut, fin, exact=False)
    params = {"operation": "searchRetrieve", "version": "1.2", "query": query,
              "maximumRecords": str(max(1, min(nombre, NOMBRE_MAX))), "startRecord": "1"}
    requete = f"{gallica.SRU}?{urlencode(params, quote_via=quote)}"
    try:
        xml_text, cached = ctx.http.get(gallica.SRU, params=params, ttl=90 * DAY, source="gallica", parse="text")
        total, records = gallica.parse_sru(xml_text)
    except Exception as exc:  # noqa: BLE001 — erreur rendue et journalisée par error_envelope
        err = error_envelope(ctx, "gallica", "sru", {"query": query}, exc)
        etat = {"service": "GALLICA", "statut": err.get("statut") or "erreur", "motif": err["erreur"],
                "journal": err["journal"], "requete": requete}
        for k in ("protection", "date_detection", "coupe_circuit", "exclusion", "exclu_jusqu_au", "reessayer_apres",
                  "echec_memorise"):
            if k in err:
                etat[k] = err[k]
        return etat, []
    env = envelope(ctx, "gallica", "sru", {"query": query}, records, total, cached)
    etat = {"service": "GALLICA", "statut": "interroge", "total": total, "nb_resultats": 0, "journal": env["journal"],
            "depuis_cache": cached, "requete": requete}
    resultats: list[dict] = []
    extraits_possibles = True
    for rec in records:
        ref = _reference_gallica(rec, requete)
        if ref is None:
            continue
        try:
            registre.enregistrer(ref, statut=200, reponse=xml_text)  # le client ne rend que les corps 2xx
            au_registre = True
        except (NonConsultee, ReferenceInvalide):
            au_registre = False
        item = {**ref.to_dict(), "ocr": False, "extrait": "", "vue": None, "url": rec.get("url", ""),
                "au_registre": au_registre}
        if extraits_possibles and len(resultats) < EXTRAITS_MAX and (texte or "").strip():
            doc = gallica.search_in_document(ctx, rec["id_externe"], texte)
            if "erreur" in doc:
                extraits_possibles = False  # blocage ou panne : pas d'autre requête de page
                etat["extraits"] = f"extraits OCR interrompus : {doc['erreur']}"
            elif doc.get("resultats"):
                hit = doc["resultats"][0]
                if hit.get("extrait"):
                    item.update(ocr=True, extrait=hit["extrait"], mention=MENTION_OCR)
                item.update(vue=hit.get("page"), url=hit.get("url") or item["url"], image=hit.get("image", ""))
        item["suite"] = ("Lire la vue sur l'image (gallica_iiif ou gallica_texte), puis l'archiver avec piece_archiver "
                         "avant de citer le numéro et la page ; vue = numéro de vue Gallica (fN), pas forcément la "
                         "page imprimée.")
        resultats.append(item)
    etat["nb_resultats"] = len(resultats)
    return etat, resultats


def _sans_requete(code: str, config) -> dict:
    """Service écarté sans requête : motif de services.refus, ou analyseur non livré."""
    refus = services.refus(code, config)
    if refus is not None:
        s = services.par_code(code) or {}
        statut = "lien_seulement" if s.get("mode") == "lien_seulement" else "refuse"
        return {"service": code, "statut": statut, "motif": refus["erreur"], "requetes_emises": 0}
    return {"service": code, "statut": "sans_analyseur", "requetes_emises": 0,
            "motif": (f"{code} : interrogeable, mais aucun analyseur livré (aucune réponse réelle de l'API "
                      "enregistrée, #323) ; consulter le lien")}


def rechercher(ctx: SourceContext, registre: RegistreReferences, texte: str, lieu: str = "", periode: str = "",
               services_demandes: str = "", nombre: int = 10) -> dict:
    """Recherche de presse ancienne sur les services demandés, dans l'ordre, avec repli explicite. La garde des
    vivants est appelée par l'outil avant ce module."""
    debut, fin = lire_periode(periode)
    codes = lire_services(services_demandes)
    if not _mots(texte, lieu):
        raise PresseInvalide("texte : mots à chercher attendus (événement, métier, lieu ; jamais une personne vivante)")
    etats: list[dict] = []
    resultats: list[dict] = []
    for code in codes:
        if code == "GALLICA":
            etat, res = _gallica(ctx, registre, texte, lieu, debut, fin, nombre)
            resultats += res
        else:
            etat = _sans_requete(code, ctx.config)
        etats.append(etat)
    liens = liens_consultation(texte, lieu, debut, fin)
    bloque = next((e for e in etats if e.get("statut") == "bloque_antirobot"), None)
    parametres = {"texte": texte, "lieu": lieu, "periode": periode, "services": list(codes)}
    interroge = any(e.get("statut") == "interroge" for e in etats)
    statut_journal = ("positif" if resultats else "bloque_antirobot" if bloque else "negatif" if interroge
                      else "manuel")
    note = services.masquer_cles(json.dumps({"services": [{k: e[k] for k in ("service", "statut", "motif")
                                                             if k in e} for e in etats]}, ensure_ascii=False),
                                 ctx.config)
    jid = ctx.journal.add(
        source="presse", operation="presse_recherche", parametres=parametres,
        statut=statut_journal,
        nb_resultats=len(resultats),
        resume="; ".join(f"{r.get('publication')} {r.get('date') or r.get('annee') or ''}".strip()
                         for r in resultats[:5]) or "aucun résultat : tâche manuelle (liens de consultation)",
        references=[r["url"] for r in resultats[:20] if r.get("url")] or [x["url"] for x in liens],
        note=note)
    out = {"outil": "presse_recherche",
           "requete": {"texte": texte, "lieu": lieu, "periode": {"de": debut, "a": fin} if debut else {},
                       "services": list(codes)},
           "statut": "resultats" if resultats else ("bloque_antirobot" if bloque else "tache_manuelle"),
           "services": etats, "resultats": resultats, "nb_resultats": len(resultats), "journal": jid,
           "liens_consultation": liens, "avertissement": AVERTISSEMENT}
    if resultats:
        return out
    out["recherche_negative"] = ("Aucun résultat obtenu par les services interrogeables : recherche tracée au "
                                 "journal ; consultation manuelle à faire (tache_manuelle).")
    out["tache_manuelle"] = {
        "statut": "a_faire",
        "description": f"Chercher « {_mots(texte, lieu)} » dans la presse ancienne"
                       + (f" ({debut}-{fin})" if debut else "") + " depuis le poste de l'utilisateur.",
        "motifs": {e["service"]: e.get("motif") or "aucun résultat" for e in etats},
        "liens": liens,
        "a_relever": ("titre du périodique, date et numéro, page, extrait lu sur l'image (pas l'OCR), "
                      "identifiant ou URL de la vue"),
        "reprise": ["source_collee", "piece_archiver", "media_enregistrer"],
    }
    if bloque:
        url = liens[SERVICES_PRESSE.index("GALLICA")]["url"]
        out.update(service="GALLICA", protection=bloque.get("protection", ""),
                   date_detection=bloque.get("date_detection", ""), url=url,
                   consigne=consigne_antirobot(bloque.get("protection"), url), suite=suite_sans_navigateur(url))
    else:
        out["suite"] = suite_sans_navigateur(liens[SERVICES_PRESSE.index("RETRONEWS")]["url"])
    return out
