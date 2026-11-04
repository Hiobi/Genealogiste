"""Référentiel des services d'archives publiques françaises (referentiels/archives_fr.json).

Chaque entrée : code, nom, type, département, site, visionneuse, NAAN ARK, mise en ligne par type de document
(``{"naissance": {"de": 1792, "a": 1922}}`` ; absent = inconnu), inscription, demande à distance, date de
vérification. Les valeurs sont vérifiées à la main : rien n'est déduit ni inventé (docs/archives.md).
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from . import ark
from .normalize.places import DEPARTEMENTS, normalize_place

PATH = Path(__file__).parent / "referentiels" / "archives_fr.json"
STALE_DAYS = 365
TYPES = ("departementales", "communales", "nationales", "militaires", "notariales", "diocesaines", "autre")
DOCUMENTS = ("naissance", "mariage", "deces", "tables_decennales", "recensement", "notaire", "matricule",
             "cadastre", "paroissiaux")


@lru_cache(maxsize=1)
def services() -> tuple[dict, ...]:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    out = tuple(data["services"])
    for s in out:  # table NAAN de ark.py complétée par le référentiel (sans écraser les entrées vérifiées)
        if s.get("ark_naan") and s["ark_naan"] not in ark.NAANS:
            ark.NAANS[s["ark_naan"]] = {"code": s["code"], "nom": s["nom"],
                                        "hote": s.get("visionneuse") or s.get("site", "")}
    return out


def validate() -> list[str]:
    """Problèmes de format du référentiel (utilisé par les tests et le script de vérification)."""
    errs, seen = [], set()
    for s in services():
        c = s.get("code", "")
        if not c or c in seen:
            errs.append(f"code manquant ou en double : {c!r}")
        seen.add(c)
        if not s.get("nom"):
            errs.append(f"{c} : nom manquant")
        if s.get("type") not in TYPES:
            errs.append(f"{c} : type {s.get('type')!r} (valeurs : {', '.join(TYPES)})")
        if s.get("type") == "departementales" and s.get("departement") not in DEPARTEMENTS:
            errs.append(f"{c} : département {s.get('departement')!r} inconnu")
        for k, v in (s.get("en_ligne") or {}).items():
            if k not in DOCUMENTS or not isinstance(v, dict) or not set(v) <= {"de", "a", "note"}:
                errs.append(f"{c} : en_ligne.{k} invalide (documents : {', '.join(DOCUMENTS)} ; {{de, a, note}})")
        if s.get("verifie_le"):
            try:
                date.fromisoformat(s["verifie_le"])
            except ValueError:
                errs.append(f"{c} : verifie_le {s['verifie_le']!r} n'est pas une date ISO")
    return errs


def by_code(code: str) -> dict | None:
    c = (code or "").strip().lower()
    return next((s for s in services() if s["code"].lower() == c), None)


def departemental(dep: str) -> dict | None:
    return next((s for s in services() if s.get("type") == "departementales" and s.get("departement") == dep), None)


def staleness(s: dict, today: date | None = None) -> str:
    today = today or date.today()
    if not s.get("verifie_le"):
        return f"{s['code']} : entrée jamais vérifiée, à contrôler sur le site du service."
    age = (today - date.fromisoformat(s["verifie_le"])).days
    if age > STALE_DAYS:
        return f"{s['code']} : entrée vérifiée le {s['verifie_le']} (plus de 12 mois), informations à revérifier."
    return ""


def online(s: dict | None, document: str, annee: int | None) -> bool | None:
    """Document de cette année en ligne chez ce service ? None = inconnu (référentiel muet)."""
    if not s or annee is None:
        return None
    rng = (s.get("en_ligne") or {}).get(document)
    if not rng:
        return None
    lo, hi = rng.get("de"), rng.get("a")
    return (lo is None or annee >= lo) and (hi is None or annee <= hi)


def view(s: dict, document: str = "", annee: int | None = None) -> dict:
    out = {k: v for k, v in s.items() if v not in ("", None, {}, [])}
    out["lien"] = s.get("visionneuse") or s.get("site") or (
        f"https://francearchives.gouv.fr/fr/search?q={s['nom'].replace(' ', '+')}")
    if document:
        out["en_ligne_pour_la_demande"] = online(s, document, annee)
    if w := staleness(s):
        out["avertissement"] = w
    return out


def service(lieu: str = "", departement: str = "", code: str = "", document: str = "",
            annee: int | None = None) -> dict:
    """Service d'archives d'un lieu, d'un département ou d'un code (AD59, SHD, ANOM…)."""
    if code:
        s = by_code(code)
        if not s:
            return {"erreur": f"Service inconnu : {code!r}", "codes": [x["code"] for x in services()]}
        return view(s, document, annee)
    dep = departement.strip().upper().zfill(2) if departement and departement.strip().isdigit() else \
        departement.strip().upper()
    if lieu and not dep:
        dep = normalize_place(lieu).get("departement_code") or ""
    if not dep:
        return {"erreur": "Préciser un lieu avec son département, un numéro de département ou un code de service."}
    s = departemental(dep)
    if s:
        return view(s, document, annee)
    nom = DEPARTEMENTS.get(dep, dep)
    return {"code": f"AD{dep}", "nom": f"Archives départementales — {nom} ({dep})", "type": "departementales",
            "departement": dep, **({"en_ligne_pour_la_demande": None} if document else {}),
            "lien": f"https://francearchives.gouv.fr/fr/search?q=archives+d%C3%A9partementales+{nom.replace(' ', '+')}",
            "avertissement": f"AD{dep} absentes du référentiel : site et mise en ligne inconnus (docs/archives.md "
                             "pour contribuer)."}


COURRIER = """Objet : demande de copie {acte}

Madame, Monsieur,

Dans le cadre de recherches généalogiques, je vous serais reconnaissant(e) de bien vouloir m'adresser une copie
intégrale (ou à défaut un extrait avec filiation) de l'acte {acte} de {personne}, {evenement} à {lieu}{date}.

Cet acte est communicable ({regle}). Je joins une enveloppe timbrée pour la réponse.

Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations distinguées.
"""

ACTES = {"naissance": ("de naissance", "né(e)"), "mariage": ("de mariage", "marié(e)"),
         "deces": ("de décès", "décédé(e)")}


def request_letter(document: str, regle: str, personne: str = "", lieu: str = "", date_acte: str = "") -> str:
    acte, ev = ACTES.get(document, (f"({document})", "concerné(e)"))
    return COURRIER.format(acte=acte, personne=personne or "[prénom NOM]", evenement=ev, lieu=lieu or "[commune]",
                           date=f" le {date_acte}" if date_acte else " [date]", regle=regle)


def _year(v: str) -> int | None:
    from .normalize.dates import parse_date
    g = parse_date(v) if v else None
    return g.to_dict()["annee_min"] if g else None


ETAT_CIVIL = ("naissance", "mariage", "deces")


def communicability_online(document: str, date_document: str = "", date_naissance: str = "", date_deces: str = "",
                           lieu: str = "", personne: str = "") -> dict:
    """Communicabilité (Code du patrimoine) puis, si un lieu est donné, mise en ligne chez le service réel."""
    from .fr_sources import communicability
    res = communicability(document, date_document, date_naissance, date_deces)
    if not lieu or "erreur" in res:
        return res
    key = document.lower().replace("é", "e").replace("è", "e").replace(" ", "_")
    svc = service(lieu=lieu, document=key, annee=_year(date_document))
    res["service_archives"] = svc
    res["en_ligne"] = svc.get("en_ligne_pour_la_demande")
    if res.get("communicable") and res["en_ligne"] is not True:
        conseil = ("Communicable mais " + ("pas en ligne" if res["en_ligne"] is False else
                                            "mise en ligne inconnue pour cette année (référentiel muet)") + " : "
                   f"vérifier la visionneuse ({svc.get('lien', '')}), sinon demander une copie.")
        if key in ETAT_CIVIL:
            conseil += (" En règle générale, les registres de l'état civil de moins de 100 ans environ sont encore en "
                        "mairie (collection communale) ; les plus anciens sont aux AD (collection du greffe). La "
                        "demande peut aussi passer par le formulaire de demande à distance des AD, s'il existe.")
        res["si_pas_en_ligne"] = {
            "conseil": conseil,
            "courrier": request_letter(key, res.get("regle", ""), personne, normalize_place(lieu).get("commune")
                                       or lieu, date_document)}
    elif res.get("communicable") is False:
        res["si_non_communicable"] = ("Pas encore communicable de plein droit : demande de dérogation possible auprès "
                                      "du service (art. L213-3 du Code du patrimoine). Pour l'état civil, la copie "
                                      "intégrale reste délivrée par la mairie aux personnes habilitées (intéressé, "
                                      "ascendants, descendants, conjoint), en règle générale.")
    return res
