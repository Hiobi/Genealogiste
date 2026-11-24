"""contexte_local (#289) : situer un individu (ou un lieu à une période) dans son contexte, sans inventer l'histoire.

Assemblage des modules du jalon, sans nouvelle définition de format (socle #321) :

1. **Entrées** : avec ``personne``, lieux (avec années de présence), période de vie et métiers lus dans les seuls
   faits **sourcés** de l'arbre (``requete.depuis_personne``) ; sinon un ``lieu`` et une ``periode`` donnés.
2. **Collecte**, service par service, l'échec de l'un n'arrêtant pas les autres : géographie historique
   (``lieux.lieu_historique`` : population et cartes sourcées), index Wikidata (``index_wikidata``, gabarits
   légers à l'échelle de la commune et du département), bibliographie (``bibliographie.rechercher``), presse (``presse.rechercher``). Hors de France, seuls les
   services dont la ``couverture`` du référentiel inclut le pays sont interrogés.
3. **Éléments** : ``ElementContexte`` dont l'``enonce`` est tiré de la source (titre de la notice, extrait OCR cité,
   valeur d'un jeu de données, titre d'une couche cartographique), jamais rédigé ; la source est une référence du
   registre des références consultées, sinon l'élément est écarté (``ecartes``, avec le motif).
4. **Contrôles** (``portee.controler``) : hors de la période de vie ou des lieux de vie = rejeté ; échelle
   supérieure à la commune = mention « tendance générale, ne prouve rien pour l'individu ».
5. **Rattachement** : ``atteste`` seulement si une citation de l'arbre portant sur l'individu contient
   l'identifiant de la source (``citation_arbre``) ; sinon ``compatible`` (même commune, années recoupant la présence
   attestée) ou ``non_demontre``, avec une justification factuelle.

Rien trouvé : ``resultat`` vaut « contexte non documenté », jamais un texte général. Aucune requête ne contient le
nom, le prénom ni l'identifiant de la personne (``residus_identite`` contrôle chaque requête avant l'envoi).
Référence : docs/contexte-historique.md, « Outils », « contexte_local ».
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from ..normalize.pays import pays_du_lieu, pays_par_nom
from ..normalize.places import normalize_place
from ..sources.base import SourceContext
from . import bibliographie as biblio
from . import index_wikidata as wdi
from . import lieux as geo_hist
from . import presse
from . import services as srv
from .gabarits import ORDRE, Recherche
from .modeles import (
    ECHELLES,
    NIVEAUX_RATTACHEMENT,
    ElementContexte,
    Portee,
    Rattachement,
    Reference,
    ReferenceInvalide,
    SourceElement,
)
from .portee import LieuDeVie, Periode, controler
from .registre import NonConsultee, RegistreReferences

OUTIL = "contexte_local"
NON_DOCUMENTE = "contexte non documenté"
ECHELLES_DEFAUT = ("commune", "departement")
MAX_LIEUX = 3  # communes (et départements) d'une même collecte
MAX_PRESSE = 2  # communes interrogées en presse, par pays (Gallica : une requête de recherche et trois d'extraits chacune)
ECARTES_MAX = 100
# Zones du référentiel (couverture) qui couvrent un pays ; un pays absent : services internationaux seulement.
ZONES_PAYS = {"FR": ("FR", "EU", "INT"), "US": ("US", "INT")}
ZONES_DEFAUT = ("INT",)
_ATTRIBUT = {"commune": "commune", "departement": "departement", "region": "region", "pays": "pays_naturel",
             "nation": "pays"}

# Type d'un élément tiré d'une notice ou d'un extrait : classement lexical indicatif du texte de la source (racines
# de mots, dans cet ordre), « culture » à défaut. Ce n'est pas une affirmation historique.
TYPES_LEXIQUE = (
    ("evenement", ("catastroph", "accident", "explosion", "greve", "inondation", "epidemi", "bataille", "guerre",
                   "incendie", "emeute", "massacre")),
    ("demographie", ("population", "recensement", "demograph", "migration", "emigr", "immigr", "natalit",
                     "mortalit")),
    ("economie", ("mine", "minier", "miniere", "houill", "charbon", "industri", "commerce", "compagnie", "usine",
                  "salaire", "agricol", "marche")),
    ("institution", ("ecole", "eglise", "paroisse", "mairie", "administration", "hopital", "seigneur")),
    ("droit", ("droit", "loi", "justice", "tribunal", "coutume")),
    ("geographie", ("carte", "plan", "cadastre", "geograph", "topograph")),
)

AVERTISSEMENT = ("Contexte : chaque élément situe l'individu, il ne prouve rien sur lui. L'énoncé est tiré de la source "
                 "citée (titre, extrait, valeur d'un jeu de données) : notices seules, lire le passage avant de citer. "
                 "Un rapprochement entre le contexte et une décision de l'individu reste une hypothèse au "
                 "conditionnel, jamais un fait.")
RAPPEL_INDEX = ("Wikidata est un index, jamais une source : une entrée signalée « non sourcé » ne peut être citée "
                "qu'après consultation de sa référence externe (lien donné).")


class ContexteInvalide(ValueError):
    """Arguments insuffisants ou incohérents : aucune requête émise."""


def _plat(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").casefold()
    return re.sub(r"[^\w]+", " ", s).strip()


def _cite(texte: str, terme: str) -> bool:
    t = _plat(terme)
    return bool(t) and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", _plat(texte)) is not None


def type_lexical(texte: str) -> str:
    """Type d'élément d'après les mots du texte de la source (TYPES_LEXIQUE), « culture » à défaut."""
    mots = _plat(texte).split()
    for type_, racines in TYPES_LEXIQUE:
        if any(m.startswith(r) for m in mots for r in racines):
            return type_
    return "culture"


# ------------------------------------------------------------------------------------------------- entrées

@dataclass
class Entrees:
    """Ce que l'outil cherche : lieux de vie (avec pays et années de présence), période de vie, métiers."""

    lieux: list[LieuDeVie]
    periode: Periode | None
    metiers: list[str] = field(default_factory=list)
    themes: str = ""
    echelles: tuple[str, ...] = ECHELLES_DEFAUT
    personne: str = ""

    def to_dict(self) -> dict:
        return {"personne": self.personne, "depuis_personne": bool(self.personne),
                "lieux": [{k: v for k, v in vars(x).items() if v not in ("", None)} for x in self.lieux],
                "periode": self.periode.to_dict() if self.periode else None, "metiers": self.metiers,
                "themes": self.themes, "echelles": list(self.echelles)}


def lire_echelles(texte: str) -> tuple[str, ...]:
    valeurs = [x.strip().lower() for x in re.split(r"[,;\s]+", texte or "") if x.strip()]
    if not valeurs:
        return ECHELLES_DEFAUT
    inconnues = [x for x in valeurs if x not in ECHELLES]
    if inconnues:
        raise ContexteInvalide(f"echelles : {', '.join(inconnues)} inconnue(s) ; valeurs possibles "
                               f"{' | '.join(ECHELLES)}")
    return tuple(x for x in ECHELLES if x in valeurs)


def preparer(tree, personne: str = "", lieu: str = "", periode: str = "", echelles: str = "",
             themes: str = "") -> Entrees:
    """Entrées depuis l'arbre (``personne`` : faits sourcés seulement) ou depuis ``lieu`` et ``periode``."""
    ech = lire_echelles(echelles)
    themes = re.sub(r"\s+", " ", (themes or "").replace(",", " ")).strip()
    try:
        per = biblio.lire_periode(periode)
    except biblio.RechercheInvalide as exc:
        raise ContexteInvalide(str(exc)) from None
    if personne and (lieu or "").strip():
        raise ContexteInvalide("donner personne OU lieu : avec personne, les lieux viennent des faits sourcés de "
                               "l'arbre")
    if personne:
        from .requete import depuis_personne

        try:
            rq = depuis_personne(tree, personne, pays_du_lieu=lambda x: pays_du_lieu(x).get("nom") or None)
        except KeyError:
            raise ContexteInvalide(f"personne inconnue dans l'arbre : {personne}") from None
        vie = rq.periode
        if per and vie:
            if per.de > vie.a or per.a < vie.de:
                raise ContexteInvalide(f"periode {per.de}-{per.a} hors de la période de vie sourcée "
                                       f"({vie.de}-{vie.a})")
            vie = Periode(max(per.de, vie.de), min(per.a, vie.a))
        return Entrees(rq.lieux, vie, list(rq.metiers), themes, ech, personne)
    if not (lieu or "").strip():
        raise ContexteInvalide("préciser personne (id de l'arbre) ou lieu (« Billy-Montigny, Pas-de-Calais »)")
    if per is None:
        raise ContexteInvalide("periode obligatoire avec lieu (« 1880-1914 ») : le contexte est toujours borné")
    n = normalize_place(lieu)
    pays = pays_du_lieu(lieu)
    lv = LieuDeVie(commune=n.get("commune") or "", departement=n.get("departement") or "",
                   pays=pays.get("nom") or "", de=per.de, a=per.a)
    return Entrees([lv], per, [], themes, ech, "")


def _code_pays(lieu: LieuDeVie) -> str:
    return pays_par_nom(lieu.pays) if lieu.pays else ""


def _zones(code_pays: str) -> tuple[str, ...]:
    return ZONES_PAYS.get(code_pays, ZONES_DEFAUT)


def _couvre(code_service: str, code_pays: str) -> bool:
    s = srv.par_code(code_service) or {}
    return bool(set((s.get("couverture") or {}).get("zone", [])) & set(_zones(code_pays)))


# ------------------------------------------------------------------------------------------------ collecte

@dataclass
class Collecte:
    """Accumulateur de l'enveloppe : éléments retenus, écartés, signalés non sourcés, état des services."""

    entrees: Entrees
    registre: RegistreReferences
    style: str
    citations_arbre: list[tuple[str, str]]  # (texte de la citation, libellé) des faits de la personne
    elements: dict[str, list[dict]] = field(default_factory=dict)
    ecartes: list[dict] = field(default_factory=list)
    non_sources: list[dict] = field(default_factory=list)
    interroges: list[dict] = field(default_factory=list)
    echecs: list[dict] = field(default_factory=list)
    services_ecartes: list[dict] = field(default_factory=list)
    taches: list[dict] = field(default_factory=list)
    _vus: set = field(default_factory=set)

    def ecarter(self, origine: str, enonce: str, motif: str, **extra) -> None:
        entree = {"origine": origine, "enonce": (enonce or "")[:200], "motif": motif, **extra}
        if entree not in self.ecartes:  # même notice écartée par deux collectes : une seule fois
            self.ecartes.append(entree)

    def rattachement(self, ref: Reference, portee: Portee) -> Rattachement:
        """``atteste`` seulement sur une citation de l'arbre (faits de la personne) qui contient l'identifiant de la
        source ; sinon ``compatible`` (même commune, années recoupant la présence attestée) ou ``non_demontre``."""
        e = self.entrees
        if e.personne:
            valeur = ref.identifiant.valeur.casefold()
            for texte, libelle in self.citations_arbre:
                if valeur and valeur in texte:
                    return Rattachement(e.personne, "atteste", "une citation de l'arbre portant sur l'individu donne "
                                        f"l'identifiant de cette source ({ref.identifiant.cle})", libelle)
        if portee.echelle == "commune":
            for lv in e.lieux:
                if lv.commune and _cite(portee.lieu, lv.commune) and _cite(lv.commune, portee.lieu):
                    presence = ("présence attestée par l'arbre" if e.personne else "période demandée") + (
                        f" ({lv.de}-{lv.a})" if lv.de is not None else " (non datée)")
                    if lv.de is not None and lv.a is not None and portee.de <= lv.a and portee.a >= lv.de:
                        return Rattachement(e.personne, "compatible", (
                            f"même lieu ({lv.commune}, échelle commune) et années recoupant la {presence} ; aucune "
                            "source ne relie l'individu à cet élément"))
                    return Rattachement(e.personne, "non_demontre", (
                        f"même lieu ({lv.commune}, échelle commune), hors des années de la {presence} ; aucune "
                        "source ne relie l'individu à cet élément"))
        return Rattachement(e.personne, "non_demontre", (
            f"contexte d'échelle {portee.echelle} ({portee.lieu}) : tendance générale, aucune source ne relie "
            "l'individu à cet élément"))

    def proposer(self, origine: str, ref: Reference | None, enonce: str, type_: str, lieu: str, echelle: str,
                 de: int | None, a: int | None, population: str = "", localisation: str = "") -> None:
        """Construit, contrôle et retient (ou écarte avec motif) un élément de contexte."""
        if ref is None or not self.registre.est_consultee(ref.identifiant):
            self.ecarter(origine, enonce, "source absente du registre des références consultées")
            return
        if not (enonce or "").strip():
            self.ecarter(origine, ref.titre, "aucun énoncé lisible dans la source")
            return
        if de is None:
            self.ecarter(origine, enonce, "élément non daté par la source")
            return
        try:
            portee = Portee(lieu=lieu, echelle=echelle, de=de, a=a if a is not None else de, population=population)
            source = SourceElement.depuis_reference(ref, localisation, self.style)
            el = ElementContexte(enonce=enonce.strip(), type=type_, portee=portee, source=source,
                                 rattachement=self.rattachement(ref, portee))
        except ReferenceInvalide as exc:
            self.ecarter(origine, enonce, f"élément non conforme au format commun : {exc}")
            return
        e = self.entrees
        ctl = controler(el, e.periode, e.lieux) if e.periode else {"retenu": False, "mention": "",
                                                                    "motifs": ["période de vie inconnue"]}
        if not ctl["retenu"]:
            self.ecarter(origine, enonce, " ; ".join(ctl["motifs"]), source=el.source.identifiant)
            return
        if not self.registre.est_consultee(el.source.identifiant):  # identifiant tel que porté par l'élément
            self.ecarter(origine, enonce, "source absente du registre des références consultées")
            return
        if el.source.identifiant in self._vus:  # même source déjà retenue à une échelle plus locale
            return
        self._vus.add(el.source.identifiant)
        sortie = {**el.to_dict(), "origine": origine}
        if ctl["mention"]:
            sortie["mention"] = ctl["mention"]
        self.elements.setdefault(echelle, []).append(sortie)


def _lieux_fr(e: Entrees) -> list[LieuDeVie]:
    return [x for x in e.lieux if _code_pays(x) == "FR" and x.commune][:MAX_LIEUX]


def _date_lieu(lv: LieuDeVie, vie: Periode) -> tuple[int, int]:
    de = lv.de if lv.de is not None else vie.de
    a = lv.a if lv.a is not None else vie.a
    return de, a


def _geographie(ctx: SourceContext, c: Collecte, residus) -> dict[str, str]:
    """lieu_historique par commune française : population et cartes sourcées ; renvoie les codes INSEE établis."""
    codes: dict[str, str] = {}
    e = c.entrees
    for lv in _lieux_fr(e):
        if not lv.departement:
            c.services_ecartes.append({"service": "lieu_historique", "lieu": lv.commune,
                                       "motif": "département inconnu : commune non identifiable sans lui"})
            continue
        de, a = _date_lieu(lv, e.periode)
        libelle, quand = f"{lv.commune}, {lv.departement}", (str(de) if de == a else f"BET {de} AND {a}")
        if residus and (trouves := residus(libelle)):
            c.echecs.append({"service": "lieu_historique", "lieu": lv.commune, "erreur": (
                f"requête non émise : elle contiendrait un élément d'identité ({', '.join(trouves)})")})
            continue
        res = geo_hist.lieu_historique(ctx, libelle, quand)
        if "erreur" in res:
            c.echecs.append({"service": "lieu_historique", "lieu": lv.commune, "erreur": res["erreur"],
                             "journal": res.get("journal")})
            continue
        if res.get("homonymie") or res.get("pays_inconnu") or res.get("hors_perimetre"):
            c.services_ecartes.append({"service": "lieu_historique", "lieu": lv.commune,
                                       "motif": res.get("consigne") or res.get("message", "")})
            continue
        for service, statut in (res.get("requetes") or {}).items():
            entree = {"service": f"lieu_historique:{service}", "lieu": lv.commune, "statut": statut}
            if statut.startswith("erreur"):
                c.echecs.append({**entree, "erreur": statut})
            elif statut.startswith("non interrogé"):
                c.services_ecartes.append({**entree, "motif": statut})
            else:
                c.interroges.append({**entree, "journal": res.get("journal")})
        if res.get("commune"):
            codes[lv.commune] = res["commune"]["code_insee"]
        _population(c, res, lv)
        _cartes(c, res, lv)
    return codes


def _reference_url(c: Collecte, url: str, service: str, titre: str, publication: str = "") -> Reference | None:
    """Référence d'un jeu de données ou d'un service interrogé par son URL (requête 2xx émise par le plugin),
    inscrite au registre (identifiant ``url`` égal à la requête)."""
    try:
        ref = Reference(identifiant={"type": "url", "valeur": url}, nature="primaire", titre=titre,
                        publication=publication, service=service, requete=url,
                        consulte_le=date.today().isoformat())
        return c.registre.enregistrer(ref, statut=200, reponse="")
    except (ReferenceInvalide, NonConsultee):
        return None


def _population(c: Collecte, res: dict, lv: LieuDeVie) -> None:
    pop = res.get("population") or {}
    if pop.get("valeur") in (None, geo_hist.INCONNU) or not pop.get("source"):
        return
    s = pop["source"]
    if s.get("service") == "CASSINI-LOCAL":  # base Cassini installée par l'utilisateur (#349) : indication
        ref = c.registre.lire(s.get("reference", ""))  # inscrite à l'installation (métadonnées Nakala, 2xx)
        enonce = (f"Base Cassini (EHESS), recensement de {pop.get('recensement') or pop.get('annee')} : "
                  f"{pop['valeur']} habitants (indication à confirmer sur le recensement lui-même)")
        c.proposer("NAKALA", ref, enonce, "demographie", lv.commune, "commune", pop.get("annee"), pop.get("annee"),
                   localisation=f"fichier installé par l'utilisateur ; {s.get('attribution', '')} ; "
                                f"{s.get('conditions', '')}")
        return
    ref = _reference_url(c, s.get("url", ""), "INSEE-MELODI", s.get("titre", ""), s.get("jeu", ""))
    enonce = (f"{s.get('titre') or s.get('jeu')} : {pop['valeur']} ({pop.get('mesure', '')}, "
              f"{pop.get('annee')})")
    c.proposer("INSEE-MELODI", ref, enonce, "demographie", lv.commune, "commune", pop.get("annee"),
               pop.get("annee"), localisation=s.get("geographie", ""))


def _cartes(c: Collecte, res: dict, lv: LieuDeVie) -> None:
    cartes = res.get("cartes") or {}
    source = cartes.get("source") or {}
    for carte in cartes.get("retenues", []):
        titre, per = carte.get("titre") or "", carte.get("periode_de_validite") or {}
        if not carte.get("lien"):
            c.ecarter("IGN-GEOPLATEFORME", titre, "couverture du lieu non vérifiée (aucune tuile contenant le "
                                                  f"centre de la commune : {carte.get('motif_lien', '')})")
            continue
        ref = _reference_url(c, source.get("url", ""), "IGN-GEOPLATEFORME", "Géoplateforme, GetCapabilities WMTS",
                             source.get("fournisseur", ""))
        de = int(per["debut"]) if str(per.get("debut", "")).isdigit() else None
        a = int(per["fin"]) if str(per.get("fin", "")).isdigit() else None
        c.proposer("IGN-GEOPLATEFORME", ref, titre, "geographie", lv.commune, "commune", de, a,
                   localisation=f"couche {carte.get('couche')} ; tuile {carte.get('lien')}")


def _index_wikidata(ctx: SourceContext, c: Collecte, codes: dict[str, str], personne: str | None, residus) -> None:
    e = c.entrees
    for lv in e.lieux[:MAX_LIEUX]:
        if not lv.commune:
            continue
        if not _couvre(wdi.SERVICE, _code_pays(lv)):
            continue
        code = codes.get(lv.commune)
        if not code:
            c.services_ecartes.append({"service": wdi.SERVICE, "operation": "index:evenements_commune",
                                       "lieu": lv.commune, "motif": (
                                           "code INSEE non établi (commune française du COG depuis 1943 "
                                           "seulement) : gabarit non applicable")})
            continue
        r = wdi.interroger(ctx, "evenements_commune", code, e.periode.de, e.periode.a, personne, residus)
        lignes = r.pop("lignes")
        r["lieu"] = lv.commune
        if r["statut"] == "interroge":
            c.interroges.append(r)
        elif r["statut"] == "erreur":
            c.echecs.append({**{k: v for k, v in r.items() if k != "motif"}, "erreur": r["motif"]})
        else:
            c.services_ecartes.append(r)
        for ligne in lignes:
            _ligne_index(c, ligne, lv.commune)


def _index_wikidata_departement(ctx: SourceContext, c: Collecte, personne: str | None, residus) -> None:
    """Gabarit ``evenements_departement`` (#345) : une requête par département français des lieux de vie, désigné par
    son code INSEE (tiré du nom du département, sans réseau). Index seulement, comme le gabarit communal."""
    e = c.entrees
    operation = "index:evenements_departement"
    vus: set[str] = set()
    for lv in e.lieux[:MAX_LIEUX]:
        if not lv.departement or not _couvre(wdi.SERVICE, _code_pays(lv)):
            continue
        code = normalize_place(f"x, {lv.departement}").get("departement_code") or ""
        if code in vus:
            continue
        vus.add(code)
        if not re.fullmatch(wdi.CODE_DEPARTEMENT, code):
            c.services_ecartes.append({"service": wdi.SERVICE, "operation": operation, "lieu": lv.departement,
                                       "motif": "code INSEE du département non établi : gabarit non applicable"})
            continue
        r = wdi.interroger(ctx, "evenements_departement", code, e.periode.de, e.periode.a, personne, residus)
        lignes = r.pop("lignes")
        r["lieu"] = lv.departement
        if r["statut"] == "interroge":
            c.interroges.append(r)
        elif r["statut"] == "erreur":
            c.echecs.append({**{k: v for k, v in r.items() if k != "motif"}, "erreur": r["motif"]})
        else:
            c.services_ecartes.append(r)
        for ligne in lignes:
            _ligne_index(c, ligne, lv.departement, "departement")


def _ligne_index(c: Collecte, ligne: wdi.LigneIndex, lieu: str, echelle: str = "commune") -> None:
    origine = f"{wdi.SERVICE} (index)"
    idents = ligne.identifiants()
    if not idents:
        c.ecarter(origine, ligne.libelle, "entrée de l'index sans référence externe (BnF, IdRef, Persée) : non "
                                          "sourcé, jamais présenté comme source", qid=ligne.qid)
        return
    ref = next((r for i in idents if (r := c.registre.lire(i)) is not None), None)
    if ref is None:
        c.non_sources.append({**ligne.to_dict(), "lieu": lieu, "echelle": echelle, "statut": "non sourcé",
                              "motif": "référence externe présente dans l'index mais non consultée : à consulter "
                                       "(liens) avant tout usage"})
        c.ecarter(origine, ligne.libelle, "référence externe non consultée (signalée dans non_sources)",
                  qid=ligne.qid)
        return
    c.proposer(origine, ref, ref.titre, "evenement", lieu, echelle, ligne.de, ligne.a)


def _groupes(e: Entrees) -> dict[str, list[LieuDeVie]]:
    out: dict[str, list[LieuDeVie]] = {}
    for lv in e.lieux:
        out.setdefault(_code_pays(lv), []).append(lv)
    return out


def _bibliographie(ctx: SourceContext, c: Collecte, personne: str | None, residus) -> None:
    e = c.entrees
    cfg = ctx.config
    sujet = e.themes or (e.metiers[0] if e.metiers else "")
    for echelle in e.echelles:
        if echelle == "international":
            c.services_ecartes.append({"service": "bibliographie", "echelle": echelle,
                                       "motif": "échelle internationale : aucun lieu à chercher"})
            continue
        for pays, lieux in _groupes(e).items():
            attr = _ATTRIBUT[echelle]
            valeurs = list(dict.fromkeys(getattr(x, attr) for x in lieux if getattr(x, attr)))[:MAX_LIEUX]
            nom_pays = next((x.pays for x in lieux if x.pays), "") or "pays inconnu"
            if not valeurs:
                c.services_ecartes.append({"service": "bibliographie", "echelle": echelle, "pays": nom_pays,
                                           "motif": f"aucun lieu de vie renseigné à l'échelle « {echelle} »"})
                continue
            codes = [x for x in ORDRE if srv.etat(x, cfg).actif and _couvre(x, pays)]
            if not codes:
                c.services_ecartes.append({"service": "bibliographie", "echelle": echelle, "pays": nom_pays,
                                           "motif": f"aucun service bibliographique actif ne couvre {nom_pays} : "
                                                    "contexte non documenté par le plugin"})
                continue
            larges = tuple(dict.fromkeys(x.departement for x in lieux if x.departement)) if echelle == "commune" \
                else ()
            demande = biblio.Demande(Recherche(lieux=tuple(valeurs), sujet=sujet, limite=10), e.periode, echelle,
                                     larges, bool(e.personne), list(e.metiers))
            out = biblio.rechercher(ctx, c.registre, demande, codes, c.style, personne, residus)
            for x in out["services_interroges"]:
                c.interroges.append({**x, "operation": "bibliographie", "echelle": echelle})
            for x in out["services_en_echec"]:
                c.echecs.append({**x, "operation": "bibliographie", "echelle": echelle})
            for x in out["services_ecartes"]:
                c.services_ecartes.append({**x, "operation": "bibliographie", "echelle": echelle})
            for x in out.get("notices_ecartees", []):
                c.ecarter(x.get("service", ""), x.get("titre", ""), x.get("motif", ""))
            for r in out["references"]:
                _reference_biblio(c, r, echelle, valeurs, larges)


def _bornes(pertinence: dict) -> list[tuple[int, int]]:
    out = []
    for x in pertinence.get("annees_citees", []):
        m = re.fullmatch(r"(\d{3,4})(?:-(\d{3,4}))?", str(x))
        if m:
            out.append((int(m.group(1)), int(m.group(2) or m.group(1))))
    return out


def _reference_biblio(c: Collecte, r: dict, echelle: str, lieux: list[str], larges: tuple[str, ...]) -> None:
    origine = (r.get("trouvee_par") or [r.get("service", "")])[0]
    ident = f"{r['identifiant']['type']}:{r['identifiant']['valeur']}"
    ref = c.registre.lire(ident)
    titre = (ref.titre if ref else r.get("titre", "")) or ""
    lieu = next((x for x in lieux if _cite(titre, x)), "")
    ech = echelle
    if not lieu:
        lieu = next((x for x in larges if _cite(titre, x)), "")
        ech = "departement"
    if not lieu:
        c.ecarter(origine, titre, "aucun lieu de vie cité dans le titre de la notice (portée géographique non "
                                  "établie)", source=ident)
        return
    p = r.get("pertinence") or {}
    per = c.entrees.periode
    bornes = _bornes(p)
    recoupe = [b for b in bornes if per and b[0] <= per.a and b[1] >= per.de]
    if recoupe:
        de, a = recoupe[0]
    elif p.get("periode") == "contemporaine" and ref and ref.annee:
        de = a = ref.annee
    elif bornes:
        de, a = bornes[0]  # hors période : rejeté par le contrôle, avec son motif
    else:
        de = a = None
    c.proposer(origine, ref, titre, type_lexical(titre), lieu, ech, de, a)


def _presse(ctx: SourceContext, c: Collecte, residus) -> None:
    e = c.entrees
    if "commune" not in e.echelles:
        return
    texte = e.themes or (e.metiers[0] if e.metiers else "")
    choisis = [lv for lieux in _groupes(e).values() for lv in [x for x in lieux if x.commune][:MAX_PRESSE]]
    for lv in choisis:  # MAX_PRESSE communes par pays
        pays = _code_pays(lv)
        codes = [x for x in presse.SERVICES_PRESSE if _couvre(x, pays)]
        if not codes:
            c.services_ecartes.append({"service": "presse", "lieu": lv.commune,
                                       "motif": f"aucun service de presse ne couvre {lv.pays or 'ce pays'}"})
            continue
        de, a = _date_lieu(lv, e.periode)
        if residus and (trouves := residus(f"{texte} {lv.commune}")):
            c.echecs.append({"service": "presse", "lieu": lv.commune, "erreur": (
                f"requête non émise : elle contiendrait un élément d'identité ({', '.join(trouves)})")})
            continue
        try:
            out = presse.rechercher(ctx, c.registre, texte, lv.commune, f"{de}-{a}", ",".join(codes))
        except presse.PresseInvalide as exc:
            c.services_ecartes.append({"service": "presse", "lieu": lv.commune, "motif": str(exc)})
            continue
        for etat in out["services"]:
            entree = {**etat, "operation": "presse", "lieu": lv.commune}
            if etat.get("statut") == "interroge":
                c.interroges.append(entree)
            elif etat.get("statut") in ("bloque_antirobot", "erreur"):
                c.echecs.append({**entree, "erreur": etat.get("motif", "")})
            else:
                c.services_ecartes.append(entree)
        if out.get("tache_manuelle"):
            c.taches.append({"lieu": lv.commune, **out["tache_manuelle"]})
        for r in out["resultats"]:
            _resultat_presse(c, r, lv)


def _resultat_presse(c: Collecte, r: dict, lv: LieuDeVie) -> None:
    ident = f"{r['identifiant']['type']}:{r['identifiant']['valeur']}"
    extrait = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", r.get("extrait") or "")).strip()
    libelle = f"{r.get('publication', '')} {r.get('date') or r.get('annee') or ''}".strip()
    service = r.get("service") or "GALLICA"
    if not r.get("au_registre"):
        c.ecarter(service, libelle, "référence non inscrite au registre", source=ident)
        return
    if not extrait:
        c.ecarter(service, libelle, "aucun extrait lu : le numéro n'est pas un énoncé (lien dans la tâche de "
                                    "lecture)", source=ident)
        return
    if not _cite(extrait, lv.commune):
        c.ecarter(service, libelle, f"le lieu ({lv.commune}) ne figure pas dans l'extrait", source=ident)
        return
    enonce = f"« {extrait} » ({presse.MENTION_OCR})"
    c.proposer(service, c.registre.lire(ident), enonce, type_lexical(extrait), lv.commune, "commune",
               r.get("annee"), r.get("annee"), localisation=f"vue {r['vue']}" if r.get("vue") else "")


# -------------------------------------------------------------------------------------------------- outil

def _citations_personne(tree, personne: str) -> list[tuple[str, str]]:
    """Citations des faits de la personne et de ses unions : (texte de recherche, libellé « titre, page »)."""
    if not personne or tree is None:
        return []
    p = tree.person(personne)
    evenements = list(p.evenements)
    for fam in tree.spouses_families(p.id):
        evenements += fam.evenements
    out = []
    for e in evenements:
        for ci in e.citations:
            s = tree.sources.get(ci.source)
            titre = s.titre if s else ci.source
            texte = " ".join([ci.page, ci.texte, ci.note, ci.ark, titre, *(([s.url, s.ark]) if s else [])])
            out.append((texte.casefold(), f"{titre}, {ci.page}".strip(", ")))
    return out


def contexte_local(ctx: SourceContext, registre: RegistreReferences, tree=None, personne: str = "", lieu: str = "",
                   periode: str = "", echelles: str = "", themes: str = "", style: str = "iso690",
                   residus: Callable[[str], list[str]] | None = None) -> dict:
    """Éléments de contexte sourcés, classés et bornés (voir le module). La garde des vivants est appelée par
    l'outil avant ce module. Lève ``ContexteInvalide`` (aucune requête) pour des arguments insuffisants."""
    e = preparer(tree, personne, lieu, periode, echelles, themes)
    c = Collecte(e, registre, style, _citations_personne(tree, personne))
    p = personne or None
    if not e.lieux or e.periode is None:
        motif = ("aucun lieu sourcé dans l'arbre" if not e.lieux else "aucune date sourcée dans l'arbre")
        c.services_ecartes.append({"service": "tous", "motif": f"{motif} : rien à chercher sans borne"})
    else:
        codes = _geographie(ctx, c, residus) if "commune" in e.echelles else {}
        if "commune" in e.echelles:
            _index_wikidata(ctx, c, codes, p, residus)
        if "departement" in e.echelles:
            _index_wikidata_departement(ctx, c, p, residus)
        _bibliographie(ctx, c, p, residus)
        _presse(ctx, c, residus)
    return _enveloppe(ctx, c, p)


def _enveloppe(ctx: SourceContext, c: Collecte, personne: str | None) -> dict:
    e = c.entrees
    rang = {n: i for i, n in enumerate(NIVEAUX_RATTACHEMENT)}
    elements = {}
    for echelle in ECHELLES:
        if echelle in c.elements:
            elements[echelle] = sorted(c.elements[echelle], key=lambda x: (
                rang[x["rattachement"]["niveau"]], x["portee"]["de"], x["enonce"]))
    nb = sum(len(v) for v in elements.values())
    resultat = NON_DOCUMENTE if not nb else f"{nb} élément(s) de contexte sourcé(s)"
    parametres = {"lieux": [x.commune or x.departement for x in e.lieux],
                  "periode": f"{e.periode.de}-{e.periode.a}" if e.periode else "", "echelles": list(e.echelles),
                  "themes": e.themes}
    jid = ctx.journal.add("contexte", OUTIL, parametres, "positif" if nb else "negatif", nb_resultats=nb,
                          personne=personne,
                          resume="; ".join(x["enonce"][:60] for v in elements.values() for x in v[:3])
                          or NON_DOCUMENTE,
                          references=list(dict.fromkeys(x["source"]["identifiant"] for v in elements.values()
                                                        for x in v))[:20])
    out = {"outil": OUTIL, "requete": e.to_dict(), "style_citation": c.style, "resultat": resultat,
           "nb_elements": nb, "elements": elements,
           "non_documente": [x for x in e.echelles if x not in elements],
           "non_sources": c.non_sources, "nb_ecartes": len(c.ecartes), "ecartes": c.ecartes[:ECARTES_MAX],
           "services_interroges": c.interroges, "services_en_echec": c.echecs,
           "services_ecartes": c.services_ecartes, "taches_manuelles": c.taches, "journal": jid,
           "avertissement": AVERTISSEMENT, "rappel_index": RAPPEL_INDEX}
    if not nb:
        out["recherche_negative"] = (f"{NON_DOCUMENTE} : aucun élément sourcé, borné dans le lieu et la période, "
                                     "n'a été trouvé par les services interrogés. Ne pas combler par un texte "
                                     "général.")
    return out
