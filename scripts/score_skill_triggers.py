#!/usr/bin/env python3
"""Score which skill a request actually reaches.

A skill is selected from its description. Rewriting the descriptions to carry
the words a user types, and to name the sibling that owns the neighbouring work,
was an assumption about model behaviour -- and this package's own rule is that a
rate is computed from recorded observations, never self-reported. So the harness
records one selection per case and this script computes the number.

  --template PATH   write one observation row per case, to be filled in
  --observed PATH   compute accuracy, per-skill recall and confusion pairs
  --lexical         no model: report cases whose wording has no anchor in the
                    expected skill's description, or a stronger anchor in
                    another skill's

The lexical pass is a pre-check, not an eval: it catches a request that cannot
plausibly reach its skill, using the same segmentation as retrieval, and says
nothing about what a model would actually choose.
"""
from pathlib import Path
import argparse
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, tokenize, write_json, write_jsonl
from afc_card_runtime.config import find_afc_home, load_settings

try:
    import yaml
except Exception:  # pragma: no cover - yaml is a hard requirement at runtime
    yaml = None


def load_cases(path):
    if yaml is None:
        raise RuntimeError('PyYAML is required to read the trigger cases')
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    cases = data.get('cases') or []
    seen = set()
    for case in cases:
        for key in ('id', 'request', 'expect'):
            if not case.get(key):
                raise ValueError(f'case is missing {key}: {case}')
        if case['id'] in seen:
            raise ValueError('duplicate case id: ' + case['id'])
        seen.add(case['id'])
    return cases


def skill_descriptions(root):
    out = {}
    for path in sorted((Path(root) / 'skills').glob('*/SKILL.md')):
        text = path.read_text(encoding='utf-8')
        head = text.split('---')[1] if text.startswith('---') else ''
        match = re.search(r'(?m)^description:\s*(.+)$', head)
        out[path.parent.name] = match.group(1).strip() if match else ''
    return out


def terms(text):
    """Tokens worth matching on: drops 1-character CJK fragments and noise."""
    return {t for t in tokenize(text) if len(t) >= 2}


def lexical_report(cases, descriptions):
    """Where a request's wording sits relative to every skill's description."""
    rows = []
    for case in cases:
        request = terms(case['request'])
        scores = {name: len(request & terms(desc)) for name, desc in descriptions.items()}
        expected = case['expect']
        best = max(scores.values()) if scores else 0
        winners = sorted(n for n, s in scores.items() if s == best and s > 0)
        anchored = case.get('lexical_anchor', True)
        rows.append({
            'id': case['id'],
            'expect': expected,
            'lexical_anchor_expected': anchored,
            'anchor_terms': sorted(request & terms(descriptions.get(expected, ''))),
            'expected_score': scores.get(expected, 0),
            'best_score': best,
            'lexical_winners': winners,
            'no_anchor': anchored and scores.get(expected, 0) == 0,
            'outscored_by': [n for n in winners if anchored and n != expected
                             and scores[n] > scores.get(expected, 0)],
        })
    return rows


def main():
    settings = load_settings()
    root = find_afc_home()
    default_cases = root / 'config' / 'skill-trigger-cases.yaml'
    ap = argparse.ArgumentParser(description='Score which skill a request reaches.')
    ap.add_argument('--cases', default=str(default_cases))
    ap.add_argument('--observed', help='JSONL: {"id": ..., "selected": "afc-..."} per case')
    ap.add_argument('--template', help='Write an observation template here and exit')
    ap.add_argument('--lexical', action='store_true',
                    help='Run the description pre-check instead of scoring observations')
    ap.add_argument('--min-accuracy', type=float,
                    default=settings.get('skill_triggers.min_accuracy', 0.9))
    ap.add_argument('--json-output')
    a = ap.parse_args()

    cases = load_cases(a.cases)
    descriptions = skill_descriptions(root)

    if a.template:
        write_jsonl(a.template, [
            {'id': c['id'], 'request': c['request'], 'selected': '',
             'note': 'the skill you would load for this request, and why if it is not obvious'}
            for c in cases])
        print(json.dumps({'cases': len(cases), 'template': a.template,
                          'next': 'fill in "selected" for every row, then rerun with --observed'},
                         ensure_ascii=False, indent=2))
        return 0

    if a.lexical:
        rows = lexical_report(cases, descriptions)
        unanchored = [r for r in rows if r['no_anchor']]
        outscored = [r for r in rows if r['outscored_by']]
        out = {'mode': 'lexical-precheck', 'cases': len(rows),
               'cases_with_no_anchor': [r['id'] for r in unanchored],
               'cases_outscored_by_another_skill':
                   {r['id']: r['outscored_by'] for r in outscored},
               'note': ('A pre-check on wording only. It cannot tell you what a model '
                        'would choose; it can tell you a request has nothing in common '
                        'with the description it is supposed to reach.'),
               'rows': rows}
        if a.json_output:
            write_json(a.json_output, out)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if not unanchored else 2

    if not a.observed:
        ap.error('pass --observed, --template or --lexical')

    observed = {}
    for row in read_jsonl(a.observed):
        case_id = row.get('id')
        if case_id:
            observed[str(case_id)] = (row.get('selected') or '').strip()

    by_id = {c['id']: c for c in cases}
    missing = [c['id'] for c in cases if not observed.get(c['id'])]
    extra = [i for i in observed if i not in by_id]
    unknown_skill = sorted({s for s in observed.values()
                            if s and s not in descriptions})

    results, confusion = [], {}
    for case in cases:
        selected = observed.get(case['id'], '')
        if not selected:
            continue
        correct = selected == case['expect']
        row = {'id': case['id'], 'expect': case['expect'], 'selected': selected,
               'correct': correct}
        if not correct:
            row['confusable_with'] = case.get('confusable_with')
            row['anticipated'] = selected == case.get('confusable_with')
            pair = f"{case['expect']} -> {selected}"
            confusion[pair] = confusion.get(pair, 0) + 1
        results.append(row)

    answered = len(results)
    correct = sum(1 for r in results if r['correct'])
    accuracy = (correct / answered) if answered else None
    per_skill = {}
    for case in cases:
        bucket = per_skill.setdefault(case['expect'], {'cases': 0, 'answered': 0, 'correct': 0})
        bucket['cases'] += 1
        selected = observed.get(case['id'], '')
        if selected:
            bucket['answered'] += 1
            bucket['correct'] += int(selected == case['expect'])

    # An incomplete or contaminated observation set cannot be graded, the same
    # rule the Loop Gate metrics follow.
    if missing or extra or unknown_skill:
        integrity = 'UNVERIFIED'
    else:
        integrity = 'VERIFIED'
    if integrity != 'VERIFIED':
        grade = 'UNVERIFIED_OBSERVATIONS'
    elif accuracy is None:
        grade = 'NO_OBSERVATIONS'
    else:
        grade = 'PASS' if accuracy >= a.min_accuracy else 'FAIL'

    out = {
        'mode': 'observed',
        'grade': grade,
        'observation_integrity': integrity,
        'cases': len(cases),
        'answered': answered,
        'correct': correct,
        'accuracy': round(accuracy, 4) if accuracy is not None else None,
        'min_accuracy': a.min_accuracy,
        'cases_without_an_observation': missing,
        'observations_for_unknown_cases': extra,
        'selections_naming_no_skill': unknown_skill,
        'confusion': dict(sorted(confusion.items(), key=lambda kv: -kv[1])),
        'anticipated_confusions': sum(1 for r in results if r.get('anticipated')),
        'per_expected_skill': per_skill,
        'results': results,
        'cases_file': str(a.cases),
    }
    if a.json_output:
        write_json(a.json_output, out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if grade == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
