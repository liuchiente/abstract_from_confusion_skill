# afc-gold-v1 — extraction gold set

Every other check in this package tests files, documents and consistency. This
one tests whether following the skills produces good knowledge. The spec can be
perfectly self-consistent and the extraction still wrong; without a known
answer to compare against, nothing says so.

## What it asserts, and what it does not

A Card is model-authored prose. Asserting its text would test wording, fail on
every harmless rewrite and teach everyone to ignore the result. So nothing here
scores phrasing. It scores the things the architecture says are not free:

| Checked | Where |
| --- | --- |
| Step 0 selection, exactly | `expected-step0.json` |
| Nested table, merged header, uncached formula survive | `expected-step0.json` |
| A named source string appears verbatim in Evidence | `expected-claims.yaml` → `literals` |
| Each claim is covered by a Card citing the right unit | `expected-claims.yaml` → `claims` |
| A fact the source does not state appears nowhere | `expected-claims.yaml` → `forbidden` |
| Every selected unit has exactly one disposition | the run's coverage ledger |

The `forbidden` list matters most. A Card claiming 「30 天」 where the source says
「加買期限」 is the failure this package exists to prevent, and no other check in
the suite detects it.

## The sources

Synthetic, and generated rather than committed as binaries — a binary fixture
cannot be reviewed in a diff, and this repository is public. Nothing comes from
a real specification or from third-party training material.

```bash
python3 gold/afc-gold-v1/make_sources.py --out /tmp/gold-sources
```

| File | Why it is there |
| --- | --- |
| `cb_spec.docx` | A nested table inside a table cell, Vietnamese UI messages beside their codes and lengths, a definition paragraph |
| `cb_fields.xlsx` | A merged header governing two columns, and a formula cell with no cached value |
| `cb_process.md` | Prose sections whose claims cross a heading |
| `other_product.md` | In the same folder, outside the active Scope: none of it may be selected |
| `cb_negation.md` | Names the active Scope only to deny applicability — a known false positive, recorded |
| `afc-scope.md` | The directory's Scope declaration, which is not source material |

## Running it

Step 0 needs no model and is asserted exactly:

```bash
./afc selftest.py -k gold
```

Scoring a Step 1 run you have actually produced:

```bash
./afc score_extraction_gold.py --gold gold/afc-gold-v1 \
  --cards work/step-card-1-cards.jsonl \
  --evidence work/step-card-1-evidence.jsonl \
  --coverage work/step-card-1-coverage.jsonl \
  --source-map work/step-card-0-source-map.jsonl
```

Floors live in `settings.yaml` under `gold.*`. Literal preservation has no
sensible floor below 1.0.

## What a failure means

- **A literal is missing** — Evidence was translated, normalized or dropped.
  Repair Evidence; this is never a reason to write a Card instead.
- **A claim is uncovered** — extraction missed something the source states.
  Check whether the unit was selected at all before blaming Step 1.
- **A fabrication is found** — a Card asserts a fact no source states, or
  carries one across a Scope boundary. This is the serious one.
- **A unit is unaccounted** — it was selected and never assessed. That is work
  in progress, not a Review decision.
- **Step 0 selection changed** — the parsers or scope resolution behave
  differently. If intended, update `expected-step0.json` in the same change and
  say why.

## Known limitations

`expected-step0.json` records three places where Step 0 does something a
reviewer would argue with: a file that names the Scope only to deny it is still
selected; a section inside an in-scope file can lose the inheritance chain and
drop a literal-bearing paragraph; and that miss is counted under
`signal_unselected_outside_boundary`, which AGENTS.md treats as not a finding.

They are recorded, not endorsed. Pinning them means a fix shows up as a
deliberate expectation change rather than a silent shift, and each entry says
what to do when it flips.
