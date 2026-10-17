# AFC Card Experiment v0.8.4

This release adds a discussion-first knowledge update workflow and makes query
disambiguation explicit.

## What's new

- **`afc-discuss`** investigates a user-raised knowledge gap or conflict,
  compares source evidence, and records the discussion before any accepted
  Knowledge Base data changes.
- **`afc-update`** consumes a discussion marked `Ready for Update`, creates
  release proposals, and publishes only after every proposal has an explicit
  accept, reject, or defer decision.
- **Semantic Domain Keys** classify subtopics inside a Knowledge Base. The KB ID
  remains the knowledge-base boundary. Existing Domain Key data stays compatible.
- **Query disambiguation** asks the user to choose when multiple KBs, Scopes,
  Boxes, or subtopics could lead to materially different answers.
- The operations guide now includes examples for the discussion and update
  handoff.

## Upgrade notes

- Existing Knowledge Base releases and Domain Key registries do not need a data
  migration.
- Discussion records are stored under the selected KB's `discussions/` folder.
  They are working governance records and are not included in portable release
  packs.
- AFC requires Python 3.10 or newer.

## Install

Extract this package, then run from its directory:

```bash
export AFC_PYTHON="$(command -v python3.10)"
bash install_codex.sh /path/to/your/project
"$AFC_PYTHON" -m pip install -r /path/to/your/project/.afc-card-experiment/requirements.txt
bash verify_codex_install.sh /path/to/your/project
```

Start a new Codex session from inside the project after installation. See
`OPERATIONS.md` for setup, ingestion, querying, updates, and portable Knowledge
Base packs.

## Package verification

The release archive's internal checksums and ZIP structure were verified. The
automated test suite was not run for this release preparation.
