# AFC Card Experiment v9.1

A portable skill bundle for a Card-centric AFC knowledge architecture: source
Contexts, Business Context-to-Scope resolution, source-preserving Evidence
Records, normalized Atomic Cards, a topology-aware Box Graph, Card Links, and
fast hybrid retrieval.

This repository holds the whole package — the `skills/` instructions **and** the
Python runtime, parsers, schemas, config and installers they call. Earlier
versions published the skills alone; they cannot be trusted on their own,
because each skill's generated Scope section promises that an out-of-scope
command will be refused, and that refusal lives in the runtime
(`config/skill-scopes.yaml` plus the `afc` launcher). Shipping the promise
without the mechanism is the exact defect class this package exists to remove.

Install it into a Codex or Claude Code repo with
`install.sh --target codex|claude|both`, or clone and run from here.

## v9.1 — declared scope, two harness targets, resumable extraction

Each skill now declares what it may run and the strongest change it may cause,
and the launcher enforces it: with `AFC_SKILL` set to the skill being followed,
a command outside that scope is refused and the owning skill is named. One
source installs for both Codex and Claude Code. Step 1 can be batched and
resumed for a source too large to extract in one pass. Three silent passes
became failures: a mistyped source map, a mistyped flag, and an option value
the launcher used to rewrite into a path.

`GITHUB_RELEASE_v9.1.md` has the highlights and `MIGRATION.md` lists all five
breaking changes — the first being that `afc-publish` stages and no longer
publishes.

v0.8.0 introduced a workspace catalog that routes multiple source folders to
separate, portable Knowledge Bases by KB ID. v0.8.1 added static syntax-tree
parsing for Java, Dart/Flutter, JavaScript/TypeScript (including Ionic
Angular/React/Vue source), and PHP. Python source continues to use the
standard-library AST. Source code is never imported or executed. General
reference knowledge can use an explicit Scope-neutral policy, while product
knowledge continues to use directory or prompt Scope boundaries.

The user-facing selector is the KB ID. Current accepted release selection stays
internal. The workspace catalog records KB roots, source folders, and whether
product Scope applies. Overlapping source folders within one KB retain separate
memberships; the same folder can be registered in different KBs, but knowledge
is kept isolated between them. See `OPERATIONS.md` for setup, scans, updates,
queries, export/import, and troubleshooting.

## v0.8.6 — article section boundaries

Article PDF extraction now carries the document topic and active chapter path
across page breaks. Numbered sibling sections such as `9.1` and `9.2` remain
siblings, and nested headings such as `9.2.1` stay under the correct parent.
Coverage validation reports Card, Skip, Review and unaccounted source units by
document section, so a high-level completion rate cannot hide untouched
sections. The default `fast` PDF profile retains its legacy extraction path.

## v0.8.1 — code parser expansion

The optional code parser uses local Tree-sitter grammars for Java, Dart, JS/TS,
PHP, HTML templates, Vue single-file components, and CSS/SCSS. It creates source units for
modules, classes, methods/functions, imports, HTML elements, Vue templates, and style rules. It
does not execute code, resolve types, or claim runtime behavior. Install
`requirements-code.txt` with Python 3.10+, then pre-download the selected
grammars with `prepare_code_parser.py`; subsequent parsing uses the local cache.

## v0.8.3 — parser, lifecycle, and portability fixes

Python files now complete the same parser reporting path as the other code
languages. Source Unit IDs gain a folder namespace only when registered roots
contain colliding relative paths. Incremental scans retain registered source
memberships when a subfolder is selected, and inventory prunes common generated
and dependency directories before traversal. Proposal decisions are bound to
the reviewed proposal content; release validation requires Evidence for
source-derived Cards; queries filter Superseded and Retired Cards and Evidence.
New or updated source-derived Cards must carry Evidence. Existing accepted
releases stay readable during migration. Portable packs now use their bundled
query vocabulary, and old default query indexes are rebuilt automatically when
a KB is queried.

## v0.8.5 — article-PDF extraction and release quality gate

PDF fast mode remains unchanged. An explicit `article` profile uses pypdf layout
extraction, adds conservative numbered-heading context, and can emit embedded
PDF images as traceable image Source Units using the optional PyMuPDF/Pillow
dependencies.
`afc-cards` now requires semantic, atomic claim extraction from prose and study
guides; signal matches are discovery hints, and a signal miss is not by itself a
reason to leave a unit in Review. Tables, diagrams, code and slide notes have
separate extraction guidance. Persistent staging binds the current Card health
report; publishing a non-READY run requires a separate, explicit quality-risk
acknowledgement. Continuing to Links no longer implies release-quality approval.

## v0.8.4 — discussion-first updates and query disambiguation

`afc-discuss` records a human-led investigation of gaps or conflicts before
`afc-update` creates release proposals. Query asks the user to choose when
multiple KBs, Scopes, Boxes, or semantic subdomains remain plausible and that
choice could change the answer. Semantic Domain Keys classify subtopics inside
one KB; the KB ID remains the knowledge-base boundary.

## v0.8.2 — Python runtime floor

All AFC commands now require Python 3.10 or newer. Set `AFC_PYTHON` to the interpreter used to install the runtime requirements; the launcher checks the version before running any command. Optional code parsing uses that same interpreter.

## v0.8.0 — workspace and knowledge management

**One workspace can manage multiple knowledge fields.** `afc-workspace.json`
registers each KB ID, its independent storage root, source folders, and Scope
policy. `workspace.py` routes inventory, queries, and portable-pack export by
KB ID. Process KBs sequentially because AFC's `work/` and `output/` are shared.

**One scan can dispatch several document types.** `parse_sources.py` reads only
files approved by the selected KB's inventory and dispatches them to Word,
Excel, PDF, text, or code adapters. Parsers preserve source paths and emit
structure reports for review. Unsupported structures remain visible as review
items; they are not silently treated as extracted facts.

**General knowledge has an explicit mode.** A KB can declare `not-applicable`
when product Scope does not apply, for example multilingual reference material
or a study guide. Code parsing is documented in the v0.8.1 section above.

The v0.7.0 OCR-first extraction, human-initiated updates, semantic domain keys,
and portable Knowledge Base packs remain available. The v0.6 foundations of
incremental inventory, immutable accepted releases, human review, rollback, and
derived query indexes remain in place.

## v0.6.0 foundation

**Scope is configured at the source directory.** Put an `afc-scope.md` in a
product folder, with `預設 Scope` and `排除 Scope` sections. The nearest file
applies to each source; a child file replaces its parent's settings. A run may
provide an explicit target Scope. Exclusions remain active unless the run names
an explicit override. `context.xml` (or the compatible YAML map) only maps
company Business Context names to canonical Scope IDs; it does not define
source boundaries.

**Scanning is incremental and membership-aware.** The inventory records source
hashes, Scope metadata hashes, and every selected-root membership. Overlapping
folders keep separate memberships while the same physical file is parsed once.
Unchanged files are omitted from the extraction list by default. Use
`--rescan-unchanged` when the requested behavior or extraction method changes.
Removed files become review candidates only after an explicit complete-boundary
scan; a partial scan records unscanned sources without retiring them.

**Canonical storage is portable JSONL; query speed is derived.** Each accepted
release stores Cards, Evidence, Links, Boxes, Contexts, coverage, source
memberships, and Scope attributions as JSONL. The accepted release pointer and
append-only identity registry live in the Knowledge Base root. SQLite/FTS files
are disposable indexes rebuilt from a selected release, so they can be moved or
regenerated without becoming a second source of truth.

**Updates require a human decision.** Pipeline outputs are staged as object-level
proposals. Each proposal must be accepted, rejected, or deferred before a release
can be published. Published releases are retained; `rollback` changes the
current pointer without deleting history. During v0.5 import, consistent legacy
Scope values are retained as accepted attributions; conflicting values are
marked `Needs Review`. If the original ID registry is missing, the importer
reconstructs bindings from the accepted master and records which historical
identity data could not be recovered.

See `MIGRATION.md` for the v0.5.0 import and upgrade workflow. OpenSpec project
specification management is intentionally outside this runtime release.

## What this is, and what it is not

This turns specification documents into a **normalized fact base with a faceted
index and a query planner**. That is what it is good at: a PM or SA can ask what
a rule says, what the source literally displayed, or what the original component
type was, and get a traceable answer.

It is sometimes described as a card-box or Zettelkasten system. The resemblance
is limited and worth being clear about, because the metaphor sets the wrong
expectations:

- Links here are generated from a single source document and are required to be
  evidence-backed, with `Direct Source` preferred. They re-express structure the
  document already had. They are not the accumulated, human-authored links that
  make a Zettelkasten generative.
- There is no note sequence, no entry/index note, no discipline of rewriting in
  your own words, and no accumulation over time.
- The largest investment, the Box Graph, is faceted classification — which is the
  part Luhmann deliberately avoided.

So: expect a reliable, traceable, queryable fact base. Do not expect emergent
insight, and do not add structure merely because the metaphor suggests it.

## v0.5.0 — what changed and why

This release fixes defects where the documentation described a guarantee the code
did not provide. Each item has a regression test in `tests/`.

**Chinese retrieval was broken.** `tokenize()` emitted an unbroken CJK run of
four characters or fewer as a single token, and the FTS expression matched exact
terms only. An Evidence Record reading 「加買失敗」 could not be retrieved by a query
for 「加買」 or 「失敗」 — zero results, then a spurious Knowledge Gap Candidate.
Vietnamese and English were unaffected, so the failure was invisible to anyone
testing in a space-delimited language. Both sides now emit overlapping 2-gram and
3-gram terms, `tokenize()` is versioned, and `ensure_query_index.py` rebuilds a
stale index. A golden fingerprint test ties the tokenizer's behaviour to its
declared version.

**`SOURCE_PARSING_GAP` could not detect what it claimed to.** The parser
incremented its `discovered` and `extracted` counters on the same line for
tables, nested tables and text boxes, so those could never disagree. The only
structure that could diverge was a blank paragraph — so the gate fired on
essentially every real DOCX while being structurally unable to notice a missed
table or shape, and reported `PASS` for content no parser reads at all.
`discovered` now comes from a separate pass over the OOXML package, blank
paragraphs are excluded, and unreadable content (header/footer text, footnotes,
endnotes, reviewer comments, charts, SmartArt, OLE objects, equations, scanned
PDF pages, uncached Excel formula cells) is reported as
`SOURCE_UNSUPPORTED_STRUCTURE` instead of passing silently. A parser that should
have run but produced no report is itself a gap.

**Card and Evidence IDs were not stable.** Only the ID *format* was validated;
the numbering was left to the model, while Card delta, rerun novelty,
`afc-curate`'s "never renumber" rule and every Gold baseline assumed stability.
IDs now come from a content-derived identity kept in `work/id-registry.jsonl`.
Rewording a Card keeps its ID; a genuinely different claim gets a new one.

**Four of six Loop Gate metrics were self-assessments presented as
measurements.** The saturation, fidelity and atomicity reports were written by
the extracting model about its own work, on a sample it chose, then graded
GREEN/YELLOW/RED. The sample is now drawn by `sample_units.py` from a seed;
`compute_review_metrics.py` accepts verdicts only for exactly the drawn items and
computes the rate itself; and a rate is graded only when the sample is large
enough for the green threshold to be expressible — at n=12 the smallest non-zero
rate is 8.3%, so a 2% green band was meaningless. Otherwise the metric reads
`INSUFFICIENT_SAMPLE` or `UNVERIFIED_SAMPLE` and the run cannot reach `READY`.

**"PM/SA owns the decision" had no gate.** The pipeline was told never to pause
and to treat every review item as non-blocking, so a run always ended "READY WITH
REVIEW ITEMS" and nothing recorded that a person had looked.
`record_decision.py` writes a decision bound to the health report's content hash;
Step 2 is gated on it, and it goes stale when health changes.

**`settings.yaml` was never read.** Every threshold was duplicated across the
YAML, argparse defaults, README, AGENTS.md and the SKILL.md files — five copies
that drifted. Defaults now live once in `afc_card_runtime/config.py`, the YAML
overrides them, and each report states which file its thresholds came from.
Legacy flat keys are migrated automatically.

**13 JSON Schemas were unused.** `jsonschema` was not even a dependency, and the
hand-written validators had drifted from the schemas in both directions.
`validate_schema.py` now validates every artifact, and a file whose kind cannot
be resolved fails rather than being skipped.

**Step 0 signal matching contradicted its own guardrail.** `afc-context` said
never to select a unit merely because it contains generic words such as
`message`, `error` or `code`, while the script matched exactly those against row
content — so `signal_unselected` was non-zero on nearly every run and the REVIEW
flag carried no information. Patterns moved to
`config/knowledge-signals.yaml`, split into terms that may identify a header and
narrow value-shaped terms that may select a content row. The audit now separates
`signal_unselected_within_boundary` (actionable) from
`signal_unselected_outside_boundary` (out of scope, not a finding).

**Excel and PDF ingestion caught up with DOCX.** Merged-cell anchors propagate
across their range, so a merged column header reaches the rows it governs;
displayed values and formulas are captured separately, and a formula with no
cached value is kept and flagged rather than dropped; embedded sheet images are
extracted straight from the package (no Pillow needed, where openpyxl silently
reports none); dates render as displayed rather than as `2024-01-01 00:00:00`;
hidden sheets and rows are flagged; and both parsers emit structure reports so the
audit can detect a gap instead of defaulting to `PASS`.

**Source Unit IDs collided.** They were keyed on the bare filename while
recursion was on by default, so two same-named files in different folders
overwrote each other. They are now path-derived.

**Knowledge lifecycle had nowhere to live.** `afc-validate` asked for current
value, historical value, change records and replacement semantics while the data
model stored none of it. Cards and Evidence now carry `Status` / `Superseded By`
/ `First Seen Run` / `Last Seen Run`, and `record_changes.py` appends
`work/knowledge-change-log.jsonl`, keeping the verbatim previous value.

**The retrieval-regression layer had no runner.** `config/query-cases.yaml`
described expected resolutions that nothing executed.
`run_query_benchmark.py` runs them against the real index and fails on a
regression against the accepted baseline.

**There were no tests.** A package whose selling point is regression validation
had none of its own. `tests/` now covers every defect above; `./afc selftest.py`
runs it, and `afc-validate` runs it first.

**Two path conventions.** SKILL.md used `../../scripts/` while README used
`scripts/`, nothing said which directory to run from, and the installer rewrote
every SKILL.md to patch the difference. There is now one convention: the `afc`
launcher.

See `MIGRATION.md` before pointing v0.5.0 at an existing knowledge base.

## How to run anything

```bash
./afc --help      # usage
./afc --home      # where the runtime lives
./afc --list      # available scripts
./afc selftest.py # package self-test
```

The launcher finds the runtime, makes any existing input path absolute, then runs
from inside the runtime — so `work/`, `output/`, `config/` and `input/` always
mean the same directories whether you are in the development tree or an installed
repo.

## Model

```text
Source Documents
      ↓  structure ingestion + audit
Structural Context
      ↓
Source-preserving Evidence Records
      ↓  Business Context → Scope resolution
Atomic Cards  ──→ stable IDs (configured registry; persistent in v0.6)
      ↓
Card↔Box Membership ──→ Box Graph ──┐
      ↓                              ├──→ Query Router
Card Graph ────────────────────────┘
```

The separations that matter:

| Term | Meaning |
| --- | --- |
| Context | where source knowledge appears |
| Business Context | company-approved high-level term, e.g. `車險` |
| Scope | the authoritative applicability boundary, e.g. `CA`, `CB` |
| Evidence Record | original source-native text/value/structured fact |
| Card | normalized atomic knowledge |
| Box | reusable knowledge/context boundary and navigation node |
| Card Link | knowledge-to-knowledge relationship |
| Box Link | context/topology relationship |

`車險 -> [CA, CB]` resolves a query. It never rewrites a Card whose Product
Context is `CA`.

## Boxes are not folders

A Card exists once and holds several memberships:

```text
CARD-000188  Back -> return and preserve entered values
  Business Box  CA
  Scenario Box  New Business Application
  Function Box  Navigation / Back
  Screen Box    Confirmation Page
```

Box-to-Box relations are graph edges: `parent_of`, `part_of`, `related_to`,
`depends_on`, `precedes`, `uses_function`, `shared_with`. Hierarchy is one
relation type among them.

Retrieval distinguishes exactly two cases: hierarchy (`parent_of`/`part_of`)
builds a transitive closure so a parent-Box query admits descendants, and the
other five are one set of soft navigation edges expanded at most one hop. Choose
among those five for human clarity; do not expect retrieval to weight them
differently.

## Query model

```text
Query
→ Business Context Resolver
→ Scope Resolver
→ Seed Box Resolver
→ Hard Box Boundary
→ Intent / Target-Mode Router
→ Field / Card / Evidence retrieval
→ Evidence Sufficiency → bounded recovery
→ optional Box 1-hop → optional Card Link 1-hop
→ answer
```

`CA 確認頁 Back 的行為是什麼？` resolves to Scope `CA`, Boxes
`Confirmation Page ∩ Back`, intent `knowledge`, Card 0-hop inside the boundary.
`投保流程用了哪些功能？` uses Box topology one hop through `uses_function`.
`哪些規則會控制生效日期？` uses Card Link one hop through
`controls`/`applies_to`/`depends_on`. The two graphs are not expanded together
unless the question needs both.

A question naming a source language (「越文錯誤訊息」) makes Evidence retrieval
prefer that language, and the recovery stage actually used is reported.

## Skills

| Skill | Step | Responsibility |
| --- | --- | --- |
| `afc-context` | 0 | structure ingestion/audit, Business Context/Scope, knowledge-signal selection |
| `afc-cards` | 1 | Evidence Records, Atomic Cards, stable IDs, coverage ledger, measured health |
| `afc-links` | 2 | evidence-backed Card Links and Concept Cards |
| `afc-boxes` | 3 | Box nodes, Card memberships, Box graph |
| `afc-curate` | 4 | governed Card master, lifecycle, change log |
| `afc-publish` | 5 | publish and reopen-validate the datasets |
| `afc-query` | 6 | topology-aware hybrid retrieval |
| `afc-domains` | — | govern semantic subtopics within a KB |
| `afc-discuss` | — | investigate and record gaps/conflicts before an update |
| `afc-update` | — | turn a completed discussion into reviewed release proposals |
| `afc-share` | — | portable accepted Knowledge Base packs |
| `afc-workspace` | — | route multiple source folders and Knowledge Bases by KB ID |
| `afc-validate` | — | read-only QA, self-test, Gold regression (not a step) |
| `afc-pipeline` | — | orchestration, gates and the final report |

## Common commands

```bash
# Step 0 — ingest and audit the source structure
./afc parse_word.py input -o work/step-card-0-word-source-units.jsonl \
  --structure-report work/step-card-0-word-structure-report.json --media-dir work/source-media
# --source-map is repeatable: name what the parsers wrote. The merged
# step-card-0-source-map.jsonl does not exist until build_context_candidates.py.
./afc audit_source_structure.py --source-map work/step-card-0-word-source-units.jsonl \
  --structure-report work/step-card-0-word-structure-report.json \
  --expect-parsers parse_word.py --json-output work/step-card-0-source-structure-audit.json

# Step 1 — batch a large source, extract, merge, then allocate IDs once
./afc plan_extraction_batches.py --source-map work/step-card-0-source-map.jsonl \
  --run-id "$RUN" -o work/step-card-1-extraction-plan.json
./afc merge_extraction_batches.py --cards work/step-card-1-cards.*.jsonl \
  --evidence work/step-card-1-evidence.*.jsonl --coverage work/step-card-1-coverage.*.jsonl \
  --plan work/step-card-1-extraction-plan.json

# Step 1 — stable IDs, then a measured health report
./afc allocate_ids.py --cards work/step-card-1-cards.jsonl \
  --evidence work/step-card-1-evidence.jsonl --run-id "$RUN"
./afc sample_units.py --purpose saturation --source-map work/step-card-0-source-map.jsonl \
  -n 40 --run-id "$RUN" -o work/step-card-1-saturation-sample.json \
  --verdict-template work/step-card-1-saturation-verdicts.jsonl
./afc compute_review_metrics.py --sample work/step-card-1-saturation-sample.json \
  --verdicts work/step-card-1-saturation-verdicts.jsonl -o work/step-card-1-saturation-report.json
./afc evaluate_card_health.py --source-map work/step-card-0-source-map.jsonl \
  --coverage work/step-card-1-coverage.jsonl --cards work/step-card-1-cards.jsonl \
  --evidence work/step-card-1-evidence.jsonl \
  --saturation-report work/step-card-1-saturation-report.json \
  --json-output work/step-card-1-health.json

# Step 1 → 2 gate
./afc record_decision.py verify --health work/step-card-1-health.json \
  --decision work/step-card-1-decision.json

# Step 3 — validate the Box graph
./afc validate_boxes.py --boxes work/step-card-3-boxes.jsonl \
  --memberships work/step-card-3-box-memberships.jsonl \
  --box-links work/step-card-3-box-links.jsonl \
  --cards work/step-card-1-reconciled-cards.jsonl \
  --json-output work/step-card-3-box-audit.json

# Step 6 — build/reuse the index and query
./afc ensure_query_index.py --cards output/knowledge_card_master.jsonl \
  --evidence output/knowledge_evidence.jsonl --links output/knowledge_links.jsonl \
  --context-map config/business-contexts.yaml --boxes output/knowledge_boxes.jsonl \
  --box-memberships output/knowledge_box_memberships.jsonl \
  --box-links output/knowledge_box_links.jsonl --db work/query-index/afc-query.db
./afc query_fast.py --db work/query-index/afc-query.db --query 'CA 確認頁 Back 的行為是什麼？'

# QA
./afc selftest.py
./afc validate_schema.py --all
./afc run_query_benchmark.py --db work/query-index/afc-query.db \
  --cases config/query-cases.yaml -o work/query-runs/benchmark.json \
  --baseline work/query-runs/baseline.json
./afc check_pipeline_artifacts.py
```

## Configuration

All of these are read at runtime; nothing here is decorative.

| File | Holds |
| --- | --- |
| `config/settings.yaml` | paths, retrieval limits, health thresholds, the decision gate |
| `config/company-context.md` | company terminology for enrichment |
| `config/business-contexts.yaml` | approved Business Context → Scope map |
| `config/box-taxonomy.yaml` | company-approved seed Boxes and relations |
| `config/knowledge-signals.yaml` | Step 0 signal patterns and languages |
| `config/query-terms.yaml` | question vocabulary, language hints |
| `config/query-cases.example.yaml` | executable retrieval benchmark cases |
| `config/context.xml.example` | mapping-only Business Context → Scope example |
| `templates/afc-scope.md` | directory-local default and excluded Scope template |

Retrieval defaults: general knowledge → Card 0-hop; plain Field lookup → Field
index; context-specific Field lookup → Box-filtered Card Type = Field; Box
relationship → Box topology ≤ 1 hop; Card relationship → Card Link ≤ 1 hop. Scope
is always authoritative over Box topology. The numbers themselves
(`candidate_k`, `top_k`, `evidence_k`, hop caps) live in `settings.yaml` and are
echoed in every query result with their source.

Do not add vector search until topology-aware hybrid retrieval has been
benchmarked with `run_query_benchmark.py`.

## Persistent Knowledge Base lifecycle

Initialize a Knowledge Base outside the runtime, for example one per product:

```bash
./afc knowledge_base.py init --kb-root ../knowledge/cproduct \
  --kb-id cproduct --name "C Product"
```

Put an `afc-scope.md` in the product source directory. Then inventory the exact
source root and the behavior being extracted:

```bash
./afc knowledge_base.py inventory \
  --kb-root ../knowledge/cproduct --source ../products/cproduct \
  --behavior "passenger insurance add-on rules" --run-id cproduct-20261012-01
```

Use `runs/<run-id>/candidate/eligible-source-paths.json` as the extraction input
list. Inventory stores a separate membership for each overlapping source root;
unchanged files are skipped unless `--rescan-unchanged` is supplied. Only use
`--complete-boundary` for a scan covering the entire selected source boundary.

Set `AFC_KB_ROOT` during extraction so ID allocation uses the persistent,
append-only registry. After pipeline outputs are ready, stage and review them:

```bash
export AFC_KB_ROOT="$PWD/knowledge/cproduct"
./afc knowledge_base.py stage --kb-root ../knowledge/cproduct \
  --run-id cproduct-20261012-01 \
  --health-report work/step-card-1-health.json
# Review proposals.jsonl and record accept/reject/defer for every proposal.
./afc knowledge_base.py publish --kb-root ../knowledge/cproduct \
  --run-id cproduct-20261012-01
./afc knowledge_base.py index --kb-root ../knowledge/cproduct
./afc knowledge_base.py query --kb-root ../knowledge/cproduct \
  --query '乘客險什麼時候可加買？'
```

Each accepted release is canonical JSONL. SQLite/FTS is a rebuildable query
index. See `MIGRATION.md` for import from v0.5, review decisions, integrity
validation, and rollback.

## Install

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt     # to run ./afc selftest.py
bash install.sh /path/to/your-repo --target both
bash verify_install.sh /path/to/your-repo --target both
```

`--target codex` installs into `.codex/skills` and `.agents/skills` with the
rules section in `AGENTS.md`; `--target claude` installs into `.claude/skills`
with the rules section in `CLAUDE.md`; `both` is the default. The skills,
scripts, config and rules template are the same files either way — the target
only decides where they land, and `verify_install.sh` fails if two installed
copies differ. `install_codex.sh` and `install_claude.sh` are one-line wrappers
for the two single-target cases.

The installer updates the runtime code and every skill while preserving existing
input, output, work, and user configuration. New defaults land beside existing
configuration as versioned examples. Start a new session from inside the repo. The installer does not migrate or publish Knowledge Base data; use `OPERATIONS.md`
to register existing stores and `MIGRATION.md` for version upgrade details.

## Run all seven steps in one instruction

```text
Use afc-pipeline to run AFC Step 0 through Step 6 end-to-end.
Business Context: 車險
Source: use all files under the configured input path.
Do not pause for confirmation between normal steps.
Do not auto-loop Context or Cards; report the health metrics with their sample
grades and stop at the decision gate if one is owed.
At Step 6, build/reuse the query index and report Query Readiness.
Finally run quick afc-validate and give me the complete pipeline report.
```

`RUN_ALL.md` has variants, including one with an explicit final query.
