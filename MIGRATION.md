# Upgrade and operate AFC v9.1

## v9.1 breaking changes — read before upgrading

Five changes alter behaviour that an existing script or habit may rely on. None
touch accepted Knowledge Base data; all of them turn something that used to pass
silently into something that stops and says why.

**1. `afc-publish` no longer publishes.** Step 5 writes the candidate datasets
and stages them so a reviewer has proposals; recording the per-proposal
decisions and advancing the release pointer is `afc-update`. Its own text always
said it did not accept knowledge into the Knowledge Base, while its commands
published — the scope check now makes that contradiction impossible. **If an
automation runs `knowledge_base.py publish` as part of Step 5, move that step to
`afc-update`.**

**2. Skill scope is enforced.** `config/skill-scopes.yaml` declares, per skill,
the scripts it may run and the strongest change it may cause. With `AFC_SKILL`
set to the skill being followed, the launcher refuses anything outside that
scope and exits 3. With `AFC_SKILL` unset nothing is checked, so existing
operator scripts keep working unchanged. Set it when an agent follows a skill;
leave it unset for direct commands.

**3. `knowledge_base.py` rejects unknown flags.** It used `parse_known_args` for
every subcommand, so a mistyped flag was silently ignored — including
`--accept-quality-risk-by` and `--rebuild`, where being ignored looked like
success. Only `query` still forwards its remaining arguments, to `query_fast.py`.
**Check any wrapper script for flag typos before upgrading: what used to be
ignored is now an error.**

**4. The launcher no longer rewrites an option value that is not a path.** `afc`
absolutises arguments that name an existing path so they survive its `cd` into
the runtime. "Exists in the current directory" turned out to be too weak a test:
run from a directory holding a product folder named `CA`, `--target-scope CA`
became `/abs/path/CA` and was recorded as the run's Scope. An option's value is
now treated as a path only when it looks like one or is an existing file;
positional arguments may still be bare directory names, so `parse_word.py input`
is unchanged.

**5. A missing source map is a gap, not an empty audit.**
`audit_source_structure.py --source-map` is now repeatable, takes one parser
output per flag, and reports a named file that does not exist as
`SOURCE_PARSING_GAP`. It previously read `[]` for a mistyped path and could pass
with zero units. `extract_ocr.py --source-map` is repeatable too.

### Also new in v9.1

- `install.sh --target codex|claude|both` installs for Codex, Claude Code, or
  both from one source. `install_codex.sh` and `install_claude.sh` are wrappers;
  `verify_install.sh` replaces `verify_codex_install.sh` and takes the same
  `--target`. The rules section now lands in `AGENTS.md` and `CLAUDE.md` at the
  repo root — the old location inside the runtime directory was never loaded by
  any harness, so an installed repo ran with no AFC rules at all.
- Step 1 can be batched and resumed: `plan_extraction_batches.py` plans, each
  batch is written separately, `merge_extraction_batches.py` rejoins them and
  refuses a half-merge. Batch size comes from `extraction.max_units_per_batch`.
- `validate_schema.py --draft` reports an unallocated placeholder ID as a
  placeholder instead of an error, so a batch can be checked before
  `allocate_ids.py` runs. Never use it to sign off Step 1.
- `knowledge_base.py decide --decisions-file` records a reviewed set of
  proposals in one atomic write instead of one process per proposal.
- `config/skill-scopes.yaml` is package structure, not configuration: an upgrade
  replaces it, like `schemas/`. Your `settings.yaml`, company context, taxonomy
  and query terms are still preserved.
- The runtime version is read from `VERSION`. Releases created before this
  upgrade recorded `runtime_version` from a literal in the code and may name an
  older version than the package that wrote them; this is a recording defect in
  those manifests, not a reason to republish.

### Upgrade sequence

```bash
bash install.sh /path/to/project --target both
bash verify_install.sh /path/to/project --target both
./afc selftest.py
```

Then, in that order: fix any wrapper that publishes from Step 5; run your
wrappers once and look for `unrecognized arguments`; re-run the Step 0 audit
naming each parser output explicitly.

## v0.8.6 workflow changes

The article PDF profile carries its document and section context across page
breaks and treats numbered sibling headings as siblings. Coverage reports now
group accounting by section. The fast PDF profile and persistent KB data remain
unchanged. Re-run article-mode parsing and Card extraction for sources whose
old section paths chained sibling headings incorrectly; do not regenerate or
publish Cards without reviewing the updated boundaries.

## v0.8.5 workflow changes

The default PDF parser remains on its fast legacy path. For article or study-guide
PDFs, use `parse_pdf.py --profile article` (or `parse_sources.py
--pdf-profile article`) to add layout text, heading context, and embedded-image
Source Units. Install the optional OCR requirements to extract PDF images and
run the existing local OCR path. When the extraction method changes, rescan the
same source boundary with `--rescan-unchanged`.

Persistent staging now requires the exact current Card health report. Publish
blocks if it is not `READY`; allowing diagnostic continuation through Links does
not approve Card quality. A separate reviewer and rationale are required to
accept release despite non-READY metrics. Existing accepted releases are not
rewritten by this upgrade.
If a v0.8.4 run is already staged and awaiting review, restage it with the
current health report before publishing; prior proposal decisions do not count
as Card quality acceptance.

## v0.8.4 workflow changes

Use `afc-discuss` to investigate and save a gap/conflict discussion before asking
`afc-update` to stage release proposals. Discussion records are stored under the
selected KB's `discussions/` directory and are not included in portable release
packs. Existing Semantic Domain Keys remain valid; they classify subtopics
within a KB, while KB ID remains the knowledge-base boundary. Query now asks the
user to resolve an ambiguity when the choice of KB, Scope, Box, or subtopic could
change the answer.

## Upgrade from v0.8.2

Install v0.8.6 using the commands below. The accepted Knowledge Bases and
workspace catalog remain in place. The first query against a v0.8.2 Knowledge
Base automatically rebuilds its derived query index with lifecycle filtering.
Custom indexes must be rebuilt before use.
If a v0.8.2 run is still awaiting review, restage it and record the decisions
again; the new publisher requires each decision to match the exact proposal
content that was reviewed.

## Upgrade from v0.8.1

Install v0.8.6 with Python 3.10 or newer. The accepted Knowledge Bases and workspace catalog remain in place.

```bash
export AFC_PYTHON="$(command -v python3.10)"
bash install.sh /path/to/your/project
"$AFC_PYTHON" -m pip install -r /path/to/your/project/.afc-card-experiment/requirements.txt
bash verify_install.sh /path/to/your/project
```

## Upgrade from v0.8.0

Install the v0.8.6 package into the project that contains the AFC launcher. It includes the Python runtime floor and the v0.8.1 code parser expansion.

The update preserves the installed workspace catalog and accepted Knowledge
Base data. All AFC commands now require Python 3.10 or newer. Set `AFC_PYTHON` to
the runtime interpreter and use it to install `requirements.txt`. The code parser
remains optional. To enable Java, Dart/Flutter,
JavaScript/TypeScript (including Ionic), PHP, HTML templates, Vue SFC, and CSS/SCSS structure,
install the optional parser package and prepare the local grammar cache:

```bash
export AFC_PYTHON="$(command -v python3.10)"
"$AFC_PYTHON" -m pip install -r "$(./afc --home)/requirements.txt"
"$AFC_PYTHON" -m pip install -r "$(./afc --home)/requirements-code.txt"
./afc prepare_code_parser.py
```

The first preparation needs network access to download the selected grammars.
Later scans use the local cache. The code parser is static and does not execute
the project. Python sources continue to use the AFC runtime's standard-library
AST parser; all AFC commands now require Python 3.10+.

After changing from a text-only code scan to structural parsing, run an
incremental inventory for the same KB ID with `--rescan-unchanged`, review the
new structure report, then use the ordinary AFC update and human publication
workflow. Existing accepted releases remain unchanged until reviewed proposals
are explicitly published.

## Upgrade from v0.7.0

Install v0.8.6 with the installation commands above. It preserves the existing
runtime configuration and accepted Knowledge Bases. Initialize `afc-workspace.json`
then register each existing KB root and its source folders using
`workspace.py register`; do not create a new KB root for an existing store.
Choose `product` or `not-applicable` to match the field. Follow `OPERATIONS.md`
for scanning, querying, code parser setup, and migration of source folders.

## Upgrade from v0.6.0

Existing v0.6 accepted releases remain readable. Validate them, rebuild the query
index with v0.7, then run an ordinary reviewed update to add the new empty or
populated `knowledge_domains.jsonl` dataset. Domain keys are introduced through
human review; they are not automatically inferred into the accepted release.

## Move an accepted Knowledge Base to another computer

Export a validated release snapshot:

```bash
./afc knowledge_pack.py export \
  --kb-root ../knowledge/cproduct \
  --output ./dist/cproduct.afc-kb.zip
```

The default pack includes accepted releases, `CURRENT.json`, the identity
registry, histories, hash manifest, and configured Business Context, query-term,
and Box taxonomy maps. It omits working runs and disposable indexes. Install the
matching runtime and skills on the destination, then import and rebuild its local index:

```bash
./afc knowledge_pack.py import \
  --archive ./cproduct.afc-kb.zip \
  --kb-root ./knowledge/cproduct
./afc knowledge_base.py validate --kb-root ./knowledge/cproduct
./afc knowledge_base.py index --kb-root ./knowledge/cproduct
```

Set `AFC_KB_ROOT` to the recipient's local path before invoking `afc-query`.
Evidence text travels in the pack; original source documents do not. Share them
separately if recipients need to open original files, and review the package for
confidential information before distribution.

## v0.5.0 to v0.6.0 migration

v0.6.0 extends the v0.5.0 runtime and its nine AFC skills. Keep the current
v0.5.0 Knowledge Base intact until the v0.6 import has been validated. The
installer updates runtime code and skills; it does not move source documents or
publish a Knowledge Base release.

## 1. Install the runtime and skills

From the v0.6.0 package directory:

```bash
pip install -r requirements.txt
bash install.sh /path/to/your/project
bash verify_install.sh /path/to/your/project
```

The installer keeps the project's existing `settings.yaml`, company context,
Business Context map, Box taxonomy, and query configuration. It puts the v0.6.0
defaults beside existing configuration as versioned examples. Review the new
`settings.v0.6.0.example.yaml` before changing local settings. In particular,
replace legacy `exclude_scope` display names with canonical Scope IDs under
`excluded_scopes`; v0.6.0 deliberately ignores the old key.

## 2. Create an independent persistent Knowledge Base

Choose a Knowledge Base directory outside the runtime, for example
`/path/to/your/project/knowledge/cproduct`:

```bash
cd /path/to/your/project
./afc knowledge_base.py init \
  --kb-root ../knowledge/cproduct --kb-id cproduct --name "C Product"
```

The Knowledge Base directory contains `identity/`, `releases/`, `runs/`,
`history/`, and `indexes/`. It is separate from runtime `work/` and `output/` so
upgrading the runtime does not replace accepted knowledge. Use one KB root per
maintained product/domain boundary; overlapping source folders can still be
recorded as separate source memberships.

## 3. Import the v0.5.0 accepted baseline

The import preserves the v0.5 Card/Evidence IDs. Review the source `output/`
datasets and, if present, `work/id-registry.jsonl` first; record who accepted
the baseline and why:

```bash
./afc knowledge_base.py migrate-v05 \
  --v05-root .afc-card-experiment \
  --kb-root ../knowledge/cproduct --kb-id cproduct \
  --accept-baseline \
  --accepted-by "Your Name" \
  --rationale "Reviewed the v0.5.0 product knowledge baseline"
```

If the original registry exists, the importer verifies every imported Card and
Evidence ID against it. If it is missing, the importer reconstructs current
bindings from the accepted Card/Evidence master, preserves those IDs, and
reserves the highest ID numbers observed in available output/work JSONL so the
allocator will not reuse them. The release manifest records this recovery and
its limitation: prior identity history and deleted IDs absent from every
available artifact cannot be recovered. Keep a backup of the v0.5 directory.

Optional fields whose v0.5 values are `null` but whose v0.6 schema permits only
a concrete type are omitted during import and listed in the release manifest's
`migration_normalization` report. Required null fields still fail validation.

Conflicting legacy Card Scope fields are marked `Needs Review`. Non-conflicting
legacy Scope values are preserved as explicit `Legacy Card Scope` attributions
and treated as part of the accepted baseline. The source catalog starts empty:
v0.5.0 did not keep complete source hashes or membership records, so the first
v0.6.0 inventory establishes that baseline without claiming historical
additions or removals.

The import validates schemas, cross-references, and ID bindings before moving
the current release pointer. If validation fails, correct or curate the v0.5
source data before retrying the import. If the registry is absent, reconstruction
is the only safe path to preserve IDs visible in the v0.5 artifacts; it cannot
restore history that was never shipped.

## 4. Add directory-local Scope boundaries

Copy `templates/afc-scope.md` into each product source directory and replace the
example with canonical Scope IDs:

```markdown
## 預設 Scope
- `CA` — C Product

## 排除 Scope
- `CB`
```

The closest `afc-scope.md` applies to a source file. A child file replaces its
parent's defaults and exclusions. `無。` means an empty section. A prompt's
explicit target Scope takes precedence over a directory default; an exclusion
still blocks it unless that same run explicitly overrides the excluded Scope.

Keep `config/business-contexts.yaml` or supply a mapping-only XML file through
`--context-map`. These maps define company-approved Business Context → Scope
aliases only. They do not define source folders or exclusions.

## 5. Inventory and extract incrementally

```bash
./afc knowledge_base.py inventory \
  --kb-root ../knowledge/cproduct \
  --source ../products/cproduct \
  --behavior "passenger insurance add-on rules" \
  --run-id cproduct-20261012-01
```

Read `knowledge/cproduct/runs/<run-id>/inventory-report.json` and
`candidate/eligible-source-paths.json`. Parse and extract the listed paths for
this run; unchanged files are omitted. If the requested behavior or extraction
logic changes while the source files have not, add `--rescan-unchanged`. If you
selected only part of the source tree, do not pass `--complete-boundary`. Use
that option only when the selected roots cover the full inventory boundary;
then missing memberships become `Removed Candidate`, which still needs human
review.

When running the extraction pipeline, set `AFC_KB_ROOT` so stable IDs continue
from the persistent registry:

```bash
export AFC_KB_ROOT="$PWD/knowledge/cproduct"
```

Pass the same explicit Scope/source boundary to Step 0, for example:

```bash
./afc build_context_candidates.py work/step-card-0-word-source-units.jsonl \
  --target-scope CA --scope-root path/to/product/cproduct \
  -o work/step-card-0-source-map.jsonl --report work/step-card-0-report.json
```

## 6. Review and publish changes

After Step 5 has written the candidate datasets under `output/`, stage them
against the current accepted release:

```bash
./afc knowledge_base.py stage \
  --kb-root ../knowledge/cproduct --run-id cproduct-20261012-01
```

Review `runs/<run-id>/proposals.jsonl`. Record one decision for every proposal
with `knowledge_base.py decide`; use `accept`, `reject`, or `defer`, and include
a reviewer and rationale. For a large set, record the reviewed decisions as one
JSONL file and pass `--decisions-file`; all rows are validated before any is
written. Only accepted proposals enter the next release.
Deferred/rejected proposals leave the current values in place. Publish after
every proposal has an explicit decision:

```bash
./afc knowledge_base.py publish \
  --kb-root ../knowledge/cproduct --run-id cproduct-20261012-01
./afc knowledge_base.py validate --kb-root ../knowledge/cproduct
./afc knowledge_base.py index --kb-root ../knowledge/cproduct
```

Query the accepted release through its derived SQLite/FTS index:

```bash
./afc knowledge_base.py query --kb-root ../knowledge/cproduct \
  --query "乘客險什麼時候可加買？"
```

The index is disposable and is rebuilt from canonical JSONL when needed. To
restore a previous accepted release, use `knowledge_base.py rollback` with a
reviewer and rationale. Releases and the review/change history remain available:

```bash
./afc knowledge_base.py rollback --kb-root ../knowledge/cproduct \
  --release-id release-000001 --reviewer "Your Name" \
  --rationale "Restore the last accepted product baseline"
```

## What stays in v0.5.0

The original `.afc-card-experiment` `input/`, `output/`, and `work/` directories
are preserved by the installer. The v0.6 import copies the accepted JSONL data
and ID registry into the separate Knowledge Base; it does not delete v0.5 files.
OpenSpec project specification management remains deferred.
