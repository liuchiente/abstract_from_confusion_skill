# Batched extraction and resume

Read this when the source is too large to extract in one pass, or when
picking up an extraction that stopped part way. A small source needs none of
it: extract it in one pass and go to the coverage ledger.


Step 1 is the one step whose output you write by hand: an Evidence Record per
preserved source fact, Cards for supported knowledge, and exactly one coverage
ledger row per selected Source Unit. A large source therefore has a size this
cannot be done in one pass, and guessing where you stopped is not a protocol.

Plan the batches before extracting anything. The batch size comes from
`extraction.max_units_per_batch` in `config/settings.yaml`; do not pick one from
memory:

```bash
./afc plan_extraction_batches.py \
  --source-map work/step-card-0-source-map.jsonl \
  --run-id "$RUN" -o work/step-card-1-extraction-plan.json
```

The plan groups pending selected units so a batch keeps its reading context — a
section, sheet or table stays together where it fits — and writes each batch's
units to its own file. Read that file, not the whole source map. A batch whose
group was too large to keep whole is flagged `split_groups`: re-read the
surrounding section before judging those units.

Write each batch to the per-batch paths the plan names
(`work/step-card-1-{cards,evidence,coverage}.<batch_id>.jsonl`) and prefix every
placeholder ID with the batch's `id_prefix` (`EVD-P7f67e3-B002-014`). Two batches
that both invent `EVD-TMP-001` are a collision the merge will reject, and should.

Check a batch's shape before moving on. IDs are still placeholders at this
point, so use draft mode: it reports an unallocated ID as a placeholder instead
of an error, leaving the real structural mistakes visible.

```bash
./afc validate_schema.py --draft \
  work/step-card-1-cards.<batch_id>.jsonl \
  work/step-card-1-evidence.<batch_id>.jsonl \
  work/step-card-1-coverage.<batch_id>.jsonl
```

Merge when the batches are done, then allocate IDs **once** over the merged
files:

```bash
./afc merge_extraction_batches.py \
  --cards work/step-card-1-cards.*.jsonl \
  --evidence work/step-card-1-evidence.*.jsonl \
  --coverage work/step-card-1-coverage.*.jsonl \
  --plan work/step-card-1-extraction-plan.json \
  --json-output work/step-card-1-merge-report.json
```

The merge writes nothing unless it is clean: one ID may not name two different
records, one Source Unit may not carry two dispositions, a ledger row may only
cite Cards and Evidence present in the merge, and with `--plan` every planned
unit must be accounted for. An unfinished extraction is reported as unfinished
rather than passing as a complete one.

**To resume**, regenerate the plan with the coverage you already have. Accounted
units drop out and you get the remaining work; the plan is a snapshot, not a
fixed schedule:

```bash
./afc plan_extraction_batches.py \
  --source-map work/step-card-0-source-map.jsonl \
  --coverage work/step-card-1-coverage.jsonl \
  --coverage work/step-card-1-coverage.*.jsonl \
  --run-id "$RUN" -o work/step-card-1-extraction-plan.json
```

Batching is a context budget, not a checkpoint for approval: keep going through
the batches without stopping to ask, and do not treat a batch boundary as a
reason to lower extraction quality or to stop at the easy units. Small sources
need no plan — extract them in one pass.
