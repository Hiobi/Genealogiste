"""#70 : archivage des pièces d'archives en ligne dans le vault (pleine résolution, convention, note compagnon,
registre sans retéléchargement, section « Pièces » des fiches, cache des aperçus hors du vault)."""

import io
import shutil
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from PIL import Image

from genealogiste_mcp import server
from genealogiste_mcp.config import Config


def _jpeg(couleur="red", taille=(300, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", taille, couleur).save(buf, "JPEG")
    return buf.getvalue()


SERVICE = "https://iiif.example/image/registre-12"
SOURCE = f"{SERVICE}/full/800,/0/gray.jpg"


@pytest.fixture
def vapp(tmp_path, fixtures):
    vault = tmp_path / "vault"
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", notes_dir=vault,
                 media_dir_conf=vault / "documents")
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    a.vault = vault
    yield a
    server.set_app(None)


@pytest.fixture
def iiif():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def test_archivage_iiif_complet(vapp, iiif):
    img = _jpeg()
    route = iiif.get(f"{SERVICE}/full/max/0/default.jpg").mock(return_value=httpx.Response(200, content=img))
    r = server.piece_archiver(SOURCE, personnes=["I1"], type_piece="D", commune="Rochefort", depot="AD17",
                              annees="1885", cote="2 E 299", acte="3")
    assert "erreur" not in r, r
    f = Path(r["chemin_absolu"])
    assert f.read_bytes() == img                                   # pleine résolution, sans réduction
    assert f.parent == vapp.vault / "documents" / "État civil" / "MARTIN"
    assert f.name == "MARTIN Jean -- ROCHEFORT - AD17 - D [1885] - 2 E 299 - n.3.jpg"
    note = f.with_suffix(".md").read_text(encoding="utf-8")
    assert "![](" in note and "%5B1885%5D" in note and "[[I1 - Jean MARTIN (1820-1885)]]" in note
    assert f"service_iiif: \"{SERVICE}\"" in note and f"consulte_le: \"{date.today().isoformat()}\"" in note
    assert "sha256:" in note
    # jamais retéléchargé
    r2 = server.piece_archiver(SOURCE, personnes=["I1"], type_piece="D")
    assert r2["deja_archivee"] and route.call_count == 1
    assert server.journal_lister(source="archives")[-1]["operation"] == "piece_archiver"


def test_repli_full_full(vapp, iiif):
    iiif.get(f"{SERVICE}/full/max/0/default.jpg").mock(return_value=httpx.Response(400))
    iiif.get(f"{SERVICE}/full/full/0/default.jpg").mock(return_value=httpx.Response(200, content=_jpeg()))
    r = server.piece_archiver(SOURCE, personnes=["DUPONT Jean"], type_piece="N")
    assert Path(r["chemin_absolu"]).exists()


def test_gallica_ark(vapp, iiif):
    img = _jpeg("blue")
    iiif.get("https://gallica.bnf.fr/iiif/ark:/12148/bpt6k123/f5/full/max/0/default.jpg").mock(
        return_value=httpx.Response(200, content=img))
    r = server.piece_archiver("https://gallica.bnf.fr/ark:/12148/bpt6k123/f5", personnes=["I1"], type_piece="D")
    note = Path(r["chemin_absolu"]).with_suffix(".md").read_text(encoding="utf-8")
    assert 'ark: "ark:/12148/bpt6k123/f5"' in note and "vue: 5" in note
    assert r["citation_suggeree"]["ark"] == "ark:/12148/bpt6k123/f5" and r["citation_suggeree"]["page"] == "vue 5"


def test_fichier_local_et_collision(vapp, tmp_path):
    a = tmp_path / "a.png"
    Image.new("RGB", (50, 40), "white").save(a)
    b = tmp_path / "b.png"
    Image.new("RGB", (50, 40), "black").save(b)
    r1 = server.piece_archiver(str(a), personnes=["DUPONT Jean"], type_piece="N", annees="1801")
    r2 = server.piece_archiver(str(b), personnes=["DUPONT Jean"], type_piece="N", annees="1801")
    p1, p2 = Path(r1["chemin_absolu"]), Path(r2["chemin_absolu"])
    assert p1.suffix == ".png" and p1.parent.name == "DUPONT" and p2.name.endswith(" (2).png")
    assert server.piece_archiver(str(a), personnes=["DUPONT Jean"], type_piece="N")["deja_archivee"]


def test_contenu_non_image_refuse(vapp, iiif):
    iiif.get(f"{SERVICE}/full/max/0/default.jpg").mock(return_value=httpx.Response(200, text="<html>connexion</html>"))
    r = server.piece_archiver(SOURCE, personnes=["I1"])
    assert "erreur" in r
    assert not list((vapp.vault / "documents").rglob("*.jpg")) if (vapp.vault / "documents").exists() else True


def test_sans_personne_a_trier_et_vivant_signale(vapp, tmp_path):
    a = tmp_path / "x.jpg"
    a.write_bytes(_jpeg("green"))
    r = server.piece_archiver(str(a), depot="AD17", cote="2 E 1")
    assert "_À trier" in Path(r["chemin_absolu"]).parts and any("_À trier" in x for x in r["alertes"])
    b = tmp_path / "y.jpg"
    b.write_bytes(_jpeg("yellow"))
    r = server.piece_archiver(str(b), personnes=["I9"], type_piece="PHOTO")
    assert any("vivante" in x for x in r["alertes"])


def test_fiche_affiche_la_piece_et_lien_graphique(vapp, tmp_path):
    a = tmp_path / "acte.jpg"
    a.write_bytes(_jpeg("purple"))
    r = server.piece_archiver(str(a), personnes=["I1"], type_piece="D", annees="1885")
    p = server.arbre_proposer(r["operations_suggerees"], "Acte de décès", "Image archivée de l'acte.")
    assert "jeton" in p, p
    server.arbre_appliquer(p["jeton"])
    server.notes_generer()
    fiche = next((vapp.vault / "personnes").glob("I1 - *.md")).read_text(encoding="utf-8")
    assert "## Pièces" in fiche and "![](../documents/" in fiche and "%5B1885%5D" in fiche
    assert ".md)" in fiche  # lien Markdown vers la note de la pièce


def test_vivant_masque_sans_piece(vapp, tmp_path):
    a = tmp_path / "p.jpg"
    a.write_bytes(_jpeg("white"))
    r = server.piece_archiver(str(a), personnes=["I9"], type_piece="PHOTO")
    p = server.arbre_proposer(r["operations_suggerees"], "Photo", "Photo de famille.")
    server.arbre_appliquer(p["jeton"])
    server.notes_generer()
    fiche = next((vapp.vault / "personnes").glob("I9 - *.md")).read_text(encoding="utf-8")
    assert "## Pièces" not in fiche


def test_cache_apercus_ignore_par_git(vapp):
    assert "cache-images/" in (vapp.store.dir / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_media_enregistrer_classe_sans_double_documents(vapp, tmp_path):
    a = tmp_path / "z.jpg"
    a.write_bytes(_jpeg("orange"))
    r = server.media_enregistrer(str(a), "DUPONT Jean -- PHOTO.jpg", classer=True)
    assert Path(r["chemin_absolu"]).parent == vapp.vault / "photographies" / "DUPONT"


def test_liens_markdown_des_pieces_resolvent_les_fichiers(vapp, tmp_path):
    from urllib.parse import unquote, urlsplit

    from markdown_it import MarkdownIt

    source = tmp_path / 'original.jpg'
    source.write_bytes(_jpeg())
    resultat = server.piece_archiver(str(source), personnes=['I1'], type_piece='N',
                                     nom='MARTIN Jean -- N [1820] (copie) #1.jpg')
    image = Path(resultat['chemin_absolu'])
    proposition = server.arbre_proposer(resultat['operations_suggerees'], 'Image fictive', 'Test de lien.')
    server.arbre_appliquer(proposition['jeton'])
    server.notes_generer()
    fiche = next((vapp.vault / 'personnes').glob('I1 - *.md'))
    compagnon = image.with_suffix('.md')
    for note in (fiche, compagnon):
        enfants = [enfant for bloc in MarkdownIt().parse(note.read_text()) for enfant in bloc.children or []]
        images = [c.attrGet('src') for c in enfants if c.type == 'image']
        assert len(images) == 1
        url = urlsplit(images[0])
        assert not url.fragment and not url.query
        assert (note.parent / unquote(url.path)).resolve() == image
        assert '%5B1820%5D' in images[0] and '%23' in images[0]
        if note == fiche:
            liens = [c.attrGet('href') for c in enfants if c.type == 'link_open']
            assert any((note.parent / unquote(lien)).resolve() == compagnon for lien in liens)
