# AFC seven-step one-run instructions

After installing, start a new Codex session in the project and paste one of
these. Commands inside the skills use the `./afc` launcher, so no path setup is
needed — confirm it resolves first:

```bash
./afc --home
./afc check_environment.py
```

## Configuration-driven run

```text
Use afc-pipeline to run the complete AFC seven-step pipeline (Step 0 through Step 6) using the
existing project configuration and all source files under the configured input path.

Do not pause for confirmation between normal steps. Preserve review items and health
recommendations, and only hard-stop when the next step cannot safely run or when the Step 1
decision gate is owed.

At Step 0, run Source Structure Ingestion/Audit first. Recursively extract DOCX nested tables,
text box/shape text and embedded images; propagate merged Excel headers; capture Excel formulas
alongside displayed values. Run configured local OCR on images and scanned PDF pages first.
Preserve high-confidence OCR text verbatim and route low-confidence or missing OCR to review.
Use vision only when I explicitly authorize it; otherwise report SOURCE_VISUAL_EXTRACTION_GAP.
Report SOURCE_UNSUPPORTED_STRUCTURE with a judgement
about whether the unreadable content carries knowledge my queries need. Then use the two-axis
selection model and preserve Semantic Knowledge, Literal Knowledge, Structured Facts and Structural
Context within the active Scope boundary.

At Step 1, allocate stable Card/Evidence IDs from the registry, create source-preserving Evidence
Records for selected literal/structured facts even when they do not need standalone Cards, and
never use image alt text in place of an original visible message. Draw the saturation, fidelity and
atomicity samples with sample_units.py, record one verdict per drawn item, and compute the rates
with compute_review_metrics.py. Report each metric's grade, including INSUFFICIENT_SAMPLE or
UNVERIFIED_SAMPLE, with its sample size.

At the end, run quick afc-validate and return the final pipeline report with Step 0-6 status,
counts, the health and loop recommendation with sample grades, the decision state, and query
readiness.
```

## Business Context run

```text
Use afc-pipeline to run AFC Step 0 through Step 6 end-to-end.
Business Context: 車險
Use the approved Business Context mapping to resolve active scopes.
Source: use all files under the configured input path.
Do not pause for confirmation between normal steps.
Do not auto-loop Context or Cards; report the health metrics and stop at the decision gate if one
is owed, telling me the exact record_decision.py command to run.
At Step 6, build/reuse the query index and report Query Readiness, including the index's
tokenizer_version and any rebuild reasons.
Finally run quick afc-validate and give me the complete pipeline report, including the Source
Structure Audit status, nested-table count, image Source Unit count, pending visual extraction
count, unsupported structures by kind, and any SOURCE_PARSING_GAP /
SOURCE_UNSUPPORTED_STRUCTURE / SOURCE_VISUAL_EXTRACTION_GAP route.
```

## Business Context + final query

```text
Use afc-pipeline to run AFC Step 0 through Step 6 end-to-end.
Business Context: 車險
Source: use all files under the configured input path.
Final query: 無法加買時，來源文件的原始錯誤訊息是什麼？
Do not pause for confirmation between normal steps, and do not auto-loop on health metrics.
Preserve source-native names, messages, component types, codes, values and languages in Evidence
Records.
After Step 6, run quick afc-validate and return the pipeline report plus the final query result
with source/evidence traceability, the target mode detected, and the recovery stage used.
```

## Unattended run

The Step 1 decision gate pauses a run when Card health is not READY and nobody
has chosen a route. To run fully unattended, make that explicit in
`config/settings.yaml` rather than asking the agent to skip it:

```yaml
decision:
  required_when_not_ready: false
```

The pipeline report then states that the gate did not apply and why.

## Validation only

```text
Use afc-validate in standard mode against the current AFC artifacts.
Start with the package self-test and schema conformance, then source structure, coverage, Card
convergence including the sample grades, Evidence preservation, structural correctness, the
retrieval benchmark against the accepted baseline, and lifecycle regression.
Report whether a current human decision exists for the Card-stage recommendation.
```

## Persist and review a v0.6 Knowledge Base update

Before Step 0, inventory the exact product source root and behavior. Use the
run's `eligible-source-paths.json` as the extraction list, set `AFC_KB_ROOT` so
stable IDs use the persistent registry, and do not mark a partial source scan as
a complete boundary. After Step 5 and pipeline QA, stage the outputs and review
every proposal. Record accept/reject/defer with a reviewer and rationale before
publishing. A pipeline run alone does not advance the accepted Knowledge Base.

```text
Use afc-pipeline to extract this behavior into the v0.6 Knowledge Base.
Knowledge Base: ../knowledge/cproduct
Business Context: 車險
Target Scope: CA
Source root: ../products/cproduct
Behavior to extract: passenger insurance add-on rules
Use an incremental scan. After Steps 0-6 and QA, stage the candidate changes,
show the proposals for human review, and stop before publish until I decide them.
```
