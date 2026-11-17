"""#158 : mode autonome du chercheur (parcours archives compris, sans question, arrêt sur budget, dépôt en file).

Deux volets :
- documentation : agent, commandes et skill décrivent le même parcours d'archives ; la section « Mode autonome »
  de l'agent ne cite que des outils autorisés sans confirmation (aucune écriture) ; le compte rendu a un format
  fixe, documenté dans docs/enquetes.md ;
- recette : la séquence d'outils du parcours autonome, rejouée sur la fixture avec HTTP mocké, va jusqu'au dépôt
  d'une proposition sans aucune écriture de l'arbre ni aucun outil soumis à confirmation (hook réel exécuté).
  Un vrai modèle ne tourne pas en CI : la recette avec Claude reste manuelle (docs/enquetes.md)."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
import respx
from PIL import Image
from test_coherence_docs import noms_cites
from test_enquetes import MANIFEST, REGISTRE, mock_ad59, mock_matchid
from test_outils import PREFIXES, _decisions_hook

from genealogiste_mcp import outils, server

ROOT = Path(__file__).resolve().parents[2]
CHERCHEUR = ROOT / "agents" / "chercheur.md"

# Parcours d'archives commun : service et couverture, localisation du registre, sondage/navigation, lecture,
# archivage de la pièce.
PARCOURS = {"archives_service", "archives_registres", "ark_resoudre", "archives_naviguer", "archive_image",
            "piece_archiver"}
TITRES_COMPTE_RENDU = ("## Trouvé", "## Négatif", "## Bloqué", "## À valider", "## À faire à la main")


def _lire(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def section(texte: str, titre: str) -> str:
    """Contenu d'une section « ## titre » jusqu'à la section suivante de même niveau (hors blocs de code : un
    exemple de compte rendu contient des titres « ## »)."""
    lignes, dedans, bloc = [], False, False
    for ligne in texte.splitlines():
        if ligne.startswith("```"):
            bloc = not bloc
        if not bloc and ligne.startswith("## "):
            if dedans:
                break
            dedans = ligne[3:].strip() == titre
            continue
        if dedans:
            lignes.append(ligne)
    assert dedans, f"section « {titre} » absente"
    return "\n".join(lignes)


def classe_effective(nom: str, sans_conditions: bool = True) -> str:
    """Classe d'un outil tel qu'appelé en mode autonome : un outil en deux temps (CONDITIONS) l'est sans le
    paramètre qui le ferait passer en écriture (budget, réouverture), ce que la section interdit."""
    if sans_conditions and nom in outils.CONDITIONS:
        return outils.CONDITIONS[nom][1]
    return outils.OUTILS[nom][1]


# ---------------------------------------------------------------------------- documentation

@pytest.mark.parametrize("rel", ["agents/chercheur.md", "commands/enquete.md", "commands/acte.md",
                                 "skills/genealogiste/SKILL.md", "skills/sources-francaises/SKILL.md"])
def test_meme_parcours_archives_partout(rel):
    manquants = PARCOURS - noms_cites(_lire(rel))
    assert not manquants, f"{rel} ne décrit pas le parcours d'archives complet : {sorted(manquants)}"


def test_mode_autonome_n_utilise_aucun_outil_d_ecriture():
    autonome = section(CHERCHEUR.read_text(encoding="utf-8"), "Mode autonome")
    cites = noms_cites(autonome)
    assert PARCOURS | {"enquete_ouvrir", "enquete_reprendre", "enquete_noter", "propositions_deposer",
                       "prochaine_source", "arbre_statut_preuve"} <= cites
    ecritures = {n for n in cites if classe_effective(n) == outils.ECRITURE}
    assert not ecritures, f"outils soumis à confirmation dans le mode autonome : {sorted(ecritures)}"
    assert all(outils.DECISIONS[classe_effective(n)] == outils.ALLOW for n in cites)
    # les paramètres qui feraient demander une confirmation sont explicitement exclus
    assert "budget" in autonome and "ouverte" in autonome


def test_interdits_du_mode_autonome():
    texte = CHERCHEUR.read_text(encoding="utf-8")
    interdits = noms_cites(section(texte, "Interdits en mode autonome"))
    assert {"arbre_proposer", "arbre_appliquer", "media_enregistrer"} <= interdits
    # tout outil de classe écriture cité dans l'agent hors du mode autonome est listé parmi les interdits
    ecritures = {n for n in noms_cites(texte) if classe_effective(n) == outils.ECRITURE}
    assert ecritures <= interdits


def test_marqueur_et_commandes():
    texte = CHERCHEUR.read_text(encoding="utf-8")
    assert "MODE AUTONOME" in texte and "enquete: <id>" in texte
    assert "Mode interactif" in texte
    for rel in ("commands/enquete.md", "commands/acte.md"):
        commande = _lire(rel)
        assert "--autonome" in commande and "MODE AUTONOME" in commande, rel
        assert "--autonome" in re.search(r"^argument-hint:.*$", commande, re.M).group(0), rel
    assert "--autonome" in _lire("wiki/Commandes.md")


def test_compte_rendu_a_format_fixe_documente():
    doc = section(_lire("docs/enquetes.md"), "Compte rendu autonome")
    agent = section(CHERCHEUR.read_text(encoding="utf-8"), "Compte rendu autonome")
    for titre in TITRES_COMPTE_RENDU:
        assert re.search(rf"^{re.escape(titre)}$", doc, re.M), titre
        assert titre in agent, titre
    assert "Budget :" in doc and "Budget :" in agent
    assert "docs/enquetes.md" in agent


def test_recette_manuelle_documentee():
    doc = section(_lire("docs/enquetes.md"), "Recette du mode autonome")
    assert "--autonome" in doc and "test_chercheur_autonome" in doc


# ---------------------------------------------------------------------------- recette (séquence rejouée)

def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def routes():
    with respx.mock(assert_all_called=False) as router:
        yield router


class Chercheur:
    """Rejoue les appels d'outils d'un chercheur autonome : chaque appel passe d'abord par le hook réel (plugin
    stdio et serveur HTTP Docker) et doit être autorisé sans confirmation, sinon une personne serait sollicitée."""

    def __init__(self):
        self.appels: list[str] = []

    def __call__(self, _outil: str, /, **params):
        for prefixe in PREFIXES:
            decisions = _decisions_hook(prefixe + _outil, params)
            assert decisions and set(decisions) == {"allow"}, f"{_outil} demanderait une confirmation : {decisions}"
        self.appels.append(_outil)
        return getattr(server, _outil)(**params)


def test_recette_enquete_autonome_jusqu_au_depot(app_famille, routes):
    mock_matchid(routes)
    mock_ad59(routes)
    routes.get(MANIFEST).respond(200, json={"items": [
        {"items": [{"items": [{"body": {"id": "https://archives.exemple.org/vues/vue.jpg", "type": "Image"}}]}]}
        for _ in range(3)]})
    routes.get("https://archives.exemple.org/vues/vue.jpg").respond(200, content=_jpeg(),
                                                                    headers={"Content-Type": "image/jpeg"})
    avant, commits = app_famille.store.text(), len(app_famille.store.log(50))
    outil = Chercheur()

    # Le lanceur (commande, campagne) a ouvert l'enquête avec son budget, avec l'accord de l'utilisateur.
    eid = server.enquete_ouvrir("Décès de Jean MARTIN (1885, Rochefort)", personnes=["I1"],
                                id="deces-jean-martin", budget={"images": 5})["id"]

    # 1. reprise et cadrage
    assert outil("enquete_reprendre", enquete=eid)["enquete"] == eid
    assert outil("arbre_vivant", id="I1")["vivant"] is False
    outil("arbre_personne", id="I1")
    outil("enquete_noter", enquete=eid, piste={"question": "Décès de Jean MARTIN en 1885 à Rochefort",
                                                "hypotheses": ["Rochefort, 4 janvier 1885"], "statut": "en_cours"})
    # 2. sources nominatives (matchID : négatif attendu avant 1970)
    multi = outil("recherche_multi", nom="MARTIN", prenom="Jean", decede_vers="1885", lieu="Rochefort",
                  sources=["matchid"], personne="I1", enquete=eid)
    assert "budget" in multi
    # 3. archives : service et couverture, registre, sondage, lecture, archivage
    outil("archives_service", departement="17", document="deces", annee=1885)
    outil("prochaine_source", fait="DEAT", date_fait="1885", lieu="Rochefort")
    nav = outil("archives_naviguer", source=REGISTRE, page=1, pas=3, enquete=eid)
    assert "erreur" not in nav, nav
    img = outil("archive_image", source=MANIFEST, page=1, enquete=eid)
    assert "erreur" not in img and img["budget"]["reste"]["images"] == 4, img
    piece = outil("piece_archiver", source=MANIFEST, page=1, personnes=["I1"], type_piece="D",
                  commune="Rochefort", depot="AD17", annees="1885", acte="3")
    assert "erreur" not in piece, piece
    outil("enquete_noter", enquete=eid, registre={"source": REGISTRE, "service": "AD17", "piste": "p1",
                                                   "lectures": [{"vue": 1, "date": "1885-01-04", "type": "deces",
                                                                 "numero": "3"}],
                                                   "verdict": "acte n° 3 lu", "statut": "trouve"})
    # ce qui exige une personne devient une tâche manuelle, jamais une question
    outil("enquete_noter", enquete=eid, tache={"description": "AD17 : table décennale 1883-1892 non numérisée, "
                                                              "consultation sur place", "service": "AD17",
                                                "piste": "p1"})
    # 4. preuve et dépôt dans la file (jamais arbre_proposer + arbre_appliquer)
    outil("arbre_statut_preuve", id="I1", fait="DEAT")
    depot = outil("propositions_deposer", operations=[
        {"op": "ajouter_citation", "cible": {"type": "evenement", "uid": "11111111-1111-4111-8111-111111111113"},
         "citation": {"source": "S1", "page": "Décès 1885, acte n° 3, vue 1", "type_source": "originale",
                      "information": "primaire", "consultation": "image"}}],
        titre="Acte de décès de Jean MARTIN (1885) — à vérifier",
        justification="Acte n° 3 lu sur le registre ; vérificateur indépendant non sollicité.",
        pieces=[piece["fichier"]], personnes=["I1"], enquete=eid)
    assert "erreur" not in depot and depot["statut"] == "en_attente", depot
    outil("enquete_noter", enquete=eid, piste={"id": "p1", "statut": "trouve",
                                                "note": f"proposition {depot['id']} déposée"})

    # aucune écriture d'arbre
    assert app_famille.store.text() == avant
    assert len(app_famille.store.log(50)) == commits
    assert not {"arbre_proposer", "arbre_appliquer", "media_enregistrer"} & set(outil.appels)
    # proposition en file liée à l'enquête
    file = {e["id"]: e for e in server.propositions_lister()["propositions"]}
    assert file[depot["id"]]["enquete"] == eid and file[depot["id"]]["statut"] == "en_attente"
    # budget consommé, côté serveur
    etat = server.enquete_etat(eid)
    assert etat["consomme"]["images"] == 1 and sum(etat["consomme"]["requetes"].values()) >= 2
    assert etat["statut"] == "ouverte"
    # état reprenable : demandes déjà faites, tâche manuelle en attente
    reprise = server.enquete_reprendre(eid)
    assert {d["outil"] for d in reprise["deja_fait"]} >= {"recherche_multi", "archives_naviguer", "archive_image"}
    assert any("table décennale" in t["description"] for t in reprise["taches_manuelles"])
    assert reprise["budget"]["reste"]["images"] == 4
