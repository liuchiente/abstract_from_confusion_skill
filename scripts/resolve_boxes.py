#!/usr/bin/env python3
from pathlib import Path
import argparse, json, re, sqlite3, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import normalize_text


def alias_in_query(alias, query):
    alias=normalize_text(alias); query=normalize_text(query)
    if not alias or not query: return False
    if re.fullmatch(r'[A-Za-z0-9_-]+',alias):
        return re.search(r'(?<![A-Za-z0-9_])'+re.escape(alias)+r'(?![A-Za-z0-9_])',query,flags=re.I) is not None
    return alias.lower() in query.lower()


def main():
    ap=argparse.ArgumentParser(description='Resolve AFC Box aliases from a built query index.')
    ap.add_argument('--db',required=True); ap.add_argument('--query',required=True); ap.add_argument('--box',action='append',default=[])
    a=ap.parse_args(); con=sqlite3.connect(a.db)
    rows=con.execute('''SELECT b.id,b.box_type,b.name,b.canonical_key,b.scope_hints,a.alias
                        FROM boxes b JOIN box_alias_map a ON a.box_id=b.id
                        ORDER BY length(a.alias) DESC''').fetchall()
    explicit=[normalize_text(x) for x in a.box if normalize_text(x)]
    out=[]; seen=set()
    for bid,btype,name,key,hints_json,alias in rows:
        if explicit:
            candidates={normalize_text(x).lower() for x in [bid,btype,name,key,alias] if normalize_text(x)}
            ok=any(x.lower() in candidates for x in explicit)
        else: ok=alias_in_query(alias,a.query)
        if not ok or bid in seen: continue
        seen.add(bid)
        try: hints=json.loads(hints_json or '[]')
        except Exception: hints=[]
        descendants=[x[0] for x in con.execute('SELECT descendant_id FROM box_closure WHERE ancestor_id=? ORDER BY depth,descendant_id',(bid,)).fetchall()]
        out.append({'box_id':bid,'box_type':btype,'name':name,'canonical_key':key,'matched_alias':alias,'scope_hints':hints,'hierarchy_descendants':descendants})
    con.close(); print(json.dumps({'query':a.query,'boxes':out},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
