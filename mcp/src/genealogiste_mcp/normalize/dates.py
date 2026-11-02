"""Dates généalogiques : GEDCOM 7/5.5.1, texte français, calendriers grégorien, julien et républicain.

Toute date est réduite à un intervalle de jours juliens [jdn_min, jdn_max] dans lequel
l'événement a eu lieu, ce qui permet les comparaisons avec tolérance (±2 ans par défaut).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

GREG_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
FRENCH_MONTHS = ["VEND", "BRUM", "FRIM", "NIVO", "PLUV", "VENT", "GERM", "FLOR", "PRAI", "MESS", "THER", "FRUC", "COMP"]
FRENCH_MONTH_NAMES = [
    "vendémiaire", "brumaire", "frimaire", "nivôse", "pluviôse", "ventôse",
    "germinal", "floréal", "prairial", "messidor", "thermidor", "fructidor", "jours complémentaires",
]
FR_MONTHS_TEXT = {
    "janvier": 1, "janv": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3, "avril": 4, "avr": 4,
    "mai": 5, "juin": 6, "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "sept": 9, "7bre": 9,
    "octobre": 10, "oct": 10, "8bre": 10, "novembre": 11, "nov": 11, "9bre": 11,
    "decembre": 12, "dec": 12, "xbre": 12, "10bre": 12,
}
FR_REP_TEXT = {
    "vendemiaire": 1, "brumaire": 2, "frimaire": 3, "nivose": 4, "pluviose": 5, "ventose": 6,
    "germinal": 7, "floreal": 8, "prairial": 9, "messidor": 10, "thermidor": 11, "fructidor": 12,
    "complementaire": 13, "complementaires": 13, "sansculottide": 13, "sansculottides": 13,
}
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
GREG_MONTH_NAMES_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

FRENCH_EPOCH = 2375840  # 1er vendémiaire an I = 22 septembre 1792 (grégorien)
SEXTILES = {3, 7, 11, 15}
YEAR_DAYS = 365.2425
APPROX_YEARS = 2  # tolérance par défaut pour ABT/CAL/EST


def _strip(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------- jours juliens

def gregorian_to_jdn(y: int, m: int, d: int) -> int:
    a = (14 - m) // 12
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    return d + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045


def julian_to_jdn(y: int, m: int, d: int) -> int:
    a = (14 - m) // 12
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    return d + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - 32083


def jdn_to_gregorian(j: int) -> tuple[int, int, int]:
    a = j + 32044
    b = (4 * a + 3) // 146097
    c = a - 146097 * b // 4
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = 100 * b + d - 4800 + m // 10
    return year, month, day


def jdn_to_julian(j: int) -> tuple[int, int, int]:
    c = j + 32082
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = d - 4800 + m // 10
    return year, month, day


def _french_year_start(an: int) -> int:
    return FRENCH_EPOCH + 365 * (an - 1) + sum(1 for s in SEXTILES if s < an)


def french_year_length(an: int) -> int:
    return 366 if an in SEXTILES else 365


def french_to_jdn(an: int, mois: int, jour: int) -> int:
    if an < 1:
        raise ValueError("Année républicaine invalide")
    if not 1 <= mois <= 13:
        raise ValueError("Mois républicain invalide")
    max_day = 30 if mois <= 12 else french_year_length(an) - 360
    if not 1 <= jour <= max_day:
        raise ValueError(f"Jour républicain invalide ({jour} {FRENCH_MONTHS[mois - 1]} an {an})")
    return _french_year_start(an) + 30 * (mois - 1) + jour - 1


def jdn_to_french(j: int) -> tuple[int, int, int]:
    if j < FRENCH_EPOCH:
        raise ValueError("Date antérieure au calendrier républicain")
    an = 1
    while _french_year_start(an + 1) <= j:
        an += 1
    off = j - _french_year_start(an)
    return an, off // 30 + 1, off % 30 + 1


def roman_to_int(s: str) -> int:
    s = s.upper()
    total = 0
    for i, ch in enumerate(s):
        v = ROMAN[ch]
        if i + 1 < len(s) and ROMAN[s[i + 1]] > v:
            total -= v
        else:
            total += v
    return total


def int_to_roman(n: int) -> str:
    vals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, r in vals:
        while n >= v:
            out += r
            n -= v
    return out


def iso(j: int) -> str:
    y, m, d = jdn_to_gregorian(j)
    return f"{y:04d}-{m:02d}-{d:02d}"


# ---------------------------------------------------------------------------- modèle

@dataclass
class DatePoint:
    calendar: str  # GREGORIAN | JULIAN | FRENCH_R
    year: int
    month: int | None = None
    day: int | None = None

    def bounds(self) -> tuple[int, int]:
        y, m, d = self.year, self.month, self.day
        if self.calendar == "FRENCH_R":
            if m is None:
                start = _french_year_start(y)
                return start, start + french_year_length(y) - 1
            if d is None:
                start = french_to_jdn(y, m, 1)
                length = 30 if m <= 12 else french_year_length(y) - 360
                return start, start + length - 1
            j = french_to_jdn(y, m, d)
            return j, j
        conv = julian_to_jdn if self.calendar == "JULIAN" else gregorian_to_jdn
        if m is None:
            return conv(y, 1, 1), conv(y + 1, 1, 1) - 1
        if d is None:
            nxt = conv(y + (m == 12), 1 if m == 12 else m + 1, 1)
            return conv(y, m, 1), nxt - 1
        return conv(y, m, d), conv(y, m, d)

    def gedcom(self, version: int = 7) -> str:
        months = FRENCH_MONTHS if self.calendar == "FRENCH_R" else GREG_MONTHS
        parts = []
        if self.day:
            parts.append(str(self.day))
        if self.month:
            parts.append(months[self.month - 1])
        parts.append(str(self.year))
        body = " ".join(parts)
        if self.calendar == "GREGORIAN":
            return body
        if version >= 7:
            return f"{self.calendar} {body}"
        return {"JULIAN": "@#DJULIAN@", "FRENCH_R": "@#DFRENCH R@"}[self.calendar] + " " + body

    def texte(self) -> str:
        if self.calendar == "FRENCH_R":
            parts = []
            if self.day:
                parts.append("1er" if self.day == 1 else str(self.day))
            if self.month:
                parts.append(FRENCH_MONTH_NAMES[self.month - 1])
            parts.append(f"an {int_to_roman(self.year)}")
            return " ".join(parts)
        parts = []
        if self.day:
            parts.append("1er" if self.day == 1 else str(self.day))
        if self.month:
            parts.append(GREG_MONTH_NAMES_FR[self.month - 1])
        parts.append(str(self.year))
        s = " ".join(parts)
        return s + (" (julien)" if self.calendar == "JULIAN" else "")


@dataclass
class GenDate:
    original: str
    qualifier: str | None  # None | ABT | CAL | EST | BEF | AFT | BET | FROM | TO | FROMTO
    start: DatePoint | None
    end: DatePoint | None = None
    phrase: str | None = None
    tolerance_years: int = APPROX_YEARS

    @property
    def interval(self) -> tuple[int, int]:
        """Intervalle [min, max] en jours juliens (grégorien proleptique)."""
        lo, hi = self.start.bounds()
        span = int(round(self.tolerance_years * YEAR_DAYS))
        q = self.qualifier
        if q in ("ABT", "CAL", "EST"):
            return lo - span, hi + span
        if q == "BEF":
            return lo - int(100 * YEAR_DAYS), lo - 1
        if q == "AFT":
            return hi + 1, hi + int(100 * YEAR_DAYS)
        if q in ("BET", "FROMTO") and self.end:
            return lo, self.end.bounds()[1]
        if q == "FROM":
            return lo, lo + int(100 * YEAR_DAYS)
        if q == "TO":
            return lo - int(100 * YEAR_DAYS), hi
        return lo, hi

    @property
    def is_exact_day(self) -> bool:
        return self.qualifier is None and self.start is not None and self.start.day is not None

    def gedcom(self, version: int = 7) -> str:
        s = self.start.gedcom(version)
        q = self.qualifier
        if q in ("ABT", "CAL", "EST", "BEF", "AFT", "FROM", "TO"):
            out = f"{q} {s}"
        elif q == "BET":
            out = f"BET {s} AND {self.end.gedcom(version)}"
        elif q == "FROMTO":
            out = f"FROM {s} TO {self.end.gedcom(version)}"
        else:
            out = s
        return out

    def texte(self) -> str:
        labels = {"ABT": "vers", "CAL": "calculé", "EST": "estimé", "BEF": "avant", "AFT": "après",
                  "FROM": "depuis", "TO": "jusqu'à"}
        q = self.qualifier
        s = self.start.texte()
        if q == "BET":
            return f"entre {s} et {self.end.texte()}"
        if q == "FROMTO":
            return f"de {s} à {self.end.texte()}"
        if q in labels:
            return f"{labels[q]} {s}"
        return s

    def to_dict(self) -> dict:
        lo, hi = self.interval
        d = {
            "original": self.original,
            "gedcom": self.gedcom(7),
            "texte": self.texte(),
            "qualificatif": self.qualifier,
            "calendrier": self.start.calendar,
            "debut_gregorien": iso(lo),
            "fin_gregorien": iso(hi),
            "annee_min": jdn_to_gregorian(lo)[0],
            "annee_max": jdn_to_gregorian(hi)[0],
            "jour_exact": self.is_exact_day,
        }
        if self.start.calendar != "GREGORIAN" and self.qualifier is None:
            a, b = self.start.bounds()
            d["equivalent_gregorien"] = iso(a) if a == b else f"{iso(a)} / {iso(b)}"
        if self.start.calendar == "GREGORIAN" and self.qualifier is None and self.start.day:
            j = self.start.bounds()[0]
            if FRENCH_EPOCH <= j <= gregorian_to_jdn(1805, 12, 31):
                an, m, dd = jdn_to_french(j)
                d["equivalent_republicain"] = DatePoint("FRENCH_R", an, m, dd).texte()
        d["point"] = asdict(self.start)
        return d


# ---------------------------------------------------------------------------- analyse GEDCOM

_CAL_RE = re.compile(r"^(?:@#D(JULIAN|GREGORIAN|FRENCH R)@|(JULIAN|GREGORIAN|FRENCH_R))\s+")


def _parse_point(text: str) -> DatePoint:
    text = text.strip()
    cal = "GREGORIAN"
    m = _CAL_RE.match(text)
    if m:
        cal = (m.group(1) or m.group(2)).replace(" ", "_")
        text = text[m.end():]
    tokens = text.split()
    if tokens and tokens[-1] in ("BCE", "B.C."):
        raise ValueError("Dates avant notre ère non gérées")
    if not tokens:
        raise ValueError("Date vide")
    year_tok = tokens[-1]
    if not re.fullmatch(r"\d{1,4}(/\d{2})?", year_tok):
        raise ValueError(f"Année invalide : {year_tok}")
    if "/" in year_tok:  # double datation 5.5.1 : 1700/01
        year_tok = year_tok.split("/")[0]
    year = int(year_tok)
    month = day = None
    months = FRENCH_MONTHS if cal == "FRENCH_R" else GREG_MONTHS
    if len(tokens) >= 2:
        mon = tokens[-2].upper()
        if mon not in months:
            raise ValueError(f"Mois inconnu : {tokens[-2]}")
        month = months.index(mon) + 1
    if len(tokens) >= 3:
        day = int(tokens[-3])
    pt = DatePoint(cal, year, month, day)
    pt.bounds()  # validation
    return pt


def parse_gedcom_date(value: str) -> GenDate | None:
    if not value or not value.strip():
        return None
    raw = value.strip()
    s = raw
    phrase = None
    pm = re.search(r"\((.*)\)\s*$", s)
    if pm:
        phrase = pm.group(1)
        s = s[: pm.start()].strip()
        if not s:
            return None
    up = s.upper()
    try:
        m = re.match(r"^BET\s+(.+?)\s+AND\s+(.+)$", up)
        if m:
            return GenDate(raw, "BET", _parse_point(m.group(1)), _parse_point(m.group(2)), phrase)
        m = re.match(r"^FROM\s+(.+?)\s+TO\s+(.+)$", up)
        if m:
            return GenDate(raw, "FROMTO", _parse_point(m.group(1)), _parse_point(m.group(2)), phrase)
        for q in ("ABT", "CAL", "EST", "BEF", "AFT", "FROM", "TO", "INT"):
            if up.startswith(q + " "):
                return GenDate(raw, None if q == "INT" else q, _parse_point(up[len(q) + 1:]), None, phrase)
        return GenDate(raw, None, _parse_point(up), None, phrase)
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------- analyse texte français

def _parse_fr_point(t: str) -> DatePoint | None:
    t = _strip(t.lower()).replace(",", " ").replace("le ", " ").replace("1er", "1").strip()
    t = re.sub(r"\s+", " ", t)
    # Républicain : "12 vendémiaire an III", "an 3", "4e jour complémentaire an II"
    m = re.search(r"(?:(\d{1,2})(?:e|eme)?\s+(?:jour\s+)?)?([a-z]+)?\s*(?:de\s+l')?\s*an\s+([ivxlc]+|\d+)", t)
    if m and (m.group(2) in FR_REP_TEXT or m.group(2) is None or m.group(2) in ("jour", "jours")):
        year_tok = m.group(3)
        an = int(year_tok) if year_tok.isdigit() else roman_to_int(year_tok)
        mois = FR_REP_TEXT.get(m.group(2) or "", None)
        if mois is None and "complementaire" in t:
            mois = 13
        jour = int(m.group(1)) if m.group(1) and mois else None
        pt = DatePoint("FRENCH_R", an, mois, jour)
        pt.bounds()
        return pt
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return DatePoint("GREGORIAN", int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", t)
    if m:
        return DatePoint("GREGORIAN", int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", t)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return DatePoint("GREGORIAN", y, mo or None, d or None)
    julian = "julien" in t or "vieux style" in t
    t = t.replace("julien", "").replace("(", "").replace(")", "").replace("vieux style", "").strip()
    m = re.fullmatch(r"(?:(\d{1,2})\s+)?([a-z0-9]+)\.?\s+(\d{3,4})", t)
    if m and m.group(2) in FR_MONTHS_TEXT:
        return DatePoint("JULIAN" if julian else "GREGORIAN", int(m.group(3)), FR_MONTHS_TEXT[m.group(2)],
                         int(m.group(1)) if m.group(1) else None)
    m = re.fullmatch(r"(\d{3,4})", t)
    if m:
        return DatePoint("JULIAN" if julian else "GREGORIAN", int(m.group(1)))
    return None


def parse_date(text: str, tolerance_years: int = APPROX_YEARS) -> GenDate | None:
    """Analyse une date GEDCOM (5.5.1 ou 7) ou un texte français libre."""
    if not text or not str(text).strip():
        return None
    text = str(text).strip()
    g = parse_gedcom_date(text)
    if g:
        g.tolerance_years = tolerance_years
        return g
    t = _strip(text.lower()).strip()
    qual = None
    prefixes = (("vers ", "ABT"), ("environ ", "ABT"), ("circa ", "ABT"), ("ca. ", "ABT"), ("~", "ABT"),
                ("calcule ", "CAL"), ("estime ", "EST"), ("avant ", "BEF"), ("apres ", "AFT"),
                ("depuis ", "FROM"))
    for w, q in prefixes:
        if t.startswith(w):
            qual = q
            t = t[len(w):].strip()
            break
    m = re.match(r"^entre\s+(.+?)\s+et\s+(.+)$", t)
    if m:
        a, b = _parse_fr_point(m.group(1)), _parse_fr_point(m.group(2))
        if a and b:
            return GenDate(text, "BET", a, b, tolerance_years=tolerance_years)
        return None
    pt = _parse_fr_point(t)
    if not pt:
        return None
    return GenDate(text, qual, pt, tolerance_years=tolerance_years)


# ---------------------------------------------------------------------------- comparaisons

def years_between(j1: int, j2: int) -> float:
    return (j2 - j1) / YEAR_DAYS


def compare(a: GenDate, b: GenDate, tolerance_years: float = APPROX_YEARS) -> dict:
    """Compare deux dates : chevauchement des intervalles avec tolérance."""
    alo, ahi = a.interval
    blo, bhi = b.interval
    tol = int(tolerance_years * YEAR_DAYS)
    if ahi < blo:
        gap = blo - ahi
    elif bhi < alo:
        gap = alo - bhi
    else:
        gap = 0
    exact = a.is_exact_day and b.is_exact_day and alo == blo
    return {
        "compatible": gap <= tol,
        "identique": exact,
        "ecart_annees": round(gap / YEAR_DAYS, 2),
        "chevauchement": gap == 0,
    }


def age_interval(birth: GenDate, at: GenDate) -> tuple[float, float]:
    """Âge minimal et maximal (en années) à la date `at`."""
    blo, bhi = birth.interval
    alo, ahi = at.interval
    return max(0.0, years_between(bhi, alo)), years_between(blo, ahi)


def birth_from_age(at: GenDate, age_years: float, age_months: float = 0, age_days: float = 0,
                   approximate: bool = True) -> GenDate:
    """Naissance déduite d'un âge déclaré (décès, mariage, recensement)."""
    alo, ahi = at.interval
    total = age_years + age_months / 12 + age_days / YEAR_DAYS
    lo = alo - int((total + 1) * YEAR_DAYS)
    hi = ahi - int(total * YEAR_DAYS)
    if approximate:
        # âges déclarés souvent arrondis : on élargit de la tolérance usuelle
        lo -= int(APPROX_YEARS * YEAR_DAYS)
        hi += int(APPROX_YEARS * YEAR_DAYS)
    y1 = jdn_to_gregorian(lo)[0]
    y2 = jdn_to_gregorian(hi)[0]
    g = GenDate(f"calculé d'après âge {age_years} au {at.original}", "BET",
                DatePoint("GREGORIAN", y1), DatePoint("GREGORIAN", y2))
    return g


def parse_age(text: str) -> tuple[float, float, float] | None:
    """'45y 3m', '45 ans', '45 ans 3 mois', '3m', '> 45y' -> (ans, mois, jours)."""
    if not text:
        return None
    t = _strip(text.lower())
    y = m = d = 0.0
    found = False
    for pat, unit in ((r"(\d+)\s*(?:y|ans?|annees?)", "y"), (r"(\d+)\s*(?:m|mois)\b", "m"),
                      (r"(\d+)\s*(?:d|j|jours?)\b", "d"), (r"(\d+)\s*(?:w|semaines?)\b", "w")):
        mm = re.search(pat, t)
        if mm:
            found = True
            v = float(mm.group(1))
            if unit == "y":
                y = v
            elif unit == "m":
                m = v
            elif unit == "d":
                d = v
            else:
                d += v * 7
    if not found:
        mm = re.fullmatch(r"\s*[<>]?\s*(\d+)\s*", t)
        if mm:
            return float(mm.group(1)), 0.0, 0.0
        return None
    return y, m, d


def convert(text: str) -> dict:
    """Conversion lisible : toutes les représentations d'une date."""
    g = parse_date(text)
    if not g:
        return {"erreur": f"Date non reconnue : {text!r}"}
    out = g.to_dict()
    if g.qualifier is None and g.start.day:
        j = g.start.bounds()[0]
        y, m, d = jdn_to_julian(j)
        out["equivalent_julien"] = f"{d:02d}/{m:02d}/{y}"
        out["jour_semaine"] = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"][j % 7]
    out["gedcom_551"] = g.gedcom(5)
    return out
