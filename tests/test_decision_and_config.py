"""Decision-gate, config and signal-precision tests."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from afc_card_runtime.config import DEFAULTS, load_settings  # noqa: E402


def run(args, expect_ok=True):
    proc = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=ROOT)
    if expect_ok:
        assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def write_jsonl(path, rows):
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')


def health(tmp_path, overall='REVIEW_RECOMMENDED', route='RUN_HEALTH_CHECKS', saturation=None):
    obj = {
        'health_schema_version': '2.0', 'overall_status': overall, 'primary_loop_route': route,
        'metrics': {'saturation_miss_rate': saturation},
        'metric_states': {'saturation': 'UNVERIFIED_SAMPLE'},
        'review_samples': {'saturation': {'gate': 'UNVERIFIED_SAMPLE', 'sample_count': None}},
        'dispositions': {'Card': 10, 'Skip': 0, 'Review': 0, 'Unaccounted': 0},
        'selected_source_units': 10, 'card_count': 10, 'recommendations': [],
    }
    p = tmp_path / f'health-{overall}-{saturation}.json'
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')
    return p


# --- decision gate --------------------------------------------------------

def test_ready_health_needs_no_decision(tmp_path):
    h = health(tmp_path, overall='READY', route='READY_FOR_LINKS')
    out = json.loads(run(['scripts/record_decision.py', 'verify', '--health', str(h),
                          '--decision', str(tmp_path / 'none.json')]).stdout)
    assert out['status'] == 'OK'
    assert out['decision_required'] is False


def test_non_ready_health_without_a_decision_blocks(tmp_path):
    h = health(tmp_path)
    proc = run(['scripts/record_decision.py', 'verify', '--health', str(h),
                '--decision', str(tmp_path / 'none.json')], expect_ok=False)
    assert proc.returncode != 0
    assert json.loads(proc.stdout)['status'] == 'MISSING'


def test_a_recorded_continuing_decision_unblocks(tmp_path):
    h = health(tmp_path)
    d = tmp_path / 'decision.json'
    run(['scripts/record_decision.py', 'record', '--health', str(h), '--decision', str(d),
         '--route', 'ACCEPT_REVIEW_ITEMS', '--decided-by', 'PM: test', '--rationale', 'smoke run'])
    out = json.loads(run(['scripts/record_decision.py', 'verify', '--health', str(h),
                          '--decision', str(d)]).stdout)
    assert out['status'] == 'OK' and out['chosen_route'] == 'ACCEPT_REVIEW_ITEMS'


def test_a_decision_goes_stale_when_health_changes(tmp_path):
    h1 = health(tmp_path, saturation=0.0)
    d = tmp_path / 'decision.json'
    run(['scripts/record_decision.py', 'record', '--health', str(h1), '--decision', str(d),
         '--route', 'ACCEPT_REVIEW_ITEMS', '--decided-by', 'PM: test'])
    h2 = health(tmp_path, saturation=0.11)
    proc = run(['scripts/record_decision.py', 'verify', '--health', str(h2),
                '--decision', str(d)], expect_ok=False)
    assert json.loads(proc.stdout)['status'] == 'STALE'


def test_a_looping_route_does_not_unblock_step_2(tmp_path):
    h = health(tmp_path)
    d = tmp_path / 'decision.json'
    run(['scripts/record_decision.py', 'record', '--health', str(h), '--decision', str(d),
         '--route', 'RETURN_TO_CONTEXT', '--decided-by', 'SA'])
    proc = run(['scripts/record_decision.py', 'verify', '--health', str(h),
                '--decision', str(d)], expect_ok=False)
    assert json.loads(proc.stdout)['status'] == 'BLOCKED'


# --- config ---------------------------------------------------------------

def test_settings_is_actually_read():
    s = load_settings()
    assert s.path is not None and s.path.name == 'settings.yaml'
    assert s.query('top_k') == DEFAULTS['query']['top_k']


def test_legacy_flat_keys_still_work(tmp_path):
    cfg = tmp_path / 'settings.yaml'
    cfg.write_text('query_top_k: 7\ncontext_neighbor_window: 9\n', encoding='utf-8')
    s = load_settings(path=cfg, home=ROOT, use_cache=False)
    assert s.query('top_k') == 7
    assert s.get('context_fallback_block_window') == 9
    assert 'query_top_k' in s.migrated_legacy_keys


def test_every_threshold_has_exactly_one_home():
    s = load_settings()
    for key in ('saturation_green_lt', 'min_sample_for_rate_grading'):
        assert s.card_health(key) == s.get(f'card_health.{key}')


# --- Step 0 signal precision ---------------------------------------------

def test_generic_words_in_content_do_not_create_a_literal_candidate(tmp_path):
    parsed = tmp_path / 'parsed.jsonl'
    write_jsonl(parsed, [
        {'source_unit_id': 's::Spec::R000001', 'kind': 'sheet-row', 'sheet': 'Spec', 'row': 1,
         'value': '商品代號 CA | Error Message | Component Type'},
        {'source_unit_id': 's::Spec::R000002', 'kind': 'sheet-row', 'sheet': 'Spec', 'row': 2,
         'value': '保單號碼 | Tải lên thất bại | textbox'},
        {'source_unit_id': 's::Other::R000020', 'kind': 'sheet-row', 'sheet': 'Other', 'row': 20,
         'value': '傷害險：若上傳失敗請洽業務，error 狀況請回報，label 與 code 說明見附件'},
    ])
    out = tmp_path / 'map.jsonl'
    run(['scripts/build_context_candidates.py', str(parsed), '--anchors', 'CA',
         '-o', str(out), '--report', str(tmp_path / 'rep.json')])
    rows = {r['source_unit_id']: r for r in
            (json.loads(l) for l in out.read_text(encoding='utf-8').splitlines() if l.strip())}
    prose = rows['s::Other::R000020']
    assert prose['knowledge_signal_types'] == [], 'generic words must not select a content row'
    # Recall is preserved: the in-scope row still inherits its header's signals.
    in_scope = rows['s::Spec::R000002']
    assert 'Literal Knowledge' in in_scope['knowledge_signal_types']
    assert 'Header Inherited' in in_scope['knowledge_signal_basis']


def test_out_of_boundary_signals_do_not_raise_review(tmp_path):
    parsed = tmp_path / 'parsed.jsonl'
    write_jsonl(parsed, [
        {'source_unit_id': 's::Spec::R000001', 'kind': 'sheet-row', 'sheet': 'Spec', 'row': 1,
         'value': '商品代號 CA | Error Message'},
        {'source_unit_id': 's::Spec::R000002', 'kind': 'sheet-row', 'sheet': 'Spec', 'row': 2,
         'value': '保單號碼 | 加買失敗'},
        {'source_unit_id': 's::Other::R000030', 'kind': 'sheet-row', 'sheet': 'Other', 'row': 30,
         'value': '旅遊險 | Error Message | Max Length'},
    ])
    out = tmp_path / 'map.jsonl'
    run(['scripts/build_context_candidates.py', str(parsed), '--anchors', 'CA',
         '-o', str(out), '--report', str(tmp_path / 'rep.json')])
    proc = run(['scripts/validate_context_selection.py', '--source-map', str(out)])
    audit = json.loads(proc.stdout)
    assert audit['signal_unselected_outside_boundary'] >= 1
    assert audit['signal_unselected_within_boundary'] == 0
    assert audit['status'] == 'PASS', 'an out-of-scope signal is not a finding'


def test_a_missing_signal_file_warns_instead_of_silently_passing(tmp_path):
    parsed = tmp_path / 'parsed.jsonl'
    write_jsonl(parsed, [{'source_unit_id': 's::Spec::R000001', 'kind': 'sheet-row',
                          'sheet': 'Spec', 'row': 1, 'value': 'CA | Error Message'}])
    proc = run(['scripts/build_context_candidates.py', str(parsed), '--anchors', 'CA',
                '-o', str(tmp_path / 'map.jsonl'), '--signals', str(tmp_path / 'nope.yaml')])
    assert 'WARNING' in proc.stderr and 'signal recall is disabled' in proc.stderr
