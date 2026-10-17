#!/usr/bin/env python3
from pathlib import Path
import argparse, json, re, sqlite3, sys, time
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import normalize_text, fts_terms, fts_or_expr
from afc_card_runtime.config import load_settings

LINK_INTENT={
  'relationship':['controls','applies_to','depends_on'],
  'reference':['references','defines'],
  'concept':['instance_of','defines'],
}
NON_HIER_BOX_RELATIONS=['related_to','depends_on','precedes','uses_function','shared_with']
INTENT_ORDER=['box_relationship','relationship','comparison','field_lookup','reference','concept']

# Loaded from config/query-terms.yaml so query vocabulary (and its languages)
# is configuration, not code. v0.4.1 hard-coded zh-TW/English lists and matched
# them as bare substrings, so 'code' fired on 'barcode' and a Vietnamese
# question never reached the Evidence layer.
TERMS={'intent':{},'rule_terms':[],'target_mode':{},'box_relations':{},'card_types':{},'language_hints':{}}
_ASCII_TERM=re.compile(r'^[A-Za-z0-9_-]+$')


def load_query_terms(path):
    data={}
    if path and Path(path).exists():
        data=yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    return {
        'intent':{k:list(v or []) for k,v in (data.get('intent') or {}).items()},
        'rule_terms':list(data.get('rule_terms') or []),
        'target_mode':{k:list(v or []) for k,v in (data.get('target_mode') or {}).items()},
        'box_relations':{k:list(v or []) for k,v in (data.get('box_relations') or {}).items()},
        'card_types':{k:list(v or []) for k,v in (data.get('card_types') or {}).items()},
        'language_hints':{k:list(v or []) for k,v in (data.get('language_hints') or {}).items()},
    }


def term_in(term, text):
    """ASCII terms match on word boundaries; everything else as a substring."""
    term=normalize_text(term)
    if not term: return False
    if _ASCII_TERM.match(term):
        return re.search(r'(?<![A-Za-z0-9_])'+re.escape(term)+r'(?![A-Za-z0-9_])', text, flags=re.I) is not None
    return term.lower() in text.lower()


def any_term(terms, text):
    return any(term_in(t, text) for t in terms or [])


def matched_terms(terms, text):
    return [t for t in terms or [] if term_in(t, text)]


def detect_intent(q):
    low=normalize_text(q)
    for intent in INTENT_ORDER:
        terms=TERMS['intent'].get(intent) or []
        if not any_term(terms, low): continue
        # A field question that also names rules/conditions is a knowledge question.
        if intent=='field_lookup' and any_term(TERMS['rule_terms'], low): continue
        return intent
    return 'knowledge'


def detect_target_mode(q):
    low=normalize_text(q)
    is_structured=any_term(TERMS['target_mode'].get('structured_fact'), low)
    is_literal=any_term(TERMS['target_mode'].get('literal'), low)
    if is_structured and is_literal: return 'mixed'
    if is_structured: return 'structured_fact'
    if is_literal: return 'literal'
    return 'semantic'


def detect_source_languages(q):
    """Languages the question explicitly asks for, e.g. 「越文錯誤訊息」 -> ['vi']."""
    low=normalize_text(q)
    return [lang for lang,terms in (TERMS.get('language_hints') or {}).items() if any_term(terms, low)]


def target_mode_evidence(q):
    low=normalize_text(q)
    return {'literal_terms':matched_terms(TERMS['target_mode'].get('literal'), low),
            'structured_terms':matched_terms(TERMS['target_mode'].get('structured_fact'), low)}


def _alias_in_query(alias, query):
    alias=normalize_text(alias); query=normalize_text(query)
    if not alias or not query: return False
    if re.fullmatch(r'[A-Za-z0-9_-]+', alias):
        return re.search(r'(?<![A-Za-z0-9_])'+re.escape(alias)+r'(?![A-Za-z0-9_])', query, flags=re.I) is not None
    return alias.lower() in query.lower()


def resolve_business_contexts(con, query, explicit_contexts):
    try: rows=con.execute('SELECT context,alias,scope,description FROM business_context_map ORDER BY length(alias) DESC').fetchall()
    except sqlite3.OperationalError: rows=[]
    explicit=[normalize_text(x) for x in (explicit_contexts or []) if normalize_text(x)]
    matched=[]; seen=set(); scopes=[]; aliases=[]
    for context,alias,scope,desc in rows:
        ok=any(x.lower() in {normalize_text(context).lower(),normalize_text(alias).lower()} for x in explicit) if explicit else _alias_in_query(alias,query)
        if not ok: continue
        key=(context,alias,scope)
        if key in seen: continue
        seen.add(key); matched.append({'context':context,'alias':alias,'scope':scope,'description':desc})
        if scope and scope not in scopes: scopes.append(scope)
        if alias and alias not in aliases: aliases.append(alias)
    contexts=[]
    for m in matched:
        if m['context'] not in contexts: contexts.append(m['context'])
    return {'contexts':contexts,'scopes':scopes,'aliases':aliases,'matches':matched}


def resolve_boxes(con, query, explicit_boxes):
    rows=con.execute('''SELECT b.id,b.box_type,b.name,b.canonical_key,b.description,b.status,b.scope_hints,a.alias
                        FROM boxes b JOIN box_alias_map a ON a.box_id=b.id
                        ORDER BY length(a.alias) DESC''').fetchall()
    explicit=[normalize_text(x) for x in (explicit_boxes or []) if normalize_text(x)]
    matched=[]; seen=set(); aliases=[]
    for bid,btype,name,key,desc,status,hints_json,alias in rows:
        if explicit:
            candidates={normalize_text(bid).lower(),normalize_text(name).lower(),normalize_text(key).lower(),normalize_text(alias).lower()}
            ok=any(x.lower() in candidates for x in explicit)
        else:
            ok=_alias_in_query(alias,query)
        if not ok or bid in seen: continue
        seen.add(bid)
        try: hints=json.loads(hints_json or '[]')
        except Exception: hints=[]
        matched.append({'box_id':bid,'box_type':btype,'name':name,'canonical_key':key,'description':desc,'status':status,'scope_hints':hints,'matched_alias':alias})
        if alias not in aliases: aliases.append(alias)
    return {'boxes':matched,'aliases':aliases}


def qterms(q, removals, limit=12):
    text=q
    for a in removals or []:
        a=normalize_text(a)
        if not a: continue
        if re.fullmatch(r'[A-Za-z0-9_-]+',a): text=re.sub(r'(?<![A-Za-z0-9_])'+re.escape(a)+r'(?![A-Za-z0-9_])',' ',text,flags=re.I)
        else: text=re.sub(re.escape(a),' ',text,flags=re.I)
    # fts_terms drops FTS5 operator words (AND/OR/NOT/NEAR), which v0.4.1 passed
    # straight through -- a query like 'A OR B' injected a bare `or` term.
    return fts_terms(text, min_len=2, limit=limit)


def fts_expr(terms):
    return fts_or_expr(terms)


def payloads(con, table, ids):
    if not ids: return []
    qs=','.join('?'*len(ids)); rows=con.execute(f'SELECT id,payload FROM {table} WHERE id IN ({qs})',ids).fetchall(); by={i:json.loads(p) for i,p in rows}
    return [by[i] for i in ids if i in by]


def hierarchy_boxes(con, box_id):
    rows=con.execute('SELECT descendant_id FROM box_closure WHERE ancestor_id=? ORDER BY depth,descendant_id',(box_id,)).fetchall()
    return [x[0] for x in rows] or [box_id]


def cards_for_box_boundary(con, seed_box_ids):
    if not seed_box_ids: return None
    intersection=None
    for bid in seed_box_ids:
        box_ids=hierarchy_boxes(con,bid); qs=','.join('?'*len(box_ids))
        rows=con.execute(f'SELECT DISTINCT card_id FROM card_box WHERE box_id IN ({qs}) AND status != ?',[*box_ids,'Needs Review']).fetchall()
        ids={x[0] for x in rows}
        intersection=ids if intersection is None else intersection & ids
    return intersection if intersection is not None else set()


def cards_for_any_boxes(con, box_ids):
    if not box_ids: return set()
    expanded=[]
    for bid in box_ids: expanded.extend(hierarchy_boxes(con,bid))
    expanded=list(dict.fromkeys(expanded)); qs=','.join('?'*len(expanded))
    return {x[0] for x in con.execute(f'SELECT DISTINCT card_id FROM card_box WHERE box_id IN ({qs}) AND status != ?',[*expanded,'Needs Review']).fetchall()}


def search_field(con, expr, products, limit):
    params=[]; where=[]
    if products: where.append('i.product IN ('+','.join('?'*len(products))+')'); params.extend(products)
    if expr:
        sql='SELECT i.id,bm25(field_fts) AS rank FROM field_fts JOIN field_items i ON i.id=field_fts.id WHERE field_fts MATCH ?'; p=[expr]
        if where: sql+=' AND '+' AND '.join(where); p+=params
        sql+=' ORDER BY rank LIMIT ?'; p.append(limit); return con.execute(sql,p).fetchall()
    sql='SELECT i.id,0.0 FROM field_items i'
    if where: sql+=' WHERE '+' AND '.join(where)
    sql+=' LIMIT ?'; params.append(limit); return con.execute(sql,params).fetchall()


def search_card(con, expr, scopes, limit, eligible_ids=None, exclude_concepts=False, card_types=None):
    where=["COALESCE(i.status,'Active')='Active'"]; params=[]
    if scopes:
        qs=','.join('?'*len(scopes))
        where.append(f'(i.is_shared=1 OR EXISTS (SELECT 1 FROM card_scopes cs WHERE cs.card_id=i.id AND cs.scope IN ({qs})))'); params.extend(scopes)
    if eligible_ids is not None:
        if not eligible_ids: return []
        ids=list(eligible_ids); where.append('i.id IN ('+','.join('?'*len(ids))+')'); params.extend(ids)
    if exclude_concepts: where.append('i.is_concept=0')
    if card_types:
        where.append('i.card_type IN ('+','.join('?'*len(card_types))+')'); params.extend(card_types)
    if expr:
        sql='SELECT i.id,bm25(card_fts) AS rank FROM card_fts JOIN card_items i ON i.id=card_fts.id WHERE card_fts MATCH ?'; p=[expr]
        if where: sql+=' AND '+' AND '.join(where); p+=params
        sql+=' ORDER BY rank LIMIT ?'; p.append(limit); return con.execute(sql,p).fetchall()
    sql='SELECT i.id,0.0 FROM card_items i'
    if where: sql+=' WHERE '+' AND '.join(where)
    sql+=' LIMIT ?'; params.append(limit); return con.execute(sql,params).fetchall()


def search_evidence(con, expr, scopes, limit, eligible_card_ids=None, languages=None):
    where=["COALESCE(e.status,'Active')='Active'",
           "(NOT EXISTS (SELECT 1 FROM evidence_card ec0 WHERE ec0.evidence_id=e.id) "
           "OR EXISTS (SELECT 1 FROM evidence_card ec1 JOIN card_items ci1 ON ci1.id=ec1.card_id "
           "WHERE ec1.evidence_id=e.id AND COALESCE(ci1.status,'Active')='Active'))"]
    params=[]
    if languages:
        # Match the language family too, so 'vi' also accepts 'vi-VN'.
        clauses=[]
        for lang in languages:
            clauses.append('LOWER(e.source_language)=LOWER(?)')
            params.append(lang)
            clauses.append('LOWER(e.source_language) LIKE LOWER(?)')
            params.append(lang.split('-')[0]+'-%')
        where.append('('+' OR '.join(clauses)+')')
    if scopes:
        qs=','.join('?'*len(scopes))
        where.append('(EXISTS (SELECT 1 FROM evidence_card ec JOIN card_items ci ON ci.id=ec.card_id WHERE ec.evidence_id=e.id AND COALESCE(ci.status,\'Active\')=\'Active\' AND (ci.is_shared=1 OR EXISTS (SELECT 1 FROM card_scopes cs WHERE cs.card_id=ci.id AND cs.scope IN ('+qs+')))))')
        params.extend(scopes)
    if eligible_card_ids is not None:
        if not eligible_card_ids: return []
        ids=list(eligible_card_ids); qs=','.join('?'*len(ids))
        where.append('EXISTS (SELECT 1 FROM evidence_card ec2 WHERE ec2.evidence_id=e.id AND ec2.card_id IN ('+qs+'))')
        params.extend(ids)
    if expr:
        sql='SELECT e.id,bm25(evidence_fts) AS rank FROM evidence_fts JOIN evidence_items e ON e.id=evidence_fts.id WHERE evidence_fts MATCH ?'
        p=[expr]
        if where: sql+=' AND '+' AND '.join(where); p+=params
        sql+=' ORDER BY rank LIMIT ?'; p.append(limit)
        return con.execute(sql,p).fetchall()
    sql='SELECT e.id,0.0 FROM evidence_items e'
    if where: sql+=' WHERE '+' AND '.join(where)
    sql+=' LIMIT ?'; params.append(limit)
    return con.execute(sql,params).fetchall()


def evidence_for_cards(con, card_ids, limit):
    if not card_ids: return []
    qs=','.join('?'*len(card_ids))
    rows=con.execute('SELECT DISTINCT e.id,e.payload FROM evidence_items e JOIN evidence_card ec ON ec.evidence_id=e.id WHERE COALESCE(e.status,\'Active\')=\'Active\' AND ec.card_id IN ('+qs+') LIMIT ?',[*card_ids,limit]).fetchall()
    return [{'id':eid,'record':json.loads(payload)} for eid,payload in rows]


def evidence_of_cards_ranked(con, card_ids, limit, languages=None):
    """Evidence of already-retrieved Cards, in the Cards' own rank order.

    Used when the source-native value shares no token with the question (a
    Chinese field name against an English `textbox` value). Returning the
    best-ranked Card's Evidence first is what makes this answerable.
    """
    out, seen = [], set()
    for cid in card_ids:
        sql = ('SELECT e.id FROM evidence_items e JOIN evidence_card ec ON ec.evidence_id=e.id '
               "WHERE ec.card_id=? AND COALESCE(e.status,'Active')='Active'")
        params = [cid]
        if languages:
            clauses = []
            for lang in languages:
                clauses.append('LOWER(e.source_language)=LOWER(?)'); params.append(lang)
                clauses.append('LOWER(e.source_language) LIKE LOWER(?)'); params.append(lang.split('-')[0] + '-%')
            sql += ' AND (' + ' OR '.join(clauses) + ')'
        sql += ' ORDER BY e.id'
        for (eid,) in con.execute(sql, params).fetchall():
            if eid in seen:
                continue
            seen.add(eid); out.append((eid, 0.0))
            if len(out) >= limit:
                return out
    return out


def infer_box_relations(query):
    low=normalize_text(query)
    rel=TERMS['box_relations']
    for name in ('uses_function','depends_on','precedes','shared_with'):
        if any_term(rel.get(name), low): return [name]
    if any_term(rel.get('related_to'), low):
        return ['related_to','uses_function','depends_on','shared_with']
    return NON_HIER_BOX_RELATIONS


def expand_box_links(con, seed_box_ids, allowed_types, limit):
    if not seed_box_ids or not allowed_types: return []
    seen=set(seed_box_ids); hits=[]; qs=','.join('?'*len(allowed_types))
    for sid in seed_box_ids:
        rows=con.execute(f'''SELECT id,source_id,relation_type,target_id,link_basis,evidence,status,payload
                             FROM box_edges WHERE (source_id=? OR target_id=?) AND relation_type IN ({qs})''',[sid,sid,*allowed_types]).fetchall()
        for eid,s,rel,t,basis,evidence,status,payload in rows:
            tid=t if s==sid else s
            if tid in seen: continue
            b=con.execute('SELECT id,box_type,name,canonical_key,description,status,scope_hints,payload FROM boxes WHERE id=?',(tid,)).fetchone()
            if not b: continue
            try: hints=json.loads(b[6] or '[]')
            except Exception: hints=[]
            seen.add(tid)
            hits.append({'seed_box_id':sid,'expanded_box_id':tid,'box_link_id':eid,'relation_type':rel,'direction':'out' if s==sid else 'in','link_basis':basis,'link_evidence':evidence,'link_status':status,'box':{'box_id':b[0],'box_type':b[1],'name':b[2],'canonical_key':b[3],'description':b[4],'status':b[5],'scope_hints':hints}})
            if len(hits)>=limit: return hits
    return hits


def expand_card_links(con, seed_ids, allowed_types, scopes, limit):
    if not seed_ids or not allowed_types: return []
    seen=set(seed_ids); hits=[]; qs=','.join('?'*len(allowed_types))
    for sid in seed_ids:
        rows=con.execute(f'''SELECT id,source_id,target_id,link_type,link_basis,evidence,payload
                             FROM links WHERE (source_id=? OR target_id=?) AND link_type IN ({qs})''',[sid,sid,*allowed_types]).fetchall()
        for lid,s,t,lt,lb,ev,pay in rows:
            tid=t if s==sid else s
            if tid in seen: continue
            card=con.execute("SELECT payload,is_shared FROM card_items WHERE id=? AND COALESCE(status,'Active')='Active'",(tid,)).fetchone()
            if not card: continue
            if scopes and not card[1]:
                row=con.execute('SELECT 1 FROM card_scopes WHERE card_id=? AND scope IN ('+','.join('?'*len(scopes))+') LIMIT 1',[tid,*scopes]).fetchone()
                if not row: continue
            seen.add(tid); hits.append({'seed_card_id':sid,'expanded_card_id':tid,'link_id':lid,'link_type':lt,'link_basis':lb,'link_evidence':ev,'record':json.loads(card[0])})
            if len(hits)>=limit: return hits
    return hits


def infer_card_types(query,intent,hard_context_boxes):
    low=normalize_text(query)
    if intent=='field_lookup' and hard_context_boxes: return ['Field']
    if intent=='knowledge':
        ct=TERMS['card_types']
        if any_term(ct.get('Exception'), low): return ['Exception']
        if any_term(ct.get('Definition'), low): return ['Definition']
        if any_term(ct.get('Process'), low): return ['Process','Rule']
        if any_term(ct.get('Rule'), low): return ['Rule','Condition','Exception']
    return []


def decide_mode(requested,intent,hard_context_boxes):
    if requested!='auto': return requested
    if intent=='field_lookup': return 'card' if hard_context_boxes else 'field'
    if intent in {'relationship','reference','concept'}: return 'relation'
    return 'card'


def main():
    global TERMS
    s=load_settings()
    ap=argparse.ArgumentParser(description='Fast topology-aware AFC query with scope, Box boundaries, and restricted Card/Box graph expansion.')
    ap.add_argument('--db',required=True,default=None); ap.add_argument('--query',required=True)
    ap.add_argument('--mode',choices=['auto','field','card','relation','compare'],default=s.query('mode'))
    ap.add_argument('--business-context',action='append',default=[]); ap.add_argument('--scope',action='append',default=[]); ap.add_argument('--product'); ap.add_argument('--anchor',action='append',default=[])
    ap.add_argument('--box',action='append',default=[]); ap.add_argument('--box-hop',type=int,choices=[0,1]); ap.add_argument('--box-relations')
    ap.add_argument('--box-expand-k',type=int,default=s.query('box_expand_k'))
    ap.add_argument('--top-k',type=int,default=s.query('top_k')); ap.add_argument('--candidate-k',type=int,default=s.query('candidate_k'))
    ap.add_argument('--link-k',type=int,default=s.query('link_k')); ap.add_argument('--link-types')
    ap.add_argument('--evidence-k',type=int,default=s.query('evidence_k'))
    ap.add_argument('--max-terms',type=int,default=s.query('max_query_terms'))
    ap.add_argument('--query-terms',default=str(s.resolve('query_terms') or (s.home/'config'/'query-terms.yaml')),
                    help='Query classification vocabulary (config/query-terms.yaml)')
    ap.add_argument('-o','--output')
    a=ap.parse_args(); t0=time.perf_counter()
    TERMS=load_query_terms(a.query_terms)
    if not any(TERMS['target_mode'].values()):
        print(f'WARNING: no query terms loaded from {a.query_terms!r}; every question will '
              f'classify as semantic and Literal/Structured Evidence will not be targeted',
              file=sys.stderr)
    con=sqlite3.connect(a.db)
    try:
        schema_row=con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        schema_version=json.loads(schema_row[0]) if schema_row else None
    except sqlite3.Error:
        schema_version=None
    if str(schema_version) != '10':
        con.close()
        raise SystemExit('Query index is outdated or invalid. Rebuild it with `knowledge_base.py index --kb-root ...`.')

    bc=resolve_business_contexts(con,a.query,a.business_context)
    explicit_scopes=list(dict.fromkeys([normalize_text(x) for x in a.scope if normalize_text(x)]))
    if a.product and normalize_text(a.product) not in explicit_scopes: explicit_scopes.append(normalize_text(a.product))
    if explicit_scopes: resolved_scopes=explicit_scopes; scope_source='explicit_scope'
    elif bc['scopes']: resolved_scopes=bc['scopes']; scope_source='business_context_map'
    else:
        resolved_scopes=list(dict.fromkeys([normalize_text(x) for x in a.anchor if normalize_text(x)])); scope_source='anchor_fallback' if resolved_scopes else 'none'

    br=resolve_boxes(con,a.query,a.box)
    seed_boxes=br['boxes']; seed_box_ids=[x['box_id'] for x in seed_boxes]
    redundant_business=[]; hard_boxes=[]
    for b in seed_boxes:
        hints=set(b.get('scope_hints') or [])
        if b['box_type']=='Business' and resolved_scopes and hints.intersection(resolved_scopes): redundant_business.append(b)
        else: hard_boxes.append(b)
    hard_box_ids=[x['box_id'] for x in hard_boxes]
    hard_context_boxes=any(x['box_type'] in {'Scenario','Function','Screen'} for x in hard_boxes)
    eligible=cards_for_box_boundary(con,hard_box_ids) if hard_box_ids else None

    intent=detect_intent(a.query); target_mode=detect_target_mode(a.query); mode=decide_mode(a.mode,intent,hard_context_boxes)
    requested_languages=detect_source_languages(a.query)
    removals=list(dict.fromkeys([*bc['aliases'],*bc['contexts'],*resolved_scopes,*br['aliases'],*(a.anchor or [])]))
    terms=qterms(a.query,removals,limit=a.max_terms); expr=fts_expr(terms)

    auto_box_hop=s.query('max_box_hops') if intent=='box_relationship' else s.query('default_box_hops')
    box_hop=auto_box_hop if a.box_hop is None else a.box_hop
    box_hop=min(box_hop, s.query('max_box_hops'))
    box_relations=[x.strip() for x in a.box_relations.split(',') if x.strip()] if a.box_relations else infer_box_relations(a.query)
    box_expanded=expand_box_links(con,seed_box_ids,box_relations,a.box_expand_k) if box_hop==1 else []
    soft_box_ids=[x['expanded_box_id'] for x in box_expanded]
    soft_eligible=cards_for_any_boxes(con,soft_box_ids) if soft_box_ids else set()
    if eligible is not None and soft_eligible and intent!='box_relationship': soft_eligible=soft_eligible & eligible

    out={
      'query':a.query,'requested_business_contexts':a.business_context,'detected_business_contexts':bc['contexts'],'business_context_matches':bc['matches'],
      'resolved_scopes':resolved_scopes,'scope_source':scope_source,'seed_boxes':seed_boxes,'hard_boundary_boxes':hard_boxes,'redundant_business_boxes':redundant_business,
      'hierarchy_boundary_card_count':None if eligible is None else len(eligible),'box_topology':{'hop_count':box_hop,'relations_used':box_relations if box_hop else [],'expanded':box_expanded},
      'detected_intent':intent,'query_target_mode':target_mode,'target_mode_evidence':target_mode_evidence(a.query),
      'requested_source_languages':requested_languages,
      'requested_mode':a.mode,'selected_mode':mode,'terms':terms,'card_hop_count':0,
      'query_terms_file':a.query_terms,'retrieval_limits':{
          'top_k':a.top_k,'candidate_k':a.candidate_k,'evidence_k':a.evidence_k,
          'link_k':a.link_k,'box_expand_k':a.box_expand_k,'max_query_terms':a.max_terms,
          'max_box_hops':s.query('max_box_hops'),'max_card_hops':s.query('max_card_hops'),
          'source':str(s.path) if s.path else 'afc_card_runtime.config.DEFAULTS'}
    }

    def do_evidence(card_ids=None):
        """Evidence retrieval following afc-query's recovery ladder.

        Each stage is tried only when the previous one produced nothing, and the
        stage actually used is reported. v0.4.1 ran a single text search and
        emitted no recovery diagnostics, so a literal/structured question whose
        wording shares no token with the source string (a Chinese question about
        a Vietnamese message, or a Chinese field name against an English
        `textbox` value) silently returned no Evidence.
        """
        stages = []
        card_ids = card_ids or []

        def run(name, expr_arg, langs, eligible_cards, eligible_box_cards):
            hits = search_evidence(con, expr_arg, resolved_scopes, a.evidence_k,
                                   eligible_card_ids=eligible_cards if eligible_cards is not None else eligible_box_cards,
                                   languages=langs)
            stages.append({'stage': name, 'hits': len(hits)})
            return hits

        def run_cards(name, langs):
            hits = evidence_of_cards_ranked(con, card_ids, a.evidence_k, languages=langs)
            stages.append({'stage': name, 'hits': len(hits)})
            return hits

        hits = []
        literalish = target_mode in {'literal', 'structured_fact', 'mixed'}
        if requested_languages:
            # An explicitly named source language is a stronger constraint than
            # lexical overlap, so every language-filtered stage is exhausted
            # before any unfiltered one. Otherwise a question asking for the
            # Vietnamese message comes back with whichever literal happened to
            # share a word with the question.
            hits = run('text_search_language_filtered', expr, requested_languages, None, eligible)
            if not hits and card_ids:
                hits = run_cards('retrieved_cards_language_filtered', requested_languages)
            if not hits and literalish:
                # Narrowing by language inside the existing Scope/Box boundary;
                # this does not widen Scope.
                hits = run('language_scoped_evidence', None, requested_languages, None, eligible)
        if not hits:
            hits = run('text_search', expr, None, None, eligible)
        if not hits and card_ids and literalish:
            hits = run_cards('retrieved_cards', None)

        direct_ids = [x[0] for x in hits[:a.evidence_k]]
        direct_records = payloads(con, 'evidence_items', direct_ids)
        rank_by = {x[0]: x[1] for x in hits}
        direct = [{'id': eid, 'rank': rank_by.get(eid, 0.0), 'record': direct_records[idx]}
                  for idx, eid in enumerate(direct_ids) if idx < len(direct_records)]
        linked = evidence_for_cards(con, card_ids, a.evidence_k)
        used = next((st['stage'] for st in stages if st['hits']), None)
        return {'direct': direct,
                'linked_to_retrieved_cards': linked,
                'requested_source_languages': requested_languages,
                'recovery_stages_tried': stages,
                'recovery_stage_used': used,
                'language_filter_applied': used in {'text_search_language_filtered',
                                                    'retrieved_cards_language_filtered',
                                                    'language_scoped_evidence'}}

    def do_field():
        hits=search_field(con,expr,resolved_scopes,a.candidate_k); ids=[x[0] for x in hits[:a.top_k]]; records=payloads(con,'field_items',ids)
        return [{'id':i,'rank':hits[idx][1],'record':records[idx]} for idx,i in enumerate(ids) if idx<len(records)]

    def do_card(with_links=False):
        card_types=infer_card_types(a.query,intent,hard_context_boxes)
        hits=search_card(con,expr,resolved_scopes,a.candidate_k,eligible_ids=eligible,exclude_concepts=(intent!='concept'),card_types=card_types or None)
        # If explicit Box boundaries already narrowed the universe and generic question wording produced no FTS hit,
        # fall back to the bounded candidate set rather than widening the boundary.
        if not hits and eligible is not None and len(eligible)<=a.candidate_k:
            hits=search_card(con,None,resolved_scopes,a.candidate_k,eligible_ids=eligible,exclude_concepts=(intent!='concept'),card_types=card_types or None)
        ids=[x[0] for x in hits[:a.top_k]]; records=payloads(con,'card_items',ids)
        direct=[{'id':i,'rank':hits[idx][1],'record':records[idx]} for idx,i in enumerate(ids) if idx<len(records)]
        box_nav=[]
        if soft_eligible:
            soft_hits=search_card(con,expr,resolved_scopes,min(a.box_expand_k,a.candidate_k),eligible_ids=soft_eligible,exclude_concepts=(intent!='concept'),card_types=card_types or None)
            if not soft_hits and len(soft_eligible)<=a.box_expand_k:
                soft_hits=search_card(con,None,resolved_scopes,min(a.box_expand_k,a.candidate_k),eligible_ids=soft_eligible,exclude_concepts=(intent!='concept'),card_types=card_types or None)
            direct_ids=set(ids)
            soft_ids=[x[0] for x in soft_hits if x[0] not in direct_ids][:a.box_expand_k]
            soft_records=payloads(con,'card_items',soft_ids)
            rank_by={x[0]:x[1] for x in soft_hits}
            box_nav=[{'id':cid,'rank':rank_by.get(cid,0.0),'record':soft_records[idx]} for idx,cid in enumerate(soft_ids) if idx<len(soft_records)]
        expanded=[]; types=[]
        if with_links:
            types=[x.strip() for x in a.link_types.split(',') if x.strip()] if a.link_types else LINK_INTENT.get(intent,['controls','applies_to','depends_on'])
            expanded=expand_card_links(con,ids,types,resolved_scopes,a.link_k)
        return direct,box_nav,expanded,types,card_types

    if mode=='field':
        out['field']=do_field()
        if target_mode in {'literal','structured_fact','mixed'}: out['evidence']=do_evidence([])
        if hard_box_ids: out['warning']='Field index cannot enforce non-Business Box membership; use auto/card for context-specific Field queries.'
    elif mode=='card':
        d,bx,e,types,ct=do_card(False); out['card']={'direct':d,'box_navigation':bx,'expanded':e}; out['card_type_filter']=ct; out['link_types_used']=types
        out['evidence']=do_evidence([x['id'] for x in d])
    elif mode=='relation':
        d,bx,e,types,ct=do_card(True); out['card']={'direct':d,'box_navigation':bx,'expanded':e}; out['card_type_filter']=ct; out['link_types_used']=types; out['card_hop_count']=1
        out['evidence']=do_evidence([x['id'] for x in d])
    elif mode=='compare':
        out['field']=do_field(); d,bx,e,types,ct=do_card(intent in {'relationship','reference','concept'}); out['card']={'direct':d,'box_navigation':bx,'expanded':e}; out['card_type_filter']=ct; out['link_types_used']=types; out['card_hop_count']=1 if e else 0
        out['evidence']=do_evidence([x['id'] for x in d])

    out['elapsed_ms']=round((time.perf_counter()-t0)*1000,2); con.close(); text=json.dumps(out,ensure_ascii=False,indent=2)
    if a.output:
        p=Path(a.output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text,encoding='utf-8'); print(str(p))
    else: print(text)

if __name__=='__main__': main()
