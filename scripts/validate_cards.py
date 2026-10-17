#!/usr/bin/env python3
"""Cross-file checks on Knowledge Cards.

Field shapes, enums and required keys belong to schemas/knowledge-card.schema.json
and are checked by validate_schema.py. v0.4.1's hand-written checks had drifted
from that schema in both directions (it ignored the required `Source Location`;
it required a non-empty `Content` the schema never asked for), so this script
now covers only what a schema cannot express, and the `Content` rule is a
warning with an explicit rationale instead of a silent divergence.
"""
from pathlib import Path
import argparse, json, re, sys
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, write_json, normalize_text

ALLOWED = {'Concept', 'Context', 'Field', 'Rule', 'Definition', 'Process',
           'Condition', 'Mapping', 'Exception', 'Reference', 'Note'}
CONTENT_OPTIONAL = {'Concept', 'Context'}
ID_RE = re.compile(r'^CARD-\d{6}$')


def main():
    ap = argparse.ArgumentParser(description='Validate AFC Knowledge Card identity, references and lifecycle.')
    ap.add_argument('input')
    ap.add_argument('--json-output')
    a = ap.parse_args()
    rows = read_jsonl(a.input)
    errors, warnings = [], []
    ids = set()
    for i, r in enumerate(rows, 1):
        cid = normalize_text(r.get('Card ID'))
        typ = r.get('Card Type')
        if not ID_RE.match(cid):
            errors.append(f'row {i}: invalid Card ID {cid!r} (allocate with scripts/allocate_ids.py)')
        if cid in ids:
            errors.append(f'row {i}: duplicate Card ID {cid}')
        ids.add(cid)
        if typ not in ALLOWED:
            errors.append(f'row {i}: invalid Card Type {typ!r}')
        if not normalize_text(r.get('Source')):
            errors.append(f'row {i} {cid}: missing Source')
        if not normalize_text(r.get('Source Location')):
            errors.append(f'row {i} {cid}: missing Source Location')
        if not normalize_text(r.get('Content')) and typ not in CONTENT_OPTIONAL:
            warnings.append(f'row {i} {cid}: empty Content on a {typ} Card; a claim with no text '
                            f'cannot be retrieved or reviewed')
        if typ not in CONTENT_OPTIONAL and not (normalize_text(r.get('Concept Key'))
                                                or normalize_text(r.get('Claim Key'))):
            warnings.append(f'row {i} {cid}: no Concept Key / Claim Key, so the Card ID is identified '
                            f'by Title and will churn when the wording changes')
        status = normalize_text(r.get('Status')) or 'Active'
        if status not in {'Active', 'Superseded', 'Retired'}:
            errors.append(f'row {i} {cid}: invalid Status {status!r}')
        if status == 'Superseded' and not normalize_text(r.get('Superseded By')):
            errors.append(f'row {i} {cid}: Status=Superseded requires Superseded By')
        if normalize_text(r.get('Superseded By')) and status == 'Active':
            warnings.append(f'row {i} {cid}: has Superseded By while Status is Active')

    # Dangling lifecycle and relationship references inside the Card set.
    for i, r in enumerate(rows, 1):
        cid = normalize_text(r.get('Card ID'))
        sb = normalize_text(r.get('Superseded By'))
        if sb and sb not in ids:
            errors.append(f'row {i} {cid}: Superseded By {sb} is not in this Card set')
        if sb == cid and sb:
            errors.append(f'row {i} {cid}: Superseded By points at itself')
        for ref in r.get('Supersedes') or []:
            if normalize_text(ref) not in ids:
                errors.append(f'row {i} {cid}: Supersedes {ref} is not in this Card set')
        for ref in r.get('Related Card IDs') or []:
            if normalize_text(ref) not in ids:
                warnings.append(f'row {i} {cid}: Related Card ID {ref} is not in this Card set')

    types = Counter(normalize_text(r.get('Card Type')) for r in rows)
    result = {'cards': len(rows), 'card_types': dict(types),
              'errors': errors, 'warnings': warnings,
              'error_count': len(errors), 'warning_count': len(warnings),
              'status': 'PASS' if not errors else 'FAIL'}
    print(f'cards={len(rows)} errors={len(errors)} warnings={len(warnings)}')
    for e in errors[:100]:
        print('ERROR', e)
    for w in warnings[:100]:
        print('WARN', w)
    if a.json_output:
        write_json(a.json_output, result)
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
