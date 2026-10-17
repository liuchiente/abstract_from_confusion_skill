"""Stable Card/Evidence identity tests.

v0.4.1 validated only the ID *format* and left numbering to the model, while
Card delta, rerun novelty, `afc-curate`'s "never renumber" rule and all Gold
regression depended on the IDs being stable across runs.
"""
from afc_card_runtime.ids import (CARD_PREFIX, EVIDENCE_PREFIX, IdRegistry,
                                  card_claim_key, card_identity, evidence_identity)


EVD = {'Evidence ID': 'EVD-000001', 'Evidence Mode': 'VERBATIM', 'Evidence Kind': 'Message',
       'Original Text': 'Tải lên thất bại', 'Source': 'spec.docx',
       'Source Location': 'Table 1 / Row 2 / Cell 3',
       'Source Unit IDs': ['spec.docx::B1::T001::R0002']}

CARD = {'Card ID': 'CARD-000001', 'Card Type': 'Rule', 'Concept Key': 'upload-failure',
        'Title': '上傳失敗顯示錯誤訊息', 'Content': '...', 'Scope': 'CA', 'Context': 'CTX-001',
        'Source': 'spec.docx', 'Source Location': 'Table 1 / Row 2',
        'Evidence Record IDs': ['EVD-000001']}


def test_evidence_identity_ignores_whitespace_only_changes():
    a = dict(EVD)
    b = dict(EVD, **{'Original Text': 'Tải lên   thất bại'})
    assert evidence_identity(a) == evidence_identity(b)


def test_evidence_identity_changes_when_the_literal_changes():
    b = dict(EVD, **{'Original Text': 'Tải lên thành công'})
    assert evidence_identity(EVD) != evidence_identity(b)


def test_evidence_identity_changes_when_the_location_changes():
    b = dict(EVD, **{'Source Location': 'Table 1 / Row 3 / Cell 3'})
    assert evidence_identity(EVD) != evidence_identity(b)


def test_card_identity_survives_rewording_when_a_concept_key_exists():
    b = dict(CARD, **{'Title': '完全不同的標題', 'Content': '改寫過的內容'})
    assert card_identity(CARD) == card_identity(b)


def test_card_identity_changes_with_scope():
    b = dict(CARD, **{'Scope': 'CB'})
    assert card_identity(CARD) != card_identity(b)


def test_claim_key_disambiguates_two_claims_from_one_row():
    a = dict(CARD); a.pop('Concept Key'); a['Claim Key'] = 'claim-a'
    b = dict(CARD); b.pop('Concept Key'); b['Claim Key'] = 'claim-b'
    assert card_identity(a) != card_identity(b)


def test_claim_key_source_is_reported():
    assert card_claim_key(CARD)[1] == 'Concept Key'
    no_key = {k: v for k, v in CARD.items() if k != 'Concept Key'}
    assert card_claim_key(no_key)[1] == 'Title'


def test_registry_reuses_ids_and_never_reuses_numbers(tmp_path):
    path = tmp_path / 'reg.jsonl'
    reg = IdRegistry(path)
    first, action, _ = reg.resolve_id(EVIDENCE_PREFIX, dict(EVD, **{'Evidence ID': ''}), run_id='R1')
    assert action == 'new'
    again, action, _ = reg.resolve_id(EVIDENCE_PREFIX, dict(EVD, **{'Evidence ID': ''}), run_id='R2')
    assert (again, action) == (first, 'reused')
    other = dict(EVD, **{'Evidence ID': '', 'Original Text': 'khác'})
    third, action, _ = reg.resolve_id(EVIDENCE_PREFIX, other, run_id='R2')
    assert action == 'new' and third != first
    reg.save()
    # A reloaded registry keeps the mapping and the counter.
    reloaded = IdRegistry(path)
    assert reloaded.resolve_id(EVIDENCE_PREFIX, dict(EVD, **{'Evidence ID': ''}))[0] == first
    assert reloaded.stats()[EVIDENCE_PREFIX] == 2


def test_rebind_keeps_an_id_across_a_rewording(tmp_path):
    reg = IdRegistry(tmp_path / 'reg.jsonl')
    no_key = {k: v for k, v in CARD.items() if k != 'Concept Key'}
    cid, action, _ = reg.resolve_id(CARD_PREFIX, dict(no_key, **{'Card ID': ''}), run_id='R1')
    assert action == 'new'
    reworded = dict(no_key, **{'Card ID': cid, 'Title': '改寫後的標題'})
    same, action, _ = reg.resolve_id(CARD_PREFIX, reworded, run_id='R2')
    assert (same, action) == (cid, 'rebound')
    assert reg.by_id[cid]['identity_history']


def test_rebind_is_refused_when_two_records_claim_one_id(tmp_path):
    reg = IdRegistry(tmp_path / 'reg.jsonl')
    no_key = {k: v for k, v in CARD.items() if k != 'Concept Key'}
    cid, _, _ = reg.resolve_id(CARD_PREFIX, dict(no_key, **{'Card ID': ''}), run_id='R1')
    a = dict(no_key, **{'Card ID': cid, 'Title': 'A'})
    b = dict(no_key, **{'Card ID': cid, 'Title': 'B'})
    first, action_a, _ = reg.resolve_id(CARD_PREFIX, a, run_id='R2', reserved={cid})
    second, action_b, _ = reg.resolve_id(CARD_PREFIX, b, run_id='R2', reserved={cid})
    assert action_a == 'new' and action_b == 'new'
    assert first != second != cid
