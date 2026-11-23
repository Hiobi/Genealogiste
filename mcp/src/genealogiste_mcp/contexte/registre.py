"""Registre des références consultées (#321) : seule définition de « référence résolue » du jalon M7.

Une Reference n'y entre que si sa notice a effectivement été récupérée par une requête du plugin : réponse HTTP
2xx dont le corps contient l'identifiant (ou, pour un identifiant ``url``, URL égale à la requête émise). Chaque
entrée garde le service, la requête et la date de consultation. Les outils de contexte inscrivent ce qu'ils
renvoient ; ``contexte_local``, la rédaction et le vérificateur n'acceptent qu'une source dont
``est_consultee(identifiant)`` est vrai.

Stockage : ``<données>/references-consultees.jsonl`` (``Config.references_consultees_path``), une ligne JSON par
consultation, la dernière l'emportant. Le fichier est hors du cache SQLite : ``cache_purger`` ne le touche jamais.
Écritures verrouillées entre processus (plusieurs serveurs sur les mêmes données), lignes corrompues ignorées.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

from ..fichiers import ajouter_jsonl, lire_jsonl, verrou
from .modeles import Identifiant, Reference, ReferenceInvalide

VERROU = ".references.lock"


class NonConsultee(ValueError):
    """La réponse ne prouve pas que la notice a été récupérée : rien n'est inscrit au registre."""


def _texte_reponse(reponse) -> str:
    if isinstance(reponse, bytes):
        reponse = reponse.decode("utf-8", errors="replace")
    elif not isinstance(reponse, str):
        reponse = json.dumps(reponse, ensure_ascii=False)
    t = reponse.replace("\\/", "/").casefold()
    return t + "\n" + unquote(t)


def identifiant_dans_reponse(ident: Identifiant, reponse, requete: str = "") -> bool:
    """Vrai si ``reponse`` (texte, octets ou objet JSON) contient l'identifiant normalisé (sans casse, barres
    obliques JSON échappées ou encodage d'URL acceptés), ou si un identifiant ``url`` est la requête elle-même."""
    if ident.type == "url" and requete.strip() == ident.valeur:
        return True
    return ident.valeur.casefold() in _texte_reponse(reponse)


def _ident(identifiant: Identifiant | str) -> Identifiant | None:
    if isinstance(identifiant, Identifiant):
        return identifiant
    try:
        return Identifiant.depuis_cle(identifiant)
    except ReferenceInvalide:
        return Identifiant.depuis_texte(identifiant)


class RegistreReferences:
    """Registre persistant des références consultées.

    API : ``enregistrer(reference, statut=, reponse=)``, ``est_consultee(identifiant) -> bool``,
    ``lire(identifiant) -> Reference | None``, ``lister() -> list[Reference]``. ``identifiant`` : un
    ``Identifiant``, sa clé (« doi:10.… ») ou une forme libre reconnue par ``Identifiant.depuis_texte``."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.lignes_corrompues: list[int] = []  # lignes JSON illisibles (numéros), à la dernière lecture
        self.entrees_invalides = 0  # lignes JSON lisibles mais non conformes au format, à la dernière lecture

    def enregistrer(self, reference: Reference, *, statut: int, reponse) -> Reference:
        """Inscrit ``reference`` après contrôle de la consultation : ``statut`` HTTP 2xx et identifiant présent
        dans ``reponse`` (corps reçu). ``service``, ``requete`` et ``consulte_le`` sont obligatoires. Lève
        ``NonConsultee`` (preuve insuffisante) ou ``ReferenceInvalide`` (trace incomplète) sans rien écrire."""
        if not isinstance(reference, Reference):
            raise ReferenceInvalide("Reference attendue")
        for champ in ("service", "requete", "consulte_le"):
            if not getattr(reference, champ):
                raise ReferenceInvalide(f"{champ} manquant : la trace de consultation est obligatoire")
        if not isinstance(statut, int) or not 200 <= statut < 300:
            raise NonConsultee(f"réponse HTTP {statut} : seule une réponse 2xx prouve la consultation")
        if not identifiant_dans_reponse(reference.identifiant, reponse, reference.requete):
            raise NonConsultee(f"identifiant {reference.identifiant.cle} absent de la réponse : notice non "
                               "récupérée, référence non inscrite")
        entree = {"cle": reference.identifiant.cle, "statut": statut,
                  "enregistre_le": datetime.now(UTC).isoformat(timespec="seconds"),
                  "reference": reference.to_dict()}
        with self._lock, verrou(self.path.parent, VERROU):
            ajouter_jsonl(self.path, entree)
        return reference

    def _index(self) -> dict[str, Reference]:
        lignes, self.lignes_corrompues = lire_jsonl(self.path)
        self.entrees_invalides = 0
        index: dict[str, Reference] = {}
        for e in lignes:
            try:
                ref = Reference.from_dict(e["reference"])
            except (KeyError, TypeError, ReferenceInvalide):
                self.entrees_invalides += 1
                continue
            index.pop(ref.identifiant.cle, None)  # dernière consultation en fin d'ordre
            index[ref.identifiant.cle] = ref
        return index

    def lire(self, identifiant: Identifiant | str) -> Reference | None:
        """Dernière consultation de la référence, ou None si elle n'a jamais été consultée. Une forme libre sans
        type explicite (« 10.… », « hal-… ») est cherchée parmi tous les types."""
        ident = _ident(identifiant)
        index = self._index()
        if ident is not None and ident.cle in index:
            return index[ident.cle]
        valeur = (ident.valeur if ident else str(identifiant or "").strip()).casefold()
        if not valeur:
            return None
        return next((r for r in reversed(index.values()) if r.identifiant.valeur.casefold() == valeur), None)

    def est_consultee(self, identifiant: Identifiant | str) -> bool:
        """Vrai si la notice de cet identifiant a été récupérée par le plugin (définition unique de « résolue »)."""
        return self.lire(identifiant) is not None

    def lister(self) -> list[Reference]:
        """Références consultées, une par identifiant (dernière consultation), dans l'ordre de consultation."""
        return list(self._index().values())
