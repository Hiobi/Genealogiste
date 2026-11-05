"""Notes de recherche Markdown (Obsidian / LLM) dans GENEALOGISTE_NOTES_DIR.

Une fiche par personne, famille, source et patronyme (#61), plus ``index.md``. Chaque fiche a :
- un frontmatter YAML typé (Dataview / Bases) ; les clés ajoutées à la main sont conservées ;
- des sections générées entre ``<!-- sosa:debut NOM -->`` et ``<!-- sosa:fin -->``, régénérables ;
- une section « Notes libres » que l'outil ne modifie jamais (sauf ``notes_ajouter``, sur demande).

Les notes restent un espace de travail : rien n'est écrit dans l'arbre depuis les notes.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import quote

from .evidence import assess_person
from .export.charts import _years, ancestors
from .export.fiche import _fmt_date
from .models import EVENT_LABELS, Tree
from .normalize.dates import parse_date
from .normalize.names import normalize_surname
from .pieces import _part, _personne, lire_nom
from .privacy import is_living
from .statuts import GRAVITE, ICONS
from .statuts import LABELS as LABEL

START = "<!-- sosa:debut {} -->"
END = "<!-- sosa:fin -->"
FREE = "## Notes libres"
FREE_HINT = "<!-- Texte libre : jamais modifié par l'outil (hypothèses, réflexions, à faire). -->"
FOLDERS = {"personne": "personnes", "famille": "familles", "source": "sources", "patronyme": "patronymes"}
METHODS = {"personne": "person", "famille": "family", "source": "source", "patronyme": "surname"}
SECTIONS = {"hypothese": "Hypothèses", "piste": "Pistes", "conclusion": "Conclusions", "courrier": "Courriers",
            "a_faire": "À faire", "note": "Notes"}
RANK = GRAVITE
_BAD = re.compile(r'[\\/:*?"<>|#^\[\]]+')
_BLOCK = re.compile(r"<!-- sosa:debut (?P<name>[\w-]+) -->\n.*?<!-- sosa:fin -->", re.S)


# Clés de frontmatter produites par le générateur (toutes catégories) : toujours remplacées ou retirées, jamais
# conservées comme « manuelles » (sinon un remasquage laisserait nom et dates d'un vivant, #36).
GENERATED_KEYS = {"id", "type", "nom", "statut", "sosa", "naissance", "deces", "lieux", "sources", "journal", "vivant",
                  "epoux", "epouse", "mariage", "titre", "depot", "cote", "url", "nature", "cite_par", "personnes",
                  "familles", "mis_a_jour", "patronyme", "variantes", "berceau"}


class NotesError(RuntimeError):
    pass


def _safe(text: str, limit: int = 80) -> str:
    s = _BAD.sub(" ", text).replace(".", " ").strip()
    return re.sub(r"\s+", " ", s)[:limit].strip()


def patronyme(p) -> str:
    """Clé du patronyme : celle des dossiers de pièces (``documents/<type>/<NOM>/``, docs/pieces.md)."""
    return _part(p.nom_principal.nom).upper()


def _yaml(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_yaml(v) for v in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


def _frontmatter(fields: dict, keep: list[str]) -> str:
    lines = [f"{k}: {_yaml(v)}" for k, v in fields.items()]
    return "---\n" + "\n".join(lines + keep) + "\n---\n"


def _split(text: str) -> tuple[list[str], str]:
    """(lignes du frontmatter, corps)."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[4:end].splitlines(), text[end + 5:]
    return [], text


def _manual_keys(lines: list[str], generated: set[str]) -> list[str]:
    """Lignes du frontmatter dont la clé n'est pas générée (ajouts manuels), avec leurs continuations."""
    out, keep = [], False
    for line in lines:
        m = re.match(r"^([^\s:#][^:]*):", line)
        if m:
            keep = m.group(1).strip() not in generated
        if keep:
            out.append(line)
    return out


class Notes:
    def __init__(self, directory: Path | None, vivants: str = "masquer", strict: bool = False,
                 sosa_racine: str = "", journal=None, today=date.today, data_dir: Path | None = None):
        self.dir = Path(directory).expanduser() if directory else None
        self.data_dir = Path(data_dir) if data_dir else None
        self.vivants = vivants
        self.strict = strict
        self.sosa_racine = sosa_racine
        self.journal = journal
        self.today = today

    # ------------------------------------------------------------------ noms de fichiers et liens
    def enabled(self) -> bool:
        return self.dir is not None

    def _require(self) -> Path:
        if not self.dir:
            raise NotesError("Notes désactivées : définir GENEALOGISTE_NOTES_DIR (par exemple un vault Obsidian).")
        return self.dir

    def _masked(self, tree: Tree, pid: str) -> bool:
        p = tree.personnes[pid]
        return p.prive or (self.vivants != "complet" and is_living(tree, p)["vivant"])

    def _existing(self, kind: str, oid: str) -> Path | None:
        folder = self._require() / FOLDERS[kind]
        hits = sorted(folder.glob(f"{oid} - *.md")) if folder.exists() else []
        return hits[0] if hits else None

    def name(self, tree: Tree, kind: str, oid: str) -> str:
        """Nom de fichier stable (sans .md) : le fichier existant est réutilisé même si le libellé change."""
        if kind == "patronyme":
            return _safe(oid, 120)
        hit = self._existing(kind, oid)
        return hit.stem if hit else self.fresh_name(tree, kind, oid)

    def fresh_name(self, tree: Tree, kind: str, oid: str) -> str:
        """Nom qu'aurait un fichier créé maintenant (sans tenir compte de l'existant)."""
        if kind == "patronyme":
            return _safe(oid, 120)
        if kind == "personne":
            p = tree.personnes[oid]
            if self._masked(tree, oid):
                return f"{oid} - personne vivante"
            years = _years(tree, oid).replace("–", "-")
            label = p.nom_principal.complet or "(sans nom)"
            return _safe(f"{oid} - {label}" + (f" ({years})" if years else ""), 120)
        if kind == "famille":
            f = tree.familles[oid]
            sides = []
            for x, unknown in ((f.epoux, "inconnu"), (f.epouse, "inconnue")):
                if x and x in tree.personnes and self._masked(tree, x):
                    sides.append("vivant")
                elif x and x in tree.personnes:
                    sides.append(tree.personnes[x].nom_principal.nom.upper() or unknown)
                else:
                    sides.append(unknown)
            return _safe(f"{oid} - {' × '.join(sides)}", 120)
        s = tree.sources[oid]
        return _safe(f"{oid} - {s.titre or 'source'}", 120)

    def link(self, tree: Tree, kind: str, oid: str, label: str = "") -> str:
        n = self.name(tree, kind, oid)
        return f"[[{n}|{label}]]" if label else f"[[{n}]]"

    def path(self, tree: Tree, kind: str, oid: str) -> Path:
        return self._require() / FOLDERS[kind] / f"{self.name(tree, kind, oid)}.md"

    # ------------------------------------------------------------------ contenu généré
    def _sosa(self, tree: Tree) -> dict[str, int]:
        if not self.sosa_racine or self.sosa_racine not in tree.personnes:
            return {}
        out: dict[str, int] = {}
        for r in ancestors(tree, self.sosa_racine, 30):
            out.setdefault(r["id"], r["sosa"])
        return out

    def _journal(self, pid: str) -> list[dict]:
        return self.journal.entries(personne=pid, limite=200) if self.journal else []

    def person(self, tree: Tree, pid: str, sosa: dict[str, int]) -> tuple[dict, dict[str, str], str]:
        """(frontmatter, blocs, titre) d'une personne."""
        p = tree.personnes[pid]
        if self._masked(tree, pid):
            return ({"id": pid, "type": "personne", "vivant": True},
                    {"identite": "Personne présumée vivante : fiche masquée (RGPD). "
                                 "GENEALOGISTE_NOTES_VIVANTS=complet pour l'afficher."},
                    f"{pid} (personne vivante)")
        facts = assess_person(tree, pid, self.strict)
        father, mother = tree.father_mother(pid)
        ident = [f"- **Sexe** : {({'M': 'masculin', 'F': 'féminin'}).get(p.sexe, 'inconnu')}"]
        pat = patronyme(p)
        if pat and _safe(pat):
            ident.append(f"- **Patronyme** : [[{_safe(pat, 120)}]]")
        ident += [f"- **Autre nom** : {n.complet}" for n in p.noms[1:]]
        for role, x in (("Père", father), ("Mère", mother)):
            if x and x in tree.personnes:
                ident.append(f"- **{role}** : {self.link(tree, 'personne', x)}")
        for fid in p.famc:
            if fid in tree.familles:
                ident.append(f"- **Famille d'origine** : {self.link(tree, 'famille', fid)}")
        for fam in tree.spouses_families(pid):
            sp = fam.epouse if fam.epoux == pid else fam.epoux
            who = self.link(tree, "personne", sp) if sp in tree.personnes else "conjoint inconnu"
            kids = [self.link(tree, "personne", c.enfant) for c in fam.enfants if c.enfant in tree.personnes]
            ident.append(f"- **Union** {self.link(tree, 'famille', fam.id)} avec {who}"
                         + (f" ; enfants : {', '.join(kids)}" if kids else ""))
        rows = ["| Fait | Date | Lieu | Statut | Sources indépendantes |", "|---|---|---|---|---|"]
        todo: list[str] = []
        for f in facts:
            kind = f["fait"]
            label = {"nom": "Nom", "filiation": "Filiation"}.get(kind, EVENT_LABELS.get(kind, kind).capitalize())
            val = f.get("valeur") or ""
            if kind in ("nom", "OCCU", "EVEN") and val:
                label = f"{label} {val}"
            rows.append(f"| {label} | {_fmt_date(f.get('date', ''))} | {f.get('lieu', '')} | "
                        f"{ICONS[f['statut']]} {LABEL[f['statut']]} | {f['sources_independantes']} ({f['points']} pt) |")
            if f.get("prochaine_source"):
                first = f["prochaine_source"][0]
                todo.append(f"- {label} ({LABEL[f['statut']]}) → {first['source']} [{first['cote_typique']}]")
        filiation = {c.source for fam, link in tree.parents(pid) for c in link.citations}
        srcs = sorted({c.source for e in p.evenements for c in e.citations} | filiation
                      | {c.source for n in p.noms for c in n.citations} | {c.source for c in p.citations})
        src_links = [self.link(tree, "source", s) for s in srcs if s in tree.sources]
        jr = self._journal(pid)
        research = [f"- {e['date'][:10]} · {e['source']} · {e['operation']} · {e['statut']}"
                    + (f" — {e['resume'][:200]}" if e.get("resume") else "") + f" (`{e['id']}`)" for e in jr]
        essentials = [f["statut"] for f in facts if f["fait"] in ("BIRT", "DEAT", "filiation")]
        birth = next((e for e in p.evenements if e.type in ("BIRT", "CHR", "BAPM")), None)
        death = next((e for e in p.evenements if e.type in ("DEAT", "BURI")), None)
        places = sorted({e.lieu.nom for e in p.evenements if e.lieu and e.lieu.nom})
        fm = {"id": pid, "type": "personne", "nom": p.nom_principal.complet, "patronyme": pat,
              "statut": min(essentials, key=lambda s: RANK.get(s, 9)) if essentials else "non_source",
              "sosa": sosa.get(pid), "naissance": birth.date if birth else "", "deces": death.date if death else "",
              "lieux": places, "sources": src_links, "journal": [e["id"] for e in jr], "vivant": False}
        blocks = {"identite": "\n".join(ident), "faits": "## Faits et statut de preuve\n\n" + "\n".join(rows),
                  "pieces": "## Pièces\n\n" + ("\n\n".join(self._pieces(tree, pid)) or "- (aucune)"),
                  "sources": "## Sources\n\n" + ("\n".join(f"- {x}" for x in src_links) or "- (aucune)"),
                  "prochaines": "## Prochaines sources\n\n" + ("\n".join(dict.fromkeys(todo)) or "- (aucune)"),
                  "recherches": "## Recherches (journal)\n\n" + ("\n".join(research) or "- (aucune)")}
        return fm, blocks, p.label()

    def _pieces(self, tree: Tree, pid: str) -> list[str]:
        """Médias de la personne, de ses noms, faits et citations (et des unions) : image affichée et lien vers la
        note de la pièce (vue graphique d'Obsidian) ; hors du vault, chemin seulement (#70)."""
        p = tree.personnes[pid]
        from .tree.integrite import iter_citations

        ids = list(p.medias)
        owners = [p, *tree.spouses_families(pid)]
        for o in owners:
            ids += [m for c in iter_citations(o) for m in c.medias]
        out = []
        racine = self._require().resolve()
        for mid in dict.fromkeys(ids):
            m = tree.medias.get(mid)
            if not m or not m.fichier:
                continue
            f = Path(m.fichier).expanduser()
            if not f.is_absolute() and self.data_dir:
                f = self.data_dir / f
            f = f.resolve()
            titre = m.titre or f.stem
            if not f.is_relative_to(racine):
                out.append(f"- {titre} : `{m.fichier}` (hors du vault)")
                continue
            rel = f.relative_to(racine).as_posix()
            ligne = f"![[{rel}]]"
            note = f.with_suffix(".md")
            if note.exists() and note != f:
                ligne += f"\n[[{note.relative_to(racine).with_suffix('').as_posix()}|{titre}]]"
            else:
                ligne += f"\n{titre}"
            out.append(ligne)
        return out

    def _porteurs(self, tree: Tree) -> dict[str, list[str]]:
        """Patronyme -> personnes affichables qui le portent (nom principal) ; personnes masquées exclues."""
        out: dict[str, list[str]] = {}
        for pid in sorted(tree.personnes):
            pat = patronyme(tree.personnes[pid])
            if pat and _safe(pat) and not self._masked(tree, pid):
                out.setdefault(pat, []).append(pid)
        return out

    def surname(self, tree: Tree, key: str, porteurs: dict[str, list[str]]) -> tuple[dict, dict[str, str], str]:
        """(frontmatter, blocs, titre) d'un patronyme : personnes, variantes, berceau, pièces, requête Dataview."""
        pids = porteurs.get(key, [])
        if not pids:
            return ({"type": "patronyme", "nom": key, "personnes": 0},
                    {"personnes": "Aucune personne affichable (personnes présumées vivantes ou privées masquées)."},
                    key)

        def naissance(pid):
            e = next(iter(tree.personnes[pid].events("BIRT", "CHR", "BAPM")), None)
            g = parse_date(e.date) if e else None
            return (g.start.bounds()[0] if g and g.start else float("inf"), pid)  # année déclarée

        pids = sorted(pids, key=naissance)
        gens = [f"- {self.link(tree, 'personne', x)}" for x in pids]
        variantes: set[str] = set()
        for x in pids:
            p = tree.personnes[x]
            variantes |= {_part(n.nom).upper() for n in p.noms[1:] if n.nom}
            variantes |= {_part(n.surnom).upper() for n in p.noms if n.surnom}
            variantes |= set(normalize_surname(p.nom_principal.nom)["dit"])
        variantes.discard(key)
        variantes.discard("")
        phon = normalize_surname(key)["phonetique"]
        proches = sorted(k for k in porteurs if k != key and phon and normalize_surname(k)["phonetique"] == phon)
        communes = Counter(e.lieu.nom.split(",")[0].strip() for x in pids for e in tree.personnes[x].evenements
                           if e.lieu and e.lieu.nom.strip())
        berceau = [c for c, _ in communes.most_common(5) if c]
        var_lines = [f"- {v}" for v in sorted(variantes)] + [f"- [[{_safe(k, 120)}]] (même phonétique)"
                                                             for k in proches]
        var_lines.append(f"- Clé phonétique : `{phon}`" if phon else "")
        fm = {"type": "patronyme", "nom": key, "personnes": len(pids), "variantes": sorted(variantes) + proches,
              "berceau": berceau}
        requete = ("```dataview\nTABLE naissance, deces, statut, sosa\nFROM \"personnes\"\n"
                   f"WHERE patronyme = {_yaml(key)}\nSORT naissance ASC\n```")
        blocks = {
            "personnes": f"## Porteurs ({len(pids)})\n\n" + "\n".join(gens),
            "variantes": "## Variantes\n\n" + ("\n".join(x for x in var_lines if x) or "- (aucune)"),
            "berceau": "## Berceau\n\n" + ("\n".join(f"- {c} ({n} faits)" for c, n in communes.most_common(5) if c)
                                             or "- (aucun lieu)"),
            "pieces": "## Pièces\n\n" + ("\n".join(self._pieces_patronyme(tree, key)) or "- (aucune)"),
            "requete": "## Requête Dataview\n\n" + requete,
        }
        return fm, blocks, key

    def _pieces_patronyme(self, tree: Tree, key: str) -> list[str]:
        """Pièces rangées sous documents/*/<NOM>/, photographies/<NOM>/ et photographies/Sépultures/<NOM>/ ;
        celles dont le nom désigne une personne masquée sont omises."""
        racine = self._require()
        dossiers = [*sorted((racine / "documents").glob(f"*/{key}")), racine / "photographies" / key,
                    racine / "photographies" / "Sépultures" / key]
        caches = set()
        for x, p in tree.personnes.items():
            if self._masked(tree, x):
                caches |= {_personne({"nom": n.nom, "prenom": n.prenoms}).casefold() for n in p.noms}
        out = []
        for d in dossiers:
            if not d.is_dir() or d.is_symlink():
                continue
            for f in sorted(d.rglob("*")):
                rel = f.relative_to(racine)
                if not f.is_file() or f.is_symlink() or f.suffix.lower() == ".md" \
                        or any(part.startswith(".") for part in rel.parts):
                    continue
                if {n.casefold() for n in lire_nom(f.name)["personnes"]} & caches:
                    continue
                # lien Markdown encodé : les crochets de « [1820] » casseraient un wikilink
                label = f.name.replace("[", "\\[").replace("]", "\\]")
                out.append(f"- [{label}](../{quote(rel.as_posix())})")  # relatif à patronymes/
        return out

    def family(self, tree: Tree, fid: str) -> tuple[dict, dict[str, str], str]:
        f = tree.familles[fid]
        sides = {r: (self.link(tree, "personne", x) if x and x in tree.personnes else "") for r, x in
                 (("epoux", f.epoux), ("epouse", f.epouse))}
        marr = next((e for e in f.evenements if e.type == "MARR"), None)
        lines = [f"- **Époux** : {sides['epoux'] or 'inconnu'}", f"- **Épouse** : {sides['epouse'] or 'inconnue'}"]
        if marr:
            lines.append(f"- **Mariage** : {_fmt_date(marr.date)}" + (f" à {marr.lieu.nom}" if marr.lieu else ""))
        kids = [f"- {self.link(tree, 'personne', c.enfant)}" + (f" ({c.filiation})" if c.filiation not in ("", "BIRTH")
                                                                 else "")
                for c in f.enfants if c.enfant in tree.personnes]
        srcs = sorted({c.source for e in f.evenements for c in e.citations} | {c.source for c in f.citations}
                      | {c.source for k in f.enfants for c in k.citations})
        src_links = [self.link(tree, "source", s) for s in srcs if s in tree.sources]
        fm = {"id": fid, "type": "famille", "epoux": sides["epoux"], "epouse": sides["epouse"],
              "mariage": marr.date if marr else "", "sources": src_links}
        blocks = {"identite": "\n".join(lines), "enfants": "## Enfants\n\n" + ("\n".join(kids) or "- (aucun)"),
                  "sources": "## Sources\n\n" + ("\n".join(f"- {x}" for x in src_links) or "- (aucune)")}
        return fm, blocks, f"Famille {fid}"

    def source(self, tree: Tree, sid: str) -> tuple[dict, dict[str, str], str]:
        s = tree.sources[sid]
        repo = tree.depots.get(s.depot) if s.depot else None
        users = []
        for pid, p in sorted(tree.personnes.items()):
            if any(c.source == sid for e in p.evenements for c in e.citations) or \
               any(c.source == sid for c in p.citations) or any(c.source == sid for n in p.noms for c in n.citations):
                users.append(self.link(tree, "personne", pid))
        lines = [f"- **Titre** : {s.titre}"]
        for label, v in (("Auteur", s.auteur), ("Publication", s.publication),
                         ("Dépôt", (repo.sigle or repo.nom) if repo else ""), ("Cote", s.cote), ("URL", s.url),
                         ("Nature", s.type_source if s.type_source != "indeterminee" else "")):
            if v:
                lines.append(f"- **{label}** : {v}")
        if s.original and s.original in tree.sources:
            lines.append(f"- **Dérivée de** : {self.link(tree, 'source', s.original)}")
        fm = {"id": sid, "type": "source", "titre": s.titre, "depot": (repo.sigle or repo.nom) if repo else "",
              "cote": s.cote, "url": s.url, "nature": s.type_source, "cite_par": users}
        blocks = {"identite": "\n".join(lines),
                  "citations": "## Cité par\n\n" + ("\n".join(f"- {u}" for u in users) or "- (personne)")}
        return fm, blocks, f"{sid} — {s.titre}"

    # ------------------------------------------------------------------ fusion avec le fichier existant
    def _render(self, path: Path, fm: dict, blocks: dict[str, str], title: str) -> tuple[str, bool]:
        """(texte, modifié ?) : sections générées remplacées, texte libre et clés manuelles conservés."""
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        old_fm, body = _split(old)
        keep = _manual_keys(old_fm, set(fm) | GENERATED_KEYS)
        if not old:
            parts = [f"# {title}", ""] + [f"{START.format(k)}\n{v}\n{END}\n" for k, v in blocks.items()]
            body = "\n".join(parts) + f"\n{FREE}\n\n{FREE_HINT}\n"
        else:
            seen = set()

            def repl(m):
                k = m.group("name")
                seen.add(k)
                # bloc généré absent du nouveau contenu (ex. fiche remasquée) : retiré, jamais conservé
                return f"{START.format(k)}\n{blocks[k]}\n{END}" if k in blocks else ""

            body = re.sub(r"\n{3,}", "\n\n", _BLOCK.sub(repl, body))
            body = re.sub(r"\A(\s*)# [^\n]*", lambda m: f"{m.group(1)}# {title}", body, count=1)  # titre généré
            missing = [k for k in blocks if k not in seen]
            if missing:
                add = "\n".join(f"{START.format(k)}\n{blocks[k]}\n{END}\n" for k in missing)
                i = body.find(FREE)
                body = body[:i] + add + "\n" + body[i:] if i != -1 else body.rstrip("\n") + "\n\n" + add
        prev = next((ln.split(":", 1)[1].strip().strip('"') for ln in old_fm if ln.startswith("mis_a_jour:")), "")
        text = _frontmatter({**fm, "mis_a_jour": prev or self.today().isoformat()}, keep) + body
        if old and text == old:
            return old, False
        return _frontmatter({**fm, "mis_a_jour": self.today().isoformat()}, keep) + body, True

    def _write(self, path: Path, fm: dict, blocks: dict[str, str], title: str) -> bool:
        text, changed = self._render(path, fm, blocks, title)
        if changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return changed

    # ------------------------------------------------------------------ opérations
    def generate(self, tree: Tree, target: str = "tout") -> dict:
        root = self._require()
        sosa = self._sosa(tree)
        porteurs = self._porteurs(tree)
        ids = self._targets(tree, target, porteurs)
        written, unchanged, alertes = [], 0, []
        extra = {"personne": (sosa,), "patronyme": (porteurs,)}
        for kind, oid in ids:
            fm, blocks, title = getattr(self, METHODS[kind])(tree, oid, *extra.get(kind, ()))
            path = self.path(tree, kind, oid)
            if self._write(path, fm, blocks, title):
                written.append(str(path.relative_to(root)))
            else:
                unchanged += 1
            alertes += self._alertes(tree, kind, oid, path, porteurs)
        if target == "tout":
            self._index(tree, porteurs)
        out = {"repertoire": str(root), "ecrites": written, "inchangees": unchanged}
        if alertes:
            out["alertes"] = alertes
        if w := self.git_warning():
            out["avertissement"] = w
        return out

    def _alertes(self, tree: Tree, kind: str, oid: str, path: Path, porteurs: dict | None = None) -> list[str]:
        """Ce qui reste d'une personne masquée et que l'outil ne touche pas : nom de fichier, texte manuel."""
        if kind == "patronyme":
            if porteurs is not None and oid not in porteurs:
                return [f"{path.relative_to(self._require())} : plus aucune personne affichable ; le nom du fichier "
                        "et le texte saisi à la main peuvent identifier une personne masquée (supprimer à la main ?)."]
            return []
        masked = (kind == "personne" and self._masked(tree, oid)) or (kind == "famille" and any(
            x in tree.personnes and self._masked(tree, x) for x in (tree.familles[oid].epoux, tree.familles[oid].epouse)))
        if not masked:
            return []
        out = []
        rel = path.relative_to(self._require())
        fresh = self.fresh_name(tree, kind, oid)
        if path.stem != fresh:
            out.append(f"{rel} : le nom du fichier peut identifier une personne masquée ; le renommer à la main en "
                       f"« {fresh}.md » (les liens Obsidian suivent un renommage fait dans Obsidian).")
        old_fm, body = _split(path.read_text(encoding="utf-8"))
        libre = body.split(FREE, 1)[1].replace(FREE_HINT, "").strip() if FREE in body else ""
        manuel = _BLOCK.sub("", body.split(FREE, 1)[0])
        manuel = re.sub(r"\A\s*# [^\n]*", "", manuel).strip()
        if libre or manuel or _manual_keys(old_fm, GENERATED_KEYS):
            out.append(f"{rel} : texte ou propriétés saisis à la main conservés ; vérifier qu'ils ne contiennent "
                       "pas de données sur la personne masquée.")
        return out

    def _targets(self, tree: Tree, target: str, porteurs: dict | None = None) -> list[tuple[str, str]]:
        porteurs = self._porteurs(tree) if porteurs is None else porteurs
        if target == "tout":
            # patronymes : ceux des personnes affichables, et les fiches existantes devenues sans porteur (remasquage)
            folder = self._require() / FOLDERS["patronyme"]
            existants = {f.stem for f in folder.glob("*.md")} if folder.exists() else set()
            stems = {_safe(k, 120) for k in porteurs}
            return ([("personne", x) for x in sorted(tree.personnes)] + [("famille", x) for x in sorted(tree.familles)]
                    + [("source", x) for x in sorted(tree.sources)]
                    + [("patronyme", k) for k in sorted(porteurs)] + [("patronyme", s) for s in sorted(existants - stems)])
        for kind, coll in (("personne", tree.personnes), ("famille", tree.familles), ("source", tree.sources)):
            if target in coll:
                out = [(kind, target)]
                pat = patronyme(tree.personnes[target]) if kind == "personne" else ""
                if pat in porteurs and target in porteurs[pat]:
                    out.append(("patronyme", pat))  # fiche du patronyme tenue à jour avec ses porteurs
                return out
        if target.upper() in porteurs:
            return [("patronyme", target.upper())]
        raise NotesError(f"Identifiant inconnu dans l'arbre : {target!r} (personne, famille, source, patronyme "
                         "ou « tout »)")

    def _index(self, tree: Tree, porteurs: dict[str, list[str]]) -> None:
        path = self._require() / "index.md"
        lines = ["## Personnes", ""] + [f"- {self.link(tree, 'personne', x)}" for x in sorted(tree.personnes)]
        lines += ["", "## Familles", ""] + [f"- {self.link(tree, 'famille', x)}" for x in sorted(tree.familles)]
        lines += ["", "## Sources", ""] + [f"- {self.link(tree, 'source', x)}" for x in sorted(tree.sources)]
        lines += ["", "## Patronymes", ""] + [f"- [[{_safe(k, 120)}]] ({len(v)})" for k, v in sorted(porteurs.items())]
        fm = {"type": "index", "personnes": len(tree.personnes), "familles": len(tree.familles),
              "sources": len(tree.sources), "patronymes": len(porteurs)}
        self._write(path, fm, {"index": "\n".join(lines)}, "Index des notes de recherche")

    def read(self, tree: Tree, oid: str) -> dict:
        kind, oid = self._targets(tree, oid)[0]
        path = self.path(tree, kind, oid)
        if not path.exists():
            self.generate(tree, oid)
        return {"fichier": str(path), "contenu": path.read_text(encoding="utf-8")}

    def add(self, tree: Tree, oid: str, texte: str, section: str = "note") -> dict:
        """Entrée datée ajoutée dans le texte libre, sous « ### <section> » (créée au besoin)."""
        if section not in SECTIONS:
            raise NotesError(f"section : {', '.join(SECTIONS)}")
        if not texte.strip():
            raise NotesError("texte vide")
        kind, oid = self._targets(tree, oid)[0]
        if kind == "personne" and self._masked(tree, oid):
            raise NotesError("Personne présumée vivante : fiche masquée (GENEALOGISTE_NOTES_VIVANTS=complet).")
        path = self.path(tree, kind, oid)
        if not path.exists():
            self.generate(tree, oid)
        text = path.read_text(encoding="utf-8")
        entry = f"- {self.today().isoformat()} : {texte.strip()}"
        heading = f"### {SECTIONS[section]}"
        if FREE not in text:
            text = text.rstrip("\n") + f"\n\n{FREE}\n"
        free_at = text.index(FREE)
        head, free = text[:free_at], text[free_at:]
        if heading in free:
            i = free.index(heading) + len(heading)
            nxt = re.search(r"\n#{2,3} ", free[i:])
            end = i + nxt.start() if nxt else len(free)
            free = free[:end].rstrip("\n") + "\n" + entry + "\n" + ("\n" + free[end:].lstrip("\n") if nxt else "")
        else:
            free = free.rstrip("\n") + f"\n\n{heading}\n\n{entry}\n"
        path.write_text(head + free, encoding="utf-8")
        return {"fichier": str(path), "ajoute": entry, "section": SECTIONS[section]}

    def git_warning(self) -> str:
        root = self._require()
        try:
            out = subprocess.run(["git", "-C", str(root), "remote", "-v"], capture_output=True, text=True,
                                 timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
        if out:
            return ("Le répertoire des notes est dans un dépôt Git avec un dépôt distant : vérifier qu'il est PRIVÉ "
                    "(données de personnes, y compris vivantes si GENEALOGISTE_NOTES_VIVANTS=complet).")
        return ""


def touched(before: Tree, after: Tree) -> list[str]:
    """Personnes, familles et sources modifiées entre deux états de l'arbre (régénération après écriture)."""
    out = []
    for coll in ("personnes", "familles", "sources"):
        a, b = getattr(before, coll), getattr(after, coll)
        for oid, obj in b.items():
            if oid not in a or a[oid].to_dict() != obj.to_dict():
                out.append(oid)
    return out
