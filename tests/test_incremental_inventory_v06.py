from pathlib import Path
from types import SimpleNamespace
import json
import sys
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from afc_card_runtime.common import read_jsonl  # noqa: E402
from afc_card_runtime.knowledge_store import (  # noqa: E402
    accept_run,
    append_decision,
    current_release,
    init_store,
    stage_proposals,
)
from scripts.knowledge_base import inventory_command  # noqa: E402


def run_inventory(kb, source, run_id, rescan_unchanged=False):
    args = SimpleNamespace(
        kb_root=str(kb), source=[str(source)], context_map=None,
        business_context=[], target_scope=[], exclude_scope=[],
        override_excluded_scope=[], complete_boundary=False,
        rescan_unchanged=rescan_unchanged, no_recursive=False,
        behavior='product rules', run_id=run_id,
    )
    inventory_command(args)
    return kb / 'runs' / run_id


def accept_inventory_catalog(kb, run_dir, run_id):
    proposals = stage_proposals(
        current_release(kb, allow_empty=True), run_dir / 'candidate', run_dir, run_id)
    for row in proposals:
        append_decision(run_dir, row['Proposal ID'], 'accept', 'reviewer', 'Accept inventory snapshot')
    health_path = run_dir / 'card-health.json'
    health_path.write_text(json.dumps({'overall_status':'READY','run_id':run_id}), encoding='utf-8')
    manifest_path = run_dir / 'run-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['card_health'] = {
        'overall_status':'READY',
        'sha256':hashlib.sha256(health_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    accept_run(kb, run_dir, run_id)


def test_incremental_inventory_skips_unchanged_and_selects_modified_sources(tmp_path, capsys):
    kb = init_store(tmp_path / 'kb', 'test-kb')
    source = tmp_path / 'product'
    source.mkdir()
    (source / 'afc-scope.md').write_text(
        '## 預設 Scope\n- CA\n## 排除 Scope\n- 無。\n', encoding='utf-8')
    document = source / 'policy.txt'
    document.write_text('first version', encoding='utf-8')

    first = run_inventory(kb, source, 'scan-1')
    first_result = json.loads(capsys.readouterr().out)
    assert first_result['eligible_source_files'] == 1
    assert json.loads((first / 'candidate' / 'eligible-source-paths.json').read_text())['paths'] == [str(document.resolve())]
    accept_inventory_catalog(kb, first, 'scan-1')

    second = run_inventory(kb, source, 'scan-2')
    second_result = json.loads(capsys.readouterr().out)
    assert second_result['unchanged_source_files_skipped'] == 1
    assert json.loads((second / 'candidate' / 'eligible-source-paths.json').read_text())['paths'] == []

    document.write_text('changed version', encoding='utf-8')
    third = run_inventory(kb, source, 'scan-3')
    third_result = json.loads(capsys.readouterr().out)
    assert third_result['modified'] == 1
    assert json.loads((third / 'candidate' / 'eligible-source-paths.json').read_text())['paths'] == [str(document.resolve())]

