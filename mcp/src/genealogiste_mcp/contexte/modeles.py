"""Formats communs du contexte historique (#321) : Reference, ElementContexte et constantes partagées.

Une ``Reference`` décrit une notice bibliographique **récupérée** par le plugin (jamais reconstituée de mémoire) :
elle porte toujours un identifiant résolvable. Un ``ElementContexte`` est un énoncé de contexte borné dans le lieu
et le temps, rattaché à une source (identifiant d'une Reference) et à l'individu avec un niveau de rattachement.
La validation est faite à la construction : un objet existant est toujours conforme. Format décrit dans
docs/contexte-historique.md, « Formats communs ».
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields
from datetime import date

TYPES_IDENTIFIANT = ("doi", "ark", "hal", "handle", "ppn", "lccn", "europeana", "url")
NATURES = ("primaire", "secondaire_savante", "secondaire", "tertiaire", "index")
EVALUATIONS = ("oui", "non", "inconnu")  # évaluation par les pairs
ACCES = ("libre", "restreint", "")  # "" : non renseigné par le service
LECTURES = ("oui", "notice_seule")  # texte lu, ou notice seule (« non lu »)
TYPES_DOCUMENT = ("article", "chapitre", "monographie", "these", "presse", "autre")
ECHELLES = ("commune", "pays", "departement", "region", "nation", "international")  # du plus local au plus large
TYPES_ELEMENT = ("evenement", "economie", "demographie", "institution", "droit", "geographie", "culture")
NIVEAUX_RATTACHEMENT = ("atteste", "compatible", "non_demontre")
MENTION_TENDANCE = "tendance générale, ne prouve rien pour l'individu"


class ReferenceInvalide(ValueError):
    """Reference, identifiant ou élément de contexte non conforme au format commun."""


def _choix(valeur, permis: tuple, champ: str) -> None:
    if valeur not in permis:
        raise ReferenceInvalide(f"{champ}={valeur!r} : valeurs possibles {' | '.join(x or '«»' for x in permis)}")


def _texte(valeur, champ: str) -> str:
    if not isinstance(valeur, str):
        raise ReferenceInvalide(f"{champ} : texte attendu")
    return valeur.strip()


def _date_iso(valeur: str, champ: str) -> None:
    if not valeur:
        return
    try:
        date.fromisoformat(valeur[:10])
    except ValueError:
        raise ReferenceInvalide(f"{champ}={valeur!r} : date ISO attendue (AAAA-MM-JJ)") from None
    if len(valeur) > 10 and valeur[10] != "T":
        raise ReferenceInvalide(f"{champ}={valeur!r} : date ISO attendue (AAAA-MM-JJ)")


def _annee(valeur, champ: str) -> None:
    if valeur is None:
        return
    if not isinstance(valeur, int) or isinstance(valeur, bool) or not 0 < valeur <= date.today().year + 1:
        raise ReferenceInvalide(f"{champ}={valeur!r} : année (entier) attendue")


def _depuis_dict(cls, data: dict, imbriques: dict | None = None, ignores: tuple = ()):
    if not isinstance(data, dict):
        raise ReferenceInvalide(f"{cls.__name__} : objet attendu")
    noms = {f.name for f in fields(cls)}
    inconnus = set(data) - noms - set(ignores)
    if inconnus:
        raise ReferenceInvalide(f"{cls.__name__} : champs inconnus {sorted(inconnus)}")
    kw = {k: v for k, v in data.items() if k in noms}
    for k, sous in (imbriques or {}).items():
        if k in kw and not isinstance(kw[k], sous):
            kw[k] = sous.from_dict(kw[k])
    try:
        return cls(**kw)
    except TypeError as exc:
        raise ReferenceInvalide(f"{cls.__name__} : {exc}") from None


# ---------------------------------------------------------------------------------------------- identifiant

_PREFIXES_URL = {
    "doi": r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
    "handle": r"^(?:https?://hdl\.handle\.net/|hdl:\s*)",
    "hal": r"^https?://[^/]*hal[^/]*/",
    "ppn": r"^(?:https?://(?:www\.)?sudoc\.(?:fr|abes\.fr)/|ppn:?\s*)",
    "lccn": r"^(?:https?://lccn\.loc\.gov/)",
    "europeana": r"^(?:https?://(?:www\.)?europeana\.eu/(?:[a-z]{2}/)?item)",
}
_FORMES = {
    "doi": r"10\.\d{4,9}/\S+",
    "ark": r"ark:/\d{5}/\S+",
    "hal": r"[a-z]+-\d{8}(?:v\d+)?",
    "handle": r"\d+(?:\.\d+)*/\S+",
    "ppn": r"\d{8}[\dX]",
    "lccn": r"[a-z]{0,3}\d{8,10}",
    "europeana": r"/\d+/\S+",
    "url": r"https?://[^\s/]+\.[^\s/]+\S*",
}


@dataclass(frozen=True)
class Identifiant:
    """Identifiant pérenne d'une notice, normalisé (DOI en minuscules, ARK commençant par ``ark:/``, PPN nu…).
    ``cle`` (« doi:10.… ») est la forme stockée au registre et portée par ``ElementContexte.source.identifiant``."""

    type: str
    valeur: str

    def __post_init__(self):
        _choix(self.type, TYPES_IDENTIFIANT, "identifiant.type")
        if not isinstance(self.valeur, str) or not self.valeur.strip():
            raise ReferenceInvalide("identifiant.valeur vide : une référence sans identifiant est refusée")
        v = self._normaliser(self.type, self.valeur.strip())
        if not re.fullmatch(_FORMES[self.type], v):
            raise ReferenceInvalide(f"identifiant {self.type} mal formé : {self.valeur!r}")
        object.__setattr__(self, "valeur", v)

    @staticmethod
    def _normaliser(type_: str, v: str) -> str:
        if type_ in _PREFIXES_URL:
            v = re.sub(_PREFIXES_URL[type_], "", v, flags=re.I)
        if type_ == "doi":
            return v.lower()
        if type_ == "ark":
            i = v.lower().find("ark:")
            v = v[i:] if i >= 0 else v
            return "ark:/" + v[4:].lstrip("/") if v.lower().startswith("ark:") else v
        if type_ == "hal":
            return v.strip("/").lower()
        if type_ == "ppn":
            return v.strip("/").upper()
        if type_ == "lccn":
            return re.sub(r"\s+", "", v).lower()
        if type_ == "europeana":
            return "/" + v.lstrip("/")
        return v

    @property
    def cle(self) -> str:
        return f"{self.type}:{self.valeur}"

    def to_dict(self) -> dict:
        return {"type": self.type, "valeur": self.valeur}

    @classmethod
    def from_dict(cls, data) -> Identifiant:
        if isinstance(data, Identifiant):
            return data
        if not isinstance(data, dict) or not data.get("type") or not data.get("valeur"):
            raise ReferenceInvalide("identifiant manquant : une référence sans identifiant est refusée")
        return _depuis_dict(cls, data)

    @classmethod
    def depuis_cle(cls, cle: str) -> Identifiant:
        type_, sep, valeur = (cle or "").partition(":")
        if not sep or type_ not in TYPES_IDENTIFIANT:
            raise ReferenceInvalide(f"clé d'identifiant invalide : {cle!r} (attendu type:valeur)")
        return cls(type_, valeur)

    @classmethod
    def depuis_texte(cls, texte: str) -> Identifiant | None:
        """Reconnaît un identifiant écrit librement (« doi:10.… », « https://doi.org/… », « 10.… », « ark:/… »,
        « hal-… », « ppn:… », « type:valeur », URL). None si rien n'est reconnu (jamais deviné au-delà)."""
        t = (texte or "").strip()
        if not t:
            return None
        essais: list[tuple[str, str]] = []
        type_, sep, reste = t.partition(":")
        if sep and type_.lower() in TYPES_IDENTIFIANT and type_.lower() != "url" and not reste.startswith("//"):
            essais.append((type_.lower(), reste))
        bas = t.lower()
        if "doi.org/" in bas or bas.startswith("10."):
            essais.append(("doi", t))
        if "hdl.handle.net/" in bas:
            essais.append(("handle", t))
        if "ark:" in bas:
            essais.append(("ark", t))
        if "sudoc." in bas:
            essais.append(("ppn", t))
        if re.fullmatch(_FORMES["hal"], bas):
            essais.append(("hal", t))
        if bas.startswith(("http://", "https://")):
            essais.append(("url", t))
        for type_, valeur in essais:
            try:
                return cls(type_, valeur)
            except ReferenceInvalide:
                continue
        return None


# ------------------------------------------------------------------------------------------------ référence

@dataclass
class Reference:
    """Notice bibliographique récupérée par un outil du plugin.

    Champs du format commun (#286) : ``auteurs`` (« Nom, Prénom » ou nom de collectivité, tels que la notice les
    donne), ``titre``, ``publication`` (revue, éditeur, université ou titre du journal selon ``type_document``),
    ``annee``, ``pages``, ``identifiant``, ``nature``, ``evaluation_par_les_pairs``, ``acces``, ``lu``, ``service``,
    ``requete`` (URL ou requête émise, sans nom de personne), ``consulte_le`` (date ISO). Compléments pour la
    citation : ``type_document``, ``volume``, ``numero``, ``lieu_edition``, ``date`` (date ISO d'un numéro de
    presse). Un champ inconnu de la notice reste vide : il n'est jamais complété de mémoire. La citation normée
    n'est pas stockée : ``to_dict`` la calcule (``contexte.citation.citer``)."""

    identifiant: Identifiant
    nature: str
    titre: str = ""
    auteurs: list[str] = field(default_factory=list)
    publication: str = ""
    annee: int | None = None
    pages: str = ""
    type_document: str = "autre"
    volume: str = ""
    numero: str = ""
    lieu_edition: str = ""
    date: str = ""
    evaluation_par_les_pairs: str = "inconnu"
    acces: str = ""
    lu: str = "notice_seule"
    service: str = ""
    requete: str = ""
    consulte_le: str = ""

    def __post_init__(self):
        if self.identifiant is None or self.identifiant == {}:
            raise ReferenceInvalide("identifiant manquant : une référence sans identifiant est refusée")
        self.identifiant = Identifiant.from_dict(self.identifiant)
        _choix(self.nature, NATURES, "nature")
        _choix(self.evaluation_par_les_pairs, EVALUATIONS, "evaluation_par_les_pairs")
        _choix(self.acces, ACCES, "acces")
        _choix(self.lu, LECTURES, "lu")
        _choix(self.type_document, TYPES_DOCUMENT, "type_document")
        _annee(self.annee, "annee")
        if not isinstance(self.auteurs, list) or not all(isinstance(a, str) for a in self.auteurs):
            raise ReferenceInvalide("auteurs : liste de textes attendue")
        self.auteurs = [a.strip() for a in self.auteurs if a.strip()]
        for champ in ("titre", "publication", "pages", "volume", "numero", "lieu_edition", "date", "service",
                      "requete", "consulte_le"):
            setattr(self, champ, _texte(getattr(self, champ), champ))
        _date_iso(self.consulte_le, "consulte_le")
        _date_iso(self.date, "date")

    def to_dict(self, style: str = "iso690") -> dict:
        """Forme sérialisée, avec ``citation`` calculée dans ``style`` (iso690 | evidence_explained)."""
        from .citation import citer

        d = asdict(self)
        d["identifiant"] = self.identifiant.to_dict()
        return {"citation": citer(self, style), **d}

    @classmethod
    def from_dict(cls, data: dict) -> Reference:
        """Construit et valide ; ``citation`` éventuellement présente est ignorée (toujours recalculée)."""
        if isinstance(data, dict) and "identifiant" not in data:
            raise ReferenceInvalide("identifiant manquant : une référence sans identifiant est refusée")
        return _depuis_dict(cls, data, ignores=("citation",))


# ------------------------------------------------------------------------------------- élément de contexte

@dataclass
class Portee:
    """Bornes de l'élément : ``lieu`` (libellé), ``echelle`` (ECHELLES), années ``de`` et ``a`` (``a`` = ``de`` si
    absent), ``population`` concernée (facultative, ex. « mineurs de fond »)."""

    lieu: str
    echelle: str
    de: int
    a: int | None = None
    population: str = ""

    def __post_init__(self):
        if not _texte(self.lieu, "portee.lieu"):
            raise ReferenceInvalide("portee.lieu vide")
        _choix(self.echelle, ECHELLES, "portee.echelle")
        for champ in ("de", "a"):
            v = getattr(self, champ)
            if v is not None and (not isinstance(v, int) or isinstance(v, bool)):
                raise ReferenceInvalide(f"portee.{champ}={v!r} : année (entier) attendue")
        if self.de is None:
            raise ReferenceInvalide("portee.de manquante : un élément de contexte est toujours daté")
        self.a = self.de if self.a is None else self.a
        if self.a < self.de:
            raise ReferenceInvalide(f"portee : a ({self.a}) antérieure à de ({self.de})")

    @classmethod
    def from_dict(cls, data: dict) -> Portee:
        return _depuis_dict(cls, data)


@dataclass
class SourceElement:
    """Source d'un élément : ``identifiant`` est la clé (« doi:… ») d'une Reference du registre des références
    consultées ; ``localisation`` : page, paragraphe ou colonne du passage utile."""

    citation: str
    identifiant: str
    nature: str
    consulte_le: str = ""
    localisation: str = ""

    def __post_init__(self):
        ident = Identifiant.depuis_texte(_texte(self.identifiant, "source.identifiant"))
        if ident is None:
            raise ReferenceInvalide(f"source.identifiant non reconnu : {self.identifiant!r} (un énoncé sans "
                                    "identifiant de source est refusé)")
        self.identifiant = ident.cle
        _choix(self.nature, NATURES, "source.nature")
        _date_iso(self.consulte_le, "source.consulte_le")

    @classmethod
    def from_dict(cls, data: dict) -> SourceElement:
        return _depuis_dict(cls, data)

    @classmethod
    def depuis_reference(cls, ref: Reference, localisation: str = "", style: str = "iso690") -> SourceElement:
        from .citation import citer

        return cls(citation=citer(ref, style), identifiant=ref.identifiant.cle, nature=ref.nature,
                   consulte_le=ref.consulte_le, localisation=localisation)


@dataclass
class Rattachement:
    """Lien de l'élément avec l'individu. ``atteste`` exige ``citation_arbre`` (citation de l'arbre portant sur
    l'individu, ex. « S7, liste des victimes ») : un outil ne l'attribue jamais seul."""

    personne: str = ""
    niveau: str = "non_demontre"
    justification: str = ""
    citation_arbre: str = ""

    def __post_init__(self):
        _choix(self.niveau, NIVEAUX_RATTACHEMENT, "rattachement.niveau")
        if self.niveau == "atteste" and not (self.personne and _texte(self.citation_arbre, "citation_arbre")):
            raise ReferenceInvalide("rattachement atteste : personne et citation_arbre (citation de l'arbre "
                                    "portant sur l'individu) obligatoires")

    @classmethod
    def from_dict(cls, data: dict) -> Rattachement:
        return _depuis_dict(cls, data)


@dataclass
class ElementContexte:
    """Élément de contexte (format #289) : ``enonce`` tiré de la source, ``type`` (TYPES_ELEMENT), ``portee``,
    ``source``, ``rattachement``."""

    enonce: str
    type: str
    portee: Portee
    source: SourceElement
    rattachement: Rattachement = field(default_factory=Rattachement)

    def __post_init__(self):
        if not _texte(self.enonce, "enonce"):
            raise ReferenceInvalide("enonce vide")
        _choix(self.type, TYPES_ELEMENT, "type")
        for champ, cls in (("portee", Portee), ("source", SourceElement), ("rattachement", Rattachement)):
            v = getattr(self, champ)
            if not isinstance(v, cls):
                setattr(self, champ, cls.from_dict(v))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ElementContexte:
        return _depuis_dict(cls, data, {"portee": Portee, "source": SourceElement, "rattachement": Rattachement})
