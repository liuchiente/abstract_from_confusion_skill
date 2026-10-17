# 002 — An actionable signal miss must be reported as one

Status: **applied**
Decided by: user, 2026-10-18
Follows: 001, which surfaced this with evidence.

## Why

The gold set showed `cb_process.md::TXT000008` — the paragraph holding
`Tải lên thất bại` and `E102` — unselected in a file that is otherwise in scope
(6 of its 8 units selected), and the audit counted it under
`signal_unselected_outside_boundary`. AGENTS.md says that number is "out of
scope and not a finding", so a real knowledge loss is filed as a non-finding.

The cause is narrower than it looks. `boundary_membership()` answers "is this
unselected unit inside a structurally selected boundary?" and knows exactly
three structures: a table whose other rows were selected, a contiguous Excel
segment, and a PDF page. A `paragraph` is none of those, so **no prose unit can
ever be within a boundary**, in any document, ever. Word and Markdown sources
therefore have every signal miss reported as not-a-finding.

## The distinction this change draws

One flag is being asked two different questions:

- **May I auto-select this unit?** Needs a strict bar. A structural boundary is
  the right one: it is what stops a generic term like "message" from widening
  product Scope. Unchanged.
- **Is this miss worth a human's attention?** A much weaker bar. A miss inside a
  document that is demonstrably in the active Scope is actionable whether or not
  a structural sibling happened to be selected.

So: keep `signal_within_selected_boundary` (structural, drives recovery) and add
`signal_within_scope_boundary` for reporting.

## What "demonstrably in the active Scope" means

Not the directory's `afc-scope.md`: that makes a file eligible, and
`other_product.md` sits in the same CB directory while being entirely about
傷害險. Its misses are correctly not findings.

**First attempt, wrong:** "the file has at least one selected unit". An existing
test caught it —
`test_decision_and_config.py::test_out_of_boundary_signals_do_not_raise_review`
builds one workbook with a `Spec` sheet for CA and an `Other` sheet for 旅遊險,
and asserts the 旅遊險 signal is not a finding. File-level granularity makes it
one, so every spec workbook with a sheet per product would become a page of
false findings. That is the shape of source this package is aimed at, so the
test was defending something real.

**What the change does instead:** judge a miss within **the nearest division
that can carry a Scope of its own**.

| Unit kind | Division |
| --- | --- |
| `sheet-row` | its sheet |
| `table-row` | its table |
| `pdf-block` | its page |
| prose (`paragraph`, `text-box`, …) | its document |

A structured source divides itself, and those divisions often *are* the scope
boundary: one workbook, a sheet per product; one table per screen. Prose does
not — a section inside a product document is a topic, not another product — so a
paragraph belongs to its document. A division with at least one selected unit
has shown by direct evidence that it is in scope; a division with none is a
boundary decision.

| Unit | Division | Selected in it | A miss there is |
| --- | --- | --- | --- |
| `cb_process.md::TXT000008` | the document | 6 of 8 | actionable |
| `s::Other::R000030` | sheet `Other` | 0 | not a finding |
| `other_product.md::*` | the document | 0 of 3 | not a finding |

## Deliberately not in this change

- **Recovery.** Nothing is selected that was not selected before. Selection
  changes extraction output, and that is change 003's decision to make with its
  own evidence.
- **Scope detection.** The negation case (`與 CB 乘客險無關` still selects) stays
  recorded as a known limitation.

This is a reporting fix. Its whole value is that it makes change 003's problem
visible: after this, the gold run reports one actionable miss instead of zero,
and that number is the argument for fixing inheritance.

## Tasks

- [x] `build_context_candidates.py`: emit `signal_within_scope_boundary`, and
      classify the unselected-signal buckets by it
- [x] `validate_context_selection.py`: use the new field, falling back to the
      old one for a legacy source map
- [x] Update `afc-context` and `afc-validate` on what the two numbers mean
- [x] Update AGENTS.md's one-line statement of the same rule
- [x] Gold set: the known limitation flips; record the new expectation and
      rewrite limitation 2 to note the audit now reports it
- [x] A test that a prose miss in an in-scope file is actionable, and that a
      miss in an out-of-scope file is not

## Verdict

Smaller than 001 and the proposal still paid, in two ways. Writing down that one
flag was answering two questions produced the fix in a sentence, and the
"deliberately not in this change" section is what kept selection untouched —
without it the obvious move would have been to widen `boundary_membership()` to
cover paragraphs, which quietly changes what every run extracts.

The second way is less flattering and more useful: the proposal's first answer
was wrong, a test that predates this work caught it, and the amendment is in the
document above rather than only in a commit message. A proposal that cannot
record being wrong is just a press release. What the suite could not have caught
is that this granularity question needed deciding at all — that came from the
gold set, which is what change 001 was for.
