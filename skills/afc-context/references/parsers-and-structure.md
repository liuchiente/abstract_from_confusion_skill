# Parsers, structure reports and the ingestion gate

Read this before the first parse of a run: which parser reads which source,
what each structure report claims, and what the three ingestion routes mean.
The rule in `afc-context/SKILL.md` is that source structure must be shown to
have entered AFC before anything is judged in or out of scope.

## Parsers

When multiple file types are registered, use `parse_sources.py` with the KB ID
and the inventory's eligible source list. It dispatches Word, Excel, PDF, text,
and code files to their adapters. Include every applicable structure report in
the audit. Python code uses the standard-library AST. Java, Dart/Flutter,
JavaScript/TypeScript (including Ionic Angular/React/Vue source), PHP, HTML templates, Vue SFC,
and CSS/SCSS use local Tree-sitter parsing when the optional code runtime is
installed; other languages remain unsupported. A module unit can overlap with
class/function units. Treat module text as file-level context and deduplicate
Evidence by source file and line span; do not turn the same lines into repeated
claims. The AFC runtime requires Python 3.10 or newer. For setup, read the installation
and code parser sections in `OPERATIONS.md`.
