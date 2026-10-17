#!/usr/bin/env python3
from pathlib import Path
import argparse, json, re, sys
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, write_jsonl, normalize_text
from afc_card_runtime.config import load_settings
from afc_card_runtime.scope import (
    load_business_context_map, resolve_business_context_map,
    resolve_membership_scopes, source_memberships,
)

# Knowledge signals are recall aids, not business truth. They help Step 0 avoid
# dropping source-native messages / labels / component metadata before Cards exist.
#
# The patterns live in config/knowledge-signals.yaml, split into terms that may
# only identify a HEADER and narrow, value-shaped terms that may select a
# CONTENT row. v0.4.1 matched generic words such as `error`, `code`, `length`
# and `失敗` against row content, which contradicted afc-context's own guardrail
# and made `signal_unselected` non-zero on essentially every run.
SIGNAL_PATTERNS = {'header': {'literal': {}, 'structured': {}},
                   'content': {'literal': {}, 'structured': {}},
                   'semantic': {}}
_settings = None


def load_signal_patterns(path):
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {} if path and Path(path).exists() else {}
    out = {'header': {'literal': {}, 'structured': {}},
           'content': {'literal': {}, 'structured': {}}, 'semantic': {}}
    for scope, key in (('header', 'header_terms'), ('content', 'content_terms')):
        for group in ('literal', 'structured'):
            for kind, pats in ((data.get(key) or {}).get(group) or {}).items():
                out[scope][group][kind] = [re.compile(p, re.I) for p in pats or []]
    for kind, pats in (data.get('semantic_terms') or {}).items():
        out['semantic'][kind] = [re.compile(p, re.I) for p in pats or []]
    return out


def match_anchor(text, anchors):
    t=normalize_text(text or '')
    hits=[]
    for a in anchors:
        a=(a or '').strip()
        if not a: continue
        if re.fullmatch(r'[A-Za-z0-9_.-]+', a):
            if re.search(r'(?<![A-Za-z0-9_])'+re.escape(a)+r'(?![A-Za-z0-9_])', t, flags=re.I):
                hits.append(a)
        elif a.casefold() in t.casefold():
            hits.append(a)
    return hits


def anchor_hits(r, anchors):
    fields=['value','sheet','paragraph_style']
    found=[]; hit_fields=[]
    for f in fields:
        vals=match_anchor(str(r.get(f,'') or ''),anchors)
        if vals:
            found.extend(vals); hit_fields.append(f)
    return list(dict.fromkeys(found)), hit_fields


def _pattern_hits(text, pattern_map):
    t=normalize_text(text or '')
    hits=[]
    for kind, pats in pattern_map.items():
        if any(p.search(t) for p in pats): hits.append(kind)
    return hits


SENTENCE_PUNCT = '。！？；!?;'
MAX_HEADER_CELL_LEN = 24


def row_cells(record):
    cells = record.get('cells')
    if isinstance(cells, list) and cells:
        out = []
        for c in cells:
            out.append(normalize_text(c.get('value') if isinstance(c, dict) else c))
        return [x for x in out if x]
    value = normalize_text(record.get('value'))
    return [x.strip() for x in value.split('|') if x.strip()] if value else []


def looks_like_header(record):
    """Whether a row is shaped like a column-header row rather than prose.

    Without this, the "first three rows of a region may be headers" heuristic
    promotes any sentence that happens to mention `error`/`label`/`code` into a
    header, and its signals then propagate to the whole region -- the same
    false-positive engine this release removes from content matching.
    """
    if record.get('kind') not in ('sheet-row', 'table-row'):
        return False
    cells = row_cells(record)
    if len(cells) < 2:
        return False
    for cell in cells:
        if len(cell) > MAX_HEADER_CELL_LEN:
            return False
        if any(ch in cell for ch in SENTENCE_PUNCT):
            return False
    return True


def header_signals(record):
    """Signals a unit carries *as a header* for the rows it governs."""
    if not looks_like_header(record):
        return [], []
    text=str(record.get('value','') or '')
    types=[]; kinds=[]
    for label,group in (('Literal Knowledge','literal'),('Structured Fact','structured')):
        h=_pattern_hits(text, SIGNAL_PATTERNS['header'][group])
        if h:
            types.append(label); kinds.extend(h)
    return list(dict.fromkeys(types)), list(dict.fromkeys(kinds))


def direct_knowledge_signals(record):
    """Signals a unit carries in its own content.

    Only narrow, value-shaped literal/structured patterns apply here; generic
    header vocabulary is deliberately excluded so a sentence mentioning
    "error" does not become a literal-evidence candidate on its own.
    """
    text=str(record.get('value','') or '')
    types=[]; kinds=[]
    for label,group in (('Literal Knowledge','literal'),('Structured Fact','structured')):
        h=_pattern_hits(text, SIGNAL_PATTERNS['content'][group])
        if h:
            types.append(label); kinds.extend(h)
    h=_pattern_hits(text, SIGNAL_PATTERNS['semantic'])
    if h:
        types.append('Semantic Knowledge'); kinds.extend(h)
    # Headings are structural knowledge even when they do not contain business claims.
    if record.get('heading_level'):
        types.append('Structural Context'); kinds.append('Heading')
    # Images inside an active structural boundary are potential literal/source evidence.
    # Do not infer their text here; visual extraction must preserve the original image text.
    if record.get('kind')=='image':
        types.append('Structural Context'); kinds.append('Image Evidence')
        if record.get('image_text_status') in ('PENDING_VISUAL_EXTRACTION','ALT_TEXT_ONLY'):
            types.append('Literal Knowledge'); kinds.append('Potential Image Text')
    if record.get('kind')=='text-box':
        types.append('Structural Context'); kinds.append('Text Box')
    return list(dict.fromkeys(types)), list(dict.fromkeys(kinds))


def build_header_signal_map(records):
    """Infer table/segment signal types from source-native headers.

    This is deliberately conservative: it only propagates that a row is a
    candidate for preservation. It does not infer the business meaning/value.
    """
    header_map={}
    # Word tables: first 3 rows may contain headers.
    by_table={}
    for i,r in enumerate(records):
        if r.get('kind')=='table-row': by_table.setdefault(r.get('table'),[]).append((i,r))
    for table, items in by_table.items():
        for i,r in items[:3]:
            t,k=header_signals(r)
            if 'Literal Knowledge' in t or 'Structured Fact' in t:
                header_map.setdefault(('word-table',table), {'types':[], 'kinds':[], 'header_index':i})
                header_map[('word-table',table)]['types'] += [x for x in t if x in ('Literal Knowledge','Structured Fact')]
                header_map[('word-table',table)]['kinds'] += k
                header_map[('word-table',table)]['header_index']=max(header_map[('word-table',table)].get('header_index',i), i)
    # Excel: each contiguous region's first 3 rows may contain headers.
    if any(r.get('kind')=='sheet-row' for r in records):
        _,segments=contiguous_excel_segments(records)
        groups={}
        for i,seg in segments.items(): groups.setdefault((seg[0],seg[1]),[]).append(i)
        for key, idxs in groups.items():
            idxs=sorted(idxs,key=lambda j:int(records[j].get('row') or 0))
            for i in idxs[:3]:
                t,k=header_signals(records[i])
                if 'Literal Knowledge' in t or 'Structured Fact' in t:
                    header_map.setdefault(('excel-segment',key), {'types':[], 'kinds':[], 'header_index':i})
                    header_map[('excel-segment',key)]['types'] += [x for x in t if x in ('Literal Knowledge','Structured Fact')]
                    header_map[('excel-segment',key)]['kinds'] += k
                    header_map[('excel-segment',key)]['header_index']=max(header_map[('excel-segment',key)].get('header_index',i), i)
    for v in header_map.values():
        v['types']=list(dict.fromkeys(v['types'])); v['kinds']=list(dict.fromkeys(v['kinds']))
    return header_map


def annotate_knowledge_signals(records):
    header_map=build_header_signal_map(records)
    _,segments=contiguous_excel_segments(records) if any(r.get('kind')=='sheet-row' for r in records) else ({},{})
    out=[]
    for i,r in enumerate(records):
        types,kinds=direct_knowledge_signals(r); basis=[]
        if types: basis.append('Direct Content')
        inherited=None
        if r.get('kind')=='table-row': inherited=header_map.get(('word-table',r.get('table')))
        elif r.get('kind')=='sheet-row' and i in segments:
            seg=segments[i]; inherited=header_map.get(('excel-segment',(seg[0],seg[1])))
        if inherited and i >= inherited.get('header_index', i):
            for x in inherited['types']:
                if x not in types: types.append(x)
            for x in inherited['kinds']:
                if x not in kinds: kinds.append(x)
            basis.append('Header Inherited')
        structural_only = types and all(x=='Structural Context' for x in types)
        out.append({
            'knowledge_signal_types': types,
            'knowledge_signal_kinds': kinds,
            'knowledge_signal_basis': basis,
            'knowledge_relevance_candidate': bool(types),
            # Structural-only signals (a heading, a text box) are not themselves
            # claims to preserve; they are context for their children.
            'knowledge_signal_is_structural_only': bool(structural_only),
        })
    return out


def add_reason(state, idx, reason, hits=None, direct=False):
    s=state[idx]
    s['selected']=True
    if reason not in s['context_basis']: s['context_basis'].append(reason)
    if hits:
        for h in hits:
            if h not in s['anchor_hits']: s['anchor_hits'].append(h)
    if direct: s['context_match']='Direct'
    elif s['context_match']!='Direct': s['context_match']='Inherited'


def mark_word(records, state, anchors, window):
    doc_hits=[]
    if records:
        for f in ('source_file','source_path'):
            doc_hits.extend(match_anchor(str(records[0].get(f,'') or ''),anchors))
    doc_hits=list(dict.fromkeys(doc_hits))
    if doc_hits:
        for j in range(len(records)): add_reason(state,j,'Inherited:Document',doc_hits)
        add_reason(state,0,'Direct:DocumentAnchor',doc_hits,direct=True)
    headings=[]
    for i,r in enumerate(records):
        if r.get('kind')=='paragraph' and r.get('heading_level'):
            headings.append((i,int(r['heading_level'])))
    for i,r in enumerate(records):
        hits,fields=anchor_hits(r,anchors)
        if not hits: continue
        if r.get('kind')=='paragraph' and r.get('heading_level'):
            level=int(r['heading_level']); end=len(records)
            for j,lvl in headings:
                if j>i and lvl<=level:
                    end=j; break
            for j in range(i,end): add_reason(state,j,'Inherited:HeadingSection',hits)
            add_reason(state,i,'Direct:Heading',hits,direct=True)
            continue
        if r.get('kind')=='table-row':
            table=r.get('table')
            for j,x in enumerate(records):
                if x.get('kind')=='table-row' and x.get('table')==table:
                    add_reason(state,j,'Inherited:WordTable',hits)
            add_reason(state,i,'Direct:TableRow',hits,direct=True)
            continue
        preceding=[(j,lvl) for j,lvl in headings if j<i]
        if preceding:
            start,level=preceding[-1]; end=len(records)
            for j,lvl in headings:
                if j>start and lvl<=level:
                    end=j; break
            for j in range(start,end): add_reason(state,j,'Inherited:ContainingSection',hits)
            add_reason(state,i,'Direct:Paragraph',hits,direct=True)
        else:
            block=r.get('block_index')
            for j,x in enumerate(records):
                xb=x.get('block_index')
                if block is not None and xb is not None and abs(int(xb)-int(block))<=window:
                    add_reason(state,j,'Inherited:NeighborBlocks',hits)
            add_reason(state,i,'Direct:Paragraph',hits,direct=True)


def contiguous_excel_segments(records):
    by_sheet={}
    for i,r in enumerate(records): by_sheet.setdefault(r.get('sheet',''),[]).append((i,r))
    segments={}
    for sheet,items in by_sheet.items():
        items=sorted(items,key=lambda t:int(t[1].get('row') or 0))
        seg=[]; prev=None; n=0
        for i,r in items:
            row=int(r.get('row') or 0)
            if prev is None or row-prev<=1:
                seg.append(i)
            else:
                n+=1
                for idx in seg: segments[idx]=(sheet,n,list(seg))
                seg=[i]
            prev=row
        if seg:
            n+=1
            for idx in seg: segments[idx]=(sheet,n,list(seg))
    return by_sheet,segments


def mark_excel(records,state,anchors,window):
    by_sheet,segments=contiguous_excel_segments(records)
    doc_hits=[]
    for r in records:
        for f in ('source_file','source_path'):
            doc_hits.extend(match_anchor(str(r.get(f,'') or ''),anchors))
    doc_hits=list(dict.fromkeys(doc_hits))
    if doc_hits:
        for j in range(len(records)): add_reason(state,j,'Inherited:Workbook',doc_hits)
    for sheet,items in by_sheet.items():
        sheet_hits=match_anchor(sheet,anchors)
        if sheet_hits:
            for j,_ in items: add_reason(state,j,'Inherited:Sheet',sheet_hits)
    for i,r in enumerate(records):
        hits,fields=anchor_hits(r,anchors)
        if not hits: continue
        if 'sheet' in fields:
            add_reason(state,i,'Direct:SheetAnchor',hits,direct=True); continue
        row=int(r.get('row') or 0)
        if row and row<=5:
            for j,_ in by_sheet.get(r.get('sheet',''),[]): add_reason(state,j,'Inherited:SheetHeaderAnchor',hits)
            add_reason(state,i,'Direct:TopRowAnchor',hits,direct=True)
        else:
            seg=segments.get(i)
            if seg:
                for j in seg[2]: add_reason(state,j,'Inherited:ContiguousTableRegion',hits)
            else:
                for j in range(max(0,i-window),min(len(records),i+window+1)): add_reason(state,j,'Inherited:NeighborRows',hits)
            add_reason(state,i,'Direct:Row',hits,direct=True)


def mark_pdf(records,state,anchors,window):
    doc_hits=[]
    for r in records:
        for f in ('source_file','source_path'):
            doc_hits.extend(match_anchor(str(r.get(f,'') or ''),anchors))
    doc_hits=list(dict.fromkeys(doc_hits))
    if doc_hits:
        for j in range(len(records)): add_reason(state,j,'Inherited:PDFDocument',doc_hits)
    for i,r in enumerate(records):
        hits,fields=anchor_hits(r,anchors)
        if not hits: continue
        page=r.get('page')
        for j,x in enumerate(records):
            if x.get('page')==page: add_reason(state,j,'Inherited:PDFPage',hits)
        add_reason(state,i,'Direct:PDFBlock',hits,direct=True)


def propagate_selected_to_structural_descendants(records,state):
    """Keep nested table rows, text boxes, and images inside an already selected source boundary.

    Parser IDs preserve structural ancestry as prefixes, so this propagation does not
    widen business Scope; it only prevents nested source structure from disappearing.
    """
    selected_ids=[str(r.get('source_unit_id') or '') for i,r in enumerate(records) if state[i]['selected']]
    selected_ids=[x for x in selected_ids if x]
    changed=0
    for i,r in enumerate(records):
        if state[i]['selected']: continue
        sid=str(r.get('source_unit_id') or '')
        if not sid: continue
        ancestors=[x for x in selected_ids if sid.startswith(x+'::')]
        if ancestors:
            add_reason(state,i,'Inherited:NestedStructure',[])
            changed+=1
    return changed


def boundary_membership(records,state):
    """Which units sit inside a structural boundary that is already selected.

    Computed once, before recovery, so recovering a unit cannot widen the
    boundary that justified recovering it.
    """
    selected_tables={r.get('table') for i,r in enumerate(records) if state[i]['selected'] and r.get('kind')=='table-row'}
    _,segments=contiguous_excel_segments(records) if any(r.get('kind')=='sheet-row' for r in records) else ({},{})
    selected_segments=set()
    for i,r in enumerate(records):
        if state[i]['selected'] and i in segments:
            seg=segments[i]; selected_segments.add((seg[0],seg[1]))
    selected_pages={r.get('page') for i,r in enumerate(records) if state[i]['selected'] and r.get('kind')=='pdf-block'}
    within=[]
    for i,r in enumerate(records):
        if state[i]['selected']:
            within.append(True); continue
        ok=False
        if r.get('kind')=='table-row' and r.get('table') in selected_tables: ok=True
        elif r.get('kind')=='sheet-row' and i in segments:
            seg=segments[i]; ok=(seg[0],seg[1]) in selected_segments
        elif r.get('kind')=='pdf-block' and r.get('page') in selected_pages: ok=True
        within.append(ok)
    return within


def reporting_division(record):
    """The division a miss is judged within: the nearest container that can
    carry a Scope of its own.

    A structured source divides itself, and those divisions often are the scope
    boundary -- one spec workbook with a sheet per product, one table per
    screen. Prose does not: a section inside a product document is a topic, not
    another product. So a sheet, a table and a page are divisions; a paragraph
    belongs to its document.
    """
    kind = record.get('kind')
    if kind == 'sheet-row':
        return ('sheet', record.get('sheet'))
    if kind == 'table-row':
        return ('table', record.get('table'))
    if kind == 'pdf-block':
        return ('page', record.get('page'))
    return ('file', None)


def scope_boundary_membership(records,state):
    """Whether a miss is worth a human's attention.

    `boundary_membership` answers a stricter question -- may this unit be
    auto-selected -- and knows three structures: a table with a selected row, a
    contiguous Excel segment, a PDF page. A paragraph is none of them, so no
    prose unit was ever "within a boundary", and every signal miss in a Word or
    Markdown source was reported as not-a-finding.

    Reporting needs a weaker test, but not an absent one. A division with at
    least one selected unit has shown by direct evidence that it belongs to the
    active Scope, so a signal-bearing unit left behind in it is a gap in this
    run. A division where nothing was selected is a boundary decision: the
    旅遊險 sheet of a workbook whose CA sheet was selected is out of scope, and
    saying otherwise would make every multi-product workbook a page of
    findings.

    Directory eligibility is not evidence either: a file can sit in a CB
    directory and be entirely about another product.
    """
    selected_divisions = {reporting_division(r)
                          for i, r in enumerate(records) if state[i]['selected']}
    return [(not state[i]['selected']) and reporting_division(r) in selected_divisions
            for i, r in enumerate(records)]


def recover_signal_units_within_selected_boundaries(records,state,signals,within):
    """Select signal-bearing units only inside a structurally selected boundary.

    This prevents generic terms such as 'message' from widening product scope.
    Structural-only signals (a heading, a text box) do not trigger recovery;
    they are context for their children, not claims of their own.
    """
    recovered=0
    for i,r in enumerate(records):
        if state[i]['selected'] or not signals[i]['knowledge_relevance_candidate']:
            continue
        if signals[i].get('knowledge_signal_is_structural_only'):
            continue
        if within[i]:
            add_reason(state,i,'Recovered:KnowledgeSignalWithinSelectedBoundary')
            recovered+=1
    return recovered


def main():
    global _settings
    _settings=load_settings()
    ap=argparse.ArgumentParser(description='Build source-wide context map with scope boundaries plus Semantic/Literal/Structured knowledge-signal recovery.')
    ap.add_argument('inputs', nargs='+', help='Parsed JSONL files from parse_excel/word/pdf')
    ap.add_argument('--anchors', nargs='*', default=[], help='Direct source/product anchors such as CA')
    ap.add_argument('--business-context', action='append', default=[], help='High-level business context such as 車險')
    ap.add_argument('--target-scope', action='append', default=[], help='Explicit Scope target for this scan; overrides directory defaults')
    ap.add_argument('--context-map', help='Business Context mapping in YAML (v0.5-compatible) or mapping-only XML')
    ap.add_argument('--scope-root', action='append', default=[], help='Selected source root; repeat for overlapping roots to preserve each membership')
    ap.add_argument('--exclude-scope', action='append', default=[], help='Additional canonical Scope exclusion for this run')
    ap.add_argument('--override-excluded-scope', action='append', default=[], help='Explicitly override a matching local/global exclusion for this run')
    ap.add_argument('--allow-unscoped', action='store_true', help='Legacy escape hatch; permit files with no target Scope or directory default')
    ap.add_argument('--scope-policy',choices=['product','not-applicable'],default='product',
                    help='Use product Scope boundaries, or declare that product Scope does not apply to this KB.')
    ap.add_argument('--select-all-source-units',action='store_true',
                    help='For an explicitly bounded Scope-neutral source set, send every parsed unit to extraction.')
    ap.add_argument('-o','--output',required=True, help='Annotated source-map JSONL. Includes selected and unselected source units.')
    ap.add_argument('--report',help='Optional JSON coverage report')
    ap.add_argument('--window',type=int,default=_settings.get('context_fallback_block_window',3),
                    help='Last-resort structural block window used only when no stronger boundary exists')
    ap.add_argument('--signals',default=str(_settings.resolve('knowledge_signals') or ''),
                    help='Knowledge-signal pattern file (config/knowledge-signals.yaml)')
    ap.add_argument('--no-knowledge-signal-recovery',action='store_true',help='Annotate signals but do not recover signal-bearing units inside selected structural boundaries')
    a=ap.parse_args()
    if a.select_all_source_units and a.scope_policy!='not-applicable':
        ap.error('--select-all-source-units requires --scope-policy not-applicable')
    global SIGNAL_PATTERNS
    SIGNAL_PATTERNS=load_signal_patterns(a.signals)
    signal_pattern_counts={
        'header_literal':sum(len(v) for v in SIGNAL_PATTERNS['header']['literal'].values()),
        'header_structured':sum(len(v) for v in SIGNAL_PATTERNS['header']['structured'].values()),
        'content_literal':sum(len(v) for v in SIGNAL_PATTERNS['content']['literal'].values()),
        'content_structured':sum(len(v) for v in SIGNAL_PATTERNS['content']['structured'].values()),
        'semantic':sum(len(v) for v in SIGNAL_PATTERNS['semantic'].values()),
    }
    if not any(signal_pattern_counts.values()):
        print(f'WARNING: no knowledge-signal patterns loaded from {a.signals!r}; '
              f'Step 0 signal recall is disabled for this run', file=sys.stderr)
    context_map = a.context_map or str(_settings.resolve('business_context_map') or '')
    requested_business_contexts = list(a.business_context or _settings.get('default_business_contexts', []) or [])
    try:
        resolution=resolve_business_context_map(context_map, requested_business_contexts)
        all_mapping_rows=load_business_context_map(context_map) if context_map else []
    except Exception as exc:
        ap.error(str(exc))
    configured_anchors=list(a.anchors or _settings.get('context_anchors', []) or [])
    anchor_scope_matches=[]
    for row in all_mapping_rows:
        if any(match_anchor(alias, configured_anchors) for alias in row['aliases']):
            anchor_scope_matches.extend(row['scopes'])
    explicit_targets=list(a.target_scope or _settings.get('active_scopes', []) or [])
    mapped_targets=list(resolution['scopes'] or ([] if requested_business_contexts else anchor_scope_matches))
    search_anchors=[]
    for x in [*configured_anchors, *resolution['aliases'], *resolution['scopes'], *explicit_targets]:
        x=normalize_text(x)
        if x and x not in search_anchors: search_anchors.append(x)
    if not context_map and requested_business_contexts:
        ap.error('A Business Context was requested but no mapping was found; pass --context-map or configure business_context_map')

    raw_settings={}
    if _settings.path and _settings.path.exists():
        try: raw_settings=yaml.safe_load(_settings.path.read_text(encoding='utf-8')) or {}
        except Exception: raw_settings={}
    if raw_settings.get('exclude_scope'):
        print('WARNING: legacy exclude_scope is ignored. Replace it with canonical excluded_scopes or directory afc-scope.md values.', file=sys.stderr)
    global_excluded=list(_settings.get('excluded_scopes', []) or []) + list(a.exclude_scope or [])
    override_scopes=list(a.override_excluded_scope or [])
    all_out=[]
    report={
        'anchors':configured_anchors,'target_scopes':explicit_targets or mapped_targets,
        'requested_business_contexts':requested_business_contexts,
        'resolved_business_contexts':resolution['contexts'],'resolved_active_scopes':resolution['scopes'],
        'search_anchors':search_anchors,'files':[],'total_source_units':0,'selected_source_units':0,
        'unselected_source_units':0,'direct_source_units':0,'inherited_source_units':0,
        'knowledge_signal_candidates':0,'literal_signal_candidates':0,'structured_signal_candidates':0,
        'semantic_signal_candidates':0,'signal_candidates_selected':0,'signal_candidates_unselected':0,
        'signal_unselected_within_boundary':0,'signal_unselected_outside_boundary':0,
        'structural_only_signal_units':0,
        'signal_units_recovered':0,'nested_structure_units_propagated':0,
        'scope_boundary':{'scope_roots':a.scope_root,'global_excluded_scopes':global_excluded,
                          'explicit_override_scopes':override_scopes,'scope_overrides':[],
                          'blocked_files':[],'unresolved_files':[]},
        'signal_patterns':signal_pattern_counts,'signal_pattern_file':a.signals or None,
    }
    for source in a.inputs:
        records=read_jsonl(source)
        by_file={}
        for r in records: by_file.setdefault(r.get('source_path') or r.get('source_file') or source,[]).append(r)
        for file_key,recs in by_file.items():
            memberships=source_memberships(file_key, a.scope_root)
            membership_decisions=[]
            for membership in memberships:
                if a.scope_policy=='not-applicable':
                    decision={'target_scopes':[],'allowed_scopes':[],'excluded_scopes':[],
                              'blocked_scopes':[],'override_scopes':[],
                              'target_basis':'Knowledge Base policy: product Scope not applicable',
                              'status':'scope-neutral'}
                else:
                    decision=resolve_membership_scopes(
                        membership['scope_metadata'], requested_scopes=explicit_targets,
                        mapped_scopes=mapped_targets, global_excluded=global_excluded,
                        override_exclusions=override_scopes,
                    )
                membership.update(decision)
                if decision['status']=='needs-scope' and a.allow_unscoped:
                    membership['status']='unscoped-allowed'
                membership_decisions.append(membership)
            eligible_memberships=[m for m in membership_decisions if m['status'] in {'eligible','partially-excluded','unscoped-allowed','scope-neutral'}]
            scope_eligible=bool(eligible_memberships)
            if not scope_eligible:
                if any(m['status']=='needs-scope' for m in membership_decisions):
                    report['scope_boundary']['unresolved_files'].append(str(file_key))
                else:
                    report['scope_boundary']['blocked_files'].append(str(file_key))
            for membership in membership_decisions:
                if membership.get('override_scopes'):
                    report['scope_boundary']['scope_overrides'].append({
                        'source':str(file_key),'membership_root':membership.get('root'),
                        'scope_metadata_path':membership['scope_metadata'].get('path'),
                        'scopes':membership['override_scopes'],
                    })
            allowed_scope_ids={x.casefold() for m in eligible_memberships for x in (m.get('allowed_scopes') or [])}
            known_scope_ids={x.casefold() for row in all_mapping_rows for x in row['scopes']}
            file_anchors=[]
            for anchor in [*configured_anchors, *resolution['aliases']]:
                if anchor.casefold() in known_scope_ids and anchor.casefold() not in allowed_scope_ids:
                    continue
                if anchor not in file_anchors: file_anchors.append(anchor)
            for membership in eligible_memberships:
                for scope in membership.get('allowed_scopes') or []:
                    if scope not in file_anchors: file_anchors.append(scope)
            state=[{'selected':False,'context_match':'Unassigned','context_basis':[],'anchor_hits':[]} for _ in recs]
            kinds={r.get('kind') for r in recs}
            if scope_eligible and 'sheet-row' in kinds: mark_excel(recs,state,file_anchors,a.window)
            elif scope_eligible and {'paragraph','table-row'} & kinds: mark_word(recs,state,file_anchors,a.window)
            elif scope_eligible and 'pdf-block' in kinds: mark_pdf(recs,state,file_anchors,a.window)
            elif scope_eligible:
                direct=[]
                for i,r in enumerate(recs):
                    hits,_=anchor_hits(r,file_anchors)
                    if hits: direct.append((i,hits))
                for i,hits in direct:
                    for j in range(max(0,i-a.window),min(len(recs),i+a.window+1)): add_reason(state,j,'Inherited:FallbackWindow',hits)
                    add_reason(state,i,'Direct:Generic',hits,direct=True)
            else:
                for row in state:
                    row['context_basis'].append('Blocked:ScopeBoundary' if membership_decisions and all(m['status']!='needs-scope' for m in membership_decisions) else 'Unresolved:ScopeBoundary')
            nested_propagated=propagate_selected_to_structural_descendants(recs,state)
            signals=annotate_knowledge_signals(recs)
            if a.scope_policy=='not-applicable' and not file_anchors:
                for i,(row,signal) in enumerate(zip(recs,signals)):
                    seed=(a.select_all_source_units or signal.get('knowledge_relevance_candidate')
                          or row.get('parent_kind') in {'code-module','code-symbol'}
                          or (row.get('kind') == 'image' and row.get('parent_kind') == 'pdf-page'))
                    if seed:
                        state[i]['selected']=True
                        state[i]['context_match']='Direct'
                        state[i]['context_basis'].append(
                            'Selected:ExplicitSourceBoundary' if a.select_all_source_units
                            else ('Selected:CodeSymbol' if row.get('parent_kind') in {'code-module','code-symbol'}
                                  else 'Selected:KnowledgeSignal'))
            within=boundary_membership(recs,state)
            # Reporting uses the weaker, evidence-based boundary; recovery keeps
            # the structural one, so selection is unchanged by this distinction.
            in_scope_boundary=scope_boundary_membership(recs,state)
            recovered=0 if a.no_knowledge_signal_recovery else recover_signal_units_within_selected_boundaries(recs,state,signals,within)
            report['signal_units_recovered']+=recovered
            report['nested_structure_units_propagated']+=nested_propagated
            selected=direct=inherited=0; file_signal=0; file_signal_selected=0
            for i,r in enumerate(recs):
                out=dict(r); out.update(state[i]); out.update(signals[i])
                out['signal_within_selected_boundary']=bool(within[i])
                out['signal_within_scope_boundary']=bool(in_scope_boundary[i])
                out['requested_business_contexts']=requested_business_contexts; out['resolved_active_scopes']=list(dict.fromkeys(scope for m in eligible_memberships for scope in (m.get('allowed_scopes') or [])))
                out['source_memberships']=[{
                    'root':m.get('root'),'relative_path':m.get('relative_path'),
                    'scope_metadata_path':m['scope_metadata'].get('path'),
                    'scope_metadata_sha256':m['scope_metadata'].get('sha256'),
                    'default_scopes':m['scope_metadata'].get('default_scopes',[]),
                    'excluded_scopes':m['scope_metadata'].get('excluded_scopes',[]),
                    'target_scopes':m.get('target_scopes',[]),'allowed_scopes':m.get('allowed_scopes',[]),
                    'blocked_scopes':m.get('blocked_scopes',[]),'override_scopes':m.get('override_scopes',[]),
                    'scope_status':m.get('status'),'target_basis':m.get('target_basis'),
                } for m in membership_decisions]
                out['scope_boundary_eligible']=scope_eligible
                all_out.append(out)
                if signals[i].get('knowledge_signal_is_structural_only'):
                    report['structural_only_signal_units']+=1
                if signals[i]['knowledge_relevance_candidate']:
                    file_signal+=1; report['knowledge_signal_candidates']+=1
                    st=signals[i]['knowledge_signal_types']
                    if 'Literal Knowledge' in st: report['literal_signal_candidates']+=1
                    if 'Structured Fact' in st: report['structured_signal_candidates']+=1
                    if 'Semantic Knowledge' in st: report['semantic_signal_candidates']+=1
                    if state[i]['selected']:
                        file_signal_selected+=1; report['signal_candidates_selected']+=1
                    else:
                        report['signal_candidates_unselected']+=1
                        actionable_miss=(in_scope_boundary[i]
                                         and not signals[i].get('knowledge_signal_is_structural_only'))
                        if actionable_miss:
                            report['signal_unselected_within_boundary']+=1
                        else:
                            report['signal_unselected_outside_boundary']+=1
                if state[i]['selected']:
                    selected+=1
                    if state[i]['context_match']=='Direct': direct+=1
                    else: inherited+=1
            report['files'].append({'source':file_key,'source_units':len(recs),'selected':selected,'unselected':len(recs)-selected,'direct':direct,'inherited':inherited,'knowledge_signal_candidates':file_signal,'signal_candidates_selected':file_signal_selected,'signal_candidates_unselected':file_signal-file_signal_selected,'signal_units_recovered':recovered,'scope_boundary_eligible':scope_eligible,'source_memberships':membership_decisions})
            report['total_source_units']+=len(recs); report['selected_source_units']+=selected; report['unselected_source_units']+=len(recs)-selected; report['direct_source_units']+=direct; report['inherited_source_units']+=inherited
    write_jsonl(a.output,all_out)
    if a.report:
        Path(a.report).parent.mkdir(parents=True,exist_ok=True)
        Path(a.report).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"source_units={report['total_source_units']} selected={report['selected_source_units']} "
          f"unselected={report['unselected_source_units']} signals={report['knowledge_signal_candidates']} "
          f"signal_unselected={report['signal_candidates_unselected']} "
          f"(within_boundary={report['signal_unselected_within_boundary']}, "
          f"outside={report['signal_unselected_outside_boundary']}) "
          f"recovered={report['signal_units_recovered']} output={a.output}")
if __name__=='__main__': main()
