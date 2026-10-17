---
name: afc-validate
description: Read-only quality and regression check across package self-test, source structure, Context, Cards, Evidence, Links, Boxes, Query and knowledge lifecycle. Use for 檢查品質/驗證/回歸測試/能不能升版/health check/is this version safe to adopt. Reports what it finds and never repairs anything: a fix belongs to the step that owns it, and a measured rate to afc-cards.
allowed-tools: Bash, Read, Glob, Grep
---

# AFC Validation — cross-cutting quality gate

Not Step 0-6. A read-only layer over the AFC Knowledge Core. Run with the `afc`
launcher from the repo root.

## Principles

- Never silently repair production knowledge during validation.
- AI output is not automatically Ground Truth.
- Keep findings separate from knowledge data.
- Prefer the package self-test, fixed Gold cases and version-to-version
  regression over a subjective "looks good".

## Layer 0 — package self-test

Start here. The code has to be correct before its reports mean anything.

```bash
./afc selftest.py            # pytest over tests/
./afc check_environment.py
```

The suite covers the defects this release fixed, so a regression in any of them
fails loudly: Chinese n-gram retrieval, FTS operator words, Vietnamese
tokenization, ID stability across rewording, deterministic sampling, rejection of
partial or out-of-sample verdicts, refusal to grade an ungraded rate, parser
discovery independence, unsupported-structure reporting, merged-cell
inheritance, uncached formula cells, Source Unit ID collisions, and the decision
gate's MISSING/STALE/BLOCKED states.

## Layer 1 — schema conformance

```bash
./afc validate_schema.py --all
```

Every canonical artifact that exists is checked against `schemas/`. An artifact
whose kind cannot be resolved fails rather than being skipped; schema
conformance is the gate the hand-written validators sit behind, not a parallel
opinion.

## Layer 2 — source structure coverage

Read `work/step-card-0-source-structure-audit.json`.

Check that nested tables became Source Units, text box and shape text was
surfaced, embedded images became image Source Units with media on disk, merged
Excel headers reached the rows they govern, Excel images and hidden-sheet
decisions were reported, structure paths retain parent table/row/cell ancestry,
and image text pending visual extraction is not counted as complete literal
evidence.

Root-cause routing, in order:

1. `SOURCE_PARSING_GAP` — structure was in the package but produced no Source
   Unit. Blocking.
2. `SOURCE_UNSUPPORTED_STRUCTURE` — content exists that no parser reads. Judge
   whether it carries knowledge the requested queries need.
3. `SOURCE_VISUAL_EXTRACTION_GAP` — image evidence without reliable text.
4. Only once Source Units exist can missing selection be `RETURN_TO_CONTEXT`.
5. Only once selected Source Units exist can missing Evidence be
   `EVIDENCE_REPAIR`.

A missing parser report is itself a gap. Confirm every parser that should have
run produced one; `--expect-parsers` makes that explicit.

## Layer 3 — source fidelity

Validate `Card -> Evidence Record -> Source Unit -> Source Location -> source`.
Flag unsupported facts, changed numbers, invented scope and invented business
rules. Verify source-native names, messages, component types, codes, labels,
option values and literal strings are preserved without silent translation or
normalization.

`work/knowledge-change-log.jsonl` is the strongest signal available here: an
`Evidence Changed` row means a source-preserving value moved between runs.
Either the source changed — which should be visible in Source Version/Date — or
fidelity regressed.

## Layer 4 — coverage

Validate Card/Skip/Review accounting and `unaccounted_source_units = 0`.
Accounting alone does not prove Context recall.

Audit Step 0 signal recall using
`work/step-card-0-context-selection-audit.json`, reading the two numbers
separately: `signal_unselected_within_boundary` is actionable;
`signal_unselected_outside_boundary` is out of scope and not a finding. Then
compare Literal Evidence Coverage and Structured Fact Evidence Coverage from the
health report.

## Layer 5 — Card convergence

Read `work/step-card-1-health.json` and its history. Evaluate Unaccounted Rate,
Saturation Miss Rate, Rerun Novelty Rate, Unsupported Claim Rate, Atomicity
Issue Rate, Unresolved Review Rate, and the convergence trend.

Check the grades, not just the numbers. `INSUFFICIENT_SAMPLE` or
`UNVERIFIED_SAMPLE` means the rate was not graded: the sample was below
`card_health.min_sample_for_rate_grading`, or it did not come from
`sample_units.py` with verdicts covering exactly the drawn items. A run in that
state cannot be `READY`, and reporting its rate as if it were measured is the
error this layer exists to catch.

Then check the decision:

```bash
./afc record_decision.py verify \
  --health work/step-card-1-health.json --decision work/step-card-1-decision.json
```

`MISSING` / `STALE` / `BLOCKED` are findings. Never convert a metric
recommendation into an automatic knowledge mutation.

## Layer 6 — Evidence preservation

Validate Evidence IDs, Card-Evidence edges in both directions, exact literal
preservation, structured source facts, source language, and dangling references.
Confirm IDs came from the configured registry: an ID outside
`work/id-registry.jsonl` (standalone) or `$AFC_KB_ROOT/identity/id-registry.jsonl`
(persistent), or a registry deleted between runs, invalidates every delta and
Gold baseline. A semantic Card can be normalized; an Evidence Record cannot be
rewritten to fit its Card.

## Layer 7 — structural correctness

Validate Context inheritance, Scope boundaries, Card IDs and types, Box
memberships and topology, Link evidence, dangling references, product leakage,
and lifecycle coherence (`Superseded` implies an existing `Superseded By`).

## Layer 8 — retrieval regression

Use a fixed query benchmark and compare precision/relevance, completeness, source
support, context accuracy, noise and product leakage against the accepted
baseline.

```bash
./afc run_query_benchmark.py --db work/query-index/afc-query.db \
  --cases config/query-cases.yaml \
  -o work/query-runs/benchmark.json \
  --baseline work/query-runs/baseline.json
```

The cases in `config/query-cases.yaml` are executed, not merely documented:
`expected_resolution` asserts how the planner read the question and `expect`
asserts what came back. A case that regressed against the accepted baseline
fails the benchmark. Accept a new baseline only deliberately, with
`--update-baseline`.

`query_compare.py` remains available for the separate Field-vs-Card A/B
comparison; it is not the regression gate.

Include at least one case per target mode (Semantic, Literal, Structured Fact,
Mixed), one short CJK query, one query in each source language present in the
corpus, and one case whose answer must come back in a specifically requested
language. Confirm `tokenizer_version` in the index matches the runtime before
trusting any comparison — a stale index under-retrieves silently.

## Layer 9 — lifecycle regression

For known Knowledge Change cases, verify current value, historical value,
traceability, the change/decision record, replacement semantics, and that
unrelated knowledge stayed stable.

```bash
./afc validate_schema.py work/knowledge-change-log.jsonl --kind knowledge-change
```

Each case should be traceable to a change record and, where it was accepted
deliberately, to the decision artifact that accepted it.

For a persistent Knowledge Base, also run the read-only release check:

```bash
./afc knowledge_base.py validate --kb-root path/to/knowledge-base
```

It verifies canonical dataset hashes, schemas, and cross-references. Query
indexes are derived data; rebuild them from a validated accepted release rather
than editing them by hand.

## Gold Dataset

Recommended first baseline: 50 Source Units, 100 Cards, 30 Box Memberships, 30
Card Links, 30 Query cases, 5 Knowledge Change cases.

Human-reviewed Gold cases are authoritative. Model-generated cases need human
acceptance before entering Gold. Pin the Gold baseline to the ID registry that
produced it; without that, a renumbered knowledge base looks like a total
regression.

## Modes

- `quick` — self-test, schema, references, source traceability, coverage,
  leakage, Card health summary including sample gates, decision state
- `standard` — quick plus Gold structural cases, query benchmark, fidelity sample
- `full` — standard plus broad fidelity/coverage, change regression, version
  comparison

## Required reporting

Return one of `AFC VALIDATION PASS`, `AFC VALIDATION PASS WITH REVIEW ITEMS`,
`AFC VALIDATION FAIL`.

State the self-test result, the schema result, and whether the Card stage
recommendation is: proceed to Links, targeted Card loop, full Card rerun, return
to Context, evidence repair, or explore unresolved knowledge — and whether a
current human decision exists for it.

<!-- afc:scope:begin -->
<!-- Generated from config/skill-scopes.yaml by scripts/sync_skill_metadata.py.
     Edit the manifest, not this block: the `afc` launcher enforces the
     manifest, so a hand-edited copy here would only disagree with it. -->

## Scope

This skill may cause **read-only** changes. Set
`AFC_SKILL=afc-validate` while following it: the `afc` launcher then refuses any
command outside the scope below and names the skill that owns it.

Commands this skill may run:

- `audit_source_structure.py`
- `check_environment.py`
- `check_pipeline_artifacts.py`
- `knowledge_base.py` — only `validate, query`
- `query_compare.py`
- `query_fast.py`
- `record_decision.py` — only `verify`
- `run_query_benchmark.py`
- `selftest.py`
- `validate_boxes.py`
- `validate_cards.py`
- `validate_context_selection.py`
- `validate_coverage.py`
- `validate_evidence.py`
- `validate_links.py`
- `validate_schema.py`

Not this skill's job:

- repairing anything it finds → the owning step's skill
- rebuilding an index to make a retrieval comparison pass → `afc-query`
- grading a metric from a sample it drew itself → `afc-cards`

`./afc --scope afc-validate` prints this boundary.
<!-- afc:scope:end -->
