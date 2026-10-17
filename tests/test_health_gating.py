"""Health-grading gate tests.

In v0.4.1 four of the six Loop Gate metrics were read straight out of reports
the extracting model wrote about its own work and then graded GREEN/YELLOW/RED,
which made a self-assessment look like a measurement.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, expect_ok=True):
    proc = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=ROOT)
    if expect_ok:
        assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def write_jsonl(path, rows):
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')


def fixtures(tmp_path, n=60):
    src = [{'source_unit_id': f'u{i:04d}', 'kind': 'sheet-row', 'selected': True,
            'knowledge_signal_types': ['Literal Knowledge'] if i % 4 == 0 else ['Semantic Knowledge']}
           for i in range(1, n + 1)]
    cov = [{'Source Unit ID': f'u{i:04d}', 'Disposition': 'Card',
            'Card IDs': [f'CARD-{i:06d}'], 'Evidence Record IDs': [f'EVD-{i:06d}']}
           for i in range(1, n + 1)]
    cards = [{'Card ID': f'CARD-{i:06d}', 'Card Type': 'Rule', 'Concept Key': f'k{i}',
              'Title': f't{i}', 'Content': 'c', 'Scope': 'CA', 'Source': 's',
              'Source Location': 'l', 'Source Unit IDs': [f'u{i:04d}'],
              'Evidence Record IDs': [f'EVD-{i:06d}']} for i in range(1, n + 1)]
    evd = [{'Evidence ID': f'EVD-{i:06d}', 'Evidence Mode': 'VERBATIM', 'Original Text': 'x',
            'Source': 's', 'Source Location': 'l', 'Source Unit IDs': [f'u{i:04d}']}
           for i in range(1, n + 1)]
    paths = {}
    for name, rows in (('src', src), ('cov', cov), ('cards', cards), ('evd', evd)):
        paths[name] = tmp_path / f'{name}.jsonl'
        write_jsonl(paths[name], rows)
    return paths


def evaluate(tmp_path, paths, extra=(), out='health.json'):
    target = tmp_path / out
    run(['scripts/evaluate_card_health.py', '--source-map', str(paths['src']),
         '--coverage', str(paths['cov']), '--cards', str(paths['cards']),
         '--evidence', str(paths['evd']), '--json-output', str(target), *extra])
    return json.loads(target.read_text(encoding='utf-8'))


def clean_metric(tmp_path, paths, purpose, n, name, verdict):
    sample = tmp_path / f'{purpose}-sample.json'
    args = ['scripts/sample_units.py', '--purpose', purpose, '-n', str(n), '--run-id', 'R1',
            '-o', str(sample)]
    if purpose == 'saturation':
        args += ['--source-map', str(paths['src'])]
    else:
        args += ['--cards', str(paths['cards'])]
        if purpose == 'fidelity':
            args += ['--evidence', str(paths['evd'])]
    run(args)
    manifest = json.loads(sample.read_text(encoding='utf-8'))
    verdicts = tmp_path / f'{purpose}-v.jsonl'
    write_jsonl(verdicts, [{'item_id': i['item_id'], 'verdict': verdict} for i in manifest['items']])
    report = tmp_path / name
    run(['scripts/compute_review_metrics.py', '--sample', str(sample),
         '--verdicts', str(verdicts), '-o', str(report)])
    return report


def test_a_self_reported_report_cannot_reach_ready(tmp_path):
    paths = fixtures(tmp_path)
    # Exactly the v0.4.1 report shape: a rate, no sample provenance.
    selfreported = tmp_path / 'sat.json'
    selfreported.write_text(json.dumps(
        {'sample_count': 12, 'missing_count': 0, 'saturation_miss_rate': 0.0}), encoding='utf-8')
    health = evaluate(tmp_path, paths, ['--saturation-report', str(selfreported)])
    assert health['metric_states']['saturation'] == 'UNVERIFIED_SAMPLE'
    assert health['overall_status'] != 'READY'
    assert health['primary_loop_route'] == 'RUN_HEALTH_CHECKS'


def test_a_sample_below_the_minimum_is_not_graded(tmp_path):
    paths = fixtures(tmp_path)
    report = clean_metric(tmp_path, paths, 'saturation', 12, 'sat.json', 'complete')
    health = evaluate(tmp_path, paths, ['--saturation-report', str(report)])
    assert health['metric_states']['saturation'] == 'INSUFFICIENT_SAMPLE'
    assert health['review_samples']['saturation']['sample_count'] == 12
    # A 0.02 green threshold is not expressible at n=12, and the report says so.
    assert health['review_samples']['saturation']['min_detectable_rate'] > 0.02
    assert health['overall_status'] != 'READY'


def test_verified_clean_samples_reach_ready(tmp_path):
    paths = fixtures(tmp_path)
    sat = clean_metric(tmp_path, paths, 'saturation', 40, 'sat.json', 'complete')
    fid = clean_metric(tmp_path, paths, 'fidelity', 40, 'fid.json', 'supported')
    atom = clean_metric(tmp_path, paths, 'atomicity', 40, 'atom.json', 'atomic_keep')
    health = evaluate(tmp_path, paths, [
        '--saturation-report', str(sat), '--fidelity-report', str(fid),
        '--atomicity-report', str(atom), '--previous-cards', str(paths['cards'])])
    assert health['overall_status'] == 'READY'
    assert all(health['metric_states'][k] == 'GREEN'
               for k in ('saturation', 'novelty', 'unsupported', 'atomicity'))


def test_an_unsupported_claim_forces_evidence_repair(tmp_path):
    paths = fixtures(tmp_path)
    sat = clean_metric(tmp_path, paths, 'saturation', 40, 'sat.json', 'complete')
    fid = clean_metric(tmp_path, paths, 'fidelity', 40, 'fid.json', 'unsupported_claim')
    health = evaluate(tmp_path, paths, ['--saturation-report', str(sat), '--fidelity-report', str(fid)])
    assert health['metric_states']['unsupported'] == 'RED'
    assert health['primary_loop_route'] == 'EVIDENCE_REPAIR'
    assert health['overall_status'] == 'RERUN_RECOMMENDED'


def test_missing_literal_evidence_is_reported_as_a_coverage_gap(tmp_path):
    paths = fixtures(tmp_path)
    # Drop the Evidence of one literal-signal unit.
    cov = [json.loads(l) for l in paths['cov'].read_text(encoding='utf-8').splitlines()]
    cov[3]['Evidence Record IDs'] = []
    write_jsonl(paths['cov'], cov)
    evd = [json.loads(l) for l in paths['evd'].read_text(encoding='utf-8').splitlines()]
    write_jsonl(paths['evd'], [e for e in evd if e['Evidence ID'] != 'EVD-000004'])
    health = evaluate(tmp_path, paths)
    assert health['evidence_coverage']['literal']['coverage'] < 1.0
    assert any(r['action'] == 'EVIDENCE_REPAIR' for r in health['recommendations'])


def test_thresholds_come_from_settings(tmp_path):
    paths = fixtures(tmp_path)
    health = evaluate(tmp_path, paths)
    assert health['thresholds']['min_sample_for_rate_grading'] == 30
    assert 'settings.yaml' in health['thresholds']['source']
