---
name: afc-links
description: AFC Step 2: build typed, evidence-backed relationships between Knowledge Cards and create reusable Concept Cards when repeated context-specific Cards share one stable concept. Use for 卡片關聯/卡片關係/依賴/影響/concept card/card links. Not for knowledge boundaries and navigation nodes (afc-boxes), and never edits a Card claim or Scope (afc-cards).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# STEP 2 — Typed Card Links

Run commands with the `afc` launcher from the repo root.

Inputs: `work/step-card-1-reconciled-cards.jsonl` when it exists, otherwise
`work/step-card-1-cards.jsonl`; plus `work/step-card-1-evidence.jsonl`,
`work/step-card-0-contexts.jsonl` and the original source.

## Gate

Step 2 runs only once the Card stage is settled. Check it:

```bash
./afc record_decision.py verify \
  --health work/step-card-1-health.json \
  --decision work/step-card-1-decision.json
```

`OK` means health is `READY`, or a current decision authorises continuing.
`MISSING`, `STALE` and `BLOCKED` mean the Card loop is not finished — report that
and stop rather than building a graph on contested Cards.

## Goal

Make relationships explicit so retrieval can traverse knowledge instead of
relying on keyword or vector similarity alone.

Link Types for new links:

| Type | Use when | Example |
| --- | --- | --- |
| `instance_of` | a context-specific Card realises a reusable Concept | `CA 確認頁返回` → `返回` Concept |
| `applies_to` | a rule applies to a field/entity | 加買期限規則 → 加買按鈕 |
| `defines` | one Card defines a term another uses | 加買期限定義 → 加買規則 |
| `controls` | one Card governs another's behaviour | 生效日規則 → 保費計算 |
| `depends_on` | one claim is only valid given another | 加買 → 已完成身分驗證 |
| `references` | one Card cites another | 流程 → 外部規範編號 |
| `conflicts_with` | evidence disagrees and neither wins | 舊版 30 天 ↔ 新版 15 天 |
| `replaces` | source/version evidence supports succession | v2 規則 replaces v1 規則 |
| `alias_of` | two Cards name the same thing | 車主 ↔ 被保人（來源同義） |

`belongs_to` is legacy-only. Contextual membership belongs to Step 3 Box
Membership; existing `belongs_to` links may be carried during migration, and
`validate_links.py` warns on each one so the migration can be finished rather
than forgotten.

## Concept Cards vs context-specific Cards

When several context-specific Cards realise the same stable concept, create one
reusable `Concept` Card and link each instance with `instance_of`. Many `返回`
buttons can share a `返回` Concept while CA/CB and per-screen behaviour Cards stay
separate.

Keep behaviour Cards separate whenever behaviour differs materially — one
universal context Card that averages three different behaviours answers no
question correctly.

New Concept Cards go through ID allocation like any other Card:

```bash
./afc allocate_ids.py --cards work/step-card-2-cards-with-concepts.jsonl \
  --evidence work/step-card-1-evidence.jsonl --run-id "$RUN"
```

Give each Concept Card a `Concept Key`; it is what keeps its ID stable. Preserve
every existing source-derived Card ID and report the additions.

## ID format and required fields

Enforced by `schemas/knowledge-link.schema.json` and `validate_links.py`.

| Field | Rule |
| --- | --- |
| `Link ID` | `LINK-nnnnnn` |
| `Source Card ID`, `Target Card ID` | existing `CARD-nnnnnn` in the current Card set |
| `Link Type` | one of the table above |
| `Evidence` | required; the source text or structure that supports the link |
| `Link Basis` | `Direct Source`, `Inherited Context` or `Semantic Supported` |
| `Source Reference` | where that evidence is |

```json
{"Link ID":"LINK-000001","Source Card ID":"CARD-000188","Link Type":"instance_of","Target Card ID":"CARD-000004","Evidence":"兩處皆為「返回」按鈕行為","Link Basis":"Inherited Context","Source Reference":"CA_spec_v2.docx Table 2 / Row 1"}
```

Prefer Direct Source. `Semantic Supported` requires both Cards to carry enough
evidence of their own and must not manufacture a business fact that neither
source states.

## Conflict and version links

Use `conflicts_with` when the evidence genuinely disagrees, and `replaces` only
when source or version evidence supports succession. Never pick a winner
silently — keep both Cards and let Step 4 and Query present the conflict.

When a `replaces` link reflects a real knowledge change, set the superseded
Card's `Status` to `Superseded` and its `Superseded By`, so the change log and
`afc-validate`'s lifecycle layer can see it.

## Outputs and validation

```bash
# work/step-card-2-links.jsonl
./afc validate_schema.py work/step-card-2-links.jsonl
./afc validate_links.py work/step-card-2-links.jsonl --cards work/step-card-1-cards.jsonl
```

Required: no dangling endpoints, no self links, no duplicate Link IDs. Warnings
worth acting on: a link with no Evidence, a duplicate edge, and any remaining
legacy `belongs_to`.

Report: link count by type, Link Basis distribution, Concept Cards added, cards
left with no relationship, and any conflict pairs preserved.

<!-- afc:scope:begin -->
<!-- Generated from config/skill-scopes.yaml by scripts/sync_skill_metadata.py.
     Edit the manifest, not this block: the `afc` launcher enforces the
     manifest, so a hand-edited copy here would only disagree with it. -->

## Scope

This skill may cause **work** changes. Set
`AFC_SKILL=afc-links` while following it: the `afc` launcher then refuses any
command outside the scope below and names the skill that owns it.

Commands this skill may run:

- `allocate_ids.py`
- `record_decision.py`
- `validate_links.py`
- `validate_schema.py`

Not this skill's job:

- editing a Card's claim, Scope or Evidence → `afc-cards`
- creating Boxes or memberships → `afc-boxes`

`./afc --scope afc-links` prints this boundary.
<!-- afc:scope:end -->
