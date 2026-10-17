from pathlib import Path
import sys
import json
import hashlib
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from afc_card_runtime.common import read_jsonl  # noqa: E402
from afc_card_runtime.knowledge_store import (  # noqa: E402
    accept_run,
    append_decision,
    current_release,
    init_store,
    normalize_migrated_null_fields,
    stage_proposals,
)
from scripts.knowledge_base import migrate_v05_command  # noqa: E402


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(__import__('json').dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def make_candidate(root, title='Passenger coverage'):
    candidate = root / 'candidate'
    write_rows(candidate / 'knowledge_card_master.jsonl', [{
        'Card ID': 'CARD-000001', 'Card Type': 'Rule', 'Title': title,
        'Content': 'Passenger coverage can be added.', 'Scopes': ['CA'],
        'Evidence Record IDs': ['EVD-000001'], 'Source': 'policy.docx',
        'Source Location': 'Section 1',
    }])
    write_rows(candidate / 'knowledge_evidence.jsonl', [{
        'Evidence ID': 'EVD-000001', 'Evidence Mode': 'VERBATIM',
        'Original Text': 'Passenger coverage can be added.', 'Source': 'policy.docx',
        'Source Location': 'Section 1', 'Card IDs': ['CARD-000001'],
    }])
    return candidate


def decide_all(run_dir, decision='accept'):
    for proposal in read_jsonl(run_dir / 'proposals.jsonl'):
        append_decision(run_dir, proposal['Proposal ID'], decision, 'reviewer', 'Reviewed test proposal')
    health_path = run_dir / 'card-health.json'
    health_path.write_text(json.dumps({'overall_status':'READY','run_id':run_dir.name}), encoding='utf-8')
    kb_root = run_dir.parents[1]
    current = current_release(kb_root, allow_empty=True)
    manifest_path = run_dir / 'run-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    manifest.update({
        'run_id':run_dir.name,
        'base_release_id': current.name if current else None,
        'card_health': {
            'overall_status':'READY',
            'sha256':hashlib.sha256(health_path.read_bytes()).hexdigest(),
        },
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


def test_publish_requires_human_decision_and_confirms_scope_attribution(tmp_path):
    kb = init_store(tmp_path / 'kb', 'test-kb')
    run_dir = kb / 'runs' / 'run-1'
    candidate = make_candidate(run_dir)
    proposals = stage_proposals(None, candidate, run_dir, 'run-1')

    try:
        accept_run(kb, run_dir, 'run-1')
    except ValueError as exc:
        assert 'every proposal needs' in str(exc)
    else:
        raise AssertionError('release published without explicit human decisions')

    decide_all(run_dir)
    release_id = accept_run(kb, run_dir, 'run-1')
    release = current_release(kb)
    attributions = read_jsonl(release / 'knowledge_scope_attributions.jsonl')
    assert release_id == 'release-000001'
    assert len(proposals) == 3
    assert attributions[0]['Status'] == 'Confirmed'
    assert (release / 'release-manifest.json').exists()


def test_rejected_update_keeps_current_value_and_release_can_be_rolled_back(tmp_path):
    kb = init_store(tmp_path / 'kb', 'test-kb')
    first = kb / 'runs' / 'run-1'
    stage_proposals(None, make_candidate(first), first, 'run-1')
    decide_all(first)
    first_release = accept_run(kb, first, 'run-1')

    second = kb / 'runs' / 'run-2'
    stage_proposals(current_release(kb), make_candidate(second, 'Changed title'), second, 'run-2')
    decide_all(second, decision='reject')
    second_release = accept_run(kb, second, 'run-2')
    assert second_release == 'release-000002'
    cards = read_jsonl(current_release(kb) / 'knowledge_card_master.jsonl')
    assert cards[0]['Title'] == 'Passenger coverage'

    from afc_card_runtime.knowledge_store import publish_pointer
    publish_pointer(kb, first_release)
    assert current_release(kb).name == first_release


def test_new_scope_evidence_requires_a_review_proposal(tmp_path):
    kb = init_store(tmp_path / 'kb', 'test-kb')
    first = kb / 'runs' / 'run-1'
    stage_proposals(None, make_candidate(first), first, 'run-1')
    decide_all(first)
    accept_run(kb, first, 'run-1')

    second = kb / 'runs' / 'run-2'
    candidate = second / 'candidate'
    write_rows(candidate / 'knowledge_card_master.jsonl', [{
        'Card ID': 'CARD-000001', 'Card Type': 'Rule', 'Title': 'Passenger coverage',
        'Content': 'Passenger coverage can be added.', 'Scopes': ['CA'],
        'Evidence Record IDs': ['EVD-000001', 'EVD-000002'], 'Source': 'policy.docx',
        'Source Location': 'Section 1',
    }])
    write_rows(candidate / 'knowledge_evidence.jsonl', [{
        'Evidence ID': 'EVD-000001', 'Evidence Mode': 'VERBATIM',
        'Original Text': 'Passenger coverage can be added.', 'Source': 'policy.docx',
        'Source Location': 'Section 1', 'Card IDs': ['CARD-000001'],
    }, {
        'Evidence ID': 'EVD-000002', 'Evidence Mode': 'VERBATIM',
        'Original Text': 'May be added for CA.', 'Source': 'policy-v2.docx',
        'Source Location': 'Section 2', 'Card IDs': ['CARD-000001'],
    }])
    proposals = stage_proposals(current_release(kb), candidate, second, 'run-2')
    assert any(row['Dataset'] == 'scope_attributions' for row in proposals)


def test_v05_migration_reconstructs_missing_registry_without_changing_ids(tmp_path, capsys):
    v05 = tmp_path / 'v05'
    output = v05 / 'output'
    work = v05 / 'work'
    output.mkdir(parents=True)
    work.mkdir()
    write_rows(output / 'knowledge_card_master.jsonl', [{
        'Card ID': 'CARD-000010', 'Card Type': 'Rule', 'Title': 'Existing rule',
        'Content': 'The source rule.', 'Scopes': ['CA'],
        'Evidence Record IDs': ['EVD-000022'], 'Source': 'policy.docx',
        'Source Location': 'Section 1',
    }])
    write_rows(output / 'knowledge_evidence.jsonl', [{
        'Evidence ID': 'EVD-000022', 'Evidence Mode': 'VERBATIM',
        'Original Text': 'The source rule.', 'Source': 'policy.docx',
        'Source Location': 'Section 1', 'Card IDs': ['CARD-000010'],
    }])
    # Preserve numbers known from earlier work even if their records are no
    # longer in the accepted master.
    (work / 'step-card-1-cards.jsonl').write_text('{"Card ID":"CARD-000099"}\n', encoding='utf-8')
    kb = tmp_path / 'kb'
    args = SimpleNamespace(
        accept_baseline=True, kb_root=str(kb), kb_id='test-kb', name=None,
        v05_root=str(v05), run_id='migrate-test', accepted_by='reviewer',
        rationale='Validate migration fallback',
    )

    migrate_v05_command(args)
    capsys.readouterr()
    release = current_release(kb)
    cards = read_jsonl(release / 'knowledge_card_master.jsonl')
    registry = read_jsonl(kb / 'identity' / 'id-registry.jsonl')
    assert cards[0]['Card ID'] == 'CARD-000010'
    assert {row['id'] for row in registry} >= {'CARD-000010', 'CARD-000099', 'EVD-000022'}
    manifest = json.loads((release / 'release-manifest.json').read_text(encoding='utf-8'))
    assert manifest['id_registry_reconstruction']['method'] == 'reconstructed-from-current-master-and-observed-jsonl-ids'


def test_v05_null_normalization_drops_only_optional_schema_nulls(tmp_path):
    release = tmp_path / 'release'
    write_rows(release / 'knowledge_contexts.jsonl', [{
        'Context ID': 'CTX-000001', 'Content': 'Context', 'Detected Scopes': [],
        'Source': 'policy.docx', 'Source Location': 'Section 1',
        'Parent Context ID': None,
    }])
    result = normalize_migrated_null_fields(release)
    row = read_jsonl(release / 'knowledge_contexts.jsonl')[0]
    assert result['removed_optional_null_count'] == 1
    assert 'Parent Context ID' not in row



def test_batch_decisions_are_all_or_nothing(tmp_path):
    """One process per proposal rewrote decisions.jsonl per call; a batch must
    still refuse to half-record a review."""
    from afc_card_runtime.knowledge_store import append_decisions

    kb = init_store(tmp_path / 'kb', 'test-kb')
    run_dir = kb / 'runs' / 'run-1'
    proposals = stage_proposals(None, make_candidate(run_dir), run_dir, 'run-1')
    entries = [{'proposal_id': p['Proposal ID'], 'decision': 'accept',
                'reviewer': 'PM', 'rationale': 'reviewed'} for p in proposals]

    for broken, expected in (
        (entries + [{'proposal_id': 'PROP-NOPE', 'decision': 'accept',
                     'reviewer': 'PM', 'rationale': 'x'}], KeyError),
        (entries[:1] + [{**entries[0]}], ValueError),
        ([{**entries[0], 'decision': 'looks-fine'}], ValueError),
    ):
        try:
            append_decisions(run_dir, broken)
        except expected:
            pass
        else:
            raise AssertionError(f'append_decisions accepted {broken!r}')
        assert read_jsonl(run_dir / 'decisions.jsonl') == [], 'a rejected batch wrote decisions'

    recorded = append_decisions(run_dir, entries)
    assert len(recorded) == len(proposals)
    assert {row['Decision'] for row in read_jsonl(run_dir / 'decisions.jsonl')} == {'accept'}


def test_decide_accepts_a_decisions_file_and_rejects_unknown_flags(tmp_path):
    """`decide` once per proposal does not scale to a real release, and
    parse_known_args() used to swallow a mistyped governance flag."""
    import subprocess

    kb = init_store(tmp_path / 'kb', 'test-kb')
    run_dir = kb / 'runs' / 'run-1'
    proposals = stage_proposals(None, make_candidate(run_dir), run_dir, 'run-1')
    decisions_file = tmp_path / 'decisions.jsonl'
    write_rows(decisions_file, [
        # the canonical proposals.jsonl spelling must work as well
        {'Proposal ID': p['Proposal ID'], 'Decision': 'accept',
         'Reviewer': 'PM: reviewer', 'Rationale': 'reviewed in batch'}
        for p in proposals
    ])

    def run(*args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts' / 'knowledge_base.py'), *args],
                              capture_output=True, text=True, cwd=ROOT)

    proc = run('decide', '--kb-root', str(kb), '--run-id', 'run-1',
               '--decisions-file', str(decisions_file))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)['decisions'] == len(proposals)
    assert len(read_jsonl(run_dir / 'decisions.jsonl')) == len(proposals)

    proc = run('decide', '--kb-root', str(kb), '--run-id', 'run-1',
               '--decisions-file', str(decisions_file), '--decision', 'accept')
    assert proc.returncode == 1 and 'not both' in proc.stderr

    # A mistyped optional flag must fail instead of being ignored.
    proc = run('index', '--kb-root', str(kb), '--rebuldd')
    assert proc.returncode == 2 and 'unrecognized arguments' in proc.stderr
    proc = run('publish', '--kb-root', str(kb), '--run-id', 'run-1',
               '--accepted-quality-risk-by', 'PM')
    assert proc.returncode == 2 and 'unrecognized arguments' in proc.stderr
