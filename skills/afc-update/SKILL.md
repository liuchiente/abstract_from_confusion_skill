---
name: afc-update
description: Turn a completed discussion or a staged pipeline run into evidence-backed release proposals, record an explicit accept/reject/defer per proposal, and publish the accepted release. Use for 套用變更/更新知識庫/發佈新版本/接受提案/apply the update. The investigation that justifies a change is afc-discuss; this skill never invents a fact the source does not support.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
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

`decide` takes one proposal at a time, or a whole reviewed set at once. For more
than a handful of proposals, write one row per proposal and pass the file: every
row is validated before anything is recorded, so a bad row leaves the review
untouched rather than half-recorded. One row per proposal is still one explicit
decision — the file is a way to record a completed review, not a way to skip it.

```bash
# work/release-decisions.jsonl, one reviewed proposal per row
# {"proposal_id":"PROP-000001","decision":"accept","reviewer":"PM: <name>","rationale":"<why>"}
./afc knowledge_base.py decide \
  --kb-root ../knowledge/cproduct --run-id cproduct-20261012-01 \
  --decisions-file work/release-decisions.jsonl
```

Publish only after every staged proposal has a current explicit decision. If the
base release changed or a proposal changed after review, stage and review again.

## Validate and report

After publish, validate the new release, rebuild its query index, and run the
affected query cases. Report the old and new release IDs, source Evidence,
accepted/rejected/deferred counts, unresolved items, and query impact. Keep
rejected and deferred proposals in run history.

If the requested change is unsupported by source Evidence, do not manufacture a
fact. Return it to `afc-discuss` or keep it recorded as an unresolved gap.

<!-- afc:scope:begin -->
<!-- Generated from config/skill-scopes.yaml by scripts/sync_skill_metadata.py.
     Edit the manifest, not this block: the `afc` launcher enforces the
     manifest, so a hand-edited copy here would only disagree with it. -->

## Scope

This skill may cause **release** changes. Set
`AFC_SKILL=afc-update` while following it: the `afc` launcher then refuses any
command outside the scope below and names the skill that owns it.

Commands this skill may run:

- `knowledge_base.py`
- `query_fast.py`
- `run_query_benchmark.py`
- `validate_schema.py`

Not this skill's job:

- inventing a fact the source Evidence does not support → `afc-discuss`
- inferring a proposal decision from silence → the user
- re-running source extraction → `afc-pipeline`

`./afc --scope afc-update` prints this boundary.
<!-- afc:scope:end -->
