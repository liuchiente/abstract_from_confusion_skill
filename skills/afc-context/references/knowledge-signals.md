# How knowledge signals are matched, and why

Read this when deciding whether a unit carries a Literal or Structured
signal, or when a source language is not being recovered. Patterns live in
`config/knowledge-signals.yaml`; add languages there, not in a script. A
knowledge signal never widens Scope.


Patterns live in `config/knowledge-signals.yaml`, split in two:

- `header_terms` identify a **column header or section label**. A header match
  preserves the rows that header governs. Generic vocabulary belongs here:
  `Error Message` as a column title is strong evidence.
- `content_terms` match **row content** and select that single unit. This list is
  deliberately narrow and value-shaped (code patterns like `E102`, length
  constraints), because a sentence that merely mentions "error" or "code" is not
  literal evidence.

This is the mechanism behind the rule that generic words must not select a unit.
A row holding an actual Vietnamese error string rarely contains the words "error
message"; it is preserved because its column header does. Add your source
languages to that file rather than relying on the defaults.

Signal kinds worth preserving:

- **Literal Knowledge** — exact error/validation messages, UI text, button text,
  labels, placeholders, return messages, source-native names, localized strings.
- **Structured Fact** — component type, required flag, min/max length, format,
  codes, enum/option values, default/original values, function codes, field and
  parameter names.
- **Semantic Knowledge** — rules, conditions, processes, definitions,
  exceptions, mappings.
- **Structural Context** — headings, section and table headers needed to
  interpret children. These are context for their children, not claims of their
  own, so they do not themselves trigger signal recovery.

Preserve literal and structured text exactly as found. Translation and
normalization are Step 1's business, and even there only on the Card side.
