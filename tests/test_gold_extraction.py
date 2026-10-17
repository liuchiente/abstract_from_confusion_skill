"""Does following the skills actually produce good knowledge?

Every other test in this suite checks files, documents and consistency. The spec
can be perfectly self-consistent and the extraction still wrong, and until now
nothing would have said so. The gold set measures a run against answers a person
wrote down instead of against itself.

Two halves. Step 0 is deterministic -- the parsers plus
build_context_candidates.py give the same source map every time -- so it is
asserted exactly and needs no model. Step 1 is model-authored, so what is
asserted is literal preservation, claim coverage, fabrication and accounting,
never wording; the reference extraction below stands in for a model's output so
the scorer itself is tested.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOLD = ROOT / 'gold' / 'afc-gold-v1'
IS_SOURCE_TREE = GOLD.is_dir() and (ROOT / 'skills').is_dir()
source_only = pytest.mark.skipif(not IS_SOURCE_TREE, reason='package-source layout only')

EXPECTED_STEP0 = json.loads((GOLD / 'expected-step0.json').read_text(encoding='utf-8')) \
    if IS_SOURCE_TREE else {}


def run_script(script, *args, cwd):
    proc = subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *args],
                          capture_output=True, text=True, cwd=cwd,
                          env={'AFC_HOME': str(ROOT), 'PATH': os.environ.get('PATH', '')})
    return proc


@pytest.fixture(scope='module')
def step0(tmp_path_factory):
    """Generate the fixtures and run Step 0 for real."""
    if not IS_SOURCE_TREE:
        pytest.skip('package-source layout only')
    base = tmp_path_factory.mktemp('gold')
    sources, work = base / 'sources', base / 'work'
    work.mkdir()
    gen = subprocess.run([sys.executable, str(GOLD / 'make_sources.py'), '--out', str(sources)],
                         capture_output=True, text=True)
    assert gen.returncode == 0, gen.stderr

    for script, name in (('parse_word.py', 'word'), ('parse_excel.py', 'excel'),
                         ('parse_text.py', 'text')):
        proc = run_script(script, str(sources), '-o', str(work / f'{name}.jsonl'),
                          '--structure-report', str(work / f'{name}-report.json'), cwd=base)
        assert proc.returncode == 0, f'{script}: {proc.stderr or proc.stdout}'

    proc = run_script('build_context_candidates.py',
                      str(work / 'word.jsonl'), str(work / 'excel.jsonl'),
                      str(work / 'text.jsonl'),
                      '--target-scope', EXPECTED_STEP0['target_scope'],
                      '--scope-root', str(sources),
                      '-o', str(work / 'source-map.jsonl'),
                      '--report', str(work / 'context-report.json'), cwd=base)
    assert proc.returncode == 0, proc.stderr or proc.stdout

    from afc_card_runtime.common import read_json, read_jsonl
    return {'base': base, 'sources': sources, 'work': work,
            'units': read_jsonl(work / 'source-map.jsonl'),
            'report': read_json(work / 'context-report.json')}


# --- Step 0: deterministic, asserted exactly ------------------------------

@source_only
def test_the_scope_metadata_file_is_not_a_source(step0):
    """afc-scope.md declares a boundary; it is not knowledge inside it."""
    ingested = [u['source_unit_id'] for u in step0['units']
                if u['source_unit_id'].startswith('afc-scope.md')]
    assert not ingested, (
        f'AFC\'s own scope file was parsed as source material: {ingested[:3]}. '
        'The inventory has always ignored it; the parsers must too.')


@source_only
def test_step0_selects_exactly_what_the_gold_set_expects(step0):
    units = step0['units']
    assert len(units) == EXPECTED_STEP0['source_units']['total']
    selected = [u for u in units if u.get('selected')]
    assert len(selected) == EXPECTED_STEP0['source_units']['selected']

    per_file = {}
    for unit in units:
        name = unit['source_unit_id'].split('::')[0]
        bucket = per_file.setdefault(name, {'units': 0, 'selected': 0})
        bucket['units'] += 1
        bucket['selected'] += bool(unit.get('selected'))
    assert per_file == EXPECTED_STEP0['per_file'], (
        'Step 0 selection changed. If that was intended, update '
        'gold/afc-gold-v1/expected-step0.json in the same change, and say why.')


@source_only
def test_the_scope_boundary_holds_and_the_required_units_survive(step0):
    selected = {u['source_unit_id'] for u in step0['units'] if u.get('selected')}
    missing = [u for u in EXPECTED_STEP0['must_be_selected'] if u not in selected]
    assert not missing, f'units carrying required knowledge were not selected: {missing}'
    leaked = [u for u in EXPECTED_STEP0['must_not_be_selected'] if u in selected]
    assert not leaked, (
        f'out-of-scope units were selected for a {EXPECTED_STEP0["target_scope"]} run: {leaked}')


@source_only
def test_the_structures_extraction_must_survive_are_present(step0):
    units = step0['units']
    counts = {
        'nested_table_units': sum(1 for u in units if u.get('is_nested_table')),
        'uncached_formula_units': sum(1 for u in units if u.get('has_uncached_formula')),
        'merged_header_inherited_rows': sum(1 for u in units if u.get('has_merged_inheritance')),
    }
    expected = {k: v for k, v in EXPECTED_STEP0['structure'].items() if k != 'comment'}
    assert counts == expected, (
        f'structural extraction changed: {counts} != {expected}. A parser that stops '
        'recursing into a nested table, drops a merged header, or invents a value for '
        'a formula cell changes these.')


@source_only
@pytest.mark.parametrize('limitation', EXPECTED_STEP0.get('known_limitations', []),
                         ids=lambda item: item['id'])
def test_a_known_limitation_still_behaves_as_recorded(step0, limitation):
    """Recorded, not endorsed.

    These are places where Step 0 does something a reviewer would argue with.
    Pinning them means a fix shows up as a deliberate expectation change rather
    than a silent shift, and the file says what to do when it flips.
    """
    check = limitation.get('check', 'selection')
    units = {u['source_unit_id']: u for u in step0['units']}
    if check == 'selection':
        selected = {uid for uid, u in units.items() if u.get('selected')}
        actual = {'selected' if unit in selected else 'unselected'
                  for unit in limitation['units']}
        expected = {limitation['current']}
    elif check == 'signal_types':
        actual = sorted({t for unit in limitation['units']
                         for t in units[unit].get('knowledge_signal_types') or []})
        expected = sorted(limitation['current'])
    elif check == 'report_field':
        actual = step0['report'].get(limitation['report_field'])
        expected = limitation['current']
    else:
        raise AssertionError(f'unknown check: {check}')
    assert actual == expected, (
        f"{limitation['id']}: recorded as {expected}, now {actual}. "
        f"{limitation['if_this_changes']}")


# --- Step 1: the scorer, exercised on a reference extraction --------------

UNIT_SPEC_RULE = 'cb_spec.docx::B000002'
UNIT_SPEC_DEF = 'cb_spec.docx::B000008'
UNIT_MSG = 'cb_spec.docx::B000004::T001::R0002'
UNIT_MSG2 = 'cb_spec.docx::B000004::T001::R0003'
UNIT_NESTED = 'cb_spec.docx::B000006::T002::R0002::C002::N01::T003::R0002'
UNIT_FIELD = 'cb_fields.xlsx::欄位定義::R000003'
UNIT_REVIEW = 'cb_process.md::TXT000006'


def reference_extraction():
    """What a correct Step 1 produces for the gold sources.

    Deliberately worded differently from the gold statements: the scorer must
    accept any wording that preserves the literals and covers the claims.
    """
    evidence = [
        {'Evidence ID': 'EVD-000001', 'Evidence Mode': 'VERBATIM+STRUCTURED',
         'Evidence Kind': 'Message', 'Original Text': 'Tải lên thất bại',
         'Original Error Message': 'Tải lên thất bại', 'Original Code': 'E102',
         'Original Max Length': '100', 'Source Language': 'vi',
         'Source': 'cb_spec.docx', 'Source Location': 'Table 1 / Row 2',
         'Source Unit IDs': [UNIT_MSG]},
        {'Evidence ID': 'EVD-000002', 'Evidence Mode': 'VERBATIM+STRUCTURED',
         'Evidence Kind': 'Message', 'Original Text': 'Số hợp đồng không hợp lệ',
         'Original Error Message': 'Số hợp đồng không hợp lệ', 'Original Code': 'E205',
         'Source Language': 'vi', 'Source': 'cb_spec.docx',
         'Source Location': 'Table 1 / Row 3', 'Source Unit IDs': [UNIT_MSG2]},
        {'Evidence ID': 'EVD-000003', 'Evidence Mode': 'VERBATIM',
         'Evidence Kind': 'Rule',
         'Original Text': 'CB 保單在生效日之前可以加買乘客險。生效之後是否仍可加買，'
                          '依加買期限判定；超過加買期限時系統不允許加買。',
         'Source': 'cb_spec.docx', 'Source Location': 'Block 2',
         'Source Unit IDs': [UNIT_SPEC_RULE]},
        {'Evidence ID': 'EVD-000004', 'Evidence Mode': 'VERBATIM',
         'Evidence Kind': 'Definition',
         'Original Text': '加買期限：保單生效後仍允許加買的期間，由商品設定決定。',
         'Source': 'cb_spec.docx', 'Source Location': 'Block 8',
         'Source Unit IDs': [UNIT_SPEC_DEF]},
        {'Evidence ID': 'EVD-000005', 'Evidence Mode': 'VERBATIM',
         'Evidence Kind': 'Rule', 'Original Text': '日結進行中 | 加買請求退回，顯示 E102',
         'Source': 'cb_spec.docx', 'Source Location': 'Table 2 / nested Table 3 / Row 2',
         'Source Unit IDs': [UNIT_NESTED]},
        {'Evidence ID': 'EVD-000006', 'Evidence Mode': 'STRUCTURED',
         'Evidence Kind': 'Field', 'Original Name': '被保人姓名',
         'Original Required': 'Y', 'Original Max Length': '60',
         'Source': 'cb_fields.xlsx', 'Source Location': '欄位定義 / Row 3',
         'Source Unit IDs': [UNIT_FIELD]},
        {'Evidence ID': 'EVD-000007', 'Evidence Mode': 'VERBATIM',
         'Evidence Kind': 'Process',
         'Original Text': '申請建立後需由核保人員覆核，覆核不通過時退回業務員補件。',
         'Source': 'cb_process.md', 'Source Location': 'Section 2',
         'Source Unit IDs': [UNIT_REVIEW]},
    ]
    cards = [
        {'Card ID': 'CARD-000001', 'Card Type': 'Rule',
         'Concept Key': 'cb-add-before-effective-date',
         'Title': '生效日前允許加買乘客險',
         'Content': 'CB 保單在生效日之前可以加買乘客險。', 'Scope': 'CB',
         'Evidence Record IDs': ['EVD-000003']},
        {'Card ID': 'CARD-000002', 'Card Type': 'Rule',
         'Concept Key': 'cb-add-blocked-after-deadline',
         'Title': '超過加買期限不允許加買',
         'Content': '已生效且超過加買期限時，系統不允許加買。', 'Scope': 'CB',
         'Evidence Record IDs': ['EVD-000003']},
        {'Card ID': 'CARD-000003', 'Card Type': 'Definition',
         'Concept Key': 'cb-deadline-is-product-configured',
         'Title': '加買期限的定義',
         'Content': '加買期限是保單生效後仍允許加買的期間，由商品設定決定。', 'Scope': 'CB',
         'Evidence Record IDs': ['EVD-000004']},
        {'Card ID': 'CARD-000004', 'Card Type': 'Exception',
         'Concept Key': 'cb-upload-failure-message',
         'Title': '上傳失敗的訊息與代碼',
         'Content': '上傳失敗時顯示來源訊息並記錄 E102。', 'Scope': 'CB',
         'Evidence Record IDs': ['EVD-000001']},
        {'Card ID': 'CARD-000005', 'Card Type': 'Condition',
         'Concept Key': 'cb-batch-window-rejects',
         'Title': '日結進行中退回加買請求',
         'Content': '批次日結進行中時，加買請求退回並顯示 E102。', 'Scope': 'CB',
         'Evidence Record IDs': ['EVD-000005']},
        {'Card ID': 'CARD-000006', 'Card Type': 'Field',
         'Concept Key': 'cb-insured-name-required',
         'Title': '被保人姓名為必填',
         'Content': '被保人姓名必填，長度上限 60。', 'Scope': 'CB',
         'Evidence Record IDs': ['EVD-000006']},
        {'Card ID': 'CARD-000007', 'Card Type': 'Process',
         'Concept Key': 'cb-process-requires-underwriting-review',
         'Title': '加買申請需核保覆核',
         'Content': '申請建立後由核保人員覆核，不通過則退回業務員補件。', 'Scope': 'CB',
         'Evidence Record IDs': ['EVD-000007']},
    ]
    return cards, evidence


def score(tmp_path, cards, evidence, coverage=None, source_map=None):
    def dump(name, rows):
        path = tmp_path / name
        path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows),
                        encoding='utf-8')
        return str(path)

    args = ['--gold', str(GOLD),
            '--cards', dump('cards.jsonl', cards),
            '--evidence', dump('evidence.jsonl', evidence)]
    if coverage is not None:
        args += ['--coverage', dump('coverage.jsonl', coverage)]
    if source_map is not None:
        args += ['--source-map', dump('source-map.jsonl', source_map)]
    proc = run_script('score_extraction_gold.py', *args, cwd=tmp_path)
    return proc, json.loads(proc.stdout)


@source_only
def test_a_correct_extraction_passes_whatever_its_wording(tmp_path):
    cards, evidence = reference_extraction()
    proc, report = score(tmp_path, cards, evidence)
    assert report['status'] == 'PASS', json.dumps(report['failures'], ensure_ascii=False)
    assert report['literal_preservation']['rate'] == 1.0
    assert report['claim_coverage']['rate'] == 1.0
    assert report['fabrication']['count'] == 0
    assert proc.returncode == 0


@source_only
def test_an_altered_literal_fails(tmp_path):
    """Translating a Vietnamese message into Chinese is a fidelity defect."""
    cards, evidence = reference_extraction()
    for record in evidence:
        if record['Evidence ID'] == 'EVD-000001':
            record['Original Text'] = '上傳失敗'
            record['Original Error Message'] = '上傳失敗'
    _, report = score(tmp_path, cards, evidence)
    assert report['status'] == 'FAIL'
    assert 'Tải lên thất bại' in report['literal_preservation']['missing']


@source_only
def test_a_missing_claim_fails(tmp_path):
    """The claim that exists only in a table nested inside a table cell."""
    cards, evidence = reference_extraction()
    cards = [c for c in cards if c['Concept Key'] != 'cb-batch-window-rejects']
    _, report = score(tmp_path, cards, evidence)
    assert report['status'] == 'FAIL'
    assert 'cb-batch-window-rejects' in report['claim_coverage']['uncovered']


@source_only
def test_an_invented_fact_fails(tmp_path):
    """No source states a number of days; a Card naming one has invented it."""
    cards, evidence = reference_extraction()
    cards[1]['Content'] = '保單生效後 30 天內仍可加買，超過則不允許。'
    _, report = score(tmp_path, cards, evidence)
    assert report['status'] == 'FAIL'
    assert report['fabrication']['count'] == 1
    assert report['fabrication']['found'][0]['text'] == '30 天'


@source_only
def test_a_fact_from_outside_the_scope_fails(tmp_path):
    """cb_negation.md is currently selected, so its facts are reachable."""
    cards, evidence = reference_extraction()
    cards[0]['Content'] += ' 自負額為 3000 元。'
    _, report = score(tmp_path, cards, evidence)
    assert report['status'] == 'FAIL'
    assert any(f['text'] == '3000' for f in report['fabrication']['found'])


@source_only
def test_an_unassessed_selected_unit_fails(tmp_path, step0):
    cards, evidence = reference_extraction()
    units = step0['units']
    selected = [u for u in units if u.get('selected')]
    coverage = [{'Source Unit ID': u['source_unit_id'], 'Disposition': 'Skip',
                 'Skip Reason': 'x', 'Card IDs': [], 'Evidence Record IDs': []}
                for u in selected[:-2]]
    _, report = score(tmp_path, cards, evidence, coverage=coverage, source_map=units)
    assert report['status'] == 'FAIL'
    assert len(report['accounting']['unaccounted']) == 2


@source_only
def test_the_floors_come_from_settings():
    from afc_card_runtime.config import load_settings
    settings = load_settings(home=ROOT)
    assert settings.get('gold.min_literal_preservation') == 1.0, (
        'a named source string must be preserved exactly; there is no sensible '
        'floor below 1.0')
    assert 0 < settings.get('gold.min_claim_coverage') <= 1.0


# --- change 002: an actionable miss is reported as one --------------------

@source_only
def test_a_prose_miss_in_an_in_scope_file_is_actionable(step0):
    """One flag was answering two questions.

    `boundary_membership` gates auto-recovery and knows three structures: a
    table with a selected row, a contiguous Excel segment, a PDF page. A
    paragraph is none of them, so no prose unit was ever "within a boundary"
    and every signal miss in a Word or Markdown source was reported under
    `outside_boundary`, which AGENTS.md calls not a finding.
    """
    expected = EXPECTED_STEP0['expected_report']
    report = step0['report']
    assert report['signal_unselected_within_boundary'] == \
        expected['signal_unselected_within_boundary']
    assert report['signal_unselected_outside_boundary'] == \
        expected['signal_unselected_outside_boundary']

    misses = [u for u in step0['units']
              if u.get('knowledge_relevance_candidate') and not u.get('selected')]
    actionable = [u['source_unit_id'] for u in misses
                  if u.get('signal_within_scope_boundary')]
    assert actionable == expected['actionable_source_unit_ids']


@source_only
def test_the_two_boundaries_are_distinct(step0):
    """The point of the change: a unit can be reportable without being recoverable."""
    diverging = [u for u in step0['units']
                 if u.get('signal_within_scope_boundary')
                 and not u.get('signal_within_selected_boundary')]
    assert diverging, (
        'no unit distinguishes the scope boundary from the structural one, so the '
        'reporting fix has no effect and one of the two tests is wrong')
    assert all(not u.get('selected') for u in diverging)


@source_only
def test_a_miss_in_an_out_of_scope_file_is_not_a_finding(step0):
    """other_product.md sits in a CB directory and is entirely about another product."""
    out_of_scope = [u for u in step0['units']
                    if u['source_unit_id'].startswith('other_product.md')]
    assert out_of_scope, 'the out-of-scope fixture produced no units'
    assert all(not u.get('signal_within_scope_boundary') for u in out_of_scope), (
        'a file with no selected unit has not shown it belongs to the active Scope; '
        'a miss in it is a boundary decision, not a gap')


@source_only
def test_recovery_still_requires_a_structural_boundary(step0):
    """Change 002 must not have altered what gets selected."""
    recovered = [u for u in step0['units']
                 if 'Recovered:KnowledgeSignalWithinSelectedBoundary'
                 in (u.get('selection_reasons') or u.get('context_match_reasons') or [])]
    assert not recovered, (
        'a unit was auto-recovered in the gold run. Selection changes extraction '
        'output; that belongs in its own change, not in a reporting fix.')
    per_file = {}
    for unit in step0['units']:
        name = unit['source_unit_id'].split('::')[0]
        bucket = per_file.setdefault(name, {'units': 0, 'selected': 0})
        bucket['units'] += 1
        bucket['selected'] += bool(unit.get('selected'))
    assert per_file == EXPECTED_STEP0['per_file']


@source_only
def test_the_validator_agrees_with_the_run_report(step0, tmp_path):
    """Two scripts classify the same thing; they must not disagree."""
    out = tmp_path / 'audit.json'
    proc = run_script('validate_context_selection.py',
                      '--source-map', str(step0['work'] / 'source-map.jsonl'),
                      '--json-output', str(out), cwd=step0['base'])
    audit = json.loads(proc.stdout)
    expected = EXPECTED_STEP0['expected_report']
    assert audit['signal_unselected_within_boundary'] == \
        expected['signal_unselected_within_boundary']
    assert audit['signal_unselected_outside_boundary'] == \
        expected['signal_unselected_outside_boundary']
    assert [x['source_unit_id'] for x in audit['actionable_source_unit_ids']] == \
        expected['actionable_source_unit_ids']


@source_only
def test_a_legacy_source_map_without_the_annotation_stays_conservative(tmp_path):
    """An old source map carries neither flag; the audit must not pass silently."""
    legacy = tmp_path / 'source-map.jsonl'
    legacy.write_text(json.dumps({
        'source_unit_id': 'old.docx::B000001', 'kind': 'paragraph', 'selected': False,
        'knowledge_relevance_candidate': True, 'knowledge_signal_types': ['Literal Knowledge'],
        'value': 'Tải lên thất bại',
    }, ensure_ascii=False) + '\n', encoding='utf-8')
    proc = run_script('validate_context_selection.py', '--source-map', str(legacy),
                      cwd=tmp_path)
    audit = json.loads(proc.stdout)
    assert audit['signal_unselected_within_boundary'] == 1, (
        'a source map with no boundary annotation must be treated as in-boundary, '
        'so an old run is reviewed rather than quietly passed')
