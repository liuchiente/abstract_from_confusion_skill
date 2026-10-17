#!/usr/bin/env python3
from pathlib import Path
import argparse, hashlib, json, sqlite3, subprocess, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import TOKENIZER_VERSION

INDEX_SCHEMA_VERSION = '10'


def sha256_file(path):
    if not path: return None
    p=Path(path)
    if not p.exists(): return None
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def current_hashes(a):
    return {
        'field_xlsx':sha256_file(a.field_xlsx),
        'cards':sha256_file(a.cards),
        'evidence':sha256_file(a.evidence),
        'links':sha256_file(a.links),
        'context_map':sha256_file(a.context_map),
        'boxes':sha256_file(a.boxes),
        'box_memberships':sha256_file(a.box_memberships),
        'box_links':sha256_file(a.box_links),
        'scope_attributions':sha256_file(a.scope_attributions),
        'domains':sha256_file(a.domains),
    }


def indexed_meta(db):
    p=Path(db)
    if not p.exists(): return None
    try:
        con=sqlite3.connect(p)
        rows=con.execute("SELECT key,value FROM meta").fetchall()
        con.close()
    except Exception:
        return None
    out={}
    for k,v in rows:
        try: out[k]=json.loads(v)
        except Exception: out[k]=v
    return out


def main():
    ap=argparse.ArgumentParser(description='Reuse AFC query index when knowledge, Box graph, and mappings are unchanged; rebuild only when stale.')
    ap.add_argument('--field-xlsx'); ap.add_argument('--cards'); ap.add_argument('--evidence'); ap.add_argument('--links'); ap.add_argument('--context-map')
    ap.add_argument('--boxes'); ap.add_argument('--box-memberships'); ap.add_argument('--box-links'); ap.add_argument('--scope-attributions'); ap.add_argument('--domains'); ap.add_argument('--db',required=True)
    a=ap.parse_args(); cur=current_hashes(a); meta=indexed_meta(a.db) or {}
    old=meta.get('source_hashes')
    reasons=[]
    if meta.get('tokenizer_version')!=TOKENIZER_VERSION:
        reasons.append(f"tokenizer_version {meta.get('tokenizer_version')!r} != {TOKENIZER_VERSION!r}")
    if str(meta.get('schema_version'))!=INDEX_SCHEMA_VERSION:
        reasons.append(f"index schema_version {meta.get('schema_version')!r} != {INDEX_SCHEMA_VERSION!r}")
    if old!=cur:
        changed=[k for k in cur if (old or {}).get(k)!=cur[k]] if old else ['(no indexed hashes)']
        reasons.append('source changed: '+', '.join(changed))
    if not reasons:
        print(json.dumps({'status':'fresh','db':a.db,'tokenizer_version':TOKENIZER_VERSION,
                          'index_schema_version':INDEX_SCHEMA_VERSION,'source_hashes':cur},
                         ensure_ascii=False)); return
    builder=Path(__file__).with_name('build_query_index.py')
    cmd=[sys.executable,str(builder),'-o',a.db]
    for flag,val in [
        ('--field-xlsx',a.field_xlsx),('--cards',a.cards),('--evidence',a.evidence),('--links',a.links),('--context-map',a.context_map),
        ('--boxes',a.boxes),('--box-memberships',a.box_memberships),('--box-links',a.box_links),('--domains',a.domains)]:
        if val: cmd += [flag,val]
    if a.scope_attributions: cmd += ['--scope-attributions',a.scope_attributions]
    subprocess.run(cmd,check=True)
    print(json.dumps({'status':'rebuilt','db':a.db,'rebuild_reasons':reasons,
                      'tokenizer_version':TOKENIZER_VERSION,
                      'index_schema_version':INDEX_SCHEMA_VERSION,
                      'old_hashes':old,'source_hashes':cur},ensure_ascii=False))

if __name__=='__main__': main()
