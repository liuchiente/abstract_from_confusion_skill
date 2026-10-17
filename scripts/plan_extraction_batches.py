#!/usr/bin/env python3
"""Split the selected Source Units of Step 1 into resumable extraction batches.

Step 1 is the one step whose output the model writes by hand: one Evidence
Record per preserved source fact, Cards for supported knowledge, and exactly one
coverage ledger row per selected Source Unit. Until v0.8.6 nothing bounded that
work, while afc-pipeline asked for "one uninterrupted run" -- so a few thousand
selected rows ran out of context mid-extraction with no protocol for what had
been done or where to continue, and a rerun started from zero.

This script owns the deterministic part of batching: which units are still
unaccounted, in what order, grouped so a batch keeps its reading context, and
under the configured size bound. Reasoning still owns what each unit means.

Batches follow source order and keep whole groups (one document section, sheet
or table) together where they fit. A plan is a snapshot of what was pending when
it was written: after merging a batch, regenerate it. Each plan carries a short
content hash, and batch ID prefixes include it, so placeholder IDs minted in one
plan cannot collide with another plan's.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, write_json, write_jsonl
from afc_card_runtime.config import load_settings


def group_key(row):
    """The reading context a batch should avoid splitting."""
    source = row.get('source_path') or row.get('source_file') or '[unknown source]'
    section = row.get('section_key')
    if not section:
        path = row.get('section_heading_path') or []
        section = ' / '.join(str(x) for x in path if str(x).strip())
    if not section:
        structure = row.get('structure_path') or []
        # Table/sheet identity: everything above the row itself.
        section = ' / '.join(str(x) for x in structure[:-1] if str(x).strip())
    return f"{source}::{section or '[no section]'}"


def accounted_unit_ids(paths):
    seen = set()
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            continue
        for row in read_jsonl(path):
            unit_id = row.get('Source Unit ID')
            if unit_id and row.get('Disposition'):
                seen.add(str(unit_id))
    return seen


def build_batches(pending, max_units):
    """Whole groups per batch where they fit; oversized groups split in order."""
    groups, order = {}, []
    for row in pending:
        key = group_key(row)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    batches, current = [], {'units': [], 'groups': [], 'split_groups': []}
    for key in order:
        members = groups[key]
        if len(members) > max_units:
            if current['units']:
                batches.append(current)
                current = {'units': [], 'groups': [], 'split_groups': []}
            for start in range(0, len(members), max_units):
                chunk = members[start:start + max_units]
                batches.append({'units': chunk, 'groups': [key], 'split_groups': [key]})
            continue
        if current['units'] and len(current['units']) + len(members) > max_units:
            batches.append(current)
            current = {'units': [], 'groups': [], 'split_groups': []}
        current['units'].extend(members)
        current['groups'].append(key)
    if current['units']:
        batches.append(current)
    return batches


def main():
    settings = load_settings()
    default_max = settings.get('extraction.max_units_per_batch')
    ap = argparse.ArgumentParser(
        description='Split selected Source Units into resumable Step 1 extraction batches.',
        epilog='Rerun after merging a batch: the plan excludes units that already have a '
               'coverage ledger row, so it doubles as the resume point.')
    ap.add_argument('--source-map', required=True, help='work/step-card-0-source-map.jsonl')
    ap.add_argument('--coverage', action='append', default=[],
                    help='Existing coverage ledger(s); accounted units are excluded. Repeatable.')
    ap.add_argument('--max-units', type=int, default=default_max,
                    help=f'Units per batch; defaults to extraction.max_units_per_batch ({default_max})')
    ap.add_argument('--run-id', default='')
    ap.add_argument('--units-dir', default='work/extraction-batches',
                    help='Where each batch\'s Source Units are written so the model can read '
                         'one batch instead of the whole source map.')
    ap.add_argument('-o', '--output', required=True, help='work/step-card-1-extraction-plan.json')
    a = ap.parse_args()

    if a.max_units is None or a.max_units < 1:
        ap.error('--max-units must be a positive integer')
    source_path = Path(a.source_map)
    if not source_path.exists():
        ap.error(f'source map not found: {a.source_map}')

    rows = read_jsonl(source_path)
    selected = [r for r in rows if r.get('selected') and r.get('source_unit_id')]
    accounted = accounted_unit_ids(a.coverage)
    pending = [r for r in selected if str(r.get('source_unit_id')) not in accounted]

    digest = hashlib.sha256(
        '\n'.join(str(r.get('source_unit_id')) for r in pending).encode('utf-8')).hexdigest()
    plan_id = 'P' + digest[:6]

    units_dir = Path(a.units_dir)
    batches = []
    for number, batch in enumerate(build_batches(pending, a.max_units), 1):
        batch_id = f'{plan_id}-B{number:03d}'
        units_file = units_dir / f'{batch_id}-units.jsonl'
        write_jsonl(units_file, batch['units'])
        batches.append({
            'batch_id': batch_id,
            'units': len(batch['units']),
            'groups': batch['groups'],
            'split_groups': batch['split_groups'],
            'source_files': sorted({str(r.get('source_file') or r.get('source_path') or '')
                                    for r in batch['units']}),
            'units_file': units_file.as_posix(),
            'id_prefix': batch_id,
            'cards': f'work/step-card-1-cards.{batch_id}.jsonl',
            'evidence': f'work/step-card-1-evidence.{batch_id}.jsonl',
            'coverage': f'work/step-card-1-coverage.{batch_id}.jsonl',
            'source_unit_ids': [str(r.get('source_unit_id')) for r in batch['units']],
        })

    plan = {
        'plan_schema_version': '1',
        'plan_id': plan_id,
        'run_id': a.run_id,
        'source_map': source_path.as_posix(),
        'settings_path': str(settings.path) if settings.path else None,
        'max_units_per_batch': a.max_units,
        'source_units_total': len(rows),
        'selected_total': len(selected),
        'accounted_total': len(selected) - len(pending),
        'pending_total': len(pending),
        'batch_count': len(batches),
        'next_batch': batches[0]['batch_id'] if batches else None,
        'batches': batches,
        'note': ('Placeholder IDs must carry the batch id_prefix so two batches cannot mint the '
                 'same temporary ID. Merge with merge_extraction_batches.py, then allocate real '
                 'IDs once over the merged files. A plan is a snapshot: regenerate it after a '
                 'merge to get the remaining work.'),
    }
    write_json(a.output, plan)
    print(json.dumps({k: v for k, v in plan.items() if k != 'batches'},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0)


if __name__ == '__main__':
    main()
