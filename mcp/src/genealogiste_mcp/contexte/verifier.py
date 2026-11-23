"""contexte_verifier (#324) : contrôle déterministe d'un texte de contexte (note, récit, billet), sans réseau.

Règles et listes fermées, versionnées (``VERSION_LISTES``), jamais un jugement du modèle. Pour un texte et une
personne de l'arbre :

1. **Phrases sans référence** : chaque phrase de la section « Contexte » porte un appel de note (``[1]``,
   ``[^1]``) ; une déclaration d'absence (« contexte non documenté », « contexte à documenter ») en est dispensée.
2. **Références non consultées** : chaque note appelée dans la section « Contexte » donne un identifiant pérenne
   (DOI, ARK, HAL, PPN, Handle, LCCN, Europeana, sinon URL) présent au registre des références consultées ; une note
   qui cite une source de l'arbre portant sur l'individu est une source individuelle, pas une référence de contexte.
3. **Portée** (``hors_portee``) : années citées hors de la période de vie sourcée (anachronisme), département ou
   pays cité hors des lieux de vie sourcés, phrase dont ni le texte ni la référence ne citent un lieu de vie.
4. **Causalités** : connecteur causal ou motif prêté (``CONNECTEURS``) appliqué à l'individu sans source
   individuelle, dans tout le texte (sauf questions et hypothèses déclarées).
5. **Formulations** : généralisation (``GENERALISATIONS``, tout le texte) ; dans la section « Contexte »,
   formulation contraire au niveau de rattachement déclaré (``compatible`` ou ``non démontré`` : aucune
   affirmation sur l'individu ; ``attesté`` : source individuelle) ou affirmation sur l'individu appuyée sur une
   seule référence de contexte ; mention « tendance générale » absente au-delà de la commune.

Format lu (celui du ``redacteur``, docs/notes.md, #291) : titres Markdown (``## Contexte``) ou ligne en gras seule
(``**Contexte**``, billet de Gramps Web) ; section des notes « Notes et sources » (ou « Notes », « Sources »,
« Références ») avec des lignes ``[1] citation``, ``1. citation`` ou ``[^1]: citation`` ; énoncés repris des
sources entre guillemets « ». Frontmatter, sections générées (``<!-- genealogiste:debut … -->``), commentaires
HTML et blocs de code sont ignorés.

``conforme`` est vrai seulement si aucune liste n'a d'entrée. Un texte conforme n'est pas un texte vrai : voir
``LIMITES``. Référence : docs/contexte-historique.md, « Rédaction et contrôle ».
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..marqueurs import BLOCK
from ..normalize.pays import PAYS, pays_par_nom
from ..normalize.places import DEPARTEMENTS
from .local import preparer
from .modeles import Identifiant, ReferenceInvalide
from .portee import _departement
from .registre import RegistreReferences

OUTIL = "contexte_verifier"
VERSION_LISTES = "1"
NON_DOCUMENTE = "contexte non documenté"
RAPPEL = ("Contrôle de forme, lexical et déterministe : « conforme » signifie qu'aucune règle n'a été enfreinte, pas "
          "que le texte est vrai. Relire chaque énoncé contre sa source. conforme: false bloque la publication d'un "
          "billet de Gramps Web.")

LIMITES = (
    f"Détection lexicale par listes fermées (version {VERSION_LISTES}) : connecteurs causaux et motifs prêtés, "
    "marqueurs de généralisation, formules de rattachement. Une paraphrase absente des listes n'est pas vue ; un "
    "mot des listes peut être signalé à tort (« grâce à », « chassé par » employés au sens propre).",
    "Découpage en phrases par la ponctuation finale, abréviations courantes et citations « » protégées ; un "
    "paragraphe ou un élément de liste est au moins une phrase. Un découpage erroné peut déplacer un appel de note.",
    "Référence consultée = identifiant présent au registre des références consultées (notice récupérée par le "
    "plugin). Le contrôle ne lit pas la source : il ne vérifie ni que l'énoncé dit ce que dit la notice, ni la page, "
    "ni la pertinence de la référence pour la phrase.",
    "Période : années à quatre chiffres (1000-2099), intervalles « 1880-1914 » et siècles en chiffres romains "
    "(« XIXe ») ; un nombre suivi d'une unité (habitants, morts, francs…) ou précédé de « n° », « p. » n'est pas une "
    "année. Une date en lettres ou un événement nommé sans année n'est pas vu.",
    "Lieux : communes, départements et pays des faits sourcés de la personne (requete.depuis_personne). Dans le "
    "texte, seuls les départements français et les pays de la table fermée sont reconnus (sensibles à la casse : "
    "« la Somme » rivière ou département) ; une province, une région ou une commune étrangère n'est vue que si rien "
    "d'autre ne situe la phrase.",
    "Les mots entre guillemets « » sont lus comme la citation d'une source : leurs années et leurs lieux de vie "
    "comptent pour la portée, mais ils ne sont pas lus comme affirmation (causalité, généralisation, lieu hors "
    "périmètre).",
    "L'individu est reconnu par ses prénoms, son nom et les pronoms il, elle, ils, elles, lui (tournures "
    "impersonnelles exclues) ; une tournure possessive (« son départ ») n'est pas vue.",
    "Source individuelle : note qui contient le titre d'une source de l'arbre citée pour un fait de la personne ou "
    "de ses unions. Le contrôle ne vérifie pas que cette source dit la cause ou le rattachement affirmés.",
    "Les appels de note, la présence au registre et la portée sont contrôlés dans la section « Contexte » "
    "seulement ; les causalités et les généralisations dans tout le texte, hors questions (phrase finissant par "
    "« ? ») et hypothèses déclarées (section « Hypothèses », conditionnel, « peut-être », « hypothèse »).",
)


# ------------------------------------------------------------------------------------------- listes fermées

@dataclass(frozen=True)
class Regle:
    """Entrée d'une liste fermée : ``motif`` (expression sur le texte aplati : minuscules, sans accents, apostrophes
    droites), ``categorie``, un ``exemple`` qui doit être signalé et un ``contre_exemple`` qui ne doit pas l'être
    (vérifiés par tests/test_contexte_verifier.py)."""

    cle: str
    motif: str
    categorie: str
    exemple: str
    contre_exemple: str

    def cherche(self, plat: str) -> re.Match | None:
        return re.search(self.motif, plat)


_D = r"d(?:e |u |es |')"  # de, du, des, d'
# Causalité : « causal » (connecteur appliqué à l'individu s'il est nommé ou désigné par un pronom), « causatif »
# (le pronom complément désigne l'individu : toujours appliqué), « motif » (intention ou sentiment prêté).
CONNECTEURS: tuple[Regle, ...] = (
    Regle("a_cause_de", rf"\ba cause {_D}", "causal", "Il émigra à cause de la crise minière.",
          "La route fut coupée à cause de la crue [1]."),
    Regle("en_raison_de", rf"\ben raison {_D}", "causal", "Elle quitta la paroisse en raison de la disette.",
          "Le marché fut déplacé en raison des travaux [1]."),
    Regle("pousse_par", r"\bpousse(?:e|s|es)? par\b", "causal", "Poussé par la misère, il partit pour Lille.",
          "Le chariot, poussé par deux hommes, traversa la place [1]."),
    Regle("fuyant", r"\bfuyants?\b", "causal", "Fuyant la crise, il gagna les États-Unis.",
          "Il habitait près de la ligne fuyante du marais."),
    Regle("c_est_pourquoi", r"\bc'est pourquoi\b", "causal", "La mine ferma ; c'est pourquoi il partit.",
          "La mine ferma en 1910 ; c'est pourquoi la commune perdit des habitants [1]."),
    Regle("contraint", rf"\bcontraint(?:e|s|es)? (?:par\b|{_D})", "causal", "Contraint par la guerre, il partit.",
          "Il contrôla le registre des contraintes [1]."),
    Regle("force_de", rf"\b(?:fut|a ete|est|etait|furent|ont ete) force(?:e|s|es)? {_D}", "causal",
          "Il fut forcé de quitter la paroisse.", "Il montra une grande force de caractère."),
    Regle("oblige_de", rf"\b(?:fut|a ete|est|etait|furent|ont ete|se vit|se voit) oblige(?:e|s|es)? {_D}", "causal",
          "Il se vit obligé de vendre sa terre.", "Il était l'obligé du seigneur."),
    Regle("par_consequent", r"\bpar consequent\b", "causal", "Il perdit son emploi et, par conséquent, il partit.",
          "La récolte fut mauvaise et, par conséquent, le prix du grain monta [1]."),
    Regle("en_consequence", r"\ben consequence\b", "causal", "Il perdit son emploi ; en conséquence, il partit.",
          "La récolte fut mauvaise ; en conséquence, le prix du grain monta [1]."),
    Regle("de_ce_fait", r"\bde ce fait\b", "causal", "La forge ferma ; de ce fait, il changea de métier.",
          "La forge ferma ; de ce fait, la rue perdit son atelier [1]."),
    Regle("du_fait_de", rf"\bdu fait {_D}", "causal", "Il partit du fait de la crise.",
          "Le pont fut fermé du fait de la crue [1]."),
    Regle("grace_a", r"\bgrace (?:a|au|aux)\b", "causal", "Il trouva du travail grâce à la mine.",
          "La commune s'agrandit grâce à la mine [1]."),
    Regle("faute_de", rf"\bfaute {_D}", "causal", "Faute de travail, il quitta la commune.",
          "Faute de travail, la commune se dépeupla [1]."),
    Regle("chasse_par", r"\bchasse(?:e|s|es)? par\b", "causal", "Chassé par la famine, il partit.",
          "La chasse par battue était réservée au seigneur [1]."),
    Regle("pour_fuir", rf"\b(?:pour|afin {_D}) (?:fuir|echapper)\b", "causal", "Il partit pour fuir la misère.",
          "Le gibier se cacha pour fuir les chasseurs [1]."),
    Regle("attire_par", r"\battire(?:e|s|es)? par\b", "causal", "Attiré par les salaires, il partit.",
          "Le bétail était attiré par le sel [1]."),
    Regle("parce_que", r"\bparce qu(?:e|')", "causal", "Il partit parce que la mine avait fermé.",
          "La mine ferma parce que le filon était épuisé [1]."),
    Regle("puisque", r"\bpuisqu(?:e|')", "causal", "Il partit, puisque la mine avait fermé.",
          "La mine ferma, puisque le filon était épuisé [1]."),
    Regle("car", r",\s*car\b", "causal", "Il partit, car la mine avait fermé.", "Il prit le car de Lille."),
    Regle("du_a", r"\bdu(?:e|s|es)? (?:a|au|aux)\b(?! \d)", "causal", "Il partit, son exil étant dû à la crise.",
          "La crue fut due à la fonte des neiges [1]."),
    Regle("cause_par", r"\b(?:cause|provoque)(?:e|s|es)? par\b", "causal",
          "Il partit, son départ étant provoqué par la crise.", "La catastrophe fut provoquée par un coup de grisou [1]."),
    Regle("ce_qui_explique", r"\bce qui (?:explique|expliquerait|motiva|motive)\b", "causal",
          "Il était mineur, ce qui explique son départ.", "La mine ferma, ce qui explique la baisse de "
          "population [1]."),
    Regle("causatif", r"(?:\bl'|\b(?:le|la|les) )(?:amena|amene|amenerent|conduisit|conduisirent|poussa|pousse"
                      r"|pousserent|obligea|oblige|obligerent|forca|force|forcerent|contraignit|decida|incita|incite)"
                      r" a\b", "causatif", "La misère le poussa à émigrer.",
          "Le courant porta le bateau à la rive [1]."),
    Regle("dans_l_espoir", rf"\bdans l'espoir {_D}", "motif", "Il partit dans l'espoir de faire fortune.",
          "La commune bâtit un pont dans l'espoir d'attirer le commerce [1]."),
    Regle("esperant", r"\besperant\b", "motif", "Espérant une vie meilleure, il partit.",
          "Les marchands, espérant la paix, rouvrirent la foire [1]."),
    Regle("desireux", rf"\bdesireu(?:x|se|ses) {_D}", "motif", "Désireux de s'établir, il acheta une terre.",
          "Les échevins, désireux de s'agrandir, achetèrent un pré [1]."),
    Regle("revant_de", rf"\brevant {_D}", "motif", "Rêvant d'Amérique, il partit.",
          "Le registre porte la mention « rêvant de paix » [1]."),
    Regle("par_motif", r"\bpar (?:patriotisme|conviction|necessite|ambition|misere|devoir|amour|ideal|desespoir"
                       r"|vocation)\b", "motif", "Il s'est engagé par patriotisme.",
          "Le monument fut élevé par souscription [1]."),
)

# Généralisation d'une tendance (époque, groupe, région) : interdite comme énoncé, sourcé ou non.
GENERALISATIONS: tuple[Regle, ...] = (
    Regle("a_cette_epoque", r"\ba cette epoque\b", "generalisation", "À cette époque, la vie était dure.",
          "À la même époque et au même endroit : « Notice sur la commune » [1]."),
    Regle("a_l_epoque", r"\ba l'epoque\b", "generalisation", "À l'époque, on se mariait jeune.",
          "Au même endroit et à la même époque : « Notice sur la commune » [1]."),
    Regle("en_ce_temps_la", r"\ben ce temps-?la\b", "generalisation", "En ce temps-là, on mourait jeune.",
          "Le registre de ce temps est perdu [1]."),
    Regle("de_tout_temps", r"\bde tout temps\b", "generalisation", "De tout temps, les paysans ont souffert.",
          "Le registre de toute la période est perdu [1]."),
    Regle("comme_tous_les", r"\bcomme tou(?:s|tes) (?:les|ses|leurs)\b", "generalisation",
          "Comme tous les poilus, il connut les tranchées.", "« Comme tous les ans » est le titre de la "
          "notice [1]."),
    Regle("comme_beaucoup", rf"\bcomme (?:beaucoup|la plupart|nombre|tant) {_D}", "generalisation",
          "Comme beaucoup de mineurs, il partit.", "Le registre compte un grand nombre de baptêmes [1]."),
    Regle("comme_ses_contemporains", r"\bcomme (?:ses|leurs) contemporains\b", "generalisation",
          "Comme ses contemporains, il savait à peine lire.", "Les contemporains sont cités dans la notice [1]."),
    Regle("beaucoup_de", rf"\bbeaucoup {_D}", "generalisation", "Beaucoup de journaliers quittaient la terre.",
          "« Beaucoup de bruit pour rien » est le titre de la pièce [1]."),
    Regle("la_plupart_des", r"\bla plupart (?:des|d')", "generalisation", "La plupart des laboureurs étaient "
          "illettrés.", "La part des laboureurs est donnée par la notice [1]."),
    Regle("en_general", r"\ben general\b", "generalisation", "En général, les familles étaient nombreuses.",
          "La tendance générale est mentionnée (tendance générale, ne prouve rien pour l'individu) [1]."),
    Regle("la_vie_etait", r"\bla vie (?:y )?etait\b", "generalisation", "La vie était dure dans les marais.",
          "La notice décrit la vie municipale [1]."),
    Regle("rythmee_par", r"\b(?:etait|etaient) rythmee?s? par\b", "generalisation",
          "Les journées étaient rythmées par les cloches.", "La notice décrit le rythme des foires [1]."),
    Regle("dans_cette_region", r"\bdans (?:cette|ces) (?:regions?|campagnes?|contrees?)\b", "generalisation",
          "Dans cette région rurale, on vivait de peu.", "Dans la commune, plus généralement : « Notice » [1]."),
    Regle("nos_ancetres", r"\bnos (?:ancetres|aieux)\b", "generalisation", "Nos ancêtres vivaient de la terre.",
          "L'ancêtre est cité dans la source [1]."),
    Regle("typique", r"\btypique(?:s|ment)?\b", "generalisation", "Il menait une vie typique de laboureur.",
          "La notice décrit la typologie des fermes [1]."),
)

# Formules de rattachement (#291) et mention de tendance (#321), sur le texte aplati.
FORMULE_COMPATIBLE = (r"\ba la meme epoque et au meme endroit\b|\bau meme endroit et a la meme epoque\b"
                      r"|\(rattachement ?: ?compatible\)")
FORMULE_NON_DEMONTRE = (r"\bplus generalement\b|\(rattachement ?: ?non demontre\)"
                        r"|\ba l'echelle (?:du departement|de la region|du pays|nationale|de la nation)\b")
FORMULE_ATTESTE = r"\(rattachement ?: ?atteste\)"
MENTION = r"\btendance generale\b"
ECHELLE_SUPERIEURE = (r"\bdans (?:le|ce) departement\b|\bdans (?:la|cette) region\b|\ba l'echelle\b"
                      r"|\bdans (?:le|ce) pays\b|\bdans (?:la|cette) nation\b")
HYPOTHESE = (r"\bhypothese\b|\bpeut-etre\b|\bil est possible qu|\bil se peut qu|\b(?:aurai(?:t|ent)|serai(?:t|ent)"
             r"|pourrai(?:t|ent)|devrai(?:t|ent))\b")
ABSENCE = r"^\W*(?:le\s+)?contexte (?:non documente|a documenter)\b"
PRONOMS = r"\b(?:il|elle|ils|elles|lui)\b|\bl'(?:individu|ancetre|interesse)\b|\bnotre ancetre\b"
IMPERSONNELS = (r"\bil (?:y a|y avait|y eut|n'y a|n'y avait|existe|existait|faut|fallait|s'agit|s'agissait|semble"
                r"|semblait|reste|restait|convient|se peut|est (?:possible|probable|vraisemblable|certain|difficile"
                r"|impossible|utile|necessaire))\b")

# Unités : un nombre de quatre chiffres suivi de l'une d'elles n'est pas une année (« 1099 morts »).
UNITES = (r"habitants?|hab\b|ames|feux|personnes|morts|victimes|tues|blesses|ouvriers|mineurs|soldats|hommes|femmes"
          r"|enfants|familles|maisons|francs|livres|sous|ecus|euros|hectares|ha\b|arpents|km|kilometres|metres|m\b"
          r"|tonnes|t\b|pages|p\b|%")
_SIECLES = {"XI": (1001, 1100), "XII": (1101, 1200), "XIII": (1201, 1300), "XIV": (1301, 1400),
            "XV": (1401, 1500), "XVI": (1501, 1600), "XVII": (1601, 1700), "XVIII": (1701, 1800),
            "XIX": (1801, 1900), "XX": (1901, 2000), "XXI": (2001, 2100)}

# Sections reconnues (titre aplati, sans ponctuation finale).
SECTIONS_NOTES = ("notes et sources", "notes", "sources", "references", "notes et references", "sources et notes",
                  "bibliographie")


# ------------------------------------------------------------------------------------------- texte aplati

def plat(s: str) -> str:
    """Minuscules, sans accents, apostrophes et espaces normalisés."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").casefold()
    s = s.replace("’", "'").replace("‘", "'").replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def _cite(texte: str, terme: str) -> bool:
    t = re.sub(r"[^\w]+", " ", plat(terme)).strip()
    p = re.sub(r"[^\w]+", " ", plat(texte))
    return bool(t) and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", p) is not None


_APPEL = re.compile(r"\[\^([\w-]+)\](?!:)|\[(\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*)\](?!\()")
_GUILLEMETS = re.compile(r"«[^»]*»|“[^”]*”")
_URL = re.compile(r"https?://\S+")


def appels(phrase: str) -> list[str]:
    """Appels de note d'une phrase, dans l'ordre : ``[1]``, ``[1, 3]``, ``[2-4]``, ``[^cle]``."""
    out: list[str] = []
    for m in _APPEL.finditer(phrase):
        if m.group(1):
            out.append(m.group(1))
            continue
        for partie in re.split(r"\s*[,;]\s*", m.group(2)):
            de, _, a = partie.partition("-") if "-" in partie else partie.partition("–")
            if a and de.isdigit() and a.isdigit() and int(de) <= int(a) <= int(de) + 50:
                out += [str(n) for n in range(int(de), int(a) + 1)]
            else:
                out.append(de.strip())
    return list(dict.fromkeys(out))


def sans_appels(phrase: str) -> str:
    return _APPEL.sub(" ", phrase)


def hors_guillemets(phrase: str) -> str:
    return _GUILLEMETS.sub(" ", phrase)


# ------------------------------------------------------------------------------------------- découpage

_ABREVIATIONS = {"p", "pp", "f", "fo", "fol", "ff", "n", "no", "vol", "ed", "t", "m", "mm", "mme", "me", "dr", "st",
                 "ste", "cf", "env", "av", "apr", "j.-c", "s", "ss", "chap", "coll", "dir", "op", "cit", "ibid",
                 "id", "art", "col", "fig", "ms", "suiv", "sq", "trad", "etc", "sr", "mgr", "r", "v", "vo", "ro"}


@dataclass
class Phrase:
    texte: str
    section: str  # titre de la section (« » si aucune)
    genre: str  # contexte | notes | hypotheses | questions | autre

    @property
    def appels(self) -> list[str]:
        return appels(self.texte)


def _fin_de_phrase(texte: str, i: int) -> bool:
    """Le point en ``i`` termine-t-il une phrase ? (abréviation ou initiale : non)."""
    if texte[i] != ".":
        return True
    m = re.search(r"([\w.-]+)$", texte[:i])
    mot = (m.group(1) if m else "").casefold()
    return not (mot in _ABREVIATIONS or (len(mot) == 1 and mot.isalpha()) or mot.replace(".", "").isdigit()
                and "." in mot)


def decouper(bloc: str) -> list[str]:
    """Phrases d'un paragraphe : coupe après . ! ? … (hors citations « » et abréviations) suivis d'un espace et d'une
    majuscule, d'un chiffre ou d'un guillemet ; un appel de note qui suit la ponctuation reste avec sa phrase."""
    phrases, debut, profondeur, i = [], 0, 0, 0
    n = len(bloc)
    while i < n:
        c = bloc[i]
        if c in "«“":
            profondeur += 1
        elif c in "»”":
            profondeur = max(0, profondeur - 1)
        elif c in ".!?…" and profondeur == 0 and _fin_de_phrase(bloc, i):
            j = i + 1
            while j < n and bloc[j] in ".!?…»”\")":
                j += 1
            while True:  # appels de note collés à la ponctuation
                m = re.match(r"\s*(\[\^[\w-]+\]|\[\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*\])", bloc[j:])
                if not m:
                    break
                j += m.end()
            m = re.match(r"\s+(?=[«“\"(\[]?\s*[A-ZÀ-ÖØ-Þ0-9])", bloc[j:])
            if m or j >= n:
                phrases.append(bloc[debut:j].strip())
                debut = j + (m.end() if m else 0)
                i = debut
                continue
        i += 1
    reste = bloc[debut:].strip()
    if reste:
        phrases.append(reste)
    return [p for p in phrases if re.search(r"\w", sans_appels(p))]


_TITRE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_GRAS = re.compile(r"^\*\*([^*]+?)\*\*\s*:?\s*$")
_NOTE_DEF = re.compile(r"^\s*(?:[-*+]\s+)?(?:\[\^([\w-]+)\]:|\[(\d{1,3})\]|(\d{1,3})[.)])\s+(.*)$")
_LISTE = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+")


def _genre(titre: str) -> str:
    t = re.sub(r"[^\w' ]+", " ", plat(titre)).strip()
    if t.startswith("contexte") and not t.startswith(("contexte a documenter", "contexte non documente")):
        return "contexte"
    if t in SECTIONS_NOTES:
        return "notes"
    if t.startswith("hypothese"):
        return "hypotheses"
    if t.startswith("questions"):
        return "questions"
    return "autre"


def nettoyer(texte: str) -> str:
    """Retire frontmatter, sections générées, commentaires HTML et blocs de code (non rédigés à la main)."""
    t = (texte or "").replace("\r\n", "\n")
    t = re.sub(r"\A---\n.*?\n---\n", "", t, flags=re.S)
    t = BLOCK.sub("", t)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"^(```|~~~).*?^\1[^\n]*$", "", t, flags=re.S | re.M)
    return t


@dataclass
class Analyse:
    phrases: list[Phrase] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)
    sections_contexte: int = 0


def analyser(texte: str) -> Analyse:
    """Sections, phrases et définitions de notes d'un texte."""
    out = Analyse()
    titre, genre, niveau = "", "autre", 0
    bloc: list[str] = []
    derniere_note = None

    def vider():
        if bloc:
            for p in decouper(" ".join(x.strip() for x in bloc)):
                out.phrases.append(Phrase(p, titre, genre))
            bloc.clear()

    for ligne in nettoyer(texte).split("\n"):
        m, g = _TITRE.match(ligne), _GRAS.match(ligne)
        if m or g:
            vider()
            nouveau = m.group(2) if m else g.group(1)
            lvl = len(m.group(1)) if m else 7
            # un intertitre plus profond reste dans la section « Contexte »
            if not (genre == "contexte" and lvl > niveau and _genre(nouveau) == "autre"):
                titre, genre, niveau = nouveau.strip(), _genre(nouveau), lvl
                out.sections_contexte += genre == "contexte"
            derniere_note = None
            continue
        d = _NOTE_DEF.match(ligne)
        if d and (genre == "notes" or d.group(1)):
            vider()
            cle = d.group(1) or d.group(2) or d.group(3)
            out.notes[cle] = d.group(4).strip()
            derniere_note = cle
            continue
        if derniere_note and ligne.startswith(("  ", "\t")) and ligne.strip():
            out.notes[derniere_note] += " " + ligne.strip()
            continue
        derniere_note = None
        if genre == "notes":
            continue
        if not ligne.strip():
            vider()
        elif _LISTE.match(ligne):
            vider()
            bloc.append(_LISTE.sub("", ligne))
        else:
            bloc.append(ligne)
    vider()
    return out


# ------------------------------------------------------------------------------------------- identifiants

_FORMES_ID = (
    ("doi", r"(?:\bdoi:\s*|https?://(?:dx\.)?doi\.org/|\bDOI\s+)(10\.\d{4,9}/[^\s<>\]»\"]+)"),
    ("doi", r"(?<![\w/.])(10\.\d{4,9}/[^\s<>\]»\"]+)"),
    ("ark", r"(ark:/?\d{5}/[^\s<>\]»\",;]+)"),
    ("hal", r"(?:\bHAL\s+|\bhal:\s*|https?://[^\s/]*hal[^\s/]*/)([a-z]+-\d{8}(?:v\d+)?)"),
    ("ppn", r"(?:\bPPN\s*:?\s*|\bppn:|sudoc\.(?:fr|abes\.fr)/)(\d{8}[\dX])\b"),
    ("handle", r"(?:\bHandle\s+|\bhdl:\s*|hdl\.handle\.net/)(\d+(?:\.\d+)*/[^\s<>\]»\"]+)"),
    ("lccn", r"(?:\bLCCN\s+|lccn\.loc\.gov/)([a-z]{0,3}\d{8,10})\b"),
    ("europeana", r"(?:\bEuropeana\s+|europeana\.eu/(?:[a-z]{2}/)?item)(/\d+/[^\s<>\]»\"]+)"),
)


def identifiants(note: str) -> list[Identifiant]:
    """Identifiants pérennes lus dans le texte d'une note (formes de ``citation.citer`` et formes libres) ; les URL
    ne sont retenues que si la note ne donne aucun autre identifiant."""
    vus: dict[str, Identifiant] = {}
    for type_, motif in _FORMES_ID:
        for m in re.finditer(motif, note or ""):
            valeur = m.group(1).rstrip(".,;:)")
            try:
                ident = Identifiant(type_, valeur)
            except ReferenceInvalide:
                continue
            vus.setdefault(ident.cle, ident)
    if vus:
        return list(vus.values())
    for m in _URL.finditer(note or ""):
        ident = Identifiant.depuis_texte(m.group(0).rstrip(".,;:)>»]"))
        if ident is not None:
            vus.setdefault(ident.cle, ident)
    return list(vus.values())


# ------------------------------------------------------------------------------------------- portée

def annees(texte: str) -> list[tuple[int, int]]:
    """Années et intervalles cités (hors appels de note et URL), siècles en chiffres romains."""
    t = _URL.sub(" ", sans_appels(texte))
    out = []
    for m in re.finditer(r"(?<![\w.,/°-])(1\d{3}|20\d{2})(?:\s*[-–]\s*(1\d{3}|20\d{2}))?(?![\w,/°]|\.\d)", t):
        avant = plat(t[max(0, m.start() - 8):m.start()])
        apres = plat(t[m.end():m.end() + 14])
        if re.search(r"(?:n°|no|p\.|f°|fo|vol\.|capital)\s*$", avant) or re.match(rf"\s*(?:{UNITES})", apres):
            continue
        de, a = int(m.group(1)), int(m.group(2) or m.group(1))
        out.append((min(de, a), max(de, a)))
    for m in re.finditer(r"(?<![A-Za-z])(X{0,2}(?:IX|IV|V?I{0,3}))(?:e|ème|eme)\b", t):
        if m.group(1) in _SIECLES:
            out.append(_SIECLES[m.group(1)])
    return out


def _variantes_commune(nom: str) -> list[str]:
    n = re.sub(r"\s*\([^)]*\)", "", nom or "").strip()
    sans_article = re.sub(r"^(?:les|le|la|l')\s*", "", n, flags=re.I).strip()
    return [x for x in dict.fromkeys([nom, n, sans_article]) if x]


_NOMS_DEPARTEMENTS = sorted(DEPARTEMENTS.values(), key=len, reverse=True)
_NOMS_PAYS = sorted((v[0] for v in PAYS.values()), key=len, reverse=True)


def _lieux_cites(texte: str, noms: list[str]) -> list[str]:
    """Noms (sensibles à la casse) cités en mots entiers, sans être une partie d'un nom composé."""
    return [n for n in noms if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", texte)]


# ------------------------------------------------------------------------------------------- vérification

@dataclass
class Personne:
    """Ce que le contrôle sait de l'individu : faits sourcés seulement (comme contexte_local)."""

    periode: tuple[int, int] | None
    communes: list[str]
    departements: set[str]  # codes
    noms_departements: list[str]
    pays: set[str]  # codes ISO
    noms_pays: list[str]
    identite: list[str]  # prénoms, nom (aplatis)
    sources: list[str]  # titres des sources de l'arbre citées pour ses faits (aplatis)


def personne_depuis_arbre(tree, personne: str) -> Personne:
    """Période et lieux de vie lus dans les faits sourcés (``local.preparer``), identité et sources de l'arbre.
    Lève ``local.ContexteInvalide`` si la personne est inconnue."""
    e = preparer(tree, personne)
    communes = [v for lv in e.lieux for v in _variantes_commune(lv.commune)]
    deps = {_departement(lv.departement) for lv in e.lieux if lv.departement}
    noms_deps = [lv.departement for lv in e.lieux if lv.departement]
    pays = {pays_par_nom(lv.pays) or plat(lv.pays) for lv in e.lieux if lv.pays}
    noms_pays = [lv.pays for lv in e.lieux if lv.pays]
    p = tree.person(personne)
    identite = set()
    for n in p.noms:
        identite |= {plat(n.nom), plat(n.surnom), *(plat(x) for x in n.prenoms.split())}
    identite.discard("")
    evenements = list(p.evenements)
    for fam in tree.spouses_families(p.id):
        evenements += fam.evenements
    sources = []
    for ev in evenements:
        for ci in ev.citations:
            s = tree.sources.get(ci.source)
            if s and s.titre.strip():
                sources.append(plat(s.titre))
            for x in ((s.ark, s.url) if s else ()) + (ci.ark,):
                if x and x.strip():
                    sources.append(plat(x))
    periode = (e.periode.de, e.periode.a) if e.periode else None
    return Personne(periode, list(dict.fromkeys(communes)), deps, noms_deps, pays, noms_pays,
                    sorted(x for x in identite if len(x) >= 2), list(dict.fromkeys(sources)))


def vise_individu(texte: str, p: Personne) -> bool:
    """La phrase (hors citations entre guillemets) désigne-t-elle l'individu ? Nom, prénoms, pronoms personnels
    (tournures impersonnelles exclues)."""
    t = re.sub(IMPERSONNELS, " ", plat(hors_guillemets(sans_appels(texte))))
    t = re.sub(r"\bne prouve rien pour l'individu\b", " ", t)  # mention de tendance (#321) : pas une affirmation
    if re.search(PRONOMS, t):
        return True
    return any(re.search(rf"(?<![\w-]){re.escape(x)}(?![\w-])", t) for x in p.identite)


def _est_individuelle(note: str, p: Personne) -> bool:
    n = plat(note)
    return any(s and s in n for s in p.sources)


def _hypothese(phrase: Phrase) -> bool:
    return phrase.genre == "hypotheses" or re.search(HYPOTHESE, plat(phrase.texte)) is not None


def _question(phrase: Phrase) -> bool:
    return sans_appels(phrase.texte).rstrip().endswith("?")


def verifier(texte: str, tree, personne: str, registre: RegistreReferences) -> dict:
    """Rapport du contrôle (voir le module). Lève ``local.ContexteInvalide`` si la personne est inconnue."""
    p = personne_depuis_arbre(tree, personne)
    a = analyser(texte)
    sans_ref: list[dict] = []
    non_consultees: list[dict] = []
    hors_portee: list[dict] = []
    causalites: list[dict] = []
    formulations: list[dict] = []
    nb_contexte = nb_sourcees = nb_anachronismes = 0
    references: dict[str, bool] = {}  # clé -> consultée
    vus_non_consultees: set[tuple] = set()

    for ph in a.phrases:
        libre = hors_guillemets(sans_appels(ph.texte))
        pl = plat(libre)
        individu = vise_individu(ph.texte, p)
        notes_individuelles = [c for c in ph.appels if c in a.notes and _est_individuelle(a.notes[c], p)]
        if not _question(ph) and not _hypothese(ph):
            for r in CONNECTEURS:
                if r.cherche(pl) and (r.categorie == "causatif" or individu) and not notes_individuelles:
                    causalites.append({"phrase": ph.texte, "section": ph.section, "connecteur": r.cle,
                                       "categorie": r.categorie,
                                       "motif": "connecteur causal ou motif prêté appliqué à l'individu sans source "
                                                "individuelle : à formuler comme hypothèse au conditionnel, avec la "
                                                "source qui la trancherait"})
        if not _question(ph):
            for r in GENERALISATIONS:
                if r.cherche(pl):
                    formulations.append({"phrase": ph.texte, "section": ph.section, "type": "generalisation",
                                         "marqueur": r.cle, "motif": "généralisation d'une tendance (époque, groupe, "
                                         "région) : ne s'applique pas à l'individu"})
        if ph.genre != "contexte":
            continue
        if re.search(ABSENCE, plat(sans_appels(ph.texte))):
            continue
        nb_contexte += 1

        # 1. appels de note
        connus = [c for c in ph.appels if c in a.notes]
        if not ph.appels:
            sans_ref.append({"phrase": ph.texte, "section": ph.section})
        elif connus:
            nb_sourcees += 1
        # 2. références
        titres: list[str] = []
        refs_contexte = 0
        for c in ph.appels:
            if c not in a.notes:
                cle = ("absente", c)
                references.setdefault(f"note:{c}", False)
                if cle not in vus_non_consultees:
                    vus_non_consultees.add(cle)
                    non_consultees.append({"appel": c, "phrase": ph.texte, "motif": "appel sans note correspondante "
                                           "dans « Notes et sources »"})
                continue
            if c in notes_individuelles:
                continue
            refs_contexte += 1
            ids = identifiants(a.notes[c])
            if not ids:
                references.setdefault(f"note:{c}", False)
                cle = ("sans_id", c)
                if cle not in vus_non_consultees:
                    vus_non_consultees.add(cle)
                    non_consultees.append({"appel": c, "note": a.notes[c], "phrase": ph.texte, "motif": (
                        "aucun identifiant pérenne lisible (DOI, ARK, HAL, PPN, Handle, URL…) : référence "
                        "invérifiable, donc non consultée")})
                continue
            for ident in ids:
                ref = registre.lire(ident)
                references[ident.cle] = ref is not None
                if ref is None:
                    cle = ("hors_registre", ident.cle)
                    if cle not in vus_non_consultees:
                        vus_non_consultees.add(cle)
                        non_consultees.append({"appel": c, "identifiant": ident.cle, "note": a.notes[c],
                                               "phrase": ph.texte, "motif": "absente du registre des références "
                                               "consultées : notice jamais récupérée par le plugin (référence de "
                                               "mémoire ?)"})
                elif ref.titre:
                    titres.append(ref.titre)

        # 3. portée : période
        if p.periode is None:
            if annees(ph.texte) or ph.appels:
                hors_portee.append({"phrase": ph.texte, "type": "periode", "motif": "période de vie sourcée "
                                    "inconnue (aucun fait daté et cité) : portée non vérifiable"})
        else:
            de, a_ = p.periode
            dehors = [x for x in annees(ph.texte) if x[1] < de or x[0] > a_]
            if dehors:
                nb_anachronismes += len(dehors)
                lib = ", ".join(f"{x}" if x == y else f"{x}-{y}" for x, y in dehors)
                hors_portee.append({"phrase": ph.texte, "type": "periode", "annees": [list(x) for x in dehors],
                                    "motif": f"année(s) {lib} hors de la période de vie sourcée ({de}-{a_}) : "
                                             "anachronisme"})
        # 3. portée : lieux cités hors des lieux de vie
        etrangers = [n for n in _lieux_cites(libre, _NOMS_DEPARTEMENTS) if _departement(n) not in p.departements]
        etrangers += [n for n in _lieux_cites(libre, _NOMS_PAYS) if (pays_par_nom(n) or plat(n)) not in p.pays]
        if etrangers:
            hors_portee.append({"phrase": ph.texte, "type": "lieu", "lieux": etrangers,
                                "motif": f"lieu cité hors des lieux de vie sourcés : {', '.join(etrangers)}"})
        complet = " ".join([sans_appels(ph.texte), *titres])
        commune = any(_cite(complet, x) for x in p.communes)
        large = (any(_cite(complet, x) for x in p.noms_departements + p.noms_pays)
                 or re.search(ECHELLE_SUPERIEURE, plat(libre)) is not None)
        if refs_contexte and not commune and not any(_cite(complet, x) for x in p.noms_departements + p.noms_pays):
            hors_portee.append({"phrase": ph.texte, "type": "lieu", "motif": "portée géographique non établie : ni "
                                "la phrase ni la référence ne citent un lieu de vie sourcé"})

        # 5. formulation selon le rattachement
        declare = ("atteste" if re.search(FORMULE_ATTESTE, pl) else "compatible" if re.search(FORMULE_COMPATIBLE, pl)
                   else "non_demontre" if re.search(FORMULE_NON_DEMONTRE, pl) else "")
        if declare in ("compatible", "non_demontre") and individu:
            formulations.append({"phrase": ph.texte, "type": "rattachement", "niveau": declare, "motif": (
                f"rattachement {declare} déclaré : aucune affirmation sur l'individu"
                " (« à la même époque et au même endroit… », « plus généralement… »)")})
        elif declare == "atteste" and not notes_individuelles:
            formulations.append({"phrase": ph.texte, "type": "rattachement", "niveau": declare, "motif": (
                "rattachement attesté déclaré sans appel vers une source de l'arbre portant sur l'individu")})
        elif not declare and individu and ph.appels and not notes_individuelles and not _hypothese(ph):
            formulations.append({"phrase": ph.texte, "type": "rattachement", "niveau": "", "motif": (
                "affirmation sur l'individu appuyée sur une référence de contexte seulement : un élément de contexte "
                "n'est attesté pour l'individu que par une citation de l'arbre")})
        if refs_contexte and large and not commune and not re.search(MENTION, pl):
            formulations.append({"phrase": ph.texte, "type": "mention", "motif": (
                "élément d'échelle supérieure à la commune sans la mention « tendance générale, ne prouve rien pour "
                "l'individu »")})

    nb_refs = len(references)
    nb_consultees = sum(references.values())
    rapport = {
        "outil": OUTIL, "personne": personne, "version_listes": VERSION_LISTES,
        "conforme": not (sans_ref or non_consultees or hors_portee or causalites or formulations),
        "contexte": ("present" if nb_contexte else
                     "non_documente" if re.search(r"contexte (?:non documente|a documenter)", plat(texte or ""))
                     else "absent"),
        "phrases_sans_reference": sans_ref, "references_non_consultees": non_consultees,
        "hors_portee": hors_portee, "causalites": causalites, "formulations": formulations,
        "mesures": {
            "phrases_contexte": nb_contexte, "phrases_sourcees": nb_sourcees,
            "part_phrases_sourcees": round(nb_sourcees / nb_contexte, 4) if nb_contexte else None,
            "references_citees": nb_refs, "references_consultees": nb_consultees,
            "part_references_consultees": round(nb_consultees / nb_refs, 4) if nb_refs else None,
            "anachronismes": nb_anachronismes, "causalites_non_sourcees": len(causalites),
        },
        "periode_de_vie": list(p.periode) if p.periode else None,
        "limites": list(LIMITES),
        "rappel": RAPPEL,
    }
    rapport["publication_billet"] = "autorisée" if rapport["conforme"] else "bloquée (conforme: false)"
    if rapport["contexte"] != "present":
        rapport["limites"] = [("Aucune phrase de contexte à contrôler : sortie attendue « contexte non documenté » "
                               "dans les questions ouvertes, jamais un paragraphe général.")] + rapport["limites"]
    return rapport
