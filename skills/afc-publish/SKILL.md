---
name: afc-publish
description: AFC Step 5: write and reopen-validate the Card, Evidence, Card-Link, Box-Graph, Context and coverage datasets as JSONL plus a human-review Excel, then stage them against the accepted release so a reviewer has proposals. Use for 輸出資料集/發佈候選/產出 Excel/stage proposals. Staging is not accepting: the per-proposal decisions and the publish belong to afc-update.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# STEP 5 — Dataset publish and validation

Run commands with the `afc` launcher from the repo root.

Inputs: `work/step-card-4-master.jsonl`, `work/step-card-4-evidence.jsonl`, Card
Links, Box Nodes, Card-Box Memberships, Box-Box Links, Contexts, and the Step 1
coverage artifacts.

## Goal

Publish a machine-friendly dataset for topology-aware retrieval, keep Excel for
human inspection, and preserve full extraction and relationship traceability.
JSONL is canonical; Excel is for review only and is never read back as source.

## Persistent release boundary and Card quality gate

Step 5 validates and writes this run's candidate outputs; it does not accept
them into the persistent Knowledge Base. After reviewing these artifacts, use
`knowledge_base.py stage` to diff them against the current release. Every
proposal needs an explicit human `accept`, `reject`, or `defer` decision before
`knowledge_base.py publish` can advance the release pointer. Stage the exact
current Step 1 health report with `--health-report work/step-card-1-health.json`;
the runtime binds its hash and status to the staged run. Publication is blocked
when Card health is not `READY`, even if every proposal has been accepted or a
pipeline decision allowed continuing to Links. To publish such a release, a
reviewer must separately provide `--accept-quality-risk-by` and
`--quality-risk-rationale`. This records an explicit quality-risk acceptance in
the immutable release manifest. A request to continue the pipeline is not a
quality waiver.

Step 5 stages, so that a reviewer has proposals to look at. Recording the
decisions and advancing the release pointer is `afc-update`: this step does not
publish, and a staged run is not an accepted one.

```bash
./afc knowledge_base.py stage --kb-root "$AFC_KB_ROOT" --run-id "$RUN" \
  --candidate-dir output --health-report work/step-card-1-health.json
./afc knowledge_base.py validate --kb-root "$AFC_KB_ROOT"
```

Report the staged run ID and the proposal count, then hand over to `afc-update`
for the per-proposal decisions and the publish. When Card health is not `READY`,
publication stays blocked there until a reviewer separately provides
`--accept-quality-risk-by` and `--quality-risk-rationale`; a request to continue
the pipeline is not a quality waiver.

## Outputs

```text
output/knowledge_card_master.jsonl
output/knowledge_domains.jsonl
output/knowledge_evidence.jsonl
output/knowledge_card_master.xlsx
output/knowledge_links.jsonl
output/knowledge_boxes.jsonl
output/knowledge_box_memberships.jsonl
output/knowledge_box_links.jsonl
output/knowledge_contexts.jsonl
output/source_unit_coverage.jsonl
output/source_unit_coverage_report.json
```

```bash
./afc export_cards.py work/step-card-4-master.jsonl -o output/knowledge_card_master.xlsx
```

## Validation before publishing

```bash
./afc validate_schema.py --all
./afc validate_cards.py work/step-card-4-master.jsonl
./afc validate_evidence.py work/step-card-4-evidence.jsonl --cards work/step-card-4-master.jsonl
./afc validate_links.py work/step-card-2-links.jsonl --cards work/step-card-4-master.jsonl
./afc validate_boxes.py --boxes work/step-card-3-boxes.jsonl \
  --memberships work/step-card-3-box-memberships.jsonl \
  --box-links work/step-card-3-box-links.jsonl \
  --cards work/step-card-4-master.jsonl \
  --json-output work/step-card-5-box-audit.json
./afc validate_coverage.py \
  --source-map work/step-card-0-source-map.jsonl \
  --coverage work/step-card-1-coverage.jsonl \
  --cards work/step-card-4-master.jsonl \
  --json-output output/source_unit_coverage_report.json
```

`validate_schema.py --all` validates every canonical artifact that exists against
`schemas/`. A file whose kind cannot be resolved fails rather than being skipped
quietly — a silent skip is what made 13 shipped schemas go unused in v0.4.1.

Checklist:

- Card count matches the curated master; Card IDs unique.
- Card Links have valid Card endpoints; Box Memberships have valid Card and Box
  endpoints; Box Links have valid Box endpoints.
- Hierarchy relations contain no cycle.
- Evidence Records retained with original text and values unrewritten.
- Every source-derived non-Concept Card has valid Evidence linkage, and no
  dangling Card-Evidence reference in either direction.
- Lifecycle is coherent: `Superseded` implies `Superseded By`, and that target
  exists.
- Selected Source Units are fully accounted for, `unaccounted_source_units = 0`.
- Every JSONL reparses; the Excel reopens and its row count matches.

```bash
./afc check_pipeline_artifacts.py --through-step 5 --json-output work/step-card-5-artifacts.json
```

Required artifacts must be present, non-empty and parseable — v0.4.1 accepted any
file whose size was `>= 0`, so an empty file counted as published.

## Report

Published row counts per dataset; coverage accounting; lifecycle counts by
status; change-log entries added this run; and the Excel reopen result.

Do not add vector embeddings by default. Benchmark Box-aware hybrid retrieval
first — `afc-validate`'s retrieval regression layer is where that comparison
belongs.

<!-- afc:scope:begin -->
<!-- Generated from config/skill-scopes.yaml by scripts/sync_skill_metadata.py.
     Edit the manifest, not this block: the `afc` launcher enforces the
     manifest, so a hand-edited copy here would only disagree with it. -->

## Scope

This skill may cause **work** changes. Set
`AFC_SKILL=afc-publish` while following it: the `afc` launcher then refuses any
command outside the scope below and names the skill that owns it.

Commands this skill may run:

- `check_pipeline_artifacts.py`
- `export_cards.py`
- `knowledge_base.py` — only `stage, validate, index`
- `validate_boxes.py`
- `validate_cards.py`
- `validate_coverage.py`
- `validate_evidence.py`
- `validate_links.py`
- `validate_schema.py`

Not this skill's job:

- accepting proposals or publishing a release → `afc-update`
- changing a Card, Link or Box to make validation pass → `afc-curate`

`./afc --scope afc-publish` prints this boundary.
<!-- afc:scope:end -->
