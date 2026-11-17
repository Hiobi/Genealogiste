"""Budget de collecte (#157) : par enquête, et plafond journalier par hôte des services d'archives.

- **Mesure** : un appel d'outil de collecte lié à une enquête s'exécute dans ``mesurer(garde)``. Le client HTTP
  appelle ``avant_envoi(hote)`` avant chaque requête réellement émise (essais et redirections compris ; une
  réponse servie par le cache n'émet rien et ne compte pas) : la garde lève ``BudgetEpuise`` AVANT l'envoi
  quand le budget de l'hôte est atteint ; sinon la requête est comptée par hôte. Tous les outils réseau de
  collecte du catalogue y passent avec enquete=<id> (#211). Le budget arrête une boucle d'enquête ; il ne mesure
  ni la durée ni le coût réel, plafonné côté client (--max-budget-usd).
- **Plafond journalier** (``PlafondJour``) : indépendant des enquêtes, persistant entre redémarrages (table
  ``compteurs_jour`` du cache SQLite, jamais vidée par ``cache_purger``), partagé entre serveurs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .http import SourceError

# Dimensions d'un budget d'enquête : 0 = illimité.
LIMITES = ("requetes_par_hote", "images")
# Retirées (#211) : ignorées dans les enquêtes existantes et dans les budgets reçus.
RETIREES = ("duree_min", "cout_tokens")


class BudgetEpuise(SourceError):
    """Requête refusée avant l'envoi : budget de l'enquête atteint (jamais mémorisée comme échec)."""

    def __init__(self, message: str, limite: str, hote: str = ""):
        super().__init__(message)
        self.limite = limite
        self.hote = hote


class PlafondAtteint(SourceError):
    """Requête refusée avant l'envoi : plafond journalier de l'hôte atteint."""


@dataclass
class Mesure:
    garde: Callable[[str, Mesure], None] | None = None
    requetes: Counter = field(default_factory=Counter)
    refus: BudgetEpuise | None = None


_MESURE: ContextVar[Mesure | None] = ContextVar("genealogiste_mesure_budget", default=None)


@contextmanager
def mesurer(garde: Callable[[str, Mesure], None] | None = None) -> Iterator[Mesure]:
    m = Mesure(garde)
    jeton = _MESURE.set(m)
    try:
        yield m
    finally:
        _MESURE.reset(jeton)


def avant_envoi(hote: str) -> None:
    """Appelé par le client HTTP juste avant d'émettre une requête vers ``hote``."""
    m = _MESURE.get()
    if m is None:
        return
    if m.refus is not None:  # budget déjà refusé pendant cet appel : plus rien ne part
        raise m.refus
    if m.garde is not None:
        try:
            m.garde(hote, m)
        except BudgetEpuise as exc:
            m.refus = exc
            raise


def compter(hote: str) -> None:
    m = _MESURE.get()
    if m is not None:
        m.requetes[hote] += 1


# ---------------------------------------------------------------------------- plafond journalier

def secondes_avant_minuit(maintenant: datetime | None = None) -> float:
    n = maintenant or datetime.now()
    demain = datetime.combine(n.date() + timedelta(days=1), datetime.min.time())
    return round((demain - n).total_seconds(), 1)


class PlafondJour:
    """Plafond de requêtes émises par hôte et par jour (date locale), pour tous les hôtes externes (#211).

    Avec ``politique`` (``politique_acces.PolitiqueAcces``) : plafond de chaque hôte selon la politique d'accès
    (archives : GENEALOGISTE_PLAFOND_JOUR_ARCHIVES ; autres : GENEALOGISTE_PLAFOND_JOUR_DEFAUT ; par hôte :
    GENEALOGISTE_PLAFONDS_JOUR). Sans politique (compatibilité #157) : ``plafond`` pour les seuls ``hotes`` et
    leurs sous-domaines. Un plafond de 0 désactive."""

    def __init__(self, cache, plafond: int = 0, hotes: set[str] | frozenset[str] = frozenset(),
                 jour: Callable[[], date] = date.today, *, politique=None):
        self.cache = cache
        self.plafond = max(0, int(plafond or 0))
        self.hotes = frozenset(h.lower().removeprefix("www.") for h in hotes if h)
        self.jour = jour
        self.politique = politique

    def limite(self, hote: str) -> tuple[int, str]:
        """(plafond du jour, variable qui le règle) pour ``hote`` ; 0 = aucun plafond."""
        if self.politique is not None:
            p = self.politique.politique(hote)
            return p.plafond_jour, p.variable_plafond
        h = (hote or "").lower().removeprefix("www.")
        if self.plafond and any(h == x or h.endswith("." + x) for x in self.hotes):
            return self.plafond, "GENEALOGISTE_PLAFOND_JOUR_ARCHIVES"
        return 0, ""

    def concerne(self, hote: str) -> bool:
        return bool(self.limite(hote)[0])

    def consommer(self, hote: str) -> None:
        """Compte une requête vers ``hote`` ; lève PlafondAtteint (sans compter) si le plafond est atteint."""
        plafond, variable = self.limite(hote)
        if not plafond:
            return
        n = self.cache.incrementer_jour(hote.lower(), self.jour().isoformat(), plafond)
        if n is None:
            raise PlafondAtteint(
                f"{hote} : plafond journalier de {plafond} requêtes atteint pour ce service ({variable}) ; "
                "aucune requête envoyée. Reprendre demain ou consulter le service dans le navigateur.",
                reessayer_apres=secondes_avant_minuit())

    def etat(self) -> dict:
        etat = {"plafond": self.plafond, "jour": self.jour().isoformat(),
                "consomme": self.cache.compteurs_jour(self.jour().isoformat())}
        if self.politique is not None:
            etat["plafond"] = {"archives": self.politique.plafond_archives, "autre": self.politique.plafond_defaut}
        return etat
