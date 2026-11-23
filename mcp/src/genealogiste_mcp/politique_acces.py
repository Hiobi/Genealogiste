"""Politique d'accès par service (#211, lot B) : pour chaque hôte externe, intervalle minimal entre deux requêtes,
plafond de requêtes émises par jour, concurrence et référence (CGU, documentation d'API) avec sa date de relevé.

Point d'entrée unique du client HTTP (intervalle) et du plafond journalier (``budget.PlafondJour``). Ordre de
priorité, champ par champ :

- intervalle : ``GENEALOGISTE_DEBITS`` > ``intervalle_requetes`` du référentiel des archives > table ``SERVICES``
  > ``GENEALOGISTE_DEBIT_DEFAUT`` ;
- plafond/jour : ``GENEALOGISTE_PLAFONDS_JOUR`` > table ``SERVICES`` > ``GENEALOGISTE_PLAFOND_JOUR_ARCHIVES``
  (hôtes des services d'archives du référentiel, hors type « autre », sous-domaines compris) >
  ``GENEALOGISTE_PLAFOND_JOUR_DEFAUT`` (tout autre hôte) ; 0 = pas de plafond ;
- concurrence : table ``SERVICES`` > 1.

Chaque valeur porte sa provenance (``PROVENANCES``). Une valeur n'est « sourcee » qu'avec une ``reference`` et
une date ``releve_le`` : sans référence vérifiée, la valeur reste un défaut ou une valeur historique du plugin.
Les limites relevées dans la documentation d'un service figurent dans ``limites_documentees`` ; elles ne
remplacent pas la valeur appliquée, choisie plus prudente.

Concurrence : le serveur MCP sérialise les appels d'outils (verrou de ``ServeurMCP``) et le client n'émet jamais
deux requêtes en parallèle ; la valeur 1 est donc la contrainte effective de chaque processus, consignée pour
une éventuelle parallélisation future (aucun sémaphore n'est nécessaire aujourd'hui).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from urllib.parse import urlsplit

PROVENANCES = {
    "sourcee": "valeur sourcée (référence et date de relevé)",
    "historique": "valeur historique du plugin",
    "referentiel": "référentiel des services d'archives (intervalle_requetes)",
    "environnement": "surcharge par variable d'environnement",
    "defaut": "défaut prudent du plugin",
}
CATEGORIES = ("api", "archives", "autre", "contexte")  # contexte : services de contexte historique (#285)
VARIABLE_PLAFOND = {"archives": "GENEALOGISTE_PLAFOND_JOUR_ARCHIVES", "autre": "GENEALOGISTE_PLAFOND_JOUR_DEFAUT",
                    "api": "GENEALOGISTE_PLAFOND_JOUR_DEFAUT", "contexte": "GENEALOGISTE_PLAFOND_JOUR_DEFAUT"}


@dataclass(frozen=True)
class Entree:
    """Ligne de la table des services. ``None`` = valeur par défaut de la catégorie."""

    service: str
    intervalle: float | None = None
    plafond_jour: int | None = None
    concurrence: int = 1
    reference: str = ""  # URL des CGU ou de la documentation d'API
    releve_le: str = ""  # date ISO du relevé de la référence
    limites_documentees: str = ""  # ce que dit la référence (information, pas la valeur appliquée)
    provenance_intervalle: str = "defaut"
    provenance_plafond: str = "defaut"
    provenance_concurrence: str = "defaut"
    categorie: str = "api"

    def __post_init__(self):
        for p in (self.provenance_intervalle, self.provenance_plafond, self.provenance_concurrence):
            if p not in PROVENANCES:
                raise ValueError(f"{self.service} : provenance inconnue {p!r}")
        sourcee = "sourcee" in (self.provenance_intervalle, self.provenance_plafond, self.provenance_concurrence)
        if (sourcee or self.reference) and not self.reference.startswith("https://"):
            raise ValueError(f"{self.service} : valeur sourcée sans reference (URL https)")
        if (sourcee or self.reference) and not self.releve_le:
            raise ValueError(f"{self.service} : reference sans date releve_le")
        if self.releve_le:
            date.fromisoformat(self.releve_le)
        if self.concurrence < 1:
            raise ValueError(f"{self.service} : concurrence >= 1 attendue")
        if self.categorie not in CATEGORIES:
            raise ValueError(f"{self.service} : catégorie inconnue {self.categorie!r}")


# Intervalles repris tels quels de l'ancienne table RATE de server.py ; provenance revue au 2026-11-18 (#119,
# docs/acces-machine-archives.md) : « sourcee » seulement quand la valeur appliquée est publiée par le service.
SERVICES: dict[str, Entree] = {
    "deces.matchid.io": Entree(
        "matchID (fichier des personnes décédées)", intervalle=1.0, provenance_intervalle="sourcee",
        reference="https://matchid.io/link-api", releve_le="2026-11-18",
        limites_documentees="Recherche unitaire limitée à une requête par seconde (valeur appliquée) ; sans jeton, "
                            "nombre d'appels limité (« au-delà d'une centaine d'appels » : jeton gratuit "
                            "nécessaire) ; avec jeton, nombre d'appels illimité, 1/s maintenu ; appariement "
                            "search/csv : 50 à 100 requêtes par seconde."),
    "api.wikitree.com": Entree(
        "WikiTree API", intervalle=1.0, provenance_intervalle="historique",
        reference="https://github.com/wikitree/wikitree-api/blob/main/README.md", releve_le="2026-11-17",
        limites_documentees="Requêtes sans appId soumises à des limites strictes (aucun chiffre publié) ; "
                            "le plugin envoie toujours un appId."),
    "gallica.bnf.fr": Entree(
        "Gallica (BnF)", intervalle=1.0, provenance_intervalle="historique"),
    "query.wikidata.org": Entree(
        "Wikidata Query Service", intervalle=1.0, provenance_intervalle="historique",
        reference="https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual#Query_limits",
        releve_le="2026-11-17",
        limites_documentees="Par client (User-Agent + IP) : 60 s de calcul par minute, 30 requêtes en erreur "
                            "par minute, 5 requêtes parallèles par IP ; 429 avec Retry-After au-delà ; "
                            "User-Agent conforme exigé."),
    "geo.api.gouv.fr": Entree(
        "API Géo", intervalle=0.1, provenance_intervalle="sourcee",
        reference="https://guides.data.gouv.fr/foire-aux-questions", releve_le="2026-11-18",
        limites_documentees="FAQ data.gouv.fr : 10 requêtes par seconde et par IP pour l'API Découpage "
                            "administratif (valeur appliquée) ; la fiche "
                            "https://www.data.gouv.fr/dataservices/672cf6946a8456f417812b0f annonce 50 appels "
                            "par seconde et par IP : sources contradictoires, la plus stricte est retenue."),
    "www.insee.fr": Entree("INSEE (fichiers du COG)"),
    "n2t.net": Entree("N2T (registre des NAAN ARK)"),
}


@dataclass(frozen=True)
class Politique:
    """Politique effective d'un hôte."""

    hote: str
    service: str
    categorie: str
    intervalle: float
    plafond_jour: int
    concurrence: int
    reference: str
    releve_le: str
    limites_documentees: str
    variable_plafond: str
    provenance: dict = field(default_factory=dict)  # champ -> clé de PROVENANCES

    def en_dict(self) -> dict:
        d = asdict(self)
        d["provenance_libelle"] = {k: PROVENANCES[v] for k, v in self.provenance.items()}
        return d


def services_contexte() -> dict[str, Entree]:
    """Hôtes des services de contexte historique (referentiels/sources_contexte.json), déclarés avec les valeurs
    par défaut ; une entrée de SERVICES pour le même hôte (Gallica, Wikidata) reste prioritaire."""
    from .contexte import services

    return services.entrees_politique()


def normaliser_hote(hote: str) -> str:
    """Nom d'hôte en minuscules, sans port ni identifiants (``netloc`` ou nom nu)."""
    h = (hote or "").strip()
    if "//" not in h:
        h = "//" + h
    return (urlsplit(h).hostname or "").lower()


def _sans_www(h: str) -> str:
    return h.removeprefix("www.")


class PolitiqueAcces:
    def __init__(self, *, services: dict[str, Entree] | None = None, referentiel: dict[str, float] | None = None,
                 hotes_archives: frozenset[str] | set[str] = frozenset(), services_archives: dict[str, str] | None = None,
                 debits: dict[str, float] | None = None, debit_defaut: float = 0.0,
                 plafond_archives: int = 0, plafond_defaut: int = 0, plafonds: dict[str, int] | None = None):
        if services is None:  # table du plugin, complétée par les hôtes du référentiel de contexte (#285)
            services = {**services_contexte(), **SERVICES}
        self.services = {normaliser_hote(h): e for h, e in services.items()}
        self.referentiel = {normaliser_hote(h): float(v) for h, v in (referentiel or {}).items()}
        self.hotes_archives = frozenset(_sans_www(normaliser_hote(h)) for h in hotes_archives if h)
        self.services_archives = {normaliser_hote(h): n for h, n in (services_archives or {}).items()}
        self.debits = {normaliser_hote(h): float(v) for h, v in (debits or {}).items()}
        self.debit_defaut = float(debit_defaut or 0.0)
        self.plafond_archives = max(0, int(plafond_archives or 0))
        self.plafond_defaut = max(0, int(plafond_defaut or 0))
        self.plafonds = {normaliser_hote(h): max(0, int(v)) for h, v in (plafonds or {}).items()}

    @classmethod
    def depuis_config(cls, config) -> PolitiqueAcces:
        from . import archives

        return cls(referentiel=archives.intervalles(), hotes_archives=archives.hotes(),
                   services_archives=_noms_archives(archives),
                   debits=config.debits, debit_defaut=config.debit_defaut,
                   plafond_archives=config.plafond_jour_archives, plafond_defaut=config.plafond_jour_defaut,
                   plafonds=config.plafonds_jour)

    def est_archive(self, hote: str) -> bool:
        h = _sans_www(normaliser_hote(hote))
        return any(h == x or h.endswith("." + x) for x in self.hotes_archives)

    def politique(self, hote: str) -> Politique:
        h = normaliser_hote(hote)
        entree = self.services.get(h)
        archive = self.est_archive(h)
        categorie = entree.categorie if entree else "archives" if archive else "autre"
        prov: dict[str, str] = {}
        if h in self.debits:
            intervalle, prov["intervalle"] = self.debits[h], "environnement"
        elif h in self.referentiel:
            intervalle, prov["intervalle"] = self.referentiel[h], "referentiel"
        elif entree and entree.intervalle is not None:
            intervalle, prov["intervalle"] = entree.intervalle, entree.provenance_intervalle
        else:
            intervalle, prov["intervalle"] = self.debit_defaut, "defaut"
        variable = VARIABLE_PLAFOND[categorie]
        if h in self.plafonds:
            plafond, prov["plafond_jour"], variable = self.plafonds[h], "environnement", "GENEALOGISTE_PLAFONDS_JOUR"
        elif entree and entree.plafond_jour is not None:
            plafond, prov["plafond_jour"] = entree.plafond_jour, entree.provenance_plafond
        else:
            plafond = self.plafond_archives if categorie == "archives" else self.plafond_defaut
            prov["plafond_jour"] = "defaut"
        prov["concurrence"] = entree.provenance_concurrence if entree else "defaut"
        service = entree.service if entree else self._service_archives(h)
        return Politique(hote=h, service=service, categorie=categorie, intervalle=float(intervalle),
                         plafond_jour=int(plafond), concurrence=entree.concurrence if entree else 1,
                         reference=entree.reference if entree else "", releve_le=entree.releve_le if entree else "",
                         limites_documentees=entree.limites_documentees if entree else "",
                         variable_plafond=variable, provenance=prov)

    def _service_archives(self, h: str) -> str:
        if h in self.services_archives:
            return self.services_archives[h]
        s = _sans_www(h)
        for hote, nom in self.services_archives.items():
            x = _sans_www(hote)
            if s == x or s.endswith("." + x):
                return nom
        return ""

    def intervalle(self, hote: str) -> float:
        return self.politique(hote).intervalle

    def plafond_jour(self, hote: str) -> int:
        return self.politique(hote).plafond_jour

    def intervalles_declares(self) -> dict[str, float]:
        """Intervalles explicitement déclarés (table, référentiel, environnement), hôte -> secondes."""
        out = {h: e.intervalle for h, e in self.services.items() if e.intervalle is not None}
        out.update(self.referentiel)
        out.update(self.debits)
        return out

    def table(self) -> list[dict]:
        """Politique effective des services nommés et des hôtes surchargés par l'environnement."""
        hotes = list(self.services) + [h for h in (*self.debits, *self.plafonds) if h not in self.services]
        return [self.politique(h).en_dict() for h in dict.fromkeys(hotes)]

    def defauts(self) -> dict:
        return {
            "archives": {"intervalle": self.debit_defaut, "plafond_jour": self.plafond_archives,
                         "variables": ["GENEALOGISTE_DEBIT_DEFAUT", "GENEALOGISTE_PLAFOND_JOUR_ARCHIVES"],
                         "note": "intervalle_requetes du référentiel prioritaire s'il est renseigné"},
            "autre": {"intervalle": self.debit_defaut, "plafond_jour": self.plafond_defaut,
                      "variables": ["GENEALOGISTE_DEBIT_DEFAUT", "GENEALOGISTE_PLAFOND_JOUR_DEFAUT"]},
            "contexte": {"intervalle": self.debit_defaut, "plafond_jour": self.plafond_defaut,
                         "variables": ["GENEALOGISTE_DEBIT_DEFAUT", "GENEALOGISTE_PLAFOND_JOUR_DEFAUT"],
                         "note": "hôtes du référentiel des services de contexte (sources_contexte.json)"},
        }


def _noms_archives(archives) -> dict[str, str]:
    out: dict[str, str] = {}
    for s in archives.services():
        for url in (s.get("site"), s.get("visionneuse")):
            h = urlsplit(url or "").hostname
            if h:
                out.setdefault(h.lower(), f"{s.get('code', '')} — {s.get('nom', '')}".strip(" —"))
    return out
