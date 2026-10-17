# Measuring extraction health

The command sequence for the four measured Loop Gate metrics: draw the
samples, record one verdict per drawn item, compute the rates, evaluate
health. `afc-cards/SKILL.md` holds what the result means and when a run is
`READY`; this file holds how to produce it. Sizes and thresholds come from
`config/settings.yaml` — never restate one from memory.

### Draw the samples

```bash
RUN=$(date +%Y%m%dT%H%M%S)

./afc sample_units.py --purpose saturation --source-map work/step-card-0-source-map.jsonl \
  -n 40 --run-id "$RUN" -o work/step-card-1-saturation-sample.json \
  --verdict-template work/step-card-1-saturation-verdicts.jsonl

./afc sample_units.py --purpose fidelity --cards work/step-card-1-cards.jsonl \
  --evidence work/step-card-1-evidence.jsonl \
  -n 40 --run-id "$RUN" -o work/step-card-1-fidelity-sample.json \
  --verdict-template work/step-card-1-fidelity-verdicts.jsonl

./afc sample_units.py --purpose atomicity --cards work/step-card-1-cards.jsonl \
  -n 40 --run-id "$RUN" -o work/step-card-1-atomicity-sample.json \
  --verdict-template work/step-card-1-atomicity-verdicts.jsonl
```

Use at least `card_health.min_sample_for_rate_grading` items (30 by default).
Below that the green threshold is not expressible: at n=12 the smallest non-zero
rate is 8.3%, so a 2% green band is meaningless and the metric is graded
`INSUFFICIENT_SAMPLE` rather than passed.

### Fill in one verdict per sampled item

Fill the template; answer every drawn item and nothing else. Looking only at the
easy ones is rejected, and so is adding an item you were not given.

```json
{"purpose":"saturation","item_type":"source_unit","item_id":"CA_spec_v2.docx::B000031::T003::R0009","verdict":"missing_evidence","note":"原始越南文訊息未建立 Evidence Record"}
{"purpose":"fidelity","item_type":"card","item_id":"CARD-000188","verdict":"unsupported_claim","note":"Card 聲稱 30 天，來源僅寫「期限內」"}
{"purpose":"atomicity","item_type":"card","item_id":"CARD-000205","verdict":"split_required","note":"同一張卡混合三條獨立規則"}
```

The verdict vocabulary for each purpose, with worked rows, is in
`references/review-verdicts.md`.

A stylistic rewrite is not missing knowledge. A long Card is not automatically a
split candidate.

### Compute the rates

```bash
for p in saturation fidelity atomicity; do
  ./afc compute_review_metrics.py \
    --sample "work/step-card-1-$p-sample.json" \
    --verdicts "work/step-card-1-$p-verdicts.jsonl" \
    -o "work/step-card-1-$p-report.json"
done
```

### Evaluate health

```bash
./afc evaluate_card_health.py \
  --source-map work/step-card-0-source-map.jsonl \
  --coverage work/step-card-1-coverage.jsonl \
  --cards work/step-card-1-cards.jsonl \
  --evidence work/step-card-1-evidence.jsonl \
  --saturation-report work/step-card-1-saturation-report.json \
  --fidelity-report work/step-card-1-fidelity-report.json \
  --atomicity-report work/step-card-1-atomicity-report.json \
  --context-health work/step-card-0-context-selection-audit.json \
  --history work/step-card-1-health-history.jsonl \
  --json-output work/step-card-1-health.json \
  --append-history work/step-card-1-health-history.jsonl
```

Add `--previous-cards` when comparing against the same source/context baseline;
with stable registry IDs, rerun novelty is now computed rather than estimated.
Add `--baseline-run` only when the Knowledge Base has no accepted Card release.
Verified reviews of the full population may be graded as a census even when the
population is smaller than the configured statistical sample minimum.
