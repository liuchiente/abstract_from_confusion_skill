# AFC Card Experiment v0.8.5

## Highlights

- Added an opt-in `article` PDF profile. The default `fast` profile keeps the
  existing text extraction path; article mode adds layout text, numbered
  heading context, and extracted image Source Units.
- Embedded PDF images can be extracted through PyMuPDF or pypdf's Pillow
  support, then sent through AFC's existing local OCR workflow. Image units
  retain stable source IDs, page locations, media paths, and SHA-256 hashes.
- Expanded Step 0 semantic signal categories for definitions, principles,
  methods, artifacts, comparisons, formulas, examples, and quantitative
  knowledge. Signals remain recall hints, not a filter for Card extraction.
- Added document-specific Card guidance for study guides, prose, tables,
  diagrams, code, slides and notes. A signal miss alone is no longer a reason
  to leave selected content in Review; long Reference excerpts do not count as
  complete semantic extraction.
- Bound persistent staging to the exact Card health report. Publishing a
  non-READY run now needs a separate reviewer and rationale, in addition to
  object-level proposal decisions. Continuing to Links is not quality approval.

## Compatibility and migration

Existing accepted Knowledge Base releases remain unchanged. Rescan unchanged
sources when switching PDF profile. Install optional OCR/image dependencies from
`requirements-ocr.txt` to enable embedded-image extraction and local OCR. See
`MIGRATION.md` and `OPERATIONS.md` for workflow changes.

The article profile is a better structure-preserving starting point, not a
guarantee of correct reading order for every multi-column or diagram-heavy PDF.
Review its structure report and OCR evidence before accepting extracted Cards.
