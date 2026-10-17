#!/usr/bin/env python3
"""Evaluate AFC Card extraction health and recommend the next human-guided loop.

What changed in v0.5.0
----------------------
Four of the six Loop Gate metrics used to be read straight out of reports the
extracting model wrote about its own work, then dressed in GREEN/YELLOW/RED.
Now a rate is only graded when:

  * it came from `compute_review_metrics.py` over a sample drawn by
    `sample_units.py` (`sample_integrity == VERIFIED`), and
  * the sample is large enough for the green threshold to be distinguishable
    from zero (`card_health.min_sample_for_rate_grading`).

Otherwise the metric is graded INSUFFICIENT_SAMPLE or UNVERIFIED_SAMPLE and the
run cannot reach READY. Thresholds come from config/settings.yaml via
afc_card_runtime.config, not from argparse defaults.
"""
from pathlib import Path
import argparse, hashlib, json, math, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, read_json, write_json, normalize_text
from afc_card_runtime.config import load_settings

GRADEABLE = ('saturation', 'novelty', 'unsupported', 'atomicity')


def ratio(n, d):
    return (float(n) / float(d)) if d else 0.0


def get_metric(obj, *keys):
    if not obj:
        return None
    for k in keys:
        if k in obj and obj[k] is not None:
            try:
                return float(obj[k])
            except (TypeError, ValueError):
                pass
    return None


def card_fingerprint(c):
    parts = [c.get('Card Type', ''), c.get('Title', ''), c.get('Content', ''), c.get('Scope', ''),
             c.get('Context', ''), c.get('Source', ''), c.get('Source Location', ''),
             c.get('Original Evidence', '')]
    return hashlib.sha256('|'.join(normalize_text(x) for x in parts).encode('utf-8')).hexdigest()


def sample_state(report, min_n):
    """Whether a rate from this report may be graded at all."""
    if not report:
        return 'UNKNOWN', None, None
    n = report.get('sample_count') or report.get('claims_reviewed') or report.get('candidates_reviewed')
    try:
        n = int(n) if n is not None else None
    except (TypeError, ValueError):
        n = None
    integrity = str(report.get('sample_integrity') or '').upper()
    if integrity != 'VERIFIED':
        return 'UNVERIFIED_SAMPLE', n, integrity or 'MISSING'
    if n is None:
        return 'UNVERIFIED_SAMPLE', None, 'NO_SAMPLE_COUNT'
    population = report.get('population')
    try:
        population = int(population) if population is not None else None
    except (TypeError, ValueError):
        population = None
    if n < min_n and n != population:
        return 'INSUFFICIENT_SAMPLE', n, integrity
    return 'OK', n, integrity


def classify(value, green_lt, yellow_lte, zero_required=False, gate='OK'):
    if gate != 'OK':
        return gate
    if value is None:
        return 'UNKNOWN'
    if zero_required:
        if value <= 0:
            return 'GREEN'
        return 'YELLOW' if value <= yellow_lte else 'RED'
    if value < green_lt:
        return 'GREEN'
    return 'YELLOW' if value <= yellow_lte else 'RED'


def min_detectable_rate(n):
    return (1.0 / n) if n else None


def main():
    s = load_settings()
    ch = s.data.get('card_health', {})
    ap = argparse.ArgumentParser(description='Evaluate AFC Card extraction health and recommend the next human-guided loop route.')
    ap.add_argument('--source-map', required=True)
    ap.add_argument('--coverage', required=True)
    ap.add_argument('--cards', required=True)
    ap.add_argument('--evidence')
    ap.add_argument('--previous-cards')
    ap.add_argument('--baseline-run', action='store_true', help='Explicitly grade a first accepted-baseline build with no previous Cards.')
    ap.add_argument('--saturation-report')
    ap.add_argument('--fidelity-report')
    ap.add_argument('--atomicity-report')
    ap.add_argument('--context-health')
    ap.add_argument('--history')
    ap.add_argument('--json-output', required=True)
    ap.add_argument('--append-history')
    # Defaults come from settings.yaml; flags remain for one-off overrides.
    ap.add_argument('--green-saturation', type=float, default=ch.get('saturation_green_lt'))
    ap.add_argument('--yellow-saturation', type=float, default=ch.get('saturation_yellow_lte'))
    ap.add_argument('--green-novelty', type=float, default=ch.get('novelty_green_lt'))
    ap.add_argument('--yellow-novelty', type=float, default=ch.get('novelty_yellow_lte'))
    ap.add_argument('--green-atomicity', type=float, default=ch.get('atomicity_green_lt'))
    ap.add_argument('--yellow-atomicity', type=float, default=ch.get('atomicity_yellow_lte'))
    ap.add_argument('--green-review', type=float, default=ch.get('review_green_lt'))
    ap.add_argument('--yellow-review', type=float, default=ch.get('review_yellow_lte'))
    ap.add_argument('--min-sample', type=int, default=ch.get('min_sample_for_rate_grading'))
    a = ap.parse_args()

    source = read_jsonl(a.source_map)
    coverage = read_jsonl(a.coverage)
    cards = read_jsonl(a.cards)
    evidence = read_jsonl(a.evidence) if a.evidence else []
    previous = read_jsonl(a.previous_cards) if a.previous_cards else []

    selected = {r.get('source_unit_id'): r for r in source if r.get('selected') and r.get('source_unit_id')}
    ledger = {r.get('Source Unit ID'): r for r in coverage if r.get('Source Unit ID')}

    dispositions = {'Card': 0, 'Skip': 0, 'Review': 0, 'Unaccounted': 0}
    by_kind = {}
    for sid, r in selected.items():
        row = ledger.get(sid)
        disp = row.get('Disposition') if row else 'Unaccounted'
        if disp not in dispositions:
            disp = 'Unaccounted'
        dispositions[disp] += 1
        kind = r.get('kind') or 'unknown'
        d = by_kind.setdefault(kind, {'selected': 0, 'card': 0, 'skip': 0, 'review': 0, 'unaccounted': 0})
        d['selected'] += 1
        d[disp.lower()] += 1
    selected_n = len(selected)
    unaccounted_rate = ratio(dispositions['Unaccounted'], selected_n)
    unresolved_review_rate = ratio(dispositions['Review'], selected_n)

    sat = read_json(a.saturation_report)
    fidelity = read_json(a.fidelity_report)
    atomic = read_json(a.atomicity_report)

    sat_gate, sat_n, sat_integrity = sample_state(sat, a.min_sample)
    fid_gate, fid_n, fid_integrity = sample_state(fidelity, a.min_sample)
    atom_gate, atom_n, atom_integrity = sample_state(atomic, a.min_sample)

    saturation_miss_rate = get_metric(sat, 'saturation_miss_rate', 'miss_rate')
    if saturation_miss_rate is None and sat:
        saturation_miss_rate = ratio(sat.get('missing_count') or 0, sat.get('sample_count') or 0) or None
    unsupported_claim_rate = get_metric(fidelity, 'unsupported_claim_rate', 'unsupported_rate')
    atomicity_issue_rate = get_metric(atomic, 'atomicity_issue_rate', 'issue_rate')

    # Evidence-layer coverage of the signals Step 0 preserved.
    evidence_by_unit = {}
    for e in evidence:
        for sid in e.get('Source Unit IDs') or []:
            evidence_by_unit.setdefault(normalize_text(sid), set()).add(normalize_text(e.get('Evidence ID')))
    for row in coverage:
        for eid in row.get('Evidence Record IDs') or []:
            evidence_by_unit.setdefault(normalize_text(row.get('Source Unit ID')), set()).add(normalize_text(eid))

    def signal_coverage(signal):
        pool = [sid for sid, r in selected.items() if signal in (r.get('knowledge_signal_types') or [])]
        covered = [sid for sid in pool if evidence_by_unit.get(sid)]
        return {'selected': len(pool), 'with_evidence': len(covered),
                'coverage': ratio(len(covered), len(pool)) if pool else None,
                'missing_sample': sorted(set(pool) - set(covered))[:20]}

    literal_cov = signal_coverage('Literal Knowledge')
    structured_cov = signal_coverage('Structured Fact')

    novelty_rate = added_cards = updated_cards = None
    if a.previous_cards:
        old_ids = {c.get('Card ID'): c for c in previous if c.get('Card ID')}
        new_ids = {c.get('Card ID'): c for c in cards if c.get('Card ID')}
        added = set(new_ids) - set(old_ids)
        shared = set(new_ids) & set(old_ids)
        updated = {cid for cid in shared if card_fingerprint(new_ids[cid]) != card_fingerprint(old_ids[cid])}
        added_cards, updated_cards = len(added), len(updated)
        novelty_rate = ratio(added_cards, len(cards))
    elif a.baseline_run:
        novelty_rate = 0.0

    context = read_json(a.context_health)
    context_status, context_recall_rate = 'UNKNOWN', None
    if context:
        context_status = str(context.get('status') or context.get('context_recall_health')
                             or context.get('recall_assessment') or 'UNKNOWN').upper().replace(' ', '_')
        context_recall_rate = get_metric(context, 'context_recall_rate', 'recall_rate')

    metrics = {
        'unaccounted_rate': unaccounted_rate,
        'saturation_miss_rate': saturation_miss_rate,
        'rerun_novelty_rate': novelty_rate,
        'unsupported_claim_rate': unsupported_claim_rate,
        'atomicity_issue_rate': atomicity_issue_rate,
        'unresolved_review_rate': unresolved_review_rate,
    }
    states = {
        'unaccounted': classify(unaccounted_rate, 0.0, 0.0, zero_required=True),
        'saturation': classify(saturation_miss_rate, a.green_saturation, a.yellow_saturation, gate=sat_gate),
        # Novelty is computed here from stable registry IDs, so it needs no review sample.
        'novelty': classify(novelty_rate, a.green_novelty, a.yellow_novelty),
        'unsupported': classify(unsupported_claim_rate, 0.0, 0.0, zero_required=True, gate=fid_gate),
        'atomicity': classify(atomicity_issue_rate, a.green_atomicity, a.yellow_atomicity, gate=atom_gate),
        'review': classify(unresolved_review_rate, a.green_review, a.yellow_review),
    }
    evidence_rounds = {
        'saturation': {'gate': sat_gate, 'sample_count': sat_n, 'integrity': sat_integrity,
                       'min_detectable_rate': min_detectable_rate(sat_n)},
        'fidelity': {'gate': fid_gate, 'sample_count': fid_n, 'integrity': fid_integrity,
                     'min_detectable_rate': min_detectable_rate(fid_n)},
        'atomicity': {'gate': atom_gate, 'sample_count': atom_n, 'integrity': atom_integrity,
                      'min_detectable_rate': min_detectable_rate(atom_n)},
    }

    source_type = {k: {**d, 'card_extraction_rate': ratio(d['card'], d['selected'])} for k, d in by_kind.items()}

    yields = {'0': 0, '1': 0, '2': 0, '3-5': 0, '>5': 0}
    card_ids_by_unit = {sid: set() for sid in selected}
    for c in cards:
        for sid in c.get('Source Unit IDs') or []:
            if sid in card_ids_by_unit and c.get('Card ID'):
                card_ids_by_unit[sid].add(c['Card ID'])
    for sid in selected:
        n = len(card_ids_by_unit.get(sid, set()))
        key = '0' if n == 0 else '1' if n == 1 else '2' if n == 2 else '3-5' if n <= 5 else '>5'
        yields[key] += 1
    yield_outlier_rate = ratio(yields['>5'], selected_n)

    trend = 'INSUFFICIENT_DATA'
    hist = read_jsonl(a.history) if a.history else []
    points = []
    for h in hist[-4:]:
        m = h.get('metrics', {})
        vals = [x for x in (m.get('saturation_miss_rate'), m.get('rerun_novelty_rate')) if x is not None]
        if vals:
            points.append(sum(vals) / len(vals))
    current = [x for x in (saturation_miss_rate, novelty_rate) if x is not None]
    if current:
        points.append(sum(current) / len(current))
    if len(points) >= 2:
        trend = ('IMPROVING' if points[-1] < points[-2] - 0.002
                 else 'WORSENING' if points[-1] > points[-2] + 0.002 else 'FLAT')

    recommendations = []

    def add(action, reason, priority):
        recommendations.append({'action': action, 'reason': reason, 'priority': priority})

    if context_status in {'FAIL', 'PROBABLY_INCOMPLETE', 'INCOMPLETE', 'RED'}:
        add('RETURN_TO_CONTEXT', 'Context recall is not healthy; rerunning Cards cannot recover source units that Step 0 never selected.', 1)
    if dispositions['Unaccounted'] > 0:
        add('CARD_RECOVERY', f"{dispositions['Unaccounted']} selected source units have no Card/Skip/Review disposition.", 1)
    if unsupported_claim_rate is not None and fid_gate == 'OK' and unsupported_claim_rate > 0:
        add('EVIDENCE_REPAIR', 'Unsupported claims were detected; repair evidence fidelity before downstream graph construction.', 1)
    if fidelity and (fidelity.get('altered_literal_count') or fidelity.get('dropped_structured_fact_count')):
        add('EVIDENCE_REPAIR',
            f"Fidelity review found {fidelity.get('altered_literal_count', 0)} altered literal value(s) and "
            f"{fidelity.get('dropped_structured_fact_count', 0)} dropped structured fact(s).", 1)
    for label, cov in (('Literal Knowledge', literal_cov), ('Structured Fact', structured_cov)):
        if cov['selected'] and cov['coverage'] is not None and cov['coverage'] < 1.0:
            add('EVIDENCE_REPAIR',
                f"{cov['selected'] - cov['with_evidence']} selected {label} source units have no Evidence Record.", 2)

    ungraded = [k for k in GRADEABLE if states[k] in {'UNKNOWN', 'INSUFFICIENT_SAMPLE', 'UNVERIFIED_SAMPLE'}]
    if ungraded:
        detail = ', '.join(f'{k}={states[k]}' for k in ungraded)
        add('RUN_HEALTH_CHECKS',
            'Convergence metrics are not gradeable: ' + detail +
            f'. Draw a sample with sample_units.py (>= {a.min_sample} items) and compute the rate with '
            'compute_review_metrics.py.', 2)

    if states['saturation'] == 'RED':
        add('RERUN_CARD_DISCOVERY', f'Saturation miss rate {saturation_miss_rate:.2%} is above the red threshold.', 2)
    elif states['saturation'] == 'YELLOW':
        add('TARGETED_CARD_DISCOVERY', f'Saturation miss rate {saturation_miss_rate:.2%} remains above the green threshold.', 3)
    if states['novelty'] == 'RED':
        add('RERUN_CARD_DISCOVERY', f'Rerun novelty {novelty_rate:.2%} indicates extraction has not converged.', 2)
    elif states['novelty'] == 'YELLOW':
        add('TARGETED_CARD_DISCOVERY', f'Rerun novelty {novelty_rate:.2%} is still material.', 3)
    if states['atomicity'] == 'RED':
        add('CARD_RECONCILIATION', f'Atomicity issue rate {atomicity_issue_rate:.2%} is high.', 2)
    elif states['atomicity'] == 'YELLOW':
        add('TARGETED_ATOMICITY_REVIEW', f'Atomicity issue rate {atomicity_issue_rate:.2%} warrants review.', 3)
    if states['review'] == 'RED':
        add('AFC_EXPLORE', f'Unresolved review rate {unresolved_review_rate:.2%} is high; repeated extraction is unlikely to resolve source ambiguity.', 2)
    elif states['review'] == 'YELLOW':
        add('REVIEW_ITEMS', f'Unresolved review rate {unresolved_review_rate:.2%} should be inspected by PM/SA.', 4)

    if not recommendations:
        add('READY_FOR_LINKS', 'All gradeable Card extraction health metrics are green on verified samples.', 5)

    primary = sorted(recommendations, key=lambda x: (x['priority'], x['action']))[0]
    action = primary['action']
    # READY requires every gradeable metric to actually be GREEN.
    all_green = all(states[k] == 'GREEN' for k in GRADEABLE)
    if action == 'READY_FOR_LINKS' and all_green:
        overall = 'READY'
    elif action in {'RETURN_TO_CONTEXT', 'CARD_RECOVERY', 'EVIDENCE_REPAIR',
                    'RERUN_CARD_DISCOVERY', 'TARGETED_CARD_DISCOVERY'}:
        overall = 'RERUN_RECOMMENDED'
    else:
        overall = 'REVIEW_RECOMMENDED'

    result = {
        'health_schema_version': '2.0',
        'selected_source_units': selected_n,
        'dispositions': dispositions,
        'card_count': len(cards),
        'evidence_count': len(evidence),
        'previous_card_count': len(previous) if a.previous_cards else None,
        'added_cards': added_cards,
        'updated_cards': updated_cards,
        'metrics': metrics,
        'metric_states': states,
        'review_samples': evidence_rounds,
        'evidence_coverage': {'literal': literal_cov, 'structured_fact': structured_cov},
        'context_health': {'status': context_status, 'recall_rate': context_recall_rate},
        'diagnostics': {
            'source_type_extraction': source_type,
            'card_yield_distribution': yields,
            'card_yield_outlier_rate': yield_outlier_rate,
            'convergence_trend': trend,
        },
        'thresholds': {
            'saturation_green_lt': a.green_saturation, 'saturation_yellow_lte': a.yellow_saturation,
            'novelty_green_lt': a.green_novelty, 'novelty_yellow_lte': a.yellow_novelty,
            'atomicity_green_lt': a.green_atomicity, 'atomicity_yellow_lte': a.yellow_atomicity,
            'review_green_lt': a.green_review, 'review_yellow_lte': a.yellow_review,
            'unsupported_required': 0.0, 'unaccounted_required': 0.0,
            'min_sample_for_rate_grading': a.min_sample,
            'source': str(s.path) if s.path else 'afc_card_runtime.config.DEFAULTS',
        },
        'overall_status': overall,
        'baseline_run': bool(a.baseline_run),
        'primary_loop_route': primary['action'],
        'recommendations': sorted(recommendations, key=lambda x: (x['priority'], x['action'])),
        'human_decision_required': overall != 'READY',
        'note': ('Thresholds are decision aids, not automatic truth. A rate is graded only when it '
                 'comes from a deterministic sample with VERIFIED integrity and at least '
                 f'{a.min_sample} reviewed items. PM/SA owns the decision to rerun, explore, return '
                 'to Context, or proceed; record it with record_decision.py.'),
    }
    write_json(a.json_output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if a.append_history:
        hp = Path(a.append_history)
        hp.parent.mkdir(parents=True, exist_ok=True)
        with hp.open('a', encoding='utf-8') as f:
            f.write(json.dumps(result, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
