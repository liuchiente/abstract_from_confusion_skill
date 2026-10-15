---
name: afc-update
description: Convert a completed AFC Knowledge Discussion or explicit pipeline change into evidence-backed release proposals, record per-proposal decisions, and publish an accepted update.
---

# AFC Knowledge Update — governed release change

Use after `afc-discuss` has marked a case `Ready for Update`, or when the user
explicitly asks to turn a completed pipeline run into a persistent Knowledge Base
update. Ordinary factual questions belong to `afc-query`; unresolved conflicts
belong to `afc-discuss`.

## Establish the update base

Resolve one KB ID and read its current `CURRENT.json` release. For discussion-led
updates, require the discussion record path and verify its KB ID, base release,
and `Ready for Update` status. If the base changed, compare the affected facts
with the new release and return to `afc-discuss` when the prior conclusion may no
longer apply.

## Build and review proposals

Translate each confirmed discussion outcome into the smallest supported object
changes: Cards, Evidence, Links, Boxes, Scope attributions, or Domain Keys as
applicable. Keep facts and unresolved questions separate. A discussion record
guides the proposed change; it does not silently authorize changes to the
accepted release.

For pipeline-produced candidates, run `knowledge_base.py stage` against the same
base release. Review `runs/<run-id>/proposals.jsonl` and record an explicit
`accept`, `reject`, or `defer` for every proposal using `knowledge_base.py decide`
with reviewer and rationale. Never infer a decision from silence or from a
discussion about the general direction.

Publish only after every staged proposal has a current explicit decision. If the
base release changed or a proposal changed after review, stage and review again.

## Validate and report

After publish, validate the new release, rebuild its query index, and run the
affected query cases. Report the old and new release IDs, source Evidence,
accepted/rejected/deferred counts, unresolved items, and query impact. Keep
rejected and deferred proposals in run history.

If the requested change is unsupported by source Evidence, do not manufacture a
fact. Return it to `afc-discuss` or keep it recorded as an unresolved gap.
