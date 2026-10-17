---
name: afc-boxes
description: AFC Step 3: build the Knowledge Box graph — Box nodes as knowledge boundaries, evidence-backed Card-Box memberships, and Box-Box relations of which hierarchy is only one type. Use for 知識邊界/情境/功能/畫面分類/Box 圖/navigation. A Box is not a Scope and never changes one. Not for Card-to-Card relationships — that is afc-links.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# STEP 3 — Knowledge Box Graph

Run commands with the `afc` launcher from the repo root.

Inputs: `work/step-card-1-reconciled-cards.jsonl` when available, otherwise the
current Card master; `work/step-card-0-contexts.jsonl`;
`work/step-card-2-links.jsonl`; `config/business-contexts.yaml`;
`config/box-taxonomy.yaml`; and the original source where needed.

## Core model

A Box is not a folder. Three distinct graph objects:

1. **Box Node** — a reusable knowledge/context boundary.
2. **Card-Box Membership** — why a Card is valid in or associated with that Box.
3. **Box-Box Link** — topology between Boxes, of which hierarchy is one kind.

A Card exists once and may hold several memberships. `CARD-000188`
(*Back / returns and preserves entered values*) can be a member of Business `CA`,
Scenario `New Business Application`, Function `Navigation`, and Screen
`Confirmation Page` — as four memberships, not four copies of the Card.

## Box types

First version: `Business`, `Scenario`, `Function`, `Screen`, `Inbox`.

- Business — Insurance, Motor Insurance, CA, CB, Accident Insurance, Travel Insurance
- Scenario — New Business Application, Underwriting, Confirmation, Search, Renewal
- Function — Payment, Navigation, Upload, Identity Verification, Back
- Screen — Basic Information Page, Confirmation Page, Search Result Page
- Inbox — Unclassified, Needs Context, Conflict

A new source label is not a reason to invent a new Box Type.

## Box identity

Stable identity is `Box Type + Canonical Key`. Preserve existing `BOX-*` IDs
while that identity is unchanged. Different display names or aliases describing
the same boundary are aliases, not new Boxes.

## Card-Box Membership

Membership is first-class data, not a tag array on the Card.

Types: `belongs_to`, `valid_in`, `uses_function`, `defined_in`, `shared_in`.

Each Membership records: Membership ID, Card ID, Box ID, Membership Type,
Membership Basis, Evidence, Source Context IDs where available, Confidence,
Status. Evidence is required for a confirmed source-derived membership.

A company taxonomy may supply a Business membership, but it must not rewrite the
Card's source/product Scope.

## Box-Box topology

Relation Types: `parent_of`, `part_of`, `related_to`, `depends_on`, `precedes`,
`uses_function`, `shared_with`.

```text
Motor Insurance --parent_of--> CA
CA --part_of--> Motor Insurance
Application Flow --uses_function--> Payment
Confirmation --precedes--> Submit
Payment --shared_with--> Motor Insurance
```

Semantic similarity between two Box names is not a relation. A confirmed Box Link
needs traceable evidence from source structure, source text, the company-approved
taxonomy, consistent cross-Card evidence, or explicit manual configuration.

### What retrieval actually does with these

Be honest about this when deciding how much topology to build:

- **Hierarchy (`parent_of` / `part_of`)** is special-cased. It builds a
  transitive closure, so a query naming a parent Box also admits its
  descendants.
- **The other five relations are treated as one set** of non-hierarchical,
  soft navigation edges, expanded at most one hop and only when query intent
  calls for it. `query-terms.yaml` maps question wording to a relation, so
  「用了哪些功能」 prefers `uses_function` — but retrieval does not otherwise give
  them different weight.

So use `parent_of`/`part_of` only for true containment, where the closure
behaviour is what you want. Choose among the other five for human and
documentation value, and do not invest in fine distinctions expecting retrieval
to honour them. If you need a relation retrieval treats differently, that is a
change to the Query Planner, not more edges.

Do not force a cross-cutting Function such as Payment under a single Business
parent when Motor, Accident and Travel all use it — `uses_function` or
`shared_with` says what is true.

## Knowledge boundary principle

A Box answers: *in what knowledge/context space is this Card valid or useful?*
Same-looking Cards stay separate when their boundaries differ:

```text
Back / CA / Data Entry        -> returns to previous page
Back / CA / Confirmation      -> returns and preserves input
Back / CB / Search Result     -> returns to search criteria
```

These are not duplicates because the label is `Back`.

## Procedure

- **Pass A — Seed Boxes.** Load company-approved Boxes from
  `config/box-taxonomy.yaml`, preserving canonical identity.
- **Pass B — Discover source-supported Boxes.** Look for repeated, reusable
  Scenario/Function/Screen boundaries in Contexts and Cards. Not every heading is
  a Box; a Box should be useful across Cards and independently meaningful for
  retrieval or navigation.
- **Pass C — Build Memberships.** For each Card, evaluate which memberships the
  evidence supports. Not every Card needs every dimension: Business only,
  Business + Scenario, Scenario + Function, all four, or no safe Box yet →
  `Inbox / Needs Context`.
- **Pass D — Build Box Links.** Only source- or taxonomy-supported edges. Do not
  infer open-ended `related_to` edges from embedding similarity.
- **Pass E — Review recurrence.** Use Box boundaries when reviewing repeated
  concepts: same content with a different `valid_in` Box is normally context
  recurrence, not extraction duplication.

Note that a Box in the taxonomy is not a Scope. `傷害險` can be a Business Box
that a Card is navigable through while being entirely outside the run's Active
Scope. Scope comes from the explicit run target, the nearest source
directory's `afc-scope.md`, and optionally the Business Context mapping; a Box
or Box taxonomy never defines the source boundary.

## Outputs

```text
work/step-card-3-boxes.jsonl
work/step-card-3-box-memberships.jsonl
work/step-card-3-box-links.jsonl
work/step-card-3-box-delta.json
work/step-card-3-box-audit.json
```

Do not overwrite the Card dataset, and do not copy Card content into Boxes.

## ID formats and required fields

These are enforced by `schemas/` and `validate_boxes.py`. Using a different
prefix fails validation, so take them from here rather than inventing one.

| Record | ID format | Required fields |
| --- | --- | --- |
| Box Node | `BOX-nnnnnn` | Box ID, Box Type, Name, Canonical Key, Status |
| Card-Box Membership | `BM-nnnnnn` | Membership ID, Box ID, Card ID, Membership Type, Membership Basis, Status |
| Box-Box Link | `BL-nnnnnn` | Box Link ID, Source Box ID, Relation Type, Target Box ID, Link Basis, Status |

`Status` is `Confirmed`, `Candidate` or `Needs Review`. `Confidence`, when
given, is `High`, `Medium` or `Low`.

`Membership Basis` is one of `Direct Source`, `Structural Context`,
`Business Context Mapping`, `Function Evidence`, `Scenario Evidence`,
`Screen Evidence`, `Inherited Box`, `Manual Configuration`, `Review`.

`Link Basis` is one of `Direct Source`, `Structural Context`,
`Business Context Mapping`, `Company Taxonomy`, `Cross-Card Evidence`,
`Manual Configuration`, `Review`.

A worked membership:

```json
{"Membership ID":"BM-000001","Card ID":"CARD-000188","Box ID":"BOX-000014","Membership Type":"valid_in","Membership Basis":"Direct Source","Evidence":"表 2 標題「確認頁」","Source Context IDs":["CTX-000012"],"Confidence":"High","Status":"Confirmed"}
```

## Stable identity

```text
Box          Box Type + Canonical Key
Membership   Card ID + Box ID + Membership Type
Box Link     Source Box ID + Relation Type + Target Box ID
```

Canonicalize symmetric pairs (`related_to`, `shared_with`) before assigning
identity so a regenerated reverse edge is the same edge.

## Validation

```bash
./afc validate_schema.py \
  work/step-card-3-boxes.jsonl work/step-card-3-box-memberships.jsonl work/step-card-3-box-links.jsonl

./afc validate_boxes.py \
  --boxes work/step-card-3-boxes.jsonl \
  --memberships work/step-card-3-box-memberships.jsonl \
  --box-links work/step-card-3-box-links.jsonl \
  --cards work/step-card-1-reconciled-cards.jsonl \
  --json-output work/step-card-3-box-audit.json
```

Required: no dangling Box or Card IDs, no self Box links, stable canonical keys,
no duplicate Membership or Box Link identities, no cycle in `parent_of`/`part_of`,
and cross-product memberships that do not rewrite Card Scope.

Warnings, not automatic deletion: orphan Cards with no membership, high-degree
Boxes, broad `related_to` fan-out, Candidate/Needs Review relations.

## Query semantics to preserve

Explicitly named Seed Boxes become hard retrieval boundaries. Hierarchical
descendants satisfy a parent-Box query. Non-hierarchical links are soft
navigation, expanded only when intent needs them, default 0 hops and at most 1
(`settings.yaml: query.max_box_hops`). Do not design Boxes on the assumption that
queries start at the root.

## Guardrails

- Box is not Scope, not Source Context, not a Card Link.
- Hierarchy is not the only navigation model.
- A Card exists once; sharing a Concept or a label is not grounds for merging.
- Box topology never overrides source/product Scope.

<!-- afc:scope:begin -->
<!-- Generated from config/skill-scopes.yaml by scripts/sync_skill_metadata.py.
     Edit the manifest, not this block: the `afc` launcher enforces the
     manifest, so a hand-edited copy here would only disagree with it. -->

## Scope

This skill may cause **work** changes. Set
`AFC_SKILL=afc-boxes` while following it: the `afc` launcher then refuses any
command outside the scope below and names the skill that owns it.

Commands this skill may run:

- `resolve_boxes.py`
- `validate_boxes.py`
- `validate_schema.py`

Not this skill's job:

- changing a Card's Scope or Product Context → `afc-cards`
- creating or retyping Card Links → `afc-links`

`./afc --scope afc-boxes` prints this boundary.
<!-- afc:scope:end -->
