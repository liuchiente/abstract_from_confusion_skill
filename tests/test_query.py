"""Retrieval regression tests over a real SQLite FTS index."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from afc_card_runtime.common import normalize_text  # noqa: E402


def run(args, expect_ok=True):
    proc = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=ROOT)
    if expect_ok:
        assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def write_jsonl(path, rows):
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')


CARDS = [
    {'Card ID': 'CARD-000001', 'Card Type': 'Rule', 'Concept Key': 'ca-add-cover-failure',
     'Title': 'CA 無法加買時的處理',
     'Content': '當保單已生效且超過加買期限時，系統不允許加買並顯示錯誤訊息。',
     'Scope': 'CA', 'Context': 'CTX-001', 'Source': 'spec.docx',
     'Source Location': 'Table 1 / Row 2', 'Evidence Record IDs': ['EVD-000001', 'EVD-000002']},
    {'Card ID': 'CARD-000002', 'Card Type': 'Field', 'Concept Key': 'policy-no',
     'Title': '保單號碼欄位', 'Content': '確認頁顯示保單號碼，為唯讀文字欄位。',
     'Scope': 'CA', 'Context': 'CTX-002', 'Source': 'spec.xlsx',
     'Source Location': 'Spec / Row 3', 'Evidence Record IDs': ['EVD-000003']},
    {'Card ID': 'CARD-000003', 'Card Type': 'Rule', 'Concept Key': 'confirm-back',
     'Title': '確認頁返回保留已輸入資料',
     'Content': '使用者在確認頁按下返回時，系統返回上一頁並保留已輸入資料。',
     'Scope': 'CA', 'Context': 'CTX-002', 'Source': 'spec.docx',
     'Source Location': 'Table 2 / Row 1', 'Evidence Record IDs': ['EVD-000004']},
]
EVIDENCE = [
    {'Evidence ID': 'EVD-000001', 'Evidence Mode': 'VERBATIM', 'Evidence Kind': 'Message',
     'Original Text': 'Tải lên thất bại', 'Source Language': 'vi', 'Source': 'spec.docx',
     'Source Location': 'Table 1 / Row 2 / Cell 3', 'Card IDs': ['CARD-000001']},
    {'Evidence ID': 'EVD-000002', 'Evidence Mode': 'VERBATIM+STRUCTURED', 'Evidence Kind': 'Message',
     'Original Text': '加買失敗', 'Source Language': 'zh-TW', 'Original Error Message': '加買失敗',
     'Original Code': 'E102', 'Source': 'spec.docx',
     'Source Location': 'Table 1 / Row 2 / Cell 4', 'Card IDs': ['CARD-000001']},
    {'Evidence ID': 'EVD-000003', 'Evidence Mode': 'STRUCTURED', 'Evidence Kind': 'ComponentType',
     'Original Text': 'textbox', 'Original Component Type': 'textbox', 'Original Max Length': '20',
     'Source': 'spec.xlsx', 'Source Location': 'Spec / Row 3', 'Card IDs': ['CARD-000002']},
    {'Evidence ID': 'EVD-000004', 'Evidence Mode': 'VERBATIM', 'Evidence Kind': 'ButtonText',
     'Original Text': 'Sửa đơn và gửi lại', 'Source Language': 'vi', 'Source': 'spec.docx',
     'Source Location': 'Table 2 / Row 1', 'Card IDs': ['CARD-000003']},
]
BOXES = [
    {'Box ID': 'BOX-000001', 'Box Type': 'Business', 'Name': 'CA', 'Canonical Key': 'ca',
     'Aliases': ['CA'], 'Scope Hints': ['CA'], 'Status': 'Confirmed'},
    {'Box ID': 'BOX-000002', 'Box Type': 'Screen', 'Name': '確認頁',
     'Canonical Key': 'confirmation-page', 'Aliases': ['確認頁'], 'Status': 'Confirmed'},
    {'Box ID': 'BOX-000003', 'Box Type': 'Function', 'Name': 'Back', 'Canonical Key': 'back',
     'Aliases': ['Back', '返回'], 'Status': 'Confirmed'},
]
MEMBERSHIPS = [
    {'Membership ID': 'MEM-000001', 'Card ID': 'CARD-000003', 'Box ID': 'BOX-000002',
     'Membership Type': 'valid_in', 'Membership Basis': 'Direct Source', 'Evidence': 'h', 'Status': 'Confirmed'},
    {'Membership ID': 'MEM-000002', 'Card ID': 'CARD-000003', 'Box ID': 'BOX-000003',
     'Membership Type': 'uses_function', 'Membership Basis': 'Direct Source', 'Evidence': 'h', 'Status': 'Confirmed'},
    {'Membership ID': 'MEM-000003', 'Card ID': 'CARD-000002', 'Box ID': 'BOX-000002',
     'Membership Type': 'valid_in', 'Membership Basis': 'Direct Source', 'Evidence': 'h', 'Status': 'Confirmed'},
]


@pytest.fixture(scope='module')
def index(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('q')
    paths = {}
    for name, rows in (('cards', CARDS), ('evidence', EVIDENCE),
                       ('boxes', BOXES), ('mem', MEMBERSHIPS)):
        paths[name] = tmp / f'{name}.jsonl'
        write_jsonl(paths[name], rows)
    paths['boxlinks'] = tmp / 'boxlinks.jsonl'
    paths['boxlinks'].write_text('', encoding='utf-8')
    db = tmp / 'afc.db'
    run(['scripts/ensure_query_index.py', '--cards', str(paths['cards']),
         '--evidence', str(paths['evidence']), '--context-map', 'config/business-contexts.yaml',
         '--boxes', str(paths['boxes']), '--box-memberships', str(paths['mem']),
         '--box-links', str(paths['boxlinks']), '--db', str(db)])
    return db, tmp


def query(index, q, extra=()):
    db, tmp = index
    out = tmp / 'out.json'
    run(['scripts/query_fast.py', '--db', str(db), '--query', q, '-o', str(out), *extra])
    return json.loads(out.read_text(encoding='utf-8'))


def card_ids(result):
    return [c['record']['Card ID'] for c in result.get('card', {}).get('direct', [])]


def evidence_ids(result):
    return [e['record']['Evidence ID'] for e in result.get('evidence', {}).get('direct', [])]


def test_short_chinese_query_retrieves(index):
    # v0.4.1 returned nothing here: the index held 「加買失敗」 as one token.
    result = query(index, '加買失敗')
    assert 'CARD-000001' in card_ids(result)
    assert 'EVD-000002' in evidence_ids(result)


def test_a_named_source_language_is_answered_in_that_language(index):
    result = query(index, '無法加買時原始的越文錯誤訊息是什麼？')
    assert result['query_target_mode'] == 'literal'
    assert result['requested_source_languages'] == ['vi']
    assert evidence_ids(result) == ['EVD-000001']
    assert result['evidence']['language_filter_applied'] is True


def test_a_vietnamese_question_reaches_the_evidence_layer(index):
    result = query(index, 'Thông báo lỗi khi tải lên thất bại là gì?')
    assert result['query_target_mode'] == 'literal'
    assert 'EVD-000001' in evidence_ids(result)


def test_a_structured_fact_question_ranks_the_source_value_first(index):
    result = query(index, '保單號碼的原始元件類型是什麼？')
    assert result['query_target_mode'] == 'structured_fact'
    assert evidence_ids(result)[0] == 'EVD-000003'
    assert result['evidence']['recovery_stage_used'] == 'retrieved_cards'


def test_explicit_boxes_become_hard_boundaries(index):
    result = query(index, '確認頁 Back 的行為是什麼？')
    names = {b['name'] for b in result['hard_boundary_boxes']}
    assert {'確認頁', 'Back'} <= names
    assert card_ids(result) == ['CARD-000003']


def test_business_context_resolves_to_scopes(index):
    result = query(index, '車險的加買規則是什麼？')
    assert result['detected_business_contexts'] == ['車險']
    assert set(result['resolved_scopes']) == {'CA', 'CB'}


def test_retrieval_limits_are_reported_with_their_source(index):
    result = query(index, '加買')
    limits = result['retrieval_limits']
    assert limits['top_k'] == 12 and limits['max_box_hops'] == 1
    assert 'settings.yaml' in limits['source']


def test_a_bare_boolean_operator_does_not_break_the_query(index):
    result = query(index, '加買 OR 失敗')
    assert 'or' not in result['terms']
    assert card_ids(result)


def test_index_is_reused_when_nothing_changed(index):
    db, tmp = index
    proc = run(['scripts/ensure_query_index.py', '--cards', str(tmp / 'cards.jsonl'),
                '--evidence', str(tmp / 'evidence.jsonl'),
                '--context-map', 'config/business-contexts.yaml',
                '--boxes', str(tmp / 'boxes.jsonl'), '--box-memberships', str(tmp / 'mem.jsonl'),
                '--box-links', str(tmp / 'boxlinks.jsonl'), '--db', str(db)])
    assert json.loads(proc.stdout.strip().splitlines()[-1])['status'] == 'fresh'


def test_a_stale_tokenizer_forces_a_rebuild(index):
    import sqlite3
    db, tmp = index
    con = sqlite3.connect(db)
    con.execute("UPDATE meta SET value='\"1\"' WHERE key='tokenizer_version'")
    con.commit()
    con.close()
    proc = run(['scripts/ensure_query_index.py', '--cards', str(tmp / 'cards.jsonl'),
                '--evidence', str(tmp / 'evidence.jsonl'),
                '--context-map', 'config/business-contexts.yaml',
                '--boxes', str(tmp / 'boxes.jsonl'), '--box-memberships', str(tmp / 'mem.jsonl'),
                '--box-links', str(tmp / 'boxlinks.jsonl'), '--db', str(db)])
    last = json.loads(proc.stdout.strip().splitlines()[-1])
    assert last['status'] == 'rebuilt'
    assert any('tokenizer_version' in r for r in last['rebuild_reasons'])


# --- benchmark runner ----------------------------------------------------

BENCH_CASES = """
queries:
  - id: B001-short-cjk
    query: 加買失敗
    expect:
      min_cards: 1
      min_evidence: 1
  - id: B002-named-language
    query: 無法加買時原始的越文錯誤訊息是什麼？
    expected_resolution:
      target_mode: literal
      source_languages: [vi]
    expect:
      top_evidence: EVD-000001
  - id: B003-hard-box
    query: CA 確認頁 Back 的行為是什麼？
    expected_resolution:
      scopes: [CA]
      boxes:
        - type: Screen
          name: 確認頁
    expect:
      top_card: CARD-000003
      max_product_leakage: 0
"""


def test_benchmark_cases_are_executed_and_pass(index):
    db, tmp = index
    cases = tmp / 'cases.yaml'
    cases.write_text(BENCH_CASES, encoding='utf-8')
    out = tmp / 'bench.json'
    run(['scripts/run_query_benchmark.py', '--db', str(db), '--cases', str(cases),
         '-o', str(out), '--update-baseline', str(tmp / 'baseline.json')])
    report = json.loads(out.read_text(encoding='utf-8'))
    assert report['status'] == 'PASS'
    assert report['total'] == report['passed'] == 3


def test_a_regression_against_the_baseline_fails_the_benchmark(index):
    db, tmp = index
    cases = tmp / 'cases.yaml'
    # Same ids, but B001 now expects something the index cannot deliver.
    cases.write_text(BENCH_CASES.replace('min_cards: 1', 'min_cards: 99'), encoding='utf-8')
    out = tmp / 'bench2.json'
    proc = run(['scripts/run_query_benchmark.py', '--db', str(db), '--cases', str(cases),
                '-o', str(out), '--baseline', str(tmp / 'baseline.json')], expect_ok=False)
    assert proc.returncode != 0
    report = json.loads(out.read_text(encoding='utf-8'))
    assert report['status'] == 'FAIL'
    regressed = [r['id'] for r in report['baseline_comparison']['regressions']]
    assert 'B001-short-cjk' in regressed


def test_shipped_example_cases_parse_and_run(index):
    db, tmp = index
    out = tmp / 'bench3.json'
    # The shipped example set may not all pass against this tiny fixture index,
    # but every case must be runnable: a case that errors is a benchmark defect.
    run(['scripts/run_query_benchmark.py', '--db', str(db),
         '--cases', 'config/query-cases.example.yaml', '-o', str(out)], expect_ok=False)
    report = json.loads(out.read_text(encoding='utf-8'))
    assert report['errored'] == 0
    assert report['total'] == 10


def test_a_named_language_is_exhausted_before_any_unfiltered_fallback(index):
    # 'message' appears in a Chinese header row, so an unfiltered text search
    # would answer a Vietnamese-language request with a Chinese record.
    result = query(index, 'Vietnamese message 原文')
    assert result['requested_source_languages'] == ['vi']
    ev = result['evidence']
    assert ev['language_filter_applied'] is True
    assert ev['recovery_stage_used'].endswith('language_filtered') or \
        ev['recovery_stage_used'] == 'language_scoped_evidence'
    langs = {normalize_text(e['record'].get('Source Language')) for e in ev['direct']}
    assert langs == {'vi'}, f'expected only Vietnamese evidence, got {langs}'


def test_no_language_request_leaves_ranking_to_the_text_search(index):
    result = query(index, '無法加買時的原始錯誤訊息是什麼？')
    assert result['requested_source_languages'] == []
    assert result['evidence']['recovery_stage_used'] == 'text_search'
    assert result['evidence']['language_filter_applied'] is False
