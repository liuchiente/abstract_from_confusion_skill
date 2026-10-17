---
name: afc-discuss
description: Investigate a reported gap, conflict or outdated fact against one accepted Knowledge Base, collect the source evidence on each side, and record a human-reviewed conclusion. Use for 這個答案不對/來源到底怎麼寫/兩份文件寫得不一樣/不一致/知識衝突/過時規則/缺漏/investigate a discrepancy. An ordinary factual question is afc-query, not a source scan; applying the conclusion is afc-update. Changes no knowledge itself.
allowed-tools: Bash, Read, Write, Glob, Grep
---

# AFC Knowledge Discussion

Use this before `afc-update` when a user reports a conflict, missing fact,
outdated rule, or an answer that needs investigation. Ordinary factual questions
belong to `afc-query`; do not turn every query into a source scan.

## Establish the discussion boundary

Resolve the KB ID first. If the named field maps to multiple KBs, ask the user to
choose. Record the current accepted release, the issue, relevant Scope, Context
or Boxes, and any source folders the user selected. Domain Keys classify
subtopics within the selected KB; if multiple subtopics could change the
conclusion, ask which one the user means.

## Investigate and discuss

Everything here reads. Confirm the release you are discussing is intact, then
query it:

```bash
./afc knowledge_base.py validate --kb-root "$AFC_KB_ROOT"
./afc knowledge_base.py query --kb-root "$AFC_KB_ROOT" \
  --query '<the reported fact, in the user's own words>' \
  --mode card -o work/query-runs/<case-id>-accepted.json
```

Ask the Evidence layer separately when the dispute is about what the source
literally says — a `--mode` of `field` or a question naming a language reaches
the source-preserving records rather than the normalized claim. With a workspace
catalog, select the KB first with `workspace.py list` and
`workspace.py query --kb-id <id> --query ...`.

1. Query the accepted release and inspect relevant Cards and Evidence Records.
2. Trace the reported fact to source units and locations. A search miss is not
   proof that the fact is absent from the source.
3. Compare candidate facts by KB, Scope, scenario, source version/date, effective
   period, and literal Evidence before calling them conflicts.
4. Present the current accepted knowledge, source-backed alternatives, evidence
   gaps, and likely impact in plain language. Discuss the alternatives with the
   user; do not choose a winner without their direction and supporting evidence.
5. Record new facts, corrections, exclusions, unresolved questions, and the
   user's conclusion as the discussion evolves. Keep the accepted release
   unchanged.

## Collect the discussion record

Persist one Markdown record at
`$AFC_KB_ROOT/discussions/<case-id>.md`. If no persistent KB root is active, use
`work/discussions/<case-id>.md`. Use a short stable case ID and include:

- KB ID and base accepted Release ID
- issue and requested outcome
- relevant Scope, Context, Box, and Domain Keys, if known
- current accepted fact and affected Card/Evidence IDs
- source alternatives with verbatim excerpts, source locations, and versions
- conflict or gap classification
- discussion decisions, rationale, and unresolved questions
- status: `Collecting`, `Needs More Evidence`, or `Ready for Update`
- date and reviewer

Write the record with your own file tools; no AFC command produces it. Mark
`Ready for Update` only after the user confirms the discussion is captured well
enough to form change proposals. If evidence is still missing, keep the case
open and identify the next source or question needed. Do not edit release JSONL,
stage proposals, or publish during this skill.

## Handoff

When the user asks to apply a completed discussion, pass its record path to
`afc-update`. If the accepted base release changed since the discussion, compare
the affected Cards and Evidence again, update the record, and reconfirm any
conclusion that may have changed.

Example request:

```text
Use afc-discuss for KB `cproduct`. Investigate the passenger insurance add-on
period conflict between the accepted knowledge and the selected source folder.
Collect the evidence, explain the alternatives, and save a discussion record.
Do not update the accepted release.
```

<!-- afc:scope:begin -->
<!-- Generated from config/skill-scopes.yaml by scripts/sync_skill_metadata.py.
     Edit the manifest, not this block: the `afc` launcher enforces the
     manifest, so a hand-edited copy here would only disagree with it. -->

## Scope

This skill may cause **read-only** changes. Set
`AFC_SKILL=afc-discuss` while following it: the `afc` launcher then refuses any
command outside the scope below and names the skill that owns it.

Commands this skill may run:

- `knowledge_base.py` — only `query, validate`
- `query_fast.py`
- `validate_schema.py`
- `workspace.py` — only `query, list`

Not this skill's job:

- staging proposals, deciding them or publishing → `afc-update`
- editing release JSONL → `afc-update`
- choosing between conflicting source facts without the user → the user

`./afc --scope afc-discuss` prints this boundary.
<!-- afc:scope:end -->
