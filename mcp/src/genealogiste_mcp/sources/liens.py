"""Sources secondaires sans API ouverte : URL de recherche à ouvrir dans le navigateur de l'utilisateur.

Lecture seule. L'utilisateur colle ensuite le résultat (tool source_collee) pour qu'il soit tracé et exploité.
"""

from __future__ import annotations

from urllib.parse import urlencode

from .. import archives, sites_tiers
from ..fr_sources import SERIES, next_source_hint
from ..normalize.dates import parse_date
from ..normalize.places import DEPARTEMENTS, normalize_place


def _year(v: str) -> int | None:
    g = parse_date(v) if v else None
    return g.to_dict()["annee_min"] if g else None


def search_links(nom: str, prenom: str = "", ne_vers: str = "", lieu: str = "", decede_vers: str = "") -> dict:
    y = _year(ne_vers)
    dy = _year(decede_vers)
    place = normalize_place(lieu) if lieu else {}
    commune = place.get("commune", "")
    dep_code = place.get("departement_code") or ""
    dep = place.get("departement") or ""
    links = []

    def add(site, url, couverture, connexion=False, note=""):
        links.append({"site": site, "url": url, "couverture": couverture, "connexion_requise": connexion,
                      **({"note": note} if note else {})})

    gq = {"go": "1", "nom": nom, "prenom": prenom}
    if commune:
        gq["place__0__"] = commune
    add("Geneanet (arbres et relevés)", "https://www.geneanet.org/fonds/individus/?" + urlencode(gq),
        "arbres en ligne (composite) et relevés d'associations (dérivés)", True,
        "Arbres = pistes ; remonter à l'acte original." + (f" Filtrer la période {y - 5}-{y + 5} dans le formulaire." if y else ""))
    add("FranceArchives (portail national des archives)",
        "https://francearchives.gouv.fr/fr/search?" + urlencode({"q": f"{prenom} {nom} {commune}".strip()}),
        "inventaires des services d'archives, index nominatifs")
    if y is None or y >= 1870 or (dy and dy >= 1914):
        add("Mémoire des hommes (SGA)", "https://www.memoiredeshommes.sga.defense.gouv.fr/",
            "morts pour la France (14-18, 39-45, Indochine, AFN), JMO, sépultures de guerre",
            note=f"Rechercher « {nom} {prenom} » dans la base « Morts pour la France » adaptée au conflit.")
    add("Grand Mémorial (ministère de la Culture)",
        "https://www.culture.gouv.fr/rechercher-une-publication-du-ministere-de-la-culture/bases-de-donnees/grand-memorial",
        "registres matricules indexés (soldats de 14-18) des AD participantes",
        note="Recherche par nom, prénom, année et lieu de naissance.")
    if dep_code:
        svc = archives.departemental(dep_code)
        if svc and (svc.get("visionneuse") or svc.get("site")):
            add(svc["nom"], svc.get("visionneuse") or svc["site"],
                "état civil, registres paroissiaux, matricules, recensements numérisés",
                note=" ".join(x for x in (svc.get("notes", ""), archives.staleness(svc)) if x))
        else:
            add(f"Archives départementales — {dep} ({dep_code})",
                "https://francearchives.gouv.fr/fr/search?" + urlencode({"q": f"archives départementales {dep}"}),
                "état civil, registres paroissiaux, matricules, recensements numérisés",
                note="Le site des AD est accessible depuis la fiche du service sur FranceArchives.")
    add("Retronews (presse)", "https://www.retronews.fr/",
        "presse ancienne (complète Gallica)", True, note=f'Rechercher « "{prenom} {nom}" ».')
    if dy and dy >= 1970:
        add("matchID (décès INSEE)", "https://deces.matchid.io/search?" + urlencode({"q": f"{prenom} {nom}"}),
            "décès depuis 1970 — interrogeable directement par l'outil matchid_recherche")
    tiers = sites_tiers_du_lieu(dep_code, y, dy, nom, prenom)
    return {
        "personne": f"{prenom} {nom}".strip(), "liens": links,
        **({"sites_tiers": tiers, "sites_tiers_avertissement": sites_tiers.AVERTISSEMENT} if tiers else {}),
        "consigne": ("Ouvrir les liens dans le navigateur (session personnelle de l'utilisateur), "
                     "puis coller le résultat avec l'outil source_collee pour le tracer au journal. "
                     "Ne jamais contourner une authentification ni extraire en masse (CGU)."),
    }


def sites_tiers_du_lieu(dep_code: str, annee_min: int | None = None, annee_max: int | None = None,
                        nom: str = "", prenom: str = "") -> list[dict]:
    """Sites tiers utiles pour un département (#181) : cercles et relevés dont la zone le couvre, puis réseaux
    nationaux de relevés. Les bases thématiques passent par sources_catalogue (theme=...)."""
    if not dep_code:
        return []
    fin = annee_max if annee_max is not None else (annee_min + 100 if annee_min is not None else None)
    locaux = [s for s in sites_tiers.filtrer(dep_code, annee_min=annee_min, annee_max=fin, nationaux=False)
              if s["type"] in ("cercle_departemental", "releves_benevoles", "arbre_collaboratif")]
    nationaux = [s for s in sites_tiers.filtrer(type="releves_benevoles") if "FR" in s["zone"]]
    return [sites_tiers.lien(s, nom, prenom) for s in locaux + nationaux]


DOCS = {"BIRT": "naissance", "CHR": "naissance", "BAPM": "naissance", "MARR": "mariage", "DEAT": "deces",
        "BURI": "deces", "CENS": "recensement"}


def cote_suggestions(fait: str, date: str = "", lieu: str = "") -> dict:
    place = normalize_place(lieu) if lieu else {}
    dep_code = place.get("departement_code")
    svc = archives.service(departement=dep_code, document=DOCS.get(fait.upper(), ""),
                           annee=_year(date)) if dep_code in DEPARTEMENTS else None
    return {
        "fait": fait,
        "lieu": place.get("commune") or lieu,
        "service": (svc["nom"] if svc else "Archives départementales du lieu (département à préciser)"),
        "service_archives": svc,
        "sources": next_source_hint(fait.upper(), date, lieu),
        "series": SERIES,
        **({"sites_tiers": tiers} if (tiers := sites_tiers_du_lieu(dep_code or "", _year(date))) else {}),
        "avertissement": "Cotes typiques du cadre de classement : vérifier dans l'inventaire du service.",
    }
