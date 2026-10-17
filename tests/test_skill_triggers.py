"""Does a request actually reach the skill it should?

Skill descriptions were rewritten to carry the words a user types and to name
the sibling that owns the neighbouring work. That was an assumption about model
behaviour, and this package's rule is that a rate is computed from recorded
observations rather than self-reported. These tests cover the part that can be
checked without a model: that the case set is complete, that every case's
wording can plausibly reach its skill, and that the scorer computes what it
claims.
"""
from pathlib import Path
import json
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES_FILE = ROOT / 'config' / 'skill-trigger-cases.yaml'
IS_SOURCE_TREE = (ROOT / 'skills').is_dir() and CASES_FILE.is_file()
source_only = pytest.mark.skipif(not IS_SOURCE_TREE, reason='package-source layout only')

CASES = (yaml.safe_load(CASES_FILE.read_text(encoding='utf-8')) or {}).get('cases', []) \
    if IS_SOURCE_TREE else []
SKILLS = sorted(p.parent.name for p in (ROOT / 'skills').glob('*/SKILL.md')) \
    if IS_SOURCE_TREE else []


def run(*args):
    return subprocess.run([sys.executable, str(ROOT / 'scripts' / 'score_skill_triggers.py'),
                           *args], capture_output=True, text=True, cwd=ROOT,
                          env={'AFC_HOME': str(ROOT), 'PATH': ''})


@source_only
def test_every_skill_is_the_answer_to_at_least_one_case():
    expected = {c['expect'] for c in CASES}
    missing = sorted(set(SKILLS) - expected)
    assert not missing, (
        f'no trigger case expects: {missing}. An unmeasured skill is one whose '
        'description nobody has tested.')
    unknown = sorted(expected - set(SKILLS))
    assert not unknown, f'cases expect skills that do not exist: {unknown}'


@source_only
def test_the_ambiguous_pairs_are_covered():
    """The overlaps that actually caused mis-selection need cases, not the easy ones."""
    pairs = {(c['expect'], c.get('confusable_with')) for c in CASES}
    for expect, confusable in (('afc-discuss', 'afc-query'), ('afc-query', 'afc-discuss'),
                               ('afc-update', 'afc-publish'), ('afc-publish', 'afc-update'),
                               ('afc-cards', 'afc-context'), ('afc-links', 'afc-boxes')):
        assert (expect, confusable) in pairs, (
            f'no case checks that {expect} is not mistaken for {confusable}')


@source_only
def test_the_case_set_is_bilingual():
    cjk = sum(1 for c in CASES if any('一' <= ch <= '鿿' for ch in c['request']))
    assert cjk >= len(CASES) // 3, 'too few Chinese requests for a team that works in Chinese'
    assert len(CASES) - cjk >= 5, 'too few English requests'


@source_only
def test_every_case_can_plausibly_reach_its_skill():
    """The lexical pre-check, as a ratchet on the descriptions.

    A request whose wording has nothing in common with the description it is
    meant to reach is a predictable mis-trigger. A case made only of
    subject-matter words declares `lexical_anchor: false`, since a real product
    question shares no vocabulary with any skill description.
    """
    proc = run('--lexical')
    report = json.loads(proc.stdout)
    assert not report['cases_with_no_anchor'], (
        'requests with no anchor in their skill\'s description: '
        f"{report['cases_with_no_anchor']}. Add the words a user types to that "
        'description, or mark the case lexical_anchor: false if it is a pure '
        'subject-matter question.')
    assert not report['cases_outscored_by_another_skill'], (
        'another skill\'s description matches the request better: '
        f"{report['cases_outscored_by_another_skill']}")
    assert proc.returncode == 0


@source_only
def test_the_scorer_computes_accuracy_and_refuses_an_incomplete_set(tmp_path):
    observed = tmp_path / 'observed.jsonl'

    def write(rows):
        observed.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows),
                            encoding='utf-8')

    # One wrong answer out of all cases, every case observed.
    rows = [{'id': c['id'], 'selected': c['expect']} for c in CASES]
    rows[0]['selected'] = 'afc-validate' if rows[0]['selected'] != 'afc-validate' else 'afc-query'
    write(rows)
    report = json.loads(run('--observed', str(observed)).stdout)
    assert report['observation_integrity'] == 'VERIFIED'
    assert report['answered'] == len(CASES)
    assert report['correct'] == len(CASES) - 1
    assert report['accuracy'] == round((len(CASES) - 1) / len(CASES), 4)
    assert len(report['confusion']) == 1

    # A missing observation cannot be graded, the rule the Loop Gate follows.
    write(rows[:-3])
    partial = json.loads(run('--observed', str(observed)).stdout)
    assert partial['grade'] == 'UNVERIFIED_OBSERVATIONS'
    assert len(partial['cases_without_an_observation']) == 3

    # A selection naming no skill is contamination, not a wrong answer.
    write([{'id': c['id'], 'selected': 'afc-made-up'} for c in CASES])
    bogus = json.loads(run('--observed', str(observed)).stdout)
    assert bogus['grade'] == 'UNVERIFIED_OBSERVATIONS'
    assert bogus['selections_naming_no_skill'] == ['afc-made-up']


@source_only
def test_the_accuracy_floor_comes_from_settings():
    from afc_card_runtime.config import load_settings
    assert load_settings(home=ROOT).get('skill_triggers.min_accuracy') is not None, \
        'the floor belongs in settings.yaml, not in a flag default'


@source_only
def test_the_template_has_one_row_per_case(tmp_path):
    template = tmp_path / 'observations.jsonl'
    proc = run('--template', str(template))
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(line) for line in template.read_text(encoding='utf-8').splitlines()]
    assert [r['id'] for r in rows] == [c['id'] for c in CASES]
    assert all(r['selected'] == '' for r in rows), 'the template must not pre-fill an answer'
