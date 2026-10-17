#!/usr/bin/env python3
from pathlib import Path
import argparse, json, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, write_jsonl
from afc_card_runtime.config import load_settings

_settings=load_settings()
ap=argparse.ArgumentParser(description='Merge OCR, human, or explicitly requested vision text back into image and scanned-PDF Source Units.')
ap.add_argument('--source-map',required=True,help='One parser output to enrich in place; the '
                'output keeps that map\'s unit set, so run it once per map that holds images.')
ap.add_argument('--visual-jsonl',required=True,help='JSONL rows: source_unit_id, original_text, optional source_language/confidence/extraction_method')
ap.add_argument('-o','--output',required=True)
ap.add_argument('--min-confidence',type=float,default=_settings.get('ocr.min_confidence',0.75),help='Lower-confidence output is retained as review text, not confirmed literal evidence.')
a=ap.parse_args()
if not 0.0 <= a.min_confidence <= 1.0: ap.error('--min-confidence must be between 0 and 1')
# read_jsonl returns [] for a path that does not exist, which would write an
# empty "enriched" map over a mistyped name and look like a successful merge.
for required in (a.source_map, a.visual_jsonl):
    if not Path(required).exists(): ap.error(f'input not found: {required}')
rows=read_jsonl(a.source_map); vis=read_jsonl(a.visual_jsonl)
by_id={str(x.get('source_unit_id')):x for x in vis if x.get('source_unit_id')}
updated=0; low_confidence=0; missing=[]
for r in rows:
    sid=str(r.get('source_unit_id') or '')
    supported = r.get('kind') == 'image' or (r.get('kind') == 'pdf-block' and r.get('image_text_status') == 'PENDING_VISUAL_EXTRACTION')
    if not supported or sid not in by_id: continue
    x=by_id[sid]
    items=x.get('items') or []
    text=str(x.get('original_text') or '')
    if not text and items:
        text='\n'.join(str(i.get('text') or '') for i in items if i.get('text'))
    if not text: continue
    r['visual_original_text']=text
    r['visual_items']=items
    r['value']=text
    r['source_language']=x.get('source_language') or r.get('source_language')
    r['visual_extraction_method']=x.get('extraction_method') or 'VISION'
    r['visual_extraction_confidence']=x.get('confidence')
    confidence=x.get('confidence')
    try:
        confidence_value=float(confidence)
    except (TypeError, ValueError):
        confidence_value=None
    if confidence_value is None or not 0.0 <= confidence_value <= 1.0 or confidence_value < a.min_confidence:
        r['image_text_status']='LOW_CONFIDENCE_REVIEW'
        r['literal_source_status']='OCR_CANDIDATE_REVIEW'
        low_confidence+=1
    else:
        r['image_text_status']='VISUAL_EXTRACTED'
        r['literal_source_status']='EXTRACTED_VERBATIM_FROM_IMAGE'
    updated+=1
for sid in by_id:
    if not any(str(r.get('source_unit_id') or '')==sid for r in rows): missing.append(sid)
write_jsonl(a.output,rows)
print(json.dumps({'updated_source_units':updated,'low_confidence_review':low_confidence,'unknown_source_unit_ids':missing,'output':a.output},ensure_ascii=False,indent=2))
