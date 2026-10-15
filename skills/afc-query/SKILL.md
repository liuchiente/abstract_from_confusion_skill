---
name: afc-query
description: AFC Query Planner with canonical intent, Scope/Box resolution, Card-first retrieval, source-preserving Evidence retrieval, language-aware literal answers, sufficiency checks and bounded recovery/graph expansion.
---

# AFC Query — Evidence-seeking Query Planner

Run commands with the `afc` launcher from the repo root.

Read `config/settings.yaml` (retrieval limits), the configured Business Context
map and question vocabulary, then the current Cards, Evidence Records, Boxes,
Memberships, Box Links and Card Links. When querying an imported Knowledge Base,
prefer `AFC_KB_ROOT/config/business-contexts.yaml` and
`AFC_KB_ROOT/config/query-terms.yaml` when present; they travel with its release
pack and preserve the publisher's query vocabulary.

For a v0.8 workspace query, use `workspace.py query --kb-id <id> --query ...`
so the catalog selects the correct Knowledge Base. Ask which KB ID when the
user names a field mapped to more than one KB. Search multiple IDs only when
explicitly requested, and report each KB's results separately before synthesis.
The current accepted release is selected internally; do not ask for a Release ID.
Never answer from an unreviewed run candidate. The Knowledge Base's SQLite/FTS
index is derived from canonical release JSONL and can be rebuilt with
`knowledge_base.py index`.

## Core principle

AFC Query is not raw Top-K search:

`Question -> Canonical Query -> Scope/Box Resolution -> Seed Retrieval -> Evidence Sufficiency -> bounded recovery -> Answer`

Card and Evidence Record have different jobs. A Card is normalized semantic
knowledge; an Evidence Record is the source-preserving original fact. The query
must pick the right layer rather than treating them as interchangeable.

## 1. Normalize the question

Produce Canonical Topic, Target Property, Query Intent, Business Context,
Explicit Scope, Scenario/Function/Screen, aliases/synonyms, and the possible
interpretations when the question is ambiguous. Equivalent human questions should
converge on the same canonical target rather than on the same literal wording.

## 2. Target mode

| Mode | Answer layer | Examples |
| --- | --- | --- |
| Semantic | normalized Card claims | 這個規則是什麼？哪些條件不能加買？流程怎麼走？ |
| Literal | source-preserving Evidence | 原文是什麼？越文錯誤訊息是什麼？系統實際顯示的提示文字？ |
| Structured Fact | structured Evidence facts | 原始元件類型？Return Code？Max Length？Option Values？ |
| Mixed | both | meaning plus the source-native detail |

Literal answers use source text verbatim: no regeneration, translation,
polishing or normalization of the requested string.

Classification vocabulary lives in the active `query-terms.yaml`, which also holds
`language_hints`. A question naming a language (「越文錯誤訊息」, "Vietnamese
message") makes Evidence retrieval prefer records whose `Source Language`
matches — an explicitly requested language is a stronger constraint than lexical
overlap, so it is exhausted before any fallback. Add your languages to that file;
a question in a language the file does not cover will classify as Semantic and
never reach the Evidence layer.

## 3. Business Context and Scope

Priority: explicit user Scope, then the Business Context map, then
source-supported inferred Scope, then unresolved. Never broaden an explicit
narrow Scope just because a Business Context maps to several products, and never
rewrite a Card's Scope.

Resolve a named Semantic Domain Key or alias against the selected KB's accepted
`knowledge_domains.jsonl`. KB ID is the knowledge-base boundary; Domain Keys
classify subtopics within it and help seed retrieval. They never override product
Scope or an explicit Box.

## Ambiguity that needs user confirmation

Do not guess when two or more interpretations are plausible and choosing between
them could materially change the factual answer. Ask the user to choose, giving
the short list of likely KB IDs, Scopes, Boxes, or Semantic Domain Keys and why
each changes the result. Continue without asking when the selected KB and target
are clear, or when the ambiguity does not affect the answer. Never search every
KB as a substitute for resolving an unclear boundary.

## 4. Box resolution

Resolve explicitly named Scenario/Function/Screen/Business Boxes before selecting
Cards. An explicitly requested Box Membership is a hard validity boundary;
Box-to-Box topology is soft navigation that must not widen Scope. Retrieval does
not require root-to-leaf traversal: a parent-Box query admits hierarchical
descendants through the closure, and the non-hierarchical relations are expanded
at most one hop when intent calls for it.

## 5. Query plan

Canonical Topic; Target Property; Intent; Target Mode; Active/Candidate Scope;
Seed Boxes; target Card Types; target Evidence Kinds and source-fact fields;
allowed retrieval channels; allowed Box/Card relations; initial hop count 0.

## 6. Seed retrieval

```bash
./afc query_fast.py --db work/query-index/afc-query.db \
  --query 'CA 確認頁 Back 的行為是什麼？' --mode auto -o work/query-runs/last.json
```

Channels: exact/keyword, Scope/Box/Card Type metadata, concept/alias match, Field
lookup for plain field questions, Evidence search for literal and structured
targets. Card retrieval is primary for semantic knowledge; Evidence retrieval is
mandatory for literal and source-native facts. No Card Graph expansion yet.

Chinese retrieval depends on overlapping n-grams generated on both the index and
the query side; `tokenize()` is versioned and `ensure_query_index.py` rebuilds an
index built by an older tokenizer. Never hand-edit the index.

## 7. Core evidence selection

Select the smallest evidence set that establishes the requested target. For a
literal message question, a Card saying 「加買失敗」 is not sufficient — the actual
message Evidence Record is required. For a structured fact question, a normalized
Card statement does not substitute for the original source value.

## 8. Evidence sufficiency

Return `Sufficient`, `Partially Sufficient`, `Insufficient` or
`Needs Exploration`, judged against the Target Property rather than topical
relevance:

- target = Error Message, only a condition Card → insufficient
- target = Original Component Type, only a semantic Field Card → insufficient
- target = rule meaning, Card plus supporting Evidence → sufficient

## 9. Bounded recovery

When evidence is insufficient, recover in order and report the stage used
(`query_fast.py` emits `recovery_stages_tried` and `recovery_stage_used`):

1. **Canonical/synonym retry** — normalized concept and known aliases.
2. **Language-filtered Evidence** — when a source language was named.
3. **Boundary-preserving broader retrieval** — relax wording and ranking while
   Scope and Box stay fixed.
4. **Evidence of retrieved Cards** — the source-native value may share no token
   with the question (a Chinese field name against an English `textbox` value),
   so inspect the Evidence of the Cards already retrieved, in their rank order.
5. **Context fallback** — when the fact exists in the source but has no Evidence
   or Card representation, use source context as a traceable fallback and emit a
   Knowledge Gap Candidate.
6. **Restricted Box/Card 1-hop** — only if the target still lacks evidence; one
   hop maximum.

Re-run sufficiency after each stage. Recovery never widens Scope.

## 10. Knowledge gaps

When AFC can answer only by falling back to source context, emit: Gap Type,
Target Property, Source/Context ID, Evidence Exists, Queryable Card Exists,
Queryable Evidence Record Exists, Suggested Loop Route.

Gap Types: `Missing Card Representation`, `Missing Evidence Record`,
`Dropped Structured Source Fact`, `Missing Literal Message`,
`Alias / Canonicalization Gap`.

Query reports gaps; it never mutates the knowledge base. Fixing a gap is a Step 0
or Step 1 loop, recorded through `record_decision.py`.

## 11. Conflict and ambiguity

Before calling two values a conflict, check Scope, Scenario, Box, version, UI vs
API vs DB, business rule vs technical constraint, and historical vs current
source. In a persistent v0.6 query, use the accepted Knowledge Base history for
historical values; `work/knowledge-change-log.jsonl` is run-local. A superseded
value is a lifecycle fact, not a conflict. If unresolved, return
`Needs Exploration` and preserve all evidence.

## 12. Fact vs recommendation

Return facts and evidence first. If the question also asks how the system should
change, separate Knowledge Fact (AFC Query) from Design/Implementation
Recommendation (SA Toolkit).

## 13. Traceability

Every material factual answer traces to a Card and/or an Evidence Record. For
literal and structured answers return Evidence ID, the original value, Source
Language, Source, Source Location and linked Card IDs. A Concept Card alone is
not source proof.

## 14. Query index

```bash
./afc ensure_query_index.py \
  --field-xlsx output/insurance_field_knowledge.xlsx \
  --cards output/knowledge_card_master.jsonl \
  --evidence output/knowledge_evidence.jsonl \
  --links output/knowledge_links.jsonl \
  --context-map config/business-contexts.yaml \
  --boxes output/knowledge_boxes.jsonl \
  --box-memberships output/knowledge_box_memberships.jsonl \
  --box-links output/knowledge_box_links.jsonl \
  --db work/query-index/afc-query.db
```

Indexed separately: Fields, Cards, Evidence Records, Card-Evidence edges, Card
Links, the Business Context map, Boxes and aliases, Box Memberships, Box Links.
Rebuilds happen when a source hash, the index schema, or the tokenizer version
changes; the result reports `rebuild_reasons`.

Retrieval limits come from `settings.yaml` (`query.*`) and are echoed in each
run's `retrieval_limits` with their source — do not restate them from memory.

Diagnostic Box resolution:

```bash
./afc resolve_boxes.py --db work/query-index/afc-query.db --query 'CA 確認頁 Back 的行為是什麼？'
```

## 15. Runtime diagnostics

Record: Original Query, Canonical Topic, Target Property, Query Target Mode,
Requested Source Languages, Intent, Resolved Scopes and their source, Seed Boxes
and their source, Seed Candidate Count, Core Card IDs, Core Evidence IDs,
Evidence Sufficiency, recovery stages tried and used, Expanded Evidence Count,
Box/Card hop count, Product Leakage Count, Knowledge Gap Candidates,
`elapsed_ms`. `Product Leakage Count` must stay 0.

## 16. Stability objective

Equivalent questions should converge on the same canonical target, Scope, major
Box boundary, core Card/Evidence set and factual conclusion. Candidate counts and
wording may vary; a supported factual conclusion must not change because the user
paraphrased.

## Retrieval defaults

- general knowledge → Card 0-hop
- plain Field lookup → Field index
- context-specific Field lookup → Box-filtered Card Type = Field
- Box relationship question → Box topology ≤ 1 hop
- Card relationship question → Card Link ≤ 1 hop
- Scope is always authoritative over Box topology
