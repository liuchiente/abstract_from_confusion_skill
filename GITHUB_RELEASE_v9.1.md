# AFC Card Experiment v9.1

## Highlights

- **Skill scope is declared and enforced.** `config/skill-scopes.yaml` states,
  per skill, the scripts it may run and the strongest change it may cause
  (`read-only` / `work` / `release`). With `AFC_SKILL` set to the skill being
  followed, the `afc` launcher refuses anything outside that scope and names the
  skill that owns it, so a step cannot quietly do the next step's work — no
  rescanning sources to answer a question, no publishing from a validation pass,
  no inventing a Card to fill a gap. `./afc --scope <skill>` prints a boundary.
- **One package, two harnesses.** `install.sh --target codex|claude|both`
  installs for Codex and Claude Code from the same skills, scripts, config and
  rules template. The rules section now lands in `AGENTS.md` and `CLAUDE.md` at
  the repo root; the previous location inside the runtime directory was never
  loaded, so an installed repo ran with no AFC rules at all.
- **Step 1 can be batched and resumed.** A source too large to extract in one
  pass is planned into batches that keep their reading context, written per
  batch, then rejoined by a merge that refuses a half-merge, a placeholder-ID
  collision, or two dispositions for one Source Unit. Resuming regenerates the
  plan from the coverage already recorded.
- **Three silent passes became failures.** A mistyped source map now routes
  `SOURCE_PARSING_GAP` instead of auditing zero units; a mistyped flag on
  `knowledge_base.py` is an error instead of being ignored; and the launcher no
  longer rewrites `--target-scope CA` into a path because a folder named `CA`
  happens to exist.

## Changed behaviour

`afc-publish` stages and no longer publishes: the per-proposal decisions and the
release pointer belong to `afc-update`. `MIGRATION.md` lists all five breaking
changes and the upgrade sequence.

## Also in this release

- `validate_schema.py --draft` separates unallocated placeholder IDs from real
  schema errors, so a batch can be checked before `allocate_ids.py` runs.
- `knowledge_base.py decide --decisions-file` records a reviewed set of
  proposals in one atomic write, validating every row before writing any.
- `afc-query` has a fast path for a plain lookup, with explicit conditions for
  falling back to the full planner.
- Skill descriptions carry the words a user actually types, in Chinese and
  English, and name the sibling that owns the neighbouring work.
- `afc-cards` and `afc-context` moved reference material into `references/`, so
  a run loads the step's rules and only the detail it needs.
- Version-conditional clauses are gone from the skills: one current behaviour,
  with the real condition named instead of a release number.
- The runtime version is read from `VERSION` rather than restated in code, where
  three copies had gone stale — including the one stamped into release
  manifests.

## Verification

332 tests pass in the source tree and from an installed runtime. New checks pin
the things that used to drift: every documented command is inside its skill's
declared scope, every script has a change class, every documented input artifact
is produced by some documented command, the OCR-enriched map reaches Card
extraction, both install targets produce byte-identical skills, and the
verifier always reaches a verdict.
