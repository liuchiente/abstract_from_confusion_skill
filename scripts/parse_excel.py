#!/usr/bin/env python3
"""Extract Excel source units as ordered structural Source Units.

v0.5.0 closes the gaps that v0.4.1 only fixed for DOCX:
  * both the displayed value and the formula are captured, instead of
    `data_only=False` silently storing `=A1&B1` as the "original" source text;
  * merged-cell anchors propagate across the merged range, so a merged column
    header still reaches the rows underneath (Step 0 header inheritance depends
    on this);
  * embedded images become image Source Units with media on disk;
  * a structure report is produced, so `audit_source_structure.py` can detect an
    Excel ingestion gap instead of reporting PASS by default;
  * Source Unit IDs are path-derived, so same-named workbooks in different
    folders no longer collide.

This does not decide whether a row is a Field.
"""
from pathlib import Path
import argparse, datetime, hashlib, json, posixpath, sys, zipfile
from lxml import etree
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import write_jsonl, source_prefix, normalize_text

EXTS = {'.xlsx', '.xlsm'}


def files_from(inputs, recursive=True):
    files = []
    for raw in inputs:
        p = Path(raw)
        if not p.exists():
            raise FileNotFoundError(f'Source path does not exist: {p}')
        if p.is_file():
            if p.suffix.lower() in EXTS:
                files.append(p)
            continue
        it = p.rglob('*') if recursive else p.glob('*')
        files.extend(x for x in it if x.is_file() and x.suffix.lower() in EXTS)
    return sorted(dict.fromkeys(files), key=lambda x: str(x))


def display_value(value, number_format=''):
    """Render a computed cell value the way the sheet shows it.

    Without this a date cell becomes '2024-01-01 00:00:00', which would then be
    preserved as source-native text in an Evidence Record.
    """
    if value is None:
        return ''
    if isinstance(value, datetime.datetime):
        fmt = str(number_format or '').lower()
        if 'h' not in fmt and 's' not in fmt and value.time() == datetime.time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=' ')
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.isoformat()
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def merged_anchor_map(ws):
    """Map every covered cell in a merged range to its anchor coordinate."""
    out = {}
    for rng in list(ws.merged_cells.ranges):
        anchor = f'{get_column_letter(rng.min_col)}{rng.min_row}'
        for row in range(rng.min_row, rng.max_row + 1):
            for col in range(rng.min_col, rng.max_col + 1):
                coord = f'{get_column_letter(col)}{row}'
                if coord != anchor:
                    out[coord] = anchor
    return out


XDR_NS = 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'
NS = {
    'xdr': XDR_NS,
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
    'main': 'http://spreadsheetml.org/2006/main',
    'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
}
R_NS = NS['r']


def _read_rels(zf, part):
    """Relationship id -> target part path, resolved against the owning part."""
    base = posixpath.dirname(part)
    rels_part = posixpath.join(base, '_rels', posixpath.basename(part) + '.rels')
    out = {}
    try:
        root = etree.fromstring(zf.read(rels_part))
    except (KeyError, etree.XMLSyntaxError):
        return out
    for rel in root.findall('rel:Relationship', NS):
        rid, target, rtype = rel.get('Id'), rel.get('Target'), rel.get('Type') or ''
        if not rid or not target:
            continue
        if str(target).startswith('/'):
            resolved = str(target).lstrip('/')
        else:
            resolved = posixpath.normpath(posixpath.join(base, target))
        out[rid] = {'target': resolved, 'type': rtype}
    return out


def excel_package_images(path):
    """Locate embedded sheet images straight from the XLSX package.

    openpyxl only exposes `ws._images` when Pillow is installed, and silently
    reports none otherwise -- precisely the kind of silent ingestion gap this
    release is about. Reading the package directly needs no extra dependency
    and keeps discovery independent of extraction.
    """
    per_sheet, media_files = {}, []
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return per_sheet, media_files
    with zf:
        names = set(zf.namelist())
        media_files = sorted(n for n in names if n.startswith('xl/media/'))
        try:
            wb_root = etree.fromstring(zf.read('xl/workbook.xml'))
        except (KeyError, etree.XMLSyntaxError):
            return per_sheet, media_files
        wb_rels = _read_rels(zf, 'xl/workbook.xml')
        sheets = []
        for sh in wb_root.findall('.//x:sheets/x:sheet', NS):
            rid = sh.get(f'{{{R_NS}}}id')
            target = (wb_rels.get(rid) or {}).get('target')
            if sh.get('name') and target:
                sheets.append((sh.get('name'), target))
        for sheet_name, sheet_part in sheets:
            sheet_rels = _read_rels(zf, sheet_part)
            drawing_parts = [v['target'] for v in sheet_rels.values() if v['type'].endswith('/drawing')]
            found = []
            for dpart in drawing_parts:
                try:
                    droot = etree.fromstring(zf.read(dpart))
                except (KeyError, etree.XMLSyntaxError):
                    continue
                drels = _read_rels(zf, dpart)
                for anchor in droot.iterchildren():
                    blips = anchor.findall('.//a:blip', NS)
                    if not blips:
                        continue
                    frm = anchor.find('xdr:from', NS)
                    cell = ''
                    if frm is not None:
                        col = frm.find('xdr:col', NS)
                        row = frm.find('xdr:row', NS)
                        try:
                            cell = f'{get_column_letter(int(col.text) + 1)}{int(row.text) + 1}'
                        except (AttributeError, TypeError, ValueError):
                            cell = ''
                    for blip in blips:
                        rid = blip.get(f'{{{R_NS}}}embed')
                        target = (drels.get(rid) or {}).get('target')
                        if target:
                            found.append({'part': target, 'anchor_cell': cell})
            if found:
                per_sheet[sheet_name] = found
    return per_sheet, media_files


def extract_images(path, images, media_dir, prefix, sheet_title, seen_media):
    """Emit embedded sheet images as image Source Units."""
    rows = []
    if not images:
        return rows
    with zipfile.ZipFile(path) as zf:
        for idx, info in enumerate(images, 1):
            part = info['part']
            anchor = info.get('anchor_cell') or ''
            rec = {
                'source_unit_id': f'{prefix}::{sheet_title}::IMG{idx:03d}',
                'kind': 'image', 'parent_kind': 'sheet',
                'sheet': sheet_title, 'image': idx, 'anchor_cell': anchor,
                'source_partname': part,
                'structure_path': [sheet_title, f'Image {idx}'] + ([f'Anchor {anchor}'] if anchor else []),
                'image_text_status': 'PENDING_VISUAL_EXTRACTION', 'value': '',
            }
            try:
                blob = zf.read(part)
            except KeyError:
                blob = None
            if blob:
                digest = hashlib.sha256(blob).hexdigest()
                if digest in seen_media:
                    media_path = seen_media[digest]
                else:
                    ext = Path(part).suffix or '.bin'
                    target = Path(media_dir) / f'IMG-{idx:04d}-{digest[:10]}{ext}'
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(blob)
                    media_path = str(target)
                    seen_media[digest] = media_path
                rec.update({'media_path': media_path, 'sha256': digest, 'media_extracted': True})
            else:
                rec.update({'media_extracted': False, 'media_error': f'package part missing: {part}'})
            rows.append(rec)
    return rows


def discover_workbook(fp, wb_values, package_images):
    """Structure counts taken independently of the extraction loop."""
    found = {'sheets': 0, 'hidden_sheets': 0, 'rows_with_content': 0,
             'merged_ranges': 0, 'images': 0, 'charts': 0, 'cells_with_comments': 0}
    unsupported = []
    found['images'] = sum(len(v) for v in package_images.values())
    per_sheet_rows = {}
    for ws in wb_values.worksheets:
        found['sheets'] += 1
        if ws.sheet_state != 'visible':
            found['hidden_sheets'] += 1
        found['merged_ranges'] += len(list(ws.merged_cells.ranges))
        found['charts'] += len(list(getattr(ws, '_charts', []) or []))
        sheet_rows = 0
        for row in ws.iter_rows():
            has = False
            for c in row:
                v = c.value
                if v is not None and str(v).strip() != '':
                    has = True
                elif isinstance(v, str) and v.startswith('='):
                    has = True
                if getattr(c, 'comment', None) is not None:
                    found['cells_with_comments'] += 1
            if has:
                sheet_rows += 1
        per_sheet_rows[ws.title] = sheet_rows
        found['rows_with_content'] += sheet_rows
    found['rows_with_content_per_sheet'] = per_sheet_rows

    def mark(structure, detail, count):
        if count:
            unsupported.append({'structure': structure, 'detail': detail, 'count': count})

    mark('chart', 'Chart series/labels are not read as Source Units.', found['charts'])
    mark('cell_comment', 'Cell comments/notes are not ingested.', found['cells_with_comments'])
    mark('hidden_sheet', 'Hidden sheets are parsed but flagged; confirm they belong in scope.', found['hidden_sheets'])
    names = getattr(getattr(wb_values, 'defined_names', None), 'definedName', None)
    try:
        name_count = len(list(wb_values.defined_names))
    except Exception:
        name_count = len(names or [])
    mark('defined_name', 'Workbook defined names are not ingested.', name_count)
    if fp.suffix.lower() == '.xlsm':
        mark('vba_macro', 'Macro-enabled workbook; VBA code is not inspected.', 1)
    return {'discovered': found, 'unsupported': unsupported}


def main():
    ap = argparse.ArgumentParser(description='Extract Excel rows and embedded images as ordered structural source units.')
    ap.add_argument('inputs', nargs='+', help='One or more source files/directories')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--media-dir', help='Directory for extracted sheet images. Defaults beside output.')
    ap.add_argument('--structure-report', help='Write Source Structure Coverage JSON.')
    ap.add_argument('--source-root', action='append', default=[], help='Stable source boundary used for path-based Source Unit IDs')
    ap.add_argument('--include-hidden-sheets', action='store_true',
                    help='Include sheets whose state is hidden/veryHidden (they are flagged either way)')
    ap.add_argument('--no-recursive', action='store_true', help='Do not recurse into subdirectories')
    args = ap.parse_args()

    output = Path(args.output)
    media_root = Path(args.media_dir) if args.media_dir else output.parent / (output.stem + '_media')
    rows, reports = [], []
    files = files_from(args.inputs, recursive=not args.no_recursive)

    for fp in files:
        prefix = source_prefix(fp, args.source_root or args.inputs)
        # Two loads: displayed values for Evidence, formulas kept alongside.
        wb_values = load_workbook(fp, data_only=True)
        wb_formula = load_workbook(fp, data_only=False)
        package_images, package_media = excel_package_images(fp)
        discovery = discover_workbook(fp, wb_values, package_images)
        extracted = {'sheets': 0, 'rows_with_content': 0, 'merged_ranges_applied': 0,
                     'image_units': 0, 'image_media': 0, 'formula_cells': 0,
                     'formula_cells_without_cached_value': 0, 'hidden_rows': 0}
        file_media_dir = media_root / fp.stem
        seen_media = {}
        skipped_hidden_sheets = []

        for ws in wb_values.worksheets:
            hidden_sheet = ws.sheet_state != 'visible'
            if hidden_sheet and not args.include_hidden_sheets:
                skipped_hidden_sheets.append(ws.title)
                continue
            extracted['sheets'] += 1
            ws_f = wb_formula[ws.title] if ws.title in wb_formula.sheetnames else None
            anchors = merged_anchor_map(ws)
            extracted['merged_ranges_applied'] += len(list(ws.merged_cells.ranges))
            for row in ws.iter_rows():
                cells = []
                for cell in row:
                    coord = cell.coordinate
                    raw = cell.value
                    inherited_from = None
                    if raw is None or str(raw).strip() == '':
                        anchor = anchors.get(coord)
                        if anchor:
                            raw = ws[anchor].value
                            inherited_from = anchor
                    text = display_value(raw, getattr(cell, 'number_format', ''))
                    formula = None
                    if ws_f is not None:
                        f = ws_f[coord].value if inherited_from is None else ws_f[inherited_from].value
                        if isinstance(f, str) and f.startswith('='):
                            formula = f
                    if text == '' and not formula:
                        continue
                    item = {'coordinate': coord, 'column': cell.column, 'value': text}
                    if inherited_from:
                        item['merged_from'] = inherited_from
                    if formula:
                        item['formula'] = formula
                        extracted['formula_cells'] += 1
                        if text == '':
                            # The workbook carries no cached result, so there is no
                            # displayed text to preserve. Keep the formula and flag
                            # it rather than dropping the cell silently.
                            item['value_status'] = 'NO_CACHED_VALUE'
                            extracted['formula_cells_without_cached_value'] += 1
                    cells.append(item)
                if not cells:
                    continue
                row_no = row[0].row if row else 0
                row_hidden = bool(getattr(ws.row_dimensions.get(row_no, None), 'hidden', False))
                if row_hidden:
                    extracted['hidden_rows'] += 1
                extracted['rows_with_content'] += 1
                rec = {
                    'source_unit_id': f'{prefix}::{ws.title}::R{row_no:06d}',
                    'source_file': fp.name, 'source_path': str(fp),
                    'kind': 'sheet-row', 'sheet': ws.title, 'row': row_no,
                    'cells': cells,
                    'value': ' | '.join(c['value'] for c in cells),
                    'structure_path': [ws.title, f'Row {row_no}'],
                    'structure_path_text': f'{ws.title} / Row {row_no}',
                    'literal_source_status': 'EXTRACTED_VERBATIM',
                }
                if hidden_sheet:
                    rec['sheet_hidden'] = True
                if row_hidden:
                    rec['row_hidden'] = True
                if any('merged_from' in c for c in cells):
                    rec['has_merged_inheritance'] = True
                if any('formula' in c for c in cells):
                    rec['has_formula'] = True
                if any(c.get('value_status') == 'NO_CACHED_VALUE' for c in cells):
                    rec['has_uncached_formula'] = True
                rows.append(rec)

            for rec in extract_images(fp, package_images.get(ws.title, []), file_media_dir, prefix, ws.title, seen_media):
                rec['source_file'] = fp.name
                rec['source_path'] = str(fp)
                rec['structure_path_text'] = ' / '.join(rec['structure_path'])
                extracted['image_units'] += 1
                if rec.get('media_extracted'):
                    extracted['image_media'] += 1
                rows.append(rec)

        wb_values.close()
        wb_formula.close()

        discovered = discovery['discovered']
        gaps = []
        per_sheet = discovered.get('rows_with_content_per_sheet', {})
        expected_rows = sum(n for name, n in per_sheet.items() if name not in skipped_hidden_sheets)
        discovered['rows_with_content_in_scope'] = expected_rows
        if extracted['formula_cells_without_cached_value']:
            discovery['unsupported'].append({
                'structure': 'formula_without_cached_value',
                'detail': ('Formula cells have no cached result in the workbook, so no displayed text '
                           'exists to preserve as literal Evidence. Open and save the workbook in Excel, '
                           'or treat these cells as Structured Facts (the formula) only.'),
                'count': extracted['formula_cells_without_cached_value']})
        if skipped_hidden_sheets:
            # Hidden sheets were deliberately skipped; that is a scope choice,
            # reported as such rather than as a parsing gap.
            discovery['unsupported'].append({
                'structure': 'skipped_hidden_sheet',
                'detail': 'Hidden sheets were skipped. Re-run with --include-hidden-sheets if they are in scope.',
                'count': len(skipped_hidden_sheets), 'sheets': skipped_hidden_sheets})
        if expected_rows > extracted['rows_with_content']:
            gaps.append({'structure': 'rows_with_content', 'discovered': expected_rows,
                         'extracted': extracted['rows_with_content'],
                         'detail': 'Rows containing content produced no Source Unit.'})
        if discovered['images'] > extracted['image_media']:
            gaps.append({'structure': 'images', 'discovered': discovered['images'],
                         'extracted': extracted['image_media'],
                         'detail': 'Embedded sheet images were not extracted to media.'})
        reports.append({
            'source_file': fp.name, 'source_path': str(fp),
            'discovered': discovered, 'extracted': extracted,
            'media_files_in_package': package_media,
            'parser_gaps': gaps, 'unsupported_structures': discovery['unsupported'],
            'skipped_hidden_sheets': skipped_hidden_sheets,
            'source_structure_status': 'FAIL' if gaps else ('REVIEW' if discovery['unsupported'] else 'PASS'),
        })

    write_jsonl(output, rows)
    all_gaps = [{'source_file': r['source_file'], **g} for r in reports for g in r['parser_gaps']]
    all_unsupported = [{'source_file': r['source_file'], **u} for r in reports for u in r['unsupported_structures']]
    pending = sum(1 for r in rows if r.get('kind') == 'image' and r.get('image_text_status') == 'PENDING_VISUAL_EXTRACTION')
    report = {
        'parser': 'parse_excel.py', 'report_schema_version': '2', 'files': reports,
        'summary': {
            'files': len(files), 'source_units': len(rows),
            'discovered_rows_with_content': sum(r['discovered']['rows_with_content'] for r in reports),
            'discovered_rows_with_content_in_scope': sum(r['discovered'].get('rows_with_content_in_scope', 0) for r in reports),
            'extracted_rows_with_content': sum(r['extracted']['rows_with_content'] for r in reports),
            'merged_ranges': sum(r['discovered']['merged_ranges'] for r in reports),
            'rows_with_merged_inheritance': sum(1 for r in rows if r.get('has_merged_inheritance')),
            'rows_with_formula': sum(1 for r in rows if r.get('has_formula')),
            'rows_with_uncached_formula': sum(1 for r in rows if r.get('has_uncached_formula')),
            'hidden_rows': sum(r['extracted']['hidden_rows'] for r in reports),
            'image_source_units': sum(r['extracted']['image_units'] for r in reports),
            'image_text_pending_visual_extraction': pending,
            'image_alt_text_only': 0,
            'parser_gap_count': len(all_gaps),
            'unsupported_structure_count': sum(u.get('count', 0) for u in all_unsupported),
        },
        'parser_gaps': all_gaps, 'unsupported_structures': all_unsupported,
    }
    report['status'] = 'FAIL' if all_gaps else ('REVIEW' if (pending or all_unsupported) else 'PASS')
    if args.structure_report:
        rp = Path(args.structure_report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    s = report['summary']
    print(f"files={len(files)} source_units={len(rows)} rows={s['extracted_rows_with_content']}/{s['discovered_rows_with_content_in_scope']} "
          f"merged={s['merged_ranges']} merged_inherited_rows={s['rows_with_merged_inheritance']} formula_rows={s['rows_with_formula']} "
          f"images={s['image_source_units']} gaps={s['parser_gap_count']} unsupported={s['unsupported_structure_count']} "
          f"status={report['status']} output={output}")


if __name__ == '__main__':
    main()
