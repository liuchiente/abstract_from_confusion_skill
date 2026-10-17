#!/usr/bin/env python3
"""Validate AFC artifacts against the JSON Schemas in schemas/.

v0.4.1 shipped 13 schemas that nothing read -- `jsonschema` was not even a
dependency -- while hand-written checks in validate_cards.py / validate_links.py
drifted from them (the Card schema required `Source Location`, the validator did
not; the validator required non-empty `Content`, the schema did not).

This is the first gate: schema first, then the cross-file reference checks that
a schema cannot express. Artifact kinds are auto-detected from the filename, or
named explicitly with --kind.

  validate_schema.py --all --root .
  validate_schema.py work/step-card-1-cards.jsonl --kind knowledge-card
"""
from pathlib import Path
import argparse, json, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, read_json, write_json
from afc_card_runtime.config import find_afc_home

try:
    import jsonschema
except ImportError:
    jsonschema = None

# kind -> (schema file, one-object-per-line?)
KINDS = {
    'knowledge-card': ('knowledge-card.schema.json', True),
    'evidence-record': ('evidence-record.schema.json', True),
    'knowledge-link': ('knowledge-link.schema.json', True),
    'knowledge-box': ('knowledge-box.schema.json', True),
    'box-membership': ('box-membership.schema.json', True),
    'box-link': ('box-link.schema.json', True),
    'context-block': ('context-block.schema.json', True),
    'card-coverage': ('card-coverage.schema.json', True),
    'visual-extraction': ('visual-extraction.schema.json', True),
    'review-verdict': ('review-verdict.schema.json', True),
    'knowledge-change': ('knowledge-change.schema.json', True),
    'id-registry': ('id-registry.schema.json', True),
    'card-health': ('card-health.schema.json', False),
    'source-structure-audit': ('source-structure-audit.schema.json', False),
    'review-sample': ('review-sample.schema.json', False),
    'review-metric': ('review-metric.schema.json', False),
    'card-decision': ('card-decision.schema.json', False),
    'query-run': ('query-run.schema.json', False),
    'query-benchmark': ('query-benchmark.schema.json', False),
    'business-context': ('business-context.schema.json', False),
    'scope-attribution': ('knowledge-scope-attribution.schema.json', True),
    'semantic-domain': ('semantic-domain.schema.json', True),
}

# Filename fragment -> kind, longest fragment wins.
DETECT = [
    ('step-card-0-source-structure-audit', 'source-structure-audit'),
    ('step-card-0-contexts', 'context-block'),
    ('step-card-0-visual-extractions', 'visual-extraction'),
    ('step-card-1-coverage', 'card-coverage'),
    ('step-card-1-health', 'card-health'),
    ('step-card-1-decision', 'card-decision'),
    ('step-card-1-evidence', 'evidence-record'),
    ('step-card-1-cards', 'knowledge-card'),
    ('step-card-1-reconciled-cards', 'knowledge-card'),
    ('step-card-2-links', 'knowledge-link'),
    ('step-card-3-box-memberships', 'box-membership'),
    ('step-card-3-box-links', 'box-link'),
    ('step-card-3-boxes', 'knowledge-box'),
    ('step-card-4-evidence', 'evidence-record'),
    ('step-card-4-master', 'knowledge-card'),
    ('knowledge-change-log', 'knowledge-change'),
    ('id-registry', 'id-registry'),
    ('knowledge_card_master', 'knowledge-card'),
    ('knowledge_evidence', 'evidence-record'),
    ('knowledge_links', 'knowledge-link'),
    ('knowledge_box_memberships', 'box-membership'),
    ('knowledge_box_links', 'box-link'),
    ('knowledge_boxes', 'knowledge-box'),
    ('knowledge_contexts', 'context-block'),
    ('knowledge_scope_attributions', 'scope-attribution'),
    ('knowledge_domains', 'semantic-domain'),
    ('source_unit_coverage', 'card-coverage'),
    ('-sample', 'review-sample'),
    ('-verdicts', 'review-verdict'),
    ('saturation-report', 'review-metric'),
    ('benchmark', 'query-benchmark'),
    ('fidelity-report', 'review-metric'),
    ('atomicity-report', 'review-metric'),
]

# Artifacts checked by --all, in pipeline order.
ALL_TARGETS = [
    'work/step-card-0-source-structure-audit.json',
    'work/step-card-0-contexts.jsonl',
    'work/step-card-1-evidence.jsonl',
    'work/step-card-1-cards.jsonl',
    'work/step-card-1-reconciled-cards.jsonl',
    'work/step-card-1-coverage.jsonl',
    'work/step-card-1-saturation-report.json',
    'work/step-card-1-fidelity-report.json',
    'work/step-card-1-atomicity-report.json',
    'work/step-card-1-health.json',
    'work/step-card-1-decision.json',
    'work/step-card-2-links.jsonl',
    'work/step-card-3-boxes.jsonl',
    'work/step-card-3-box-memberships.jsonl',
    'work/step-card-3-box-links.jsonl',
    'work/step-card-4-master.jsonl',
    'work/step-card-4-evidence.jsonl',
    'work/id-registry.jsonl',
    'work/knowledge-change-log.jsonl',
    'output/knowledge_card_master.jsonl',
    'output/knowledge_evidence.jsonl',
    'output/knowledge_links.jsonl',
    'output/knowledge_boxes.jsonl',
    'output/knowledge_box_memberships.jsonl',
    'output/knowledge_box_links.jsonl',
    'output/knowledge_contexts.jsonl',
    'output/knowledge_scope_attributions.jsonl',
    'output/knowledge_domains.jsonl',
    'output/source_unit_coverage.jsonl',
]


def detect_kind(path):
    name = Path(path).name
    best = None
    for fragment, kind in DETECT:
        if fragment in name and (best is None or len(fragment) > len(best[0])):
            best = (fragment, kind)
    return best[1] if best else None


def validate_file(validator, path, per_line, max_errors):
    errors = []
    if per_line:
        try:
            rows = read_jsonl(path)
        except ValueError as e:
            return [{'row': None, 'path': '', 'message': str(e)}], 0
        for i, row in enumerate(rows, 1):
            for err in validator.iter_errors(row):
                errors.append({'row': i, 'path': '/'.join(str(x) for x in err.absolute_path),
                               'message': err.message})
                if len(errors) >= max_errors:
                    return errors, len(rows)
        return errors, len(rows)
    obj = read_json(path)
    for err in validator.iter_errors(obj):
        errors.append({'row': None, 'path': '/'.join(str(x) for x in err.absolute_path),
                       'message': err.message})
        if len(errors) >= max_errors:
            break
    return errors, 1


# An ID field whose value is a placeholder, in the one error shape jsonschema
# produces for it. Everything else about the record is still checked.
ID_PATTERN_FIELDS = ('Card ID', 'Evidence ID', 'Card IDs', 'Evidence Record IDs',
                     'Source Card ID', 'Target Card ID', 'Superseded By')


def split_placeholder_id_errors(errors):
    """Separate 'this ID is not a registry ID yet' from real schema errors.

    Step 1 writes Cards and Evidence with placeholder IDs and allocate_ids.py
    replaces them, so before allocation every record fails the ID pattern. That
    made it impossible to schema-check a draft: the real errors arrived buried
    in one pattern complaint per record.
    """
    real, placeholders = [], []
    for err in errors:
        path = str(err.get('path') or '')
        field = path.split('/')[0]
        is_id_field = field in ID_PATTERN_FIELDS
        is_pattern = 'does not match' in str(err.get('message') or '')
        if is_id_field and is_pattern:
            placeholders.append(err)
        else:
            real.append(err)
    return real, placeholders


def main():
    ap = argparse.ArgumentParser(description='Validate AFC artifacts against schemas/.')
    ap.add_argument('inputs', nargs='*', help='Artifact files to validate')
    ap.add_argument('--kind', choices=sorted(KINDS), help='Force a kind instead of detecting it')
    ap.add_argument('--all', action='store_true', help='Validate every canonical artifact that exists')
    ap.add_argument('--root', default=None, help='AFC root for --all (default: detected AFC home)')
    ap.add_argument('--schemas', default=None, help='Schema directory (default: <root>/schemas)')
    ap.add_argument('--max-errors', type=int, default=20, help='Per-file error cap')
    ap.add_argument('--draft', action='store_true',
                    help='Check the shape of pre-allocation output: an ID that does not match '
                         'the registry pattern is reported as a placeholder instead of an '
                         'error, so a batch can be validated before allocate_ids.py runs. '
                         'Never use it on an artifact that is meant to be final.')
    ap.add_argument('--allow-undetected', action='store_true',
                    help='Treat a file whose kind cannot be detected as a skip rather than a failure')
    ap.add_argument('--json-output')
    a = ap.parse_args()

    if jsonschema is None:
        print(json.dumps({'status': 'FAIL', 'reason': 'jsonschema is not installed. '
                                                      'Run: pip install -r requirements.txt'},
                         ensure_ascii=False, indent=2))
        raise SystemExit(2)

    root = Path(a.root).resolve() if a.root else find_afc_home()
    schema_dir = Path(a.schemas) if a.schemas else root / 'schemas'

    targets = []
    for raw in a.inputs:
        targets.append((Path(raw), a.kind or detect_kind(raw)))
    if a.all:
        for rel in ALL_TARGETS:
            p = root / rel
            if p.exists():
                targets.append((p, detect_kind(rel)))
    if not targets:
        ap.error('Provide artifact paths or --all')

    cache = {}
    results, total_errors, unknown = [], 0, []
    for path, kind in targets:
        if kind is None:
            unknown.append(str(path))
            results.append({'file': str(path), 'kind': None, 'status': 'SKIPPED',
                            'reason': 'could not detect artifact kind; pass --kind'})
            continue
        schema_file, per_line = KINDS[kind]
        if kind not in cache:
            sp = schema_dir / schema_file
            if not sp.exists():
                results.append({'file': str(path), 'kind': kind, 'status': 'SKIPPED',
                                'reason': f'schema not found: {sp}'})
                continue
            schema = json.loads(sp.read_text(encoding='utf-8'))
            cache[kind] = jsonschema.Draft202012Validator(schema)
        errors, n = validate_file(cache[kind], path, per_line, a.max_errors)
        placeholders = []
        if a.draft:
            errors, placeholders = split_placeholder_id_errors(errors)
        total_errors += len(errors)
        row = {'file': str(path), 'kind': kind, 'records': n,
               'status': 'PASS' if not errors else 'FAIL',
               'error_count': len(errors), 'errors': errors}
        if a.draft:
            row['placeholder_ids'] = len(placeholders)
            row['placeholder_id_examples'] = placeholders[:5]
        results.append(row)

    skipped = [r for r in results if r['status'] == 'SKIPPED']
    # A silent skip is the failure mode this script exists to remove, so an
    # artifact whose kind or schema could not be resolved fails by default.
    status = 'PASS' if (total_errors == 0 and (a.allow_undetected or not skipped)) else 'FAIL'
    out = {'status': status, 'mode': 'draft' if a.draft else 'final',
           'schema_dir': str(schema_dir), 'root': str(root),
           'files_checked': sum(1 for r in results if r['status'] in ('PASS', 'FAIL')),
           'files_skipped': len(skipped),
           'total_errors': total_errors, 'undetected_kinds': unknown, 'results': results}
    if a.draft:
        total_placeholders = sum(r.get('placeholder_ids', 0) for r in results)
        out['placeholder_ids'] = total_placeholders
        out['note'] = ('Draft mode: %d placeholder ID(s) were not treated as errors. Run '
                       'allocate_ids.py, then validate again without --draft before anything '
                       'downstream reads these files.' % total_placeholders)
    if skipped and not a.allow_undetected:
        out['reason'] = (f'{len(skipped)} file(s) were not validated. Pass --kind, rename to the '
                         'canonical artifact name, or use --allow-undetected deliberately.')
    if a.json_output:
        write_json(a.json_output, out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    raise SystemExit(0 if status == 'PASS' else 2)


if __name__ == '__main__':
    main()
