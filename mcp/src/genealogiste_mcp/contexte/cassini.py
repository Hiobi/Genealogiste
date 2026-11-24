"""Base Cassini installée par l'utilisateur, lue en local (#349, suite de #322 et #287).

Le jeu « lieux_cassini_devenus_communes.csv » (base Cassini de l'EHESS, redéposée sur Nakala par G. Bideau et
N. Verdier, ``doi:10.34847/nkl.e0556oog``) est sous **CC BY-NC-SA 4.0** : il n'entre jamais dans le dépôt du plugin
(GPL-3.0), ni en fixture, ni en extrait. Chaque utilisateur l'installe lui-même, par un geste explicite et tracé :

1. ``preparer`` (aucun téléchargement du jeu) lit les métadonnées du dépôt Nakala et rend source, auteurs, licence,
   réserve, taille, empreinte publiée et destination ; le serveur y joint un jeton à usage unique ;
2. ``installer`` (classe écriture) relit les métadonnées, télécharge le fichier par le client HTTP commun, vérifie
   taille, empreinte publiée et en-tête, puis l'écrit de façon atomique avec un fichier d'acceptation ;
3. ``consulter`` ne lit le fichier que s'il est présent **et** accepté **et** d'empreinte conforme, hors de tout
   dépôt Git ; sinon ``None`` : ``lieu_historique`` garde son comportement (« inconnu » + lien) ;
4. ``desinstaller`` retire le fichier, l'acceptation et les restes d'un téléchargement interrompu.

Emplacement : ``<référentiels>/cassini/`` (``Config.referentiels_dir``, défaut
``$XDG_DATA_HOME/genealogiste-referentiels``). ``refus_emplacement`` refuse tout dossier situé dans le répertoire de
données (dépôt Git de l'arbre), dans un dossier de l'utilisateur géré par le plugin (médias, notes, rapports,
exports), dans le plugin, ou sous un dépôt Git quel qu'il soit : le fichier ne peut pas être commité.

Lecture : pas d'index sur disque. Au premier appel du processus, une seule passe lit le fichier (25 Mo), contrôle
son empreinte (contrôle qui impose de toute façon une lecture complète) et garde en mémoire, par code INSEE, la
position des lignes ; chaque consultation relit ensuite quelques lignes par ``seek``. Rien de dérivé n'est écrit à
côté du fichier (aucune seconde copie de données NC-SA à tenir à jour ou à désinstaller) ; le fichier modifié ou
remplacé (taille, date) est relu et recontrôlé.

Jointure : code INSEE (colonne ``commune_mars_2021``, géographie de mars 2021). Les valeurs tirées du fichier portent
licence, attribution et référence ``doi:`` (registre des références consultées) ; elles orientent une recherche et ne
concluent rien : statut « indication », jamais d'écriture dans l'arbre.
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import os
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as Date
from pathlib import Path

from ..fichiers import ecrire_atomique
from ..sources.base import SourceContext, error_envelope
from . import services
from .modeles import Reference, ReferenceInvalide
from .registre import NonConsultee, RegistreReferences

SERVICE = "NAKALA"
API = "https://api.nakala.fr"  # même hôte que le point d'accès NAKALA du référentiel (politique d'accès commune)
DOI = "10.34847/nkl.e0556oog"
REFERENCE = f"doi:{DOI}"
FICHIER = "lieux_cassini_devenus_communes.csv"
ACCEPTATION = "acceptation.json"
SOUS_DOSSIER = "cassini"
LICENCE = "CC-BY-NC-SA-4.0"  # valeur de la métadonnée « license » du dépôt Nakala
LICENCE_NOM = "CC BY-NC-SA 4.0"
TAILLE_MAX = 100 * 1024 * 1024  # garde-fou : le fichier publié fait 25 Mo
VARIABLE = "GENEALOGISTE_REFERENTIELS_DIR"

# Liens de consultation, à ouvrir par l'utilisateur : jamais interrogés par le plugin.
LIENS = {"doi": f"https://doi.org/{DOI}",
         "licence": "https://creativecommons.org/licenses/by-nc-sa/4.0/deed.fr",
         "fiche_cassini": "http://cassini.ehess.fr/cassini/fr/html/fiche.php?select_resultat={}"}

ATTRIBUTION = ("Base Cassini (LaDéHis, EHESS), redéposée par G. Bideau et N. Verdier, Nakala, "
               f"doi:{DOI}, {LICENCE_NOM}")
CONDITIONS = ("Pas d'usage commercial : les données ne servent ni à une prestation payante ni à un produit vendu.",
              "Attribution obligatoire : citer la source, ses auteurs et la licence à chaque reprise.",
              "Partage dans les mêmes conditions : toute copie, même modifiée ou extraite, reste sous la même "
              "licence (CC BY-NC-SA 4.0).")
RESERVE = ("Licence d'origine non vérifiée : le dépôt Nakala est une redéposition par des tiers d'un fichier "
           "téléchargé auprès de l'EHESS, dont les conditions d'usage propres n'ont pas pu être lues (site "
           "injoignable aux relevés, docs/etudes/lieux-1790-1943.md). La licence affichée est celle du dépôt Nakala.")
AVERTISSEMENT = ("Indication tirée de la base Cassini installée localement : elle oriente la recherche, ne conclut "
                 "rien et ne remplace pas une source primaire (registre, recensement, acte). À confirmer avant "
                 "toute conclusion ; rien n'est écrit dans l'arbre.")
INDICATION = "indication"
INCONNU = "inconnu"

# Colonnes lues (noms relevés sur le fichier publié, en NFC). Les six premières lignes de REQUISES suffisent à la
# jointure et aux noms ; les colonnes de chef-lieu et de population sont lues si elles existent.
REQUISES = ("noacass", "nom_cassini", "nom_an3", "nom_1801", "nom_1999", "commune_mars_2021",
            "est_chef_lieu_communal_1999", "district_an_3", "departement_an_3", "departement_1999",
            "subdelegations", "intendances", "intendances_types")
CHEFS_LIEUX = {"est_chef_lieu_evêché_1789": "évêché (1789)",
               "est_chef_lieu_baillage_1789": "bailliage (1789)",
               "est_chef_lieu_recette_des_finance_1789": "recette des finances (1789)",
               "est_chef_lieu_subdelegation_1789": "subdélégation (1789)",
               "est_chef_lieu_district_1790": "district (1790)",
               "est_chef_lieu_departement_1790": "département (1790)"}
POPULATION = re.compile(r"pop_(an\d+|\d{4})_val")
# Recensements datés en années républicaines : bornes grégoriennes de l'année (calendrier, pas une donnée du jeu).
REPUBLICAINS = {"an3": ("an III", 1794, 1795), "an8": ("an VIII", 1799, 1800)}
LIEUX_MAX = 30  # lieux rendus par commune (le nombre total est toujours donné)

_VERROU = threading.Lock()
_BASES: dict[str, tuple[tuple, Base | None, str]] = {}  # dossier -> (signature, base, motif)


class CassiniRefuse(ValueError):
    """Installation ou lecture refusée : rien n'est téléchargé, écrit ni lu."""


# ---------------------------------------------------------------------------- emplacement

def dossier(config) -> Path:
    return Path(config.referentiels_dir).expanduser() / SOUS_DOSSIER


def _racine_plugin() -> Path:
    """Racine du plugin (dossier qui porte plugin.json ou .claude-plugin), à défaut le paquet Python."""
    ici = Path(__file__).resolve()
    for p in ici.parents:
        if (p / ".claude-plugin").exists() or (p / "plugin.json").is_file():
            return p
    return ici.parents[1]


def refus_emplacement(config) -> str | None:
    """Motif du refus si le dossier d'installation pourrait être commité ou redistribué ; None s'il est admis.
    Liens symboliques résolus avant contrôle."""
    cible = dossier(config).resolve()
    remede = f" Choisir un autre dossier avec {VARIABLE} (<données>/.env)."
    donnees = Path(config.data_dir).expanduser().resolve()
    if cible == donnees or cible.is_relative_to(donnees):
        return (f"dossier d'installation {cible} situé dans le répertoire de données ({donnees}), qui est le dépôt "
                "Git de l'arbre : le fichier pourrait y être commité." + remede)
    geres = {"médias": config.media_dir, "pièces": config.pieces_root, "notes": config.notes_dir,
             "rapports": config.rapports_dir, "exports": config.exports_dir}
    for nom, racine in geres.items():
        if racine is None:
            continue
        r = Path(racine).expanduser().resolve()
        if cible == r or cible.is_relative_to(r):
            return (f"dossier d'installation {cible} situé dans le dossier de l'utilisateur géré par le plugin "
                    f"({nom} : {r}), qui peut être synchronisé, partagé ou versionné." + remede)
    plugin = _racine_plugin()
    if cible == plugin or cible.is_relative_to(plugin):
        return f"dossier d'installation {cible} situé dans le plugin ({plugin}) : rien n'y est installé." + remede
    for p in (cible, *cible.parents):
        if (p / ".git").exists():
            return (f"dossier d'installation {cible} situé dans un dépôt Git ({p}) : le fichier pourrait y être "
                    "commité." + remede)
    return None


def destination(config) -> dict:
    d = dossier(config)
    return {"dossier": str(d), "fichier": str(d / FICHIER), "acceptation": str(d / ACCEPTATION),
            "variable": VARIABLE,
            "note": "Hors du plugin, hors du répertoire de données (dépôt Git de l'arbre) et hors de tout dépôt Git ; "
                    "jamais versionné, jamais inclus dans une sauvegarde de l'arbre."}


# ---------------------------------------------------------------------------- dépôt Nakala (métadonnées)

def _url_depot() -> str:
    return f"{API}/datas/{DOI}"


def _depot(ctx: SourceContext) -> tuple[dict, dict]:
    """Métadonnées du dépôt, relues à chaque appel (jamais du cache) : (dépôt analysé, réponse brute)."""
    url = _url_depot()
    if not services.url_autorisee(SERVICE, url):
        raise CassiniRefuse("point d'accès Nakala hors du référentiel des services de contexte")
    brut, _ = ctx.http.get(url, use_cache=False, ttl=0, source="nakala")
    return analyser_depot(brut), brut


def analyser_depot(brut) -> dict:
    """Ce que le dépôt publie pour le fichier : licence, version, taille, empreinte. Lève CassiniRefuse si la
    réponse ne décrit pas exactement ce que le plugin sait présenter (autre licence, fichier absent…)."""
    if not isinstance(brut, dict):
        raise CassiniRefuse("réponse inattendue de Nakala (objet JSON attendu)")
    if str(brut.get("identifier") or "").lower() != DOI:
        raise CassiniRefuse(f"le dépôt renvoyé par Nakala n'est pas doi:{DOI}")
    if brut.get("status") != "published":
        raise CassiniRefuse(f"dépôt Nakala non publié (statut {brut.get('status')!r})")
    metas = [m for m in brut.get("metas") or [] if isinstance(m, dict)]

    def valeurs(suffixe: str) -> list:
        return [m.get("value") for m in metas if str(m.get("propertyUri") or "").endswith(suffixe)]

    licences = [v for v in valeurs("#license") if isinstance(v, str)]
    if licences != [LICENCE]:
        raise CassiniRefuse(f"licence publiée par Nakala ({', '.join(licences) or 'absente'}) différente de celle "
                            f"que le plugin sait présenter ({LICENCE}) : installation refusée, à réexaminer")
    fichiers = [f for f in brut.get("files") or [] if isinstance(f, dict) and f.get("name") == FICHIER]
    if len(fichiers) != 1:
        raise CassiniRefuse(f"le dépôt Nakala ne publie pas un fichier unique nommé {FICHIER}")
    f = fichiers[0]
    sha1 = str(f.get("sha1") or "").lower()
    try:
        taille = int(f.get("size"))
    except (TypeError, ValueError):
        taille = 0
    if not re.fullmatch(r"[0-9a-f]{40}", sha1) or not 0 < taille <= TAILLE_MAX:
        raise CassiniRefuse("empreinte ou taille du fichier absente ou invraisemblable dans les métadonnées Nakala")
    auteurs = []
    for v in valeurs("#creator"):
        if isinstance(v, dict):
            nom = v.get("fullName") or " ".join(x for x in (v.get("givenname"), v.get("surname")) if x)
            if nom:
                auteurs.append(str(nom))
    deposant = (brut.get("depositor") or {}).get("name") if isinstance(brut.get("depositor"), dict) else ""
    titres = [v for v in valeurs("#title") if isinstance(v, str)]
    return {"titre": titres[0] if titres else "", "auteurs": auteurs, "deposant": deposant or "",
            "licence": LICENCE, "version": {"numero": brut.get("version"), "depose_le": brut.get("creDate") or "",
                                            "modifie_le": brut.get("modDate") or ""},
            "fichier": {"nom": FICHIER, "taille_octets": taille, "empreinte": {"algorithme": "sha1", "valeur": sha1},
                        "url": f"{API}/data/{DOI}/{sha1}"}}


def _lisible(octets: int) -> str:
    return f"{octets / 1_000_000:.1f} Mo".replace(".", ",")


# ---------------------------------------------------------------------------- préparer

def preparer(ctx: SourceContext) -> dict:
    """Présentation à valider par l'utilisateur ; aucun téléchargement du jeu, rien d'écrit. Le serveur ajoute le
    jeton. Clé ``enregistrement`` : ce que le jeton fige (empreinte, taille, URL, destination)."""
    config = ctx.config
    if motif := refus_emplacement(config):
        return {"erreur": motif, "destination": destination(config), "requetes_emises": 0}
    if refus := services.refus(SERVICE, config):
        return refus
    params = {"doi": DOI, "operation": "metadonnees"}
    try:
        depot, _ = _depot(ctx)
    except CassiniRefuse as exc:
        jid = ctx.journal.add("nakala", "cassini_preparer", params, "erreur", resume=str(exc),
                              references=[LIENS["doi"]])
        return {"erreur": str(exc), "journal": jid, "consultation": LIENS["doi"]}
    except Exception as exc:  # noqa: BLE001 - panne distante : enveloppe journalisée
        return error_envelope(ctx, "nakala", "cassini_preparer", params, exc)
    f = depot["fichier"]
    jid = ctx.journal.add("nakala", "cassini_preparer", params, "positif", nb_resultats=1,
                          resume=f"{FICHIER} : {f['taille_octets']} octets, sha1 {f['empreinte']['valeur']}",
                          references=[LIENS["doi"]])
    return {
        "source": {"nom": "Base Cassini (EHESS) : « Des villages de Cassini aux communes d'aujourd'hui »",
                   "depot": "Nakala (Huma-Num)", "titre_du_depot": depot["titre"], "auteurs": depot["auteurs"],
                   "deposant": depot["deposant"], "doi": DOI, "lien": LIENS["doi"], "version": depot["version"],
                   "contenu": "noms de l'an III, de 1801 et de 1999, populations de l'an III à 1999, district et "
                              "département de l'an III, intendance et subdélégation, par lieu de la carte de "
                              "Cassini devenu commune"},
        "licence": {"code": LICENCE, "nom": LICENCE_NOM, "lien": LIENS["licence"], "conditions": list(CONDITIONS),
                    "lue_dans": "métadonnée « license » du dépôt Nakala, relue à l'instant"},
        "reserve": RESERVE,
        "attribution": ATTRIBUTION,
        "fichier": {**f, "taille": _lisible(f["taille_octets"])},
        "destination": destination(config),
        "etat": etat(config),
        "usage": "Après installation, lieu_historique complète certains niveaux « inconnu » (noms, district et "
                 "département de l'an III, intendance, population avant 1968) par des indications marquées de la "
                 "licence et de l'attribution. Le fichier n'est jamais redistribué par le plugin ; "
                 "cassini_desinstaller le retire.",
        "enregistrement": {"type": "cassini", "doi": DOI, "licence": LICENCE, "version": depot["version"],
                           "fichier": f, "dossier": str(dossier(config).resolve())},
        "journal": jid,
        "consigne": "Présenter à l'utilisateur la source, la licence et ses trois conditions, la réserve, la taille "
                    "et la destination. N'appeler cassini_installer(jeton) qu'après son accord explicite : cet "
                    "appel vaut acceptation de la licence par l'utilisateur et l'enregistre.",
    }


# ---------------------------------------------------------------------------- installer

def _entete(donnees: bytes) -> list[str]:
    fin = donnees.find(b"\n")
    ligne = donnees[:fin if fin >= 0 else len(donnees)].decode("utf-8")
    return [unicodedata.normalize("NFC", c) for c in next(csv.reader([ligne.rstrip("\r")]))]


def _colonnes_manquantes(entete: list[str]) -> list[str]:
    return [c for c in REQUISES if c not in entete]


def installer(ctx: SourceContext, record: dict, registre: RegistreReferences | None = None) -> dict:
    """Télécharge, vérifie et installe le fichier décrit par ``record`` (enregistrement du jeton, déjà consommé).
    Rien n'est écrit tant que taille, empreinte publiée et en-tête ne sont pas conformes ; l'écriture est atomique
    (temporaire du même dossier puis renommage), l'acceptation est écrite après le fichier."""
    config = ctx.config
    if record.get("type") != "cassini":
        return {"erreur": "Ce jeton n'est pas une préparation d'installation de la base Cassini."}
    if motif := refus_emplacement(config):
        return {"erreur": motif, "destination": destination(config), "requetes_emises": 0}
    cible = dossier(config)
    if record.get("dossier") != str(cible.resolve()):
        return {"erreur": "La destination a changé depuis la préparation : relancer cassini_preparer.",
                "destination": destination(config), "requetes_emises": 0}
    if refus := services.refus(SERVICE, config):
        return refus
    attendu = record["fichier"]
    sha1, taille = attendu["empreinte"]["valeur"], attendu["taille_octets"]
    params = {"doi": DOI, "fichier": FICHIER, "sha1": sha1}
    try:
        depot, brut = _depot(ctx)
        f = depot["fichier"]
        if (f["empreinte"]["valeur"], f["taille_octets"]) != (sha1, taille):
            raise CassiniRefuse("le fichier publié par Nakala a changé depuis la préparation (empreinte ou taille) : "
                                "relancer cassini_preparer et présenter de nouveau la licence")
        if not services.url_autorisee(SERVICE, f["url"]):
            raise CassiniRefuse("URL de téléchargement hors du référentiel des services de contexte")
        corps, _ = ctx.http.get(f["url"], use_cache=False, ttl=0, source="nakala", parse="bytes")
        donnees = corps.encode("latin-1")
        del corps
        if len(donnees) != taille:
            raise CassiniRefuse(f"taille reçue ({len(donnees)} octets) différente de la taille publiée ({taille}) : "
                                "rien n'est installé")
        if hashlib.sha1(donnees, usedforsecurity=False).hexdigest() != sha1:  # empreinte publiée par Nakala
            raise CassiniRefuse("empreinte SHA-1 du fichier reçu différente de l'empreinte publiée par Nakala : "
                                "rien n'est installé")
        try:
            entete = _entete(donnees)
        except (UnicodeDecodeError, StopIteration, csv.Error) as exc:
            raise CassiniRefuse(f"fichier reçu illisible (CSV UTF-8 attendu) : {exc}") from None
        if manquantes := _colonnes_manquantes(entete):
            raise CassiniRefuse("en-tête du fichier non reconnu (colonnes absentes : " + ", ".join(manquantes)
                                + ") : version du jeu non prise en charge, rien n'est installé")
        acceptation = {
            "accepte_le": datetime.now(UTC).isoformat(timespec="seconds"),
            "geste": "cassini_installer appelé avec le jeton de cassini_preparer, après accord de l'utilisateur",
            "licence": LICENCE, "licence_lien": LIENS["licence"], "conditions": list(CONDITIONS),
            "reserve": RESERVE, "doi": DOI, "version": depot["version"], "attribution": ATTRIBUTION,
            "fichier": FICHIER, "taille_octets": taille, "source_url": f["url"],
            "empreinte": {"sha1": sha1, "sha256": hashlib.sha256(donnees).hexdigest()},
            "colonnes": len(entete),
        }
        with _VERROU:
            cible.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                os.chmod(cible, 0o700)
            # Entre les deux écritures, un fichier nouveau sous une acceptation ancienne a une empreinte non
            # conforme : il n'est pas lu. Si l'acceptation ne peut pas être écrite, rien ne reste installé.
            ecrire_atomique(cible / FICHIER, donnees)
            try:
                ecrire_atomique(cible / ACCEPTATION, json.dumps(acceptation, ensure_ascii=False, indent=2) + "\n")
            except OSError:
                for nom in (ACCEPTATION, FICHIER):
                    with contextlib.suppress(OSError):
                        (cible / nom).unlink(missing_ok=True)
                raise
            finally:
                _BASES.pop(str(cible), None)
    except CassiniRefuse as exc:
        jid = ctx.journal.add("nakala", "cassini_installer", params, "erreur", resume=str(exc),
                              references=[LIENS["doi"]])
        return {"erreur": str(exc), "installe": False, "journal": jid}
    except OSError as exc:
        jid = ctx.journal.add("nakala", "cassini_installer", params, "erreur", resume=f"écriture impossible : {exc}")
        return {"erreur": f"écriture impossible dans {cible} : {exc}", "installe": False, "journal": jid}
    except Exception as exc:  # noqa: BLE001 - panne distante : enveloppe journalisée, rien d'écrit
        return {**error_envelope(ctx, "nakala", "cassini_installer", params, exc), "installe": False}
    au_registre = _inscrire(registre, depot, brut)
    jid = ctx.journal.add("nakala", "cassini_installer", params, "positif", nb_resultats=1,
                          resume=f"{FICHIER} installé ({taille} octets), licence {LICENCE} acceptée",
                          references=[LIENS["doi"]])
    return {"installe": True, "destination": destination(config), "acceptation": acceptation,
            "licence": {"code": LICENCE, "nom": LICENCE_NOM, "lien": LIENS["licence"],
                        "conditions": list(CONDITIONS)},
            "reserve": RESERVE, "attribution": ATTRIBUTION, "reference": REFERENCE, "au_registre": au_registre,
            "journal": jid,
            "suite": "lieu_historique lit désormais ce fichier (indications marquées de la licence et de "
                     "l'attribution). cassini_desinstaller le retire."}


def _inscrire(registre: RegistreReferences | None, depot: dict, brut) -> bool:
    """Inscrit le dépôt au registre des références consultées (réponse 2xx des métadonnées, contenant le DOI)."""
    if registre is None:
        return False
    try:
        annee = int(str(depot["version"].get("depose_le") or "")[:4])
    except ValueError:
        annee = None
    try:
        ref = Reference(identifiant={"type": "doi", "valeur": DOI}, nature="secondaire_savante",
                        titre=depot["titre"] or FICHIER, auteurs=list(depot["auteurs"]), publication="Nakala",
                        annee=annee, acces="libre", lu="oui", service=SERVICE, requete=_url_depot(),
                        consulte_le=Date.today().isoformat())
        registre.enregistrer(ref, statut=200, reponse=brut)
    except (ReferenceInvalide, NonConsultee, OSError):
        return False
    return True


# ---------------------------------------------------------------------------- désinstaller

def desinstaller(ctx: SourceContext) -> dict:
    """Supprime le fichier, l'acceptation et les temporaires d'un téléchargement interrompu ; rien d'autre."""
    config = ctx.config
    cible = dossier(config)
    supprimes = []
    with _VERROU:
        _BASES.pop(str(cible), None)
        if cible.is_dir() and not cible.is_symlink():
            noms = [ACCEPTATION, FICHIER] + sorted(p.name for p in cible.iterdir() if p.name.endswith(".tmp") and (
                p.name.startswith(f".{FICHIER}.") or p.name.startswith(f".{ACCEPTATION}.")))
            for nom in noms:  # l'acceptation d'abord : jamais de fichier accepté à moitié retiré
                p = cible / nom
                if p.is_file() or p.is_symlink():
                    p.unlink()
                    supprimes.append(str(p))
            with contextlib.suppress(OSError):
                cible.rmdir()  # seulement s'il est vide : un fichier étranger n'est jamais supprimé
    jid = ctx.journal.add("cassini_local", "cassini_desinstaller", {"dossier": str(cible)},
                          "positif" if supprimes else "negatif", nb_resultats=len(supprimes),
                          resume=f"{len(supprimes)} fichier(s) supprimé(s)")
    return {"desinstalle": bool(supprimes), "supprimes": supprimes, "dossier": str(cible), "journal": jid,
            "note": ("lieu_historique revient à son comportement sans base locale (« inconnu » + lien). La référence "
                     f"{REFERENCE} reste au registre des références consultées (la notice a bien été consultée).")
            if supprimes else "Rien à supprimer : la base Cassini n'est pas installée dans ce dossier."}


# ---------------------------------------------------------------------------- lecture locale

@dataclass
class Base:
    """Fichier installé, accepté et d'empreinte conforme : en-tête et position des lignes par code INSEE."""

    chemin: Path
    entete: list[str]
    index: dict[str, list[tuple[int, int]]]
    acceptation: dict
    lignes: int

    def lieux(self, code: str) -> list[dict]:
        positions = self.index.get((code or "").upper(), [])
        out = []
        if not positions:
            return out
        with self.chemin.open("rb") as fh:
            for debut, longueur in positions:
                fh.seek(debut)
                texte = fh.read(longueur).decode("utf-8")
                ligne = next(csv.reader(io.StringIO(texte, newline="")), None)
                if ligne is None or len(ligne) != len(self.entete):
                    continue
                d = dict(zip(self.entete, ligne, strict=True))
                if d["commune_mars_2021"].strip().upper() == code.upper():
                    out.append(d)
        return out


class _Lignes:
    """Lignes physiques du fichier, avec la position de lecture en octets (un champ entre guillemets peut contenir
    un saut de ligne : csv.reader consomme alors plusieurs lignes pour un enregistrement)."""

    def __init__(self, donnees: bytes):
        self.donnees, self.pos = donnees, 0

    def __iter__(self):
        return self

    def __next__(self) -> str:
        if self.pos >= len(self.donnees):
            raise StopIteration
        fin = self.donnees.find(b"\n", self.pos)
        fin = len(self.donnees) if fin < 0 else fin + 1
        ligne = self.donnees[self.pos:fin]
        self.pos = fin
        return ligne.decode("utf-8")


def _lire_acceptation(chemin: Path) -> dict:
    try:
        a = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CassiniRefuse(f"fichier d'acceptation illisible ({exc})") from None
    sha1 = ((a.get("empreinte") or {}).get("sha1") if isinstance(a, dict) else None) or ""
    if (not isinstance(a, dict) or a.get("licence") != LICENCE or str(a.get("doi") or "").lower() != DOI
            or not a.get("accepte_le") or not re.fullmatch(r"[0-9a-f]{40}", str(sha1))):
        raise CassiniRefuse("fichier d'acceptation incomplet (licence, DOI, date ou empreinte) : licence non acceptée")
    return a


def _charger(cible: Path) -> Base:
    acceptation = _lire_acceptation(cible / ACCEPTATION)
    donnees = (cible / FICHIER).read_bytes()
    if hashlib.sha1(donnees, usedforsecurity=False).hexdigest() != acceptation["empreinte"]["sha1"]:
        raise CassiniRefuse("empreinte du fichier différente de celle de l'acceptation : fichier modifié ou "
                            "remplacé, non lu (cassini_desinstaller puis cassini_preparer pour le réinstaller)")
    lignes = _Lignes(donnees)
    lecteur = csv.reader(lignes)
    try:
        entete = [unicodedata.normalize("NFC", c) for c in next(lecteur)]
    except (StopIteration, UnicodeDecodeError, csv.Error):
        raise CassiniRefuse("fichier vide ou illisible") from None
    if manquantes := _colonnes_manquantes(entete):
        raise CassiniRefuse("en-tête non reconnu (colonnes absentes : " + ", ".join(manquantes) + ")")
    colonne = entete.index("commune_mars_2021")
    index: dict[str, list[tuple[int, int]]] = {}
    n = 0
    try:
        while True:
            debut = lignes.pos
            try:
                ligne = next(lecteur)
            except StopIteration:
                break
            n += 1
            if len(ligne) != len(entete):
                continue
            code = ligne[colonne].strip().upper()
            if code:
                index.setdefault(code, []).append((debut, lignes.pos - debut))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise CassiniRefuse(f"fichier illisible à la ligne {n + 2} : {exc}") from None
    return Base(cible / FICHIER, entete, index, acceptation, n)


def _signature(cible: Path) -> tuple:
    a, b = (cible / FICHIER).stat(), (cible / ACCEPTATION).stat()
    return (a.st_size, a.st_mtime_ns, b.st_size, b.st_mtime_ns)


def _base(config) -> tuple[Base | None, str]:
    """(base utilisable, motif sinon). Le contrôle d'empreinte est fait une fois par état du fichier (taille,
    dates) et par processus ; un refus est mémorisé de la même façon."""
    if motif := refus_emplacement(config):
        return None, motif
    cible = dossier(config)
    with _VERROU:
        try:
            signature = _signature(cible)
        except OSError:
            _BASES.pop(str(cible), None)
            present = (cible / FICHIER).is_file()
            return None, ("fichier présent sans acceptation : licence non acceptée, fichier non lu" if present
                          else "base Cassini non installée")
        connu = _BASES.get(str(cible))
        if connu and connu[0] == signature:
            return connu[1], connu[2]
        try:
            base, motif = _charger(cible), ""
        except CassiniRefuse as exc:
            base, motif = None, str(exc)
        except OSError as exc:
            base, motif = None, f"fichier illisible : {exc}"
        _BASES[str(cible)] = (signature, base, motif)
        return base, motif


def etat(config) -> dict:
    """État de l'installation, sans réseau : installée (présente, acceptée, empreinte conforme) ou motif."""
    base, motif = _base(config)
    out = {"installee": base is not None, "dossier": str(dossier(config))}
    if base is None:
        out["motif"] = motif
        return out
    a = base.acceptation
    out.update(accepte_le=a.get("accepte_le"), licence=LICENCE_NOM, doi=DOI, version=a.get("version"),
               empreinte_sha1=a["empreinte"]["sha1"], lieux=base.lignes, communes=len(base.index))
    return out


def source(base: Base, registre: RegistreReferences | None = None) -> dict:
    """Source portée par toute valeur tirée du fichier : licence, attribution, réserve, référence ``doi:``."""
    a = base.acceptation
    out = {"service": "CASSINI-LOCAL", "titre": "Base Cassini (EHESS), fichier installé par l'utilisateur",
           "reference": REFERENCE, "url": LIENS["doi"], "licence": LICENCE_NOM, "licence_lien": LIENS["licence"],
           "conditions": "pas d'usage commercial ; attribution obligatoire ; partage dans les mêmes conditions",
           "attribution": ATTRIBUTION, "reserve": RESERVE, "nature": "secondaire_savante",
           "fichier_local": {"nom": FICHIER, "empreinte_sha1": a["empreinte"]["sha1"],
                             "accepte_le": a.get("accepte_le"), "version": a.get("version")},
           "consulte_le": Date.today().isoformat()}
    if registre is not None:
        out["au_registre"] = registre.est_consultee(REFERENCE)
    return out


def _plat(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn").casefold()).strip()


def _recensements(base: Base, lieu: dict) -> list[dict]:
    out = []
    for colonne in base.entete:
        m = POPULATION.fullmatch(colonne)
        if not m:
            continue
        cle = m.group(1)
        if cle in REPUBLICAINS:
            libelle, debut, fin = REPUBLICAINS[cle]
        elif cle.isdigit():
            libelle, debut, fin = cle, int(cle), int(cle)
        else:
            continue
        valeur = (lieu.get(colonne) or "").strip()
        out.append({"recensement": libelle, "debut": debut, "fin": fin,
                    "valeur": int(valeur) if valeur.isdigit() else None,
                    "code_info": (lieu.get(f"pop_{cle}_info") or "").strip()})
    return sorted(out, key=lambda r: r["debut"])


def _resume_lieu(lieu: dict) -> dict:
    ident = lieu["noacass"].strip()
    out = {"identifiant_cassini": ident, "type": (lieu.get("featuretype") or "").strip(),
           "noms": {"carte_de_cassini": lieu["nom_cassini"].strip(), "an III": lieu["nom_an3"].strip(),
                    "1801": lieu["nom_1801"].strip(), "1999": lieu["nom_1999"].strip()},
           "chef_lieu_communal_1999": lieu["est_chef_lieu_communal_1999"].strip() == "t"}
    chefs = [libelle for colonne, libelle in CHEFS_LIEUX.items() if (lieu.get(colonne) or "").strip() == "t"]
    if chefs:
        out["chef_lieu_de"] = chefs
    if re.fullmatch(r"\d{1,6}", ident):
        out["fiche"] = LIENS["fiche_cassini"].format(ident)
    return out


def consulter(config, code: str, nom_cog: str = "") -> dict | None:
    """Lieux de la base rattachés au code INSEE ; None si la base n'est pas utilisable (non installée, non
    acceptée, empreinte non conforme, emplacement refusé) : l'appelant garde alors son comportement inchangé."""
    base, _ = _base(config)
    if base is None:
        return None
    try:
        lieux = base.lieux(code)
    except (OSError, UnicodeDecodeError, csv.Error, StopIteration):
        return None
    try:
        registre = RegistreReferences(config.references_consultees_path)
        src = source(base, registre)
    except OSError:
        src = source(base)
    chefs = [x for x in lieux if x["est_chef_lieu_communal_1999"].strip() == "t"]
    principal = chefs[0] if len(chefs) == 1 else None
    if principal is None and nom_cog:
        memes = [x for x in chefs if _plat(x["nom_1999"]) == _plat(nom_cog)]
        principal = memes[0] if len(memes) == 1 else None
    bloc = {"source": src, "code_insee": code, "nombre_de_lieux": len(lieux),
            "lieux": [_resume_lieu(x) for x in lieux[:LIEUX_MAX]],
            "note": ("Lieux de la carte de Cassini rattachés à ce code INSEE (géographie de mars 2021) par le jeu "
                     "lui-même. Un lieu qui n'est pas chef-lieu communal en 1999 peut être une ancienne commune "
                     "ou un écart réuni à la commune : le jeu ne date aucune réunion ; il oriente vers une fusion "
                     "à établir, il ne l'établit pas."),
            "avertissement": AVERTISSEMENT}
    if lieux and principal is None:
        bloc["principal"] = None
        bloc["motif"] = ("aucun lieu, ou plusieurs, marqué chef-lieu communal en 1999 pour ce code : aucun n'est "
                         "choisi, les niveaux restent « inconnu »")
    elif principal is not None:
        bloc["principal"] = principal["noacass"].strip()
    return {"bloc": bloc, "source": src, "principal": principal,
            "recensements": _recensements(base, principal) if principal else []}


def _indication(niveau: str, valeur, src: dict, debut: str | None, fin: str | None, note: str, ancien: dict,
                **extra) -> dict:
    return {"niveau": niveau, "valeur": valeur, "source": src,
            "periode_de_validite": {"debut": debut, "fin": fin, "note": note}, "statut": INDICATION,
            "avertissement": AVERTISSEMENT, "consultation": ancien.get("consultation", []), **extra}


def completer(niveaux: list[dict], population: dict, local: dict, d0: str, d1: str) -> tuple[list[dict], dict]:
    """Remplace les niveaux « inconnu » que la base documente par une indication (source, licence, attribution,
    période) ; un niveau déjà sourcé (COG, Melodi) n'est jamais touché."""
    lieu, src = local["principal"], local["source"]
    if lieu is None:
        return niveaux, population
    an3 = "instantané de l'an III (1794-1795) : valable à cette date, ni avant ni après selon le jeu"
    out = []
    for n in niveaux:
        nouveau = None
        if n.get("valeur") != INCONNU:
            out.append(n)
            continue
        if n["niveau"] == "nom":
            noms = [{"nom": lieu[c].strip(), "instantane": i} for c, i in
                    (("nom_an3", "an III (1794-1795)"), ("nom_1801", "1801"), ("nom_1999", "1999"))
                    if lieu[c].strip()]
            if noms:
                nouveau = _indication("nom", noms, src, "1794", "1999", (
                    "instantanés (an III, 1801, 1999), pas un historique continu : le nom à la date demandée "
                    "n'est pas établi par le jeu"), n, nom_sur_la_carte_de_cassini=lieu["nom_cassini"].strip())
        elif n["niveau"] == "departement":
            deps = [{"departement": lieu[c].strip(), "instantane": i} for c, i in
                    (("departement_an_3", "an III (1794-1795)"), ("departement_1999", "1999"))
                    if lieu[c].strip()]
            if deps:
                nouveau = _indication("departement", deps, src, "1794", "1999", (
                    "instantanés (nom du département en l'an III, code en 1999), pas un historique continu"), n)
        elif n["niveau"] == "district" and lieu["district_an_3"].strip():
            nouveau = _indication("district", lieu["district_an_3"].strip(), src, "1794", "1795", an3, n)
        elif n["niveau"] == "generalite" and lieu["intendances"].strip():
            nouveau = _indication("generalite", lieu["intendances"].strip(), src, None, "1789", (
                "fin de l'Ancien Régime, date non précisée par le jeu ; rattachement hérité de la carte par "
                "traitement automatique (dictionnaire des colonnes du jeu), pas un rattachement établi pour la "
                "commune"), n, type=lieu["intendances_types"].strip(),
                subdelegations=lieu["subdelegations"].strip())
        out.append(nouveau or n)
    if population.get("valeur") == INCONNU:
        y0, y1 = int(d0[:4]), int(d1[:4])
        connus = [r for r in local["recensements"] if r["valeur"] is not None]
        avant = [r for r in connus if r["debut"] <= y1]
        if avant:
            r = avant[-1]
            population = {
                "niveau": "population", "valeur": r["valeur"], "annee": r["debut"], "recensement": r["recensement"],
                "mesure": "population du lieu au recensement (base Cassini)", "source": src,
                "periode_de_validite": {"debut": str(r["debut"]), "fin": str(r["fin"]),
                                        "note": "année du recensement ; aucune valeur interpolée"},
                "statut": INDICATION, "avertissement": AVERTISSEMENT,
                "annees_disponibles": [x["recensement"] for x in connus],
                "consultation": population.get("consultation", []),
                "motif_precedent": population.get("motif", "")}
            if r["fin"] < y0:
                population["ecart_annees"] = y0 - r["fin"]
    return out, population
