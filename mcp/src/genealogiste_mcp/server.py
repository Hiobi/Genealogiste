"""Serveur MCP « genealogiste » (MCPServer) : sources, normalisation, preuve, arbre GEDCOM versionné."""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import shutil
from contextlib import contextmanager
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
    sites_tiers,
    sondage,
)
from . import pdf_markdown as pdf_md
from . import taches as taches_gramps
from .archives import communicability_online
from .auth import BearerAuth, Sante, bind_problem
from .billets import est_billet
from .budget import PlafondJour, mesurer
from .cache import Cache
from .chemins import CheminRefuse, nom_simple, sous
from .config import Config, load_config
from .contexte import services as services_contexte
from .contexte.registre import RegistreReferences
from .enquetes import EnqueteError, Enquetes
from .export import charts, chemins_medias, gramps_xml
from .export.fiche import fiche_markdown, gaps, tree_gaps
from .export.geneweb import to_geneweb
from .export.rapport import proof_report
from .fr_sources import next_source_hint
from .gedcom.mapping import read_gedcom, write_gedcom
from .gramps import groupes_noms as gn
from .gramps import reglages as rg
from .gramps.client import GrampsError
from .gramps.mapping import tree_to_gramps_stats
from .http import HttpClient, SourceError
from .journal import Journal
from .normalize import dates as d
from .normalize.names import normalize_name, surname_similarity
from .normalize.places import normalize_place
from .notes import Notes, NotesError, touched
from .politique_acces import PolitiqueAcces, normaliser_hote
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
from .tree import file_propositions as fp
from .tree.proposals import ProposalError, Proposals, TokenStore, new_alerts, prepare, targets
from .tree.store import TreeStore, remote_problem

INSTRUCTIONS = """Assistant généalogique (méthode du Genealogical Proof Standard, sources françaises).
Règles : ne jamais inventer (donnée sans source = « non sourcée ») ; toute écriture dans l'arbre (fichier GEDCOM ou
Gramps Web selon le backend) passe par arbre_proposer (diff) puis arbre_appliquer UNIQUEMENT après accord explicite de
l'utilisateur ; une annulation aussi (arbre_annuler_modification puis arbre_appliquer) ; jamais de fusion
automatique ; rien sur les personnes vivantes vers l'extérieur ; chaque recherche est tracée au journal (y compris
négative) ; toujours indiquer la prochaine source à consulter pour un fait non confirmé."""

mcp = ServeurMCP("genealogiste", instructions=INSTRUCTIONS, log_level="WARNING")
# Budget d'enquête (#211) : tous les outils réseau de collecte du catalogue acceptent enquete=<id> (enveloppe).
mcp.avec_enquete = outils.BUDGET_ENQUETE
mcp.doc_enquete = ("enquete (facultatif) : id d'enquête où noter la demande et dont le budget compte les requêtes "
                   "émises (par hôte) ; budget épuisé : refus avant la requête, enquête bloquée, appel consigné au "
                   "reste à faire. deja_fait signale la même demande déjà notée dans une enquête (sans bloquer).")

class App:
    def __init__(self, config: Config | None = None, transport=None, sleeper=None, gramps_transport=None):
        self.config = config or load_config()
        self.cache = Cache(self.config.cache_path, max_octets=int(self.config.cache_max_mo * menage.MO))
        self.cache.borner()
        menage.borner_images(self.config)
        kw = {"sleeper": sleeper} if sleeper else {}
        politique = PolitiqueAcces.depuis_config(self.config)  # intervalle et plafond par hôte (#211)
        self.http = HttpClient(self.cache, self.config.user_agent, self.config.http_timeout,
                               offline=self.config.offline, transport=transport,
                               policy=NetworkPolicy(self.config.hotes_autorises), politique=politique,
                               max_retries=self.config.http_tentatives, duree_max=self.config.http_duree_max,
                               echec_ttl=self.config.cache_echec, coupe_circuit_ttl=self.config.coupe_circuit,
                               exclusion_ttl=self.config.exclusion_antirobot,
                               plafond=PlafondJour(self.cache, politique=politique),
                               ralentissement_max=self.config.ralentissement_max,
                               **kw)
        self.store = TreeStore(self.config.data_dir, self.config.git_remote, self.config.git_delai)
        self.store.ensure()
        self.journal = Journal(self.config.journal_path)
        self.enquetes = Enquetes(self.config.data_dir, self.journal, self.config.budget_defaut())
        # Références consultées du contexte historique (#321) : hors du cache, jamais vidé par cache_purger.
        self.registre_references = RegistreReferences(self.config.references_consultees_path)
        self.proposals = Proposals(self.store, self.config.proposals_dir, self.config.exiger_source,
                                   self.config.media_reference)
        self.tokens = TokenStore(self.config.proposals_dir)
        self.file = fp.FilePropositions(self.config.proposals_dir / "file")  # file durable (#154)
        import threading
        self._verrou_gramps = threading.RLock()
        self._executeur_notes = None
        self._notes_futurs: list = []
        self.notes_etats: dict[str, dict] = {}  # jeton -> état de la régénération différée des notes
        self.tokens.purger_expirees()
        self.sctx = SourceContext(self.http, self.journal, self.config)
        self.notes = Notes(self.config.notes_dir, self.config.notes_vivants, self.config.strict_evidence,
                           self.config.sosa_racine, self.journal, data_dir=self.config.data_dir,
                           kit=self.config.notes_kit, marqueurs=self.config.marqueurs,
                           media_racines=lambda: self.config.media_racines)
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
                                         notes_liens=self.config.gramps_notes_liens,
                                         media_dir=self.config.media_racines[1:] if self.config.media_dir_conf else None,
                                         media=self.config.media_reference, forme=self.config.marqueurs,
                                         taches=self.config.gramps_taches,
                                         prive_vivants=self.config.gramps_prive_vivants)

    def taches_actives(self) -> bool:
        """Tâches de Gramps Web lues et écrites (#263) : backend gramps et GENEALOGISTE_GRAMPS_TACHES=true."""
        return self.config.backend == "gramps" and self.config.gramps_taches

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


def _groupes_noms():
    """Groupes de noms de Gramps (#276) en backend gramps, ``None`` sinon ou si Gramps Web ne répond pas : la
    recherche locale ne dépend jamais de cette lecture facultative (backend fichier : aucun groupe, rien d'inventé)."""
    a = app()
    if a.config.backend != "gramps":
        return None
    try:
        return gn.Groupes(a.backend.groupes_noms())  # même vide : group_as d'un nom prime encore (arbre_recherche)
    except GrampsError:
        return None


def _suivi_enquete(outil: str, parametres: dict, out: dict, enquete: str = "", fenetre: list[int] | None = None,
                   **noter) -> dict:
    """« Déjà fait le … » (même demande notée dans une enquête) et, avec enquete=<id>, notation de la demande
    dans l'état de cette enquête (#155). Local seulement ; n'empêche jamais l'appel ni ne modifie son résultat."""
    a = app()
    try:
        if deja := a.enquetes.deja_fait(outil, parametres, fenetre):
            out["deja_fait"] = deja
    except (OSError, ValueError):
        pass  # état illisible : l'appel reste valable
    if enquete:
        try:
            a.enquetes.enregistrer(enquete, outil, parametres, fenetre=fenetre, **noter)
            out["enquete"] = enquete
        except (EnqueteError, OSError) as exc:
            out["enquete_avertissement"] = f"Demande non notée dans l'enquête : {exc}"
    return out


def _budget_avant(enquete: str, outil: str, appel: dict, images: int = 0) -> dict | None:
    """Budget de l'enquête (#157), avant tout appel réseau : refus explicite (enquête bloquée, appel consigné au
    reste à faire) si elle est déjà bloquée ou si l'appel dépasserait une limite. Enquête inconnue : pas de
    budget (avertissement de _suivi_enquete)."""
    if not enquete:
        return None
    try:
        return app().enquetes.controler(enquete, outil, appel, images)
    except (EnqueteError, OSError, ValueError):
        return None


@contextmanager
def _mesure(enquete: str):
    """Mesure côté serveur des requêtes émises (par hôte) pendant un appel lié à une enquête ; la garde refuse
    une requête avant l'envoi quand le budget est atteint. None sans enquête valide."""
    garde = None
    if enquete:
        try:
            garde = app().enquetes.garde(enquete)
        except (EnqueteError, OSError, ValueError):
            garde = None
    if garde is None:
        yield None
        return
    with mesurer(garde) as m:
        yield m


def _budget_apres(enquete: str, m, outil: str, appel: dict, out: dict, images: int = 0,
                  reste: dict | None = None) -> dict:
    """Consommation de l'appel (requêtes par hôte, images lues) et reste du budget dans la réponse ; refus
    pendant l'appel : enquête bloquée, reste (ou l'appel) consigné."""
    if m is None:
        return out
    _tache_blocage(enquete, out)
    try:
        out.update(app().enquetes.apres_collecte(enquete, dict(m.requetes), images, m.refus, outil,
                                                 reste if reste is not None else appel))
    except (EnqueteError, OSError) as exc:
        out["enquete_avertissement"] = f"Budget non mis à jour : {exc}"
    return out


def _tache_blocage(enquete: str, out: dict) -> None:
    """Défi anti-robot pendant un appel lié à une enquête (#150) : la consultation devient une tâche manuelle
    de l'enquête (une par URL bloquée), reprise par enquete_reprendre ; l'enquête continue sur les autres pistes."""
    if out.get("statut") != "bloque_antirobot" or not isinstance(out.get("tache_manuelle"), dict):
        return
    try:
        t = app().enquetes.tache_blocage(enquete, str(out.get("service") or ""), str(out.get("url") or ""),
                                         str(out.get("protection") or ""), str(out.get("journal") or ""))
    except (EnqueteError, OSError) as exc:
        out["enquete_avertissement"] = f"Tâche manuelle non notée dans l'enquête : {exc}"
        return
    out["tache_manuelle"] = {**out["tache_manuelle"], "enquete": enquete, "id": t["id"]}


# Images lues par le modèle par appel réussi, pour les outils mesurés par l'enveloppe (archive_image compte les
# siennes lui-même).
IMAGES_PAR_APPEL = {"archives_planche": 1}


def _mesure_enquete(nom: str, fn, args: tuple, kwargs: dict, enquete: str):
    """Mesure générique (#211) d'un outil de collecte (enveloppe de ServeurMCP, appelée avec ou sans enquête) :
    avec enquete=<id>, contrôle avant appel, requêtes émises comptées par hôte, refus avant l'envoi à
    l'épuisement ; dans tous les cas, signal « déjà fait » et, avec enquete, demande notée (_suivi_collecte)."""
    try:
        appel = dict(inspect.signature(fn).bind_partial(*args, **kwargs).arguments)
    except TypeError:
        appel = dict(kwargs)
    images = IMAGES_PAR_APPEL.get(nom, 0)
    if enquete and (refus := _garde_avant_budget(nom, fn, appel)):
        return refus  # vivant : rien consommé ni consigné (le contrôle de budget noterait ses paramètres)
    if refus := _budget_avant(enquete, nom, appel, images=images):
        return refus
    with _mesure(enquete) as m:
        res = fn(*args, **kwargs)
    if not isinstance(res, dict):
        return res
    res = _budget_apres(enquete, m, nom, appel, res, images=images if "erreur" not in res else 0)
    return _suivi_collecte(nom, appel, res, enquete)


def _garde_avant_budget(nom: str, fn, appel: dict) -> dict | None:
    """Garde « vivants » de l'outil (outils.GARDE_AVANT_BUDGET), rejouée avant le contrôle de budget : même
    refus que l'outil, mêmes paramètres (défauts de la signature pour ceux omis)."""
    correspondance = outils.GARDE_AVANT_BUDGET.get(nom)
    if not correspondance:
        return None
    valeurs = {p: v.default for p, v in inspect.signature(fn).parameters.items()
               if v.default is not inspect.Parameter.empty}
    valeurs.update(appel)
    return _garde(**{arg: valeurs.get(param) or "" for arg, param in correspondance.items()})


def _suivi_collecte(nom: str, appel: dict, res: dict, enquete: str) -> dict:
    """« Déjà fait le … » des outils de collecte à identité déclarée (outils.IDENTITE_REQUETE, #211) : après un
    appel abouti seulement. Un refus (personne vivante, budget) ou une erreur n'est ni signalé ni noté : la
    garde des vivants passe avant (_garde_avant_budget, puis dans l'outil). Résultat négatif : aucun résultat
    renvoyé."""
    if nom not in outils.IDENTITE_REQUETE or "erreur" in res or "refus" in res:
        return res
    negatif = bool(res.get("recherche_negative")) or res.get("resultats") == [] or res.get("nb_lignes") == 0
    journal = [res["journal"]] if isinstance(res.get("journal"), str) else []
    return _suivi_enquete(nom, appel, res, enquete, resultat="negatif" if negatif else "positif",
                          journal=journal, appel=appel)


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


def _garde_ecriture(nom: str, fn, args: tuple, kwargs: dict) -> dict | None:
    """Garde-fou côté serveur (#159) : avec GENEALOGISTE_ECRITURE=interdite, tout appel de classe « ecriture »
    du catalogue (outils.OUTILS ; pour un outil de CONDITIONS, seulement la branche écriture) est refusé avant
    tout effet, quel que soit le mode de permission du client (hooks contournés, sans confirmation…)."""
    if nom not in outils.OUTILS or outils.OUTILS[nom][1] != outils.ECRITURE:
        return None  # lecture, collecte, proposition : jamais concernées (et sans initialiser l'App)
    if app().config.ecriture != "interdite":
        return None
    try:
        arguments = dict(inspect.signature(fn).bind_partial(*args, **kwargs).arguments)
    except TypeError:
        arguments = dict(kwargs)
    if not outils.branche_ecriture(nom, arguments):
        return None
    libelle = outils.CONDITIONS[nom][2] if nom in outils.CONDITIONS else "écriture"
    return {"erreur": f"{nom} refusé par le serveur : GENEALOGISTE_ECRITURE=interdite ({libelle} ; arbre, Gramps "
                      "Web ou fichiers de l'utilisateur). Session sans surveillance : déposer plutôt la conclusion "
                      "dans la file (propositions_deposer) pour validation ultérieure (/genealogiste:valide).",
            "refus": "ecriture_interdite", "outil": nom,
            "remede": "Relancer dans une session surveillée avec GENEALOGISTE_ECRITURE=autorisee (défaut)."}


mcp.garde = _garde_ecriture
mcp.mesure = _mesure_enquete
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
                  details: bool = False, enquete: str = "") -> dict:
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
    et à faire vérifier.
    enquete (facultatif) : id d'enquête où noter la vue consultée ; deja_fait signale une vue déjà lue.
    Avec enquete, l'appel consomme son budget (une image, requêtes par hôte) ; budget renvoie le reste ;
    cout_estime_tokens reste une information (aucune limite) ; budget épuisé : refus avant toute requête, enquête bloquée, appel consigné au reste à faire."""
    appel = {"source": source, "page": page, "region": region, "largeur": largeur, "gris": gris, "details": details}
    if refus := _budget_avant(enquete, "archive_image", appel, images=1):
        return refus
    with _mesure(enquete) as m:
        out = iiif.fetch(app().sctx, app().config.cache_images_dir, source, page, region, largeur, gris)
        res = iiif.sortie_minimale(app().sctx, out, details)
    lue = "erreur" not in res
    res = _budget_apres(enquete, m, "archive_image", appel, res, images=int(lue))
    if not lue:
        return res
    vue = res.get("vue") if isinstance(res.get("vue"), int) else (page or None)
    registre = res.get("registre") or source
    params = {"source": source, "page": page, "vue": vue, "registre": registre}
    return _suivi_enquete("archive_image", params, res, enquete, resultat="positif", registre=registre,
                          vue_lue=vue, nb_vues=res.get("nb_vues") if isinstance(res.get("nb_vues"), int) else None,
                          appel=appel)


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
    """Planche-contact d'un registre (AD59, services Mnesys) : UNE image composite de 4 à 12 vues (numéro de vue incrusté) pour
    repérer l'acte sans lire une image par vue. source : ARK de registre ou de vue (AD59, services Mnesys). de/a : première et
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
                    sources: list[str] | None = None, personne: str = "", enquete: str = "") -> dict:
    """Recherche multi-sources (matchID, WikiTree, Wikidata, Gallica) + liens des sources secondaires.
    Résultats fusionnés et classés par score de correspondance explicite.
    enquete (facultatif) : id d'enquête où noter la demande ; deja_fait signale la même requête déjà notée.
    Avec enquete, les requêtes émises par les sources consomment le budget de l'enquête (budget = reste) ;
    budget épuisé : refus avant la requête, sources restantes consignées au reste à faire, enquête bloquée."""
    refus = _garde(personne, nom, prenom, ne_vers)
    if refus:
        return refus
    a = app()
    wanted = sources or ["matchid", "wikitree", "wikidata", "gallica"]
    pid = personne or None
    appel = {"nom": nom, "prenom": prenom, "ne_vers": ne_vers, "lieu": lieu, "decede_vers": decede_vers,
             "sources": sources, "personne": personne}
    if refus := _budget_avant(enquete, "recherche_multi", appel):
        return refus
    appels = {
        "matchid": lambda: matchid.search(a.sctx, nom, prenom, ne_vers, lieu, decede_vers, personne=pid),
        "wikitree": lambda: (wikitree.search(a.sctx, nom, prenom, ne_vers, lieu, decede_vers, personne=pid)
                             if a.config.wikitree_app_id else {"erreur": "GENEALOGISTE_WIKITREE_APPID non défini"}),
        "wikidata": lambda: wikidata.search_person(a.sctx, nom, prenom, ne_vers, lieu, personne=pid),
        "gallica": lambda: gallica.search(a.sctx, f"{prenom} {nom}".strip(), personne=pid, nombre=10),
    }
    by_source: dict[str, Any] = {}
    restantes: list[str] = []  # sources non interrogées faute de budget : reste à faire
    with _mesure(enquete) as m:
        for s in [x for x in appels if x in wanted]:
            if m is not None and m.refus:
                restantes.append(s)
                continue
            res = appels[s]()
            if m is not None and m.refus:  # refusée avant l'envoi : à refaire, pas une erreur de la source
                restantes.append(s)
                continue
            by_source[s] = res
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
    out = {
        "requete": {"nom": nom, "prenom": prenom, "ne_vers": ne_vers, "lieu": lieu, "decede_vers": decede_vers},
        "personnes": persons[:40], "documents": docs[:20], "sources_negatives": negatives, "erreurs": errors,
        "sources_secondaires": liens.search_links(nom, prenom, ne_vers, lieu, decede_vers)["liens"],
        "rappel": "Score = indice de correspondance, pas une preuve. Index et arbres en ligne : remonter à l'original.",
    }
    if (groupes := _groupes_noms()) is not None and (apparentes := groupes.apparentes(nom)):
        # #276 : information LOCALE (groupes de l'arbre Gramps de l'utilisateur), jamais envoyée aux sources ni
        # ajoutée à la requête : chaque variante à tenter fait l'objet d'un appel explicite, donc de la garde (_garde)
        out["groupe_de_noms"] = {
            "patronyme": nom, "apparentes": apparentes, "envoyees_aux_sources": False,
            "consigne": ("Patronymes regroupés par Gramps avec ce nom (groupes de noms) : classement de l'arbre, pas "
                         "une preuve d'identité. Non interrogés ici ; pour en essayer un, relancer recherche_multi "
                         "avec ce nom (la garde des vivants s'applique à chaque appel).")}
    out = _budget_apres(enquete, m, "recherche_multi", appel, out,
                        reste={**appel, "sources": restantes} if restantes else None)
    faites = sources if not restantes else list(by_source)
    if not faites and restantes:
        return out  # rien d'interrogé : rien à noter comme fait
    params = {**out["requete"], "sources": faites}
    journal = [r["journal"] for r in by_source.values() if isinstance(r, dict) and r.get("journal")]
    resultat = "positif" if persons or docs else ("erreur" if errors else "negatif")
    return _suivi_enquete("recherche_multi", params, out, enquete, resultat=resultat, journal=journal,
                          appel={**appel, "sources": faites})


@mcp.tool()
def liens_recherche(nom: str, prenom: str = "", ne_vers: str = "", lieu: str = "", decede_vers: str = "") -> dict:
    """URL de recherche pour Geneanet, FranceArchives, Mémoire des hommes, Grand Mémorial, AD (navigateur
    de l'utilisateur, lecture seule), plus sites_tiers : cercles et relevés bénévoles du département du lieu
    (sources dérivées : remonter à l'acte)."""
    return liens.search_links(nom, prenom, ne_vers, lieu, decede_vers)


TYPE_CONTEXTE = "contexte"


def _config_courante() -> Config | None:
    """Configuration de l'application en place, sinon celle de l'environnement, sans construire l'application
    (outils de lecture des référentiels) ; None si elle est invalide (l'état d'activation est alors omis)."""
    try:
        return _APP.config if _APP is not None else load_config()
    except Exception:  # noqa: BLE001
        return None


@mcp.tool()
def sources_catalogue(departement: str = "", type: str = "", acces: str = "", theme: str = "") -> dict:
    """Tout ce que le plugin connaît, sans requête : archives publiques du référentiel, sites tiers de généalogie
    (cercles, relevés bénévoles, bases thématiques, annuaires, lieux) et services interrogés par API. Filtres :
    departement (« 59 », « 2A »), type (departementales… pour les archives ; cercle_departemental,
    releves_benevoles, base_thematique, annuaire, lieux, cimetieres_monuments, arbre_collaboratif pour les sites
    tiers), acces (libre, inscription_gratuite, adhesion, points, mixte, a_determiner), theme (ww2, protestants,
    juifs, deportes, emigration…). Un relevé de site tiers est une source dérivée : remonter à l'acte.
    type="contexte" : services publics de contexte historique seulement (historiographie, bibliothèques, presse,
    cartes, statistiques ; referentiels/sources_contexte.json) avec, pour chacun, activation, interrogeabilité et
    motif, état de la clé (présente/absente, jamais sa valeur) ; mode lien_seulement : jamais interrogé."""
    from .normalize.places import DEPARTEMENTS

    if type == TYPE_CONTEXTE:
        if departement or acces or theme:
            return {"erreur": "type=\"contexte\" ne se combine pas avec departement, acces ni theme"}
        cfg_ctx = _config_courante()
        ctx = [services_contexte.resume(s, cfg_ctx) for s in services_contexte.services()]
        return {"filtres": {"type": TYPE_CONTEXTE}, "totaux": {"contexte": len(ctx)}, "contexte": ctx,
                "avertissement": services_contexte.AVERTISSEMENT,
                "consigne": ("Un service non interrogeable (désactivé, clé requise absente, lien seulement, "
                             "protégé) n'émet aucune requête : son motif est donné. Activation : "
                             "GENEALOGISTE_CONTEXTE_SERVICES ; clés : GENEALOGISTE_CLE_* (diagnostic).")}
    dep = (departement or "").strip().upper()
    if dep.isdigit() and len(dep) == 1:
        dep = "0" + dep
    if dep and dep not in DEPARTEMENTS:
        return {"erreur": f"département inconnu : {departement!r} (ex. « 59 », « 2A », « 974 »)"}
    types_tiers = sites_tiers.TYPES
    if type and type not in types_tiers and type not in archives.TYPES:
        return {"erreur": f"type inconnu : {type!r}", "types_archives": list(archives.TYPES),
                "types_sites_tiers": list(types_tiers), "types_contexte": [TYPE_CONTEXTE]}
    if acces and acces not in sites_tiers.ACCES:
        return {"erreur": f"accès inconnu : {acces!r}", "valeurs": list(sites_tiers.ACCES)}
    arch = [] if (type in types_tiers or acces or theme) else [
        {k: s[k] for k in ("code", "nom", "type", "departement", "site", "visionneuse") if s.get(k)}
        for s in archives.services()
        if (not dep or s.get("departement") == dep or s.get("type") != "departementales")
        and (not type or s.get("type") == type)]
    tiers = [] if type in archives.TYPES else [
        sites_tiers.resume(s) for s in sites_tiers.filtrer(dep, type, acces, theme)]
    api = [] if (dep or type or acces or theme) else list(sites_tiers.API)
    ctx = []
    if not (dep or type or acces or theme):
        cfg_ctx = _config_courante()
        ctx = [services_contexte.resume(s, cfg_ctx) for s in services_contexte.services()]
    return {"filtres": {k: v for k, v in (("departement", dep), ("type", type), ("acces", acces),
                                          ("theme", theme)) if v},
            "totaux": {"archives": len(arch), "sites_tiers": len(tiers), "api": len(api), "contexte": len(ctx)},
            "archives": arch, "sites_tiers": tiers, "api": api, "contexte": ctx,
            "avertissement": sites_tiers.AVERTISSEMENT,
            "consigne": ("Détail d'un service d'archives : archives_service(code=...). Liens de recherche pour une "
                         "personne : liens_recherche. Site protégé ou sur adhésion : navigateur de l'utilisateur, "
                         "puis source_collee ; aucun contournement.")}


@mcp.tool()
def cotes_a_consulter(fait: str, date_fait: str = "", lieu: str = "") -> dict:
    """Sources et cotes typiques (cadre de classement des AD) pour étayer un fait (BIRT, DEAT, MARR, FILIATION…).
    pays : pays du lieu et provenance ; hors de France, aucune série d'AD (renvoi générique, piste de transcription) ;
    pays inconnu : séries « si le lieu est en France » et pays_a_preciser."""
    return liens.cote_suggestions(fait, date_fait, lieu)


@mcp.tool()
def archives_service(lieu: str = "", departement: str = "", code: str = "", document: str = "",
                     annee: int = 0) -> dict:
    """Service d'archives réel (référentiel) d'un lieu, d'un département ou d'un code (AD59, AN, SHD, ANOM…) :
    site, visionneuse, NAAN ARK, ce qui est en ligne (document = naissance, mariage, deces, recensement,
    matricule… ; préciser lieu pour les exceptions communales et annee ; None = inconnu), inscription,
    date de vérification et couverture sourcée. Un accès déclaré ne prouve pas l'existence d'un acte.
    consultation_manuelle : protection anti-robot relevée (ex. Anubis) et consigne (vue fournie par
    l'utilisateur, media_enregistrer) ; un nouvel essai réseau reste possible. defi_observe : dernier défi
    observé depuis cette installation sur ses hôtes (détections, exclusion en cours) ; acces_vps : mesure de
    recette depuis le VPS. Avec lieu seul : pays du lieu ; hors de France, aucun service d'AD (renvoi, piste_francaise)."""
    res = archives.service(lieu, departement, code, document, annee or None)
    hotes = [normaliser_hote(res.get(k) or "") for k in ("site", "visionneuse")] if "erreur" not in res else []
    if any(hotes):  # politique d'accès effective (intervalle, plafond/jour, provenance) de ses hôtes (#211)
        res["politique_acces"] = {h: app().http.politique.politique(h).en_dict() for h in hotes if h}
        if obs := _defi_observe(hotes):
            res["defi_observe"] = obs
    return res


def _defi_observe(hotes: list[str]) -> dict | None:
    """Dernier défi anti-robot observé depuis cette installation sur les hôtes du service (#150), local."""
    import time
    from datetime import UTC, datetime

    def iso(t):
        return datetime.fromtimestamp(t, UTC).isoformat(timespec="seconds") if t else None

    vus = [d for h in dict.fromkeys(hotes) if h and (d := app().cache.defi_antirobot(h))]
    if not vus:
        return None
    d = max(vus, key=lambda x: x["derniere"])
    exclu = d["exclu_jusqu_a"] if d["exclu_jusqu_a"] and d["exclu_jusqu_a"] > time.time() else None
    out = {"hote": d["hote"], "protection": d["protection"], "url": d["url"], "statut_http": d["statut"],
           "premiere_detection": iso(d["premiere"]), "derniere_detection": iso(d["derniere"]),
           "detections": d["detections"], "exclu_jusqu_au": iso(exclu),
           "note": ("Observé depuis cette installation (son adresse réseau) : vaut pour cette machine, pas "
                    "pour l'accès en général ; cache_purger('antirobot') oublie cet historique.")}
    return {k: v for k, v in out.items() if v is not None}


@mcp.tool()
def archives_registres(service: str, commune: str, annee: int, type_acte: str = "", page: int = 1,
                      personne: str = "", annee_fin: int = 0) -> dict:
    """Localiser un registre par commune et année, sans connaître son ARK. Services : AD59, et les services
    Mnesys du référentiel dotés de recherche_registres (AD14, AD19, AD25, AD27, AD37, AD39, AD51, AD55, AD58, AD69,
    AD80, AD90, AD91, AD972 ; AD25 : TD, RM et SUCC seulement ; archives_service ou sources_catalogue pour la
    liste à jour) : leur formulaire public est lu et la commune est prise dans son vocabulaire (commune_service ;
    valeur exacte acceptée en cas d'ambiguïté).
    Services Mnesys seulement : RM (registres matricules : annee = classe, soit l'année de naissance + 20 ;
    commune = bureau de recrutement, facultatif ; AD19, AD25, AD27, AD39, AD55, AD58, AD69, AD90, AD972) et SUCC
    (tables des successions et absences, série 3 Q : commune = bureau de l'enregistrement ; AD25, AD27,
    AD37 (canton), AD58, AD69, AD90, AD91).
    type_acte : N (naissance), M (mariage), D (décès), NMD ou vide (tous), TD (tables décennales : tables dont
    la période affichée recoupe l'année ou l'intervalle demandé). annee_fin (facultatif, >= annee) : intervalle
    [annee, annee_fin], ex. 1790-1802 ou une décennie ; registres dont la période le recoupe. Une seule page de
    résultats par appel ; page_suivante permet de poursuivre explicitement. Cote, ARK et période proviennent du
    résultat officiel ; une recherche vide ne prouve pas l'absence de l'acte. personne désigne seulement
    la cible locale, pour la garde des vivants et le journal ; cet identifiant n'est pas envoyé au service."""
    if refus := _garde(personne=personne, texte=commune):
        return refus
    a = app()
    try:
        return registres.rechercher(a.sctx, service, commune, annee, type_acte, page, personne, annee_fin)
    except (SourceError, ValueError) as exc:
        return error_envelope(a.sctx, "archives", "registres",
                              {"service": service, "commune": commune, "annee": annee,
                               "type_acte": type_acte, "page": page, "annee_fin": annee_fin}, exc,
                              personne=personne or None)


@mcp.tool()
def archives_naviguer(source: str, page: int = 0, pas: int = 20, enquete: str = "") -> dict:
    """Parcourir les vues d'un registre d'archives sans connaître la vue à l'avance : renvoie une fenêtre de
    vues (numéro, ARK de vue, image) et les métadonnées du registre (titre, cote, commune, période, nombre
    de vues). source : ARK de registre ou de vue d'une visionneuse Naoned reconnue (AD59, services Mnesys), ARK Gallica ou manifeste IIIF.
    page : première vue à lister (1 = début) ; pas : taille de fenêtre (1-100). Ensuite archive_image ou
    piece_archiver sur une vue choisie. nb_vues indique le total ; fin_de_registre signale la dernière fenêtre
    et vue_suivante son prochain début (None en fin). Hors bornes : erreur avec les numéros valides.
    Une navigation produit une entrée au journal, y compris depuis le cache.
    Ne localise pas un acte à partir d'un nom (voir la recherche du
    service, liens_recherche/cotes_a_consulter pour trouver le registre).
    enquete (facultatif) : id d'enquête où noter la fenêtre parcourue ; deja_fait signale la même fenêtre
    déjà notée ou des vues déjà lues. Avec enquete, les requêtes émises consomment le budget de l'enquête
    (budget = reste) ; budget épuisé : refus avant la requête, enquête bloquée, appel consigné."""
    a = app()
    params = {"source": source, "page": page, "pas": pas}
    if refus := _budget_avant(enquete, "archives_naviguer", params):
        return refus
    with _mesure(enquete) as m:
        res, out = _naviguer(a, source, page, pas, params)
    if out is not None:
        return _budget_apres(enquete, m, "archives_naviguer", params, out)
    res = _budget_apres(enquete, m, "archives_naviguer", params, res)
    fen = res.get("fenetre") or {}
    fenetre = [fen["de"], fen["a"]] if fen.get("de") and fen.get("a") else None
    reg = res.get("registre") or {}
    return _suivi_enquete("archives_naviguer", params, res, enquete, fenetre, resultat="positif",
                          journal=[res["journal"]], registre=source, nb_vues=res.get("nb_vues"),
                          titre=reg.get("titre") or "", cote=reg.get("cote") or "", appel=params,
                          periode=reg.get("periode"))


@mcp.tool()
def archives_sonder(source: str, date_cible: str, type_acte: str = "", lecture: dict | None = None,
                    conclusion: str = "", enquete: str = "", nb_vues: int = 0, periode: str = "",
                    lectures: list[dict] | None = None, ordre_series: list[str] | None = None,
                    max_lectures: int = 15) -> dict:
    """Sondage guidé d'un registre chronologique : quelle vue lire pour atteindre date_cible, sans tâtonner.
    Aucun réseau : le modèle lit la vue proposée (action : archive_image), puis rappelle archives_sonder avec
    lecture={vue, date, date_fin?, type?} (date = premier acte de la vue, date_fin = dernier acte, type =
    naissance|mariage|deces|table) ; l'outil resserre les bornes et propose la vue suivante : interpolation
    sur la période et les dates lues, puis dichotomie si l'interpolation n'a pas divisé l'intervalle par deux.
    type_acte (naissance, mariage, deces) : registre à plusieurs séries à la suite (ordre_series, défaut
    naissance, mariage, deces, table ; [] = types ignorés, actes mêlés) : la section du bon type est trouvée
    d'abord. date_cible : jour, mois ou année (première vue de la période).
    Arrêts (arret) : localise (vues à lire recadrées), absent (dates lues encadrant la cible : registre négatif
    journalisé avec les bornes examinées), budget (enquête bloquée, images épuisées, max_lectures) ; conclusion
    = trouve | absent pour clore après lecture de l'acte.
    enquete (recommandé) : enquête où le sondage est noté (lectures, historique, verdict ; source = ARK,
    URL ou id du registre r1…) ; nb_vues et la période viennent de archives_naviguer. Sans enquete : passer
    nb_vues, periode (« 1860-1869 ») et lectures (dans l'ordre fait), rien n'est noté."""
    try:
        if enquete:
            plan = app().enquetes.sonder(enquete, source, date_cible, type_acte, lecture, conclusion, nb_vues,
                                         periode or None, ordre_series, max_lectures)
        else:
            lus = [*(lectures or []), *([lecture] if lecture else [])]
            plan = sondage.planifier(nb_vues, date_cible, lus, type_acte, periode or None, None, ordre_series)
            if conclusion in ("trouve", "absent"):
                plan.update(arret=conclusion, motif="Conclusion indiquée (sans enquete : rien n'est noté).")
            elif not plan["arret"] and max_lectures and len(lus) >= max_lectures:
                plan.update(arret="budget", motif=f"{max_lectures} lectures sans localiser la date.")
            plan["source"] = source
    except (EnqueteError, sondage.SondageError) as exc:
        return {"erreur": str(exc)}
    return _consigne_sondage(plan, enquete)


def _consigne_sondage(plan: dict, enquete: str) -> dict:
    """Action prête (outil et paramètres) et consigne de la suite d'un sondage."""
    src, arret = plan.get("source", ""), plan.get("arret", "")
    suite = {"enquete": enquete} if enquete else {}
    rappel = ("puis archives_sonder(source, date_cible, type_acte, lecture={vue, date, date_fin, type}"
              + (", enquete)" if enquete else ", lectures=[…toutes les lectures dans l'ordre…], nb_vues, periode)"))
    if not arret:
        v = plan["prochaine_vue"]
        plan["action"] = {"outil": "archive_image",
                          "parametres": {"source": src, "page": v, "largeur": 800, "gris": True, **suite}}
        L, R = plan["bornes"]
        if 2 <= R - L + 1 <= sondage.MAX_PLANCHE:
            plan["alternative"] = {"outil": "archives_planche", "parametres": {
                "source": src, "de": L, "a": R, "bandeau": "pct:0,0,100,35", **suite},
                "motif": "Registre AD59 : une planche-contact des vues restantes au lieu d'une vue par lecture."}
        plan["consigne"] = (f"Lire la vue {v} (action) : relever la date du premier acte (date), du dernier "
                            f"(date_fin) et le type d'acte, {rappel}. Ne pas transcrire à ce stade.")
    elif arret == "localise":
        vues = plan["vues"]
        plan["action"] = {"outil": "archive_image", "parametres": {
            "source": src, "page": vues[0], "largeur": 1600, "gris": True, **suite}}
        plan["consigne"] = (f"Date cible localisée : vue(s) {vues}. Lire l'acte (recadrer region pct:x,y,l,h), puis "
                            "archives_sonder(…, conclusion='trouve' ou 'absent', lecture={vue, …}) ; acte trouvé : "
                            "piece_archiver puis transcription.")
    elif arret == "absent":
        plan["consigne"] = ("Acte absent des bornes examinées" + (" (négatif journalisé dans l'enquête)" if enquete
                                                                 else " : le tracer au journal (journal_ajouter)")
                            + ". Prochaine source : autre registre (année voisine, commune voisine, tables "
                            "décennales) ou consultation sur place.")
    elif arret == "budget":
        plan["consigne"] = ("Arrêt : " + plan.get("motif", "budget") + " Rendre compte à l'utilisateur ; ne pas "
                            "continuer le sondage sans son accord.")
    elif arret == "trouve":
        plan["consigne"] = "Acte trouvé : piece_archiver, transcription, puis arbre_proposer avec la citation."
    return plan


def _naviguer(a: App, source: str, page: int, pas: int, params: dict) -> tuple[dict | None, dict | None]:
    """(résultat, None) ou (None, enveloppe d'erreur)."""
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
    except (SourceError, ValueError) as exc:  # VisionneuseError et IiifError sont des ValueError
        out = error_envelope(a.sctx, "archives", "naviguer", params, exc)
        if out.get("statut") != "bloque_antirobot":
            out["conseil"] = ("Vérifier l'ARK ou l'URL du registre (archives_service pour la visionneuse du service) ; "
                              "sinon ouvrir le registre dans le navigateur (liens_recherche, cotes_a_consulter).")
        return None, out
    return res, None


@mcp.tool()
def diagnostic(reseau: bool = True, vivants: bool = False) -> dict:
    """Diagnostic d'exploitation : tableau « contrôle, état (ok/attention/erreur), détail, remède » —
    version du serveur et du plugin sur disque, configuration effective (sans secret), git, uv, droits,
    espace disque, taille des caches, OCR, propositions en attente/expirées, et si reseau=True la
    joignabilité de chaque source (verdict joignable/protection/injoignable, une requête par source, tracée
    au journal) et de Gramps Web (joignabilité, version de l'API et de Gramps, rôle du compte, réglages lisibles
    sans droit Admin). Fonctionne même si la configuration est invalide. vivants=True (mode gramps, réseau) : contrôle
    des personnes vivantes (#264) — vivants non privés et exposition aux comptes Invité, privés à retirer, divergence
    avec le calcul de Gramps — au prix d'une lecture complète de l'arbre et de 30 requêtes /api/living/ au plus ;
    comptes et identifiants seulement. Par défaut : non lancé (une ligne d'information)."""
    from . import diagnostic as diag

    try:
        a = app()
    except Exception as exc:  # noqa: BLE001 — rapporté comme contrôle « configuration »
        return diag.executer(exc, verifier_demarrage(), reseau)
    return diag.executer(a, verifier_demarrage(a.config), reseau, vivants)


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
def variantes_noms(nom: str, prenom: str = "") -> dict:
    """Graphies françaises et allemandes à essayer dans les fonds étrangers (Arolsen, Bundesarchiv, Volksbund,
    listes de prisonniers ou de déportés) : tréma et transcription (Müller, Mueller, Muller), ß/ss, ei/ai/ey/ay,
    finales dt/tt/t/d, -mann/-man, C/K ; prénoms Jean/Johann/Hans, Joseph/Josef, Charles/Karl… Sans réseau.
    Une graphie commune ne prouve pas l'identité : recouper (comparer_profils)."""
    from .normalize import allemand

    return {"nom": allemand.variantes_nom(nom), "prenoms": allemand.variantes_prenom(prenom),
            "combinaisons": allemand.combinaisons(nom, prenom),
            "consigne": ("Variantes à essayer une par une dans le formulaire du site (navigateur de l'utilisateur) ; "
                         "noter chaque recherche, y compris négative (journal_ajouter ou source_collee).")}


@mcp.tool()
def convertir_date(date_texte: str) -> dict:
    """Analyse/convertit une date : GEDCOM, texte français, républicain (« 12 vendémiaire an III »), julien.
    Renvoie équivalents grégorien/républicain/julien, intervalle et forme GEDCOM 7 / 5.5.1, et `gramps` : la date
    au format Gramps (`date` : objet Date JSON de Gramps Web, `xml` : élément Gramps XML, `affichage` : affichage
    de Gramps en anglais, format ISO), correspondance de docs/gramps-web.md."""
    from .gramps.types import affichage_gramps, date_to_gramps

    out = d.convert(date_texte)
    if "erreur" not in out:
        brut = (date_texte or "").strip()
        dt = date_to_gramps(brut if d.analyser_gedcom(brut) else out["gedcom"])
        out["gramps"] = {"date": dt, "xml": gramps_xml.date_xml(dt), "affichage": affichage_gramps(dt)}
    return out


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
    « communicable » et « en ligne » (référentiel des archives) et propose sinon une demande avec modèle de courrier ;
    lieu hors de France : pays, communicable null et communicable_si_transcrit_en_france, sans service d'AD."""
    return communicability_online(document, date_document, date_naissance, date_deces, lieu, personne)


@mcp.tool()
def prochaine_source(fait: str, date_fait: str = "", lieu: str = "") -> list[dict]:
    """Sources à consulter en priorité pour étayer un fait. Avec lieu, chaque piste porte pays (code, nom,
    provenance) : hors de France, aucune série d'AD ; pays inconnu, séries d'AD « si le lieu est en France »."""
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
def arbre_recherche(texte: str = "", nom: str = "", prenom: str = "", ne_vers: str = "", limite: int = 30,
                    etiquette: str = "", objet: str = "personne", groupes_noms: bool = True) -> list[dict]:
    """Cherche dans l'arbre local (nom/prénom normalisés, variantes, ±2 ans). etiquette : seulement les personnes
    portant cette étiquette (nom exact, sensible à la casse), seule ou avec les autres critères. Chaque résultat
    donne ses étiquettes. objet="source" : les sources au lieu des personnes (texte : extrait du titre ou de
    l'auteur), par exemple les billets du blog de Gramps Web avec etiquette="Blog". Mode gramps, groupes_noms=True
    (défaut), pour les personnes : les patronymes regroupés par Gramps sous le même nom de groupe que le nom
    cherché (name groups, #276 ; ou group_as du nom de la personne) sont AJOUTÉS, marqués via_groupe_noms=True ;
    aucun résultat n'est retiré (au plus limite ajouts, listés après les autres) ; groupes_noms=False : recherche
    d'avant. Mode fichier : pas de groupes, rien ne change. Un groupe de noms n'est pas une fusion : il ne prouve
    aucune identité."""
    a = app()
    t = a.tree()
    if objet == "source":
        return _recherche_sources(t, texte or nom, etiquette, limite)
    if objet != "personne":
        return [{"erreur": f"objet {objet!r} : personne (défaut) ou source"}]
    out = []
    q = {"nom": nom, "prenoms": prenom, "naissance": {"date": ne_vers}}
    if texte and not (nom or prenom):
        nn = normalize_name(texte)
        q["nom"], q["prenoms"] = nn["nom_original"], nn["prenoms"]
    groupes, group_as = (_groupes_noms() if groupes_noms and q["nom"] else None), {}
    if groupes is not None:
        group_as = {p["gramps_id"]: (p.get("primary_name") or {}).get("group_as") or ""
                    for p in a.backend.snapshot(fresh=False).all("Person").values()}
        cle_voulue = groupes.cle_groupe(q["nom"])
    for pid in t.personnes:
        if etiquette and etiquette not in t.personnes[pid].tags:
            continue
        prof = matching.profile_from_person(t, pid)
        via_groupe = False
        if q["nom"] and surname_similarity(q["nom"], prof["nom"])["score"] < 0.85:
            if groupes is None:
                continue
            propre = group_as.get(pid, "")  # group_as du nom : prime sur le regroupement global (Gramps)
            if not (gn.cle_typographique(propre) == cle_voulue if propre else groupes.meme_groupe(q["nom"], prof["nom"])):
                continue
            via_groupe = True
        res = matching.compare_profiles({k: v for k, v in q.items() if v}, prof)
        out.append({"id": pid, "nom": t.personnes[pid].nom_principal.complet,
                    "naissance": prof["naissance"], "deces": prof["deces"], "score": res["score"],
                    "etiquettes": list(t.personnes[pid].tags), **({"via_groupe_noms": True} if via_groupe else {})})
    out.sort(key=lambda r: -r["score"])
    # les ajouts « via groupe de noms » ne prennent jamais la place d'un résultat d'avant : listes séparées
    return [r for r in out if not r.get("via_groupe_noms")][:limite] + [r for r in out if r.get("via_groupe_noms")][:limite]


def _recherche_sources(t, texte: str, etiquette: str, limite: int) -> list[dict]:
    """Sources (titre, auteur, étiquettes, confidentialité, médias dans l'ordre) ; billets du blog signalés (#261)."""
    pli = texte.casefold().strip()
    out = []
    for sid, s in sorted(t.sources.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if etiquette and etiquette not in s.tags:
            continue
        if pli and pli not in f"{s.titre} {s.auteur}".casefold():
            continue
        out.append({"id": sid, "titre": s.titre, "auteur": s.auteur, "prive": s.prive, "etiquettes": list(s.tags),
                    "medias": list(s.medias), "billet": est_billet(s),
                    **({"tache": taches_gramps.etat(s)} if taches_gramps.est_tache(s) else {})})
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
    """Contrôles biologiques et chronologiques (une personne ou tout l'arbre), marqueurs à valeur unique en double
    (#311 : Genealogiste-Vivant contradictoires, Genealogiste-UID en double…). Tout l'arbre en mode gramps : aussi
    les types personnalisés qui doublonnent un type standard de Gramps (« Baptême » pour Baptism…), par classe avec
    le nombre d'objets, et les libellés ambigus (normalisation : gramps_normaliser_types) ; et les personnes rendues
    privées par Genealogiste parce que vivantes qui ne le sont plus (retrait : gramps_proteger_vivants), et les fiches
    de preuve restées sur une autre personne après une fusion native (recalcul : gramps_recalculer_notes)."""
    a = app()
    t = a.tree()
    if id:
        return coherence.check_person(t, id)
    out = coherence.check_tree(t)
    if a.config.backend == "gramps":
        out += _types_en_doublon(a)
        out += _prive_a_retirer(a)
        out += _notes_preuve_orphelines(a)
    return out


def _notes_preuve_orphelines(a) -> list[dict]:
    """#311 : fiches de preuve générées restées sur une autre personne que celle qu'elles décrivent (fusion native
    de Gramps) ; recalcul proposé par gramps_recalculer_notes, jamais automatique."""
    from .gramps.mapping import notes_preuve_orphelines

    return [{"niveau": "alerte", "code": "note_preuve_orpheline", "personne": x["personne"],
             "message": f"{x['personne']} porte la fiche de preuve générée de {x['decrit']} (note {x['note']}), "
                        "restée après une fusion faite hors du plugin : elle décrit une autre personne ; "
                        "gramps_recalculer_notes propose le recalcul (accord explicite requis).", **x}
            for x in notes_preuve_orphelines(a.backend.snapshot(fresh=False))]


def _prive_a_retirer(a) -> list[dict]:
    """#264 : personnes marquées privées par Genealogiste « parce que vivantes » qui ne sont plus présumées vivantes
    (décès saisi, âge dépassé) : retrait à proposer par gramps_proteger_vivants, jamais automatique."""
    e = a.backend.etat_vivants()
    return [{"niveau": "info", "code": "prive_vivant_a_retirer", "personne": pid,
             "message": f"{pid} n'est plus présumé(e) vivant(e) : des objets que Genealogiste a marqués privés pour "
                        "cette personne (elle-même ou ses données propres) le restent ; gramps_proteger_vivants "
                        "propose le retrait (accord explicite requis)."}
            for pid in e["a_retirer"]]


def _types_en_doublon(a) -> list[dict]:
    """Alertes « type personnalisé en doublon » (#273) sur la base Gramps Web déjà lue (aucune écriture)."""
    from .gramps.mapping import types_en_doublon

    d = types_en_doublon(a.backend.snapshot(fresh=False))
    out = [{"niveau": "info", "code": "type_personnalise_doublon", "personne": "",
            "message": f"{x['classe']} personnalisé « {x['chaine']} » ({x['objets']} objet(s), {x['occurrences']} "
                       f"occurrence(s)) = type standard {x['standard']} (« {x['libelle']} ») : lu comme tel ; "
                       "gramps_normaliser_types pour l'écrire en type standard.", **x} for x in d["doublons"]]
    out += [{"niveau": "info", "code": "type_personnalise_ambigu", "personne": "",
             "message": f"{x['classe']} personnalisé « {x['chaine']} » ({x['objets']} objet(s)) : libellé de "
                        f"plusieurs types standard ({', '.join(x['candidats'])}), gardé tel quel, jamais tranché.",
             **x} for x in d["ambigus"]]
    return out


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
def arbre_lacunes(id: str = "", taches: bool = False) -> dict:
    """Faits manquants ou faibles + plan de recherche priorisé (une personne, ou classement de tout l'arbre).
    medias_a_lier : images jointes à une citation mais absentes de la personne, de l'événement ou de la source
    qu'elle prouve, avec l'opération modifier_media (lier_a) à soumettre par arbre_proposer.
    taches=true (avec id, GENEALOGISTE_GRAMPS_TACHES) : taches_a_proposer, une opération ajouter_tache par action
    (priorité Gramps calculée de la priorité de lacune : 0-1 haute, 2 moyenne, 3 basse), à soumettre par
    arbre_proposer ; rien n'est écrit."""
    t = app().tree()
    out = gaps(t, id, app().config.strict_evidence) if id else tree_gaps(t, app().config.strict_evidence)
    if taches:
        if not app().taches_actives():
            out["taches_a_proposer"] = {"erreur": taches_gramps.DESACTIVE}
        elif not id:
            out["taches_a_proposer"] = {"erreur": "préciser id : tâches proposées pour une personne à la fois"}
        else:
            out["taches_a_proposer"] = {
                "operations": taches_gramps.operations_lacunes(out, id),
                "titre": f"Tâches de recherche : {out['personne']}",
                "justification": "Plan de lacunes (arbre_lacunes) rendu visible dans la vue Tâches de Gramps Web ; "
                                 "priorité Gramps calculée de la priorité de lacune ; tâches privées.",
                "consigne": "Proposer seulement les actions retenues par l'utilisateur (arbre_proposer, diff, "
                            "accord, arbre_appliquer) ; vérifier d'abord les tâches existantes "
                            "(arbre_recherche(etiquette=\"ToDo\", objet=\"source\"))."}
    return out


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
    ajouter_source, modifier_source, supprimer_source, fusionner_sources, ajouter_depot, ajouter_citation,
    supprimer_citation, ajouter_media, modifier_media, ajouter_billet (blog de Gramps Web), ajouter_tache et
    modifier_tache (tâches de Gramps Web, GENEALOGISTE_GRAMPS_TACHES), ajouter_association,
    supprimer_association, fusionner_personnes, scinder_personne, definir_statut, marquer_vivant,
    dedoublonner_marqueurs (marqueurs en double après une fusion faite hors du plugin), etiqueter.
    Étiquettes : tags (ajout) sur les ajouts et modifications, tags_retrait sur les modifications, etiqueter
    pour tout objet existant (famille, dépôt, note, citation…).
    Texte des notes : brut par défaut ; format_texte="markdown" sur l'opération pour **gras**, *italique* et
    [liens](https://…) (mise en forme écrite dans Gramps Web en mode gramps, annoncée comme perdue en mode fichier).
    Tâche (ajouter_tache : titre, description, statut Open|In Progress|Blocked|Done, priorite haute|moyenne|basse,
    personnes, enquete + element) : privée par défaut, même garde des vivants que le billet.
    Billet du blog (ajouter_billet, ou source étiquetée Blog) : privé par défaut ; public refusé s'il nomme une
    personne présumée vivante. Règle de métier : tout événement ou filiation exige une citation, sauf
    non_source=true + motif.
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
    if "erreur" not in res and (trace := res.pop("trace_enquete", None)):  # signets d'enquête (#282)
        try:
            res["enquete_signets"] = a.enquetes.trace_signets(trace["enquete"], trace["poses"], trace["retires"])
        except EnqueteError as exc:  # enquête supprimée à la main : les signets restent écrits et journalisés
            res["enquete_signets"] = {"erreur": str(exc)}
    if "erreur" not in res and (entree := a.file.par_jeton(jeton)):  # reprise d'une proposition de la file
        ref = {k: res[k] for k in ("commit", "transaction") if res.get(k)}
        a.file.maj(entree["id"], fp.APPLIQUEE, f"appliquée (jeton {jeton})", **ref)
        res["proposition_file"] = entree["id"]
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
    """Prépare l'import d'un fichier GEDCOM (5.5.1 ou 7) ou Gramps Desktop (Gramps XML 1.7.1/1.7.2 « .gramps »,
    gzip ou non, ou paquet « .gpkg »), format reconnu au contenu : mode 'ajouter' (renumérote, doublons à
    recouper) ou 'remplacer'. Renvoie une proposition (diff + jeton) à valider ; rien n'est écrit dans l'arbre.
    Gramps : bilan 'non_repris' (ce que l'arbre ne représente pas) ; médias d'un .gpkg extraits dans une zone
    d'attente du répertoire de données, jamais rangés sans accord (pieces_proposer ensuite)."""
    p = Path(chemin).expanduser()
    if not p.is_file():
        return {"erreur": f"Fichier introuvable : {p}"}
    if mode not in ("ajouter", "remplacer"):
        return {"erreur": "mode : ajouter | remplacer"}
    from .gramps import lecture_xml

    try:
        fmt = lecture_xml.detecter(p)
    except lecture_xml.LectureGrampsError as exc:
        return {"erreur": f"Fichier illisible : {exc}"}
    if fmt != "gedcom":
        return _importer_gramps(p, mode)
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        tree, info = read_gedcom(text)
    except ValueError as exc:
        return {"erreur": f"GEDCOM illisible : {exc}"}
    app().journal.add("import", "gedcom", {"fichier": str(p), "mode": mode}, "positif", nb_resultats=info["personnes"])
    return _proposer_import(tree, info, mode, f"Import GEDCOM {p.name} ({mode})",
                            f"Import du fichier {p.name} ({info['version_source']}, {info['personnes']} personnes).")


def _proposer_import(tree, info: dict, mode: str, titre: str, origine: str) -> dict:
    """Même contrat pour tout import : opération remplacer_arbre (modes ajouter / remplacer), diff, jeton."""
    try:
        prop = _gramps_guard(lambda: app().backend.propose(
            [{"op": "remplacer_arbre", "mode": mode, "gedcom_texte": write_gedcom(tree)}], titre,
            f"{origine} Données importées non vérifiées : statut à établir fait par fait.", []))
    except ProposalError as exc:
        return {"erreur": str(exc)}
    if "erreur" in prop:
        return prop
    prop["import"] = info
    if len(prop["diff"]) > 8000:
        prop["diff"] = prop["diff"][:8000] + "\n… (diff tronqué : import volumineux)"
    return prop


def _importer_gramps(p: Path, mode: str) -> dict:
    """Import Gramps Desktop (#269) : Gramps XML -> objets Gramps -> gramps_to_tree (correspondance unique),
    puis le même chemin que l'import GEDCOM. Local : aucune donnée ne sort (vivants, privés)."""
    from datetime import datetime

    from .gramps import lecture_xml

    a = app()
    try:
        tree, info, zone = lecture_xml.importer(p, a.config.data_dir, datetime.now().strftime("%Y%m%d-%H%M%S"),
                                                a.config.sosa_racine, mode, a.config.media_racines,
                                                a.config.pieces_root)
    except (lecture_xml.LectureGrampsError, OSError) as exc:  # OSError : lecture, zone d'attente
        a.journal.add("import", "gramps", {"fichier": str(p), "mode": mode}, "erreur")
        return {"erreur": f"Fichier Gramps refusé : {exc}"}
    a.journal.add("import", "gramps", {"fichier": str(p), "mode": mode, "format": info["format"]}, "positif",
                  nb_resultats=info["personnes"])
    prop = _proposer_import(tree, info, mode, f"Import Gramps {p.name} ({mode})",
                            f"Import du fichier Gramps {p.name} ({info['format']}, Gramps XML {info['version_xml']}, "
                            f"Gramps {info['version_gramps']}, {info['personnes']} personnes).")
    if "erreur" in prop and zone is not None:
        shutil.rmtree(zone, ignore_errors=True)  # zone neuve créée par cet appel : rien d'autre n'y est
    ref = info.get("personne_reference") or {}
    if ref.get("suggestion"):
        prop.setdefault("avertissements", []).append(ref["suggestion"])
    if info.get("regroupements"):
        prop.setdefault("avertissements", []).append(
            f"{info['regroupements']['nombre']} groupe(s) de noms (<namemaps>) lus, non appliqués : voir "
            "import.regroupements (Genealogiste n'écrit pas les groupes de noms ; aucune personne fusionnée).")
    if info.get("non_repris"):
        prop.setdefault("avertissements", []).append(
            "Contenu Gramps non représenté par l'arbre Genealogiste, non importé : voir import.non_repris "
            "(valeurs en moins par champ Gramps ; docs/gramps.md#import-depuis-gramps-desktop).")
    return prop


# ============================================================================ file de propositions (#154)

def _personnes_visees(ctx, operations: list[dict]) -> list[str]:
    """Personnes existantes visées : ids cités, propriétaires des événements visés, époux des familles visées."""
    cibles = (targets(ctx, operations) or set()) - {v.strip("@") for v in ctx.refs.values()}
    out: set[str] = set()
    for pid, p in ctx.tree.personnes.items():
        if pid in cibles or {e.uid for e in p.evenements} & cibles:
            out.add(pid)
    for fid, f in ctx.tree.familles.items():
        if fid in cibles or {e.uid for e in f.evenements} & cibles:
            out.update(x for x in (f.epoux, f.epouse) if x)
    return sorted(out)


def _resume_entree(e: dict) -> dict:
    out = {k: e[k] for k in ("id", "titre", "statut", "raison", "depose", "personnes", "enquete", "jeton",
                             "commit", "transaction") if e.get(k) or k in ("id", "statut")}
    out.update(nb_operations=len(e.get("operations", [])), nb_pieces=len(e.get("pieces", [])))
    return out


@mcp.tool()
def propositions_deposer(operations: list[dict], titre: str, justification: str, sources: list[str] | None = None,
                         pieces: list[str] | None = None, personnes: list[str] | None = None,
                         enquete: str = "") -> dict:
    """Range une proposition dans la file durable pour une validation différée (enquête sans surveillance).
    Rien n'est écrit dans l'arbre. Les opérations (celles d'arbre_proposer, docs/operations.md) sont validées à
    sec sur l'arbre courant, règle EXIGER_SOURCE comprise : un dépôt invalide est refusé. pieces : chemins ou
    références des pièces à l'appui ; personnes : ids visés (complétés d'après les opérations) ; enquete : origine
    (texte libre). Revue : /genealogiste:valide, propositions_reprendre(id) puis arbre_appliquer après accord."""
    a = app()

    def valider() -> dict:
        tree = a.tree()
        ctx = prepare(tree, operations, titre, justification, sources, a.config.exiger_source,
                      a.config.media_reference, a.backend.name, a.taches_actives())[0]
        if write_gedcom(ctx.tree) == write_gedcom(tree) and not taches_gramps.lignes(tree, ctx.tree):
            raise ProposalError("La proposition ne modifie rien.")
        return {"ctx": ctx, "tree": tree}

    try:
        v = _gramps_guard(valider)
    except ProposalError as exc:
        return {"erreur": str(exc)}
    if "erreur" in v:
        return v
    ctx = v["ctx"]
    visees = sorted(set(personnes or []) | set(_personnes_visees(ctx, operations)))
    e = a.file.deposer({"titre": titre, "justification": justification, "operations": operations,
                        "sources": list(sources or []), "pieces": list(pieces or []), "personnes": visees,
                        "enquete": enquete})
    return {"id": e["id"], "statut": e["statut"], "resume": ctx.summary, "personnes": visees,
            "alertes_coherence_a_sec": new_alerts(v["tree"], ctx.tree), "avertissements": ctx.warnings,
            "consigne": "Rien n'est écrit. Revue : /genealogiste:valide ou propositions_reprendre(id), puis "
                        "arbre_appliquer après accord explicite."}


@mcp.tool()
def propositions_lister(statut: str = "") -> dict:
    """File des propositions déposées. statut : '' (en_attente et a_revoir), en_attente, a_revoir, appliquee,
    abandonnee ou tous. Résumé sans les opérations (voir propositions_reprendre)."""
    if statut and statut != "tous" and statut not in fp.STATUTS:
        return {"erreur": f"statut inconnu : {statut} ({', '.join(fp.STATUTS)}, tous)"}
    filtre = None if statut == "tous" else (statut,) if statut else fp.OUVERTS
    entrees = app().file.lister(filtre)
    compte: dict[str, int] = {}
    for e in entrees:
        compte[e["statut"]] = compte.get(e["statut"], 0) + 1
    return {"propositions": [_resume_entree(e) for e in entrees], "compte": compte}


@mcp.tool()
def propositions_reprendre(id: str) -> dict:
    """Rejoue une proposition de la file sur l'arbre courant : diff frais, alertes de cohérence nouvelles et jeton
    neuf (le jeton précédent de l'entrée est annulé), avec justification, sources et pièces à l'appui. Si les
    opérations ne s'appliquent plus (personne modifiée, conflit, EXIGER_SOURCE), l'entrée passe « a_revoir » avec
    la raison. Rien n'est écrit : arbre_appliquer(jeton) seulement après accord explicite."""
    a = app()
    try:
        e = a.file.lire(id)
    except fp.FileError as exc:
        return {"erreur": str(exc)}
    if e["statut"] not in fp.OUVERTS:
        return {"erreur": f"Proposition {id} {e['statut']} : rien à reprendre.", "statut": e["statut"]}
    if e.get("jeton"):
        a.backend.cancel(e["jeton"])
    try:
        r = _gramps_guard(lambda: a.backend.propose(e["operations"], e["titre"], e["justification"],
                                                    e.get("sources")))
    except ProposalError as exc:
        a.file.maj(id, fp.A_REVOIR, "reprise impossible", raison=str(exc), jeton="")
        return {"erreur": str(exc), "id": id, "statut": fp.A_REVOIR, "raison": str(exc)}
    if "erreur" in r:  # Gramps Web injoignable : entrée inchangée
        return r
    e = a.file.maj(id, fp.EN_ATTENTE if e["statut"] == fp.A_REVOIR else None, "reprise", jeton=r["jeton"])
    r["proposition"] = {k: e.get(k) for k in ("id", "titre", "justification", "sources", "pieces", "personnes",
                                              "enquete", "depose", "statut")}
    return r


@mcp.tool()
def propositions_abandonner(id: str, motif: str = "") -> dict:
    """Abandonne une proposition de la file (conservée pour mémoire, statut « abandonnee ») et annule son jeton
    en cours. Rien n'est écrit dans l'arbre."""
    a = app()
    try:
        e = a.file.lire(id)
    except fp.FileError as exc:
        return {"erreur": str(exc)}
    if e["statut"] not in fp.OUVERTS:
        return {"erreur": f"Proposition {id} déjà {e['statut']}.", "statut": e["statut"]}
    if e.get("jeton"):
        a.backend.cancel(e["jeton"])
    e = a.file.maj(id, fp.ABANDONNEE, motif or "abandon", jeton="", motif_abandon=motif)
    return {"id": id, "statut": e["statut"]}


@mcp.tool()
def arbre_exporter(format: str = "gedcom7", chemin: str = "", id: str = "", generations: int = 4,
                   masquer_vivants: bool = True, temoins_en_personnes: bool = False,
                   version_xml: str = gramps_xml.VERSION_XML_DEFAUT, compresse: bool = False,
                   chemin_base_medias: str = "", chercheur: bool | None = None) -> dict:
    """Export : gedcom7 | gedcom551 | geneweb | gramps | gpkg | mermaid_asc | mermaid_desc | svg_asc | svg_desc | fiche.
    geneweb : GEDCOM 5.5.1 pour ged2gwb, avec citations complètes, statut de preuve et témoins visibles dans
    GeneWeb (temoins_en_personnes=True crée une fiche pour chaque témoin seulement nommé).
    gramps : Gramps XML (.gramps) ; version_xml 1.7.1 (défaut : Gramps 5.2, 6.0, 6.1) ou 1.7.2 (Gramps 6.x
    seulement) ; compresse=True : gzip, forme native de Gramps Desktop (défaut : XML non compressé).
    gpkg : paquet Gramps (XML + fichiers des médias locaux sous chemins relatifs) ; médias introuvables ou hors
    des répertoires autorisés listés dans le résultat, jamais empaquetés.
    gramps/gpkg : la racine Sosa (GENEALOGISTE_SOSA_RACINE) devient la personne de référence du fichier
    (<people home>), sauf si elle n'est pas configurée, absente ou masquée par l'export public ; en mode gramps, les
    groupes de noms de Gramps sont écrits (<namemaps>, #276) ; en mode fichier, aucun (rien n'est inventé) ; export
    public : seulement les regroupements dont le patronyme figure dans l'export, sans nom d'une personne masquée.
    gramps : chemin_base_medias (absolu, vide par défaut : aucun <mediapath>, rien de la machine n'est écrit) =
    dossier où la machine qui ouvrira l'arbre trouve la racine du vault ; écrit dans l'en-tête (<mediapath>) et
    les chemins des médias qui s'y trouvent deviennent relatifs à lui (Gramps Desktop les retrouve alors
    directement). Chemin personnel : refusé avec masquer_vivants=True (export public) et pour gpkg (Gramps
    ignore le <mediapath> d'un paquet).
    Mode gramps (#282) : les formats de nom personnalisés (<name-formats>) et les signets de la base (<bookmarks>,
    objets conservés par l'export seulement : un signet vers un objet masqué est retiré) sont écrits dans gramps et
    gpkg. chercheur : fiche du chercheur de la base Gramps (SUBM en gedcom7 et gedcom551, <researcher> en gramps et
    gpkg ; champs street et county absents du XML) ; None (défaut) : écrite seulement dans un export privé
    (masquer_vivants=False), jamais dans un export public ; True : écrite sur demande explicite, même public ; False :
    jamais. Coordonnées personnelles : mode gramps seulement, jamais envoyées à une source externe.
    Vivants et objets privés masqués par défaut (RGPD) : sources, médias et notes liés à une personne masquée
    retirés avec leurs références, noms remplacés par « Vivant » dans les textes. chemin par défaut :
    <données>/exports/."""
    ext = {"gedcom7": "ged", "gedcom551": "ged", "geneweb": "ged", "gramps": "gramps", "gpkg": "gpkg",
           "mermaid_asc": "mmd", "mermaid_desc": "mmd", "svg_asc": "svg", "svg_desc": "svg", "fiche": "md"}
    if format not in ext:
        return {"erreur": f"format : {', '.join(ext)}"}
    if format in ("mermaid_asc", "mermaid_desc", "svg_asc", "svg_desc", "fiche") and not id:
        return {"erreur": "id requis pour ce format"}
    try:
        gramps_xml.verifier_version_xml(version_xml)
    except ValueError as exc:
        return {"erreur": str(exc)}
    base_medias = ""
    if chemin_base_medias:
        if format != "gramps":
            return {"erreur": "chemin_base_medias : format gramps seulement. " + (
                "Gramps remet le chemin de base de l'arbre à l'import d'un .gpkg et range les médias dans "
                "<arbre>.gpkg.media : le <mediapath> y serait ignoré (docs/gramps.md)." if format == "gpkg"
                else "Sans objet pour ce format.")}
        if masquer_vivants:
            return {"erreur": "chemin_base_medias est un chemin personnel de votre machine : refusé dans un export "
                              "public (masquer_vivants=True). masquer_vivants=False pour un fichier qui reste chez vous."}
        try:
            base_medias = gramps_xml.verifier_chemin_base_medias(chemin_base_medias)
        except ValueError as exc:
            return {"erreur": str(exc)}
    a = app()
    fiche: dict[str, str] | None = None
    bilan_chercheur: dict | None = None
    veut_chercheur = (not masquer_vivants) if chercheur is None else chercheur
    if chercheur is True and format not in ("gedcom7", "gedcom551", "gramps", "gpkg"):
        return {"erreur": "chercheur : formats gedcom7, gedcom551, gramps et gpkg seulement (SUBM ou <researcher>)."}
    if chercheur is True and a.config.backend != "gramps":
        return {"erreur": "chercheur : mode gramps seulement (GENEALOGISTE_BACKEND=gramps) : la fiche est celle de la "
                          "base Gramps ; le modèle fichier n'en a pas et n'en invente pas."}
    if veut_chercheur and a.config.backend == "gramps" and format in ("gedcom7", "gedcom551", "gramps", "gpkg"):
        try:
            lue = a.backend.client.chercheur()
        except GrampsError as exc:
            if chercheur is True:
                return {"erreur": f"Fiche du chercheur illisible : {exc}. Rien n'a été écrit."}
            lue = None
            bilan_chercheur = {"ecrit": False, "motif": f"fiche illisible ({exc})"}
        if lue is not None:
            if rg.chercheur_renseigne(lue):
                fiche = lue
            else:
                bilan_chercheur = {"ecrit": False, "motif": "fiche du chercheur vide dans la base Gramps"}
    t = complet = a.tree()
    hidden: set[str] = set()
    rapport: dict = {}
    reduits: dict = {}
    if masquer_vivants:
        t, hidden, rapport = privacy.publication(t)
        if format in ("gedcom7", "gedcom551"):  # export public : aucun chemin absolu de ce poste dans FILE (#307)
            t, reduits = chemins_medias.reduire_chemins_arbre(t)
    membres: dict = {}
    bilan_medias: dict = {}
    bilan_base: dict = {}
    if format == "gedcom7":
        content = write_gedcom(t, 7, fiche)
    elif format == "gedcom551":
        content = write_gedcom(t, 5, fiche)
    elif format == "geneweb":
        content, stats = to_geneweb(t, a.config.strict_evidence, temoins_en_personnes)
    elif format in ("gramps", "gpkg"):
        db, stats = tree_to_gramps_stats(t, None, a.config.strict_evidence, forme=a.config.marqueurs)
        if format == "gpkg":  # médias résolus par la règle commune (racines autorisées), chemins relatifs
            db, membres, bilan_medias = gramps_xml.preparer_gpkg(db, a.config.media_racines)
        elif masquer_vivants and format == "gramps":  # export public : aucun chemin absolu de ce poste
            db, reduits = gramps_xml.reduire_chemins_absolus(db)
        elif base_medias:  # chemins relatifs à la racine du vault, comme <mediapath> (#280)
            db, bilan_base = gramps_xml.chemins_relatifs_a_la_base(db, a.config.media_racines, a.config.pieces_root)
        handle_ref, motif_ref = gramps_xml.personne_reference(db, a.config.sosa_racine, hidden)
        try:  # groupes de noms (#276) : ceux de Gramps en mode gramps ; mode fichier : aucun, rien d'inventé
            table = a.backend.groupes_noms() if a.config.backend == "gramps" else {}
        except GrampsError as exc:
            return {"erreur": f"Groupes de noms illisibles : {exc}. Rien n'a été écrit."}
        regroupements, bilan_groupes = gn.regroupements_exportables(table, complet, t, hidden, masquer_vivants)
        if a.config.backend != "gramps":
            bilan_groupes = {"ecrits": 0, "source": "mode fichier : pas de groupes de noms (rien n'est inventé)"}
        signets_xml: list[tuple[str, str]] = []
        formats_xml: list[tuple[int, str, str, bool]] = []
        bilan_signets: dict = {"ecrits": 0, "source": "mode fichier : pas de signets (rien n'est inventé)"}
        if a.config.backend == "gramps":  # signets et formats de nom de la base (#282)
            try:
                etat = a.backend.client.signets_tous()
                formats_xml = a.backend.client.formats_noms()
            except GrampsError as exc:
                return {"erreur": f"Signets ou formats de nom illisibles : {exc}. Rien n'a été écrit."}
            masques = ({("person", i) for i in hidden}
                       | {("family", f.id) for f in complet.familles.values()
                          if f.prive or f.epoux in hidden or f.epouse in hidden}) if masquer_vivants else set()
            signets_xml, bilan_signets = rg.signets_pour_export(a.backend.snapshot(fresh=False), db, etat, masques)
        chercheur_xml, hors_xml = rg.chercheur_pour_xml(fiche) if fiche else ({}, [])
        content = gramps_xml.db_to_xml(db, version_xml, gramps_xml.Metadonnees(
            chercheur=chercheur_xml, formats_noms=formats_xml, signets=signets_xml,
            personne_reference=handle_ref, regroupements=regroupements, mediapath=base_medias or None))
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
    if masquer_vivants:  # garde-fou, tous formats (#307) : ni répertoire personnel ni de données dans le contenu
        prives = [str(x) for x in (Path.home(), a.config.data_dir) if len(str(x)) > 3]
        if any(x in content for x in prives):
            return {"erreur": "Export public refusé : le répertoire personnel ou le répertoire de données de ce poste "
                              "figure encore dans le fichier (chemin de média). Rien n'a été écrit."}
    reste = privacy.residues(content, rapport.get("motifs", []))
    if format in ("gramps", "gpkg"):  # prénom et patronyme en éléments distincts (<first>, <surname>) : relus à plat
        import re as _re
        reste += privacy.residues(_re.sub(r"<[^>]*>", " ", content), rapport.get("motifs", []))
    if reste:  # garde-fou : la projection a laissé passer une chaîne identifiante
        return {"erreur": "Export refusé : données identifiantes d'une personne masquée encore présentes "
                          f"({len(reste)} occurrence(s)). Rien n'a été écrit.", "occurrences": reste[:20]}
    out = Path(chemin).expanduser() if chemin else a.config.exports_dir / (
        f"{id or 'arbre'}-{format}-{date.today().isoformat()}.{ext[format]}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if format == "gpkg":
        _ecrire_atomique(out, lambda f: gramps_xml.ecrire_gpkg(f, content, membres))
    elif format == "gramps" and compresse:
        out.write_bytes(gramps_xml.compresser(content))
    else:
        out.write_text(content, encoding="utf-8")
    res = {"fichier": str(out), "format": format, "octets": out.stat().st_size,
           "vivants_masques": len(hidden), "retires": rapport.get("retires"), "apercu": content[:1500] if format.startswith(("mermaid", "fiche")) else None}
    if format == "geneweb":
        res["statistiques"] = stats
        res["import"] = f"ged2gwb {out.name} -o <base> -f   (voir docs/geneweb.md)"
    if format in ("gramps", "gpkg"):
        res["statistiques"] = stats
        res["version_xml"] = version_xml
        res["compresse"] = format == "gpkg" or compresse
        res["import"] = ("Gramps Web : Paramètres > Administration > Importer (arbre vide : un second import "
                         "duplique tout)") if format == "gramps" else (
            "Gramps Desktop : Arbre familial > Importer, fichier .gpkg (médias extraits dans <arbre>.gpkg.media ; "
            "arbre vide : un second import duplique tout)")
        if version_xml != "1.7.1":
            res["avertissement"] = f"Gramps XML {version_xml} : refusé par Gramps 5.2 (1.7.1 est lu par 5.2 à 6.1)."
        res["personne_reference"] = ({"ecrite": a.config.sosa_racine} if handle_ref else
                                     {"ecrite": None, "motif": motif_ref})
        res["groupes_de_noms"] = bilan_groupes
        res["signets"] = bilan_signets
        res["formats_de_noms"] = {"ecrits": len(formats_xml)}
        dates = gramps_xml.avertissements_dates(db, version_xml)
        if dates:
            res["avertissements_dates"] = dates
    if format == "gpkg":
        res["medias"] = bilan_medias
    if fiche is not None:
        res["chercheur"] = {"ecrit": True, "champs": rg.champs_renseignes(fiche), "forme": (
            "SUBM" if format.startswith("gedcom") else "<researcher>")}
        if format in ("gramps", "gpkg") and hors_xml:
            res["chercheur"]["champs_absents_du_format"] = hors_xml
        if masquer_vivants:
            res["chercheur"]["avertissement"] = ("Export public : la fiche du chercheur (coordonnées personnelles) "
                                                 "a été écrite sur demande explicite (chercheur=True).")
    elif bilan_chercheur is not None:
        res["chercheur"] = bilan_chercheur
    if reduits.get("nombre"):
        res["chemins_absolus_reduits"] = reduits
    if base_medias:
        res["chemin_base_medias"] = {
            "ecrit": base_medias, "medias": bilan_base,
            "consigne": "Dans Gramps Desktop, ce dossier doit être la racine du vault (Préférences > Général > "
                        "Chemin de base des médias) ; l'import le pose si l'arbre cible n'en a pas, sinon Gramps le "
                        "refuse sans bloquer et garde le sien (docs/gramps.md, « Chemin de base des médias »)."}
    return res


def _ecrire_atomique(out: Path, ecrire) -> None:
    """Fichier écrit à côté puis renommé : rien de partiel en cas d'erreur."""
    import os
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            ecrire(f)
        os.replace(tmp, out)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


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


RAPPORT_CAMPAGNE_MAX = 1_000_000  # caractères


@mcp.tool()
def rapport_campagne_enregistrer(titre: str, contenu: str, enquetes: list[str] | None = None) -> dict:
    """Enregistre le rapport d'une campagne (/genealogiste:campagne) dans un fichier NOUVEAU daté
    <données>/rapports/campagnes/AAAA-MM-JJ-<titre>.md (suffixe -2, -3… si le nom existe : jamais d'écrasement).
    Toujours dans le répertoire de données (GENEALOGISTE_RAPPORTS_DIR ignoré), ni commit, ni push, ni réseau :
    collecte, permise sans accord et avec GENEALOGISTE_ECRITURE=interdite. enquetes : ids des enquêtes couvertes
    (en-tête du rapport). Désigner les personnes par leur id d'arbre ; ne rien y copier d'une personne vivante
    qui ne soit déjà dans l'arbre."""
    import re as _re
    if len(contenu) > RAPPORT_CAMPAGNE_MAX:
        return {"erreur": f"Rapport trop long ({len(contenu)} caractères, maximum {RAPPORT_CAMPAGNE_MAX})."}
    a = app()
    jour = date.today().isoformat()
    slug = _re.sub(r"[^a-z0-9]+", "-", titre.lower()).strip("-")[:60] or "campagne"
    dossier = a.config.data_dir / "rapports" / "campagnes"
    dossier.mkdir(parents=True, exist_ok=True)
    entete = (f"---\ntitre: {json.dumps(titre, ensure_ascii=False)}\ndate: {jour}\n"
              f"enquetes: {json.dumps(list(enquetes or []), ensure_ascii=False)}\n---\n\n")
    texte = entete + contenu + ("" if contenu.endswith("\n") else "\n")
    n = 1
    while True:
        path = dossier / f"{jour}-{slug}{'' if n == 1 else f'-{n}'}.md"
        try:
            with path.open("x", encoding="utf-8") as f:  # création exclusive : jamais d'écrasement
                f.write(texte)
            break
        except FileExistsError:
            n += 1
    return {"fichier": str(path), "date": jour, "enquetes": list(enquetes or []), "commit": None,
            "note": "Rapport local, non versionné ni poussé : il reste dans le répertoire de données. "
                    "Propositions en file : /genealogiste:valide."}


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
           **({"archives": r} if (r := pieces.rattachement_archives(type_piece, cote)) else {}),
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
    from .chemins import CheminAmbigu, localiser

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
        except CheminAmbigu as exc:  # référence ambiguë (#193) : chaque candidat compte comme référencé
            for c in exc.candidats:
                out.setdefault(c.resolve(), []).append((mid, m.fichier))
            continue
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
    ANMT, PM, NOT (acte notarié ; libellé libre après le code : « NOT testament »), TSA (table des successions et
    absences), MPD (déclaration de mutation par décès), CNI, COUR (courrier), REC, SIGN, PHOTO… source (S3) :
    complète dépôt (sigle) et cote depuis l'arbre. Pour NOT, archives indique le type d'archives « notaire » et
    l'état de la cote (sous-série 3 E acceptée, à compléter ou hors 3 E) ; pour TSA et MPD, « enregistrement »,
    la cote 3 Q et la communicabilité propre au code. Ne renomme rien."""
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
    out = {"nom": nom, "dossier_convention": pieces.destination(info) or pieces.A_TRIER, "lecture": pieces.lire_nom(nom)}
    if archives := pieces.rattachement_archives(type_piece, cote):
        out["archives"] = archives
    return out


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
    pour pieces_appliquer, à n'utiliser qu'après accord explicite de l'utilisateur sur le plan. references_notes : liens de
    notes ordinaires qu'un déplacement rendrait caducs, signalés sans être réécrits."""
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
    if plan.get("nb_references_notes"):
        plan["references_notes_conseil"] = (
            "Des notes Markdown ordinaires pointent vers des pièces que ce plan déplace ou renomme : leurs liens "
            "ne seront pas réécrits. Les présenter (references_notes) avant l'accord ; une correction se fait ensuite, "
            "note par note, avec l'accord de l'utilisateur.")
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


# ============================================================================ état d'enquête (#155)

def _enquete(fn):
    try:
        return fn()
    except EnqueteError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def enquete_ouvrir(sujet: str, personnes: list[str] | None = None, id: str = "",
                   budget: dict | None = None, signets: bool = False) -> dict:
    """Ouvre une enquête : état de recherche persistant et reprenable (pistes, progression par registre,
    tâches manuelles, demandes faites), fichier JSON lisible dans <données>/enquetes/<id>.json. id facultatif
    (dérivé du sujet : minuscules, chiffres, tirets), stable : à passer à enquete_noter, enquete_reprendre et
    au paramètre enquete des outils de collecte réseau (recherche_multi, archives_naviguer, archive_image,
    sources…). personnes : ids de l'arbre. budget (facultatif, 0 = illimité ; défauts GENEALOGISTE_BUDGET_*) :
    {requetes_par_hote, images} ; arrête une boucle d'enquête, le coût réel se plafonne côté client
    (--max-budget-usd). Compté côté serveur ; à l'épuisement, refus avant toute requête et enquête « bloque ».
    signets=True (mode gramps, #282) : prépare AUSSI la proposition de mettre en signet de Gramps les personnes de
    l'enquête (jeton pour arbre_appliquer après accord explicite, clé « signets » ; jamais appliquée seule ; seuls
    les signets posés par le plugin seront proposés au retrait à la clôture ; ce sont les signets de la base, menu
    Signets de Gramps Desktop : l'interface de Gramps Web ne les affiche pas). Rien n'est envoyé à une source externe
    (signets=True lit seulement l'instance Gramps Web de l'utilisateur)."""
    def run():
        res = app().enquetes.ouvrir(sujet, personnes, id, budget)
        if signets:
            res = {**res, "signets": _signets_enquete(res["id"], "poser")}
        return res
    return _enquete(run)


@mcp.tool()
def enquete_noter(enquete: str, piste: dict | None = None, registre: dict | None = None, tache: dict | None = None,
                  requete: dict | None = None, statut: str = "", personnes: list[str] | None = None,
                  budget: dict | None = None) -> dict:
    """Note l'avancement d'une enquête (un ou plusieurs éléments par appel ; mise à jour si id existe).
    piste : {id?, question, hypotheses: [..], sources: [texte | {libelle, outil, parametres}] dans l'ordre,
      sources_faites: [libelle], statut: a_faire|en_cours|trouve|negatif|bloque|manuel, note, journal?}.
    registre : {id? | source (ARK, URL de visionneuse ou manifeste) | cote, service, titre, piste, nb_vues,
      bornes: [de, a], vues_lues: [n | [de, a]], lectures: [{vue, date, date_fin, type, numero, note}], verdict, statut}.
    tache (manuelle, pour l'utilisateur) : {id?, description, service, piste, url, statut: a_faire|faite|abandonnee}
      ; piste ou tache : tache_gramps = id de la tâche de Gramps Web liée (#263, "" pour délier)
      (un défi anti-robot rencontré avec enquete=<id> en crée une d'office).
    requete (faite hors outil suivi, ex. Geneanet) : {outil, parametres, resultat: positif|negatif|erreur|manuel,
      resume, journal?, piste}.
    statut : ouverte | bloque | close. budget : limites à modifier ({requetes_par_hote, images}, 0 = illimité) ; relever un budget épuisé débloque l'enquête (avec l'accord de l'utilisateur).
    Tout élément négatif référence une entrée du journal : journal=<id> vérifié, sinon une entrée « enquete »
    est créée (journal_cree)."""
    return _enquete(lambda: app().enquetes.noter(enquete, piste, registre, tache, requete, statut, personnes,
                                                 budget))


@mcp.tool()
def enquete_etat(enquete: str = "") -> dict:
    """État complet d'une enquête (fichier JSON), avec le contrôle de cohérence avec le journal ; sans
    enquete, liste des enquêtes (id, sujet, statut, pistes ouvertes, tâches en attente)."""
    def run():
        e = app().enquetes
        if not enquete:
            return {"enquetes": e.lister()}
        return _taches_enquete({**e.lire(enquete), "coherence_journal": e.coherence(enquete) or "ok"}, enquete)
    return _enquete(run)


def _taches_enquete(out: dict, enquete: str, proposer: bool = False, elements: list[str] | None = None) -> dict:
    """#263, réglage activé seulement : correspondance pistes / tâches manuelles <-> tâches de Gramps Web (liens,
    écarts signalés, jamais corrigés ici) et, sur demande, opérations ajouter_tache prêtes. Lecture seule."""
    if not app().taches_actives():
        return out
    try:
        e, tree = app().enquetes.lire(enquete), app().tree()
        out["taches_gramps"] = taches_gramps.correspondance(e, tree)
        if proposer:
            out["taches_a_proposer"] = taches_gramps.operations_enquete(e, tree, elements)
    except Exception as exc:  # noqa: BLE001 — l'état d'enquête reste lisible si Gramps Web ne répond pas
        out["taches_gramps"] = {"erreur": f"tâches de Gramps Web illisibles : {exc}"}
    return out


@mcp.tool()
def enquete_reprendre(enquete: str = "", taches: bool = False, elements: list[str] | None = None) -> dict:
    """Reprise après interruption, sans relire le journal : actions restantes dans l'ordre (a_faire : outil et
    paramètres prêts ; d'abord les appels refusés faute de budget), pistes ouvertes, registres en cours (vues
    restantes), tâches manuelles en attente, demandes déjà faites à ne pas relancer (deja_fait), budget
    restant et blocage éventuel. Sans enquete : liste des enquêtes ouvertes ou bloquées.
    GENEALOGISTE_GRAMPS_TACHES : taches_gramps (pistes et tâches manuelles liées aux tâches de Gramps Web, écarts
    ouvert/terminé signalés) ; taches=true : taches_a_proposer, opérations ajouter_tache prêtes pour les éléments
    ouverts sans tâche (ou ceux d'elements : p1, t2…), à soumettre par arbre_proposer. Rien n'est écrit."""
    def run():
        e = app().enquetes
        if not enquete:
            return {"enquetes": [x for x in e.lister() if x["statut"] in ("ouverte", "bloque")]}
        out = e.reprendre(enquete)
        if taches and not app().taches_actives():
            out["taches_a_proposer"] = {"erreur": taches_gramps.DESACTIVE}
        return _taches_enquete(out, enquete, taches, elements)
    return _enquete(run)


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
def marqueurs_migrer_proposer() -> dict:
    """Prépare la migration des marqueurs historiques vers la nomenclature genealogiste (#182), sans rien écrire :
    balises <!-- sosa:debut/fin --> des notes Markdown -> <!-- genealogiste:debut/fin --> (seules les balises
    changent, jamais le texte libre) et, en mode gramps, attributs Sosa-* -> Genealogiste-* et étiquette
    Sosa:auto -> Genealogiste:auto (valeurs, handles et identifiants inchangés). Renvoie fichiers et objets
    concernés, diff, incohérences (même marqueur sous les deux formes avec des valeurs différentes : laissé
    intact) et un jeton pour marqueurs_migrer_appliquer, à n'utiliser qu'après accord explicite. Idempotent :
    sans rien à migrer, pas de jeton. Les deux formes restent lues sans limite de durée."""
    a = app()
    if a.config.marqueurs == "sosa":
        return {"note": "GENEALOGISTE_MARQUEURS=sosa : l'ancienne forme est conservée en écriture, migration "
                        "désactivée (les deux formes restent lues)."}
    out: dict = {}
    record: dict = {"type": "marqueurs"}
    if a.notes.enabled():
        try:
            plan = a.notes.plan_marqueurs()
        except NotesError as exc:
            return {"erreur": str(exc)}
        out["notes"] = {"repertoire": str(a.notes.dir), "fichiers": [f["fichier"] for f in plan["fichiers"]],
                        "a_regenerer": plan["a_regenerer"], "diff": plan["diff"]}
        if plan["a_regenerer"]:
            out["notes"]["a_regenerer_conseil"] = (
                "Section présente sous les deux formes avec des contenus différents : laissée en l'état ; "
                "notes_generer(id) la résout en gardant le seul contenu régénéré (texte libre conservé).")
        if plan["fichiers"]:
            record["notes"] = plan["fichiers"]
    if a.config.backend == "gramps":
        try:
            g = _gramps_guard(a.backend.propose_marqueurs)
        except ProposalError as exc:
            return {"erreur": str(exc)}
        if "erreur" in g:
            return g
        if jeton_g := g.pop("jeton", None):
            g.pop("expire_dans_minutes", None)
            record["gramps"] = jeton_g
        out["gramps"] = g
    if not out:
        return {"note": "Rien à migrer : ni notes (GENEALOGISTE_NOTES_DIR) ni Gramps Web (mode gramps)."}
    if "notes" not in record and "gramps" not in record:
        out["note"] = "Rien à migrer : marqueurs déjà dans la forme genealogiste."
        return out
    record["resume"] = [f"Migration des marqueurs : {len(record.get('notes', []))} fiche(s)"
                        + (", base Gramps Web" if "gramps" in record else "")]
    out["jeton"] = a.tokens.create(record)
    out["consigne"] = ("Présenter fichiers, objets et diff ; n'appeler marqueurs_migrer_appliquer qu'après accord "
                       "explicite de l'utilisateur.")
    return out


@mcp.tool()
def marqueurs_migrer_appliquer(jeton: str) -> dict:
    """Applique une migration de marqueurs_migrer_proposer validée par l'utilisateur : en mode gramps, une
    transaction Gramps Web (journalisée dans gramps-transactions.jsonl, annulable par arbre_annuler_modification),
    puis les fiches de notes réécrites (refus si l'une a changé depuis la proposition) et un commit dans le dépôt
    Git des notes s'il existe. Jeton à usage unique."""
    a = app()
    try:
        rec = a.tokens.take(jeton)
    except ProposalError as exc:
        return {"erreur": str(exc)}
    if rec.get("type") != "marqueurs":
        return {"erreur": "Ce jeton n'est pas une migration de marqueurs (marqueurs_migrer_proposer)."}
    out: dict = {}
    if g := rec.get("gramps"):
        try:
            res = _gramps_guard(lambda: a.backend.apply(g))
        except ProposalError as exc:
            return {"erreur": f"Gramps Web : {exc} Rien n'a été écrit dans les notes ; relancer "
                              "marqueurs_migrer_proposer."}
        if "erreur" in res:
            return res
        out["gramps"] = res
    if fichiers := rec.get("notes"):
        try:
            out["notes"] = a.notes.appliquer_marqueurs(
                fichiers, "Migration des marqueurs sosa → genealogiste (#182)\n\n"
                          f"{len(fichiers)} fiche(s) : balises <!-- sosa:debut/fin --> renommées, contenu inchangé.")
        except NotesError as exc:
            return {**out, "erreur": str(exc)}
    return out


@mcp.tool()
def cache_purger(source: str = "") -> dict:
    """Vide le cache SQLite des réponses (tout si source est vide, sinon une catégorie). Catégories : matchid,
    wikitree, gallica, wikidata, geo, cog, archives, ark, iiif, visionneuse ; echec (échecs mémorisés sans
    source) ; coupe_circuit (lève la pause des hôtes mis en pause après un défi anti-robot, durée
    GENEALOGISTE_COUPE_CIRCUIT, et l'exclusion d'un défi persistant, GENEALOGISTE_EXCLUSION_ANTIROBOT, pour
    permettre un nouvel essai explicite) ; antirobot (oublie les défis observés, exposés par archives_service
    sous defi_observe ; une purge complète les conserve) ; ralentissement (rétablit le rythme
    normal des hôtes ralentis pour la journée après 429/502/503/504 ; jamais levé par une purge complète). Les
    échecs mémorisés d'une source partent avec elle ; un nom inconnu ne supprime rien. Purge aussi les entrées expirées et applique les plafonds
    de taille : GENEALOGISTE_CACHE_MAX_MO au cache SQLite (plus anciennes entrées d'abord) et
    GENEALOGISTE_CACHE_IMAGES_MAX_MO au dossier cache-images (plus anciennes images d'abord), qui n'est jamais
    vidé par catégorie. Les médias archivés et l'arbre ne sont pas touchés.
    Renvoie supprimes (entrées de la catégorie ou de tout le cache), images_supprimees (fichiers retirés de
    cache-images par le plafond) et restant (entrées par catégorie)."""
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
        t = gramps_to_tree(db, app().taches_actives())[0]
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
                                                     app().config.gramps_notes_auto != "false",
                                                     app().config.marqueurs, app().config.gramps_notes_liens))
    except ProposalError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def gramps_bascule_appliquer(jeton: str) -> dict:
    """Exécute la bascule après accord EXPLICITE : écrit l'arbre dans Gramps Web, fige arbre.ged (dernier commit
    « Bascule vers Gramps Web ») ; journal.jsonl reste local. Ensuite : GENEALOGISTE_BACKEND=gramps."""
    from .gramps.backend import bascule_apply
    try:
        cfg = app().config
        racines = cfg.media_racines[1:] if cfg.media_dir_conf else None  # mêmes racines que l'envoi (#193)
        return _gramps_guard(lambda: bascule_apply(app().gramps(), app().store, app().tokens, jeton, racines))
    except ProposalError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def gramps_recalculer_notes() -> dict:
    """Mode gramps : prépare le recalcul des notes et étiquettes de preuve générées (Genealogiste:auto), par ex. après
    des modifications faites dans l'interface. Les notes manuelles ne sont jamais touchées. Seul moyen de faire passer
    toutes les notes à la forme voulue par GENEALOGISTE_GRAMPS_NOTES_LIENS (liens internes ajoutés ou retirés,
    bilan transaction_gramps.liens_internes). Jeton à valider."""
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
def gramps_dater_lieux(ignorer_lieux_evenements_non_dates: bool = False) -> dict:
    """Mode gramps : prépare les noms et rattachements datés des communes (#277) d'après le COG de l'INSEE (fichiers
    publics, cache de 180 jours, requête tracée au journal même négative ; aucun nom de personne envoyé). Pour chaque
    lieu commune (code INSEE ; type City, Town, Village, Municipality ou personnalisé « Commune ») : noms anciens
    datés (changement de nom, commune nouvelle) en noms alternatifs, nom principal daté de son entrée en vigueur ;
    ancien département (Seine, Seine-et-Oise, Corse… : changement de code) et commune nouvelle d'une commune
    déléguée en rattachements datés. Gramps affiche alors le nom d'époque à la date de l'événement ; noms relus
    (« Commune, Département, Pays ») et événements inchangés. Jamais d'écrasement ni de doublon ; conflits et
    communes réunies (lieux gardés distincts, aucune fusion) listés. Règle de Gramps : un événement SANS date
    (vide ou textuelle) affichera le nom le plus ancien et l'ancien département ; la proposition le compte par lieu
    (evenements_non_dates, avertissement) avant le jeton. ignorer_lieux_evenements_non_dates=true : ces lieux restent
    hors de la proposition (lieux_exclus). Jeton pour arbre_appliquer après accord explicite ; journalisée,
    annulable par arbre_annuler_modification. Rien à dater : pas de jeton."""
    if app().config.backend != "gramps":
        return {"erreur": "Disponible en mode gramps (GENEALOGISTE_BACKEND=gramps) : le modèle fichier n'a pas "
                          "d'objet lieu (titre, code INSEE, coordonnées) où dater noms et rattachements."}
    try:
        return _gramps_guard(lambda: app().backend.propose_place_history(
            lambda codes: geo.chronologies(app().sctx, codes), ignorer_lieux_evenements_non_dates))
    except ProposalError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def gramps_normaliser_types(classes: list[str] | None = None) -> dict:
    """Mode gramps : prépare la normalisation des types personnalisés qui doublonnent un type standard de Gramps
    (#273 : événement « Baptême » -> Baptism, rôle « Témoin » -> Witness, lieu « Paroisse » -> Parish…, libellés
    du catalogue français de Gramps comparés sans casse ni accents). classes : limiter à ces classes Gramps
    (EventType, EventRoleType, AttributeType, NoteType, PlaceType, NameType, NameOriginType, FamilyRelType,
    ChildRefType, RepositoryType, SourceMediaType, UrlType, SrcAttributeType). Une seule transaction : seul le type
    change (handles, identifiants, valeurs, citations, positions inchangés) ; bilan par classe et par type, libellés
    ambigus listés sans être tranchés. Jeton pour arbre_appliquer après accord explicite ; journalisée, annulable
    par arbre_annuler_modification. Sans rien à normaliser : pas de jeton."""
    if app().config.backend != "gramps":
        return {"erreur": "Disponible en mode gramps (GENEALOGISTE_BACKEND=gramps)."}
    try:
        return _gramps_guard(lambda: app().backend.propose_types(classes))
    except ProposalError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def gramps_proteger_vivants(personnes: list[str] | None = None, limite: int = 100, retraits: bool = True) -> dict:
    """Mode gramps : prépare le marquage « privé » des personnes présumées vivantes (règle du plugin, arbre_vivant) et
    de leurs données propres, pour qu'un compte Invité (rôle 0) de Gramps Web n'en voie rien (#264) : la personne ;
    les familles dont tous les conjoints sont masqués ; les événements dont tous les propriétaires (rôle Principal ou
    Famille) sont masqués ; les citations, sources, médias et notes dont tous les référents sont masqués. Un objet
    partagé avec un objet qui reste visible (famille avec un conjoint décédé, source citée ailleurs…) n'est jamais
    rendu privé : listé dans partages avec la raison ; textes restés visibles qui nomment un vivant : residus ;
    limites : non_masquable. Sans personnes (tout l'arbre) : aussi les médias dont le seul référent est un billet ou
    une tâche privés (#261, #263), et le RETRAIT du privé que Genealogiste a posé pour des personnes qui ne sont plus
    présumées vivantes (décès saisi, âge dépassé ; retraits=False pour l'omettre), d'après le journal local des
    transactions (jamais un privé posé par l'utilisateur). Une transaction ; limite : personnes par lot (relancer
    pour la suite, reste_apres_ce_lot). Seul le drapeau privé change. Jeton pour arbre_appliquer après accord
    explicite ; journalisée, annulable par arbre_annuler_modification. Rien à faire : pas de jeton (idempotent)."""
    if app().config.backend != "gramps":
        return {"erreur": "Disponible en mode gramps (GENEALOGISTE_BACKEND=gramps) : en mode fichier, les exports "
                          "publics masquent déjà les vivants (arbre_exporter)."}
    try:
        return _gramps_guard(lambda: app().backend.propose_protection(personnes, limite, retraits))
    except ProposalError as exc:
        return {"erreur": str(exc)}


PROCEDURE_GROUPES_NOMS = (
    "Genealogiste n'écrit PAS les groupes de noms : Gramps Web les pose hors de ses transactions (rien dans "
    "l'historique à défaire) et ne sait pas revenir à « aucun regroupement » (docs/gramps-web.md, « Groupes de "
    "noms »). À appliquer soi-même, après relecture : (1) Gramps Web, par patronyme : la route de a_appliquer (rôle "
    "Editor), par exemple avec curl et un jeton d'accès, ou (2) Gramps (Desktop ou Web, rôle Owner) : enregistrer "
    "xml_import dans un fichier .gramps et l'importer (il ne crée aucun objet, seulement les regroupements ; un "
    "regroupement déjà présent n'est jamais écrasé : Gramps avertit). Un groupe de noms ne fusionne aucune "
    "personne : il ne change que le classement dans les vues, index et rapports de Gramps.")


@mcp.tool()
def gramps_grouper_noms(patronymes: list[str] | None = None, candidats: bool = True) -> dict:
    """Mode gramps : propose des groupes de noms (name groups de Gramps, #276) d'après les patronymes réellement
    attestés dans l'arbre, LECTURE SEULE (aucun jeton, rien n'est écrit : Gramps Web ne sait ni inscrire un groupe
    de noms dans son historique ni revenir à « aucun regroupement », donc l'écriture ne peut pas respecter
    proposition, accord, annulation). Un groupe de noms n'est PAS une fusion de personnes : il ne change que le
    classement par nom (vues, index, rapports de Gramps) ; personnes, noms et événements restent intacts.
    Critère prudent, seulement des écritures qui ne diffèrent que par la casse, les accents, espaces, tirets et
    apostrophes (LE GRAND, Legrand ; Lefèvre, Lefevre) ou par la transcription d'un tréma (Müller, Mueller, Muller) ;
    jamais de rapprochement phonétique, de diphtongue, de finale ou de latin : ces patronymes proches sont listés en
    candidats_non_retenus pour examen humain (candidats=False les omet). Résultat : groupes_proposes (groupe,
    patronymes, personnes, motif), deja_en_place (idempotent : relancé après application, rien à appliquer),
    conflits avec les regroupements existants (jamais tranchés, rien n'est proposé pour eux), a_appliquer (route
    Gramps Web de chaque regroupement), xml_import (import Gramps Desktop ou Web) et la procédure. patronymes :
    limiter aux familles d'écritures qui contiennent l'un de ces patronymes."""
    if app().config.backend != "gramps":
        return {"erreur": "Disponible en mode gramps (GENEALOGISTE_BACKEND=gramps) : les groupes de noms sont une "
                          "table de la base Gramps ; le modèle fichier n'en a pas et n'en invente pas."}
    try:
        r = _gramps_guard(lambda: app().backend.bilan_groupes_noms(patronymes, candidats))
    except ProposalError as exc:
        return {"erreur": str(exc)}
    if "erreur" in r:
        return r
    r["nature"] = "lecture : aucun jeton, rien n'est écrit dans Gramps Web"
    if r["a_appliquer"]:
        r["xml_import"] = gn.regroupements_xml([(x["patronyme"], x["groupe"]) for x in r["a_appliquer"]])
    r["procedure"] = PROCEDURE_GROUPES_NOMS
    return r


def _signets_enquete(eid: str, action: str) -> dict:
    """Proposition de signets pour les personnes d'une enquête (``poser``) ou de retrait de ceux que le plugin a posés
    (``retirer``), #282. Mode gramps seulement ; jamais appliquée ici."""
    a = app()
    if a.config.backend != "gramps":
        return {"erreur": "Signets : disponibles en mode gramps (GENEALOGISTE_BACKEND=gramps), ce sont ceux de la "
                          "base Gramps."}
    try:
        e = a.enquetes.lire(eid)
        b = a.backend
        ops, notes = b.operations_enquete(b.snapshot(fresh=True), e.get("personnes", []), action,
                                          a.enquetes.signets_poses(eid))
        return _gramps_guard(lambda: b.propose_signets(operations=ops, enquete=eid, notes=notes))
    except ProposalError as exc:
        return {"erreur": str(exc)}


@mcp.tool()
def gramps_reglages(chercheur: dict | None = None, signets: dict | None = None) -> dict:
    """Mode gramps : réglages de la base Gramps (#282), partagés entre Gramps Desktop et Gramps Web. Sans paramètre :
    LECTURE seule : fiche du chercheur (renseignée ou vide et noms des champs renseignés, jamais les valeurs), signets
    de chaque type d'objet (identifiants Gramps), formats de nom personnalisés (numéro, nom, format, actif) et droits
    du compte. Le format de nom PAR DÉFAUT de l'arbre n'est pas dans la base (préférence de Gramps Desktop ou du
    serveur, illisible par l'API) : fiches et récits gardent leur affichage.
    chercheur={name, addr, street, locality, city, county, state, country, postal, phone, email} (valeurs fournies
    par l'utilisateur, chaîne vide pour vider un champ) : PROPOSITION (jeton + diff avant/après), rôle Owner requis.
    signets={ajouter: [{cible, id}], retirer: [{cible, id}]} (cible : person, family, event, place, source,
    citation, repository, media, note ; id : identifiant Gramps) ou {enquete, action: poser|retirer} (personnes d'une
    enquête ; retrait limité aux signets que le plugin a posés) : PROPOSITION (jeton + diff), rôle Editor. Ce sont les
    signets de la BASE (menu Signets de Gramps Desktop) : l'interface de Gramps Web a les siens dans le navigateur et
    n'affiche pas ceux-ci.
    Ces écritures sont HORS transaction Gramps (rien dans l'historique de Gramps Web) : proposition, accord explicite
    (arbre_appliquer), journal, annulation par Genealogiste (arbre_annuler_modification : état antérieur mémorisé,
    restauré, conflit refusé). Un retrait annulé remet le signet en fin de liste. docs/gramps-web.md."""
    if app().config.backend != "gramps":
        return {"erreur": "Disponible en mode gramps (GENEALOGISTE_BACKEND=gramps) : ces réglages sont ceux de la "
                          "base Gramps ; le modèle fichier n'en a pas et n'en invente pas."}
    if chercheur is not None and signets is not None:
        return {"erreur": "Une proposition à la fois : chercheur ou signets."}
    try:
        if chercheur is not None:
            return _gramps_guard(lambda: app().backend.propose_chercheur(chercheur))
        if signets is not None:
            if not isinstance(signets, dict):
                return {"erreur": "signets : dictionnaire attendu ({ajouter, retirer} ou {enquete, action})."}
            if "enquete" in signets or "action" in signets:
                if set(signets) - {"enquete", "action"} or signets.get("action") not in ("poser", "retirer") \
                        or not isinstance(signets.get("enquete"), str):
                    return {"erreur": "signets d'enquête : {\"enquete\": id, \"action\": \"poser\" | \"retirer\"}."}
                return _enquete(lambda: _signets_enquete(signets["enquete"], signets["action"]))
            if set(signets) - {"ajouter", "retirer"}:
                return {"erreur": "signets : clés ajouter et retirer seulement (ou enquete et action)."}
            return _gramps_guard(lambda: app().backend.propose_signets(signets.get("ajouter"), signets.get("retirer")))
        return _gramps_guard(lambda: {**app().backend.lire_reglages(), "nature": "lecture : rien n'est écrit"})
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
    (attribut Genealogiste-Fichier, ou Sosa-Fichier historique, en mode gramps ; FILE en mode fichier) dont le chemin commence par ancien_prefixe, en
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
    avec le miroir Git, les commite (« Modifications externes »). GENEALOGISTE_GRAMPS_TACHES : taches_ecarts, écarts
    ouvert/terminé entre les enquêtes non closes et leurs tâches de Gramps Web (signalés, jamais corrigés)."""
    if app().config.backend != "gramps":
        return {"erreur": "Disponible en mode gramps (GENEALOGISTE_BACKEND=gramps)."}

    def run():
        b = app().backend
        b.snapshot(fresh=True)
        out = {"modifications": b.last_refresh, "objets": b.db.count(), "miroir_git": bool(b.mirror)}
        if app().taches_actives():  # #263 : écarts entre enquêtes ouvertes et tâches de Gramps Web, signalés
            tree, ecarts = b.load(), []
            for x in app().enquetes.lister():
                if x.get("statut") != "close":
                    ecarts += taches_gramps.correspondance(app().enquetes.lire(x["id"]), tree)["ecarts"]
            out["taches_ecarts"] = ecarts
        return out
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
        # Contact du User-Agent (#211, lot D) : état seulement, jamais la valeur.
        etat_contact = {"configure": "configuré", "absent": "absent"}.get(
            a.config.etat_contact, f"IGNORÉ — {a.config.contact_motif}")
        print("Contact User-Agent (GENEALOGISTE_CONTACT) :", etat_contact)
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
