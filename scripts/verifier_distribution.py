"""Refuse les fichiers privés suivis par Git, même ajoutés avec git add -f."""

import subprocess
import sys
from pathlib import PurePosixPath


def interdit(chemin: str) -> bool:
    p = PurePosixPath(chemin)
    if chemin == '.env.example':
        return False
    if p.suffix.lower() == '.ged':
        return not (p.parent == PurePosixPath('mcp/tests/fixtures'))
    return (p.name == '.env' or p.name.startswith('.env.')
            or p.suffix.lower() in {'.token', '.key', '.pem', '.p12', '.pfx', '.sqlite', '.db',
                                    '.sql', '.jsonl', '.gramps', '.gpkg'}
            or '.sqlite-' in p.name
            or any(part in {'.propositions', 'medias', 'exports', 'rapports', 'cache-images'} for part in p.parts)
            or p.parts[0] in {'personnes', 'familles', 'patronymes', 'photographies', 'documents', 'notes'}
            or (p.parts[0] == 'data' and chemin not in {'data/README.md', 'data/.gitkeep'}))


def main() -> int:
    chemins = subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')
    refuses = [p for p in chemins if p and interdit(p)]
    if refuses:
        print('Fichiers privés interdits dans la distribution :', *refuses, sep='\n', file=sys.stderr)
        return 1
    print('Distribution : aucun fichier privé suivi par Git.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
