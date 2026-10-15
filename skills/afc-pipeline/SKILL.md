---
name: afc-pipeline
description: Orchestrate the seven AFC Knowledge Core steps end-to-end without redefining them - Context, Cards/Evidence, Links, Boxes, Curate, Publish, Query Readiness. Use when the user wants one instruction to run the full AFC pipeline.
---

# AFC PIPELINE — orchestrate Steps 0 through 6

This skill owns **order, gates and the final report**. It does not restate what
each step does: that lives in the step's own skill, and duplicating it here is
how the two copies drift apart. Follow each step's skill as written.

```text
0. afc-context     1. afc-cards     2. afc-links     3. afc-boxes
4. afc-curate      5. afc-publish   6. afc-query (readiness)
```

`afc-validate` is a cross-cutting quality gate, not an eighth workflow step.
`afc-discuss`, `afc-update`, `afc-domains`, and `afc-share` are Knowledge Base
maintenance workflows, not additional source-processing steps. Use
`afc-discuss` to investigate and record a gap or conflict; use `afc-update` only
after the discussion record is ready for change proposals. Domain Keys classify
subtopics within the selected KB and do not replace its KB ID boundary.

All commands use the `afc` launcher from the repo root, so every relative path
resolves inside the AFC runtime:

```bash
./afc --home
RUN="$(date +%Y%m%dT%H%M%S)"     # one run id for the whole pipeline
```

Use one run id throughout: it ties ID allocation, review samples, the decision
artifact and the change log to the same run.

## Resolve before starting

Prefer values the user gave; otherwise read `config/settings.yaml`. Resolve
source path(s), Business Context(s), explicit Active Scope(s) if any, and an
optional final smoke-test query or query-case file. Do not ask for confirmation
for anything already present in the configuration. With no query supplied, Step 6
reports Query Readiness and does not invent a business question.

For v0.8 workspace runs, first use `afc-workspace` to resolve the KB ID, its
registered source roots, `scope_policy`, persistent KB root, and run ID. Inventory
through `workspace.py inventory` and parse only files listed in that run's
`candidate/eligible-source-paths.json` with `parse_sources.py --kb-id <id>`.
When the requested behavior or extraction method changed but source files did
not, add `--rescan-unchanged`. Pass the same selected roots and scope policy to
`afc-context`, and set `AFC_KB_ROOT` to the selected KB so ID allocation uses its
persistent registry. A partial source scan must not use `--complete-boundary`.

For `scope_policy: product`, resolve Scope from the prompt or directory-local
`afc-scope.md`; unresolved Scope remains a boundary issue. For
`scope_policy: not-applicable`, product Scope is explicitly irrelevant while the
selected source folders remain the hard scan boundary. Pass
`--scope-policy not-applicable` to `build_context_candidates.py`. During a
comprehensive first extraction, `--select-all-source-units` is allowed only for
this explicitly bounded neutral KB; focused updates should use topic anchors.

For v0.7, use the current release's `knowledge_domains.jsonl` as the domain
registry baseline. Copy it into `output/knowledge_domains.jsonl` before staging;
for a first release, create an empty JSONL file. Existing Cards keep their
approved `Semantic Domain Keys`. New domain keys are candidates until
`afc-domains` and the release review approve them.

## Run policy

One uninterrupted run, not seven confirmations. Do not stop between normal steps
to ask approval — but do not hide quality findings either: record Review items,
carry Card Health and Context Health recommendations forward unchanged, preserve
Knowledge Gaps, and never mutate a source fact to make a gate pass.

### Hard stops

- a required input artifact is missing, empty or unparseable
- `SOURCE_PARSING_GAP`: source structure was discovered but never materialized
- a parser that should have run produced no structure report
- invalid or dangling IDs prevent graph construction
- schema validation fails on a canonical artifact
- publish validation fails on a canonical published dataset
- a product KB has no resolvable Scope and would otherwise admit out-of-scope sources

### The Step 1 → Step 2 decision gate

This gate pauses a full run when Card Health is not `READY` and no current human
decision allows continuation. A separate release-review gate applies after
candidate datasets are staged.

```bash
./afc record_decision.py verify \
  --health work/step-card-1-health.json --decision work/step-card-1-decision.json
```

- `OK` — health is `READY`, or a current decision authorises continuing. Proceed.
- `MISSING` — health is not `READY` and nobody has chosen a route. Stop with
  `PIPELINE BLOCKED_PENDING_DECISION`, show the health summary and the
  recommended route, and tell the user the exact `record_decision.py record`
  command to run.
- `STALE` — a decision exists but was made against different health. Stop the
  same way.
- `BLOCKED` — the recorded route loops back into Step 0/1. Report that the loop
  is owed and stop.

When the user has explicitly asked for an unattended run, they can set
`decision.required_when_not_ready: false` in `settings.yaml`. Say so in the
report when that is why the gate did not apply; do not disable it yourself.

### Review conditions — these do not pause the run

Context signal candidates left for Review; `SOURCE_UNSUPPORTED_STRUCTURE`;
`SOURCE_VISUAL_EXTRACTION_GAP`; Card Health `REVIEW_RECOMMENDED` once a decision
authorises continuing; unresolved knowledge preserved as Review; orphan
Cards/Boxes; a Knowledge Gap Candidate from Query. Continue while downstream
artifacts stay structurally valid, and surface every one of them in the report.

`SOURCE_VISUAL_EXTRACTION_GAP` becomes a hard stop only when the missing image
text is required for the requested final query or a critical Gold case.

For images and scanned PDF pages, run local OCR from `afc-context` before model
reasoning. Multimodal reading is disabled by default and may be used only when
the user explicitly authorizes it for that run. Low-confidence OCR stays Review.

Never run an unbounded loop. If `afc-cards` recommends `RETURN_TO_CONTEXT` or
`RERUN_RECOMMENDED`, that is the human's call through the decision gate.

## Per-step gates

Each step's own skill defines its work. Orchestration checks only these:

| Step | Required before continuing |
| --- | --- |
| 0 | structure audit exists, no unexplained `SOURCE_PARSING_GAP`, source map readable, product Scope resolved or neutral policy explicitly selected |
| 1 | IDs allocated from the registry, coverage accounted (`unaccounted = 0`), review metrics present, health written, decision gate `OK` |
| 2 | links validate against the current Card set, no dangling endpoints |
| 3 | Box graph validates, no hierarchy cycle, Card Scope unchanged |
| 4 | master and evidence written, IDs preserved, change log appended |
| 5 | schema `--all` passes, publish validation passes, Cards reference registered active domains, artifacts non-empty |
| 6 | index fresh or rebuilt, tokenizer version current, Cards and Evidence indexed |

Use reconciled Cards (`work/step-card-1-reconciled-cards.jsonl`) downstream when
Step 1 produced them.

## Persistent release review (v0.6+)

Step 5 writes the pipeline's candidate datasets. It does not accept them into
the persistent Knowledge Base. After the pipeline and its QA finish, run
`knowledge_base.py stage` against the same run ID and review every object in
`runs/<run-id>/proposals.jsonl`. Record `accept`, `reject`, or `defer` for every
proposal with a reviewer and rationale. Publish only after those decisions are
recorded. If the user has not made the proposal decisions, stop with
`AWAITING_KNOWLEDGE_REVIEW`; do not publish or infer acceptance from a request to
run the pipeline. After publish, run `knowledge_base.py validate` and rebuild
the release index. Query the persistent store only after a release is accepted.

## Final cross-cutting validation

```bash
./afc selftest.py -q
./afc validate_schema.py --all
./afc check_pipeline_artifacts.py --through-step 5 --json-output work/pipeline-artifacts.json
```

Then run `afc-validate` in at least `quick` mode. This is QA over the completed
pipeline, not Step 7.

## Required final report

**Run identity** — AFC version, run id, source baseline, requested Business
Context, Active Scopes, and whether settings came from `config/settings.yaml`.

**Step results** — for each of Steps 0-6: `DONE`, `DONE_WITH_REVIEW` or `FAILED`,
primary artifacts, counts and key diagnostics.

**Source structure / ingestion** — nested table, text box and image Source Unit
counts; parser gaps; unsupported structures by kind and the judgement made about
each; pending visual extraction count; audit status and route.

**Knowledge preservation** — selected Source Units; Evidence Record count; Card
count; literal and structured signal candidates and any missing Evidence
representation; `unaccounted_source_units`; ID allocation summary
(`new`/`reused`/`rebound`) and the count of Cards identified only by Title.

**Health and decision** — carry forward without overriding: Context selection
review items, Card Health status, each metric's grade **including
`INSUFFICIENT_SAMPLE` / `UNVERIFIED_SAMPLE`** and its sample size, the
recommended route, and the decision state with who decided and when.

Report an ungraded metric as ungraded. Never present a self-reported or
small-sample rate as a measurement.

**Lifecycle** — change-log entries added this run by change type, and any
`Evidence Changed` rows flagged for fidelity review. For persistent runs, also
report the Knowledge Base release ID, proposal counts, the user's decision
state, publish/validation state, and whether the query used the accepted release
or only the current pipeline candidate.

**Query readiness** — index fresh or rebuilt and why, tokenizer version, indexed
Card and Evidence counts, Box/Link availability, and the smoke query result when
one was requested.

**Overall** — one of:

- `PIPELINE READY`
- `PIPELINE READY WITH REVIEW ITEMS`
- `PIPELINE BLOCKED_PENDING_DECISION`
- `AWAITING_KNOWLEDGE_REVIEW`
- `PIPELINE BLOCKED`

A pipeline can be READY WITH REVIEW ITEMS while PM/SA still owes a targeted
Context/Card loop. Successful execution is not evidence of complete knowledge
recall, and the report should not imply otherwise.
