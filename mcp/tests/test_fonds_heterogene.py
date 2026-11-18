"""#106 : parcours complet sur un fonds fictif hétérogène, hors vault Obsidian.

Noms opaques (UUID, IMG_), pièces déjà nommées et rangées, doublons, notes Markdown ordinaires avec des liens
existants. Les cas unitaires (convention, collisions, notes compagnons, médias de l'arbre) sont dans
test_pieces.py ; ici on enchaîne le parcours de /organise et on vérifie que les notes ne sont jamais réécrites
et que leurs liens rendus caducs sont signalés avant l'accord."""

import hashlib
from collections import Counter
from pathlib import Path

import pytest

from genealogiste_mcp import pieces, server

UUID = "3f2a9c1e-77aa-4c1b-9d0e-1234567890ab.jpg"
RANGEE = "documents/État civil/DUPONT/DUPONT Jean -- ERRE - AD59 - N [1850] - 5 Mi 023 - p.12 n.4.jpg"
NOMMEE = "vrac/MARTIN Marie -- ERRE - AD59 - D [1901] - 4 E 87 - p.3 n.18.pdf"
NOTE_RECHERCHE = (
    "---\ntags: [dupont, a-verifier]\nstatut: hypothèse\n---\n"
    "# Recherches DUPONT\n\n"
    "Scan reçu d'un cousin, à identifier : ![[IMG_1234.jpg]]\n"
    "Naissance déjà rangée : [[DUPONT Jean -- ERRE - AD59 - N [1850] - 5 Mi 023 - p.12 n.4.jpg]]\n"
    "Décès de Marie : [acte](vrac/MARTIN%20Marie%20--%20ERRE%20-%20AD59%20-%20D%20%5B1901%5D%20-%204%20E%2087"
    "%20-%20p.3%20n.18.pdf)\n\nTexte libre : ne jamais réécrire.\n"
)
NOTE_JOURNAL = "Pièce inconnue : [[" + UUID + "]]\n"


def _ecrire(racine: Path, rel: str, contenu: bytes) -> None:
    p = racine / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenu)


def _etat(racine: Path) -> dict[str, str]:
    return {str(p.relative_to(racine)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(racine.rglob("*")) if p.is_file() and "_organisation" not in p.parts}


def _notes(racine: Path) -> dict[str, bytes]:
    return {str(p.relative_to(racine)): p.read_bytes() for p in racine.rglob("*.md")}


@pytest.fixture
def fonds(tmp_path):
    """Dossier ordinaire (pas de .obsidian) : la racine d'organisation est le dossier lui-même."""
    r = tmp_path / "fonds"
    _ecrire(r, UUID, b"opaque-uuid")
    _ecrire(r, "IMG_1234.jpg", b"img-1234")
    _ecrire(r, "Scans/IMG_1235.jpg", b"img-1234")  # même contenu : doublon
    _ecrire(r, RANGEE, b"acte-dupont")
    _ecrire(r, NOMMEE, b"%PDF deces martin")
    _ecrire(r, "Recherches DUPONT.md", NOTE_RECHERCHE.encode())
    _ecrire(r, "notes/Journal.md", NOTE_JOURNAL.encode())
    return r


def test_parcours_fonds_heterogene(app, fonds):
    initial = _etat(fonds)
    notes = _notes(fonds)

    inv = server.pieces_inventaire(str(fonds))
    assert inv["pieces"] == 5 and inv["doublons"] == 1 and inv["deja_classees"] == 1
    assert inv["ignores"] == {".md": 2}

    # Plan : rien ne bouge ; ne pas appliquer le jeton (refus) laisse le fonds intact.
    plan = server.pieces_proposer(str(fonds))
    assert plan["racine"] == str(fonds.resolve()) and plan["jeton"]
    vers = {m.split("  →  ")[0]: m.split("  →  ")[1].split("  (")[0] for m in plan["apercu"]}
    assert RANGEE not in vers  # déjà nommée et rangée : on n'y touche pas
    assert vers["IMG_1234.jpg"] == "_À trier/IMG_1234.jpg"
    assert vers[UUID] == f"_À trier/{UUID}"
    assert vers["Scans/IMG_1235.jpg"] == "archives/Doublons/Scans/IMG_1235.jpg"
    assert vers[NOMMEE] == "documents/État civil/MARTIN/" + Path(NOMMEE).name
    assert not any(k.endswith(".md") for k in vers)
    # Seul le lien par chemin vers la pièce déplacée devient caduc ; les liens wiki par nom restent valides.
    assert plan["nb_references_notes"] == 1 and "references_notes_conseil" in plan
    assert plan["references_notes"][0] == {"note": "Recherches DUPONT.md", "lien": NOMMEE, "piece": NOMMEE,
                                      "vers": vers[NOMMEE]}
    assert _etat(fonds) == initial

    # Accord : déplacements, empreintes conservées, notes ordinaires intactes.
    out = server.pieces_appliquer(plan["jeton"])
    assert not out["erreurs"]
    assert out["controle"] == {"avant": 5, "apres": 5, "empreintes_identiques": True}
    apres = _etat(fonds)
    assert Counter(apres.values()) == Counter(initial.values())
    assert _notes(fonds) == notes
    assert (fonds / RANGEE).read_bytes() == b"acte-dupont"

    # Réexécution : aucun nouveau plan, le doublon isolé n'est pas réisolé.
    assert server.pieces_proposer(str(fonds))["note"] == "Rien à déplacer."

    # Triage : la pièce IMG_ identifiée est renommée ; son lien wiki devient caduc et est signalé.
    nom = server.piece_nommer(["DUPONT Pierre"], "Erre", "AD59", "M", "1878", "5 Mi 024", "40", "9")["nom"]
    tri = server.pieces_proposer(str(fonds), seulement_renommages=True,
                                renommages=[{"actuel": "_À trier/IMG_1234.jpg", "propose": nom}])
    assert tri["nb_deplacements"] == 1 and tri["doublons"] == 0
    assert [lien["note"] for lien in tri["references_notes"]] == ["Recherches DUPONT.md"]
    assert tri["references_notes"][0]["vers"] == f"documents/État civil/DUPONT/{nom}"
    out2 = server.pieces_appliquer(tri["jeton"])
    assert not out2["erreurs"] and out2["controle"]["empreintes_identiques"]
    assert _notes(fonds) == notes
    assert server.pieces_proposer(str(fonds))["note"] == "Rien à déplacer."

    # Annulation, dernier rangement d'abord : retour exact à l'état initial.
    for journal in (out2["journal"], out["journal"]):
        undo = server.pieces_proposer(str(fonds), annuler=Path(journal).name)
        assert not server.pieces_appliquer(undo["jeton"])["erreurs"]
    assert _etat(fonds) == initial


def test_references_notes_lecture_seule_et_note_compagnon_exclue(tmp_path):
    from genealogiste_mcp import archivage

    r = tmp_path / "fonds"
    _ecrire(r, "scan.jpg", b"image")
    archivage.note_compagnon(r / "scan.jpg", {}, [], "")
    _ecrire(r, "Analyse.md", b"Relu : ![](scan.jpg) et [[scan.jpg|vue 12]]\n")
    _ecrire(r, ".cache/ignore.md", b"[[scan.jpg]]")
    avant = _notes(r)
    plan = pieces.planifier(r)
    assert [m["vers"] for m in plan["deplacements"]] == ["_À trier/scan.md", "_À trier/scan.jpg"]
    # Lien Markdown relatif cassé par le déplacement ; lien wiki par nom conservé ; note compagnon mise à jour
    # par l'outil ; dossier caché ignoré.
    assert plan["references_notes"] == [{"note": "Analyse.md", "lien": "scan.jpg", "piece": "scan.jpg",
                                    "vers": "_À trier/scan.jpg"}]
    assert _notes(r) == avant
