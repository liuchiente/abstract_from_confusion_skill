#!/usr/bin/env python3
from pathlib import Path
import argparse, json, re, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, normalize_text

BOX_RE=re.compile(r'^BOX-\d{6}$'); BM_RE=re.compile(r'^BM-\d{6}$'); BL_RE=re.compile(r'^BL-\d{6}$'); CARD_RE=re.compile(r'^CARD-\d{6}$')
ALLOWED_TYPES={'Business','Scenario','Function','Screen','Inbox'}
ALLOWED_MEMBERSHIP_TYPES={'belongs_to','valid_in','uses_function','defined_in','shared_in'}
ALLOWED_BASIS={'Direct Source','Structural Context','Business Context Mapping','Function Evidence','Scenario Evidence','Screen Evidence','Inherited Box','Manual Configuration','Review'}
ALLOWED_REL={'parent_of','part_of','related_to','depends_on','precedes','uses_function','shared_with'}
ALLOWED_LINK_BASIS={'Direct Source','Structural Context','Business Context Mapping','Company Taxonomy','Cross-Card Evidence','Manual Configuration','Review'}
SYMMETRIC={'related_to','shared_with'}
SHARED_SCOPES={'Multiple','多商品','Shared','shared'}


def card_scopes(card):
    v=card.get('Scopes')
    if v is None: v=card.get('Scope')
    if v is None: v=card.get('Product Context')
    if isinstance(v,list): vals=v
    elif v is None: vals=[]
    else: vals=re.split(r'[,;，；]+',normalize_text(v))
    return [normalize_text(x) for x in vals if normalize_text(x)]


def main():
    ap=argparse.ArgumentParser(description='Validate AFC Box nodes, Card↔Box memberships, and Box↔Box topology.')
    ap.add_argument('--boxes',required=True); ap.add_argument('--memberships',required=True); ap.add_argument('--box-links',required=True); ap.add_argument('--cards',required=True); ap.add_argument('--json-output')
    a=ap.parse_args(); boxes=read_jsonl(a.boxes); mem=read_jsonl(a.memberships); edges=read_jsonl(a.box_links); cards=read_jsonl(a.cards)
    errors=[]; warnings=[]; box_ids=set(); box_by_id={}; keys=set()
    card_by_id={normalize_text(x.get('Card ID')):x for x in cards if normalize_text(x.get('Card ID'))}

    for i,b in enumerate(boxes,1):
        bid=normalize_text(b.get('Box ID')); typ=normalize_text(b.get('Box Type')); key=normalize_text(b.get('Canonical Key')); name=normalize_text(b.get('Name'))
        if not BOX_RE.match(bid): errors.append(f'box row {i}: invalid Box ID {bid!r}')
        if bid in box_ids: errors.append(f'box row {i}: duplicate Box ID {bid}')
        box_ids.add(bid); box_by_id[bid]=b
        if typ not in ALLOWED_TYPES: errors.append(f'box {bid}: invalid Box Type {typ!r}')
        if not name: errors.append(f'box {bid}: missing Name')
        if not key: errors.append(f'box {bid}: missing Canonical Key')
        elif key in keys: errors.append(f'box {bid}: duplicate Canonical Key {key!r}')
        keys.add(key)
        if b.get('Parent Box IDs'): warnings.append(f'box {bid}: Parent Box IDs is deprecated; represent hierarchy in box-links')

    mids=set(); membership_identity=set(); degree={bid:0 for bid in box_ids}
    for i,m in enumerate(mem,1):
        mid=normalize_text(m.get('Membership ID')); bid=normalize_text(m.get('Box ID')); cid=normalize_text(m.get('Card ID')); mt=normalize_text(m.get('Membership Type')); basis=normalize_text(m.get('Membership Basis'))
        if not BM_RE.match(mid): errors.append(f'membership row {i}: invalid Membership ID {mid!r}')
        if mid in mids: errors.append(f'membership row {i}: duplicate Membership ID {mid}')
        mids.add(mid)
        if bid not in box_ids: errors.append(f'membership {mid}: missing Box {bid}')
        if cid not in card_by_id: errors.append(f'membership {mid}: missing Card {cid}')
        if mt not in ALLOWED_MEMBERSHIP_TYPES: errors.append(f'membership {mid}: invalid Membership Type {mt!r}')
        if basis not in ALLOWED_BASIS: errors.append(f'membership {mid}: invalid basis {basis!r}')
        ident=(cid,bid,mt)
        if ident in membership_identity: errors.append(f'membership {mid}: duplicate identity {ident}')
        membership_identity.add(ident); degree[bid]=degree.get(bid,0)+1
        if normalize_text(m.get('Status'))=='Confirmed' and basis not in {'Manual Configuration'} and not normalize_text(m.get('Evidence')):
            warnings.append(f'membership {mid}: confirmed source-derived membership has no Evidence')
        # Product boundary mismatch warning for Business boxes with Scope Hints.
        if cid in card_by_id and bid in box_by_id:
            b=box_by_id[bid]; hints={normalize_text(x) for x in (b.get('Scope Hints') or []) if normalize_text(x)}; scopes=set(card_scopes(card_by_id[cid]))
            if b.get('Box Type')=='Business' and hints and scopes and not scopes.intersection(hints) and not scopes.intersection(SHARED_SCOPES):
                warnings.append(f'membership {mid}: Card scopes {sorted(scopes)} do not match Business Box scope hints {sorted(hints)}')

    eids=set(); edge_ident=set(); hierarchy={bid:set() for bid in box_ids}
    for i,e in enumerate(edges,1):
        eid=normalize_text(e.get('Box Link ID')); s=normalize_text(e.get('Source Box ID')); t=normalize_text(e.get('Target Box ID')); rel=normalize_text(e.get('Relation Type')); basis=normalize_text(e.get('Link Basis'))
        if not BL_RE.match(eid): errors.append(f'box-link row {i}: invalid Box Link ID {eid!r}')
        if eid in eids: errors.append(f'box-link row {i}: duplicate Box Link ID {eid}')
        eids.add(eid)
        if s not in box_ids: errors.append(f'box-link {eid}: missing source Box {s}')
        if t not in box_ids: errors.append(f'box-link {eid}: missing target Box {t}')
        if s and s==t: errors.append(f'box-link {eid}: self link')
        if rel not in ALLOWED_REL: errors.append(f'box-link {eid}: invalid relation {rel!r}')
        if basis not in ALLOWED_LINK_BASIS: errors.append(f'box-link {eid}: invalid Link Basis {basis!r}')
        ident=(s,rel,t)
        if rel in SYMMETRIC: ident=tuple(sorted([s,t]))+(rel,)
        if ident in edge_ident: errors.append(f'box-link {eid}: duplicate relation identity {ident}')
        edge_ident.add(ident); degree[s]=degree.get(s,0)+1; degree[t]=degree.get(t,0)+1
        if rel=='parent_of': hierarchy.setdefault(s,set()).add(t)
        elif rel=='part_of': hierarchy.setdefault(t,set()).add(s)
        if normalize_text(e.get('Status'))=='Confirmed' and basis not in {'Manual Configuration','Company Taxonomy'} and not normalize_text(e.get('Evidence')):
            warnings.append(f'box-link {eid}: confirmed source-derived relation has no Evidence')

    # Legacy parent fields participate in cycle check for migration safety.
    for b in boxes:
        child=normalize_text(b.get('Box ID'))
        for p in b.get('Parent Box IDs') or []:
            p=normalize_text(p)
            if p not in box_ids: errors.append(f'box {child}: dangling legacy parent {p}')
            elif p==child: errors.append(f'box {child}: self legacy parent')
            else: hierarchy.setdefault(p,set()).add(child)

    visiting=set(); visited=set(); cycle=None
    def dfs(n,path):
        nonlocal cycle
        if n in visiting:
            idx=path.index(n) if n in path else 0; cycle=path[idx:]+[n]; return True
        if n in visited: return False
        visiting.add(n)
        for c in hierarchy.get(n,set()):
            if dfs(c,path+[n]): return True
        visiting.remove(n); visited.add(n); return False
    for n in box_ids:
        if dfs(n,[]): break
    if cycle: errors.append('box hierarchy cycle: '+' -> '.join(cycle))

    membership_cards={normalize_text(m.get('Card ID')) for m in mem if normalize_text(m.get('Card ID'))}
    orphan_cards=sorted(set(card_by_id)-membership_cards)
    if orphan_cards: warnings.append(f'{len(orphan_cards)} Cards have no Box membership')
    high_degree=sorted(({'box_id':bid,'name':normalize_text(box_by_id.get(bid,{}).get('Name')),'degree':d} for bid,d in degree.items() if d>=20),key=lambda x:-x['degree'])
    if high_degree: warnings.append(f'{len(high_degree)} high-degree Boxes (degree >= 20) require review for over-broad boundaries')
    related_count=sum(1 for e in edges if normalize_text(e.get('Relation Type'))=='related_to')
    if related_count>max(20,len(boxes)*2): warnings.append('Broad related_to fan-out may create topology noise')

    report={'status':'PASS' if not errors else 'FAIL','box_count':len(boxes),'membership_count':len(mem),'box_link_count':len(edges),'card_count':len(cards),'orphan_card_count':len(orphan_cards),'high_degree_boxes':high_degree,'errors':errors,'warnings':warnings}
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if a.json_output:
        p=Path(a.json_output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text,encoding='utf-8'); print(str(p))
    else: print(text)
    raise SystemExit(0 if not errors else 1)

if __name__=='__main__': main()
