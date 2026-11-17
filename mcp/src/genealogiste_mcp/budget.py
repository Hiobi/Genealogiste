"""Budget de collecte (#157) : par enquête, et plafond journalier par hôte des services d'archives.

- **Mesure** : un appel d'outil de collecte lié à une enquête s'exécute dans ``mesurer(garde)``. Le client HTTP
  appelle ``avant_envoi(hote)`` avant chaque requête réellement émise (essais et redirections compris ; une
  réponse servie par le cache n'émet rien et ne compte pas) : la garde lève ``BudgetEpuise`` AVANT l'envoi
  quand le budget de l'hôte ou la durée est atteint ; sinon la requête est comptée par hôte.
- **Plafond journalier** (``PlafondJour``) : indépendant des enquêtes, persistant entre redémarrages (table
  ``compteurs_jour`` du cache SQLite, jamais vidée par ``cache_purger``), partagé entre serveurs.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .http import SourceError

# Dimensions d'un budget d'enquête : 0 = illimité.
LIMITES = ("requetes_par_hote", "images", "duree_min", "cout_tokens")
CARACTERES_PAR_TOKEN = 4  # ordre de grandeur du coût d'une réponse texte pour le modèle

horloge: Callable[[], float] = time.monotonic  # remplaçable dans les tests


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
    debut: float = field(default_factory=lambda: horloge())
    refus: BudgetEpuise | None = None

    def duree(self) -> float:
        return max(0.0, horloge() - self.debut)


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


def tokens_texte(texte: str) -> int:
    return -(-len(texte) // CARACTERES_PAR_TOKEN)


# ---------------------------------------------------------------------------- plafond journalier

def secondes_avant_minuit(maintenant: datetime | None = None) -> float:
    n = maintenant or datetime.now()
    demain = datetime.combine(n.date() + timedelta(days=1), datetime.min.time())
    return round((demain - n).total_seconds(), 1)


class PlafondJour:
    """Plafond de requêtes par hôte et par jour (date locale) pour les hôtes des services d'archives.

    ``plafond`` = 0 désactive. Un hôte est concerné s'il est (ou est un sous-domaine d') un hôte du
    référentiel des services d'archives."""

    def __init__(self, cache, plafond: int, hotes: set[str] | frozenset[str],
                 jour: Callable[[], date] = date.today):
        self.cache = cache
        self.plafond = max(0, int(plafond or 0))
        self.hotes = frozenset(h.lower().removeprefix("www.") for h in hotes if h)
        self.jour = jour

    def concerne(self, hote: str) -> bool:
        h = (hote or "").lower().removeprefix("www.")
        return bool(self.plafond) and any(h == x or h.endswith("." + x) for x in self.hotes)

    def consommer(self, hote: str) -> None:
        """Compte une requête vers ``hote`` ; lève PlafondAtteint (sans compter) si le plafond est atteint."""
        if not self.concerne(hote):
            return
        n = self.cache.incrementer_jour(hote.lower(), self.jour().isoformat(), self.plafond)
        if n is None:
            raise PlafondAtteint(
                f"{hote} : plafond journalier de {self.plafond} requêtes atteint pour ce service d'archives "
                "(GENEALOGISTE_PLAFOND_JOUR_ARCHIVES) ; aucune requête envoyée. Reprendre demain ou consulter "
                "le registre dans le navigateur.", reessayer_apres=secondes_avant_minuit())

    def etat(self) -> dict:
        return {"plafond": self.plafond, "jour": self.jour().isoformat(),
                "consomme": self.cache.compteurs_jour(self.jour().isoformat())}
