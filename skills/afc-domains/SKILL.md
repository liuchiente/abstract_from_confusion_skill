---
name: afc-domains
description: Propose and govern readable semantic subtopic keys within one AFC Knowledge Base to improve organization and retrieval; KB ID remains the knowledge-base boundary.
---

# AFC Semantic Subtopics within a Knowledge Base

A Knowledge Base ID selects one coherent knowledge field. A Semantic Domain Key
classifies a topic inside that KB, for example `motor.passenger_coverage` or
`motor.vehicle_eligibility` within an auto-insurance KB. It is not another KB ID,
and it never expands the query beyond the selected KB.

Manage `knowledge_domains.jsonl` as a canonical dataset inside each accepted
release. Read `$AFC_KB_ROOT/CURRENT.json`, then inspect the registry in the
pointed-to release before proposing additions or changes. Write candidate
changes to `output/knowledge_domains.jsonl`; the ordinary staging and release
review makes them versioned and portable.

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
