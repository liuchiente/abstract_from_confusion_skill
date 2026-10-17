#!/usr/bin/env python3
"""Run local Tesseract OCR for extracted images and scanned PDF pages.

No network or multimodal model is used. Tesseract and its requested language
data must be installed separately. Results are candidates until confidence and
source coverage have been reviewed.
"""
from pathlib import Path
import argparse
import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, write_jsonl
from afc_card_runtime.config import load_settings


def image_for(row, temporary):
    kind = row.get('kind')
    if kind == 'image':
        path = Path(str(row.get('media_path') or ''))
        if not path.is_file():
            raise FileNotFoundError(f"image media is missing for {row.get('source_unit_id')}: {path}")
        return path
    if kind == 'pdf-block' and row.get('image_text_status') == 'PENDING_VISUAL_EXTRACTION':
        source = Path(str(row.get('source_path') or ''))
        page_number = int(row.get('page') or 0)
        if not source.is_file() or page_number < 1:
            raise ValueError(f"PDF source/page is missing for {row.get('source_unit_id')}")
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError('Install optional OCR dependencies from requirements-ocr.txt to render scanned PDF pages.') from exc
        doc = fitz.open(source)
        try:
            page = doc.load_page(page_number - 1)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            target = Path(temporary) / f"page-{page_number:06d}.png"
            pix.save(target)
            return target
        finally:
            doc.close()
    raise ValueError(f"unsupported source unit for OCR: {row.get('source_unit_id')}")


def parse_tsv(raw):
    words_by_line = {}
    confidences = []
    reader = csv.DictReader(io.StringIO(raw), delimiter='\t')
    for row in reader:
        word = (row.get('text') or '').strip()
        try:
            confidence = float(row.get('conf') or -1)
        except ValueError:
            confidence = -1
        if not word or confidence < 0:
            continue
        key = (row.get('block_num'), row.get('par_num'), row.get('line_num'))
        item = words_by_line.setdefault(key, {'words': [], 'confidences': [], 'boxes': []})
        item['words'].append(word)
        item['confidences'].append(confidence)
        confidences.append(confidence)
        try:
            left, top = int(row['left']), int(row['top'])
            width, height = int(row['width']), int(row['height'])
            item['boxes'].append([left, top, left + width, top + height])
        except (KeyError, TypeError, ValueError):
            pass
    lines = []
    for key, value in words_by_line.items():
        boxes = value['boxes']
        region = None
        if boxes:
            region = [min(b[0] for b in boxes), min(b[1] for b in boxes),
                      max(b[2] for b in boxes), max(b[3] for b in boxes)]
        lines.append({
            'kind': 'TextLine', 'text': ' '.join(value['words']), 'region': region,
            'confidence': (sum(value['confidences']) / len(value['confidences']) / 100.0),
            'reading_order': list(key),
        })
    lines.sort(key=lambda x: tuple(int(v or 0) for v in x['reading_order']))
    confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return lines, confidence


def main():
    ap = argparse.ArgumentParser(description='Run offline Tesseract OCR over AFC image and scanned-PDF Source Units.')
    ap.add_argument('--source-map', action='append', default=[], required=True,
                    help='Parsed Source Unit JSONL; repeatable (one per parser output). '
                         'Results are keyed by source_unit_id, so several maps merge cleanly.')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--language', default=load_settings().get('ocr.language', 'eng'), help='Installed Tesseract language codes, e.g. chi_tra+eng+vie')
    ap.add_argument('--tesseract', default='tesseract', help='Path to the local Tesseract executable')
    ap.add_argument('--force', action='store_true', help='Re-run OCR even when a result already exists for a source unit')
    args = ap.parse_args()
    executable = shutil.which(args.tesseract)
    if not executable:
        ap.error(f"Tesseract executable not found: {args.tesseract}")
    rows, seen_units = [], set()
    for source_map in args.source_map:
        path = Path(source_map)
        if not path.exists():
            ap.error(f'source map not found: {source_map}')
        for row in read_jsonl(path):
            unit_id = str(row.get('source_unit_id') or '')
            if unit_id and unit_id in seen_units:
                continue
            if unit_id:
                seen_units.add(unit_id)
            rows.append(row)
    existing = {}
    output_path = Path(args.output)
    if output_path.exists() and not args.force:
        existing = {str(r.get('source_unit_id')): r for r in read_jsonl(output_path) if r.get('source_unit_id')}
    results = []
    failures = []
    version_result = subprocess.run([executable, '--version'], check=True, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace')
    extractor_version = (version_result.stdout.splitlines() or ['unknown'])[0]
    with tempfile.TemporaryDirectory(prefix='afc-ocr-') as temp:
        for row in rows:
            sid = str(row.get('source_unit_id') or '')
            eligible = row.get('kind') == 'image' or (
                row.get('kind') == 'pdf-block' and row.get('image_text_status') == 'PENDING_VISUAL_EXTRACTION')
            if not sid or not eligible:
                continue
            if sid in existing and not args.force:
                results.append(existing[sid])
                continue
            try:
                image_path = image_for(row, temp)
                proc = subprocess.run(
                    [executable, str(image_path), 'stdout', '-l', args.language, 'tsv'],
                    check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
                items, confidence = parse_tsv(proc.stdout)
                results.append({
                    'source_unit_id': sid,
                    'original_text': '\n'.join(item['text'] for item in items),
                    'source_language': args.language,
                    'extraction_method': 'OCR',
                    'extractor': 'Tesseract',
                    'extractor_version': extractor_version,
                    'confidence': confidence,
                    'items': items,
                    'source_sha256': row.get('sha256'),
                    'source_location': row.get('structure_path_text') or row.get('page'),
                })
            except Exception as exc:
                failures.append({'source_unit_id': sid, 'error': str(exc)})
    write_jsonl(output_path, results)
    print(json.dumps({'source_maps': [str(x) for x in args.source_map],
                      'source_units_read': len(rows),
                      'processed': len(results), 'failed': failures,
                      'output': str(output_path)}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if failures else 0)


if __name__ == '__main__':
    main()
