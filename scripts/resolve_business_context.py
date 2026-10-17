#!/usr/bin/env python3
from pathlib import Path
import argparse, json, re, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.scope import load_business_context_map


def norm(s):
    return re.sub(r'\s+', ' ', str(s or '').strip()).lower()


def load_map(path):
    return load_business_context_map(path)


def resolve(text, rows, explicit_contexts=None):
    q=str(text or '')
    qn=norm(q)
    requested=[]
    if explicit_contexts:
        requested=[str(x).strip() for x in explicit_contexts if str(x).strip()]
    matches=[]
    seen=set()
    for row in rows:
        matched_aliases=[]
        for alias in row['aliases']:
            a=norm(alias)
            if not a:
                continue
            explicit = any(norm(x)==a or norm(x)==norm(row['context']) for x in requested)
            if explicit or a in qn:
                matched_aliases.append(alias)
        if matched_aliases:
            key=row['context']
            if key not in seen:
                matches.append({**row, 'matched_aliases':matched_aliases})
                seen.add(key)
    scopes=[]
    for m in matches:
        for s in m['scopes']:
            if s not in scopes:
                scopes.append(s)
    return {'query':q,'business_contexts':[m['context'] for m in matches],'resolved_scopes':scopes,'matches':matches}


def main():
    ap=argparse.ArgumentParser(description='Resolve high-level AFC business context to one or more active scopes.')
    ap.add_argument('--map', required=True)
    ap.add_argument('--query', default='')
    ap.add_argument('--context', action='append', default=[])
    ap.add_argument('-o','--output')
    a=ap.parse_args()
    out=resolve(a.query, load_map(a.map), a.context)
    text=json.dumps(out,ensure_ascii=False,indent=2)
    if a.output:
        p=Path(a.output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text,encoding='utf-8'); print(str(p))
    else:
        print(text)

if __name__=='__main__':
    main()
