"""Backend « gramps » : Gramps Web est la source de vérité, Sosa y écrit en direct par transactions.

Même contrat qu'en mode fichier : proposition -> diff -> accord explicite -> écriture.
- Session : chargement complet au premier besoin, puis rafraîchissement incrémental (au plus toutes les
  ``ttl`` secondes en lecture, toujours avant de proposer et d'appliquer). Preuve, cohérence, ascendance
  sont calculées localement sur l'arbre lu.
- Une proposition validée = une transaction atomique dont le message = justification + sources.
- Conflit (objet modifié dans l'interface depuis la proposition) : refus, rechargement, nouveau diff,
  nouvel accord ; jamais ``force``.
- Annulation : transaction inverse (``undo``) de la transaction enregistrée, après accord.
- Notes de preuve ``Sosa:auto`` recalculées à chaque écriture (et sur demande).
- Journal local ``gramps-transactions.jsonl`` (pour l'annulation) ; miroir Git optionnel de l'arbre.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from ..gedcom.mapping import write_gedcom
from ..models import Tree
from ..tree.proposals import CONSIGNE, TTL_SECONDS, ProposalError, TokenStore, new_alerts, prepare, tree_diff
from ..tree.store import TreeStore
from .client import ConflictError, GrampsClient, GrampsError
from .mapping import GrampsDb, _strip_change, apply_items, diff, gramps_to_tree, summarize, tree_to_gramps

MAX_PREVIEW_OBJECTS = 40


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _label(item: dict) -> str:
    o = item.get("new") or item.get("old") or {}
    gid = o.get("gramps_id") or o.get("name") or item["handle"]
    return f"{item['type']} {item['_class']} {gid}"


class GitMirror:
    """Miroir Git optionnel : arbre Gramps exporté en GEDCOM 7 dans le dépôt des données, un commit par
    transaction ; les modifications faites hors de Sosa sont commitées à la synchronisation suivante."""

    def __init__(self, store: TreeStore):
        self.store = store

    def sync(self, tree: Tree, message: str) -> str:
        self.store.ensure()
        text = write_gedcom(tree)
        if self.store.path.read_text(encoding="utf-8") == text:
            return ""
        self.store.path.write_text(text, encoding="utf-8")
        return self.store.commit(message)


class GrampsBackend:
    name = "gramps"

    def __init__(self, client: GrampsClient, data_dir: Path, proposals_dir: Path, exiger_source: bool = True,
                 strict: bool = False, ttl: float = 30.0, mirror: GitMirror | None = None,
                 clock=time.monotonic):
        self.client = client
        self.tokens = TokenStore(proposals_dir)
        self.log_path = Path(data_dir) / "gramps-transactions.jsonl"
        self.exiger_source = exiger_source
        self.strict = strict
        self.ttl = ttl
        self.mirror = mirror
        self.clock = clock
        self.db: GrampsDb | None = None
        self._tree: Tree | None = None
        self._read_at = -1e18
        self.last_refresh: dict = {}

    # ------------------------------------------------------------------ lecture
    def snapshot(self, fresh: bool = True) -> GrampsDb:
        """Base Gramps de la session (chargée une fois, puis rafraîchie de façon incrémentale)."""
        if self.db is None:
            self.db = self.client.load_all()
            self._read_at = self.clock()
            self.last_refresh = {"chargement_complet": self.db.count()}
            self._changed("Miroir de Gramps Web (synchronisation)")
        elif fresh or self.clock() - self._read_at > self.ttl:
            self.db, report = self.client.refresh(self.db)
            self._read_at = self.clock()
            self.last_refresh = report
            if report:
                self._changed("Modifications externes (Gramps Web)")
        return self.db

    def _changed(self, title: str) -> None:
        """Modifications constatées hors de Sosa : commitées dans le miroir Git à la synchronisation."""
        self._tree = None
        if self.mirror:
            self.mirror.sync(self.load(fresh=False), f"{title}\n\nÉtat de l'arbre Gramps Web constaté le {_now()} "
                             f"(modifications hors de Sosa : interface ou autre client) : "
                             f"{json.dumps(self.last_refresh, ensure_ascii=False)}")

    def load(self, fresh: bool = False) -> Tree:
        db = self.snapshot(fresh=fresh)  # rafraîchie seulement si périmée (ttl) ou demandée
        if self._tree is None:
            self._tree = gramps_to_tree(db)[0]
        return self._tree

    def info(self) -> dict:
        return {"url": self.client.base.removesuffix("/api"), "objets": self.db.count() if self.db else None,
                "dernier_rafraichissement": self.last_refresh, "miroir_git": bool(self.mirror),
                "transactions_journalisees": len(self.transactions(1000))}

    # ------------------------------------------------------------------ propositions
    def _preview(self, items: list[dict]) -> dict:
        return {"bilan": summarize(items), "objets": [_label(i) for i in items[:MAX_PREVIEW_OBJECTS]]
                + ([f"… {len(items) - MAX_PREVIEW_OBJECTS} autre(s)"] if len(items) > MAX_PREVIEW_OBJECTS else [])}

    def propose(self, operations: list[dict], titre: str, justification: str,
                sources: list[str] | None = None) -> dict:
        db = self.snapshot(fresh=True)
        tree = self.load()
        ctx, token, message = prepare(tree, operations, titre, justification, sources, self.exiger_source)
        new = tree_to_gramps(ctx.tree, base=db, strict=self.strict)
        items = diff(db, new)
        if not items:
            raise ProposalError("La proposition ne modifie rien.")
        self.tokens.create({"jeton": token, "type": "transaction", "items": items, "message": message,
                            "operations": operations, "resume": ctx.summary, "references": ctx.refs})
        return {
            "jeton": token, "expire_dans_minutes": TTL_SECONDS // 60, "resume": ctx.summary,
            "references_creees": ctx.refs, "diff": tree_diff(write_gedcom(tree), write_gedcom(ctx.tree), "Gramps Web"),
            "transaction_gramps": self._preview(items), "nouvelles_alertes_coherence": new_alerts(tree, ctx.tree),
            "avertissements": ctx.warnings, "message_de_transaction": message, "consigne": CONSIGNE,
        }

    def propose_notes(self) -> dict:
        """Recalcul des notes de preuve Sosa:auto (après des modifications faites dans l'interface)."""
        return self.propose([], "Recalcul des notes de preuve (Sosa:auto)",
                            "Notes et étiquettes de preuve générées recalculées sur l'état actuel de l'arbre ; "
                            "les notes manuelles ne sont pas touchées.")

    def _check(self, db: GrampsDb, items: list[dict], side: str = "old") -> None:
        """Conflit si un objet a changé depuis la proposition (comparaison locale, puis par le serveur)."""
        for it in items:
            cur = db.get(it["_class"], it["handle"])
            want = it.get(side)
            if (cur is None) != (want is None) or (cur is not None and _strip_change(cur) != _strip_change(want)):
                raise ProposalError(
                    f"Conflit : {_label(it)} a été modifié dans Gramps Web depuis la proposition. "
                    "L'arbre a été rechargé : reformuler la proposition (nouveau diff, nouvel accord).")

    def _write(self, items: list[dict], message: str, undo: bool = False) -> list[dict]:
        try:
            written = self.client.transaction(items, message, undo=undo)
        except ConflictError as exc:
            self.snapshot(fresh=True)
            raise ProposalError(f"{exc} L'arbre a été rechargé.") from exc
        except GrampsError as exc:
            raise ProposalError(str(exc)) from exc
        self.db = apply_items(self.db, written if written else (
            items if not undo else [{"type": {"add": "delete", "delete": "add"}.get(i["type"], "update"),
                                     "_class": i["_class"], "handle": i["handle"], "old": i["new"], "new": i["old"]}
                                    for i in items]))
        self._tree = None
        return written or items

    def apply(self, token: str) -> dict:
        record = self.tokens.take(token)
        db = self.snapshot(fresh=True)
        kind = record.get("type")
        if kind == "annulation":
            self._check(db, record["items"], side="new")
            written = self._write(record["items"], record["message"], undo=True)
            self._log({"id": token, "type": "annulation", "annule": record["annule"], "message": record["message"],
                       "items": written})
            commit = self.mirror.sync(self.load(fresh=False), record["message"]) if self.mirror else ""
            return {"transaction": token, "annule": record["annule"], "objets": summarize(written),
                    "miroir_git": commit or None}
        if kind != "transaction":
            raise ProposalError("Jeton d'un autre type (bascule : utiliser gramps_bascule_appliquer).")
        self._check(db, record["items"])
        written = self._write(record["items"], record["message"])
        self._log({"id": token, "type": "transaction", "message": record["message"], "resume": record["resume"],
                   "items": written})
        commit = self.mirror.sync(self.load(fresh=False), record["message"]) if self.mirror else ""
        return {"transaction": token, "resume": record["resume"], "references_creees": record["references"],
                "objets": summarize(written), "miroir_git": commit or None}

    def propose_undo(self, reference: str) -> dict:
        entry = next((e for e in reversed(self.transactions(1000)) if e["id"] == reference
                      and e["type"] == "transaction"), None)
        if not entry:
            raise ProposalError(f"Transaction inconnue dans gramps-transactions.jsonl : {reference!r}")
        if any(e.get("annule") == reference for e in self.transactions(1000)):
            raise ProposalError(f"La transaction {reference} a déjà été annulée.")
        self.snapshot(fresh=True)
        title = entry["message"].splitlines()[0] if entry.get("message") else reference
        message = f"Annulation : {title}\n\nAnnulation de la transaction {reference}, validée explicitement."
        token = self.tokens.create({"type": "annulation", "annule": reference, "items": entry["items"],
                                    "message": message, "resume": [f"Annulation de {reference} : {title}"]})
        return {"jeton": token, "expire_dans_minutes": TTL_SECONDS // 60, "annule": {"id": reference, "titre": title},
                "transaction_inverse": self._preview(entry["items"]), "consigne": CONSIGNE}

    def cancel(self, token: str) -> bool:
        return self.tokens.cancel(token)

    def pending(self) -> list[dict]:
        return self.tokens.pending()

    # ------------------------------------------------------------------ journal des transactions
    def _log(self, entry: dict) -> None:
        entry["date"] = _now()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def transactions(self, limit: int = 20) -> list[dict]:
        if not self.log_path.exists():
            return []
        lines = [json.loads(x) for x in self.log_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return lines[-limit:]

    def history(self, limit: int = 20) -> list[dict]:
        out = []
        for e in reversed(self.transactions(limit)):
            out.append({"transaction": e["id"], "type": e["type"], "date": e["date"], "message": e.get("message", ""),
                        "objets": summarize(e.get("items", [])), "annule": e.get("annule")})
        return out


# ============================================================================ bascule fichier -> Gramps Web

def bascule_preview(client: GrampsClient, store: TreeStore, tokens: TokenStore, strict: bool) -> dict:
    """Prépare l'envoi de l'arbre local complet dans un arbre Gramps Web vide (vivants inclus : instance
    privée). Après accord, Gramps Web devient la référence et arbre.ged est figé."""
    if store.frozen():
        raise ProposalError("Bascule déjà faite : " + json.dumps(store.frozen(), ensure_ascii=False))
    remote = client.load_all()
    occupied = {c: n for c, n in remote.count().items() if c not in ("Tag",)}
    if occupied:
        raise ProposalError(f"L'arbre Gramps Web n'est pas vide ({occupied}) : la bascule exige un arbre vide "
                            "(pas de synchronisation bidirectionnelle).")
    tree = store.load()
    new = tree_to_gramps(tree, base=remote, strict=strict)
    items = diff(remote, new)
    if not items:
        raise ProposalError("Arbre local vide : rien à basculer.")
    token = tokens.create({"type": "bascule", "items": items, "empreinte_base": store.digest(),
                           "resume": [f"Bascule : {len(tree.personnes)} personnes, {len(tree.familles)} familles, "
                                      f"{len(tree.sources)} sources vers Gramps Web"]})
    return {"jeton": token, "expire_dans_minutes": TTL_SECONDS // 60, "personnes": len(tree.personnes),
            "familles": len(tree.familles), "sources": len(tree.sources), "objets_gramps": summarize(items),
            "apres": "Gramps Web devient l'arbre de référence ; arbre.ged est figé (dernier commit « Bascule vers "
                     "Gramps Web ») ; journal.jsonl reste local. Passer ensuite GENEALOGISTE_BACKEND=gramps.",
            "consigne": "Présenter ce bilan à l'utilisateur et n'appeler gramps_bascule_appliquer qu'après son "
                        "accord explicite."}


def bascule_apply(client: GrampsClient, store: TreeStore, tokens: TokenStore, token: str) -> dict:
    record = tokens.take(token)
    if record.get("type") != "bascule":
        raise ProposalError("Ce jeton n'est pas une bascule.")
    if store.digest() != record["empreinte_base"]:
        raise ProposalError("arbre.ged a changé depuis la proposition : refaire gramps_bascule_proposer.")
    remote = client.load_all()
    if any(n for c, n in remote.count().items() if c != "Tag"):
        raise ProposalError("L'arbre Gramps Web n'est plus vide : bascule refusée.")
    try:
        written = client.transaction(record["items"], "Bascule depuis Sosa (arbre.ged)\n\n" + record["resume"][0])
    except GrampsError as exc:
        raise ProposalError(str(exc)) from exc
    info = {"date": _now(), "gramps_url": client.base.removesuffix("/api"), "objets": summarize(record["items"]),
            "transaction": token}
    commit = store.freeze(info)
    log = Path(store.dir) / "gramps-transactions.jsonl"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": token, "type": "bascule", "date": info["date"], "message": "Bascule vers Gramps Web",
                             "items": written or record["items"]}, ensure_ascii=False) + "\n")
    return {"bascule": info, "commit": commit,
            "suite": "Redémarrer le serveur MCP avec GENEALOGISTE_BACKEND=gramps (variable d'environnement)."}
