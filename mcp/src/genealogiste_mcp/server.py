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

from . import archives, coherence, evidence, matching, pieces, privacy
from .archives import communicability_online
from .auth import BearerAuth, bind_problem
from .cache import Cache
from .chemins import CheminRefuse, nom_simple, sous
from .config import Config, load_config
from .export import charts
from .export.fiche import fiche_markdown, gaps, tree_gaps
from .export.geneweb import to_geneweb
from .export.gramps_xml import to_gramps_xml_stats
from .export.rapport import proof_report
from .fr_sources import next_source_hint
from .gedcom.mapping import read_gedcom, write_gedcom
from .http import HttpClient
from .journal import Journal
from .normalize import dates as d
from .normalize.names import normalize_name, surname_similarity
from .normalize.places import normalize_place
from .notes import Notes, NotesError, touched
from .reseau import NetworkPolicy
from .sources import ark_resolver, familysearch, gallica, geo, iiif, liens, matchid, wikidata, wikitree
from .sources.base import SourceContext
from .tree.proposals import ProposalError, Proposals, TokenStore
from .tree.store import TreeStore, remote_problem

INSTRUCTIONS = """Assistant généalogique (méthode du Genealogical Proof Standard, sources françaises).
Règles : ne jamais inventer (donnée sans source = « non sourcée ») ; toute écriture dans l'arbre (fichier GEDCOM ou
Gramps Web selon le backend) passe par arbre_proposer (diff) puis arbre_appliquer UNIQUEMENT après accord explicite de
l'utilisateur ; une annulation aussi (arbre_annuler_modification puis arbre_appliquer) ; jamais de fusion
automatique ; rien sur les personnes vivantes vers l'extérieur ; chaque recherche est tracée au journal (y compris
négative) ; toujours indiquer la prochaine source à consulter pour un fait non confirmé."""

mcp = FastMCP("genealogiste", instructions=INSTRUCTIONS, log_level="WARNING")

RATE = {"deces.matchid.io": 1.0, "api.wikitree.com": 1.0, "gallica.bnf.fr": 1.0, "query.wikidata.org": 1.0,
        "geo.api.gouv.fr": 0.1}


class App:
    def __init__(self, config: Config | None = None, transport=None, sleeper=None, gramps_transport=None):
        self.config = config or load_config()
        self.cache = Cache(self.config.cache_path)
        kw = {"sleeper": sleeper} if sleeper else {}
        self.http = HttpClient(self.cache, self.config.user_agent, self.config.http_timeout, RATE,
                               offline=self.config.offline, transport=transport,
                               policy=NetworkPolicy(self.config.hotes_autorises), **kw)
        self.store = TreeStore(self.config.data_dir, self.config.git_remote)
        self.store.ensure()
        self.journal = Journal(self.config.journal_path)
        self.proposals = Proposals(self.store, self.config.proposals_dir, self.config.exiger_source)
        self.tokens = TokenStore(self.config.proposals_dir)
        self.sctx = SourceContext(self.http, self.journal, self.config)
        self.notes = Notes(self.config.notes_dir, self.config.notes_vivants, self.config.strict_evidence,
                           self.config.sosa_racine, self.journal, data_dir=self.config.data_dir)
        self._gramps_transport = gramps_transport
        self._gramps_sleeper = sleeper
        self._client = None
        self.backend = self.proposals
        if self.config.backend == "gramps":
            from .gramps.backend import GitMirror, GrampsBackend
            self.backend = GrampsBackend(self.gramps(), self.config.data_dir, self.config.proposals_dir,
                                         self.config.exiger_source, self.config.strict_evidence,
                                         self.config.gramps_ttl,
                                         GitMirror(self.store) if self.config.git_mirror else None,
                                         notes_auto=self.config.gramps_notes_auto,
                                         media_dir=self.config.pieces_root if self.config.media_dir_conf else None)

    def gramps(self):
        """Client Gramps Web (compte dédié, identifiants de l'environnement)."""
        if self._client is None:
            from .gramps.client import GrampsClient
            kw = {"sleeper": self._gramps_sleeper} if self._gramps_sleeper else {}
            self._client = GrampsClient(self.config.gramps_url, self.config.gramps_user, self.config.gramps_password,
                                        transport=self._gramps_transport, user_agent=self.config.user_agent, **kw)
        return self._client

    def tree(self):
        return self.backend.load() if self.config.backend == "gramps" else self.store.load()

    def refresh_notes(self, ids: list[str]) -> dict | None:
        """Hook : fiches de notes régénérées après une écriture ou une entrée de journal (jamais bloquant)."""
        if not (self.notes.enabled() and self.config.notes_auto and ids):
            return None
        tree = self.tree()
        out: dict = {"ecrites": [], "erreurs": []}
        for oid in dict.fromkeys(ids):
            try:
                r = self.notes.generate(tree, oid)
                out["ecrites"] += r["ecrites"]
                if r.get('alertes'):
                    out.setdefault('alertes', []).extend(r['alertes'])
            except (NotesError, KeyError, OSError) as exc:
                out["erreurs"].append(f"{oid} : {exc}")
        if 'alertes' in out:
            out['alertes'] = list(dict.fromkeys(out['alertes']))
        return out


_APP: App | None = None


def app() -> App:
    global _APP
    if _APP is None:
        _APP = App()
    return _APP


def set_app(a: App | None) -> None:
    global _APP
    _APP = a


def _garde(personne: str = "", nom: str = "", prenom: str = "", ne_vers: str = "", texte: str = "") -> dict | None:
    """Politique de sortie réseau (privacy.external_guard) : appelée par TOUT outil qui envoie des noms ou un
    identifiant de personne à un service externe (vérifié par test_outils)."""
    return privacy.external_guard(app().tree(), personne, nom, prenom, ne_vers, texte)


# ============================================================================ sources prioritaires

@mcp.tool()
def matchid_recherche(nom: str = "", prenom: str = "", ne_vers: str = "", lieu_naissance: str = "",
                      decede_vers: str = "", lieu_deces: str = "", sexe: str = "", texte: str = "",
                      taille: int = 20, page: int = 1, personne: str = "") -> dict:
    """Fichier des décès INSEE (depuis 1970) via matchID. Dates : '12/03/1920', '1920', 'vers 1920'
    (±2 ans). personne = id de l'arbre (journal). Résultats classés par score explicite."""
    return _garde(personne, nom, prenom, ne_vers, texte) or matchid.search(
        app().sctx, nom, prenom, ne_vers, lieu_naissance, decede_vers, lieu_deces, sexe, texte, taille, page,
        personne or None)


@mcp.tool()
def matchid_appariement_csv(chemin_csv: str, colonnes: dict, sep: str = ",", format_date: str = "",
                            candidats: int = 1) -> dict:
    """Appariement par lot matchID d'un CSV. colonnes = {firstName:'Prenom', lastName:'Nom', birthDate:'Naissance',
    birthCity:..., deathDate:...}. Peut exiger un jeton (GENEALOGISTE_MATCHID_TOKEN). Les lignes désignant une
    personne présumée vivante de l'arbre ne sont pas envoyées (lignes_exclues)."""
    t = app().tree()
    index = privacy.living_index(t)

    def exclure(c: dict) -> bool:
        nom = c.get("lastName", "") or c.get("legalName", "")
        return privacy.external_guard(t, nom=nom, prenom=c.get("firstName", ""), ne_vers=c.get("birthDate", ""),
                                      index=index) is not None

    return matchid.bulk_submit(app().sctx, chemin_csv, colonnes, sep, format_date, candidats, exclure)


@mcp.tool()
def matchid_appariement_statut(job: str, sortie: str = "") -> dict:
    """Statut / résultat d'un appariement par lot matchID. sortie (facultatif) : fichier .csv dans le
    répertoire de données (chemin relatif à celui-ci), où écrire le résultat ; ailleurs, refusé."""
    return matchid.bulk_status(app().sctx, job, sortie)


@mcp.tool()
def wikitree_recherche(nom: str, prenom: str = "", ne_vers: str = "", lieu: str = "", decede_vers: str = "",
                       limite: int = 20, personne: str = "") -> dict:
    """searchPerson WikiTree (arbre collaboratif = piste, source composite)."""
    return _garde(personne, nom, prenom, ne_vers) or wikitree.search(app().sctx, nom, prenom, ne_vers, lieu, decede_vers, limite,
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
    return _garde(personne, texte=texte) or gallica.search(app().sctx, texte, type_doc, titre, debut, fin, exact, nombre,
                                                     depart, personne or None)


@mcp.tool()
def gallica_recherche_document(ark: str, texte: str) -> dict:
    """Pages d'un document Gallica contenant le texte (ContentSearch) avec extraits et liens image."""
    return _garde(texte=texte) or gallica.search_in_document(app().sctx, ark, texte)


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
def ark_resoudre(ark: str, verifier: bool = True, titre: str = "") -> dict:
    """Identifiant pérenne ARK (seul ou dans une URL d'archives / Gallica) : service qui l'a attribué (NAAN),
    URL canonique et repli n2t.net, disponibilité (requête HEAD, aucun téléchargement), manifeste IIIF éventuel
    et citation suggérée (source = ressource ARK sans qualificatif, citation = ARK complet, vue)."""
    return ark_resolver.resolve(app().sctx, ark, verifier, titre)


@mcp.tool()
def archive_image(source: str, page: int = 0, region: str = "full", largeur: int = 800, gris: bool = True) -> dict:
    """Image d'acte par IIIF, à lire ensuite avec l'outil de lecture de fichiers. source : ARK Gallica, manifeste
    IIIF, info.json ou URL d'image IIIF (pour les AD : lien copié avec « Copier le lien IIIF » dans la
    visionneuse). Méthode économe : aperçu (largeur 800, gris) pour repérer l'acte, puis recadrage
    region='pct:x,y,l,h' en largeur 1500-2000 ; coût estimé en tokens renvoyé. Image téléchargée une seule fois
    (medias/iiif/). Pour Gallica, essayer d'abord le texte OCR (gallica_texte)."""
    return iiif.fetch(app().sctx, app().config.cache_images_dir, source, page, region, largeur, gris)


@mcp.tool()
def wikidata_personne(nom: str, prenom: str = "", ne_vers: str = "", lieu: str = "", limite: int = 20,
                      personne: str = "") -> dict:
    """Recherche d'une personnalité dans Wikidata (dates avec précision, lieux, parents)."""
    return _garde(personne, nom, prenom, ne_vers) or wikidata.search_person(app().sctx, nom, prenom, ne_vers, lieu,
                                                                             limite, personne or None)


@mcp.tool()
def wikidata_sparql(requete: str) -> dict:
    """Requête SPARQL en lecture seule sur query.wikidata.org."""
    return _garde(texte=requete) or wikidata.sparql(app().sctx, requete)


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
    refus = _garde(personne, nom, prenom, ne_vers)
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
def archives_service(lieu: str = "", departement: str = "", code: str = "", document: str = "",
                     annee: int = 0) -> dict:
    """Service d'archives réel (référentiel) d'un lieu, d'un département ou d'un code (AD59, AN, SHD, ANOM…) :
    site, visionneuse, NAAN ARK, ce qui est en ligne (document = naissance, mariage, deces, recensement,
    matricule… ; annee pour savoir si c'est en ligne ; None = inconnu), inscription, date de vérification."""
    return archives.service(lieu, departement, code, document, annee or None)


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
    """Ancien exporteur FamilySearch désactivé pour sécurité ; importer un GEDCOM obtenu séparément."""
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
def communicabilite(document: str, date_document: str = "", date_naissance: str = "", date_deces: str = "",
                    lieu: str = "", personne: str = "") -> dict:
    """Délai de communicabilité (Code du patrimoine) : naissance, mariage, deces, recensement, notaire, matricule,
    judiciaire, vie_privee, medical, cadastre, hypotheques, tables_decennales. Avec lieu : distingue
    « communicable » et « en ligne » (référentiel des archives) et propose sinon une demande avec modèle de courrier."""
    return communicability_online(document, date_document, date_naissance, date_deces, lieu, personne)


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
    out = {"backend": a.config.backend, "repertoire": str(a.config.data_dir), "personnes": len(t.personnes),
           "familles": len(t.familles), "sources": len(t.sources), "medias": len(t.medias),
           "vivants_presumes": len(privacy.living_ids(t)), "propositions_en_attente": a.backend.pending(),
           "mode_preuve": "strict" if a.config.strict_evidence else "pondéré", "avertissements": []}
    if a.config.backend == "gramps":
        out["gramps"] = a.backend.info()
        out["dernier_changement"] = (a.backend.history(1) or [{}])[0]
    else:
        out["fichier"] = str(a.store.path)
        out["dernier_commit"] = (a.store.log(1) or [{}])[0]
        if a.store.frozen():
            out["avertissements"].append("arbre.ged figé : bascule vers Gramps Web faite, passer GENEALOGISTE_BACKEND=gramps")
    if a.config.git_remote:
        out["depot_distant"] = a.store.last_push or "configuré"
        out["avertissements"].append(remote_problem(a.config.git_remote) or
                                     "Dépôt distant : il contient des personnes vivantes, il doit rester PRIVÉ.")
    return out


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
    hidden = privacy.hidden_ids(t)
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
    hidden = privacy.hidden_ids(t)
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
    """Historique des modifications de l'arbre (commits Git en mode fichier, transactions Gramps Web en mode
    gramps), avec justifications et sources. La référence sert à arbre_annuler_modification."""
    return app().backend.history(limite)


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
        return _gramps_guard(lambda: app().backend.propose(operations, titre, justification, sources))
    except ProposalError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def arbre_appliquer(jeton: str) -> dict:
    """Écrit une proposition (commit Git, ou transaction Gramps Web en mode gramps). À n'appeler qu'après accord
    EXPLICITE de l'utilisateur sur le diff présenté. Jeton à usage unique, refusé si l'arbre a changé (conflit
    avec une modification faite dans l'interface : recharger, reformuler, redemander l'accord)."""
    a = app()
    before = a.tree() if a.notes.enabled() and a.config.notes_auto else None
    try:
        res = _gramps_guard(lambda: a.backend.apply(jeton))
    except ProposalError as exc:
        return {"erreur": str(exc)}
    if before is not None and "erreur" not in res:
        if notes := a.refresh_notes(touched(before, a.tree())):
            res["notes"] = notes
    return res


@mcp.tool()
def arbre_annuler_proposition(jeton: str) -> dict:
    """Abandonne une proposition en attente."""
    return {"annulee": app().backend.cancel(jeton)}


@mcp.tool()
def arbre_annuler_modification(reference: str) -> dict:
    """Prépare l'annulation d'une modification déjà écrite (référence vue dans arbre_historique : commit en mode
    fichier, transaction en mode gramps). Renvoie un jeton : arbre_appliquer après accord explicite."""
    try:
        return _gramps_guard(lambda: app().backend.propose_undo(reference))
    except ProposalError as exc:
        return {"erreur": str(exc)}


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
        prop = app().backend.propose([{"op": "remplacer_arbre", "mode": mode, "gedcom_texte": write_gedcom(tree)}],
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
    Vivants et objets privés masqués par défaut (RGPD) : sources, médias et notes liés à une personne masquée
    retirés avec leurs références, noms remplacés par « Vivant » dans les textes. chemin par défaut :
    <données>/exports/."""
    a = app()
    t = a.tree()
    hidden: set[str] = set()
    rapport: dict = {}
    if masquer_vivants:
        t, hidden, rapport = privacy.publication(t)
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
    reste = privacy.residues(content, rapport.get("motifs", []))
    if reste:  # garde-fou : la projection a laissé passer une chaîne identifiante
        return {"erreur": "Export refusé : données identifiantes d'une personne masquée encore présentes "
                          f"({len(reste)} occurrence(s)). Rien n'a été écrit.", "occurrences": reste[:20]}
    out = Path(chemin).expanduser() if chemin else a.config.exports_dir / (
        f"{id or 'arbre'}-{format}-{date.today().isoformat()}.{ext[format]}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    res = {"fichier": str(out), "format": format, "octets": len(content.encode("utf-8")),
           "vivants_masques": len(hidden), "retires": rapport.get("retires"), "apercu": content[:1500] if format.startswith(("mermaid", "fiche")) else None}
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
    """Enregistre un rapport de preuve rédigé dans <données>/rapports/ (ou GENEALOGISTE_RAPPORTS_DIR) et le
    commit quand il est dans le répertoire de données (accord requis)."""
    import re as _re
    a = app()
    a.tree().person(id)
    slug = _re.sub(r"[^a-z0-9]+", "-", titre.lower()).strip("-")[:60] or "rapport"
    path = a.config.rapports_dir / f"{id}-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contenu, encoding="utf-8")
    if not path.resolve().is_relative_to(a.config.data_dir.resolve()):
        return {"fichier": str(path), "commit": None,
                "note": "Rapport hors du répertoire de données (GENEALOGISTE_RAPPORTS_DIR) : non versionné par Sosa."}
    rel = path.resolve().relative_to(a.config.data_dir.resolve()).as_posix()
    commit = a.store.commit(f"Rapport de preuve : {titre} ({id})", [rel])
    return {"fichier": str(path), "commit": commit}


@mcp.tool()
def media_enregistrer(chemin: str, nom: str = "", classer: bool = False) -> dict:
    """Copie une image/un PDF d'acte dans le répertoire des médias (<données>/medias/ ou GENEALOGISTE_MEDIA_DIR),
    à lier ensuite via ajouter_media. nom : nom de fichier simple, sans répertoire (convention : piece_nommer),
    rendu compatible Windows/Nextcloud ; un fichier existant au contenu différent n'est pas écrasé.
    classer=True : rangé selon la convention (documents/<type>/<PATRONYME>/, photographies/…, _À trier/)."""
    src = Path(chemin).expanduser()
    if not src.is_file():
        return {"erreur": f"Fichier introuvable : {src}"}
    cfg = app().config
    media_dir = cfg.media_dir
    media_dir.mkdir(parents=True, exist_ok=True)
    try:
        name = pieces.nom_compatible(nom_simple(nom or src.name))
        sub = (pieces.destination(pieces.detecter(Path(name))) or pieces.A_TRIER) if classer else ""
        dest = sous(cfg.pieces_root if classer else media_dir, Path(sub) / name)
    except CheminRefuse as exc:
        return {"erreur": str(exc)}
    if dest.exists() and dest.read_bytes() != src.read_bytes():
        return {"erreur": f"{cfg.media_ref(dest)} existe déjà avec un autre contenu : choisir un autre nom"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return {"fichier": cfg.media_ref(dest), "chemin_absolu": str(dest)}


@mcp.tool()
def piece_archiver(source: str, page: int = 0, personnes: list[str] | None = None, type_piece: str = "",
                   commune: str = "", depot: str = "", annees: str = "", cote: str = "", acte: str = "",
                   source_arbre: str = "", nom: str = "") -> dict:
    """Archive une vue d'acte dans le répertoire des médias (vault) : pleine résolution, couleur, nom selon la
    convention (docs/pieces.md), rangée dans documents/<type>/<NOM>/ (sinon _À trier), avec une note .md à côté
    (ARK, URL, vue, consultation, personnes, source : liens Obsidian). source : ARK Gallica, manifeste IIIF,
    info.json, URL d'image IIIF ou directe, ou fichier téléchargé depuis une visionneuse. personnes : I12 ou
    « NOM Prénom ». source_arbre (S3) : dépôt et cote repris de l'arbre. Une vue déjà archivée n'est jamais
    retéléchargée. Rien n'est écrit dans l'arbre : opérations suggérées pour arbre_proposer."""
    from . import archivage
    from .archives import by_code
    from .fichiers import ecrire_atomique
    from .http import SourceError

    a = app()
    cfg = a.config
    personnes = personnes or []
    try:
        t = a.tree()
        cle, loc = iiif.archive_key(a.sctx, source, page)
        hit = archivage.deja_archivee(cfg.pieces_registre, cle=cle)
        if hit:
            return {"deja_archivee": True, "fichier": hit["fichier"], "chemin_absolu": hit["chemin_absolu"],
                    "note": hit.get("note"), "suite": "Pièce déjà archivée : rien n'a été retéléchargé."}
        if source_arbre:
            s = t.sources[source_arbre]
            r = t.depots.get(s.depot)
            depot = depot or ((r.sigle or r.nom) if r else "")
            cote = cote or s.cote
        data, extra = iiif.full_image(a.sctx, source, loc)
        ext = iiif.extension_of(data)
        if not ext:
            return {"erreur": "Le contenu reçu n'est ni une image ni un PDF (page HTML ou accès refusé ?). "
                              + iiif.CONSIGNE_AD, "source": source}
        h = archivage.empreinte(data)
        vue = str(loc.get("vue") or page or "")
        labels = [_person_label(x) for x in personnes]
        nom_f = archivage.nom_piece(labels, ext, nom, commune=commune, depot=depot, type_piece=type_piece,
                                    annees=annees, cote=cote, vue=vue, acte=acte)
        meme = archivage.deja_archivee(cfg.pieces_registre, empreinte=h)
        if meme:
            dest, existe = Path(meme["chemin_absolu"]), True
        else:
            dest, existe = archivage.emplacement(cfg.pieces_root, nom_f, data)
        if not existe:
            ecrire_atomique(dest, data)
    except (iiif.IiifError, SourceError, KeyError, CheminRefuse, pieces.PieceError, OSError) as exc:
        return {"erreur": str(exc), "source": source}
    from . import ark as _ark
    a_ = _ark.find(source)
    service = by_code(depot) if depot else None
    reutil = ""
    if service:
        reutil = service.get("reutilisation") or (f"conditions à vérifier sur {service['site']}"
                                                  if service.get("site") else "")
    meta = {"ark": a_.id if a_ else "", "url": source if source.startswith(("http://", "https://")) else "",
            "url_image": extra.get("url_image", ""), "service_iiif": loc.get("service", ""),
            "manifeste": loc.get("manifeste", ""), "vue": int(vue) if vue.isdigit() else vue, "depot": depot,
            "cote": cote, "commune": commune, "type_piece": type_piece.upper(), "annees": annees, "acte": acte,
            "consulte_le": date.today().isoformat(), "sha256": h, "reutilisation": reutil}
    ids = [x for x in personnes if x in t.personnes]
    if a.notes.enabled():
        liens = [a.notes.link(t, "personne", x) if x in t.personnes else x for x in personnes]
        src_lien = a.notes.link(t, "source", source_arbre) if source_arbre in t.sources else ""
    else:
        liens, src_lien = labels, source_arbre
    note = archivage.note_compagnon(dest, meta, liens, src_lien)
    ref = cfg.media_ref(dest)
    archivage.enregistrer(cfg.pieces_registre, {"cle": cle, "sha256": h, "fichier": ref, "chemin_absolu": str(dest),
                                                "note": cfg.media_ref(note), "source": source, "vue": vue})
    a.journal.add(source="archives", operation="piece_archiver", parametres={"source": source, "vue": vue},
                  statut="positif", resume=ref, references=[x for x in (meta["ark"], source) if x],
                  personne=ids[0] if ids else None)
    citation = {"source": source_arbre or "<S… : créer la source d'abord>", "page": f"vue {vue}" if vue else "",
                "medias": ["$piece"], "consultation": "image"}
    if meta["ark"]:
        citation["ark"] = meta["ark"]
    out = {"fichier": ref, "chemin_absolu": str(dest), "note": cfg.media_ref(note), "deja_present": existe,
           "octets": len(data), "dossier": str(dest.parent.relative_to(cfg.pieces_root.resolve()))
           if dest.resolve().is_relative_to(cfg.pieces_root.resolve()) else str(dest.parent),
           "operations_suggerees": [{"op": "ajouter_media", "ref": "piece", "fichier": ref,
                                     "format": archivage.MIME.get(ext, ""), "titre": dest.stem, "lier_a": ids}],
           "citation_suggeree": citation,
           "suite": "Proposer via arbre_proposer : ajouter_media, puis ajouter_citation sur le fait prouvé "
                    "(cible evenement uid) avec citation_suggeree."}
    alertes = []
    if pieces.A_TRIER in dest.parts:
        alertes.append("Rangée dans _À trier : préciser personnes et type_piece pour le classement.")
    vivants = [x for x in ids if privacy.is_living(t, t.personnes[x])["vivant"]]
    if vivants:
        alertes.append(f"Personne(s) présumée(s) vivante(s) {vivants} : le nom du fichier contient son nom ; "
                       "pièce à garder hors de toute publication.")
    if reutil:
        alertes.append(f"Réutilisation : {reutil}.")
    if alertes:
        out["alertes"] = alertes
    return out


# ============================================================================ pièces (dossier existant, #60)

def _tree_media_paths() -> set[Path]:
    """Fichiers référencés par les médias de l'arbre (jamais déplacés par l'organisation)."""
    a = app()
    try:
        medias = a.tree().medias.values()
    except Exception:  # noqa: BLE001 — arbre indisponible : aucune référence connue
        return set()
    out = set()
    for m in medias:
        if m.fichier:
            p = Path(m.fichier).expanduser()
            out.add((p if p.is_absolute() else a.config.data_dir / p).resolve())
    return out


def _person_label(ref: str) -> str:
    """« I12 » -> « DUPONT Jean » (nom principal de l'arbre) ; tout autre texte est repris tel quel."""
    import re as _re
    if _re.fullmatch(r"I\d+", ref.strip()):
        n = app().tree().person(ref.strip()).noms[0]
        return f"{n.nom.upper()} {n.prenoms}".strip()
    return ref


@mcp.tool()
def piece_nommer(personnes: list[str], commune: str = "", depot: str = "", type_piece: str = "", annees: str = "",
                 cote: str = "", vue: str = "", acte: str = "", extension: str = ".jpg", source: str = "") -> dict:
    """Nom de fichier d'une pièce selon la convention (docs/pieces.md) :
    NOM Prénom[ + NOM Prénom] -- COMMUNE - DÉPÔT - TYPE [AAAA-AAAA] - cote - p.vue n.acte.ext
    personnes : « NOM Prénom » ou identifiants de l'arbre (I12). type_piece : N, B, M, D, S, NMD, BMS, TD, RM,
    ANMT, REC, SIGN, PHOTO… source (S3) : complète dépôt (sigle) et cote depuis l'arbre. Ne renomme rien."""
    try:
        noms = [_person_label(p) for p in personnes]
        if source:
            t = app().tree()
            s = t.sources[source]
            r = t.depots.get(s.depot)
            depot = depot or (r.sigle or r.nom if r else "")
            cote = cote or s.cote
        nom = pieces.nommer(noms, commune, depot, type_piece, annees, cote, vue, acte, extension)
    except (pieces.PieceError, KeyError) as exc:
        return {"erreur": f"{exc}"}
    info = pieces.detecter(Path(nom))
    return {"nom": nom, "dossier_convention": pieces.destination(info) or pieces.A_TRIER, "lecture": pieces.lire_nom(nom)}


def _dossier(dossier: str) -> Path:
    p = Path(dossier).expanduser().resolve()
    if not p.is_dir():
        raise pieces.PieceError(f"Dossier introuvable : {dossier}")
    if p == Path(p.anchor) or p == Path.home().resolve():
        raise pieces.PieceError("Refus : désigner le dossier de pièces lui-même, pas la racine ni le dossier personnel.")
    return p


@mcp.tool()
def pieces_inventaire(dossier: str) -> dict:
    """Inventaire d'un dossier de pièces existant (scans, photos, PDF, audio, GeneWeb/GEDCOM) : types déduits des
    noms, patronymes, doublons (SHA-256), fichiers ignorés. Lecture seule."""
    try:
        return pieces.inventaire(_dossier(dossier))
    except pieces.PieceError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def pieces_proposer(dossier: str, renommages: list[dict] | None = None, annuler: str = "",
                    apercu: int = 60) -> dict:
    """Plan de classement d'un dossier de pièces (rien n'est déplacé) : documents/<type>/<PATRONYME>/,
    photographies/…, archives/ (GeneWeb, GEDCOM, INSEE, Doublons), _À trier/. Jamais de suppression ; les
    notes Markdown, dossiers cachés et personnes/ familles/ sources/ ne sont pas touchés ; les médias liés à
    l'arbre ne sont pas déplacés. renommages : [{actuel, propose}] (agent trieur, piece_nommer) ; le fichier est
    reclassé d'après son nouveau nom. annuler : nom d'un journal _organisation/*.tsv à défaire. Renvoie un jeton
    pour pieces_appliquer, à n'utiliser qu'après accord explicite de l'utilisateur sur le plan."""
    a = app()
    try:
        racine = _dossier(dossier)
        plan = (pieces.plan_annulation(racine, annuler) if annuler
                else pieces.planifier(racine, renommages, _tree_media_paths()))
    except pieces.PieceError as exc:
        return {"erreur": str(exc)}
    moves = plan["deplacements"]
    if not moves:
        return {**{k: v for k, v in plan.items() if k not in ("empreintes", "deplacements")},
                "note": "Rien à déplacer."}
    jeton = TokenStore(a.config.proposals_dir).create({"type": "organisation", "dossier": str(racine), "plan": plan,
                                                      "resume": [f"{len(moves)} déplacement(s) dans {racine}"]})
    tsv = a.config.proposals_dir / f"plan-{jeton}.tsv"
    tsv.write_text("ancien_chemin\tnouveau_chemin\tmotif\n" + "".join(
        f"{m['de']}\t{m['vers']}\t{m['motif']}\n" for m in moves), encoding="utf-8")
    return {**{k: v for k, v in plan.items() if k not in ("empreintes", "deplacements")},
            "nb_deplacements": len(moves), "apercu": [f"{m['de']}  →  {m['vers']}  ({m['motif']})"
                                                      for m in moves[:apercu]],
            "plan_complet": str(tsv), "jeton": jeton,
            "consigne": "Présenter le plan (résumé par dossier, doublons, _À trier) et n'appeler pieces_appliquer "
                        "qu'après accord explicite de l'utilisateur."}


@mcp.tool()
def pieces_appliquer(jeton: str) -> dict:
    """Applique un plan de pieces_proposer validé par l'utilisateur : déplacements (jamais de suppression),
    journal TSV _organisation/<date>.tsv pour annuler, contrôle du nombre de fichiers et des empreintes."""
    a = app()
    store = TokenStore(a.config.proposals_dir)
    try:
        rec = store.take(jeton)
        if rec.get("type") != "organisation":
            return {"erreur": "Ce jeton n'est pas un plan d'organisation de pièces."}
        out = pieces.appliquer(Path(rec["dossier"]), rec["plan"])
    except (ProposalError, pieces.PieceError) as exc:
        return {"erreur": str(exc)}
    (a.config.proposals_dir / f"plan-{jeton}.tsv").unlink(missing_ok=True)
    return out


# ============================================================================ journal

@mcp.tool()
def journal_lister(source: str = "", personne: str = "", statut: str = "", texte: str = "", limite: int = 50) -> list[dict]:
    """Journal de recherche (requêtes, paramètres, date, résultats y compris négatifs). Des lignes illisibles
    (arrêt pendant une écriture) sont ignorées et signalées en tête de liste."""
    j = app().journal
    out = j.entries(source or None, personne or None, statut or None, texte or None, limite)
    if j.lignes_corrompues:
        out.insert(0, {"avertissement": f"journal.jsonl : ligne(s) illisible(s) ignorée(s) {j.lignes_corrompues[:20]}"
                                        " ; les autres entrées sont intactes."})
    return out


@mcp.tool()
def journal_ajouter(source: str, operation: str, statut: str, resume: str, parametres: dict | None = None,
                    personne: str = "", references: list[str] | None = None) -> dict:
    """Ajoute une entrée manuelle (consultation en salle d'archives, courrier, recherche négative…).
    statut : positif | negatif | erreur | manuel."""
    if statut not in ("positif", "negatif", "erreur", "manuel"):
        return {"erreur": "statut : positif | negatif | erreur | manuel"}
    out = {"journal": app().journal.add(source, operation, parametres or {}, statut, resume=resume,
                                        references=references, personne=personne or None)}
    if personne and (notes := app().refresh_notes([personne])):
        out["notes"] = notes
    return out


# ============================================================================ notes de recherche Markdown

def _notes(fn):
    try:
        return fn()
    except NotesError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def notes_generer(id: str = "tout") -> dict:
    """Crée ou met à jour les fiches Markdown (Obsidian) dans GENEALOGISTE_NOTES_DIR : personne, famille, source,
    patronyme (NOM) ou « tout » (+ patronymes/ et index.md). Seules les sections générées et le frontmatter sont réécrits ; le texte libre et les
    propriétés ajoutées à la main sont conservés ; régénérer sans changement ne modifie aucun fichier."""
    return _notes(lambda: app().notes.generate(app().tree(), id))


@mcp.tool()
def notes_lire(id: str) -> dict:
    """Fiche de notes d'une personne, famille ou source, texte libre compris (contexte pour l'agent ; générée si
    absente). Les notes ne modifient jamais l'arbre : arbre_proposer → accord → arbre_appliquer."""
    return _notes(lambda: app().notes.read(app().tree(), id))


@mcp.tool()
def notes_ajouter(id: str, texte: str, section: str = "note") -> dict:
    """Ajoute une entrée datée dans le texte libre d'une fiche, sous la section hypothese | piste | conclusion |
    courrier | a_faire | note (piste, conclusion, courrier envoyé…)."""
    return _notes(lambda: app().notes.add(app().tree(), id, texte, section))


@mcp.tool()
def cache_purger(source: str = "") -> dict:
    """Vide le cache SQLite (toutes sources ou une source : matchid, wikitree, gallica, wikidata, geo, cog)."""
    return {"supprimes": app().cache.purge(source or None), "restant": app().cache.stats()}


# ============================================================================ Gramps Web

def _gramps_guard(fn):
    from .gramps.client import GrampsError
    try:
        return fn()
    except GrampsError as exc:
        return {"erreur": str(exc)}


def _profile(t, pid: str) -> dict:
    p = t.personnes[pid]
    living = privacy.is_living(t, p)
    birth = next(iter(p.events("BIRT", "CHR", "BAPM")), None)
    death = next(iter(p.events("DEAT", "BURI")), None)
    return {"id": pid, "nom": p.nom_principal.complet, "naissance": birth.date if birth else "",
            "deces": death.date if death else "", "vivant": living["vivant"]}


@mcp.tool()
def gramps_recherche(texte: str, nombre: int = 20) -> dict:
    """Recherche plein texte de personnes dans Gramps Web (index du serveur)."""
    def run():
        hits = app().gramps().search(texte, nombre)
        out = [{"handle": h.get("handle"), "gramps_id": (h.get("object") or {}).get("gramps_id"),
                "type": h.get("object_type")} for h in hits if h.get("object_type") == "person"]
        app().journal.add("grampsweb", "search", {"texte": texte}, "positif" if out else "negatif",
                          nb_resultats=len(out))
        return {"source": "grampsweb", "resultats": out}
    return _gramps_guard(run)


@mcp.tool()
def gramps_personne(handle: str) -> dict:
    """Personne Gramps Web (handle) lue avec la correspondance Sosa (id, noms, faits, statut de preuve)."""
    def run():
        from .gramps.mapping import gramps_to_tree
        db = app().gramps().load_all() if app().config.backend != "gramps" else app().backend.snapshot(fresh=False)
        p = db.get("Person", handle)
        if not p:
            return {"erreur": f"Personne Gramps inconnue : {handle}"}
        t = gramps_to_tree(db)[0]
        pid = p["gramps_id"]
        data = _profile(t, pid)
        data["faits"] = evidence.assess_person(t, pid, app().config.strict_evidence)
        return data
    return _gramps_guard(run)


@mcp.tool()
def gramps_tirer(mode: str = "remplacer") -> dict:
    """Mode fichier : lit l'arbre Gramps Web (API, correspondance complète) et prépare son import dans l'arbre
    local (proposition à valider). Pas de synchronisation bidirectionnelle : pour travailler en direct sur
    Gramps Web, utiliser GENEALOGISTE_BACKEND=gramps."""
    def run():
        from .gramps.mapping import gramps_to_tree
        if app().config.backend == "gramps":
            return {"erreur": "Backend gramps actif : l'arbre Gramps Web est déjà l'arbre de travail."}
        tree, _ = gramps_to_tree(app().gramps().load_all())
        p = app().config.exports_dir / f"grampsweb-{date.today().isoformat()}.ged"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(write_gedcom(tree), encoding="utf-8")
        return arbre_importer_gedcom(str(p), mode)
    return _gramps_guard(run)


@mcp.tool()
def gramps_bascule_proposer() -> dict:
    """Bascule du mode fichier vers Gramps Web : prépare l'envoi de tout arbre.ged (vivants inclus : instance
    privée) dans un arbre Gramps Web VIDE, en une transaction. Renvoie un bilan et un jeton à valider."""
    from .gramps.backend import bascule_preview
    try:
        return _gramps_guard(lambda: bascule_preview(app().gramps(), app().store, app().tokens,
                                                     app().config.strict_evidence,
                                                     app().config.gramps_notes_auto != "false"))
    except ProposalError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def gramps_bascule_appliquer(jeton: str) -> dict:
    """Exécute la bascule après accord EXPLICITE : écrit l'arbre dans Gramps Web, fige arbre.ged (dernier commit
    « Bascule vers Gramps Web ») ; journal.jsonl reste local. Ensuite : GENEALOGISTE_BACKEND=gramps."""
    from .gramps.backend import bascule_apply
    try:
        return _gramps_guard(lambda: bascule_apply(app().gramps(), app().store, app().tokens, jeton))
    except ProposalError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def gramps_recalculer_notes() -> dict:
    """Mode gramps : prépare le recalcul des notes et étiquettes de preuve générées (Sosa:auto), par ex. après
    des modifications faites dans l'interface. Les notes manuelles ne sont jamais touchées. Jeton à valider."""
    if app().config.backend != "gramps":
        return {"erreur": "Disponible en mode gramps (GENEALOGISTE_BACKEND=gramps)."}
    try:
        return _gramps_guard(app().backend.propose_notes)
    except ProposalError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def gramps_structurer_lieux() -> dict:
    """Mode gramps : prépare le rattachement des lieux à plat (titre « Commune, Département, Pays ») à une
    hiérarchie Gramps (commune → département → pays, lieux englobants réutilisés ou créés, code du département).
    Noms relus identiques, événements inchangés. Jeton à valider (diff, puis accord explicite)."""
    if app().config.backend != "gramps":
        return {"erreur": "Disponible en mode gramps (GENEALOGISTE_BACKEND=gramps)."}
    try:
        return _gramps_guard(app().backend.propose_places)
    except ProposalError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def gramps_envoyer_medias(appliquer: bool = False) -> dict:
    """Mode gramps : fichiers des médias (images d'actes de <données>/medias/) absents ou différents dans Gramps
    Web (somme MD5). appliquer=False : liste seulement ; appliquer=True, après accord explicite de
    l'utilisateur sur la liste : envoi (PUT /media/{handle}/file). Les médias d'une proposition acceptée sont
    envoyés automatiquement avec elle (fichiers_a_envoyer)."""
    if app().config.backend != "gramps":
        return {"erreur": "Disponible en mode gramps (GENEALOGISTE_BACKEND=gramps)."}
    return _gramps_guard(app().backend.media_send if appliquer else app().backend.media_status)


@mcp.tool()
def gramps_synchroniser() -> dict:
    """Mode gramps : relit les modifications faites dans Gramps Web depuis la dernière lecture (incrémental) ;
    avec le miroir Git, les commite (« Modifications externes »)."""
    if app().config.backend != "gramps":
        return {"erreur": "Disponible en mode gramps (GENEALOGISTE_BACKEND=gramps)."}

    def run():
        b = app().backend
        b.snapshot(fresh=True)
        return {"modifications": b.last_refresh, "objets": b.db.count(), "miroir_git": bool(b.mirror)}
    return _gramps_guard(run)


# ============================================================================ point d'entrée

def main() -> None:
    import os

    # Arbres, caches et journaux nouvellement créés restent privés sur l'hôte.
    os.umask(0o077)
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
    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return
    import uvicorn
    load_config()  # charge aussi le .env privé avant de lire les réglages du transport
    token = os.environ.get("MCP_TOKEN", "")
    if problem := bind_problem(args.host, token, os.environ.get("MCP_SANS_AUTH", "")):
        raise SystemExit(problem)
    mcp.settings.host, mcp.settings.port = args.host, args.port
    asgi = mcp.streamable_http_app() if args.transport == "streamable-http" else mcp.sse_app()
    if token:
        asgi = BearerAuth(asgi, token)
    uvicorn.run(asgi, host=args.host, port=args.port, log_level=mcp.settings.log_level.lower())


if __name__ == "__main__":
    main()
