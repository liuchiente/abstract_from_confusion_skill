#!/usr/bin/env python3
"""Score a Step 1 run against the gold set's known answers.

`evaluate_card_health.py` measures a run against itself: coverage, saturation,
atomicity, all computed from the run's own output. It cannot tell you the
extraction is wrong, only that it is internally complete. So a change to a
skill's wording could make extraction worse and every existing check would
still pass.

This measures a run against expectations a person wrote down:

  literal preservation   a named source string appears verbatim in Evidence
  claim coverage         each claim is covered by a Card citing the right unit
  fabrication            a fact the source does not state appears nowhere
  accounting             every selected Source Unit has one disposition

Nothing here asserts how a Card is phrased. Wording is free; preserving the
source, covering the claim and not inventing facts are not.

  ./afc score_extraction_gold.py --gold gold/afc-gold-v1 \\
      --cards work/step-card-1-cards.jsonl \\
      --evidence work/step-card-1-evidence.jsonl \\
      --coverage work/step-card-1-coverage.jsonl \\
      --source-map work/step-card-0-source-map.jsonl
"""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import normalize_text, read_json, read_jsonl, write_json
from afc_card_runtime.config import load_settings

try:
    import yaml
except Exception:  # pragma: no cover - yaml is a hard requirement at runtime
    yaml = None

EVIDENCE_TEXT_FIELDS = (
    'Original Text', 'Original Error Message', 'Original Message', 'Original Value',
    'Original Label', 'Original Code', 'Original Max Length', 'Original Name',
    'Original Option Values', 'Original Validation Message', 'Original Component Type',
    'visual_original_text',
)
CARD_TEXT_FIELDS = ('Title', 'Content', 'Statement', 'Note')


def evidence_strings(record):
    """Every literal a record claims to preserve, verbatim."""
    out = []
    for field in EVIDENCE_TEXT_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and value:
            out.append(value)
        elif isinstance(value, list):
            out.extend(str(x) for x in value if x)
    facts = record.get('Structured Facts')
    if isinstance(facts, dict):
        out.extend(str(v) for v in facts.values() if v not in (None, ''))
    elif isinstance(facts, list):
        out.extend(str(x) for x in facts if x)
    return out


def card_text(card):
    return ' '.join(str(card.get(f) or '') for f in CARD_TEXT_FIELDS)


def main():
    settings = load_settings()
    ap = argparse.ArgumentParser(description='Score a Step 1 run against the gold set.')
    ap.add_argument('--gold', required=True, help='Gold set directory, e.g. gold/afc-gold-v1')
    ap.add_argument('--cards', required=True)
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--coverage')
    ap.add_argument('--source-map')
    ap.add_argument('--min-literal-preservation', type=float,
                    default=settings.get('gold.min_literal_preservation', 1.0))
    ap.add_argument('--min-claim-coverage', type=float,
                    default=settings.get('gold.min_claim_coverage', 0.9))
    ap.add_argument('--json-output')
    a = ap.parse_args()

    if yaml is None:
        ap.error('PyYAML is required to read the gold expectations')
    gold = Path(a.gold)
    expectations = yaml.safe_load((gold / 'expected-claims.yaml').read_text(encoding='utf-8')) or {}

    cards = read_jsonl(a.cards)
    evidence = read_jsonl(a.evidence)
    coverage = read_jsonl(a.coverage) if a.coverage else []
    source_map = read_jsonl(a.source_map) if a.source_map else []

    if not cards and not evidence:
        print(json.dumps({'status': 'FAIL', 'reason': 'no Cards and no Evidence to score; '
                                                      'run Step 1 first'},
                         ensure_ascii=False, indent=2))
        raise SystemExit(2)

    # --- literal preservation -------------------------------------------
    all_evidence_strings = {s for record in evidence for s in evidence_strings(record)}
    literal_rows, literal_required, literal_kept = [], 0, 0
    for item in expectations.get('literals') or []:
        text = str(item['text'])
        kept = any(text in s for s in all_evidence_strings)
        optional = bool(item.get('optional'))
        if not optional:
            literal_required += 1
            literal_kept += int(kept)
        literal_rows.append({'text': text, 'kind': item.get('kind'),
                             'optional': optional, 'preserved': kept,
                             'units': item.get('units') or []})

    # --- claim coverage --------------------------------------------------
    evidence_units = {}
    for record in evidence:
        for unit in record.get('Source Unit IDs') or []:
            evidence_units.setdefault(str(record.get('Evidence ID')), set()).add(str(unit))
    claim_rows, claims_covered = [], 0
    for claim in expectations.get('claims') or []:
        wanted_units = {str(u) for u in claim.get('cited_units') or []}
        terms = [normalize_text(t) for t in claim.get('requires_any_terms') or []]
        matches = []
        for card in cards:
            text = normalize_text(card_text(card))
            if terms and not any(term in text for term in terms):
                continue
            cited = set()
            for eid in card.get('Evidence Record IDs') or []:
                cited |= evidence_units.get(str(eid), set())
            cited |= {str(u) for u in card.get('Source Unit IDs') or []}
            if not wanted_units or (cited & wanted_units):
                matches.append(card.get('Card ID'))
        covered = bool(matches)
        claims_covered += int(covered)
        claim_rows.append({'id': claim['id'], 'covered': covered,
                           'cards': matches[:5], 'cited_units': sorted(wanted_units)})

    # --- fabrication ------------------------------------------------------
    fabrications = []
    for item in expectations.get('forbidden') or []:
        text = str(item['text'])
        hits = [c.get('Card ID') for c in cards if text in card_text(c)]
        if hits:
            fabrications.append({'text': text, 'cards': hits[:5], 'why': item.get('why')})

    # --- accounting -------------------------------------------------------
    selected = {str(r.get('source_unit_id')) for r in source_map if r.get('selected')}
    accounted = {str(r.get('Source Unit ID')) for r in coverage if r.get('Disposition')}
    unaccounted = sorted(selected - accounted) if selected else []

    literal_rate = (literal_kept / literal_required) if literal_required else None
    claim_rate = (claims_covered / len(claim_rows)) if claim_rows else None
    failures = []
    if literal_rate is not None and literal_rate < a.min_literal_preservation:
        failures.append('literal preservation below the floor')
    if claim_rate is not None and claim_rate < a.min_claim_coverage:
        failures.append('claim coverage below the floor')
    if fabrications:
        failures.append('a fact the source does not state appears in a Card')
    if unaccounted:
        failures.append(f'{len(unaccounted)} selected Source Unit(s) have no disposition')

    out = {
        'status': 'FAIL' if failures else 'PASS',
        'gold_set': gold.name,
        'failures': failures,
        'literal_preservation': {
            'required': literal_required, 'preserved': literal_kept,
            'rate': round(literal_rate, 4) if literal_rate is not None else None,
            'floor': a.min_literal_preservation,
            'missing': [r['text'] for r in literal_rows
                        if not r['preserved'] and not r['optional']],
            'optional_missing': [r['text'] for r in literal_rows
                                 if not r['preserved'] and r['optional']],
        },
        'claim_coverage': {
            'claims': len(claim_rows), 'covered': claims_covered,
            'rate': round(claim_rate, 4) if claim_rate is not None else None,
            'floor': a.min_claim_coverage,
            'uncovered': [r['id'] for r in claim_rows if not r['covered']],
        },
        'fabrication': {'count': len(fabrications), 'found': fabrications},
        'accounting': {'selected': len(selected), 'accounted': len(accounted),
                       'unaccounted': unaccounted[:20]},
        'counts': {'cards': len(cards), 'evidence': len(evidence),
                   'coverage_rows': len(coverage)},
        'note': ('Wording is not scored. A failure here means a source string was not '
                 'preserved, a claim is missing, a fact was invented, or a selected unit '
                 'was never assessed.'),
        'details': {'literals': literal_rows, 'claims': claim_rows},
    }
    if a.json_output:
        write_json(a.json_output, out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    raise SystemExit(0 if out['status'] == 'PASS' else 2)


if __name__ == '__main__':
    main()
