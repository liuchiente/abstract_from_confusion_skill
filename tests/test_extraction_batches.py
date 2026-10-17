"""Step 1 is written by the model, so it is the one step that can run out of
context mid-run. Batching only helps if the split is deterministic and the
rejoin is checked; these tests pin both.
"""
from pathlib import Path
import json
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from afc_card_runtime.common import read_jsonl  # noqa: E402


def run(script, *args, cwd):
    return subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *args],
                          capture_output=True, text=True, cwd=cwd,
                          env={'AFC_HOME': str(ROOT), 'PATH': '/usr/bin:/bin'})


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows),
                    encoding='utf-8')


def source_map(path, sections):
    rows = []
    for name, count in sections:
        for i in range(count):
            rows.append({'source_unit_id': f'a.docx::{name}::R{i:04d}', 'selected': True,
                         'kind': 'table-row', 'source_file': 'a.docx', 'section_key': name})
    rows.append({'source_unit_id': 'a.docx::X::R0000', 'selected': False,
                 'kind': 'paragraph', 'source_file': 'a.docx'})
    write_rows(path, rows)
    return rows


def plan_for(tmp_path, sections, max_units=10, coverage=()):
    units = tmp_path / 'source-map.jsonl'
    source_map(units, sections)
    args = ['--source-map', str(units), '--max-units', str(max_units),
            '--units-dir', str(tmp_path / 'batches'), '-o', str(tmp_path / 'plan.json')]
    for path in coverage:
        args += ['--coverage', str(path)]
    proc = run('plan_extraction_batches.py', *args, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    return json.loads((tmp_path / 'plan.json').read_text(encoding='utf-8'))


def test_batches_cover_every_selected_unit_once_and_keep_groups_whole(tmp_path):
    plan = plan_for(tmp_path, [('s1', 8), ('s2', 25), ('s3', 3)], max_units=10)
    assert plan['selected_total'] == 36 and plan['pending_total'] == 36

    batched = [unit for batch in plan['batches'] for unit in batch['source_unit_ids']]
    assert len(batched) == len(set(batched)) == 36, 'a unit was dropped or batched twice'
    assert all(batch['units'] <= 10 for batch in plan['batches'])
    # The unselected unit is out of scope for extraction.
    assert not any('::X::' in unit for unit in batched)

    # s1 and s3 fit whole; only the oversized s2 may be split.
    split = {group for batch in plan['batches'] for group in batch['split_groups']}
    assert split == {'a.docx::s2'}
    for batch in plan['batches']:
        units_file = Path(batch['units_file'])
        assert len(read_jsonl(units_file)) == batch['units'], 'batch unit file disagrees with plan'


def test_the_plan_is_deterministic_and_resumes_from_coverage(tmp_path):
    first = plan_for(tmp_path, [('s1', 8), ('s2', 12)], max_units=10)
    again = plan_for(tmp_path, [('s1', 8), ('s2', 12)], max_units=10)
    assert first['plan_id'] == again['plan_id']
    assert [b['source_unit_ids'] for b in first['batches']] == \
           [b['source_unit_ids'] for b in again['batches']]

    done = first['batches'][0]['source_unit_ids']
    ledger = tmp_path / 'coverage.jsonl'
    write_rows(ledger, [{'Source Unit ID': unit, 'Disposition': 'Skip',
                         'Skip Reason': 'x', 'Card IDs': [], 'Evidence Record IDs': []}
                        for unit in done])
    resumed = plan_for(tmp_path, [('s1', 8), ('s2', 12)], max_units=10, coverage=[ledger])
    assert resumed['accounted_total'] == len(done)
    assert resumed['pending_total'] == 20 - len(done)
    remaining = [u for b in resumed['batches'] for u in b['source_unit_ids']]
    assert not set(remaining) & set(done), 'resume re-issued work that was already accounted'
    assert resumed['plan_id'] != first['plan_id'], (
        'a resumed plan must mint different placeholder prefixes than the plan it follows')


def batch_output(tmp_path, prefix, unit_ids, text='x'):
    write_rows(tmp_path / f'cards.{prefix}.jsonl', [
        {'Card ID': f'CARD-{prefix}-001', 'Card Type': 'Rule', 'Concept Key': 'k',
         'Title': 'T', 'Content': 'C', 'Evidence Record IDs': [f'EVD-{prefix}-001']}])
    write_rows(tmp_path / f'evidence.{prefix}.jsonl', [
        {'Evidence ID': f'EVD-{prefix}-001', 'Evidence Mode': 'VERBATIM',
         'Original Text': text, 'Source': 'a.docx', 'Source Location': 'S'}])
    write_rows(tmp_path / f'coverage.{prefix}.jsonl', [
        {'Source Unit ID': unit_ids[0], 'Disposition': 'Card',
         'Card IDs': [f'CARD-{prefix}-001'], 'Evidence Record IDs': [f'EVD-{prefix}-001']},
        *({'Source Unit ID': unit, 'Disposition': 'Skip', 'Skip Reason': 'x',
           'Card IDs': [], 'Evidence Record IDs': []} for unit in unit_ids[1:])])
    return [str(tmp_path / f'{kind}.{prefix}.jsonl') for kind in ('cards', 'evidence', 'coverage')]


def merge(tmp_path, files, plan=None):
    cards = [f for f in files if '/cards.' in f]
    evidence = [f for f in files if '/evidence.' in f]
    coverage = [f for f in files if '/coverage.' in f]
    args = ['--cards', *cards, '--evidence', *evidence, '--coverage', *coverage,
            '--cards-output', str(tmp_path / 'm-cards.jsonl'),
            '--evidence-output', str(tmp_path / 'm-evidence.jsonl'),
            '--coverage-output', str(tmp_path / 'm-coverage.jsonl')]
    if plan:
        args += ['--plan', str(plan)]
    proc = run('merge_extraction_batches.py', *args, cwd=tmp_path)
    return proc, json.loads(proc.stdout)


def test_merge_rejoins_batches_and_refuses_an_unfinished_extraction(tmp_path):
    plan = plan_for(tmp_path, [('s1', 8), ('s2', 6)], max_units=10)
    files = []
    for batch in plan['batches']:
        files += batch_output(tmp_path, batch['batch_id'], batch['source_unit_ids'])

    proc, report = merge(tmp_path, files, plan=tmp_path / 'plan.json')
    assert proc.returncode == 0, proc.stdout
    assert report['status'] == 'PASS'
    assert report['coverage_rows'] == 14 and report['cards'] == len(plan['batches'])
    assert len(read_jsonl(tmp_path / 'm-coverage.jsonl')) == 14

    # One batch missing: the merge must say so rather than produce a short Step 1.
    partial = [f for f in files if plan['batches'][0]['batch_id'] in f]
    for stale in ('m-cards.jsonl', 'm-evidence.jsonl', 'm-coverage.jsonl'):
        (tmp_path / stale).unlink()
    proc, report = merge(tmp_path, partial, plan=tmp_path / 'plan.json')
    assert proc.returncode == 2 and report['status'] == 'FAIL'
    assert 'unfinished' in ' '.join(report['errors'])
    assert not (tmp_path / 'm-coverage.jsonl').exists(), 'a failed merge wrote output anyway'


@pytest.mark.parametrize('rows,expected', [
    # One placeholder ID naming two different records -- what two batches that
    # both mint EVD-TMP-001 produce.
    ([{'Evidence ID': 'EVD-TMP-001', 'Evidence Mode': 'VERBATIM', 'Original Text': 'one'},
      {'Evidence ID': 'EVD-TMP-001', 'Evidence Mode': 'VERBATIM', 'Original Text': 'two'}],
     'two different records'),
])
def test_merge_refuses_a_placeholder_id_collision(tmp_path, rows, expected):
    for index, row in enumerate(rows, 1):
        write_rows(tmp_path / f'evidence.B{index}.jsonl', [row])
    proc = run('merge_extraction_batches.py',
               '--evidence', str(tmp_path / 'evidence.B1.jsonl'), str(tmp_path / 'evidence.B2.jsonl'),
               '--evidence-output', str(tmp_path / 'out.jsonl'), cwd=tmp_path)
    assert proc.returncode == 2
    assert expected in json.loads(proc.stdout)['errors'][0]
    assert not (tmp_path / 'out.jsonl').exists()


def test_merge_refuses_two_dispositions_for_one_unit_and_dangling_citations(tmp_path):
    write_rows(tmp_path / 'coverage.B1.jsonl', [
        {'Source Unit ID': 'a::1', 'Disposition': 'Card', 'Card IDs': ['CARD-B1-001'],
         'Evidence Record IDs': []}])
    write_rows(tmp_path / 'coverage.B2.jsonl', [
        {'Source Unit ID': 'a::1', 'Disposition': 'Skip', 'Skip Reason': 'x',
         'Card IDs': [], 'Evidence Record IDs': []}])
    proc = run('merge_extraction_batches.py',
               '--coverage', str(tmp_path / 'coverage.B1.jsonl'), str(tmp_path / 'coverage.B2.jsonl'),
               '--coverage-output', str(tmp_path / 'out.jsonl'), cwd=tmp_path)
    assert proc.returncode == 2
    errors = ' '.join(json.loads(proc.stdout)['errors'])
    assert 'exactly one disposition' in errors
    # The surviving row cites a Card nobody merged, which is also a failure.
    assert 'unknown Card ID' in errors


def test_batch_size_comes_from_settings(tmp_path):
    from afc_card_runtime.config import load_settings
    configured = load_settings().get('extraction.max_units_per_batch')
    assert isinstance(configured, int) and configured > 0
    units = tmp_path / 'source-map.jsonl'
    source_map(units, [('s1', configured + 5)])
    proc = run('plan_extraction_batches.py', '--source-map', str(units),
               '--units-dir', str(tmp_path / 'b'), '-o', str(tmp_path / 'plan.json'),
               cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    plan = json.loads((tmp_path / 'plan.json').read_text(encoding='utf-8'))
    assert plan['max_units_per_batch'] == configured, (
        'the planner must take its bound from settings.yaml, not from a literal')
