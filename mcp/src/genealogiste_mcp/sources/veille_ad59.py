"""Veille des mises en ligne des AD59 (#380) : dérive des formulaires de recherche, fils d'ajouts du forum du
service, classeur 3 E millésimé et ancienneté des référentiels embarqués.

Aucun outil MCP : la veille est lancée par ``scripts/veiller_ad59.py`` (``make veille-ad59``), étape réseau
explicite ; seule l'ancienneté des référentiels, locale, est reprise par ``diagnostic``. Toutes les requêtes
passent par le client HTTP du dépôt (politique réseau, intervalle et plafond par hôte, coupe-circuit), sans
cache, espacées de ``PAUSE`` secondes en plus de l'intervalle de l'hôte :

- formulaires : une requête par formulaire connu (``registres.formulaires_ad59``), comparé au contrat relevé
  (``referentiels/ad59_formulaires.json`` : titre et champs) ;
- forum : ``robots.txt`` puis UNE lecture par passage, le flux Atom du forum des ajouts (défaut) ou sa page
  HTML ; seuls le titre, la date et le lien de chaque fil sont extraits. Le flux transporte aussi le corps et
  l'auteur des messages : ils ne sont ni lus, ni gardés, ni mis en cache ;
- classeur 3 E : une requête sur la page des nouveautés, dont le lien ``/document/classeur-3e-…`` est comparé
  à celui du référentiel embarqué. Un nouveau classeur est signalé, jamais téléchargé.

Aucune image, aucune notice, aucun nom de personne, aucun compte. Un échec est un signalement dans la réponse,
jamais une erreur bloquante. Rien de ce qui est relevé ici n'est un fait généalogique : ce sont des annonces à
vérifier, consignées au journal.
"""

from __future__ import annotations

import html
import json
import re
import urllib.robotparser
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

from .. import couverture_3e, couverture_recensements
from ..gramps import lecture_xml
from . import registres
from .base import SourceContext, SourceError

PATH = Path(__file__).parent.parent / "referentiels" / "ad59_formulaires.json"
NOUVEAUTES = registres.HOST + "/page/nouveautes-du-site-internet"
FORUM = "https://forum-archivesdepartementales.lenord.fr"
FORUM_AJOUTS = 138  # forum « ANNÉES MANQUANTES AJOUTÉES » (relevé du 27 novembre 2026)
FLUX = f"{FORUM}/app.php/feed/forum/{FORUM_AJOUTS}"
PAGE_FORUM = f"{FORUM}/viewforum.php?f={FORUM_AJOUTS}"
ROBOTS_FORUM = FORUM + "/robots.txt"
PAUSE = 3.0  # secondes entre deux requêtes de la veille, en plus de l'intervalle de l'hôte
SEUIL_JOURS = 365  # au-delà, un référentiel embarqué est signalé « à renouveler »
MAX_FILS = 15
MAX_TITRE = 120
MAX_FLUX = 1_000_000
SOURCE_JOURNAL = "veille_ad59"
LIMITE = ("Veille indicative : un formulaire conforme ne prouve pas que ses résultats sont inchangés ; un titre "
          "de fil est une annonce à vérifier sur le site du service, pas un fait ; le contenu des messages, des "
          "notices et des documents n'est pas lu.")
RENOUVELER_3E = ("Renouveler le référentiel : télécharger le nouveau classeur à la main, puis "
                 "scripts/generer_couverture_3e_ad59.py <pdf> --source <URL> (docs/recherche-registres-ad59.md, "
                 "« Classeur 3 E », Renouvellement) et mettre à jour couverture_3e.SOURCE.")
RENOUVELER_REC = ("Relire l'état de la collection sur le site du service et régénérer le référentiel : "
                  "scripts/generer_couverture_recensements_ad59.py (docs/recensements.md).")


# ---------------------------------------------------------------------------- formulaires (dérive)

@lru_cache(maxsize=1)
def contrat() -> dict:
    """Contrat relevé des formulaires : clé de ``registres.formulaires_ad59`` -> titre et champs attendus."""
    return json.loads(PATH.read_text(encoding="utf-8"))


def _sans_indice(nom: str) -> str:
    return re.sub(r"^\d+-", "", nom)


def lire_formulaire(texte: str) -> dict | None:
    """Titre, UUID et champs visibles du formulaire de recherche d'une page ``/search/form/<uuid>`` ; None si la
    page ne porte pas le formulaire attendu. Aucune option (vocabulaire de communes ou de bureaux) n'est lue."""
    if len(texte) > registres.MAX_HTML:
        return None
    parser = registres._HTML()
    try:
        parser.feed(texte)
    except registres.FormatRegistresError:
        return None
    formulaires = parser.racine.trouver("form", identifiant="form-search-advanced-search")
    if len(formulaires) != 1:
        return None
    titres = parser.racine.trouver("title")
    # « <intitulé> - Recherche ciblée - Site Web des Archives départementales du Nord » : l'intitulé seul
    titre = re.split(r"\s+-\s+Recherche ciblée\b", titres[0].texte())[0].strip() if titres else ""
    champs, uuid = [], ""
    for n in formulaires[0].trouver():
        nom = n.attrs.get("data-name") or n.attrs.get("name") or ""
        if n.attrs.get("type") == "hidden":
            if nom == "formUuid":
                uuid = n.attrs.get("value", "")
            continue
        if nom and nom not in champs:
            champs.append(nom)
    return {"titre": titre, "uuid": uuid, "champs": champs}


def comparer(attendu: dict, lu: dict) -> dict:
    """Écarts entre le contrat (titre, champs) et le formulaire lu. Un champ disparu et un champ ajouté de même
    nom hors indice (« 2-date » -> « 3-date ») sont rapprochés en ``champs_renommes``."""
    disparus = [c for c in attendu["champs"] if c not in lu["champs"]]
    ajoutes = [c for c in lu["champs"] if c not in attendu["champs"]]
    renommes = []
    for avant in list(disparus):
        apres = next((c for c in ajoutes if _sans_indice(c) == _sans_indice(avant)), None)
        if apres:
            renommes.append({"avant": avant, "apres": apres})
            disparus.remove(avant)
            ajoutes.remove(apres)
    ecarts: dict = {}
    if disparus:
        ecarts["champs_disparus"] = disparus
    if renommes:
        ecarts["champs_renommes"] = renommes
    if ajoutes:
        ecarts["champs_ajoutes"] = ajoutes
    if " ".join(lu["titre"].split()).casefold() != " ".join(attendu["titre"].split()).casefold():
        ecarts["titre_change"] = {"attendu": attendu["titre"], "lu": lu["titre"]}
    return ecarts


def _bloquant(exc: SourceError) -> bool:
    """Échec qui vaut pour tout l'hôte : inutile (et malvenu) d'envoyer les requêtes suivantes."""
    return bool(exc.bloque_antirobot or getattr(exc, "coupe_circuit", False) or exc.status is None
                or exc.status == 429 or exc.status >= 500)


class _Passage:
    """Requêtes d'un passage de veille : sans cache, espacées, comptées (demandes au client : un échec mémorisé
    ou un refus de la politique réseau est compté sans rien émettre)."""

    def __init__(self, ctx: SourceContext):
        self.ctx, self.requetes = ctx, 0

    def lire(self, url: str) -> str:
        if self.requetes:
            self.ctx.http.sleep(PAUSE)
        self.requetes += 1
        texte, _ = self.ctx.http.get(url, parse="text", use_cache=False, ttl=0, source=SOURCE_JOURNAL)
        return texte


def sonder_formulaires(ctx: SourceContext, cles: list[str] | None = None, passage: _Passage | None = None) -> dict:
    """Une requête par formulaire connu : conforme, derive (champs ou titre changés), disparu (HTTP 404),
    non_reconnu (page sans le formulaire attendu) ou non_verifie (réseau, protection : aucune conclusion).
    Après un échec qui vaut pour l'hôte (défi anti-robot, coupe-circuit, 429, 5xx, réseau), les formulaires
    restants ne sont pas demandés."""
    passage = passage or _Passage(ctx)
    connus = registres.formulaires_ad59()
    inconnues = [c for c in cles or [] if c not in connus]
    if inconnues:
        raise ValueError(f"Formulaire(s) inconnu(s) : {', '.join(inconnues)} ; connus : {', '.join(connus)}.")
    attendus = contrat()["formulaires"]
    resultats, arret = [], ""
    for cle in cles or list(connus):
        uuid = connus[cle]
        r = {"cle": cle, "formulaire": uuid, "url": f"{registres.HOST}/search/form/{uuid}"}
        resultats.append(r)
        if arret:
            r.update(etat="non_verifie", message=f"Non demandé : {arret}")
            continue
        if cle not in attendus:
            r.update(etat="non_verifie", message="Aucun contrat relevé pour ce formulaire (ad59_formulaires.json).")
            continue
        try:
            lu = lire_formulaire(passage.lire(r["url"]))
        except SourceError as exc:
            if exc.status == 404:
                r.update(etat="disparu", message="Formulaire introuvable (HTTP 404) : UUID retiré ou remplacé.")
            else:
                r.update(etat="non_verifie", message=str(exc))
                if _bloquant(exc):
                    arret = "échec précédent sur le même hôte, aucune nouvelle requête."
            continue
        if lu is None:
            r.update(etat="non_reconnu", message="Page sans le formulaire de recherche attendu.")
            continue
        ecarts = comparer(attendus[cle], lu)
        if lu["uuid"] and lu["uuid"] != uuid:
            ecarts["formulaire_servi"] = lu["uuid"]
        r.update(etat="derive" if ecarts else "conforme", titre=lu["titre"], **ecarts)
        if ecarts:
            r["champs_lus"] = lu["champs"]
    etats = [r["etat"] for r in resultats]
    derives = [r["cle"] for r in resultats if r["etat"] in ("derive", "disparu", "non_reconnu")]
    non_verifies = [r["cle"] for r in resultats if r["etat"] == "non_verifie"]
    resume = (f"{etats.count('conforme')} formulaire(s) conforme(s) sur {len(resultats)}"
              + (f" ; dérive : {', '.join(derives)}" if derives else "")
              + (f" ; non vérifié : {', '.join(non_verifies)}" if non_verifies else ""))
    jid = ctx.journal.add(source=SOURCE_JOURNAL, operation="formulaires", parametres={"formulaires": cles or "tous"},
                          statut="erreur" if len(non_verifies) == len(resultats) else "positif",
                          nb_resultats=len(derives), resume=resume, references=[r["url"] for r in resultats
                                                                                 if r["cle"] in derives],
                          note="Contrat relevé le " + contrat()["releve_le"] + ". " + LIMITE)
    return {"etat": "derive" if derives else "non_verifie" if non_verifies else "conforme",
            "contrat_releve_le": contrat()["releve_le"], "derives": derives, "non_verifies": non_verifies,
            "resume": resume, "journal": jid, "formulaires": resultats}


# ---------------------------------------------------------------------------- forum (fils d'ajouts)

def _titre(texte: str) -> str:
    """Titre d'un fil : texte seul, sans le nom du forum en préfixe (« FORUM • titre »), borné."""
    t = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", texte or "")).split())
    t = t.split(" • ", 1)[-1]
    return t[:MAX_TITRE].rstrip() + ("…" if len(t) > MAX_TITRE else "")


def _lien(href: str) -> str:
    """Lien canonique d'un fil ou d'un message du forum, sans jeton de session ; '' s'il sort du forum."""
    parts = urlsplit(urljoin(FORUM + "/", html.unescape(href or "")))
    if f"{parts.scheme}://{parts.hostname}" != FORUM or parts.path != "/viewtopic.php":
        return ""
    q = parse_qs(parts.query)
    for cle in ("t", "p"):
        if q.get(cle, [""])[0].isdigit():
            n = q[cle][0]
            return f"{FORUM}/viewtopic.php?{cle}={n}" + (f"#p{n}" if cle == "p" else "")
    return ""


def _date(texte: str) -> str:
    m = re.match(r"\d{4}-\d{2}-\d{2}", (texte or "").strip())
    return m[0] if m else ""


def lire_flux(texte: str, limite: int = MAX_FILS) -> list[dict]:
    """Entrées d'un flux Atom du forum : ``{titre, date, lien}`` seulement. L'auteur et le corps des messages,
    présents dans le flux, ne sont pas lus. ValueError si le document n'est pas un flux Atom lisible."""
    if len(texte) > MAX_FLUX:
        raise ValueError("Flux trop volumineux : lecture abandonnée.")
    try:
        racine = lecture_xml.analyser(texte.encode("utf-8"))
    except lecture_xml.LectureGrampsError as exc:
        raise ValueError(f"Flux illisible : {exc}") from exc
    if racine.tag != "feed":
        raise ValueError("Flux non reconnu : élément racine « feed » attendu.")
    fils = []
    for entree in (n for n in racine.enfants if n.tag == "entry"):
        champs = {n.tag: n for n in reversed(entree.enfants) if n.tag in ("title", "published", "updated", "link")}
        lien = _lien(champs["link"].attrib.get("href", "")) if "link" in champs else ""
        titre = _titre(champs["title"].text) if "title" in champs else ""
        if lien and titre:
            fils.append({"titre": titre, "date": _date((champs.get("published") or champs.get("updated")
                                                        or entree).text), "lien": lien})
    return fils[:max(0, limite)]


def lire_page_forum(texte: str, limite: int = MAX_FILS) -> list[dict]:
    """Fils de la page HTML d'un forum phpBB : titre, date du dernier message, lien. Les annonces globales
    (communes à tous les forums) sont écartées ; aucun pseudonyme n'est lu."""
    if len(texte) > registres.MAX_HTML:
        raise ValueError("Page du forum trop volumineuse : lecture abandonnée.")
    parser = registres._HTML()
    try:
        parser.feed(texte)
    except registres.FormatRegistresError as exc:
        raise ValueError(str(exc)) from exc
    fils = []
    for rang in parser.racine.trouver("li", classe="row"):
        if "global-announce" in rang.attrs.get("class", "").split():
            continue
        titres = rang.trouver("a", classe="topictitle")
        if len(titres) != 1:
            continue
        dates = [t.attrs.get("datetime", "") for d in rang.trouver("dd", classe="lastpost") for t in d.trouver("time")]
        lien, titre = _lien(titres[0].attrs.get("href", "")), _titre(titres[0].texte())
        if lien and titre:
            fils.append({"titre": titre, "date": _date(dates[0] if dates else ""), "lien": lien})
    if not fils and not parser.racine.trouver(classe="topiclist"):
        raise ValueError("Page du forum non reconnue : aucune liste de fils.")
    return fils[:max(0, limite)]


def _robots_forum(passage: _Passage, agent: str, url: str) -> tuple[bool, str]:
    """(lecture permise, constat). Un robots.txt absent (HTTP 404) ou remplacé par une page HTML ne déclare
    aucune règle : la lecture reste modérée, ce n'est pas une autorisation. Illisible : pas de lecture."""
    try:
        texte = passage.lire(ROBOTS_FORUM)
    except SourceError as exc:
        if exc.status == 404:
            return True, "robots.txt absent (HTTP 404) : aucune règle déclarée, ce qui n'est pas une autorisation."
        return False, f"robots.txt illisible ({exc}) : forum non lu."
    if texte.lstrip().startswith("<"):
        return True, "robots.txt servi comme une page HTML : aucune règle déclarée, ce qui n'est pas une autorisation."
    robots = urllib.robotparser.RobotFileParser()
    robots.parse(texte.splitlines())
    if robots.can_fetch(agent, url):
        return True, "robots.txt lu : cette adresse n'est pas interdite."
    return False, "robots.txt interdit cette adresse : forum non lu."


def lire_ajouts_forum(ctx: SourceContext, mode: str = "flux", limite: int = 10,
                      passage: _Passage | None = None) -> dict:
    """Fils récents du forum des ajouts : ``robots.txt`` puis une seule lecture, le flux Atom (``mode="flux"``)
    ou la page HTML (``mode="html"``). Les fils sont consignés au journal comme nouveautés à vérifier ;
    ``nouveaux`` : liens absents des passages précédents du journal. Échec : ``etat="non_lu"`` et le motif."""
    if mode not in ("flux", "html"):
        raise ValueError("mode : flux ou html.")
    passage = passage or _Passage(ctx)
    limite = max(1, min(int(limite), MAX_FILS))
    url = FLUX if mode == "flux" else PAGE_FORUM
    params = {"forum": FORUM_AJOUTS, "mode": mode, "limite": limite}
    fils: list[dict] = []
    permis, robots = _robots_forum(passage, ctx.config.user_agent, url)
    message = "" if permis else robots
    if permis:
        try:
            texte = passage.lire(url)
            fils = (lire_flux if mode == "flux" else lire_page_forum)(texte, limite)
        except (SourceError, ValueError) as exc:
            message = f"Forum non lu ({exc})." + (" Essayer la page HTML au prochain passage (--forum html)."
                                                   if mode == "flux" else "")
    if message:
        jid = ctx.journal.add(source=SOURCE_JOURNAL, operation="forum_ajouts", parametres=params, statut="erreur",
                              resume=message, references=[url])
        return {"etat": "non_lu", "mode": mode, "url": url, "robots": robots, "message": message, "journal": jid,
                "fils": []}
    deja = {ref for e in ctx.journal.entries(source=SOURCE_JOURNAL, limite=500)
            if e["operation"] == "forum_ajouts" for ref in e["references"]}
    for f in fils:
        f["nouveau"] = f["lien"] not in deja
    nouveaux = [f for f in fils if f["nouveau"]]
    jid = ctx.journal.add(
        source=SOURCE_JOURNAL, operation="forum_ajouts", parametres=params, statut="positif" if fils else "negatif",
        nb_resultats=len(fils), references=[f["lien"] for f in fils],
        resume=f"Nouveautés AD59 à vérifier ({len(nouveaux)} nouvelle(s) sur {len(fils)} fil(s)) : "
               + " ; ".join(f"{f['date']} {f['titre']}" for f in (nouveaux or fils)[:MAX_FILS]),
        note="Titres de fils du forum du service, relevés sans lire les messages : annonces à vérifier sur le "
             "site, jamais une source généalogique.")
    return {"etat": "lu", "mode": mode, "url": url, "robots": robots, "journal": jid, "nouveaux": len(nouveaux),
            "fils": fils}


# ---------------------------------------------------------------------------- classeur 3 E et référentiels

def liens_nouveautes(texte: str) -> dict:
    """Liens utiles d'une page du service : classeurs 3 E millésimés (URL) et formulaires de recherche (UUID)."""
    if len(texte) > registres.MAX_HTML:
        raise ValueError("Page trop volumineuse : lecture abandonnée.")
    parser = registres._HTML()
    try:
        parser.feed(texte)
    except registres.FormatRegistresError as exc:
        raise ValueError(str(exc)) from exc
    classeurs, formulaires = [], {}
    for a in parser.racine.trouver("a"):
        parts = urlsplit(urljoin(registres.HOST + "/", a.attrs.get("href", "")))
        if f"{parts.scheme}://{parts.hostname}" != registres.HOST:
            continue
        if re.fullmatch(r"/document/classeur-3e-[a-z0-9-]+", parts.path):
            url = registres.HOST + parts.path
            if url not in classeurs:
                classeurs.append(url)
        m = re.fullmatch(r"/search/form/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})", parts.path)
        if m:
            formulaires.setdefault(m[1], _titre(a.texte()))
    return {"classeurs": classeurs, "formulaires": formulaires}


def rapprocher_classeur(ctx: SourceContext, passage: _Passage | None = None) -> dict:
    """Une requête sur la page des nouveautés : le classeur 3 E qu'elle propose est-il celui du référentiel
    embarqué ? ``nouveau`` : un autre classeur est proposé (signalé, jamais téléchargé). Les formulaires de
    recherche liés par la page et inconnus du plugin sont signalés (fonds nouveau ou formulaire remplacé)."""
    passage = passage or _Passage(ctx)
    enregistre = couverture_3e.referentiel()["source"]
    out: dict = {"page": NOUVEAUTES, "enregistre": enregistre}
    try:
        liens = liens_nouveautes(passage.lire(NOUVEAUTES))
    except (SourceError, ValueError) as exc:
        out.update(etat="non_verifie", message=f"Page des nouveautés non lue ({exc}).")
        out["journal"] = ctx.journal.add(source=SOURCE_JOURNAL, operation="classeur_3e", parametres={}, statut="erreur",
                                         resume=out["message"], references=[NOUVEAUTES])
        return out
    connus = set(registres.formulaires_ad59().values())
    out["formulaires_inconnus"] = [{"formulaire": u, "libelle": t, "url": f"{registres.HOST}/search/form/{u}"}
                                   for u, t in liens["formulaires"].items() if u not in connus]
    autres = [c for c in liens["classeurs"] if c != enregistre]
    if autres:
        out.update(etat="nouveau", classeurs=autres, remede=RENOUVELER_3E,
                   message=f"Nouveau classeur 3 E proposé par le service : {', '.join(autres)} (référentiel "
                           f"embarqué : {enregistre}). Non téléchargé.")
    elif liens["classeurs"]:
        out.update(etat="inchange", message="Le classeur 3 E proposé par le service est celui du référentiel.")
    else:
        out.update(etat="non_verifie", message="Aucun lien /document/classeur-3e-… sur la page des nouveautés : "
                                               "page modifiée ou classeur déplacé, à vérifier sur le site.")
    if out["formulaires_inconnus"]:
        out["message"] += (" Formulaire(s) de recherche inconnu(s) du plugin : "
                           + ", ".join(f"{f['libelle']} ({f['formulaire']})" for f in out["formulaires_inconnus"]) + ".")
    signale = out["etat"] == "nouveau" or bool(out["formulaires_inconnus"])
    out["journal"] = ctx.journal.add(
        source=SOURCE_JOURNAL, operation="classeur_3e", parametres={}, nb_resultats=len(autres),
        statut="positif" if signale else "negatif" if out["etat"] == "inchange" else "erreur",
        resume=out["message"], references=[NOUVEAUTES, *autres])
    return out


def anciennete(aujourdhui: date | None = None, seuil_jours: int = SEUIL_JOURS) -> list[dict]:
    """Âge des référentiels AD59 embarqués (classeur 3 E, état de collection des recensements), sans réseau :
    ``a_renouveler`` quand le relevé a plus de ``seuil_jours`` jours ou que sa date est illisible."""
    aujourdhui = aujourdhui or date.today()
    out = []
    for nom, ref, remede in (("classeur_3e", couverture_3e.referentiel(), RENOUVELER_3E),
                             ("recensements", couverture_recensements.referentiel(), RENOUVELER_REC)):
        try:
            age = (aujourdhui - date.fromisoformat(ref.get("releve_le") or "")).days
        except ValueError:
            age = None
        ancien = age is None or age > seuil_jours
        out.append({"referentiel": nom, "source": ref.get("document") or ref.get("source"),
                    "releve_le": ref.get("releve_le"), "sha256": ref.get("sha256"), "age_jours": age,
                    "seuil_jours": seuil_jours, "a_renouveler": ancien, **({"remede": remede} if ancien else {})})
    return out


def veiller(ctx: SourceContext, formulaires: bool = True, forum: str = "flux", classeur: bool = True,
            limite: int = 10, aujourdhui: date | None = None) -> dict:
    """Un passage de veille : ancienneté des référentiels (locale), puis, selon les options, classeur 3 E (une
    requête), forum (``flux``, ``html`` ou '' : deux requêtes) et formulaires (une requête chacun). Chaque volet
    porte son état ; ``signalements`` résume ce qui demande une action."""
    passage = _Passage(ctx)
    out: dict = {"service": "AD59", "date": (aujourdhui or date.today()).isoformat(),
                 "referentiels": anciennete(aujourdhui)}
    signalements = [f"Référentiel {r['referentiel']} relevé le {r['releve_le']} ("
                    + (f"{r['age_jours']} jours" if r["age_jours"] is not None else "date illisible")
                    + f", seuil {r['seuil_jours']}) : à renouveler." for r in out["referentiels"] if r["a_renouveler"]]
    if classeur:
        out["classeur_3e"] = rapprocher_classeur(ctx, passage)
        if out["classeur_3e"]["etat"] != "inchange" or out["classeur_3e"].get("formulaires_inconnus"):
            signalements.append(out["classeur_3e"]["message"])
    if forum:
        out["forum"] = lire_ajouts_forum(ctx, forum, limite, passage)
        if out["forum"]["etat"] != "lu":
            signalements.append(out["forum"]["message"])
        elif out["forum"]["nouveaux"]:
            signalements.append(f"{out['forum']['nouveaux']} fil(s) du forum des ajouts à vérifier (journal "
                                f"{out['forum']['journal']}).")
    if formulaires:
        out["formulaires"] = sonder_formulaires(ctx, None, passage)
        if out["formulaires"]["etat"] != "conforme":
            signalements.append("Formulaires : " + out["formulaires"]["resume"] + ".")
    out.update(signalements=signalements, requetes=passage.requetes, limite=LIMITE)
    return out
