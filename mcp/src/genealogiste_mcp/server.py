"""Serveur MCP « genealogiste » (FastMCP) : sources, normalisation, preuve, arbre GEDCOM versionné."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import coherence, evidence, matching, privacy
from .cache import Cache
from .config import Config, load_config
from .export import charts
from .export.fiche import fiche_markdown, gaps, tree_gaps
from .export.geneweb import to_geneweb
from .export.gramps_xml import to_gramps_xml_stats
from .export.rapport import proof_report
from .fr_sources import communicability, next_source_hint
from .gedcom.mapping import read_gedcom, write_gedcom
from .http import HttpClient
from .journal import Journal
from .normalize import dates as d
from .normalize.names import normalize_name, surname_similarity
from .normalize.places import normalize_place
from .sources import familysearch, gallica, geo, liens, matchid, wikidata, wikitree
from .sources.base import SourceContext
from .tree.proposals import ProposalError, Proposals
from .tree.store import TreeStore

INSTRUCTIONS = """Assistant généalogique (méthode du Genealogical Proof Standard, sources françaises).
Règles : ne jamais inventer (donnée sans source = « non sourcée ») ; toute écriture dans l'arbre passe par
arbre_proposer (diff) puis arbre_appliquer UNIQUEMENT après accord explicite de l'utilisateur ; jamais de fusion
automatique ; rien sur les personnes vivantes vers l'extérieur ; chaque recherche est tracée au journal (y compris
négative) ; toujours indiquer la prochaine source à consulter pour un fait non confirmé."""

mcp = FastMCP("genealogiste", instructions=INSTRUCTIONS, log_level="WARNING")

RATE = {"deces.matchid.io": 1.0, "api.wikitree.com": 1.0, "gallica.bnf.fr": 1.0, "query.wikidata.org": 1.0,
        "geo.api.gouv.fr": 0.1}


class App:
    def __init__(self, config: Config | None = None, transport=None, sleeper=None):
        self.config = config or load_config()
        self.cache = Cache(self.config.cache_path)
        kw = {"sleeper": sleeper} if sleeper else {}
        self.http = HttpClient(self.cache, self.config.user_agent, self.config.http_timeout, RATE,
                               offline=self.config.offline, transport=transport, **kw)
        self.store = TreeStore(self.config.data_dir)
        self.store.ensure()
        self.journal = Journal(self.config.journal_path)
        self.proposals = Proposals(self.store, self.config.proposals_dir, self.config.exiger_source)
        self.sctx = SourceContext(self.http, self.journal, self.config)

    def tree(self):
        return self.store.load()


_APP: App | None = None


def app() -> App:
    global _APP
    if _APP is None:
        _APP = App()
    return _APP


def set_app(a: App | None) -> None:
    global _APP
    _APP = a


def _guard_living(personne: str | None) -> dict | None:
    if not personne:
        return None
    t = app().tree()
    if personne in t.personnes:
        st = privacy.is_living(t, t.personnes[personne])
        if st["vivant"]:
            return {"refus": f"{personne} est présumé(e) vivant(e) ({st['raison']}) : aucune donnée n'est envoyée "
                              "à un service externe (RGPD). Marquer _VIVANT N si la personne est décédée."}
    return None


# ============================================================================ sources prioritaires

@mcp.tool()
def matchid_recherche(nom: str = "", prenom: str = "", ne_vers: str = "", lieu_naissance: str = "",
                      decede_vers: str = "", lieu_deces: str = "", sexe: str = "", texte: str = "",
                      taille: int = 20, page: int = 1, personne: str = "") -> dict:
    """Fichier des décès INSEE (depuis 1970) via matchID. Dates : '12/03/1920', '1920', 'vers 1920'
    (±2 ans). personne = id de l'arbre (journal). Résultats classés par score explicite."""
    return _guard_living(personne) or matchid.search(app().sctx, nom, prenom, ne_vers, lieu_naissance, decede_vers,
                                                     lieu_deces, sexe, texte, taille, page, personne or None)


@mcp.tool()
def matchid_appariement_csv(chemin_csv: str, colonnes: dict, sep: str = ",", format_date: str = "",
                            candidats: int = 1) -> dict:
    """Appariement par lot matchID d'un CSV. colonnes = {firstName:'Prenom', lastName:'Nom', birthDate:'Naissance',
    birthCity:..., deathDate:...}. Peut exiger un jeton (GENEALOGISTE_MATCHID_TOKEN)."""
    return matchid.bulk_submit(app().sctx, chemin_csv, colonnes, sep, format_date, candidats)


@mcp.tool()
def matchid_appariement_statut(job: str, sortie: str = "") -> dict:
    """Statut / résultat d'un appariement par lot matchID (sortie = chemin CSV où écrire le résultat)."""
    return matchid.bulk_status(app().sctx, job, sortie)


@mcp.tool()
def wikitree_recherche(nom: str, prenom: str = "", ne_vers: str = "", lieu: str = "", decede_vers: str = "",
                       limite: int = 20, personne: str = "") -> dict:
    """searchPerson WikiTree (arbre collaboratif = piste, source composite)."""
    return _guard_living(personne) or wikitree.search(app().sctx, nom, prenom, ne_vers, lieu, decede_vers, limite,
                                                      personne or None)


@mcp.tool()
def wikitree_profil(cle: str) -> dict:
    """getProfile WikiTree (clé ex. 'Martin-1234'), avec biographie et sources citées sur le profil."""
    return wikitree.get_profile(app().sctx, cle)


@mcp.tool()
def wikitree_personne(cle: str) -> dict:
    """getPerson WikiTree : personne + parents, enfants, conjoints."""
    return wikitree.get_person(app().sctx, cle)


@mcp.tool()
def wikitree_ascendants(cle: str, profondeur: int = 3) -> dict:
    """Ascendants WikiTree (getPeople ancestors=N, remplace getAncestors déprécié)."""
    return wikitree.get_ancestors(app().sctx, cle, profondeur)


@mcp.tool()
def wikitree_descendants(cle: str, profondeur: int = 2) -> dict:
    """Descendants WikiTree (getPeople descendants=N, remplace getDescendants déprécié)."""
    return wikitree.get_descendants(app().sctx, cle, profondeur)


@mcp.tool()
def gallica_recherche(texte: str, type_doc: str = "", titre: str = "", debut: str = "", fin: str = "",
                      exact: bool = True, nombre: int = 20, depart: int = 1, personne: str = "") -> dict:
    """Recherche SRU Gallica. type_doc : presse | livre | carte | manuscrit. titre : filtre (ex. 'annuaire').
    debut/fin : années de publication. exact=True : expression exacte."""
    return _guard_living(personne) or gallica.search(app().sctx, texte, type_doc, titre, debut, fin, exact, nombre,
                                                     depart, personne or None)


@mcp.tool()
def gallica_recherche_document(ark: str, texte: str) -> dict:
    """Pages d'un document Gallica contenant le texte (ContentSearch) avec extraits et liens image."""
    return gallica.search_in_document(app().sctx, ark, texte)


@mcp.tool()
def gallica_texte(ark: str, page: int = 0, max_caracteres: int = 20000) -> dict:
    """Texte OCR brut d'un document ou d'une page (fN) Gallica."""
    return gallica.text(app().sctx, ark, page or None, max_caracteres)


@mcp.tool()
def gallica_alto(ark: str, page: int) -> dict:
    """OCR ALTO d'une page (lignes, positions, confiance) : utile pour localiser un nom sur l'image."""
    return gallica.alto(app().sctx, ark, page)


@mcp.tool()
def gallica_iiif(ark: str, page: int = 0, region: str = "full", taille: str = "full") -> dict:
    """URL IIIF (manifeste, image d'une page, région 'x,y,l,h', taille 'pct:50' / '1500,')."""
    return gallica.iiif(ark, page or None, region, taille)


@mcp.tool()
def wikidata_personne(nom: str, prenom: str = "", ne_vers: str = "", lieu: str = "", limite: int = 20) -> dict:
    """Recherche d'une personnalité dans Wikidata (dates avec précision, lieux, parents)."""
    return wikidata.search_person(app().sctx, nom, prenom, ne_vers, lieu, limite)


@mcp.tool()
def wikidata_sparql(requete: str) -> dict:
    """Requête SPARQL en lecture seule sur query.wikidata.org."""
    return wikidata.sparql(app().sctx, requete)


@mcp.tool()
def geo_commune(nom: str = "", code_postal: str = "", code_insee: str = "", departement: str = "",
                limite: int = 10) -> dict:
    """Commune actuelle (API Géo) : code INSEE, département, coordonnées, libellé GEDCOM normalisé."""
    return geo.commune(app().sctx, nom, code_postal, code_insee, departement, limite)


@mcp.tool()
def geo_historique(nom: str = "", code_insee: str = "", departement: str = "") -> dict:
    """Historique d'une commune (COG INSEE depuis 1943) : fusions, changements de nom, commune actuelle."""
    return geo.history(app().sctx, nom, code_insee, departement)


@mcp.tool()
def recherche_multi(nom: str, prenom: str = "", ne_vers: str = "", lieu: str = "", decede_vers: str = "",
                    sources: list[str] | None = None, personne: str = "") -> dict:
    """Recherche multi-sources (matchID, WikiTree, Wikidata, Gallica) + liens des sources secondaires.
    Résultats fusionnés et classés par score de correspondance explicite."""
    refus = _guard_living(personne)
    if refus:
        return refus
    a = app()
    wanted = sources or ["matchid", "wikitree", "wikidata", "gallica"]
    pid = personne or None
    by_source: dict[str, Any] = {}
    if "matchid" in wanted:
        by_source["matchid"] = matchid.search(a.sctx, nom, prenom, ne_vers, lieu, decede_vers, personne=pid)
    if "wikitree" in wanted:
        by_source["wikitree"] = (wikitree.search(a.sctx, nom, prenom, ne_vers, lieu, decede_vers, personne=pid)
                                 if a.config.wikitree_app_id else {"erreur": "GENEALOGISTE_WIKITREE_APPID non défini"})
    if "wikidata" in wanted:
        by_source["wikidata"] = wikidata.search_person(a.sctx, nom, prenom, ne_vers, lieu, personne=pid)
    if "gallica" in wanted:
        by_source["gallica"] = gallica.search(a.sctx, f"{prenom} {nom}".strip(), personne=pid, nombre=10)
    persons, docs, errors, negatives = [], [], {}, []
    for s, res in by_source.items():
        if "erreur" in res:
            errors[s] = res["erreur"]
            continue
        if not res.get("resultats"):
            negatives.append(s)
        for r in res.get("resultats", []):
            (persons if "score" in r else docs).append(r)
    persons.sort(key=lambda r: -r.get("score", 0))
    return {
        "requete": {"nom": nom, "prenom": prenom, "ne_vers": ne_vers, "lieu": lieu, "decede_vers": decede_vers},
        "personnes": persons[:40], "documents": docs[:20], "sources_negatives": negatives, "erreurs": errors,
        "sources_secondaires": liens.search_links(nom, prenom, ne_vers, lieu, decede_vers)["liens"],
        "rappel": "Score = indice de correspondance, pas une preuve. Index et arbres en ligne : remonter à l'original.",
    }


@mcp.tool()
def liens_recherche(nom: str, prenom: str = "", ne_vers: str = "", lieu: str = "", decede_vers: str = "") -> dict:
    """URL de recherche pour Geneanet, FranceArchives, Mémoire des hommes, Grand Mémorial, AD (navigateur
    de l'utilisateur, lecture seule)."""
    return liens.search_links(nom, prenom, ne_vers, lieu, decede_vers)


@mcp.tool()
def cotes_a_consulter(fait: str, date_fait: str = "", lieu: str = "") -> dict:
    """Sources et cotes typiques (cadre de classement des AD) pour étayer un fait (BIRT, DEAT, MARR, FILIATION…)."""
    return liens.cote_suggestions(fait, date_fait, lieu)


@mcp.tool()
def source_collee(source: str, texte: str, url: str = "", parametres: dict | None = None, personne: str = "",
                  negatif: bool = False) -> dict:
    """Trace au journal un résultat consulté manuellement (Geneanet, AD, Mémoire des hommes…) et collé par
    l'utilisateur. negatif=True pour une recherche sans résultat."""
    jid = app().journal.add(source=source, operation="consultation_manuelle", parametres=parametres or {},
                            statut="negatif" if negatif else "manuel", resume=texte[:2000],
                            references=[url] if url else [], personne=personne or None)
    return {"journal": jid, "suite": "Créer la source/citation via arbre_proposer si l'information est retenue."}


@mcp.tool()
def familysearch_exporter(ids: list[str], ascendants: int = 4, descendants: int = 0, conjoints: bool = True) -> dict:
    """Télécharge un GEDCOM depuis FamilySearch via getmyancestors (identifiants de l'utilisateur en .env)."""
    return familysearch.export_gedcom(app().sctx, ids, ascendants, descendants, conjoints)


# ============================================================================ normalisation, analyse

@mcp.tool()
def normaliser_nom(nom_complet: str = "", prenoms: str = "", nom: str = "") -> dict:
    """Analyse un nom : prénoms (latin traduit), nom sans particule, surnom « dit », clé phonétique."""
    return normalize_name(nom_complet, prenoms, nom)


@mcp.tool()
def comparer_noms(nom1: str, nom2: str) -> dict:
    """Similarité de deux noms de famille (variantes, phonétique, latin, « dit »)."""
    return surname_similarity(nom1, nom2)


@mcp.tool()
def convertir_date(date_texte: str) -> dict:
    """Analyse/convertit une date : GEDCOM, texte français, républicain (« 12 vendémiaire an III »), julien.
    Renvoie équivalents grégorien/républicain/julien, intervalle et forme GEDCOM 7 / 5.5.1."""
    return d.convert(date_texte)


@mcp.tool()
def naissance_depuis_age(date_evenement: str, age: str) -> dict:
    """Intervalle de naissance déduit d'un âge déclaré (décès, mariage, recensement), tolérance ±2 ans."""
    g = d.parse_date(date_evenement)
    a = d.parse_age(age)
    if not g or not a:
        return {"erreur": "date ou âge non reconnu"}
    return d.birth_from_age(g, *a).to_dict()


@mcp.tool()
def normaliser_lieu(lieu: str) -> dict:
    """Normalise un lieu (Saint/St, paroisse, département, ancien département)."""
    return normalize_place(lieu)


@mcp.tool()
def comparer_profils(profil1: dict, profil2: dict) -> dict:
    """Score de correspondance argumenté entre deux profils {prenoms, nom, sexe, naissance:{date,lieu},
    deces:{date,lieu}, pere:{prenoms,nom}, mere:{...}} (ex. un résultat externe vs une personne)."""
    return matching.compare_profiles(profil1, profil2)


@mcp.tool()
def communicabilite(document: str, date_document: str = "", date_naissance: str = "", date_deces: str = "") -> dict:
    """Délai de communicabilité (Code du patrimoine) : naissance, mariage, deces, recensement, notaire, matricule,
    judiciaire, vie_privee, medical, cadastre, hypotheques, tables_decennales."""
    return communicability(document, date_document, date_naissance, date_deces)


@mcp.tool()
def prochaine_source(fait: str, date_fait: str = "", lieu: str = "") -> list[dict]:
    """Sources à consulter en priorité pour étayer un fait."""
    return next_source_hint(fait.upper(), date_fait, lieu)


# ============================================================================ arbre : lecture

@mcp.tool()
def arbre_info() -> dict:
    """Statistiques de l'arbre de travail, emplacement des données, propositions en attente."""
    a = app()
    t = a.tree()
    return {"repertoire": str(a.config.data_dir), "fichier": str(a.store.path), "personnes": len(t.personnes),
            "familles": len(t.familles), "sources": len(t.sources), "medias": len(t.medias),
            "vivants_presumes": len(privacy.living_ids(t)), "propositions_en_attente": a.proposals.pending(),
            "dernier_commit": (a.store.log(1) or [{}])[0], "mode_preuve": "strict" if a.config.strict_evidence else "pondéré",
            "backend": a.config.backend}


@mcp.tool()
def arbre_recherche(texte: str = "", nom: str = "", prenom: str = "", ne_vers: str = "", limite: int = 30) -> list[dict]:
    """Cherche dans l'arbre local (nom/prénom normalisés, variantes, ±2 ans)."""
    t = app().tree()
    out = []
    q = {"nom": nom, "prenoms": prenom, "naissance": {"date": ne_vers}}
    if texte and not (nom or prenom):
        nn = normalize_name(texte)
        q["nom"], q["prenoms"] = nn["nom_original"], nn["prenoms"]
    for pid in t.personnes:
        prof = matching.profile_from_person(t, pid)
        if q["nom"] and surname_similarity(q["nom"], prof["nom"])["score"] < 0.85:
            continue
        res = matching.compare_profiles({k: v for k, v in q.items() if v}, prof)
        out.append({"id": pid, "nom": t.personnes[pid].nom_principal.complet,
                    "naissance": prof["naissance"], "deces": prof["deces"], "score": res["score"]})
    out.sort(key=lambda r: -r["score"])
    return out[:limite]


@mcp.tool()
def arbre_personne(id: str) -> dict:
    """Personne complète : noms, événements (uid), filiation, unions, statut de preuve de chaque fait,
    alertes de cohérence, statut vivant/décédé."""
    a = app()
    t = a.tree()
    p = t.person(id)
    data = p.to_dict()
    data.pop("extra", None)
    data["statut_preuve"] = evidence.assess_person(t, id, a.config.strict_evidence)
    data["coherence"] = coherence.check_person(t, id)
    data["vivant"] = privacy.is_living(t, p)
    f, m = t.father_mother(id)
    data["parents"] = {"pere": t.personnes[f].label() if f in t.personnes else None,
                       "mere": t.personnes[m].label() if m in t.personnes else None}
    data["unions"] = [{"famille": fam.id, "conjoint": (t.personnes[x].label() if (x := (fam.epouse if fam.epoux == id
                       else fam.epoux)) in t.personnes else None),
                       "enfants": [t.personnes[c.enfant].label() for c in fam.enfants if c.enfant in t.personnes]}
                      for fam in t.spouses_families(id)]
    data["sources_citees"] = {s: t.sources[s].to_dict() for s in {c["source"] for f_ in data["statut_preuve"]
                              for g in f_.get("groupes", []) for c in g["citations"]} if s in t.sources}
    return data


@mcp.tool()
def arbre_fiche(id: str, masquer_vivants: bool = True) -> str:
    """Fiche individuelle Markdown (faits, statut de preuve, contradictions, sources, prochaines sources)."""
    return fiche_markdown(app().tree(), id, app().config.strict_evidence, masquer_vivants)


@mcp.tool()
def arbre_statut_preuve(id: str, fait: str = "") -> list[dict]:
    """Statut de preuve de chaque fait (ou d'un type de fait : BIRT, DEAT, MARR, nom, filiation)."""
    facts = evidence.assess_person(app().tree(), id, app().config.strict_evidence)
    return [f for f in facts if not fait or f["fait"] == fait or f.get("uid") == fait]


@mcp.tool()
def arbre_coherence(id: str = "") -> list[dict]:
    """Contrôles biologiques et chronologiques (une personne ou tout l'arbre)."""
    t = app().tree()
    return coherence.check_person(t, id) if id else coherence.check_tree(t)


@mcp.tool()
def arbre_comparer(id1: str, id2: str) -> dict:
    """Même personne ou homonymes ? Score explicite critère par critère, contradictions. Ne fusionne jamais."""
    return matching.compare_persons(app().tree(), id1, id2)


@mcp.tool()
def arbre_ascendance(id: str, generations: int = 4, format: str = "liste") -> Any:
    """Ascendance (numérotation Sosa). format : liste | mermaid | svg."""
    t = app().tree()
    hidden = privacy.living_ids(t)
    generations = max(1, min(generations, 12))
    if format == "mermaid":
        return charts.mermaid_ancestors(t, id, generations, hidden)
    if format == "svg":
        return charts.svg_ancestors(t, id, generations, hidden)
    return charts.ancestors(t, id, generations, hidden)


@mcp.tool()
def arbre_descendance(id: str, generations: int = 3, format: str = "liste") -> Any:
    """Descendance. format : liste | mermaid | svg. Vivants masqués."""
    t = app().tree()
    hidden = privacy.living_ids(t)
    generations = max(1, min(generations, 10))
    if format == "mermaid":
        return charts.mermaid_descendants(t, id, generations, hidden)
    if format == "svg":
        return charts.svg_descendants(t, id, generations, hidden)
    return charts.descendants(t, id, generations, hidden)


@mcp.tool()
def arbre_lacunes(id: str = "") -> dict:
    """Faits manquants ou faibles + plan de recherche priorisé (une personne, ou classement de tout l'arbre)."""
    t = app().tree()
    return gaps(t, id, app().config.strict_evidence) if id else tree_gaps(t, app().config.strict_evidence)


@mcp.tool()
def arbre_cercle(id: str, cercle: str = "famille") -> dict:
    """Individu et ses proches à enquêter : cercle = personne | famille (parents, conjoints, enfants, fratrie)
    | etendu (+ grands-parents, beaux-parents, oncles/tantes). Pour chacun : lien, vivant (exclu des
    recherches externes), nombre d'actions urgentes (lacunes)."""
    t = app().tree()
    t.person(id)
    rel: dict[str, str] = {id: "sujet"}

    def add(x, lien):
        if x and x in t.personnes and x not in rel:
            rel[x] = lien

    if cercle in ("famille", "etendu"):
        f, m = t.father_mother(id)
        add(f, "père")
        add(m, "mère")
        for fam in t.spouses_families(id):
            add(fam.epouse if fam.epoux == id else fam.epoux, "conjoint")
            for c in fam.enfants:
                add(c.enfant, "enfant")
        for fam, _ in t.parents(id):
            for c in fam.enfants:
                add(c.enfant, "frère/sœur")
    if cercle == "etendu":
        for par, side in ((t.father_mother(id)[0], "paternel"), (t.father_mother(id)[1], "maternel")):
            if not par:
                continue
            gf, gm = t.father_mother(par)
            add(gf, f"grand-père {side}")
            add(gm, f"grand-mère {side}")
            for fam, _ in t.parents(par):
                for c in fam.enfants:
                    add(c.enfant, f"oncle/tante {side}")
        for fam in t.spouses_families(id):
            sp = fam.epouse if fam.epoux == id else fam.epoux
            if sp:
                bf, bm = t.father_mother(sp)
                add(bf, "beau-père")
                add(bm, "belle-mère")
    out = []
    for pid, lien in rel.items():
        p = t.personnes[pid]
        living = privacy.is_living(t, p)["vivant"]
        g = gaps(t, pid, app().config.strict_evidence) if not living else {"plan": []}
        out.append({"id": pid, "lien": lien, "nom": "Vivant" if living else p.nom_principal.complet,
                    "vivant": living, "actions_urgentes": sum(1 for x in g["plan"] if x["priorite"] <= 1),
                    "premiere_action": g["plan"][0]["probleme"] if g["plan"] else None})
    return {"sujet": t.personnes[id].label(), "cercle": cercle,
            "a_enqueter": [x for x in out if not x["vivant"]],
            "exclus_vivants": sum(1 for x in out if x["vivant"])}


@mcp.tool()
def arbre_vivant(id: str) -> dict:
    """Statut vivant/décédé présumé (RGPD) et raisonnement."""
    t = app().tree()
    return privacy.is_living(t, t.person(id))


@mcp.tool()
def arbre_historique(limite: int = 20) -> list[dict]:
    """Historique Git des modifications de l'arbre (justifications et sources)."""
    return app().store.log(limite)


# ============================================================================ arbre : écriture (proposer -> valider)

@mcp.tool()
def arbre_proposer(operations: list[dict], titre: str, justification: str, sources: list[str] | None = None) -> dict:
    """Prépare une modification SANS l'écrire : renvoie le diff GEDCOM, les alertes de cohérence nouvelles et un
    jeton. Opérations : ajouter_personne, modifier_personne, supprimer_personne, ajouter_nom, ajouter_evenement,
    modifier_evenement, supprimer_evenement, ajouter_famille, lier_enfant, delier_enfant, lier_conjoint,
    ajouter_source, modifier_source, ajouter_depot, ajouter_citation, ajouter_media, ajouter_association,
    supprimer_association, fusionner_personnes, scinder_personne, definir_statut, marquer_vivant.
    Règle de métier : tout événement ou filiation exige une citation, sauf non_source=true + motif.
    Citation : préciser 'consultation' (original | image | transcription | index | non_vu). Référencer un objet créé dans la même proposition par
    "$ref". Voir docs/operations.md."""
    try:
        return app().proposals.propose(operations, titre, justification, sources)
    except ProposalError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def arbre_appliquer(jeton: str) -> dict:
    """Écrit une proposition et crée le commit Git. À n'appeler qu'après accord EXPLICITE de l'utilisateur
    sur le diff présenté. Jeton à usage unique, refusé si l'arbre a changé."""
    try:
        return app().proposals.apply(jeton)
    except ProposalError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def arbre_annuler_proposition(jeton: str) -> dict:
    """Abandonne une proposition en attente."""
    return {"annulee": app().proposals.cancel(jeton)}


@mcp.tool()
def arbre_importer_gedcom(chemin: str, mode: str = "ajouter") -> dict:
    """Prépare l'import d'un fichier GEDCOM (5.5.1 ou 7) : mode 'ajouter' (renumérote, doublons à recouper)
    ou 'remplacer'. Renvoie une proposition (diff + jeton) à valider."""
    p = Path(chemin).expanduser()
    if not p.is_file():
        return {"erreur": f"Fichier introuvable : {p}"}
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        tree, info = read_gedcom(text)
    except ValueError as exc:
        return {"erreur": f"GEDCOM illisible : {exc}"}
    if mode not in ("ajouter", "remplacer"):
        return {"erreur": "mode : ajouter | remplacer"}
    app().journal.add("import", "gedcom", {"fichier": str(p), "mode": mode}, "positif", nb_resultats=info["personnes"])
    try:
        prop = app().proposals.propose([{"op": "remplacer_arbre", "mode": mode, "gedcom_texte": write_gedcom(tree)}],
                                       f"Import GEDCOM {p.name} ({mode})",
                                       f"Import du fichier {p.name} ({info['version_source']}, {info['personnes']} "
                                       "personnes). Données importées non vérifiées : statut à établir fait par fait.",
                                       [])
    except ProposalError as exc:
        return {"erreur": str(exc)}
    prop["import"] = info
    if len(prop["diff"]) > 8000:
        prop["diff"] = prop["diff"][:8000] + "\n… (diff tronqué : import volumineux)"
    return prop


@mcp.tool()
def arbre_exporter(format: str = "gedcom7", chemin: str = "", id: str = "", generations: int = 4,
                   masquer_vivants: bool = True, temoins_en_personnes: bool = False) -> dict:
    """Export : gedcom7 | gedcom551 | geneweb | gramps | mermaid_asc | mermaid_desc | svg_asc | svg_desc | fiche.
    geneweb : GEDCOM 5.5.1 pour ged2gwb, avec citations complètes, statut de preuve et témoins visibles dans
    GeneWeb (temoins_en_personnes=True crée une fiche pour chaque témoin seulement nommé).
    Vivants masqués par défaut (RGPD). chemin par défaut : <données>/exports/."""
    a = app()
    t = a.tree()
    hidden: set[str] = set()
    if masquer_vivants:
        t, hidden = privacy.mask_tree(t)
    ext = {"gedcom7": "ged", "gedcom551": "ged", "geneweb": "ged", "gramps": "gramps", "mermaid_asc": "mmd", "mermaid_desc": "mmd",
           "svg_asc": "svg", "svg_desc": "svg", "fiche": "md"}
    if format not in ext:
        return {"erreur": f"format : {', '.join(ext)}"}
    if format in ("mermaid_asc", "mermaid_desc", "svg_asc", "svg_desc", "fiche") and not id:
        return {"erreur": "id requis pour ce format"}
    if format == "gedcom7":
        content = write_gedcom(t, 7)
    elif format == "gedcom551":
        content = write_gedcom(t, 5)
    elif format == "geneweb":
        content, stats = to_geneweb(t, a.config.strict_evidence, temoins_en_personnes)
    elif format == "gramps":
        content, stats = to_gramps_xml_stats(t, a.config.strict_evidence)
    elif format == "mermaid_asc":
        content = charts.mermaid_ancestors(t, id, generations, hidden)
    elif format == "mermaid_desc":
        content = charts.mermaid_descendants(t, id, generations, hidden)
    elif format == "svg_asc":
        content = charts.svg_ancestors(t, id, generations, hidden)
    elif format == "svg_desc":
        content = charts.svg_descendants(t, id, generations, hidden)
    else:
        content = fiche_markdown(t, id, a.config.strict_evidence, masquer_vivants)
    out = Path(chemin).expanduser() if chemin else a.config.exports_dir / (
        f"{id or 'arbre'}-{format}-{date.today().isoformat()}.{ext[format]}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    res = {"fichier": str(out), "format": format, "octets": len(content.encode("utf-8")),
           "vivants_masques": len(hidden), "apercu": content[:1500] if format.startswith(("mermaid", "fiche")) else None}
    if format == "geneweb":
        res["statistiques"] = stats
        res["import"] = f"ged2gwb {out.name} -o <base> -f   (voir docs/geneweb.md)"
    if format == "gramps":
        res["statistiques"] = stats
        res["import"] = ("Gramps Web : Paramètres > Administration > Importer (arbre vide : un second import "
                         "duplique tout)")
    return res


@mcp.tool()
def arbre_rapport_preuve(id: str, fait: str = "") -> str:
    """Trame de rapport de preuve (proof argument) pré-remplie : question, pièces avec citations complètes,
    recherches négatives du journal, analyse, contradictions, conclusion à rédiger, suite."""
    a = app()
    return proof_report(a.tree(), a.journal, id, fait, a.config.strict_evidence)


@mcp.tool()
def rapport_enregistrer(id: str, titre: str, contenu: str) -> dict:
    """Enregistre un rapport de preuve rédigé dans <données>/rapports/ et le commit (accord requis)."""
    import re as _re
    a = app()
    a.tree().person(id)
    slug = _re.sub(r"[^a-z0-9]+", "-", titre.lower()).strip("-")[:60] or "rapport"
    path = a.config.data_dir / "rapports" / f"{id}-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contenu, encoding="utf-8")
    commit = a.store.commit(f"Rapport de preuve : {titre} ({id})")
    return {"fichier": str(path), "commit": commit}


@mcp.tool()
def media_enregistrer(chemin: str, nom: str = "") -> dict:
    """Copie une image/un PDF d'acte dans <données>/medias/ (à lier ensuite via ajouter_media)."""
    src = Path(chemin).expanduser()
    if not src.is_file():
        return {"erreur": f"Fichier introuvable : {src}"}
    dest = app().config.media_dir / (nom or src.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return {"fichier": f"medias/{dest.name}", "chemin_absolu": str(dest)}


# ============================================================================ journal

@mcp.tool()
def journal_lister(source: str = "", personne: str = "", statut: str = "", texte: str = "", limite: int = 50) -> list[dict]:
    """Journal de recherche (requêtes, paramètres, date, résultats y compris négatifs)."""
    return app().journal.entries(source or None, personne or None, statut or None, texte or None, limite)


@mcp.tool()
def journal_ajouter(source: str, operation: str, statut: str, resume: str, parametres: dict | None = None,
                    personne: str = "", references: list[str] | None = None) -> dict:
    """Ajoute une entrée manuelle (consultation en salle d'archives, courrier, recherche négative…).
    statut : positif | negatif | erreur | manuel."""
    if statut not in ("positif", "negatif", "erreur", "manuel"):
        return {"erreur": "statut : positif | negatif | erreur | manuel"}
    return {"journal": app().journal.add(source, operation, parametres or {}, statut, resume=resume,
                                         references=references, personne=personne or None)}


@mcp.tool()
def cache_purger(source: str = "") -> dict:
    """Vide le cache SQLite (toutes sources ou une source : matchid, wikitree, gallica, wikidata, geo, cog)."""
    return {"supprimes": app().cache.purge(source or None), "restant": app().cache.stats()}


# ============================================================================ Gramps Web (backend alternatif)

def _gramps():
    from .sources.grampsweb import GrampsWeb
    return GrampsWeb(app().sctx)


@mcp.tool()
def gramps_recherche(texte: str, nombre: int = 20) -> dict:
    """Recherche de personnes dans Gramps Web (backend alternatif)."""
    try:
        return _gramps().search(texte, nombre)
    except Exception as exc:  # noqa: BLE001
        return {"erreur": str(exc)}


@mcp.tool()
def gramps_personne(handle: str) -> dict:
    """Profil d'une personne Gramps Web (handle)."""
    try:
        return _gramps().person(handle)
    except Exception as exc:  # noqa: BLE001
        return {"erreur": str(exc)}


@mcp.tool()
def gramps_tirer(mode: str = "remplacer") -> dict:
    """Exporte l'arbre Gramps Web en GEDCOM et prépare son import local (proposition à valider)."""
    try:
        text = _gramps().export_gedcom()
    except Exception as exc:  # noqa: BLE001
        return {"erreur": str(exc)}
    p = app().config.exports_dir / f"grampsweb-{date.today().isoformat()}.ged"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return arbre_importer_gedcom(str(p), mode)


@mcp.tool()
def gramps_pousser() -> dict:
    """Envoie l'arbre local (GEDCOM 5.5.1, vivants inclus : instance privée) vers Gramps Web. Écriture distante :
    exige l'accord explicite de l'utilisateur."""
    try:
        return _gramps().import_gedcom(write_gedcom(app().tree(), 5))
    except Exception as exc:  # noqa: BLE001
        return {"erreur": str(exc)}


# ============================================================================ point d'entrée

def main() -> None:
    parser = argparse.ArgumentParser(description="Serveur MCP genealogiste")
    parser.add_argument("--transport", choices=["stdio", "streamable-http", "sse"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--check", action="store_true", help="Vérifie la configuration et quitte")
    args = parser.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.check:
        a = app()
        print(json.dumps(arbre_info(), ensure_ascii=False, indent=2, default=str))
        print("WikiTree appId :", "défini" if a.config.wikitree_app_id else "ABSENT")
        return
    if args.transport != "stdio":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
