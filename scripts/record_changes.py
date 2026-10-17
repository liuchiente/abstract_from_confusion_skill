#!/usr/bin/env python3
"""Append knowledge-change records by comparing two runs.

`afc-validate` layer 7 asks for current value, historical value, change record
and replacement semantics. In v0.4.1 the data model had nowhere to put any of
that -- Cards were rebuilt from the documents every run and only `replaces`
links existed -- so that whole validation layer had nothing to check.

Now that Card/Evidence IDs are stable (scripts/allocate_ids.py), a run can be
diffed against the previous one and the result appended to
work/knowledge-change-log.jsonl. Evidence changes keep the verbatim previous
value, which is the part a historical-value question actually needs.
"""
from pathlib import Path
import argparse, datetime, json, re, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, read_json, write_jsonl, write_json, normalize_text
from afc_card_runtime.config import load_settings

CHG_RE = re.compile(r'^CHG-(\d{6})$')

CARD_CLAIM_FIELDS = ('Card Type', 'Title', 'Content', 'Scope', 'Scopes', 'Context', '中文補充')
EVIDENCE_LITERAL_FIELDS = (
    'Original Text', 'Source Language', 'Original Name', 'Original Description',
    'Original Message', 'Original Component Type', 'Original Code', 'Original Value',
    'Original Label', 'Original Placeholder', 'Original Required', 'Original Max Length',
    'Original Min Length', 'Original Format', 'Original Validation Message',
    'Original Error Message', 'Original Option Values', 'Original Function Code',
    'Structured Facts',
)
LOCATION_FIELDS = ('Source', 'Source Location', 'Source Version', 'Source Date')


def by_id(rows, field):
    return {normalize_text(r.get(field)): r for r in rows if normalize_text(r.get(field))}


def changed_fields(old, new, fields):
    out = []
    for f in fields:
        a, b = old.get(f), new.get(f)
        if isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
            same = json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)
        else:
            same = normalize_text(a) == normalize_text(b)
        if not same:
            out.append(f)
    return out


def summary(rec, fields):
    parts = []
    for f in fields:
        v = rec.get(f)
        if v in (None, '', []):
            continue
        if isinstance(v, (list, dict)):
            v = json.dumps(v, ensure_ascii=False, sort_keys=True)
        parts.append(f'{f}={v}')
    return ' | '.join(parts)


def main():
    s = load_settings()
    ap = argparse.ArgumentParser(description='Append AFC knowledge-change records for this run.')
    ap.add_argument('--cards', required=True)
    ap.add_argument('--evidence')
    ap.add_argument('--previous-cards')
    ap.add_argument('--previous-evidence')
    ap.add_argument('--log', default=str(s.resolve('artifacts.change_log')))
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--decision', help='Path to the decision artifact that accepted this run')
    ap.add_argument('--json-output')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    cards = by_id(read_jsonl(a.cards), 'Card ID')
    prev_cards = by_id(read_jsonl(a.previous_cards), 'Card ID') if a.previous_cards else {}
    evidence = by_id(read_jsonl(a.evidence), 'Evidence ID') if a.evidence else {}
    prev_evidence = by_id(read_jsonl(a.previous_evidence), 'Evidence ID') if a.previous_evidence else {}

    existing = read_jsonl(a.log)
    next_n = 0
    for row in existing:
        m = CHG_RE.match(normalize_text(row.get('Change ID')))
        if m:
            next_n = max(next_n, int(m.group(1)))
    observed_at = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    decision_ref = None
    if a.decision and Path(a.decision).exists():
        d = read_json(a.decision) or {}
        decision_ref = f"{a.decision}#{d.get('health_snapshot_sha256', '')[:12]}"

    new_rows = []

    def emit(change_type, object_type, object_id, rec, previous=None, current=None, notes=''):
        nonlocal next_n
        next_n += 1
        new_rows.append({
            'Change ID': f'CHG-{next_n:06d}',
            'Change Type': change_type,
            'Object Type': object_type,
            'Object ID': object_id,
            'Observed Run': a.run_id,
            'Observed At': observed_at,
            'Previous Value': previous,
            'Current Value': current,
            'Superseded By': normalize_text(rec.get('Superseded By')) or None,
            'Source': normalize_text(rec.get('Source')),
            'Source Location': normalize_text(rec.get('Source Location')),
            'Source Version': normalize_text(rec.get('Source Version')) or None,
            'Source Date': normalize_text(rec.get('Source Date')) or None,
            'Decision Reference': decision_ref,
            'Notes': notes,
        })

    first_run = not (prev_cards or prev_evidence)

    for eid, rec in sorted(evidence.items()):
        old = prev_evidence.get(eid)
        if old is None:
            if not first_run:
                emit('Evidence Added', 'Evidence', eid, rec,
                     current=summary(rec, EVIDENCE_LITERAL_FIELDS))
            continue
        lit = changed_fields(old, rec, EVIDENCE_LITERAL_FIELDS)
        loc = changed_fields(old, rec, LOCATION_FIELDS)
        if lit:
            # A source-preserving record whose literal text changed is either a
            # genuine source change or a fidelity failure. Either way it must be
            # visible, with the previous value retained.
            emit('Evidence Changed', 'Evidence', eid, rec,
                 previous=summary(old, EVIDENCE_LITERAL_FIELDS),
                 current=summary(rec, EVIDENCE_LITERAL_FIELDS),
                 notes='changed fields: ' + ', '.join(lit))
        elif loc:
            emit('Source Version Update', 'Evidence', eid, rec,
                 previous=summary(old, LOCATION_FIELDS),
                 current=summary(rec, LOCATION_FIELDS),
                 notes='changed fields: ' + ', '.join(loc))
    for eid, old in sorted(prev_evidence.items()):
        if eid not in evidence:
            emit('Retired', 'Evidence', eid, old,
                 previous=summary(old, EVIDENCE_LITERAL_FIELDS),
                 notes='present in the previous run, absent now')

    for cid, rec in sorted(cards.items()):
        old = prev_cards.get(cid)
        status = normalize_text(rec.get('Status')) or 'Active'
        if old is None:
            if not first_run:
                emit('Added', 'Card', cid, rec, current=summary(rec, CARD_CLAIM_FIELDS))
            continue
        old_status = normalize_text(old.get('Status')) or 'Active'
        claim = changed_fields(old, rec, CARD_CLAIM_FIELDS)
        ev = changed_fields(old, rec, ('Evidence Record IDs',))
        if status != old_status and status in {'Superseded', 'Retired'}:
            emit(status, 'Card', cid, rec, previous=summary(old, CARD_CLAIM_FIELDS),
                 current=summary(rec, CARD_CLAIM_FIELDS), notes=f'{old_status} -> {status}')
        elif status == 'Active' and old_status in {'Superseded', 'Retired'}:
            emit('Restored', 'Card', cid, rec, previous=old_status, current=status)
        elif claim and not ev:
            # Same evidence basis, different normalized claim: a reinterpretation.
            emit('Reinterpretation', 'Card', cid, rec, previous=summary(old, CARD_CLAIM_FIELDS),
                 current=summary(rec, CARD_CLAIM_FIELDS), notes='changed fields: ' + ', '.join(claim))
        elif claim or ev:
            emit('Updated', 'Card', cid, rec, previous=summary(old, CARD_CLAIM_FIELDS),
                 current=summary(rec, CARD_CLAIM_FIELDS),
                 notes='changed fields: ' + ', '.join(claim + ev))
    for cid, old in sorted(prev_cards.items()):
        if cid not in cards:
            emit('Retired', 'Card', cid, old, previous=summary(old, CARD_CLAIM_FIELDS),
                 notes='present in the previous run, absent now')

    result = {
        'log': str(a.log), 'run_id': a.run_id, 'first_run': first_run,
        'cards': len(cards), 'evidence': len(evidence),
        'previous_cards': len(prev_cards), 'previous_evidence': len(prev_evidence),
        'new_change_records': len(new_rows),
        'by_change_type': {},
        'decision_reference': decision_ref,
        'dry_run': bool(a.dry_run),
    }
    for row in new_rows:
        k = row['Change Type']
        result['by_change_type'][k] = result['by_change_type'].get(k, 0) + 1
    fidelity_alerts = [r['Object ID'] for r in new_rows if r['Change Type'] == 'Evidence Changed']
    result['evidence_changed_ids'] = fidelity_alerts[:50]
    result['status'] = 'REVIEW' if fidelity_alerts else 'PASS'
    if fidelity_alerts:
        result['note'] = ('Source-preserving Evidence text changed. Confirm the source really changed; '
                          'otherwise this is a fidelity regression, not a knowledge change.')
    if first_run:
        result['note'] = 'No previous run supplied, so the current state was treated as the baseline.'

    if not a.dry_run and new_rows:
        write_jsonl(a.log, existing + new_rows)
    if a.json_output:
        write_json(a.json_output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
