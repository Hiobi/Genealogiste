"""#61 : notes de patronymes patronymes/<NOM>.md."""

import shutil
from datetime import date

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.config import Config
from genealogiste_mcp.models import Name
from genealogiste_mcp.pieces import parcourir


@pytest.fixture
def napp(tmp_path, fixtures):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", notes_dir=tmp_path / "vault",
                 sosa_racine="I3")
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    a.notes.today = lambda: date(2026, 11, 4)
    yield a
    server.set_app(None)


def _pieces(vault):
    ec = vault / "documents" / "État civil" / "MARTIN"
    ph = vault / "photographies" / "MARTIN"
    ec.mkdir(parents=True)
    ph.mkdir(parents=True)
    (ec / "MARTIN Jean -- ROCHEFORT - AD17 - N [1820].jpg").write_bytes(b"x")
    (ph / "MARTIN Lucas -- PHOTO [2010].jpg").write_bytes(b"x")


def test_note_patronyme_generee(napp):
    vault = napp.config.notes_dir
    _pieces(vault)
    r = server.notes_generer()
    assert "patronymes/MARTIN.md" in r["ecrites"]
    t = (vault / "patronymes" / "MARTIN.md").read_text(encoding="utf-8")
    entete = t.split("\n---\n", 1)[0]
    assert 'type: "patronyme"' in entete and 'nom: "MARTIN"' in entete
    assert "Rochefort" in t                                   # berceau
    assert "[[I1 - Jean MARTIN (1820-1885)]]" in t            # personnes liées
    assert 'WHERE patronyme = "MARTIN"' in t                  # requête Dataview
    assert "](../documents/%C3%89tat%20civil/MARTIN/MARTIN%20Jean%20--%20ROCHEFORT" in t  # pièce rangée
    assert "MARTIN Jean -- ROCHEFORT - AD17 - N \\[1820\\].jpg" in t
    assert "## Notes libres" in t
    assert (vault / "patronymes" / "DUPONT.md").exists() and (vault / "patronymes" / "BERNARD.md").exists()
    jean = next((vault / "personnes").glob("I1 - *.md")).read_text(encoding="utf-8")
    assert 'patronyme: "MARTIN"' in jean and "[[MARTIN]]" in jean
    assert "[[MARTIN]]" in (vault / "index.md").read_text(encoding="utf-8")


def test_vivants_absents_de_la_note(napp):
    vault = napp.config.notes_dir
    _pieces(vault)
    server.notes_generer()
    t = (vault / "patronymes" / "MARTIN.md").read_text(encoding="utf-8")
    assert "Lucas" not in t and "I9" not in t and "1990" not in t
    napp.notes.vivants = "complet"
    server.notes_generer()
    t = (vault / "patronymes" / "MARTIN.md").read_text(encoding="utf-8")
    assert "Lucas" in t


def test_patronyme_entierement_vivant_sans_note(napp):
    t = napp.tree()
    t.personnes["I9"].noms[0].nom = "DURAND"   # seul porteur, présumé vivant
    napp.store.write(t)
    server.notes_generer()
    assert not (napp.config.notes_dir / "patronymes" / "DURAND.md").exists()


def test_variantes_et_texte_libre_preserve(napp):
    t = napp.tree()
    t.personnes["I1"].noms.append(Name(prenoms="Joannes", nom="MARTINI", type="AKA"))
    napp.store.write(t)
    server.notes_generer()
    f = napp.config.notes_dir / "patronymes" / "MARTIN.md"
    texte = f.read_text(encoding="utf-8")
    assert "MARTINI" in texte
    f.write_text(texte + "\nOrigine savoyarde probable.\n", encoding="utf-8")
    avant = f.read_text(encoding="utf-8")
    r = server.notes_generer()
    assert "patronymes/MARTIN.md" not in r["ecrites"] and f.read_text(encoding="utf-8") == avant


def test_dossier_patronymes_protege(napp, tmp_path):
    vault = napp.config.notes_dir
    (vault / "patronymes").mkdir(parents=True)
    (vault / "patronymes" / "scan.jpg").write_bytes(b"x")
    fichiers, _ = parcourir(vault)
    assert not any(f.rel.parts[0] == "patronymes" for f in fichiers)


def test_patronyme_devenu_sans_porteur_signale(napp):
    napp.notes.vivants = "complet"
    t = napp.tree()
    t.personnes["I9"].noms[0].nom = "DURAND"
    napp.store.write(t)
    server.notes_generer()
    f = napp.config.notes_dir / "patronymes" / "DURAND.md"
    assert "Lucas" in f.read_text(encoding="utf-8")
    napp.notes.vivants = "masquer"
    r = server.notes_generer()
    texte = f.read_text(encoding="utf-8")
    assert "Lucas" not in texte and "Aucune personne affichable" in texte
    assert any("DURAND.md" in a and "plus aucune personne" in a for a in r["alertes"])


def test_lire_et_generer_un_patronyme(napp):
    r = server.notes_generer("I1")
    assert "patronymes/MARTIN.md" in r["ecrites"]
    assert "## Porteurs" in server.notes_lire("martin")["contenu"]


def test_collision_troncature_ne_fusionne_pas_les_fiches(napp):
    premier, second = 'A' * 125 + 'X', 'A' * 125 + 'Y'
    tree = napp.tree()
    tree.personnes['I1'].noms[0].nom = premier
    napp.store.write(tree)
    server.notes_generer(premier)
    avant = server.notes_ajouter(premier, 'Texte manuel alpha')
    assert 'erreur' not in avant
    tree.personnes['I2'].noms[0].nom = second
    napp.store.write(tree)
    resultat = server.notes_generer()
    assert 'erreur' not in resultat, resultat
    a, b = server.notes_lire(premier), server.notes_lire(second)
    assert a['fichier'] != b['fichier']
    assert 'Texte manuel alpha' in a['contenu']
    assert 'Texte manuel alpha' not in b['contenu']
    assert '[[I1 - ' in a['contenu'] and '[[I2 - ' not in a['contenu']
    assert '[[I2 - ' in b['contenu'] and '[[I1 - ' not in b['contenu']


def test_collision_caracteres_interdits_ne_fusionne_pas_les_porteurs(napp):
    tree = napp.tree()
    tree.personnes['I1'].noms[0].nom = 'A/B'
    tree.personnes['I2'].noms[0].nom = 'A:B'
    napp.store.write(tree)
    assert 'erreur' not in server.notes_generer()
    a, b = server.notes_lire('A/B'), server.notes_lire('A:B')
    assert 'erreur' not in a and 'erreur' not in b
    assert a['fichier'] != b['fichier']
    assert '[[I1 - ' in a['contenu'] and '[[I2 - ' not in a['contenu']
    assert '[[I2 - ' in b['contenu'] and '[[I1 - ' not in b['contenu']


def test_remasquage_cible_nettoie_ancien_patronyme_et_preserve_manuel(napp):
    napp.notes.vivants = 'complet'
    tree = napp.tree()
    tree.personnes['I9'].noms[0].nom = 'DURAND'
    napp.store.write(tree)
    server.notes_generer()
    server.notes_ajouter('DURAND', 'Texte libre à conserver')
    fichier = napp.config.notes_dir / 'patronymes/DURAND.md'
    assert 'Lucas' in fichier.read_text()
    napp.notes.vivants = 'masquer'
    resultat = server.notes_generer('I9')
    contenu = fichier.read_text()
    genere = contenu.split('## Notes libres', 1)[0]
    assert 'Lucas' not in genere and '1990' not in genere and '[[I9 - ' not in genere
    assert 'Texte libre à conserver' in contenu
    assert any('DURAND.md' in a for a in resultat.get('alertes', []))
    index = (napp.config.notes_dir / 'index.md').read_text()
    assert '[[DURAND]]' not in index


@pytest.mark.parametrize('nom', ['CON', 'AUX', 'NUL', 'COM1', 'LPT9', 'ÉTÉ', 'D’ŒUVRE', '界' * 125])
def test_noms_portables_et_liens_coherents(napp, nom):
    import re
    from pathlib import Path

    tree = napp.tree()
    tree.personnes['I1'].noms[0].nom = nom
    napp.store.write(tree)
    resultat = server.notes_generer()
    assert 'erreur' not in resultat, resultat
    note = server.notes_lire(nom)
    assert 'erreur' not in note, note
    fichier = Path(note['fichier'])
    assert fichier.exists() and len(fichier.name.encode('utf-8')) <= 200
    assert fichier.stem.split('.')[0].upper() not in {'CON', 'AUX', 'NUL', 'COM1', 'LPT9'}
    assert not any(c in fichier.name for c in '<>:"/\\|?*')
    noms = {p.stem for p in napp.config.notes_dir.rglob('*.md')}
    for p in napp.config.notes_dir.rglob('*.md'):
        for lien in re.findall(r'\[\[([^\]|]+)', p.read_text()):
            assert lien in noms, (p, lien)


@pytest.mark.parametrize('changement', ['renommer', 'prive', 'supprimer'])
def test_ancien_patronyme_sans_porteur_ne_garde_pas_de_donnees(napp, changement):
    tree = napp.tree()
    tree.personnes['I1'].noms[0].nom = 'EXEMPLE'
    napp.store.write(tree)
    server.notes_generer()
    note = napp.config.notes_dir / 'patronymes/EXEMPLE.md'
    server.notes_ajouter('EXEMPLE', 'Contenu manuel de référence')
    if changement == 'renommer':
        tree.personnes['I1'].noms[0].nom = 'NOUVEAU'
    elif changement == 'prive':
        tree.personnes['I1'].prive = True
    else:
        del tree.personnes['I1']
    napp.store.write(tree)
    resultat = server.notes_generer('tout' if changement == 'supprimer' else 'I1')
    assert 'erreur' not in resultat, resultat
    contenu = note.read_text()
    assert '[[I1 - ' not in contenu.split('## Notes libres', 1)[0]
    assert 'Contenu manuel de référence' in contenu
    assert any('EXEMPLE.md' in a for a in resultat.get('alertes', []))
    if changement == 'renommer':
        assert '[[I1 - ' in (napp.config.notes_dir / 'patronymes/NOUVEAU.md').read_text()


def test_fichier_manuel_preexistant_pas_ecrase(napp):
    dossier = napp.config.notes_dir / 'patronymes'
    dossier.mkdir(parents=True)
    fichier = dossier / 'MARTIN.md'
    fichier.write_text('# Mon carnet personnel\n\nTexte irremplaçable.\n')
    avant = fichier.read_bytes()
    resultat = server.notes_generer()
    assert 'erreur' in resultat and 'écrasement' in resultat['erreur']
    assert fichier.read_bytes() == avant
    assert not (napp.config.notes_dir / 'personnes').exists()


@pytest.mark.parametrize('nom, visible, dossier, prenom, fichier', [
    ('MARTIN', 'MARTIN', 'MARTIN', 'Élodie', 'MARTIN Elodie.jpg'),
    ('A/B', 'A-B', 'A-B', 'Élodie', 'A-B Elodie.jpg'),
    ('ÉTÉ', 'ÉTÉ', 'ÉTÉ', 'E\u0301lodie', 'E\u0301TE\u0301 E\u0301lodie.jpg'),
])
def test_piece_de_vivant_omise_meme_sans_convention_et_sans_accents(napp, nom, visible, dossier, prenom, fichier):
    tree = napp.tree()
    tree.personnes['I9'].noms[0].nom = nom
    tree.personnes['I9'].noms[0].prenoms = prenom
    tree.personnes['I1'].noms[0].nom = visible
    napp.store.write(tree)
    dossier = napp.config.notes_dir / 'photographies' / dossier
    dossier.mkdir(parents=True)
    (dossier / fichier).write_bytes(b'fictif')
    (dossier / f'{visible} Jean -- PHOTO [1880].jpg').write_bytes(b'fictif')
    resultat = server.notes_generer()
    assert 'erreur' not in resultat, resultat
    contenu = server.notes_lire(visible)['contenu']
    assert 'lodie' not in contenu
    assert f'{visible} Jean' in contenu


def test_hook_transmet_les_alertes_de_remasquage(napp):
    napp.notes.vivants = 'complet'
    tree = napp.tree()
    tree.personnes['I9'].noms[0].nom = 'DURAND'
    napp.store.write(tree)
    server.notes_generer()
    server.notes_ajouter('DURAND', 'Notes manuelles')
    napp.notes.vivants = 'masquer'
    resultat = server.journal_ajouter('Test fictif', 'consultation', 'negatif', 'Rien trouvé', personne='I9')
    assert not resultat['notes']['erreurs']
    assert any('DURAND.md' in a for a in resultat['notes'].get('alertes', []))


def test_ancienne_fiche_tronquee_nettoyee_sans_perdre_texte_libre(napp):
    from pathlib import Path

    nom = 'A' * 125 + 'X'
    tree = napp.tree()
    tree.personnes['I1'].noms[0].nom = nom
    napp.store.write(tree)
    server.notes_generer(nom)
    nouvelle = Path(server.notes_lire(nom)['fichier'])
    server.notes_ajouter(nom, 'Texte manuel historique')
    ancienne = nouvelle.with_name('A' * 120 + '.md')
    nouvelle.rename(ancienne)
    resultat = server.notes_generer()
    assert 'erreur' not in resultat, resultat
    assert '[[I1 - ' not in ancienne.read_text().split('## Notes libres', 1)[0]
    assert 'Texte manuel historique' in ancienne.read_text()
    assert '[[I1 - ' in nouvelle.read_text()
    assert any(ancienne.name in a and 'non canonique' in a for a in resultat.get('alertes', []))
    avant = {p: p.read_bytes() for p in napp.config.notes_dir.rglob('*.md')}
    server.notes_generer()
    assert {p: p.read_bytes() for p in napp.config.notes_dir.rglob('*.md')} == avant


def test_lien_symbolique_de_fiche_ne_touche_pas_un_fichier_externe(napp, tmp_path):
    dossier = napp.config.notes_dir / 'patronymes'
    dossier.mkdir(parents=True)
    externe = tmp_path / 'note-privee.md'
    (dossier / 'MARTIN.md').symlink_to(externe)
    resultat = server.notes_generer()
    assert 'erreur' in resultat and 'symbolique' in resultat['erreur']
    assert not externe.exists()
    assert not (napp.config.notes_dir / 'personnes').exists()


def test_pieces_via_dossier_symbolique_externe_non_listees(napp, tmp_path):
    externe = tmp_path / 'hors-vault'
    (externe / 'MARTIN').mkdir(parents=True)
    (externe / 'MARTIN/scan-externe.jpg').write_bytes(b'fictif')
    napp.config.notes_dir.mkdir()
    (napp.config.notes_dir / 'photographies').symlink_to(externe, target_is_directory=True)
    resultat = server.notes_generer()
    assert 'erreur' not in resultat, resultat
    assert 'scan-externe' not in server.notes_lire('MARTIN')['contenu']


def test_texte_libre_signale_si_patronyme_garde_des_porteurs_masques(napp):
    napp.notes.vivants = 'complet'
    server.notes_generer()
    server.notes_ajouter('MARTIN', 'Lucas : appel familial à conserver')
    napp.notes.vivants = 'masquer'
    resultat = server.notes_generer('I9')
    contenu = server.notes_lire('MARTIN')['contenu']
    assert 'Lucas : appel familial à conserver' in contenu.split('## Notes libres', 1)[1]
    assert 'Lucas' not in contenu.split('## Notes libres', 1)[0]
    assert any('MARTIN.md' in a and 'saisis à la main' in a for a in resultat.get('alertes', []))


@pytest.mark.parametrize('nom, prenom', [('李', 'Lucas'), ('X', 'Lucas'), ('李', '雷')])
def test_piece_nommant_un_masque_avec_nom_court_exclue(napp, nom, prenom):
    tree = napp.tree()
    tree.personnes['I1'].noms[0].nom = nom
    tree.personnes['I9'].noms[0].nom = nom
    tree.personnes['I9'].noms[0].prenoms = prenom
    napp.store.write(tree)
    dossier = napp.config.notes_dir / 'photographies' / nom
    dossier.mkdir(parents=True)
    (dossier / f'{nom} {prenom} -- PHOTO [2020].jpg').write_bytes(b'fictif')
    (dossier / f'{nom} Jean -- PHOTO [1880].jpg').write_bytes(b'fictif')
    resultat = server.notes_generer()
    assert 'erreur' not in resultat, resultat
    contenu = server.notes_lire(nom)['contenu']
    assert f'{nom} {prenom}' not in contenu
    assert f'{nom} Jean' in contenu
    napp.notes.vivants = 'complet'
    server.notes_generer()
    assert f'{nom} {prenom}' in server.notes_lire(nom)['contenu']


@pytest.mark.parametrize('lien', [
    'vivant', 'prive', 'citation', 'partage', 'alias', 'source_privee', 'citation_privee', 'evenement_prive',
    'personne_privee',
])
def test_media_confidentiel_au_nom_neutre_exclu_des_notes(napp, lien):
    from genealogiste_mcp.models import Citation, Event, Media

    tree = napp.tree()
    dossier = napp.config.notes_dir / 'photographies/MARTIN'
    dossier.mkdir(parents=True)
    secret = dossier / 'scan-fictif.jpg'
    public = dossier / 'acte-historique.jpg'
    secret.write_bytes(b'fictif')
    public.write_bytes(b'fictif')
    tree.medias['O99'] = Media(id='O99', fichier=str(secret), prive=lien == 'prive')
    tree.medias['O98'] = Media(id='O98', fichier=str(public), citations=[Citation(source='S3')])
    tree.personnes['I1'].medias.append('O98')
    if lien in {'vivant', 'partage', 'alias', 'personne_privee'}:
        tree.personnes['I9'].medias.append('O99')
    elif lien == 'citation':
        tree.personnes['I9'].citations.append(Citation(source='S1', medias=['O99']))
    if lien in {'prive', 'partage'}:
        tree.personnes['I1'].medias.append('O99')
    if lien == 'personne_privee':
        tree.personnes['I9'].prive = True
    if lien == 'alias':
        tree.medias['O97'] = Media(id='O97', fichier='../vault/photographies/MARTIN/scan-fictif.jpg')
        tree.personnes['I1'].medias.append('O97')
    if lien == 'source_privee':
        tree.sources['S1'].prive = True
        tree.personnes['I1'].citations.append(Citation(source='S1', medias=['O99']))
    if lien == 'citation_privee':
        tree.personnes['I1'].citations.append(Citation(source='S3', prive=True, medias=['O99']))
    if lien == 'evenement_prive':
        tree.personnes['I1'].evenements.append(Event(type='EVEN', prive=True,
                                                   citations=[Citation(source='S3', medias=['O99'])]))
    napp.store.write(tree)
    resultat = server.notes_generer()
    assert 'erreur' not in resultat, resultat
    for contenu in (server.notes_lire('MARTIN')['contenu'], server.notes_lire('I1')['contenu']):
        assert 'scan-fictif.jpg' not in contenu
        assert 'acte-historique.jpg' in contenu
    napp.notes.vivants = 'complet'
    server.notes_generer()
    assert ('scan-fictif.jpg' in server.notes_lire('MARTIN')['contenu']) == (lien not in {'prive', 'source_privee', 'citation_privee', 'evenement_prive', 'personne_privee'})
    assert secret.read_bytes() == b'fictif' and public.read_bytes() == b'fictif'


def test_remasquage_retire_media_connu_et_preserve_notes_libres(napp):
    from genealogiste_mcp.models import Media

    tree = napp.tree()
    dossier = napp.config.notes_dir / 'photographies/MARTIN'
    dossier.mkdir(parents=True)
    image = dossier / 'scan-fictif.jpg'
    image.write_bytes(b'fictif')
    tree.medias['O99'] = Media(id='O99', fichier=str(image))
    tree.personnes['I9'].medias.append('O99')
    napp.store.write(tree)
    napp.notes.vivants = 'complet'
    server.notes_generer()
    server.notes_ajouter('MARTIN', 'Texte manuel conservé')
    assert 'scan-fictif.jpg' in server.notes_lire('MARTIN')['contenu']
    napp.notes.vivants = 'masquer'
    resultat = server.notes_generer('I9')
    contenu = server.notes_lire('MARTIN')['contenu']
    assert 'scan-fictif.jpg' not in contenu and 'Texte manuel conservé' in contenu
    assert image.read_bytes() == b'fictif'
    assert any('MARTIN.md' in a for a in resultat.get('alertes', []))
