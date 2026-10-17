"""Review-sampling integrity tests.

v0.4.1 asked the extracting model to "perform an independent, stratified
re-check" with no size, no strata and no record of which units it looked at,
then graded the resulting self-reported rate against a 0.02 threshold that a
small sample cannot even express.
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
    return json.loads(proc.stdout) if proc.stdout.strip().startswith('{') else {}


def write_jsonl(path, rows):
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')


def make_source_map(tmp_path, n=80):
    rows = []
    for i in range(1, n + 1):
        rows.append({'source_unit_id': f'u{i:04d}',
                     'kind': ['sheet-row', 'paragraph', 'table-row'][i % 3],
                     'selected': True,
                     'knowledge_signal_types': ['Literal Knowledge'] if i % 4 == 0 else ['Semantic Knowledge']})
    p = tmp_path / 'src.jsonl'
    write_jsonl(p, rows)
    return p


def draw(tmp_path, src, n, run_id='R1', out='sample.json'):
    path = tmp_path / out
    run(['scripts/sample_units.py', '--purpose', 'saturation', '--source-map', str(src),
         '-n', str(n), '--run-id', run_id, '-o', str(path)])
    return json.loads(path.read_text(encoding='utf-8'))


def test_sample_is_deterministic(tmp_path):
    src = make_source_map(tmp_path)
    a = draw(tmp_path, src, 20, out='a.json')
    b = draw(tmp_path, src, 20, out='b.json')
    assert a['items'] == b['items']
    assert a['seed'] == b['seed']


def test_a_different_run_id_draws_a_different_sample(tmp_path):
    src = make_source_map(tmp_path)
    a = draw(tmp_path, src, 20, run_id='R1', out='a.json')
    b = draw(tmp_path, src, 20, run_id='R2', out='b.json')
    assert a['items'] != b['items']


def test_every_non_empty_stratum_is_represented(tmp_path):
    src = make_source_map(tmp_path)
    manifest = draw(tmp_path, src, 20)
    for key, info in manifest['strata'].items():
        assert info['sampled'] >= 1, key
    assert manifest['sample_count'] == 20


def test_partial_verdicts_are_rejected(tmp_path):
    src = make_source_map(tmp_path)
    manifest = draw(tmp_path, src, 20)
    verdicts = tmp_path / 'v.jsonl'
    write_jsonl(verdicts, [{'item_id': i['item_id'], 'verdict': 'complete'}
                           for i in manifest['items'][:5]])
    out = run(['scripts/compute_review_metrics.py', '--sample', str(tmp_path / 'sample.json'),
               '--verdicts', str(verdicts), '-o', str(tmp_path / 'm.json')], expect_ok=False)
    assert out['status'] == 'FAIL'
    assert any('no verdict' in e for e in out['errors'])


def test_verdicts_outside_the_sample_are_rejected(tmp_path):
    src = make_source_map(tmp_path)
    manifest = draw(tmp_path, src, 20)
    verdicts = tmp_path / 'v.jsonl'
    rows = [{'item_id': i['item_id'], 'verdict': 'complete'} for i in manifest['items']]
    rows.append({'item_id': 'u9999', 'verdict': 'complete'})
    write_jsonl(verdicts, rows)
    out = run(['scripts/compute_review_metrics.py', '--sample', str(tmp_path / 'sample.json'),
               '--verdicts', str(verdicts), '-o', str(tmp_path / 'm.json')], expect_ok=False)
    assert out['status'] == 'FAIL'
    assert any('outside the drawn sample' in e for e in out['errors'])


def test_an_invalid_verdict_vocabulary_is_rejected(tmp_path):
    src = make_source_map(tmp_path)
    manifest = draw(tmp_path, src, 20)
    verdicts = tmp_path / 'v.jsonl'
    rows = [{'item_id': i['item_id'], 'verdict': 'complete'} for i in manifest['items']]
    rows[0]['verdict'] = 'looks_fine'
    write_jsonl(verdicts, rows)
    out = run(['scripts/compute_review_metrics.py', '--sample', str(tmp_path / 'sample.json'),
               '--verdicts', str(verdicts), '-o', str(tmp_path / 'm.json')], expect_ok=False)
    assert out['status'] == 'FAIL'


def test_complete_verdicts_yield_a_verified_rate(tmp_path):
    src = make_source_map(tmp_path)
    manifest = draw(tmp_path, src, 20)
    verdicts = tmp_path / 'v.jsonl'
    rows = [{'item_id': i['item_id'], 'verdict': 'complete'} for i in manifest['items']]
    rows[0]['verdict'] = 'missing_evidence'
    write_jsonl(verdicts, rows)
    out = run(['scripts/compute_review_metrics.py', '--sample', str(tmp_path / 'sample.json'),
               '--verdicts', str(verdicts), '-o', str(tmp_path / 'm.json')])
    assert out['status'] == 'PASS'
    assert out['sample_integrity'] == 'VERIFIED'
    assert out['sample_count'] == 20
    report = json.loads((tmp_path / 'm.json').read_text(encoding='utf-8'))
    assert abs(report['saturation_miss_rate'] - 0.05) < 1e-9
    assert report['missing_evidence_count'] == 1
