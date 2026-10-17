#!/usr/bin/env python3
"""Audit Step 0 selection for knowledge-signal candidates.

v0.4.1 set status=REVIEW whenever any signal candidate was unselected. Because
its signal patterns matched generic words in row content, that was true on
essentially every run, so the flag stopped carrying information.

A signal candidate that sits outside every selected structural boundary is
normal -- it is simply out of scope. The actionable case is a signal candidate
*inside* a selected boundary that was still not selected, which is the failure
mode the release notes were about (an exact Vietnamese message in an in-scope
table row never entering Coverage). Only that drives REVIEW.
"""
from pathlib import Path
import argparse, json, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, write_json

SIGNAL_TYPES = ('Literal Knowledge', 'Structured Fact', 'Semantic Knowledge', 'Structural Context')


def main():
    ap = argparse.ArgumentParser(description='Audit AFC Step 0 selection for knowledge-signal candidates.')
    ap.add_argument('--source-map', required=True)
    ap.add_argument('--json-output')
    ap.add_argument('--sample-size', type=int, default=20)
    a = ap.parse_args()
    rows = read_jsonl(a.source_map)

    m = {
        'audit_schema_version': '2',
        'total_source_units': len(rows), 'selected_source_units': 0,
        'knowledge_signal_candidates': 0,
        'literal_signal_candidates': 0, 'structured_signal_candidates': 0,
        'semantic_signal_candidates': 0, 'structural_only_signal_units': 0,
        'signal_selected': 0, 'signal_unselected': 0,
        'signal_unselected_within_boundary': 0, 'signal_unselected_outside_boundary': 0,
        'literal_unselected_within_boundary': 0, 'structured_unselected_within_boundary': 0,
        'boundary_annotation_available': False,
        'image_source_units': 0, 'image_selected': 0, 'image_text_pending': 0,
        'image_alt_text_only': 0, 'image_visual_extracted': 0,
        'actionable_source_unit_ids': [], 'out_of_scope_signal_sample': [],
    }
    actionable, out_of_scope = [], []
    for r in rows:
        sel = bool(r.get('selected'))
        if 'signal_within_selected_boundary' in r:
            m['boundary_annotation_available'] = True
        if r.get('kind') == 'image':
            m['image_source_units'] += 1
            if sel:
                m['image_selected'] += 1
            st = r.get('image_text_status')
            if st == 'PENDING_VISUAL_EXTRACTION':
                m['image_text_pending'] += 1
            elif st == 'ALT_TEXT_ONLY':
                m['image_alt_text_only'] += 1
            elif st == 'VISUAL_EXTRACTED':
                m['image_visual_extracted'] += 1
        if sel:
            m['selected_source_units'] += 1
        types = r.get('knowledge_signal_types') or []
        if not types:
            continue
        structural_only = bool(r.get('knowledge_signal_is_structural_only')) or all(
            t == 'Structural Context' for t in types)
        if structural_only:
            m['structural_only_signal_units'] += 1
        m['knowledge_signal_candidates'] += 1
        if 'Literal Knowledge' in types:
            m['literal_signal_candidates'] += 1
        if 'Structured Fact' in types:
            m['structured_signal_candidates'] += 1
        if 'Semantic Knowledge' in types:
            m['semantic_signal_candidates'] += 1
        if sel:
            m['signal_selected'] += 1
            continue
        m['signal_unselected'] += 1
        # Actionability is decided by the scope boundary -- the file proved it
        # belongs to the active Scope by having a selected unit -- not by the
        # structural boundary, which exists to gate auto-recovery and which no
        # prose unit can ever satisfy. A legacy source map carries neither
        # annotation, and is treated as in-boundary so the audit stays
        # conservative rather than silently passing.
        within = r.get('signal_within_scope_boundary',
                       r.get('signal_within_selected_boundary', True))
        if within and not structural_only:
            m['signal_unselected_within_boundary'] += 1
            if 'Literal Knowledge' in types:
                m['literal_unselected_within_boundary'] += 1
            if 'Structured Fact' in types:
                m['structured_unselected_within_boundary'] += 1
            actionable.append({'source_unit_id': r.get('source_unit_id'),
                               'kind': r.get('kind'),
                               'signal_types': types,
                               'signal_basis': r.get('knowledge_signal_basis') or [],
                               'value_excerpt': str(r.get('value') or '')[:120]})
        else:
            m['signal_unselected_outside_boundary'] += 1
            out_of_scope.append(r.get('source_unit_id'))

    m['actionable_source_unit_ids'] = actionable[:a.sample_size]
    m['actionable_count'] = len(actionable)
    m['out_of_scope_signal_sample'] = out_of_scope[:a.sample_size]
    m['signal_selection_rate'] = (m['signal_selected'] / m['knowledge_signal_candidates']
                                  if m['knowledge_signal_candidates'] else None)
    review = bool(actionable or m['image_text_pending'] or m['image_alt_text_only'])
    m['status'] = 'REVIEW' if review else 'PASS'
    m['note'] = (
        'REVIEW means a knowledge-signal candidate inside an already selected structural '
        'boundary was not selected, or image text is still unextracted. Signal candidates '
        'outside every selected boundary are reported separately and are not a finding: '
        'they are out of Active Scope.')
    if a.json_output:
        write_json(a.json_output, m)
    print(json.dumps(m, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
