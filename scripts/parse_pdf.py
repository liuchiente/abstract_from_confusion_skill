#!/usr/bin/env python3
"""Extract PDF source units for AFC candidate discovery.

v0.5.0 additions: a structure report so `audit_source_structure.py` can detect a
PDF ingestion gap instead of defaulting to PASS, explicit reporting of the
structures this parser cannot read (images, tables, annotations, form fields,
  scanned pages), and path-derived Source Unit IDs. v0.7.0 keeps scanned pages
as addressable Source Units that can be rendered and OCRed by extract_ocr.py.
"""
from pathlib import Path
import argparse, hashlib, json, re, sys
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import write_jsonl, source_prefix

EXTS = {'.pdf'}


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


def split_blocks(text):
    # Prefer paragraph breaks; fall back to non-empty lines so an entire page is not one opaque unit.
    chunks = [x.strip() for x in re.split(r'\n\s*\n', text or '') if x.strip()]
    if len(chunks) <= 1:
        chunks = [x.strip() for x in (text or '').splitlines() if x.strip()]
    return chunks


def page_assets(page):
    """Count page-level objects this parser does not turn into Source Units."""
    out = {'images': 0, 'annotations': 0}
    try:
        # pypdf's page.images needs Pillow. Count image XObjects directly,
        # including images nested inside Form XObjects, so missing optional
        # imaging libraries never turn a known image into 0.
        seen = set()
        def visit(resources):
            nonlocal out
            xobjects = (resources or {}).get('/XObject') or {}
            for ref in xobjects.values():
                obj = ref.get_object()
                object_id = getattr(ref, 'idnum', id(obj))
                if object_id in seen:
                    continue
                seen.add(object_id)
                subtype = str(obj.get('/Subtype') or '')
                if subtype == '/Image':
                    out['images'] += 1
                elif subtype == '/Form':
                    visit(obj.get('/Resources') or resources)
        visit(page.get('/Resources') or {})
    except Exception:
        pass
    try:
        annots = page.get('/Annots')
        out['annotations'] = len(annots) if annots else 0
    except Exception:
        pass
    return out


def heading_level(text):
    """Conservatively identify numbered headings common in manuals and study guides."""
    value = (text or '').strip()
    match = re.match(r'^(\d+(?:\.\d+){0,5})\s+\S', value)
    if match and len(value) <= 180:
        return match.group(1).count('.') + 1
    match = re.match(r'^(第[一二三四五六七八九十百\d]+[章節單元篇])\s*\S?', value)
    if match and len(value) <= 180:
        return 1
    return None


def extract_page_text(page, profile):
    if profile == 'article':
        # pypdf's layout extractor is opt-in; the legacy fast path remains the
        # default and retains its existing output shape and throughput.
        try:
            return (page.extract_text(extraction_mode='layout') or '').strip(), 'pypdf-layout'
        except (TypeError, ValueError):
            return (page.extract_text() or '').strip(), 'pypdf-text-fallback'
    return (page.extract_text() or '').strip(), 'pypdf-text'


def section_metadata(headings, document_title=''):
    """Return a stable per-document section identity and readable heading path."""
    heading_texts = [item[1] if isinstance(item, tuple) else item for item in (headings or [])]
    heading_path = ([f'Document: {document_title}'] if document_title else []) + heading_texts
    key_material = '\n'.join(heading_path) or '[document]'
    section_key = hashlib.sha256(key_material.encode('utf-8')).hexdigest()[:16]
    return {
        'section_heading_path': heading_path,
        'section_heading_path_text': ' / '.join(heading_path),
        'section_key': section_key,
    }


def extract_pdf_images(fp, page, page_number, media_dir, prefix, heading_stack=None, document_title=''):
    """Extract image XObjects only for the opt-in article profile."""
    images = []
    try:
        import fitz
        doc = fitz.open(fp)
        try:
            rendered_page = doc.load_page(page_number - 1)
            for image_info in rendered_page.get_images(full=True):
                xref = image_info[0]
                extracted = doc.extract_image(xref)
                rects = rendered_page.get_image_rects(xref)
                for rect in (rects or [None]):
                    region = [rect.x0, rect.y0, rect.x1, rect.y1] if rect else None
                    images.append((extracted.get('ext') or 'bin', extracted['image'], region))
        finally:
            doc.close()
    except ImportError:
        # pypdf can extract image bytes through Pillow when Pillow is available.
        # Keep this as a fallback so the article profile is still useful without
        # making PyMuPDF a mandatory runtime dependency.
        try:
            for image in page.images:
                suffix = Path(getattr(image, 'name', 'image.bin')).suffix.lstrip('.') or 'bin'
                images.append((suffix, image.data, None))
        except Exception as exc:
            return [], 'PDF image extraction needs PyMuPDF or Pillow: ' + str(exc)
    media_dir = Path(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    source_key = hashlib.sha256(prefix.encode('utf-8')).hexdigest()[:12]
    heading_texts = [item[1] if isinstance(item, tuple) else item for item in (heading_stack or [])]
    for image_index, (suffix, data, region) in enumerate(images, 1):
        name = f'{Path(fp).stem}-{source_key}-p{page_number:04d}-img{image_index:03d}.{suffix}'
        target = media_dir / name
        target.write_bytes(data)
        rows.append({
            'source_unit_id': f'{prefix}::P{page_number:04d}::IMG{image_index:03d}',
            'source_file': Path(fp).name, 'source_path': str(fp),
            'kind': 'image', 'parent_kind': 'pdf-page', 'page': page_number,
            'image_index': image_index, 'media_path': str(target),
            'sha256': hashlib.sha256(data).hexdigest(), 'media_extracted': True,
            'region': region, 'region_units': 'pdf-points' if region else None,
            'structure_path': [f'Page {page_number}', *heading_texts, f'Image {image_index}'],
            'structure_path_text': ' / '.join([f'Page {page_number}', *heading_texts, f'Image {image_index}']),
            **section_metadata(heading_stack, document_title),
            'literal_source_status': 'PENDING_VISUAL_EXTRACTION',
            'image_text_status': 'PENDING_VISUAL_EXTRACTION',
        })
    return rows, None


def main():
    ap = argparse.ArgumentParser(description='Extract ordered PDF text blocks for AFC candidate discovery.')
    ap.add_argument('inputs', nargs='+', help='One or more source files/directories')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--structure-report', help='Write Source Structure Coverage JSON.')
    ap.add_argument('--source-root', action='append', default=[], help='Stable source boundary used for path-based Source Unit IDs')
    ap.add_argument('--no-recursive', action='store_true', help='Do not recurse into subdirectories')
    ap.add_argument('--profile', choices=['fast', 'article'], default='fast',
                    help='fast preserves the legacy parser; article uses pypdf layout extraction and heading context.')
    ap.add_argument('--media-dir', help='Output directory for images extracted by the article profile.')
    a = ap.parse_args()
    rows, reports = [], []
    files = files_from(a.inputs, recursive=not a.no_recursive)

    for fp in files:
        prefix = source_prefix(fp, a.source_root or a.inputs)
        reader = PdfReader(str(fp))
        metadata = getattr(reader, 'metadata', None)
        document_title = str(getattr(metadata, 'title', '') or '').strip() if a.profile == 'article' else ''
        if a.profile == 'article' and (not document_title or re.fullmatch(
                r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', document_title)):
            document_title = fp.stem
        discovered = {'pages': len(reader.pages), 'pages_with_text': 0,
                      'images': 0, 'annotations': 0, 'form_fields': 0}
        extracted = {'pages_with_text': 0, 'text_blocks': 0}
        extracted_images = 0
        image_extraction_error = None
        empty_pages = []
        # Section headings are document structure, so retain them across page
        # boundaries. Resetting per page loses the article topic exactly where
        # a section continues onto the next page.
        heading_stack = []
        try:
            fields = reader.get_fields() or {}
            discovered['form_fields'] = len(fields)
        except Exception:
            pass
        for page_no, page in enumerate(reader.pages, 1):
            assets = page_assets(page)
            discovered['images'] += assets['images']
            discovered['annotations'] += assets['annotations']
            text, extraction_method = extract_page_text(page, a.profile)
            blocks = split_blocks(text)
            if text:
                discovered['pages_with_text'] += 1
            if not blocks:
                empty_pages.append(page_no)
                rows.append({
                    'source_unit_id': f'{prefix}::P{page_no:04d}::B0001',
                    'source_file': fp.name, 'source_path': str(fp),
                    'kind': 'pdf-block', 'page': page_no, 'block_index': 1, 'value': '',
                    'page_image_count': assets['images'],
                    'pdf_profile': a.profile, 'extraction_method': extraction_method,
                    'status': 'Manual Review Required',
                    'image_text_status': 'PENDING_VISUAL_EXTRACTION' if assets['images'] else 'NO_TEXT_NO_IMAGE',
                })
                if assets['images'] and a.profile == 'article':
                    media_dir = a.media_dir or str(Path(a.output).resolve().parent / 'source-media')
                    image_rows, image_error = extract_pdf_images(fp, page, page_no, media_dir, prefix, heading_stack, document_title)
                    rows.extend(image_rows)
                    extracted_images += len(image_rows)
                    image_extraction_error = image_extraction_error or image_error
                continue
            extracted['pages_with_text'] += 1
            for bi, block in enumerate(blocks, 1):
                extracted['text_blocks'] += 1
                level = heading_level(block) if a.profile == 'article' else None
                if level:
                    # Heading levels come from numeric depth. A new 9.2 is a
                    # sibling of 9.1, while 9.2.1 is its child. Comparing the
                    # stored levels avoids chaining sibling headings as parents
                    # when a document omits an explicit level-1 heading.
                    heading_stack = [item for item in heading_stack if item[0] < level]
                    heading_stack.append((level, block))
                heading_texts = [item[1] for item in heading_stack]
                structure_path = [f'Page {page_no}', *heading_texts, f'Block {bi}']
                row = {
                    'source_unit_id': f'{prefix}::P{page_no:04d}::B{bi:04d}',
                    'source_file': fp.name, 'source_path': str(fp),
                    'kind': 'pdf-block', 'page': page_no, 'block_index': bi, 'value': block,
                    'structure_path': structure_path,
                    'structure_path_text': ' / '.join(structure_path),
                    **(section_metadata(heading_stack, document_title) if a.profile == 'article' else {}),
                    'pdf_profile': a.profile, 'extraction_method': extraction_method,
                    'structure_type': 'heading' if level else ('list-item' if re.match(r'^(?:\d+[.)、]|[•●▪◦-])\s*', block) else 'paragraph'),
                    'heading_level': level,
                    'parent_heading': heading_stack[-1][1] if heading_stack and not level else (heading_stack[-2][1] if level and len(heading_stack) > 1 else ''),
                    'page_image_count': assets['images'],
                    'literal_source_status': 'EXTRACTED_VERBATIM',
                }
                rows.append(row)
            if assets['images'] and a.profile == 'article':
                media_dir = a.media_dir or str(Path(a.output).resolve().parent / 'source-media')
                image_rows, image_error = extract_pdf_images(fp, page, page_no, media_dir, prefix, heading_stack, document_title)
                rows.extend(image_rows)
                extracted_images += len(image_rows)
                image_extraction_error = image_extraction_error or image_error

        def mark(unsupported, structure, detail, count):
            if count:
                unsupported.append({'structure': structure, 'detail': detail, 'count': count})

        unsupported = []
        unextracted_images = max(0, discovered['images'] - extracted_images)
        if a.profile == 'fast' or unextracted_images:
            mark(unsupported, 'page_image',
                 'PDF images were counted but not extracted as media. Use --profile article with the optional PyMuPDF/Pillow dependencies, then review the OCR results.',
                 discovered['images'] if a.profile == 'fast' else unextracted_images)
        mark(unsupported, 'annotation', 'PDF annotations/comments are not ingested.', discovered['annotations'])
        mark(unsupported, 'form_field', 'AcroForm field values are not ingested.', discovered['form_fields'])
        # Scanned pages already have addressable Source Units with
        # PENDING_VISUAL_EXTRACTION. Keep that as a visual-review route so a
        # successful later OCR pass can resolve it without stale parser reports.

        gaps = []
        if discovered['pages_with_text'] > extracted['pages_with_text']:
            gaps.append({'structure': 'pages_with_text',
                         'discovered': discovered['pages_with_text'],
                         'extracted': extracted['pages_with_text'],
                         'detail': 'Pages with extractable text produced no Source Unit.'})
        reports.append({
            'source_file': fp.name, 'source_path': str(fp),
            'discovered': discovered, 'extracted': {**extracted, 'image_objects': extracted_images},
            'image_extraction_error': image_extraction_error,
            'pages_without_text': empty_pages,
            'parser_gaps': gaps, 'unsupported_structures': unsupported,
            'source_structure_status': 'FAIL' if gaps else ('REVIEW' if (unsupported or extracted_images or empty_pages) else 'PASS'),
        })

    write_jsonl(a.output, rows)
    all_gaps = [{'source_file': r['source_file'], **g} for r in reports for g in r['parser_gaps']]
    all_unsupported = [{'source_file': r['source_file'], **u} for r in reports for u in r['unsupported_structures']]
    pending = sum(1 for r in rows if r.get('image_text_status') == 'PENDING_VISUAL_EXTRACTION')
    report = {
        'parser': 'parse_pdf.py', 'report_schema_version': '3', 'profile': a.profile, 'files': reports,
        'summary': {
            'files': len(files), 'source_units': len(rows),
            'pages': sum(r['discovered']['pages'] for r in reports),
            'discovered_pages_with_text': sum(r['discovered']['pages_with_text'] for r in reports),
            'extracted_pages_with_text': sum(r['extracted']['pages_with_text'] for r in reports),
            'text_blocks': sum(r['extracted']['text_blocks'] for r in reports),
            'pages_without_text': sum(len(r['pages_without_text']) for r in reports),
            'image_text_pending_visual_extraction': pending + sum(
                max(0, r['discovered'].get('images', 0) - r['extracted'].get('image_objects', 0))
                for r in reports),
            'image_alt_text_only': 0,
            'parser_gap_count': len(all_gaps),
            'unsupported_structure_count': sum(u.get('count', 0) for u in all_unsupported),
        },
        'parser_gaps': all_gaps, 'unsupported_structures': all_unsupported,
    }
    report['status'] = 'FAIL' if all_gaps else ('REVIEW' if (pending or all_unsupported) else 'PASS')
    if a.structure_report:
        rp = Path(a.structure_report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    s = report['summary']
    print(f"files={len(files)} source_units={len(rows)} pages={s['pages']} "
          f"pages_with_text={s['extracted_pages_with_text']}/{s['discovered_pages_with_text']} "
          f"blocks={s['text_blocks']} pages_without_text={s['pages_without_text']} "
          f"gaps={s['parser_gap_count']} unsupported={s['unsupported_structure_count']} "
          f"status={report['status']} output={a.output}")


if __name__ == '__main__':
    main()
