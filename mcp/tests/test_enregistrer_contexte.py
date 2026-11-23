"""#323 : scripts/enregistrer_contexte.py (enregistrement des réponses de contexte, hors CI) testé sans réseau.

Le réseau est simulé par respx : chaque requête décrite par un manifeste reçoit la réponse enregistrée (les
réductions sont idempotentes : réduire une réponse déjà réduite redonne la même forme). Aucune requête réelle."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "enregistrer_contexte.py"
spec = importlib.util.spec_from_file_location("enregistrer_contexte", SCRIPT)
rec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rec)

REPONSES = Path(__file__).parent / "fixtures" / "contexte" / "reponses"


@pytest.fixture
def racine(tmp_path):
    copie = tmp_path / "reponses"
    shutil.copytree(REPONSES, copie)
    return copie


def _instantane(racine: Path) -> dict[str, str]:
    return {str(p.relative_to(racine)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(racine.rglob("*")) if p.is_file()}


def _entrees(racine: Path):
    for dossier, manifeste in rec.manifestes(racine):
        for e in manifeste["reponses"]:
            yield dossier, manifeste["service"], e


def _corps(dossier: Path, e: dict) -> bytes:
    return (dossier / e["fichier"]).read_bytes() if e.get("fichier") else b""


@pytest.fixture
def reseau(racine):
    """Chaque URL décrite par un manifeste répond avec la réponse enregistrée ; ``appels`` liste les requêtes."""
    table = {str(httpx.URL(e["url"])): (e["statut"], _corps(d, e), e["type"]) for d, _, e in _entrees(racine)}
    appels: list[str] = []

    def repondre(requete):
        appels.append(str(requete.url))
        statut, corps, type_ = table[str(requete.url)]
        return httpx.Response(statut, content=corps, headers={"Content-Type": type_})

    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=repondre)
        router.appels, router.table = appels, table
        yield router


def _lancer(racine, *args, capsys, dormir=None):
    pauses: list[float] = []
    code = rec.main(list(args), racine=racine, dormir=dormir or pauses.append)
    return code, capsys.readouterr().out, pauses


# ------------------------------------------------------------------------------ réductions et formes

def test_chaque_reduction_est_idempotente_sur_la_reponse_enregistree(racine):
    """Réduire une réponse déjà réduite redonne la forme enregistrée : le script reproduit la réduction du manifeste."""
    vus = set()
    for dossier, service, e in _entrees(racine):
        if (service, e.get("fichier") or "") not in rec.REDUCTIONS:
            continue
        vus.add((service, e["fichier"]))
        stocke = _corps(dossier, e)
        reduit = rec.reduire(service, e["fichier"], stocke)
        avant, apres = rec.forme(e["fichier"], stocke), rec.forme(e["fichier"], reduit)
        assert avant is not None and avant == apres, (service, e["fichier"], (avant or set()) ^ (apres or set()))
    assert vus == set(rec.REDUCTIONS), set(rec.REDUCTIONS) - vus


def test_toute_reponse_rejouable_a_une_reduction(racine):
    """Une réponse enregistrée en 2xx, non marquée « rejouable: false », a un réducteur ; sinon elle ne pourrait
    pas être réenregistrée."""
    for _, service, e in _entrees(racine):
        if e.get("fichier") and e["statut"] < 400 and e.get("rejouable") is not False:
            assert (service, e["fichier"]) in rec.REDUCTIONS, (service, e["fichier"])


def test_codes_cog_du_script_sont_ceux_du_manifeste(racine):
    manifeste = json.loads((REPONSES / "COG-INSEE" / "MANIFESTE.json").read_text(encoding="utf-8"))
    codes = tuple(sorted(set(__import__("re").findall(r"\b\d[0-9AB]\d{3}\b", manifeste["reponses"][0]["reduction"]))))
    assert codes == rec.CODES_COG


def test_forme_json_xml_csv_et_non_comparable():
    assert rec.forme("a.json", b'{"a": [{"b": 1}], "c": {}}') == {"a", "a[].b", "c"}
    assert rec.forme("a.xml", b'<r x="1"><s/></r>') == {"r", "r/@x", "r/s"}
    assert rec.forme("a.csv", b'"A","B"\n"1","2"\n') == {"colonne:A", "colonne:B"}
    assert rec.forme("a.html", b"<p>") is None and rec.forme("a.json", b"pas du json") is None


# ------------------------------------------------------------------------------------------------ verifier

def test_verifier_par_defaut_n_ecrit_rien(racine, reseau, capsys):
    avant = _instantane(racine)
    code, sortie, pauses = _lancer(racine, capsys=capsys)
    assert code == 0 and _instantane(racine) == avant, sortie
    assert "DERIVE" not in sortie and "OK" in sortie
    rejouables = {str(httpx.URL(e["url"])) for _, s, e in _entrees(racine)
                  if e.get("fichier") and e["statut"] < 400 and e.get("rejouable") is not False}
    assert set(reseau.appels) == rejouables and len(reseau.appels) == len(rejouables)
    # ni service protégé (403 enregistré), ni extrait manuel n'ont été sollicités
    assert not any("gallica.bnf.fr" in u or "loc.gov" in u or "retronews" in u or "europeana" in u
                   for u in reseau.appels)
    assert pauses and all(p > 0 for p in pauses)  # intervalle respecté entre requêtes vers un même hôte


def test_intervalle_par_hote(racine, reseau, capsys):
    _, _, pauses = _lancer(racine, "--service", "COG-INSEE", "--intervalle", "7", capsys=capsys)
    assert len(pauses) == 1 and 6 < pauses[0] <= 7  # deux fichiers du même hôte : une pause de 7 s moins le temps écoulé


def test_service_inconnu(racine, reseau, capsys):
    code, _, _ = _lancer(racine, "--service", "INCONNU", capsys=capsys)
    assert code == 2 and not reseau.appels


def test_filtre_par_service(racine, reseau, capsys):
    _lancer(racine, "--service", "hal", capsys=capsys)
    assert reseau.appels and all("archives-ouvertes.fr" in u for u in reseau.appels)


def test_derive_de_forme_signalee(racine, reseau, capsys):
    hal = next(e for _, s, e in _entrees(racine) if s == "HAL" and e["fichier"] == "courrieres-mines.json")
    corps = json.loads((racine / "hal" / "courrieres-mines.json").read_text(encoding="utf-8"))
    del corps["response"]["numFound"]
    reseau.table[str(httpx.URL(hal["url"]))] = (200, json.dumps(corps).encode(), "application/json")
    avant = _instantane(racine)
    code, sortie, _ = _lancer(racine, "--service", "HAL", capsys=capsys)
    assert code == 1 and "DERIVE" in sortie and "response.numFound" in sortie
    assert _instantane(racine) == avant  # --verifier n'écrit pas, même en cas de dérive


# ------------------------------------------------------------------------ refus, silence : laissés de côté

@pytest.mark.parametrize("reponse", [
    httpx.Response(403, text="interdit"),
    httpx.Response(429, text="trop", headers={"Retry-After": "120"}),
    httpx.Response(503, text="panne"),
    httpx.Response(403, text="<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/'>"
                             "</script></html>", headers={"cf-mitigated": "challenge"}),
    httpx.ConnectTimeout("silence"),
], ids=["403", "429", "503", "defi", "silence"])
def test_refus_ou_silence_consigne_et_service_laisse_de_cote(racine, capsys, reponse):
    avant = _instantane(racine)
    with respx.mock(assert_all_called=False) as router:
        route = router.route()
        if isinstance(reponse, Exception):
            route.mock(side_effect=reponse)
        else:
            route.mock(return_value=reponse)
        code, sortie, _ = _lancer(racine, "--ecrire", "--service", "SUDOC", "--service", "HAL", capsys=capsys)
        emises = route.call_count
    assert code == 0  # un service muet ou protégé n'est pas un échec
    assert emises == 2  # une requête par service (SUDOC, HAL) : les suivantes du même service sont laissées de côté
    assert sortie.count("AVERT") == 2 and "laissé de côté" in sortie
    assert "IGNORE" in sortie
    assert _instantane(racine) == avant  # rien n'est écrit pour un service en échec, même avec --ecrire


def test_statut_inattendu_consigne_sans_ecrire(racine, reseau, capsys):
    hal = next(e for _, s, e in _entrees(racine) if s == "HAL" and e["fichier"] == "courrieres-mines.json")
    reseau.table[str(httpx.URL(hal["url"]))] = (404, b"absent", "text/plain")
    avant = _instantane(racine)
    code, sortie, _ = _lancer(racine, "--ecrire", "--service", "HAL", capsys=capsys)
    assert code == 0 and "AVERT" in sortie and _instantane(racine) == avant


# ----------------------------------------------------------------------------------------- jamais de secret

@pytest.mark.parametrize("url", [
    "https://api.crossref.org/works?query=mines&mailto=a%40exemple.fr",
    "https://api.crossref.org/works?query=mines&mailto=a@exemple.fr",
    "https://api.europeana.eu/record/v2/search.json?wskey=cle-europeana-tres-secrete&query=mines",
    "https://exemple.fr/api?api_key=cle-europeana-tres-secrete",
    "https://exemple.fr/api?token=cle-europeana-tres-secrete",
    "http://api.crossref.org/works",
    "https://api.crossref.org/works?query=Anselme+WATTECAMPS",
    "https://api.crossref.org/works?query=brouillaud",
])
def test_requete_refusee_cle_courriel_ou_nom_de_personne(url):
    assert rec.controle_url(url)


def test_urls_enregistrees_acceptees():
    for _, manifeste in rec.manifestes(REPONSES):
        for e in manifeste["reponses"]:
            assert rec.controle_url(e["url"]) == "", e["url"]


def test_entree_avec_secret_jamais_emise(racine, reseau, capsys):
    p = racine / "crossref" / "MANIFESTE.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    m["reponses"][0]["url"] += "&mailto=chercheur%40exemple.fr"
    p.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    reseau.table[str(httpx.URL(m["reponses"][0]["url"]))] = (200, b"{}", "application/json")
    code, sortie, _ = _lancer(racine, "--ecrire", "--service", "CROSSREF", capsys=capsys)
    assert not reseau.appels and "requête refusée" in sortie and "chercheur" not in sortie


# ------------------------------------------------------------------------------------------------- ecrire

def test_ecrire_reecrit_reponses_et_manifestes(racine, reseau, capsys):
    avant = json.loads((racine / "COG-INSEE" / "MANIFESTE.json").read_text(encoding="utf-8"))
    code, sortie, _ = _lancer(racine, "--ecrire", "--service", "COG-INSEE", "--service", "WIKIDATA", capsys=capsys)
    assert code == 0 and "réécrit" in sortie
    for service in ("COG-INSEE", "WIKIDATA"):
        dossier = racine / service
        manifeste = json.loads((dossier / "MANIFESTE.json").read_text(encoding="utf-8"))
        for e in manifeste["reponses"]:
            corps = (dossier / e["fichier"]).read_bytes()
            assert e["empreinte"] == "sha256:" + hashlib.sha256(corps).hexdigest()
            assert e["statut"] == 200 and e["octets_origine"] > 0
            assert datetime.strptime(e["date"], "%Y-%m-%dT%H:%M:%SZ") >= datetime(2026, 11, 23)
    nouveau = json.loads((racine / "COG-INSEE" / "MANIFESTE.json").read_text(encoding="utf-8"))
    # la forme du manifeste est conservée (mêmes clés), seules les mesures changent
    assert [set(e) for e in nouveau["reponses"]] == [set(e) for e in avant["reponses"]]
    # les réponses réduites gardent leur contenu (réduction idempotente)
    assert (racine / "COG-INSEE" / "v_commune_depuis_1943.csv").read_bytes() == \
        (REPONSES / "COG-INSEE" / "v_commune_depuis_1943.csv").read_bytes()


def test_ecrire_ne_touche_pas_aux_services_non_choisis(racine, reseau, capsys):
    _lancer(racine, "--ecrire", "--service", "WIKIDATA", capsys=capsys)
    ref = _instantane(REPONSES)
    now = _instantane(racine)
    assert {k for k in ref if ref[k] != now[k]} <= {"WIKIDATA/MANIFESTE.json", "WIKIDATA/sparql_P374_62133.json"}
