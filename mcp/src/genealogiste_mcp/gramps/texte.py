"""Texte enrichi des notes Gramps (#279) : fonctions pures sur le ``StyledText`` brut (JSON de Gramps / Gramps Web).

Forme (Gramps ``gen/lib/styledtext.py``, ``styledtexttag.py``, ``styledtexttagtype.py``, identiques en 5.2, 6.0
et 6.1) : ``{"_class": "StyledText", "string": …, "tags": [{"_class": "StyledTextTag", "name": <type>,
"value": None | str | int, "ranges": [[début, fin], …]}]}``. Onze noms de tag : ``bold``, ``italic``,
``underline``, ``fontface`` (str), ``fontsize`` (int), ``fontcolor`` (str), ``highlight`` (str),
``superscript``, ``link`` (str), ``strikethrough``, ``subscript``.

**Plages** : ``[début, fin)`` en indices de chaîne Python, c'est-à-dire en **points de code Unicode** (pas en
unités UTF-16) : Gramps découpe ``str(text)[début:fin]`` (``docbackend.add_markup_from_styled`` : « unicode
text must be sliced correctly ») ; Gramps Desktop compte en caractères GTK (``TextIter.get_offset``) ; l'éditeur
de Gramps Web compte en points de code (``GrampsjsEditor.js`` : « Unicode code-point offset »). Un émoji hors
du plan multilingue de base (🟡) compte 1, « ⚠️ » (U+26A0 + U+FE0F) compte 2. Plusieurs tags peuvent se
chevaucher et un même tag apparaître plusieurs fois : Gramps ne fusionne qu'à l'affichage.

**Liens** : tag ``link`` dont la valeur est l'URL ; lien interne ``gramps://<Classe>/handle/<handle>`` (forme
écrite par l'éditeur de lien de Gramps, ``editlink.py``) ou ``gramps://<Classe>/gramps_id/<id>`` (lue par Gramps
et Gramps Web) ; l'import XML de Gramps ne retraduit que la forme ``handle``.

Markdown simple (sous-ensemble fermé, sans dépendance) : ``**gras**``, ``*italique*`` ou ``_italique_``,
``[texte](url)`` (``http(s)://``, ``mailto:`` ou lien interne ``gramps://``), échappement ``\\`` de ``\\ * _ [ ]``.
Tout le reste (titres, listes, tableaux, HTML, code…) est du texte brut, gardé caractère pour caractère. Une
emphase ne traverse pas de fin de ligne ; un marqueur non fermé, un lien à schéma refusé (``javascript:``…)
restent du texte.
"""

from __future__ import annotations

import bisect
import re

from .types import gtype, tname

NOMS = ("bold", "italic", "underline", "fontface", "fontsize", "fontcolor", "highlight", "superscript", "link",
        "strikethrough", "subscript")
CLASSES_LIEN = ("Person", "Family", "Event", "Place", "Source", "Citation", "Repository", "Media", "Note")
LIEN_INTERNE = re.compile(r"^gramps://(?P<classe>" + "|".join(CLASSES_LIEN) + r")/(?P<prop>handle|gramps_id)/"
                          r"(?P<valeur>[A-Za-z0-9_.\-]+)$")
_SCHEMAS = ("http://", "https://", "mailto:")
_ESC = "\\*_[]"
# URL d'un lien Markdown : sans blanc ni crochet, parenthèses équilibrées sur un niveau (« …/A_(b) »)
_URL = re.compile(r"\(([^\s()\[\]]*(?:\([^\s()\[\]]*\)[^\s()\[\]]*)*)\)")
MAX_MARKDOWN = 200_000  # caractères : au-delà, texte brut (garde-fou contre une entrée hostile)


# ---------------------------------------------------------------------------------------------- utilitaires

def tag(nom: str, plages: list[list[int]], valeur=None) -> dict:
    return {"_class": "StyledTextTag", "name": gtype("StyledTextTagType", nom), "value": valeur,
            "ranges": [list(p) for p in plages]}


def lien_interne(classe: str, handle: str) -> str:
    return f"gramps://{classe}/handle/{handle}"


def cible_interne(valeur) -> tuple[str, str, str] | None:
    """(classe, propriété, valeur) d'un lien interne ``gramps://``, sinon None."""
    m = LIEN_INTERNE.match(valeur) if isinstance(valeur, str) else None
    return (m["classe"], m["prop"], m["valeur"]) if m else None


def url_admise(url: str) -> bool:
    """Lien écrit depuis du Markdown : web, courriel ou lien interne ; jamais ``javascript:``, ``data:``…"""
    return url.lower().startswith(_SCHEMAS) and not any(c.isspace() for c in url) or cible_interne(url) is not None


def decrire(t: dict, texte: str = "") -> str:
    """Description lisible d'un tag (avertissements) : « gras « extrait » », « couleur #ff0000 « … » »."""
    nom = tname(t.get("name"))
    v = t.get("value")
    extraits = []
    for a, b in t.get("ranges") or []:
        s = texte[max(a, 0):max(b, 0)] if texte else ""
        extraits.append(f"« {s[:40]}{'…' if len(s) > 40 else ''} » [{a}, {b})" if s else f"[{a}, {b})")
    return f"{nom}{f' {v}' if v not in (None, '') else ''} " + ", ".join(extraits)


def plages_valides(texte: str, tags: list[dict]) -> bool:
    n = len(texte)
    return all(0 <= a < b <= n for t in tags for a, b in t.get("ranges") or [])


# ---------------------------------------------------------------------------------------------- texte modifié

def ajuster(ancien: str, tags: list[dict], nouveau: str) -> tuple[list[dict], list[str]]:
    """Mise en forme d'une note dont le texte change : un style dont la plage reste entière dans le préfixe commun
    inchangé est gardé, dans le suffixe commun inchangé il est décalé ; les autres (plage touchée par la
    modification, ou hors bornes) sont retirés et décrits dans la liste renvoyée (jamais de perte silencieuse)."""
    if ancien == nouveau:
        return [dict(t, ranges=[list(r) for r in t.get("ranges") or []]) for t in tags], []
    n0, n1 = len(ancien), len(nouveau)
    p = 0
    while p < min(n0, n1) and ancien[p] == nouveau[p]:
        p += 1
    q = 0
    while q < min(n0, n1) - p and ancien[n0 - 1 - q] == nouveau[n1 - 1 - q]:
        q += 1
    garde, retires = [], []
    for t in tags:
        plages, perdues = [], []
        for a, b in t.get("ranges") or []:
            if not 0 <= a < b <= n0:
                perdues.append([a, b])
            elif b <= p:
                plages.append([a, b])
            elif a >= n0 - q:
                plages.append([a + n1 - n0, b + n1 - n0])
            else:
                perdues.append([a, b])
        if perdues:
            retires.append(decrire(dict(t, ranges=perdues), ancien))
        if plages:
            garde.append(dict(t, ranges=plages))
    return garde, retires


# ---------------------------------------------------------------------------------------------- Markdown -> stylé

class _Md:
    """Analyseur à descente récursive du sous-ensemble Markdown ; un échec est mémorisé par état (pas de retour
    arrière exponentiel sur une entrée hostile)."""

    def __init__(self, s: str):
        self.s = s
        self.out: list[str] = []
        self.n = 0  # longueur du texte produit (points de code)
        self.tags: list[tuple[str, int, int, str | None]] = []
        self.echecs: set[tuple[int, str, bool, int]] = set()
        self.lignes = [k for k, c in enumerate(s) if c == "\n"]
        # fermants possibles (précédés d'un non-blanc) de chaque délimiteur
        self.fermants = {d: [k for k in range(1, len(s)) if s.startswith(d, k) and not s[k - 1].isspace()]
                         for d in ("**", "*", "_")}

    def emit(self, c: str) -> None:
        self.out.append(c)
        self.n += len(c)

    def _ouvre(self, i: int, d: str) -> bool:
        s, j = self.s, i + len(d)
        if j >= len(s) or s[j].isspace() or (d == "_" and i > 0 and s[i - 1].isalnum()):
            return False
        f = self.fermants[d]
        k = bisect.bisect_right(f, j)  # contenu non vide : fermant après j
        if k == len(f):
            return False
        x = bisect.bisect_left(self.lignes, j)
        return f[k] < (self.lignes[x] if x < len(self.lignes) else len(s))

    def _ferme(self, i: int, d: str, debut: int) -> bool:
        s = self.s
        if not s.startswith(d, i) or i == 0 or s[i - 1].isspace() or self.n == debut:
            return False
        return not (d == "_" and i + 1 < len(s) and s[i + 1].isalnum())

    def lien(self, i: int) -> tuple[int, int, str] | None:
        """``[texte](url)`` à la position i : (position du ``]``, fin du lien, url) ou None."""
        s = self.s
        j = i + 1
        while j < len(s):
            c = s[j]
            if c == "\\" and j + 1 < len(s) and s[j + 1] in _ESC:
                j += 2
                continue
            if c in "\n[":
                return None
            if c == "]":
                break
            j += 1
        m = _URL.match(s, j + 1) if j < len(s) and j > i + 1 else None
        return (j, m.end(), m.group(1)) if m else None

    def essai(self, i: int, fin: str, dans_lien: bool, prof: int) -> tuple[int, int] | None:
        """Contenu délimité depuis i : (position après le fermant, début du contenu produit) ou None (et alors
        rien n'est produit)."""
        cle = (i, fin, dans_lien, prof)
        if cle in self.echecs:
            return None
        n_out, n, n_tags = len(self.out), self.n, len(self.tags)
        j, ok = self.run(i, fin, dans_lien, prof)
        if ok and self.n > n:
            return j, n
        del self.out[n_out:], self.tags[n_tags:]
        self.n = n
        self.echecs.add(cle)
        return None

    def run(self, i: int, fin: str | None, dans_lien: bool, prof: int) -> tuple[int, bool]:
        """Analyse depuis i jusqu'au délimiteur ``fin`` : (position après, fermé ?)."""
        s, debut = self.s, self.n
        while i < len(s):
            c = s[i]
            if c == "\\" and i + 1 < len(s) and s[i + 1] in _ESC:
                self.emit(s[i + 1])
                i += 2
                continue
            if fin == "]":
                if c == "]":
                    return i, True
            elif fin in ("**", "_") and self._ferme(i, fin, debut):
                return i + len(fin), True
            elif fin == "*" and not s.startswith("**", i) and self._ferme(i, "*", debut):
                return i + 1, True
            if c == "\n" and fin in ("**", "*", "_"):
                return i, False
            if c == "[" and not dans_lien and prof < 3:
                lk = self.lien(i)
                if lk and url_admise(lk[2]):
                    r = self.essai(i + 1, "]", True, prof + 1)
                    if r:
                        self.tags.append(("link", r[1], self.n, lk[2]))
                        i = lk[1]
                        continue
            if prof < 3:
                r = None
                for d, nom in (("**", "bold"), ("*", "italic"), ("_", "italic")):
                    if d == fin or not s.startswith(d, i) or (d == "*" and s.startswith("**", i)) \
                            or not self._ouvre(i, d):
                        continue
                    r = self.essai(i + len(d), d, dans_lien, prof + 1)
                    if r:
                        self.tags.append((nom, r[1], self.n, None))
                        i = r[0]
                        break
                if r:
                    continue
            if fin == "*" and s.startswith("**", i) and self._ferme(i, "*", debut):
                return i + 1, True
            self.emit(c)
            i += 1
        return i, False


def depuis_markdown(md: str) -> dict:
    """Markdown simple -> StyledText brut (une plage par segment ; tags regroupés par nom et valeur)."""
    if len(md) > MAX_MARKDOWN:
        return {"_class": "StyledText", "string": md, "tags": []}
    p = _Md(md)
    p.run(0, None, False, 0)
    texte = "".join(p.out)
    groupes: dict[tuple[str, str | None], list[list[int]]] = {}
    for nom, a, b, v in p.tags:
        groupes.setdefault((nom, v), []).append([a, b])
    ordre = {n: i for i, n in enumerate(NOMS)}
    tags = [tag(nom, sorted(pl), v) for (nom, v), pl in sorted(groupes.items(),
                                                                key=lambda kv: (ordre[kv[0][0]], kv[0][1] or ""))]
    return {"_class": "StyledText", "string": texte, "tags": tags}


# ---------------------------------------------------------------------------------------------- stylé -> Markdown

def _union(plages: list[list[int]], n: int) -> list[list[int]]:
    out: list[list[int]] = []
    for a, b in sorted([max(0, a), min(n, b)] for a, b in plages):
        if a >= b:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def representable(texte: str, tags: list[dict]) -> tuple[dict[tuple[str, str | None], list[list[int]]], list[str]]:
    """Styles exprimables en Markdown simple, normalisés (union des plages, découpées aux fins de ligne, sans
    blanc en bordure d'emphase) et descriptions des autres (police, couleur, souligné, exposant, lien refusé…)."""
    n = len(texte)
    garde: dict[tuple[str, str | None], list[list[int]]] = {}
    pertes = []
    for t in tags:
        nom, v = tname(t.get("name")), t.get("value")
        if nom in ("bold", "italic") or (nom == "link" and isinstance(v, str) and url_admise(v)
                                         and _URL.fullmatch(f"({v})") is not None):
            garde.setdefault((nom, v if nom == "link" else None), []).extend(t.get("ranges") or [])
        else:
            pertes.append(decrire(t, texte))
    norm = {}
    for (nom, v), plages in garde.items():
        morceaux = []
        for a, b in _union(plages, n):
            debut = a
            for k in range(a, b + 1):
                if k == b or texte[k] == "\n":
                    x, y = debut, k
                    if nom != "link":
                        while x < y and texte[x].isspace():
                            x += 1
                        while y > x and texte[y - 1].isspace():
                            y -= 1
                    if x < y:
                        morceaux.append([x, y])
                    debut = k + 1
        if morceaux:
            norm[(nom, v)] = morceaux
    # liens qui se chevauchent (URL différentes) : le premier dans le texte est gardé, les autres signalés
    pris: list[list[int]] = []
    for (nom, v), pl in sorted(((k, p) for k, p in norm.items() if k[0] == "link"), key=lambda kv: kv[1][0]):
        garde = [r for r in pl if not any(r[0] < b and a < r[1] for a, b in pris)]
        if len(garde) < len(pl):
            pertes.append(decrire(tag("link", [r for r in pl if r not in garde], v), texte)
                          + " (chevauche un autre lien)")
        pris += garde
        if garde:
            norm[(nom, v)] = garde
        else:
            del norm[(nom, v)]
    return norm, pertes


def _echappe(texte: str, i: int, c: str) -> str:
    if c in "\\*[]":
        return "\\" + c
    if c == "_":
        avant = texte[i - 1] if i > 0 else ""
        apres = texte[i + 1] if i + 1 < len(texte) else ""
        return "_" if avant.isalnum() and apres.isalnum() else "\\_"
    return c


def _emettre(texte: str, norm: dict) -> str:
    n = len(texte)

    def actif(k: int) -> tuple[str | None, bool, bool]:
        lk = next((v for (nom, v), pl in norm.items() if nom == "link" and any(a <= k < b for a, b in pl)), None)
        gras = any(a <= k < b for a, b in norm.get(("bold", None), []))
        ital = any(a <= k < b for a, b in norm.get(("italic", None), []))
        return lk, gras, ital

    out: list[str] = []
    pile: list[tuple[str, str | None]] = []  # ordre : lien, gras, italique

    def fermer(jusqua: int) -> None:
        while len(pile) > jusqua:
            nom, v = pile.pop()
            out.append(f"]({v})" if nom == "link" else "**" if nom == "bold" else "*")

    for k in range(n + 1):
        voulu: list[tuple[str, str | None]] = []
        if k < n:
            lk, gras, ital = actif(k)
            if lk:
                voulu.append(("link", lk))
            if gras:
                voulu.append(("bold", None))
            if ital:
                voulu.append(("italic", None))
        # un style qui continue reste ouvert ; un style qui s'arrête ferme ceux ouverts après lui (rouverts ensuite)
        commun = 0
        while commun < len(pile) and pile[commun] in voulu:
            commun += 1
        fermer(commun)
        if k == n:
            break
        for nom, v in [x for x in voulu if x not in pile]:
            out.append("[" if nom == "link" else "**" if nom == "bold" else "*")
            pile.append((nom, v))
        out.append(_echappe(texte, k, texte[k]))
    return "".join(out)


def _plages(st: dict) -> dict:
    return representable(st["string"], st["tags"])[0]


def vers_markdown(styled: dict) -> tuple[str, list[str]]:
    """StyledText brut -> Markdown simple, et la liste des mises en forme non représentables (police, couleur,
    souligné, barré, exposant/indice, surlignage, lien à schéma non admis, gras/italique ambigus) : jamais de
    perte silencieuse."""
    texte = (styled or {}).get("string") or ""
    tags = (styled or {}).get("tags") or []
    norm, pertes = representable(texte, tags)
    # repli en cas d'ambiguïté (emphases adjacentes) : liens seuls, puis texte seul ; chaque repli est signalé
    for garde in (norm, {k: v for k, v in norm.items() if k[0] == "link"}, {}):
        md = _emettre(texte, garde)
        relu = depuis_markdown(md)
        if relu["string"] == texte and _plages(relu) == garde:
            pertes += [decrire(tag(nom, pl, v), texte) + " (ambigu en Markdown)"
                       for (nom, v), pl in norm.items() if (nom, v) not in garde]
            return md, pertes
    raise AssertionError("texte brut échappé non relu à l'identique")  # pragma: no cover (impossible)


def normaliser(styled: dict) -> tuple[str, dict]:
    """Forme comparable d'un StyledText sur le sous-ensemble Markdown (tests d'aller-retour)."""
    return styled["string"], _plages(styled)
