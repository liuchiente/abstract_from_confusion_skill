#!/usr/bin/env python3
"""Cross-file checks on source-preserving Evidence Records.

Shapes live in schemas/evidence-record.schema.json. This script checks the
things a schema cannot: Card<->Evidence edges agree in both directions, every
literal/structured Evidence actually carries a source fact, and lifecycle status
is coherent.
"""
from pathlib import Path
import argparse, re, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, write_json, normalize_text

ALLOWED_MODES={'VERBATIM','STRUCTURED','VERBATIM+STRUCTURED'}

def main():
    ap=argparse.ArgumentParser(description='Validate AFC Evidence Records and optional Card linkage.')
    ap.add_argument('evidence')
    ap.add_argument('--cards')
    ap.add_argument('--json-output')
    a=ap.parse_args()
    rows=read_jsonl(a.evidence); errors=[]; warnings=[]; ids=set()
    card_ids=set(); card_rows=[]
    if a.cards and Path(a.cards).exists():
        card_rows=read_jsonl(a.cards)
        card_ids={str(x.get('Card ID','')).strip() for x in card_rows}
    for i,r in enumerate(rows,1):
        eid=str(r.get('Evidence ID','')).strip()
        if not re.fullmatch(r'EVD-\d{6}',eid): errors.append(f'row {i}: invalid Evidence ID {eid!r}')
        if eid in ids: errors.append(f'row {i}: duplicate Evidence ID {eid}')
        ids.add(eid)
        mode=str(r.get('Evidence Mode','')).strip()
        if mode not in ALLOWED_MODES: errors.append(f'row {i}: invalid Evidence Mode {mode!r}')
        if 'Original Text' not in r: errors.append(f'row {i}: missing Original Text field')
        if not str(r.get('Source','')).strip(): errors.append(f'row {i}: missing Source')
        if not str(r.get('Source Location','')).strip(): errors.append(f'row {i}: missing Source Location')
        for cid in r.get('Card IDs') or []:
            if card_ids and cid not in card_ids: errors.append(f'row {i}: unknown Card ID {cid}')
        if mode in {'STRUCTURED','VERBATIM+STRUCTURED'}:
            has_structured=bool(r.get('Structured Facts')) or any(
                k in r and r.get(k) not in (None,'',[]) for k in [
                    'Original Name','Original Description','Original Message','Original Component Type',
                    'Original Code','Original Value','Original Label','Original Placeholder','Original Required',
                    'Original Max Length','Original Min Length','Original Format','Original Validation Message',
                    'Original Error Message','Original Option Values','Original Function Code'
                ])
            if not has_structured: warnings.append(f'row {i}: structured mode has no structured source facts')
        status=normalize_text(r.get('Status')) or 'Active'
        if status not in {'Active','Superseded','Retired'}:
            errors.append(f'row {i} {eid}: invalid Status {status!r}')

    if card_rows:
        evidence_ids=ids
        # Card -> Evidence
        card_to_evidence={}
        for i,c in enumerate(card_rows,1):
            cid=normalize_text(c.get('Card ID')); ctype=normalize_text(c.get('Card Type'))
            refs=[normalize_text(x) for x in (c.get('Evidence Record IDs') or []) if normalize_text(x)]
            card_to_evidence[cid]=set(refs)
            if ctype not in {'Concept','Context'} and not refs:
                errors.append(f'card row {i} {cid}: source-derived card has no Evidence Record IDs')
            for eid in refs:
                if eid not in evidence_ids: errors.append(f'card row {i} {cid}: unknown Evidence ID {eid}')
        # Evidence -> Card, and agreement between the two directions.
        for i,r in enumerate(rows,1):
            eid=normalize_text(r.get('Evidence ID'))
            for cid in [normalize_text(x) for x in (r.get('Card IDs') or []) if normalize_text(x)]:
                if cid not in card_ids:
                    errors.append(f'row {i} {eid}: unknown Card ID {cid}')
                elif eid not in card_to_evidence.get(cid,set()):
                    warnings.append(f'row {i} {eid}: claims Card {cid}, but that Card does not list '
                                    f'this Evidence ID; the edge is one-directional')
        for cid,refs in card_to_evidence.items():
            for eid in refs:
                row=next((x for x in rows if normalize_text(x.get('Evidence ID'))==eid), None)
                if row is not None:
                    back=[normalize_text(x) for x in (row.get('Card IDs') or [])]
                    if back and cid not in back:
                        warnings.append(f'card {cid}: references Evidence {eid}, which lists Cards '
                                        f'{back} instead')
    result={'evidence':len(rows),'errors':errors,'warnings':warnings,
            'error_count':len(errors),'warning_count':len(warnings),
            'status':'PASS' if not errors else 'FAIL'}
    print(f'evidence={len(rows)} errors={len(errors)} warnings={len(warnings)}')
    for e in errors[:100]: print('ERROR',e)
    for w in warnings[:100]: print('WARN',w)
    if a.json_output: write_json(a.json_output,result)
    raise SystemExit(1 if errors else 0)

if __name__=='__main__': main()
