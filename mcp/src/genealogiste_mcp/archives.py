"""Référentiel des services d'archives publiques françaises (referentiels/archives_fr.json).

Chaque entrée : code, nom, type, département, site, visionneuse, NAAN ARK, mise en ligne par type de document
(``{"naissance": {"de": 1792, "a": 1922}}`` ; absent = inconnu), inscription, demande à distance, date de
vérification, et ``visionneuse_acces`` (famille de visionneuse : iiif_natif, editeur_ad, visionneuse_maison,
images_statiques, authentifie ; éditeur, logiciel et version si exposée, IIIF oui/non, protection anti-robot (acces_archives.PROTECTIONS) et son relevé, date de relevé). Les
sources et relevés sont documentés ; un relevé automatisé ne remplace pas la validation humaine
(docs/archives.md et docs/couvertures-archives.md).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from . import acces_archives, ark, capacites_archives, couverture_archives
from .normalize.pays import pays_du_lieu
from .normalize.places import DEPARTEMENTS, normalize_place
from .types_documents import DOCUMENTS, normaliser

PATH = Path(__file__).parent / "referentiels" / "archives_fr.json"
RECETTES = Path(__file__).parent / "referentiels" / "recettes_archives.json"  # make test-archives (#143)
RESULTATS_RECETTE = ("ok", "echec", "protection")
STALE_DAYS = 365
TYPES = ("departementales", "communales", "nationales", "militaires", "notariales", "diocesaines", "autre")

FAMILLES_VISIONNEUSE = acces_archives.FAMILLES


@lru_cache(maxsize=1)
def services() -> tuple[dict, ...]:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    out = tuple(data["services"])
    for s in out:  # table NAAN de ark.py complétée par le référentiel (sans écraser les entrées vérifiées)
        if s.get("ark_naan") and s["ark_naan"] not in ark.NAANS:
            ark.NAANS[s["ark_naan"]] = {"code": s["code"], "nom": s["nom"],
                                        "hote": s.get("visionneuse") or s.get("site", "")}
    return out


def intervalles() -> dict[str, float]:
    """Intervalle minimal entre deux requêtes (secondes) déclaré par service (``intervalle_requetes``), par hôte
    du site et de la visionneuse ; prioritaire sur la valeur par défaut, pas sur GENEALOGISTE_DEBITS."""
    out: dict[str, float] = {}
    for s in services():
        v = s.get("intervalle_requetes")
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            continue
        for url in (s.get("site"), s.get("visionneuse")):
            hote = urlsplit(url or "").hostname
            if hote:
                out[hote.lower()] = float(v)
    return out


@lru_cache(maxsize=1)
def hotes() -> frozenset[str]:
    """Hôtes (site et visionneuse) des services d'archives du référentiel : soumis au plafond journalier de
    requêtes (GENEALOGISTE_PLAFOND_JOUR_ARCHIVES, #157), sous-domaines compris. Les services de type « autre »
    (index et bibliothèques : matchID, Gallica, RetroNews, FranceArchives) n'en font pas partie."""
    out = set()
    for s in services():
        if s.get("type") == "autre":
            continue
        for url in (s.get("site"), s.get("visionneuse")):
            hote = urlsplit(url or "").hostname
            if hote:
                out.add(hote.lower())
    return frozenset(out)


def services_recette() -> list[dict]:
    """Services dotés d'un adaptateur et d'une ressource de référence pour la recette réelle (#143)."""
    return [s for s in services() if s.get("recette")]


def recettes() -> dict:
    try:
        data = json.loads(RECETTES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def recette(code: str) -> dict | None:
    return recettes().get(code)


def enregistrer_recette(code: str, resultat: str, detail: str = "", jour: date | None = None,
                       environnement: str = "", revision: str = "", reference: dict | None = None) -> dict:
    """Inscrit le dernier essai de recette réelle d'un service (ok, echec ou protection)."""
    from .fichiers import ecrire_atomique

    if resultat not in RESULTATS_RECETTE:
        raise ValueError(f"résultat de recette inconnu : {resultat!r}")
    if environnement not in ("", "vps", "local", "ci", "inconnu"):
        raise ValueError("environnement de recette : vps, local, ci ou inconnu")
    data = recettes()
    jour_iso = (jour or date.today()).isoformat()
    entree = {"dernier_essai": jour_iso, "resultat": resultat, "detail": detail[:300]}
    precedente = data.get(code) or {}
    reussite = jour_iso if resultat == "ok" else precedente.get("derniere_reussite")
    if reussite:
        entree["derniere_reussite"] = reussite
    mesures = dict(precedente.get("mesures") or {})
    if environnement:
        mesures[environnement] = {"verdict": {"ok": "oui", "protection": "defi", "echec": "echec"}[resultat],
                                  "date_mesure": datetime.now(UTC).isoformat(timespec="seconds"),
                                  "detail": detail[:300]}
    if environnement and reference:
        mesures[environnement].update(revision=revision, reference=dict(reference))
    if mesures:
        entree["mesures"] = mesures
    data[code] = entree
    ecrire_atomique(RECETTES, json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=2) + "\n")
    return entree


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
        legacy = s.get('en_ligne') or {}
        if not isinstance(legacy, dict):
            errs.append(f"{c} : en_ligne doit être un objet")
            legacy = {}
        for k, v in legacy.items():
            if k not in DOCUMENTS or not couverture_archives.valid_legacy(v):
                errs.append(f"{c} : en_ligne.{k} invalide (document ou bornes historiques)")
        if "couvertures" in s:
            errs.extend(f"{c} : {error}" for error in couverture_archives.validate(s['couvertures'], DOCUMENTS))
        resolution = s.get("resolution_image")
        if resolution is not None:
            if not isinstance(resolution, dict) or resolution.get("type") not in {"visualizer_api"}:
                errs.append(f"{c} : résolution d'image inconnue ou mal formée")
            elif resolution.get("iiif") not in (True, False, None):
                errs.append(f"{c} : état IIIF invalide")
        if "recherche_registres" in s:  # formulaire Mnesys par commune et année (#128)
            rr = s["recherche_registres"]
            formulaires = rr.get("formulaires") if isinstance(rr, dict) else None
            uuid = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
            types_form = {"etat_civil", "tables_decennales", "matricules", "successions", "recensements"}
            if (not isinstance(formulaires, dict) or not formulaires or set(formulaires) - types_form
                    or not all(isinstance(v, str) and uuid.fullmatch(v) for v in formulaires.values())):
                errs.append(f"{c} : recherche_registres.formulaires = {{etat_civil?, tables_decennales?, matricules?, "
                            "successions?, recensements?}} en UUID, au moins un")
            releves = rr.get("releves", {}) if isinstance(rr, dict) else {}  # date de relevé propre à un formulaire
            if (not isinstance(releves, dict) or not isinstance(formulaires, dict) or set(releves) - set(formulaires)
                    or not all(isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in releves.values())):
                errs.append(f"{c} : recherche_registres.releves = {{formulaire déclaré: date ISO}}")
            champs_annee = rr.get("champs_annee", {}) if isinstance(rr, dict) else {}
            if (not isinstance(champs_annee, dict) or not isinstance(formulaires, dict)
                    or set(champs_annee) - set(formulaires)
                    or not all(isinstance(v, str) and re.fullmatch(r"\d+-[A-Za-z]+", v)
                               for v in champs_annee.values())):
                errs.append(f"{c} : recherche_registres.champs_annee = {{formulaire déclaré: nom de champ}}")
            if not s.get("ark_naan") or not (s.get("site") or "").startswith("https://"):
                errs.append(f"{c} : recherche_registres exige site https et ark_naan")
            try:
                date.fromisoformat(rr.get("releve_le", "") if isinstance(rr, dict) else "")
            except ValueError:
                errs.append(f"{c} : recherche_registres.releve_le doit être une date ISO")
            if not isinstance(rr, dict) or urlsplit(rr.get("reference", "")).hostname != urlsplit(
                    s.get("site", "")).hostname:
                errs.append(f"{c} : recherche_registres.reference doit pointer vers le site du service")
        if "visionneuse_acces" in s:
            errs.extend(f"{c} : visionneuse_acces.{e}" for e in acces_archives.valider(s["visionneuse_acces"]))
        if "intervalle_requetes" in s and (not isinstance(s["intervalle_requetes"], (int, float))
                                           or isinstance(s["intervalle_requetes"], bool)
                                           or s["intervalle_requetes"] <= 0):
            errs.append(f"{c} : intervalle_requetes doit être un nombre de secondes positif")
        if "recette" in s:
            r = s["recette"]
            if not isinstance(r, dict) or not isinstance(r.get("source"), str) or not r.get("source") \
                    or not isinstance(r.get("page", 0), int):
                errs.append(f"{c} : recette = {{source: ARK ou URL de registre, page: entier}} attendu")
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
        if s.get("origine", "").startswith("import"):
            return (f"{s['code']} : entrée importée automatiquement (site et NAAN), jamais vérifiée par une "
                    "personne ; contrôler les informations et la couverture sur le site du service.")
        return f"{s['code']} : entrée jamais vérifiée, à contrôler sur le site du service."
    age = (today - date.fromisoformat(s["verifie_le"])).days
    if age > STALE_DAYS:
        return f"{s['code']} : entrée vérifiée le {s['verifie_le']} (plus de 12 mois), informations à revérifier."
    return ""


def online(s: dict | None, document: str, annee: int | None, lieu: str = "",
           today: date | None = None) -> bool | None:
    """Disponibilité déclarée du fonds ; hors périmètre ou lacune = inconnu, jamais preuve d'un acte."""
    return couverture_archives.evaluate(s, normaliser(document), annee, lieu, today)['en_ligne']


def view(s: dict, document: str = "", annee: int | None = None, lieu: str = "") -> dict:
    document = normaliser(document)
    out = {k: v for k, v in s.items() if v not in ("", None, {}, [])}
    acces = acces_archives.selectionner(s, document)
    out["visionneuse_pour_la_demande"] = acces
    resolution = s.get("resolution_image") or {}
    gallica = s.get("ark_naan") == "12148"
    adaptateur = resolution.get("type") == "visualizer_api" or gallica
    out["telechargement"] = {"type": "iiif_gallica" if gallica else resolution.get("type"),
                             "iiif": True if gallica else resolution.get("iiif"),
                             "adaptateur_disponible": adaptateur,
                             "etat": ("automatique" if s.get("recette") else "automatique_non_eprouve") if adaptateur
                             else "lien_iiif_ou_fichier_a_fournir"}
    if adaptateur and not s.get("recette"):
        out["telechargement"]["note"] = ("Adaptateur générique de l'éditeur ; aucun registre de ce service n'a encore "
                                         "passé de recette réelle : vérifier la première vue, repli lien IIIF ou "
                                         "fichier téléchargé.")
    out["lien"] = s.get("visionneuse") or s.get("site") or (
        f"https://francearchives.gouv.fr/fr/search?q={s['nom'].replace(' ', '+')}")
    if document:
        coverage = couverture_archives.evaluate(s, document, annee, lieu)
        out["en_ligne_pour_la_demande"] = coverage['en_ligne']
        out["couverture_pour_la_demande"] = coverage
        if coverage.get('etat') == 'autre_service':
            links = {r['lien'] for r in coverage['regles'] if r.get('lien')}
            if len(links) == 1:
                out['lien'] = links.pop()
    if s.get("recette"):
        out["recette"] = recette(s["code"]) or {"resultat": None, "detail": "aucune recette réelle enregistrée"}
    out["acces_vps"] = ((recette(s["code"]) or {}).get("mesures") or {}).get("vps") or {
        "verdict": "inconnu", "detail": "Aucune mesure identifiée depuis le VPS ; une réussite locale ne suffit pas."}
    out["couverture_technique"] = capacites_archives.couverture(s, recette(s["code"]) or {}, document)
    if manuel := acces_archives.consultation_manuelle(s, document):
        out["consultation_manuelle"] = manuel
    if acces_archives.ecarte_adaptateur_service(s, document):
        out["telechargement"]["etat"] = "a_qualifier_pour_ce_type"
        out["telechargement"]["applicable_au_type"] = None
        out["telechargement"]["note"] = ("L'accès propre à ce type diffère de l'accès général (ou est invalide) : "
                                         "l'adaptateur et la recette du service ne s'appliquent pas à ce fonds.")
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
        return view(s, document, annee, lieu)
    dep = departement.strip().upper().zfill(2) if departement and departement.strip().isdigit() else \
        departement.strip().upper()
    pays = None
    if lieu and not dep:
        pays = pays_du_lieu(lieu)
        if pays["france"] is False:  # #283 : aucun service d'AD français pour un lieu hors de France
            from .fr_sources import PISTE_TRANSCRIPTION, RENVOI_INTERNATIONAL
            return {"pays": pays, "service": None,
                    "message": f"Lieu hors de France ({pays['nom'] or 'pays étranger'}, {pays['detail']}) : aucun "
                               "service d'archives départementales français.",
                    "renvoi": RENVOI_INTERNATIONAL, "piste_francaise": PISTE_TRANSCRIPTION}
        dep = normalize_place(lieu).get("departement_code") or ""
    if not dep:
        return {"erreur": "Préciser un lieu avec son département, un numéro de département ou un code de service.",
                **({"pays": pays} if pays else {})}
    s = departemental(dep)
    if s:
        return view(s, document, annee, lieu)
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
    if not g:
        return None
    bounds = g.to_dict()
    return bounds['annee_min'] if bounds['annee_min'] == bounds['annee_max'] else None


ETAT_CIVIL = ("naissance", "mariage", "deces")


def communicability_online(document: str, date_document: str = "", date_naissance: str = "", date_deces: str = "",
                           lieu: str = "", personne: str = "") -> dict:
    """Communicabilité (Code du patrimoine) puis, si un lieu est donné, mise en ligne chez le service réel."""
    from .fr_sources import communicability
    res = communicability(document, date_document, date_naissance, date_deces)
    if not lieu or "erreur" in res:
        return res
    key = normaliser(document)
    pays = pays_du_lieu(lieu)
    res["pays"] = pays
    if pays["france"] is False:  # #283 : délais français et service d'AD hors de propos pour l'acte local
        from .fr_sources import PISTE_TRANSCRIPTION
        res["communicable_si_transcrit_en_france"] = res.get("communicable")
        res["communicable"] = None
        res["hors_france"] = (f"Lieu hors de France ({pays['nom'] or 'pays étranger'}) : les délais du Code du "
                              "patrimoine valent pour les archives publiques françaises, pas pour l'acte local, dont "
                              "le régime est à vérifier auprès du service du pays. " + PISTE_TRANSCRIPTION)
        return res
    svc = service(lieu=lieu, document=key, annee=_year(date_document))
    res["service_archives"] = svc
    res["en_ligne"] = svc.get("en_ligne_pour_la_demande")
    if res.get("communicable") and res["en_ligne"] is not True:
        conseil = ("Communicable mais " + ("pas en ligne" if res["en_ligne"] is False else
                                            "mise en ligne inconnue pour cette demande") + " : "
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
