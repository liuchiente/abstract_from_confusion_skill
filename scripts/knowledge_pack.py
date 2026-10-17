#!/usr/bin/env python3
"""Export and import validated, portable AFC Knowledge Base snapshots."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import shutil
import tempfile
import sys
from datetime import datetime, timezone
from zipfile import ZIP_DEFLATED, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.knowledge_store import current_release, load_json, verify_release
from afc_card_runtime.config import load_settings

PACK_FORMAT = 'afc-knowledge-pack'
PACK_VERSION = '1.0'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def export_pack(root, destination, include_runs=False, include_indexes=False):
    root = Path(root).expanduser().resolve()
    release = current_release(root)
    verify_release(release)
    included = []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.name == 'pack-manifest.json':
            continue
        rel = path.relative_to(root)
        parts = set(rel.parts)
        if 'runs' in parts and not include_runs:
            continue
        if 'indexes' in parts and not include_indexes:
            continue
        if any(part in {'.git', '__pycache__', '.pytest_cache'} for part in rel.parts):
            continue
        if rel.parts[0] == 'config' and rel.as_posix() not in {
            'config/business-contexts.yaml', 'config/query-terms.yaml', 'config/box-taxonomy.yaml'
        }:
            continue
        # A pack must never sweep unrelated files from a user-managed KB root.
        if rel.parts[0] not in {'manifest.json', 'CURRENT.json', 'identity', 'releases', 'history', 'runs', 'indexes', 'config'}:
            continue
        included.append(path)
    # Query behavior depends on these maps. Carry configured copies so the
    # recipient can rebuild the index and classify questions consistently.
    settings = load_settings()
    packaged_config = []
    included_names = {path.relative_to(root).as_posix() for path in included}
    for key, target_name in (
        ('business_context_map', 'business-contexts.yaml'),
        ('query_terms', 'query-terms.yaml'),
        ('box_taxonomy', 'box-taxonomy.yaml'),
    ):
        local_config = root / 'config' / target_name
        configured = local_config if local_config.is_file() else settings.resolve(key)
        if configured and configured.is_file() and target_name not in included_names:
            packaged_config.append((configured, f'config/{target_name}'))
    manifest = {
        'format': PACK_FORMAT,
        'format_version': PACK_VERSION,
        'kb_id': (load_json(root / 'manifest.json', {}) or {}).get('kb_id'),
        'current_release': release.name,
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'canonical_release_sha256': (load_json(release / 'release-manifest.json', {}) or {}).get('dataset_sha256'),
        'includes_runs': bool(include_runs),
        'includes_indexes': bool(include_indexes),
        'files': {**{p.relative_to(root).as_posix(): sha256(p) for p in included},
                  **{name: sha256(path) for path, name in packaged_config}},
    }
    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for path in included:
            archive.write(path, path.relative_to(root).as_posix())
        for path, name in packaged_config:
            archive.write(path, name)
        archive.writestr('pack-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


def import_pack(archive_path, destination):
    archive_path = Path(archive_path).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError('destination must be missing or empty: ' + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.afc-kb-import-', dir=str(destination.parent)) as temporary:
        stage = Path(temporary) / 'kb'
        stage.mkdir()
        with ZipFile(archive_path) as archive:
            names = archive.namelist()
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or not path.parts:
                    raise ValueError('unsafe path in knowledge pack: ' + name)
            if 'pack-manifest.json' not in names:
                raise ValueError('knowledge pack has no pack-manifest.json')
            manifest = json.loads(archive.read('pack-manifest.json').decode('utf-8'))
            if manifest.get('format') != PACK_FORMAT or manifest.get('format_version') != PACK_VERSION:
                raise ValueError('unsupported knowledge pack format/version')
            expected_files = manifest.get('files')
            if not isinstance(expected_files, dict):
                raise ValueError('knowledge pack file hashes are missing')
            for name, expected in expected_files.items():
                if name not in names:
                    raise ValueError('knowledge pack file is missing: ' + name)
                target = stage.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
                if sha256(target) != expected:
                    raise ValueError('knowledge pack checksum mismatch: ' + name)
        current = load_json(stage / 'CURRENT.json', {}) or {}
        release_id = current.get('release_id')
        if release_id != manifest.get('current_release'):
            raise ValueError('pack current-release pointer does not match its manifest')
        verify_release(stage / 'releases' / release_id)
        if destination.exists():
            destination.rmdir()
        shutil.move(str(stage), str(destination))
    return {'status': 'imported', 'kb_root': str(destination), 'current_release': release_id,
            'kb_id': manifest.get('kb_id')}


def main():
    ap = argparse.ArgumentParser(description='Export/import validated AFC Knowledge Base snapshots.')
    sub = ap.add_subparsers(dest='command', required=True)
    exp = sub.add_parser('export', help='write a portable snapshot of accepted releases')
    exp.add_argument('--kb-root', required=True)
    exp.add_argument('--output', required=True)
    exp.add_argument('--include-runs', action='store_true', help='include working runs and proposals')
    exp.add_argument('--include-indexes', action='store_true', help='include disposable query indexes')
    imp = sub.add_parser('import', help='validate and install a snapshot into a new local directory')
    imp.add_argument('--archive', required=True)
    imp.add_argument('--kb-root', required=True)
    args = ap.parse_args()
    if args.command == 'export':
        result = export_pack(args.kb_root, args.output, args.include_runs, args.include_indexes)
        print(json.dumps({'status': 'exported', 'output': str(Path(args.output).resolve()),
                          'current_release': result['current_release'],
                          'file_count': len(result['files'])}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(import_pack(args.archive, args.kb_root), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
