---
name: afc-discuss
description: Investigate and discuss a reported gap, conflict, or outdated fact against one accepted AFC Knowledge Base, collecting source evidence and a human-reviewed conclusion before any knowledge update.
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

Mark `Ready for Update` only after the user confirms the discussion is captured
well enough to form change proposals. If evidence is still missing, keep the case
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
