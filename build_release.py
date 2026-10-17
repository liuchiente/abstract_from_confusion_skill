#!/usr/bin/env python3
"""Create the versioned install archive, manifest, and SHA-256 checksums."""

from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
# Name the archive and its top-level folder from VERSION, not from the directory
# this happens to sit in: a 9.1 release built in a v0.8.6 folder shipped as
# v0.8.6.zip, which is the one thing a release filename must never get wrong.
PACKAGE = f'afc-card-experiment-v{VERSION}'
ARCHIVE = ROOT.parent / (PACKAGE + '.zip')
# openspec/ holds change proposals for developing this package. Users get the
# package, not its development workflow.
EXCLUDED_PARTS = {'.git', '.pytest_cache', '__pycache__', 'work', 'experiments',
                  'openspec'}
EXCLUDED_NAMES = {'.DS_Store'}


def package_files():
    return sorted(
        path for path in ROOT.rglob('*')
        if path.is_file()
        and not any(part in EXCLUDED_PARTS for part in path.relative_to(ROOT).parts)
        and path.name not in EXCLUDED_NAMES
        and path.suffix != '.pyc'
    )


def main():
    manifest = ROOT / 'MANIFEST.txt'
    checksums = ROOT / 'CHECKSUMS.txt'
    payload = [p for p in package_files() if p not in {manifest, checksums}]
    manifest.write_text(
        '# Payload files in this AFC release; MANIFEST.txt and CHECKSUMS.txt are release metadata.\n'
        + ''.join(p.relative_to(ROOT).as_posix() + '\n' for p in payload),
        encoding='utf-8',
    )
    checksum_files = [p for p in package_files() if p != checksums]
    checksums.write_text(
        ''.join(f'{sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT).as_posix()}\n'
                for p in checksum_files),
        encoding='utf-8',
    )
    with ZipFile(ARCHIVE, 'w', compression=ZIP_DEFLATED) as archive:
        for path in package_files():
            archive.write(path, (PACKAGE + '/' + path.relative_to(ROOT).as_posix()))
    print(f'created {ARCHIVE} ({ARCHIVE.stat().st_size} bytes), '
          f'{len(payload)} payload files, top-level folder {PACKAGE}/')


if __name__ == '__main__':
    main()
