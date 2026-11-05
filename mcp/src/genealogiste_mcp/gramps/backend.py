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

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from ..chemins import CheminRefuse, sous
from ..fichiers import ajouter_jsonl, lire_jsonl
from ..gedcom.mapping import write_gedcom
from ..models import Tree
from ..tree.proposals import (
    CONSIGNE,
    TTL_SECONDS,
    ProposalError,
    TokenStore,
    new_alerts,
    prepare,
    tree_diff,
    validated,
)
from ..tree.store import TreeStore
from .client import ConflictError, GrampsClient, GrampsError
from .mapping import (
    A_FICHIER,
    SOSA_AUTO,
    GrampsDb,
    _attr_value,
    _strip_change,
    apply_items,
    diff,
    gramps_to_tree,
    proof_only,
    summarize,
    touched_keys,
    tree_to_gramps,
)

MAX_PREVIEW_OBJECTS = 40


def _local_media(local: str, data_dir: Path, media_dir: Path | None) -> Path:
    """Fichier d'un média : confiné au répertoire de données ou au répertoire des médias configuré."""
    try:
        return sous(data_dir, local)
    except CheminRefuse:
        if media_dir is None:
            raise
        return sous(media_dir, local)


def media_pending(db: GrampsDb, data_dir: Path, handles: set[str] | None = None,
                  media_dir: Path | None = None) -> tuple[list[dict], list[str]]:
    """Fichiers locaux à envoyer (somme MD5 différente de celle de Gramps) et fichiers locaux absents."""
    todo, missing = [], []
    for h, m in sorted(db.all("Media").items()):
        if handles is not None and h not in handles:
            continue
        local = _attr_value(m, A_FICHIER) or m.get("path") or ""
        if local:
            try:
                p = _local_media(local, data_dir, media_dir)
            except CheminRefuse:
                missing.append(f"{m.get('gramps_id') or h} : {local} (hors du répertoire de données, refusé)")
                continue
        if not local or not p.is_file():
            if local and not m.get("checksum"):
                missing.append(f"{m.get('gramps_id') or h} : {local}")
            continue
        md5 = hashlib.md5(p.read_bytes()).hexdigest()
        if md5 != (m.get("checksum") or ""):
            todo.append({"handle": h, "id": m.get("gramps_id") or h, "fichier": local, "chemin": str(p),
                         "mime": m.get("mime") or "", "checksum": m.get("checksum") or "",
                         "taille_octets": p.stat().st_size})
    return todo, missing


def media_upload(client: GrampsClient, todo: list[dict]) -> dict:
    sent, errors = [], []
    for t in todo:
        try:
            client.upload_media(t["handle"], Path(t["chemin"]).read_bytes(), t["mime"], t["checksum"])
            sent.append(f"{t['id']} : {t['fichier']}")
        except (GrampsError, OSError) as exc:
            errors.append(f"{t['id']} : {exc}")
    return {"envoyes": sent, "erreurs": errors}


TREE_FILE = "GRAMPS_ARBRE.json"


def check_tree(client: GrampsClient, data_dir: Path) -> str:
    """Un répertoire de données = un arbre Gramps Web : l'arbre du compte est enregistré à la première connexion,
    puis tout autre arbre est refusé (journal, propositions, miroir Git et notes ne doivent jamais se mélanger)."""
    tree = client.tree()
    if not tree:
        return ""  # serveur qui n'indique pas l'arbre : rien à comparer
    path = Path(data_dir) / TREE_FILE
    if path.exists():
        known = json.loads(path.read_text(encoding="utf-8"))
        if known.get("tree") != tree:
            raise GrampsError(
                f"Ce répertoire de données ({data_dir}) appartient à l'arbre Gramps Web {known.get('tree')!r} "
                f"(compte {known.get('compte', '?')}), pas à l'arbre {tree!r} du compte {client._user!r}. Un arbre = "
                "un répertoire de données : définir un autre GENEALOGISTE_DATA_DIR pour cet arbre (docs/gramps-web.md, "
                f"« Plusieurs arbres »). Si le changement est voulu, supprimer {TREE_FILE} après avoir vérifié.")
        return tree
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tree": tree, "url": client.base.removesuffix("/api"), "compte": client._user,
                                "date": _now()}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return tree


MASSIVE_OBJECTS = 50  # au-delà, pour moins de MASSIVE_OPERATIONS opérations : avertissement explicite
MASSIVE_OPERATIONS = 5


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
        self.store.commit_internes()
        self.store.write_text(text)
        return self.store.commit(message)


class GrampsBackend:
    name = "gramps"

    def __init__(self, client: GrampsClient, data_dir: Path, proposals_dir: Path, exiger_source: bool = True,
                 strict: bool = False, ttl: float = 30.0, mirror: GitMirror | None = None,
                 clock=time.monotonic, notes_auto: str = "true", media_dir: Path | None = None):
        self.client = client
        self.media_dir = Path(media_dir) if media_dir else None
        self.tokens = TokenStore(proposals_dir)
        self.data_dir = Path(data_dir)
        self.log_path = self.data_dir / "gramps-transactions.jsonl"
        self.lignes_corrompues: list[int] = []
        self.exiger_source = exiger_source
        self.strict = strict
        self.ttl = ttl
        self.mirror = mirror
        self.clock = clock
        self.notes_auto = notes_auto  # true | modifies | false (GENEALOGISTE_GRAMPS_NOTES_AUTO)
        self.db: GrampsDb | None = None
        self._tree: Tree | None = None
        self._read_at = -1e18
        self.last_refresh: dict = {}

    # ------------------------------------------------------------------ lecture
    def snapshot(self, fresh: bool = True) -> GrampsDb:
        """Base Gramps de la session (chargée une fois, puis rafraîchie de façon incrémentale)."""
        if self.db is None:
            check_tree(self.client, self.data_dir)
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
    def _preview(self, items: list[dict], db: GrampsDb | None = None) -> dict:
        out = {"bilan": summarize(items), "objets": [_label(i) for i in items[:MAX_PREVIEW_OBJECTS]]
               + ([f"… {len(items) - MAX_PREVIEW_OBJECTS} autre(s)"] if len(items) > MAX_PREVIEW_OBJECTS else [])}
        if db is not None:
            auto_tags = {h for h, t in db.all("Tag").items() if t.get("name") == SOSA_AUTO}
            out["dont_notes_de_preuve_seules"] = sum(proof_only(i, auto_tags) for i in items)
        return out

    def _massive(self, items: list[dict], preview: dict, n_ops: int) -> str:
        if len(items) <= MASSIVE_OBJECTS or n_ops >= MASSIVE_OPERATIONS:
            return ""
        proof = preview.get("dont_notes_de_preuve_seules", 0)
        return (f"Transaction massive : {len(items)} objets Gramps pour {n_ops} opération(s), dont {proof} portant "
                f"seulement sur des notes de preuve générées (Sosa:auto) et {len(items) - proof} réellement modifiés. "
                "Cause probable : première écriture sur cette base ou recalcul global des notes de preuve. "
                "Pour l'éviter : GENEALOGISTE_GRAMPS_NOTES_AUTO=modifies (recalcul limité aux objets touchés) "
                "ou false (aucune note générée).")

    def propose(self, operations: list[dict], titre: str, justification: str,
                sources: list[str] | None = None, all_notes: bool = False, structure: bool = False) -> dict:
        db = self.snapshot(fresh=True)
        tree = self.load()
        ctx, token, message = prepare(tree, operations, titre, justification, sources, self.exiger_source)
        only = touched_keys(tree, ctx.tree) if self.notes_auto == "modifies" and not all_notes else None
        new = tree_to_gramps(ctx.tree, base=db, strict=self.strict, generated=self.notes_auto != "false", only=only,
                             structure=structure)
        items = diff(db, new)
        if not items:
            raise ProposalError("La proposition ne modifie rien.")
        preview = self._preview(items, db)
        medias = {i["handle"] for i in items if i["_class"] == "Media" and i["type"] != "delete"}
        if medias:
            todo, missing = media_pending(new, self.data_dir, medias, self.media_dir)
            preview["fichiers_a_envoyer"] = [f"{t['id']} : {t['fichier']} ({t['taille_octets']} octets)" for t in todo]
            if missing:
                preview["fichiers_absents"] = missing
        warnings = list(ctx.warnings)
        if w := self._massive(items, preview, len(operations)):
            warnings.append(w)
        self.tokens.create({"jeton": token, "type": "transaction", "items": items, "message": message,
                            "operations": operations, "resume": ctx.summary, "references": ctx.refs})
        return {
            "jeton": token, "expire_dans_minutes": TTL_SECONDS // 60, "resume": ctx.summary,
            "references_creees": ctx.refs, "diff": tree_diff(write_gedcom(tree), write_gedcom(ctx.tree), "Gramps Web"),
            "transaction_gramps": preview, "nouvelles_alertes_coherence": new_alerts(tree, ctx.tree),
            "avertissements": warnings, "message_de_transaction": message, "consigne": CONSIGNE,
        }

    def propose_places(self) -> dict:
        """Lieux à plat (titre « Commune, Département, Pays ») rattachés à une hiérarchie Gramps (#11)."""
        return self.propose([], "Hiérarchie des lieux (commune → département → pays)",
                            "Lieux à plat rattachés à leurs lieux englobants, créés ou réutilisés ; les noms relus "
                            "sont identiques et aucun événement n'est modifié.",
                            structure=True)

    def propose_notes(self) -> dict:
        """Recalcul des notes de preuve Sosa:auto (après des modifications faites dans l'interface)."""
        if self.notes_auto == "false":
            raise ProposalError("Notes de preuve générées désactivées (GENEALOGISTE_GRAMPS_NOTES_AUTO=false).")
        return self.propose([], "Recalcul des notes de preuve (Sosa:auto)",
                            "Notes et étiquettes de preuve générées recalculées sur l'état actuel de l'arbre ; "
                            "les notes manuelles ne sont pas touchées.", all_notes=True)

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
        """Journal d'intention (#49) : « intention » écrite AVANT l'envoi, « envoyee » dès la réponse du serveur,
        puis l'état des étapes complémentaires (médias, miroir Git). Une transaction acceptée par Gramps Web est
        donc toujours retrouvable pour l'annulation, même si la suite échoue ou si le processus s'arrête."""
        record = self.tokens.peek(token)
        kind = record.get("type")
        if kind not in ("annulation", "transaction"):
            raise ProposalError("Jeton d'un autre type (bascule : utiliser gramps_bascule_appliquer).")
        self.recover()
        db = self.snapshot(fresh=True)
        undo = kind == "annulation"
        try:
            self._check(db, record["items"], side="new" if undo else "old")
        except ProposalError:
            self.tokens.consume(token)
            raise
        message = (f"{record['message']}, validée explicitement par l'utilisateur (jeton {token})." if undo
                   else validated(record["message"], token))
        base = {"id": token, "type": kind, "message": message}
        if undo:
            base["annule"] = record["annule"]
        else:
            base["resume"] = record["resume"]
        self._log({**base, "etat": "intention", "items": record["items"]})
        self.tokens.consume(token)
        try:
            written = self._write(record["items"], message, undo=undo)
        except ProposalError as exc:
            self._log({"id": token, "etat": "refusee", "erreur": str(exc)})
            raise
        except BaseException as exc:  # réseau coupé, interruption : issue inconnue, reprise par recover()
            self._log({"id": token, "etat": "indeterminee", "erreur": str(exc)[:500]})
            raise
        self._log({"id": token, "etat": "envoyee", "items": written})
        out = {"transaction": token, "objets": summarize(written)}
        out.update({"annule": record["annule"]} if undo else
                   {"resume": record["resume"], "references_creees": record["references"]})
        etapes: dict[str, str] = {}
        if not undo:
            medias = {i["handle"] for i in written if i["_class"] == "Media" and i["type"] != "delete"}
            if medias:  # fichiers des médias de la proposition acceptée (annoncés dans fichiers_a_envoyer)
                try:
                    todo, _ = media_pending(self.db, self.data_dir, medias, self.media_dir)
                    if todo:
                        out["medias"] = media_upload(self.client, todo)
                        self._reload_media(todo)
                    etapes["medias"] = "ok"
                except Exception as exc:  # noqa: BLE001
                    etapes["medias"] = f"échec : {exc}"
        try:
            commit = self.mirror.sync(self.load(fresh=False), message) if self.mirror else ""
            out["miroir_git"] = commit or None
            etapes["miroir_git"] = "ok"
        except Exception as exc:  # noqa: BLE001
            out["miroir_git"] = None
            etapes["miroir_git"] = f"échec : {exc}"
        echecs = {k: v for k, v in etapes.items() if v != "ok"}
        self._log({"id": token, "etat": "terminee" if not echecs else "complements_en_echec", "etapes": etapes})
        if echecs:
            out["avertissement"] = ("Transaction enregistrée dans Gramps Web et journalisée (annulable), mais "
                                    f"étapes complémentaires en échec : {echecs}. Relancer : "
                                    "gramps_envoyer_medias / gramps_synchroniser.")
        return out

    def recover(self) -> list[dict]:
        """Reprise après interruption : chaque transaction restée « intention » ou « indeterminee » est comparée
        à l'état de Gramps Web (appliquée, non appliquée ou partielle) et son état est mis à jour."""
        pending = [e for e in self.transactions(10_000) if e.get("etat") in ("intention", "indeterminee")]
        if not pending:
            return []
        db = self.snapshot(fresh=True)
        out = []
        for e in pending:
            side = "old" if e["type"] == "annulation" else "new"
            other = "new" if side == "old" else "old"
            def same(it, key):
                cur = db.get(it["_class"], it["handle"])
                want = it.get(key)
                return (cur is None) == (want is None) and (cur is None or _strip_change(cur) == _strip_change(want))
            if all(same(it, side) for it in e.get("items", [])):
                etat = "envoyee"
            elif all(same(it, other) for it in e.get("items", [])):
                etat = "non_envoyee"
            else:
                etat = "partielle"
            self._log({"id": e["id"], "etat": etat, "reprise": True})
            out.append({"transaction": e["id"], "etat": etat})
        return out

    def _reload_media(self, todo: list[dict]) -> None:
        """Relit les médias envoyés : le serveur a changé somme et chemin, parfois dans la même seconde que la
        transaction (``change`` identique), ce que la relecture incrémentale ne verrait pas."""
        db = self.snapshot(fresh=True)
        for t in todo:
            obj = self.client.get("Media", t["handle"])
            if obj is not None:
                db.put(obj)
        self._tree = None

    def media_status(self) -> dict:
        todo, missing = media_pending(self.snapshot(fresh=True), self.data_dir, None, self.media_dir)
        return {"a_envoyer": [f"{t['id']} : {t['fichier']} ({t['taille_octets']} octets)" for t in todo],
                "absents_en_local": missing}

    def media_send(self) -> dict:
        todo, missing = media_pending(self.snapshot(fresh=True), self.data_dir, None, self.media_dir)
        if not todo:
            return {"envoyes": [], "erreurs": [], "absents_en_local": missing, "note": "Rien à envoyer."}
        out = media_upload(self.client, todo)
        self._reload_media(todo)
        return {**out, "absents_en_local": missing}

    def propose_undo(self, reference: str) -> dict:
        self.recover()
        entry = next((e for e in reversed(self.transactions(1000)) if e["id"] == reference
                      and e["type"] == "transaction" and self._effective(e)), None)
        if not entry:
            raise ProposalError(f"Transaction inconnue dans gramps-transactions.jsonl : {reference!r}")
        if any(e.get("annule") == reference and self._effective(e) for e in self.transactions(1000)):
            raise ProposalError(f"La transaction {reference} a déjà été annulée.")
        self.snapshot(fresh=True)
        title = entry["message"].splitlines()[0] if entry.get("message") else reference
        message = f"Annulation : {title}\n\nAnnulation de la transaction {reference}"
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
        ajouter_jsonl(self.log_path, entry)

    def transactions(self, limit: int = 20) -> list[dict]:
        """Transactions, une par identifiant : les lignes successives (intention, envoyee, terminee…) fusionnées."""
        lines, self.lignes_corrompues = lire_jsonl(self.log_path)
        merged: dict[str, dict] = {}
        for e in lines:
            merged.setdefault(e.get("id", ""), {}).update(e)
        return list(merged.values())[-limit:]

    @staticmethod
    def _effective(e: dict) -> bool:
        """Transaction réellement écrite dans Gramps Web (anciens journaux : sans état = écrite)."""
        return e.get("etat", "envoyee") in ("envoyee", "terminee", "complements_en_echec")

    def history(self, limit: int = 20) -> list[dict]:
        out = []
        for e in reversed(self.transactions(limit)):
            out.append({"transaction": e["id"], "type": e["type"], "date": e["date"], "message": e.get("message", ""),
                        "objets": summarize(e.get("items", [])), "annule": e.get("annule"),
                        "etat": e.get("etat", "envoyee"), **({"etapes": e["etapes"]} if e.get("etapes") else {})})
        return out


# ============================================================================ bascule fichier -> Gramps Web

def bascule_preview(client: GrampsClient, store: TreeStore, tokens: TokenStore, strict: bool,
                    generated: bool = True) -> dict:
    """Prépare l'envoi de l'arbre local complet dans un arbre Gramps Web vide (vivants inclus : instance
    privée). Après accord, Gramps Web devient la référence et arbre.ged est figé."""
    if store.frozen():
        raise ProposalError("Bascule déjà faite : " + json.dumps(store.frozen(), ensure_ascii=False))
    check_tree(client, store.dir)
    remote = client.load_all()
    occupied = {c: n for c, n in remote.count().items() if c not in ("Tag",)}
    if occupied:
        raise ProposalError(f"L'arbre Gramps Web n'est pas vide ({occupied}) : la bascule exige un arbre vide "
                            "(pas de synchronisation bidirectionnelle).")
    tree = store.load()
    new = tree_to_gramps(tree, base=remote, strict=strict, generated=generated)
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
    check_tree(client, store.dir)
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
    todo, _ = media_pending(client.load_all(), store.dir)
    if todo:
        info["medias"] = media_upload(client, todo)
    log = Path(store.dir) / "gramps-transactions.jsonl"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": token, "type": "bascule", "date": info["date"], "message": "Bascule vers Gramps Web",
                             "items": written or record["items"]}, ensure_ascii=False) + "\n")
    return {"bascule": info, "commit": commit,
            "suite": "Redémarrer le serveur MCP avec GENEALOGISTE_BACKEND=gramps (variable d'environnement)."}
