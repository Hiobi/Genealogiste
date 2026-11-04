"""Propositions de modification : diff présenté → validation explicite → écriture.

Flux : proposer(ops) renvoie un diff et un jeton à usage unique ; appliquer(jeton) n'écrit que si
l'arbre n'a pas changé depuis (empreinte SHA-256 en mode fichier, état ``old`` des objets en mode Gramps)
et que le jeton n'a pas expiré. Le contenu écrit est exactement celui qui a été montré.
"""

from __future__ import annotations

import difflib
import json
import secrets
import time
from pathlib import Path

from ..coherence import check_tree
from ..gedcom.mapping import write_gedcom
from .ops import Ctx, OpError, apply_ops
from .store import TreeStore

TTL_SECONDS = 3600
MAX_DIFF_LINES = 400
CONSIGNE = "Présenter ce diff à l'utilisateur et n'appeler arbre_appliquer qu'après son accord explicite."


class ProposalError(RuntimeError):
    pass


class TokenStore:
    """Jetons de proposition (fichiers JSON dans <données>/.propositions, hors Git)."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)

    def _path(self, token: str) -> Path:
        if not token.isalnum():
            raise ProposalError("Jeton invalide")
        return self.dir / f"{token}.json"

    def create(self, record: dict) -> str:
        token = record.get("jeton") or secrets.token_hex(8)
        record.update(jeton=token, cree=time.time())
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path(token).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return token

    def take(self, token: str) -> dict:
        """Retire le jeton (usage unique, même si l'écriture échoue ensuite)."""
        path = self._path(token)
        if not path.exists():
            raise ProposalError("Jeton inconnu ou déjà utilisé.")
        record = json.loads(path.read_text(encoding="utf-8"))
        path.unlink()
        if time.time() - record["cree"] > TTL_SECONDS:
            raise ProposalError("Proposition expirée : la reformuler.")
        return record

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
            out.append({"jeton": r["jeton"], "type": r.get("type", "modification"), "resume": r.get("resume", []),
                        "age_minutes": round((time.time() - r["cree"]) / 60, 1)})
        return out


def new_token() -> str:
    return secrets.token_hex(8)


def tree_diff(before: str, after: str, label: str = "arbre.ged") -> str:
    diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(), f"{label} (actuel)",
                                     f"{label} (proposé)", lineterm="", n=2))
    truncated = len(diff) > MAX_DIFF_LINES
    return "\n".join(diff[:MAX_DIFF_LINES]) + ("\n… (diff tronqué)" if truncated else "")


def new_alerts(before_tree, after_tree) -> list[dict]:
    old = {(i["code"], i["message"]) for i in check_tree(before_tree)}
    return [i for i in check_tree(after_tree) if (i["code"], i["message"]) not in old]


def commit_message(ctx: Ctx, titre: str, justification: str, sources: list[str] | None, token: str) -> str:
    """Message de commit / de transaction : justification, opérations, sources, accord."""
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
    return (
        f"{titre.strip() or 'Modification de l arbre'}\n\n"
        f"Justification : {justification.strip()}\n\n"
        "Opérations :\n" + ("\n".join(f"- {s}" for s in ctx.summary) or "- (recalcul)") + "\n\n"
        "Sources :\n" + ("\n".join(src_lines) if src_lines else "- (aucune source citée : données non sourcées)")
    )


def validated(message: str, token: str) -> str:
    """Mention de l'accord, ajoutée seulement au moment de l'écriture (jamais dans l'aperçu de la proposition)."""
    return f"{message}\n\nValidé explicitement par l'utilisateur (proposition {token})"


def prepare(tree, operations: list[dict], titre: str, justification: str, sources: list[str] | None,
            exiger_source: bool) -> tuple[Ctx, str, str]:
    """Applique les opérations sur une copie : (contexte, jeton, message). Commun aux deux backends."""
    if not justification.strip():
        raise ProposalError("Justification obligatoire (raisonnement + sources).")
    try:
        ctx = apply_ops(tree, operations, exiger_source)
    except OpError as exc:
        raise ProposalError(str(exc)) from exc
    token = new_token()
    return ctx, token, commit_message(ctx, titre, justification, sources, token)


class Proposals:
    """Backend « fichier » : arbre GEDCOM 7 dans un dépôt Git, un commit par proposition validée."""

    name = "fichier"

    def __init__(self, store: TreeStore, directory: Path, exiger_source: bool = True):
        self.store = store
        self.tokens = TokenStore(directory)
        self.dir = self.tokens.dir
        self.exiger_source = exiger_source

    def _frozen(self) -> None:
        if self.store.frozen():
            raise ProposalError("Arbre figé : la bascule vers Gramps Web a eu lieu (BASCULE.json). L'arbre de "
                                "référence est dans Gramps Web : GENEALOGISTE_BACKEND=gramps.")

    def propose(self, operations: list[dict], titre: str, justification: str,
                sources: list[str] | None = None) -> dict:
        self._frozen()
        tree = self.store.load()
        before = self.store.text()
        ctx, token, message = prepare(tree, operations, titre, justification, sources, self.exiger_source)
        after = write_gedcom(ctx.tree)
        if after == before:
            raise ProposalError("La proposition ne modifie rien.")
        self.tokens.create({
            "jeton": token, "type": "modification", "empreinte_base": self.store.digest(), "resultat": after,
            "message": message, "operations": operations, "resume": ctx.summary, "references": ctx.refs})
        return {
            "jeton": token, "expire_dans_minutes": TTL_SECONDS // 60, "resume": ctx.summary,
            "references_creees": ctx.refs, "diff": tree_diff(before, after),
            "nouvelles_alertes_coherence": new_alerts(tree, ctx.tree), "avertissements": ctx.warnings,
            "message_de_commit": message, "consigne": CONSIGNE,
        }

    def propose_undo(self, reference: str) -> dict:
        """Annulation d'un commit (git revert) : même contrat, diff puis accord explicite."""
        self._frozen()
        entry = next((e for e in self.store.log(200, "arbre.ged") if e["commit"].startswith(reference)), None)
        if not entry or not reference:
            raise ProposalError(f"Commit introuvable dans l'historique de l'arbre : {reference!r}")
        diff = self.store.show(entry["commit"])
        token = self.tokens.create({"type": "annulation", "commit": entry["commit"],
                                    "empreinte_base": self.store.digest(),
                                    "resume": [f"Annulation du commit {entry['commit']} : "
                                               f"{entry['message'].splitlines()[0]}"]})
        return {"jeton": token, "expire_dans_minutes": TTL_SECONDS // 60, "annule": entry,
                "diff_annule": diff[:20000], "consigne": CONSIGNE}

    def apply(self, token: str) -> dict:
        record = self.tokens.take(token)
        self._frozen()
        if self.store.digest() != record["empreinte_base"]:
            raise ProposalError("L'arbre a changé depuis la proposition : la reformuler sur l'état actuel.")
        if record.get("type") == "annulation":
            commit = self.store.revert(record["commit"])
            return {"commit": commit, "resume": record["resume"]}
        self.store.path.write_text(record["resultat"], encoding="utf-8")
        commit = self.store.commit(validated(record["message"], token))
        return {"commit": commit, "resume": record["resume"], "references_creees": record["references"]}

    def cancel(self, token: str) -> bool:
        return self.tokens.cancel(token)

    def pending(self) -> list[dict]:
        return self.tokens.pending()

    def history(self, limit: int = 20) -> list[dict]:
        return self.store.log(limit)
