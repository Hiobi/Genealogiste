"""Gabarits de requête des services bibliographiques (#286) : un service = son entrée du référentiel
(``referentiels/sources_contexte.json`` : point d'accès, protocole, nature par défaut) + un gabarit (paramètres de
la requête, lecture des enregistrements en champs de ``Reference``).

Chaque analyseur a été écrit d'après une réponse réellement reçue, enregistrée sous
``tests/fixtures/contexte/reponses/<code>/`` avec son ``MANIFESTE.json`` (URL, date, statut). Aucun champ n'est
complété de mémoire : un champ absent de la notice reste vide. Une requête ne contient que des lieux, un sujet
(thème, métier) et des paramètres techniques ; jamais une donnée de personne.

Services livrés : HAL (Solr), ISIDORE (REST), SUDOC (SRU, UNIMARC), BNF-CATALOGUE (SRU, Dublin Core),
THESES-FR (REST), CROSSREF (REST).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .modeles import Identifiant, ReferenceInvalide
from .protocoles import ReponseInvalide, rest, solr, sru

# --------------------------------------------------------------------------------------------- formes communes


@dataclass(frozen=True)
class Recherche:
    """Ce qui part vers un service : lieux (du plus pertinent au moins pertinent), sujet libre, nombre de notices.
    La période ne part pas : elle ne borne pas la date de publication, elle sert au classement."""

    lieux: tuple[str, ...] = ()
    sujet: str = ""
    limite: int = 10

    @property
    def lieu_principal(self) -> str:
        return self.lieux[0] if self.lieux else ""

    def texte_libre(self) -> str:
        """Lieu principal et sujet, pour les services sans syntaxe booléenne documentée (REST)."""
        return " ".join(x for x in (self.lieu_principal, self.sujet) if x).strip()


@dataclass
class Notice:
    """Enregistrement lu dans une réponse : champs de ``Reference`` (sans service, requête ni date de
    consultation), ``indices`` (titre, sujets, mots-clés : texte servant au classement, jamais renvoyé) et
    ``ecart`` (motif d'exclusion lu sur la notice, vide si la notice est retenue)."""

    champs: dict = field(default_factory=dict)
    indices: str = ""
    ecart: str = ""
    titre_brut: str = ""  # pour signaler une notice écartée


@dataclass(frozen=True)
class Gabarit:
    code: str
    protocole: str  # solr | sru | rest | oai
    parse: str  # json | text (forme lue par HttpClient)
    parametres: Callable[[Recherche, Any], dict]  # (recherche, config) -> paramètres de la requête
    analyser: Callable[[Any], tuple[int | None, list[Notice]]]  # contenu -> (total annoncé, notices)


def _annee(texte: str) -> int | None:
    m = re.search(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)", texte or "")
    return int(m.group(1)) if m else None


def _pages_monographie(etendue: str) -> str:
    """« 223 p. » -> « 223 » ; toute autre forme (volumes, planches, feuillets) : vide (non interprétée)."""
    m = re.fullmatch(r"\s*(\d+)\s*p\.?\s*", etendue or "")
    return m.group(1) if m else ""


def _numero(v: str) -> str:
    """Volume ou numéro sans préfixe déjà écrit par le service (« n°448 », « N° 62 », « vol. 3 ») : la citation
    ajoute le sien."""
    return re.sub(r"^(?:(?:n\s*°|no\.?(?=\s*\d)|num\.|vol\.)\s*)+", "", (v or "").strip(), flags=re.I).strip()


def _doi(texte: str) -> str:
    m = re.search(r"10\.\d{4,9}/[^\s\"<>]+", texte or "")
    return m.group(0).rstrip(".,;)") if m else ""


def _identifiant(type_: str, valeur: str) -> Identifiant | None:
    try:
        return Identifiant(type_, valeur) if valeur else None
    except ReferenceInvalide:
        return None


def _sans_identifiant() -> str:
    return "aucun identifiant pérenne lisible dans la notice (DOI, ARK, HAL, PPN, Handle) : notice non renvoyée"


# ------------------------------------------------------------------------------------------------------- HAL

HAL_TYPES = "(ART OR COMM OR COUV OR OUV OR DOUV OR THESE OR HDR OR MEM OR REPORT OR OTHER)"
HAL_CHAMPS = ("docid,halId_s,doiId_s,title_s,subTitle_s,authLastName_s,authFirstName_s,authFullName_s,"
              "publicationDateY_i,journalTitle_s,docType_s,openAccess_bool,page_s,volume_s,issue_s,publisher_s,"
              "peerReviewing_s,bookTitle_s,city_s,keyword_s,authorityInstitution_s")
_HAL_DOC = {"ART": "article", "COMM": "chapitre", "COUV": "chapitre", "OUV": "monographie",
            "DOUV": "monographie", "THESE": "these", "HDR": "these"}


def _hal_parametres(r: Recherche, _config) -> dict:
    return {"q": solr.expression(list(r.lieux), r.sujet) or "*:*", "fq": f"docType_s:{HAL_TYPES}", "wt": "json",
            "rows": str(r.limite), "fl": HAL_CHAMPS}


def _hal_notice(d: dict) -> Notice:
    titre = solr.premier(d, "title_s")
    if sous := solr.premier(d, "subTitle_s"):
        titre = f"{titre} : {sous}"
    noms, prenoms = solr.valeurs(d, "authLastName_s"), solr.valeurs(d, "authFirstName_s")
    auteurs = ([f"{n}, {p}" for n, p in zip(noms, prenoms, strict=False)] if len(noms) == len(prenoms) and noms
               else solr.valeurs(d, "authFullName_s"))
    type_hal = solr.premier(d, "docType_s")
    type_doc = _HAL_DOC.get(type_hal, "autre")
    if type_doc == "chapitre" and not solr.premier(d, "bookTitle_s"):
        type_doc = "autre"
    publication = {"article": solr.premier(d, "journalTitle_s"), "chapitre": solr.premier(d, "bookTitle_s"),
                   "monographie": solr.premier(d, "publisher_s"),
                   "these": solr.premier(d, "authorityInstitution_s")}.get(type_doc, "")
    pairs = {"1": "oui", "0": "non"}.get(solr.premier(d, "peerReviewing_s"), "inconnu")
    these = type_doc == "these"
    ident = _identifiant("doi", solr.premier(d, "doiId_s")) or _identifiant("hal", solr.premier(d, "halId_s"))
    pages = solr.premier(d, "page_s")
    champs = {
        "titre": titre, "auteurs": auteurs, "publication": publication, "annee": d.get("publicationDateY_i")
        if isinstance(d.get("publicationDateY_i"), int) else None,
        "pages": _pages_monographie(pages) if type_doc in ("monographie", "these") else pages,
        "volume": _numero(solr.premier(d, "volume_s")), "numero": _numero(solr.premier(d, "issue_s")),
        "lieu_edition": solr.premier(d, "city_s") if type_doc == "monographie" else "",
        "type_document": type_doc, "evaluation_par_les_pairs": pairs,
        "acces": "libre" if d.get("openAccess_bool") is True else "",
        "nature": "secondaire_savante" if these or pairs == "oui" else "secondaire",
        "identifiant": ident,
    }
    indices = " ".join(solr.valeurs(d, "title_s") + solr.valeurs(d, "subTitle_s") + solr.valeurs(d, "keyword_s"))
    return Notice(champs, indices, "" if ident else _sans_identifiant(), titre)


def _hal_analyser(contenu) -> tuple[int | None, list[Notice]]:
    total, docs = solr.documents(contenu)
    return total, [_hal_notice(d) for d in docs]


# --------------------------------------------------------------------------------------------------- ISIDORE

_ISIDORE_DOC = {"article": "article", "chapter": "chapitre", "book": "monographie", "thesis": "these",
                "doctoralthesis": "these"}


def _isidore_parametres(r: Recherche, _config) -> dict:
    return {"q": r.texte_libre(), "output": "json", "replies": str(r.limite)}


def _isidore_titre(titres) -> str:
    """Titre d'origine (valeur sans attribut « @added ») ; à défaut, la version française."""
    liste = rest.liste(titres)
    simple = next((t for t in liste if isinstance(t, str) and t.strip()), "")
    if simple:
        return simple.strip()
    fr = next((t for t in liste if isinstance(t, dict) and t.get("@xml:lang") == "fr"), None)
    return rest.texte(fr) or rest.texte(liste)


def _isidore_notice(rep: dict) -> Notice:
    i = rep.get("isidore") if isinstance(rep.get("isidore"), dict) else {}
    uri = rest.texte(rep.get("@uri"))
    url = rest.texte(i.get("url"))
    similaire = rest.texte(rest.chemin(i, "ore.similar"))
    doi = _doi(uri) if uri.startswith("10.") else (_doi(url) if "doi.org/" in url else _doi(similaire))
    ident = _identifiant("doi", doi) or _identifiant("handle", uri)
    types = [t.lower() for t in rest.textes(rest.chemin(i, "types.type"))]
    type_doc = next((_ISIDORE_DOC[t] for t in types if t in _ISIDORE_DOC), "autre")
    createurs = rest.liste(rest.chemin(i, "enrichedCreators.creator"))
    auteurs = [rest.texte(c.get("@origin")) for c in createurs if isinstance(c, dict) and rest.texte(c.get("@origin"))]
    noms_source = rest.liste(rest.chemin(i, "source.name"))
    source_fr = next((n for n in noms_source if isinstance(n, dict) and n.get("@xml:lang") == "fr"), None)
    publication = rest.texte(source_fr) or rest.texte(noms_source)
    couverture = rest.texte(rest.chemin(i, "coverages.coverage"))
    pages = re.sub(r"^pp?\.\s*", "", couverture) if re.match(r"^pp?\.\s*\d", couverture) else ""
    droits = " ".join(rest.textes(i.get("dc:rights")))
    sujets = rest.textes(rest.chemin(i, "subjects.subject"))
    titre = _isidore_titre(i.get("title"))
    champs = {
        "titre": titre, "auteurs": auteurs,
        "publication": publication if type_doc == "article" else "",
        "annee": rest.entier(rest.chemin(i, "date.year")), "pages": pages if type_doc != "monographie" else "",
        "type_document": type_doc, "acces": "libre" if "openaccess" in droits.lower() else "",
        "nature": "secondaire_savante" if type_doc == "these" else "secondaire", "identifiant": ident,
    }
    return Notice(champs, " ".join([titre, *sujets]), "" if ident else _sans_identifiant(), titre)


def _isidore_analyser(contenu) -> tuple[int | None, list[Notice]]:
    rest.exiger(contenu, "response", dict)
    replies = rest.chemin(contenu, "response.replies")
    if not isinstance(replies, dict):
        raise ReponseInvalide("réponse Isidore sans response.replies")
    total = rest.entier(rest.chemin(replies, "meta.@items"))
    reponses = rest.liste(rest.chemin(replies, "content.reply"))
    return total, [_isidore_notice(x) for x in reponses if isinstance(x, dict)]


# ----------------------------------------------------------------------------------------------------- SUDOC

def _sudoc_cql(r: Recherche) -> str:
    lieux = [f"tou={p}" for p in (sru.cql_phrase(x) for x in r.lieux) if p]
    parties = []
    if lieux:
        parties.append(lieux[0] if len(lieux) == 1 else "(" + " or ".join(lieux) + ")")
    parties += [f"tou={m}" for m in sru.cql_mots(r.sujet)]
    return " and ".join(parties)


def _sudoc_parametres(r: Recherche, _config) -> dict:
    return {"operation": "searchRetrieve", "version": "1.1", "query": _sudoc_cql(r), "recordSchema": "unimarc",
            "maximumRecords": str(r.limite)}


def _sudoc_auteurs(n: sru.Unimarc) -> list[str]:
    out = []
    for tag in ("700", "701", "702"):
        for sf in n.occurrences(tag):
            d = dict(reversed(sf))  # premier sous-champ de chaque code
            if d.get("a"):
                out.append(f"{d['a']}, {d['b']}" if d.get("b") else d["a"])
    for tag in ("710", "711", "712"):
        for sf in n.occurrences(tag):
            if a := next((v for c, v in sf if c == "a"), ""):
                out.append(a)
    return list(dict.fromkeys(out))


def _sudoc_notice(el) -> Notice:
    n = sru.unimarc(el)
    ppn = n.controles.get("001", "")
    titre = n.premier("200", "a")
    if complement := n.premier("200", "e"):
        titre = f"{titre} : {complement}"
    ident = _identifiant("ppn", ppn)
    if n.leader[6:7] not in ("a", "b"):
        return Notice({}, "", "document non textuel (carte, image, son, objet…)", titre)
    these = n.a("328")
    niveau = n.leader[7:8]
    type_doc = "these" if these else {"m": "monographie", "a": "article"}.get(niveau, "autre")
    edition = "210" if n.a("210") else "214"
    lieu = n.premier(edition, "a")
    annee = _annee(n.premier(edition, "d")) or _annee(n.premier("100", "a")[9:13])
    champs = {
        "titre": titre, "auteurs": _sudoc_auteurs(n),
        "publication": n.premier("328", "e") if these else n.premier(edition, "c"),
        "lieu_edition": "" if "inconnu" in lieu.lower() else lieu.strip("[] "),
        "annee": annee, "pages": _pages_monographie(n.premier("215", "a")), "type_document": type_doc,
        "nature": "secondaire_savante" if these else "secondaire", "identifiant": ident,
    }
    sujets = [v for tag in ("600", "601", "606", "607") for v in n.sous_champs(tag, "a")]
    indices = " ".join([titre, *sujets])
    return Notice(champs, indices, "" if ident else _sans_identifiant(), titre)


def _sudoc_analyser(contenu) -> tuple[int | None, list[Notice]]:
    total, recs = sru.enregistrements(contenu)
    return total, [_sudoc_notice(el) for el in recs]


# --------------------------------------------------------------------------------------------- BNF-CATALOGUE

def _bnf_cql(r: Recherche) -> str:
    lieux = [f"bib.anywhere all {p}" for p in (sru.cql_phrase(x) for x in r.lieux) if p]
    parties = []
    if lieux:
        parties.append(lieux[0] if len(lieux) == 1 else "(" + " or ".join(lieux) + ")")
    if mots := sru.cql_mots(r.sujet):
        parties.append(f'bib.anywhere all "{" ".join(mots)}"')
    return " and ".join(parties)


def _bnf_parametres(r: Recherche, _config) -> dict:
    return {"version": "1.2", "operation": "searchRetrieve", "query": _bnf_cql(r), "recordSchema": "dublincore",
            "maximumRecords": str(r.limite)}


def _bnf_auteur(createur: str) -> str:
    """« Tavernier, André (19..-.... ; historien…). Auteur du texte » -> « Tavernier, André »."""
    a = createur
    while re.search(r"\([^()]*\)", a):  # dates et qualificatifs entre parenthèses, imbriquées comprises
        a = re.sub(r"\s*\([^()]*\)", "", a)
    a = a.strip()
    return re.sub(r"\.\s+[^.,]+$", "", a).strip()  # rôle final (« . Auteur du texte »)


def _bnf_notice(el) -> Notice:
    dc = sru.dublin_core(el)
    val = lambda nom: [v for v, _ in dc.get(nom, [])]  # noqa: E731
    titre = (val("title") or [""])[0].split(" / ")[0].strip()
    ark = next((v for v in val("identifier") if "ark:/" in v), "")
    ident = _identifiant("ark", ark)
    types = [t.lower() for t in val("type")]
    if not any(t in ("texte imprimé", "texte manuscrit", "text", "printed text") for t in types):
        return Notice({}, "", "document non textuel (image, carte, son, objet…)", titre)
    date = (val("date") or [""])[0]
    format_ = (val("format") or [""])[0]
    champs = {
        "titre": titre, "auteurs": [a for a in (_bnf_auteur(c) for c in val("creator")) if a],
        "publication": (val("publisher") or [""])[0], "annee": _annee(date),
        "pages": _pages_monographie(format_), "type_document": "autre" if re.search(r"\d-", date) else "monographie",
        "nature": "secondaire", "identifiant": ident,
    }
    return Notice(champs, " ".join([titre, *val("subject")]), "" if ident else _sans_identifiant(), titre)


def _bnf_analyser(contenu) -> tuple[int | None, list[Notice]]:
    total, recs = sru.enregistrements(contenu)
    return total, [_bnf_notice(el) for el in recs]


# ------------------------------------------------------------------------------------------------- THESES-FR

def _theses_parametres(r: Recherche, _config) -> dict:
    return {"q": r.texte_libre(), "debut": "0", "nombre": str(r.limite)}


def _theses_notice(t: dict) -> Notice:
    titre = rest.texte(t.get("titrePrincipal"))
    if rest.texte(t.get("status")) != "soutenue":
        return Notice({}, "", "thèse non soutenue (en préparation) : pas de texte à citer", titre)
    ident = _identifiant("doi", rest.texte(t.get("doi")))
    auteurs = [f"{rest.texte(a.get('nom'))}, {rest.texte(a.get('prenom'))}".strip(", ")
               for a in rest.liste(t.get("auteurs")) if isinstance(a, dict) and rest.texte(a.get("nom"))]
    sujets = [rest.texte(s.get("libelle")) for cle in ("sujets", "sujetsRameau")
              for s in rest.liste(t.get(cle)) if isinstance(s, dict)]
    champs = {
        "titre": titre, "auteurs": auteurs, "publication": rest.texte(t.get("etabSoutenanceN")),
        "annee": _annee(rest.texte(t.get("dateSoutenance"))), "type_document": "these",
        "nature": "secondaire_savante", "identifiant": ident,
    }
    ecart = "" if ident else ("thèse sans DOI dans la réponse : identifiant non résolvable, notice non renvoyée "
                              f"(consultable sur https://theses.fr/{rest.texte(t.get('nnt'))})")
    return Notice(champs, " ".join([titre, *sujets]), ecart, titre)


def _theses_analyser(contenu) -> tuple[int | None, list[Notice]]:
    theses = rest.exiger(contenu, "theses", list)
    return rest.entier(contenu.get("totalHits")), [_theses_notice(t) for t in theses if isinstance(t, dict)]


# -------------------------------------------------------------------------------------------------- CROSSREF

CROSSREF_TYPES = "type:journal-article,type:book-chapter,type:book,type:monograph,type:dissertation"
CROSSREF_CHAMPS = "DOI,title,author,container-title,published,issued,page,volume,issue,type,publisher,URL,subject"
_CROSSREF_DOC = {"journal-article": "article", "book-chapter": "chapitre", "book": "monographie",
                 "monograph": "monographie", "dissertation": "these"}


def _crossref_parametres(r: Recherche, config) -> dict:
    from .services import mailto

    p = {"query.bibliographic": r.texte_libre(), "filter": CROSSREF_TYPES, "rows": str(r.limite),
         "select": CROSSREF_CHAMPS}
    if adresse := mailto(config):  # vide par défaut : donnée personnelle envoyée seulement si renseignée
        p["mailto"] = adresse
    return p


def _crossref_annee(item: dict) -> int | None:
    for cle in ("issued", "published"):
        v = rest.chemin(item, f"{cle}.date-parts.0.0")
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return None


def _crossref_notice(item: dict) -> Notice:
    titre = rest.texte(item.get("title"))
    type_doc = _CROSSREF_DOC.get(rest.texte(item.get("type")), "autre")
    auteurs = []
    for a in rest.liste(item.get("author")):
        if not isinstance(a, dict):
            continue
        famille, prenom = rest.texte(a.get("family")), rest.texte(a.get("given"))
        nom = f"{famille}, {prenom}" if famille and prenom else (famille or rest.texte(a.get("name")))
        if nom:
            auteurs.append(nom)
    if type_doc == "these":
        affil = rest.chemin(item, "author.0.affiliation.0.name")
        publication = rest.texte(affil)
    elif type_doc == "monographie":
        publication = rest.texte(item.get("publisher"))
    else:
        publication = rest.texte(item.get("container-title"))
    ident = _identifiant("doi", rest.texte(item.get("DOI")))
    champs = {
        "titre": titre, "auteurs": auteurs, "publication": publication, "annee": _crossref_annee(item),
        "pages": rest.texte(item.get("page")) if type_doc in ("article", "chapitre") else "",
        "volume": _numero(rest.texte(item.get("volume"))), "numero": _numero(rest.texte(item.get("issue"))),
        "type_document": type_doc, "nature": "secondaire_savante" if type_doc == "these" else "secondaire",
        "identifiant": ident,
    }
    indices = " ".join([*rest.textes(item.get("title")), *rest.textes(item.get("container-title")),
                        *rest.textes(item.get("subject"))])
    return Notice(champs, indices, "" if ident else _sans_identifiant(), titre)


def _crossref_analyser(contenu) -> tuple[int | None, list[Notice]]:
    if rest.chemin(contenu, "status") != "ok":
        raise ReponseInvalide(f"réponse Crossref de statut {rest.texte(rest.chemin(contenu, 'status')) or 'absent'}")
    items = rest.exiger(contenu, "message.items", list)
    total = rest.entier(rest.chemin(contenu, "message.total-results"))
    return total, [_crossref_notice(x) for x in items if isinstance(x, dict)]


# ---------------------------------------------------------------------------------------------------- registre

GABARITS: dict[str, Gabarit] = {
    "HAL": Gabarit("HAL", "solr", "json", _hal_parametres, _hal_analyser),
    "ISIDORE": Gabarit("ISIDORE", "rest", "json", _isidore_parametres, _isidore_analyser),
    "SUDOC": Gabarit("SUDOC", "sru", "text", _sudoc_parametres, _sudoc_analyser),
    "BNF-CATALOGUE": Gabarit("BNF-CATALOGUE", "sru", "text", _bnf_parametres, _bnf_analyser),
    "THESES-FR": Gabarit("THESES-FR", "rest", "json", _theses_parametres, _theses_analyser),
    "CROSSREF": Gabarit("CROSSREF", "rest", "json", _crossref_parametres, _crossref_analyser),
}
ORDRE = tuple(GABARITS)  # ordre d'interrogation et de livraison
