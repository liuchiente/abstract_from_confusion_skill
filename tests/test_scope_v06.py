import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from afc_card_runtime.scope import (  # noqa: E402
    load_business_context_map, parse_scope_metadata, resolve_membership_scopes,
    source_memberships,
)


def test_markdown_scope_sections_parse_canonical_ids_and_empty_exclusions(tmp_path):
    scope_file = tmp_path / 'afc-scope.md'
    scope_file.write_text(
        '## 預設 Scope\n- `CA` — 車險 CA\n\n## 排除 Scope\n- 無。\n',
        encoding='utf-8',
    )
    parsed = parse_scope_metadata(scope_file)
    assert parsed['default_scopes'] == ['CA']
    assert parsed['excluded_scopes'] == []
    assert len(parsed['sha256']) == 64


def test_nearest_child_scope_replaces_inherited_default_and_exclusion(tmp_path):
    root = tmp_path / 'product'
    child = root / 'child'
    child.mkdir(parents=True)
    (root / 'afc-scope.md').write_text(
        '## 預設 Scope\n- CA\n## 排除 Scope\n- CB\n', encoding='utf-8')
    (child / 'afc-scope.md').write_text(
        '## 預設 Scope\n- CB\n## 排除 Scope\n- 無\n', encoding='utf-8')
    source = child / 'spec.docx'
    source.write_bytes(b'fixture')
    membership = source_memberships(source, [root])[0]
    assert membership['scope_metadata']['path'] == str((child / 'afc-scope.md').resolve())
    assert membership['scope_metadata']['default_scopes'] == ['CB']
    assert membership['scope_metadata']['excluded_scopes'] == []


def test_nearest_parent_scope_applies_but_outside_paths_fail_closed(tmp_path):
    parent = tmp_path / 'parent'
    selected = parent / 'selected'
    selected.mkdir(parents=True)
    (parent / 'afc-scope.md').write_text('## 預設 Scope\n- CA\n', encoding='utf-8')
    source = selected / 'policy.docx'
    source.write_bytes(b'fixture')
    memberships = source_memberships(source, [selected])
    assert memberships[0]['scope_metadata']['default_scopes'] == ['CA']
    assert source_memberships(parent / 'other.docx', [selected]) == []


def test_mapping_only_context_xml_resolves_aliases_and_scopes(tmp_path):
    path = tmp_path / 'context.xml.example'
    path.write_text(
        '<context-map><scopes><scope id="CA"/><scope id="CB"/></scopes>'
        '<business-contexts><business-context id="vehicle" name="車險">'
        '<aliases><alias>汽車險</alias></aliases><maps-to>'
        '<scope-ref id="CA"/><scope-ref id="CB"/></maps-to></business-context>'
        '</business-contexts></context-map>', encoding='utf-8')
    rows = load_business_context_map(path)
    assert rows[0]['context'] == '車險'
    assert rows[0]['aliases'] == ['車險', '汽車險']
    assert rows[0]['scopes'] == ['CA', 'CB']


def test_scope_exclusion_blocks_prompt_target_until_specific_override(tmp_path):
    scope_file = tmp_path / 'afc-scope.md'
    scope_file.write_text('## 預設 Scope\n- CA\n## 排除 Scope\n- CB\n', encoding='utf-8')
    metadata = parse_scope_metadata(scope_file)
    blocked = resolve_membership_scopes(metadata, requested_scopes=['CA', 'CB'])
    assert blocked['status'] == 'partially-excluded'
    assert blocked['allowed_scopes'] == ['CA']
    assert blocked['blocked_scopes'] == ['CB']
    overridden = resolve_membership_scopes(
        metadata, requested_scopes=['CA', 'CB'], override_exclusions=['CB'])
    assert overridden['allowed_scopes'] == ['CA', 'CB']
    assert overridden['override_scopes'] == ['CB']


def test_step_zero_applies_scope_file_and_records_override(tmp_path):
    root = tmp_path / 'product'
    root.mkdir()
    (root / 'afc-scope.md').write_text(
        '## 預設 Scope\n- CA\n## 排除 Scope\n- CB\n', encoding='utf-8')
    source = root / 'spec.docx'
    source.write_bytes(b'not parsed by this focused selection test')
    parsed = tmp_path / 'parsed.jsonl'
    parsed.write_text(json.dumps({
        'source_unit_id': 'spec::B000001', 'source_path': str(source),
        'kind': 'paragraph', 'value': 'CB passenger coverage',
    }) + '\n', encoding='utf-8')

    def run(output, *extra):
        report = output.with_suffix('.json')
        proc = subprocess.run([
            sys.executable, 'scripts/build_context_candidates.py', str(parsed),
            '--target-scope', 'CB', '--scope-root', str(root), '-o', str(output),
            '--report', str(report), *extra,
        ], cwd=ROOT, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        rows = [json.loads(line) for line in output.read_text(encoding='utf-8').splitlines()]
        return rows[0], json.loads(report.read_text(encoding='utf-8'))

    blocked, blocked_report = run(tmp_path / 'blocked.jsonl')
    assert blocked['selected'] is False
    assert blocked['scope_boundary_eligible'] is False
    assert blocked_report['scope_boundary']['blocked_files']

    allowed, allowed_report = run(tmp_path / 'allowed.jsonl', '--override-excluded-scope', 'CB')
    assert allowed['selected'] is True
    assert allowed['source_memberships'][0]['override_scopes'] == ['CB']
    assert allowed_report['scope_boundary']['scope_overrides']
