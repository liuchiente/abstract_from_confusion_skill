#!/usr/bin/env python3
"""Draw a deterministic stratified review sample.

v0.4.1 asked the extracting model to "perform an independent, stratified
re-check" with no sample size, no stratum definition and no constraint on which
units it looked at -- so the three health reports it then wrote about its own
work were self-graded on a self-chosen sample. Here the sample is drawn by
script from a seed, and `compute_review_metrics.py` refuses verdicts that do not
cover exactly the drawn sample.

Purposes:
  saturation  selected Source Units -- is any supported knowledge or
              source-native literal/structured fact still unrepresented?
  fidelity    Cards and Evidence Records -- is every claim supported, and is
              every literal/structured source value preserved unaltered?
  atomicity   Cards at risk of bundling several independent claims.
"""
from pathlib import Path
import argparse, hashlib, json, random, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, write_jsonl, write_json, normalize_text

VERDICTS = {
    'saturation': ['complete', 'missing_card', 'missing_evidence', 'missing_both'],
    'fidelity': ['supported', 'unsupported_claim', 'altered_literal', 'dropped_structured_fact'],
    'atomicity': ['atomic_keep', 'split_required', 'ambiguous'],
}

ATOMICITY_RISK_TYPES = {'Rule', 'Process', 'Condition', 'Exception', 'Mapping'}


def seed_int(*parts):
    blob = '|'.join(str(p) for p in parts)
    return int(hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16], 16)


def stratum_key(row, fields):
    vals = []
    for f in fields:
        v = row.get(f)
        if isinstance(v, (list, tuple)):
            v = ','.join(sorted(normalize_text(x) for x in v))
        vals.append(normalize_text(v) or '(none)')
    return ' | '.join(vals) if vals else '(all)'


def allocate(strata_sizes, n):
    """Proportional allocation with a floor of one per non-empty stratum."""
    total = sum(strata_sizes.values())
    if total == 0:
        return {}
    if n >= total:
        return dict(strata_sizes)
    keys = sorted(strata_sizes)
    alloc = {k: 1 if strata_sizes[k] else 0 for k in keys}
    remaining = n - sum(alloc.values())
    if remaining < 0:
        # More strata than the budget: keep the largest strata only.
        order = sorted(keys, key=lambda k: (-strata_sizes[k], k))
        alloc = {k: 0 for k in keys}
        for k in order[:n]:
            alloc[k] = 1
        return alloc
    shares = []
    for k in keys:
        free = strata_sizes[k] - alloc[k]
        if free <= 0:
            continue
        want = remaining * (strata_sizes[k] / total)
        shares.append([k, int(want), want - int(want), free])
    for item in shares:
        k, base, _, free = item
        add = min(base, free)
        alloc[k] += add
        remaining -= add
    shares.sort(key=lambda x: (-x[2], x[0]))
    i = 0
    while remaining > 0 and shares:
        k, _, _, _ = shares[i % len(shares)]
        if alloc[k] < strata_sizes[k]:
            alloc[k] += 1
            remaining -= 1
        elif all(alloc[s[0]] >= strata_sizes[s[0]] for s in shares):
            break
        i += 1
    return alloc


def draw(candidates, id_field, strata_fields, n, seed):
    buckets = {}
    for row in candidates:
        buckets.setdefault(stratum_key(row, strata_fields), []).append(row)
    sizes = {k: len(v) for k, v in buckets.items()}
    alloc = allocate(sizes, n)
    rng = random.Random(seed)
    picked, detail = [], {}
    for key in sorted(buckets):
        pool = sorted(buckets[key], key=lambda r: normalize_text(r.get(id_field)))
        take = min(alloc.get(key, 0), len(pool))
        chosen = rng.sample(pool, take) if take else []
        chosen.sort(key=lambda r: normalize_text(r.get(id_field)))
        detail[key] = {'population': len(pool), 'sampled': len(chosen)}
        picked.extend(chosen)
    return picked, detail, sizes


def main():
    ap = argparse.ArgumentParser(description='Draw a deterministic stratified AFC review sample.')
    ap.add_argument('--purpose', required=True, choices=sorted(VERDICTS))
    ap.add_argument('--source-map', help='Required for purpose=saturation')
    ap.add_argument('--cards', help='Required for purpose=fidelity/atomicity')
    ap.add_argument('--evidence', help='Optional extra population for purpose=fidelity')
    ap.add_argument('-n', '--sample-size', type=int, default=40)
    ap.add_argument('--strata', default='', help='Comma-separated fields to stratify on; '
                                                'defaults per purpose when omitted')
    ap.add_argument('--run-id', default='', help='Included in the seed so each run draws its own sample')
    ap.add_argument('--seed', help='Explicit seed; overrides --run-id derivation')
    ap.add_argument('-o', '--output', required=True, help='Sample manifest JSON')
    ap.add_argument('--verdict-template', help='Write a pre-filled verdict JSONL to complete')
    a = ap.parse_args()

    if a.purpose == 'saturation':
        if not a.source_map:
            ap.error('--source-map is required for purpose=saturation')
        pop = [r for r in read_jsonl(a.source_map) if r.get('selected') and r.get('source_unit_id')]
        id_field, item_type = 'source_unit_id', 'source_unit'
        strata = a.strata or 'kind,knowledge_signal_types'
    elif a.purpose == 'atomicity':
        if not a.cards:
            ap.error('--cards is required for purpose=atomicity')
        cards = read_jsonl(a.cards)
        pop = [c for c in cards
               if normalize_text(c.get('Card Type')) in ATOMICITY_RISK_TYPES
               or len(str(c.get('Content') or '')) >= 160
               or str(c.get('Content') or '').count('\n') >= 2]
        id_field, item_type = 'Card ID', 'card'
        strata = a.strata or 'Card Type'
    else:
        if not a.cards:
            ap.error('--cards is required for purpose=fidelity')
        pop = [dict(c, _item_type='card') for c in read_jsonl(a.cards)]
        if a.evidence:
            pop += [dict(e, _item_type='evidence', **{'Card ID': e.get('Evidence ID')})
                    for e in read_jsonl(a.evidence)]
        id_field, item_type = 'Card ID', 'mixed'
        strata = a.strata or '_item_type,Card Type'

    strata_fields = [x.strip() for x in strata.split(',') if x.strip()]
    seed = int(a.seed) if a.seed else seed_int(a.run_id, a.purpose, a.sample_size, strata)
    picked, detail, sizes = draw(pop, id_field, strata_fields, a.sample_size, seed)

    items = []
    for row in picked:
        items.append({
            'item_type': row.get('_item_type', item_type),
            'item_id': normalize_text(row.get(id_field)),
            'stratum': stratum_key(row, strata_fields),
        })
    manifest = {
        'sample_schema_version': '1',
        'purpose': a.purpose,
        'run_id': a.run_id or None,
        'seed': seed,
        'strata_fields': strata_fields,
        'population': len(pop),
        'requested_sample_size': a.sample_size,
        'sample_count': len(items),
        'strata': detail,
        'allowed_verdicts': VERDICTS[a.purpose],
        'items': items,
        'note': ('The sample is drawn deterministically from (run_id, purpose, size, strata). '
                 'compute_review_metrics.py accepts verdicts only for exactly these item ids.'),
    }
    write_json(a.output, manifest)
    if a.verdict_template:
        write_jsonl(a.verdict_template, [
            {'purpose': a.purpose, 'item_type': it['item_type'], 'item_id': it['item_id'],
             'verdict': '', 'note': ''} for it in items])
    print(json.dumps({k: v for k, v in manifest.items() if k != 'items'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
