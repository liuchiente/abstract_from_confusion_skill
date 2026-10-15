---
name: afc-curate
description: Assemble the governed AFC Knowledge Card Master while preserving source evidence, stable IDs, Box memberships/topology, Card Links, conflicts, lifecycle status and context-specific recurrence. Use as AFC Card Experiment Step 4.
---

# STEP 4 — Knowledge Card Master curation

Run commands with the `afc` launcher from the repo root.

Inputs: reconciled Cards, Evidence Records, Card Links, Box Nodes, Card-Box
Memberships, Box-Box Links, Contexts, and the configured stable-ID registry.
With `AFC_KB_ROOT` set, that registry is
`$AFC_KB_ROOT/identity/id-registry.jsonl`; otherwise it is `work/id-registry.jsonl`.

## Goal

Produce a stable Card Master without a human approval gate at this step —
the human gate is at Step 1, on Card health. Preserve every valid
context-specific Card, Concept Card, source Evidence Record, conflict, Box
boundary and relationship. Evidence Records stay a separate governed
source-preservation dataset and are never rewritten to match curated Card
wording.

Preserve `Semantic Domain Keys` only when they reference an existing accepted
domain registry. Keep labels synchronized with registry canonical labels. Do not
mint new keys during curation; propose new domains through `afc-domains` so they
receive their own human-reviewed release proposal.

## Identity

Card, Evidence, Box, Membership, Box Link and Card Link IDs are preserved
whenever their stable identity is unchanged. Identity is computed, not chosen:

```bash
./afc allocate_ids.py \
  --cards work/step-card-4-master.jsonl \
  --evidence work/step-card-4-evidence.jsonl \
  --run-id "$RUN" --json-output work/step-card-4-id-allocation.json
```

Never renumber. A Card reinterpretation must not mutate the historical Evidence
it was derived from; the allocation report's `rebound` count is how a reworded
claim keeps its ID.

## Lifecycle

Each Card and Evidence Record carries `Status` (`Active`, `Superseded`,
`Retired`). A superseded Card also carries `Superseded By`, and the Card that
replaced it may carry `Supersedes`. `First Seen Run` and `Last Seen Run` come
from ID allocation.

Append this run's changes so historical values survive the rebuild:

```bash
./afc record_changes.py \
  --cards work/step-card-4-master.jsonl --evidence work/step-card-4-evidence.jsonl \
  --previous-cards output/knowledge_card_master.jsonl \
  --previous-evidence output/knowledge_evidence.jsonl \
  --run-id "$RUN" --decision work/step-card-1-decision.json \
  --log work/knowledge-change-log.jsonl
```

This is the run-local change log. In persistent v0.6, `knowledge_base.py stage`
creates human-review proposals after publication artifacts are ready; only
accepted proposals are copied to the Knowledge Base history and next release.
The pipeline rebuilds Cards from documents every run, so keep accepted history
to answer historical-value questions. Treat `Evidence Changed` as REVIEW —
either the source changed, or a literal was altered, and those need different
responses.

## Chinese enrichment

`中文補充` is separate from source fact. With no Chinese source text, prefer
current Vietnamese, then English, then Company Context terminology, and legacy
Chinese only as a translation reference. Never overwrite a newer
Vietnamese/English fact with an older Chinese document, and keep
`中文補充依據` pointing at what the enrichment was derived from.

## Box boundary preservation

Similar content with different confirmed Box boundaries stays separate:

```text
Back / CA / Confirmation Page
Back / CA / Search Result Page
```

remain two Cards when the behaviour or context differs. Do not copy Card content
into Box datasets.

## Dates

`Source Version` and `Source Date` come only from source evidence. The pipeline
run date is separate metadata and must not be presented as a Source Date.

## Conflicts

Keep both Cards and the `conflicts_with` link where evidence supports it. Box
topology is not a tool for normalizing or hiding a conflicting fact.

## Outputs

```text
work/step-card-4-master.jsonl
work/step-card-4-evidence.jsonl
work/step-card-4-id-allocation.json
work/knowledge-change-log.jsonl
```

Carried forward as separate governed datasets:
`work/step-card-2-links.jsonl`, `work/step-card-3-boxes.jsonl`,
`work/step-card-3-box-memberships.jsonl`, `work/step-card-3-box-links.jsonl`.

## Validation

```bash
./afc validate_schema.py work/step-card-4-master.jsonl work/step-card-4-evidence.jsonl
./afc validate_cards.py work/step-card-4-master.jsonl
./afc validate_evidence.py work/step-card-4-evidence.jsonl --cards work/step-card-4-master.jsonl
./afc validate_links.py work/step-card-2-links.jsonl --cards work/step-card-4-master.jsonl
./afc validate_boxes.py --boxes work/step-card-3-boxes.jsonl \
  --memberships work/step-card-3-box-memberships.jsonl \
  --box-links work/step-card-3-box-links.jsonl \
  --cards work/step-card-4-master.jsonl \
  --json-output work/step-card-4-box-audit.json
```

## Delta

Report Added / Resolved / Updated / Unchanged / Removed Confirmed / Conflict with
stable IDs and the properties that changed, plus the change-log summary by change
type. A Card whose wording changed while its evidence basis did not is a
`Reinterpretation`, not an update to a source fact — keep them distinguishable.
