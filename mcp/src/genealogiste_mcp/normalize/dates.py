"""Dates généalogiques : GEDCOM 7/5.5.1, texte français ; calendriers grégorien, julien, républicain, hébreu et,
en extension, ceux que Gramps connaît en plus (persan, islamique, suédois : docs/gedcom-extensions.md).

Toute date est réduite à un intervalle de jours juliens [jdn_min, jdn_max] dans lequel
l'événement a eu lieu, ce qui permet les comparaisons avec tolérance (±2 ans par défaut).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, replace

from .calendriers import SDN, YMD

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


# ---------------------------------------------------------------------------- calendriers

# Calendriers du modèle, dans l'ordre de Gramps (Date.CALENDARS) : ceux de GEDCOM 7 (GREGORIAN, JULIAN, HEBREW,
# FRENCH_R) et trois calendriers d'extension pour ceux que Gramps connaît en plus (docs/gedcom-extensions.md).
CALENDRIERS = ("GREGORIAN", "JULIAN", "HEBREW", "FRENCH_R", "_PERSIAN", "_ISLAMIC", "_SWEDISH")
HEBREW_MONTHS = ["TSH", "CSH", "KSL", "TVT", "SHV", "ADR", "ADS", "NSN", "IYR", "SVN", "TMZ", "AAV", "ELL"]
PERSIAN_MONTHS = ["FARVA", "ORDIB", "KHORD", "TIR", "MORDA", "SHAHR", "MEHR", "ABAN", "AZAR", "DEY", "BAHMA",
                  "ESFAN"]
ISLAMIC_MONTHS = ["MUHAR", "SAFAR", "RABIA", "RABIT", "JUMAA", "JUMAT", "RAJAB", "SHAAB", "RAMAD", "SHAWW",
                  "DHUAQ", "DHUAH"]
MONTHS = {"GREGORIAN": GREG_MONTHS, "JULIAN": GREG_MONTHS, "HEBREW": HEBREW_MONTHS, "FRENCH_R": FRENCH_MONTHS,
          "_PERSIAN": PERSIAN_MONTHS, "_ISLAMIC": ISLAMIC_MONTHS, "_SWEDISH": GREG_MONTHS}
NOMS_CALENDRIERS = {"GREGORIAN": "grégorien", "JULIAN": "julien", "HEBREW": "hébreu", "FRENCH_R": "républicain",
                    "_PERSIAN": "persan", "_ISLAMIC": "islamique", "_SWEDISH": "suédois"}
MONTH_NAMES = {
    "HEBREW": ["tishri", "heshvan", "kislev", "tevet", "shevat", "adar I", "adar II", "nissan", "iyar", "sivan",
               "tamouz", "av", "eloul"],
    "_PERSIAN": ["farvardin", "ordibehecht", "khordad", "tir", "mordad", "chahrivar", "mehr", "aban", "azar", "dey",
                 "bahman", "esfand"],
    "_ISLAMIC": ["mouharram", "safar", "rabia al-awal", "rabia ath-thani", "joumada al-oula", "joumada ath-thania",
                 "rajab", "chaabane", "ramadan", "chawwal", "dhou al-qi'da", "dhou al-hijja"],
}
ESCAPES_551 = {"JULIAN": "@#DJULIAN@", "FRENCH_R": "@#DFRENCH R@", "HEBREW": "@#DHEBREW@"}
# Nouvel an décalé (Gramps : Date.newyear) : code -> nom écrit, et coupure (mois, jour)
NOUVEL_AN = {1: "Mar1", 2: "Mar25", 3: "Sep1"}
COUPURES = {1: (3, 1), 2: (3, 25), 3: (9, 1)}
_SDN_DIRECT = {"HEBREW", "_PERSIAN", "_ISLAMIC", "_SWEDISH"}  # bornes par les calendriers de Gramps


def nouvel_an_texte(ny) -> str:
    """Code Gramps (1, 2, 3) ou (mois, jour) -> « Mar1 », « Mar25 », « Sep1 », « 4-15 »."""
    if isinstance(ny, (list, tuple)):
        return f"{ny[0]}-{ny[1]}"
    return NOUVEL_AN.get(ny, "")


def _nouvel_an(s: str):
    for k, v in NOUVEL_AN.items():
        if v.upper() == s.upper():
            return k
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", s)
    if m and 1 <= int(m[1]) <= 12 and 1 <= int(m[2]) <= 31:
        return int(m[1]), int(m[2])
    return None


def coupure(ny) -> tuple[int, int] | None:
    """Premier (mois, jour) de l'année pour un nouvel an Gramps, None au 1er janvier."""
    c = tuple(ny) if isinstance(ny, (list, tuple)) else COUPURES.get(ny)
    return c if c and c != (0, 0) else None


# ---------------------------------------------------------------------------- modèle

@dataclass
class DatePoint:
    calendar: str  # GREGORIAN | JULIAN | HEBREW | FRENCH_R | _PERSIAN | _ISLAMIC | _SWEDISH
    year: int  # 0 : année inconnue (« ? ») ; négative : avant notre ère (-1 = 1 BCE, comme Gramps)
    month: int | None = None
    day: int | None = None
    dual: bool = False  # double datation « 1721/22 » : year = 1722 (année nouveau style, comme Gramps)

    def validate(self) -> DatePoint:
        """Composantes possibles dans leur calendrier, sinon ValueError au message clair (#46)."""
        y, m, d = self.year, self.month, self.day
        cal = NOMS_CALENDRIERS.get(self.calendar)
        if cal is None:
            raise ValueError(f"Calendrier inconnu : {self.calendar}")
        if not y or (y < 0 and self.calendar not in ("GREGORIAN", "JULIAN")) \
                or (self.calendar == "FRENCH_R" and y > 20):
            raise ValueError(f"Année impossible dans le calendrier {cal} : {y}")
        if m is None:
            if d is not None:
                raise ValueError("Jour sans mois")
            return self
        if not 1 <= m <= len(MONTHS[self.calendar]):
            raise ValueError(f"Mois impossible dans le calendrier {cal} : {m}")
        if d is None:
            return self
        if self.calendar in _SDN_DIRECT:
            i = CALENDRIERS.index(self.calendar)
            if not 1 <= d <= 31 or YMD[i](SDN[i](y, m, d)) != (y, m, d):
                raise ValueError(f"Jour impossible : {d}/{m}/{y} (calendrier {cal})")
            return self
        if self.calendar == "FRENCH_R":
            last = 30 if m <= 12 else french_year_length(y) - 360
        elif m == 2:
            a = y + 1 if y < 0 else y  # année astronomique : 1 BCE = 0, bissextile
            leap = a % 4 == 0 if self.calendar == "JULIAN" else (a % 4 == 0 and (a % 100 != 0 or a % 400 == 0))
            last = 29 if leap else 28
        else:
            last = 30 if m in (4, 6, 9, 11) else 31
        if not 1 <= d <= last:
            raise ValueError(f"Jour impossible : {d}/{m}/{y} (calendrier {cal}, {last} jours dans ce mois)")
        return self

    def bounds(self) -> tuple[int, int]:
        self.validate()
        y, m, d = self.year, self.month, self.day
        if self.calendar in _SDN_DIRECT or y < 0:
            return self._bounds_gramps()
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

    def _bounds_gramps(self) -> tuple[int, int]:
        """Bornes par les calendriers de Gramps (hébreu, persan, islamique, suédois, années avant notre ère)."""
        i = CALENDRIERS.index(self.calendar)
        sdn, ymd = SDN[i], YMD[i]
        y, m, d = self.year, self.month, self.day
        if d:
            j = sdn(y, m, d)
            return j, j
        if m:
            fin = next((sdn(y, m, j) for j in range(31, 27, -1) if ymd(sdn(y, m, j)) == (y, m, j)), sdn(y, m, 1))
            return sdn(y, m, 1), fin
        suivante = 1 if y == -1 else y + 1
        return sdn(y, 1, 1), sdn(suivante, 1, 1) - 1

    def _annee(self, version: int) -> str:
        y = abs(self.year)
        if not y:
            return "?"
        s = f"{y - 1}/{y % 100:02d}" if self.dual else str(y)
        if self.year < 0:
            s += " BCE" if version >= 7 else " B.C."
        return s

    def gedcom(self, version: int = 7) -> str:
        months = MONTHS.get(self.calendar, GREG_MONTHS)
        parts = []
        if self.day:
            parts.append(str(self.day))
        if self.month:
            parts.append(months[self.month - 1])
        elif self.day:
            parts.append("?")
        parts.append(self._annee(version))
        body = " ".join(parts)
        if self.calendar == "GREGORIAN":
            return body
        if version >= 7 or self.calendar not in ESCAPES_551:
            return f"{self.calendar} {body}"
        return ESCAPES_551[self.calendar] + " " + body

    def texte(self) -> str:
        if self.year == 0 and not self.month and not self.day:
            return "date inconnue"
        if self.calendar == "FRENCH_R":
            parts = []
            if self.day:
                parts.append("1er" if self.day == 1 else str(self.day))
            if self.month:
                parts.append(FRENCH_MONTH_NAMES[self.month - 1])
            parts.append(f"an {int_to_roman(self.year)}" if self.year > 0 else "année inconnue")
            return " ".join(parts)
        noms = MONTH_NAMES.get(self.calendar, GREG_MONTH_NAMES_FR)
        parts = []
        if self.day:
            parts.append("1er" if self.day == 1 else str(self.day))
        if self.month:
            parts.append(noms[self.month - 1])
        elif self.day:
            parts.append("(mois inconnu)")
        y = abs(self.year)
        if y:
            parts.append(f"{y - 1}/{y % 100:02d}" if self.dual else str(y))
            if self.year < 0:
                parts.append("av. J.-C.")
        else:
            parts.append("(année inconnue)")
        s = " ".join(parts)
        if self.calendar != "GREGORIAN":
            s += f" ({NOMS_CALENDRIERS.get(self.calendar, self.calendar)})"
        return s


@dataclass
class GenDate:
    original: str
    qualifier: str | None  # None | ABT | CAL | EST | BEF | AFT | BET | FROM | TO | FROMTO
    start: DatePoint | None
    end: DatePoint | None = None
    phrase: str | None = None
    tolerance_years: int = APPROX_YEARS
    quality: str | None = None  # EST | CAL combinée à un qualificatif (« EST BEF 1850 », forme Gramps)
    newyear: int | tuple[int, int] = 0  # nouvel an décalé de Gramps (« (Mar25) ») : code ou (mois, jour)

    def _bornes(self, p: DatePoint) -> tuple[int, int]:
        """Bornes d'un point ; nouvel an décalé : année diminuée d'un à partir de la coupure, comme le fait Gramps
        (``Date._adjust_newyear``)."""
        lo, hi = p.bounds()
        c = coupure(self.newyear) if self.newyear else None
        if not c or not p.year:
            return lo, hi
        try:
            prec = replace(p, year=p.year - 1 if p.year != 1 else -1, dual=False)
            if p.month and p.day:
                return prec.bounds() if (p.month, p.day) >= c else (lo, hi)
            if p.month:
                return (prec.bounds()[0] if (p.month, 1) >= c else lo,
                        prec.bounds()[1] if (p.month, 31) >= c else hi)
            return (DatePoint(p.calendar, prec.year, *c).bounds()[0],
                    DatePoint(p.calendar, p.year, *c).bounds()[0] - 1)
        except ValueError:
            return lo, hi

    @property
    def interval(self) -> tuple[int, int]:
        """Intervalle [min, max] en jours juliens (grégorien proleptique)."""
        lo, hi = self._bornes(self.start)
        span = int(round(self.tolerance_years * YEAR_DAYS))
        q = self.qualifier
        if q in ("ABT", "CAL", "EST"):
            return lo - span, hi + span
        if q == "BEF":
            return lo - int(100 * YEAR_DAYS), lo - 1
        if q == "AFT":
            return hi + 1, hi + int(100 * YEAR_DAYS)
        if q in ("BET", "FROMTO") and self.end:
            return lo, self._bornes(self.end)[1]
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
        if self.quality:
            out = f"{self.quality} {out}"
        if self.newyear:
            out += f" ({nouvel_an_texte(self.newyear)})"
        return out

    def texte(self) -> str:
        labels = {"ABT": "vers", "CAL": "calculé", "EST": "estimé", "BEF": "avant", "AFT": "après",
                  "FROM": "depuis", "TO": "jusqu'à"}
        q = self.qualifier
        s = self.start.texte()
        if q == "BET":
            out = f"entre {s} et {self.end.texte()}"
        elif q == "FROMTO":
            out = f"de {s} à {self.end.texte()}"
        elif q in labels:
            out = f"{labels[q]} {s}"
        else:
            out = s
        if self.quality:
            out = f"{labels[self.quality]} : {out}"
        if self.newyear:
            out += f" (nouvel an : {nouvel_an_texte(self.newyear)})"
        return out

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
        if self.quality:
            d["qualite"] = self.quality
        if self.newyear:
            d["nouvel_an"] = nouvel_an_texte(self.newyear)
        if self.start.calendar != "GREGORIAN" and self.qualifier is None:
            a, b = self._bornes(self.start)
            d["equivalent_gregorien"] = iso(a) if a == b else f"{iso(a)} / {iso(b)}"
        if self.start.calendar == "GREGORIAN" and self.qualifier is None and self.start.day and not self.newyear:
            j = self.start.bounds()[0]
            if FRENCH_EPOCH <= j <= gregorian_to_jdn(1805, 12, 31):
                an, m, dd = jdn_to_french(j)
                d["equivalent_republicain"] = DatePoint("FRENCH_R", an, m, dd).texte()
        point = asdict(self.start)
        if not point.pop("dual"):
            d["point"] = point
        else:
            d["point"] = {**point, "double_datation": True}
        return d


# ---------------------------------------------------------------------------- analyse GEDCOM

_CAL_RE = re.compile(r"^(?:@#D(JULIAN|GREGORIAN|FRENCH R|HEBREW)@|(JULIAN|GREGORIAN|FRENCH_R|HEBREW|_PERSIAN"
                     r"|_ISLAMIC|_SWEDISH))\s+")
_BCE = ("BCE", "B.C.", "BC")
# nouvel an de Gramps puis phrase éventuelle : « 12 FEB 1721 (Mar25) (texte) »
_NY_RE = re.compile(r"^(.*?\S)\s*\((MAR1|MAR25|SEP1|\d{1,2}-\d{1,2})\)(?:\s*\((.*)\))?\s*$", re.IGNORECASE)
_QUAL_RE = re.compile(r"^(EST|CAL)\s+((?:ABT|BEF|AFT|BET|FROM|TO)\s+.*)$")


def _parse_point(text: str, strict: bool = True) -> DatePoint:
    """Un point de date GEDCOM. ``strict`` : composantes validées dans leur calendrier (sinon seulement la forme :
    « ? » pour une année, un mois ou un point inconnus, comme Gramps les admet)."""
    text = text.strip()
    cal = "GREGORIAN"
    m = _CAL_RE.match(text)
    if m:
        cal = (m.group(1) or m.group(2)).replace("FRENCH R", "FRENCH_R")
        text = text[m.end():]
    tokens = text.split()
    if tokens == ["?"] and not strict:
        return DatePoint(cal, 0)
    neg = bool(tokens) and tokens[-1] in _BCE
    if neg:
        tokens = tokens[:-1]
    if not tokens:
        raise ValueError("Date vide")
    year_tok = tokens[-1]
    dual = False
    if year_tok == "?" and not neg:
        year = 0
    elif re.fullmatch(r"\d{1,4}(/\d{1,4})?", year_tok):
        year = int(year_tok.split("/")[0])
        if "/" in year_tok:  # double datation 1721/22 : année nouveau style, comme Gramps
            year, dual = year + 1, True
        year = -year if neg else year
    else:
        raise ValueError(f"Année invalide : {year_tok}")
    month = day = None
    months = MONTHS[cal]
    if len(tokens) >= 2:
        mon = tokens[-2].upper()
        if mon != "?":
            if mon not in months:
                raise ValueError(f"Mois inconnu : {tokens[-2]}")
            month = months.index(mon) + 1
    if len(tokens) >= 3:
        if not tokens[-3].isdigit():
            raise ValueError(f"Jour invalide : {tokens[-3]}")
        day = int(tokens[-3])
    pt = DatePoint(cal, year, month, day, dual)
    if strict:
        pt.bounds()  # validation
    elif (year == 0 and (month, day) == (None, None)) or (month is None and len(tokens) >= 2 and day is None):
        raise ValueError("Point incomplet")
    return pt


def _ordered(g: GenDate) -> GenDate:
    if g._bornes(g.start)[0] > g._bornes(g.end)[1]:
        raise ValueError(f"Intervalle inversé : {g.start.gedcom()} est après {g.end.gedcom()}")
    return g


def date_problem(text: str) -> str:
    """Motif précis du refus d'une date (composante impossible, intervalle inversé…), ou "" si elle est valide
    ou simplement non reconnue."""
    g = analyser_gedcom(text)
    if g is not None:
        try:
            _verifier(g)
            return ""
        except ValueError as exc:
            msg = str(exc)
            if not msg.startswith(("Mois inconnu", "Année invalide", "Date vide")):
                return msg
    try:
        _parse_fr_point(_strip(text.lower()))
    except ValueError as exc:
        return str(exc)
    return ""


def _decouper(raw: str) -> tuple[str, int | tuple[int, int], str | None]:
    """Date -> (cœur, nouvel an, phrase)."""
    m = _NY_RE.match(raw)
    if m and _nouvel_an(m.group(2)) is not None:
        return m.group(1).strip(), _nouvel_an(m.group(2)), m.group(3)
    pm = re.search(r"\((.*)\)\s*$", raw)
    if pm:
        return raw[: pm.start()].strip(), 0, pm.group(1)
    return raw, 0, None


def analyser_gedcom(value: str) -> GenDate | None:
    """Forme d'une date GEDCOM (7, 5.5.1, extensions de docs/gedcom-extensions.md) sans contrôle des composantes ni
    de l'ordre d'un intervalle : sert à la correspondance avec Gramps, qui admet une année ou un mois inconnus
    (« ? ») et fait son propre contrôle. Pour le sens d'une date : :func:`parse_gedcom_date`."""
    if not value or not value.strip():
        return None
    raw = value.strip()
    s, ny, phrase = _decouper(raw)
    if not s:
        return None
    up = s.upper()
    quality = None
    qm = _QUAL_RE.match(up)
    if qm:
        quality, up = qm.group(1), qm.group(2)
    try:
        m = re.match(r"^BET\s+(.+?)\s+AND\s+(.+)$", up)
        if m:
            g = GenDate(raw, "BET", _parse_point(m.group(1), False), _parse_point(m.group(2), False), phrase)
        else:
            m = re.match(r"^FROM\s+(.+?)\s+TO\s+(.+)$", up)
            if m:
                g = GenDate(raw, "FROMTO", _parse_point(m.group(1), False), _parse_point(m.group(2), False),
                            phrase)
            else:
                q = next((q for q in ("ABT", "CAL", "EST", "BEF", "AFT", "FROM", "TO", "INT")
                          if up.startswith(q + " ")), None)
                if quality and q in (None, "INT", "CAL", "EST"):
                    return None
                g = GenDate(raw, None if q == "INT" else q, _parse_point(up[len(q) + 1:] if q else up, False),
                            None, phrase)
    except (ValueError, IndexError):
        return None
    g.quality, g.newyear = quality, ny
    return g


def _verifier(g: GenDate) -> GenDate:
    for p in (g.start, g.end):
        if p is not None:
            p.bounds()
    if g.newyear and g.start.calendar not in ("GREGORIAN", "JULIAN", "_SWEDISH"):
        raise ValueError("Nouvel an décalé impossible dans ce calendrier")
    if g.end is not None:
        _ordered(g)
    return g


def parse_gedcom_date(value: str) -> GenDate | None:
    g = analyser_gedcom(value)
    if g is None:
        return None
    try:
        return _verifier(g)
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
        return DatePoint("GREGORIAN", int(m.group(1)), int(m.group(2)), int(m.group(3))).validate()
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", t)
    if m:
        return DatePoint("GREGORIAN", int(m.group(3)), int(m.group(2)), int(m.group(1))).validate()
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", t)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return DatePoint("GREGORIAN", y, mo or None, (d or None) if mo else None).validate()
    julian = "julien" in t or "vieux style" in t
    t = t.replace("julien", "").replace("(", "").replace(")", "").replace("vieux style", "").strip()
    m = re.fullmatch(r"(?:(\d{1,2})\s+)?([a-z0-9]+)\.?\s+(\d{3,4})", t)
    if m and m.group(2) in FR_MONTHS_TEXT:
        return DatePoint("JULIAN" if julian else "GREGORIAN", int(m.group(3)), FR_MONTHS_TEXT[m.group(2)],
                         int(m.group(1)) if m.group(1) else None).validate()
    m = re.fullmatch(r"(\d{3,4})", t)
    if m:
        return DatePoint("JULIAN" if julian else "GREGORIAN", int(m.group(1))).validate()
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
    try:
        m = re.match(r"^entre\s+(.+?)\s+et\s+(.+)$", t)
        if m:
            a, b = _parse_fr_point(m.group(1)), _parse_fr_point(m.group(2))
            if a and b:
                return _ordered(GenDate(text, "BET", a, b, tolerance_years=tolerance_years))
            return None
        pt = _parse_fr_point(t)
    except (ValueError, IndexError):  # composante impossible : jamais d'exception brute (#46)
        return None
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
        why = date_problem(text)
        return {"erreur": f"Date impossible : {text!r} — {why}" if why else f"Date non reconnue : {text!r}"}
    out = g.to_dict()
    if g.qualifier is None and g.start.day:
        j = g.start.bounds()[0]
        y, m, d = jdn_to_julian(j)
        out["equivalent_julien"] = f"{d:02d}/{m:02d}/{y}"
        out["jour_semaine"] = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"][j % 7]
    out["gedcom_551"] = g.gedcom(5)
    return out
