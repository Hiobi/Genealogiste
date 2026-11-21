"""Backend « gramps » : Gramps Web est la source de vérité, Sosa y écrit en direct par transactions.

Même contrat qu'en mode fichier : proposition -> diff -> accord explicite -> écriture.
- Session : chargement complet au premier besoin, puis rafraîchissement incrémental (au plus toutes les
  ``ttl`` secondes en lecture, toujours avant de proposer et d'appliquer). Preuve, cohérence, ascendance
  sont calculées localement sur l'arbre lu.
- Une proposition validée = une transaction atomique dont le message = justification + sources.
- Conflit (objet modifié dans l'interface depuis la proposition) : refus, rechargement, nouveau diff,
  nouvel accord ; jamais ``force``.
- Annulation : transaction inverse (``undo``) de la transaction enregistrée, après accord.
- Notes de preuve ``Genealogiste:auto`` (historique ``Sosa:auto``) recalculées à chaque écriture (et sur demande).
- Types personnalisés qui doublonnent un type standard normalisés par une transaction explicite
  (:meth:`GrampsBackend.propose_types`, #273).
- Marqueurs ``Sosa-*`` / ``Sosa:auto`` migrés vers ``Genealogiste-*`` / ``Genealogiste:auto`` par une transaction
  explicite (:meth:`GrampsBackend.propose_marqueurs`, #182).
- Journal local ``gramps-transactions.jsonl`` (pour l'annulation) ; miroir Git optionnel de l'arbre.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from ..chemins import CheminAmbigu, CheminRefuse, localiser
from ..etiquettes import lignes_arbres
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
    targets,
    tree_diff,
    validated,
)
from ..tree.store import TreeStore
from .client import ConflictError, GrampsClient, GrampsError
from .mapping import (
    A_FICHIER,
    GrampsDb,
    _attr_value,
    _strip_change,
    apply_items,
    dater_lieux,
    diff,
    est_commune,
    etiquettes_en_double,
    etiquettes_gerees,
    gramps_to_tree,
    liens_internes_changes,
    lignes_etiquettes,
    migrer_marqueurs,
    normaliser_types,
    proof_only,
    summarize,
    touched_keys,
    tree_to_gramps,
)

MAX_PREVIEW_OBJECTS = 40


def _racines_media(data_dir: Path, media_dir) -> tuple:
    """Racines d'un média : le répertoire de données puis media_dir (un dossier, ou la suite des racines de
    Config.media_racines après les données : répertoire des médias, arborescence des pièces)."""
    if media_dir is None:
        return (data_dir,)
    if isinstance(media_dir, (str, Path)):
        return (data_dir, Path(media_dir))
    return (data_dir, *media_dir)


def _local_media(local: str, data_dir: Path, media_dir=None) -> Path:
    """Fichier d'un média : confiné aux racines autorisées, résolu par la règle unique de chemins.localiser
    (#192, #193 : relatif essayé dans l'ordre, refusé s'il désigne des fichiers différents sous deux racines)."""
    return localiser(_racines_media(data_dir, media_dir), local)


def media_pending(db: GrampsDb, data_dir: Path, handles: set[str] | None = None,
                  media_dir=None) -> tuple[list[dict], list[str]]:
    """Fichiers locaux à envoyer (somme MD5 différente de celle de Gramps) et fichiers locaux absents."""
    todo, missing = [], []
    for h, m in sorted(db.all("Media").items()):
        if handles is not None and h not in handles:
            continue
        local = _attr_value(m, A_FICHIER) or m.get("path") or ""
        if local:
            try:
                p = _local_media(local, data_dir, media_dir)
            except CheminAmbigu as exc:
                missing.append(f"{m.get('gramps_id') or h} : {local} ({exc})")
                continue
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


def exiger_ecriture(client: GrampsClient) -> None:
    """Point commun des propositions et écritures : compte sans droit d'écriture refusé avant tout calcul (#265)."""
    try:
        client.exiger_ecriture()
    except GrampsError as exc:
        raise ProposalError(str(exc)) from exc


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
    transaction ; les modifications faites hors de Genealogiste sont commitées à la synchronisation suivante."""

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
                 clock=time.monotonic, notes_auto: str = "true", media_dir=None,
                 media=None, forme: str = "genealogiste", notes_liens: bool = False):
        self.notes_liens = notes_liens  # liens internes gramps:// dans les notes générées (#279)
        self.forme = forme  # forme écrite des marqueurs (GENEALOGISTE_MARQUEURS, #182)
        self.client = client
        self.media = media  # résolution des fichiers d'ajouter_media (Config.media_reference)
        # racines des médias après les données (dossier, ou suite de Config.media_racines : #193)
        self.media_dir = (Path(media_dir) if isinstance(media_dir, (str, Path)) else tuple(media_dir)) \
            if media_dir else None
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
        """Modifications constatées hors de Genealogiste : commitées dans le miroir Git à la synchronisation."""
        self._tree = None
        if self.mirror:
            self._tree = gramps_to_tree(self.db)[0]
            self.mirror.sync(self._tree, f"{title}\n\nÉtat de l'arbre Gramps Web constaté le {_now()} "
                             f"(modifications hors de Genealogiste : interface ou autre client) : "
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
            gerees = etiquettes_gerees(db, items)
            out["dont_notes_de_preuve_seules"] = sum(proof_only(i, gerees) for i in items)
            if lignes := lignes_etiquettes(db, items):  # #262 : une ligne par objet étiqueté
                out["etiquettes"] = lignes
        if liens := liens_internes_changes(items):  # #279 : notes dont les liens internes gramps:// changent
            out["liens_internes"] = liens
        return out

    @staticmethod
    def _doublons(db: GrampsDb, items: list[dict]) -> list[str]:
        """Avertissement : étiquette posée dont le nom est porté par plusieurs objets Tag de Gramps Web."""
        doubles = etiquettes_en_double(db)
        poses = {h for it in items if it["_class"] != "Tag" and it.get("new")
                 for h in set(it["new"].get("tag_list") or []) - set((it.get("old") or {}).get("tag_list") or [])}
        return [f"Étiquette « {nom} » présente {len(hs)} fois dans Gramps Web (handles {', '.join(hs)}) : la première "
                "dans l'ordre de priorité est utilisée ; rien n'est fusionné (à corriger dans Gramps Web si voulu)."
                for nom, hs in sorted(doubles.items()) if hs[0] in poses]

    def _massive(self, items: list[dict], preview: dict, n_ops: int) -> str:
        if len(items) <= MASSIVE_OBJECTS or n_ops >= MASSIVE_OPERATIONS:
            return ""
        proof = preview.get("dont_notes_de_preuve_seules", 0)
        return (f"Transaction massive : {len(items)} objets Gramps pour {n_ops} opération(s), dont {proof} portant "
                f"seulement sur des notes de preuve générées (Genealogiste:auto) et {len(items) - proof} réellement modifiés. "
                "Cause probable : première écriture sur cette base, recalcul global des notes de preuve ou "
                "changement de GENEALOGISTE_GRAMPS_NOTES_LIENS (liens internes ajoutés ou retirés par ce recalcul). "
                "Pour l'éviter : GENEALOGISTE_GRAMPS_NOTES_AUTO=modifies (recalcul limité aux objets touchés) "
                "ou false (aucune note générée).")

    def propose(self, operations: list[dict], titre: str, justification: str,
                sources: list[str] | None = None, all_notes: bool = False, structure: bool = False) -> dict:
        exiger_ecriture(self.client)  # avant la lecture de l'arbre et le calcul du diff
        db = self.snapshot(fresh=True)
        tree = self.load()
        ctx, token, message = prepare(tree, operations, titre, justification, sources, self.exiger_source,
                                      self.media)
        only = touched_keys(tree, ctx.tree) if self.notes_auto == "modifies" and not all_notes else None
        avis: list[str] = []
        new = tree_to_gramps(ctx.tree, base=db, strict=self.strict, generated=self.notes_auto != "false", only=only,
                             structure=structure, forme=self.forme, liens=self.notes_liens, recalcul=all_notes,
                             avis=avis)
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
        warnings = list(ctx.warnings) + avis + self._doublons(db, items)
        if w := self._massive(items, preview, len(operations)):
            warnings.append(w)
        self.tokens.create({"jeton": token, "type": "transaction", "items": items, "message": message,
                            "operations": operations, "resume": ctx.summary, "references": ctx.refs})
        return {
            "jeton": token, "expire_dans_minutes": TTL_SECONDS // 60, "resume": ctx.summary,
            "references_creees": ctx.refs, "transaction_gramps": preview,
            "diff": tree_diff(write_gedcom(tree), write_gedcom(ctx.tree), "Gramps Web", targets(ctx, operations),
                              lignes_arbres(tree, ctx.tree)),
            "nouvelles_alertes_coherence": new_alerts(tree, ctx.tree),
            "avertissements": warnings, "message_de_transaction": message, "consigne": CONSIGNE,
        }

    def propose_places(self) -> dict:
        """Lieux à plat (titre « Commune, Département, Pays ») rattachés à une hiérarchie Gramps (#11)."""
        return self.propose([], "Hiérarchie des lieux (commune → département → pays)",
                            "Lieux à plat rattachés à leurs lieux englobants, créés ou réutilisés ; les noms relus "
                            "sont identiques et aucun événement n'est modifié.",
                            structure=True)

    def propose_notes(self) -> dict:
        """Recalcul des notes de preuve générées (après des modifications faites dans l'interface)."""
        if self.notes_auto == "false":
            raise ProposalError("Notes de preuve générées désactivées (GENEALOGISTE_GRAMPS_NOTES_AUTO=false).")
        return self.propose([], "Recalcul des notes de preuve (Genealogiste:auto)",
                            "Notes et étiquettes de preuve générées recalculées sur l'état actuel de l'arbre ; "
                            "les notes manuelles ne sont pas touchées.", all_notes=True)

    def propose_marqueurs(self) -> dict:
        """Migration des marqueurs Sosa-* / Sosa:auto vers Genealogiste-* / Genealogiste:auto (#182) : une
        transaction (jeton, accord explicite, journalisée et annulable), sans changement d'identifiant ni de
        valeur. Renvoie {jeton?, bilan, objets, incoherences}."""
        exiger_ecriture(self.client)
        db = self.snapshot(fresh=True)
        items, incoherences = migrer_marqueurs(db)
        out: dict = {"incoherences": incoherences}
        if incoherences:
            out["incoherences_conseil"] = ("Objets portant le même marqueur sous les deux formes avec des valeurs "
                                           "différentes : la nouvelle forme est lue, l'ancienne est conservée "
                                           "intacte. Corriger à la main dans Gramps Web (garder la bonne valeur).")
        if not items:
            return out
        message = ("Migration des marqueurs Sosa → Genealogiste (#182)\n\nAttributs Sosa-* renommés en "
                   "Genealogiste-* et étiquette Sosa:auto en Genealogiste:auto ; valeurs, handles et identifiants "
                   "inchangés.")
        token = self.tokens.create({"type": "transaction", "marqueurs": True, "items": items, "message": message,
                                    "operations": [], "resume": ["Migration des marqueurs Sosa → Genealogiste"],
                                    "references": {}})
        return {**out, "jeton": token, "expire_dans_minutes": TTL_SECONDS // 60, **self._preview(items)}

    def propose_types(self, classes: list[str] | None = None) -> dict:
        """Normalisation des types personnalisés qui doublonnent un type standard (#273) : une transaction (jeton,
        accord explicite, journalisée et annulable) où seul le type change. Renvoie {jeton?, bilan_types, ambigus,
        transaction_gramps}. Sans rien à normaliser : pas de jeton."""
        exiger_ecriture(self.client)
        db = self.snapshot(fresh=True)
        try:
            items, bilan = normaliser_types(db, classes)
        except ValueError as exc:
            raise ProposalError(str(exc)) from exc
        out: dict = {"bilan_types": bilan["par_classe"], "ambigus": bilan["ambigus"]}
        if bilan["ambigus"]:
            out["ambigus_conseil"] = ("Libellés qui désignent plusieurs types standard (ex. « Officiant » : Celebrant "
                                      "ou Officiator) : laissés tels quels, jamais tranchés. Choisir le type dans "
                                      "Gramps Web si voulu.")
        if not items:
            out["note"] = "Rien à normaliser : aucun type personnalisé ne doublonne un type standard."
            return out
        n = sum(len(v) for v in bilan["par_classe"].values())
        message = (f"Normalisation des types personnalisés (#273)\n\n{n} libellé(s) personnalisé(s) remplacé(s) par "
                   "le type standard de Gramps qu'ils désignent ; seul le type change (handles, identifiants, "
                   "valeurs, citations et positions inchangés).")
        resume = [f"Normalisation des types : {cls} « {s} » -> {x['standard']} ({x['objets']} objet(s))"
                  for cls, v in sorted(bilan["par_classe"].items()) for s, x in sorted(v.items())]
        token = self.tokens.create({"type": "transaction", "items": items, "message": message, "operations": [],
                                    "resume": resume, "references": {}})
        return {**out, "jeton": token, "expire_dans_minutes": TTL_SECONDS // 60,
                "transaction_gramps": self._preview(items, db), "message_de_transaction": message,
                "consigne": CONSIGNE}

    def propose_place_history(self, chronologies, ignorer_non_dates: bool = False) -> dict:
        """Noms et rattachements datés des communes (#277) d'après le COG : ``chronologies(codes INSEE)`` renvoie
        l'enveloppe de :func:`sources.geo.chronologies` (requête journalisée). Une transaction (jeton, accord
        explicite, journalisée et annulable) ; événements et noms relus inchangés. Sans rien à dater : pas de jeton.
        COG injoignable : erreur, rien n'est préparé. Effet sur les événements sans date annoncé avant le jeton
        (``evenements_non_dates``, ``avertissement``) ; ``ignorer_non_dates`` : lieux concernés laissés hors de la
        proposition (``lieux_exclus``)."""
        exiger_ecriture(self.client)
        db = self.snapshot(fresh=True)
        codes = sorted({p["code"].strip() for p in db.all("Place").values() if est_commune(p)})
        if not codes:
            return {"communes_examinees": 0,
                    "note": "Aucune commune identifiée (code INSEE et type commune) : rien à dater, aucune requête."}
        env = chronologies(codes)
        if env.get("erreur"):
            raise ProposalError(f"COG injoignable : {env['erreur']} (journal {env.get('journal')}). Rien n'est "
                                "préparé ni écrit ; réessayer plus tard.")
        items, rapport = dater_lieux(db, {r["code_insee"]: r for r in env.get("resultats") or []},
                                     ignorer_non_dates)
        out: dict = {"communes_examinees": len(codes), "journal": env.get("journal"),
                     **{k: v for k, v in rapport.items() if v},
                     "nombre_evenements_non_dates": rapport["nombre_evenements_non_dates"]}
        if env.get("inconnus"):
            out["codes_inconnus_du_cog"] = env["inconnus"]
        if rapport["conflits"]:
            out["conflits_conseil"] = ("Nom ou rattachement déjà saisi sur la même période (ou nom du lieu différent "
                                       "du nom actuel du COG) : le lieu est laissé tel quel pour ce volet, rien "
                                       "n'est tranché. Corriger dans Gramps Web si voulu, puis relancer.")
        if not items:
            out["note"] = "Rien à dater : noms et rattachements déjà présents, ou aucun changement connu du COG."
            return out
        message = (f"Noms et rattachements datés des communes (#277)\n\nD'après le Code officiel géographique de "
                   f"l'INSEE (journal {env.get('journal')}) : noms anciens datés, nom principal et rattachement actuel "
                   "datés, anciens départements ; noms relus et événements inchangés.")
        resume = [f"Lieux datés (COG) : {x}" for x in rapport["lieux"]]
        token = self.tokens.create({"type": "transaction", "items": items, "message": message, "operations": [],
                                    "resume": resume, "references": {}})
        return {**out, "jeton": token, "expire_dans_minutes": TTL_SECONDS // 60,
                "transaction_gramps": self._preview(items, db), "message_de_transaction": message,
                "consigne": CONSIGNE}

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
        exiger_ecriture(self.client)  # avant de consommer le jeton : un refus de droits ne le brûle pas
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

    def media_checksums(self) -> dict[str, str]:
        """Somme MD5 connue de Gramps Web par identifiant de média (même règle d'identifiant que la lecture)."""
        return {o.get("gramps_id") or f"O{h}": o.get("checksum") or ""
                for h, o in self.snapshot(fresh=True).all("Media").items()}

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
        exiger_ecriture(self.client)
        self.recover()
        entry = next((e for e in reversed(self.transactions(1000)) if e["id"] == reference
                      and e["type"] == "transaction" and self._effective(e)), None)
        if not entry:
            raise ProposalError(f"Transaction inconnue dans gramps-transactions.jsonl : {reference!r}")
        if any(e.get("annule") == reference and self._effective(e) for e in self.transactions(1000)):
            raise ProposalError(f"La transaction {reference} a déjà été annulée.")
        db = self.snapshot(fresh=True)
        title = entry["message"].splitlines()[0] if entry.get("message") else reference
        message = f"Annulation : {title}\n\nAnnulation de la transaction {reference}"
        token = self.tokens.create({"type": "annulation", "annule": reference, "items": entry["items"],
                                    "message": message, "resume": [f"Annulation de {reference} : {title}"]})
        inverse = self._preview(entry["items"])
        rev = {"add": "delete", "delete": "add"}
        if lignes := lignes_etiquettes(db, [{**i, "type": rev.get(i["type"], "update"), "old": i.get("new"),
                                             "new": i.get("old")} for i in entry["items"]]):
            inverse["etiquettes"] = lignes  # étiquettes restaurées par l'annulation (#262)
        return {"jeton": token, "expire_dans_minutes": TTL_SECONDS // 60, "annule": {"id": reference, "titre": title},
                "transaction_inverse": inverse, "consigne": CONSIGNE}

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
                    generated: bool = True, forme: str = "genealogiste", liens: bool = False) -> dict:
    """Prépare l'envoi de l'arbre local complet dans un arbre Gramps Web vide (vivants inclus : instance
    privée). Après accord, Gramps Web devient la référence et arbre.ged est figé."""
    if store.frozen():
        raise ProposalError("Bascule déjà faite : " + json.dumps(store.frozen(), ensure_ascii=False))
    exiger_ecriture(client)
    check_tree(client, store.dir)
    remote = client.load_all()
    occupied = {c: n for c, n in remote.count().items() if c not in ("Tag",)}
    if occupied:
        raise ProposalError(f"L'arbre Gramps Web n'est pas vide ({occupied}) : la bascule exige un arbre vide "
                            "(pas de synchronisation bidirectionnelle).")
    tree = store.load()
    new = tree_to_gramps(tree, base=remote, strict=strict, generated=generated, forme=forme, liens=liens)
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


def bascule_apply(client: GrampsClient, store: TreeStore, tokens: TokenStore, token: str, media_dir=None) -> dict:
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
        written = client.transaction(record["items"], "Bascule depuis Genealogiste (arbre.ged)\n\n" + record["resume"][0])
    except GrampsError as exc:
        raise ProposalError(str(exc)) from exc
    info = {"date": _now(), "gramps_url": client.base.removesuffix("/api"), "objets": summarize(record["items"]),
            "transaction": token}
    commit = store.freeze(info)
    todo, _ = media_pending(client.load_all(), store.dir, None, media_dir)
    if todo:
        info["medias"] = media_upload(client, todo)
    log = Path(store.dir) / "gramps-transactions.jsonl"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": token, "type": "bascule", "date": info["date"], "message": "Bascule vers Gramps Web",
                             "items": written or record["items"]}, ensure_ascii=False) + "\n")
    return {"bascule": info, "commit": commit,
            "suite": "Redémarrer le serveur MCP avec GENEALOGISTE_BACKEND=gramps (variable d'environnement)."}
