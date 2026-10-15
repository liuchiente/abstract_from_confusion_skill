---
name: afc-publish
description: Publish and reopen-validate AFC Card, Evidence, Card-Link, Box-Graph, Context and coverage datasets as machine-friendly JSONL plus a human review Excel. Use as AFC Card Experiment Step 5.
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

## Persistent release boundary (v0.6)

Step 5 validates and writes this run's candidate outputs; it does not accept
them into the persistent Knowledge Base. After reviewing these artifacts, use
`knowledge_base.py stage` to diff them against the current release. Every
proposal needs an explicit human `accept`, `reject`, or `defer` decision before
`knowledge_base.py publish` can advance the release pointer. Do not treat a
successful Step 5 artifact export as an accepted knowledge update.

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
