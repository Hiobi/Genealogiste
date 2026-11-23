"""Géographie historique d'un lieu à une date (#287) : outil ``lieu_historique``.

Niveau par niveau, chaque valeur porte sa ``source`` et sa ``periode_de_validite`` ; rien n'est déduit, ni par le
code ni par le modèle. Périmètre fixé par l'étude #322 (docs/etudes/lieux-1790-1943.md) :

- commune (nom, département, rattachement de commune déléguée ou associée, existence) **depuis 1943** : COG INSEE,
  par ``sources.geo`` (``history`` puis ``IndexCog.chronologie``), sans logique dupliquée ;
- population **depuis 1968** : INSEE Melodi, jeu ``DS_POPULATIONS_HISTORIQUES`` (année de l'observation, mesure,
  géographie de diffusion lue dans le catalogue du jeu) ;
- cartes anciennes : couches WMTS de la Géoplateforme choisies selon la date (période lue dans le titre de la
  couche, sinon dans sa fiche de métadonnées CSW) ; liens de tuile centrés sur le lieu, aucune image téléchargée ;
- tout le reste (noms et fusions avant 1943 ; canton, arrondissement, district ; province, généralité, bailliage,
  diocèse ; population avant 1968) : « inconnu », « à établir », avec un lien de consultation (fiche Cassini/EHESS
  par l'identifiant Wikidata P8422, dépôt Nakala de la base Cassini).

Lieu hors de France : hors périmètre, sans requête. Pays inconnu ou homonymie : demande de précision (département
ou code INSEE), sans choisir. Seul le code INSEE part vers les services de contexte (aucune donnée de personne).
Avant toute requête vers un service du référentiel : ``services.refus`` et ``services.url_autorisee``.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from datetime import date as Date
from urllib.parse import urlencode

from ..normalize.dates import parse_date
from ..normalize.pays import pays_du_lieu, pays_resume
from ..normalize.places import normalize_place
from ..sources import geo
from ..sources.base import DAY, SourceContext, error_envelope
from . import services

INCONNU = "inconnu"
A_ETABLIR = "à établir"
COG_DEBUT = "1943-01-01"  # première date du fichier v_commune_depuis_1943 (étude #322)

MELODI = "https://api.insee.fr/melodi"
JEU_POPULATION = "DS_POPULATIONS_HISTORIQUES"
WMTS = "https://data.geopf.fr/wmts"
SPARQL = "https://query.wikidata.org/sparql"

# Couches retenues par l'étude #322 (identifiants revérifiés dans le GetCapabilities du 2026-11-23).
COUCHES = ("AN-IGNF_GEOGRAPHICALGRIDSYSTEMS.CASSINI", "BNF-IGNF_GEOGRAPHICALGRIDSYSTEMS.CASSINI",
           "GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR40", "GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR10",
           "GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN50.1950", "ORTHOIMAGERY.ORTHOPHOTOS.1950-1965")
NIVEAU_TUILE = "14"  # niveau de tuile préféré (sinon le plus fin disponible pour la couche)

# Liens de consultation (étude #322), à ouvrir par l'utilisateur : jamais interrogés par le plugin (d'où un
# dictionnaire, distinct des constantes de points d'accès relevées par test_politique_acces).
LIENS = {"fiche_cassini": "http://cassini.ehess.fr/cassini/fr/html/fiche.php?select_resultat={}",  # format P8422
         "nakala_cassini": "https://doi.org/10.34847/nkl.e0556oog",
         "nakala_districts": "https://doi.org/10.34847/nkl.54ff05lv"}

NS = {"w": "http://www.opengis.net/wmts/1.0", "ows": "http://www.opengis.net/ows/1.1",
      "xlink": "http://www.w3.org/1999/xlink", "gml": "http://www.opengis.net/gml/3.2"}
ANNEES = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b(?:\s*-\s*\b(1[5-9]\d\d|20\d\d)\b)?")
R_TERRE = 6378137.0  # sphère de la projection EPSG:3857
PIXEL = 0.00028  # taille de pixel normalisée du WMTS 1.0.0 (m)

AVERTISSEMENT = ("Géographie historique : chaque niveau porte sa source et sa période de validité ; un niveau sans "
                 "source vaut « inconnu » (à établir sur les sources indiquées). Aucun rattachement n'est déduit : "
                 "ne pas compléter un niveau « inconnu » de mémoire.")


# ---------------------------------------------------------------------------- outil

def lieu_historique(ctx: SourceContext, lieu: str, date: str) -> dict:
    """Géographie historique de ``lieu`` (libellé avec département, ou code INSEE) à ``date`` (GEDCOM ou texte)."""
    lieu, date = (lieu or "").strip(), (date or "").strip()
    if not lieu:
        return {"erreur": "lieu vide : donner la commune avec son département (« Billy-Montigny, Pas-de-Calais ») "
                          "ou son code INSEE"}
    g = parse_date(date)
    if g is None:
        return {"erreur": f"date illisible : {date!r} (ex. « 1906 », « 12 MAR 1906 », « vers 1750 »)"}
    gd = g.to_dict()
    quand = {"original": date, "texte": gd["texte"], "debut": gd["debut_gregorien"], "fin": gd["fin_gregorien"]}
    code = lieu.upper() if geo.INSEE.match(lieu.upper()) else ""
    pays = pays_du_lieu({"nom": "", "code_insee": code} if code else lieu)
    base = {"lieu": lieu, "date": quand, "pays": pays_resume(pays)}
    if pays["france"] is False:
        return {**base, "hors_perimetre": True, "requetes_emises": 0,
                "message": (f"Lieu hors de France ({pays['nom'] or pays['detail']}) : la géographie historique "
                            "française (COG, cantons, Ancien Régime) ne s'applique pas ; rien n'est extrapolé."),
                "consigne": "Chercher les découpages historiques auprès des sources du pays concerné."}
    if pays["france"] is None:
        return {**base, "pays_inconnu": True, "requetes_emises": 0,
                "message": f"Pays du lieu inconnu ({pays['detail']}) : aucune requête émise.",
                "consigne": "Préciser le département (« Billy-Montigny, Pas-de-Calais ») ou le code INSEE."}

    n = normalize_place(lieu) if not code else {}
    nom, dep = ("", "") if code else (n.get("commune") or "", n.get("departement_code") or "")
    hist = geo.history(ctx, nom=nom, code_insee=code, departement=dep)
    if "erreur" in hist:
        return {**base, "erreur": f"COG INSEE indisponible : {hist['erreur']}", "journal": hist.get("journal")}
    candidats = sorted({r["code_insee"]: r for r in hist["resultats"]}.values(), key=lambda r: r["code_insee"])
    if len(candidats) > 1:
        return {**base, "homonymie": True, "journal": hist.get("journal"),
                "candidats": [{"code_insee": r["code_insee"], "nom": r["libelle"],
                               "departement": geo.nom_departement(geo.code_departement(r["code_insee"]), r["fin"]),
                               "debut": r["debut"], "fin": r["fin"]} for r in candidats],
                "consigne": "Plusieurs communes répondent à ce nom : préciser le département ou le code INSEE ; "
                            "aucune n'est choisie."}
    rec = candidats[0] if candidats else None
    return _niveaux(ctx, base, quand, rec, hist)


def _niveaux(ctx: SourceContext, base: dict, quand: dict, rec: dict | None, hist: dict) -> dict:
    d0, d1 = quand["debut"], quand["fin"]
    requetes: dict[str, str] = {"cog": "positif" if rec else "negatif"}
    cassini = _cassini(ctx, rec["code_insee"], requetes) if rec else {}
    consultation = _consultation(cassini)
    niveaux: list[dict] = []
    centre = None
    if rec:
        code = rec["code_insee"]
        try:
            index = geo.IndexCog(geo.Cog(ctx).communes(), geo.Cog(ctx).mouvements())
            ch = index.chronologie(code)
            lignes = [x for c in ch["codes"] for x in index.lignes.get(c, [])]
        except Exception:  # noqa: BLE001 - lu juste avant par geo.history (cache) ; panne improbable
            ch, lignes = {"noms": [], "departements": [], "rattachements": []}, []
        source = _source_cog(ctx)
        niveaux += _niveaux_commune(ch, lignes, hist, code, d0, d1, source, consultation)
        niveaux.append({"niveau": "evenements_depuis_1943", "valeur": hist.get("mouvements", []), "source": source,
                        "periode_de_validite": {"debut": COG_DEBUT, "fin": None}})
        if rec.get("actuelle"):
            centre = _centre(ctx, code, requetes)
    else:
        niveaux.append(_inconnu("commune", "commune absente du COG INSEE depuis 1943 (disparue avant 1943, nom "
                                           "ancien ou mal orthographié) : aucune source structurée retenue (#322)",
                                consultation))
    for niveau, lien in (("canton", None), ("arrondissement", None), ("district", LIENS["nakala_districts"])):
        liens = consultation + ([{"titre": "Atlas de la Révolution française, les districts en 1790 (limites, "
                                           "sans code commune ; ODbL)", "url": lien}] if lien else [])
        niveaux.append(_inconnu(niveau, "rattachement non daté par le COG et sans source structurée retenue (#322) : "
                                        "le plugin ne l'établit pas", liens))
    for niveau in ("province", "generalite", "bailliage_ou_senechaussee", "diocese"):
        niveaux.append(_inconnu(niveau, "Ancien Régime : aucune source structurée ouverte par commune (#322) ; "
                                        "aucun rattachement déduit",
                                consultation + [{"titre": "Dictionnaire topographique du département (s'il est publié)",
                                                 "url": None}]))
    population = _population(ctx, rec["code_insee"], d0, d1, requetes, consultation) if rec else \
        _inconnu("population", "commune absente du COG : population non recherchée", consultation)
    cartes = _cartes(ctx, d0, d1, centre, requetes)
    sources = sum(1 for x in [*niveaux, population] if x["valeur"] != INCONNU)
    jid = ctx.journal.add(source="lieu_historique", operation="niveaux",
                          parametres={"lieu": base["lieu"], "date": quand["original"],
                                      "code_insee": rec["code_insee"] if rec else ""},
                          statut="positif" if sources else "negatif", nb_resultats=sources,
                          resume=f"{sources} niveau(x) sourcé(s), {len(cartes.get('retenues', []))} carte(s)",
                          references=[c["lien"] for c in cartes.get("retenues", []) if c.get("lien")][:10])
    return {**base, "commune": _resume_commune(rec, centre), "niveaux": niveaux, "population": population,
            "cartes": cartes, "consultation": consultation, "requetes": requetes, "journal": jid,
            "avertissement": AVERTISSEMENT}


def _resume_commune(rec: dict | None, centre: dict | None) -> dict | None:
    if not rec:
        return None
    out = {"code_insee": rec["code_insee"], "nom_cog": rec["libelle"], "actuelle": rec["actuelle"]}
    if centre:
        out["centre"] = centre
    return out


# ---------------------------------------------------------------------------- niveaux du COG

def _source_cog(ctx: SourceContext) -> dict:
    millesime = re.search(r"_(\d{4})\.csv$", ctx.config.cog_mvt_url or "")
    return {"service": "COG INSEE", "titre": "Code officiel géographique, communes depuis 1943 et mouvements",
            "url": [ctx.config.cog_communes_url, ctx.config.cog_mvt_url],
            "millesime": millesime.group(1) if millesime else "", "consulte_le": Date.today().isoformat()}


def _periode(debut: str | None, fin: str | None) -> dict:
    p = {"debut": debut, "fin": fin}
    if debut == COG_DEBUT:
        p["note"] = "début de la couverture du COG : valable au moins depuis 1943-01-01, antérieur inconnu"
    return p


def _niveau(niveau: str, valeur, source: dict, debut: str | None, fin: str | None, **extra) -> dict:
    return {"niveau": niveau, "valeur": valeur, "source": source, "periode_de_validite": _periode(debut, fin),
            **extra}


def _inconnu(niveau: str, motif: str, consultation: list[dict]) -> dict:
    return {"niveau": niveau, "valeur": INCONNU, "source": None, "periode_de_validite": None, "statut": A_ETABLIR,
            "motif": motif, "consultation": consultation}


def _a_la_date(niveau: str, periodes: list[dict], d0: str, d1: str, source: dict, consultation: list[dict]):
    """Valeur du COG sur l'intervalle [d0, d1] ; « inconnu » avant 1943 ; None si aucune période ne le couvre."""
    if d1 < COG_DEBUT:
        return _inconnu(niveau, "date antérieure au 1943-01-01 : hors du COG, aucune source structurée retenue "
                                "(#322)", consultation)
    if d0 < COG_DEBUT:
        return _inconnu(niveau, "intervalle de dates à cheval sur 1943-01-01 : préciser la date (avant 1943, "
                                "aucune source structurée retenue)", consultation)
    hits = [p for p in periodes if p["debut"] <= d1 and (p["fin"] is None or p["fin"] > d0)]
    if not hits:
        return None
    if len(hits) == 1:
        return _niveau(niveau, hits[0]["valeur"], source, hits[0]["debut"], hits[0]["fin"])
    return _niveau(niveau, "plusieurs valeurs sur l'intervalle", source, hits[0]["debut"], hits[-1]["fin"],
                   valeurs=[{"valeur": p["valeur"], "periode_de_validite": _periode(p["debut"], p["fin"])}
                            for p in hits])


def _niveaux_commune(ch: dict, lignes: list[dict], hist: dict, code: str, d0: str, d1: str, source: dict,
                     consultation: list[dict]) -> list[dict]:
    out = []
    noms = [{"valeur": x["nom"], "debut": x["debut"], "fin": x["fin"]} for x in ch["noms"]]
    fins = [x["DATE_FIN"] for x in lignes]
    fin_existence = max(fins) if fins and all(fins) else None  # dernière ligne « commune » close au COG
    supprimee = d0 >= COG_DEBUT and fin_existence is not None and d0 >= fin_existence
    if supprimee:  # plus de ligne « commune » au COG à cette date : les mouvements de cette date, rien de plus
        mvts = [m for m in hist.get("mouvements", []) if m["date"] == fin_existence
                and m["avant"].endswith(f"({code})")]
        out.append(_niveau("existence", "plus une commune de plein exercice au COG", source, fin_existence, None,
                           mouvements=mvts))
    else:
        nom = _a_la_date("nom", noms, d0, d1, source, consultation)
        out.append(nom or _inconnu("nom", "aucun nom du COG à cette date", consultation))
        deps = [{"valeur": f"{x['nom']} ({x['code']})", "debut": x["debut"], "fin": x["fin"]}
                for x in ch["departements"]]
        dep = _a_la_date("departement", deps, d0, d1, source, consultation)
        out.append(dep or _inconnu("departement", "aucun département du COG à cette date", consultation))
    ratt = [{"valeur": f"{x['statut']} de {x['nom']} ({x['code_insee']})", "debut": x["debut"], "fin": x["fin"]}
            for x in ch["rattachements"]]
    r = _a_la_date("rattachement_communal", ratt, d0, d1, source, consultation)
    if r is None:  # dans la couverture du COG, aucun rattachement enregistré sur l'intervalle
        r = _niveau("rattachement_communal", "aucun (commune non déléguée ni associée selon le COG)", source, d0, d1)
    out.append(r)
    if ch.get("absorbees"):
        out.append(_niveau("communes_absorbees", ch["absorbees"], source, COG_DEBUT, None))
    return out


def _centre(ctx: SourceContext, code: str, requetes: dict) -> dict | None:
    """Centre de la commune actuelle (API Géo, appel de sources.geo.commune)."""
    r = geo.commune(ctx, code_insee=code)
    if "erreur" in r or not r.get("resultats"):
        requetes["geo"] = "erreur" if "erreur" in r else "negatif"
        return None
    x = r["resultats"][0]
    requetes["geo"] = "positif"
    if x.get("latitude") is None or x.get("longitude") is None:
        return None
    return {"latitude": x["latitude"], "longitude": x["longitude"], "source": "API Géo (geo.api.gouv.fr), centre de "
                                                                             "la commune actuelle"}


# ---------------------------------------------------------------------------- consultation (Cassini, Nakala)

def _cassini(ctx: SourceContext, code: str, requetes: dict) -> dict:
    """Identifiant Cassini/EHESS (P8422) par l'index Wikidata (jamais source) ; {} si absent ou non interrogeable."""
    if refus := services.refus("WIKIDATA", ctx.config):
        requetes["wikidata"] = "non interrogé : " + refus["erreur"]
        return {}
    if not geo.INSEE.match(code) or not services.url_autorisee("WIKIDATA", SPARQL):
        return {}
    q = (f'SELECT ?item ?cassini WHERE {{ ?item wdt:P374 "{code}" ; wdt:P8422 ?cassini . }} LIMIT 5')
    params = {"code_insee": code, "proprietes": "P374, P8422"}
    try:
        data, cached = ctx.http.get(SPARQL, params={"query": q, "format": "json"},
                                    headers={"Accept": "application/sparql-results+json"}, ttl=90 * DAY,
                                    source="wikidata")
        lignes = [{k: v.get("value", "") for k, v in b.items()}
                  for b in (data.get("results") or {}).get("bindings", [])] if isinstance(data, dict) else []
    except Exception as exc:  # noqa: BLE001
        e = error_envelope(ctx, "wikidata", "identifiant_cassini", params, exc)
        requetes["wikidata"] = "erreur : " + e["erreur"]
        return {}
    trouves = [{"qid": x.get("item", "").rsplit("/", 1)[-1], "id": x["cassini"]} for x in lignes
               if re.fullmatch(r"\d{1,6}", x.get("cassini", ""))]
    ctx.journal.add("wikidata", "identifiant_cassini", params, "positif" if trouves else "negatif",
                    nb_resultats=len(trouves), cache=cached,
                    references=[f"https://www.wikidata.org/wiki/{t['qid']}" for t in trouves])
    requetes["wikidata"] = "positif" if trouves else "negatif"
    return {"ids": trouves}


def _consultation(cassini: dict) -> list[dict]:
    s = services.par_code("CASSINI-EHESS") or {}
    etat = f"site sans réponse aux relevés ({s.get('releve', 'non relevé')})"
    out = []
    for t in cassini.get("ids", []):
        out.append({"titre": "Fiche communale « Des villages de Cassini aux communes d'aujourd'hui » (EHESS)",
                    "url": LIENS["fiche_cassini"].format(t["id"]), "identifiant_cassini": t["id"],
                    "trouve_par": f"Wikidata (index, jamais source) {t['qid']}, propriété P8422", "note": etat})
    if not out:
        out.append({"titre": "Des villages de Cassini aux communes d'aujourd'hui (EHESS), rechercher la commune",
                    "url": s.get("site") or None, "note": etat})
    out.append({"titre": "Base Cassini redéposée sur Nakala (Bideau, Verdier), noms an III, 1801, 1999 et populations "
                         "an III-1999 ; CC BY-NC-SA 4.0, ni embarquée ni interrogée par le plugin",
                "url": LIENS["nakala_cassini"]})
    return out


# ---------------------------------------------------------------------------- population (Melodi)

def _population(ctx: SourceContext, code: str, d0: str, d1: str, requetes: dict, consultation: list[dict]) -> dict:
    if refus := services.refus("INSEE-MELODI", ctx.config):
        requetes["melodi"] = "non interrogé : " + refus["erreur"]
        return _inconnu("population", refus["erreur"], consultation)
    url_cat, url_data = f"{MELODI}/catalog/{JEU_POPULATION}", f"{MELODI}/data/{JEU_POPULATION}"
    if not (services.url_autorisee("INSEE-MELODI", url_cat) and services.url_autorisee("INSEE-MELODI", url_data)):
        return _inconnu("population", "point d'accès Melodi hors référentiel", consultation)
    params = {"jeu": JEU_POPULATION, "code_insee": code}
    try:
        cat, _ = ctx.http.get(url_cat, ttl=30 * DAY, source="melodi")
        geographie = str((cat or {}).get("spatialTemporal") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", geographie):
            raise ValueError("catalogue Melodi sans géographie de diffusion (spatialTemporal)")
        geo_code = f"{geographie[:4]}-COM-{code}"
        data, cached = ctx.http.get(url_data, params={"GEO": geo_code}, ttl=90 * DAY, source="melodi")
        obs = sorted(_observations(data, geo_code))
    except Exception as exc:  # noqa: BLE001
        e = error_envelope(ctx, "melodi", "population", params, exc)
        requetes["melodi"] = "erreur : " + e["erreur"]
        return _inconnu("population", f"INSEE Melodi : {e['erreur']}", consultation)
    titres = cat.get("title") if isinstance(cat.get("title"), list) else []
    titre = next((t.get("content", "") for t in titres if isinstance(t, dict) and t.get("lang") == "fr"), "")
    temporal = cat.get("temporal") or {}
    premiere = str(temporal.get("startPeriod") or "")[:4]
    ctx.journal.add("melodi", "population", params, "positif" if obs else "negatif", nb_resultats=len(obs),
                    cache=cached, references=[f"{url_data}?GEO={geo_code}"])
    requetes["melodi"] = "positif" if obs else "negatif"
    if not obs:
        return _inconnu("population", f"aucune observation Melodi pour {geo_code} (commune absente de la géographie "
                                      f"au {geographie})", consultation)
    y0, y1 = int(d0[:4]), int(d1[:4])
    avant = [o for o in obs if o[0] <= y1]
    if not avant:
        return _inconnu("population", f"date antérieure à la première année du jeu Melodi ({premiere or obs[0][0]}) : "
                                      "aucune source structurée retenue avant (#322)", consultation)
    annee, mesure, valeur = avant[-1]
    source = {"service": "INSEE-MELODI", "titre": titre, "jeu": JEU_POPULATION, "url": f"{url_data}?GEO={geo_code}",
              "geographie": f"géographie communale au {geographie} (catalogue du jeu)",
              "consulte_le": Date.today().isoformat()}
    out = {"niveau": "population", "valeur": valeur, "annee": annee, "mesure": mesure, "source": source,
           "periode_de_validite": {"debut": str(annee), "fin": str(annee),
                                   "note": "année de l'observation (TIME_PERIOD) ; aucune valeur interpolée"}}
    if annee < y0:
        out["ecart_annees"] = y0 - annee
    out["annees_disponibles"] = [o[0] for o in obs]
    return out


def _observations(data, geo_code: str) -> list[tuple[int, str, int]]:
    out = []
    for o in (data or {}).get("observations", []) if isinstance(data, dict) else []:
        dims, mes = o.get("dimensions") or {}, (o.get("measures") or {}).get("OBS_VALUE_NIVEAU") or {}
        an, v = str(dims.get("TIME_PERIOD", "")), mes.get("value")
        if dims.get("GEO") != geo_code or not re.fullmatch(r"\d{4}", an) or not isinstance(v, (int, float)):
            continue
        out.append((int(an), str(dims.get("POPREF_MEASURE", "")), int(v)))
    return out


# ---------------------------------------------------------------------------- cartes (Géoplateforme WMTS)

def _cartes(ctx: SourceContext, d0: str, d1: str, centre: dict | None, requetes: dict) -> dict:
    if refus := services.refus("IGN-GEOPLATEFORME", ctx.config):
        requetes["geoplateforme"] = "non interrogé : " + refus["erreur"]
        return {"retenues": [], "autres": [], "erreur": refus["erreur"]}
    params = {"service": "WMTS", "requete": "GetCapabilities"}
    try:
        texte, cached = ctx.http.get(WMTS, params={"SERVICE": "WMTS", "REQUEST": "GetCapabilities"},
                                     ttl=30 * DAY, source="geoplateforme", parse="text")
        caps = _capacites(texte)
    except Exception as exc:  # noqa: BLE001
        e = error_envelope(ctx, "geoplateforme", "capacites", params, exc)
        requetes["geoplateforme"] = "erreur : " + e["erreur"]
        return {"retenues": [], "autres": [], "erreur": f"Géoplateforme : {e['erreur']}"}
    y0, y1 = int(d0[:4]), int(d1[:4])
    couches = []
    for ident in COUCHES:
        c = caps["couches"].get(ident)
        if c is None:
            couches.append({"couche": ident, "motif": "absente du GetCapabilities"})
            continue
        periode = _periode_couche(ctx, c)
        c = {**c, **periode}
        c.update(_tuile(caps, c, centre))
        couches.append(c)
    retenues, autres = _choisir(couches, y0, y1)
    ctx.journal.add("geoplateforme", "cartes", {**params, "annees": f"{y0}-{y1}"},
                    "positif" if retenues else "negatif", nb_resultats=len(retenues), cache=cached,
                    references=[c["lien"] for c in retenues if c.get("lien")])
    requetes["geoplateforme"] = "positif" if retenues else "negatif"
    return {"source": {"service": "IGN-GEOPLATEFORME", "url": f"{WMTS}?SERVICE=WMTS&REQUEST=GetCapabilities",
                       "fournisseur": caps["fournisseur"], "conditions": caps["conditions"], "frais": caps["frais"],
                       "consulte_le": Date.today().isoformat()},
            "retenues": [_sortie(c) for c in retenues], "autres": [_sortie(c, court=True) for c in autres],
            "note": ("Liens de tuile WMTS (une image de 256 px contenant le centre de la commune) : à ouvrir par "
                     "l'utilisateur ; aucune image n'est téléchargée par le plugin.")}


def _capacites(texte: str) -> dict:
    root = ET.fromstring(texte)
    si = root.find("ows:ServiceIdentification", NS)
    fournisseur = root.findtext("ows:ServiceProvider/ows:ProviderName", "", NS)
    out = {"version": root.get("version", "1.0.0"), "fournisseur": fournisseur,
           "conditions": si.findtext("ows:AccessConstraints", "", NS) if si is not None else "",
           "frais": si.findtext("ows:Fees", "", NS) if si is not None else "", "couches": {}, "tms": {}}
    contents = root.find("w:Contents", NS)
    if contents is None:
        raise ValueError("GetCapabilities sans Contents")
    for t in contents.findall("w:TileMatrixSet", NS):
        matrices = {}
        for m in t.findall("w:TileMatrix", NS):
            x0, y0 = (float(v) for v in m.findtext("w:TopLeftCorner", "", NS).split())
            matrices[m.findtext("ows:Identifier", "", NS)] = {
                "echelle": float(m.findtext("w:ScaleDenominator", "", NS)), "x0": x0, "y0": y0,
                "largeur": int(m.findtext("w:TileWidth", "256", NS)), "hauteur": int(m.findtext("w:TileHeight", "256", NS))}
        out["tms"][t.findtext("ows:Identifier", "", NS)] = {"crs": t.findtext("ows:SupportedCRS", "", NS),
                                                            "matrices": matrices}
    for lay in contents.findall("w:Layer", NS):
        ident = lay.findtext("ows:Identifier", "", NS)
        if ident not in COUCHES:
            continue
        bas = lay.findtext("ows:WGS84BoundingBox/ows:LowerCorner", "", NS).split()
        haut = lay.findtext("ows:WGS84BoundingBox/ows:UpperCorner", "", NS).split()
        style = next((s.findtext("ows:Identifier", "", NS) for s in lay.findall("w:Style", NS)
                      if s.get("isDefault") == "true"), "") or lay.findtext("w:Style/ows:Identifier", "", NS)
        lien_tms = lay.find("w:TileMatrixSetLink", NS)
        limites = {}
        if lien_tms is not None:
            for li in lien_tms.findall("w:TileMatrixSetLimits/w:TileMatrixLimits", NS):
                limites[li.findtext("w:TileMatrix", "", NS)] = tuple(
                    int(li.findtext(f"w:{k}", "0", NS)) for k in ("MinTileRow", "MaxTileRow", "MinTileCol", "MaxTileCol"))
        meta = [m.get(f"{{{NS['xlink']}}}href", "") for m in lay.findall("ows:Metadata", NS)]
        out["couches"][ident] = {
            "couche": ident, "titre": lay.findtext("ows:Title", "", NS), "resume": lay.findtext("ows:Abstract", "", NS),
            "emprise": [float(v) for v in (*bas, *haut)] if len(bas) == 2 and len(haut) == 2 else None,
            "format": lay.findtext("w:Format", "", NS), "style": style,
            "tms": lien_tms.findtext("w:TileMatrixSet", "", NS) if lien_tms is not None else "",
            "limites": limites, "fiches": [m for m in meta if m and "/csw?" not in m],
            "csw": next((m for m in meta if "/csw?" in m), "")}
    return out


def _periode_couche(ctx: SourceContext, c: dict) -> dict:
    """Années couvertes par la couche : titre du GetCapabilities, sinon étendue temporelle de sa fiche CSW."""
    m = ANNEES.search(c["titre"])
    if m:
        a = int(m.group(1))
        return {"annees": [a, int(m.group(2) or a)], "periode_lue_dans": "titre de la couche (GetCapabilities)"}
    if not c["csw"] or not services.url_autorisee("IGN-GEOPLATEFORME", c["csw"]):
        return {"annees": None, "periode_lue_dans": "non renseignée par le service"}
    try:
        texte, _ = ctx.http.get(c["csw"], ttl=180 * DAY, source="geoplateforme", parse="text")
        tp = ET.fromstring(texte).find(".//gml:TimePeriod", NS)
        debut, fin = (tp.findtext(f"gml:{k}", "", NS) if tp is not None else "" for k in ("beginPosition", "endPosition"))
        if not (re.match(r"\d{4}", debut) and re.match(r"\d{4}", fin)):
            raise ValueError("fiche CSW sans étendue temporelle")
    except Exception as exc:  # noqa: BLE001
        e = error_envelope(ctx, "geoplateforme", "metadonnees_couche", {"couche": c["couche"]}, exc)
        return {"annees": None, "periode_lue_dans": f"non renseignée (fiche CSW : {e['erreur']})"}
    return {"annees": [int(debut[:4]), int(fin[:4])], "periode_lue_dans": f"fiche de métadonnées CSW ({debut} à {fin})"}


def _tuile(caps: dict, c: dict, centre: dict | None) -> dict:
    """Tuile WMTS contenant le centre de la commune : niveau, ligne, colonne, lien GetTile ; couverture du lieu."""
    if not centre:
        return {"couvre_le_lieu": None, "lien": None, "motif_lien": "coordonnées du lieu inconnues"}
    lat, lon = centre["latitude"], centre["longitude"]
    e = c.get("emprise")
    if e and not (e[0] <= lon <= e[2] and e[1] <= lat <= e[3]):
        return {"couvre_le_lieu": False, "lien": None, "motif_lien": "lieu hors de l'emprise de la couche"}
    tms = caps["tms"].get(c["tms"]) or {}
    if "3857" not in tms.get("crs", "") or not c["limites"]:
        return {"couvre_le_lieu": None, "lien": None, "motif_lien": "jeu de tuiles non pris en charge"}
    niveau = NIVEAU_TUILE if NIVEAU_TUILE in c["limites"] else max(c["limites"], key=int)
    m = tms["matrices"].get(niveau)
    if not m:
        return {"couvre_le_lieu": None, "lien": None, "motif_lien": "niveau de tuile absent du jeu"}
    x = R_TERRE * math.radians(lon)
    y = R_TERRE * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    pas = m["echelle"] * PIXEL
    col, row = int((x - m["x0"]) // (pas * m["largeur"])), int((m["y0"] - y) // (pas * m["hauteur"]))
    rmin, rmax, cmin, cmax = c["limites"][niveau]
    if not (rmin <= row <= rmax and cmin <= col <= cmax):
        return {"couvre_le_lieu": False, "lien": None, "motif_lien": "lieu hors des tuiles publiées de la couche"}
    q = {"SERVICE": "WMTS", "REQUEST": "GetTile", "VERSION": caps["version"], "LAYER": c["couche"],
         "STYLE": c["style"], "FORMAT": c["format"], "TILEMATRIXSET": c["tms"], "TILEMATRIX": niveau,
         "TILEROW": row, "TILECOL": col}
    return {"couvre_le_lieu": True, "lien": f"{WMTS}?{urlencode(q)}",
            "tuile": {"jeu": c["tms"], "niveau": niveau, "ligne": row, "colonne": col}}


def _choisir(couches: list[dict], y0: int, y1: int) -> tuple[list[dict], list[dict]]:
    """Couches contemporaines de la date ; à défaut, la plus proche avant et la plus proche après."""
    utiles, autres = [], []
    for c in couches:
        if "titre" not in c:
            autres.append(c)
        elif not c.get("annees"):
            autres.append({**c, "motif": "période de la couche non renseignée"})
        elif c.get("couvre_le_lieu") is False:
            autres.append({**c, "motif": c.get("motif_lien") or "hors emprise"})
        else:
            utiles.append(c)
    contemporaines = [c for c in utiles if c["annees"][0] <= y1 and c["annees"][1] >= y0]
    if contemporaines:
        retenues = [{**c, "motif": "contemporaine de la date"} for c in contemporaines]
    else:
        avant = [c for c in utiles if c["annees"][1] < y0]
        apres = [c for c in utiles if c["annees"][0] > y1]
        fin_av = max((c["annees"][1] for c in avant), default=None)
        deb_ap = min((c["annees"][0] for c in apres), default=None)
        retenues = [{**c, "motif": f"la plus proche avant la date ({y0 - c['annees'][1]} an(s))"}
                    for c in avant if c["annees"][1] == fin_av]
        retenues += [{**c, "motif": f"la plus proche après la date ({c['annees'][0] - y1} an(s))"}
                     for c in apres if c["annees"][0] == deb_ap]
    pris = {c["couche"] for c in retenues}
    autres += [{**c, "motif": "hors période"} for c in utiles if c["couche"] not in pris]
    return retenues, autres


def _sortie(c: dict, court: bool = False) -> dict:
    a = c.get("annees")
    out = {"couche": c["couche"], "titre": c.get("titre"), "motif": c.get("motif"),
           "periode_de_validite": {"debut": str(a[0]), "fin": str(a[1]), "lue_dans": c.get("periode_lue_dans")}
           if a else None}
    if court:
        return out
    out.update({"resume": c.get("resume"), "lien": c.get("lien"), "fiches": c.get("fiches", []),
                "source": {"service": "IGN-GEOPLATEFORME", "couche": c["couche"]}})
    if c.get("tuile"):
        out["tuile"] = c["tuile"]
    if not c.get("lien"):
        out["motif_lien"] = c.get("motif_lien")
    return out
