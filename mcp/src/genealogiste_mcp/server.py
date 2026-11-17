"""Serveur MCP « genealogiste » (MCPServer) : sources, normalisation, preuve, arbre GEDCOM versionné."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import date
from pathlib import Path
from typing import Any

from . import (
    archivage,
    archives,
    ark,
    coherence,
    erreurs,
    evidence,
    matching,
    menage,
    outils,
    pieces,
    privacy,
)
from . import pdf_markdown as pdf_md
from .archives import communicability_online
from .auth import BearerAuth, Sante, bind_problem
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
from .http import HttpClient, SourceError
from .journal import Journal
from .normalize import dates as d
from .normalize.names import normalize_name, surname_similarity
from .normalize.places import normalize_place
from .notes import Notes, NotesError, touched
from .reseau import NetworkPolicy
from .serveur_mcp import ServeurMCP
from .sources import (
    ark_resolver,
    familysearch,
    gallica,
    geo,
    iiif,
    liens,
    matchid,
    planche,
    registres,
    visionneuses,
    wikidata,
    wikitree,
)
from .sources.base import SourceContext, error_envelope
from .tree.proposals import ProposalError, Proposals, TokenStore
from .tree.store import TreeStore, remote_problem

INSTRUCTIONS = """Assistant généalogique (méthode du Genealogical Proof Standard, sources françaises).
Règles : ne jamais inventer (donnée sans source = « non sourcée ») ; toute écriture dans l'arbre (fichier GEDCOM ou
Gramps Web selon le backend) passe par arbre_proposer (diff) puis arbre_appliquer UNIQUEMENT après accord explicite de
l'utilisateur ; une annulation aussi (arbre_annuler_modification puis arbre_appliquer) ; jamais de fusion
automatique ; rien sur les personnes vivantes vers l'extérieur ; chaque recherche est tracée au journal (y compris
négative) ; toujours indiquer la prochaine source à consulter pour un fait non confirmé."""

mcp = ServeurMCP("genealogiste", instructions=INSTRUCTIONS, log_level="WARNING")

RATE = {"deces.matchid.io": 1.0, "api.wikitree.com": 1.0, "gallica.bnf.fr": 1.0, "query.wikidata.org": 1.0,
        "geo.api.gouv.fr": 0.1}


class App:
    def __init__(self, config: Config | None = None, transport=None, sleeper=None, gramps_transport=None):
        self.config = config or load_config()
        self.cache = Cache(self.config.cache_path, max_octets=int(self.config.cache_max_mo * menage.MO))
        self.cache.borner()
        menage.borner_images(self.config)
        kw = {"sleeper": sleeper} if sleeper else {}
        intervalles = {**RATE, **archives.intervalles(), **self.config.debits}  # env > référentiel > code
        self.http = HttpClient(self.cache, self.config.user_agent, self.config.http_timeout, intervalles,
                               offline=self.config.offline, transport=transport,
                               policy=NetworkPolicy(self.config.hotes_autorises),
                               default_interval=self.config.debit_defaut,
                               max_retries=self.config.http_tentatives, duree_max=self.config.http_duree_max,
                               echec_ttl=self.config.cache_echec, coupe_circuit_ttl=self.config.coupe_circuit, **kw)
        self.store = TreeStore(self.config.data_dir, self.config.git_remote, self.config.git_delai)
        self.store.ensure()
        self.journal = Journal(self.config.journal_path)
        self.proposals = Proposals(self.store, self.config.proposals_dir, self.config.exiger_source,
                                   self.config.media_reference)
        self.tokens = TokenStore(self.config.proposals_dir)
        import threading
        self._verrou_gramps = threading.RLock()
        self._executeur_notes = None
        self._notes_futurs: list = []
        self.notes_etats: dict[str, dict] = {}  # jeton -> état de la régénération différée des notes
        self.tokens.purger_expirees()
        self.sctx = SourceContext(self.http, self.journal, self.config)
        self.notes = Notes(self.config.notes_dir, self.config.notes_vivants, self.config.strict_evidence,
                           self.config.sosa_racine, self.journal, data_dir=self.config.data_dir,
                           kit=self.config.notes_kit)
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
                                         media_dir=self.config.pieces_root if self.config.media_dir_conf else None,
                                         media=self.config.media_reference)

    def gramps(self):
        """Client Gramps Web (compte dédié, identifiants de l'environnement)."""
        if self._client is None:
            from .gramps.client import GrampsClient
            kw = {"sleeper": self._gramps_sleeper} if self._gramps_sleeper else {}
            self._client = GrampsClient(self.config.gramps_url, self.config.gramps_user, self.config.gramps_password,
                                        transport=self._gramps_transport, user_agent=self.config.user_agent, **kw)
        return self._client

    def tree(self):
        if self.config.backend == "gramps":
            with self._verrou_gramps:  # instantané partagé : lectures parallèles sans écriture concurrente
                return self.backend.load()
        return self.store.load()

    def regenerer_notes_differe(self, jeton: str, ids: list[str]) -> dict:
        """Régénération des notes dans un fil dédié (une à la fois), après une écriture : l'outil répond dès la
        transaction validée. Attend au plus GENEALOGISTE_NOTES_ATTENTE ; au-delà, état « en_cours » consultable
        par arbre_statut_transaction(jeton)."""
        import time
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as Delai

        etat = {"etat": "en_cours", "objets": len(dict.fromkeys(ids)), "debut": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.notes_etats[jeton] = etat
        if self._executeur_notes is None:
            self._executeur_notes = ThreadPoolExecutor(max_workers=1, thread_name_prefix="notes")

        def travail():
            try:
                r = self.refresh_notes(ids) or {"ecrites": [], "erreurs": []}
                etat.update(r, etat="terminee" if not r.get("erreurs") else "terminee_avec_erreurs")
            except Exception as exc:  # noqa: BLE001 — l'écriture est faite ; seul l'état des notes échoue
                etat.update(etat="echec", erreurs=[str(exc)])
            etat["fin"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            return etat

        futur = self._executeur_notes.submit(travail)
        self._notes_futurs.append(futur)
        try:
            futur.result(timeout=self.config.notes_attente)
        except Delai:
            pass
        out = dict(etat)
        if out["etat"] == "en_cours":
            out["suivi"] = (f"Régénération des notes en arrière-plan ({out['objets']} objets) ; l'écriture est faite. "
                            f"Suivre avec arbre_statut_transaction(\"{jeton}\").")
        return out

    def attendre_notes(self, delai: float | None = None) -> None:
        """Attend la fin des régénérations en cours (tests, arrêt propre)."""
        for futur in list(self._notes_futurs):
            futur.result(timeout=delai)
        self._notes_futurs.clear()

    def refresh_notes(self, ids: list[str]) -> dict | None:
        """Hook : fiches de notes régénérées après une écriture ou une entrée de journal (jamais bloquant)."""
        if not (self.notes.enabled() and self.config.notes_auto and ids):
            return None
        tree = self.tree()
        out: dict = {"ecrites": [], "erreurs": []}
        try:  # un seul lot : coût linéaire en nombre de fiches touchées (#151)
            r = self.notes.generate(tree, list(dict.fromkeys(ids)))
        except (NotesError, KeyError, OSError) as exc:
            out["erreurs"].append(str(exc))
            return out
        out["ecrites"] = r["ecrites"]
        out["erreurs"] = r.get("erreurs", [])
        if r.get("renommees"):
            out["renommees"] = r["renommees"]
        if r.get('alertes'):
            out['alertes'] = list(dict.fromkeys(r['alertes']))
        return out


_APP: App | None = None


_INIT = __import__("threading").Lock()


def app() -> App:
    global _APP
    if _APP is None:
        with _INIT:  # des outils de lecture peuvent arriver en parallèle au premier appel
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

class _Observateur:
    """Journal d'exploitation (#149) : n'initialise jamais l'App ; les appels faits avant une App valide ne sont
    tracés que sur stderr (interception #146)."""

    def avant(self, outil: str = ""):
        import time

        # Les outils sans verrou (lecture, sans réseau) tournent en parallèle : ne pas vider le relevé d'hôtes
        # d'un appel sérialisé en cours.
        if _APP is not None and outil not in mcp.sans_verrou:
            _APP.http.hotes_contactes.clear()
        return time.monotonic()

    def apres(self, debut, outil: str, arguments: dict, resultat=None, exception=None) -> None:
        from . import exploitation

        if _APP is None:
            return
        statut, erreur = "ok", ""
        if exception is not None:
            statut = "exception"
        elif resultat is not None:
            contenu = resultat.structured_content if isinstance(resultat.structured_content, dict) else {}
            if not contenu and resultat.content:
                try:
                    contenu = json.loads(getattr(resultat.content[0], "text", "") or "{}")
                except ValueError:
                    contenu = {}
            if not isinstance(contenu, dict):
                contenu = {}
            contenu = contenu.get("result", contenu) if isinstance(contenu.get("result"), dict) else contenu
            if resultat.is_error or "erreur" in contenu or "refus" in contenu:
                statut = "erreur"
                erreur = str(contenu.get("erreur") or contenu.get("refus") or "")
                if not erreur and resultat.content:
                    erreur = getattr(resultat.content[0], "text", "")
        exploitation.enregistrer(_APP.config, outil, debut, statut, arguments, erreur, exception,
                                 [] if outil in mcp.sans_verrou else list(_APP.http.hotes_contactes))


mcp.observateur = _Observateur()
# Outils de lecture pure (catalogue) : servis sans attendre une écriture en cours (#151).
mcp.sans_verrou = {nom for nom, (effet, _) in outils.OUTILS.items() if effet == outils.LECTURE}


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
    a = app()
    try:
        return ark_resolver.resolve(a.sctx, ark, verifier, titre)
    except SourceError as exc:
        return error_envelope(a.sctx, "ark", "resoudre", {"ark": ark, "verifier": verifier}, exc)


@mcp.tool()
def archive_image(source: str, page: int = 0, region: str = "full", largeur: int = 800, gris: bool = True,
                  details: bool = False) -> dict:
    """Aperçu économe d'une vue : lien IIIF (tous pays), ARK Gallica ou visionneuse AD59, image directe,
    fichier local. Les pages qui déclarent un manifeste IIIF sont résolues côté Python, sans HTML envoyé
    au modèle. D'abord largeur 800/gris, puis region='pct:x,y,l,h' pour l'acte seul ; coût indicatif renvoyé.
    Réutilise le cache d'originale pour recadrer et archiver. Un ARK seul ne garantit pas le téléchargement.
    Pour conserver la pleine résolution : piece_archiver. Pour Gallica, essayer d'abord l'OCR.

    Sortie minimale : chemin_absolu (à lire avec l'outil de lecture de fichiers), vue, nb_vues, ark_vue,
    dimensions et coût estimé, registre. Cote, titre, commune et période du registre ne sont donnés qu'au
    premier aperçu de ce registre dans la session, ou avec details=true. La licence et les conditions de
    réutilisation ne sont jamais renvoyées ici : elles sont conservées par piece_archiver (note compagnon).
    Consigne : aperçu d'abord (≈ 800 px, gris) pour repérer l'acte, puis recadrer l'acte seul
    (region pct:x,y,l,h, largeur 1500-2000). Transcription produite par le modèle : à marquer comme telle
    et à faire vérifier."""
    out = iiif.fetch(app().sctx, app().config.cache_images_dir, source, page, region, largeur, gris)
    return iiif.sortie_minimale(app().sctx, out, details)


@mcp.tool()
def pdf_markdown(chemin: str, langue: str = "fra", forcer_ocr: bool = False, reconvertir: bool = False) -> dict:
    """PDF dactylographié ou imprimé (texte natif ou scan) → un fichier Markdown compact, une section par page,
    titres et tableaux conservés : bien moins de tokens que les pages en images. Texte natif extrait sans OCR ;
    scan : OCR Tesseract (langue='fra' par défaut, 'fra+lat'…). Résultat en cache (clé = empreinte du PDF) :
    jamais reconverti s'il n'a pas changé. Lire ensuite le fichier chemin_absolu. Les pages listées dans
    pages_a_lire_en_image (manuscrit, OCR absent ou peu fiable) se lisent avec archive_image(chemin, page=n).
    Si « installation » est présent (Tesseract ou langue absents), proposer d'abord la commande à l'utilisateur."""
    try:
        return pdf_md.convertir(chemin, app().config.cache_pdf_dir, langue, forcer_ocr, reconvertir,
                                app().config.tesseract)
    except pdf_md.PdfErreur as e:
        return {"erreur": str(e)}


@mcp.tool()
def archives_planche(source: str, de: int, a: int = 0, pas: int = 1, bandeau: str = "", largeur: int = 1200,
                     gris: bool = True, miniatures: bool = False) -> dict:
    """Planche-contact d'un registre AD59 : UNE image composite de 4 à 12 vues (numéro de vue incrusté) pour
    repérer l'acte sans lire une image par vue. source : ARK de registre ou de vue AD59. de/a : première et
    dernière vue (a = 0 : six vues) ; pas : une vue sur N (sondage large, puis planche fine). bandeau : ne garder
    que le haut de chaque vue (ex. pct:0,0,100,35) pour lire date et numéro d'acte dans la grille.
    Limites : 12 vues et 1 600 px par planche ; une requête et un téléchargement par vue (originales en cache,
    partagé avec archive_image et piece_archiver), arrêt à la première erreur ou protection, aucun
    contournement. miniatures=true : miniatures du service (100 px), pour la mise en page seulement.
    Renvoie chemin_absolu (à lire avec l'outil de lecture de fichiers), vues, grille et cout_estime_tokens.
    Repérée la vue, lire l'acte avec archive_image (region), puis piece_archiver."""
    return planche.planche(app().sctx, source, de, a, pas, bandeau, largeur, gris, miniatures)


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
    matricule… ; préciser lieu pour les exceptions communales et annee ; None = inconnu), inscription,
    date de vérification et couverture sourcée. Un accès déclaré ne prouve pas l'existence d'un acte.
    consultation_manuelle : protection anti-robot relevée (ex. Anubis) et consigne (vue fournie par
    l'utilisateur, media_enregistrer) ; un nouvel essai réseau reste possible."""
    return archives.service(lieu, departement, code, document, annee or None)


@mcp.tool()
def archives_registres(service: str, commune: str, annee: int, type_acte: str = "", page: int = 1,
                      personne: str = "") -> dict:
    """Localiser un registre par commune et année, sans connaître son ARK : service=AD59 uniquement.
    type_acte : N (naissance), M (mariage), D (décès), NMD ou vide (tous). Une seule page de résultats
    par appel ; page_suivante permet de poursuivre explicitement. Cote, ARK et période proviennent du
    résultat officiel ; une recherche vide ne prouve pas l'absence de l'acte. personne désigne seulement
    la cible locale, pour la garde des vivants et le journal ; cet identifiant n'est pas envoyé au service."""
    if refus := _garde(personne=personne, texte=commune):
        return refus
    a = app()
    try:
        return registres.rechercher(a.sctx, service, commune, annee, type_acte, page, personne)
    except (SourceError, ValueError) as exc:
        return error_envelope(a.sctx, "archives", "registres",
                              {"service": service, "commune": commune, "annee": annee,
                               "type_acte": type_acte, "page": page}, exc, personne=personne or None)


@mcp.tool()
def archives_naviguer(source: str, page: int = 0, pas: int = 20) -> dict:
    """Parcourir les vues d'un registre d'archives sans connaître la vue à l'avance : renvoie une fenêtre de
    vues (numéro, ARK de vue, image) et les métadonnées du registre (titre, cote, commune, période, nombre
    de vues). source : ARK de registre ou de vue AD59 (visionneuse reconnue), ARK Gallica ou manifeste IIIF.
    page : première vue à lister (1 = début) ; pas : taille de fenêtre (1-100). Ensuite archive_image ou
    piece_archiver sur une vue choisie. nb_vues indique le total ; fin_de_registre signale la dernière fenêtre
    et vue_suivante son prochain début (None en fin). Hors bornes : erreur avec les numéros valides.
    Une navigation produit une entrée au journal, y compris depuis le cache.
    Ne localise pas un acte à partir d'un nom (voir la recherche du
    service, liens_recherche/cotes_a_consulter pour trouver le registre)."""
    a = app()
    params = {"source": source, "page": page, "pas": pas}
    try:
        res = visionneuses.naviguer(a.sctx, source, page, pas)
        if res is None:
            ark_obj = ark.find(source)
            manifeste = (f"https://gallica.bnf.fr/iiif/{ark_obj.base}/manifest.json"
                         if ark_obj and ark_obj.naan == "12148" else source)
            res = iiif.naviguer(a.sctx, manifeste, page, pas)
        res["journal"] = a.journal.add(source="archives", operation="naviguer", parametres=params,
                                       statut="positif", nb_resultats=len(res["vues"]),
                                       resume=res["registre"].get("titre", ""), references=[source],
                                       cache=res["depuis_cache"])
        return res
    except (SourceError, ValueError) as exc:  # VisionneuseError et IiifError sont des ValueError
        out = error_envelope(a.sctx, "archives", "naviguer", params, exc)
        if out.get("statut") != "bloque_antirobot":
            out["conseil"] = ("Vérifier l'ARK ou l'URL du registre (archives_service pour la visionneuse du service) ; "
                              "sinon ouvrir le registre dans le navigateur (liens_recherche, cotes_a_consulter).")
        return out


@mcp.tool()
def diagnostic(reseau: bool = True) -> dict:
    """Diagnostic d'exploitation : tableau « contrôle, état (ok/attention/erreur), détail, remède » —
    version du serveur et du plugin sur disque, configuration effective (sans secret), git, uv, droits,
    espace disque, taille des caches, OCR, propositions en attente/expirées, et si reseau=True la
    joignabilité de chaque source (verdict joignable/protection/injoignable, une requête par source, tracée
    au journal) et de Gramps Web. Fonctionne même si la configuration est invalide."""
    from . import diagnostic as diag

    try:
        a = app()
    except Exception as exc:  # noqa: BLE001 — rapporté comme contrôle « configuration »
        return diag.executer(exc, verifier_demarrage(), reseau)
    return diag.executer(a, verifier_demarrage(a.config), reseau)


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
    judiciaire (alias justice), vie_privee, medical, cadastre, hypotheques, tables_decennales.
    Paroissiaux, enregistrement et insinuation : régime à préciser, réponse inconnue sans délai inventé.
    Les pluriels recensements, notaires et matricules sont acceptés. Avec lieu : distingue
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
    from . import diagnostic as diag
    out["version_serveur"] = diag.version_serveur()
    version_plugin, _ = diag.version_plugin()
    if version_plugin:
        out["version_plugin"] = version_plugin
    if ecart := diag.ecart_version():
        out["avertissements"].append(ecart)
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
    ajouter_source, modifier_source, ajouter_depot, ajouter_citation, ajouter_media, modifier_media, ajouter_association,
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
        if ids := touched(before, a.tree()):
            res["notes"] = a.regenerer_notes_differe(jeton, ids)
    return res


@mcp.tool()
def arbre_statut_transaction(jeton: str) -> dict:
    """État d'une écriture par son jeton, utilisable même pendant une écriture longue : en_attente (proposition
    non appliquée), appliquee (commit, ou transaction Gramps Web terminée), en_cours / echec côté Gramps, ou
    inconnue (jeton expiré, annulé ou erroné) ; plus l'état de la régénération différée des notes. À consulter
    après un délai dépassé sur arbre_appliquer avant toute nouvelle tentative."""
    a = app()
    out: dict = {"jeton": jeton}
    if a.config.backend == "gramps":
        etapes = [e for e in a.backend.transactions(10_000) if e.get("id") == jeton]
        if etapes:
            dernier = etapes[-1].get("etat", "")
            out["etat"] = {"terminee": "appliquee", "complements_en_echec": "appliquee",
                           "envoyee": "en_cours", "intention": "en_cours", "refusee": "echec",
                           "indeterminee": "indeterminee"}.get(dernier, dernier)
            out["transaction"] = etapes[-1]
    else:
        commits = [c for c in a.store.log(200) if f"(proposition {jeton})" in c.get("message", "")]
        if commits:
            out.update(etat="appliquee", commit=commits[0]["commit"], date=commits[0]["date"])
    if "etat" not in out:
        out["etat"] = "en_attente" if a.tokens._path(jeton).exists() else "inconnue"
    if jeton in a.notes_etats:
        out["notes"] = dict(a.notes_etats[jeton])
    return out


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
                "note": "Rapport hors du répertoire de données (GENEALOGISTE_RAPPORTS_DIR) : non versionné par Genealogiste."}
    rel = path.resolve().relative_to(a.config.data_dir.resolve()).as_posix()
    commit = a.store.commit(f"Rapport de preuve : {titre} ({id})", [rel])
    return {"fichier": str(path), "commit": commit}


@mcp.tool()
def media_enregistrer(chemin: str, nom: str = "", classer: bool = False) -> dict:
    """Copie une image/un PDF d'acte dans le répertoire des médias (<données>/medias/ ou GENEALOGISTE_MEDIA_DIR),
    à lier ensuite via ajouter_media. nom : nom de fichier simple, sans répertoire (convention : piece_nommer),
    rendu compatible Windows/Nextcloud ; un fichier existant au contenu différent n'est pas écrasé.
    classer=True : rangé selon la convention (documents/<type>/<PATRONYME>/, photographies/…, _À trier/).
    reference_media : valeur exacte à passer à ajouter_media (fichier)."""
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
    ref = cfg.media_ref(dest)
    return {"fichier": ref, "chemin_absolu": str(dest), "reference_media": ref}


@mcp.tool()
def piece_archiver(source: str, page: int = 0, personnes: list[str] | None = None, type_piece: str = "",
                   commune: str = "", depot: str = "", annees: str = "", cote: str = "", acte: str = "",
                   source_arbre: str = "", nom: str = "", nom_fichier: str = "") -> dict:
    """Archive une vue d'acte dans le répertoire des médias (vault) : pleine résolution, couleur, nom selon la
    convention (docs/pieces.md), rangée dans documents/<type>/<NOM>/ (sinon _À trier), avec une note .md à côté
    (ARK, URL, vue, consultation, personnes, source : liens Obsidian). source : ARK Gallica, manifeste IIIF,
    info.json, URL d'image IIIF ou directe, lien de visionneuse AD59 ou fichier local. nom_fichier : nom complet
    facultatif suivant la convention, jamais un patronyme seul (nom est un ancien alias). personnes : I12 ou
    « NOM Prénom ». source_arbre (S3) : dépôt et cote repris de l'arbre. Une vue déjà archivée n'est jamais
    retéléchargée. Rien n'est écrit dans l'arbre : opérations suggérées pour arbre_proposer."""
    from . import archivage
    from .archives import by_code
    from .fichiers import ecrire_atomique

    a = app()
    cfg = a.config
    personnes = personnes or []
    if nom and nom_fichier and nom != nom_fichier:
        return {"erreur": "Donner nom_fichier ou l'ancien nom, avec une seule valeur."}
    custom_name = nom_fichier or nom
    if custom_name:
        try:
            nom_simple(custom_name)
        except CheminRefuse as exc:
            return {"erreur": str(exc)}
    extension_demandee = Path(custom_name).suffix.lower() if custom_name else ""
    extensions_images = set(archivage.MIME) | {".jpeg", ".tiff"}
    if extension_demandee and extension_demandee not in extensions_images and not extension_demandee[1:].isdigit():
        return {"erreur": "nom_fichier : extension d'image ou PDF attendue ; .md est réservé à la note compagnon."}
    if type_piece.strip() and type_piece.split()[0].upper() not in pieces.TYPES:  # « NOT testament » : code + libellé
        return {"erreur": "type_piece inconnu : utiliser un code de la convention de classement."}
    if custom_name and " -- " not in custom_name:
        return {"erreur": "nom_fichier désigne le nom complet selon la convention (avec ' -- '), pas le patronyme. "
                          "L'omettre pour calculer le nom depuis personnes, type_piece, cote et vue."}
    def resultat_archive(hit, localisation=None):
        return {"deja_archivee": True, "fichier": hit["fichier"], "chemin_absolu": hit["chemin_absolu"],
                    "note": hit.get("note"), **(hit.get("localisation") or localisation or {}),
                    "dimensions_originales": hit.get("dimensions_originales"),
                    "cout_estime_tokens": hit.get("cout_estime_tokens"),
                    "suite": "Pièce déjà archivée : rien n'a été retéléchargé."}

    try:
        t = a.tree()
        labels = [_person_label(x) for x in personnes]
        if source_arbre and source_arbre not in t.sources:
            return {"erreur": f"Source de l'arbre inconnue : {source_arbre}"}
        if source.startswith(("http://", "https://", "ark:")):
            hit = archivage.deja_archivee(cfg.pieces_registre, source=source, page_demandee=page)
            if hit:
                return resultat_archive(hit)
        cle, loc = iiif.archive_key(a.sctx, source, page)
        hit = archivage.deja_archivee(cfg.pieces_registre, cle=cle)
        if hit:
            return resultat_archive(hit, loc)
        if source_arbre:
            s = t.sources[source_arbre]
            r = t.depots.get(s.depot)
            depot = depot or ((r.sigle or r.nom) if r else "")
            cote = cote or s.cote
        depot = depot or loc.get("depot", "")
        cote = cote or loc.get("cote", "")
        commune = commune or loc.get("commune", "")
        bounds = loc.get("periode")
        if not annees and bounds:
            annees = bounds[0][:4] + ("-" + bounds[1][:4] if bounds[1][:4] != bounds[0][:4] else "")
        data, extra = iiif.full_image(a.sctx, source, loc)
        loc["url_image"] = extra.get("url_image") or loc.get("url_image", "")
        ext = iiif.extension_of(data)
        if not ext:
            return {"erreur": "Le contenu reçu n'est ni une image ni un PDF (page HTML ou accès refusé ?). "
                              + iiif.CONSIGNE_AD, "source": source}
        aliases = {".jpeg": ".jpg", ".tiff": ".tif"}
        if extension_demandee in extensions_images and aliases.get(extension_demandee, extension_demandee) != ext:
            return {"erreur": f"Extension {extension_demandee} incompatible avec le contenu {ext} ; "
                              "omettre l'extension pour utiliser celle de l'originale."}
        h = archivage.empreinte(data)
        vue = str(loc.get("vue") or page or "")
        nom_f = archivage.nom_piece(labels, ext, custom_name, commune=commune, depot=depot, type_piece=type_piece,
                                    annees=annees, cote=cote, vue=vue, acte=acte)
        meme = archivage.deja_archivee(cfg.pieces_registre, empreinte=h)
        if meme:
            dest, existe = Path(meme["chemin_absolu"]), True
        else:
            info_classement = pieces.detecter(Path(archivage.nom_piece(labels, ext, commune=commune,
                depot=depot, type_piece=type_piece, annees=annees, cote=cote, vue=vue, acte=acte)))
            dossier = pieces.destination(info_classement) or pieces.A_TRIER
            dest, existe = archivage.emplacement(cfg.pieces_root, nom_f, data, dossier=dossier)
        if not existe:
            ecrire_atomique(dest, data)
    except (iiif.IiifError, SourceError, KeyError, CheminRefuse, pieces.PieceError, OSError) as exc:
        failure = error_envelope(a.sctx, "archives", "piece_archiver", {"source": source, "page": page}, exc)
        return {**failure, "source": source}
    from . import ark as _ark
    source_obj = t.sources.get(source_arbre)
    arbre_ark = (source_obj.ark or source_obj.url) if source_obj else ""
    source_ark = _ark.find(arbre_ark)
    ark_citation = loc.get("ark_vue") or ""
    if not loc.get("ark_ressource") and source_ark:
        loc["ark_ressource"] = source_ark.base
    ark_lien = ark_citation or (source_ark.id if source_ark else "") or loc.get("ark_ressource", "")
    service = by_code(depot) if depot else None
    reutil = ""
    if service:
        reutil = service.get("reutilisation") or (f"conditions à vérifier sur {service['site']}"
                                                  if service.get("site") else "")
    meta = {"ark": ark_lien, "url": source if source.startswith(("http://", "https://")) else "",
            "url_image": extra.get("url_image", ""), "service_iiif": loc.get("service", ""),
            "manifeste": loc.get("manifeste", ""), "vue": int(vue) if vue.isdigit() else vue, "depot": depot,
            "cote": cote, "commune": commune, "type_piece": type_piece.upper(), "annees": annees, "acte": acte,
            "consulte_le": date.today().isoformat(), "sha256": h, "reutilisation": loc.get("licence") or reutil,
            "titre_registre": loc.get("titre_registre"), "nb_vues": loc.get("nb_vues"),
            "mode": loc.get("mode"), "licence": loc.get("licence")}
    ids = [x for x in personnes if x in t.personnes]
    if a.notes.enabled():
        liens = [a.notes.link(t, "personne", x) if x in t.personnes else x for x in personnes]
        src_lien = a.notes.link(t, "source", source_arbre) if source_arbre in t.sources else ""
    else:
        liens, src_lien = labels, source_arbre
    note = archivage.note_compagnon(dest, meta, liens, src_lien)
    ref = cfg.media_ref(dest)
    dimensions = None
    if ext != ".pdf":
        import io

        from PIL import Image
        try:
            with Image.open(io.BytesIO(data)) as image:
                dimensions = list(image.size)
        except (OSError, Image.DecompressionBombError):
            pass
    cout_tokens = round(dimensions[0] * dimensions[1] * iiif.TOKENS_PER_PIXEL) if dimensions else None
    localisation = {k: v for k, v in loc.items() if k not in {"service", "fichier_source"}}
    archivage.enregistrer(cfg.pieces_registre, {"cle": cle, "sha256": h, "fichier": ref, "chemin_absolu": str(dest),
                                                "note": cfg.media_ref(note), "source": source, "vue": vue,
                                                "localisation": localisation, "page_demandee": page, "dimensions_originales": dimensions,
                                                "cout_estime_tokens": cout_tokens})
    a.journal.add(source="archives", operation="piece_archiver", parametres={"source": source, "vue": vue},
                  statut="positif", resume=ref, references=[x for x in (meta["ark"], source) if x],
                  personne=ids[0] if ids else None)
    citation = {"source": source_arbre or "<S… : créer la source d'abord>", "page": (f"vue {vue}" + (f"/{loc['nb_vues']}" if loc.get("nb_vues") else "")) if vue else "",
                "medias": ["$piece"], "consultation": "image"}
    if ark_citation:
        citation["ark"] = ark_citation
    out = {**localisation, "dimensions_originales": dimensions, "cout_estime_tokens": cout_tokens,
           "fichier": ref, "chemin_absolu": str(dest), "note": cfg.media_ref(note), "deja_present": existe,
           "octets": len(data), "dossier": str(dest.parent.relative_to(cfg.pieces_root.resolve()))
           if dest.resolve().is_relative_to(cfg.pieces_root.resolve()) else str(dest.parent),
           "operations_suggerees": [{"op": "ajouter_media", "ref": "piece", "fichier": ref,
                                     "format": archivage.MIME.get(ext, ""), "titre": dest.stem, "lier_a": ids}],
           "citation_suggeree": citation,
           "suite": "Proposer via arbre_proposer : ajouter_media, puis ajouter_citation sur le fait prouvé "
                    "(cible evenement uid) avec citation_suggeree."}
    alertes = []
    if nom:
        alertes.append("Le paramètre nom est conservé pour compatibilité ; utiliser nom_fichier pour un nom complet.")
    if custom_name and personnes:
        alertes.append("nom_fichier remplace le nom calculé ; le classement suit les personnes et le type fournis.")
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

def _tree_media_refs(strict: bool = False) -> dict[Path, list[tuple[str, str]]]:
    """Fichiers locaux référencés par les médias de l'arbre : chemin absolu -> [(id, référence)]. Un chemin
    relatif est cherché comme ajouter_media le fait (données, médias, arborescence des pièces : #192).
    strict : une erreur de lecture de l'arbre est propagée (sinon : aucune référence connue)."""
    from .chemins import localiser

    a = app()
    try:
        medias = a.tree().medias
    except Exception:  # noqa: BLE001 — arbre indisponible : aucune référence connue
        if strict:
            raise
        return {}
    out: dict[Path, list[tuple[str, str]]] = {}
    for mid, m in medias.items():
        if not m.fichier or "://" in m.fichier:
            continue
        try:
            p = localiser(a.config.media_racines, m.fichier)
        except CheminRefuse:
            p = Path(m.fichier).expanduser()
            p = p if p.is_absolute() else a.config.data_dir / p
        out.setdefault(p.resolve(), []).append((mid, m.fichier))
    return out


def _proposer_suivi_medias(racine: Path, realises: list[dict], refs: dict[Path, list[tuple[str, str]]]) -> dict:
    """Après un rangement réussi (#193) : proposition d'arbre (modifier_media en lot, diff + jeton) pour les
    médias dont le fichier vient d'être déplacé. refs est relevé AVANT les déplacements (un chemin relatif ne se
    localise plus une fois son fichier parti). Rien n'est écrit dans l'arbre ici."""
    a = app()
    ops, lignes = [], []
    for m in realises:
        if "contenu_apres" in m:  # note compagnon
            continue
        for mid, ancien in refs.get((racine / m["de"]).resolve(), ()):
            neuf = a.config.media_ref(racine / m["vers"])
            ops.append({"op": "modifier_media", "id": mid, "champs": {"fichier": neuf}})
            lignes.append(f"{mid} : {ancien} → {neuf}")
    if not ops:
        return {}
    out = {"medias_a_mettre_a_jour": lignes}
    try:
        prop = _gramps_guard(lambda: a.backend.propose(
            ops, f"Suivi de {len(ops)} média(s) rangé(s)",
            "Fichiers des médias déplacés par pieces_appliquer (organisation des pièces) ; même contenu."))
    except ProposalError as exc:
        prop = {"erreur": str(exc)}
    if "erreur" in prop:
        return {**out, "operations_medias": ops,
                "avertissement_medias": f"Pièces déplacées, mais proposition d'arbre impossible ({prop['erreur']}) : "
                                        "ces médias pointent vers des fichiers absents. Reproposer "
                                        "arbre_proposer(operations_medias) puis arbre_appliquer après accord, ou "
                                        "annuler le rangement (pieces_proposer(dossier, annuler=journal))."}
    return {**out, "proposition_arbre": prop,
            "consigne_medias": "Fichiers déplacés : ces médias pointent vers leurs anciens chemins (absents) tant que "
                               "la proposition n'est pas appliquée. Présenter le diff et appeler "
                               "arbre_appliquer(proposition_arbre.jeton) après accord explicite ; à défaut (refus, "
                               "jeton expiré), annuler le rangement ou reproposer les modifier_media."}


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
    ANMT, PM, NOT (acte notarié ; libellé libre après le code : « NOT testament »), CNI, COUR (courrier), REC,
    SIGN, PHOTO… source (S3) : complète dépôt (sigle) et cote depuis l'arbre. Ne renomme rien."""
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
                    apercu: int = 60, seulement_renommages: bool = False, suivre_medias: bool = False) -> dict:
    """Plan de classement d'un dossier de pièces (rien n'est déplacé) : documents/<type>/<PATRONYME>/,
    photographies/…, archives/ (GeneWeb, GEDCOM, INSEE, Doublons), _À trier/. Jamais de suppression ; les
    notes Markdown ordinaires, dossiers cachés et personnes/ familles/ sources/ sont protégés ; les médias liés à
    l'arbre ne sont pas déplacés, sauf suivre_medias=true (racine sous les répertoires des médias) : ils sont
    alors rangés (jamais comme doublons, liste medias_suivis) et pieces_appliquer renvoie, après le déplacement,
    une proposition d'arbre (modifier_media) à valider par arbre_appliquer. renommages : [{actuel, propose, dossier?}] (agent trieur, piece_nommer) ; le
    fichier est reclassé d'après son nouveau nom, ou dans dossier s'il est donné (relatif à la racine, sous
    documents/, photographies/ ou courriers/ uniquement ; tout autre dossier refuse le plan). Les chemins
    actuel sont relatifs à dossier ; l'aperçu est relatif à racine (configuration médias ou vault .obsidian). seulement_renommages limite le plan aux fichiers
    nommés, sans isoler les doublons. Les notes type: piece suivent leur média, avec fichier et embed mis à
    jour ; leur texte libre est conservé. annuler : nom d'un journal _organisation/*.tsv à défaire. Renvoie un jeton
    pour pieces_appliquer, à n'utiliser qu'après accord explicite de l'utilisateur sur le plan."""
    a = app()
    conseil = ""
    try:
        perimetre = _dossier(dossier)
        racine = _dossier(str(pieces.racine_organisation(perimetre, a.config.pieces_root)))
        try:
            refs = {} if annuler else _tree_media_refs(strict=suivre_medias)
        except Exception as exc:  # noqa: BLE001 — arbre illisible : rien à suivre de façon sûre
            return {"erreur": f"Arbre illisible, médias de l'arbre impossibles à suivre : {exc}"}
        # Le nouveau chemin doit rester sous les racines des médias, sinon modifier_media le refuserait.
        suivre = suivre_medias and any(racine.is_relative_to(Path(r).resolve()) for r in a.config.media_racines)
        if suivre_medias and not suivre:
            conseil = ("suivre_medias ignoré : la racine d'organisation est hors des répertoires des médias "
                       "(données, GENEALOGISTE_MEDIA_DIR) ; les médias de l'arbre restent en place.")
        plan = (pieces.plan_annulation(racine, annuler) if annuler
                else pieces.planifier(racine, renommages, set(refs), perimetre, seulement_renommages, suivre))
    except pieces.PieceError as exc:
        return {"erreur": str(exc)}
    plan.setdefault("perimetre", str(perimetre))
    suivis = [f"{mid} : {ancien} → {a.config.media_ref(racine / m['vers'])}"
              for m in plan["deplacements"] if m.get("media_arbre")
              for mid, ancien in refs.get((racine / m["de"]).resolve(), ())]
    if suivis:
        plan["medias_suivis"] = suivis
    if plan.get("references_arbre_non_deplacees") and not conseil:
        conseil = ("Pièces référencées par un média de l'arbre laissées en place : pieces_proposer(…, "
                   "suivre_medias=true) les range et met à jour les médias (proposition d'arbre après le "
                   "déplacement, à valider).")
    if conseil:
        plan["medias_conseil"] = conseil
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
    journal TSV _organisation/<date>.tsv pour annuler, contrôle du nombre de fichiers et des empreintes. Si des
    fichiers référencés par des médias de l'arbre ont été déplacés (suivre_medias, annulation), renvoie une
    proposition_arbre (modifier_media, diff + jeton) : rien n'est écrit dans l'arbre sans arbre_appliquer."""
    a = app()
    store = TokenStore(a.config.proposals_dir)
    try:
        rec = store.take(jeton)
        if rec.get("type") != "organisation":
            return {"erreur": "Ce jeton n'est pas un plan d'organisation de pièces."}
        # Relevé avant les déplacements (localisation des chemins relatifs) ; obligatoire si le plan suit des médias.
        suivi = any(m.get("media_arbre") for m in rec["plan"]["deplacements"])
        try:
            refs = _tree_media_refs(strict=suivi)
        except Exception as exc:  # noqa: BLE001 — sans l'arbre, les médias suivis ne pourraient être mis à jour
            return {"erreur": f"Arbre illisible ({exc}) : rangement non effectué, rien n'a été déplacé ; "
                              "reformuler le plan (pieces_proposer)."}
        out = pieces.appliquer(Path(rec["dossier"]), rec["plan"])
    except (ProposalError, pieces.PieceError) as exc:
        return {"erreur": str(exc)}
    realises = out.pop("deplacements_realises", [])
    # Médias de l'arbre dont le fichier a bougé (suivre_medias, annulation) : proposition, jamais écriture.
    out.update(_proposer_suivi_medias(Path(rec["dossier"]), realises, refs))
    # Préserver la reconnaissance des originales archivées, sans retéléchargement après rangement/annulation.
    try:
        archivage.relocaliser(a.config.pieces_registre, Path(rec["dossier"]), realises, a.config.media_ref)
    except OSError as exc:
        out["avertissements"] = [f"Pièces déplacées, mais registre d'archivage non actualisé : {exc}. "
                                 "Conserver le journal ; un archivage ultérieur pourrait retélécharger la vue."]
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
    patronyme (NOM) ou « tout » (+ patronymes/, index.md et kit Obsidian : vues Bases/Dataview, modèles, extrait
    CSS, sauf GENEALOGISTE_NOTES_KIT=false ; un fichier du kit modifié à la main est conservé). Seules les sections générées et le frontmatter sont réécrits ; le texte libre et les
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
    """Vide le cache SQLite (tout, ou une catégorie). Catégories : matchid, wikitree, gallica, wikidata, geo,
    cog, archives, ark, iiif, visionneuse ; echec (échecs mémorisés sans source) ; coupe_circuit (lève la pause
    d'un hôte après blocage anti-robot). Les échecs mémorisés d'une source partent avec elle. Purge aussi les
    entrées expirées et applique les plafonds de taille (GENEALOGISTE_CACHE_MAX_MO, _CACHE_IMAGES_MAX_MO)."""
    a = app()
    supprimes = a.cache.purge(source or None)
    a.cache.borner()
    return {"supprimes": supprimes, "images_supprimees": menage.borner_images(a.config),
            "restant": a.cache.stats()}


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
    """Personne Gramps Web (handle) lue avec la correspondance Genealogiste (id, noms, faits, statut de preuve)."""
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
def gramps_relocaliser_medias(ancien_prefixe: str, nouveau_prefixe: str) -> dict:
    """Après un changement de machine ou de point de montage : prépare la réécriture du fichier local des médias
    (attribut Sosa-Fichier en mode gramps, FILE en mode fichier) dont le chemin commence par ancien_prefixe, en
    remplaçant ce préfixe par nouveau_prefixe. Chaque nouveau chemin doit exister sous les répertoires autorisés et,
    si Gramps Web connaît la somme du fichier, avoir le même MD5 ; les autres sont listés à part (introuvables,
    md5_differents, refuses) et laissés intacts. Renvoie une proposition (diff, jeton) : une seule transaction,
    écrite par arbre_appliquer après accord explicite, annulable par arbre_annuler_modification."""
    import hashlib

    from .chemins import localiser

    # Préfixes comparés comme dossiers : « /a/b » couvre « /a/b/x.jpg », jamais « /a/b2/x.jpg ».
    ancien, nouveau = ancien_prefixe.rstrip("/"), nouveau_prefixe.rstrip("/")
    if not ancien:
        return {"erreur": "ancien_prefixe requis, autre que la racine (ex. « /ancienne/racine/vault »)."}
    a = app()

    def run():
        sommes = a.backend.media_checksums() if a.config.backend == "gramps" else {}
        cfg = a.config
        out: dict[str, list[str]] = {"a_relocaliser": [], "introuvables": [], "md5_differents": [], "refuses": []}
        ops = []
        for mid, m in a.tree().medias.items():
            reste = m.fichier[len(ancien):]
            if not m.fichier.startswith(ancien) or (reste and not reste.startswith("/")):
                continue
            neuf = nouveau + reste if nouveau else reste.lstrip("/")
            if "://" not in neuf:
                try:
                    p = localiser(cfg.media_racines, neuf)
                except CheminRefuse as exc:
                    out["refuses"].append(f"{mid} : {neuf} ({exc})")
                    continue
                if not p.is_file():
                    out["introuvables"].append(f"{mid} : {neuf}")
                    continue
                somme = sommes.get(mid, "")
                if somme and hashlib.md5(p.read_bytes()).hexdigest() != somme:
                    out["md5_differents"].append(f"{mid} : {neuf} (MD5 différent de celui de Gramps Web)")
                    continue
                neuf = cfg.media_ref(p)
            if neuf == m.fichier:
                continue
            out["a_relocaliser"].append(f"{mid} : {m.fichier} → {neuf}")
            ops.append({"op": "modifier_media", "id": mid, "champs": {"fichier": neuf}})
        if not ops:
            return {**out, "note": f"Aucun média à relocaliser (préfixe « {ancien_prefixe} »)."}
        prop = a.backend.propose(ops, f"Relocalisation de {len(ops)} média(s)",
                                 f"Fichiers des médias déplacés de « {ancien_prefixe} » vers « {nouveau_prefixe} » "
                                 "(changement de machine ou de point de montage) ; existence"
                                 + (" et MD5 vérifiés." if sommes else " vérifiée."))
        return {**out, **prop}

    try:
        return _gramps_guard(run)
    except ProposalError as exc:
        return {"erreur": str(exc)}


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

def verifier_demarrage(cfg: Config | None = None) -> dict | None:
    """Validation légère au démarrage (#146) : configuration lisible, git présent, répertoire de données hors
    du plugin et inscriptible. Sans réseau ni chargement de l'arbre (le client laisse peu de temps à la
    connexion). Renvoie la description de la première erreur, ou None."""
    import os

    try:
        cfg = cfg or load_config()
        if shutil.which("git") is None:
            raise FileNotFoundError(2, "No such file or directory: 'git'", "git")
        TreeStore(cfg.data_dir, cfg.git_remote).verifier_emplacement()
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(cfg.data_dir, os.W_OK | os.X_OK):
            raise PermissionError(13, "Permission denied", str(cfg.data_dir))
    except Exception as exc:  # noqa: BLE001 — toute erreur est décrite, jamais avalée
        return erreurs.decrire(exc)
    return None


def _signaler(desc: dict) -> None:
    import sys

    print(f"genealogiste : configuration invalide ({desc['cause']}) : {desc['erreur']}\n  remède : {desc['remede']}",
          file=sys.stderr)


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
    probleme = verifier_demarrage()
    if probleme:
        _signaler(probleme)
    if args.check:
        if probleme:
            raise SystemExit(2)
        try:
            a = app()
        except Exception as exc:  # noqa: BLE001
            _signaler(erreurs.decrire(exc))
            raise SystemExit(2) from exc
        print(json.dumps(arbre_info(), ensure_ascii=False, indent=2, default=str))
        print("WikiTree appId :", "défini" if a.config.wikitree_app_id else "ABSENT")
        langues = pdf_md._tesseract_langues(a.config.tesseract)
        if langues is None:
            cmd = pdf_md.commande_installation(["fra"]).get("commande") or "voir docs/pieces.md"
            print("OCR (Tesseract) : ABSENT — PDF scannés lus en image ; installer :", cmd)
        else:
            utiles = [x for x in ("fra", "lat") if x in langues]
            print("OCR (Tesseract) : présent, langues", ", ".join(utiles) or "fra/lat ABSENTES",
                  f"({len(langues)} installées)")
        return
    if args.transport == "stdio":
        # Mode dégradé volontaire : le serveur reste joignable et chaque outil renvoie cause et remède au modèle
        # (sinon Claude Code n'affiche qu'un échec de connexion, sans la cause).
        mcp.run(transport="stdio")
        return
    if probleme and erreurs.fatale(probleme):
        raise SystemExit(2)  # service HTTP sous superviseur : refuser de démarrer, cause sur stderr
    import uvicorn
    load_config()  # charge aussi le .env privé avant de lire les réglages du transport
    token = os.environ.get("MCP_TOKEN", "")
    if problem := bind_problem(args.host, token, os.environ.get("MCP_SANS_AUTH", "")):
        raise SystemExit(problem)
    asgi = mcp.streamable_http_app() if args.transport == "streamable-http" else mcp.sse_app()
    if token:
        asgi = BearerAuth(asgi, token)
    from .diagnostic import version_serveur
    asgi = Sante(asgi, "degrade" if probleme else "ok", version_serveur())
    uvicorn.run(asgi, host=args.host, port=args.port, log_level=mcp.settings.log_level.lower())


if __name__ == "__main__":
    main()
