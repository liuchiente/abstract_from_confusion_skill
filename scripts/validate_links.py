#!/usr/bin/env python3
"""Cross-file checks on Card Links.

Shapes and the Link Type enum live in schemas/knowledge-link.schema.json.
v0.4.1 still accepted new `belongs_to` links silently even though afc-links
declares them legacy-only (Step 3 Box Membership owns contextual membership);
they are now reported as warnings so a migration can actually be finished.
"""
from pathlib import Path
import argparse, re, sys
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, write_json, normalize_text

ALLOWED = {'instance_of', 'applies_to', 'defines', 'controls', 'depends_on',
           'references', 'conflicts_with', 'replaces', 'alias_of'}
LEGACY = {'belongs_to'}
SYMMETRIC = {'conflicts_with', 'alias_of'}
ID_RE = re.compile(r'^LINK-\d{6}$')


def main():
    ap = argparse.ArgumentParser(description='Validate AFC Card Links against the current Card set.')
    ap.add_argument('links')
    ap.add_argument('--cards', required=True)
    ap.add_argument('--json-output')
    a = ap.parse_args()
    cards = read_jsonl(a.cards)
    valid = {normalize_text(r.get('Card ID')) for r in cards if r.get('Card ID')}
    rows = read_jsonl(a.links)
    errors, warnings = [], []
    seen_ids, seen_edges = set(), {}
    for i, r in enumerate(rows, 1):
        lid = normalize_text(r.get('Link ID'))
        lt = normalize_text(r.get('Link Type'))
        src = normalize_text(r.get('Source Card ID'))
        tgt = normalize_text(r.get('Target Card ID'))
        if lid and not ID_RE.match(lid):
            warnings.append(f'row {i}: Link ID {lid!r} does not match LINK-nnnnnn')
        if lid:
            if lid in seen_ids:
                errors.append(f'row {i}: duplicate Link ID {lid}')
            seen_ids.add(lid)
        if lt in LEGACY:
            warnings.append(f'row {i}: {lt} is legacy-only; contextual membership belongs to '
                            f'Step 3 Box Membership. Migrate {src} -> {tgt}.')
        elif lt not in ALLOWED:
            errors.append(f'row {i}: invalid Link Type {lt!r}')
        if src not in valid:
            errors.append(f'row {i}: source Card {src!r} is not in the Card set')
        if tgt not in valid:
            errors.append(f'row {i}: target Card {tgt!r} is not in the Card set')
        if src and src == tgt:
            errors.append(f'row {i}: self link on {src}')
        if not normalize_text(r.get('Evidence')):
            warnings.append(f'row {i}: link {src} --{lt}--> {tgt} has no Evidence')
        key = (tuple(sorted((src, tgt))) if lt in SYMMETRIC else (src, tgt), lt)
        if key in seen_edges:
            warnings.append(f'row {i}: duplicate edge {src} --{lt}--> {tgt} '
                            f'(also row {seen_edges[key]})')
        else:
            seen_edges[key] = i

    result = {'links': len(rows), 'link_types': dict(Counter(normalize_text(r.get('Link Type')) for r in rows)),
              'legacy_belongs_to': sum(1 for r in rows if normalize_text(r.get('Link Type')) in LEGACY),
              'errors': errors, 'warnings': warnings,
              'error_count': len(errors), 'warning_count': len(warnings),
              'status': 'PASS' if not errors else 'FAIL'}
    print(f'links={len(rows)} errors={len(errors)} warnings={len(warnings)}')
    for e in errors[:100]:
        print('ERROR', e)
    for w in warnings[:100]:
        print('WARN', w)
    if a.json_output:
        write_json(a.json_output, result)
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
