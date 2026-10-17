#!/usr/bin/env python3
"""Audit AFC source-structure ingestion before Context selection.

v0.4.1 compared `discovered` with `extracted` numbers that the parser
incremented on the same line, so the only structure that could ever diverge was
a blank paragraph -- meaning SOURCE_PARSING_GAP fired on nearly every real DOCX
while being unable to detect a genuinely missed table, text box or shape. The
parsers now report counts taken from an independent pass over the package and
list the structures they cannot read at all, so this audit distinguishes:

  SOURCE_PARSING_GAP           structure was discovered but not materialized;
  SOURCE_UNSUPPORTED_STRUCTURE source content exists that no parser can read;
  SOURCE_VISUAL_EXTRACTION_GAP image evidence exists without reliable text;
  CONTINUE_TO_CONTEXT          no known ingestion gap.
"""
from pathlib import Path
import argparse, json, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, read_json, write_json
from afc_card_runtime.config import load_settings

LEGACY_REPORT_KEYS = ('paragraphs', 'tables', 'nested_tables', 'text_boxes', 'images')


def collect_reports(paths):
    reports, unreadable = [], []
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            unreadable.append({'path': str(p), 'reason': 'missing'})
            continue
        try:
            reports.append({'path': str(p), 'report': json.loads(p.read_text(encoding='utf-8'))})
        except json.JSONDecodeError as e:
            unreadable.append({'path': str(p), 'reason': f'invalid JSON: {e}'})
    return reports, unreadable


def collect_source_units(paths, unreadable):
    """Union the Source Units of every named map, keeping the first row per ID.

    `read_jsonl` returns [] for a path that does not exist, so a mistyped map
    used to produce a zero-unit audit that still passed. A named map that is
    missing is recorded as unreadable, which routes SOURCE_PARSING_GAP.
    """
    rows, seen, duplicates = [], set(), 0
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            unreadable.append({'path': str(path), 'reason': 'missing source map'})
            continue
        for row in read_jsonl(path):
            unit_id = str(row.get('source_unit_id') or '')
            if unit_id and unit_id in seen:
                duplicates += 1
                continue
            if unit_id:
                seen.add(unit_id)
            rows.append(row)
    return rows, duplicates


def report_gaps(report):
    """Parser gaps, preferring the v2 report's own list over count comparison."""
    schema = str(report.get('report_schema_version') or '1')
    if schema >= '2' and 'parser_gaps' in report:
        return list(report.get('parser_gaps') or []), schema
    # Legacy v0.4.x report: compare counts, but never treat blank paragraphs as a
    # gap, which was the dominant false positive.
    gaps = []
    for f in report.get('files', []):
        d = f.get('discovered') or {}
        e = f.get('extracted') or {}
        for key in LEGACY_REPORT_KEYS:
            if key == 'paragraphs':
                continue
            if d.get(key, 0) > e.get(key, 0):
                gaps.append({'source_file': f.get('source_file'), 'structure': key,
                             'discovered': d.get(key, 0), 'extracted': e.get(key, 0),
                             'detail': 'legacy report: count mismatch'})
    return gaps, schema


def main():
    s = load_settings()
    ap = argparse.ArgumentParser(description='Audit AFC source-structure ingestion before Context selection.')
    ap.add_argument('--source-map', action='append', default=[],
                    help='Parsed or annotated Source Unit JSONL; repeatable (one per parser '
                         'output). A named map that does not exist is a gap, not an empty audit.')
    ap.add_argument('--structure-report', action='append', default=[],
                    help='Parser structure report JSON; repeatable (one per parser/source set)')
    ap.add_argument('--expect-parsers', default='',
                    help='Comma-separated parser names that must have produced a report, '
                         'e.g. parse_word.py,parse_excel.py. Missing ones become a gap.')
    ap.add_argument('--json-output')
    a = ap.parse_args()

    reports, unreadable = collect_reports(a.structure_report)
    rows, duplicate_units = collect_source_units(a.source_map, unreadable)

    def count(pred):
        return sum(1 for r in rows if pred(r))

    summary = {
        'source_units': len(rows),
        'duplicate_source_unit_ids': duplicate_units,
        'paragraph_units': count(lambda r: r.get('kind') == 'paragraph'),
        'table_row_units': count(lambda r: r.get('kind') == 'table-row'),
        'nested_table_row_units': count(lambda r: r.get('kind') == 'table-row' and r.get('is_nested_table')),
        'sheet_row_units': count(lambda r: r.get('kind') == 'sheet-row'),
        'sheet_rows_with_merged_inheritance': count(lambda r: r.get('has_merged_inheritance')),
        'sheet_rows_with_uncached_formula': count(lambda r: r.get('has_uncached_formula')),
        'pdf_block_units': count(lambda r: r.get('kind') == 'pdf-block'),
        'text_box_units': count(lambda r: r.get('kind') == 'text-box'),
        'image_units': count(lambda r: r.get('kind') == 'image'),
        'image_media_missing': count(lambda r: r.get('kind') == 'image' and not r.get('media_extracted')),
        'image_text_pending_visual_extraction': count(
            lambda r: r.get('image_text_status') in {'PENDING_VISUAL_EXTRACTION', 'LOW_CONFIDENCE_REVIEW'}),
        'image_alt_text_only': count(lambda r: r.get('image_text_status') == 'ALT_TEXT_ONLY'),
        'image_visual_extracted': count(lambda r: r.get('image_text_status') == 'VISUAL_EXTRACTED'),
    }

    parser_gaps, unsupported, parsers_seen, legacy_reports = [], [], [], []
    for item in reports:
        rpt = item['report']
        gaps, schema = report_gaps(rpt)
        parser = rpt.get('parser') or Path(item['path']).name
        parsers_seen.append(parser)
        if schema < '2':
            legacy_reports.append({'path': item['path'], 'parser': parser,
                                   'note': 'pre-v0.5.0 structure report; unsupported-structure '
                                           'detection is unavailable for this parser run'})
        for g in gaps:
            parser_gaps.append({'parser': parser, **g})
        for u in rpt.get('unsupported_structures') or []:
            unsupported.append({'parser': parser, **u})

    missing_reports = []
    expected = [x.strip() for x in a.expect_parsers.split(',') if x.strip()]
    for want in expected:
        if not any(want in p for p in parsers_seen):
            missing_reports.append(want)

    if summary['image_media_missing']:
        parser_gaps.append({'parser': 'source-map', 'structure': 'image_media',
                            'discovered': summary['image_units'],
                            'extracted': summary['image_units'] - summary['image_media_missing'],
                            'detail': 'Image Source Units exist whose media was not written to disk.'})

    routes = []
    if parser_gaps or missing_reports or unreadable:
        routes.append('SOURCE_PARSING_GAP')
    if unsupported:
        routes.append('SOURCE_UNSUPPORTED_STRUCTURE')
    if summary['image_text_pending_visual_extraction'] or summary['image_alt_text_only']:
        routes.append('SOURCE_VISUAL_EXTRACTION_GAP')

    blocking = bool(parser_gaps or missing_reports or unreadable)
    status = 'FAIL' if blocking else ('REVIEW' if routes else 'PASS')
    out = {
        'audit_schema_version': '2',
        'status': status,
        'summary': summary,
        'source_maps': [str(x) for x in a.source_map],
        'parsers_reporting': sorted(set(parsers_seen)),
        'missing_parser_reports': missing_reports,
        'unreadable_structure_reports': unreadable,
        'legacy_structure_reports': legacy_reports,
        'parser_gaps': parser_gaps,
        'unsupported_structures': unsupported,
        'unsupported_structure_count': sum(u.get('count', 0) for u in unsupported),
        'recommended_routes': routes or ['CONTINUE_TO_CONTEXT'],
        'audit_required': bool(s.get('source_structure', {}).get('audit_required', True)),
        'note': ('SOURCE_PARSING_GAP blocks Context selection. '
                 'SOURCE_UNSUPPORTED_STRUCTURE and SOURCE_VISUAL_EXTRACTION_GAP are review '
                 'conditions: decide per source whether the unreadable content carries knowledge '
                 'the requested queries need.'),
    }
    if a.json_output:
        write_json(a.json_output, out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    raise SystemExit(0 if status != 'FAIL' else 2)


if __name__ == '__main__':
    main()
