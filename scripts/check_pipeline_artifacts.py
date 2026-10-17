#!/usr/bin/env python3
"""Check presence and readability of AFC Step 0-6 artifacts after a run.

v0.4.1 accepted any file whose size was `>= 0`, i.e. an empty file counted as
present. Required artifacts must now be non-empty and parseable, optional ones
are reported without failing, and the v0.5.0 artifacts (ID registry, review
samples, decision, change log) are included.
"""
from pathlib import Path
import argparse, json, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, read_json, write_json
from afc_card_runtime.config import find_afc_home, load_settings

# step -> list of (relative path, required, may_be_empty)
CHECKS = {
    'step0': [
        ('work/step-card-0-source-structure-audit.json', True, False),
        ('work/step-card-0-source-map.jsonl', True, False),
        ('work/step-card-0-contexts.jsonl', True, False),
        ('work/step-card-0-context-report.json', True, False),
        ('work/step-card-0-context-selection-audit.json', True, False),
        ('work/step-card-0-visual-extractions.jsonl', False, True),
    ],
    'step1': [
        ('work/step-card-1-evidence.jsonl', True, False),
        ('work/step-card-1-cards.jsonl', True, False),
        ('work/step-card-1-coverage.jsonl', True, False),
        ('work/step-card-1-coverage-report.json', True, False),
        ('work/step-card-1-saturation-report.json', True, False),
        ('work/step-card-1-fidelity-report.json', True, False),
        ('work/step-card-1-atomicity-report.json', True, False),
        ('work/step-card-1-health.json', True, False),
        ('work/id-registry.jsonl', True, False),
        ('work/step-card-1-saturation-sample.json', False, False),
        ('work/step-card-1-fidelity-sample.json', False, False),
        ('work/step-card-1-atomicity-sample.json', False, False),
        ('work/step-card-1-decision.json', False, False),
        ('work/step-card-1-reconciled-cards.jsonl', False, False),
    ],
    'step2': [('work/step-card-2-links.jsonl', True, True)],
    'step3': [
        ('work/step-card-3-boxes.jsonl', True, False),
        ('work/step-card-3-box-memberships.jsonl', True, True),
        ('work/step-card-3-box-links.jsonl', True, True),
        ('work/step-card-3-box-audit.json', True, False),
    ],
    'step4': [
        ('work/step-card-4-master.jsonl', True, False),
        ('work/step-card-4-evidence.jsonl', True, False),
    ],
    'step5': [
        ('output/knowledge_card_master.jsonl', True, False),
        ('output/knowledge_domains.jsonl', True, True),
        ('output/knowledge_evidence.jsonl', True, False),
        ('output/knowledge_links.jsonl', True, True),
        ('output/knowledge_boxes.jsonl', True, False),
        ('output/knowledge_box_memberships.jsonl', True, True),
        ('output/knowledge_box_links.jsonl', True, True),
        ('output/knowledge_contexts.jsonl', True, False),
        ('output/source_unit_coverage.jsonl', True, False),
        ('output/source_unit_coverage_report.json', True, False),
        ('output/knowledge_card_master.xlsx', False, False),
    ],
    'step6': [('work/query-index/afc-query.db', True, False)],
    'lifecycle': [('work/knowledge-change-log.jsonl', False, True)],
}


def inspect(path, may_be_empty):
    if not path.exists() or not path.is_file():
        return 'missing', None
    size = path.stat().st_size
    if size == 0:
        return ('empty_ok' if may_be_empty else 'empty'), 0
    if path.suffix == '.jsonl':
        try:
            return 'ok', len(read_jsonl(path))
        except ValueError as e:
            return f'unparseable: {e}', None
    if path.suffix == '.json':
        try:
            read_json(path)
        except json.JSONDecodeError as e:
            return f'unparseable: {e}', None
        return 'ok', 1
    return 'ok', None


def main():
    ap = argparse.ArgumentParser(description='Check AFC Step 0-6 artifacts after an end-to-end run.')
    ap.add_argument('--root', default=None, help='AFC runtime root (default: detected AFC home)')
    ap.add_argument('--through-step', type=int, choices=range(0, 7), default=6,
                    help='Only require artifacts through this pipeline step (0-6).')
    ap.add_argument('--json-output')
    a = ap.parse_args()
    root = Path(a.root).resolve() if a.root else find_afc_home()

    checks = {key: list(value) for key, value in CHECKS.items()}
    settings = load_settings()
    registry = settings.resolve('artifacts.id_registry')
    if registry:
        checks['step1'] = [(str(registry) if rel == 'work/id-registry.jsonl' else rel, required, empty)
                           for rel, required, empty in checks['step1']]
    result = {'root': str(root), 'through_step': a.through_step, 'steps': {}, 'overall': 'PASS',
              'missing_required': [], 'empty_required': [], 'unparseable': []}
    step_numbers = {'step0': 0, 'step1': 1, 'step2': 2, 'step3': 3, 'step4': 4, 'step5': 5, 'step6': 6}
    for step, items in checks.items():
        if step in step_numbers and step_numbers[step] > a.through_step:
            continue
        entries, failed = [], False
        for rel, required, may_be_empty in items:
            state, count = inspect(root / rel, may_be_empty)
            entry = {'path': rel, 'required': required, 'state': state, 'records': count}
            entries.append(entry)
            if state == 'missing' and required:
                result['missing_required'].append(rel); failed = True
            elif state == 'empty' and required:
                result['empty_required'].append(rel); failed = True
            elif state.startswith('unparseable'):
                result['unparseable'].append({'path': rel, 'error': state}); failed = True
        result['steps'][step] = {'status': 'FAIL' if failed else 'PASS', 'artifacts': entries}
        if failed:
            result['overall'] = 'FAIL'
    if a.json_output:
        write_json(a.json_output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['overall'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
