#!/usr/bin/env python3
from pathlib import Path
import argparse, hashlib, json, re, sys, zipfile
from collections import Counter
from lxml import etree
from docx import Document
from docx.text.paragraph import Paragraph
from docx.table import Table, _Cell
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import write_jsonl, source_prefix

EXTS={'.docx'}


def files_from(inputs, recursive=True):
    files=[]
    for raw in inputs:
        p=Path(raw)
        if not p.exists():
            raise FileNotFoundError(f'Source path does not exist: {p}')
        if p.is_file():
            if p.suffix.lower() in EXTS: files.append(p)
            continue
        it=p.rglob('*') if recursive else p.glob('*')
        files.extend(x for x in it if x.is_file() and x.suffix.lower() in EXTS)
    return sorted(dict.fromkeys(files), key=lambda x:str(x))


def heading_level(style_name):
    if not style_name: return None
    m=re.search(r'(?:heading|標題)\s*([1-9])', style_name, flags=re.I)
    return int(m.group(1)) if m else None


def iter_block_items(parent):
    """Yield direct paragraphs/tables in source order for Document or Cell."""
    parent_elm = parent.element.body if hasattr(parent, 'element') and hasattr(parent.element, 'body') else parent._tc
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield 'paragraph', Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield 'table', Table(child, parent)


def direct_cell_text(cell):
    # Keep only direct cell paragraphs. Nested-table text is emitted separately.
    parts=[]
    for kind,obj in iter_block_items(cell):
        if kind=='paragraph':
            t=obj.text.strip()
            if t: parts.append(t)
    return '\n'.join(parts).strip()


def structure_path_str(parts):
    return ' / '.join(str(x) for x in parts if x is not None and str(x)!='')


def safe_xpath(el, expr):
    try:
        return el.xpath(expr)
    except Exception:
        return []


def textbox_texts(el):
    vals=[]
    for tx in safe_xpath(el, './/w:txbxContent'):
        texts=[]
        for t in safe_xpath(tx, './/w:t'):
            if t.text: texts.append(t.text)
        joined=''.join(texts).strip()
        if joined and joined not in vals: vals.append(joined)
    return vals


def drawing_infos(el, part):
    infos=[]
    docprs=safe_xpath(el, './/wp:docPr') + safe_xpath(el, './/pic:cNvPr')
    alt=[]
    for d in docprs:
        item={k:d.get(k) for k in ('name','descr','title') if d.get(k)}
        if item and item not in alt: alt.append(item)
    rel_ids=[]
    for blip in safe_xpath(el, './/a:blip'):
        rid=blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
        if rid: rel_ids.append(rid)
    # Older/compatibility Word drawings may use VML instead of DrawingML.
    for imagedata in safe_xpath(el, './/v:imagedata'):
        rid=imagedata.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        if rid: rel_ids.append(rid)
    for rid in dict.fromkeys(rel_ids):
        try:
            rel=part.rels[rid]
            target=rel.target_part
            blob=target.blob
            content_type=getattr(target,'content_type',None)
            partname=str(getattr(target,'partname',''))
            infos.append({'rid':rid,'blob':blob,'content_type':content_type,'partname':partname,'alt':alt})
        except Exception as e:
            infos.append({'rid':rid,'error':str(e),'alt':alt})
    return infos


W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS = {
    'w': W_NS,
    'r': R_NS,
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'v': 'urn:schemas-microsoft-com:vml',
    'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
    'wpg': 'http://schemas.microsoft.com/office/word/2010/wordprocessingGroup',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
}


def _para_has_text(p):
    return bool(''.join(t.text or '' for t in p.findall(f'.//{{{W_NS}}}t')).strip())


def _part_has_text(root):
    return bool(''.join(t.text or '' for t in root.findall(f'.//{{{W_NS}}}t')).strip())


def _image_rids(el):
    """Relationship ids of images referenced under an element, in document order."""
    rids = []
    for blip in el.findall('.//a:blip', NS):
        rid = blip.get(f'{{{R_NS}}}embed')
        if rid:
            rids.append(rid)
    for vml in el.findall('.//v:imagedata', NS):
        rid = vml.get(f'{{{R_NS}}}id')
        if rid:
            rids.append(rid)
    return rids


def discover_docx_structure(path):
    """Count DOCX structure straight from the OOXML, independent of extraction.

    v0.4.1 incremented its `discovered` and `extracted` counters on the same
    line, so `discovered > extracted` could only ever be true for blank
    paragraphs. That made SOURCE_PARSING_GAP fire on almost every real document
    while being structurally unable to detect a genuinely missed table, text box
    or shape. Here `discovered` comes from a separate parse of the package, and
    structures this parser does not support at all are reported explicitly
    rather than silently counted as complete.
    """
    found = {
        'body_paragraphs_with_text': 0, 'tables': 0, 'nested_tables': 0,
        'table_rows': 0, 'text_boxes': 0, 'grouped_shapes': 0,
    }
    image_parts, unsupported = [], []
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        try:
            doc_root = etree.fromstring(zf.read('word/document.xml'))
        except (KeyError, etree.XMLSyntaxError) as e:
            return {'discovered': found, 'image_parts': [], 'media_files': [],
                    'unsupported': [{'structure': 'document.xml', 'detail': str(e), 'count': 1}],
                    'discovery_error': str(e)}
        body = doc_root.find(f'{{{W_NS}}}body')
        if body is not None:
            found['body_paragraphs_with_text'] = sum(
                1 for p in body.findall(f'{{{W_NS}}}p') if _para_has_text(p))
        tables = doc_root.findall(f'.//{{{W_NS}}}tbl')
        found['tables'] = len(tables)
        found['nested_tables'] = sum(
            1 for t in tables if any(a.tag == f'{{{W_NS}}}tbl' for a in t.iterancestors()))
        found['table_rows'] = len(doc_root.findall(f'.//{{{W_NS}}}tr'))
        found['text_boxes'] = len(doc_root.findall(f'.//{{{W_NS}}}txbxContent'))
        found['grouped_shapes'] = len(doc_root.findall('.//wpg:wgp', NS))

        # Resolve image relationships to their package parts so the comparison
        # is set-based rather than count-based.
        rel_targets = {}
        if 'word/_rels/document.xml.rels' in names:
            try:
                rels = etree.fromstring(zf.read('word/_rels/document.xml.rels'))
                for rel in rels.findall('rel:Relationship', NS):
                    rel_targets[rel.get('Id')] = rel.get('Target')
            except etree.XMLSyntaxError:
                pass
        for rid in dict.fromkeys(_image_rids(doc_root)):
            target = rel_targets.get(rid)
            if target:
                image_parts.append('word/' + str(target).lstrip('/').replace('../', ''))
        media_files = sorted(n for n in names if n.startswith('word/media/'))

        def mark(structure, detail, count):
            if count:
                unsupported.append({'structure': structure, 'detail': detail, 'count': count})

        hf = [n for n in names if re.fullmatch(r'word/(header|footer)\d*\.xml', n)]
        hf_with_text = 0
        for n in hf:
            try:
                if _part_has_text(etree.fromstring(zf.read(n))):
                    hf_with_text += 1
            except etree.XMLSyntaxError:
                hf_with_text += 1
        mark('header_footer_text', 'Header/footer parts carry text; this parser reads word/document.xml only.', hf_with_text)

        for part, label in (('word/footnotes.xml', 'footnote_text'), ('word/endnotes.xml', 'endnote_text')):
            if part in names:
                try:
                    root = etree.fromstring(zf.read(part))
                    notes = [n for n in root.findall(f'.//{{{W_NS}}}*')
                             if n.tag.endswith('}footnote') or n.tag.endswith('}endnote')]
                    real = [n for n in notes if n.get(f'{{{W_NS}}}id') not in ('0', '-1') and _part_has_text(n)]
                    mark(label, f'{part} carries note text that never becomes a Source Unit.', len(real))
                except etree.XMLSyntaxError:
                    mark(label, f'{part} is unreadable.', 1)

        if 'word/comments.xml' in names:
            try:
                root = etree.fromstring(zf.read('word/comments.xml'))
                mark('comment_text', 'Reviewer comments are not ingested.',
                     len([c for c in root.findall(f'.//{{{W_NS}}}comment') if _part_has_text(c)]))
            except etree.XMLSyntaxError:
                mark('comment_text', 'word/comments.xml is unreadable.', 1)

        mark('chart', 'Chart parts contain data/labels this parser cannot read.',
             len([n for n in names if n.startswith('word/charts/')]))
        mark('smartart_diagram', 'SmartArt/diagram parts contain text this parser cannot read.',
             len([n for n in names if n.startswith('word/diagrams/')]))
        mark('embedded_object', 'Embedded OLE objects (e.g. nested workbooks) are not opened.',
             len([n for n in names if n.startswith('word/embeddings/')]))
        mark('tracked_revision', 'Tracked insertions/deletions are flattened to the current text.',
             len(doc_root.findall(f'.//{{{W_NS}}}ins')) + len(doc_root.findall(f'.//{{{W_NS}}}del')))
        mark('equation', 'OMML equations are not converted to text.', len(doc_root.findall('.//m:oMath', NS)))

    return {'discovered': found, 'image_parts': sorted(set(image_parts)),
            'media_files': media_files, 'unsupported': unsupported}


def media_ext(content_type, partname):
    suffix=Path(partname).suffix
    if suffix: return suffix
    mapping={'image/png':'.png','image/jpeg':'.jpg','image/jpg':'.jpg','image/gif':'.gif','image/webp':'.webp','image/tiff':'.tif','image/bmp':'.bmp'}
    return mapping.get(content_type,'.bin')


def main():
    ap=argparse.ArgumentParser(description='Extract DOCX source units in true structural order, including nested tables, text boxes/shapes, and embedded image evidence.')
    ap.add_argument('inputs', nargs='+', help='One or more source files/directories')
    ap.add_argument('-o','--output',required=True)
    ap.add_argument('--media-dir', help='Directory to extract embedded image media. Defaults beside output.')
    ap.add_argument('--structure-report', help='Write per-file Source Structure Coverage JSON.')
    ap.add_argument('--source-root', action='append', default=[], help='Stable source boundary used for path-based Source Unit IDs')
    ap.add_argument('--no-recursive', action='store_true', help='Do not recurse into source directories')
    a=ap.parse_args()
    output=Path(a.output)
    media_root=Path(a.media_dir) if a.media_dir else output.parent/(output.stem+'_media')
    media_root.mkdir(parents=True,exist_ok=True)
    rows=[]; reports=[]
    files=files_from(a.inputs, recursive=not a.no_recursive)

    for fp in files:
        doc=Document(fp)
        discovery=discover_docx_structure(fp)
        extracted=Counter()
        extracted_image_parts=set()
        table_seq=0; paragraph_seq=0; image_seq=0; textbox_seq=0
        seen_media={}
        prefix=source_prefix(fp, a.source_root or a.inputs)
        file_media_dir=media_root/re.sub(r'[^A-Za-z0-9._-]+','_',fp.stem)
        file_media_dir.mkdir(parents=True,exist_ok=True)

        def add_textboxes(el, base_id, path, parent_kind, part):
            nonlocal textbox_seq
            vals=textbox_texts(el)
            for idx,text in enumerate(vals,1):
                textbox_seq+=1; extracted['text_boxes']+=1
                rows.append({
                    'source_unit_id':f'{base_id}::TBX{idx:02d}',
                    'source_file':fp.name,'source_path':str(fp),
                    'kind':'text-box','parent_kind':parent_kind,
                    'textbox':textbox_seq,'value':text,
                    'structure_path':[ *path, f'TextBox {idx}' ],
                    'structure_path_text':structure_path_str([*path,f'TextBox {idx}']),
                    'literal_source_status':'EXTRACTED_VERBATIM'
                })

        def add_images(el, base_id, path, parent_kind, part):
            nonlocal image_seq
            infos=drawing_infos(el,part)
            for idx,info in enumerate(infos,1):
                image_seq+=1; extracted['image_units']+=1
                rec={
                    'source_unit_id':f'{base_id}::IMG{idx:02d}',
                    'source_file':fp.name,'source_path':str(fp),
                    'kind':'image','parent_kind':parent_kind,
                    'image':image_seq,
                    'structure_path':[ *path, f'Image {idx}' ],
                    'structure_path_text':structure_path_str([*path,f'Image {idx}']),
                    'content_type':info.get('content_type'),
                    'source_partname':info.get('partname'),
                    'alt_text':info.get('alt') or [],
                    'image_text_status':'PENDING_VISUAL_EXTRACTION',
                    'value':''
                }
                blob=info.get('blob')
                if blob:
                    digest=hashlib.sha256(blob).hexdigest()
                    if digest in seen_media:
                        media_path=seen_media[digest]
                    else:
                        ext=media_ext(info.get('content_type'),info.get('partname',''))
                        name=f'IMG-{image_seq:04d}-{digest[:10]}{ext}'
                        target=file_media_dir/name
                        target.write_bytes(blob)
                        media_path=str(target)
                        seen_media[digest]=media_path
                    rec['media_path']=media_path
                    rec['sha256']=digest
                    rec['media_extracted']=True
                    extracted['image_media']+=1
                    partname=info.get('partname') or ''
                    if partname: extracted_image_parts.add(str(partname).lstrip('/'))
                else:
                    rec['media_extracted']=False
                    rec['media_error']=info.get('error')
                alt_strings=[]
                for d in rec['alt_text']:
                    for k in ('descr','title','name'):
                        if d.get(k): alt_strings.append(d[k])
                if alt_strings:
                    rec['value']=' | '.join(dict.fromkeys(alt_strings))
                    rec['image_text_status']='ALT_TEXT_ONLY'
                rows.append(rec)

        def emit_paragraph(p, path, block_id, parent_kind='document'):
            nonlocal paragraph_seq
            paragraph_seq+=1
            text=p.text.strip(); style_name=getattr(p.style,'name','') if p.style else ''
            base_id=f'{prefix}::{block_id}'
            if text:
                # Only paragraphs that carry text are comparable with discovery;
                # a blank paragraph is layout, not a missed Source Unit.
                if parent_kind=='document': extracted['body_paragraphs_with_text']+=1
                extracted['paragraphs_with_text']+=1
                rows.append({
                    'source_unit_id':base_id,'source_file':fp.name,'source_path':str(fp),
                    'kind':'paragraph','parent_kind':parent_kind,
                    'paragraph':paragraph_seq,'paragraph_style':style_name,
                    'heading_level':heading_level(style_name),'value':text,
                    'structure_path':path,'structure_path_text':structure_path_str(path)
                })
            add_textboxes(p._p,base_id,path,parent_kind,p.part)
            add_images(p._p,base_id,path,parent_kind,p.part)

        def emit_table(table, path, block_id, depth=0, parent_kind='document'):
            nonlocal table_seq
            table_seq+=1; this_table=table_seq
            extracted['tables']+=1
            if depth>0:
                extracted['nested_tables']+=1
            table_path=[*path, f'Table {this_table}']
            for ri,row in enumerate(table.rows,1):
                cells=[direct_cell_text(c) for c in row.cells]
                row_id=f'{prefix}::{block_id}::T{this_table:03d}::R{ri:04d}'
                row_path=[*table_path,f'Row {ri}']
                # A row is a Source Unit even when all of its content lives in a
                # nested table, so it counts as extracted either way.
                extracted['table_rows']+=1
                if not any(cells): extracted['table_rows_nested_content_only']+=1
                rows.append({
                    'source_unit_id':row_id,'source_file':fp.name,'source_path':str(fp),
                    'kind':'table-row','parent_kind':parent_kind,
                    'table':this_table,'row':ri,'table_depth':depth,
                    'is_nested_table':depth>0,'cells':cells,'value':' | '.join(cells),
                    'structure_path':row_path,'structure_path_text':structure_path_str(row_path)
                })
                seen_cell_xml=set()
                for ci,cell in enumerate(row.cells,1):
                    cell_path=[*row_path,f'Cell {ci}']
                    cell_xml_id=id(cell._tc)
                    if cell_xml_id in seen_cell_xml:
                        continue
                    seen_cell_xml.add(cell_xml_id)
                    # Surface drawings/textboxes from direct cell paragraphs only.
                    # Descendant nested-table content is handled recursively to avoid duplicate image/text-box units.
                    nested_idx=0; direct_para_idx=0
                    for kind,obj in iter_block_items(cell):
                        if kind=='paragraph':
                            direct_para_idx+=1
                            pid=f'{row_id}::C{ci:03d}::P{direct_para_idx:03d}'
                            ppath=[*cell_path,f'Paragraph {direct_para_idx}']
                            add_textboxes(obj._p,pid,ppath,'table-cell',obj.part)
                            add_images(obj._p,pid,ppath,'table-cell',obj.part)
                        elif kind=='table':
                            nested_idx+=1
                            emit_table(obj,[*cell_path,f'Nested {nested_idx}'],f'{block_id}::T{this_table:03d}::R{ri:04d}::C{ci:03d}::N{nested_idx:02d}',depth+1,'table-cell')

        body_block=0
        for kind,obj in iter_block_items(doc):
            body_block+=1
            block_id=f'B{body_block:06d}'
            if kind=='paragraph':
                emit_paragraph(obj,[f'Block {body_block}'],block_id)
            else:
                emit_table(obj,[f'Block {body_block}'],block_id,0)

        image_pending=sum(1 for r in rows if r.get('source_path')==str(fp) and r.get('kind')=='image' and r.get('image_text_status')=='PENDING_VISUAL_EXTRACTION')
        image_alt_only=sum(1 for r in rows if r.get('source_path')==str(fp) and r.get('kind')=='image' and r.get('image_text_status')=='ALT_TEXT_ONLY')
        discovered=discovery['discovered']
        extracted_counts={
            'body_paragraphs_with_text':extracted.get('body_paragraphs_with_text',0),
            'tables':extracted.get('tables',0),
            'nested_tables':extracted.get('nested_tables',0),
            'table_rows':extracted.get('table_rows',0),
            'text_boxes':extracted.get('text_boxes',0),
            'grouped_shapes':discovered.get('grouped_shapes',0),
        }
        discovered_parts=[x.lstrip('/') for x in discovery['image_parts']]
        missing_parts=sorted(set(discovered_parts)-extracted_image_parts)
        gaps=[]
        for key,label in (('body_paragraphs_with_text','body paragraphs with text'),
                          ('tables','tables'),('nested_tables','nested tables'),
                          ('table_rows','table rows'),('text_boxes','text boxes')):
            d=discovered.get(key,0); e=extracted_counts.get(key,0)
            if d>e:
                gaps.append({'structure':key,'discovered':d,'extracted':e,'detail':f'{d-e} {label} discovered in the package were not materialized as Source Units.'})
        if missing_parts:
            gaps.append({'structure':'image_parts','discovered':len(discovered_parts),'extracted':len(extracted_image_parts),
                         'detail':'Image parts referenced by document.xml produced no extracted media.','missing':missing_parts})
        reports.append({
            'source_file':fp.name,'source_path':str(fp),
            'discovered':discovered,
            'discovered_image_parts':discovered_parts,
            'media_files_in_package':discovery['media_files'],
            'extracted':extracted_counts,
            'extracted_detail':dict(extracted),
            'extracted_image_parts':sorted(extracted_image_parts),
            'parser_gaps':gaps,
            'unsupported_structures':discovery['unsupported'],
            'image_text_pending_visual_extraction':image_pending,
            'image_alt_text_only':image_alt_only,
            'source_structure_status':'FAIL' if gaps else ('REVIEW' if (image_pending or image_alt_only or discovery['unsupported']) else 'PASS')
        })

    write_jsonl(output,rows)
    def total(section,key):
        return sum(x.get(section,{}).get(key,0) for x in reports)
    all_gaps=[{'source_file':x['source_file'],**g} for x in reports for g in x['parser_gaps']]
    all_unsupported=[{'source_file':x['source_file'],**u} for x in reports for u in x['unsupported_structures']]
    report={
        'parser':'parse_word.py','report_schema_version':'2',
        'files':reports,
        'summary':{
            'files':len(files),'source_units':len(rows),
            'discovered_body_paragraphs_with_text':total('discovered','body_paragraphs_with_text'),
            'extracted_body_paragraphs_with_text':total('extracted','body_paragraphs_with_text'),
            'discovered_tables':total('discovered','tables'),'extracted_tables':total('extracted','tables'),
            'discovered_nested_tables':total('discovered','nested_tables'),'extracted_nested_tables':total('extracted','nested_tables'),
            'discovered_table_rows':total('discovered','table_rows'),'extracted_table_rows':total('extracted','table_rows'),
            'discovered_text_boxes':total('discovered','text_boxes'),'extracted_text_boxes':total('extracted','text_boxes'),
            'discovered_image_parts':sum(len(x.get('discovered_image_parts',[])) for x in reports),
            'extracted_image_parts':sum(len(x.get('extracted_image_parts',[])) for x in reports),
            'image_source_units':sum(x.get('extracted_detail',{}).get('image_units',0) for x in reports),
            'image_text_pending_visual_extraction':sum(x.get('image_text_pending_visual_extraction',0) for x in reports),
            'image_alt_text_only':sum(x.get('image_alt_text_only',0) for x in reports),
            'parser_gap_count':len(all_gaps),
            'unsupported_structure_count':sum(u.get('count',0) for u in all_unsupported),
        },
        'parser_gaps':all_gaps,
        'unsupported_structures':all_unsupported,
    }
    s=report['summary']
    report['status']=('FAIL' if all_gaps else
                      'REVIEW' if (s['image_text_pending_visual_extraction'] or s['image_alt_text_only'] or all_unsupported)
                      else 'PASS')
    if a.structure_report:
        rp=Path(a.structure_report); rp.parent.mkdir(parents=True,exist_ok=True)
        rp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"files={len(files)} source_units={len(rows)} tables={s['extracted_tables']}/{s['discovered_tables']} nested={s['extracted_nested_tables']}/{s['discovered_nested_tables']} text_boxes={s['extracted_text_boxes']}/{s['discovered_text_boxes']} images={s['extracted_image_parts']}/{s['discovered_image_parts']} pending_visual={s['image_text_pending_visual_extraction']} gaps={s['parser_gap_count']} unsupported={s['unsupported_structure_count']} status={report['status']} output={output}")

if __name__=='__main__': main()
