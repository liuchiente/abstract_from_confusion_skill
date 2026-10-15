# Abstract From Confusion Skill Collection

Version **0.8.4** of the AFC (Abstract From Confusion) Codex skill collection.

This repository contains the 14 skill instruction folders under [`skills/`](skills/).
It does not contain the AFC Python runtime, parsers, schemas, or command-line
scripts. Install the matching AFC v0.8.4 package when using skills that invoke
the `./afc` launcher or its runtime commands.

## Skills

| Skill | Purpose |
| --- | --- |
| `afc-workspace` | Route source folders and work by Knowledge Base ID. |
| `afc-pipeline` | Orchestrate the full source-to-query-readiness workflow. |
| `afc-context` | Inspect source structure, Scope, and knowledge signals. |
| `afc-cards` | Preserve Evidence and extract atomic Knowledge Cards. |
| `afc-links` | Build evidence-backed relationships between Cards. |
| `afc-boxes` | Build context boundaries and Box relationships. |
| `afc-curate` | Curate the stable Card Master and lifecycle history. |
| `afc-publish` | Validate and export candidate datasets. |
| `afc-query` | Retrieve Cards and source Evidence with boundary checks. |
| `afc-domains` | Govern semantic subtopic keys within a Knowledge Base. |
| `afc-discuss` | Investigate and record a gap or conflict before updating. |
| `afc-update` | Convert a completed discussion into reviewed release proposals. |
| `afc-share` | Export and import portable Knowledge Base release packs. |
| `afc-validate` | Run cross-cutting, read-only quality checks. |

## Installation

For full AFC functionality, install the matching v0.8.4 release package into a
Codex project. The installer places the skills into both `.codex/skills/` and
`.agents/skills/` and installs the runtime separately. See the AFC package's
`OPERATIONS.md` for setup and usage instructions.

The key update workflow is `afc-discuss` → `afc-update`: first collect and review
evidence in a discussion record, then create and decide release proposals.
Knowledge Base ID selects the knowledge boundary; Semantic Domain Keys classify
subtopics within that KB. If a query has multiple plausible interpretations that
could change the answer, `afc-query` asks the user to choose.
