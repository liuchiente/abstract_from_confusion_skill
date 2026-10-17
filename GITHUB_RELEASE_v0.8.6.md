# AFC Card Experiment v0.8.6

## Highlights

- PDF article mode now keeps the active chapter and section context across page
  boundaries and records it on text and image Source Units.
- Numbered heading hierarchy now compares heading depth, so sibling sections
  such as `9.1` and `9.2` no longer become parent and child. A nested heading
  such as `9.2.1` remains attached to `9.2`.
- Invalid UUID-like PDF metadata titles are ignored in favor of the source file
  name as the document topic.
- Coverage validation includes per-section counts for Cards, Skips, Reviews and
  unaccounted units. Unassessed work remains distinguishable from an explicit
  Review decision.
- `afc-context` and `afc-cards` now instruct extraction to use article themes
  and sections as review boundaries while keeping individual claim boundaries
  atomic and evidence-backed.
- The default fast PDF profile retains its legacy extraction path.
- Install archives omit local `work/` and `experiments/` artifacts; those stay
  available in the project folder without bloating or personalizing the skill
  package.

## Verification

The supplied PMP uncertainty-domain PDF was parsed with article mode: 31/31
pages with text produced Source Units, 361 text units and 4 image units, with no
parser gaps. Its numbered section headings now produce 27 distinct topic paths.
The focused section and coverage regression tests pass.

The full package test suite passes: 156 tests. The launcher requires Python
3.10 or newer; this environment's system Python is 3.9, so the run explicitly
selected the bundled Python 3.12 interpreter and redirected bytecode cache into
a writable temporary directory.
