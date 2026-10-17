#!/usr/bin/env python3
"""Turn per-item review verdicts into the AFC health reports.

The reviewer (human or model) never writes a rate. It writes one verdict per
sampled item; this script checks the verdicts cover exactly the drawn sample and
then computes the rate, carrying the sample size forward so
`evaluate_card_health.py` can refuse to grade a rate that the sample is too
small to support.
"""
from pathlib import Path
import argparse, json, sys
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, read_json, write_json, normalize_text

VERDICTS = {
    'saturation': ['complete', 'missing_card', 'missing_evidence', 'missing_both'],
    'fidelity': ['supported', 'unsupported_claim', 'altered_literal', 'dropped_structured_fact'],
    'atomicity': ['atomic_keep', 'split_required', 'ambiguous'],
}


def ratio(n, d):
    return (float(n) / float(d)) if d else None


def main():
    ap = argparse.ArgumentParser(description='Compute an AFC review metric from a sample manifest plus verdicts.')
    ap.add_argument('--sample', required=True, help='Manifest from sample_units.py')
    ap.add_argument('--verdicts', required=True, help='JSONL: item_id, verdict, optional note')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--allow-partial', action='store_true',
                    help='Report with missing verdicts instead of failing (marks the sample UNVERIFIED)')
    a = ap.parse_args()

    manifest = read_json(a.sample)
    if not manifest:
        raise SystemExit(f'sample manifest not found or empty: {a.sample}')
    purpose = manifest.get('purpose')
    if purpose not in VERDICTS:
        raise SystemExit(f'unknown purpose in manifest: {purpose!r}')
    allowed = set(VERDICTS[purpose])

    expected = [normalize_text(i['item_id']) for i in manifest.get('items', [])]
    expected_set = set(expected)
    stratum_of = {normalize_text(i['item_id']): i.get('stratum') for i in manifest.get('items', [])}

    rows = read_jsonl(a.verdicts)
    seen, invalid, duplicates, unexpected = {}, [], [], []
    for r in rows:
        iid = normalize_text(r.get('item_id'))
        verdict = normalize_text(r.get('verdict')).lower()
        if not iid:
            invalid.append({'row': r, 'reason': 'missing item_id'})
            continue
        if iid not in expected_set:
            unexpected.append(iid)
            continue
        if verdict not in allowed:
            invalid.append({'item_id': iid, 'verdict': r.get('verdict'),
                            'reason': f'verdict must be one of {sorted(allowed)}'})
            continue
        if iid in seen:
            duplicates.append(iid)
            continue
        seen[iid] = {'verdict': verdict, 'note': normalize_text(r.get('note'))}

    missing = [i for i in expected if i not in seen]
    counts = Counter(v['verdict'] for v in seen.values())
    reviewed = len(seen)

    errors = []
    if unexpected:
        errors.append(f'{len(unexpected)} verdicts are outside the drawn sample')
    if duplicates:
        errors.append(f'{len(duplicates)} items have more than one verdict')
    if invalid:
        errors.append(f'{len(invalid)} verdict rows are invalid')
    if missing and not a.allow_partial:
        errors.append(f'{len(missing)} sampled items have no verdict')

    integrity = 'VERIFIED' if (not errors and not missing) else 'UNVERIFIED'
    report = {
        'metric_schema_version': '1',
        'purpose': purpose,
        'run_id': manifest.get('run_id'),
        'seed': manifest.get('seed'),
        'sample_source': 'sample_units.py',
        'sample_integrity': integrity,
        'population': manifest.get('population'),
        'sample_count': reviewed,
        'drawn_sample_count': manifest.get('sample_count'),
        'missing_verdicts': missing[:50],
        'missing_verdict_count': len(missing),
        'unexpected_verdicts': sorted(set(unexpected))[:50],
        'duplicate_verdicts': sorted(set(duplicates))[:50],
        'invalid_verdicts': invalid[:50],
        'verdict_counts': dict(counts),
        'errors': errors,
        'status': 'PASS' if not errors else 'FAIL',
    }

    if purpose == 'saturation':
        miss = counts['missing_card'] + counts['missing_evidence'] + counts['missing_both']
        report.update({
            'missing_card_count': counts['missing_card'] + counts['missing_both'],
            'missing_evidence_count': counts['missing_evidence'] + counts['missing_both'],
            'missing_count': miss,
            'saturation_miss_rate': ratio(miss, reviewed),
            'findings': [{'item_id': k, 'verdict': v['verdict'], 'note': v['note']}
                         for k, v in sorted(seen.items()) if v['verdict'] != 'complete'],
            'sampled_item_ids': sorted(seen),
        })
    elif purpose == 'fidelity':
        bad = counts['unsupported_claim']
        report.update({
            'claims_reviewed': reviewed,
            'unsupported_claim_count': bad,
            'unsupported_claim_rate': ratio(bad, reviewed),
            'altered_literal_count': counts['altered_literal'],
            'dropped_structured_fact_count': counts['dropped_structured_fact'],
            'evidence_records_reviewed': sum(
                1 for i in manifest.get('items', []) if i.get('item_type') == 'evidence'),
            'findings': [{'item_id': k, 'verdict': v['verdict'], 'note': v['note']}
                         for k, v in sorted(seen.items()) if v['verdict'] != 'supported'],
        })
    else:
        issues = counts['split_required'] + counts['ambiguous']
        report.update({
            'candidates_reviewed': reviewed,
            'atomic_keep': counts['atomic_keep'],
            'split_required': counts['split_required'],
            'ambiguous': counts['ambiguous'],
            'atomicity_issue_rate': ratio(issues, reviewed),
            'findings': [{'item_id': k, 'verdict': v['verdict'], 'note': v['note']}
                         for k, v in sorted(seen.items()) if v['verdict'] != 'atomic_keep'],
        })

    write_json(a.output, report)
    print(json.dumps({k: v for k, v in report.items() if k not in ('findings', 'sampled_item_ids')},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['status'] == 'PASS' else 2)


if __name__ == '__main__':
    main()
