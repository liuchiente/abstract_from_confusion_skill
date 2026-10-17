---
name: afc-share
description: Create, import, validate and query a portable read-only Knowledge Base release pack on another computer. Use for 匯出知識庫/給別台電腦/交付快照/匯入 release pack/portable snapshot. The pack and the AFC runtime are separate deliverables. This skill never edits knowledge on either side of the transfer: a correction goes through afc-discuss and afc-update.
allowed-tools: Bash, Read, Write, Glob, Grep
---

# AFC Knowledge Base Sharing

Use this workflow to hand another computer a published AFC knowledge snapshot.
The Knowledge Base pack and the AFC runtime/skills are separate deliverables:
the pack contains governed knowledge; the runtime provides parsers and query
commands; `afc-query` provides the model's retrieval and answer rules.

## Export a read-only snapshot

Start from a validated accepted release. With a workspace catalog, name the KB
ID to export the selected Knowledge Base:

```bash
./afc workspace.py export --kb-id cproduct \
  --output ./dist/cproduct.afc-kb.zip
```

For a legacy installation without a workspace catalog, the lower-level
`knowledge_pack.py export --kb-root ...` command remains available.

By default, the pack includes all accepted releases, the current pointer, identity
registry, review/change history, integrity manifest, and the configured Business
Context, query-term, and Box taxonomy maps needed for consistent query setup. It omits disposable
query indexes and in-progress runs/proposals. Do not include source files or
working runs unless the recipient needs them and the data owner approves sharing.

Deliver the version-matched AFC runtime and `afc-query` skill installation
instructions alongside the pack. State the package version and current release
ID. Treat Evidence text as knowledge data that may be confidential.

## Import on the recipient computer

Install the matching AFC runtime and skills, then import to a new or empty local
directory. Import rejects unsafe archive paths, checks file hashes, and validates
the current release before placing it:

```bash
./afc knowledge_pack.py import \
  --archive ./cproduct.afc-kb.zip \
  --kb-root ./knowledge/cproduct
./afc knowledge_base.py validate --kb-root ./knowledge/cproduct
./afc knowledge_base.py index --kb-root ./knowledge/cproduct
./afc workspace.py register --kb-id cproduct --name "C Product" \
  --kb-root ./knowledge/cproduct --scope-policy product \
  --source ./product-docs/cproduct
```

Configure `AFC_KB_ROOT` to that local directory for the session, then invoke
`afc-query`. The query always reads the pack's accepted `CURRENT.json` release;
it must not answer from a run candidate. Rebuild the index when the runtime,
index schema, tokenizer or domain registry differs. The index builder automatically
uses the packaged `config/business-contexts.yaml`; the other packaged maps guide
the query skill's intent and Box interpretation.

## Limits to explain to recipients

The pack contains Evidence text and source locations, but does not automatically
copy original Word, Excel or PDF files. Machine-specific absolute source paths may
not exist on the recipient computer. Answers remain traceable to stored Evidence;
opening the original source requires separately shared files or a shared source
location. A read-only pack is a snapshot: send a newly published pack to deliver
later updates. Recipients should submit proposed corrections through
`afc-update`, not edit the snapshot in place.

<!-- afc:scope:begin -->
<!-- Generated from config/skill-scopes.yaml by scripts/sync_skill_metadata.py.
     Edit the manifest, not this block: the `afc` launcher enforces the
     manifest, so a hand-edited copy here would only disagree with it. -->

## Scope

This skill may cause **release** changes. Set
`AFC_SKILL=afc-share` while following it: the `afc` launcher then refuses any
command outside the scope below and names the skill that owns it.

Commands this skill may run:

- `knowledge_base.py`
- `knowledge_pack.py`
- `workspace.py`

Not this skill's job:

- editing knowledge on either side of the transfer → `afc-update`
- packing a release that does not validate → `afc-publish`

`./afc --scope afc-share` prints this boundary.
<!-- afc:scope:end -->
