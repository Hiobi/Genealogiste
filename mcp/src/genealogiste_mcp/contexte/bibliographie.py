"""contexte_bibliographie (#286) : littérature historique savante, citée et normalisée.

Orchestration, sans définition de format (socle #321) : construit la recherche (lieux, sujet, période ; depuis
l'arbre quand une personne est donnée, jamais son identité), interroge les services bibliographiques actifs
(``services.refus`` avant toute requête, hôtes du référentiel seulement), normalise chaque notice en
``Reference`` (gabarits par service, analyseurs par protocole), dédoublonne (DOI, puis PPN, puis titre et année),
classe (pertinence géographique et temporelle, puis nature : savante d'abord), cite dans le style configuré et
inscrit chaque référence renvoyée au registre des références consultées. Chaque requête est tracée au journal, y
compris négative ou en échec. Rien trouvé : résultat vide explicite, jamais de remplissage.

Référence : docs/contexte-historique.md, « Outils », « contexte_bibliographie ».
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import httpx

from . import services as srv
from .gabarits import GABARITS, ORDRE, Notice, Recherche
from .modeles import Reference, ReferenceInvalide
from .portee import Periode
from .protocoles import ReponseInvalide
from .registre import NonConsultee, RegistreReferences

OUTIL = "contexte_bibliographie"
ECHELLES_LIEU = ("commune", "departement", "region", "pays", "nation")
LIMITE_MAX = 25
MAX_LIEUX = 3  # lieux d'une personne envoyés dans une même requête
TTL = 30 * 86400.0
RANG_NATURE = {"secondaire_savante": 0, "primaire": 1, "secondaire": 2, "index": 3, "tertiaire": 4}
EXCLUS = {"WIKIPEDIA": "Wikipédia n'est pas une source de cet outil (tertiaire) : remonter à ses références et "
                       "les chercher ici par leur sujet ou leur lieu."}
RAPPEL = ("Une référence situe un individu, elle ne prouve rien sur lui. Notices seules (« non lu ») : lire le "
          "passage utile avant de citer un énoncé, avec sa page. Citer la citation renvoyée, jamais de mémoire.")
VIDE = ("Aucune référence trouvée : contexte non documenté par les services interrogés pour cette recherche. "
        "Élargir l'échelle (département, région) ou le sujet ; ne pas combler par un texte général.")


class RechercheInvalide(ValueError):
    """Arguments insuffisants ou incohérents : aucune requête émise."""


# ------------------------------------------------------------------------------------------------- recherche

def _plat(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").casefold()
    return re.sub(r"[^\w]+", " ", s).strip()


def lire_periode(texte: str) -> Periode | None:
    """« 1880-1914 », « 1880 – 1914 », « 1906 » -> Periode ; vide -> None ; autre forme : RechercheInvalide."""
    t = (texte or "").strip()
    if not t:
        return None
    m = re.fullmatch(r"(\d{3,4})(?:\s*[-–—/à]+\s*(\d{3,4}))?", t)
    if not m:
        raise RechercheInvalide(f"periode={texte!r} : attendu « AAAA » ou « AAAA-AAAA »")
    de = int(m.group(1))
    a = int(m.group(2) or de)
    if a < de:
        raise RechercheInvalide(f"periode={texte!r} : fin antérieure au début")
    return Periode(de, a)


@dataclass
class Demande:
    """Recherche préparée : ce qui part (``recherche``) et ce qui sert au classement (période, lieux élargis)."""

    recherche: Recherche
    periode: Periode | None
    echelle: str
    lieux_larges: tuple[str, ...] = ()  # échelle supérieure (département…) des lieux d'une personne
    depuis_personne: bool = False
    metiers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"sujet": self.recherche.sujet, "lieux": list(self.recherche.lieux), "echelle": self.echelle,
                "periode": self.periode.to_dict() if self.periode else None,
                "depuis_personne": self.depuis_personne, "metiers": self.metiers,
                "limite_par_service": self.recherche.limite}


_ATTRIBUT = {"commune": "commune", "departement": "departement", "region": "region", "pays": "pays_naturel",
             "nation": "pays"}


def preparer(sujet: str = "", lieu: str = "", periode: str = "", echelle: str = "commune", limite: int = 10,
             tree=None, personne: str = "") -> Demande:
    """Recherche à partir des arguments ; avec ``personne`` (et ``tree``), lieu, période et métier manquants sont
    lus dans l'arbre (faits sourcés seulement, ``requete.depuis_personne``). Jamais de nom ni d'identifiant."""
    echelle = (echelle or "commune").strip().lower()
    if echelle not in ECHELLES_LIEU:
        raise RechercheInvalide(f"echelle={echelle!r} : valeurs possibles {' | '.join(ECHELLES_LIEU)}")
    if not isinstance(limite, int) or isinstance(limite, bool) or limite < 1:
        raise RechercheInvalide("limite : entier positif attendu")
    per = lire_periode(periode)
    sujet = re.sub(r"\s+", " ", sujet or "").strip()
    lieux = [lieu.strip()] if (lieu or "").strip() else []
    larges: list[str] = []
    metiers: list[str] = []
    if personne:
        from ..normalize.pays import pays_du_lieu
        from .requete import depuis_personne

        rq = depuis_personne(tree, personne, pays_du_lieu=lambda x: pays_du_lieu(x).get("nom") or None)
        metiers = list(rq.metiers)
        if not lieux:
            attr = _ATTRIBUT[echelle]
            lieux = list(dict.fromkeys(getattr(x, attr) for x in rq.lieux if getattr(x, attr)))[:MAX_LIEUX]
            if not lieux and rq.lieux:
                raise RechercheInvalide(f"aucun lieu de la personne n'est renseigné à l'échelle « {echelle} » : "
                                        "préciser lieu ou choisir une autre échelle")
            if echelle == "commune":
                larges = [d for d in dict.fromkeys(x.departement for x in rq.lieux if x.departement)]
        if not sujet and metiers:
            sujet = metiers[0]
        if per is None and rq.periode is not None:
            per = rq.periode
    if not lieux and not sujet:
        raise RechercheInvalide("préciser au moins un lieu, un sujet ou une personne dont l'arbre donne des lieux "
                                "sourcés")
    rech = Recherche(lieux=tuple(lieux), sujet=sujet, limite=min(limite, LIMITE_MAX))
    return Demande(rech, per, echelle, tuple(larges), bool(personne), metiers)


# ------------------------------------------------------------------------------------------------ classement

_SIECLES = {"XV": (1401, 1500), "XVI": (1501, 1600), "XVII": (1601, 1700), "XVIII": (1701, 1800),
            "XIX": (1801, 1900), "XX": (1901, 2000), "XXI": (2001, 2100)}


def _contient(indices: str, terme: str) -> bool:
    t = _plat(terme)
    return bool(t) and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", indices) is not None


def _mot_sujet(indices: str, mot: str) -> bool:
    m = _plat(mot)
    if len(m) < 3:
        return False
    racine = m[:max(4, len(m) - 2)]
    return re.search(rf"(?<!\w){re.escape(racine)}", indices) is not None


def _bornes_citees(texte_brut: str) -> list[tuple[int, int]]:
    """Années et siècles cités dans le titre, les sujets ou les mots-clés (« 1880-1914 », « 1906 », « XIXe »)."""
    out = []
    for m in re.finditer(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?:\s*[-–]\s*(1[0-9]{3}|20[0-9]{2}))?(?!\d)", texte_brut):
        de, a = int(m.group(1)), int(m.group(2) or m.group(1))
        out.append((min(de, a), max(de, a)))
    for m in re.finditer(r"(?<![A-Za-z])(X{0,2}(?:IX|IV|V?I{0,3}))e\b", texte_brut):
        if m.group(1) in _SIECLES:
            out.append(_SIECLES[m.group(1)])
    return out


def pertinence(ref: Reference, notice: Notice, demande: Demande) -> dict:
    """Pertinence géographique (lieu demandé, lieu plus large, aucun) et temporelle (recoupe, contemporaine,
    non précisée, hors période) lue sur la notice ; ``sujet`` : un mot du sujet figure dans la notice."""
    plat = _plat(" ".join([notice.indices, ref.titre, ref.publication]))
    lieu = next((x for x in demande.recherche.lieux if _contient(plat, x)), "")
    large = "" if lieu else next((x for x in demande.lieux_larges if _contient(plat, x)), "")
    sujet = any(_mot_sujet(plat, m) for m in demande.recherche.sujet.split())
    out = {"lieu": "demande" if lieu else ("plus_large" if large else "aucun"), "lieu_cite": lieu or large,
           "sujet": sujet}
    per = demande.periode
    if per is None:
        out["periode"] = "sans_objet"
        return out
    bornes = _bornes_citees(" ".join([notice.indices, ref.titre]))
    if ref.annee and per.de <= ref.annee <= per.a:
        out["periode"] = "contemporaine"
    elif any(de <= per.a and a >= per.de for de, a in bornes):
        out["periode"] = "recoupe"
    elif bornes:
        out["periode"] = "hors_periode"
    else:
        out["periode"] = "non_precisee"
    if bornes:
        out["annees_citees"] = [f"{de}-{a}" if a != de else str(de) for de, a in bornes][:6]
    return out


def _score(p: dict) -> tuple[int, int]:
    geo = {"demande": 2, "plus_large": 1}.get(p["lieu"], 0)
    temps = {"contemporaine": 2, "recoupe": 2, "non_precisee": 1, "sans_objet": 1}.get(p["periode"], 0)
    return geo, temps


# ------------------------------------------------------------------------------------------- dédoublonnage

def cle_doublon(ref: Reference) -> list[str]:
    """Clés de dédoublonnage, dans l'ordre : DOI, PPN, titre normalisé et année."""
    cles = []
    if ref.identifiant.type in ("doi", "ppn"):
        cles.append(ref.identifiant.cle)
    if ref.titre and ref.annee:
        cles.append(f"titre:{_plat(ref.titre)[:120]}|{ref.annee}")
    return cles


def _remplis(ref: Reference) -> int:
    return sum(bool(getattr(ref, c)) for c in ("auteurs", "titre", "publication", "annee", "pages", "volume",
                                               "numero", "lieu_edition"))


@dataclass
class _Trouvee:
    ref: Reference
    contenu: object  # corps de la réponse qui porte la notice (preuve de consultation)
    pertinence: dict
    rang: tuple
    services: list[str]


def dedoublonner(trouvees: list[_Trouvee]) -> list[_Trouvee]:
    """Une entrée par œuvre : même DOI, sinon même PPN, sinon même titre et même année. L'entrée gardée est la
    plus savante, puis la plus complète ; ``services`` réunit tous les services qui l'ont trouvée."""
    groupes: list[list[_Trouvee]] = []
    index: dict[str, int] = {}
    for t in trouvees:
        cles = cle_doublon(t.ref)
        g = next((index[c] for c in cles if c in index), None)
        if g is None:
            g = len(groupes)
            groupes.append([])
        groupes[g].append(t)
        for c in cles:
            index.setdefault(c, g)
    out = []
    for g in groupes:
        g.sort(key=lambda t: (RANG_NATURE.get(t.ref.nature, 9), -_remplis(t.ref)))
        garde = g[0]
        garde.services = list(dict.fromkeys(s for t in g for s in t.services))
        out.append(garde)
    return out


# --------------------------------------------------------------------------------------------- orchestration

def _nature(champs: dict, periode: Periode | None, defaut: str) -> str:
    """Nature de la notice : celle du gabarit ; un imprimé publié pendant la période étudiée est une source
    contemporaine (primaire) ; à défaut, la nature du service au référentiel."""
    nature = champs.get("nature") or defaut
    annee = champs.get("annee")
    if periode and isinstance(annee, int) and periode.de <= annee <= periode.a and champs.get("type_document") != "these":
        return "primaire"
    return nature


def _url(base: str, params: dict) -> str:
    return str(httpx.URL(base, params={k: v for k, v in params.items() if v not in (None, "")}))


def _echec(ctx, code: str, params_journal: dict, exc: Exception, personne: str | None, secret: bool) -> dict:
    """Service en échec : tracé au journal (avec la tâche manuelle d'un blocage anti-robot). Quand une clé ou le
    mailto a été envoyé, le message est masqué et tracé sans l'adresse de la requête."""
    from ..sources.base import error_envelope

    cfg = ctx.config
    if not secret:
        env = error_envelope(ctx, code.lower(), "bibliographie", params_journal, exc, personne)
    else:
        msg = srv.masquer_cles(str(exc), cfg)
        env = {"erreur": msg, "journal": ctx.journal.add(code.lower(), "bibliographie", params_journal, "erreur",
                                                          resume=msg, personne=personne)}
    out = {"service": code, "erreur": srv.masquer_cles(str(env.get("erreur", "")), cfg), "journal": env.get("journal")}
    for k in ("statut", "protection", "tache_manuelle", "reessayer_apres", "coupe_circuit", "echec_memorise"):
        if k in env:
            out[k] = env[k]
    return out


def rechercher(ctx, registre: RegistreReferences, demande: Demande, services_demandes: list[str] | None = None,
               style: str = "iso690", personne: str | None = None,
               residus: Callable[[str], list[str]] | None = None, aujourd_hui: str | None = None) -> dict:
    """Interroge les services, normalise, dédoublonne, classe, inscrit au registre et renvoie l'enveloppe.

    ``residus`` : fonction URL -> éléments d'identité de la personne trouvés dans l'URL (``requete.residus_identite``) ;
    une requête qui en contient n'est pas émise."""
    cfg = ctx.config
    consulte_le = aujourd_hui or date.today().isoformat()
    codes = list(dict.fromkeys((c or "").strip().upper() for c in services_demandes)) if services_demandes \
        else [c for c in ORDRE if srv.etat(c, cfg).actif]
    interroges, echecs, ecartes, notices_ecartees = [], [], [], []
    trouvees: list[_Trouvee] = []
    for code in codes:
        if refus := srv.refus(code, cfg):
            ecartes.append({"service": refus["service"], "motif": refus["erreur"]})
            continue
        if code in EXCLUS:
            ecartes.append({"service": code, "motif": EXCLUS[code]})
            continue
        gab = GABARITS.get(code)
        entree = srv.par_code(code)
        if gab is None:
            ecartes.append({"service": code, "motif": (
                f"{entree['nom']} : pas d'analyseur bibliographique livré pour ce service (protocole "
                f"{entree['protocole']}) ; aucune requête émise. Services livrés : {', '.join(ORDRE)}")})
            continue
        base = entree["url_api"]
        params = gab.parametres(demande.recherche, cfg)
        url = _url(base, params)
        url_masquee = srv.masquer_cles(url, cfg)
        params_journal = {"requete": url_masquee}
        secret = url_masquee != url
        if not srv.url_autorisee(code, url):
            ecartes.append({"service": code, "motif": f"hôte hors du référentiel : {url_masquee}"})
            continue
        if residus and (trouves := residus(url)):
            echecs.append({"service": code, "erreur": (
                f"requête non émise : elle contiendrait un élément d'identité de la personne ({', '.join(trouves)}) ; "
                "préciser lieu et sujet sans nom")})
            continue
        try:
            contenu, cache = ctx.http.get(base, params=params, parse=gab.parse, ttl=TTL, source=f"contexte:{code}")
        except Exception as exc:  # noqa: BLE001 — un service en échec n'empêche pas les autres
            echecs.append(_echec(ctx, code, params_journal, exc, personne, secret))
            continue
        try:
            total, notices = gab.analyser(contenu)
        except ReponseInvalide as exc:
            echecs.append(_echec(ctx, code, params_journal, exc, personne, secret))
            continue
        retenues = []
        for rang, n in enumerate(notices):
            if n.ecart:
                notices_ecartees.append({"service": code, "titre": n.titre_brut[:200], "motif": n.ecart})
                continue
            champs = dict(n.champs)
            champs["nature"] = _nature(champs, demande.periode, entree["nature"])
            try:
                ref = Reference(service=code, requete=url_masquee, consulte_le=consulte_le, **champs)
            except (ReferenceInvalide, TypeError) as exc:
                notices_ecartees.append({"service": code, "titre": n.titre_brut[:200],
                                         "motif": f"notice non conforme au format commun : {exc}"})
                continue
            p = pertinence(ref, n, demande)
            if p["lieu"] == "aucun" and not p["sujet"]:
                notices_ecartees.append({"service": code, "titre": ref.titre[:200],
                                         "motif": "ni le lieu ni le sujet ne figurent dans le titre ou les sujets de "
                                                  "la notice"})
                continue
            geo, temps = _score(p)
            retenues.append(_Trouvee(ref, contenu, p, (-geo, -temps, RANG_NATURE.get(ref.nature, 9),
                                                       ORDRE.index(code), rang), [code]))
        jid = ctx.journal.add(code.lower(), "bibliographie", params_journal, "positif" if retenues else "negatif",
                              nb_resultats=len(retenues), cache=cache, personne=personne,
                              resume="; ".join(t.ref.titre[:80] for t in retenues[:5]),
                              references=[t.ref.identifiant.cle for t in retenues[:20]])
        interroges.append({"service": code, "requete": url_masquee, "total": total, "nb_notices": len(notices),
                           "nb_retenues": len(retenues), "depuis_cache": cache, "journal": jid})
        trouvees += retenues

    finales = sorted(dedoublonner(trouvees), key=lambda t: t.rang)
    references = []
    for t in finales:
        try:
            registre.enregistrer(t.ref, statut=200, reponse=t.contenu)
        except (NonConsultee, ReferenceInvalide) as exc:
            notices_ecartees.append({"service": t.ref.service, "titre": t.ref.titre[:200],
                                     "motif": f"non inscrite au registre des références consultées : {exc}"})
            continue
        references.append({**t.ref.to_dict(style), "trouvee_par": t.services, "pertinence": t.pertinence})

    out = {"outil": OUTIL, "requete": demande.to_dict(), "style_citation": style, "nb_references": len(references),
           "references": references, "services_interroges": interroges, "services_en_echec": echecs,
           "services_ecartes": ecartes, "notices_ecartees": notices_ecartees[:50], "rappel": RAPPEL}
    if not references:
        out["recherche_negative"] = VIDE
    if echecs and not interroges:
        out["erreur"] = "Aucun service n'a répondu : " + " ; ".join(f"{e['service']} : {e['erreur']}" for e in echecs)
    return out
