#!/usr/bin/env python3
"""Assign stable Card / Evidence IDs from a content-derived registry.

Step 1 writes Cards and Evidence Records with any local placeholder IDs
(`EVD-TMP-1`, `tmp:msg-a`, ...) or with the IDs a previous run produced. This
script resolves them against a registry keyed on content identity, so the same
source fact keeps the same ID across reruns and the Card delta / rerun-novelty /
Gold-regression machinery has a real foundation instead of model-chosen numbers.

Evidence is resolved first because Card identity includes its Evidence IDs.
"""
from pathlib import Path
import argparse
import json
import sys
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, write_jsonl, write_json, normalize_text
from afc_card_runtime.config import load_settings
from afc_card_runtime.ids import IdRegistry, CARD_PREFIX, EVIDENCE_PREFIX, ID_RE, card_claim_key


def _ids(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [normalize_text(x) for x in value if normalize_text(x)]
    return [normalize_text(value)] if normalize_text(value) else []


def _resolve_all(reg, prefix, records, id_field, run_id):
    """Resolve a whole dataset, reserving IDs so two records cannot claim one."""
    claimed = [normalize_text(r.get(id_field)) for r in records]
    reserved = Counter(c for c in claimed if c and ID_RE[prefix].match(c))
    id_map, actions = {}, Counter()
    for rec, claim in zip(records, claimed):
        # An ID claimed by more than one record cannot be rebound to either.
        blocked = {c for c, n in reserved.items() if n > 1}
        rid, action, _ = reg.resolve_id(prefix, rec, run_id=run_id, claimed_id=claim, reserved=blocked)
        actions[action] += 1
        if claim:
            id_map[claim] = rid
        rec[id_field] = rid
        rec.setdefault('Status', 'Active')
        if action == 'new' and run_id:
            rec.setdefault('First Seen Run', run_id)
        if run_id:
            rec['Last Seen Run'] = run_id
    return id_map, dict(actions)


def main():
    s = load_settings()
    ap = argparse.ArgumentParser(description='Allocate stable Card/Evidence IDs from the AFC ID registry.')
    ap.add_argument('--cards')
    ap.add_argument('--evidence')
    ap.add_argument('--registry', default=str(s.resolve('artifacts.id_registry')))
    ap.add_argument('--cards-output', help='Defaults to rewriting --cards in place')
    ap.add_argument('--evidence-output', help='Defaults to rewriting --evidence in place')
    ap.add_argument('--run-id', default='', help='Run identifier recorded as First/Last Seen Run')
    ap.add_argument('--json-output')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--require-concept-key', action='store_true',
                    help='Fail when a non-Concept Card has no Concept Key / Claim Key')
    a = ap.parse_args()
    if not a.cards and not a.evidence:
        ap.error('Provide --cards and/or --evidence')

    reg = IdRegistry(a.registry)
    run_id = a.run_id or None
    cards = read_jsonl(a.cards) if a.cards else []
    evidence = read_jsonl(a.evidence) if a.evidence else []

    evidence_map, evidence_actions = _resolve_all(reg, EVIDENCE_PREFIX, evidence, 'Evidence ID', run_id)

    # Point Cards at the resolved Evidence IDs before deriving Card identity.
    unknown_evidence_refs = []
    for rec in cards:
        resolved = []
        for r in _ids(rec.get('Evidence Record IDs')):
            if r in evidence_map:
                resolved.append(evidence_map[r])
            elif ID_RE[EVIDENCE_PREFIX].match(r) and r in reg.by_id:
                resolved.append(r)
            else:
                unknown_evidence_refs.append({'card': normalize_text(rec.get('Card ID')), 'evidence_ref': r})
        rec['Evidence Record IDs'] = list(dict.fromkeys(resolved))

    # A Card whose identity rests on its Title churns its ID whenever the
    # wording changes. Surface that instead of letting it degrade silently.
    title_keyed = []
    for rec in cards:
        _, field = card_claim_key(rec)
        if field == 'Title' and normalize_text(rec.get('Card Type')) != 'Concept':
            title_keyed.append(normalize_text(rec.get('Card ID')) or normalize_text(rec.get('Title')))

    card_map, card_actions = _resolve_all(reg, CARD_PREFIX, cards, 'Card ID', run_id)

    # Rewrite every cross-reference that used a pre-allocation ID.
    for rec in evidence:
        rec['Card IDs'] = list(dict.fromkeys(card_map.get(c, c) for c in _ids(rec.get('Card IDs'))))
    for rec in cards:
        if rec.get('Related Card IDs'):
            rec['Related Card IDs'] = list(dict.fromkeys(
                card_map.get(c, c) for c in _ids(rec.get('Related Card IDs'))))
        if rec.get('Superseded By'):
            rec['Superseded By'] = card_map.get(normalize_text(rec['Superseded By']), rec['Superseded By'])

    def _collisions(records, field):
        counts = Counter(normalize_text(r.get(field)) for r in records)
        return sorted([k for k, n in counts.items() if k and n > 1])

    collisions = {'cards': _collisions(cards, 'Card ID'), 'evidence': _collisions(evidence, 'Evidence ID')}

    result = {
        'registry': str(reg.path),
        'run_id': run_id,
        'cards_in': len(cards), 'card_actions': card_actions,
        'evidence_in': len(evidence), 'evidence_actions': evidence_actions,
        'card_id_map': card_map, 'evidence_id_map': evidence_map,
        'unknown_evidence_refs': unknown_evidence_refs,
        'title_keyed_cards': title_keyed[:50],
        'title_keyed_card_count': len(title_keyed),
        'identity_collisions': collisions,
        'registry_counters': reg.stats(),
        'dry_run': bool(a.dry_run),
    }
    errors = []
    if unknown_evidence_refs:
        errors.append(f'{len(unknown_evidence_refs)} Card->Evidence references could not be resolved')
    if collisions['cards'] or collisions['evidence']:
        errors.append('two records resolved to the same ID; add a distinct Claim Key')
    if a.require_concept_key and title_keyed:
        errors.append(f'{len(title_keyed)} non-Concept Cards have no Concept Key / Claim Key')
    result['errors'] = errors
    result['status'] = 'FAIL' if errors else ('REVIEW' if title_keyed else 'PASS')
    if title_keyed and not a.require_concept_key:
        result['note'] = ('Cards without Concept Key / Claim Key are identified by Title, '
                          'so their IDs change when the wording changes. Add a Concept Key '
                          'to make them stable across reruns.')

    if not a.dry_run and result['status'] != 'FAIL':
        if a.evidence:
            write_jsonl(a.evidence_output or a.evidence, evidence)
        if a.cards:
            write_jsonl(a.cards_output or a.cards, cards)
        reg.save()
    if a.json_output:
        write_json(a.json_output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['status'] != 'FAIL' else 2)


if __name__ == '__main__':
    main()
