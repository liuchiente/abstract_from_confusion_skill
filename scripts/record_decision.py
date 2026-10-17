#!/usr/bin/env python3
"""Record and verify the human loop decision after Card health.

v0.4.1 repeated "PM/SA owns the final decision" while `afc-pipeline` was told
never to pause and to treat every review item as non-blocking, so in practice a
run always ended "READY WITH REVIEW ITEMS", nothing recorded that a person had
looked, and the next run could not tell whether a review had been handled.

The decision is now an artifact bound to the exact health report it was made
against: if health changes, the decision goes stale and must be made again.

  record  write a decision for the current health report
  verify  check that a valid, non-stale decision exists (Step 2 gate)
"""
from pathlib import Path
import argparse, datetime, hashlib, json, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_json, write_json, normalize_text
from afc_card_runtime.config import load_settings

ROUTES = [
    'PROCEED_TO_LINKS', 'TARGETED_CARD_DISCOVERY', 'RERUN_CARD_DISCOVERY',
    'CARD_RECONCILIATION', 'TARGETED_ATOMICITY_REVIEW', 'EVIDENCE_REPAIR',
    'CARD_RECOVERY', 'RETURN_TO_CONTEXT', 'AFC_EXPLORE', 'ACCEPT_REVIEW_ITEMS',
]
# Routes that let the pipeline continue into Step 2 with the current artifacts.
CONTINUING_ROUTES = {'PROCEED_TO_LINKS', 'ACCEPT_REVIEW_ITEMS'}


def health_digest(health):
    """Hash the decision-relevant part of a health report.

    Diagnostics and timestamps are excluded so a cosmetic change does not
    invalidate a decision, while anything that could change the decision does.
    """
    material = {
        'overall_status': health.get('overall_status'),
        'primary_loop_route': health.get('primary_loop_route'),
        'metrics': health.get('metrics'),
        'metric_states': health.get('metric_states'),
        'dispositions': health.get('dispositions'),
        'review_samples': {k: {kk: vv for kk, vv in (v or {}).items() if kk != 'min_detectable_rate'}
                           for k, v in (health.get('review_samples') or {}).items()},
        'evidence_coverage': {k: {kk: vv for kk, vv in (v or {}).items() if kk != 'missing_sample'}
                              for k, v in (health.get('evidence_coverage') or {}).items()},
        'selected_source_units': health.get('selected_source_units'),
        'card_count': health.get('card_count'),
    }
    blob = json.dumps(material, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def main():
    s = load_settings()
    ap = argparse.ArgumentParser(description='Record or verify the AFC Card-stage human loop decision.')
    ap.add_argument('action', choices=['record', 'verify'])
    ap.add_argument('--health', required=True, help='work/step-card-1-health.json')
    ap.add_argument('--decision', required=True, help='work/step-card-1-decision.json')
    ap.add_argument('--route', choices=ROUTES, help='record: the route the decision maker chose')
    ap.add_argument('--decided-by', help='record: who decided (name or role, e.g. "PM: 林")')
    ap.add_argument('--rationale', default='', help='record: why')
    ap.add_argument('--run-id', default='')
    ap.add_argument('--json-output')
    a = ap.parse_args()

    health = read_json(a.health)
    if not health:
        out = {'status': 'FAIL', 'reason': f'health report not found or empty: {a.health}'}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    digest = health_digest(health)
    overall = normalize_text(health.get('overall_status')) or 'UNKNOWN'

    if a.action == 'record':
        if not a.route or not a.decided_by:
            ap.error('record requires --route and --decided-by')
        decision = {
            'decision_schema_version': '1',
            'decided_by': a.decided_by,
            'decided_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            'run_id': a.run_id or None,
            'health_report': str(Path(a.health)),
            'health_overall_status': overall,
            'health_primary_loop_route': health.get('primary_loop_route'),
            'health_snapshot_sha256': digest,
            'chosen_route': a.route,
            'continues_pipeline': a.route in CONTINUING_ROUTES,
            'rationale': a.rationale,
        }
        write_json(a.decision, decision)
        print(json.dumps({'status': 'RECORDED', **decision}, ensure_ascii=False, indent=2))
        return

    required = bool(s.get('decision', {}).get('required_when_not_ready', True))
    result = {'health_overall_status': overall, 'health_snapshot_sha256': digest,
              'decision_required': required and overall != 'READY',
              'decision_path': str(Path(a.decision))}
    if overall == 'READY':
        result.update({'status': 'OK', 'reason': 'Card health is READY; no human decision is required.'})
    elif not required:
        result.update({'status': 'OK', 'reason': 'decision.required_when_not_ready is disabled in settings.yaml.'})
    else:
        decision = read_json(a.decision)
        if not decision:
            result.update({'status': 'MISSING',
                           'reason': ('Card health is not READY and no decision artifact exists. '
                                      'Have PM/SA choose a route, then record it with '
                                      '`record_decision.py record --route ... --decided-by ...`.')})
        elif normalize_text(decision.get('health_snapshot_sha256')) != digest:
            result.update({'status': 'STALE', 'decided_by': decision.get('decided_by'),
                           'recorded_snapshot': decision.get('health_snapshot_sha256'),
                           'reason': ('The recorded decision was made against a different health report. '
                                      'Re-run the decision against the current health.')})
        elif not decision.get('continues_pipeline'):
            result.update({'status': 'BLOCKED', 'chosen_route': decision.get('chosen_route'),
                           'decided_by': decision.get('decided_by'),
                           'reason': (f"The recorded decision chose {decision.get('chosen_route')}, which is a "
                                      'loop back into Step 0/1 rather than a continuation. Complete that loop, '
                                      'then decide again.')})
        else:
            result.update({'status': 'OK', 'chosen_route': decision.get('chosen_route'),
                           'decided_by': decision.get('decided_by'),
                           'decided_at': decision.get('decided_at'),
                           'reason': 'A current decision authorises continuing to Step 2.'})
    if a.json_output:
        write_json(a.json_output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['status'] == 'OK' else 2)


if __name__ == '__main__':
    main()
