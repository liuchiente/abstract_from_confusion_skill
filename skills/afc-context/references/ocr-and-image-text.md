# Images and scanned PDF pages (OCR-first)

Read this whenever the source holds images, diagrams or scanned pages. OCR
runs locally and before model reasoning; multimodal reading is off unless the
user authorizes it for that run, and low-confidence output stays Review.


An image whose `image_text_status` is `PENDING_VISUAL_EXTRACTION` or
`ALT_TEXT_ONLY` is not text-complete. Alt text is not the image's visible text.

Run the configured local OCR path before model extraction. Tesseract and the
configured language packs must be installed; scanned-PDF rendering also needs
the optional dependency in `requirements-ocr.txt`.

OCR reads the parser outputs; `--source-map` is repeatable and results are keyed
by `source_unit_id`, so one run covers every parser that emitted images:

```bash
./afc extract_ocr.py \
  --source-map work/step-card-0-word-source-units.jsonl \
  --source-map work/step-card-0-pdf-source-units.jsonl \
  -o work/step-card-0-visual-extractions.jsonl
```

The output records OCR text, line regions, language, confidence, and extractor
version. Preserve visible strings separately; do not translate or repair wording
during recognition. Apply results using the configured minimum confidence:

```json
{"source_unit_id":"spec.docx::B000012::IMG01","original_text":"Tải lên thất bại\nSửa đơn và gửi lại","source_language":"vie","extraction_method":"OCR","confidence":0.95,"items":[{"kind":"Message","text":"Tải lên thất bại","region":[12,20,220,48]},{"kind":"ButtonText","text":"Sửa đơn và gửi lại","region":[30,80,240,110]}]}
```

Keep distinct visible strings distinct; do not merge them into a sentence, and do
not translate during extraction. OCR runs locally and does not send source media
to a multimodal model. Keep low-confidence output in Review.

`apply_visual_extractions.py` rewrites one map in place, so run it once per
parser output that holds images and keep the `-enriched` name that section 4
consumes. Everything downstream — the audit above and
`build_context_candidates.py` — must read the enriched map, or the recognized
image text never reaches Card extraction:

```bash
./afc apply_visual_extractions.py \
  --source-map work/step-card-0-word-source-units.jsonl \
  --visual-jsonl work/step-card-0-visual-extractions.jsonl \
  --min-confidence 0.75 \
  -o work/step-card-0-word-source-units-enriched.jsonl

./afc apply_visual_extractions.py \
  --source-map work/step-card-0-pdf-source-units.jsonl \
  --visual-jsonl work/step-card-0-visual-extractions.jsonl \
  --min-confidence 0.75 \
  -o work/step-card-0-pdf-source-units-enriched.jsonl
```

Both commands default to the language and confidence threshold in
`config/settings.yaml` (`ocr.language` and `ocr.min_confidence`). Rerun the
Source Structure Audit using the enriched map so successfully recognized pages
are no longer reported as pending; low-confidence and failed units remain in
the audit for review.

If OCR is unavailable, fails, or does not meet the confidence threshold, retain
the Source Unit and route `SOURCE_VISUAL_EXTRACTION_GAP`. It does not count as
complete Literal Coverage. Do not switch to multimodal reading automatically. A
vision fallback requires explicit user authorization for that run and must record
`extraction_method = VISION` and the reason.
