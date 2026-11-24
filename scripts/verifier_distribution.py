"""Refuse les fichiers privés suivis par Git, même ajoutés avec git add -f, et tout fichier qui ressemble au jeu
Cassini (CC BY-NC-SA 4.0, #349)."""

import os
import subprocess
import sys
from pathlib import PurePosixPath


def interdit(chemin: str) -> bool:
    p = PurePosixPath(chemin)
    if chemin == '.env.example':
        return False
    if p.suffix.lower() == '.ged':
        return p.parent not in (PurePosixPath('mcp/tests/fixtures'), PurePosixPath('mcp/tests/fixtures/contexte'))
    if p.suffix.lower() in {'.gramps', '.gpkg'}:  # arbre fictif écrit par Gramps Desktop (#269), et rien d'autre
        return not (p.parent.parent == PurePosixPath('mcp/tests/fixtures/gramps-desktop')
                    and p.parent.name.startswith('gramps-') and p.stem == 'famille')
    return (p.name == '.env' or p.name.startswith('.env.')
            or p.suffix.lower() in {'.token', '.key', '.pem', '.p12', '.pfx', '.sqlite', '.db',
                                    '.sql', '.jsonl', '.gramps', '.gpkg'}
            or '.sqlite-' in p.name
            or any(part in {'.propositions', 'medias', 'exports', 'rapports', 'cache-images'} for part in p.parts)
            or p.parts[0] in {'personnes', 'familles', 'patronymes', 'photographies', 'documents', 'notes'}
            or (p.parts[0] == 'data' and chemin not in {'data/README.md', 'data/.gitkeep'}))


# Base Cassini (#349) : jeu sous CC BY-NC-SA 4.0, jamais redistribué par le dépôt (GPL-3.0), ni entier, ni en
# extrait, ni en fixture. Trois signaux indépendants : le nom, la taille, l'en-tête.
CASSINI_TAILLE = 25_497_478  # octets du fichier publié (doi:10.34847/nkl.e0556oog)
CASSINI_MAX_TABLEUR = 5_000_000  # aucun tableur légitime de cette taille dans le dépôt
CASSINI_TABLEURS = {'.csv', '.tsv', '.ods', '.xlsx', '.xls', '.parquet', '.rdata', '.rds', '.gz', '.zip', '.7z',
                    '.bz2', '.xz'}
CASSINI_COLONNES = {'noacass', 'nom_cassini', 'lien_site_cassini', 'commune_mars_2021', 'nom_an3', 'district_an_3',
                    'departement_an_3', 'position_cassini'}


def cassini_interdit(chemin: str, taille: int = 0, debut: bytes = b'') -> str:
    """Motif du refus si le fichier ressemble au jeu Cassini (nom, taille ou en-tête) ; '' sinon."""
    p = PurePosixPath(chemin)
    nom, suffixe = p.name.lower(), p.suffix.lower()
    if 'lieux_cassini' in nom or ('cassini' in nom and suffixe in CASSINI_TABLEURS):
        return 'nom de fichier du jeu Cassini'
    if taille == CASSINI_TAILLE or (suffixe in CASSINI_TABLEURS and taille > CASSINI_MAX_TABLEUR):
        return 'taille du jeu Cassini ou tableur volumineux'
    premiere = debut.split(b'\n', 1)[0].decode('utf-8-sig', errors='replace').lower()
    champs = {c.strip().strip('"\'') for c in premiere.replace(';', ',').replace('\t', ',').split(',')}
    if len(champs & CASSINI_COLONNES) >= 3:
        return 'en-tête du jeu Cassini'
    return ''


def _apercu(racine: str, chemin: str) -> tuple[int, bytes]:
    complet = os.path.join(racine, chemin)
    try:
        with open(complet, 'rb') as fh:
            debut = fh.read(8192)
        return os.path.getsize(complet), debut
    except OSError:  # fichier suivi mais absent de l'arbre de travail : seul le nom est contrôlé
        return 0, b''


def main() -> int:
    # Depuis la racine du dépôt, quel que soit le dossier d'appel (make, uv --directory mcp) : chemins complets.
    racine = subprocess.check_output(['git', 'rev-parse', '--show-toplevel']).decode().strip()
    chemins = subprocess.check_output(['git', '-C', racine, 'ls-files', '-z']).decode().split('\0')
    refuses = [p for p in chemins if p and interdit(p)]
    refuses += [f'{p} ({motif})' for p in chemins if p and (motif := cassini_interdit(p, *_apercu(racine, p)))]
    if refuses:
        print('Fichiers privés interdits dans la distribution :', *refuses, sep='\n', file=sys.stderr)
        return 1
    print('Distribution : aucun fichier privé suivi par Git.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
