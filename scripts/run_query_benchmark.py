#!/usr/bin/env python3
"""Run the AFC query benchmark and compare it against an accepted baseline.

v0.4.1 described a retrieval-regression layer and shipped
config/query-cases.example.yaml, but nothing executed those cases: the expected
resolutions were documentation. This runner executes each case against the real
index, asserts the documented expectations, and diffs the result against a saved
baseline so a regression is a failing case rather than an impression.

  run_query_benchmark.py --db work/query-index/afc-query.db \\
      --cases config/query-cases.yaml -o work/query-runs/benchmark.json
  run_query_benchmark.py ... --baseline work/query-runs/baseline.json
"""
from pathlib import Path
import argparse, json, subprocess, sys, tempfile

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import normalize_text, read_json, write_json

RUNNER = Path(__file__).with_name('query_fast.py')


def run_query(db, query, extra=()):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'q.json'
        cmd = [sys.executable, str(RUNNER), '--db', str(db), '--query', query, '-o', str(out), *extra]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f'query_fast.py failed for {query!r}: {proc.stderr.strip()}')
        return json.loads(out.read_text(encoding='utf-8'))


def ids(result, section, key):
    return [normalize_text(x['record'].get(key)) for x in (result.get(section) or {}).get('direct', [])]


def check(case, result):
    """Assert one case. Returns (list of failures, observed summary)."""
    failures = []
    exp_res = case.get('expected_resolution') or {}
    exp = case.get('expect') or {}

    card_ids = ids(result, 'card', 'Card ID')
    evidence_ids = ids(result, 'evidence', 'Evidence ID')
    observed = {
        'business_contexts': result.get('detected_business_contexts') or [],
        'scopes': result.get('resolved_scopes') or [],
        'target_mode': result.get('query_target_mode'),
        'intent': result.get('detected_intent'),
        'source_languages': result.get('requested_source_languages') or [],
        'boxes': [{'type': b.get('box_type'), 'name': b.get('name')}
                  for b in result.get('hard_boundary_boxes') or []],
        'box_hops': (result.get('box_topology') or {}).get('hop_count'),
        'card_hops': result.get('card_hop_count'),
        'recovery_stage': (result.get('evidence') or {}).get('recovery_stage_used'),
        'cards': card_ids,
        'evidence': evidence_ids,
        'elapsed_ms': result.get('elapsed_ms'),
    }

    def expect_set(name, want, got):
        missing = [x for x in want if normalize_text(x) not in {normalize_text(g) for g in got}]
        if missing:
            failures.append(f'{name}: missing {missing}, got {got}')

    for key in ('business_contexts', 'scopes', 'source_languages'):
        if key in exp_res:
            expect_set(key, exp_res[key], observed[key])
    for key in ('target_mode', 'intent'):
        if key in exp_res and normalize_text(exp_res[key]) != normalize_text(observed[key]):
            failures.append(f'{key}: expected {exp_res[key]!r}, got {observed[key]!r}')
    for key in ('box_hops', 'card_hops'):
        if key in exp_res and exp_res[key] != observed[key]:
            failures.append(f'{key}: expected {exp_res[key]}, got {observed[key]}')
    if 'boxes' in exp_res:
        got = {(normalize_text(b['type']), normalize_text(b['name'])) for b in observed['boxes']}
        for want in exp_res['boxes']:
            pair = (normalize_text(want.get('type')), normalize_text(want.get('name')))
            if pair not in got:
                failures.append(f'boxes: missing {pair}, got {sorted(got)}')

    if 'cards_include' in exp:
        expect_set('cards_include', exp['cards_include'], card_ids)
    if 'evidence_include' in exp:
        expect_set('evidence_include', exp['evidence_include'], evidence_ids)
    if 'cards_exclude' in exp:
        hit = [x for x in exp['cards_exclude'] if normalize_text(x) in card_ids]
        if hit:
            failures.append(f'cards_exclude: unexpectedly returned {hit}')
    if 'top_card' in exp:
        if not card_ids or normalize_text(card_ids[0]) != normalize_text(exp['top_card']):
            failures.append(f"top_card: expected {exp['top_card']}, got {card_ids[:1]}")
    if 'top_evidence' in exp:
        if not evidence_ids or normalize_text(evidence_ids[0]) != normalize_text(exp['top_evidence']):
            failures.append(f"top_evidence: expected {exp['top_evidence']}, got {evidence_ids[:1]}")
    if 'min_cards' in exp and len(card_ids) < exp['min_cards']:
        failures.append(f"min_cards: expected >= {exp['min_cards']}, got {len(card_ids)}")
    if 'min_evidence' in exp and len(evidence_ids) < exp['min_evidence']:
        failures.append(f"min_evidence: expected >= {exp['min_evidence']}, got {len(evidence_ids)}")
    if 'recovery_stage' in exp and normalize_text(exp['recovery_stage']) != normalize_text(observed['recovery_stage']):
        failures.append(f"recovery_stage: expected {exp['recovery_stage']!r}, got {observed['recovery_stage']!r}")

    # Product leakage: a Card outside the resolved Scope must not be returned.
    leakage = []
    scopes = {normalize_text(x) for x in observed['scopes']}
    if scopes:
        for item in (result.get('card') or {}).get('direct', []):
            rec = item['record']
            raw = rec.get('Scopes') or rec.get('Scope') or rec.get('Product Context') or ''
            card_scopes = {normalize_text(x) for x in (raw if isinstance(raw, list) else str(raw).replace('，', ',').split(','))}
            card_scopes = {x for x in card_scopes if x}
            if card_scopes and not (card_scopes & scopes) and not card_scopes & {'Multiple', 'Shared', '多商品'}:
                leakage.append(normalize_text(rec.get('Card ID')))
    observed['product_leakage'] = leakage
    if len(leakage) > exp.get('max_product_leakage', 0):
        failures.append(f'product_leakage: {leakage}')

    return failures, observed


def main():
    ap = argparse.ArgumentParser(description='Run the AFC query benchmark against an index.')
    ap.add_argument('--db', required=True)
    ap.add_argument('--cases', required=True)
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--baseline', help='A previous benchmark result to diff against')
    ap.add_argument('--update-baseline', help='Write the current result as the new baseline')
    a = ap.parse_args()

    data = yaml.safe_load(Path(a.cases).read_text(encoding='utf-8')) or {}
    cases = data.get('queries') or []
    if not cases:
        raise SystemExit(f'no queries in {a.cases}')

    results, passed, failed, errored = [], 0, 0, 0
    for case in cases:
        cid = case.get('id') or case.get('query')
        extra = []
        for flag, key in (('--scope', 'scope'), ('--business-context', 'business_context'),
                          ('--box', 'box'), ('--mode', 'mode')):
            for v in (case.get('args') or {}).get(key, []) if isinstance((case.get('args') or {}).get(key), list) else ([ (case.get('args') or {}).get(key) ] if (case.get('args') or {}).get(key) else []):
                extra += [flag, str(v)]
        try:
            result = run_query(a.db, case['query'], extra)
        except Exception as e:  # a query that cannot run is a benchmark failure
            errored += 1
            results.append({'id': cid, 'query': case.get('query'), 'status': 'ERROR', 'error': str(e)})
            continue
        failures, observed = check(case, result)
        status = 'PASS' if not failures else 'FAIL'
        passed += status == 'PASS'
        failed += status == 'FAIL'
        results.append({'id': cid, 'query': case.get('query'), 'status': status,
                        'failures': failures, 'observed': observed})

    report = {
        'benchmark_schema_version': '1', 'db': str(a.db), 'cases_file': str(a.cases),
        'total': len(cases), 'passed': passed, 'failed': failed, 'errored': errored,
        'results': results,
        'status': 'PASS' if (failed == 0 and errored == 0) else 'FAIL',
    }

    if a.baseline:
        base = read_json(a.baseline) or {}
        base_by = {r.get('id'): r for r in base.get('results', [])}
        regressions, fixes, new_cases = [], [], []
        for r in results:
            prev = base_by.get(r['id'])
            if prev is None:
                new_cases.append(r['id'])
            elif prev.get('status') == 'PASS' and r['status'] != 'PASS':
                regressions.append({'id': r['id'], 'failures': r.get('failures')})
            elif prev.get('status') != 'PASS' and r['status'] == 'PASS':
                fixes.append(r['id'])
        removed = [cid for cid in base_by if cid not in {r['id'] for r in results}]
        report['baseline_comparison'] = {
            'baseline': str(a.baseline), 'regressions': regressions, 'fixed': fixes,
            'new_cases': new_cases, 'cases_removed_from_baseline': removed,
        }
        if regressions:
            report['status'] = 'FAIL'

    write_json(a.output, report)
    if a.update_baseline:
        write_json(a.update_baseline, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}, ensure_ascii=False, indent=2))
    for r in results:
        if r['status'] != 'PASS':
            print(f"  {r['status']} {r['id']}: {r.get('failures') or r.get('error')}")
    raise SystemExit(0 if report['status'] == 'PASS' else 2)


if __name__ == '__main__':
    main()
