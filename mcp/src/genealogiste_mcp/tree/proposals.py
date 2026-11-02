"""Propositions de modification : diff présenté → validation explicite → commit.

Flux : proposer(ops) renvoie un diff et un jeton à usage unique ; appliquer(jeton) n'écrit que si
l'arbre n'a pas changé depuis (empreinte SHA-256) et que le jeton n'a pas expiré. Le contenu écrit est
exactement celui qui a été montré.
"""

from __future__ import annotations

import difflib
import json
import secrets
import time
from pathlib import Path

from ..coherence import check_tree
from ..gedcom.mapping import write_gedcom
from .ops import OpError, apply_ops
from .store import TreeStore

TTL_SECONDS = 3600
MAX_DIFF_LINES = 400


class ProposalError(RuntimeError):
    pass


class Proposals:
    def __init__(self, store: TreeStore, directory: Path, exiger_source: bool = True):
        self.store = store
        self.dir = Path(directory)
        self.exiger_source = exiger_source

    def _path(self, token: str) -> Path:
        if not token.isalnum():
            raise ProposalError("Jeton invalide")
        return self.dir / f"{token}.json"

    def propose(self, operations: list[dict], titre: str, justification: str,
                sources: list[str] | None = None) -> dict:
        if not justification.strip():
            raise ProposalError("Justification obligatoire (raisonnement + sources).")
        tree = self.store.load()
        before = self.store.text()
        try:
            ctx = apply_ops(tree, operations, self.exiger_source)
        except OpError as exc:
            raise ProposalError(str(exc)) from exc
        after = write_gedcom(ctx.tree)
        if after == before:
            raise ProposalError("La proposition ne modifie rien.")
        diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(),
                                         "arbre.ged (actuel)", "arbre.ged (proposé)", lineterm="", n=2))
        old_issues = {(i["code"], i["message"]) for i in check_tree(tree)}
        new_issues = [i for i in check_tree(ctx.tree) if (i["code"], i["message"]) not in old_issues]
        cited = sorted(set(sources or []) | ctx.sources_cited)
        src_lines = []
        for sid in cited:
            s = ctx.tree.sources.get(sid)
            if s:
                repo = ctx.tree.depots.get(s.depot) if s.depot else None
                src_lines.append(f"- {sid} : " + ", ".join(x for x in (
                    (repo.sigle or repo.nom) if repo else "", s.cote, s.titre, s.url) if x))
            else:
                src_lines.append(f"- {sid}")
        token = secrets.token_hex(8)
        message = (
            f"{titre.strip() or 'Modification de l arbre'}\n\n"
            f"Justification : {justification.strip()}\n\n"
            "Opérations :\n" + "\n".join(f"- {s}" for s in ctx.summary) + "\n\n"
            "Sources :\n" + ("\n".join(src_lines) if src_lines else "- (aucune source citée : données non sourcées)")
            + f"\n\nValidé explicitement par l'utilisateur (proposition {token})"
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        record = {
            "jeton": token, "cree": time.time(), "empreinte_base": self.store.digest(),
            "resultat": after, "message": message, "operations": operations, "resume": ctx.summary,
            "references": ctx.refs,
        }
        self._path(token).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        truncated = len(diff) > MAX_DIFF_LINES
        return {
            "jeton": token,
            "expire_dans_minutes": TTL_SECONDS // 60,
            "resume": ctx.summary,
            "references_creees": ctx.refs,
            "diff": "\n".join(diff[:MAX_DIFF_LINES]) + ("\n… (diff tronqué)" if truncated else ""),
            "nouvelles_alertes_coherence": new_issues,
            "avertissements": ctx.warnings,
            "message_de_commit": message,
            "consigne": "Présenter ce diff à l'utilisateur et n'appeler arbre_appliquer qu'après son accord explicite.",
        }

    def apply(self, token: str) -> dict:
        path = self._path(token)
        if not path.exists():
            raise ProposalError("Jeton inconnu ou déjà utilisé.")
        record = json.loads(path.read_text(encoding="utf-8"))
        path.unlink()  # usage unique, même en cas d'échec ci-dessous
        if time.time() - record["cree"] > TTL_SECONDS:
            raise ProposalError("Proposition expirée : la reformuler.")
        if self.store.digest() != record["empreinte_base"]:
            raise ProposalError("L'arbre a changé depuis la proposition : la reformuler sur l'état actuel.")
        self.store.path.write_text(record["resultat"], encoding="utf-8")
        commit = self.store.commit(record["message"])
        return {"commit": commit, "resume": record["resume"], "references_creees": record["references"]}

    def cancel(self, token: str) -> bool:
        path = self._path(token)
        if path.exists():
            path.unlink()
            return True
        return False

    def pending(self) -> list[dict]:
        if not self.dir.exists():
            return []
        out = []
        for p in sorted(self.dir.glob("*.json")):
            r = json.loads(p.read_text(encoding="utf-8"))
            out.append({"jeton": r["jeton"], "resume": r["resume"],
                        "age_minutes": round((time.time() - r["cree"]) / 60, 1)})
        return out
