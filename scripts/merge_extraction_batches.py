#!/usr/bin/env python3
"""Merge per-batch Step 1 extraction output into the canonical Step 1 files.

The companion to plan_extraction_batches.py. Batched extraction only helps if
rejoining the parts is checked rather than hoped for, so this refuses to write
anything unless the merge is clean:

  * the same ID used for two different records (the collision a placeholder like
    EVD-TMP-001, minted independently in two batches, produces) is an error, not
    a silent overwrite;
  * two coverage rows for one Source Unit are an error -- a unit gets exactly
    one disposition;
  * a ledger row may only cite Cards and Evidence present in the merge;
  * with --plan, every planned unit must be accounted for exactly once, so an
    unfinished batch is reported instead of passing as a complete extraction.

Allocate real IDs once over the merged files; never per batch.
"""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_json, read_jsonl, write_json, write_jsonl

CARD_ID = 'Card ID'
EVIDENCE_ID = 'Evidence ID'
UNIT_ID = 'Source Unit ID'


def canonical(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def collect(paths, id_field, errors, label):
    """Union rows by ID, rejecting one ID that names two different records."""
    merged, sources, duplicates = {}, {}, 0
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            errors.append(f'{label} file not found: {path}')
            continue
        for number, row in enumerate(read_jsonl(path), 1):
            row_id = row.get(id_field)
            if not row_id:
                errors.append(f'{path}:{number}: {label} row has no {id_field}')
                continue
            row_id = str(row_id)
            if row_id in merged:
                if canonical(merged[row_id]) == canonical(row):
                    duplicates += 1
                    continue
                errors.append(
                    f'{label} {id_field} {row_id} describes two different records: '
                    f'{sources[row_id]} and {path}:{number}. Placeholder IDs must carry the '
                    'batch id_prefix from the extraction plan.')
                continue
            merged[row_id] = row
            sources[row_id] = f'{path}:{number}'
    return merged, duplicates


def collect_coverage(paths, errors):
    merged, sources = {}, {}
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            errors.append(f'coverage file not found: {path}')
            continue
        for number, row in enumerate(read_jsonl(path), 1):
            unit_id = row.get(UNIT_ID)
            if not unit_id:
                errors.append(f'{path}:{number}: coverage row has no {UNIT_ID}')
                continue
            unit_id = str(unit_id)
            if unit_id in merged:
                if canonical(merged[unit_id]) == canonical(row):
                    continue
                errors.append(
                    f'two different coverage rows for {unit_id}: {sources[unit_id]} and '
                    f'{path}:{number}. One selected Source Unit gets exactly one disposition.')
                continue
            merged[unit_id] = row
            sources[unit_id] = f'{path}:{number}'
    return merged


def main():
    ap = argparse.ArgumentParser(
        description='Merge per-batch Step 1 cards, evidence and coverage into the canonical files.')
    ap.add_argument('--cards', nargs='+', default=[], help='Per-batch card JSONL files')
    ap.add_argument('--evidence', nargs='+', default=[], help='Per-batch evidence JSONL files')
    ap.add_argument('--coverage', nargs='+', default=[], help='Per-batch coverage ledger files')
    ap.add_argument('--plan', help='work/step-card-1-extraction-plan.json; checks completeness')
    ap.add_argument('--cards-output', default='work/step-card-1-cards.jsonl')
    ap.add_argument('--evidence-output', default='work/step-card-1-evidence.jsonl')
    ap.add_argument('--coverage-output', default='work/step-card-1-coverage.jsonl')
    ap.add_argument('--json-output')
    a = ap.parse_args()

    if not (a.cards or a.evidence or a.coverage):
        ap.error('pass at least one of --cards, --evidence, --coverage')

    errors = []
    cards, card_duplicates = collect(a.cards, CARD_ID, errors, 'card')
    evidence, evidence_duplicates = collect(a.evidence, EVIDENCE_ID, errors, 'evidence')
    coverage = collect_coverage(a.coverage, errors)

    for unit_id, row in coverage.items():
        for cid in row.get('Card IDs') or []:
            if str(cid) not in cards:
                errors.append(f'coverage row {unit_id} cites unknown Card ID {cid}')
        for eid in row.get('Evidence Record IDs') or []:
            if str(eid) not in evidence:
                errors.append(f'coverage row {unit_id} cites unknown Evidence ID {eid}')
    for card_id, row in cards.items():
        for eid in row.get('Evidence Record IDs') or []:
            if str(eid) not in evidence:
                errors.append(f'card {card_id} cites unknown Evidence ID {eid}')

    planned, missing, unplanned = [], [], []
    if a.plan:
        plan = read_json(a.plan) or {}
        for batch in plan.get('batches') or []:
            planned.extend(str(x) for x in batch.get('source_unit_ids') or [])
        missing = [unit for unit in planned if unit not in coverage]
        unplanned = [unit for unit in coverage if planned and unit not in set(planned)]
        if missing:
            errors.append(f'{len(missing)} planned Source Unit(s) have no coverage row; the '
                          'extraction is unfinished: ' + ', '.join(missing[:10]))

    report = {
        'status': 'FAIL' if errors else 'PASS',
        'cards': len(cards),
        'evidence': len(evidence),
        'coverage_rows': len(coverage),
        'identical_duplicate_rows': {'cards': card_duplicates, 'evidence': evidence_duplicates},
        'planned_units': len(planned),
        'planned_units_without_coverage': missing[:50],
        'coverage_rows_outside_the_plan': unplanned[:50],
        'dispositions': {},
        'outputs': [],
        'errors': errors,
    }
    for row in coverage.values():
        disposition = str(row.get('Disposition') or '[missing]')
        report['dispositions'][disposition] = report['dispositions'].get(disposition, 0) + 1

    if errors:
        report['note'] = 'Nothing was written; a half-merged Step 1 is worse than an unmerged one.'
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if a.json_output:
            write_json(a.json_output, report)
        raise SystemExit(2)

    for rows, out, id_field in ((cards, a.cards_output, CARD_ID),
                                (evidence, a.evidence_output, EVIDENCE_ID),
                                (coverage, a.coverage_output, UNIT_ID)):
        if not rows:
            continue
        write_jsonl(out, [rows[key] for key in sorted(rows)])
        report['outputs'].append(out)

    report['note'] = ('IDs are still placeholders; run allocate_ids.py once over the merged '
                      'cards and evidence, then rewrite the ledger with its id maps.')
    if a.json_output:
        write_json(a.json_output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0)


if __name__ == '__main__':
    main()
