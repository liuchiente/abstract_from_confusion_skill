# Review sample verdicts

Read this when filling a verdict template drawn by `sample_units.py`. Answer
every drawn item and nothing else; `compute_review_metrics.py` turns the
verdicts into the rate.

Verdict vocabularies:

| Purpose | Question per item | Verdicts |
| --- | --- | --- |
| saturation | Is any supported knowledge or source-native literal/structured fact still unrepresented? | `complete`, `missing_card`, `missing_evidence`, `missing_both` |
| fidelity | Is the claim supported, and is every literal/structured source value preserved unaltered? | `supported`, `unsupported_claim`, `altered_literal`, `dropped_structured_fact` |
| atomicity | Does this Card hold exactly one independently referenceable claim? | `atomic_keep`, `split_required`, `ambiguous` |
