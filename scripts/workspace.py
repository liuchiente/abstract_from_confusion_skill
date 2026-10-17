#!/usr/bin/env python3
"""Manage a workspace catalog and route operations to one or more AFC KBs."""
from pathlib import Path
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.knowledge_store import atomic_json, init_store, load_json

RUNTIME = Path(__file__).resolve().parents[1]
PROJECT = Path(os.environ.get('AFC_PROJECT_ROOT') or Path.cwd()).expanduser().resolve()
CATALOG_FORMAT = 'afc-workspace-catalog'
CATALOG_VERSION = 1


def catalog_path(value=None):
    path = Path(value).expanduser() if value else PROJECT / 'afc-workspace.json'
    return path.resolve() if path.is_absolute() else (PROJECT / path).resolve()


def load_catalog(path, create=False):
    path = Path(path)
    if not path.exists():
        if not create:
            raise FileNotFoundError(f'workspace catalog not found: {path}; run workspace.py init first')
        return {'format': CATALOG_FORMAT, 'version': CATALOG_VERSION, 'knowledge_bases': []}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('format') != CATALOG_FORMAT or data.get('version') != CATALOG_VERSION:
        raise ValueError(f'unsupported workspace catalog format/version: {path}')
    if not isinstance(data.get('knowledge_bases'), list):
        raise ValueError('catalog knowledge_bases must be a list')
    return data


def save_catalog(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.afc-catalog-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def resolve_path(value, catalog):
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (Path(catalog).parent / path).resolve()


def store_path(path, catalog):
    path = Path(path).expanduser().resolve()
    try:
        return path.relative_to(Path(catalog).parent.resolve()).as_posix()
    except ValueError:
        return str(path)


def find_kb(data, kb_id):
    matches = [row for row in data['knowledge_bases'] if row.get('kb_id') == kb_id]
    if not matches:
        raise KeyError(f'KB ID is not registered: {kb_id}')
    if len(matches) > 1:
        raise ValueError(f'duplicate KB ID in catalog: {kb_id}')
    return matches[0]


def kb_root(row, catalog):
    return resolve_path(row['kb_root'], catalog)


def register(path, kb_id, name, root, scope_policy, sources):
    if not re.fullmatch(r'[a-z][a-z0-9._-]{0,63}', kb_id):
        raise ValueError('KB ID must start with a lowercase letter and contain only lowercase letters, digits, dot, underscore, or hyphen (max 64 characters)')
    data = load_catalog(path, create=True)
    root = Path(root).expanduser().resolve()
    manifest = load_json(root / 'manifest.json', {}) or {}
    if manifest.get('kb_id') != kb_id:
        raise ValueError(f'KB root identity mismatch: expected {kb_id!r}, found {manifest.get("kb_id")!r}')
    if scope_policy not in {'product', 'not-applicable'}:
        raise ValueError('scope policy must be product or not-applicable')
    if manifest.get('scope_policy') not in (None, scope_policy):
        raise ValueError(f'KB manifest scope policy is {manifest.get("scope_policy")!r}, not {scope_policy!r}')
    if manifest.get('scope_policy') is None:
        manifest['scope_policy'] = scope_policy
        atomic_json(root / 'manifest.json', manifest)
    resolved_sources = []
    for raw in sources:
        source = resolve_path(raw, path)
        if not source.exists():
            raise FileNotFoundError(f'source root does not exist: {source}')
        saved = store_path(source, path)
        if saved not in resolved_sources:
            resolved_sources.append(saved)
    existing = next((row for row in data['knowledge_bases'] if row.get('kb_id') == kb_id), None)
    if existing:
        old_root = kb_root(existing, path)
        if old_root != root:
            raise ValueError(f'{kb_id} is already registered at {old_root}; remove it before changing KB root')
        existing.update({'name': name or existing.get('name') or kb_id, 'scope_policy': scope_policy})
        existing['source_roots'] = list(dict.fromkeys([*existing.get('source_roots', []), *resolved_sources]))
    else:
        data['knowledge_bases'].append({
            'kb_id': kb_id, 'name': name or manifest.get('name') or kb_id,
            'kb_root': store_path(root, path), 'scope_policy': scope_policy,
            'source_roots': resolved_sources,
        })
    data['knowledge_bases'].sort(key=lambda row: row['kb_id'].casefold())
    save_catalog(path, data)
    return find_kb(data, kb_id)


def run_script(script, args, env=None):
    command = [sys.executable, str(RUNTIME / 'scripts' / script), *map(str, args)]
    subprocess.run(command, check=True, cwd=str(RUNTIME), env={**os.environ, **(env or {})})


def cmd_init(args):
    path = catalog_path(args.catalog)
    if path.exists() and not args.force:
        raise FileExistsError(f'catalog already exists: {path}; use --force only when it is empty or backed up')
    if path.exists() and args.force:
        existing = load_catalog(path)
        if existing.get('knowledge_bases'):
            raise ValueError('--force is only allowed for an empty workspace catalog')
    save_catalog(path, {'format': CATALOG_FORMAT, 'version': CATALOG_VERSION, 'knowledge_bases': []})
    print(json.dumps({'status': 'initialized', 'catalog': str(path)}, ensure_ascii=False, indent=2))


def cmd_init_kb(args):
    path = catalog_path(args.catalog)
    root = resolve_path(args.kb_root, path)
    init_store(root, args.kb_id, args.name, scope_policy=args.scope_policy)
    row = register(path, args.kb_id, args.name, root, args.scope_policy, args.source)
    print(json.dumps({'status': 'initialized', 'catalog': str(path), 'knowledge_base': row}, ensure_ascii=False, indent=2))


def cmd_register(args):
    path = catalog_path(args.catalog)
    root = resolve_path(args.kb_root, path)
    row = register(path, args.kb_id, args.name, root, args.scope_policy, args.source)
    print(json.dumps({'status': 'registered', 'catalog': str(path), 'knowledge_base': row}, ensure_ascii=False, indent=2))


def cmd_list(args):
    path = catalog_path(args.catalog)
    data = load_catalog(path, create=True)
    result = []
    for row in data['knowledge_bases']:
        root = kb_root(row, path)
        manifest = load_json(root / 'manifest.json', {}) or {}
        current = load_json(root / 'CURRENT.json', {}) or {}
        result.append({**row, 'kb_root': str(root), 'current_release': current.get('release_id'),
                       'kb_status': 'initialized' if manifest.get('kb_id') == row.get('kb_id') else 'missing-or-mismatched'})
    print(json.dumps({'catalog': str(path), 'knowledge_bases': result}, ensure_ascii=False, indent=2))


def cmd_add_source(args):
    path = catalog_path(args.catalog)
    data = load_catalog(path)
    row = find_kb(data, args.kb_id)
    for raw in args.source:
        source = resolve_path(raw, path)
        if not source.exists():
            raise FileNotFoundError(f'source root does not exist: {source}')
        saved = store_path(source, path)
        if saved not in row['source_roots']:
            row['source_roots'].append(saved)
    save_catalog(path, data)
    print(json.dumps({'status': 'sources-updated', 'kb_id': args.kb_id, 'source_roots': row['source_roots']}, ensure_ascii=False, indent=2))


def cmd_remove_source(args):
    path = catalog_path(args.catalog)
    data = load_catalog(path)
    row = find_kb(data, args.kb_id)
    target = resolve_path(args.source, path)
    before = list(row.get('source_roots', []))
    row['source_roots'] = [item for item in before if resolve_path(item, path) != target]
    if row['source_roots'] == before:
        raise KeyError(f'source root is not registered for {args.kb_id}: {target}')
    save_catalog(path, data)
    print(json.dumps({'status': 'source-removed', 'kb_id': args.kb_id,
                      'source_roots': row['source_roots']}, ensure_ascii=False, indent=2))


def cmd_inventory(args):
    path = catalog_path(args.catalog)
    data = load_catalog(path)
    row = find_kb(data, args.kb_id)
    registered = [resolve_path(item, path) for item in row.get('source_roots', [])]
    selected = [resolve_path(item, path) for item in args.source] if args.source else registered
    if not selected:
        raise ValueError(f'no source roots registered for {args.kb_id}; add one with workspace.py add-source')
    for selected_root in selected:
        if not any(selected_root == root or root in selected_root.parents for root in registered):
            raise ValueError(f'selected source is outside registered roots for {args.kb_id}: {selected_root}')
    if args.complete_boundary and set(selected) != set(registered):
        raise ValueError('--complete-boundary requires selecting every registered source root')
    cmd = ['--kb-root', str(kb_root(row, path)), '--behavior', args.behavior,
           '--scope-policy', row['scope_policy']]
    for item in registered:
        cmd += ['--registered-source-root', str(item)]
    for item in selected:
        cmd += ['--source', str(item)]
    for flag, values in (
        ('--business-context', args.business_context), ('--target-scope', args.target_scope),
        ('--exclude-scope', args.exclude_scope), ('--override-excluded-scope', args.override_excluded_scope),
    ):
        for value in values:
            cmd += [flag, value]
    for flag, value in (('--context-map', args.context_map), ('--run-id', args.run_id)):
        if value:
            cmd += [flag, str(resolve_path(value, path)) if flag == '--context-map' else value]
    if args.complete_boundary:
        cmd.append('--complete-boundary')
    if args.rescan_unchanged:
        cmd.append('--rescan-unchanged')
    run_script('knowledge_base.py', ['inventory', *cmd])


def cmd_query(args):
    path = catalog_path(args.catalog)
    data = load_catalog(path)
    for kb_id in args.kb_id:
        row = find_kb(data, kb_id)
        print(f'=== KB {kb_id} — {row.get("name", kb_id)} ===')
        run_script('knowledge_base.py', ['query', '--kb-root', str(kb_root(row, path)), '--query', args.query])


def cmd_export(args):
    path = catalog_path(args.catalog)
    data = load_catalog(path)
    row = find_kb(data, args.kb_id)
    cmd = ['export', '--kb-root', str(kb_root(row, path)), '--output', str(resolve_path(args.output, path))]
    if args.include_runs:
        cmd.append('--include-runs')
    if args.include_indexes:
        cmd.append('--include-indexes')
    run_script('knowledge_pack.py', cmd)


def build_parser():
    ap = argparse.ArgumentParser(description='Register AFC Knowledge Bases and route source/query operations by KB ID.')
    ap.add_argument('--catalog', help='Workspace catalog JSON; default: <project>/afc-workspace.json')
    sub = ap.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init', help='create an empty workspace catalog')
    init.add_argument('--force', action='store_true'); init.set_defaults(func=cmd_init)
    init_kb = sub.add_parser('init-kb', help='initialize a KB and register it in the workspace')
    init_kb.add_argument('--kb-id', required=True); init_kb.add_argument('--name')
    init_kb.add_argument('--kb-root', required=True); init_kb.add_argument('--scope-policy', choices=['product','not-applicable'], required=True)
    init_kb.add_argument('--source', action='append', default=[]); init_kb.set_defaults(func=cmd_init_kb)
    reg = sub.add_parser('register', help='register an existing initialized KB')
    reg.add_argument('--kb-id', required=True); reg.add_argument('--name'); reg.add_argument('--kb-root', required=True)
    reg.add_argument('--scope-policy', choices=['product','not-applicable'], required=True)
    reg.add_argument('--source', action='append', default=[]); reg.set_defaults(func=cmd_register)
    add = sub.add_parser('add-source', help='add source roots to a KB')
    add.add_argument('--kb-id', required=True); add.add_argument('--source', action='append', required=True); add.set_defaults(func=cmd_add_source)
    remove = sub.add_parser('remove-source', help='remove a source root from a KB catalog entry')
    remove.add_argument('--kb-id', required=True); remove.add_argument('--source', required=True); remove.set_defaults(func=cmd_remove_source)
    listing = sub.add_parser('list', help='show registered KB IDs and their current releases')
    listing.set_defaults(func=cmd_list)
    inv = sub.add_parser('inventory', help='inventory registered source roots for one KB ID')
    inv.add_argument('--kb-id', required=True); inv.add_argument('--behavior', required=True)
    inv.add_argument('--source', action='append', default=[]); inv.add_argument('--business-context', action='append', default=[])
    inv.add_argument('--target-scope', action='append', default=[]); inv.add_argument('--exclude-scope', action='append', default=[])
    inv.add_argument('--override-excluded-scope', action='append', default=[]); inv.add_argument('--context-map')
    inv.add_argument('--run-id'); inv.add_argument('--complete-boundary', action='store_true')
    inv.add_argument('--rescan-unchanged', action='store_true'); inv.set_defaults(func=cmd_inventory)
    query = sub.add_parser('query', help='query one or more explicitly selected KB IDs')
    query.add_argument('--kb-id', action='append', required=True); query.add_argument('--query', required=True); query.set_defaults(func=cmd_query)
    exp = sub.add_parser('export', help='export a portable pack for one KB ID')
    exp.add_argument('--kb-id', required=True); exp.add_argument('--output', required=True)
    exp.add_argument('--include-runs', action='store_true'); exp.add_argument('--include-indexes', action='store_true'); exp.set_defaults(func=cmd_export)
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    try:
        args.func(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f'workspace: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
