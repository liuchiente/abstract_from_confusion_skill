#!/usr/bin/env python3
"""Initialize, inventory, review, publish and query a persistent AFC KB."""

from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import IGNORED_SOURCE_FILES, read_jsonl
from afc_card_runtime.config import package_version
from afc_card_runtime.config import load_settings
from afc_card_runtime.knowledge_store import (
    DATASETS, accept_run, append_decisions, atomic_json, atomic_jsonl,
    current_release, empty_release_datasets, entity_map, init_store,
    load_json, make_scope_attributions, next_release_id, publish_pointer,
    normalize_migrated_null_fields,
    reconstruct_v05_id_registry, validate_registry_against_release,
    release_hashes, sha256_file, stage_proposals, utc_now, validate_release,
    verify_release,
)
from afc_card_runtime.scope import (
    load_business_context_map, resolve_business_context_map,
    resolve_membership_scopes, source_memberships,
)


DATASET_ALIASES = {
    'cards': ('knowledge_card_master.jsonl', 'step-card-4-master.jsonl', 'step-card-1-cards.jsonl'),
    'evidence': ('knowledge_evidence.jsonl', 'step-card-4-evidence.jsonl', 'step-card-1-evidence.jsonl'),
    'links': ('knowledge_links.jsonl', 'step-card-2-links.jsonl'),
    'boxes': ('knowledge_boxes.jsonl', 'step-card-3-boxes.jsonl'),
    'memberships': ('knowledge_box_memberships.jsonl', 'step-card-3-box-memberships.jsonl'),
    'box_links': ('knowledge_box_links.jsonl', 'step-card-3-box-links.jsonl'),
    'contexts': ('knowledge_contexts.jsonl', 'step-card-0-contexts.jsonl'),
    'coverage': ('source_unit_coverage.jsonl', 'step-card-1-coverage.jsonl'),
    'domains': ('knowledge_domains.jsonl', 'semantic-domains.jsonl'),
}

IGNORED_DIRS = {'.git', '.codex', '.agents', '.afc-card-experiment', 'afc-card-experiment-v0.6.0', 'afc-card-experiment-v0.7.0', 'afc-card-experiment-v0.8.0', 'afc-card-experiment-v0.8.1', 'afc-card-experiment-v0.8.2', 'afc-card-experiment-v0.8.3', 'afc-card-experiment-v0.8.4', 'afc-knowledge-base', 'node_modules', 'vendor', 'build', 'dist', 'target', '.gradle', '.idea', '.dart_tool', '.next', 'coverage'}
# The inventory and the parsers must agree on what is not source material.
IGNORED_FILES = set(IGNORED_SOURCE_FILES)


def run_id_now():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def inventory_files(roots, recursive=True, exclude_roots=None):
    found = {}
    excluded = [Path(x).resolve() for x in (exclude_roots or [])]
    for root in roots:
        p = Path(root).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError('source path does not exist: ' + str(p))
        if p.is_file():
            if any(p == excluded_root or excluded_root in p.parents for excluded_root in excluded):
                continue
            found.setdefault(p, set()).add(p.parent)
            continue
        for directory, dirnames, filenames in os.walk(p, topdown=True, followlinks=False):
            current = Path(directory)
            rel_dir = current.relative_to(p)
            if any(part in IGNORED_DIRS or part.startswith('.') for part in rel_dir.parts):
                dirnames[:] = []
                continue
            if not recursive:
                dirnames[:] = []
            else:
                dirnames[:] = [name for name in dirnames
                               if name not in IGNORED_DIRS and not name.startswith('.')]
            for filename in filenames:
                item = current / filename
                if item.name in IGNORED_FILES or item.name.startswith('~$') or item.name.startswith('.'):
                    continue
                resolved_item = item.resolve()
                if any(resolved_item == excluded_root or excluded_root in resolved_item.parents for excluded_root in excluded):
                    continue
                found.setdefault(resolved_item, set()).add(p)
    return found


def membership_id(root, relative_path):
    import hashlib
    raw = str(root or '') + '\0' + str(relative_path)
    return 'SRC-' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]


def inventory_command(args):
    settings = load_settings()
    kb_root = Path(args.kb_root).expanduser().resolve()
    release = current_release(kb_root, allow_empty=True)
    base_id = release.name if release else None
    prior_rows = read_jsonl(release / 'source_catalog.jsonl') if release and (release / 'source_catalog.jsonl').exists() else []
    prior = {row.get('Membership ID'): row for row in prior_rows
             if row.get('Membership ID') and row.get('Status') not in {'Removed', 'Removed Candidate'}}

    mapping_path = Path(args.context_map).expanduser().resolve() if args.context_map else settings.resolve('business_context_map')
    if args.business_context and not mapping_path:
        raise ValueError('provide --context-map or configure business_context_map')
    resolution = resolve_business_context_map(mapping_path, args.business_context)
    target_scopes = list(args.target_scope or settings.get('active_scopes', []) or [])
    mapped_scopes = resolution['scopes']
    global_excluded = list(settings.get('excluded_scopes', []) or []) + list(args.exclude_scope or [])
    override_scopes = list(args.override_excluded_scope or [])
    roots = [Path(value).expanduser().resolve() for value in args.source]
    registered_roots = [Path(value).expanduser().resolve()
                        for value in getattr(args, 'registered_source_root', [])]
    registered_roots.extend(Path(row['Source Root']).resolve() for row in prior_rows
                            if row.get('Source Root') and row.get('Status') not in {'Removed', 'Removed Candidate'})
    registered_roots = list(dict.fromkeys(registered_roots))
    files = inventory_files(roots, recursive=not args.no_recursive, exclude_roots=[kb_root])
    run_id = args.run_id or run_id_now()
    run_dir = kb_root / 'runs' / run_id
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError('run directory already contains data: ' + str(run_dir))
    candidate_dir = run_dir / 'candidate'
    candidate_dir.mkdir(parents=True, exist_ok=True)

    current_memberships = set()
    inventory = []
    catalog = []
    eligible_paths = set()
    selected_roots = {str(root if root.is_dir() else root.parent) for root in roots}
    scope_policy = getattr(args, 'scope_policy', (load_json(kb_root / 'manifest.json', {}) or {}).get('scope_policy', 'product'))
    for file_path, matched_roots in sorted(files.items(), key=lambda pair: str(pair[0]).casefold()):
        file_hash = sha256_file(file_path)
        stat = file_path.stat()
        stable_roots = {str(root) for root in registered_roots
                        if file_path == root or root in file_path.parents}
        membership_roots = stable_roots or {str(root) for root in matched_roots}
        memberships = source_memberships(file_path, sorted(membership_roots))
        for membership in memberships:
            root = membership.get('root')
            metadata = membership['scope_metadata']
            if scope_policy == 'not-applicable':
                decision = {
                    'target_scopes': [], 'allowed_scopes': [],
                    'excluded_scopes': list(dict.fromkeys([*global_excluded, *metadata.get('excluded_scopes', [])])),
                    'blocked_scopes': [], 'override_scopes': [],
                    'target_basis': 'Knowledge Base policy: product Scope not applicable',
                    'status': 'scope-neutral',
                }
            else:
                decision = resolve_membership_scopes(
                    metadata, requested_scopes=target_scopes, mapped_scopes=mapped_scopes,
                    global_excluded=global_excluded, override_exclusions=override_scopes,
                )
            mid = membership_id(root, membership['relative_path'])
            current_memberships.add(mid)
            old = prior.get(mid)
            metadata_hash = metadata.get('sha256')
            boundary_status = decision['status']
            if old is None:
                source_status = 'added'
            elif old.get('content_sha256') != file_hash:
                source_status = 'modified'
            elif old.get('scope_metadata_sha256') != metadata_hash:
                source_status = 'modified'
            elif (old.get('target_scopes') != decision['target_scopes']
                  or old.get('allowed_scopes') != decision['allowed_scopes']
                  or old.get('boundary_status') != boundary_status):
                source_status = 'modified'
            else:
                source_status = 'unchanged'
            row = {
                'Membership ID': mid, 'Source Path': str(file_path),
                'Source Root': root, 'Relative Path': membership['relative_path'],
                'content_sha256': file_hash, 'size_bytes': stat.st_size,
                'modified_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                'scope_metadata_path': metadata.get('path'),
                'scope_metadata_sha256': metadata_hash,
                'default_scopes': metadata.get('default_scopes', []),
                'directory_excluded_scopes': metadata.get('excluded_scopes', []),
                'requested_business_contexts': args.business_context,
                'resolved_business_contexts': resolution['contexts'],
                'target_scopes': decision['target_scopes'],
                'allowed_scopes': decision['allowed_scopes'],
                'blocked_scopes': decision['blocked_scopes'],
                'override_scopes': decision['override_scopes'],
                'boundary_status': boundary_status,
                'source_status': source_status,
            }
            inventory.append(row)
            if boundary_status in {'eligible', 'partially-excluded', 'scope-neutral'}:
                if source_status != 'unchanged' or args.rescan_unchanged:
                    eligible_paths.add(str(file_path))
                if source_status == 'unchanged' and old:
                    catalog.append(old)
                else:
                    catalog_row = dict(row)
                    catalog_row.pop('source_status', None)
                    catalog_row['Status'] = 'Active'
                    catalog_row['last_seen_run'] = run_id
                    catalog.append(catalog_row)
            else:
                catalog_row = dict(row)
                catalog_row.pop('source_status', None)
                catalog_row['Status'] = 'Excluded' if boundary_status == 'excluded' else 'Needs Scope'
                catalog_row['last_seen_run'] = run_id
                catalog.append(catalog_row)
    for mid, old in sorted(prior.items()):
        if mid in current_memberships:
            continue
        if args.complete_boundary and old.get('Source Root') in selected_roots:
            inventory.append({**old, 'source_status': 'removed', 'boundary_status': 'not-present-in-complete-inventory'})
            catalog.append({**old, 'Status': 'Removed Candidate', 'last_seen_run': run_id})
        else:
            inventory.append({**old, 'source_status': 'unscanned', 'boundary_status': 'outside-this-run'})
            catalog.append(old)

    run_manifest = {
        'run_id': run_id, 'kb_id': (load_json(kb_root / 'manifest.json', {}) or {}).get('kb_id'),
        'base_release_id': base_id, 'operation': 'full-refresh' if args.complete_boundary else 'incremental',
        'status': 'inventory_complete', 'requested_behavior': args.behavior,
        'business_contexts': args.business_context, 'resolved_business_contexts': resolution['contexts'],
        'scope_policy': scope_policy,
        'target_scopes': target_scopes or mapped_scopes,
        'source_roots': [str(root) for root in roots],
        'context_map_path': str(mapping_path) if mapping_path else None,
        'context_map_sha256': sha256_file(mapping_path) if mapping_path and Path(mapping_path).is_file() else None,
        'scope_overrides': override_scopes, 'complete_boundary': bool(args.complete_boundary),
        'rescan_unchanged': bool(args.rescan_unchanged),
        'started_at': utc_now(),
    }
    atomic_json(run_dir / 'run-manifest.json', run_manifest)
    atomic_jsonl(run_dir / 'source-inventory.jsonl', inventory)
    atomic_json(candidate_dir / 'eligible-source-paths.json', {'paths': sorted(eligible_paths)})
    atomic_jsonl(candidate_dir / 'source_catalog.jsonl', catalog)
    summary = {
        'run_id': run_id, 'run_dir': str(run_dir), 'base_release_id': base_id,
        'files_discovered': len(files), 'membership_rows': len(inventory),
        'eligible_source_files': len(eligible_paths),
        'unchanged_source_files_skipped': sum(1 for row in inventory if row.get('source_status') == 'unchanged') if not args.rescan_unchanged else 0,
        'added': sum(1 for row in inventory if row.get('source_status') == 'added'),
        'modified': sum(1 for row in inventory if row.get('source_status') == 'modified'),
        'unchanged': sum(1 for row in inventory if row.get('source_status') == 'unchanged'),
        'removed': sum(1 for row in inventory if row.get('source_status') == 'removed'),
        'unscanned': sum(1 for row in inventory if row.get('source_status') == 'unscanned'),
        'scope_blocked': sum(1 for row in inventory if row.get('boundary_status') == 'excluded'),
        'scope_unresolved': sum(1 for row in inventory if row.get('boundary_status') == 'needs-scope'),
        'scope_not_applicable': sum(1 for row in inventory if row.get('boundary_status') == 'scope-neutral'),
    }
    atomic_json(run_dir / 'inventory-report.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def init_command(args):
    root = init_store(args.kb_root, args.kb_id, args.name)
    print(json.dumps({'status': 'initialized', 'kb_root': str(root), 'kb_id': args.kb_id}, ensure_ascii=False))


def migrate_v05_command(args):
    if not args.accept_baseline:
        raise ValueError('v0.5 import requires --accept-baseline after reviewing the source output and identity baseline')
    root = Path(args.kb_root).expanduser().resolve()
    if not (root / 'manifest.json').exists():
        init_store(root, args.kb_id, args.name)
    if current_release(root, allow_empty=True):
        raise ValueError('v0.5 import only initializes an empty Knowledge Base')
    source_root = Path(args.v05_root).expanduser().resolve()
    filenames = {
        'cards': 'knowledge_card_master.jsonl', 'evidence': 'knowledge_evidence.jsonl',
        'links': 'knowledge_links.jsonl', 'boxes': 'knowledge_boxes.jsonl',
        'memberships': 'knowledge_box_memberships.jsonl', 'box_links': 'knowledge_box_links.jsonl',
        'contexts': 'knowledge_contexts.jsonl', 'coverage': 'source_unit_coverage.jsonl',
    }
    registry_source = source_root / 'work' / 'id-registry.jsonl'
    run_id = args.run_id or ('migrate-v05-' + run_id_now())
    release_id = next_release_id(root)
    release_dir = root / 'releases' / release_id
    release_dir.mkdir(parents=True, exist_ok=False)
    empty_release_datasets(release_dir)
    for dataset, filename in filenames.items():
        src = source_root / 'output' / filename
        if src.exists():
            atomic_jsonl(release_dir / DATASETS[dataset][0], read_jsonl(src))
    migration_normalization = normalize_migrated_null_fields(release_dir)
    cards = read_jsonl(release_dir / DATASETS['cards'][0])
    atomic_jsonl(release_dir / DATASETS['scope_attributions'][0],
                 make_scope_attributions(cards, run_id, accepted_legacy=True))
    atomic_jsonl(release_dir / DATASETS['source_catalog'][0], [])
    validation = validate_release(release_dir)
    if registry_source.exists():
        registry_rows = read_jsonl(registry_source)
        registry_reconstruction = None
    else:
        registry_rows, registry_reconstruction = reconstruct_v05_id_registry(source_root, release_dir, run_id)
    identity_validation = validate_registry_against_release(registry_rows, release_dir)
    atomic_jsonl(root / 'identity' / 'id-registry.jsonl', registry_rows)
    change_source = source_root / 'work' / 'knowledge-change-log.jsonl'
    if change_source.exists():
        atomic_jsonl(root / 'history' / 'knowledge-change-log.jsonl', read_jsonl(change_source))
    manifest = {
        'release_id': release_id, 'kb_id': args.kb_id, 'schema_version': '1.0',
        'runtime_version': package_version(), 'parent_release_id': None, 'run_id': run_id,
        'accepted_at': utc_now(), 'migration_source': 'AFC v0.5.0',
        'accepted_by': args.accepted_by, 'rationale': args.rationale,
        'id_registry_validation': identity_validation,
        'id_registry_reconstruction': registry_reconstruction,
        'migration_normalization': migration_normalization,
        'scope_conflicts_needing_review': sum(1 for row in read_jsonl(release_dir / DATASETS['scope_attributions'][0]) if row['Status'] == 'Needs Review'),
        'source_inventory_note': 'v0.5 output does not contain a complete fingerprinted source catalog; inventory starts with the first v0.6 scan.',
        'validation': validation,
        'dataset_sha256': release_hashes(release_dir),
    }
    atomic_json(release_dir / 'release-manifest.json', manifest)
    publish_pointer(root, release_id)
    print(json.dumps({'status': 'migrated', 'release_id': release_id, 'kb_root': str(root), **manifest}, ensure_ascii=False, indent=2))


def stage_command(args):
    root = Path(args.kb_root).expanduser().resolve()
    run_dir = root / 'runs' / args.run_id
    run_manifest = load_json(run_dir / 'run-manifest.json', None)
    if run_manifest is None:
        raise FileNotFoundError('run was not inventoried: ' + str(run_dir))
    health_path = Path(args.health_report).expanduser().resolve()
    health_report = load_json(health_path, None)
    if not isinstance(health_report, dict) or not health_report.get('overall_status'):
        raise ValueError('a valid Step 1 Card health report is required to stage a pipeline release: ' + str(health_path))
    health_run_id = health_report.get('run_id')
    if health_run_id and str(health_run_id) != str(args.run_id):
        raise ValueError(f'Card health report belongs to run {health_run_id!r}, not staged run {args.run_id!r}')
    health_snapshot = run_dir / 'card-health.json'
    shutil.copy2(str(health_path), str(health_snapshot))
    base = current_release(root, allow_empty=True)
    base_id = base.name if base else None
    if run_manifest.get('base_release_id') != base_id:
        raise ValueError('current release changed since inventory; rerun inventory against the new base')
    source_dir = Path(args.candidate_dir).expanduser().resolve()
    candidate_dir = run_dir / 'candidate'
    candidate_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for dataset, aliases in DATASET_ALIASES.items():
        for filename in aliases:
            source = source_dir / filename
            if source.exists():
                destination = candidate_dir / DATASETS[dataset][0]
                if source.resolve() != destination.resolve():
                    shutil.copy2(str(source), str(destination))
                copied.append(dataset)
                break
    settings = load_settings()
    registry = Path(args.id_registry).expanduser().resolve() if args.id_registry else settings.resolve('artifacts.id_registry')
    if registry and Path(registry).exists():
        shutil.copy2(str(registry), str(candidate_dir / 'id-registry.jsonl'))
    proposals = stage_proposals(base, candidate_dir, run_dir, args.run_id)
    staged_manifest = load_json(run_dir / 'run-manifest.json', {}) or {}
    staged_manifest['card_health'] = {
        'overall_status': str(health_report.get('overall_status') or '').upper(),
        'path': str(health_snapshot),
        'sha256': hashlib.sha256(health_snapshot.read_bytes()).hexdigest(),
    }
    atomic_json(run_dir / 'run-manifest.json', staged_manifest)
    print(json.dumps({'status': 'awaiting_review', 'run_id': args.run_id,
                      'candidate_datasets': sorted(set(copied)), 'proposal_count': len(proposals),
                      'proposals': str(run_dir / 'proposals.jsonl'),
                      'decisions': str(run_dir / 'decisions.jsonl')}, ensure_ascii=False, indent=2))


DECISION_FIELDS = (('proposal_id', 'Proposal ID'), ('decision', 'Decision'),
                   ('reviewer', 'Reviewer'), ('rationale', 'Rationale'))


def read_decision_file(path):
    rows = read_jsonl(path)
    if not rows:
        raise ValueError('no decisions found in ' + str(path))
    entries = []
    for number, row in enumerate(rows, 1):
        entry = {key: row.get(key, row.get(canonical)) for key, canonical in DECISION_FIELDS}
        for key in ('proposal_id', 'decision'):
            if not entry.get(key):
                raise ValueError(f'{path}:{number}: {key} is required')
        if not entry.get('reviewer'):
            raise ValueError(f'{path}:{number}: reviewer is required; a decision without one is '
                             'not an explicit human review')
        entries.append(entry)
    return entries


def decide_command(args):
    root = Path(args.kb_root).expanduser().resolve()
    run_dir = root / 'runs' / args.run_id
    single = [args.proposal_id, args.decision, args.reviewer, args.rationale]
    if args.decisions_file and any(x is not None for x in single):
        raise ValueError('pass --decisions-file or the single-proposal flags, not both')
    if args.decisions_file:
        entries = read_decision_file(args.decisions_file)
    else:
        missing = [flag for flag, value in zip(
            ('--proposal-id', '--decision', '--reviewer', '--rationale'), single) if value is None]
        if missing:
            raise ValueError('missing required argument(s): ' + ', '.join(missing)
                             + ' (or pass --decisions-file)')
        entries = [{'proposal_id': args.proposal_id, 'decision': args.decision,
                    'reviewer': args.reviewer, 'rationale': args.rationale}]
    rows = append_decisions(run_dir, entries)
    if len(rows) == 1:
        print(json.dumps({'status': 'recorded', **rows[0]}, ensure_ascii=False, indent=2))
    else:
        counts = {}
        for row in rows:
            counts[row['Decision']] = counts.get(row['Decision'], 0) + 1
        print(json.dumps({'status': 'recorded', 'decisions': len(rows), 'by_decision': counts,
                          'proposal_ids': [row['Proposal ID'] for row in rows]},
                         ensure_ascii=False, indent=2))


def publish_command(args):
    root = Path(args.kb_root).expanduser().resolve()
    release_id = accept_run(
        root, root / 'runs' / args.run_id, args.run_id,
        quality_override_by=args.accept_quality_risk_by,
        quality_override_rationale=args.quality_risk_rationale,
    )
    print(json.dumps({'status': 'published', 'kb_root': str(root), 'release_id': release_id}, ensure_ascii=False))


def rollback_command(args):
    root = Path(args.kb_root).expanduser().resolve()
    target = root / 'releases' / args.release_id
    if not target.is_dir():
        raise FileNotFoundError('release does not exist: ' + str(target))
    verify_release(target)
    publish_pointer(root, args.release_id)
    from afc_card_runtime.knowledge_store import atomic_jsonl
    events = read_jsonl(root / 'history' / 'release-events.jsonl')
    events.append({'event': 'rollback', 'release_id': args.release_id, 'at': utc_now(), 'reviewer': args.reviewer, 'rationale': args.rationale})
    atomic_jsonl(root / 'history' / 'release-events.jsonl', events)
    print(json.dumps({'status': 'rolled_back', 'current_release': args.release_id}, ensure_ascii=False))


def validate_command(args):
    root = Path(args.kb_root).expanduser().resolve()
    release = current_release(root)
    result = verify_release(release)
    print(json.dumps({'status': 'valid', 'release_id': release.name, **result}, ensure_ascii=False, indent=2))


def index_command(args):
    root = Path(args.kb_root).expanduser().resolve()
    release = current_release(root)
    verify_release(release)
    release_manifest = load_json(release / 'release-manifest.json', {}) or {}
    db = root / 'indexes' / (release.name + '-afc-query.db')
    runtime = Path(__file__).resolve().parents[1]
    settings = load_settings()
    packaged_mapping = root / 'config' / 'business-contexts.yaml'
    mapping = args.context_map or str(packaged_mapping if packaged_mapping.is_file()
                                      else settings.resolve('business_context_map') or '')
    command = [sys.executable, str(runtime / 'scripts' / 'ensure_query_index.py'), '--db', str(db)]
    arg_map = {
        '--cards': 'cards', '--evidence': 'evidence', '--links': 'links',
        '--boxes': 'boxes', '--box-memberships': 'memberships', '--box-links': 'box_links',
        '--scope-attributions': 'scope_attributions', '--domains': 'domains',
    }
    for flag, dataset in arg_map.items():
        candidate = release / DATASETS[dataset][0]
        if candidate.exists():
            command += [flag, str(candidate)]
    if mapping and Path(mapping).exists():
        command += ['--context-map', mapping]
    if args.field_xlsx:
        command += ['--field-xlsx', str(Path(args.field_xlsx).expanduser().resolve())]
    if args.rebuild:
        build = [sys.executable, str(runtime / 'scripts' / 'build_query_index.py'), '-o', str(db)]
        for flag, dataset in arg_map.items():
            candidate = release / DATASETS[dataset][0]
            if candidate.exists():
                build += [flag, str(candidate)]
        if mapping and Path(mapping).exists(): build += ['--context-map', mapping]
        if args.field_xlsx: build += ['--field-xlsx', str(Path(args.field_xlsx).expanduser().resolve())]
        command = build
    subprocess.run(command, check=True, cwd=str(runtime), env={**os.environ, 'AFC_HOME': str(runtime)})
    print(json.dumps({'status': 'indexed', 'release_id': release.name, 'index': str(db)}, ensure_ascii=False))


def query_command(args, unknown):
    root = Path(args.kb_root).expanduser().resolve()
    release = current_release(root)
    db = Path(args.db).expanduser().resolve() if args.db else root / 'indexes' / (release.name + '-afc-query.db')
    if not db.exists():
        raise FileNotFoundError('query index is missing; run `knowledge_base.py index --kb-root ...` first: ' + str(db))
    import sqlite3
    try:
        with sqlite3.connect(str(db)) as con:
            indexed_schema = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        schema_version = json.loads(indexed_schema[0]) if indexed_schema else None
    except (sqlite3.Error, json.JSONDecodeError, TypeError):
        schema_version = None
    if str(schema_version) != '10':
        if args.db:
            raise ValueError('custom query index uses an outdated or invalid schema; rebuild it before querying: ' + str(db))
        print('Query index schema is outdated; rebuilding it from the accepted release.')
        index_command(argparse.Namespace(kb_root=str(root), context_map=None,
                                         field_xlsx=None, rebuild=True))
    runtime = Path(__file__).resolve().parents[1]
    command = [sys.executable, str(runtime / 'scripts' / 'query_fast.py'), '--db', str(db)]
    packaged_terms = root / 'config' / 'query-terms.yaml'
    if packaged_terms.is_file():
        command += ['--query-terms', str(packaged_terms)]
    # --query is declared here so `knowledge_base.py query --help` documents it;
    # it still has to be handed to query_fast.py, which does the retrieval.
    if args.query:
        command += ['--query', args.query]
    elif not any(arg == '--query' or arg.startswith('--query=') for arg in unknown):
        raise ValueError("a question is required, e.g. --query '乘客險什麼時候可加買？'")
    command.extend(unknown)
    subprocess.run(command, check=True, cwd=str(runtime), env={**os.environ, 'AFC_HOME': str(runtime)})


def main():
    ap = argparse.ArgumentParser(
        description=f'Persistent AFC Knowledge Base lifecycle manager (v{package_version()}).')
    sub = ap.add_subparsers(dest='command', required=True)

    init = sub.add_parser('init', help='initialize a portable Knowledge Base directory')
    init.add_argument('--kb-root', required=True); init.add_argument('--kb-id', required=True); init.add_argument('--name')
    init.set_defaults(func=init_command)

    inventory = sub.add_parser('inventory', help='fingerprint sources and apply per-directory Scope boundaries')
    inventory.add_argument('--kb-root', required=True); inventory.add_argument('--source', action='append', required=True)
    inventory.add_argument('--behavior', required=True); inventory.add_argument('--business-context', action='append', default=[])
    inventory.add_argument('--target-scope', action='append', default=[]); inventory.add_argument('--context-map')
    inventory.add_argument('--scope-policy', choices=['product','not-applicable'], default='product',
                           help='Whether product Scope is required or intentionally not applicable for this KB.')
    inventory.add_argument('--registered-source-root', action='append', default=[],
                           help='Stable source membership root from the workspace catalog; may include roots above a selected subfolder.')
    inventory.add_argument('--exclude-scope', action='append', default=[]); inventory.add_argument('--override-excluded-scope', action='append', default=[])
    inventory.add_argument('--complete-boundary', action='store_true'); inventory.add_argument('--rescan-unchanged', action='store_true')
    inventory.add_argument('--no-recursive', action='store_true')
    inventory.add_argument('--run-id'); inventory.set_defaults(func=inventory_command)

    migrate = sub.add_parser('migrate-v05', help='import v0.5.0 data, preserving current IDs and reconstructing missing registry state')
    migrate.add_argument('--v05-root', required=True); migrate.add_argument('--kb-root', required=True)
    migrate.add_argument('--kb-id', required=True); migrate.add_argument('--name')
    migrate.add_argument('--accepted-by', required=True); migrate.add_argument('--rationale', required=True)
    migrate.add_argument('--accept-baseline', action='store_true'); migrate.add_argument('--run-id')
    migrate.set_defaults(func=migrate_v05_command)

    stage = sub.add_parser('stage', help='diff pipeline outputs against the accepted release')
    stage.add_argument('--kb-root', required=True); stage.add_argument('--run-id', required=True)
    stage.add_argument('--candidate-dir', default='./output'); stage.add_argument('--id-registry')
    stage.add_argument('--health-report', required=True,
                       help='Current work/step-card-1-health.json; bound to this staged release for publish gating.')
    stage.set_defaults(func=stage_command)

    decide = sub.add_parser('decide', help='record human review decisions for staged proposals')
    decide.add_argument('--kb-root', required=True); decide.add_argument('--run-id', required=True)
    decide.add_argument('--proposal-id'); decide.add_argument('--decision', choices=['accept','reject','defer'])
    decide.add_argument('--reviewer'); decide.add_argument('--rationale')
    decide.add_argument('--decisions-file',
                        help='JSONL with one explicit decision per row instead of one process per '
                             'proposal: {"proposal_id","decision","reviewer","rationale"}. The '
                             'canonical "Proposal ID"/"Decision"/"Reviewer"/"Rationale" spellings '
                             'are accepted too. All rows are validated before anything is written.')
    decide.set_defaults(func=decide_command)

    publish = sub.add_parser('publish', help='publish only explicitly reviewed accepted proposals')
    publish.add_argument('--kb-root', required=True); publish.add_argument('--run-id', required=True)
    publish.add_argument('--accept-quality-risk-by',
                         help='Explicit reviewer acknowledgement required when Card health is not READY.')
    publish.add_argument('--quality-risk-rationale',
                         help='Why publishing despite non-READY Card health is acceptable for this release.')
    publish.set_defaults(func=publish_command)

    rollback = sub.add_parser('rollback', help='point CURRENT.json to a prior immutable release')
    rollback.add_argument('--kb-root', required=True); rollback.add_argument('--release-id', required=True)
    rollback.add_argument('--reviewer', required=True); rollback.add_argument('--rationale', required=True)
    rollback.set_defaults(func=rollback_command)

    validate = sub.add_parser('validate', help='check current release hashes, schemas and cross references')
    validate.add_argument('--kb-root', required=True); validate.set_defaults(func=validate_command)

    index = sub.add_parser('index', help='build/rebuild the query index from CURRENT release')
    index.add_argument('--kb-root', required=True); index.add_argument('--context-map'); index.add_argument('--field-xlsx')
    index.add_argument('--rebuild', action='store_true'); index.set_defaults(func=index_command)

    query = sub.add_parser(
        'query', help='query CURRENT release through the materialized SQLite/FTS index',
        epilog='Remaining arguments are forwarded to query_fast.py, which requires --query and '
               'also accepts --mode, --business-context, --scope, --box, --top-k and the other '
               'retrieval limits. Run `./afc query_fast.py --help` for that list.')
    query.add_argument('--kb-root', required=True); query.add_argument('--db')
    query.add_argument('--query', help="The question, e.g. --query '乘客險什麼時候可加買？'; "
                                       'forwarded to query_fast.py with any other retrieval flags.')
    # Only `query` forwards its remaining arguments to query_fast.py. Parsing
    # every subcommand with parse_known_args() silently accepted a mistyped
    # flag, so `index --rebuldd` or a misspelt --accept-quality-risk-by looked
    # like it had taken effect.
    argv = sys.argv[1:]
    if argv[:1] == ['query']:
        args, forwarded = ap.parse_known_args(argv)
    else:
        args, forwarded = ap.parse_args(argv), []
    try:
        if args.command == 'query':
            query_command(args, forwarded)
        else:
            args.func(args)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print('knowledge_base:', str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
