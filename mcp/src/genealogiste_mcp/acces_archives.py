"""Accès documentaires par type, sans qualification implicite d'adaptateur."""
from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit

from .types_documents import DOCUMENTS, normaliser

FAMILLES = ("iiif_natif", "editeur_ad", "visionneuse_maison", "images_statiques", "authentifie")
# Protections anti-robot relevées sur un service (#196) ; null = aucune protection relevée.
PROTECTIONS = ("anubis", "cloudflare", "cloudflare_hcaptcha", "hcaptcha", "recaptcha", "datadome", "attente",
               "redirection_js")  # redirection_js : page de redirection JavaScript avant contenu (sonde #128)


def _url_valide(reference) -> bool:
    try:
        url = urlsplit(reference if isinstance(reference, str) else "")
        return bool(url.scheme in ("http", "https") and url.hostname and not url.username and not url.password)
    except ValueError:
        return False


def _date_valide(valeur) -> bool:
    try:
        date.fromisoformat(valeur)
    except (TypeError, ValueError):
        return False
    return True


def erreurs_acces(acces, *, specifique=False) -> list[str]:
    if not isinstance(acces, dict):
        return ["objet attendu"]
    erreurs = []
    if acces.get("famille") not in FAMILLES:
        erreurs.append("famille inconnue")
    if acces.get("iiif") is not None and not isinstance(acces["iiif"], bool):
        erreurs.append("iiif doit être un booléen ou null")
    for champ in ("editeur", "logiciel", "version", "protection", "reference_logiciel", "protection_note"):
        if champ in acces and acces[champ] is not None and not isinstance(acces[champ], str):
            erreurs.append(f"{champ} doit être une chaîne ou null")
    if isinstance(acces.get("protection"), str) and acces["protection"] not in PROTECTIONS:
        erreurs.append(f"protection inconnue (valeurs : {', '.join(PROTECTIONS)})")
    if "protection_releve_le" in acces and not _date_valide(acces["protection_releve_le"]):
        erreurs.append("protection_releve_le doit être une date ISO")
    if "protection_reference" in acces and not _url_valide(acces["protection_reference"]):
        erreurs.append("protection_reference HTTP(S) sans identifiants requise")
    if specifique:
        if not _url_valide(acces.get("reference")):
            erreurs.append("reference HTTP(S) sans identifiants requise")
        if not _date_valide(acces.get("releve_le", "")):
            erreurs.append("releve_le doit être une date ISO")
        if "par_type" in acces:
            erreurs.append("par_type imbriqué interdit")
    return erreurs


def valider(acces) -> list[str]:
    if not isinstance(acces, dict):
        return ["objet attendu"]
    erreurs = []
    # Un objet contenant seulement par_type n'annonce aucun accès générique.
    if set(acces) != {"par_type"}:
        erreurs.extend(erreurs_acces(acces))
    if "par_type" in acces:
        types = acces["par_type"]
        if not isinstance(types, dict) or not types:
            erreurs.append("par_type doit être un dictionnaire non vide")
        else:
            for document, valeur in types.items():
                if document not in DOCUMENTS:
                    erreurs.append(f"par_type.{document} : clé canonique de document attendue")
                erreurs.extend(f"par_type.{document} : {e}" for e in erreurs_acces(valeur, specifique=True))
    return erreurs


def consultation_manuelle(service: dict, document: str = "") -> dict | None:
    """Service à protection anti-robot relevée : consultation manuelle conseillée, sans interdire un réessai."""
    choisi = selectionner(service, document).get("acces") or {}
    generique = service.get("visionneuse_acces") if isinstance(service.get("visionneuse_acces"), dict) else {}
    source = choisi if "protection" in choisi else generique
    protection = source.get("protection")
    if not isinstance(protection, str) or not protection:
        return None
    out = {"protection": protection,
           "releve_le": source.get("protection_releve_le") or source.get("releve_le"),
           "reference": source.get("protection_reference") or source.get("reference"),
           "consigne": ("Consultation manuelle : l'utilisateur ouvre la vue dans son navigateur et fournit une capture "
                        "ou l'image téléchargée ; l'enregistrer avec media_enregistrer(chemin, nom, classer=true), "
                        "puis tracer le relevé avec source_collee. Aucun contournement du défi."),
           "reessai": ("Les outils réseau restent permis : une protection peut être levée. Un défi détecté met l'hôte "
                       "en pause (coupe-circuit, GENEALOGISTE_COUPE_CIRCUIT) ; cache_purger(\"coupe_circuit\") "
                       "permet un nouvel essai explicite.")}
    if source.get("protection_note"):
        out["note"] = source["protection_note"]
    return {k: v for k, v in out.items() if v}


def selectionner(service: dict, document: str = "") -> dict:
    document = normaliser(document)
    inconnu = {"document": document, "origine": "inconnu", "acces": None}
    acces = service.get("visionneuse_acces")
    if not isinstance(acces, dict):
        return inconnu
    types = acces.get("par_type", {})
    if document and not isinstance(types, dict):
        return {**inconnu, "erreurs": ["par_type invalide"]}
    if document and document in types:
        erreurs = erreurs_acces(types[document], specifique=True)
        if erreurs:
            return {**inconnu, "erreurs": erreurs}
        return {"document": document, "origine": "document", "acces": dict(types[document])}
    generique = {k: v for k, v in acces.items() if k != "par_type"}
    if erreurs_acces(generique):
        return inconnu
    return {"document": document, "origine": "service", "acces": generique}


def ecarte_adaptateur_service(service: dict, document: str = "") -> bool:
    """Vrai si l'accès propre au type empêche d'appliquer l'adaptateur et la recette du service.

    Un adaptateur est propre à un éditeur (#128) : un accès typé du même éditeur que l'accès général
    conserve l'adaptateur ; un éditeur différent, inconnu ou une entrée invalide l'écarte.
    """
    if not normaliser(document):
        return False
    choisi = selectionner(service, document)
    if choisi.get("erreurs"):
        return True
    if choisi["origine"] != "document":
        return False
    acces = service.get("visionneuse_acces") or {}
    generique = {k: v for k, v in acces.items() if k != "par_type"}
    if not generique or erreurs_acces(generique):
        return True
    specifique = choisi["acces"]
    return (not generique.get("editeur") or specifique.get("famille") != generique.get("famille")
            or specifique.get("editeur") != generique.get("editeur"))
