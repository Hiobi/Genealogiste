"""pistes_contexte (#290) : hypothèses de recherche réfutables tirées des faits de l'arbre et du contexte sourcé.

Règle d'inférence : **le contexte oriente une recherche, il ne conclut jamais.** Assemblage, sans nouvelle définition
de format ni nouvelle source :

- faits de l'arbre et leur statut de preuve (``evidence.assess_event``), fenêtre de départ
  (``emigration.fenetre_depart``, #284) ;
- éléments de contexte sourcés (``local.contexte_local``, #289), tels quels ;
- chaînes de sources (``fr_sources.next_source_hint``, #283 et #284), intitulés et avertissements tels quels.

Chaque piste est engendrée par une règle fermée (``REGLES``) ; aucun intitulé n'est rédigé librement, aucun fait
historique n'est ajouté : une piste de contexte reprend l'``enonce`` de l'élément, sans connecteur causal.

Statuts : ``a_tester`` ; ``confirmee`` seulement si l'arbre porte déjà un fait sourcé (statut confirmé ou probable)
qui tranche ; ``refutee`` n'est attribué par aucune règle livrée (voir ``REGLES``) ; ``contexte_seul`` pour une piste
fondée uniquement sur un élément de contexte, plafonnée à « hypothèse » au sens GPS et jamais convertie en
proposition d'écriture.

Rien n'est écrit : ni l'arbre, ni l'enquête, ni la file de propositions. Chaque piste porte les paramètres prêts pour
``enquete_noter`` (versement à l'enquête, par l'appelant) et, pour une piste à tester, le chemin vers la file de
propositions comme tâche (``enquete_reprendre(taches=true)`` puis ``arbre_proposer`` ou ``propositions_deposer``).
Référence : docs/contexte-historique.md, « Outils », « pistes_contexte ».
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

from ..emigration import _faits, fenetre_depart
from ..fr_sources import next_source_hint
from ..models import EVENT_LABELS
from ..normalize.dates import jdn_to_gregorian, parse_date
from ..normalize.pays import pays_du_lieu, pays_resume
from ..sources.base import SourceContext
from ..statuts import LABELS
from . import local
from .registre import RegistreReferences

OUTIL = "pistes_contexte"

STATUTS = ("a_tester", "confirmee", "refutee", "contexte_seul")
STATUTS_LIBELLES = {"a_tester": "à tester", "confirmee": "confirmée", "refutee": "réfutée",
                    "contexte_seul": "contexte seul"}
COUTS = ("en_ligne", "courrier", "deplacement", "a_determiner")

# Statuts de preuve d'un fait de l'arbre qui suffisent à trancher une piste (un fait en hypothèse ne tranche pas).
STATUTS_QUI_TRANCHENT = ("confirme", "probable")
# Statuts de preuve qui excluent un fait comme fondement (« métier attesté »).
STATUTS_ECARTES = ("refute", "contradictoire", "non_source")

# Éléments de géographie historique (population, cartes) : ils décrivent le lieu, ils ne fondent pas de piste.
ORIGINES_DESCRIPTIVES = ("INSEE-MELODI", "IGN-GEOPLATEFORME")

REGLES = (
    {"code": "fenetre_depart",
     "si": "fenêtre de départ déterminée par deux faits datés et situés de l'arbre (emigration.fenetre_depart)",
     "piste": "« Départ de France entre <date du dernier fait en France> et <date du premier fait à l'étranger> »",
     "test": "chaîne de sources du parcours émigration (next_source_hint(\"EMIG\", début), versants français et "
             "étranger)",
     "statut": "confirmee si un EMIG ou IMMI de la personne ou de ses unions, cité et au statut confirmé ou "
               "probable, est daté dans la fenêtre ; sinon a_tester. Jamais refutee : un fait contraire déplace la "
               "fenêtre, qui est tirée de l'arbre."},
    {"code": "meme_metier_a_l_arrivee",
     "si": "métier attesté (OCCU cité, ni réfuté, ni contradictoire, situé en France ou sans lieu, au plus tard au "
           "premier fait à l'étranger) et premier fait daté situé à l'étranger",
     "piste": "« Même profession après l'arrivée (<pays>) : <intitulé du métier dans l'arbre> »",
     "test": "sources nominatives du pays d'arrivée (versant étranger de next_source_hint(\"RESI\", premier fait "
             "à l'étranger))",
     "statut": "confirmee si un OCCU situé à l'étranger, cité, au statut confirmé ou probable, porte le même "
               "intitulé ; sinon a_tester. Jamais refutee : une autre profession attestée ne l'exclut pas."},
    {"code": "element_de_contexte",
     "si": "élément de contexte_local retenu (rattachement compatible ou non_demontre), hors géographie "
           "historique descriptive (population, cartes)",
     "piste": "« Élément de contexte sourcé (<lieu>, <années>) : <enonce de l'élément> »",
     "test": "aucune source individuelle connue : la piste reste non démontrée",
     "statut": "contexte_seul, toujours : plafonnée à « hypothèse » (GPS), jamais tranchée par le contexte, "
               "jamais convertie en proposition d'écriture ni en tâche"},
)

AVERTISSEMENT = ("Pistes = hypothèses de recherche, pas des faits. Le contexte oriente une recherche, il ne conclut "
                 "jamais : une piste « contexte seul » reste une hypothèse non démontrée tant qu'aucune source "
                 "individuelle ne la porte. Aucune piste n'est écrite dans l'arbre.")
CONSIGNE_DEPOT = ("Rien n'est déposé par cet outil. Enquête : enquete_noter(enquete=<id>, **depot.enquete_noter) "
                  "pour chaque piste retenue. File de propositions (pistes a_tester seulement, comme tâches) : "
                  "depot.file. Une piste contexte_seul ne va jamais dans la file.")
MOTIF_CONTEXTE_SEUL = ("aucune source individuelle connue : la piste reste non démontrée (contexte seul) ; seule une "
                       "source portant sur l'individu pourrait la confirmer ou la réfuter")
MOTIF_SANS_FILE = ("contexte seul : jamais converti en proposition d'écriture ni en tâche de la file "
                   "(règle d'inférence)")


def _plat(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").casefold()
    return re.sub(r"[^\w]+", " ", s).strip()


def _cout(source: dict) -> str:
    """Coût d'une source de test, seulement s'il est déclaré par la chaîne de sources : « en ligne » explicite ;
    courrier et déplacement ne sont jamais déduits (aucun champ du référentiel ne les donne)."""
    return "en_ligne" if _plat(source.get("en_ligne", "")).startswith("en ligne") else "a_determiner"


def _test(sources: list[dict], motif: str = "") -> dict:
    out = {"sources": [{**s, "cout": _cout(s)} for s in sources]}
    if motif:
        out["motif"] = motif
    return out


def _cout_piste(test: dict) -> str:
    return "en_ligne" if any(s["cout"] == "en_ligne" for s in test["sources"]) else "a_determiner"


def _fait(e, porteur: str, preuve: dict, role: str) -> dict:
    """Fondement tiré de l'arbre : identifiant du fait, porteur, statut de preuve et citations."""
    g = parse_date(e.date) if e.date else None
    refs = [c["reference"] for gr in preuve.get("groupes", []) for c in gr["citations"]]
    out = {"role": role, "fait": e.type, "libelle": EVENT_LABELS.get(e.type, e.type), "uid": e.uid,
           "porteur": porteur, "date": e.date, "date_texte": g.texte() if g else e.date,
           "lieu": e.lieu.nom if e.lieu else "", "statut": preuve["statut"],
           "statut_libelle": preuve.get("libelle") or LABELS.get(preuve["statut"], preuve["statut"]),
           "citations": list(dict.fromkeys(refs))}
    if e.valeur:
        out["valeur"] = e.valeur
    return out


def _borne(b: dict, role: str) -> dict:
    """Fondement tiré d'une borne de la fenêtre de départ (déjà un fait de l'arbre avec son statut)."""
    return {"role": role, **{k: b[k] for k in ("fait", "libelle", "uid", "porteur", "date", "date_texte", "lieu",
                                               "statut", "statut_libelle", "citations") if k in b}}


def _tranche(preuve: dict, e) -> bool:
    return bool(e.citations) and preuve["statut"] in STATUTS_QUI_TRANCHENT


def _intervalle(date: str) -> tuple[int, int] | None:
    g = parse_date(date) if date else None
    return g.interval if g else None


def _annees(date: str) -> tuple[int, int] | None:
    iv = _intervalle(date)
    return (jdn_to_gregorian(iv[0])[0], jdn_to_gregorian(iv[1])[0]) if iv else None


def _depot(piste: dict, personne: str) -> dict:
    """Paramètres prêts pour l'appelant ; rien n'est déposé ici."""
    piste_enquete = {"question": piste["hypothese"], "hypotheses": [piste["hypothese"]],
                     "sources": [s["source"] for s in piste["test"]["sources"]],
                     "note": f"pistes_contexte, règle {piste['regle']} ; statut {piste['statut_libelle']}"}
    if piste["statut"] == "contexte_seul":
        piste_enquete["note"] += " ; " + MOTIF_CONTEXTE_SEUL
        piste_enquete["contexte_seul"] = True  # marqueur lu par les enquêtes : jamais une tâche, jamais la file (#325)
    parametres = {"piste": piste_enquete}
    if personne:
        parametres["personnes"] = [personne]
    out = {"enquete_noter": parametres}
    if piste["statut"] == "contexte_seul":
        out["file"] = None
        out["motif_file"] = MOTIF_SANS_FILE
    else:
        out["file"] = ("comme tâche, après enquete_noter : enquete_reprendre(enquete=<id>, taches=true, "
                       "elements=[<id de la piste notée>]) donne l'opération ajouter_tache (backend gramps et "
                       "GENEALOGISTE_GRAMPS_TACHES=true), à déposer par propositions_deposer ou arbre_proposer ; "
                       "jamais un fait")
    return out


def _finaliser(p: dict, i: int, personne: str) -> dict:
    """Piste dans l'ordre de lecture : id, règle, hypothèse, fondements, test, coût, statut, puis le reste."""
    p = {**p, "id": f"h{i}", "statut_libelle": STATUTS_LIBELLES[p["statut"]], "cout": _cout_piste(p["test"])}
    p["depot"] = _depot(p, personne) if p["statut"] in ("a_tester", "contexte_seul") else None
    tete = ("id", "regle", "hypothese", "fondements", "test", "cout", "statut", "statut_libelle")
    return {**{k: p[k] for k in tete}, **{k: v for k, v in p.items() if k not in tete}}


# --------------------------------------------------------------------------------------------- règles

def _regle_fenetre(fenetre: dict | None, faits: list) -> dict | None:
    if not fenetre or not fenetre.get("determinee"):
        return None
    debut, fin = fenetre["debut"], fenetre["fin"]
    piste = {"regle": "fenetre_depart",
             "hypothese": f"Départ de France entre {debut['date_texte']} et {fin['date_texte']}",
             "fondements": {"arbre": [_borne(debut, "dernier fait daté situé en France"),
                                      _borne(fin, "premier fait daté situé à l'étranger")], "contexte": []},
             "test": _test(fenetre.get("pistes") or []), "statut": "a_tester"}
    lo = _intervalle(debut["date"])
    hi = _intervalle(fin["date"])
    for e, porteur, preuve in faits:
        if e.type not in ("EMIG", "IMMI") or not _tranche(preuve, e):
            continue
        iv = _intervalle(e.date)
        if iv and lo and hi and iv[0] >= lo[0] and iv[1] <= hi[1]:
            piste["statut"] = "confirmee"
            piste["fondements"]["arbre"].append(_fait(e, porteur, preuve, "fait sourcé qui tranche"))
            break
    return piste


def _regle_metier(fenetre: dict | None, faits: list) -> list[dict]:
    if not fenetre or not fenetre.get("fin"):
        return []
    fin = fenetre["fin"]
    hi = _intervalle(fin["date"])
    evt_fin = next((e for e, _, _ in faits if e.uid == fin["uid"]), None)
    lieu_fin = evt_fin.lieu if evt_fin and evt_fin.lieu else fin["lieu"]
    pays = pays_du_lieu(lieu_fin)
    nom_pays = pays["nom"] or "pays d'arrivée"
    metiers: dict[str, tuple] = {}
    for e, porteur, preuve in faits:
        if e.type != "OCCU" or not e.valeur.strip() or not e.citations or preuve["statut"] in STATUTS_ECARTES:
            continue
        p = pays_du_lieu(e.lieu) if e.lieu else None
        if p is not None and p["france"] is False:
            continue
        iv = _intervalle(e.date)
        if iv and hi and iv[0] > hi[1]:
            continue
        metiers.setdefault(_plat(e.valeur), (e, porteur, preuve))
    out = []
    for cle, (e, porteur, preuve) in metiers.items():
        quand = _annees(e.date)
        attestee = f", attestée en {quand[0]}" if quand and quand[0] == quand[1] else ""
        sources = [s for s in next_source_hint("RESI", fin["date"], lieu_fin) if s.get("versant") == "etranger"]
        piste = {"regle": "meme_metier_a_l_arrivee",
                 "hypothese": f"Même profession après l'arrivée ({nom_pays}) : {e.valeur.strip()}{attestee}",
                 "fondements": {"arbre": [_fait(e, porteur, preuve, "métier attesté"),
                                          _borne(fin, "premier fait daté situé à l'étranger")],
                                "contexte": []},
                 "test": _test(sources), "statut": "a_tester", "pays_arrivee": pays_resume(pays)}
        for x, px, prx in faits:
            if x.type != "OCCU" or _plat(x.valeur) != cle or not _tranche(prx, x) or not x.lieu:
                continue
            if pays_du_lieu(x.lieu)["france"] is False:
                piste["statut"] = "confirmee"
                piste["fondements"]["arbre"].append(_fait(x, px, prx, "fait sourcé qui tranche"))
                break
        out.append(piste)
    return out


def _regle_contexte(contexte: dict, fenetre: dict | None) -> tuple[list[dict], list[dict]]:
    pistes, non_retenus = [], []
    bornes = None
    if fenetre and fenetre.get("determinee"):
        a, b = _annees(fenetre["debut"]["date"]), _annees(fenetre["fin"]["date"])
        bornes = (a[0], b[1]) if a and b else None
    for echelle, elements in (contexte.get("elements") or {}).items():
        for el in elements:
            niveau = el["rattachement"]["niveau"]
            if el.get("origine") in ORIGINES_DESCRIPTIVES or el["type"] == "geographie":
                non_retenus.append({"enonce": el["enonce"], "source": el["source"]["identifiant"],
                                    "motif": "géographie historique descriptive (population, carte) : situe le "
                                             "lieu, ne fonde pas de piste"})
                continue
            if niveau not in ("compatible", "non_demontre"):
                non_retenus.append({"enonce": el["enonce"], "source": el["source"]["identifiant"],
                                    "motif": f"rattachement {niveau} : déjà porté par une citation de l'arbre, "
                                             "pas une piste de contexte"})
                continue
            p = el["portee"]
            annees = str(p["de"]) if p["de"] == p["a"] else f"{p['de']}-{p['a']}"
            fondement = {k: el[k] for k in ("enonce", "type", "portee", "source", "rattachement", "origine",
                                            "mention") if k in el}
            piste = {"regle": "element_de_contexte",
                     "hypothese": f"Élément de contexte sourcé ({p['lieu']}, {annees}) : {el['enonce']}",
                     "fondements": {"arbre": [], "contexte": [fondement]},
                     "test": _test([], MOTIF_CONTEXTE_SEUL), "statut": "contexte_seul",
                     "plafond_gps": "hypothese", "echelle": echelle}
            if bornes:
                piste["recoupe_fenetre_depart"] = p["de"] <= bornes[1] and p["a"] >= bornes[0]
            pistes.append(piste)
    return pistes, non_retenus


# ---------------------------------------------------------------------------------------------- outil

def pistes_contexte(ctx: SourceContext, registre: RegistreReferences, tree=None, personne: str = "",
                    lieu: str = "", periode: str = "", echelles: str = "", themes: str = "",
                    style: str = "iso690", residus: Callable[[str], list[str]] | None = None) -> dict:
    """Pistes réfutables (voir le module). La garde des vivants est appelée par l'outil avant ce module. Lève
    ``local.ContexteInvalide`` (aucune requête) pour des arguments insuffisants ; ne modifie rien."""
    contexte = local.contexte_local(ctx, registre, tree, personne, lieu, periode, echelles, themes, style, residus)
    pistes: list[dict] = []
    non_appliquees: list[dict] = []
    fenetre = None
    if personne:
        faits = _faits(tree, personne)
        fenetre = fenetre_depart(tree, personne)
        if (p := _regle_fenetre(fenetre, faits)) is not None:
            pistes.append(p)
        else:
            non_appliquees.append({"regle": "fenetre_depart", "motif": (
                "aucun fait situé à l'étranger ni fait de migration dans l'arbre" if fenetre is None
                else fenetre.get("motif", "fenêtre de départ indéterminée"))})
        metier = _regle_metier(fenetre, faits)
        pistes += metier
        if not metier:
            non_appliquees.append({"regle": "meme_metier_a_l_arrivee", "motif": (
                "aucun fait daté situé à l'étranger" if not fenetre or not fenetre.get("fin")
                else "aucun métier attesté (OCCU cité, non réfuté) avant le premier fait à l'étranger")})
    else:
        for code in ("fenetre_depart", "meme_metier_a_l_arrivee"):
            non_appliquees.append({"regle": code, "motif": "sans personne : aucun fait de l'arbre"})
    ctx_pistes, non_retenus = _regle_contexte(contexte, fenetre)
    pistes += ctx_pistes
    if not ctx_pistes:
        non_appliquees.append({"regle": "element_de_contexte", "motif": (
            f"contexte_local : {contexte.get('resultat', local.NON_DOCUMENTE)}" if not contexte.get("nb_elements")
            else "aucun élément de contexte retenu comme piste (voir elements_non_retenus)")})
    pistes = [_finaliser(p, i, personne) for i, p in enumerate(pistes, 1)]
    nb = len(pistes)
    rq = contexte["requete"]
    jid = ctx.journal.add("contexte", OUTIL, {"lieux": [x.get("commune") or x.get("departement", "")
                                                        for x in rq.get("lieux") or []],
                                              "periode": rq.get("periode"), "echelles": rq.get("echelles")},
                          "positif" if nb else "negatif", nb_resultats=nb, personne=personne or None,
                          resume="; ".join(f"{p['statut']} : {p['hypothese'][:60]}" for p in pistes[:5])
                          or "aucune piste")
    out = {"outil": OUTIL, "personne": personne, "regle_inference": "le contexte oriente une recherche, il ne "
           "conclut jamais", "regles": list(REGLES), "nb_pistes": nb, "pistes": pistes,
           "regles_non_appliquees": non_appliquees, "elements_non_retenus": non_retenus,
           "contexte": {k: contexte.get(k) for k in ("resultat", "nb_elements", "non_documente", "services_en_echec",
                                                     "services_ecartes", "taches_manuelles", "journal")},
           "journal": jid, "depot": CONSIGNE_DEPOT, "avertissement": AVERTISSEMENT}
    if fenetre is not None:
        out["fenetre_depart"] = {k: fenetre.get(k) for k in ("determinee", "texte", "avertissement")}
    if not nb:
        out["recherche_negative"] = ("aucune piste : aucune règle ne s'applique aux faits sourcés de l'arbre, et "
                                     "contexte non documenté. Ne pas combler par une hypothèse libre.")
    return out
