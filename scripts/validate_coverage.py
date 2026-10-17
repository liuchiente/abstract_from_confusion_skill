#!/usr/bin/env python3
from pathlib import Path
import argparse, json, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl

def main():
    ap=argparse.ArgumentParser(description='Validate AFC Card source-unit accounting: every selected source unit must produce Cards, an explicit Skip, or an explicit Review item.')
    ap.add_argument('--source-map',required=True)
    ap.add_argument('--coverage',required=True)
    ap.add_argument('--cards',required=True)
    ap.add_argument('--json-output')
    a=ap.parse_args()
    source=read_jsonl(a.source_map); ledger=read_jsonl(a.coverage); cards=read_jsonl(a.cards)
    selected={r.get('source_unit_id'):r for r in source if r.get('selected') and r.get('source_unit_id')}
    card_ids={c.get('Card ID') for c in cards if c.get('Card ID')}
    ledger_by={}; errors=[]
    for row in ledger:
        sid=row.get('Source Unit ID')
        if not sid:
            errors.append('Coverage row missing Source Unit ID'); continue
        if sid in ledger_by: errors.append(f'Duplicate coverage row: {sid}')
        ledger_by[sid]=row
        disp=row.get('Disposition'); ids=row.get('Card IDs') or []
        if disp=='Card':
            if not ids: errors.append(f'Card disposition without Card IDs: {sid}')
            for cid in ids:
                if cid not in card_ids: errors.append(f'Unknown Card ID {cid} for {sid}')
        elif disp=='Skip':
            if not str(row.get('Skip Reason') or '').strip(): errors.append(f'Skip without reason: {sid}')
        elif disp=='Review':
            if not str(row.get('Review Reason') or row.get('Notes') or '').strip(): errors.append(f'Review without reason: {sid}')
        else:
            errors.append(f'Invalid Disposition for {sid}: {disp!r}')
    missing=[sid for sid in selected if sid not in ledger_by]
    extra=[sid for sid in ledger_by if sid not in selected]
    if missing: errors.append(f'Unaccounted selected source units: {len(missing)}')
    if extra: errors.append(f'Coverage rows outside selected context: {len(extra)}')
    counts={'Card':0,'Skip':0,'Review':0}
    by_kind={}
    by_section={}
    for sid,r in selected.items():
        kind=r.get('kind','unknown')
        d=by_kind.setdefault(kind,{'selected':0,'card':0,'skip':0,'review':0,'missing':0})
        d['selected']+=1
        row=ledger_by.get(sid)
        section_path=r.get('section_heading_path') or []
        section_label=' / '.join(str(x) for x in section_path if str(x).strip()) or '[未識別章節]'
        section_key=f"{r.get('source_path') or r.get('source_file','[unknown source]')}::{r.get('section_key') or section_label}"
        section=by_section.setdefault(section_key,{
            'source_file':r.get('source_file',''),
            'section_heading_path':section_path,
            'section_heading_path_text':section_label,
            'selected':0,'card':0,'skip':0,'review':0,'missing':0,
        })
        section['selected']+=1
        if not row: d['missing']+=1
        else:
            disp=row.get('Disposition')
            if disp in counts:
                counts[disp]+=1; d[disp.lower()]+=1; section[disp.lower()]+=1
        if not row: section['missing']+=1
    result={
        'selected_source_units':len(selected),
        'accounted_source_units':len(selected)-len(missing),
        'card_source_units':counts['Card'],
        'skipped_source_units':counts['Skip'],
        'review_source_units':counts['Review'],
        'unaccounted_source_units':len(missing),
        'coverage_accounting_rate': (len(selected)-len(missing))/len(selected) if selected else 1.0,
        'review_rate': counts['Review']/len(selected) if selected else 0.0,
        # A work-in-progress gap is kept separate from an intentional Review.
        # Section grouping makes incomplete extraction visible at the same
        # boundaries used to reason about article topics.
        'by_section':sorted(by_section.values(), key=lambda x:(x['source_file'], x['section_heading_path_text'])),
        'card_count':len(cards),
        'by_kind':by_kind,
        'errors':errors,
        'status':'PASS' if not errors else 'FAIL',
        'sample_unaccounted':missing[:20],
        'sample_extra':extra[:20]
    }
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if a.json_output:
        Path(a.json_output).parent.mkdir(parents=True,exist_ok=True)
        Path(a.json_output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(0 if not errors else 2)
if __name__=='__main__': main()
