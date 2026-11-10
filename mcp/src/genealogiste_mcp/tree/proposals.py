"""Propositions de modification : diff présenté → validation explicite → écriture.

Flux : proposer(ops) renvoie un diff et un jeton à usage unique ; appliquer(jeton) n'écrit que si
l'arbre n'a pas changé depuis (empreinte SHA-256 en mode fichier, état ``old`` des objets en mode Gramps)
et que le jeton n'a pas expiré. Le contenu écrit est exactement celui qui a été montré.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from ..coherence import check_tree
from ..fichiers import verrou
from ..gedcom.mapping import read_gedcom, write_gedcom
from .ops import Ctx, OpError, apply_ops
from .store import GitError, TreeStore

TTL_SECONDS = 3600
MAX_DIFF_LINES = 400
MAX_DIFF_LINE_CHARS = 300
_XREF = re.compile(r"@([^@\s]+)@")
CONSIGNE = "Présenter ce diff à l'utilisateur et n'appeler arbre_appliquer qu'après son accord explicite."


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
        """Retire le jeton (usage unique)."""
        record = self.peek(token)
        self.consume(token)
        return record

    def peek(self, token: str) -> dict:
        """Lit le jeton sans le consommer ; un jeton expiré est retiré."""
        path = self._path(token)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ProposalError("Jeton inconnu ou déjà utilisé.") from None
        if time.time() - record["cree"] > TTL_SECONDS:
            path.unlink(missing_ok=True)
            raise ProposalError("Proposition expirée : la reformuler.")
        return record

    def consume(self, token: str) -> None:
        """Consommation atomique : un seul appelant y parvient (le renommage échoue pour les autres)."""
        path = self._path(token)
        pris = path.with_suffix(f".pris-{os.getpid()}-{threading.get_ident()}")
        try:
            os.rename(path, pris)
        except FileNotFoundError:
            raise ProposalError("Jeton inconnu ou déjà utilisé.") from None
        pris.unlink(missing_ok=True)

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


def _records(text: str) -> dict[str, tuple[str, list[str]]]:
    """Enregistrements GEDCOM de niveau 0 : xref sans « @ » (ou étiquette : HEAD, TRLR) -> (type, lignes)."""
    out: dict[str, tuple[str, list[str]]] = {}
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("0 ") or not lines:
            parts = line.split()
            if len(parts) > 2 and parts[1].startswith("@"):
                key, kind = parts[1].strip("@"), parts[2]
            else:
                key = kind = parts[1] if len(parts) > 1 else line
            lines = []
            out[key] = (kind, lines)
        lines.append(line)
    return out


def _uids(lines: list[str]) -> set[str]:
    """UID des sous-structures (événements) : une opération peut viser un événement par son UID."""
    return {p[2] for p in (line.split(maxsplit=2) for line in lines) if len(p) == 3 and p[1] in ("UID", "_UID")}


def _cap(line: str) -> str:
    extra = len(line) - MAX_DIFF_LINE_CHARS
    return line if extra <= 0 else f"{line[:MAX_DIFF_LINE_CHARS]}… (+{extra} car.)"


def targets(ctx: Ctx, operations: list[dict]) -> set[str] | None:
    """Xrefs et UID visés : chaînes des opérations (« $x » résolues) et objets créés.
    None sans opération (recalcul global) : tout le diff est alors détaillé."""
    if not operations:
        return None
    out = {v.strip("@") for v in ctx.refs.values()}

    def walk(value) -> None:
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str):
            out.add(ctx.refs.get(value[1:], value) if value.startswith("$") else value.strip("@"))

    walk(operations)
    return out


def tree_diff(before: str, after: str, label: str = "arbre.ged", cibles: set[str] | None = None) -> str:
    """Diff par enregistrement de niveau 0 (contexte confiné à l'enregistrement).

    Avec ``cibles``, seuls sont détaillés les enregistrements visés, ceux qui contiennent un événement visé (UID)
    et ceux dont les lignes modifiées citent une cible (famille d'une personne fusionnée, citation d'une source
    visée). Les notes (NOTE, SNOTE) non visées sont seulement comptées et nommées ; les autres enregistrements
    modifiés tiennent sur une ligne ``+a/-b``.
    Sans ``cibles``, tout est détaillé. Chaque ligne est plafonnée à MAX_DIFF_LINE_CHARS caractères."""
    old, new = _records(before), _records(after)
    out = [f"--- {label} (actuel)", f"+++ {label} (proposé)"]
    notes: list[str] = []
    for key in list(new) + [k for k in old if k not in new]:
        kind = (new.get(key) or old[key])[0]
        b = old[key][1] if key in old else []
        a = new[key][1] if key in new else []
        if a == b:
            continue
        xref = f"@{key}@ {kind}" if kind != key else key
        changed = [h for h in difflib.unified_diff(b, a, lineterm="", n=0) if h[:1] in ("+", "-")][2:]
        cited = set(_XREF.findall("\n".join(changed)))
        if cibles is None or key in cibles or (_uids(a + b) | cited) & cibles:
            out.append(f"@@ {xref} @@")
            hunks = list(difflib.unified_diff(b, a, lineterm="", n=2))[3:]
            out += [" …" if h.startswith("@@") else _cap(h) for h in hunks]
        elif kind in ("NOTE", "SNOTE"):
            notes.append(f"@{key}@")
        else:
            plus = sum(h.startswith("+") for h in changed)
            out.append(f"@@ {xref} (hors cible, détail omis) : +{plus}/-{len(changed) - plus} @@")
    if notes:
        out.append(f"@@ {len(notes)} note(s) hors cible modifiée(s), contenu omis : {', '.join(notes)} @@")
    truncated = len(out) > MAX_DIFF_LINES
    return "\n".join(out[:MAX_DIFF_LINES]) + ("\n… (diff tronqué)" if truncated else "")


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
        before = self.store.text()  # un seul instantané : diff et empreinte portent sur le même état (#38)
        tree = read_gedcom(before)[0]
        ctx, token, message = prepare(tree, operations, titre, justification, sources, self.exiger_source)
        after = write_gedcom(ctx.tree)
        if after == before:
            raise ProposalError("La proposition ne modifie rien.")
        self.tokens.create({
            "jeton": token, "type": "modification", "empreinte_base": _digest(before), "resultat": after,
            "message": message, "operations": operations, "resume": ctx.summary, "references": ctx.refs})
        return {
            "jeton": token, "expire_dans_minutes": TTL_SECONDS // 60, "resume": ctx.summary,
            "references_creees": ctx.refs, "diff": tree_diff(before, after, cibles=targets(ctx, operations)),
            "nouvelles_alertes_coherence": new_alerts(tree, ctx.tree), "avertissements": ctx.warnings,
            "message_de_commit": message, "consigne": CONSIGNE,
        }

    def propose_undo(self, reference: str) -> dict:
        """Annulation d'un commit (git revert) : même contrat, diff puis accord explicite."""
        self._frozen()
        entry = next((e for e in self.store.log(200, "arbre.ged") if e["commit"].startswith(reference)), None)
        if not entry or not reference:
            raise ProposalError(f"Commit introuvable dans l'historique de l'arbre : {reference!r}")
        base = self.store.text()
        diff = self.store.show(entry["commit"])
        fichiers = self.store.files(entry["commit"])
        token = self.tokens.create({"type": "annulation", "commit": entry["commit"],
                                    "empreinte_base": _digest(base), "fichiers": fichiers,
                                    "resume": [f"Annulation du commit {entry['commit']} : "
                                               f"{entry['message'].splitlines()[0]}"]})
        out = {"jeton": token, "expire_dans_minutes": TTL_SECONDS // 60, "annule": entry,
               "fichiers_annules": fichiers, "diff_annule": diff[:20000], "consigne": CONSIGNE}
        autres = [f for f in fichiers if f != "arbre.ged"]
        if autres:
            out["attention"] = (f"L'annulation défait tout le commit, y compris {', '.join(autres)} "
                                "(voir diff_annule).")
        return out

    def apply(self, token: str) -> dict:
        """Sous verrou : vérification, écriture atomique, commit, puis seulement consommation du jeton (#38, #44).
        Si le commit échoue, l'arbre précédent est restauré et le jeton reste valable (reprise possible)."""
        with verrou(self.store.dir):
            record = self.tokens.peek(token)
            self._frozen()
            avant = self.store.text()
            if _digest(avant) != record["empreinte_base"]:
                self.tokens.consume(token)
                raise ProposalError("L'arbre a changé depuis la proposition : la reformuler sur l'état actuel.")
            if record.get("type") == "annulation":
                try:
                    commit = self.store.revert(record["commit"])
                except GitError as exc:
                    raise ProposalError(f"Annulation impossible ({exc}) : rien n'a changé, le jeton reste "
                                        "valable.") from exc
                self.tokens.consume(token)
                return {"commit": commit, "ecrit": True, "commite": True, "resume": record["resume"]}
            self.store.commit_internes()
            self.store.write_text(record["resultat"])
            try:
                commit = self.store.commit(validated(record["message"], token))
            except GitError as exc:
                self.store.write_text(avant)
                raise ProposalError(f"Échec du commit ({exc}) : arbre restauré à l'état précédent, jeton "
                                    "toujours valable ; corriger le dépôt Git puis relancer arbre_appliquer.") from exc
            self.tokens.consume(token)
        return {"commit": commit, "ecrit": True, "commite": True, "resume": record["resume"],
                "references_creees": record["references"]}

    def cancel(self, token: str) -> bool:
        return self.tokens.cancel(token)

    def pending(self) -> list[dict]:
        return self.tokens.pending()

    def history(self, limit: int = 20) -> list[dict]:
        return self.store.log(limit)
