"""Identifiants pérennes ARK (Archival Resource Key) des archives et bibliothèques.

Forme : ``[https://hôte/…]ark:/NAAN/Nom[/Qualificatif][?…]``. Le NAAN (Name Assigning Authority Number)
désigne le service qui attribue l'identifiant (12148 = BnF / Gallica, 33518 = AD du Nord…), le nom désigne
la ressource (un registre), le qualificatif une partie (une image, une page ``f12``).

Normalisation (ARK Alliance) : préfixe ``ark:`` sans ``/`` superflu, NAAN tel quel, tirets ignorés dans le nom
(caractères de mise en forme), qualificatifs de présentation (``.item``, ``.texte``…) retirés ; la vue ``fNN``
de Gallica est conservée pour la page.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

N2T = "https://n2t.net/"
NAAN_REGISTRY = "https://n2t.net/e/pub/naan_registry.txt"

# Services connus (vérifiés sur des liens réels). Le registre de l'ARK Alliance complète la table au besoin.
NAANS: dict[str, dict] = {
    "12148": {"code": "BnF", "nom": "Bibliothèque nationale de France (Gallica)",
              "hote": "https://gallica.bnf.fr", "iiif": "https://gallica.bnf.fr/iiif/ark:/12148/{nom}/manifest.json"},
    "33518": {"code": "AD59", "nom": "Archives départementales du Nord",
              "hote": "https://archivesdepartementales.lenord.fr"},
    "64297": {"code": "AD62", "nom": "Archives départementales du Pas-de-Calais",
              "hote": "http://archivesenligne.pasdecalais.fr/v2"},
}

_ARK = re.compile(r"ark:/?(?P<naan>[0-9bcdfghjkmnpqrstvwxz]{5,})/(?P<rest>[^?#\s]+)", re.I)
_VIEW = re.compile(r"^f(\d+)$")
_PRESENTATION = re.compile(r"\.(item|texte\w*|image|planchecontact|r=.*|zoom|highres|lowres|thumbnail)$", re.I)


def _clean(part: str) -> str:
    """Retire les suffixes de présentation successifs (``f12.item.r=Rochefort`` -> ``f12``)."""
    prev = None
    while prev != part:
        prev, part = part, _PRESENTATION.sub("", part)
    return part


class ArkError(ValueError):
    pass


@dataclass
class Ark:
    naan: str
    nom: str  # ressource (registre, document)
    qualificatif: str = ""  # partie : image, vue (sans les suffixes de présentation)
    hote: str = ""  # hôte de l'URL d'origine (sans le chemin ARK)

    @property
    def base(self) -> str:
        """ARK de la ressource, sans qualificatif : clé de dédoublonnage des sources."""
        return f"ark:/{self.naan}/{self.nom}"

    @property
    def id(self) -> str:
        """ARK normalisé complet (avec qualificatif) : clé d'une citation."""
        return self.base + (f"/{self.qualificatif}" if self.qualificatif else "")

    @property
    def vue(self) -> int | None:
        """Numéro de vue (Gallica ``f12``), si le qualificatif l'indique."""
        last = self.qualificatif.rsplit("/", 1)[-1] if self.qualificatif else ""
        m = _VIEW.match(last)
        return int(m.group(1)) if m else None

    @property
    def service(self) -> dict | None:
        return NAANS.get(self.naan)

    def url(self) -> str:
        """URL par l'hôte d'origine (ou celui du service connu), sinon par le résolveur global n2t."""
        host = self.hote or (self.service or {}).get("hote")
        return f"{host.rstrip('/')}/{self.id}" if host else self.n2t()

    def n2t(self) -> str:
        return N2T + self.id

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(ark=self.id, ark_ressource=self.base, vue=self.vue, url=self.url(), url_n2t=self.n2t(),
                 service=self.service)
        return d


def parse(value: str) -> Ark:
    """Lit un ARK seul ou dans une URL (http/https, avec ou sans hôte, avec qualificatif et paramètres)."""
    v = (value or "").strip()
    m = _ARK.search(v)
    if not m:
        raise ArkError(f"Identifiant ARK non reconnu : {value!r} (forme attendue : ark:/NAAN/nom)")
    host = v[:m.start()].rstrip("/")
    if host and not re.match(r"^https?://", host, re.I):
        host = ""
    parts = [p for p in m.group("rest").split("/") if p]
    nom = parts[0].replace("-", "") if parts[0] else ""
    nom = _clean(nom)
    quals = [_clean(p) for p in parts[1:]]
    quals = [q for q in quals if q]
    if not nom:
        raise ArkError(f"ARK sans nom : {value!r}")
    return Ark(naan=m.group("naan").lower(), nom=nom, qualificatif="/".join(quals), hote=host)


def find(value: str) -> Ark | None:
    try:
        return parse(value)
    except ArkError:
        return None


def same_resource(a: str, b: str) -> bool:
    x, y = find(a), find(b)
    return bool(x and y and x.base == y.base)


def parse_naan_registry(text: str) -> dict[str, dict]:
    """Registre public des NAAN (format ANVL : blocs « naa: » avec who / what / where)."""
    out: dict[str, dict] = {}
    for block in re.split(r"\n\s*\n", text or ""):
        fields: dict[str, str] = {}
        key = ""
        for line in block.splitlines():
            if line.startswith("#"):
                continue
            if line[:1] in (" ", "\t") and key:
                fields[key] += " " + line.strip()
                continue
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip().lstrip("!").lower()
                fields[key] = val.strip()
        naan = fields.get("what", "")
        if naan and re.fullmatch(r"[0-9bcdfghjkmnpqrstvwxz]{5,}", naan):
            who = fields.get("who", "")
            nom, _, sigle = who.partition("(=)")
            out[naan] = {"nom": nom.strip(), "sigle": sigle.strip(), "hote": fields.get("where", "").rstrip("/")}
    return out


def suggested_citation(a: Ark, titre: str = "") -> dict:
    """Citation suggérée à partir d'un ARK (à compléter : titre, n° d'acte, qualité)."""
    svc = a.service or {}
    return {
        "source": {"titre": titre or "(titre du registre à préciser)", "ark": a.base, "url": a.url(),
                   "depot": svc.get("code", "")},
        "citation": {"ark": a.id, "page": f"vue {a.vue}" if a.vue else "(vue / n° d'acte à préciser)",
                     "consultation": "image"},
    }
