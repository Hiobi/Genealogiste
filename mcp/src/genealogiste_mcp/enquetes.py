"""État de recherche persistant et reprenable, par enquête (#155).

Une enquête = un fichier JSON lisible dans ``<données>/enquetes/<id>.json`` (écriture atomique, verrou
interprocessus), versionné avec le journal de recherche (fichiers internes du dépôt Git des données). Il
contient :

- les **pistes** : question, hypothèses, sources à consulter dans l'ordre, statut ;
- la **progression par registre** : service, ARK ou cote, vues lues et ce qu'on y a lu, bornes, verdict ;
- les **tâches manuelles** pour l'utilisateur ;
- les **requêtes faites** (outil, paramètres normalisés, date, résultat, entrées du journal) ;
- le **budget** (#157, #211) : limites (requêtes par hôte, images), consommation mesurée côté serveur, blocage
  et reste à faire à l'épuisement. Les anciennes clés ``duree_min``, ``cout_tokens`` et ``duree_s`` sont
  ignorées à la lecture.

Le journal reste la trace exhaustive ; l'état dit où en est la recherche. Toute entrée négative de l'état
référence une entrée du journal (créée si besoin). Rien ici ne part sur le réseau.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from . import ark, outils, sondage
from .budget import LIMITES, RETIREES, BudgetEpuise
from .fichiers import ecrire_atomique, verrou
from .journal import Journal
from .normalize.names import strip_accents

VERROU = ".enquetes.lock"
STATUTS_PISTE = ("a_faire", "en_cours", "trouve", "negatif", "bloque", "manuel")
STATUTS_TACHE = ("a_faire", "faite", "abandonnee")
STATUTS_ENQUETE = ("ouverte", "bloque", "close")
LIBELLES_LIMITES = {"requetes_par_hote": "requêtes par hôte", "images": "images lues"}
RESULTATS = ("positif", "negatif", "erreur", "manuel")
TERMINES = ("trouve", "negatif")  # piste ou registre sans action restante
# identité dédiée (cle_requete) ; les autres outils budgétés : outils.IDENTITE_REQUETE (#211)
OUTILS_SUIVIS = ("recherche_multi", "archives_naviguer", "archive_image")
SOURCES_MULTI = ("matchid", "wikitree", "wikidata", "gallica")
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
PAS_DEFAUT = 20
MAX_LECTURES_SONDAGE = 15  # lectures d'un sondage guidé avant l'arrêt (#156)


class EnqueteError(ValueError):
    pass


_ID_TACHE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _lien_tache(element: dict, d: dict) -> None:
    """``tache_gramps`` (#263) : identifiant de la tâche de Gramps Web liée à une piste ou une tâche manuelle
    (noté après application de la proposition qui l'a créée) ; "" retire le lien."""
    if "tache_gramps" not in d:
        return
    v = d["tache_gramps"]
    if v in ("", None):
        element.pop("tache_gramps", None)
    elif isinstance(v, str) and _ID_TACHE.match(v.strip()):
        element["tache_gramps"] = v.strip()
    else:
        raise EnqueteError("tache_gramps : identifiant de la tâche de Gramps Web (S12…), ou \"\" pour délier.")


def maintenant() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def cle_source(source: str) -> str:
    """Identité d'un registre : ARK de la ressource (sans vue), sinon l'URL ou la cote telle quelle."""
    a = ark.find(source or "")
    return a.base if a else (source or "").strip().rstrip("/")


def _txt(v) -> str:
    return re.sub(r"\s+", " ", strip_accents(str(v or "")).lower()).strip()


def cle_requete(outil: str, parametres: dict) -> dict:
    """Clé exacte et prudente d'une demande : deux demandes ne sont « la même » que si leur clé est égale."""
    p = parametres or {}
    if outil == "recherche_multi":
        cle = {k: _txt(p.get(k)) for k in ("nom", "prenom", "ne_vers", "lieu", "decede_vers")}
        cle["sources"] = sorted(p.get("sources") or SOURCES_MULTI)
        return cle
    if outil == "archives_naviguer":
        return {"registre": cle_source(p.get("source", "")), "page": int(p.get("page") or 0),
                "pas": int(p.get("pas") or PAS_DEFAUT)}
    if outil == "archive_image":
        return {"registre": cle_source(p.get("registre") or p.get("source", "")),
                "vue": int(p.get("vue") or p.get("page") or 0)}
    if (identite := outils.IDENTITE_REQUETE.get(outil)) is not None:  # outils de collecte budgétés (#211)
        return {k: _identite(nature, p.get(k), defaut) for k, (nature, defaut) in identite.items()}
    return {k: _txt(v) if isinstance(v, str) else v for k, v in sorted(p.items())}


def _identite(nature: str, valeur, defaut):
    """Valeur normalisée d'un paramètre d'identité (outils.IDENTITE_REQUETE) ; absent ou None : le défaut."""
    v = defaut if valeur is None else valeur
    if nature == outils.TEXTE:
        return _txt(v)
    if nature == outils.ENTIER:
        try:
            return int(v)
        except (TypeError, ValueError):
            return _txt(v)  # valeur inattendue : comparée telle quelle, jamais confondue avec un entier
    if nature == outils.BOOLEEN:
        return v if isinstance(v, bool) else _txt(v) in ("true", "1", "oui", "vrai")
    return str(v).strip()


# ---------------------------------------------------------------------------- intervalles de vues

def _intervalles(valeurs) -> list[list[int]]:
    """Liste d'entiers ou d'intervalles [de, a] -> intervalles triés et fusionnés."""
    bruts = []
    for v in valeurs or []:
        if isinstance(v, int | str) and str(v).strip().lstrip("-").isdigit():
            n = int(v)
            bruts.append([n, n])
        elif isinstance(v, list | tuple) and len(v) == 2:
            de, a = int(v[0]), int(v[1])
            bruts.append([min(de, a), max(de, a)])
        else:
            raise EnqueteError(f"Vue ou intervalle de vues invalide : {v!r} (entier ou [de, a]).")
    out: list[list[int]] = []
    for de, a in sorted(bruts):
        if out and de <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], a)
        else:
            out.append([de, a])
    return out


def _contient(intervalles: list[list[int]], de: int, a: int) -> bool:
    return any(x <= de and a <= y for x, y in intervalles)


def _soustraire(borne: list[int], lus: list[list[int]]) -> list[list[int]]:
    reste = [list(borne)]
    for x, y in lus:
        nouveau = []
        for de, a in reste:
            if y < de or x > a:
                nouveau.append([de, a])
                continue
            if de < x:
                nouveau.append([de, x - 1])
            if y < a:
                nouveau.append([y + 1, a])
        reste = nouveau
    return reste


# ---------------------------------------------------------------------------- stockage

def consomme_vide() -> dict:
    return {"requetes": {}, "images": 0}


def valider_budget(d) -> dict:
    """Limites partielles d'un budget : nombres positifs ou nuls (0 = illimité) ; clés retirées (#211)
    ignorées."""
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise EnqueteError(f"budget : objet {{{', '.join(LIMITES)}}} attendu (0 = illimité).")
    out = {}
    for k, v in d.items():
        if k in RETIREES:
            continue
        if k not in LIMITES:
            raise EnqueteError(f"budget : clé {k!r} inconnue ({', '.join(LIMITES)} ; 0 = illimité).")
        if isinstance(v, bool) or not isinstance(v, int | float) or v < 0:
            raise EnqueteError(f"budget.{k} : nombre positif ou nul attendu (0 = illimité), reçu {v!r}.")
        out[k] = int(v)
    return out


def _depasse(consomme: float, prevu: float, limite: float) -> bool:
    return bool(limite) and (consomme >= limite or consomme + prevu > limite)


class Enquetes:
    def __init__(self, data_dir: Path, journal: Journal, budget_defaut: dict | None = None):
        self.budget_defaut = {k: int((budget_defaut or {}).get(k) or 0) for k in LIMITES}
        self.data_dir = Path(data_dir)
        self.dir = self.data_dir / "enquetes"
        self.journal = journal
        self._crees: list[str] = []  # entrées de journal créées par la notation en cours

    # -- fichiers
    def _chemin(self, eid: str) -> Path:
        if not _ID.match(eid or ""):
            raise EnqueteError(f"Identifiant d'enquête invalide : {eid!r} (minuscules, chiffres, - et _).")
        return self.dir / f"{eid}.json"

    def _charger(self, eid: str) -> dict:
        chemin = self._chemin(eid)
        if not chemin.exists():
            raise EnqueteError(f"Enquête inconnue : {eid!r} (enquete_ouvrir pour la créer, enquete_etat pour "
                               "la liste).")
        return json.loads(chemin.read_text(encoding="utf-8"))

    def _ecrire(self, e: dict) -> None:
        e["mise_a_jour"] = maintenant()
        ecrire_atomique(self._chemin(e["id"]), json.dumps(e, ensure_ascii=False, indent=2) + "\n")

    def _toutes(self) -> list[dict]:
        if not self.dir.is_dir():
            return []
        out = []
        for f in sorted(self.dir.glob("*.json")):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue  # fichier édité à la main et illisible : ignoré, les autres restent utilisables
        return out

    def existe(self, eid: str) -> bool:
        try:
            return self._chemin(eid).exists()
        except EnqueteError:
            return False

    # -- création, lecture
    def ouvrir(self, sujet: str, personnes: list[str] | None = None, eid: str = "",
               budget: dict | None = None) -> dict:
        if not (sujet or "").strip():
            raise EnqueteError("sujet requis (ex. « naissance de Jean Dupont vers 1860 »).")
        limites = {**self.budget_defaut, **valider_budget(budget)}
        with verrou(self.data_dir, VERROU):
            if eid:
                if self._chemin(eid).exists():
                    raise EnqueteError(f"L'enquête {eid!r} existe déjà : enquete_reprendre({eid!r}).")
            else:
                base = re.sub(r"[^a-z0-9]+", "-", _txt(sujet).lower()).strip("-")[:60] or "enquete"
                eid, n = base, 2
                while self._chemin(eid).exists():
                    eid, n = f"{base}-{n}", n + 1
            e = {"id": eid, "sujet": sujet.strip(), "personnes": list(dict.fromkeys(personnes or [])),
                 "statut": "ouverte", "creee": maintenant(), "mise_a_jour": "", "pistes": [], "registres": [],
                 "taches_manuelles": [], "requetes": [], "budget": limites, "consomme": consomme_vide(),
                 "reste_a_faire": []}
            self._ecrire(e)
        return e

    def lire(self, eid: str) -> dict:
        e = self._charger(eid)
        self._budget(e)  # vue normalisée (clés retirées ignorées), sans réécrire le fichier
        return e

    def lister(self) -> list[dict]:
        out = []
        for e in self._toutes():
            out.append({"id": e.get("id"), "sujet": e.get("sujet"), "statut": e.get("statut"),
                        "personnes": e.get("personnes", []), "mise_a_jour": e.get("mise_a_jour"),
                        "pistes_ouvertes": sum(p.get("statut") not in TERMINES for p in e.get("pistes", [])),
                        "taches_en_attente": sum(t.get("statut") == "a_faire"
                                                 for t in e.get("taches_manuelles", []))})
        return out

    # -- journal
    def _journal_negatif(self, e: dict, objet: str, element: dict, resume: str, references: list[str],
                         journal: list[str] | str | None) -> list[str]:
        """Entrée(s) du journal d'un élément négatif : référence vérifiée, sinon entrée créée."""
        ids = [journal] if isinstance(journal, str) else list(journal or [])
        if ids:
            connus = {x.get("id") for x in self.journal.entries(limite=10**9)}
            absents = [j for j in ids if j not in connus]
            if absents:
                raise EnqueteError(f"Entrée(s) de journal introuvable(s) : {absents} (journal_lister).")
            return ids
        params = {"enquete": e["id"], objet: element.get("id")}
        jid = self.journal.add(source="enquete", operation=objet, parametres=params, statut="negatif",
                               resume=resume, references=[r for r in references if r],
                               personne=(e.get("personnes") or [None])[0])
        self._crees.append(jid)
        return [jid]

    # -- notation
    def noter(self, eid: str, piste: dict | None = None, registre: dict | None = None, tache: dict | None = None,
              requete: dict | None = None, statut: str = "", personnes: list[str] | None = None,
              budget: dict | None = None) -> dict:
        if statut and statut not in STATUTS_ENQUETE:
            raise EnqueteError(f"statut d'enquête : {' | '.join(STATUTS_ENQUETE)}")
        limites = valider_budget(budget)
        with verrou(self.data_dir, VERROU):
            e = self._charger(eid)
            out: dict = {"enquete": eid, "modifie": [], "journal_cree": []}
            self._crees = out["journal_cree"]
            if personnes:
                e["personnes"] = list(dict.fromkeys([*e.get("personnes", []), *personnes]))
                out["modifie"].append("personnes")
            if piste:
                out["modifie"].append(f"piste {self._piste(e, piste)['id']}")
            if registre:
                out["modifie"].append(f"registre {self._registre(e, registre)['id']}")
            if tache:
                out["modifie"].append(f"tache {self._tache(e, tache)['id']}")
            if requete:
                r = self._requete(e, requete.get("outil", ""), requete.get("parametres") or {},
                                  requete.get("resultat", ""), requete.get("journal"), requete.get("piste", ""),
                                  requete.get("resume", ""))
                out["modifie"].append(f"requete {r['outil']}")
            if statut:
                e["statut"] = statut
                out["modifie"].append(f"statut {statut}")
                if statut != "bloque":
                    e.pop("blocage", None)
            if limites:
                self._budget(e)
                e["budget"].update(limites)
                out["modifie"].append("budget")
                if e.get("statut") == "bloque" and (e.get("blocage") or {}).get("motif") == "budget" \
                        and not self._epuise(e):
                    e["statut"] = "ouverte"
                    e.pop("blocage", None)
                    out["modifie"].append("statut ouverte (budget relevé)")
                out["budget"] = self.etat_budget(e)
            self._ecrire(e)
            self._crees = []
        return out

    def tache_blocage(self, eid: str, service: str, url: str, protection: str = "", journal: str = "") -> dict:
        """Défi anti-robot rencontré pendant l'enquête (#150) : tâche manuelle « à faire » pour l'utilisateur
        (lien exact, ce qu'il faut relever), une seule par URL bloquée tant qu'elle reste à faire."""
        with verrou(self.data_dir, VERROU):
            e = self._charger(eid)
            taches = e.setdefault("taches_manuelles", [])
            t = next((x for x in taches if x.get("statut") == "a_faire" and url and x.get("url") == url), None)
            if t is None:
                t = self._tache(e, {
                    "description": (f"Défi anti-robot{f' {protection}' if protection else ''} sur {service} : ouvrir "
                                    f"{url or 'le service'} depuis un accès autorisé et relever cote, registre, "
                                    "vue et provenance (ou télécharger la vue) ; reprendre avec source_collee, "
                                    "piece_archiver ou media_enregistrer."),
                    "service": service, "url": url})
                if journal:
                    t["journal"] = [journal]
                self._ecrire(e)
        return t

    @staticmethod
    def _nouvel_id(items: list[dict], prefixe: str) -> str:
        n = 1
        pris = {x.get("id") for x in items}
        while f"{prefixe}{n}" in pris:
            n += 1
        return f"{prefixe}{n}"

    def _piste(self, e: dict, d: dict) -> dict:
        pistes = e.setdefault("pistes", [])
        p = next((x for x in pistes if d.get("id") and x["id"] == d["id"]), None)
        if p is None:
            if d.get("id") and not d.get("question"):
                raise EnqueteError(f"Piste inconnue : {d['id']!r}.")
            if not d.get("question"):
                raise EnqueteError("Nouvelle piste : question requise.")
            p = {"id": d.get("id") or self._nouvel_id(pistes, "p"), "question": "", "hypotheses": [],
                 "sources": [], "statut": "a_faire", "note": "", "journal": []}
            pistes.append(p)
        for k in ("question", "note"):
            if k in d:
                p[k] = d[k]
        _lien_tache(p, d)
        if "hypotheses" in d:
            p["hypotheses"] = list(d["hypotheses"] or [])
        if "sources" in d:
            p["sources"] = [self._source(s) for s in d["sources"] or []]
        for libelle in d.get("sources_faites") or []:
            s = next((x for x in p["sources"] if x["libelle"] == libelle), None)
            if s is None:
                raise EnqueteError(f"Source {libelle!r} absente de la piste {p['id']}.")
            s["fait"], s["date"] = True, maintenant()
        if "statut" in d:
            if d["statut"] not in STATUTS_PISTE:
                raise EnqueteError(f"statut de piste : {' | '.join(STATUTS_PISTE)}")
            p["statut"] = d["statut"]
        if p["statut"] == "negatif":
            if d.get("journal") or not p.get("journal"):
                p["journal"] = self._journal_negatif(e, "piste", p, f"{e['sujet']} — {p['question']} : négatif. "
                                                     f"{p.get('note', '')}".strip(), [], d.get("journal"))
        elif d.get("journal"):
            p["journal"] = [d["journal"]] if isinstance(d["journal"], str) else list(d["journal"])
        p["maj"] = maintenant()
        return p

    @staticmethod
    def _source(s) -> dict:
        if isinstance(s, str):
            return {"libelle": s, "fait": False}
        if not isinstance(s, dict) or not (s.get("libelle") or s.get("outil")):
            raise EnqueteError(f"Source de piste invalide : {s!r} (texte, ou {{libelle, outil, parametres}}).")
        out = {"libelle": s.get("libelle") or s["outil"], "fait": bool(s.get("fait"))}
        if s.get("outil"):
            out["outil"], out["parametres"] = s["outil"], dict(s.get("parametres") or {})
        return out

    def _trouver_registre(self, e: dict, d: dict) -> dict | None:
        regs = e.setdefault("registres", [])
        if d.get("id"):
            return next((x for x in regs if x["id"] == d["id"]), None)
        source = d.get("source") or d.get("ark") or ""
        if source:
            cle = cle_source(source)
            return next((x for x in regs if x.get("cle") == cle), None)
        if d.get("cote"):
            return next((x for x in regs if x.get("cote") == d["cote"]), None)
        return None

    def _registre(self, e: dict, d: dict) -> dict:
        regs = e.setdefault("registres", [])
        r = self._trouver_registre(e, d)
        if r is None:
            if d.get("id") and not (d.get("source") or d.get("ark") or d.get("cote")):
                raise EnqueteError(f"Registre inconnu : {d['id']!r}.")
            source = d.get("source") or d.get("ark") or ""
            if not (source or d.get("cote")):
                raise EnqueteError("Registre : source (ARK, URL de visionneuse ou manifeste) ou cote requise.")
            r = {"id": d.get("id") or self._nouvel_id(regs, "r"), "source": source,
                 "cle": cle_source(source) if source else "", "service": "", "cote": "", "titre": "", "piste": "",
                 "nb_vues": None, "bornes": None, "vues_lues": [], "lectures": [], "verdict": "",
                 "statut": "en_cours", "journal": []}
            regs.append(r)
        for k in ("service", "cote", "titre", "piste", "verdict"):
            if d.get(k):
                r[k] = d[k]
        if d.get("periode"):
            r["periode"] = list(d["periode"]) if isinstance(d["periode"], list | tuple) else d["periode"]
        if not r.get("source") and (d.get("source") or d.get("ark")):
            r["source"] = d.get("source") or d.get("ark")
            r["cle"] = cle_source(r["source"])
        if d.get("nb_vues"):
            r["nb_vues"] = int(d["nb_vues"])
        if d.get("bornes"):
            b = _intervalles([d["bornes"]])
            r["bornes"] = b[0] if b else None
        lues = list(d.get("vues_lues") or [])
        for lec in d.get("lectures") or []:
            if not isinstance(lec, dict) or not lec.get("vue"):
                raise EnqueteError(f"Lecture invalide : {lec!r} ({{vue, date, type, numero, note}}).")
            lecture = {k: lec[k] for k in ("vue", "date", "date_fin", "type", "numero", "note")
                       if lec.get(k) not in (None, "")}
            lecture["vue"] = int(lecture["vue"])
            r["lectures"] = [x for x in r["lectures"] if not (x["vue"] == lecture["vue"]
                                                               and x.get("numero") == lecture.get("numero"))]
            r["lectures"].append(lecture)
            r["lectures"].sort(key=lambda x: x["vue"])
            lues.append(lecture["vue"])
        if lues:
            r["vues_lues"] = _intervalles([*r["vues_lues"], *lues])
        if "statut" in d:
            if d["statut"] not in STATUTS_PISTE:
                raise EnqueteError(f"statut de registre : {' | '.join(STATUTS_PISTE)}")
            r["statut"] = d["statut"]
        if r["statut"] == "negatif":
            if d.get("journal") or not r.get("journal"):
                resume = (f"{e['sujet']} — registre {r.get('cote') or r.get('source')} : négatif "
                          f"(vues lues {r['vues_lues']}). {r.get('verdict', '')}").strip()
                r["journal"] = self._journal_negatif(e, "registre", r, resume, [r.get("source", "")],
                                                     d.get("journal"))
        elif d.get("journal"):
            r["journal"] = [d["journal"]] if isinstance(d["journal"], str) else list(d["journal"])
        r["maj"] = maintenant()
        return r

    def _tache(self, e: dict, d: dict) -> dict:
        taches = e.setdefault("taches_manuelles", [])
        t = next((x for x in taches if d.get("id") and x["id"] == d["id"]), None)
        if t is None:
            if not d.get("description"):
                raise EnqueteError("Nouvelle tâche manuelle : description requise." if not d.get("id")
                                   else f"Tâche inconnue : {d['id']!r}.")
            t = {"id": d.get("id") or self._nouvel_id(taches, "t"), "description": "", "service": "", "piste": "",
                 "statut": "a_faire", "creee": maintenant()}
            taches.append(t)
        for k in ("description", "service", "piste", "resultat", "url"):
            if d.get(k):
                t[k] = d[k]
        _lien_tache(t, d)
        if "statut" in d:
            if d["statut"] not in STATUTS_TACHE:
                raise EnqueteError(f"statut de tâche : {' | '.join(STATUTS_TACHE)}")
            t["statut"] = d["statut"]
        t["maj"] = maintenant()
        return t

    def _requete(self, e: dict, outil: str, parametres: dict, resultat: str, journal, piste: str = "",
                 resume: str = "", fenetre: list[int] | None = None) -> dict:
        if not outil:
            raise EnqueteError("Requête : outil requis (ex. recherche_multi, ou le nom d'un site consulté).")
        if resultat not in RESULTATS:
            raise EnqueteError(f"résultat de requête : {' | '.join(RESULTATS)}")
        r = {"outil": outil, "parametres": parametres, "cle": cle_requete(outil, parametres), "date": maintenant(),
             "resultat": resultat, "journal": [journal] if isinstance(journal, str) else list(journal or [])}
        if piste:
            r["piste"] = piste
        if resume:
            r["resume"] = resume
        if fenetre:
            r["fenetre"] = list(fenetre)
        if resultat == "negatif":
            r["journal"] = self._journal_negatif(e, "requete", {"id": outil}, resume or
                                                 f"{e['sujet']} — {outil} {parametres} : négatif.",
                                                 [], r["journal"])
        requetes = e.setdefault("requetes", [])
        ancienne = next((x for x in requetes if x["outil"] == outil and x["cle"] == r["cle"]), None)
        if ancienne is not None:  # même demande refaite : une seule entrée, date de la dernière fois
            r["journal"] = list(dict.fromkeys([*ancienne.get("journal", []), *r["journal"]]))
            r["premiere_date"] = ancienne.get("premiere_date") or ancienne["date"]
            requetes.remove(ancienne)
        requetes.append(r)
        return r

    # -- appels des outils réseau (paramètre enquete=…)
    def enregistrer(self, eid: str, outil: str, parametres: dict, resultat: str, journal: list[str] | None = None,
                    fenetre: list[int] | None = None, nb_vues: int | None = None, vue_lue: int | None = None,
                    registre: str = "", titre: str = "", cote: str = "", appel: dict | None = None,
                    periode=None) -> None:
        """Note une demande faite par un outil réseau (et, pour une image, la vue consultée). appel : paramètres
        de l'appel tels que reçus ; une demande refusée faute de budget et désormais faite sort du reste à faire."""
        with verrou(self.data_dir, VERROU):
            self._crees = []
            e = self._charger(eid)
            r = self._requete(e, outil, parametres, resultat, journal, fenetre=fenetre)
            faites = [r["cle"]] + ([cle_requete(outil, appel)] if appel is not None else [])
            # clé recalculée aussi depuis les paramètres consignés : un refus consigné avant que l'outil ait une
            # identité dédiée (outils.IDENTITE_REQUETE, #211) sort quand même du reste à faire
            e["reste_a_faire"] = [x for x in e.get("reste_a_faire", [])
                                  if not (x.get("outil") == outil
                                          and (x.get("cle") in faites
                                               or cle_requete(outil, x.get("parametres") or {}) in faites))]
            if registre:
                d = {"source": registre, "titre": titre, "cote": cote, "nb_vues": nb_vues, "periode": periode}
                if vue_lue:
                    d["vues_lues"] = [vue_lue]
                r = self._trouver_registre(e, d)
                if r is None or r.get("statut") not in TERMINES or vue_lue or nb_vues:
                    self._registre(e, {k: v for k, v in d.items() if v})
            self._ecrire(e)

    # -- « déjà fait le … »
    def deja_fait(self, outil: str, parametres: dict, fenetre: list[int] | None = None) -> list[dict]:
        """Demandes identiques déjà notées dans une enquête (clé exacte), ou vues déjà lues d'un registre."""
        cle = cle_requete(outil, parametres)
        out = []
        for e in self._toutes():
            for r in e.get("requetes", []):
                if r.get("outil") == outil and r.get("cle") == cle:
                    out.append({"enquete": e["id"], "date": r["date"], "resultat": r.get("resultat"),
                                "journal": r.get("journal", []),
                                "message": f"Déjà fait le {r['date'][:10]} (enquête {e['id']}) : "
                                           f"{outil}, résultat {r.get('resultat')}."})
            if outil not in ("archives_naviguer", "archive_image") or not cle.get("registre"):
                continue
            for reg in e.get("registres", []):
                if reg.get("cle") != cle["registre"]:
                    continue
                if outil == "archive_image" and cle["vue"]:
                    de = a = cle["vue"]
                elif outil == "archives_naviguer" and fenetre:
                    de, a = fenetre
                else:
                    continue
                if _contient(reg.get("vues_lues", []), de, a):
                    lectures = [x for x in reg.get("lectures", []) if de <= x["vue"] <= a]
                    out.append({"enquete": e["id"], "registre": reg["id"], "date": reg.get("maj", ""),
                                "vues_lues": [de, a], "lectures": lectures,
                                "message": f"Vue(s) {de}-{a} déjà lue(s) le {reg.get('maj', '')[:10]} "
                                           f"(enquête {e['id']}, registre {reg['id']})."})
        return out

    # -- reprise
    def reprendre(self, eid: str) -> dict:
        e = self._charger(eid)
        faites = {(r["outil"], json.dumps(r["cle"], sort_keys=True)): r for r in e.get("requetes", [])}
        a_faire: list[dict] = []
        deja: list[dict] = [{"outil": r["outil"], "parametres": r["parametres"], "date": r["date"],
                             "resultat": r["resultat"]} for r in e.get("requetes", [])]
        pistes = []
        for p in e.get("pistes", []):
            if p.get("statut") in TERMINES:
                continue
            restantes = []
            for s in p.get("sources", []):
                if s.get("fait"):
                    continue
                if s.get("outil") and (s["outil"], json.dumps(cle_requete(s["outil"], s.get("parametres", {})),
                                                              sort_keys=True)) in faites:
                    continue  # demande déjà notée : ne pas relancer
                restantes.append(s)
            pistes.append({"id": p["id"], "question": p["question"], "statut": p["statut"],
                           "hypotheses": p.get("hypotheses", []), "sources_restantes": restantes})
            if p.get("statut") in ("bloque", "manuel"):
                continue
            for s in restantes:
                action = {"type": "source", "piste": p["id"], "libelle": s["libelle"]}
                if s.get("outil"):
                    action.update(outil=s["outil"], parametres=s.get("parametres", {}))
                a_faire.append(action)
        registres = []
        for r in e.get("registres", []):
            if r.get("statut") in TERMINES:
                continue
            bornes = r.get("bornes") or ([1, r["nb_vues"]] if r.get("nb_vues") else None)
            restantes = _soustraire(bornes, r.get("vues_lues", [])) if bornes else None
            registres.append({"id": r["id"], "source": r.get("source"), "cote": r.get("cote"),
                              "service": r.get("service"), "statut": r["statut"], "bornes": bornes,
                              "vues_lues": r.get("vues_lues", []), "vues_restantes": restantes,
                              "lectures": r.get("lectures", [])[-3:], "verdict": r.get("verdict", "")})
            if r.get("statut") in ("bloque", "manuel"):
                continue
            if restantes == []:
                a_faire.append({"type": "registre", "registre": r["id"],
                                "motif": "Toutes les vues des bornes sont lues : noter le verdict (statut trouve "
                                         "ou negatif) ou élargir les bornes."})
                continue
            if not r.get("source"):
                a_faire.append({"type": "registre", "registre": r["id"],
                                "motif": "Registre sans ARK ni URL : consultation manuelle (tâche manuelle)."})
                continue
            if restantes:
                de, a = restantes[0]
            else:
                lues = r.get("vues_lues", [])
                de = lues[-1][1] + 1 if lues else 1
                a = de + PAS_DEFAUT - 1
            a_faire.append(self._action_registre(e, r, de, a, faites))
        taches = [t for t in e.get("taches_manuelles", []) if t.get("statut") == "a_faire"]
        refusees = [{"type": "budget", "outil": x["outil"], "parametres": x["parametres"],
                     "motif": f"Refusé faute de budget ({LIBELLES_LIMITES.get(x.get('limite'), x.get('limite'))}) "
                              f"le {x.get('date', '')[:10]}."} for x in e.get("reste_a_faire", [])]
        consigne = ("Reprendre par a_faire, dans l'ordre. Ne pas relancer les demandes de deja_fait ; "
                    "passer enquete=<id> aux outils réseau pour noter la suite, et enquete_noter pour les "
                    "lectures, verdicts et tâches manuelles.")
        if e.get("statut") == "bloque":
            consigne = (f"Enquête bloquée ({(e.get('blocage') or {}).get('message', 'budget épuisé')}). Faire le point "
                        "avec l'utilisateur ; ne reprendre qu'après accord, en relevant le budget avec "
                        f"enquete_noter({eid!r}, budget={{...}}). " + consigne)
        out = {"enquete": eid, "sujet": e["sujet"], "personnes": e.get("personnes", []), "statut": e["statut"],
               "mise_a_jour": e.get("mise_a_jour"), "a_faire": refusees + a_faire, "pistes_ouvertes": pistes,
               "registres_en_cours": registres, "taches_manuelles": taches, "deja_fait": deja,
               "budget": self.etat_budget(e), "consigne": consigne}
        if e.get("blocage"):
            out["blocage"] = e["blocage"]
        return out

    # -- budget (#157)
    def _budget(self, e: dict) -> tuple[dict, dict]:
        """Limites et consommation (un fichier antérieur au budget reçoit les valeurs par défaut). Les clés
        retirées (#211 : duree_min, cout_tokens, duree_s) sont ignorées, et un blocage sur l'une d'elles levé :
        cette limite n'existe plus."""
        budget, consomme = e.get("budget") or {}, e.get("consomme") or {}
        e["budget"] = {k: budget.get(k, self.budget_defaut[k]) for k in LIMITES}
        e["consomme"] = {k: consomme.get(k, v) for k, v in consomme_vide().items()}
        e.setdefault("reste_a_faire", [])
        blocage = e.get("blocage") or {}
        if blocage.get("motif") == "budget" and blocage.get("limite") in RETIREES:
            e.pop("blocage", None)
            if e.get("statut") == "bloque":
                e["statut"] = "ouverte"
        return e["budget"], e["consomme"]

    def etat_budget(self, e: dict) -> dict:
        lim, c = self._budget(e)
        illimite = "illimite"
        rq = lim["requetes_par_hote"]
        reste = {
            "requetes_par_hote": ({h: max(0, rq - n) for h, n in sorted(c["requetes"].items())} if rq else illimite),
            "requetes_autre_hote": rq or illimite,
            "images": max(0, lim["images"] - c["images"]) if lim["images"] else illimite,
        }
        return {"limites": dict(lim), "consomme": dict(c), "reste": reste}

    def _epuise(self, e: dict, images: int = 0, hotes: bool = True) -> str:
        """Première limite atteinte ou que l'appel prévu dépasserait ("" sinon). hotes : compter aussi un hôte
        dont le budget est atteint (le contrôle avant appel ne connaît pas encore les hôtes visés)."""
        lim, c = self._budget(e)
        if images and _depasse(c["images"], images, lim["images"]):
            return "images"
        if hotes and lim["requetes_par_hote"] and any(n >= lim["requetes_par_hote"] for n in c["requetes"].values()):
            return "requetes_par_hote"
        return ""

    def garde(self, eid: str):
        """Contrôle appelé par le client HTTP avant chaque requête émise pendant un appel lié à l'enquête."""
        e = self._charger(eid)
        lim, c = self._budget(e)

        def controler(hote: str, mesure) -> None:
            rq = lim["requetes_par_hote"]
            if rq and c["requetes"].get(hote, 0) + mesure.requetes[hote] >= rq:
                raise BudgetEpuise(f"{hote} : budget de l'enquête {eid} atteint ({rq} requêtes par hôte) ; "
                                   "requête non envoyée.", "requetes_par_hote", hote)
        return controler

    def controler(self, eid: str, outil: str, appel: dict, images: int = 0) -> dict | None:
        """Avant un appel de collecte : refus (et état bloqué, reste à faire consigné) si l'enquête est bloquée
        faute de budget ou si l'appel dépasserait une limite ; None sinon."""
        with verrou(self.data_dir, VERROU):
            e = self._charger(eid)
            self._budget(e)  # normalise une enquête antérieure (clés retirées)
            blocage = e.get("blocage") or {}
            if e.get("statut") == "bloque" and blocage.get("motif") == "budget":
                limite, message = blocage.get("limite", ""), blocage.get("message", "")
            else:
                limite, message = self._epuise(e, images, hotes=False), ""
            if not limite:
                return None
            refus = self._bloquer(e, outil, appel, limite, message)
            self._ecrire(e)
        return refus

    def apres_collecte(self, eid: str, requetes: dict, images: int, refus: BudgetEpuise | None = None,
                       outil: str = "", appel: dict | None = None) -> dict:
        """Ajoute la consommation mesurée d'un appel ; en cas de refus pendant l'appel, bloque l'enquête et
        consigne l'appel (ou sa partie non faite) au reste à faire. Renvoie les champs à ajouter à la réponse."""
        with verrou(self.data_dir, VERROU):
            e = self._charger(eid)
            _, c = self._budget(e)
            for h, n in requetes.items():
                c["requetes"][h] = c["requetes"].get(h, 0) + n
            c["images"] += images
            out = self._bloquer(e, outil, appel or {}, refus.limite, str(refus)) if refus else {}
            out["budget"] = self.etat_budget(e)
            self._ecrire(e)
        return out

    def _bloquer(self, e: dict, outil: str, appel: dict, limite: str, detail: str = "") -> dict:
        self._budget(e)
        libelle = LIBELLES_LIMITES.get(limite, limite)
        message = detail or f"budget épuisé : {libelle}"
        if not message.startswith("Budget"):
            message = f"Budget de l'enquête épuisé ({libelle}) : {message}"
        e["statut"] = "bloque"
        e["blocage"] = {"motif": "budget", "limite": limite, "date": maintenant(), "message": message}
        cle = cle_requete(outil, appel)
        if not any(x.get("outil") == outil and cle in (x.get("cle"), cle_requete(outil, x.get("parametres") or {}))
                   for x in e["reste_a_faire"]):
            e["reste_a_faire"].append({"outil": outil, "parametres": dict(appel), "cle": cle, "date": maintenant(),
                                       "limite": limite})
        return {"refus": f"{outil} non exécuté pour l'enquête {e['id']} : {message} Aucune requête envoyée.",
                "enquete": e["id"], "statut": "bloque", "motif": "budget", "limite": limite,
                "budget": self.etat_budget(e), "reste_a_faire": e["reste_a_faire"],
                "compte_rendu": self.compte_rendu(e),
                "consigne": ("Arrêt propre : ne pas relancer ni contourner. Rendre compte à l'utilisateur (compte_rendu) ; "
                             "pour continuer, avec son accord, relever le budget par enquete_noter(id, budget={...}) "
                             "puis enquete_reprendre(id), qui place le reste à faire en tête.")}

    @staticmethod
    def compte_rendu(e: dict) -> dict:
        """Compte rendu partiel : ce qui est fait, ce qui reste ouvert (repris par enquete_reprendre)."""
        requetes = e.get("requetes", [])
        return {"requetes_faites": len(requetes),
                "positives": sum(r.get("resultat") == "positif" for r in requetes),
                "negatives": sum(r.get("resultat") == "negatif" for r in requetes),
                "pistes_ouvertes": [p["id"] for p in e.get("pistes", []) if p.get("statut") not in TERMINES],
                "registres_en_cours": [{"id": r["id"], "cote": r.get("cote") or r.get("source"),
                                        "vues_lues": r.get("vues_lues", [])}
                                       for r in e.get("registres", []) if r.get("statut") not in TERMINES],
                "taches_manuelles": sum(t.get("statut") == "a_faire" for t in e.get("taches_manuelles", []))}

    @staticmethod
    def _action_registre(e: dict, r: dict, de: int, a: int, faites: dict) -> dict:
        """Prochaine vue d'un registre : la lire si une navigation l'a déjà listée, sinon naviguer."""
        listee = any(x["outil"] == "archives_naviguer" and x["cle"].get("registre") == r["cle"]
                     and x.get("fenetre") and x["fenetre"][0] <= de <= x["fenetre"][1]
                     for x in e.get("requetes", []))
        base = {"type": "registre", "registre": r["id"], "vues": [de, a]}
        if listee:
            return {**base, "outil": "archive_image", "parametres": {"source": r["source"], "page": de},
                    "motif": f"Vue {de} déjà listée, pas encore lue."}
        pas = max(1, min(PAS_DEFAUT, a - de + 1))
        params = {"source": r["source"], "page": de, "pas": pas}
        if (("archives_naviguer", json.dumps(cle_requete("archives_naviguer", params), sort_keys=True))
                in faites):
            return {**base, "outil": "archive_image", "parametres": {"source": r["source"], "page": de},
                    "motif": f"Fenêtre déjà parcourue ; vue {de} pas encore lue."}
        return {**base, "outil": "archives_naviguer", "parametres": params,
                "motif": f"Vues {de}-{a} restantes."}

    # -- sondage guidé d'un registre (#156)
    def sonder(self, eid: str, source: str, date_cible: str, type_acte: str = "", lecture: dict | None = None,
               conclusion: str = "", nb_vues: int = 0, periode=None, ordre_series: list[str] | None = None,
               max_lectures: int = MAX_LECTURES_SONDAGE) -> dict:
        """Note la lecture d'une vue dans le registre de l'enquête et propose la vue suivante (sondage.planifier).
        Arrêts : localise ; trouve ou absent (conclusion, ou dates lues qui encadrent la cible : registre négatif
        journalisé avec les bornes examinées) ; budget (enquête bloquée, images épuisées, max_lectures)."""
        if conclusion not in ("", "trouve", "absent"):
            raise EnqueteError("conclusion : trouve | absent (vide pendant le sondage).")
        sondage.intervalle_date(date_cible, "date_cible")  # refus avant toute écriture
        sondage.intervalle_periode(periode)
        if lecture:
            sondage.lecture(lecture)
        with verrou(self.data_dir, VERROU):
            self._crees = []
            e = self._charger(eid)
            r = (next((x for x in e.setdefault("registres", []) if x["id"] == source), None)
                 or self._trouver_registre(e, {"source": source}))
            maj = {"nb_vues": nb_vues, "periode": periode}
            r = self._registre(e, {"id": r["id"], **maj} if r else {"source": source, **maj})
            if lecture and r.get("nb_vues") and int(lecture["vue"]) > r["nb_vues"]:
                raise EnqueteError(f"Vue {lecture['vue']} au-delà des {r['nb_vues']} vues du registre.")
            typ = sondage.type_canonique(type_acte)
            s = next((x for x in r.setdefault("sondages", [])
                      if x.get("cible") == date_cible.strip() and x.get("type_acte") == typ), None)
            if s is None:
                s = {"cible": date_cible.strip(), "type_acte": typ, "historique": [], "statut": "en_cours",
                     "debut": maintenant()}
                r["sondages"].append(s)
            if ordre_series is not None:
                s["ordre_series"] = list(ordre_series)
            if lecture:
                self._registre(e, {"id": r["id"], "lectures": [lecture]})
                vue = int(lecture["vue"])
                s["historique"] = [v for v in s["historique"] if v != vue] + [vue]
            avert: list[str] = []
            per = r.get("periode")
            try:
                sondage.intervalle_periode(per)
            except sondage.SondageError as exc:  # période notée illisible : sondage sans interpolation initiale
                avert.append(f"Période du registre ignorée : {exc}")
                per = None
            plan = sondage.planifier(r.get("nb_vues") or 0, s["cible"], self._lectures_sondage(r, s, avert), typ,
                                     per, r.get("bornes"), s.get("ordre_series"))
            plan["avertissements"] = avert + plan["avertissements"]
            if conclusion:
                vues = [int(lecture["vue"])] if lecture else plan.get("vues") or plan["bornes"]
                plan["arret"] = conclusion
                plan["motif"] = f"Conclusion notée : acte {'trouvé' if conclusion == 'trouve' else 'absent'} (vues {vues})."
            arret = plan.get("arret", "")
            if arret in ("trouve", "absent"):
                statut = "trouve" if arret == "trouve" else "negatif"
                verdict = (f"Sondage {s['cible']}{' (' + typ + ')' if typ else ''} : "
                           + ("acte trouvé" if arret == "trouve" else "absent")
                           + f", bornes examinées {plan.get('encadrement') or plan['bornes']}, {len(s['historique'])} lecture(s) "
                           f"(vues {s['historique']}). {plan['motif']}")
                s["statut"], s["fin"] = statut, maintenant()
                self._registre(e, {"id": r["id"], "verdict": verdict, "statut": statut})
                if statut == "negatif":
                    s["journal"] = list(r.get("journal", []))
            elif not arret and (limite := self._arret_budget(e, s, max_lectures)):
                plan.update(arret="budget", motif=limite)
            plan.update(sondage={"historique": s["historique"], "statut": s["statut"]}, registre=r["id"],
                        source=r.get("source", ""), journal_cree=list(self._crees), budget=self.etat_budget(e))
            self._ecrire(e)
            self._crees = []
        return plan

    @staticmethod
    def _lectures_sondage(r: dict, s: dict, avert: list[str]) -> list[dict]:
        """Lectures du registre dans l'ordre utile : celles d'avant le sondage (par vue), puis celles du sondage
        dans l'ordre où elles ont été faites. Une lecture ancienne illisible est ignorée (avertissement)."""
        hist = s.get("historique", [])
        avant = [x for x in r.get("lectures", []) if x["vue"] not in hist]
        pendant = [x for v in hist for x in r.get("lectures", []) if x["vue"] == v]
        out = []
        for x in avant + pendant:
            if not (x.get("date") or x.get("type")):
                continue
            try:
                sondage.lecture(x)
            except sondage.SondageError as exc:
                avert.append(f"Lecture ignorée : {exc}")
                continue
            out.append(x)
        return out

    def _arret_budget(self, e: dict, s: dict, max_lectures: int) -> str:
        if e.get("statut") == "bloque":
            return f"Enquête bloquée : {(e.get('blocage') or {}).get('message', 'budget épuisé')}"
        reste = self.etat_budget(e)["reste"]["images"]
        if reste != "illimite" and reste <= 0:
            return "Budget d'images de l'enquête épuisé : rendre compte ; le relever seulement avec l'accord de l'utilisateur."
        if max_lectures and len(s.get("historique", [])) >= max_lectures:
            return (f"{max_lectures} lectures sans localiser la date : vérifier les dates lues, le type d'acte et "
                    "l'ordre des séries, ou consulter la table du registre.")
        return ""

    # -- cohérence avec le journal
    def coherence(self, eid: str) -> list[str]:
        """Éléments négatifs sans entrée de journal existante (liste vide = cohérent)."""
        e = self._charger(eid)
        connus = {x.get("id") for x in self.journal.entries(limite=10**9)}
        problemes = []
        elements = ([("piste", p) for p in e.get("pistes", []) if p.get("statut") == "negatif"]
                    + [("registre", r) for r in e.get("registres", []) if r.get("statut") == "negatif"]
                    + [("requete", q) for q in e.get("requetes", []) if q.get("resultat") == "negatif"])
        for objet, x in elements:
            ids = x.get("journal") or []
            if not ids or any(j not in connus for j in ids):
                problemes.append(f"{objet} {x.get('id') or x.get('outil')} : négatif sans entrée de journal ({ids})")
        return problemes
