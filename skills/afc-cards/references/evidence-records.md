# Evidence Records — preservation rules and worked examples

Read this before writing the first Evidence Record of a run, and whenever a
source value is at risk of being normalized. `afc-cards/SKILL.md` holds the
rule; this file holds the detail and the examples.

### Preservation rules

For source-derived Evidence, keep the value as found: no translation, no
terminology normalization, no capitalization changes, no grammar or spelling
corrections, no rewritten component types, no substituting company-preferred
terms for source codes or values, and no merging strings of different languages
into one synthetic string. Collapsing whitespace for storage is fine; changing
the textual value is not.

If the source says `textbox`, store `Original Component Type = textbox`. If AFC
prefers a canonical `Text Input`, that interpretation belongs on the Card.

When source text is Vietnamese and AFC adds a Chinese explanation, the
Vietnamese stays as the Evidence Record and the Chinese is an enrichment with
its own provenance. Never label a translation as original source text.

### A worked Evidence Record

```json
{
  "Evidence ID": "EVD-TMP-001",
  "Evidence Mode": "VERBATIM+STRUCTURED",
  "Evidence Kind": "Message",
  "Original Text": "Tải lên thất bại",
  "Source Language": "vi",
  "Original Error Message": "Tải lên thất bại",
  "Original Code": "E102",
  "Original Component Type": "textbox",
  "Original Max Length": "100",
  "Source": "CA_spec_v2.docx",
  "Source Location": "Table 3 / Row 7 / Cell 4",
  "Context ID": "CTX-000012",
  "Source Unit IDs": ["CA_spec_v2.docx::B000031::T003::R0007"],
  "Card IDs": ["CARD-TMP-004"]
}
```

Write any local placeholder you like for `Evidence ID` and `Card IDs`
(`EVD-TMP-001`, `tmp:msg-a`). `allocate_ids.py` replaces them with registry IDs
and rewrites every cross-reference. Do not hand-number IDs: in v0.4.1 the model
chose the numbers, which meant Card delta, rerun novelty and every Gold baseline
rested on IDs that drifted between runs.

`Evidence Mode` is `VERBATIM`, `STRUCTURED` or `VERBATIM+STRUCTURED`. Structured
modes should carry at least one `Original *` field or a `Structured Facts`
object.

### Literal knowledge is first-class

Preserve the exact source string for error messages, validation messages, UI
labels, button text, API return messages, codes, enum/option values, original
field names, product names, and any Vietnamese/English/Chinese string. A question
asking for the original Vietnamese error message must be answerable from Evidence
without regeneration.

### Image-derived evidence

For a Source Unit with `kind = image` or a scanned-PDF page: do not build literal Evidence from alt
text unless the user explicitly asks for alt text; when
`image_text_status = VISUAL_EXTRACTED`, preserve `visual_original_text` verbatim;
carry media/page reference, the Source Unit ID and full `structure_path` into
traceability; record the extraction method (`OCR`, `HUMAN`, or explicitly
authorized `VISION`) separately from the text. OCR below the configured
confidence threshold stays `Review`; if recognition is pending, use `Review`
rather than inventing content.

Image text can produce `Message`, `Label`, `ButtonText`, `ImageText` or
`VisualEvidence` records. It may support a semantic Card; the visible string
itself stays Evidence.
