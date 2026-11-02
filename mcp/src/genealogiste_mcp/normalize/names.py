"""Noms : normalisation, variantes orthographiques, latin des registres, particules, surnoms « dit »."""

from __future__ import annotations

import re
import unicodedata

PARTICLES = {"de", "du", "des", "de la", "de l", "d", "le", "la", "les", "l", "van", "von", "der", "den", "di", "da"}

# Formes latines (nominatif et cas obliques courants) -> prénom français
LATIN_GIVEN = {
    "joannes": "Jean", "johannes": "Jean", "joanne": "Jean", "joannis": "Jean", "joannem": "Jean", "joanni": "Jean",
    "joannes baptista": "Jean-Baptiste", "joannes baptistae": "Jean-Baptiste",
    "petrus": "Pierre", "petri": "Pierre", "petrum": "Pierre", "petro": "Pierre",
    "jacobus": "Jacques", "jacobi": "Jacques", "jacobum": "Jacques",
    "franciscus": "François", "francisci": "François", "franciscum": "François",
    "ludovicus": "Louis", "ludovici": "Louis", "ludovicum": "Louis", "lodoicus": "Louis",
    "carolus": "Charles", "caroli": "Charles", "carolum": "Charles",
    "nicolaus": "Nicolas", "nicolai": "Nicolas", "nicolaum": "Nicolas",
    "stephanus": "Étienne", "stephani": "Étienne", "stephanum": "Étienne",
    "guillelmus": "Guillaume", "guillelmi": "Guillaume", "gulielmus": "Guillaume", "guilielmus": "Guillaume",
    "antonius": "Antoine", "antonii": "Antoine", "antonium": "Antoine",
    "claudius": "Claude", "claudii": "Claude", "claudium": "Claude",
    "michael": "Michel", "michaelis": "Michel", "michaelem": "Michel",
    "andreas": "André", "andreae": "André", "andream": "André",
    "martinus": "Martin", "martini": "Martin", "martinum": "Martin",
    "renatus": "René", "renati": "René", "renatum": "René",
    "egidius": "Gilles", "aegidius": "Gilles", "egidii": "Gilles",
    "dionysius": "Denis", "dionysii": "Denis",
    "laurentius": "Laurent", "laurentii": "Laurent",
    "matthaeus": "Mathieu", "mathaeus": "Mathieu", "matthaei": "Mathieu",
    "josephus": "Joseph", "josephi": "Joseph", "josephum": "Joseph",
    "hugo": "Hugues", "hugonis": "Hugues",
    "gabriel": "Gabriel", "gabrielis": "Gabriel",
    "thomas": "Thomas", "thomae": "Thomas",
    "simon": "Simon", "simonis": "Simon",
    "julianus": "Julien", "juliani": "Julien",
    "vincentius": "Vincent", "vincentii": "Vincent",
    "benedictus": "Benoît", "benedicti": "Benoît",
    "bartholomaeus": "Barthélemy", "bartholomaei": "Barthélemy",
    "georgius": "Georges", "georgii": "Georges",
    "honoratus": "Honoré", "honorati": "Honoré",
    "maria": "Marie", "mariae": "Marie", "mariam": "Marie",
    "anna": "Anne", "annae": "Anne", "annam": "Anne",
    "joanna": "Jeanne", "johanna": "Jeanne", "joannae": "Jeanne", "joannam": "Jeanne",
    "margarita": "Marguerite", "margaritae": "Marguerite", "margareta": "Marguerite",
    "catharina": "Catherine", "catharinae": "Catherine", "catherina": "Catherine",
    "francisca": "Françoise", "franciscae": "Françoise",
    "elisabetha": "Élisabeth", "elisabeth": "Élisabeth", "elisabethae": "Élisabeth",
    "magdalena": "Madeleine", "magdalenae": "Madeleine",
    "ludovica": "Louise", "ludovicae": "Louise",
    "petronilla": "Perrine", "petronillae": "Perrine", "petronella": "Perrine",
    "susanna": "Suzanne", "susannae": "Suzanne",
    "barbara": "Barbe", "barbarae": "Barbe",
    "agatha": "Agathe", "agathae": "Agathe",
    "nicolaa": "Nicole", "nicolea": "Nicole",
    "antonia": "Antoinette", "antoniae": "Antoinette",
    "claudia": "Claudine", "claudiae": "Claudine",
    "genovefa": "Geneviève", "genovefae": "Geneviève",
    "juliana": "Julienne", "julianae": "Julienne",
    "renata": "Renée", "renatae": "Renée",
    "michaela": "Michelle",
    "helena": "Hélène", "helenae": "Hélène",
}

# Variantes françaises usuelles -> forme de référence
GIVEN_VARIANTS = {
    "jehan": "jean", "jan": "jean", "johan": "jean",
    "jacque": "jacques", "jaques": "jacques",
    "francois": "francois", "francoys": "francois",
    "estienne": "etienne", "anthoine": "antoine", "anthoyne": "antoine",
    "guilaume": "guillaume", "nicollas": "nicolas", "mathieu": "mathieu", "matthieu": "mathieu",
    "magdelaine": "madeleine", "magdeleine": "madeleine", "madelaine": "madeleine",
    "marguerite": "marguerite", "margueritte": "marguerite",
    "catherine": "catherine", "catharine": "catherine", "katherine": "catherine",
    "elisabeth": "elisabeth", "elizabeth": "elisabeth", "isabeau": "elisabeth", "isabelle": "elisabeth",
    "perrine": "perrine", "perine": "perrine", "pierrette": "perrine",
    "jeanne": "jeanne", "jehanne": "jeanne",
    "loys": "louis", "louys": "louis",
    "denys": "denis", "gilles": "gilles", "gille": "gilles",
}

LATIN_SURNAME_ENDINGS = ("ius", "us", "ii", "um", "is", "em", "ae", "am", "i", "o", "a")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def basic(s: str) -> str:
    s = strip_accents(s or "").lower()
    s = s.replace("’", "'").replace("œ", "oe").replace("æ", "ae")
    s = re.sub(r"[^a-z' -]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def split_dit(surname: str) -> tuple[str, list[str]]:
    """'MARTIN dit LAFLEUR' -> ('MARTIN', ['LAFLEUR'])."""
    parts = re.split(r"\s+(?:dit|dite|dits|alias|ou)\s+", surname.strip(), flags=re.I)
    return parts[0].strip(), [p.strip() for p in parts[1:] if p.strip()]


def strip_particles(surname: str) -> tuple[str, str]:
    """('de la Fontaine') -> ('fontaine', 'de la')."""
    s = basic(surname).replace("'", "' ")
    tokens = s.split()
    particle = []
    while len(tokens) > 1:
        two = " ".join(tokens[:2]).replace("'", "")
        one = tokens[0].replace("'", "")
        if two in PARTICLES:
            particle += tokens[:2]
            tokens = tokens[2:]
        elif one in PARTICLES:
            particle.append(tokens[0])
            tokens = tokens[1:]
        else:
            break
    return " ".join(tokens).replace("' ", "'"), " ".join(particle).replace("' ", "'")


def latin_to_french(given: str) -> str | None:
    key = basic(given)
    if key in LATIN_GIVEN:
        return LATIN_GIVEN[key]
    return None


def normalize_given(given: str) -> list[str]:
    """Liste de prénoms normalisés (latin traduit, variantes ramenées à la forme de référence)."""
    if not given:
        return []
    out = []
    g = basic(given)
    fr = latin_to_french(g)
    if fr:
        g = basic(fr)
    for tok in re.split(r"[\s-]+", g):
        if not tok:
            continue
        fr = latin_to_french(tok)
        if fr:
            tok = basic(fr)
        out.append(GIVEN_VARIANTS.get(tok, tok))
    return out


def phonetic_fr(word: str) -> str:
    """Clé phonétique française simplifiée (inspirée de Phonex/Soundex-FR).

    Rapproche les graphies anciennes : Lefebvre/Lefèvre/Lefeuvre, Dupont/Dupond, Thibault/Thibaut.
    """
    s = strip_accents(word or "").upper()
    s = re.sub(r"[^A-Z]", "", s)
    if not s:
        return ""
    rules = [
        (r"AULT$", "O"), (r"AUD$", "O"), (r"(ER|EZ|ET|AY|AI|ES)$", "E"),
        (r"^MAC", "MAK"), (r"^MC", "MAK"), (r"Y", "I"), (r"PH", "F"), (r"TH", "T"), (r"GU([EI])", r"G\1"),
        (r"QU", "K"), (r"Q", "K"), (r"C([EI])", r"S\1"), (r"SCH", "CH"), (r"CH", "X"), (r"CK", "K"),
        (r"C", "K"), (r"G([EI])", r"J\1"), (r"GN", "NI"), (r"W", "V"), (r"Z", "S"),
        (r"EAUX?$", "O"), (r"EAU", "O"), (r"AUX?$", "O"), (r"AU", "O"), (r"AI", "E"), (r"EI", "E"),
        (r"OU", "U"), (r"OI", "UA"), (r"EU", "E"),
        (r"[AE]N(?=[^AEIOU]|$)", "A"), (r"[AE]M(?=[BP])", "A"), (r"[IE]IN(?=[^AEIOU]|$)", "I"),
        (r"IN(?=[^AEIOU]|$)", "I"), (r"ON(?=[^AEIOU]|$)", "O"), (r"OM(?=[BP])", "O"),
        (r"BV", "V"), (r"FV", "V"), (r"B(?=[RV])", ""), (r"PT", "T"),
        (r"(?<!^)H", ""), (r"^H", ""), (r"ILL", "I"), (r"LL", "L"),
        (r"(.)\1+", r"\1"),
    ]
    for pat, rep in rules:
        s = re.sub(pat, rep, s)
    s = re.sub(r"[DTSXZ]$", "", s) if len(s) > 2 else s
    s = re.sub(r"E$", "", s) if len(s) > 2 else s
    s = re.sub(r"(?<=.)[E](?=.)", "E", s)
    s = re.sub(r"(.)\1+", r"\1", s)
    return s


def normalize_surname(surname: str) -> dict:
    main, aliases = split_dit(surname or "")
    core, particle = strip_particles(main)
    return {
        "original": surname,
        "nom": core.upper(),
        "particule": particle,
        "dit": [a.upper() for a in aliases],
        "phonetique": phonetic_fr(core),
        "phonetique_dit": [phonetic_fr(strip_particles(a)[0]) for a in aliases],
    }


def latin_surname_stem(surname: str) -> str:
    """Retire une désinence latine probable ('Martini' -> 'martin')."""
    s = basic(surname)
    for end in LATIN_SURNAME_ENDINGS:
        if s.endswith(end) and len(s) - len(end) >= 4:
            return s[: -len(end)]
    return s


# ---------------------------------------------------------------------------- similarité

def jaro_winkler(a: str, b: str) -> float:
    if a == b:
        return 1.0 if a else 0.0
    if not a or not b:
        return 0.0
    match_dist = max(len(a), len(b)) // 2 - 1
    a_m = [False] * len(a)
    b_m = [False] * len(b)
    matches = 0
    for i, ca in enumerate(a):
        lo, hi = max(0, i - match_dist), min(i + match_dist + 1, len(b))
        for j in range(lo, hi):
            if not b_m[j] and b[j] == ca:
                a_m[i] = b_m[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    t = 0
    k = 0
    for i, ca in enumerate(a):
        if a_m[i]:
            while not b_m[k]:
                k += 1
            if ca != b[k]:
                t += 1
            k += 1
    t /= 2
    jaro = (matches / len(a) + matches / len(b) + (matches - t) / matches) / 3
    prefix = 0
    for ca, cb in zip(a[:4], b[:4], strict=False):
        if ca != cb:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


def surname_similarity(a: str, b: str) -> dict:
    na, nb = normalize_surname(a), normalize_surname(b)
    def forms(n):
        out = [n["nom"].lower()] + [d.lower() for d in n["dit"]]
        if n["particule"]:
            out.append((n["particule"] + n["nom"]).lower().replace(" ", "").replace("'", ""))
        return out

    forms_a, forms_b = forms(na), forms(nb)
    best = 0.0
    reason = "différents"
    for fa in forms_a:
        for fb in forms_b:
            if not fa or not fb:
                continue
            if fa == fb:
                return {"score": 1.0, "raison": "identiques (après normalisation)"}
            fa2, fb2 = fa.replace(" ", ""), fb.replace(" ", "")
            if fa2 == fb2:
                return {"score": 0.98, "raison": "identiques (particule agglutinée)"}
            if phonetic_fr(fa2) == phonetic_fr(fb2):
                v = max(0.92, jaro_winkler(fa2, fb2))
                if v > best:
                    best, reason = v, "variante phonétique"
            if latin_surname_stem(fa) == latin_surname_stem(fb):
                if best < 0.9:
                    best, reason = 0.9, "forme latinisée"
            jw = jaro_winkler(fa2, fb2)
            if jw > best:
                best, reason = jw, f"similarité orthographique {jw:.2f}"
    return {"score": round(best, 3), "raison": reason}


def given_similarity(a: str, b: str) -> dict:
    ga, gb = normalize_given(a), normalize_given(b)
    if not ga or not gb:
        return {"score": 0.5, "raison": "prénom manquant"}
    if ga == gb:
        return {"score": 1.0, "raison": "identiques (après normalisation/latin)"}
    sa, sb = set(ga), set(gb)
    common = sa & sb
    if common:
        # prénom d'usage souvent l'un des prénoms de baptême
        ratio = len(common) / min(len(sa), len(sb))
        return {"score": round(0.75 + 0.2 * ratio, 3), "raison": f"prénom(s) commun(s) : {', '.join(sorted(common))}"}
    best = 0.0
    for x in ga:
        for y in gb:
            if phonetic_fr(x) == phonetic_fr(y):
                best = max(best, 0.85)
            best = max(best, jaro_winkler(x, y) * 0.9)
    return {"score": round(best, 3), "raison": "prénoms différents" if best < 0.8 else "variante probable"}


def normalize_name(full: str = "", given: str = "", surname: str = "") -> dict:
    """Analyse d'un nom complet (« Jean Pierre MARTIN dit LAFLEUR » ou GEDCOM « Jean /MARTIN/ »)."""
    if full and not (given or surname):
        m = re.match(r"^(.*?)/(.*?)/(.*)$", full)
        if m:
            given, surname = m.group(1).strip(), m.group(2).strip()
        else:
            parts = full.split()
            up = [p for p in parts if p.isupper() and len(p) > 1]
            if up:
                idx = parts.index(up[0])
                given, surname = " ".join(parts[:idx]), " ".join(parts[idx:])
            elif parts:
                given, surname = " ".join(parts[:-1]), parts[-1]
    sur = normalize_surname(surname)
    latin = latin_to_french(given)
    return {
        "prenoms": given,
        "prenoms_normalises": normalize_given(given),
        "traduction_latin": latin,
        **{k: v for k, v in sur.items() if k != "original"},
        "nom_original": surname,
    }
