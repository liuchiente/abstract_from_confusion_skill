---
name: afc-domains
description: Propose and govern readable semantic subtopic keys (for example motor.passenger_coverage) inside one Knowledge Base, to improve organization and retrieval. Use for 主題分類/子主題/領域鍵/domain key. A Domain Key is not a KB ID, a Scope or a Box, and never widens either; the KB ID stays the knowledge-base boundary. Publishing the registry is afc-update.
allowed-tools: Bash, Read, Write, Glob, Grep
---

# AFC Semantic Subtopics within a Knowledge Base

A Knowledge Base ID selects one coherent knowledge field. A Semantic Domain Key
classifies a topic inside that KB, for example `motor.passenger_coverage` or
`motor.vehicle_eligibility` within an auto-insurance KB. It is not another KB ID,
and it never expands the query beyond the selected KB.

Manage `knowledge_domains.jsonl` as a canonical dataset inside each accepted
release. Read the current registry before proposing anything, and write
candidates to `output/knowledge_domains.jsonl`; the ordinary staging and release
review makes them versioned and portable.

## Read the current registry

```bash
./afc knowledge_base.py validate --kb-root "$AFC_KB_ROOT"      # release integrity first
```

The accepted release is whatever `$AFC_KB_ROOT/CURRENT.json` points at; its
registry is `$AFC_KB_ROOT/releases/<release-id>/knowledge_domains.jsonl`. Read
that file, and never edit it: a release directory is immutable. With a workspace
catalog, resolve the KB first with `workspace.py list` and
`workspace.py query --kb-id <id>`.

## Write and check candidates

Copy the accepted registry to `output/knowledge_domains.jsonl` and add or amend
rows there. For a first release, start from an empty file. Then check the shape
before anything stages it:

```bash
./afc validate_schema.py output/knowledge_domains.jsonl
```

Staging, the per-proposal decisions and the publish belong to `afc-update`: this
skill proposes, and a candidate key is not an approved one.

## Domain key rules

- A `Domain Key` is a stable, readable semantic identifier such as
  `motor.passenger_coverage`; it is not a Card ID, Business Context, Scope, or Box.
- Generate a key proposal from the domain's meaning, not from one document title.
  Check existing labels and aliases for duplicates before proposing a new key.
- Keep keys stable when wording changes. Change the canonical label or add an
  alias instead. Deprecate a key only when the concept itself is retired or
  deliberately replaced; retain `Superseded By` when applicable.
- A Card may carry several `Semantic Domain Keys` when evidence supports genuine
  cross-topic use. Do not use a domain tag to widen product Scope or cross a KB
  boundary.
- Domain hierarchy is optional navigation. Prefer a small, useful set of domains
  over a tag for every Card.

## Human approval

When a collection or update needs new domain keys, propose them with the key,
canonical label, aliases, parent keys, reason, and representative source-backed
Cards. The human approves, revises, or rejects the proposal. Only approved
domains receive `Active` status and enter `output/knowledge_domains.jsonl` for
the normal staging and release review. Candidate keys must not be assigned to
accepted Cards.

Assign Cards only to existing Active or Deprecated keys, preserve existing tags
unless evidence or the user requests a change, and copy canonical display labels
from the registry into `Semantic Domain Labels` for search. The query index
adds registry labels and aliases to Card search text. Domain labels help resolve
subtopic wording but are not hard retrieval boundaries; KB ID, Scope and explicit
Box boundaries remain authoritative.

## Report

Report proposed, accepted, deprecated, and rejected keys; Cards whose tags
changed; duplicate or ambiguous labels; and any Scope boundary that needed human
resolution. Do not silently rename a key or relabel a Card to improve retrieval.

<!-- afc:scope:begin -->
<!-- Generated from config/skill-scopes.yaml by scripts/sync_skill_metadata.py.
     Edit the manifest, not this block: the `afc` launcher enforces the
     manifest, so a hand-edited copy here would only disagree with it. -->

## Scope

This skill may cause **work** changes. Set
`AFC_SKILL=afc-domains` while following it: the `afc` launcher then refuses any
command outside the scope below and names the skill that owns it.

Commands this skill may run:

- `knowledge_base.py` — only `query, validate`
- `validate_schema.py`
- `workspace.py` — only `query, list`

Not this skill's job:

- assigning a candidate domain key to an accepted Card → the user
- publishing the domain registry → `afc-update`
- using a domain tag to widen Scope or cross a KB boundary → the user

`./afc --scope afc-domains` prints this boundary.
<!-- afc:scope:end -->
